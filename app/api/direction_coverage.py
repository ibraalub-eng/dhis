"""Direction coverage screen API — which indicators still have no direction?

Quality Alerts can only say whether a deviation is good or bad when the
indicator carries a clinical direction. Most registrations do, but the
remaining ones fall back to a purely statistical label, so their active alerts
cannot be interpreted. This screen lists exactly those gaps, orders them by the
number of ACTIVE alerts they affect, and proposes a direction with its basis:

* ``clinical_guideline`` — the registry's clinical threshold metadata says
  which way is worse (``app.engine.clinical.thresholds``). Nothing is invented:
  the suggestion is the configured guideline, and its text is shown.
* ``numerator_of``      — the element is counted in the numerator of one or
  more rates whose direction is known (recorded, or from their guideline), so
  a higher count moves those rates in that direction. A conflicting or
  denominator role yields no suggestion.
* ``none``              — no guideline and no directed rate maps this element;
  it is left for a human decision, never auto-filled.

Bulk apply is deliberate: it only writes the reviewed items. Family edits go to
the representative definition (the scan merges the family's settings from any
copy), and raw element edits go through the same column + audit trail as the
Data Element drawer.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.indicator_definitions import (
    _invalidate_indicator_consumers,
    _record_version,
)
from app.core.deps import require_permission
from app.database import get_db
from app.engine import indicator_service
from app.engine.clinical.thresholds import ClinicalThreshold, get_threshold
from app.models import (
    Indicator,
    IndicatorDefinition,
    IndicatorDirectionHistory,
    QualityAlert,
)
from app.indicators import SYNTHETIC_INDICATOR_CODES

router = APIRouter(
    prefix="/direction-coverage",
    tags=["direction-coverage"],
    dependencies=[Depends(require_permission("settings.read"))],
)

WRITE = Depends(require_permission("settings.write"))

#: Directions this screen may write. "none" is not offered: the list is about
#: ADDING a meaning, and clearing one belongs to the element/definition screen
#: where the change is explicit.
_DIRECTIONS = ("higher_is_better", "lower_is_better")


# ── suggestion helpers ──────────────────────────────────────────────────────

def _threshold_keys(definition) -> List[str]:
    """Candidate registry keys for the clinical-guideline table.

    System definitions are stored per analysis site (``sys_clinical_rate_avd``)
    while the guideline table is keyed by the canonical rate code
    (``rate_avd``), so the site prefix and the ``*_rate``/``rate_*`` spelling
    are both normalised here instead of hardcoding one alias per rate.
    """
    keys: List[str] = []

    def _add(key: Optional[str]) -> None:
        key = (key or "").strip()
        if key and key not in keys:
            keys.append(key)

    for key in (getattr(definition, "legacy_code", None),
                getattr(definition, "code", None)):
        _add(key)
    for key in list(keys):
        if key.startswith("sys_"):
            tail = "_".join(key.split("_")[2:])
            _add(tail)
        if key.endswith("_rate"):
            _add("rate_" + key[: -len("_rate")])
    return keys


def _threshold_for(definition) -> Optional[ClinicalThreshold]:
    for key in _threshold_keys(definition):
        threshold = get_threshold(key)
        if threshold is not None and threshold.higher_is_worse is not None:
            return threshold
    return None


def _threshold_direction(definition) -> Tuple[Optional[str], Optional[str]]:
    threshold = _threshold_for(definition)
    if threshold is None:
        return None, None
    direction = ("lower_is_better" if threshold.higher_is_worse
                 else "higher_is_better")
    return direction, threshold.clinical_guideline or None


def _family_directions(db: Session) -> Dict[str, str]:
    """Effective direction of every ACTIVE registration, recorded or guideline.

    Used only to derive element suggestions. Quality Alerts' own resolver stays
    the authority for what the scan interprets; this map exists because the
    coverage screen must reason about rates the scan already directs through
    their guideline fallback.
    """
    out: Dict[str, str] = {}
    for group in indicator_service.canonical_formulas(db):
        values = getattr(group.resolved.family_settings, "values", {}) or {}
        direction = (values.get("global_direction")
                     or values.get("direction") or "")
        if direction not in _DIRECTIONS:
            direction, _ = _threshold_direction(group.resolved.definition)
        if direction in _DIRECTIONS:
            for code in group.registered_codes:
                out[code] = direction
    return out


def _element_roles(db: Session, directions: Dict[str, str]):
    """(numerator roles, denominator roles) per raw code, with family names.

    Only ACTIVE definitions contribute. A definition with no known direction
    contributes nothing: it cannot tell us which way its numerator moves.
    """
    numerators: Dict[str, Dict[str, str]] = {}
    denominators: Dict[str, set] = {}
    definitions = (db.query(IndicatorDefinition)
                   .filter(IndicatorDefinition.is_active.is_(True))
                   .all())
    for definition in definitions:
        direction = directions.get(definition.code)
        name = definition.name or definition.code
        if direction:
            for code in (definition.numerator_codes or []):
                numerators.setdefault(code, {})[name] = direction
        for code in (definition.denominator_codes or []):
            denominators.setdefault(code, set()).add(name)
    return numerators, denominators


def _suggestion_for_element(code: str, numerators, denominators):
    roles = numerators.get(code) or {}
    directions = set(roles.values())
    if len(directions) == 1 and code not in denominators:
        names = ", ".join(sorted(roles))
        return (next(iter(directions)), "numerator_of",
                f"Counted in the numerator of: {names}")
    if len(directions) > 1:
        detail = ", ".join(f"{name} ({direction})"
                           for name, direction in sorted(roles.items()))
        return (None, "conflict",
                f"Its rates disagree on the direction: {detail}")
    if code in denominators:
        names = ", ".join(sorted(denominators[code]))
        return (None, "none",
                f"Denominator/total element for: {names} — a higher count "
                "does not imply a better or worse outcome")
    return (None, "none",
            "No clinical guideline and no directed rate maps this element")


def _recorded_direction(values: Dict[str, object]) -> Optional[str]:
    """The family's own recorded decision, if it has one (None = no decision)."""
    for key in ("global_direction", "direction"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ── payload builders ────────────────────────────────────────────────────────

def _active_alert_counts(db: Session) -> Dict[str, int]:
    rows = (db.query(QualityAlert.indicator_code, func.count(QualityAlert.id))
            .filter(QualityAlert.active.is_(True))
            .group_by(QualityAlert.indicator_code)
            .all())
    return {code: int(count) for code, count in rows}


def _build_items(db: Session) -> List[dict]:
    counts = _active_alert_counts(db)
    directions = _family_directions(db)
    numerators, denominators = _element_roles(db, directions)

    items: List[dict] = []
    definition_codes = set()
    for group in indicator_service.canonical_formulas(db):
        definition = group.resolved.definition
        definition_codes.update(group.registered_codes)
        values = getattr(group.resolved.family_settings, "values", {}) or {}
        if _recorded_direction(values) is not None:
            continue  # any recorded decision counts, explicit "none" included
        suggested, basis, reason = (None, "none", None)
        threshold_direction, guideline = _threshold_direction(definition)
        if threshold_direction:
            suggested = threshold_direction
            basis = "clinical_guideline"
            reason = (guideline or
                      "The clinical guideline metadata sets this direction")
        items.append({
            "kind": "family",
            "code": group.code,
            "name": group.resolved.name,
            "group_name": getattr(definition, "group_name", None),
            "unit": getattr(group.resolved, "unit", None),
            "definition_id": getattr(definition, "id", None),
            "registered_codes": list(group.registered_codes),
            "active_alerts": sum(counts.get(code, 0)
                                 for code in group.registered_codes),
            "suggested_direction": suggested,
            "suggestion_basis": basis,
            "suggestion_reason": reason,
        })

    raw_rows = (db.query(Indicator)
                .filter(~Indicator.code.in_(SYNTHETIC_INDICATOR_CODES))
                .order_by(Indicator.sort_order, Indicator.code)
                .all())
    for row in raw_rows:
        if row.code in definition_codes:
            continue  # a registered definition shadows the raw code
        recorded = (row.global_direction or "").strip()
        if recorded and recorded != "none":
            continue
        suggested, basis, reason = _suggestion_for_element(
            row.code, numerators, denominators)
        items.append({
            "kind": "raw",
            "code": row.code,
            "name": row.name,
            "group_name": row.group_name,
            "unit": None,
            "definition_id": None,
            "indicator_id": row.id,
            "registered_codes": [row.code],
            "active_alerts": counts.get(row.code, 0),
            "suggested_direction": suggested,
            "suggestion_basis": basis,
            "suggestion_reason": reason,
        })

    items.sort(key=lambda item: (
        -item["active_alerts"],
        0 if item["kind"] == "family" else 1,
        str(item["code"]),
    ))
    return items


@router.get("")
def direction_coverage(db: Session = Depends(get_db)):
    """Families and data elements with no recorded direction, worst first.

    Ordered by the number of ACTIVE alerts whose stored interpretation is
    affected. Nothing is recomputed and nothing is written.
    """
    items = _build_items(db)
    return {
        "items": items,
        "summary": {
            "families": sum(1 for item in items if item["kind"] == "family"),
            "elements": sum(1 for item in items if item["kind"] == "raw"),
            "active_alerts": sum(item["active_alerts"] for item in items),
            "with_suggestion": sum(1 for item in items
                                   if item["suggested_direction"]),
        },
    }


# ── bulk apply ──────────────────────────────────────────────────────────────

class _ApplyItem(BaseModel):
    kind: str
    code: str
    direction: Optional[str] = None


class _ApplyBody(BaseModel):
    items: List[_ApplyItem]


def _resolve_family(db: Session, code: str):
    for group in indicator_service.canonical_formulas(db):
        if code == group.code or code in group.registered_codes:
            return group
    return None


@router.post("/apply")
def apply_direction_coverage(payload: _ApplyBody, db: Session = Depends(get_db),
                             user=Depends(require_permission("settings.write"))):
    """Write the reviewed directions in ONE transaction.

    The whole batch is validated before anything is touched: an invalid
    direction or an unknown code rejects the request (422) instead of applying
    half of a reviewed list. Items already carrying the requested direction are
    reported as skipped and write no audit row.
    """
    if not payload.items:
        raise HTTPException(status_code=422,
                            detail="No items selected for review")

    planned = []
    errors: List[str] = []
    counts = _active_alert_counts(db)
    for requested in payload.items:
        kind = (requested.kind or "").strip().lower()
        code = (requested.code or "").strip()
        direction = (requested.direction or "").strip()
        label = f"{kind}:{code}"
        if kind not in ("family", "raw"):
            errors.append(f"{label}: kind must be 'family' or 'raw'")
            continue
        if direction not in _DIRECTIONS:
            errors.append(f"{label}: direction must be one of "
                          f"{', '.join(_DIRECTIONS)}")
            continue
        if kind == "family":
            group = _resolve_family(db, code)
            if group is None:
                errors.append(f"{label}: no active indicator family '{code}'")
                continue
            planned.append((kind, code, direction, group))
        else:
            row = db.query(Indicator).filter(Indicator.code == code).first()
            if row is None:
                errors.append(f"{label}: no data element '{code}'")
                continue
            if db.query(IndicatorDefinition.id).filter(
                    IndicatorDefinition.code == code).first() is not None:
                # A registered definition shadows the raw code: the scan reads
                # the definition, so a column here would never be applied.
                errors.append(f"{label}: '{code}' is a registered indicator, "
                              "not a raw data element")
                continue
            planned.append((kind, code, direction, row))
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    results = []
    applied = 0
    affected_alerts = 0
    for kind, code, direction, target in planned:
        if kind == "family":
            definition = target.resolved.definition
            if definition.global_direction == direction:
                results.append({"kind": kind, "code": code,
                                "direction": direction, "status": "skipped",
                                "message": "Already recorded"})
                continue
            definition.global_direction = direction
            definition.version = int(definition.version or 1) + 1
            _record_version(db, definition, "updated", ["global_direction"],
                            user)
            codes = list(target.registered_codes)
        else:
            if target.global_direction == direction:
                results.append({"kind": kind, "code": code,
                                "direction": direction, "status": "skipped",
                                "message": "Already recorded"})
                continue
            db.add(IndicatorDirectionHistory(
                indicator_id=target.id,
                indicator_code=target.code,
                previous_value=target.global_direction or None,
                new_value=direction,
                changed_by=getattr(user, "username", None),
            ))
            target.global_direction = direction
            codes = [code]
        applied += 1
        affected_alerts += sum(counts.get(c, 0) for c in codes)
        results.append({"kind": kind, "code": code, "direction": direction,
                        "status": "applied", "message": None})

    if applied:
        db.commit()
        _invalidate_indicator_consumers()
    return {
        "applied": applied,
        "skipped": len(results) - applied,
        "affected_alerts": affected_alerts,
        # Stored alert rows keep the interpretation they were scanned with;
        # Quality Alerts must be re-scanned before the new direction shows up.
        "rescan_required": applied > 0,
        "items": results,
    }
