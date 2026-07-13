from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import Optional, List
from app.database import get_db
from app.models import Hospital, ValidationResult, AnomalyResult, QualityScore

router = APIRouter(prefix="/alerts", tags=["alerts"])

SEVERITY_ORDER = case(
    (ValidationResult.severity == "CRITICAL", 0),
    (ValidationResult.severity == "HIGH", 1),
    (ValidationResult.severity == "MEDIUM", 2),
    (ValidationResult.severity == "LOW", 3),
    else_=4,
)


def _severity_color(sev: str) -> str:
    return {"CRITICAL": "#b71c1c", "HIGH": "#c62828", "MEDIUM": "#e65100", "LOW": "#1565c0"}.get(sev, "#888")


def _severity_icon(sev: str) -> str:
    return {"CRITICAL": "\u26a0", "HIGH": "\u26a0", "MEDIUM": "\u26a1", "LOW": "\u2139"}.get(sev, "\u2139")


@router.get("/overview")
def alerts_overview(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    db: Session = Depends(get_db),
):
    q = db.query(ValidationResult).filter(ValidationResult.status == "FAIL")
    if month:
        q = q.filter(ValidationResult.month == month)
    if hospital_id:
        q = q.filter(ValidationResult.hospital_id == hospital_id)
    total = q.count()

    severity_counts = (
        q.with_entities(ValidationResult.severity, func.count().label("cnt"))
        .group_by(ValidationResult.severity)
        .all()
    )
    sev_map = {}
    for row in severity_counts:
        sev_map[row.severity] = {
            "count": row.cnt,
            "color": _severity_color(row.severity),
            "icon": _severity_icon(row.severity),
        }
    for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if s not in sev_map:
            sev_map[s] = {"count": 0, "color": _severity_color(s), "icon": _severity_icon(s)}

    hospital_counts = (
        db.query(
            ValidationResult.hospital_id,
            func.count().label("cnt"),
        )
        .filter(ValidationResult.status == "FAIL")
        .filter(ValidationResult.severity.in_(["CRITICAL", "HIGH"]))
    )
    if month:
        hospital_counts = hospital_counts.filter(ValidationResult.month == month)
    hospital_counts = hospital_counts.group_by(ValidationResult.hospital_id).order_by(func.count().desc()).limit(10).all()

    hc = []
    for row in hospital_counts:
        hosp = db.query(Hospital).filter(Hospital.id == row.hospital_id).first()
        hc.append({"hospital_id": row.hospital_id, "hospital": hosp.name if hosp else "Unknown", "alert_count": row.cnt})

    critical_q = db.query(ValidationResult).filter(
        ValidationResult.status == "FAIL",
        ValidationResult.severity == "CRITICAL",
    )
    if month:
        critical_q = critical_q.filter(ValidationResult.month == month)
    if hospital_id:
        critical_q = critical_q.filter(ValidationResult.hospital_id == hospital_id)
    critical_q = critical_q.order_by(SEVERITY_ORDER, ValidationResult.rule_code).limit(20)
    critical = []
    for vr in critical_q.all():
        hosp = db.query(Hospital).filter(Hospital.id == vr.hospital_id).first()
        critical.append({
            "id": vr.id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": vr.month,
            "rule_code": vr.rule_code,
            "rule_description": vr.rule_description,
            "severity": vr.severity,
            "rule_type": vr.rule_type,
            "details": vr.details,
        })

    outlier_count = 0
    oq = db.query(AnomalyResult).filter(AnomalyResult.is_outlier == True)
    if month:
        oq = oq.filter(AnomalyResult.month == month)
    if hospital_id:
        oq = oq.filter(AnomalyResult.hospital_id == hospital_id)
    outlier_count = oq.count()

    return {
        "total_alerts": total,
        "by_severity": sev_map,
        "top_hospitals": hc,
        "recent_critical": critical,
        "outlier_count": outlier_count,
    }


@router.get("/list")
def alerts_list(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    rule_type: Optional[str] = Query(None, description="Filter by rule type"),
    limit: int = Query(50, description="Max results"),
    offset: int = Query(0, description="Offset"),
    db: Session = Depends(get_db),
):
    q = db.query(ValidationResult).filter(ValidationResult.status == "FAIL")
    if month:
        q = q.filter(ValidationResult.month == month)
    if hospital_id:
        q = q.filter(ValidationResult.hospital_id == hospital_id)
    if severity:
        q = q.filter(ValidationResult.severity == severity.upper())
    if rule_type:
        q = q.filter(ValidationResult.rule_type == rule_type.upper())

    total = q.count()
    rows = q.order_by(SEVERITY_ORDER, ValidationResult.month.desc(), ValidationResult.rule_code).offset(offset).limit(limit).all()

    items = []
    for vr in rows:
        hosp = db.query(Hospital).filter(Hospital.id == vr.hospital_id).first()
        items.append({
            "id": vr.id,
            "hospital_id": vr.hospital_id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": vr.month,
            "rule_code": vr.rule_code,
            "rule_description": vr.rule_description,
            "severity": vr.severity,
            "rule_type": vr.rule_type or "LOGIC",
            "details": vr.details or "",
        })

    return {"total": total, "items": items, "offset": offset, "limit": limit}
