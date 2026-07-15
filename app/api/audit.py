from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital
from app.engine.audit import get_calculation_steps, get_benchmark, get_data_audit, generate_audit_report

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/calculation-steps/{hospital_id}")
def api_calculation_steps(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_calculation_steps(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/benchmark/{hospital_id}")
def api_benchmark(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_benchmark(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/data-auditor/{hospital_id}")
def api_data_auditor(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_data_audit(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/report/{hospital_id}")
def api_report(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = generate_audit_report(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
