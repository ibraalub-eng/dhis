from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital
from app.engine.audit import get_calculation_steps, get_benchmark, get_data_audit, generate_audit_report, build_explanation
from app.core.deps import require_permission

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_permission("audit.read"))])


@router.get("/")
def list_audit_summary():
    """Audit log placeholder — AuditLog model not yet created.
    Returns empty list for now."""
    return []


@router.get("/explain")
def api_explain(
    kind: str = Query(..., description="quality_score | anomaly | heatmap_cell | rule"),
    hospital_id: int = Query(None, description="Omit for a month-level aggregate explanation"),
    month: str = Query(..., description="Month YYYY-MM"),
    rate_name: str = Query(None),
    indicator_code: str = Query(None),
    rule_code: str = Query(None),
    component: str = Query(None, description="quality component for the score_trend sparkline: quality_score | rule_compliance | completeness | consistency | outlier_score"),
    db: Session = Depends(get_db),
):
    """Explain any derived result: what / where / why / how / reproduce / chain.

    Computed on demand from the DB (no cache) — the answer is always built
    from the same rows the dashboards display. 404s when the underlying
    result does not exist so the popup can show a clear empty state.
    """
    if hospital_id is not None:
        hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
        if not hosp:
            raise HTTPException(status_code=404, detail="Hospital not found")
    result = build_explanation(
        db, kind, hospital_id, month,
        rate_name=rate_name, indicator_code=indicator_code, rule_code=rule_code,
        component=component,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


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
