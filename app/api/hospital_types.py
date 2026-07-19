from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import HospitalType, Hospital
from app.schemas import HospitalTypeOut, HospitalTypeCreate

router = APIRouter(prefix="/hospital-types", tags=["hospital_types"])


@router.get("/", response_model=List[HospitalTypeOut])
def list_hospital_types(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(HospitalType).order_by(HospitalType.name)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=HospitalTypeOut)
def create_hospital_type(data: HospitalTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(HospitalType).filter(HospitalType.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Hospital type already exists")
    ht = HospitalType(name=data.name)
    db.add(ht)
    db.commit()
    db.refresh(ht)
    cache.invalidate()
    return ht


@router.put("/{hospital_type_id}", response_model=HospitalTypeOut)
def update_hospital_type(hospital_type_id: int, data: HospitalTypeCreate, db: Session = Depends(get_db)):
    ht = db.query(HospitalType).filter(HospitalType.id == hospital_type_id).first()
    if not ht:
        raise HTTPException(status_code=404, detail="Hospital type not found")
    dup = db.query(HospitalType).filter(HospitalType.name == data.name, HospitalType.id != hospital_type_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Hospital type name already taken")
    ht.name = data.name
    db.commit()
    db.refresh(ht)
    cache.invalidate()
    return ht


@router.delete("/{hospital_type_id}")
def delete_hospital_type(hospital_type_id: int, db: Session = Depends(get_db)):
    ht = db.query(HospitalType).filter(HospitalType.id == hospital_type_id).first()
    if not ht:
        raise HTTPException(status_code=404, detail="Hospital type not found")
    linked = db.query(Hospital).filter(Hospital.hospital_type_id == hospital_type_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete hospital type with linked hospitals")
    db.delete(ht)
    db.commit()
    cache.invalidate()
    return {"ok": True}
