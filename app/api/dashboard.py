import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db

logger = logging.getLogger(__name__)
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult
from sqlalchemy import func, text
from app.engine.pipeline import get_enabled_values_for_hospital_month
from app.core.deps import require_permission, get_user_hospital_ids

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_permission("dashboard.read"))])

# المعدلات السريرية الرئيسية المعروضة في لوحة المستشفى وعمود متوسط المعدل السريري
_MAIN_CLINICAL_RATES = {
    "C-Section Rate", "Maternal Mortality Ratio", "Neonatal Mortality Rate",
    "Preterm Birth Rate", "Severe Maternal Morbidity Rate", "Stillbirth Rate",
    "NICU Admission Rate",
}


@router.get("/overview")
def dashboard_overview(
    hospital_id: int | None = None,
    month: str | None = None,
    month_from: str | None = None,
    month_to: str | None = None,
    year: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dashboard.read")),
):
    # Filter by user's assigned hospitals
    user_hosp_ids = get_user_hospital_ids(user, db)
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db, hospital_id=hospital_id)

    # Filter hospitals by active status
    hosp_q = db.query(Hospital).filter(Hospital.is_active.is_(True))
    if user_hosp_ids is not None:
        hosp_q = hosp_q.filter(Hospital.id.in_(user_hosp_ids))
    total_hospitals = hosp_q.count()

    # Count reports only for enabled months.
    # NOTE: Query.distinct(col1, col2) emits PostgreSQL-only DISTINCT ON which is
    # silently ignored on SQLite (inflating the count with duplicate rows). Use a
    # portable subquery on the (hospital_id, month) pair instead.
    reports_q = db.query(QualityScore.hospital_id, QualityScore.month).distinct()
    if user_hosp_ids is not None:
        reports_q = reports_q.filter(QualityScore.hospital_id.in_(user_hosp_ids))
    if hospital_id:
        reports_q = reports_q.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        reports_q = reports_q.filter(QualityScore.month >= month_from)
    if month_to:
        reports_q = reports_q.filter(QualityScore.month <= month_to)
    elif enabled_months:
        reports_q = reports_q.filter(QualityScore.month.in_(enabled_months))
    total_reports = reports_q.count()

    q = db.query(func.avg(QualityScore.score))
    if hospital_id:
        q = q.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        q = q.filter(QualityScore.month >= month_from)
    if month_to:
        q = q.filter(QualityScore.month <= month_to)
    elif enabled_months:
        q = q.filter(QualityScore.month.in_(enabled_months))
    avg_score = round(q.scalar() or 0, 1)

    alerts_q = db.query(ValidationResult).filter(
        ValidationResult.status == "FAIL"
    )
    if hospital_id:
        alerts_q = alerts_q.filter(ValidationResult.hospital_id == hospital_id)
    if month_from:
        alerts_q = alerts_q.filter(ValidationResult.month >= month_from)
    if month_to:
        alerts_q = alerts_q.filter(ValidationResult.month <= month_to)
    alerts_total = alerts_q.count()

    trend_q = db.query(
        QualityScore.month,
        func.avg(QualityScore.score).label("score"),
    )
    if hospital_id:
        trend_q = trend_q.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        trend_q = trend_q.filter(QualityScore.month >= month_from)
    if month_to:
        trend_q = trend_q.filter(QualityScore.month <= month_to)
    elif year:
        if not re.match(r"^\d{4}$", str(year)):
            return {"error": "Invalid year format"}
        trend_q = trend_q.filter(QualityScore.month.like(f"{year}-%"))
    elif enabled_months:
        trend_q = trend_q.filter(QualityScore.month.in_(enabled_months))
    trend_rows = trend_q.group_by(QualityScore.month).order_by(QualityScore.month.desc()).limit(12).all()
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
    if month_from:
        comp_q = comp_q.filter(QualityScore.month >= month_from)
    if month_to:
        comp_q = comp_q.filter(QualityScore.month <= month_to)
    elif enabled_months:
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
    if month_from:
        conf_q = conf_q.filter(ConfidenceScore.month >= month_from)
    if month_to:
        conf_q = conf_q.filter(ConfidenceScore.month <= month_to)
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
    if month_from:
        radar_q = radar_q.filter(QualityScore.month >= month_from)
    if month_to:
        radar_q = radar_q.filter(QualityScore.month <= month_to)
    elif month:
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
    if month_from:
        outlier_q = outlier_q.filter(QualityScore.month >= month_from)
    if month_to:
        outlier_q = outlier_q.filter(QualityScore.month <= month_to)
    elif month:
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


@router.get("/kpi")
def dashboard_kpi(hospital_id: int | None = None, month: str | None = None, month_from: str | None = None, month_to: str | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db, hospital_id=hospital_id)
    base = db.query(QualityScore)
    if hospital_id:
        base = base.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        base = base.filter(QualityScore.month >= month_from)
    if month_to:
        base = base.filter(QualityScore.month <= month_to)
    elif month:
        base = base.filter(QualityScore.month == month)
    elif enabled_months:
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
    if month_from:
        cq = cq.filter(ConfidenceScore.month >= month_from)
    if month_to:
        cq = cq.filter(ConfidenceScore.month <= month_to)
    total_conf = cq.scalar() or 1

    cq_high = db.query(func.count(ConfidenceScore.id)).filter(
        ConfidenceScore.level == "HIGH"
    )
    if hospital_id:
        cq_high = cq_high.filter(ConfidenceScore.hospital_id == hospital_id)
    if month_from:
        cq_high = cq_high.filter(ConfidenceScore.month >= month_from)
    if month_to:
        cq_high = cq_high.filter(ConfidenceScore.month <= month_to)
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
def dashboard_ranking(hospital_id: int | None = None, month_from: str | None = None, month_to: str | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db)

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    rows = []
    for h in hospitals:
        q = db.query(QualityScore).filter(QualityScore.hospital_id == h.id)
        if month_from:
            q = q.filter(QualityScore.month >= month_from)
        if month_to:
            q = q.filter(QualityScore.month <= month_to)
        elif enabled_months:
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

        # المعدل السريري: متوسط قيم المعدلات الرئيسية لآخر شهر متاح، يُحسب مباشرة
        # من بيانات المستشفى (مثل لوحة المستشفى) — جدول ClinicalInsight لا يُملأ
        # في أي مكان، فكان العمود صفراً دائماً.
        clinical_rates = {}
        if scores:
            latest_month = scores[-1].month
            try:
                from app.engine.pipeline import get_enabled_values_for_hospital_month
                from app.engine.clinical import run_clinical_analysis
                values = get_enabled_values_for_hospital_month(db, h.id, latest_month)
                if values:
                    # include_ai=False: نحتاج قيم المعدلات فقط — لا توصيات AI لكل مستشفى
                    result = run_clinical_analysis(hospital=h.name, month=latest_month,
                                                   values=values, include_ai=False)
                    clinical_rates = {
                        c.rate_name: round(c.value, 1)
                        for c in result.classifications
                        if c.rate_name in _MAIN_CLINICAL_RATES and c.value is not None
                    }
            except Exception as e:
                logger.warning("Clinical analysis failed for hospital %s: %s", h.name, e)

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
            # Run the analysis even when values are empty: every rate comes back None
            # (= no data) so the UI shows an explicit "N/A" marker instead of an
            # empty chart.
            from app.engine.clinical import run_clinical_analysis
            result = run_clinical_analysis(hospital=hospital.name, month=latest_month,
                                           values=values, include_ai=False)
            for c in result.classifications:
                if c.rate_name in _MAIN_CLINICAL_RATES:
                    # Keep None as None (missing denominator = no data) instead of
                    # flattening to 0, so the UI can distinguish "reported zero"
                    # from "no data available".
                    clinical_rates.append({
                        "rate_name": c.rate_name,
                        "value": round(c.value, 1) if c.value is not None else None,
                        "unit": c.unit,
                        "classification": c.classification,
                    })
        except Exception as e:
            logger.warning("Clinical analysis failed for hospital %s: %s", hospital_id, e)

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
                    pr = rca_peer(hospital=ph.name, month=latest_month, values=pv, include_ai=False)
                except Exception as e:
                    logger.debug("Peer clinical analysis failed for %s: %s", ph.name, e)
                    continue
                for c in pr.classifications:
                    if c.rate_name in peer_rate_vals and c.value is not None:
                        peer_rate_vals[c.rate_name].append(c.value)
            for r in clinical_rates:
                vals = peer_rate_vals.get(r["rate_name"], [])
                r["peer_avg"] = round(sum(vals) / len(vals), 1) if vals else None
        except Exception as e:
            logger.warning("Peer comparison failed for hospital %s: %s", hospital_id, e)

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


@router.get("/component-diagnostics")
def component_diagnostics(
    hospital_id: int | None = None,
    month_from: str | None = None,
    month_to: str | None = None,
    year: str | None = None,
    metric: str | None = None,
    db: Session = Depends(get_db),
):
    """Detailed per-component diagnostics with causes, impact, and monthly history.
    If metric is specified (e.g. completeness, rule_compliance), return only that component."""
    from app.api.analysis import get_enabled_months
    from app.models import Indicator, IndicatorValue, HospitalIndicatorConfig
    enabled_months = get_enabled_months(db, hospital_id=hospital_id)

    base = db.query(QualityScore)
    if hospital_id:
        base = base.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        base = base.filter(QualityScore.month >= month_from)
    if month_to:
        base = base.filter(QualityScore.month <= month_to)
    elif enabled_months:
        base = base.filter(QualityScore.month.in_(enabled_months))
    if year:
        base = base.filter(QualityScore.month.like(f"{year}-%"))

    scores = base.order_by(QualityScore.month.asc()).all()
    if not scores:
        return {"components": [], "trend": []}

    n = len(scores)

    # Full trend array
    trend = []
    for s in scores:
        trend.append({
            "month": s.month,
            "rule_compliance": round(float(s.rule_compliance or 0), 1),
            "completeness": round(float(s.completeness or 0), 1),
            "consistency": round(float(s.consistency or 0), 1),
            "outlier_score": round(max(0, 100 - (s.outlier_penalty or 0)), 1),
            "score": round(float(s.score or 0), 1),
        })

    # Targets
    targets = {"rule_compliance": 85, "completeness": 90, "consistency": 85, "outlier_score": 90}
    try:
        from app.models import SystemConfig
        cfg = db.query(SystemConfig).all()
        cfg_map = {c.key: c.value for c in cfg}
        if "quality_rule_compliance" in cfg_map:
            targets["rule_compliance"] = round(float(cfg_map.get("quality_rule_compliance", 0.35)) * 100)
        if "quality_completeness" in cfg_map:
            targets["completeness"] = round(float(cfg_map.get("quality_completeness", 0.25)) * 100)
        if "quality_consistency" in cfg_map:
            targets["consistency"] = round(float(cfg_map.get("quality_consistency", 0.25)) * 100)
    except Exception:
        pass

    def _direction(vals):
        if len(vals) < 2:
            return "stable"
        recent = vals[-2:]
        if recent[-1] > recent[0] + 2:
            return "improving"
        elif recent[-1] < recent[0] - 2:
            return "declining"
        return "stable"

    def _first_bad(vals, threshold):
        for i, v in enumerate(vals):
            if v < threshold:
                return i
        return -1

    def _stdev(vals):
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        return round((sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5, 1)

    # Rule Compliance
    rc_vals = [round(float(s.rule_compliance or 0), 1) for s in scores]
    rc_months = [{"month": scores[i].month, "value": rc_vals[i]} for i in range(n)]
    avg_rc = round(sum(rc_vals) / n, 1)
    rc_first_bad = _first_bad(rc_vals, targets["rule_compliance"])
    rc_causes = []
    rc_bad_count = sum(1 for v in rc_vals if v < targets["rule_compliance"])
    rc_bad_avg = round(sum(v for v in rc_vals if v < targets["rule_compliance"]) / max(rc_bad_count, 1), 1) if rc_bad_count else 0
    if rc_bad_count > 0:
        impact = round((targets["rule_compliance"] - rc_bad_avg) * rc_bad_count / n, 1)
        rc_causes.append({
            "cause": "Rule validation failures",
            "detail": f"{rc_bad_count}/{n} months below {targets['rule_compliance']}% target",
            "severity": "critical" if rc_bad_avg < 60 else "warning",
            "impact_pct": impact,
            "first_month": scores[rc_first_bad].month if rc_first_bad >= 0 else None,
        })
    if _direction(rc_vals) == "declining":
        rc_causes.append({"cause": "Declining trend", "detail": "Recent months show decreasing compliance", "severity": "warning", "impact_pct": round(targets["rule_compliance"] - avg_rc, 1) * 0.3})
    if not rc_causes:
        rc_causes.append({"cause": "All rules passing", "detail": f"Average {avg_rc}% across {n} months", "severity": "ok", "impact_pct": 0})

    # Completeness
    cp_vals = [round(float(s.completeness or 0), 1) for s in scores]
    cp_months = [{"month": scores[i].month, "value": cp_vals[i]} for i in range(n)]
    avg_cp = round(sum(cp_vals) / n, 1)
    cp_first_bad = _first_bad(cp_vals, targets["completeness"])
    cp_causes = []
    cp_critical_count = sum(1 for v in cp_vals if v < 50)
    cp_warn_count = sum(1 for v in cp_vals if 50 <= v < targets["completeness"])

    # Find specific missing indicators per month for the worst months
    cp_missing_details = []
    if hospital_id:
        try:
            # Get all enabled indicators for this hospital
            enabled_ind_ids = [c.indicator_id for c in db.query(HospitalIndicatorConfig).filter(
                HospitalIndicatorConfig.hospital_id == hospital_id,
                HospitalIndicatorConfig.is_enabled.is_(True)
            ).all()]
            all_indicators = {i.id: i.name for i in db.query(Indicator).filter(Indicator.id.in_(enabled_ind_ids)).all()} if enabled_indicators else {}

            # For each month, find which indicators have no value
            for i, s in enumerate(scores):
                month_vals = db.query(IndicatorValue.indicator_id, IndicatorValue.value).filter(
                    IndicatorValue.hospital_id == hospital_id,
                    IndicatorValue.month == s.month,
                    IndicatorValue.indicator_id.in_(enabled_ind_ids)
                ).all()
                filled_ids = {iv.indicator_id for iv in month_vals if iv.value is not None}
                missing_ids = set(enabled_ind_ids) - filled_ids
                if missing_ids and cp_vals[i] < targets["completeness"]:
                    missing_names = [all_indicators.get(mid, f"Indicator #{mid}") for mid in sorted(missing_ids)]
                    cp_missing_details.append({
                        "month": s.month,
                        "value": cp_vals[i],
                        "missing_count": len(missing_names),
                        "missing_indicators": missing_names[:10],  # cap at 10
                    })
        except Exception:
            pass

    if cp_critical_count > 0:
        # Build detail text with missing indicator names
        worst_detail = ""
        if cp_missing_details:
            worst = min(cp_missing_details, key=lambda x: x["value"])
            worst_detail = f" — Worst: {worst['month']} ({worst['value']}%), missing: " + ", ".join(worst["missing_indicators"][:5])
        cp_causes.append({
            "cause": "Severely missing indicator data",
            "detail": f"{cp_critical_count}/{n} months below 50% — most indicators empty" + worst_detail,
            "severity": "critical",
            "impact_pct": round(sum(targets["completeness"] - v for v in cp_vals if v < 50) / n, 1),
            "first_month": scores[_first_bad(cp_vals, 50)].month if _first_bad(cp_vals, 50) >= 0 else None,
        })
    if cp_warn_count > 0:
        remaining = [v for v in cp_vals if 50 <= v < targets["completeness"]]
        warn_detail = ""
        if cp_missing_details:
            # Show indicators missing in most warn-level months
            from collections import Counter
            all_missing = []
            for md in cp_missing_details:
                if md["value"] >= 50:
                    all_missing.extend(md["missing_indicators"])
            if all_missing:
                common = Counter(all_missing).most_common(5)
                warn_detail = " — Common gaps: " + ", ".join(f"{name} ({cnt}x)" for name, cnt in common)
        cp_causes.append({
            "cause": "Partial indicator gaps",
            "detail": f"{cp_warn_count}/{n} months between 50-{targets['completeness']}%" + warn_detail,
            "severity": "warning",
            "impact_pct": round(sum(targets["completeness"] - v for v in remaining) / n, 1),
            "first_month": scores[cp_first_bad].month if cp_first_bad >= 0 else None,
        })
    if not cp_causes:
        cp_causes.append({"cause": "All indicators reported", "detail": f"Average {avg_cp}% — data coverage is good", "severity": "ok", "impact_pct": 0})

    # Consistency
    co_vals = [round(float(s.consistency or 0), 1) for s in scores]
    co_months = [{"month": scores[i].month, "value": co_vals[i]} for i in range(n)]
    avg_co = round(sum(co_vals) / n, 1)
    co_stdev = _stdev(co_vals)
    co_first_bad = _first_bad(co_vals, targets["consistency"])
    co_causes = []
    co_bad_count = sum(1 for v in co_vals if v < targets["consistency"])
    if co_stdev > 10:
        co_causes.append({
            "cause": "High score volatility",
            "detail": f"Standard deviation {co_stdev} — scores fluctuate significantly month-to-month",
            "severity": "warning",
            "impact_pct": round(co_stdev * 0.8, 1),
            "first_month": scores[co_first_bad].month if co_first_bad >= 0 else None,
        })
    if co_bad_count > 0:
        co_causes.append({
            "cause": "Inconsistent rule outcomes",
            "detail": f"{co_bad_count}/{n} months below {targets['consistency']}% target",
            "severity": "critical" if avg_co < 70 else "warning",
            "impact_pct": round(sum(targets["consistency"] - v for v in co_vals if v < targets["consistency"]) / n, 1),
            "first_month": scores[co_first_bad].month if co_first_bad >= 0 else None,
        })
    if not co_causes:
        co_causes.append({"cause": "Stable and consistent", "detail": f"Average {avg_co}% — low variance (std={co_stdev})", "severity": "ok", "impact_pct": 0})

    # Outlier Score
    op_vals = [round(max(0, 100 - (s.outlier_penalty or 0)), 1) for s in scores]
    op_months = [{"month": scores[i].month, "value": op_vals[i]} for i in range(n)]
    avg_op = round(sum(op_vals) / n, 1)
    op_first_bad = _first_bad(op_vals, targets["outlier_score"])
    op_causes = []
    op_bad_count = sum(1 for v in op_vals if v < targets["outlier_score"])
    op_severe = sum(1 for v in op_vals if v < 60)
    if op_severe > 0:
        op_causes.append({
            "cause": "Severe outlier penalties",
            "detail": f"{op_severe}/{n} months with score < 60 — extreme anomalies detected",
            "severity": "critical",
            "impact_pct": round(sum(targets["outlier_score"] - v for v in op_vals if v < 60) / n, 1),
            "first_month": scores[_first_bad(op_vals, 60)].month if _first_bad(op_vals, 60) >= 0 else None,
        })
    elif op_bad_count > 0:
        op_causes.append({
            "cause": "Moderate outlier penalties",
            "detail": f"{op_bad_count}/{n} months below {targets['outlier_score']}% target",
            "severity": "warning",
            "impact_pct": round(sum(targets["outlier_score"] - v for v in op_vals if v < targets["outlier_score"]) / n, 1),
            "first_month": scores[op_first_bad].month if op_first_bad >= 0 else None,
        })
    if not op_causes:
        op_causes.append({"cause": "No significant outliers", "detail": f"Average {avg_op}% — data within normal range", "severity": "ok", "impact_pct": 0})

    def _build(name, key, avg, vals, months, direction, causes, target):
        gap = round(max(0, target - avg), 1)
        min_val = min(vals) if vals else 0
        max_val = max(vals) if vals else 0
        worst_idx = vals.index(min_val) if vals else 0
        return {
            "name": name, "key": key, "avg": avg, "target": target, "gap": gap,
            "min": min_val, "max": max_val, "range": round(max_val - min_val, 1),
            "direction": direction,
            "worst_month": scores[worst_idx].month if scores else None,
            "causes": causes, "monthly": months,
        }

    components = [
        _build("Rule Compliance", "rule_compliance", avg_rc, rc_vals, rc_months, _direction(rc_vals), rc_causes, targets["rule_compliance"]),
        _build("Completeness", "completeness", avg_cp, cp_vals, cp_months, _direction(cp_vals), cp_causes, targets["completeness"]),
        _build("Consistency", "consistency", avg_co, co_vals, co_months, _direction(co_vals), co_causes, targets["consistency"]),
        _build("Outlier Score", "outlier_score", avg_op, op_vals, op_months, _direction(op_vals), op_causes, targets["outlier_score"]),
    ]
    # Filter by metric if specified
    if metric:
        components = [c for c in components if c["key"] == metric]

    return {"components": components, "trend": trend}
