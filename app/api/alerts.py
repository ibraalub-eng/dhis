from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_
from typing import Optional
from app.database import get_db
from app.models import Hospital, Rule, ValidationResult
from app.core.deps import require_permission, get_user_hospital_ids

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_permission("alerts.read"))])

SEVERITY_ORDER = case(
    (ValidationResult.severity == "CRITICAL", 0),
    (ValidationResult.severity == "HIGH", 1),
    (ValidationResult.severity == "MEDIUM", 2),
    (ValidationResult.severity == "LOW", 3),
    else_=4,
)


def _non_benchmark_failures(query):
    """Real, non-benchmark failures: the rule must still exist.

    ValidationResult rows are snapshots of the rules that existed when they
    were written. A deleted rule (or a restore that brought back rows without
    its Rule) leaves rows behind whose code is absent from the Rules Manager —
    showing them here produced "R0xx failures" that nobody could find or fix in
    the rules screen. The inner join makes an orphan row unlistable at read
    time even if a cleanup pass has not run yet.
    """
    return query.join(Rule, Rule.code == ValidationResult.rule_code).filter(
        or_(
            ValidationResult.rule_type.is_(None),
            func.upper(ValidationResult.rule_type) != "BENCHMARK",
        )
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
    user=Depends(require_permission("alerts.read")),
):
    user_hosp_ids = get_user_hospital_ids(user, db)
    q = _non_benchmark_failures(
        db.query(ValidationResult).filter(ValidationResult.status == "FAIL")
    )
    if user_hosp_ids is not None:
        q = q.filter(ValidationResult.hospital_id.in_(user_hosp_ids))
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

    hospital_counts = _non_benchmark_failures(
        db.query(
            ValidationResult.hospital_id,
            func.count().label("cnt"),
        )
        .filter(ValidationResult.status == "FAIL")
        .filter(ValidationResult.severity.in_(["CRITICAL", "HIGH"]))
    )
    if user_hosp_ids is not None:
        hospital_counts = hospital_counts.filter(ValidationResult.hospital_id.in_(user_hosp_ids))
    if month:
        hospital_counts = hospital_counts.filter(ValidationResult.month == month)
    hospital_counts = hospital_counts.group_by(ValidationResult.hospital_id).order_by(func.count().desc()).limit(10).all()

    hc = []
    for row in hospital_counts:
        hosp = db.query(Hospital).filter(Hospital.id == row.hospital_id).first()
        hc.append({"hospital_id": row.hospital_id, "hospital": hosp.name if hosp else "Unknown", "alert_count": row.cnt})

    critical_q = _non_benchmark_failures(
        db.query(ValidationResult).filter(
            ValidationResult.status == "FAIL",
            ValidationResult.severity == "CRITICAL",
        )
    )
    if user_hosp_ids is not None:
        critical_q = critical_q.filter(ValidationResult.hospital_id.in_(user_hosp_ids))
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
            "hospital_id": vr.hospital_id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": vr.month,
            "rule_code": vr.rule_code,
            "rule_description": vr.rule_description,
            "severity": vr.severity,
            "rule_type": vr.rule_type,
            "details": vr.details,
        })

    return {
        "total_alerts": total,
        "by_severity": sev_map,
        "top_hospitals": hc,
        "recent_critical": critical,
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
    user=Depends(require_permission("alerts.read")),
):
    user_hosp_ids = get_user_hospital_ids(user, db)
    q = _non_benchmark_failures(
        db.query(ValidationResult).filter(ValidationResult.status == "FAIL")
    )
    if user_hosp_ids is not None:
        q = q.filter(ValidationResult.hospital_id.in_(user_hosp_ids))
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
