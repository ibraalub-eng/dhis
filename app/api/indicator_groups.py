"""Indicator Groups API — bulk enable/disable macros (design rev 2).

A group is a named set of indicators toggled together. The group itself is
never consulted at runtime: toggling upserts IndicatorDefaultConfig rows
(scope='all') or HospitalIndicatorConfig rows (scope='hospital') for its
members, and the existing effective-state logic
(hospital override → monthly default → True) does the rest.

Key design decisions implemented here (docs/superpowers/specs/
2026-09-28-indicator-groups-design.md rev 2):

* No stored is_enabled flag — the list view DERIVES state from member config
  rows, so it stays correct after single-indicator edits.
* Explicit toggle body {"enabled": bool} — idempotent, unlike the flip
  semantics of the single-indicator endpoints.
* Hospital-scoped groups are month-agnostic: HospitalIndicatorConfig has no
  month column, so a month range cannot apply to them. Storing a range on a
  hospital-scoped group is a 422.
* Exclusive membership is enforced in the service layer: adding an indicator
  to a group evicts it from all other groups in the same transaction.
* Every mutation drops the smart-analytics caches and recalculates quality
  scores, mirroring the never-reported bulk endpoint.
"""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.database import get_db
from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorGroup,
    IndicatorGroupMember,
    IndicatorValue,
)
from app.schemas import (
    IndicatorGroupCreate,
    IndicatorGroupMembersIn,
    IndicatorGroupOut,
    IndicatorGroupToggleIn,
    IndicatorGroupUpdate,
)

router = APIRouter(
    prefix="/indicator-groups",
    tags=["indicator-groups"],
    dependencies=[Depends(require_permission("settings.read"))],
)

_MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


# ── Validation helpers ──────────────────────────────────────────────────────

def _validate_months(month_from: Optional[str], month_to: Optional[str]):
    """YYYY-MM format + ordering. months are expanded later, never stored raw."""
    for label, m in (("month_from", month_from), ("month_to", month_to)):
        if m is not None and not re.match(_MONTH_RE, m):
            raise HTTPException(status_code=422, detail=f"{label} must be YYYY-MM")
    if month_from and month_to and month_from > month_to:
        raise HTTPException(status_code=422, detail="month_from must be <= month_to")


def _validate_scope(
    db: Session,
    scope_type: str,
    hospital_id: Optional[int],
    month_from: Optional[str] = None,
    month_to: Optional[str] = None,
    check_range_rejected: bool = False,
):
    if scope_type not in ("all", "hospital"):
        raise HTTPException(status_code=422, detail="scope_type must be 'all' or 'hospital'")
    if scope_type == "hospital":
        if hospital_id is None:
            raise HTTPException(status_code=422, detail="hospital scope requires hospital_id")
        if not db.query(Hospital).filter(Hospital.id == hospital_id).first():
            raise HTTPException(status_code=404, detail="Hospital not found")
        # HARD CONSTRAINT (rev 2): hospital overrides are month-agnostic —
        # hospital_indicator_config has no month column. Storing a range would
        # silently promise scoping the schema cannot deliver.
        if check_range_rejected and (month_from is not None or month_to is not None):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Hospital-scoped groups cannot apply a month range: per-hospital "
                    "overrides (hospital_indicator_config) have no month column and "
                    "apply to every month. Omit the range or use scope_type='all'."
                ),
            )
    else:
        if hospital_id is not None:
            raise HTTPException(status_code=422, detail="scope 'all' must not set hospital_id")
    _validate_months(month_from, month_to)


# ── Derived state + expansion helpers ───────────────────────────────────────

def _derived_member_enabled(db: Session, group: IndicatorGroup, indicator_id: int) -> bool:
    """Effective enabled state for a member, matching _get_effective_state."""
    if group.scope_type == "hospital":
        cfg = db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == group.hospital_id,
            HospitalIndicatorConfig.indicator_id == indicator_id,
        ).first()
        return cfg.is_enabled if cfg else True
    # scope 'all': enabled iff no default config disables it in ANY month
    # (mirrors _get_default_state(month='__all__') semantics).
    rows = db.query(IndicatorDefaultConfig.is_enabled).filter(
        IndicatorDefaultConfig.indicator_id == indicator_id,
    ).all()
    if not rows:
        return True
    return all(e for (e,) in rows)


def _expand_months(db: Session, month_from: Optional[str], month_to: Optional[str]) -> List[str]:
    """Expand the inclusive range; empty range falls back to every known month
    (same fallback the toggle-default endpoint uses for month='__all__')."""
    if not month_from and not month_to:
        months = {m for (m,) in db.query(IndicatorValue.month).distinct().all()}
        months |= {m for (m,) in db.query(IndicatorDefaultConfig.month).distinct().all()}
        return sorted(months)
    if month_from and not month_to:
        month_to = month_from
    if month_to and not month_from:
        month_from = month_to
    y1, m1 = int(month_from[:4]), int(month_from[5:7])
    y2, m2 = int(month_to[:4]), int(month_to[5:7])
    months = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        months.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


# ── Serialization ───────────────────────────────────────────────────────────

def _group_out(db: Session, group: IndicatorGroup, include_members: bool = False) -> dict:
    member_rows = (
        db.query(IndicatorGroupMember, Indicator)
        .join(Indicator, IndicatorGroupMember.indicator_id == Indicator.id)
        .filter(IndicatorGroupMember.group_id == group.id)
        .order_by(IndicatorGroupMember.sort_order, Indicator.id)
        .all()
    )
    members = [
        {
            "indicator_id": m.indicator_id,
            "indicator_code": ind.code,
            "indicator_name": ind.name,
            "sort_order": m.sort_order,
        }
        for m, ind in member_rows
    ]
    hospital_name = None
    if group.hospital_id:
        h = db.query(Hospital).filter(Hospital.id == group.hospital_id).first()
        hospital_name = h.name if h else None
    is_enabled = all(
        _derived_member_enabled(db, group, mid["indicator_id"]) for mid in members
    ) if members else True
    out = {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "scope_type": group.scope_type,
        "hospital_id": group.hospital_id,
        "hospital_name": hospital_name,
        "month_from": group.month_from,
        "month_to": group.month_to,
        "member_count": len(members),
        "is_enabled": is_enabled,
        "members": members if include_members else [],
    }
    return out


# ── Shared service-layer mutations ──────────────────────────────────────────

def _evict_from_other_groups(db: Session, group_id: int, indicator_ids: List[int]):
    """Exclusive membership (AC #3): an indicator lives in at most one group."""
    if not indicator_ids:
        return 0
    rows = db.query(IndicatorGroupMember).filter(
        IndicatorGroupMember.indicator_id.in_(indicator_ids),
        IndicatorGroupMember.group_id != group_id,
    ).all()
    for row in rows:
        db.delete(row)
    return len(rows)


def _invalidate_caches():
    """Drop smart-analytics caches after bulk config writes (same as the
    never-reported endpoint — stale drilldowns would keep serving members
    in their old enabled/disabled state)."""
    try:
        from app.cache import cache as _smart_cache
        _smart_cache.invalidate("smart_drilldown_")
        _smart_cache.invalidate("smart_trend_")
        _smart_cache.invalidate("smart_overview_")
    except Exception:
        pass


def _recalc_scores(db: Session, hospital_ids: Optional[List[int]] = None):
    try:
        from app.api.indicator_config import _recalc_all_hospital_scores, _recalc_hospital_scores
        if hospital_ids:
            for hid in hospital_ids:
                _recalc_hospital_scores(db, hid)
        else:
            _recalc_all_hospital_scores(db)
    except Exception:
        pass


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[IndicatorGroupOut])
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(IndicatorGroup).order_by(IndicatorGroup.name).all()
    return [_group_out(db, g) for g in groups]


@router.post("", response_model=IndicatorGroupOut, dependencies=[Depends(require_permission("settings.write"))])
def create_group(body: IndicatorGroupCreate, db: Session = Depends(get_db)):
    _validate_scope(db, body.scope_type, body.hospital_id, body.month_from, body.month_to,
                    check_range_rejected=True)
    if db.query(IndicatorGroup).filter(IndicatorGroup.name == body.name).first():
        raise HTTPException(status_code=400, detail=f"Group name '{body.name}' already exists")
    group = IndicatorGroup(
        name=body.name,
        description=body.description,
        scope_type=body.scope_type,
        hospital_id=body.hospital_id,
        month_from=body.month_from,
        month_to=body.month_to,
    )
    db.add(group)
    db.flush()
    if body.indicator_ids:
        _validate_member_ids(db, body.indicator_ids)
        _evict_from_other_groups(db, group.id, body.indicator_ids)
        for order, iid in enumerate(body.indicator_ids):
            db.add(IndicatorGroupMember(group_id=group.id, indicator_id=iid, sort_order=order))
    db.commit()
    db.refresh(group)
    return _group_out(db, group, include_members=True)


def _validate_member_ids(db: Session, indicator_ids: List[int]):
    found = {r[0] for r in db.query(Indicator.id).filter(Indicator.id.in_(indicator_ids)).all()}
    missing = set(indicator_ids) - found
    if missing:
        raise HTTPException(status_code=404, detail=f"Indicator(s) not found: {sorted(missing)}")


@router.get("/{group_id}", response_model=IndicatorGroupOut)
def get_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return _group_out(db, group, include_members=True)


@router.put("/{group_id}", response_model=IndicatorGroupOut, dependencies=[Depends(require_permission("settings.write"))])
def update_group(group_id: int, body: IndicatorGroupUpdate, db: Session = Depends(get_db)):
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    new_scope = body.scope_type if body.scope_type is not None else group.scope_type
    new_hospital = body.hospital_id if body.hospital_id is not None else group.hospital_id
    new_from = body.month_from if body.month_from is not None else group.month_from
    new_to = body.month_to if body.month_to is not None else group.month_to
    # Explicitly clearing a field passes null — handle that before validation.
    if body.hospital_id is None and "hospital_id" not in body.model_fields_set and new_scope == "all":
        new_hospital = None
    if body.month_from is None and "month_from" in body.model_fields_set:
        new_from = None
    if body.month_to is None and "month_to" in body.model_fields_set:
        new_to = None

    if body.name is not None and body.name != group.name:
        dup = db.query(IndicatorGroup).filter(
            IndicatorGroup.name == body.name, IndicatorGroup.id != group_id,
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail=f"Group name '{body.name}' already exists")
        group.name = body.name
    if body.description is not None:
        group.description = body.description

    _validate_scope(db, new_scope, new_hospital, new_from, new_to, check_range_rejected=True)
    group.scope_type = new_scope
    group.hospital_id = new_hospital
    group.month_from = new_from
    group.month_to = new_to
    db.commit()
    db.refresh(group)
    return _group_out(db, group, include_members=True)


@router.delete("/{group_id}", dependencies=[Depends(require_permission("settings.write"))])
def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    # Deleting a group never touches the config rows its past toggles wrote —
    # configs are runtime state, the group is only a macro definition.
    db.delete(group)
    db.commit()
    return {"ok": True, "deleted": group.name}


# ── Impact preview (dry run) ────────────────────────────────────────────────

@router.get("/{group_id}/impact")
def group_impact(
    group_id: int,
    enabled: bool = Query(..., description="The target state you are considering"),
    hospital_id: Optional[int] = Query(None, description="Preview completeness for one hospital (scope 'all' groups otherwise aggregate every active hospital)"),
    db: Session = Depends(get_db),
):
    """Dry-run for the bulk toggle: NOTHING is written.

    Mirrors the real toggle's state math — effective state is
    hospital override > monthly default > True — and reports which members
    would change, how many config rows the toggle would write, which enabled
    rules reference the changing indicators, and the completeness-denominator
    effect. Quality scores are NOT recomputed here; the 'after' denominators
    are derived arithmetically from the same state maps the recalc uses,
    including requirement_type exclusion (Optional members never count) and
    the auto_disable_null_indicators setting (null/missing rows are already
    outside the denominator, so config-disabling them predicts zero change).
    """
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.scope_type == "hospital" and (group.month_from or group.month_to):
        raise HTTPException(status_code=422, detail="Hospital-scoped group has a stored month range it cannot apply")

    member_rows = (
        db.query(IndicatorGroupMember, Indicator)
        .join(Indicator, IndicatorGroupMember.indicator_id == Indicator.id)
        .filter(IndicatorGroupMember.group_id == group.id)
        .order_by(IndicatorGroupMember.sort_order, Indicator.id)
        .all()
    )
    if not member_rows:
        raise HTTPException(status_code=400, detail="Group has no members — nothing to toggle")
    member_ids = [m.indicator_id for m, _ in member_rows]
    code_by_id = {m.indicator_id: ind.code for m, ind in member_rows}
    target = bool(enabled)

    # ── Scope: which hospitals and which months does the toggle touch? ──
    if group.scope_type == "hospital":
        hospitals = [db.query(Hospital).filter(Hospital.id == group.hospital_id).first()]
        months = [None]  # month-agnostic overrides
        months_note = "every month (per-hospital overrides have no month column)"
    else:
        if hospital_id is not None:
            h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
            if not h:
                raise HTTPException(status_code=404, detail="Hospital not found")
            hospitals = [h]
        else:
            hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.id).all()
        months = _expand_months(db, group.month_from, group.month_to)
        months_note = (
            "all known months (no range set)"
            if not (group.month_from or group.month_to)
            else f"{group.month_from} → {group.month_to}"
        )
    if not hospitals or hospitals[0] is None:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if group.scope_type == "all" and not months:
        raise HTTPException(status_code=400, detail="No known months in the database — nothing to preview")

    hid_list = [h.id for h in hospitals]

    # Denominator sample month: the first month of the range for scope 'all'
    # (each month's denominator is independent), or the latest known month
    # for hospital scope (whose overrides apply to every month).
    sample_month = months[0] if group.scope_type == "all" else (
        db.query(IndicatorValue.month).order_by(IndicatorValue.month.desc()).first()[0]
        if db.query(IndicatorValue.month).first() else None
    )

    # ── Load the state maps (2 queries) ──
    default_state = {}  # (indicator_id, month) -> is_enabled
    if group.scope_type == "all":
        q = db.query(IndicatorDefaultConfig).filter(IndicatorDefaultConfig.indicator_id.in_(member_ids))
        if group.month_from or group.month_to:
            q = q.filter(IndicatorDefaultConfig.month.in_(months))
        for c in q.all():
            default_state[(c.indicator_id, c.month)] = c.is_enabled
    override_state = {}  # (hospital_id, indicator_id) -> is_enabled
    for c in db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hid_list),
        HospitalIndicatorConfig.indicator_id.in_(member_ids),
    ).all():
        override_state[(c.hospital_id, c.indicator_id)] = c.is_enabled

    def _state_before(hid: int, iid: int, month: Optional[str]) -> bool:
        if (hid, iid) in override_state:
            return override_state[(hid, iid)]
        if month is not None and (iid, month) in default_state:
            return default_state[(iid, month)]
        return True

    # Effective-state changes per hospital, and default-row writes per month.
    # Denominator math mirrors pipeline.get_required_indicator_ids exactly:
    # a member counts iff its effective state is enabled AND it is Required —
    # and when auto_disable_null_indicators is on, it must also have a
    # non-null value row at the sampled month (null/missing rows are
    # auto-disabled already, so config-disabling them predicts zero change).
    changing_codes = set()
    config_rows_to_write = 0
    affected_hospitals = set()
    hospital_deltas = {}  # hid -> [denom_before, denom_after]

    from app.engine.pipeline import _is_auto_disable_null, get_required_indicator_ids
    auto_disable_null = _is_auto_disable_null(db)
    req_by_id = {
        m.indicator_id: (ind.requirement_type or "Required")
        for m, ind in member_rows
    }
    nonnull_rows = set()  # (hid, iid) with a non-null value row at the sample month
    if auto_disable_null and sample_month:
        for hid, iid in (
            db.query(IndicatorValue.hospital_id, IndicatorValue.indicator_id)
            .filter(
                IndicatorValue.hospital_id.in_(hid_list),
                IndicatorValue.indicator_id.in_(member_ids),
                IndicatorValue.month == sample_month,
                IndicatorValue.value.isnot(None),
            )
            .all()
        ):
            nonnull_rows.add((hid, iid))

    def _in_denominator(hid: int, iid: int, eff_enabled: bool) -> bool:
        if not eff_enabled:
            return False
        if req_by_id.get(iid, "Required") != "Required":
            return False
        if auto_disable_null:
            return (hid, iid) in nonnull_rows
        return True

    for h in hospitals:
        before_cnt = after_cnt = None
        try:
            if sample_month:
                before_cnt = len(get_required_indicator_ids(db, h.id, sample_month))
        except Exception:
            before_cnt = None
        after_cnt = before_cnt
        for iid in member_ids:
            has_override = (h.id, iid) in override_state
            if group.scope_type == "hospital":
                before = _state_before(h.id, iid, None)
                after = target
                if before != after:
                    config_rows_to_write += 1
                    affected_hospitals.add(h.id)
                    changing_codes.add(code_by_id[iid])
            else:
                # Effective state after the toggle = target, unless this
                # hospital holds an override row: overrides outrank the
                # defaults the toggle writes, so they shield the member.
                state_changes = (
                    not has_override
                    and any(_state_before(h.id, iid, m) != target for m in months)
                )
                if state_changes:
                    affected_hospitals.add(h.id)
                    changing_codes.add(code_by_id[iid])
            if before_cnt is not None:
                # Denominator delta at the sampled month only.
                before_eff = _state_before(h.id, iid, sample_month if group.scope_type == "all" else None)
                after_eff = before_eff if (group.scope_type == "all" and has_override) else target
                b_in = _in_denominator(h.id, iid, before_eff)
                a_in = _in_denominator(h.id, iid, after_eff)
                if b_in != a_in:
                    after_cnt += 1 if a_in else -1
        if before_cnt is not None:
            hospital_deltas[h.id] = [before_cnt, after_cnt]
    if group.scope_type == "all":
        for iid in member_ids:
            for month in months:
                cur = default_state.get((iid, month), True)
                if cur != target:
                    config_rows_to_write += 1

    # ── Rules referencing indicators whose state would change ──
    rule_impact = []
    if changing_codes:
        from app.engine.confidence import build_indicator_rule_map
        try:
            rule_map = build_indicator_rule_map(db)
        except Exception:
            rule_map = {}
        rule_codes = sorted({rc for code in changing_codes for rc in rule_map.get(code, [])})
        if rule_codes:
            from app.models import Rule
            for rc, name in db.query(Rule.code, Rule.name).filter(Rule.code.in_(rule_codes)).all():
                rule_impact.append({"rule_code": rc, "rule_name": name})

    return {
        "group_id": group.id,
        "group_name": group.name,
        "enabled": target,
        "dry_run": True,
        "scope": group.scope_type,
        "members": len(member_ids),
        "months": months if group.scope_type == "all" else None,
        "months_note": months_note,
        "hospitals_affected": len(affected_hospitals),
        "config_rows_to_write": config_rows_to_write,
        "changing_indicators": sorted(changing_codes),
        "rule_impact": rule_impact,
        "completeness": {
            "month": sample_month,
            "per_hospital": [
                {"hospital_id": hid, "before": b, "after": a}
                for hid, (b, a) in sorted(hospital_deltas.items())
            ][:50],
            "sum_before": sum(b for _, (b, _) in hospital_deltas.items()) if hospital_deltas else None,
            "sum_after": sum(a for _, (_, a) in hospital_deltas.items()) if hospital_deltas else None,
        },
        "note": (
            "Quality scores and smart-analytics caches are recalculated automatically when you confirm."
        ),
    }


# ── Bulk toggle ─────────────────────────────────────────────────────────────

@router.put("/{group_id}/toggle", dependencies=[Depends(require_permission("settings.write"))])
def toggle_group(group_id: int, body: IndicatorGroupToggleIn, db: Session = Depends(get_db)):
    """Apply an explicit enable/disable to every member.

    scope='all'      → upsert IndicatorDefaultConfig(indicator, month)
    scope='hospital' → upsert HospitalIndicatorConfig(hospital, indicator)
                       (month-agnostic by schema — see _validate_scope)
    """
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    # Hospital scope must not carry a stored range: the range can never apply.
    if group.scope_type == "hospital" and (group.month_from or group.month_to):
        raise HTTPException(
            status_code=422,
            detail="Hospital-scoped group has a stored month range it cannot apply — edit the group first",
        )

    member_rows = db.query(IndicatorGroupMember.indicator_id).filter(
        IndicatorGroupMember.group_id == group.id,
    ).all()
    indicator_ids = [r[0] for r in member_rows]
    if not indicator_ids:
        raise HTTPException(status_code=400, detail="Group has no members — nothing to toggle")

    new_state = bool(body.enabled)
    updated = 0

    if group.scope_type == "all":
        months = _expand_months(db, group.month_from, group.month_to)
        if not months:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No month range set on the group and the database has no known "
                    "months (no indicator values or default configs yet) — set an "
                    "explicit range on the group first"
                ),
            )
        existing = {
            (c.indicator_id, c.month): c
            for c in db.query(IndicatorDefaultConfig).filter(
                IndicatorDefaultConfig.indicator_id.in_(indicator_ids),
                IndicatorDefaultConfig.month.in_(months),
            ).all()
        }
        for iid in indicator_ids:
            for m in months:
                cfg = existing.get((iid, m))
                if cfg is None:
                    db.add(IndicatorDefaultConfig(indicator_id=iid, month=m, is_enabled=new_state))
                elif cfg.is_enabled != new_state:
                    cfg.is_enabled = new_state
                else:
                    continue
                updated += 1
        db.commit()
        _invalidate_caches()
        _recalc_scores(db)
        return {
            "group_id": group.id,
            "enabled": new_state,
            "scope": "all",
            "months": months,
            "config_rows": updated,
            "message": (
                f"{'Enabled' if new_state else 'Disabled'} {len(indicator_ids)} indicator(s) "
                f"across {len(months)} month(s) ({updated} config rows written)"
            ),
        }

    # Hospital scope — month-agnostic override rows.
    existing = {
        c.indicator_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == group.hospital_id,
            HospitalIndicatorConfig.indicator_id.in_(indicator_ids),
        ).all()
    }
    for iid in indicator_ids:
        cfg = existing.get(iid)
        if cfg is None:
            db.add(HospitalIndicatorConfig(
                hospital_id=group.hospital_id, indicator_id=iid, is_enabled=new_state,
            ))
        elif cfg.is_enabled != new_state:
            cfg.is_enabled = new_state
        else:
            continue
        updated += 1
    db.commit()
    _invalidate_caches()
    _recalc_scores(db, [group.hospital_id])
    return {
        "group_id": group.id,
        "enabled": new_state,
        "scope": "hospital",
        "hospital_id": group.hospital_id,
        "config_rows": updated,
        "message": (
            f"{'Enabled' if new_state else 'Disabled'} {len(indicator_ids)} indicator(s) "
            f"for hospital {group.hospital_id} ({updated} config rows written)"
        ),
    }


# ── Membership ──────────────────────────────────────────────────────────────

@router.post("/{group_id}/members", response_model=IndicatorGroupOut, dependencies=[Depends(require_permission("settings.write"))])
def add_members(group_id: int, body: IndicatorGroupMembersIn, db: Session = Depends(get_db)):
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    _validate_member_ids(db, body.indicator_ids)

    existing_ids = {
        r[0] for r in db.query(IndicatorGroupMember.indicator_id).filter(
            IndicatorGroupMember.group_id == group.id,
        ).all()
    }
    next_order = db.query(IndicatorGroupMember).filter(
        IndicatorGroupMember.group_id == group.id,
    ).count()
    added = 0
    for iid in body.indicator_ids:
        if iid in existing_ids:
            continue
        db.add(IndicatorGroupMember(group_id=group.id, indicator_id=iid, sort_order=next_order))
        next_order += 1
        added += 1
    # Exclusive membership: newly added members leave every other group.
    evicted = _evict_from_other_groups(db, group.id, body.indicator_ids)
    db.commit()
    return _group_out(db, group, include_members=True)


@router.delete("/{group_id}/members/{indicator_id}", dependencies=[Depends(require_permission("settings.write"))])
def remove_member(group_id: int, indicator_id: int, db: Session = Depends(get_db)):
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    row = db.query(IndicatorGroupMember).filter(
        IndicatorGroupMember.group_id == group_id,
        IndicatorGroupMember.indicator_id == indicator_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Indicator is not a member of this group")
    db.delete(row)
    db.commit()
    return {"ok": True, "group_id": group_id, "removed": indicator_id}


@router.put("/{group_id}/members/reorder", dependencies=[Depends(require_permission("settings.write"))])
def reorder_members(group_id: int, body: dict, db: Session = Depends(get_db)):
    """Body: {"indicator_ids": [id1, id2, ...]} — position defines sort_order."""
    group = db.query(IndicatorGroup).filter(IndicatorGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    indicator_ids = body.get("indicator_ids", [])
    _validate_member_ids(db, indicator_ids)
    member_ids = {
        r[0] for r in db.query(IndicatorGroupMember.indicator_id).filter(
            IndicatorGroupMember.group_id == group_id,
        ).all()
    }
    if not set(indicator_ids) <= member_ids:
        raise HTTPException(status_code=400, detail="All indicator_ids must already be members")
    for order, iid in enumerate(indicator_ids):
        db.query(IndicatorGroupMember).filter(
            IndicatorGroupMember.group_id == group_id,
            IndicatorGroupMember.indicator_id == iid,
        ).update({"sort_order": order}, synchronize_session=False)
    db.commit()
    return {"ok": True, "group_id": group_id, "reordered": len(indicator_ids)}
