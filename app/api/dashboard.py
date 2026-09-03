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


# ── Shared helper: recalculate completeness (batch-optimized) ──
def _recalc_completeness(db, scores):
    """Recalculate completeness for QualityScore objects using batch pre-fetching.
    Replaces N+1 queries with ~4 batch queries + in-memory lookups."""
    from app.models import Indicator as _RI, IndicatorValue as _RIV, HospitalIndicatorConfig as _HIC, SystemSetting
    if not scores:
        return []
    # 1. Pre-fetch all indicators ONCE
    all_ids = [i.id for i in db.query(_RI.id).all()]
    # 2. Collect unique (hospital, month) pairs
    hosp_months = list(set((s.hospital_id, s.month) for s in scores))
    all_hids = list(set(h[0] for h in hosp_months))
    all_months = list(set(h[1] for h in hosp_months))
    # 3. Pre-fetch ALL indicator values in ONE query
    iv_rows = db.query(_RIV.hospital_id, _RIV.month, _RIV.indicator_id, _RIV.value).filter(
        _RIV.hospital_id.in_(all_hids), _RIV.month.in_(all_months)
    ).all()
    iv_index = {}  # {(hid, month): {ind_id: value}}
    for row in iv_rows:
        key = (row[0], row[1])
        if key not in iv_index:
            iv_index[key] = {}
        iv_index[key][row[2]] = row[3]
    # 4. Pre-fetch ALL manually disabled indicators in ONE query
    manual_rows = db.query(_HIC.hospital_id, _HIC.indicator_id).filter(
        _HIC.is_enabled.is_(False), _HIC.hospital_id.in_(all_hids)
    ).all()
    manual_map = {}  # {hid: set(ind_ids)}
    for row in manual_rows:
        manual_map.setdefault(row[0], set()).add(row[1])
    # 5. Read auto-disable setting ONCE
    auto_disable = False
    try:
        ads = db.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
        auto_disable = ads is not None and ads.value == "true"
    except Exception:
        pass
    # 6. Compute disabled set for (hid, month) in memory
    def _dis(hid, month):
        d = set(manual_map.get(hid, ()))
        if auto_disable:
            ivm = iv_index.get((hid, month), {})
            for iid in all_ids:
                if iid not in ivm or ivm[iid] is None:
                    d.add(iid)
        return d
    # 7. Compute completeness for each score
    result = []
    for s in scores:
        try:
            dis = _dis(s.hospital_id, s.month)
            en = [iid for iid in all_ids if iid not in dis]
            if not en:
                result.append(float(s.completeness or 0))
                continue
            ivm = iv_index.get((s.hospital_id, s.month), {})
            filled = sum(1 for iid in en if ivm.get(iid) is not None)
            result.append(filled / len(en) * 100)
        except Exception:
            result.append(float(s.completeness or 0))
    return result


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
    # Recalculate radar completeness with current disabled indicators
    _radar_q = db.query(QualityScore)
    if hospital_id:
        _radar_q = _radar_q.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        _radar_q = _radar_q.filter(QualityScore.month >= month_from)
    if month_to:
        _radar_q = _radar_q.filter(QualityScore.month <= month_to)
    elif enabled_months:
        _radar_q = _radar_q.filter(QualityScore.month.in_(enabled_months))
    if year:
        _radar_q = _radar_q.filter(QualityScore.month.like(f"{year}-%"))
    _radar_scores = _radar_q.all()
    _radar_cp = _recalc_completeness(db, _radar_scores)
    _radar_cp_avg = round(sum(_radar_cp) / len(_radar_cp), 1) if _radar_cp else 0
    radar_components = {
        "Validation rule": round(float(radar_row.rule_compliance or 0), 1),
        "Completeness": _radar_cp_avg,
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
        func.avg(QualityScore.consistency).label("avg_consistency"),
    ).first()

    avg_score = round(float(agg.avg_score or 0), 1)
    avg_compliance = round(float(agg.avg_compliance or 0), 1)
    avg_consistency = round(float(agg.avg_consistency or 0), 1)

    # Recalculate completeness using current disabled indicator set
    _kpi_scores = base.all()
    _kpi_cp = _recalc_completeness(db, _kpi_scores)
    avg_completeness = round(sum(_kpi_cp) / len(_kpi_cp), 1) if _kpi_cp else 0

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

    # Outlier score (lower penalty = better)
    _op_q = base.with_entities(func.avg(QualityScore.outlier_penalty).label("avg_op")).first()
    outlier_penalty = round(float(_op_q.avg_op or 0), 1)

    report_count = base.count()

    kpis = [
        {"id": "quality_score", "label": "Quality Score", "value": avg_score,
         "target": 80, "unit": "%", "higher_is_better": True},
        {"id": "rule_compliance", "label": "Validation rule", "value": avg_compliance,
         "target": 85, "unit": "%", "higher_is_better": True},
        {"id": "completeness", "label": "Completeness", "value": avg_completeness,
         "target": 90, "unit": "%", "higher_is_better": True},
        {"id": "consistency", "label": "Consistency", "value": avg_consistency,
         "target": 85, "unit": "%", "higher_is_better": True},
        {"id": "conf_high", "label": "High Confidence", "value": conf_high_pct,
         "target": 60, "unit": "%", "higher_is_better": True},
        {"id": "outlier_score", "label": "Outlier Score", "value": 100 - outlier_penalty,
         "target": 90, "unit": "%", "higher_is_better": True},
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
        avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1)

        # Recalculate completeness using current disabled indicator set
        _cp_vals = _recalc_completeness(db, scores)
        avg_completeness = round(sum(_cp_vals) / len(_cp_vals), 1) if _cp_vals else 0

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
            "rule_compliance": avg_compliance,
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
    avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1) if scores else 0

    # Recalculate completeness using current disabled indicator set
    _pcp = _recalc_completeness(db, scores)
    avg_completeness = round(sum(_pcp) / len(_pcp), 1) if _pcp else 0

    # Confidence high %
    from app.models import ConfidenceScore as _CS
    conf_q = db.query(_CS).filter(_CS.hospital_id == hospital_id).all()
    if conf_q:
        high_count = sum(c.high_count or 0 for c in conf_q)
        total_indicators = sum(c.indicator_count or 0 for c in conf_q)
        avg_confidence = round(high_count / total_indicators * 100, 1) if total_indicators > 0 else 0
    else:
        avg_confidence = 0

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
        "avg_confidence": avg_confidence,
        "quality_trend": quality_trend, "clinical_rates": clinical_rates,
        "total_alerts": total_alerts, "last_alerts": last_alerts,
    }


@router.post("/recalculate-completeness")
def recalculate_completeness(db: Session = Depends(get_db)):
    """Bulk recalculate completeness for all quality_scores (batch-optimized)."""
    from app.models import Indicator, IndicatorValue as _IV, HospitalIndicatorConfig as _HIC, SystemSetting, SystemConfig
    # Pre-fetch all data in batch
    all_ind_ids = [i.id for i in db.query(Indicator.id).all()]
    scores = db.query(QualityScore).all()
    if not scores:
        return {"updated": 0, "total": 0}
    all_hids = list(set(s.hospital_id for s in scores))
    all_months = list(set(s.month for s in scores))
    # Batch fetch indicator values
    iv_rows = db.query(_IV.hospital_id, _IV.month, _IV.indicator_id, _IV.value).filter(
        _IV.hospital_id.in_(all_hids), _IV.month.in_(all_months)
    ).all()
    iv_index = {}
    for row in iv_rows:
        key = (row[0], row[1])
        if key not in iv_index:
            iv_index[key] = {}
        iv_index[key][row[2]] = row[3]
    # Batch fetch disabled indicators
    manual_rows = db.query(_HIC.hospital_id, _HIC.indicator_id).filter(
        _HIC.is_enabled.is_(False), _HIC.hospital_id.in_(all_hids)
    ).all()
    manual_map = {}
    for row in manual_rows:
        manual_map.setdefault(row[0], set()).add(row[1])
    auto_disable = False
    try:
        ads = db.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
        auto_disable = ads is not None and ads.value == "true"
    except Exception:
        pass
    # Pre-fetch weights
    try:
        cfg_rows = db.query(SystemConfig).all()
        cfg_map = {c.key: c.value for c in cfg_rows}
        w_rc = float(cfg_map.get("quality_rule_compliance", "0.35"))
        w_cp = float(cfg_map.get("quality_completeness", "0.25"))
        w_co = float(cfg_map.get("quality_consistency", "0.25"))
        w_op = float(cfg_map.get("quality_outlier_penalty", "0.15"))
    except Exception:
        w_rc, w_cp, w_co, w_op = 0.35, 0.25, 0.25, 0.15
    updated = 0
    for s in scores:
        try:
            # Compute disabled set in memory
            dis = set(manual_map.get(s.hospital_id, ()))
            if auto_disable:
                ivm = iv_index.get((s.hospital_id, s.month), {})
                for iid in all_ind_ids:
                    if iid not in dis and (iid not in ivm or ivm[iid] is None):
                        dis.add(iid)
            enabled_ids = [iid for iid in all_ind_ids if iid not in dis]
            if not enabled_ids:
                continue
            ivm = iv_index.get((s.hospital_id, s.month), {})
            filled = sum(1 for iid in enabled_ids if ivm.get(iid) is not None)
            new_cp = round(filled / len(enabled_ids) * 100, 1)
            s.completeness = new_cp
            rc = float(s.rule_compliance or 0) / 100
            cp = new_cp / 100
            co = float(s.consistency or 0) / 100
            op = float(s.outlier_penalty or 0) / 100
            new_score = max(0, min(100, round((rc * w_rc + cp * w_cp + co * w_co + (1.0 - op) * w_op) * 100, 1)))
            s.score = new_score
            updated += 1
        except Exception:
            pass

    db.commit()
    return {"updated": updated, "total": len(scores)}


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

    # Full trend array — aggregate by month (completeness recalculated)
    from collections import defaultdict
    trend_buckets = defaultdict(lambda: {"rc": [], "cp": [], "co": [], "op": [], "sc": []})
    _trend_cp = _recalc_completeness(db, scores)
    for i, s in enumerate(scores):
        b = trend_buckets[s.month]
        b["rc"].append(float(s.rule_compliance or 0))
        b["cp"].append(_trend_cp[i])
        b["co"].append(float(s.consistency or 0))
        b["op"].append(max(0, 100 - (s.outlier_penalty or 0)))
        b["sc"].append(float(s.score or 0))
    trend = []
    for month in sorted(trend_buckets.keys()):
        b = trend_buckets[month]
        trend.append({
            "month": month,
            "rule_compliance": round(sum(b["rc"]) / len(b["rc"]), 1),
            "completeness": round(sum(b["cp"]) / len(b["cp"]), 1),
            "consistency": round(sum(b["co"]) / len(b["co"]), 1),
            "outlier_score": round(sum(b["op"]) / len(b["op"]), 1),
            "score": round(sum(b["sc"]) / len(b["sc"]), 1),
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
    rc_by_month = {}
    for i in range(n):
        m = scores[i].month
        rc_by_month.setdefault(m, []).append(rc_vals[i])
    rc_months = [{"month": m, "value": round(sum(vs)/len(vs), 1)} for m, vs in sorted(rc_by_month.items())]
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

    # Completeness — batch-optimized: pre-fetch all data in one pass
    from app.engine.pipeline import get_disabled_indicator_ids as _get_disabled
    from app.models import HospitalIndicatorConfig as _HIC
    # Pre-fetch all indicators once
    all_ind_ids = [i.id for i in db.query(Indicator.id).all()]
    all_ind_names_map = {i.id: i.name for i in db.query(Indicator).all()}
    # Pre-fetch ALL indicator values for this query in one batch
    hosp_months = [(s.hospital_id, s.month) for s in scores]
    all_hosp_ids = list(set(h[0] for h in hosp_months))
    all_months = list(set(h[1] for h in hosp_months))
    all_iv_rows = db.query(IndicatorValue.hospital_id, IndicatorValue.month,
                           IndicatorValue.indicator_id, IndicatorValue.value).filter(
        IndicatorValue.hospital_id.in_(all_hosp_ids),
        IndicatorValue.month.in_(all_months)
    ).all()
    # Index: {(hospital_id, month): {indicator_id: value}}
    iv_index = {}
    for row in all_iv_rows:
        key = (row[0], row[1])
        if key not in iv_index:
            iv_index[key] = {}
        iv_index[key][row[2]] = row[3]
    # Pre-fetch manually disabled indicators for all hospitals
    manual_disabled = db.query(_HIC.hospital_id, _HIC.indicator_id).filter(
        _HIC.is_enabled.is_(False),
        _HIC.hospital_id.in_(all_hosp_ids)
    ).all()
    manual_disabled_map = {}  # {hospital_id: set(indicator_ids)}
    for row in manual_disabled:
        if row[0] not in manual_disabled_map:
            manual_disabled_map[row[0]] = set()
        manual_disabled_map[row[0]].add(row[1])
    # Pre-fetch auto-disable setting
    try:
        auto_disable_setting = db.query(SystemSetting).filter(
            SystemSetting.key == "auto_disable_null_indicators"
        ).first()
        auto_disable = auto_disable_setting and auto_disable_setting.value == "true"
    except Exception:
        auto_disable = False
    # Compute disabled sets per (hospital, month) in memory
    def _fast_disabled(hid, month):
        disabled = set(manual_disabled_map.get(hid, set()))
        if auto_disable:
            iv_map = iv_index.get((hid, month), {})
            for ind_id in all_ind_ids:
                if ind_id not in iv_map or iv_map[ind_id] is None:
                    disabled.add(ind_id)
        return disabled
    # Compute completeness for each score
    cp_vals = []
    for s in scores:
        try:
            disabled = _fast_disabled(s.hospital_id, s.month)
            enabled_ids = [iid for iid in all_ind_ids if iid not in disabled]
            if not enabled_ids:
                cp_vals.append(round(float(s.completeness or 0), 1))
                continue
            iv_map = iv_index.get((s.hospital_id, s.month), {})
            filled = sum(1 for iid in enabled_ids if iv_map.get(iid) is not None)
            cp_vals.append(round(filled / len(enabled_ids) * 100, 1))
        except Exception:
            cp_vals.append(round(float(s.completeness or 0), 1))
    cp_by_month = {}
    for i in range(n):
        m = scores[i].month
        cp_by_month.setdefault(m, []).append(cp_vals[i])
    cp_months = [{"month": m, "value": round(sum(vs)/len(vs), 1)} for m, vs in sorted(cp_by_month.items())]
    avg_cp = round(sum(cp_vals) / n, 1)
    cp_first_bad = _first_bad(cp_vals, targets["completeness"])
    cp_causes = []
    cp_critical_count = sum(1 for v in cp_vals if v < 50)
    cp_warn_count = sum(1 for v in cp_vals if 50 <= v < targets["completeness"])

    # Find specific missing indicators per month
    cp_missing_details = []
    try:
        from collections import Counter

        if hospital_id:
            # Single hospital: find indicators that SHOULD have values but don't (uses pre-fetched data)
            for i, s in enumerate(scores):
                disabled_ids = _fast_disabled(hospital_id, s.month)
                enabled_for_month = set(all_ind_ids) - disabled_ids
                iv_map = iv_index.get((hospital_id, s.month), {})
                filled_ids = {iid for iid in enabled_for_month if iv_map.get(iid) is not None}
                truly_missing = enabled_for_month - filled_ids
                if truly_missing and cp_vals[i] < targets["completeness"]:
                    missing_names = [all_ind_names_map.get(mid, f"Indicator #{mid}") for mid in sorted(truly_missing)]
                    cp_missing_details.append({
                        "month": s.month,
                        "value": cp_vals[i],
                        "missing_count": len(missing_names),
                        "missing_indicators": missing_names[:10],
                    })
        else:
            # All hospitals: use pre-fetched iv_index to count per indicator
            hosp_ids = list(set(h[0] for h in hosp_months))
            distinct_months = sorted(set(s.month for s in scores))
            for month in distinct_months:
                ind_hospital_count = Counter()
                for hid in hosp_ids:
                    iv_map = iv_index.get((hid, month), {})
                    for iid, val in iv_map.items():
                        if val is not None:
                            ind_hospital_count[iid] += 1
                # Only show indicators that SOME hospitals have but others don't
                # (not universally disabled)
                partially_missing = {}
                for mid in all_ind_ids:
                    count = ind_hospital_count.get(mid, 0)
                    if 0 < count < len(hosp_ids):
                        partially_missing[mid] = len(hosp_ids) - count
                if partially_missing:
                    month_cp_vals = [cp_vals[i] for i in range(n) if scores[i].month == month]
                    month_avg = sum(month_cp_vals) / len(month_cp_vals) if month_cp_vals else 0
                    if month_avg < targets["completeness"]:
                        sorted_missing = sorted(partially_missing.items(), key=lambda x: -x[1])
                        missing_names = [all_ind_names_map.get(mid, f"Indicator #{mid}") for mid, cnt in sorted_missing[:10]]
                        cp_missing_details.append({
                            "month": month,
                            "value": round(month_avg, 1),
                            "missing_count": sum(partially_missing.values()),
                            "missing_indicators": missing_names,
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
    co_by_month = {}
    for i in range(n):
        m = scores[i].month
        co_by_month.setdefault(m, []).append(co_vals[i])
    co_months = [{"month": m, "value": round(sum(vs)/len(vs), 1)} for m, vs in sorted(co_by_month.items())]
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
    op_by_month = {}
    for i in range(n):
        m = scores[i].month
        op_by_month.setdefault(m, []).append(op_vals[i])
    op_months = [{"month": m, "value": round(sum(vs)/len(vs), 1)} for m, vs in sorted(op_by_month.items())]
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

    # ── Per-hospital detail for each cause ──
    _cause_hospitals = {}
    try:
        all_hosp = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
        hosp_names = {h.id: h.name for h in all_hosp}

        # ── Completeness ──
        _cp_cause_hosp = {}
        for cause in cp_causes:
            _cp_cause_hosp[cause["cause"]] = []
        for s in scores:
            hid = s.hospital_id
            idx = scores.index(s)
            cp_val = cp_vals[idx]
            if cp_val >= targets["completeness"]:
                continue
            # Find missing indicators (uses pre-fetched data)
            missing_names = []
            try:
                disabled_ids = _fast_disabled(hid, s.month)
                enabled_ids = [iid for iid in all_ind_ids if iid not in disabled_ids]
                iv_map = iv_index.get((hid, s.month), {})
                filled_ids = {iid for iid in enabled_ids if iv_map.get(iid) is not None}
                missing_ids = set(enabled_ids) - filled_ids
                missing_names = [all_ind_names_map.get(mid, f"Indicator #{mid}") for mid in sorted(missing_ids)][:10]
            except Exception:
                pass
            # Find which cause this hospital belongs to
            if cp_val < 50:
                for cause in cp_causes:
                    if cause["cause"] == "Severely missing indicator data":
                        _cp_cause_hosp["Severely missing indicator data"].append({
                            "hospital_id": hid, "hospital_name": hosp_names.get(hid, f"#{hid}"),
                            "value": cp_val, "month": s.month,
                            "missing_indicators": missing_names,
                        })
            elif cp_val < targets["completeness"]:
                for cause in cp_causes:
                    if cause["cause"] == "Partial indicator gaps":
                        _cp_cause_hosp["Partial indicator gaps"].append({
                            "hospital_id": hid, "hospital_name": hosp_names.get(hid, f"#{hid}"),
                            "value": cp_val, "month": s.month,
                            "missing_indicators": missing_names,
                        })
        # Aggregate by hospital: group rows, collect unique months and indicators
        for cause_key in _cp_cause_hosp:
            rows = _cp_cause_hosp[cause_key]
            hosp_agg = {}
            for r in rows:
                hkey = r["hospital_id"]
                if hkey not in hosp_agg:
                    hosp_agg[hkey] = {"hospital_id": hkey, "hospital_name": r["hospital_name"],
                                       "problem_months": [], "missing_indicators": set(), "values": []}
                hosp_agg[hkey]["problem_months"].append(r["month"])
                hosp_agg[hkey]["values"].append(r["value"])
                hosp_agg[hkey]["missing_indicators"].update(r["missing_indicators"])
            result_list = []
            for hkey, ha in hosp_agg.items():
                result_list.append({
                    "hospital_id": ha["hospital_id"],
                    "hospital_name": ha["hospital_name"],
                    "avg_value": round(sum(ha["values"]) / len(ha["values"]), 1),
                    "missing_indicators": sorted(list(ha["missing_indicators"]))[:10],
                    "problem_months": sorted(set(ha["problem_months"])),
                })
            result_list.sort(key=lambda x: x["avg_value"])
            _cp_cause_hosp[cause_key] = result_list
        _cause_hospitals["completeness"] = _cp_cause_hosp

        # ── Rule Compliance ──
        # Pre-fetch rule results for affected hospitals
        _rule_results_map = {}  # {(hospital_id, month): [rule_code, ...]}
        _rule_desc_map = {}  # {rule_code: {severity, description}}
        try:
            from app.models import ValidationResult as _VR, Rule as _Rule
            # Fetch failed rule codes with severity/description
            vr_q = db.query(_VR.hospital_id, _VR.month, _VR.rule_code).filter(
                _VR.status == "FAIL",
                _VR.hospital_id.in_(all_hosp_ids),
                _VR.month.in_(all_months)
            ).all()
            for row in vr_q:
                key = (row[0], row[1])
                if key not in _rule_results_map:
                    _rule_results_map[key] = []
                _rule_results_map[key].append(row[2])
            # Fetch rule descriptions for display
            all_codes = set()
            for codes in _rule_results_map.values():
                all_codes.update(codes)
            if all_codes:
                rules_q = db.query(_Rule.code, _Rule.severity, _Rule.description).filter(
                    _Rule.code.in_(all_codes)
                ).all()
                for rr in rules_q:
                    _rule_desc_map[rr[0]] = {"severity": rr[1] or "HIGH", "description": rr[2] or rr[0]}
        except Exception:
            pass
        # Build per-hospital rule failure data (always show even if on target)
        _rc_hosp_entries = []  # flat list of (hospital_id, month, val, hosp_name, failed_rules)
        for s in scores:
            val = round(float(s.rule_compliance or 0), 1)
            hosp_name = hosp_names.get(s.hospital_id, f"#{s.hospital_id}")
            failed_rules = _rule_results_map.get((s.hospital_id, s.month), [])
            if failed_rules:  # only include hospitals that actually have rule failures
                _rc_hosp_entries.append({
                    "hospital_id": s.hospital_id, "hospital_name": hosp_name,
                    "value": val, "month": s.month,
                    "failed_rules": failed_rules[:10],
                })
        # Group entries into cause buckets
        _rc_cause_hosp = {}
        for cause in rc_causes:
            _rc_cause_hosp[cause["cause"]] = []
        for entry in _rc_hosp_entries:
            val = entry["value"]
            if val < targets["rule_compliance"] - 15:
                cause_label = next((c["cause"] for c in rc_causes if c["severity"] == "critical"), rc_causes[0]["cause"] if rc_causes else None)
            elif val < targets["rule_compliance"]:
                cause_label = next((c["cause"] for c in rc_causes if c["severity"] == "warning"), rc_causes[0]["cause"] if rc_causes else None)
            else:
                cause_label = next((c["cause"] for c in rc_causes if c["severity"] == "ok"), None)
            if cause_label and cause_label in _rc_cause_hosp:
                _rc_cause_hosp[cause_label].append(entry)
        # Aggregate per hospital across months
        for cause_key in _rc_cause_hosp:
            rows = _rc_cause_hosp[cause_key]
            hosp_agg = {}
            for r in rows:
                hkey = r["hospital_id"]
                if hkey not in hosp_agg:
                    hosp_agg[hkey] = {"hospital_id": hkey, "hospital_name": r["hospital_name"],
                                       "problem_months": [], "values": [], "failed_rules_set": set()}
                hosp_agg[hkey]["problem_months"].append(r["month"])
                hosp_agg[hkey]["values"].append(r["value"])
                for fr in r.get("failed_rules", []):
                    hosp_agg[hkey]["failed_rules_set"].add(fr)
            result_list = []
            for hkey, ha in hosp_agg.items():
                enriched_rules = []
                for code in sorted(ha["failed_rules_set"]):
                    info = _rule_desc_map.get(code, {})
                    enriched_rules.append({
                        "code": code,
                        "severity": info.get("severity", "HIGH"),
                        "description": info.get("description", code),
                    })
                result_list.append({
                    "hospital_id": ha["hospital_id"],
                    "hospital_name": ha["hospital_name"],
                    "avg_value": round(sum(ha["values"]) / len(ha["values"]), 1),
                    "problem_months": sorted(set(ha["problem_months"])),
                    "failed_rules": enriched_rules,
                })
            result_list.sort(key=lambda x: x["avg_value"])
            _rc_cause_hosp[cause_key] = result_list
        _cause_hospitals["rule_compliance"] = _rc_cause_hosp

        # ── Consistency ──
        _co_cause_hosp = {}
        for cause in co_causes:
            _co_cause_hosp[cause["cause"]] = []
        for s in scores:
            val = round(float(s.consistency or 0), 1)
            if val >= targets["consistency"]:
                continue
            hosp_name = hosp_names.get(s.hospital_id, f"#{s.hospital_id}")
            for cause in co_causes:
                if cause["severity"] in ("critical", "warning"):
                    _co_cause_hosp[cause["cause"]].append({
                        "hospital_id": s.hospital_id, "hospital_name": hosp_name,
                        "value": val, "month": s.month,
                    })
        for cause_key in _co_cause_hosp:
            rows = _co_cause_hosp[cause_key]
            hosp_agg = {}
            for r in rows:
                hkey = r["hospital_id"]
                if hkey not in hosp_agg:
                    hosp_agg[hkey] = {"hospital_id": hkey, "hospital_name": r["hospital_name"],
                                       "problem_months": [], "values": []}
                hosp_agg[hkey]["problem_months"].append(r["month"])
                hosp_agg[hkey]["values"].append(r["value"])
            result_list = []
            for hkey, ha in hosp_agg.items():
                result_list.append({
                    "hospital_id": ha["hospital_id"],
                    "hospital_name": ha["hospital_name"],
                    "avg_value": round(sum(ha["values"]) / len(ha["values"]), 1),
                    "problem_months": sorted(set(ha["problem_months"])),
                })
            result_list.sort(key=lambda x: x["avg_value"])
            _co_cause_hosp[cause_key] = result_list
        _cause_hospitals["consistency"] = _co_cause_hosp

        # ── Outlier Score ──
        _op_cause_hosp = {}
        for cause in op_causes:
            _op_cause_hosp[cause["cause"]] = []
        for s in scores:
            val = round(max(0, 100 - (s.outlier_penalty or 0)), 1)
            if val >= targets["outlier_score"]:
                continue
            hosp_name = hosp_names.get(s.hospital_id, f"#{s.hospital_id}")
            for cause in op_causes:
                if cause["severity"] in ("critical", "warning"):
                    _op_cause_hosp[cause["cause"]].append({
                        "hospital_id": s.hospital_id, "hospital_name": hosp_name,
                        "value": val, "month": s.month,
                    })
        for cause_key in _op_cause_hosp:
            rows = _op_cause_hosp[cause_key]
            hosp_agg = {}
            for r in rows:
                hkey = r["hospital_id"]
                if hkey not in hosp_agg:
                    hosp_agg[hkey] = {"hospital_id": hkey, "hospital_name": r["hospital_name"],
                                       "problem_months": [], "values": []}
                hosp_agg[hkey]["problem_months"].append(r["month"])
                hosp_agg[hkey]["values"].append(r["value"])
            result_list = []
            for hkey, ha in hosp_agg.items():
                result_list.append({
                    "hospital_id": ha["hospital_id"],
                    "hospital_name": ha["hospital_name"],
                    "avg_value": round(sum(ha["values"]) / len(ha["values"]), 1),
                    "problem_months": sorted(set(ha["problem_months"])),
                })
            result_list.sort(key=lambda x: x["avg_value"])
            _op_cause_hosp[cause_key] = result_list
        _cause_hospitals["outlier_score"] = _op_cause_hosp

    except Exception:
        pass

    def _build(name, key, avg, vals, months, direction, causes, target):
        gap = round(max(0, target - avg), 1)
        min_val = min(vals) if vals else 0
        max_val = max(vals) if vals else 0
        worst_idx = vals.index(min_val) if vals else 0
        result = {
            "name": name, "key": key, "avg": avg, "target": target, "gap": gap,
            "min": min_val, "max": max_val, "range": round(max_val - min_val, 1),
            "direction": direction,
            "worst_month": scores[worst_idx].month if scores else None,
            "causes": causes, "monthly": months,
        }
        for cause in result["causes"]:
            cause["affected_hospitals"] = _cause_hospitals.get(key, {}).get(cause["cause"], [])
        return result

    components = [
        _build("Validation rule", "rule_compliance", avg_rc, rc_vals, rc_months, _direction(rc_vals), rc_causes, targets["rule_compliance"]),
        _build("Completeness", "completeness", avg_cp, cp_vals, cp_months, _direction(cp_vals), cp_causes, targets["completeness"]),
        _build("Consistency", "consistency", avg_co, co_vals, co_months, _direction(co_vals), co_causes, targets["consistency"]),
        _build("Outlier Score", "outlier_score", avg_op, op_vals, op_months, _direction(op_vals), op_causes, targets["outlier_score"]),
    ]
    # Filter by metric if specified
    if metric:
        components = [c for c in components if c["key"] == metric]

    # When a specific hospital is selected, build hospital-specific trend

    hosp_trend = []

    if hospital_id:

        hosp_scores = [s for s in scores if s.hospital_id == hospital_id]

        hosp_trend_buckets = defaultdict(lambda: {"rc": [], "cp": [], "co": [], "op": [], "sc": []})

        for s in hosp_scores:

            b = hosp_trend_buckets[s.month]

            b["rc"].append(float(s.rule_compliance or 0))

            b["co"].append(float(s.consistency or 0))

            b["op"].append(max(0, 100 - (s.outlier_penalty or 0)))

            b["sc"].append(float(s.score or 0))

        # Use recalculated completeness for this hospital

        hosp_cp = _recalc_completeness(db, hosp_scores)

        for i, s in enumerate(hosp_scores):

            hosp_trend_buckets[s.month]["cp"].append(hosp_cp[i])

        for month in sorted(hosp_trend_buckets.keys()):

            b = hosp_trend_buckets[month]

            hosp_trend.append({

                "month": month,

                "rule_compliance": round(sum(b["rc"]) / len(b["rc"]), 1),

                "completeness": round(sum(b["cp"]) / len(b["cp"]), 1),

                "consistency": round(sum(b["co"]) / len(b["co"]), 1),

                "outlier_score": round(sum(b["op"]) / len(b["op"]), 1),

                "score": round(sum(b["sc"]) / len(b["sc"]), 1),

            })

    return {"components": components, "trend": trend, "hosp_trend": hosp_trend}
