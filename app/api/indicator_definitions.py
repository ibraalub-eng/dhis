"""Indicators management API — the Indicators tab (design 2026-10-18).

The list exposes exactly TWO categories — "Data Element" (the raw Data-Tree
catalog) and "Derived Indicator" (everything calculated from data elements).
A group name is NOT a dimension of this screen any more: it never leaks
into the category axis, and the tab has no group filter, chips or column.

* ``raw``      — the existing Data-Tree catalog (app.models.Indicator).
                 Read-only here: raw elements are created/edited/removed in
                 the Data Tree, this tab only lists + views them, so the two
                 screens can never diverge or duplicate records.
* ``derived``  — all versioned definitions in
                 app.models.IndicatorDefinition, including migrated
                 system definitions and user-created indicators.

Safety doctrine implemented here:

* Every draft is validated by the strict formula parser BEFORE save —
  syntax errors, unknown/synthetic data-element references, self
  references, duplicate codes, threshold conflicts and period
  inapplicability are surfaced as errors/warnings, never swallowed.
* Updates bump ``version`` and append a full snapshot to
  IndicatorDefinitionVersion (audit trail), but NEVER recompute stored
  results — historical IndicatorResult rows keep the version they were
  computed with and show as stale until an explicit recompute.
* Deleting a definition that has stored results is a 409 unless the
  caller explicitly purges; version history survives deletion.
"""
from __future__ import annotations

import json
import math
import re
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.database import get_db
from app.engine import indicator_calc as calc
from app.engine import indicator_service
from app.engine.indicator_groups import group_sort_key
from app.engine.rate_config import sync_rate_config_from_definition
from app.indicators import PARENT_CHILD_MAP, SYNTHETIC_INDICATOR_CODES
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorDefinition,
    IndicatorDefinitionVersion,
    IndicatorValue,
)
from app.schemas import (
    IndicatorCatalogGroupOut,
    IndicatorCatalogItem,
    IndicatorDefinitionCreate,
    IndicatorDefinitionOut,
    IndicatorDefinitionUpdate,
    IndicatorDefinitionVersionOut,
    IndicatorListOut,
    IndicatorPreviewIn,
    IndicatorPreviewOut,
    IndicatorRefInfo,
    IndicatorToggleIn,
    IndicatorValidateIn,
    IndicatorValidateOut,
)

router = APIRouter(
    prefix="/indicators",
    tags=["indicators"],
    dependencies=[Depends(require_permission("settings.read"))],
)


def _invalidate_indicator_consumers() -> None:
    from app.cache import cache

    cache.invalidate("analysis:")
    cache.invalidate("reports:")


WRITE = Depends(require_permission("settings.write"))

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# The catalog exposes ONE classification axis with exactly two values:
# raw source data ("Data Element") and anything calculated ("Derivative
# Indicator" — managed definitions AND system rate specs; the kind column
# in each payload tells them apart). A group name is metadata, never a
# category: it must not leak into this axis (the tab has no group filter,
# chips or column).
_CATEGORY_FALLBACK = {
    "derived": "Derivative Indicator",
    "rate_spec": "Derivative Indicator",
    "raw": "Data Element",
}

# Migration bookkeeping that must never reach the screen: the seeded system
# definitions carry it as their description ("Migrated system definition
# (clinical); legacy key rate_x."). It is stripped for display only — the
# stored text stays untouched as audit metadata.
_MIGRATED_LABEL_RE = re.compile(
    r"^\s*Migrated system definition\b[^;]*;\s*legacy key\s+\S+\s*\.?\s*",
    re.IGNORECASE,
)


def _public_description(text: Optional[str]) -> Optional[str]:
    """Description as the screen shows it — without the migration label."""
    if not text:
        return None
    cleaned = _MIGRATED_LABEL_RE.sub("", str(text)).strip()
    return cleaned or None

# columns whose change bumps the definition version
_CONTENT_FIELDS = (
    "name", "description", "group_name", "formula_type", "expression",
    "numerator_codes", "denominator_codes", "operator", "multiplier",
    "aggregation", "result_type", "unit", "precision", "rounding",
    "direction", "threshold_low",
    "threshold_high", "target_min", "target_max",
)


# ═══════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════

def _natural_key(text: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text or "")]


def _name_map(db: Session, codes: Sequence[str]) -> Dict[str, str]:
    codes = [c for c in dict.fromkeys(codes or []) if c]
    if not codes:
        return {}
    rows = db.query(Indicator.code, Indicator.name).filter(Indicator.code.in_(codes)).all()
    return {code: name for code, name in rows}


def _raw_status_map(db: Session, indicator_ids: Sequence[int]) -> Dict[int, str]:
    """Status of every Data Element, read from the Data Tree configuration.

    The Data Tree's global switch is the "All Hospitals" default config
    (IndicatorDefaultConfig); a hospital-level override never changes the
    catalog status. An element that is switched off for ANY month reads
    "inactive" — exactly how the Data Tree renders its "all months" view
    — everything else stays "active". The switch itself lives on the Data
    Tree; this screen only mirrors it.
    """
    ids = [i for i in dict.fromkeys(indicator_ids or []) if i]
    if not ids:
        return {}
    rows = db.query(
        IndicatorDefaultConfig.indicator_id,
        IndicatorDefaultConfig.is_enabled,
    ).filter(
        IndicatorDefaultConfig.indicator_id.in_(ids),
    ).all()
    disabled = {iid for iid, enabled in rows if not enabled}
    return {i: ("inactive" if i in disabled else "active") for i in ids}


def _prefer_rate_code(candidate: str, current: str) -> bool:
    """Choose the canonical rate alias when duplicate system definitions share a formula."""
    candidate = (candidate or "").strip()
    current = (current or "").strip()
    if not current:
        return True
    if not candidate:
        return False
    if candidate.startswith("rate_") and not current.startswith("rate_"):
        return True
    if current.startswith("rate_") and not candidate.startswith("rate_"):
        return False
    return candidate < current


def _rate_variant_preference(defn) -> tuple:
    """Rank system rate variants so the same legacy alias resolves to one canonical definition."""
    code = ((getattr(defn, "legacy_code", None) or getattr(defn, "code", None) or "").strip())
    site = (getattr(defn, "source_site", None) or "").lower()
    return (
        0 if code.startswith("rate_") else 1,
        0 if site == "clinical" else 1 if site == "forecast" else 2,
        0 if bool(getattr(defn, "is_active", False)) else 1,
        (getattr(defn, "id", 0) or 0),
    )


def _prefer_rate_variant(candidate, current) -> bool:
    if current is None:
        return True
    return _rate_variant_preference(candidate) < _rate_variant_preference(current)


# Fields that describe HOW a rate is calculated. The catalog collapses the
# identical per-site variants of a system rate into one row, so editing that
# row must move the calculation for every variant or the outlier (zscore),
# clinical and forecast engines would keep computing the old formula.
_RATE_SHARED_FIELDS = frozenset({
    "formula_type", "expression", "numerator_codes", "denominator_codes",
    "operator", "multiplier", "aggregation", "result_type", "unit",
    "precision", "rounding",
})


def _canonical_formula(defn) -> str:
    """Return a code-based, registry-safe formula string for catalog/detail output."""
    if getattr(defn, "formula_type", "ratio") == "expression":
        expression = (getattr(defn, "expression", None) or "").strip()
        if expression:
            return expression
    num = list(getattr(defn, "numerator_codes", None) or [])
    den = list(getattr(defn, "denominator_codes", None) or [])
    op = getattr(defn, "operator", "/") or "/"
    mult = float(getattr(defn, "multiplier", 1.0) or 1.0)
    return calc.build_ratio_expression(num, den, op, mult)


def _rate_variant_siblings(db: Session, defn) -> List["IndicatorDefinition"]:
    """Other system definitions the catalog collapsed into the same row.

    Mirrors the listing rule exactly (identical canonical formula + unit), so
    the group edited from one visible row is the group the screen merged.
    """
    formula = _canonical_formula(defn)
    unit = defn.unit or None
    siblings = []
    for other in (db.query(IndicatorDefinition)
                  .filter(IndicatorDefinition.is_system.is_(True),
                          IndicatorDefinition.id != defn.id)
                  .all()):
        if (other.unit or None) != unit:
            continue
        if _canonical_formula(other) == formula:
            siblings.append(other)
    return siblings


def _display_refs(expr: Optional[str], names: Dict[str, str]) -> Optional[str]:
    """`{5}` -> `Caesarean Sections [5]` for human-facing formulas."""
    if not expr:
        return None

    def _sub(m: "re.Match") -> str:
        code = m.group(1)
        name = names.get(code)
        return f"{name} [{code}]" if name else f"[{code}]"

    return re.sub(r"\{([^{}]*)\}", _sub, expr)


def _ratio_display(defn, names: Dict[str, str]) -> str:
    """Human formula for the ratio shape, aggregation-aware."""
    num = list(getattr(defn, "numerator_codes", None) or [])
    den = list(getattr(defn, "denominator_codes", None) or [])
    agg = getattr(defn, "aggregation", "sum") or "sum"
    op = getattr(defn, "operator", "/") or "/"
    mult = float(getattr(defn, "multiplier", 1.0) or 1.0)

    def _part(codes: List[str]) -> str:
        labels = [f"{names.get(c, '?')} [{c}]" for c in codes]
        if len(labels) > 1 and agg and agg != "sum":
            return f"{agg}({', '.join(labels)})"
        return " + ".join(labels)

    body = _part(num)
    if den:
        body = f"{body} {op} { _part(den) }"
    if mult != 1.0:
        body = f"({body}) × {_intish(mult)}"
    return body


def _intish(v: float) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else str(v)


def _formula_display(defn, names: Dict[str, str]) -> str:
    if (getattr(defn, "formula_type", "ratio") or "ratio") == "expression":
        return _display_refs(getattr(defn, "expression", None), names) or ""
    return _ratio_display(defn, names)


def _definition_fields(defn) -> dict:
    return {
        "code": defn.code,
        "name": defn.name,
        "description": defn.description,
        "group_name": defn.group_name,
        "source_site": getattr(defn, "source_site", None),
        "legacy_code": getattr(defn, "legacy_code", None),
        "is_system": bool(getattr(defn, "is_system", False)),
        "formula_type": defn.formula_type,
        "expression": defn.expression,
        "numerator_codes": list(defn.numerator_codes or []),
        "denominator_codes": list(defn.denominator_codes or []),
        "operator": defn.operator,
        "multiplier": float(defn.multiplier),
        "aggregation": defn.aggregation,
        "result_type": defn.result_type,
        "unit": defn.unit,
        "precision": getattr(defn, "precision", None),
        "rounding": getattr(defn, "rounding", None) or "half_up",
        "direction": defn.direction,
        "threshold_low": defn.threshold_low,
        "threshold_high": defn.threshold_high,
        "target_min": defn.target_min,
        "target_max": defn.target_max,
        "is_active": bool(defn.is_active),
        "version": int(defn.version),
    }


def _snapshot(defn) -> str:
    return json.dumps(_definition_fields(defn), ensure_ascii=False, default=str)


def _record_version(db: Session, defn, action: str,
                    changed_fields: Optional[List[str]] = None,
                    user=None) -> None:
    db.add(IndicatorDefinitionVersion(
        definition_id=defn.id,
        definition_code=defn.code,
        version=int(defn.version or 1),
        action=action,
        snapshot=_snapshot(defn),
        changed_fields=json.dumps(changed_fields) if changed_fields else None,
        changed_by=getattr(user, "username", None),
    ))


def _definition_out(db: Session, defn) -> dict:
    data = _definition_fields(defn)
    data["formula_display"] = _formula_display(defn, _name_map(db, _spec_codes(defn)))
    data["id"] = defn.id
    data["created_at"] = defn.created_at
    data["updated_at"] = defn.updated_at
    return data


def _as_spec(fields: dict) -> SimpleNamespace:
    return SimpleNamespace(**fields)


def _spec_codes(spec) -> List[str]:
    try:
        return calc.definition_codes(spec)
    except calc.FormulaError:
        return []


# ── validation ──────────────────────────────────────────────────────────────

def _validate_draft(db: Session, draft, exclude_id: Optional[int] = None,
                    hospital_id: Optional[int] = None,
                    month: Optional[str] = None) -> IndicatorValidateOut:
    errors: List[str] = []
    warnings: List[str] = []

    code = (draft.code or "").strip()
    name = (draft.name or "").strip()
    if not code or not calc._CODE_RE.match(code):
        errors.append(
            "Indicator ID must be 1-50 characters from letters, digits, '.', '_' or '-'")
    if not name:
        errors.append("Indicator name is required")
    elif len(name) > 500:
        errors.append("Indicator name is too long (max 500 characters)")
    if draft.group_name and len(draft.group_name) > 100:
        errors.append("Group name is too long (max 100 characters)")
    if draft.unit and len(draft.unit) > 30:
        errors.append("Unit is too long (max 30 characters)")

    if draft.formula_type not in calc.FORMULA_TYPES:
        errors.append(f"Formula type must be one of: {', '.join(calc.FORMULA_TYPES)}")
    if draft.aggregation not in calc.AGGREGATIONS:
        errors.append(f"Aggregation must be one of: {', '.join(calc.AGGREGATIONS)}")
    if draft.operator not in calc.OPERATORS:
        errors.append(f"Operator must be one of: {', '.join(calc.OPERATORS)}")
    if draft.result_type not in calc.RESULT_TYPES:
        errors.append(f"Result type must be one of: {', '.join(calc.RESULT_TYPES)}")
    if draft.direction is not None and draft.direction not in calc.DIRECTIONS:
        errors.append(f"Direction must be one of: {', '.join(calc.DIRECTIONS)}")
    if getattr(draft, "precision", None) is not None:
        try:
            p = int(draft.precision)
            if p != draft.precision or not (0 <= p <= calc.MAX_PRECISION):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                f"Precision must be a whole number of decimals between 0 and {calc.MAX_PRECISION} (or empty for full precision)")
    rounding = getattr(draft, "rounding", None)
    if rounding is None:
        draft.rounding = "half_up"
    elif rounding not in calc.ROUNDING_MODES:
        errors.append(f"Rounding must be one of: {', '.join(calc.ROUNDING_MODES)}")

    try:
        mult = float(draft.multiplier)
        if not math.isfinite(mult):
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Multiplier must be a finite number")
        mult = 1.0

    # threshold sanity
    for label, lo, hi in (("Threshold", draft.threshold_low, draft.threshold_high),
                          ("Target range", draft.target_min, draft.target_max)):
        if lo is not None and hi is not None:
            if not (math.isfinite(lo) and math.isfinite(hi)):
                errors.append(f"{label} values must be finite numbers")
            elif lo > hi:
                errors.append(f"{label}: low value cannot exceed high value")
    if draft.direction == "target_range" and (draft.target_min is None or draft.target_max is None):
        errors.append("Direction 'target_range' requires both target min and max")
    if ((draft.threshold_low is not None or draft.threshold_high is not None)
            and (draft.direction in (None, "", "none"))):
        warnings.append("Thresholds are set but interpretation direction is 'none' — "
                        "alerts will not be scored")

    # ── code conflicts ────────────────────────────────────────────────────
    if code:
        clash = db.query(IndicatorDefinition).filter(
            IndicatorDefinition.code == code)
        if exclude_id is not None:
            clash = clash.filter(IndicatorDefinition.id != exclude_id)
        if clash.first() is not None:
            errors.append(f"An indicator with ID '{code}' already exists")
        if db.query(Indicator).filter(Indicator.code == code).first() is not None:
            errors.append(f"ID '{code}' conflicts with an existing raw data element")
        system_alias = db.query(IndicatorDefinition.id).filter(
            IndicatorDefinition.is_system.is_(True),
            IndicatorDefinition.legacy_code == code,
        ).first()
        if system_alias:
            errors.append(
                f"ID '{code}' is already registered as a system rate"
            )

    # ── formula structure ─────────────────────────────────────────────────
    refs: List[str] = []
    canonical: Optional[str] = None
    if draft.formula_type == "ratio":
        num = _clean_codes(draft.numerator_codes)
        den = _clean_codes(draft.denominator_codes)
        if not num:
            errors.append("At least one numerator data element is required")
        if draft.operator == "/" and not den:
            errors.append("The '/' operator requires at least one denominator data element")
        for c in num + den:
            if c and not calc._CODE_RE.match(c):
                errors.append(f"Invalid data element reference '{c}'")
        refs = list(dict.fromkeys(num + den))
        if not errors:
            canonical = calc.build_ratio_expression(num, den, draft.operator, mult)
        # double-count detection (parent + its own child selected)
        warnings.extend(_nesting_warnings(refs))
    else:
        expr = (draft.expression or "").strip()
        if not expr:
            errors.append("Expression formula is required")
        else:
            try:
                ast = calc.parse_expression(expr)
                refs = calc.ast_codes(ast)
                canonical = calc.render_expression(ast)
                if not refs:
                    errors.append("Formula must reference at least one data element "
                                  "using {code}")
            except calc.FormulaError as exc:
                errors.append(f"Invalid formula: {exc}")

    for c in dict.fromkeys(refs):
        if c in SYNTHETIC_INDICATOR_CODES:
            errors.append(f"'{c}' is a form-header label, not a data element")
        elif c == code:
            errors.append("An indicator cannot reference itself")

    known: Dict[str, Indicator] = {}
    dep_defs: Dict[str, IndicatorDefinition] = {}
    checkable = [c for c in dict.fromkeys(refs)
                 if c not in SYNTHETIC_INDICATOR_CODES and c != code]
    if checkable:
        rows = db.query(Indicator).filter(Indicator.code.in_(checkable)).all()
        known = {r.code: r for r in rows}
        remaining = [c for c in checkable if c not in known]
        if remaining:
            # A reference may also point at ANOTHER (managed or system)
            # indicator — indicator-on-indicator dependencies are supported
            # and computed on demand at calculation time.
            dep_defs = {d.code: d for d in db.query(IndicatorDefinition)
                        .filter(IndicatorDefinition.code.in_(remaining)).all()}
        for c in checkable:
            if c not in known and c not in dep_defs:
                errors.append(
                    "Unknown data element '" + c + "' — it does not exist in "
                    "the Data Tree or the indicator registry")

        # Circular-dependency protection: from every referenced indicator,
        # follow the reference graph of other definitions; any path that
        # reaches back to this indicator is a cycle.
        if dep_defs:
            graph: Dict[str, List[str]] = {}
            rows_q = db.query(IndicatorDefinition)
            if exclude_id:
                rows_q = rows_q.filter(IndicatorDefinition.id != exclude_id)
            for d in rows_q.all():
                if d.code == code or d.code in known:
                    continue  # raw elements terminate the walk
                try:
                    graph[d.code] = [c2 for c2 in calc.definition_codes(d)
                                     if c2 and c2 not in SYNTHETIC_INDICATOR_CODES]
                except calc.FormulaError:
                    graph[d.code] = []
            for start in dict.fromkeys(refs):
                if start not in graph:
                    continue
                visited = {start}
                stack = [(start, [start])]
                while stack:
                    node, path = stack.pop()
                    if node == code:
                        errors.append(
                            "Circular dependency: " + " → ".join(path))
                        stack = []
                        break
                    for nxt in graph.get(node, []):
                        if nxt not in visited:
                            visited.add(nxt)
                            stack.append((nxt, path + [nxt]))
    ref_infos = [
        IndicatorRefInfo(
            code=c,
            name=known[c].name if c in known else (
                dep_defs[c].name if c in dep_defs else None),
            group_name=known[c].group_name if c in known else (
                dep_defs[c].group_name if c in dep_defs else None),
            level=known[c].level if c in known else None,
            exists=c in known or c in dep_defs,
        )
        for c in dict.fromkeys(refs)
    ]

    # ── period applicability + preview ────────────────────────────────────
    preview: Optional[IndicatorPreviewOut] = None
    if month and not _MONTH_RE.match(month):
        errors.append("Month must be in YYYY-MM format")
        month = None
    if refs and month and not errors:
        counts = calc.codes_with_data(db, refs, month, hospital_id)
        # Indicator dependencies are not raw rows — their values compute on
        # demand, so "no stored data" does not apply to them.
        empty = [c for c, n in counts.items() if n == 0 and c not in dep_defs]
        if empty:
            where = "this hospital" if hospital_id else "any hospital"
            warnings.append(
                "No data for the selected period (" + month + ") in " + where
                + " for: " + ", ".join(empty))
    if hospital_id and month and not errors:
        spec = _as_spec(_draft_fields(draft, canonical))
        preview = _preview(db, spec, hospital_id, month)
        if preview.status == calc.STATUS_ZERO_DENOMINATOR:
            warnings.append("Preview: denominator is zero for the selected "
                            "hospital and period — the result will not be computable")
        elif preview.status == calc.STATUS_NO_DATA:
            warnings.append("Preview: no raw data reported for the selected "
                            "hospital and period")

    return IndicatorValidateOut(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        expression=canonical,
        formula_display=_formula_display(
            _as_spec(_draft_fields(draft, canonical)),
            _name_map(db, refs)) if not errors else None,
        refs=ref_infos,
        preview=preview,
    )


def _clean_codes(codes) -> List[str]:
    out: List[str] = []
    for c in codes or []:
        c = str(c).strip()
        if c and c not in out:
            out.append(c)
    return out


def _nesting_warnings(codes: Sequence[str]) -> List[str]:
    """Warn when a parent element and its own child are both selected
    (their sum would double-count the same reports)."""
    children: Dict[str, set] = {}

    def _desc(code: str) -> set:
        if code in children:
            return children[code]
        out: set = set()
        for child in PARENT_CHILD_MAP.get(code, []) or []:
            out.add(child)
            out |= _desc(child)
        children[code] = out
        return out

    msgs: List[str] = []
    seen = set()
    for a in codes:
        for b in codes:
            if a == b or (b, a) in seen:
                continue
            seen.add((a, b))
            if b in _desc(a):
                msgs.append(
                    f"'{a}' contains '{b}' — selecting both double-counts the "
                    "same reports")
    return msgs


def _draft_fields(draft, canonical: Optional[str]) -> dict:
    """Draft -> engine-spec fields (ratio mode gets the canonical expr)."""
    return {
        "code": (draft.code or "").strip(),
        "name": (draft.name or "").strip(),
        "description": draft.description,
        "group_name": draft.group_name,
        "formula_type": draft.formula_type,
        "expression": canonical if draft.formula_type != "expression"
        else (draft.expression or "").strip(),
        "numerator_codes": _clean_codes(draft.numerator_codes),
        "denominator_codes": _clean_codes(draft.denominator_codes),
        "operator": draft.operator,
        "multiplier": float(draft.multiplier or 1.0),
        "aggregation": draft.aggregation,
        "result_type": draft.result_type,
        "unit": draft.unit,
        "precision": getattr(draft, "precision", None),
        "rounding": getattr(draft, "rounding", None) or "half_up",
        "direction": draft.direction,
        "threshold_low": draft.threshold_low,
        "threshold_high": draft.threshold_high,
        "target_min": draft.target_min,
        "target_max": draft.target_max,
        "is_active": bool(draft.is_active),
        "version": 1,
    }


def _preview(db: Session, spec, hospital_id: int, month: str) -> IndicatorPreviewOut:
    codes = _spec_codes(spec)
    raw = calc.load_raw_values(db, codes, hospital_id, month)
    extra_reasons: List[str] = []
    missing = [c for c in codes if c not in raw]
    if missing:
        # Indicator-on-indicator dependencies compute on demand; a
        # resolvable dep supplies its value here.
        try:
            from app.engine import indicator_service as indsvc
            values, reasons = indsvc._resolve_indicator_refs(
                db, missing, set(), hospital_id, month)
            raw.update(values)
            extra_reasons = reasons
        except Exception:  # pragma: no cover — preview never hard-fails
            extra_reasons = []
    outcome = calc.evaluate_definition(spec, raw)
    names = _name_map(db, codes)
    inputs = [
        {"code": c, "name": names.get(c), "value": outcome.inputs.get(c),
         "missing": c not in raw or raw.get(c) is None}
        for c in codes
    ]
    message = outcome.message
    if extra_reasons and outcome.value is None:
        message = (message.rstrip(".") + "; " if message else "") + "; ".join(extra_reasons)
    return IndicatorPreviewOut(
        status=outcome.status,
        value=outcome.value,
        numerator=outcome.numerator,
        denominator=outcome.denominator,
        inputs=inputs,
        message=message,
    )


def _get_definition(db: Session, definition_id: int) -> IndicatorDefinition:
    defn = db.get(IndicatorDefinition, definition_id)
    if defn is None:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return defn


def _validate_or_422(db: Session, draft, exclude_id=None,
                     hospital_id=None, month=None) -> IndicatorValidateOut:
    result = _validate_draft(db, draft, exclude_id=exclude_id,
                             hospital_id=hospital_id, month=month)
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail={"errors": result.errors, "warnings": result.warnings})
    return result


# ═══════════════════════════════════════════════════════════════════════════
# catalog (list)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("", response_model=IndicatorListOut)
def list_indicators(
    q: Optional[str] = Query(None, description="search name / ID / category"),
    category: Optional[str] = Query(None, description="Data Element | Derived Indicator"),
    kind: Optional[str] = Query(None, description="raw | rate_spec | derived"),
    group: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="active | inactive (``catalog`` is a legacy alias for the raw data elements)"),
    db: Session = Depends(get_db),
):
    items: List[IndicatorCatalogItem] = []

    # raw catalog (existing indicators — listed once, never duplicated)
    raw_rows = (
        db.query(Indicator)
        .filter(~Indicator.code.in_(SYNTHETIC_INDICATOR_CODES))
        .order_by(Indicator.sort_order, Indicator.code)
        .all()
    )
    raw_codes = {ind.code for ind in raw_rows}
    raw_status = _raw_status_map(db, [ind.id for ind in raw_rows])
    # Required-flagged elements the completeness denominator skips because all
    # of their sources are Optional (pipeline.get_optional_source_indicator_ids
    # filtered to the ones whose own flag still says Required). Mirrored, never
    # re-derived here — the catalog must agree with the score.
    try:
        from app.engine.pipeline import get_optional_by_inheritance_ids
        optional_inherited_ids = get_optional_by_inheritance_ids(db)
    except Exception:  # fail closed: mirror the stored flag only
        optional_inherited_ids = set()
    for ind in raw_rows:
        items.append(IndicatorCatalogItem(
            kind="raw",
            ref_id=ind.id,
            code=ind.code,
            name=ind.name,
            group_name=ind.group_name,
            indicator_type=ind.indicator_type or "count",
            formula=ind.formula or None,
            # Data Elements are READ-ONLY on this screen: their status and
            # their Required/Optional setting are mirrored from the Data Tree
            # configuration, never edited here. The status is the global
            # "All Hospitals" default of the reporting month — the same
            # switch the Data Tree exposes.
            status=raw_status.get(ind.id, "active"),
            requirement_type=ind.requirement_type or "Required",
            optional_by_inheritance=ind.id in optional_inherited_ids,
            level=ind.level,
        ))

    # Managed derived definitions are the editable registry; legacy system rates
    # are surfaced as readonly rate-spec rows to avoid duplication and to keep the
    # legacy aliases visible under their canonical codes.
    system_rate_items: List[IndicatorCatalogItem] = []
    candidate_by_legacy_code: Dict[str, IndicatorDefinition] = {}
    for defn in db.query(IndicatorDefinition).order_by(IndicatorDefinition.code).all():
        if not defn.is_system:
            continue
        if not (list(defn.numerator_codes or []) or list(defn.denominator_codes or [])):
            continue
        if (not list(defn.denominator_codes or [])
                and len(list(defn.numerator_codes or [])) == 1
                and list(defn.numerator_codes or [])[0] in raw_codes
                and float(defn.multiplier or 1.0) == 1.0):
            continue
        legacy_code = (defn.legacy_code or defn.code or "").strip()
        if not legacy_code:
            continue
        existing = candidate_by_legacy_code.get(legacy_code)
        if existing is None or _prefer_rate_variant(defn, existing):
            candidate_by_legacy_code[legacy_code] = defn

    rate_name_by_key: Dict[tuple[str, str], str] = {}
    for defn in candidate_by_legacy_code.values():
        legacy_code = (defn.legacy_code or defn.code or "").strip()
        formula = _canonical_formula(defn)
        key = (formula or "", defn.unit or "")
        existing_code = rate_name_by_key.get(key)
        if existing_code is None:
            rate_name_by_key[key] = legacy_code
            system_rate_items.append(IndicatorCatalogItem(
                kind="rate_spec",
                ref_id=defn.id,
                definition_id=defn.id,
                code=legacy_code,
                name=defn.name,
                description=defn.description,
                group_name=defn.group_name,
                indicator_type=defn.result_type,
                unit=defn.unit,
                formula=formula,
                numerator_codes=list(defn.numerator_codes or []),
                denominator_codes=list(defn.denominator_codes or []),
                status="active" if defn.is_active else "inactive",
                version=defn.version,
                site=defn.source_site,
                is_system=True,
            ))
        elif _prefer_rate_code(legacy_code, existing_code):
            for idx, existing in enumerate(system_rate_items):
                if existing.formula == formula and existing.unit == defn.unit:
                    system_rate_items[idx] = IndicatorCatalogItem(
                        kind="rate_spec",
                        ref_id=defn.id,
                        definition_id=defn.id,
                        code=legacy_code,
                        name=defn.name,
                        description=defn.description,
                        group_name=defn.group_name,
                        indicator_type=defn.result_type,
                        unit=defn.unit,
                        formula=formula,
                        numerator_codes=list(defn.numerator_codes or []),
                        denominator_codes=list(defn.denominator_codes or []),
                        status="active" if defn.is_active else "inactive",
                        version=defn.version,
                        site=defn.source_site,
                        is_system=True,
                    )
                    rate_name_by_key[key] = legacy_code
                    break

    for defn in db.query(IndicatorDefinition).order_by(IndicatorDefinition.code).all():
        if defn.is_system:
            continue
        items.append(IndicatorCatalogItem(
            kind="derived",
            ref_id=defn.id,
            definition_id=defn.id,
            code=defn.code,
            name=defn.name,
            description=defn.description,
            group_name=defn.group_name,
            indicator_type=defn.result_type,
            unit=defn.unit,
            formula=_formula_display(defn, _name_map(db, _spec_codes(defn))),
            numerator_codes=list(defn.numerator_codes or []),
            denominator_codes=list(defn.denominator_codes or []),
            status="active" if defn.is_active else "inactive",
            version=defn.version,
            site=defn.source_site,
            is_system=bool(defn.is_system),
        ))

    items.extend(system_rate_items)

    for item in items:
        # Strict two-value category axis: raw source rows are "Data Element",
        # everything calculated is "Derived Indicator". A group name is
        # metadata only — it never leaks into the category axis, and the tab
        # has no group filter/chips/column any more.
        item.category = _CATEGORY_FALLBACK.get(item.kind, item.kind)
        # The migration label is never shown (the stored text stays as audit
        # metadata).
        item.description = _public_description(item.description)

    # ── filter options (computed from the full catalog, before filtering) ─
    categories = sorted({i.category for i in items if i.category})
    groups = sorted({i.group_name for i in items if i.group_name})
    types = sorted({i.indicator_type for i in items if i.indicator_type})
    # Every code the catalog knows — the client uses it to generate an
    # indicator ID that cannot collide with an existing one.
    codes = sorted({i.code for i in items if i.code})

    # ── filters ───────────────────────────────────────────────────────────
    if category:
        items = [i for i in items if (i.category or "") == category]
    if kind:
        items = [i for i in items if i.kind == kind]
    if group:
        # Group chips come from /indicators/groups, whose names are the
        # explicit group name or the kind's category fallback ("Data
        # Element"/"Derivative Indicator" for UNGROUPED rows). Matching on
        # group_name alone made those fallback chips filter every row away;
        # match the exact group name, plus ungrouped rows whose fallback
        # label equals the chip name — keeping filter results in sync with
        # the chip counts.
        items = [
            i for i in items
            if (i.group_name or "").strip() == group
            or (not (i.group_name or "").strip()
                and group in _CATEGORY_FALLBACK.values()
                and (i.category or "") == group)
        ]
    if type:
        items = [i for i in items if (i.indicator_type or "") == type]
    if status:
        if status == "catalog":
            # Legacy alias: raw data elements report "active" now, so
            # ?status=catalog keeps meaning "show me the Data Elements".
            items = [i for i in items if i.kind == "raw"]
        else:
            items = [i for i in items if i.status == status]
    if q:
        needle = str(q).strip().lower()

        def _hay(i: IndicatorCatalogItem) -> str:
            return " ".join(str(x or "") for x in
                            (i.name, i.code, i.group_name, i.category,
                             i.description, i.formula)).lower()
        items = [i for i in items if needle in _hay(i)]

    kind_order = {"derived": 0, "rate_spec": 1, "raw": 2}
    items.sort(key=lambda i: (kind_order.get(i.kind, 9), _natural_key(i.code)))
    return IndicatorListOut(items=items, count=len(items),
                            categories=categories, groups=groups, types=types,
                            codes=codes)


# ═══════════════════════════════════════════════════════════════════════════
# validation / creation (literal paths before /{id})
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/validate", response_model=IndicatorValidateOut)
def validate_indicator(payload: IndicatorValidateIn,
                       db: Session = Depends(get_db)):
    """Dry-run validation of a draft — syntax, references, applicability
    and (optionally) a live preview against real test data."""
    return _validate_draft(
        db, payload.draft, exclude_id=payload.exclude_id,
        hospital_id=payload.hospital_id, month=payload.month)


@router.post("", response_model=IndicatorDefinitionOut, dependencies=[WRITE])
def create_indicator(payload: IndicatorDefinitionCreate,
                     db: Session = Depends(get_db),
                     user=Depends(require_permission("settings.write"))):
    result = _validate_or_422(db, payload)
    fields = _draft_fields(payload, None)
    if payload.formula_type == "ratio":
        fields["expression"] = result.expression
    defn = IndicatorDefinition(**fields)
    db.add(defn)
    db.flush()
    defn.version = 1
    _record_version(db, defn, "created", ["*"], user)
    # A zscore-scoped definition is the formula the Outlier Scan / Quality
    # engine must calculate with — push it onto its rate_config row.
    sync_rate_config_from_definition(db, defn)
    db.commit()
    _invalidate_indicator_consumers()
    db.refresh(defn)
    return _definition_out(db, defn)


@router.post("/recompute", dependencies=[WRITE])
def recompute_indicators(payload: Optional[IndicatorPreviewIn] = None,
                         db: Session = Depends(get_db)):
    """Explicit recompute of stored derived results for a period."""
    month = payload.month if payload else None
    hospital_id = payload.hospital_id if payload else None
    summary = calc.recompute(db, month=month, hospital_id=hospital_id)
    _invalidate_indicator_consumers()
    return summary


@router.get("/calculate")
def calculate_indicator(code: str = Query(..., description="any catalog code: derived | rate_spec | raw"),
                        hospital_id: int = Query(...),
                        month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
                        site: Optional[str] = Query(None, description="rate_config site disambiguator"),
                        db: Session = Depends(get_db)):
    """Shared calculation engine — value + full provenance (indicator ID,
    formula version, hospital, reporting period, status). Read-only;
    identical math to the Indicators screen, Audit benchmark and Outlier
    Analysis because all three go through indicator_service."""
    resolved = indicator_service.resolve(db, code, site=site)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown indicator code '{code}'")
    if month is None:
        month = calc.latest_data_month(db)
    result = indicator_service.calculate_resolved(db, resolved, hospital_id, month)
    return {
        "indicator_id": result.indicator_id,
        "code": result.code,
        "name": result.name,
        "source": result.source,
        "value": result.value,
        "status": result.status,
        "formula": result.formula,
        "formula_version": result.formula_version,
        "hospital_id": result.hospital_id,
        "month": result.month,
        "numerator": result.numerator,
        "denominator": result.denominator,
        "inputs": result.inputs,
        "message": result.message,
        "modules": indicator_service.dependencies(resolved),
    }


@router.get("/dependencies")
def indicator_dependencies(code: str = Query(...),
                           site: Optional[str] = Query(None),
                           db: Session = Depends(get_db)):
    """Which system modules consume the given indicator — powers the
    drawer's Used-by section and safe-delete/deactivate prompts."""
    resolved = indicator_service.resolve(db, code, site=site)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown indicator code '{code}'")
    return {
        "indicator_id": resolved.indicator_id,
        "code": resolved.code,
        "name": resolved.name,
        "source": resolved.source,
        "site": resolved.site,
        "formula_version": resolved.formula_version,
        "modules": indicator_service.dependencies(resolved),
    }


@router.get("/groups", response_model=List[IndicatorCatalogGroupOut])
def indicator_groups(db: Session = Depends(get_db)):
    """Distinct groups of the catalog, with counts — the reuse surface for
    other screens. Built DYNAMICALLY from the full catalog (raw + system
    rates + derived, active and inactive): whatever groups exist are
    reported, canonical clinical-domain groups first (see
    app.engine.indicator_groups), then everything else alphabetically.
    Any screen that wants "a group of indicators" — an audit scope, an
    outlier set, a report section, a forecast board — filters the
    catalog by these names; empty groups are never returned."""
    # NB: never call the route function with only db= — the remaining
    # parameters would keep their Query(None) sentinels, which are truthy
    # and would filter the whole catalog away. Pass the filters explicitly.
    catalog = list_indicators(q=None, category=None, kind=None, group=None,
                              type=None, status=None, db=db)
    agg: Dict[str, dict] = {}
    for item in catalog.items:
        name = ((item.group_name or "").strip()
                or _CATEGORY_FALLBACK.get(item.kind, item.kind))
        rec = agg.get(name)
        if rec is None:
            rec = agg[name] = {
                "name": name, "total": 0, "active": 0,
                "kinds": set(), "sites": set(), "types": set(),
            }
        rec["total"] += 1
        if item.status == "active":
            rec["active"] += 1
        if item.kind:
            rec["kinds"].add(item.kind)
        if item.site:
            rec["sites"].add(item.site)
        if item.indicator_type:
            rec["types"].add(item.indicator_type)
    groups = [
        IndicatorCatalogGroupOut(
            name=rec["name"],
            total=rec["total"],
            active=rec["active"],
            kinds=sorted(rec["kinds"]),
            sites=sorted(rec["sites"]),
            types=sorted(rec["types"]),
        )
        for rec in agg.values()
    ]
    groups.sort(key=lambda g: group_sort_key(g.name))
    return groups


# ═══════════════════════════════════════════════════════════════════════════
# detail / update / lifecycle
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{definition_id}", response_model=IndicatorDefinitionOut)
def get_indicator(definition_id: int, db: Session = Depends(get_db)):
    defn = _get_definition(db, definition_id)
    return _definition_out(db, defn)


@router.get("/{definition_id}/refs", response_model=List[IndicatorRefInfo])
def get_indicator_refs(definition_id: int, db: Session = Depends(get_db)):
    defn = _get_definition(db, definition_id)
    codes = _spec_codes(defn)
    names = _name_map(db, codes)
    counts = calc.codes_with_data(db, codes, _latest_month(db)) if codes else {}
    return [
        IndicatorRefInfo(
            code=c,
            name=names.get(c),
            group_name=_group_map(db, codes).get(c),
            level=_level_map(db, codes).get(c),
            exists=c in names,
            data_count=counts.get(c),
        )
        for c in codes
    ]


def _latest_month(db: Session) -> Optional[str]:
    row = db.query(IndicatorValue.month).order_by(IndicatorValue.month.desc()).first()
    return row[0] if row else None


# ═══════════════════════════════════════════════════════════════════════════
# helpers for the reference maps of a definition's data elements
# ═══════════════════════════════════════════════════════════════════════════

def _group_map(db: Session, codes: Sequence[str]) -> Dict[str, str]:
    return _field_map(db, codes, Indicator.group_name)


def _level_map(db: Session, codes: Sequence[str]) -> Dict[str, int]:
    return _field_map(db, codes, Indicator.level)


def _field_map(db: Session, codes: Sequence[str], column) -> Dict[str, object]:
    codes = [c for c in dict.fromkeys(codes or []) if c]
    if not codes:
        return {}
    rows = db.query(Indicator.code, column).filter(Indicator.code.in_(codes)).all()
    return {code: val for code, val in rows}


@router.put("/{definition_id}", response_model=IndicatorDefinitionOut,
            dependencies=[WRITE])
def update_indicator(definition_id: int, payload: IndicatorDefinitionUpdate,
                     db: Session = Depends(get_db),
                     user=Depends(require_permission("settings.write"))):
    """Partial content update. The prospective state is validated BEFORE a
    single attribute is touched — a rejected draft leaves the row (and the
    session) completely untouched."""
    defn = _get_definition(db, definition_id)
    data = payload.dict(exclude_unset=True)

    status_change: Optional[str] = None
    if "is_active" in data:
        desired = bool(data.pop("is_active"))
        if desired != defn.is_active:
            status_change = "activated" if desired else "deactivated"

    normalized: Dict[str, object] = {}
    for key, value in data.items():
        if key in ("numerator_codes", "denominator_codes") and value is not None:
            value = _clean_codes(value)
        if key == "multiplier" and value is not None:
            value = float(value)
        normalized[key] = value

    def _norm(v):
        return list(v) if isinstance(v, list) else v

    changed = [k for k, v in normalized.items()
               if _norm(getattr(defn, k)) != _norm(v)]

    result = None
    if changed:
        prospective = _definition_fields(defn)
        prospective.update({k: normalized[k] for k in changed})
        result = _validate_or_422(db, SimpleNamespace(**prospective),
                                  exclude_id=defn.id)

    # System rates are seeded per analysis site and the catalog shows one row
    # per (formula, unit); collect the hidden variants BEFORE the update so the
    # whole group keeps a single calculation.
    siblings = []
    if changed and defn.is_system:
        siblings = _rate_variant_siblings(db, defn)

    # ── apply only after validation passed ─────────────────────────────────
    for key in changed:
        setattr(defn, key, normalized[key])
    if changed:
        if defn.formula_type == "ratio":
            defn.expression = result.expression
        defn.version = int(defn.version or 1) + 1
        _record_version(db, defn, "updated", changed, user)
        for sibling in siblings:
            applied = [k for k in changed
                       if k in _RATE_SHARED_FIELDS
                       and _norm(getattr(sibling, k)) != _norm(normalized[k])]
            if not applied:
                continue
            for key in applied:
                setattr(sibling, key, normalized[key])
            if sibling.formula_type == "ratio":
                sibling.expression = result.expression
            sibling.version = int(sibling.version or 1) + 1
            _record_version(db, sibling, "updated", applied, user)
    if status_change:
        defn.is_active = status_change == "activated"
        _record_version(db, defn, status_change, None, user)

    if changed or status_change:
        # The same rate is stored twice (registry row + rate_config row). Save
        # both so the Quality / Outlier explanation cannot keep calculating
        # with the old formula after the Indicators screen was edited.
        for stored in [defn, *siblings]:
            sync_rate_config_from_definition(db, stored)
        db.commit()
        _invalidate_indicator_consumers()
        db.refresh(defn)
    return _definition_out(db, defn)


@router.put("/{definition_id}/toggle", dependencies=[WRITE])
def toggle_indicator(definition_id: int, payload: IndicatorToggleIn,
                     db: Session = Depends(get_db),
                     user=Depends(require_permission("settings.write"))):
    defn = _get_definition(db, definition_id)
    desired = bool(payload.is_active)
    if desired != defn.is_active:
        action = "activated" if desired else "deactivated"
        defn.is_active = desired
        _record_version(db, defn, action, None, user)
        # A system rate is ONE row on the Indicators screen but is stored once
        # per analysis site (zscore / clinical / forecast). Flipping only the
        # visible variant left the row reading "Active" — the catalog merges
        # the group and prefers an active member — while the engine already
        # skipped the rate. The whole group flips together, exactly like an
        # edit (see _RATE_SHARED_FIELDS).
        siblings = _rate_variant_siblings(db, defn) if defn.is_system else []
        for sibling in siblings:
            if bool(sibling.is_active) == desired:
                continue
            sibling.is_active = desired
            _record_version(db, sibling, action, None, user)
        for stored in [defn, *siblings]:
            sync_rate_config_from_definition(db, stored)
        db.commit()
        _invalidate_indicator_consumers()
        db.refresh(defn)
    return {"id": defn.id, "code": defn.code, "is_active": defn.is_active,
            "version": defn.version}


@router.delete("/{definition_id}", dependencies=[WRITE])
def delete_indicator(definition_id: int,
                     purge: bool = Query(
                         False, description="also delete stored results"),
                     db: Session = Depends(get_db),
                     user=Depends(require_permission("settings.write"))):
    """Safe deletion: definitions with stored results are refused (409)
    unless explicitly purged; version history always survives."""
    from app.models import IndicatorResult
    defn = _get_definition(db, definition_id)
    if defn.is_system:
        raise HTTPException(
            status_code=409,
            detail="System indicator definitions cannot be deleted; deactivate them instead.",
        )
    result_rows = db.query(IndicatorResult).filter(
        IndicatorResult.definition_id == defn.id)
    result_count = result_rows.count()
    if result_count and not purge:
        raise HTTPException(
            status_code=409,
            detail=(f"'{defn.code}' has {result_count} stored result(s). "
                    "Deactivate it instead, or repeat with purge=true to "
                    "remove the results as well."))
    _record_version(db, defn, "deleted", None, user)
    for row in result_rows.all():
        db.delete(row)
    # keep the audit trail: detach history rows instead of dropping them
    for row in db.query(IndicatorDefinitionVersion).filter(
            IndicatorDefinitionVersion.definition_id == defn.id).all():
        row.definition_id = None
    db.delete(defn)
    db.commit()
    _invalidate_indicator_consumers()
    return {"deleted": True, "id": definition_id, "results_deleted": result_count}


@router.get("/{definition_id}/versions",
            response_model=List[IndicatorDefinitionVersionOut])
def get_indicator_versions(definition_id: int, db: Session = Depends(get_db)):
    _get_definition(db, definition_id)
    rows = (db.query(IndicatorDefinitionVersion)
            .filter(IndicatorDefinitionVersion.definition_id == definition_id)
            .order_by(IndicatorDefinitionVersion.version.desc(),
                      IndicatorDefinitionVersion.id.desc())
            .all())
    out = []
    for row in rows:
        try:
            snapshot = json.loads(row.snapshot) if row.snapshot else None
        except json.JSONDecodeError:  # pragma: no cover
            snapshot = None
        try:
            fields = json.loads(row.changed_fields) if row.changed_fields else None
        except json.JSONDecodeError:  # pragma: no cover
            fields = None
        out.append(IndicatorDefinitionVersionOut(
            id=row.id,
            definition_code=row.definition_code,
            version=row.version,
            action=row.action,
            snapshot=snapshot,
            changed_fields=fields,
            changed_by=row.changed_by,
            created_at=row.created_at,
        ))
    return out


@router.get("/{definition_id}/results")
def get_indicator_results(
    definition_id: int,
    hospital_id: Optional[int] = Query(None),
    month: Optional[str] = Query(None),
    month_from: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """Stored results — historical rows keep the version they were
    computed with; ``stale`` flags a newer definition version."""
    from app.models import IndicatorResult
    defn = _get_definition(db, definition_id)
    q = db.query(IndicatorResult).filter(
        IndicatorResult.definition_id == definition_id)
    if hospital_id is not None:
        q = q.filter(IndicatorResult.hospital_id == hospital_id)
    if month:
        q = q.filter(IndicatorResult.month == month)
    if month_from:
        q = q.filter(IndicatorResult.month >= month_from)
    rows = q.order_by(IndicatorResult.month.desc(),
                      IndicatorResult.hospital_id).limit(limit).all()
    hosp_names = {}
    out = []
    for row in rows:
        if row.hospital_id not in hosp_names:
            hospital = db.get(Hospital, row.hospital_id)
            hosp_names[row.hospital_id] = hospital.name if hospital else None
        stale = int(row.definition_version or 1) != int(defn.version or 1)
        out.append({
            "id": row.id,
            "definition_id": row.definition_id,
            "definition_code": row.definition_code,
            "hospital_id": row.hospital_id,
            "hospital_name": hosp_names[row.hospital_id],
            "month": row.month,
            "value": row.value,
            "status": row.status,
            "numerator": row.numerator,
            "denominator": row.denominator,
            "definition_version": row.definition_version,
            "current_version": defn.version,
            "stale": stale,
            "computed_at": row.computed_at,
        })
    return {"items": out, "count": len(out)}


@router.post("/{definition_id}/preview", response_model=IndicatorPreviewOut)
def preview_indicator(definition_id: int, payload: IndicatorPreviewIn,
                      db: Session = Depends(get_db)):
    defn = _get_definition(db, definition_id)
    month = payload.month or _latest_month(db)
    if not month:
        raise HTTPException(status_code=400, detail="No data available yet")
    hospital_id = payload.hospital_id
    if hospital_id is None:
        hospital = (db.query(Hospital)
                    .filter(Hospital.is_active.is_(True))
                    .order_by(Hospital.id).first())
        if hospital is None:
            raise HTTPException(status_code=400, detail="No active hospital")
        hospital_id = hospital.id
    if not defn.is_active:
        # still preview — but say so
        result = _preview(db, defn, hospital_id, month)
        result.message = (result.message + " — " if result.message else "") \
            + "indicator is inactive; preview only"
        return result
    return _preview(db, defn, hospital_id, month)


# ═══════════════════════════════════════════════════════════════════════════
# read-only detail for the other two kinds
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/raw/{code}")
def get_raw_indicator(code: str, db: Session = Depends(get_db)):
    """Raw catalog element detail: formula if any, data coverage, and
    which derived definitions reference it (safe-edit context)."""
    ind = db.query(Indicator).filter(Indicator.code == code).first()
    if ind is None:
        raise HTTPException(status_code=404, detail="Data element not found")
    children = db.query(Indicator).filter(Indicator.parent_id == ind.id).all()
    total_rows = db.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == ind.id).count()
    month_row = (db.query(IndicatorValue.month)
                 .filter(IndicatorValue.indicator_id == ind.id)
                 .order_by(IndicatorValue.month.desc()).first())
    referenced_by = []
    for defn in db.query(IndicatorDefinition).all():
        try:
            if code in calc.definition_codes(defn):
                referenced_by.append({"code": defn.code, "name": defn.name,
                                      "id": defn.id})
        except calc.FormulaError:  # pragma: no cover — validated on save
            continue
    parent_code = None
    if ind.parent_id:
        parent = db.get(Indicator, ind.parent_id)
        parent_code = parent.code if parent else None
    # The same rule the completeness denominator composes through: a Required
    # element whose every source is Optional is not counted as required. The
    # drawer shows the flag and names the sources that make it so.
    try:
        from app.engine.pipeline import get_optional_by_inheritance_ids
        optional_inherited_ids = get_optional_by_inheritance_ids(db)
    except Exception:  # fail closed: mirror the stored flag only
        optional_inherited_ids = set()
    return {
        "kind": "raw",
        "id": ind.id,
        "code": ind.code,
        "name": ind.name,
        "group_name": ind.group_name,
        "level": ind.level,
        "indicator_type": ind.indicator_type or "count",
        "requirement_type": ind.requirement_type or "Required",
        "optional_by_inheritance": ind.id in optional_inherited_ids,
        "minimum_history_period": ind.minimum_history_period,
        "outlier_method": ind.outlier_method,
        "historical_enabled": ind.historical_enabled,
        "peer_comparison_enabled": ind.peer_comparison_enabled,
        "formula": ind.formula or None,
        "default_weight": ind.default_weight,
        "parent_code": parent_code,
        "children": [
            {
                "code": c.code,
                "name": c.name,
                "requirement_type": c.requirement_type or "Required",
                "optional_by_inheritance": c.id in optional_inherited_ids,
            }
            for c in children
        ],
        "data_rows": total_rows,
        "latest_month": month_row[0] if month_row else None,
        "referenced_by": referenced_by,
    }


@router.get("/rate/{code}")
def get_rate_spec(code: str, site: Optional[str] = Query(None),
                  db: Session = Depends(get_db)):
    """Compatibility lookup for legacy keys; canonical deduped rate rows are allowed."""
    query = db.query(IndicatorDefinition).filter(
        IndicatorDefinition.is_system.is_(True),
        IndicatorDefinition.legacy_code == code,
    )
    if site:
        query = query.filter(IndicatorDefinition.source_site == site)
    definitions = query.order_by(IndicatorDefinition.source_site, IndicatorDefinition.id).all()
    if not definitions:
        raise HTTPException(status_code=404, detail="Rate definition not found")
    if len(definitions) > 1:
        definition = min(
            definitions,
            key=lambda d: _rate_variant_preference(d),
        )
    else:
        definition = definitions[0]
    num = list(definition.numerator_codes or [])
    den = list(definition.denominator_codes or [])
    names = _name_map(db, num + den)
    formula = _canonical_formula(definition)
    return {
        "kind": "rate_spec",
        "definition_id": definition.id,
        "code": definition.legacy_code,
        "registry_code": definition.code,
        "legacy_code": definition.legacy_code,
        "name": definition.name,
        "site": definition.source_site,
        "indicator_type": definition.result_type,
        "unit": definition.unit,
        "multiplier": definition.multiplier,
        "is_active": definition.is_active,
        "version": definition.version,
        "is_system": True,
        "formula": formula,
        "formula_display": _display_refs(formula, names),
        "refs": [
            {"code": c, "name": names.get(c), "role": "numerator" if c in num else "denominator"}
            for c in dict.fromkeys(num + den)
        ],
    }
