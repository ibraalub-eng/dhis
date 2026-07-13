from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig, SystemSetting
from app.indicators import build_tree_from_db, get_flat_list_from_db

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


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


@router.get("/{hospital_id}/indicator-tree")
def get_indicator_tree(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

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
