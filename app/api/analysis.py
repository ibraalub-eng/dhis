from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import case
from typing import List, Optional
import threading
from app.database import get_db, SessionLocal
from app.tasks import create_task, run_task
from app.cache import cache
from app.models import (
    Hospital, IndicatorValue, Indicator, QualityScore,
    AnomalyResult, ValidationResult, ConfidenceScore,
    HospitalIndicatorConfig,
)
from app.engine.pipeline import run_full_analysis, get_enabled_values_for_hospital_month, get_all_hospital_data_for_month
from app.engine.anomaly import detect_anomalies
from app.engine.anomaly import (
    analyze_historical_trends,
    compare_hospitals,
    detect_trend_anomalies,
    generate_historical_summary,
)
from app.engine.clinical import run_clinical_analysis
from pydantic import BaseModel
from app.schemas import (
    HistoricalAnalysisOut, HospitalComparisonOut,
)
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


class QualityTrendPoint(BaseModel):
    month: str
    score: float
    rule_compliance: Optional[float] = None
    completeness: Optional[float] = None
    consistency: Optional[float] = None
    outlier_penalty: Optional[float] = None
    issues_count: int = 0


class QualityTrendOut(BaseModel):
    hospital: str
    hospital_id: int
    data: List[QualityTrendPoint]
    current_score: Optional[float] = None
    previous_score: Optional[float] = None
    change: Optional[float] = None
    trend_direction: str = "stable"
    consecutive_declines: int = 0
    max_score: Optional[float] = None
    min_score: Optional[float] = None
    avg_score: Optional[float] = None


@router.get("/historical/{hospital_id}", response_model=HistoricalAnalysisOut)
def historical_analysis(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail=f"Hospital id {hospital_id} not found")

    rows = (
        db.query(IndicatorValue.month)
        .filter(IndicatorValue.hospital_id == hospital_id)
        .distinct()
        .order_by(IndicatorValue.month)
        .all()
    )
    months = sorted([r[0] for r in rows])
    if len(months) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 months of data for historical analysis")

    monthly_data = {}
    for m in months:
        vals = get_enabled_values_for_hospital_month(db, hospital_id, m)
        if vals:
            monthly_data[m] = vals

    if len(monthly_data) < 2:
        raise HTTPException(status_code=400, detail="Not enough data for historical analysis")

    trends = analyze_historical_trends(hospital.name, monthly_data)
    last_month = months[-1]

    all_hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    all_monthly_data = {}
    for h in all_hospitals:
        h_rows = (
            db.query(IndicatorValue.month)
            .filter(IndicatorValue.hospital_id == h.id)
            .distinct()
            .all()
        )
        h_months = sorted([r[0] for r in h_rows])
        h_data = {}
        for m in h_months:
            v = get_enabled_values_for_hospital_month(db, h.id, m)
            if v:
                h_data[m] = v
        if h_data:
            all_monthly_data[h.name] = h_data

    comparisons = compare_hospitals(all_monthly_data, last_month)
    cross_hospital_data = get_all_hospital_data_for_month(db, last_month)
    cross_anomalies = detect_anomalies(cross_hospital_data, hospital.name, last_month)
    trend_anomaly_results = detect_trend_anomalies(hospital.name, monthly_data)
    summary = generate_historical_summary(trends, comparisons, trend_anomaly_results, cross_anomalies)

    def _trend_to_dict(t):
        return {
            "hospital": t.hospital,
            "indicator_code": t.indicator_code,
            "rate_name": t.rate_name,
            "months": t.months,
            "values": t.values,
            "mean": t.mean,
            "std": t.std,
            "slope": t.slope,
            "slope_pct": t.slope_pct,
            "trend_direction": t.trend_direction,
            "trend_severity": t.trend_severity,
            "is_significant": t.is_significant,
            "cv": t.cv,
            "last_vs_mean_pct_change": t.last_vs_mean_pct_change,
            "consecutive_direction": t.consecutive_direction,
            "consecutive_count": t.consecutive_count,
            "findings": t.findings,
        }

    def _comparison_to_dict(c):
        return {
            "hospital": c.hospital,
            "indicator_code": c.indicator_code,
            "rate_name": c.rate_name,
            "value": c.value,
            "benchmark": c.benchmark,
            "deviation_pct": c.deviation_pct,
            "percentile_rank": c.percentile_rank,
            "comparison_label": c.comparison_label,
        }

    def _anomaly_to_dict(a):
        return {
            "indicator_code": a.indicator_code,
            "rate_name": a.rate_name,
            "value": round(a.value, 2) if a.value is not None else None,
            "benchmark": round(a.benchmark, 2) if a.benchmark is not None else None,
            "z_score": round(a.z_score, 2) if a.z_score is not None else None,
            "is_outlier": bool(a.is_outlier),
        }

    return HistoricalAnalysisOut(
        hospital=hospital.name,
        months_analyzed=months,
        trends=[_trend_to_dict(t) for t in trends],
        hospital_comparisons=[_comparison_to_dict(c) for c in comparisons],
        cross_hospital_anomalies=[_anomaly_to_dict(a) for a in cross_anomalies],
        trend_anomalies=[_anomaly_to_dict(a) for a in trend_anomaly_results],
        summary=summary,
    )


@router.get("/quality-trend/{hospital_id}")
def quality_trend(hospital_id: int, db: Session = Depends(get_db)):
    cache_key = cache.make_key("analysis:quality-trend", hospital_id=hospital_id)
    cached = cache.get(cache_key)
    if cached:
        return cached

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    scores = (
        db.query(QualityScore)
        .filter(QualityScore.hospital_id == hospital_id)
        .order_by(QualityScore.month)
        .all()
    )
    if not scores:
        return QualityTrendOut(hospital=hospital.name, hospital_id=hospital_id, data=[])

    data = []
    for s in scores:
        issues = []
        try:
            if s.issues:
                issues = json.loads(s.issues)
        except Exception:
            pass
        data.append(QualityTrendPoint(
            month=s.month,
            score=round(s.score, 1),
            rule_compliance=round(s.rule_compliance, 1) if s.rule_compliance is not None else None,
            completeness=round(s.completeness, 1) if s.completeness is not None else None,
            consistency=round(s.consistency, 1) if s.consistency is not None else None,
            outlier_penalty=round(s.outlier_penalty, 1) if s.outlier_penalty is not None else None,
            issues_count=len(issues),
        ))

    scores_only = [d.score for d in data]
    current_score = scores_only[-1] if scores_only else None
    previous_score = scores_only[-2] if len(scores_only) >= 2 else None
    change = round(current_score - previous_score, 1) if current_score is not None and previous_score is not None else None

    if len(scores_only) >= 2:
        slope = (scores_only[-1] - scores_only[0]) / len(scores_only)
        if slope > 1:
            trend_direction = "improving"
        elif slope < -1:
            trend_direction = "declining"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "stable"

    consecutive = 0
    for i in range(len(scores_only) - 1, 0, -1):
        if scores_only[i] < scores_only[i - 1]:
            consecutive += 1
        else:
            break

    max_score = max(scores_only) if scores_only else None
    min_score = min(scores_only) if scores_only else None
    avg_score = round(sum(scores_only) / len(scores_only), 1) if scores_only else None

    result = QualityTrendOut(
        hospital=hospital.name,
        hospital_id=hospital_id,
        data=data,
        current_score=current_score,
        previous_score=previous_score,
        change=change,
        trend_direction=trend_direction,
        consecutive_declines=consecutive,
        max_score=max_score,
        min_score=min_score,
        avg_score=avg_score,
    )
    cache.set(cache_key, result)
    return result


@router.get("/compare", response_model=List[HospitalComparisonOut])
def compare_all_hospitals(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    all_hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    if not all_hospitals:
        return []

    hospital_ids = [h.id for h in all_hospitals]

    disabled_rows = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    disabled_by_hospital: dict[int, set[int]] = {}
    for row in disabled_rows:
        disabled_by_hospital.setdefault(row.hospital_id, set()).add(row.indicator_id)

    value_rows = (
        db.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(
            IndicatorValue.hospital_id.in_(hospital_ids),
            IndicatorValue.month == month,
        )
        .all()
    )
    values_by_hospital: dict[int, dict[str, float]] = {}
    for val, ind in value_rows:
        disabled = disabled_by_hospital.get(val.hospital_id, set())
        if ind.id in disabled or val.value is None:
            continue
        values_by_hospital.setdefault(val.hospital_id, {})[ind.code] = val.value

    all_monthly_data = {}
    for h in all_hospitals:
        vals = values_by_hospital.get(h.id)
        if vals:
            all_monthly_data[h.name] = {month: vals}

    if len(all_monthly_data) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 hospitals with data for comparison")

    comparisons = compare_hospitals(all_monthly_data, month)
    return comparisons


@router.get("/outliers")
def list_outliers(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    rate_name: Optional[str] = Query(None, description="Filter by rate name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("analysis:outliers_v2", month=month, hospital_id=hospital_id, rate_name=rate_name, skip=skip, limit=limit)
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = db.query(AnomalyResult).options(selectinload(AnomalyResult.hospital)).join(Hospital, AnomalyResult.hospital_id == Hospital.id).filter(AnomalyResult.is_outlier, Hospital.is_active.is_(True))
    if hospital_id:
        enabled_months = get_enabled_months(db, hospital_id=hospital_id)
        if enabled_months:
            query = query.filter(AnomalyResult.month.in_(enabled_months))
    if month:
        query = query.filter(AnomalyResult.month == month)
    if hospital_id:
        query = query.filter(AnomalyResult.hospital_id == hospital_id)
    if rate_name:
        query = query.filter(AnomalyResult.rate_name.ilike(f"%{rate_name}%"))
    total = query.count()
    results = query.order_by(AnomalyResult.z_score.desc()).offset(skip).limit(limit).all()
    output = []
    for r in results:
        hosp = r.hospital
        output.append({
            "id": r.id,
            "hospital_id": r.hospital_id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": r.month,
            "indicator_code": r.indicator_code,
            "rate_name": r.rate_name,
            "value": r.value,
            "benchmark": r.benchmark,
            "z_score": r.z_score,
            "is_outlier": r.is_outlier,
        })
    result = {"total": total, "skip": skip, "limit": limit, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/ml")
def get_ml_analysis(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Run ML analysis (clustering, anomaly detection, PCA) for a given month."""
    from app.engine.pipeline import _build_ml_config
    from app.engine.ml import run_ml_analysis
    from app.config_utils import get_config_dict

    ml_config_flat = get_config_dict(db, "ml")
    ml_config = _build_ml_config(ml_config_flat)
    if not ml_config.get("enabled", False):
        return {}

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    if not hospitals:
        return {}

    enabled_months = get_enabled_months(db)
    if month not in enabled_months:
        return {}

    disabled_ids = set()
    disabled_rows = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    for dr in disabled_rows:
        disabled_ids.add((dr.hospital_id, dr.indicator_id))

    value_rows = (
        db.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(IndicatorValue.month == month)
        .all()
    )
    all_hospital_data: dict[str, dict[str, float]] = {}
    for val, ind in value_rows:
        if (val.hospital_id, ind.id) in disabled_ids or val.value is None:
            continue
        h = next((h for h in hospitals if h.id == val.hospital_id), None)
        if not h:
            continue
        all_hospital_data.setdefault(h.name, {})[ind.code] = val.value

    if len(all_hospital_data) < 2:
        return {}

    result = run_ml_analysis(all_hospital_data, ml_config)
    return result


@router.get("/rule-failures")
def list_rule_failures(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    severity: Optional[str] = Query(None, description="Filter by severity HIGH/MEDIUM/LOW"),
    rule_type: Optional[str] = Query(None, description="Filter by rule type LOGIC/CLINICAL/STATISTICAL/TREND"),
    rule_code: Optional[str] = Query(None, description="Filter by rule code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("analysis:rule-failures_v2", month=month, hospital_id=hospital_id, severity=severity, rule_type=rule_type, rule_code=rule_code, skip=skip, limit=limit)
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = db.query(ValidationResult).options(selectinload(ValidationResult.hospital)).join(Hospital, ValidationResult.hospital_id == Hospital.id).filter(ValidationResult.status == "FAIL", Hospital.is_active.is_(True))
    if hospital_id:
        enabled_months = get_enabled_months(db, hospital_id=hospital_id)
        if enabled_months:
            query = query.filter(ValidationResult.month.in_(enabled_months))
    if month:
        query = query.filter(ValidationResult.month == month)
    if hospital_id:
        query = query.filter(ValidationResult.hospital_id == hospital_id)
    if severity:
        query = query.filter(ValidationResult.severity == severity.upper())
    if rule_type:
        query = query.filter(ValidationResult.rule_type == rule_type.upper())
    if rule_code:
        query = query.filter(ValidationResult.rule_code == rule_code.upper())
    total = query.count()
    sev_order = case(
        (ValidationResult.severity == "CRITICAL", 0),
        (ValidationResult.severity == "HIGH", 1),
        (ValidationResult.severity == "MEDIUM", 2),
        (ValidationResult.severity == "LOW", 3),
        else_=4,
    )
    results = query.order_by(sev_order, ValidationResult.rule_code).offset(skip).limit(limit).all()
    output = []
    for r in results:
        hosp = r.hospital
        output.append({
            "id": r.id,
            "hospital_id": r.hospital_id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": r.month,
            "rule_code": r.rule_code,
            "rule_description": r.rule_description,
            "status": r.status,
            "severity": r.severity,
            "rule_type": r.rule_type,
            "details": r.details,
        })
    result = {"total": total, "skip": skip, "limit": limit, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/months")
def list_months_with_data(db: Session = Depends(get_db)):
    cache_key = "analysis:months"
    cached = cache.get(cache_key)
    if cached:
        return cached
    tables = [QualityScore, ValidationResult, ConfidenceScore, AnomalyResult]
    all_months: set = set()
    for tbl in tables:
        rows = db.query(tbl.month).distinct().all()
        all_months.update(r[0] for r in rows)
    result = sorted(all_months)
    cache.set(cache_key, result)
    return result


def get_enabled_months(db: Session, hospital_id: int = None) -> list:
    """Get list of months enabled for analysis (filters out disabled months)."""
    from app.models import SystemSetting
    from app.api.config_api import MONTH_SETTINGS_PREFIX
    all_months = list_months_with_data(db)
    if hospital_id is not None:
        prefix = MONTH_SETTINGS_PREFIX + str(hospital_id) + "_"
    else:
        prefix = MONTH_SETTINGS_PREFIX
    rows = db.query(SystemSetting).filter(
        SystemSetting.key.like(prefix + "%")
    ).all()
    disabled = {
        row.key[len(prefix):]
        for row in rows
        if row.value == "false"
    }
    return [m for m in all_months if m not in disabled]


@router.post("/reanalyze-all")
def reanalyze_all(
    force: bool = Query(False, description="Force re-analysis even if cached results exist"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    task_id = create_task("Re-analyze All", lambda: None)

    def _run(tid, hosp_list, frc):
        bg_db = SessionLocal()
        try:
            total = 0
            skipped = 0
            errors = []
            # Calculate total work across all hospitals with their enabled months
            total_work = 0
            for h in hosp_list:
                h_months = get_enabled_months(bg_db, hospital_id=h.id)
                total_work += len(h_months)
            done = 0
            for h in hosp_list:
                h_months = get_enabled_months(bg_db, hospital_id=h.id)
                for m in h_months:
                    try:
                        from app.engine.pipeline import check_analysis_exists
                        if not frc and check_analysis_exists(bg_db, h.id, m):
                            skipped += 1
                        else:
                            run_full_analysis(bg_db, h.id, m, force=frc)
                            total += 1
                    except Exception as e:
                        errors.append(f"H{h.id}/{m}: {e}")
                    done += 1
                    from app.tasks import set_progress
                    set_progress(tid, int(done / total_work * 100) if total_work > 0 else 0)
            # Clear cache after re-analysis so fresh data is served
            cache.invalidate()
            from app.tasks import set_status
            set_status(tid, "done")
        finally:
            bg_db.close()

    if background_tasks is not None:
        background_tasks.add_task(run_task, task_id, _run, task_id, hospitals, force)
    else:
        threading.Thread(target=run_task, args=(task_id, _run, task_id, hospitals, force), daemon=True).start()

    return {
        "task_id": task_id,
        "message": f"Re-analysis started. Use /tasks/{task_id} to check status.",
    }


@router.get("/cache-status")
def analysis_cache_status(db: Session = Depends(get_db)):
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()
    months = get_enabled_months(db)
    from app.engine.pipeline import check_analysis_exists
    status = []
    for h in hospitals:
        h_months = []
        for m in months:
            has_cache = check_analysis_exists(db, h.id, m)
            h_months.append({"month": m, "analyzed": has_cache})
        status.append({
            "hospital_id": h.id,
            "hospital": h.name,
            "months": h_months,
            "cached_count": sum(1 for x in h_months if x["analyzed"]),
            "total_count": len(h_months),
        })
    return {"status": status}


@router.get("/heatmap")
def heatmap_data(month: str = Query(None), db: Session = Depends(get_db)):
    cache_key = cache.make_key("analysis:heatmap_v2", month=month)
    cached = cache.get(cache_key)
    if cached:
        return cached

    q = db.query(
        QualityScore.hospital_id,
        QualityScore.month,
        QualityScore.score,
    )
    if month:
        q = q.filter(QualityScore.month == month)
    rows = q.all()

    # Get hospital names and active status
    hosp_map = {h.id: h for h in db.query(Hospital).all()}
    active_ids = {h.id for h in hosp_map.values() if h.is_active}

    # Get enabled months per hospital
    from app.api.analysis import get_enabled_months
    enabled_by_hid: dict = {}
    for hid in set(r.hospital_id for r in rows):
        if hid in active_ids:
            enabled_by_hid[hid] = set(get_enabled_months(db, hospital_id=hid))

    hospitals = sorted([h.name for h in hosp_map.values() if h.is_active])
    months = sorted(set(r.month for r in rows))

    matrix: dict = {}
    for r in rows:
        key = f"{r.hospital_id}||{r.month}"
        matrix[key] = round(float(r.score), 1)

    data = []
    for hid, hname in sorted([(h.id, h.name) for h in hosp_map.values() if h.is_active]):
        row = {"hospital": hname}
        for m in months:
            key = f"{hid}||{m}"
            if key in matrix:
                enabled_set = enabled_by_hid.get(hid)
                if enabled_set is not None and m not in enabled_set:
                    row[m] = None  # Disabled month → show as "--"
                else:
                    row[m] = matrix[key]
            else:
                row[m] = None
        data.append(row)

    result = {"hospitals": hospitals, "months": months, "data": data}
    cache.set(cache_key, result)
    return result


@router.post("/generate-report")
def generate_report(
    month: Optional[str] = Query(None, description="Month YYYY-MM, or omit for all months"),
    db: Session = Depends(get_db),
):
    hospitals = db.query(Hospital).order_by(Hospital.name).all()
    if not hospitals:
        raise HTTPException(status_code=404, detail="No hospitals found")

    if month:
        months_list = [month]
    else:
        month_rows = db.query(IndicatorValue.month).distinct().order_by(IndicatorValue.month).all()
        months_list = sorted(set(r[0] for r in month_rows))

    if not months_list:
        raise HTTPException(status_code=404, detail="No data months found")

    hospital_ids = [h.id for h in hospitals]

    disabled_rows = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    disabled_by_hospital: dict[int, set[int]] = {}
    for row in disabled_rows:
        disabled_by_hospital.setdefault(row.hospital_id, set()).add(row.indicator_id)

    value_rows = (
        db.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(
            IndicatorValue.hospital_id.in_(hospital_ids),
            IndicatorValue.month.in_(months_list),
        )
        .all()
    )
    values_by_key: dict[tuple[int, str], dict[str, float]] = {}
    for val, ind in value_rows:
        disabled = disabled_by_hospital.get(val.hospital_id, set())
        if ind.id in disabled or val.value is None:
            continue
        values_by_key.setdefault((val.hospital_id, val.month), {})[ind.code] = val.value

    score_rows = db.query(QualityScore).filter(
        QualityScore.hospital_id.in_(hospital_ids),
        QualityScore.month.in_(months_list),
    ).all()
    scores_by_key: dict[tuple[int, str], QualityScore] = {}
    for qs in score_rows:
        scores_by_key[(qs.hospital_id, qs.month)] = qs

    failure_rows = db.query(ValidationResult).filter(
        ValidationResult.hospital_id.in_(hospital_ids),
        ValidationResult.month.in_(months_list),
        ValidationResult.status == "FAIL",
    ).all()
    failures_by_key: dict[tuple[int, str], list[dict]] = {}
    for vr in failure_rows:
        key = (vr.hospital_id, vr.month)
        failures_by_key.setdefault(key, []).append({
            "rule_code": vr.rule_code,
            "details": vr.details or "",
            "severity": vr.severity,
        })

    reports = []
    errors = []

    enabled_cache = {}
    for h in hospitals:
        h_enabled = get_enabled_months(db, hospital_id=h.id)
        enabled_cache[h.id] = set(h_enabled)
    for h in hospitals:
        for m in months_list:
            if m not in enabled_cache.get(h.id, set()):
                continue
            try:
                vals = values_by_key.get((h.id, m))
                if not vals:
                    continue
                qs = scores_by_key.get((h.id, m))
                rule_failures = failures_by_key.get((h.id, m), [])

                ca = run_clinical_analysis(
                    hospital=h.name,
                    month=m,
                    values=vals,
                    quality_score=qs.score if qs else None,
                    issues=json.loads(qs.issues) if qs and qs.issues else [],
                    rule_failures=rule_failures,
                    completeness=qs.completeness if qs else 0,
                    consistency=qs.consistency if qs else 0,
                    rule_compliance=qs.rule_compliance if qs else 0,
                    outlier_penalty=qs.outlier_penalty if qs else 0,
                )
                reports.append(ca.to_dict())
            except Exception as e:
                errors.append(f"{h.name}/{m}: {e}")

    return {
        "reports": reports,
        "total": len(reports),
        "errors": errors,
        "months": months_list,
        "hospitals": [h.name for h in hospitals],
    }
