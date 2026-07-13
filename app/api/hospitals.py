from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from app.database import get_db
from app.cache import cache
from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig, QualityScore, ValidationResult, AnomalyResult, SystemSetting
from app.schemas import (
    HospitalOut, QualityScoreOut, ValidationOut, AnomalyOut,
    ReportOut, ReportSummaryOut, HospitalIndicatorConfigOut,
    ConfigToggleOut, IndicatorUpdate, IndicatorOut, IndicatorBase,
)
from app.indicators import build_tree_from_db, get_flat_list_from_db
from app.engine.pipeline import run_full_analysis
from app.engine.pipeline import run_full_analysis
import json

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.get("/", response_model=List[HospitalOut])
def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("hospitals:list", skip=skip, limit=limit)
    cached = cache.get(cache_key)
    if cached:
        return cached
    hospitals = db.query(Hospital).offset(skip).limit(limit).all()
    cache.set(cache_key, hospitals)
    return hospitals


@router.get("/indicators", response_model=List[IndicatorOut])
def list_all_indicators(db: Session = Depends(get_db)):
    cache_key = "hospitals:indicators"
    cached = cache.get(cache_key)
    if cached:
        return cached
    result = db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    cache.set(cache_key, result)
    return result


@router.get("/{hospital_id}", response_model=HospitalOut)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital


# ── Helpers ──────────────────────────────────────────────────────────

def _get_or_create_config(db: Session, hospital_id: int, indicator_id: int) -> HospitalIndicatorConfig:
    config = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id == hospital_id,
        HospitalIndicatorConfig.indicator_id == indicator_id,
    ).first()
    if not config:
        config = HospitalIndicatorConfig(
            hospital_id=hospital_id,
            indicator_id=indicator_id,
            is_enabled=True,
        )
        db.add(config)
        db.flush()
    return config


def _get_all_descendant_ids(db: Session, indicator_id: int) -> List[int]:
    """Recursively find all descendant indicator DB ids."""
    children = (
        db.query(Indicator.id)
        .filter(Indicator.parent_id == indicator_id)
        .all()
    )
    result = []
    for (child_id,) in children:
        result.append(child_id)
        result.extend(_get_all_descendant_ids(db, child_id))
    return result


# ── Hospital Indicator Config ────────────────────────────────────────

@router.get("/{hospital_id}/indicator-config", response_model=List[HospitalIndicatorConfigOut])
def get_hospital_indicator_config(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    indicators = db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    configs = {
        c.indicator_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id
        ).all()
    }

    results = []
    for ind in indicators:
        config = configs.get(ind.id)
        results.append(HospitalIndicatorConfigOut(
            id=config.id if config else 0,
            hospital_id=hospital_id,
            indicator_id=ind.id,
            indicator_code=ind.code,
            indicator_name=ind.name,
            is_enabled=config.is_enabled if config else True,
            weight_override=config.weight_override if config else None,
            default_weight=ind.default_weight or 1.0,
        ))
    return results


@router.put("/{hospital_id}/indicators/{indicator_id}/toggle", response_model=ConfigToggleOut)
def toggle_indicator(
    hospital_id: int,
    indicator_id: int,
    cascade: bool = Query(False, description="Also toggle all descendant indicators"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    config = _get_or_create_config(db, hospital_id, indicator_id)
    new_state = not config.is_enabled

    if cascade and not new_state:
        # Disabling parent → disable all descendants too
        descendant_ids = _get_all_descendant_ids(db, indicator_id)
        for desc_id in descendant_ids:
            desc_config = _get_or_create_config(db, hospital_id, desc_id)
            desc_config.is_enabled = False
        config.is_enabled = False
        msg = f"Branch '{indicator.name}' and all {len(descendant_ids)} sub-indicators disabled for {hospital.name}"
    elif cascade and new_state:
        # Enabling with cascade → enable all descendants too
        descendant_ids = _get_all_descendant_ids(db, indicator_id)
        for desc_id in descendant_ids:
            desc_config = _get_or_create_config(db, hospital_id, desc_id)
            desc_config.is_enabled = True
        config.is_enabled = True
        msg = f"Branch '{indicator.name}' and all {len(descendant_ids)} sub-indicators enabled for {hospital.name}"
    else:
        config.is_enabled = new_state
        msg = f"Indicator '{indicator.name}' {'enabled' if new_state else 'disabled'} for {hospital.name}"

    db.commit()
    db.refresh(config)
    return ConfigToggleOut(
        hospital_id=hospital_id,
        indicator_id=indicator_id,
        is_enabled=config.is_enabled,
        message=msg,
    )


@router.put("/{hospital_id}/indicators/{indicator_id}/weight", response_model=ConfigToggleOut)
def update_indicator_weight(
    hospital_id: int,
    indicator_id: int,
    weight: Optional[float] = Query(None),
    reset: bool = Query(False),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    config = _get_or_create_config(db, hospital_id, indicator_id)
    if reset:
        config.weight_override = None
    else:
        config.weight_override = weight
    db.commit()
    db.refresh(config)
    return ConfigToggleOut(
        hospital_id=hospital_id,
        indicator_id=indicator_id,
        is_enabled=config.is_enabled,
        message="Weight updated" if not reset else "Weight reset to default",
    )


# ── Global Indicator CRUD ────────────────────────────────────────────

@router.put("/indicators/reorder")
def bulk_reorder_indicators(
    body: dict,
    db: Session = Depends(get_db),
):
    """Bulk reorder: pass {"items": [{"id": 1, "sort_order": 0}, {"id": 2, "sort_order": 1}, ...]}"""
    items = body.get("items", [])
    for item in items:
        ind = db.query(Indicator).filter(Indicator.id == item["id"]).first()
        if ind:
            ind.sort_order = item["sort_order"]
    db.commit()
    return {"message": f"{len(items)} indicators reordered"}


@router.post("/{hospital_id}/save-tree-config")
def save_tree_config(
    hospital_id: int,
    body: dict,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Save tree config (enabled/disabled state) for a hospital/month."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    items = body.get("items", [])
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
        if not config:
            config = HospitalIndicatorConfig(
                hospital_id=hospital_id, indicator_id=ind_id, is_enabled=is_enabled,
            )
            db.add(config)
        else:
            config.is_enabled = is_enabled
        count += 1
    db.commit()
    return {"message": f"Saved {count} config entries for {hospital.name} / {month}"}


@router.put("/indicators/{indicator_id}", response_model=IndicatorOut)
def update_global_indicator(
    indicator_id: int,
    update: IndicatorUpdate,
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    if update.name is not None:
        ind.name = update.name
    if update.formula is not None:
        ind.formula = update.formula
    if update.default_weight is not None:
        ind.default_weight = update.default_weight
    db.commit()
    db.refresh(ind)
    return ind


@router.post("/indicators", response_model=IndicatorOut)
def create_global_indicator(
    indicator: IndicatorBase,
    db: Session = Depends(get_db),
):
    existing = db.query(Indicator).filter(Indicator.code == indicator.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Indicator code '{indicator.code}' already exists")
    db_ind = Indicator(
        code=indicator.code,
        name=indicator.name,
        parent_id=indicator.parent_id,
        level=indicator.level,
        sort_order=indicator.sort_order,
        group_name=indicator.group_name,
    )
    db.add(db_ind)
    db.commit()
    db.refresh(db_ind)
    return db_ind


@router.delete("/indicators/{indicator_id}")
def delete_global_indicator(
    indicator_id: int,
    cascade: bool = Query(False, description="Also delete all descendant indicators"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")

    # Check for children
    children = db.query(Indicator).filter(Indicator.parent_id == indicator_id).count()
    if children > 0 and not cascade:
        raise HTTPException(
            status_code=400,
            detail=f"Indicator '{ind.code}' has {children} child indicators. Use cascade=true to delete them all.",
        )

    if cascade:
        descendant_ids = _get_all_descendant_ids(db, indicator_id)
        # Delete configs, values, then indicators
        for desc_id in descendant_ids + [indicator_id]:
            db.query(HospitalIndicatorConfig).filter(
                HospitalIndicatorConfig.indicator_id == desc_id
            ).delete()
            db.query(IndicatorValue).filter(
                IndicatorValue.indicator_id == desc_id
            ).delete()
        db.query(Indicator).filter(Indicator.id.in_(descendant_ids + [indicator_id])).delete(synchronize_session=False)
    else:
        db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == indicator_id
        ).delete()
        db.query(IndicatorValue).filter(
            IndicatorValue.indicator_id == indicator_id
        ).delete()
        db.query(Indicator).filter(Indicator.id == indicator_id).delete()

    db.commit()
    return {"message": f"Indicator '{ind.code}' deleted", "indicator_id": indicator_id, "cascade": cascade}


@router.put("/indicators/{indicator_id}/reparent")
def reparent_indicator(
    indicator_id: int,
    new_parent_id: Optional[int] = Query(None, description="New parent indicator id, or null for root"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")

    if new_parent_id is not None:
        parent = db.query(Indicator).filter(Indicator.id == new_parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent indicator not found")
        # Prevent circular reference
        if new_parent_id == indicator_id:
            raise HTTPException(status_code=400, detail="Cannot set self as parent")
        descendants = _get_all_descendant_ids(db, indicator_id)
        if new_parent_id in descendants:
            raise HTTPException(status_code=400, detail="Cannot set a descendant as parent (circular reference)")

    ind.parent_id = new_parent_id
    db.commit()
    db.refresh(ind)
    return {"message": f"Indicator '{ind.code}' reparented", "indicator_id": indicator_id, "new_parent_id": new_parent_id}


# ── Global Indicator Management ──────────────────────────────────────

@router.post("/{hospital_id}/re-analyze")
def reanalyze_hospital(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    force: bool = Query(False, description="Force re-analysis even if cached results exist"),
    db: Session = Depends(get_db),
):
    """Re-run full analysis for a specific hospital/month (after config changes)."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    try:
        report = run_full_analysis(db, hospital_id, month, force=force)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/indicator-tree/manage")
def get_management_tree(db: Session = Depends(get_db)):
    """Return tree from DB without hospital/month data — for global management UI."""
    tree = build_tree_from_db(db)
    flat = get_flat_list_from_db(db)
    code_to_name = {ind["code"]: ind["name"] for ind in flat}
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


@router.put("/indicators/{indicator_id}/global-toggle")
def global_toggle_indicator(
    indicator_id: int,
    cascade: bool = Query(False, description="Also toggle all descendant indicators"),
    db: Session = Depends(get_db),
):
    """Enable or disable an indicator for ALL hospitals."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    hospitals = db.query(Hospital).all()
    if not hospitals:
        raise HTTPException(status_code=400, detail="No hospitals exist")

    hospital_ids = [h.id for h in hospitals]

    configs = {
        c.hospital_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == indicator_id
        ).all()
    }
    all_enabled = all(
        configs.get(h.id, HospitalIndicatorConfig(is_enabled=True)).is_enabled
        for h in hospitals
    )
    new_state = not all_enabled

    target_ids = [indicator_id]
    if cascade:
        target_ids += _get_all_descendant_ids(db, indicator_id)

    existing = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.indicator_id.in_(target_ids),
    ).all()
    existing_set = {(c.hospital_id, c.indicator_id) for c in existing}

    new_configs = []
    for tid in target_ids:
        for h in hospitals:
            if (h.id, tid) not in existing_set:
                new_configs.append(HospitalIndicatorConfig(
                    hospital_id=h.id, indicator_id=tid, is_enabled=new_state,
                ))
    if new_configs:
        db.add_all(new_configs)
        db.flush()

    db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.indicator_id.in_(target_ids),
    ).update({"is_enabled": new_state}, synchronize_session=False)

    db.commit()
    count = len(target_ids) * len(hospitals)
    return {
        "indicator_id": indicator_id,
        "cascade": cascade,
        "is_enabled": new_state,
        "message": f"{'Enabled' if new_state else 'Disabled'} indicator for all {len(hospitals)} hospitals ({count} configs updated)",
    }


@router.put("/indicators/{indicator_id}/sort-order")
def set_indicator_sort_order(
    indicator_id: int,
    order: int = Query(..., description="New sort order"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    ind.sort_order = order
    db.commit()
    return {"message": f"Sort order updated to {order}", "indicator_id": indicator_id, "sort_order": order}


# ── Indicator Tree ───────────────────────────────────────────────────

@router.get("/{hospital_id}/indicator-tree")
def get_indicator_tree(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Query all values for this hospital/month
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

    # Build code → DB id mapping and fetch configs
    all_indicators = {ind.code: ind for ind in db.query(Indicator).all()}
    configs = {
        c.indicator_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id
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
        is_enabled = config.is_enabled if config else True

        raw_value = value_map.get(code)
        if auto_disable_null and raw_value is None:
            is_enabled = False
        tooltip = None
        if db_indicator and db_indicator.formula:
            # formula like "2,5" or "2,3,4" — codes whose values compose this indicator
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
        "hospital": hospital.name,
        "month": month,
        "indicator_group": raw_tree["indicator_group"],
        "children": [_enrich_node(child) for child in raw_tree["children"]],
    }

    return tree