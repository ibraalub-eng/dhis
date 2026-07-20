from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import FacilityOwnership, Hospital
from app.schemas import FacilityOwnershipOut, FacilityOwnershipCreate

router = APIRouter(prefix="/facility-ownerships", tags=["facility_ownerships"])


@router.get("/", response_model=List[FacilityOwnershipOut])
def list_facility_ownerships(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(FacilityOwnership).order_by(FacilityOwnership.name)
    return q.offset(skip).limit(limit).all()


@router.get("/{ownership_id}", response_model=FacilityOwnershipOut)
def get_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    return ow


@router.post("/", response_model=FacilityOwnershipOut)
def create_facility_ownership(data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
    existing = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Facility ownership already exists")
    ow = FacilityOwnership(name=data.name)
    db.add(ow)
    db.commit()
    db.refresh(ow)
    cache.invalidate()
    return ow


@router.put("/{ownership_id}", response_model=FacilityOwnershipOut)
def update_facility_ownership(ownership_id: int, data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    dup = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name, FacilityOwnership.id != ownership_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Facility ownership name already taken")
    ow.name = data.name
    db.commit()
    db.refresh(ow)
    cache.invalidate()
    return ow


@router.delete("/{ownership_id}")
def delete_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    linked = db.query(Hospital).filter(Hospital.facility_ownership_id == ownership_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete facility ownership with linked hospitals")
    db.delete(ow)
    db.commit()
    cache.invalidate()
    return {"ok": True}
