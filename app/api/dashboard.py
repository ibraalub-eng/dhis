import json
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult, ClinicalInsight
from sqlalchemy import func, text
from app.engine.pipeline import get_enabled_values_for_hospital_month

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(hospital_id: int | None = None, month: str | None = None, year: str | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db, hospital_id=hospital_id)

    # Filter hospitals by active status
    total_hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).count()

    # Count reports only for enabled months
    reports_q = db.query(QualityScore).distinct(
        QualityScore.hospital_id, QualityScore.month
    )
    if enabled_months:
        reports_q = reports_q.filter(QualityScore.month.in_(enabled_months))
    total_reports = reports_q.count()

    q = db.query(func.avg(QualityScore.score))
    if hospital_id:
        q = q.filter(QualityScore.hospital_id == hospital_id)
    if enabled_months:
        q = q.filter(QualityScore.month.in_(enabled_months))
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
    if enabled_months:
        placeholders = ", ".join([f":m{i}" for i in range(len(enabled_months))])
        trend_conditions.append(f"qs.month IN ({placeholders})")
        for i, m in enumerate(enabled_months):
            trend_params[f"m{i}"] = m
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

    # hospital comparison (only enabled months)
    comp_q = db.query(
        Hospital.id,
        Hospital.name,
        func.coalesce(func.avg(QualityScore.score), 0).label("avg_score"),
        func.count(QualityScore.id).label("report_count"),
    ).outerjoin(
        QualityScore, QualityScore.hospital_id == Hospital.id
    ).filter(
        Hospital.is_active.is_(True)
    )
    if enabled_months:
        comp_q = comp_q.filter(QualityScore.month.in_(enabled_months))
    comp = comp_q.group_by(Hospital.id, Hospital.name).order_by(
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

    # radar components (only enabled months)
    radar_q = db.query(
        func.avg(QualityScore.rule_compliance).label("rule_compliance"),
        func.avg(QualityScore.completeness).label("completeness"),
        func.avg(QualityScore.consistency).label("consistency"),
    )
    if hospital_id:
        radar_q = radar_q.filter(QualityScore.hospital_id == hospital_id)
    if month:
        radar_q = radar_q.filter(QualityScore.month == month)
    elif enabled_months:
        radar_q = radar_q.filter(QualityScore.month.in_(enabled_months))
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
    elif enabled_months:
        outlier_q = outlier_q.filter(QualityScore.month.in_(enabled_months))
    if year:
        outlier_q = outlier_q.filter(QualityScore.month.like(f"{year}-%"))
    outlier_row = outlier_q.first()
    outlier_penalty = round(float(outlier_row.avg_op or 0), 1)
    radar_components["Outlier Score"] = round(max(0, 100 - outlier_penalty), 1)

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
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db, hospital_id=hospital_id)
    base = db.query(QualityScore)
    if hospital_id:
        base = base.filter(QualityScore.hospital_id == hospital_id)
    if month:
        base = base.filter(QualityScore.month == month)
    if enabled_months:
        base = base.filter(QualityScore.month.in_(enabled_months))

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


@router.get("/ranking")
def dashboard_ranking(hospital_id: int | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db)

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    rows = []
    for h in hospitals:
        q = db.query(QualityScore).filter(QualityScore.hospital_id == h.id)
        if enabled_months:
            q = q.filter(QualityScore.month.in_(enabled_months))
        scores = q.order_by(QualityScore.month.asc()).all()

        if not scores:
            continue

        avg_score = round(sum(s.score for s in scores) / len(scores), 1)
        avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1)
        avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1)
        avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1)

        recent_3 = [s.score for s in scores[-3:]]
        if len(recent_3) >= 2:
            direction = "up" if recent_3[-1] > recent_3[0] else "down" if recent_3[-1] < recent_3[0] else "stable"
        else:
            direction = "stable"

        conf = db.query(ConfidenceScore).filter(
            ConfidenceScore.hospital_id == h.id
        ).order_by(ConfidenceScore.month.desc()).first()
        conf_score = round(conf.overall_confidence, 1) if conf else 0

        alerts_count = db.query(ValidationResult).filter(
            ValidationResult.hospital_id == h.id,
            ValidationResult.status == "FAIL"
        ).count()

        insights = db.query(ClinicalInsight).filter(
            ClinicalInsight.hospital_id == h.id
        ).all()
        rate_values = {}
        for ins in insights:
            try:
                data = json.loads(ins.analysis_data)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in data.get("classifications", []):
                rn = c.get("rate_name", "")
                val = c.get("value")
                if val is not None:
                    rate_values.setdefault(rn, []).append(val)
        clinical_rates = {}
        for rn, vals in rate_values.items():
            if vals:
                clinical_rates[rn] = round(sum(vals) / len(vals), 1)

        rows.append({
            "id": h.id,
            "name": h.name,
            "avg_score": avg_score,
            "trend_direction": direction,
            "avg_clinical_rate": round(sum(clinical_rates.values()) / len(clinical_rates), 1) if clinical_rates else 0,
            "confidence": conf_score,
            "completeness": avg_completeness,
            "consistency": avg_consistency,
            "reports": len(scores),
            "alerts": alerts_count,
        })

    rows.sort(key=lambda r: r["avg_score"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return rows


@router.get("/hospital-performance/{hospital_id}")
def hospital_performance(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    scores = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id
    ).order_by(QualityScore.month.asc()).all()

    quality_trend = [{"month": s.month, "score": round(s.score, 1)} for s in scores]
    avg_score = round(sum(s.score for s in scores) / len(scores), 1) if scores else 0
    avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1) if scores else 0

    if avg_score >= 90: grade = "A"
    elif avg_score >= 75: grade = "B"
    elif avg_score >= 60: grade = "C"
    else: grade = "D"

    latest_month = scores[-1].month if scores else None
    clinical_rates = []
    if latest_month:
        try:
            values = get_enabled_values_for_hospital_month(db, hospital_id, latest_month)
            if values:
                from app.engine.clinical import run_clinical_analysis
                result = run_clinical_analysis(hospital=hospital.name, month=latest_month, values=values)
                MAIN_RATES = {"C-Section Rate", "Maternal Mortality Ratio", "Neonatal Mortality Rate",
                              "Preterm Birth Rate", "Severe Maternal Morbidity Rate", "Stillbirth Rate",
                              "NICU Admission Rate"}
                for c in result.classifications:
                    if c.rate_name in MAIN_RATES:
                        clinical_rates.append({
                            "rate_name": c.rate_name,
                            "value": round(c.value, 1) if c.value else 0,
                            "unit": c.unit,
                            "classification": c.classification,
                        })
        except Exception:
            pass

    if latest_month and clinical_rates:
        try:
            peers = db.query(Hospital).filter(Hospital.is_active.is_(True), Hospital.id != hospital_id).all()
            peer_rate_vals = {r["rate_name"]: [] for r in clinical_rates}
            for ph in peers:
                pv = get_enabled_values_for_hospital_month(db, ph.id, latest_month)
                if not pv:
                    continue
                from app.engine.clinical import run_clinical_analysis as rca_peer
                try:
                    pr = rca_peer(hospital=ph.name, month=latest_month, values=pv)
                except Exception:
                    continue
                for c in pr.classifications:
                    if c.rate_name in peer_rate_vals and c.value is not None:
                        peer_rate_vals[c.rate_name].append(c.value)
            for r in clinical_rates:
                vals = peer_rate_vals.get(r["rate_name"], [])
                r["peer_avg"] = round(sum(vals) / len(vals), 1) if vals else None
        except Exception:
            pass

    total_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).count()
    recent_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).order_by(ValidationResult.month.desc()).limit(5).all()
    last_alerts = [
        {"month": a.month, "rule_code": a.rule_code, "severity": a.severity, "details": (a.details or "")[:80]}
        for a in recent_alerts
    ]

    return {
        "id": hospital.id, "name": hospital.name, "grade": grade,
        "avg_score": avg_score, "avg_compliance": avg_compliance,
        "avg_completeness": avg_completeness, "avg_consistency": avg_consistency,
        "quality_trend": quality_trend, "clinical_rates": clinical_rates,
        "total_alerts": total_alerts, "last_alerts": last_alerts,
    }
