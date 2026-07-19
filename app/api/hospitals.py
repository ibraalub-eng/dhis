from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import Hospital, Indicator
from app.schemas import HospitalOut, IndicatorOut, HospitalCreate
from app.engine.pipeline import run_full_analysis

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.get("/", response_model=List[HospitalOut])
def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    include_inactive: bool = Query(False, description="Include inactive hospitals"),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("hospitals:list", skip=skip, limit=limit, include_inactive=include_inactive)
    cached = cache.get(cache_key)
    if cached:
        result = []
        for item in cached:
            if isinstance(item, dict):
                result.append(item)
            else:
                d = {
                    "id": item.id,
                    "name": item.name,
                    "region": item.region,
                    "governorate_id": item.governorate_id,
                    "hospital_type_id": item.hospital_type_id,
                    "address": item.address,
                    "is_active": item.is_active,
                    "created_at": item.created_at,
                    "governorate_name": item.governorate.name if item.governorate else None,
                    "hospital_type_name": item.hospital_type.name if item.hospital_type else None,
                }
                result.append(d)
        return result
    q = db.query(Hospital)
    if not include_inactive:
        q = q.filter(Hospital.is_active.is_(True))
    hospitals = q.offset(skip).limit(limit).all()
    result = []
    for h in hospitals:
        result.append({
            "id": h.id,
            "name": h.name,
            "region": h.region,
            "governorate_id": h.governorate_id,
            "hospital_type_id": h.hospital_type_id,
            "address": h.address,
            "is_active": h.is_active,
            "created_at": h.created_at,
            "governorate_name": h.governorate.name if h.governorate else None,
            "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
        })
    cache.set(cache_key, result)
    return result


@router.post("/", response_model=HospitalOut)
def create_hospital(data: HospitalCreate, db: Session = Depends(get_db)):
    existing = db.query(Hospital).filter(Hospital.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Hospital already exists")
    hosp = Hospital(
        name=data.name,
        region=data.region,
        governorate_id=data.governorate_id,
        hospital_type_id=data.hospital_type_id,
        address=data.address,
    )
    db.add(hosp)
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp


@router.put("/{hospital_id}/toggle-active")
def toggle_hospital_active(hospital_id: int, db: Session = Depends(get_db)):
    """Toggle a hospital's active status. Inactive hospitals are excluded from analysis and reports."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    hospital.is_active = not hospital.is_active
    db.commit()
    cache.invalidate()
    return {"id": hospital.id, "name": hospital.name, "is_active": hospital.is_active}


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
    h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return {
        "id": h.id,
        "name": h.name,
        "region": h.region,
        "governorate_id": h.governorate_id,
        "hospital_type_id": h.hospital_type_id,
        "address": h.address,
        "is_active": h.is_active,
        "created_at": h.created_at,
        "governorate_name": h.governorate.name if h.governorate else None,
        "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
    }


@router.put("/{hospital_id}", response_model=HospitalOut)
def update_hospital(hospital_id: int, data: HospitalCreate, db: Session = Depends(get_db)):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    dup = db.query(Hospital).filter(Hospital.name == data.name, Hospital.id != hospital_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Hospital name already taken")
    hosp.name = data.name
    hosp.region = data.region
    hosp.governorate_id = data.governorate_id
    hosp.hospital_type_id = data.hospital_type_id
    hosp.address = data.address
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp


@router.delete("/{hospital_id}")
def delete_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    db.delete(hosp)
    db.commit()
    cache.invalidate()
    return {"ok": True}


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
        # Clear cache so fresh data is served
        cache.invalidate()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
