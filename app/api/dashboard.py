import re
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult
from sqlalchemy import func, text

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(hospital_id: int | None = None, month: str | None = None, year: str | None = None, db: Session = Depends(get_db)):
    total_hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).count()
    total_reports = db.query(QualityScore).distinct(
        QualityScore.hospital_id, QualityScore.month
    ).count()

    q = db.query(func.avg(QualityScore.score))
    if hospital_id:
        q = q.filter(QualityScore.hospital_id == hospital_id)
    avg_score = round(q.scalar() or 0, 1)

    alerts_total = db.query(ValidationResult).filter(
        ValidationResult.status == "FAIL"
    ).count()

    trend_params = {}
    trend_conditions = []
    if hospital_id:
        trend_conditions.append("qs.hospital_id = :hid")
        trend_params["hid"] = hospital_id
    if year:
        if not re.match(r"^\d{4}$", str(year)):
            return {"error": "Invalid year format"}
        trend_conditions.append("qs.month LIKE :year_pattern")
        trend_params["year_pattern"] = f"{year}-%"
    where_clause = " AND ".join(trend_conditions) if trend_conditions else "1=1"

    # quality trend (last 12 months, optionally filtered by year)
    trend_sql = f"""
        SELECT qs.month, AVG(qs.score) as score
        FROM quality_scores qs
        WHERE {where_clause}
        GROUP BY qs.month ORDER BY qs.month DESC LIMIT 12
    """
    trend_rows = db.execute(text(trend_sql), trend_params).fetchall()
    trend_data = sorted(
        [{"month": t[0], "score": round(float(t[1]), 1)} for t in trend_rows],
        key=lambda x: x["month"],
    )

    # hospital comparison
    comp = db.query(
        Hospital.id,
        Hospital.name,
        func.coalesce(func.avg(QualityScore.score), 0).label("avg_score"),
        func.count(QualityScore.id).label("report_count"),
    ).outerjoin(
        QualityScore, QualityScore.hospital_id == Hospital.id
    ).filter(
        Hospital.is_active.is_(True)
    ).group_by(Hospital.id, Hospital.name).order_by(
        func.avg(QualityScore.score).desc().nullslast()
    ).all()

    hospital_compare = [
        {
            "id": c.id,
            "name": c.name,
            "avg_score": round(float(c.avg_score), 1) if c.avg_score else 0,
            "report_count": c.report_count,
        }
        for c in comp
    ]

    # confidence distribution
    conf_q = db.query(
        ConfidenceScore.level,
        func.count(ConfidenceScore.id).label("count"),
    )
    if hospital_id:
        conf_q = conf_q.filter(ConfidenceScore.hospital_id == hospital_id)
    conf_dist = conf_q.group_by(ConfidenceScore.level).all()
    dist_map = {"CRITICAL": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for c in conf_dist:
        dist_map[c.level] = c.count

    # radar components
    radar_q = db.query(
        func.avg(QualityScore.rule_compliance).label("rule_compliance"),
        func.avg(QualityScore.completeness).label("completeness"),
        func.avg(QualityScore.consistency).label("consistency"),
    )
    if hospital_id:
        radar_q = radar_q.filter(QualityScore.hospital_id == hospital_id)
    if month:
        radar_q = radar_q.filter(QualityScore.month == month)
    if year:
        radar_q = radar_q.filter(QualityScore.month.like(f"{year}-%"))
    radar_row = radar_q.first()
    radar_components = {
        "Rule Compliance": round(float(radar_row.rule_compliance or 0), 1),
        "Completeness": round(float(radar_row.completeness or 0), 1),
        "Consistency": round(float(radar_row.consistency or 0), 1),
    }
    outlier_q = db.query(func.avg(func.abs(QualityScore.outlier_penalty)).label("avg_op"))
    if hospital_id:
        outlier_q = outlier_q.filter(QualityScore.hospital_id == hospital_id)
    if month:
        outlier_q = outlier_q.filter(QualityScore.month == month)
    if year:
        outlier_q = outlier_q.filter(QualityScore.month.like(f"{year}-%"))
    outlier_row = outlier_q.first()
    outlier_penalty = round(float(outlier_row.avg_op or 0), 1)
    radar_components["Outlier Penalty (inv)"] = max(0, 100 - outlier_penalty)

    return {
        "total_hospitals": total_hospitals,
        "total_reports": total_reports,
        "avg_quality_score": avg_score,
        "total_alerts": alerts_total,
        "quality_trend": trend_data,
        "hospital_compare": hospital_compare,
        "confidence_distribution": dist_map,
        "radar_components": radar_components,
    }


@router.get("/yoy")
def year_over_year(hospital_id: int | None = None, db: Session = Depends(get_db)):
    sql = """
        SELECT SUBSTR(qs.month, 6, 2) as mm,
               SUBSTR(qs.month, 1, 4) as yyyy,
               AVG(qs.score) as score
        FROM quality_scores qs
        WHERE 1=1
    """
    params = {}
    if hospital_id:
        sql += " AND qs.hospital_id = :hid"
        params["hid"] = hospital_id
    sql += " GROUP BY mm, yyyy ORDER BY yyyy, mm"
    rows = db.execute(text(sql), params).fetchall()

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    years = sorted(set(r[1] for r in rows))
    result = {}
    for y in years:
        year_data = {month_names[int(r[0]) - 1]: round(float(r[2]), 1)
                     for r in rows if r[1] == y}
        result[f"year_{y}"] = year_data

    all_months = sorted(set(int(r[0]) for r in rows))
    labels = [month_names[m - 1] for m in all_months]

    return {
        "labels": labels,
        "years": sorted(years),
        "data": result,
    }


@router.get("/kpi")
def dashboard_kpi(hospital_id: int | None = None, month: str | None = None, db: Session = Depends(get_db)):
    base = db.query(QualityScore)
    if hospital_id:
        base = base.filter(QualityScore.hospital_id == hospital_id)
    if month:
        base = base.filter(QualityScore.month == month)

    agg = base.with_entities(
        func.avg(QualityScore.score).label("avg_score"),
        func.avg(QualityScore.rule_compliance).label("avg_compliance"),
        func.avg(QualityScore.completeness).label("avg_completeness"),
        func.avg(QualityScore.consistency).label("avg_consistency"),
    ).first()

    avg_score = round(float(agg.avg_score or 0), 1)
    avg_compliance = round(float(agg.avg_compliance or 0), 1)
    avg_completeness = round(float(agg.avg_completeness or 0), 1)
    avg_consistency = round(float(agg.avg_consistency or 0), 1)

    # confidence high %
    cq = db.query(func.count(ConfidenceScore.id))
    if hospital_id:
        cq = cq.filter(ConfidenceScore.hospital_id == hospital_id)
    total_conf = cq.scalar() or 1

    cq_high = db.query(func.count(ConfidenceScore.id)).filter(
        ConfidenceScore.level == "HIGH"
    )
    if hospital_id:
        cq_high = cq_high.filter(ConfidenceScore.hospital_id == hospital_id)
    high_count = cq_high.scalar() or 0
    conf_high_pct = round((high_count / total_conf) * 100, 1)

    report_count = base.count()

    kpis = [
        {"id": "quality_score", "label": "Quality Score", "value": avg_score,
         "target": 80, "unit": "%", "higher_is_better": True},
        {"id": "rule_compliance", "label": "Rule Compliance", "value": avg_compliance,
         "target": 85, "unit": "%", "higher_is_better": True},
        {"id": "completeness", "label": "Completeness", "value": avg_completeness,
         "target": 90, "unit": "%", "higher_is_better": True},
        {"id": "consistency", "label": "Consistency", "value": avg_consistency,
         "target": 85, "unit": "%", "higher_is_better": True},
        {"id": "conf_high", "label": "High Confidence", "value": conf_high_pct,
         "target": 60, "unit": "%", "higher_is_better": True},
        {"id": "report_coverage", "label": "Report Coverage", "value": report_count,
         "target": None, "unit": "reports", "higher_is_better": True},
    ]
    return {"kpis": kpis}
