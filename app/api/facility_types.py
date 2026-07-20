from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import FacilityType, Hospital
from app.schemas import FacilityTypeOut, FacilityTypeCreate

router = APIRouter(prefix="/facility-types", tags=["facility_types"])


@router.get("/", response_model=List[FacilityTypeOut])
def list_facility_types(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(FacilityType).order_by(FacilityType.name)
    return q.offset(skip).limit(limit).all()


@router.get("/{type_id}", response_model=FacilityTypeOut)
def get_facility_type(type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Facility type not found")
    return ft


@router.post("/", response_model=FacilityTypeOut)
def create_facility_type(data: FacilityTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(FacilityType).filter(FacilityType.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Facility type already exists")
    ft = FacilityType(name=data.name)
    db.add(ft)
    db.commit()
    db.refresh(ft)
    cache.invalidate()
    return ft


@router.put("/{type_id}", response_model=FacilityTypeOut)
def update_facility_type(type_id: int, data: FacilityTypeCreate, db: Session = Depends(get_db)):
    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Facility type not found")
    dup = db.query(FacilityType).filter(FacilityType.name == data.name, FacilityType.id != type_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Facility type name already taken")
    ft.name = data.name
    db.commit()
    db.refresh(ft)
    cache.invalidate()
    return ft


@router.delete("/{type_id}")
def delete_facility_type(type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Facility type not found")
    linked = db.query(Hospital).filter(Hospital.facility_type_id == type_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete facility type with linked hospitals")
    db.delete(ft)
    db.commit()
    cache.invalidate()
    return {"ok": True}
