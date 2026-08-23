from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import Governorate, Hospital
from app.schemas import GovernorateOut, GovernorateCreate
from app.core.deps import require_permission

router = APIRouter(prefix="/governorates", tags=["governorates"], dependencies=[Depends(require_permission("analysis.read"))])


@router.get("/", response_model=List[GovernorateOut])
def list_governorates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(Governorate).order_by(Governorate.name)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=GovernorateOut)
def create_governorate(data: GovernorateCreate, db: Session = Depends(get_db)):
    existing = db.query(Governorate).filter(Governorate.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Governorate already exists")
    gov = Governorate(name=data.name)
    db.add(gov)
    db.commit()
    db.refresh(gov)
    cache.invalidate()
    return gov


@router.put("/{governorate_id}", response_model=GovernorateOut)
def update_governorate(governorate_id: int, data: GovernorateCreate, db: Session = Depends(get_db)):
    gov = db.query(Governorate).filter(Governorate.id == governorate_id).first()
    if not gov:
        raise HTTPException(status_code=404, detail="Governorate not found")
    dup = db.query(Governorate).filter(Governorate.name == data.name, Governorate.id != governorate_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Governorate name already taken")
    gov.name = data.name
    db.commit()
    db.refresh(gov)
    cache.invalidate()
    return gov


@router.delete("/{governorate_id}")
def delete_governorate(governorate_id: int, db: Session = Depends(get_db)):
    gov = db.query(Governorate).filter(Governorate.id == governorate_id).first()
    if not gov:
        raise HTTPException(status_code=404, detail="Governorate not found")
    linked = db.query(Hospital).filter(Hospital.governorate_id == governorate_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete governorate with linked hospitals")
    db.delete(gov)
    db.commit()
    cache.invalidate()
    return {"ok": True}
