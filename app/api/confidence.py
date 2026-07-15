from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Hospital, Indicator, ConfidenceScore
from app.engine.pipeline import (
    get_enabled_values_for_hospital_month,
    get_all_hospital_data_for_month,
    get_historical_months,
)
from app.engine.quality import ValidationContext, run_rules_from_db, run_all_rules
from app.engine.confidence import (
    calculate_confidence,
    build_indicator_rule_map,
    HospitalConfidenceResult,
)
from app.indicators import PARENT_CHILD_MAP, INDICATOR_CODE_TO_NAME
from app.schemas import HospitalConfidenceOut, ConfidenceComparisonOut
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/confidence", tags=["confidence"])

KEY_INDICATOR_CODES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "17", "18", "26"]


def _run_confidence_for_hospital(
    db: Session,
    hospital_id: int,
    month: str,
) -> HospitalConfidenceResult:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise ValueError(f"Hospital id {hospital_id} not found")

    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not values:
        raise ValueError(f"No data found for hospital {hospital.name} / {month}")

    all_hospital_data = get_all_hospital_data_for_month(db, month)
    historical = get_historical_months(db, hospital_id, month)

    ctx = ValidationContext(
        values=values,
        hospital_name=hospital.name,
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data=historical if historical else None,
    )

    rule_results = run_rules_from_db(db, ctx)
    if not rule_results:
        rule_results = run_all_rules(ctx)

    indicator_rule_map = build_indicator_rule_map(db)

    all_indicators = db.query(Indicator.code, Indicator.name).all()
    indicator_map = {ind.code: ind.name for ind in all_indicators}
    indicator_map.update(INDICATOR_CODE_TO_NAME)

    result = calculate_confidence(
        hospital_name=hospital.name,
        month=month,
        values=values,
        rule_results=rule_results,
        historical_data=historical if historical else {},
        all_hospital_data=all_hospital_data,
        indicator_map=indicator_map,
        indicator_children=PARENT_CHILD_MAP,
        indicator_rule_map=indicator_rule_map,
        key_indicator_codes=KEY_INDICATOR_CODES,
        session=db,
    )
    return result


@router.get("/{hospital_id}", response_model=HospitalConfidenceOut)
def get_confidence_scores(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    try:
        result = _run_confidence_for_hospital(db, hospital_id, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error computing confidence for hospital {hospital_id}/{month}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    return result.to_dict()


@router.get("/{hospital_id}/summary")
def get_confidence_summary(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    try:
        result = _run_confidence_for_hospital(db, hospital_id, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    d = result.to_dict()
    return {
        "hospital": d["hospital"],
        "month": d["month"],
        "overall_confidence": d["overall_confidence"],
        "level": d["level"],
        "by_level": d["by_level"],
        "by_group": d["by_group"],
        "priority_verify_count": len(d["priority_verify"]),
        "priority_indicators": [
            {"code": i["indicator_code"], "name": i["indicator_name"], "confidence": i["confidence"], "level": i["level"]}
            for i in d["priority_verify"]
        ],
        "summary": d["summary"],
    }


@router.get("/compare/all", response_model=List[ConfidenceComparisonOut])
def compare_hospital_confidence(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    results: List[dict] = []
    for hosp in hospitals:
        vals = get_enabled_values_for_hospital_month(db, hosp.id, month)
        if not vals:
            continue
        try:
            result = _run_confidence_for_hospital(db, hosp.id, month)
            d = result.to_dict()
            results.append(ConfidenceComparisonOut(
                hospital=d["hospital"],
                hospital_id=hosp.id,
                overall_confidence=d["overall_confidence"],
                level=d["level"],
                critical_count=d["by_level"].get("CRITICAL", 0),
                low_count=d["by_level"].get("LOW", 0),
                medium_count=d["by_level"].get("MEDIUM", 0),
                high_count=d["by_level"].get("HIGH", 0),
            ))
        except Exception as e:
            logger.warning(f"Could not compute confidence for {hosp.name}/{month}: {e}")
            continue
    results.sort(key=lambda r: r.overall_confidence, reverse=True)
    return results


@router.get("/{hospital_id}/stored")
def get_stored_confidence(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    cs = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if not cs:
        raise HTTPException(status_code=404, detail="No stored confidence score. Run analysis first.")
    import json
    indicators = json.loads(cs.indicators_data) if cs.indicators_data else []
    return {
        "hospital": hosp.name,
        "hospital_id": hospital_id,
        "month": cs.month,
        "overall_confidence": cs.overall_confidence,
        "level": cs.level,
        "indicator_count": cs.indicator_count,
        "by_level": {
            "HIGH": cs.high_count,
            "MEDIUM": cs.medium_count,
            "LOW": cs.low_count,
            "CRITICAL": cs.critical_count,
        },
        "indicators": indicators,
        "summary": cs.summary,
        "created_at": cs.created_at.isoformat() if cs.created_at else None,
    }


@router.get("/weights")
def get_confidence_weights(db: Session = Depends(get_db)):
    from app.models import ConfidenceWeights
    cw = db.query(ConfidenceWeights).first()
    if not cw:
        cw = ConfidenceWeights(rule_compliance=0.55, historical=0.10, cross_hospital=0.10, trend=0.10, completeness=0.15)
        db.add(cw)
        db.commit()
        db.refresh(cw)
    return {
        "rule_compliance": cw.rule_compliance,
        "historical": cw.historical,
        "cross_hospital": cw.cross_hospital,
        "trend": cw.trend,
        "completeness": cw.completeness,
    }


@router.put("/weights")
def update_confidence_weights(weights: dict, db: Session = Depends(get_db)):
    from app.models import ConfidenceWeights
    fields = ["rule_compliance", "historical", "cross_hospital", "trend", "completeness"]
    cw = db.query(ConfidenceWeights).first()
    if not cw:
        cw = ConfidenceWeights()
        db.add(cw)
    total = 0
    for f in fields:
        val = weights.get(f)
        if val is not None:
            setattr(cw, f, float(val))
            total += float(val)
    if abs(total - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail=f"Weights must sum to 1.0 (got {total:.2f})")
    db.commit()
    db.refresh(cw)
    return {
        "rule_compliance": cw.rule_compliance,
        "historical": cw.historical,
        "cross_hospital": cw.cross_hospital,
        "trend": cw.trend,
        "completeness": cw.completeness,
        "updated_at": cw.updated_at.isoformat() if cw.updated_at else None,
    }
