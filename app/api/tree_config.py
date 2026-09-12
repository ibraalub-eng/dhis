from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func
from app.database import get_db
from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig, SystemSetting, IndicatorDefaultConfig
from app.indicators import build_tree_from_db, get_flat_list_from_db
from app.core.deps import require_permission

router = APIRouter(prefix="/hospitals", tags=["hospitals"], dependencies=[Depends(require_permission("settings.read"))])


class _State:
    """Minimal stand-in for config rows used by the All-Months default view."""
    def __init__(self, is_enabled: bool):
        self.is_enabled = is_enabled


@router.post("/{hospital_id}/save-tree-config")
def save_tree_config(
    hospital_id: int,
    body: dict,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Save tree config (enabled/disabled state) for a hospital/month.

    A hospital state that matches the default (All Hospitals) config for that
    month removes the per-hospital override (so it inherits the default).
    """
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    items = body.get("items", [])
    if month == "__all__":
        # Hospital config is month-agnostic; compare against the aggregated default
        # (disabled when ANY month has it disabled).
        disabled_any = {
            iid for iid, enabled in db.query(
                IndicatorDefaultConfig.indicator_id, IndicatorDefaultConfig.is_enabled
            ).all() if not enabled
        }
        default_states = {iid: False for iid in disabled_any}
    else:
        default_states = {
            c.indicator_id: c.is_enabled
            for c in db.query(IndicatorDefaultConfig).filter(
                IndicatorDefaultConfig.month == month,
            ).all()
        }
    count = 0
    for item in items:
        ind_id = item.get("indicator_id")
        is_enabled = item.get("is_enabled", True)
        if not ind_id:
            continue
        config = db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id,
            HospitalIndicatorConfig.indicator_id == ind_id,
        ).first()
        default_state = default_states.get(ind_id)
        if default_state is not None and default_state == is_enabled:
            # Matches the default → drop override so it inherits the default.
            if config:
                db.delete(config)
            continue
        if not config:
            config = HospitalIndicatorConfig(
                hospital_id=hospital_id, indicator_id=ind_id, is_enabled=is_enabled,
            )
            db.add(config)
        else:
            config.is_enabled = is_enabled
        count += 1
    db.commit()
    from app.cache import cache as _smart_cache
    _smart_cache.invalidate(f"smart_drilldown_{hospital_id}_{month}")
    _smart_cache.invalidate(f"smart_trend_{hospital_id}")
    _smart_cache.invalidate(f"smart_overview_{month}")
    from app.engine.pipeline import run_full_analysis
    try:
        run_full_analysis(db, hospital_id, month, force=True)
    except Exception:
        pass
    return {"message": f"Saved {count} config entries for {hospital.name} / {month}"}


@router.post("/save-default-tree-config")
def save_default_tree_config(
    body: dict,
    month: str = Query(..., description="Month YYYY-MM, or '__all__' to apply to every known month"),
    db: Session = Depends(get_db),
):
    """Save the default (All Hospitals) tree config for a month.

    With month='__all__' the config is written to every known month.

    This config is inherited by every hospital that has no per-hospital override."""
    items = body.get("items", [])
    months = [month]
    if month == "__all__":
        from app.api.indicator_config import _all_known_months
        months = _all_known_months(db)
    if not items or not months:
        return {"message": f"Saved 0 default config entries for {month}"}
    count = 0
    for m in months:
        existing = {
            c.indicator_id: c
            for c in db.query(IndicatorDefaultConfig).filter(
                IndicatorDefaultConfig.month == m,
            ).all()
        }
        for item in items:
            ind_id = item.get("indicator_id")
            is_enabled = item.get("is_enabled", True)
            if not ind_id:
                continue
            config = existing.get(ind_id)
            if not config:
                config = IndicatorDefaultConfig(
                    indicator_id=ind_id, month=m, is_enabled=is_enabled,
                )
                db.add(config)
            else:
                config.is_enabled = is_enabled
            count += 1
    db.commit()
    from app.cache import cache as _smart_cache
    _smart_cache.invalidate("smart_drilldown_")
    _smart_cache.invalidate("smart_trend_")
    if month == "__all__":
        _smart_cache.invalidate("smart_overview_")
    else:
        _smart_cache.invalidate(f"smart_overview_{month}")
    from app.engine.pipeline import run_full_analysis
    from app.models import Hospital as _Hosp
    _all_hids = [h.id for h in db.query(_Hosp.id).filter(_Hosp.is_active == True).all()]
    for _hid in _all_hids:
        try:
            run_full_analysis(db, _hid, month, force=True)
        except Exception:
            pass
    return {"message": f"Saved {count} default config entries for {month}"}


@router.get("/indicator-tree/manage")
def get_management_tree(db: Session = Depends(get_db)):
    """Return tree from DB without hospital/month data — for global management UI."""
    tree = build_tree_from_db(db)
    code_to_id = {}
    for ind in db.query(Indicator).all():
        code_to_id[ind.code] = ind.id

    def _enrich(node):
        code = str(node["id"])
        enriched = {
            "code": code,
            "indicator_id": code_to_id.get(code),
            "name": node["name"],
            "children": [],
            "leaf": not bool(node.get("children")),
        }
        for child in node.get("children", []):
            enriched["children"].append(_enrich(child))
        return enriched

    return {
        "indicator_group": tree["indicator_group"],
        "children": [_enrich(child) for child in tree["children"]],
    }


@router.get("/indicator-tree/default")
def get_default_indicator_tree(
    month: str = Query(..., description="Month YYYY-MM, or '__all__' for all months"),
    db: Session = Depends(get_db),
):
    """Return the tree showing the default (All Hospitals) config for a month —
    inherited by every hospital that has no per-hospital override."""
    return _build_tree(db, month, default_scope=True)


@router.get("/{hospital_id}/indicator-tree")
def get_indicator_tree(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM, or '__all__' for all months"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return _build_tree(db, month, hospital_id=hospital_id, hospital=hospital)


def _build_tree(db, month: str, hospital_id: int | None = None, hospital=None, default_scope: bool = False):
    name = "Default (All Hospitals)" if default_scope else (hospital.name if hospital else "All Hospitals")
    value_map = {}
    if hospital_id:
        if month == "__all__":
            rows = (
                db.query(Indicator.code, IndicatorValue.value)
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .filter(IndicatorValue.hospital_id == hospital_id)
                .all()
            )
            # Aggregate across all months: sum numeric values per indicator.
            agg: dict[str, float] = {}
            for code, val in rows:
                if val is None:
                    continue
                agg[code] = agg.get(code, 0.0) + val
            value_map = agg
        else:
            rows = (
                db.query(Indicator.code, IndicatorValue.value)
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .filter(
                    IndicatorValue.hospital_id == hospital_id,
                    IndicatorValue.month == month,
                )
                .all()
            )
            value_map = {code: val for code, val in rows if val is not None}
    elif default_scope:
        # Aggregate across ALL hospitals so the default tree shows real data,
        # and keep a per-hospital breakdown for each indicator.
        breakdown_map: dict[str, list[dict]] = {}

        def _sum_rows(_rows):
            _fm: dict[str, float] = {}
            for code, val in _rows:
                if val is None:
                    continue
                _fm[code] = _fm.get(code, 0.0) + val
            return {code: float(v) for code, v in _fm.items()}

        if month == "__all__":
            rows = (
                db.query(Indicator.code, sa_func.sum(IndicatorValue.value))
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .filter(IndicatorValue.value.isnot(None))
                .group_by(Indicator.code)
                .all()
            )
            value_map = _sum_rows(rows)
            b_rows = (
                db.query(
                    Indicator.code,
                    IndicatorValue.hospital_id,
                    Hospital.name,
                    sa_func.sum(IndicatorValue.value),
                )
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .join(Hospital, Hospital.id == IndicatorValue.hospital_id)
                .filter(IndicatorValue.value.isnot(None))
                .group_by(Indicator.code, IndicatorValue.hospital_id, Hospital.name)
                .all()
            )
            for code, hid, hname, val in b_rows:
                breakdown_map.setdefault(code, []).append(
                    {"hospital_id": hid, "hospital": hname, "value": float(val)}
                )
        else:
            rows = (
                db.query(Indicator.code, sa_func.sum(IndicatorValue.value))
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .filter(
                    IndicatorValue.month == month,
                    IndicatorValue.value.isnot(None),
                )
                .group_by(Indicator.code)
                .all()
            )
            value_map = _sum_rows(rows)
            b_rows = (
                db.query(
                    Indicator.code,
                    IndicatorValue.hospital_id,
                    Hospital.name,
                    IndicatorValue.value,
                )
                .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
                .join(Hospital, Hospital.id == IndicatorValue.hospital_id)
                .filter(
                    IndicatorValue.month == month,
                    IndicatorValue.value.isnot(None),
                )
                .all()
            )
            for code, hid, hname, val in b_rows:
                breakdown_map.setdefault(code, []).append(
                    {"hospital_id": hid, "hospital": hname, "value": float(val)}
                )

    all_indicators = {ind.code: ind for ind in db.query(Indicator).all()}
    configs = {}
    if hospital_id:
        configs = {
            c.indicator_id: c
            for c in db.query(HospitalIndicatorConfig).filter(
                HospitalIndicatorConfig.hospital_id == hospital_id
            ).all()
        }
    if month == "__all__":
        # Default state for All Months: an indicator counts as enabled unless a
        # config row for SOME month disables it.
        disabled_any = {
            iid for iid, enabled in db.query(
                IndicatorDefaultConfig.indicator_id, IndicatorDefaultConfig.is_enabled
            ).all() if not enabled
        }
        default_configs = {iid: _State(is_enabled=False) for iid in disabled_any}
    else:
        default_configs = {
            c.indicator_id: c
            for c in db.query(IndicatorDefaultConfig).filter(
                IndicatorDefaultConfig.month == month
            ).all()
        }

    raw_tree = build_tree_from_db(db)
    flat_list = get_flat_list_from_db(db)

    code_to_name = {ind["code"]: ind["name"] for ind in flat_list}

    row = (db.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first())
    auto_disable_null = bool(row and row.value == "true")

    def _enrich_node(node):
        code = str(node["id"])
        db_indicator = all_indicators.get(code)
        db_id = db_indicator.id if db_indicator else None
        config = configs.get(db_id) if db_id else None
        default_config = default_configs.get(db_id) if db_id else None
        if config is not None:
            is_enabled = config.is_enabled
        elif default_config is not None:
            is_enabled = default_config.is_enabled
        else:
            is_enabled = True

        raw_value = value_map.get(code)
        if auto_disable_null and raw_value is None:
            is_enabled = False
        tooltip = None
        if db_indicator and db_indicator.formula:
            parts = [c.strip() for c in db_indicator.formula.split(",")]
            resolved = []
            for p in parts:
                pv = value_map.get(p)
                if pv is not None:
                    resolved.append(f"{p}={pv}")
            if resolved:
                tooltip = f"{raw_value} = " + " + ".join(resolved) if raw_value is not None else " + ".join(resolved)

        enriched = {
            "code": code,
            "indicator_id": db_id,
            "name": node["name"],
            "value": raw_value,
            "label": code_to_name.get(code, node["name"]),
            "is_enabled": is_enabled,
            "children": [],
            "leaf": not bool(node.get("children")),
            "tooltip": tooltip,
        }
        if default_scope and raw_value is not None:
            parts = breakdown_map.get(code) or []
            parts = sorted(parts, key=lambda p: p["hospital"])
            enriched["per_hospital"] = parts
        if node.get("children"):
            child_values = []
            for child in node["children"]:
                child_enriched = _enrich_node(child)
                enriched["children"].append(child_enriched)
                if child_enriched["value"] is not None:
                    child_values.append(child_enriched["value"])
            if enriched["value"] is None and child_values:
                enriched["children_sum"] = sum(child_values)
                enriched["child_details"] = [
                    {"code": c["code"], "name": c["name"], "value": c["value"]}
                    for c in enriched["children"] if c["value"] is not None
                ]
            enriched["leaf"] = False
        return enriched

    tree = {
        "hospital": name,
        "month": month,
        "indicator_group": raw_tree["indicator_group"],
        "children": [_enrich_node(child) for child in raw_tree["children"]],
        "default_scope": default_scope,
        "auto_disable_null": auto_disable_null,
    }

    return tree
