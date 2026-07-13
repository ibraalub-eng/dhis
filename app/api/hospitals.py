from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import Hospital, Indicator
from app.schemas import HospitalOut, IndicatorOut
from app.engine.pipeline import run_full_analysis

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
