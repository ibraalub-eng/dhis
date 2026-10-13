import json
import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, selectinload

from app.cache import cache
from app.core.deps import require_permission
from app.database import SessionLocal, get_db
from app.engine.anomaly import (
    analyze_historical_trends,
    compare_hospitals,
    detect_anomalies,
    detect_trend_anomalies,
    generate_historical_summary,
)
from app.engine.clinical import run_clinical_analysis
from app.engine.pipeline import (
    get_all_hospital_data_for_month,
    get_enabled_values_for_hospital_month,
    run_full_analysis,
)
from app.models import (
    AnomalyResult,
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    ValidationResult,
)
from app.schemas import (
    HistoricalAnalysisOut,
    HospitalComparisonOut,
)
from app.tasks import create_task, run_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"], dependencies=[Depends(require_permission("analysis.read"))])


class QualityTrendPoint(BaseModel):
    month: str
    score: float
    rule_compliance: Optional[float] = None
    completeness: Optional[float] = None
    consistency: Optional[float] = None
    outlier_penalty: Optional[float] = None
    issues_count: int = 0
    peer_avg: Optional[float] = None


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
        except Exception as e:
            logger.warning("Failed to parse issues JSON for hospital %s month %s: %s", s.hospital_id, s.month, e)
        data.append(QualityTrendPoint(
            month=s.month,
            score=round(s.score, 1),
            rule_compliance=round(s.rule_compliance, 1) if s.rule_compliance is not None else None,
            completeness=round(s.completeness, 1) if s.completeness is not None else None,
            consistency=round(s.consistency, 1) if s.consistency is not None else None,
            outlier_penalty=round(s.outlier_penalty, 1) if s.outlier_penalty is not None else None,
            issues_count=len(issues),
        ))

    # Calculate peer average (avg score across all hospitals per month)
    peer_months = [d.month for d in data]
    peer_avgs = {}
    if peer_months:
        from sqlalchemy import func as sa_func
        peer_rows = (
            db.query(
                QualityScore.month,
                sa_func.avg(QualityScore.score).label("peer_avg"),
            )
            .filter(QualityScore.month.in_(peer_months))
            .group_by(QualityScore.month)
            .all()
        )
        peer_avgs = {r.month: round(r.peer_avg, 1) for r in peer_rows if r.peer_avg is not None}

    for d in data:
        d.peer_avg = peer_avgs.get(d.month)

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

    # Default (All Hospitals) disabled for this month — inherited unless hospital overrides
    default_disabled = set(
        r[0] for r in db.query(IndicatorDefaultConfig.indicator_id).filter(
            IndicatorDefaultConfig.month == month,
            IndicatorDefaultConfig.is_enabled.is_(False),
        ).all()
    )
    override_ids_by_hospital: dict[int, set[int]] = {}
    override_rows = db.query(HospitalIndicatorConfig.hospital_id, HospitalIndicatorConfig.indicator_id).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
    ).all()
    for row in override_rows:
        override_ids_by_hospital.setdefault(row.hospital_id, set()).add(row.indicator_id)
    for hid in hospital_ids:
        inherited = default_disabled - override_ids_by_hospital.get(hid, set())
        disabled_by_hospital.setdefault(hid, set()).update(inherited)

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
    # Enrich with hospital_ids
    by_name = {h.name: h.id for h in all_hospitals}
    out = []
    for c in comparisons:
        d = c.__dict__ if hasattr(c, '__dict__') else dict(c)
        d['hospital_id'] = by_name.get(c.hospital)
        out.append(d)
    return out


@router.get("/outliers")
def list_outliers(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    rate_name: Optional[str] = Query(None, description="Filter by rate name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    # v4: layered_type/layered_level/layered_interpretation added below — a
    # cached v3 payload would hide the classification column for up to 24h.
    cache_key = cache.make_key("analysis:outliers_v4", month=month, hospital_id=hospital_id, rate_name=rate_name, skip=skip, limit=limit)
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

    layered_by_key = {}
    rate_code_by_name = {}
    if results:
        from app.engine.rate_config import load_rate_specs

        rate_code_by_name = {spec.rate_name: spec.rate_code for spec in load_rate_specs(db).values()}
        layered_rows = (
            db.query(LayeredOutlierResult)
            .filter(
                LayeredOutlierResult.hospital_id.in_({r.hospital_id for r in results}),
                LayeredOutlierResult.month.in_({r.month for r in results}),
            )
            .all()
        )
        layered_by_key = {
            (lr.hospital_id, lr.month, lr.analysis_code): lr for lr in layered_rows
        }

    output = []
    for r in results:
        hosp = r.hospital
        layered_code = rate_code_by_name.get(r.rate_name) or r.indicator_code
        lr = layered_by_key.get((r.hospital_id, r.month, layered_code))
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
            # Peer metadata — same numbers the audit benchmark screen shows
            # (NULL for trend rows / rows computed before this field existed).
            "peer_count": r.peer_count,
            "peer_std": r.peer_std,
            "peer_min": r.peer_min,
            "peer_max": r.peer_max,
            "peer_median": r.peer_median,
            "peers_detail": r.peers_detail,
            # Layered classification (application-level LEFT JOIN — None when
            # no layered row exists for this hospital/month/analysis unit).
            "layered_type": lr.outlier_type if lr else None,
            "layered_level": lr.outlier_level if lr else None,
            "layered_interpretation": lr.interpretation if lr else None,
        })
    result = {"total": total, "skip": skip, "limit": limit, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/layered")
def list_layered(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital: Optional[int] = Query(None, description="Filter by hospital ID"),
    indicator: Optional[str] = Query(None, description="Filter by analysis code (indicator or rate code)"),
    classification: Optional[str] = Query(None, description="Filter by outlier_type"),
    level: Optional[str] = Query(None, description="Filter by outlier_level (NONE..VERY_HIGH)"),
    investigation: Optional[str] = Query(None, description="Filter by investigation_route (none|data_quality|clinical|contextual)"),
    sort: str = Query("month", description="Sort key: month | level | type | raw_value | rate | denominator"),
    order: str = Query("desc", description="Sort direction: asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Persisted layered-outlier rows, paged (design spec 2026-10-08 §8.1)."""
    from app.engine.anomaly.layered import LEVELS, build_analysis_specs

    cache_key = cache.make_key(
        "analysis:layered_v1",
        month=month,
        hospital=hospital,
        indicator=indicator,
        classification=classification,
        level=level,
        investigation=investigation,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .options(selectinload(LayeredOutlierResult.hospital))
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)
    if hospital:
        query = query.filter(LayeredOutlierResult.hospital_id == hospital)
    if indicator:
        query = query.filter(LayeredOutlierResult.analysis_code == indicator)
    if classification:
        query = query.filter(LayeredOutlierResult.outlier_type == classification)
    if level:
        query = query.filter(LayeredOutlierResult.outlier_level == level)
    if investigation:
        query = query.filter(LayeredOutlierResult.investigation_route == investigation)

    total = query.count()

    sort_columns = {
        "month": LayeredOutlierResult.month,
        "raw_value": LayeredOutlierResult.raw_value,
        "rate": LayeredOutlierResult.rate,
        "denominator": LayeredOutlierResult.denominator,
        "type": LayeredOutlierResult.outlier_type,
        # Rank NONE < LOW < MODERATE < HIGH < VERY_HIGH for ordering.
        "level": case({name: i for i, name in enumerate(LEVELS)}, value=LayeredOutlierResult.outlier_level),
    }
    sort_column = sort_columns.get(sort, LayeredOutlierResult.month)
    direction = sort_column.asc() if order == "asc" else sort_column.desc()
    rows = (
        query.order_by(direction, LayeredOutlierResult.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    spec_meta = {spec.analysis_code: (spec.name, spec.indicator_type)
                 for spec in build_analysis_specs(db)}
    output = []
    for r in rows:
        row = {c.name: getattr(r, c.name) for c in LayeredOutlierResult.__table__.columns}
        row.pop("created_at", None)
        name, itype = spec_meta.get(r.analysis_code, (None, None))
        row["hospital"] = r.hospital.name if r.hospital else "Unknown"
        row["indicator_name"] = name
        row["indicator_type"] = itype
        output.append(row)

    result = {"total": total, "page": page, "page_size": page_size, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/layered/summary")
def layered_summary(
    month: Optional[str] = Query(None, description="Month YYYY-MM (all months when omitted)"),
    db: Session = Depends(get_db),
):
    """Classification counts + per-hospital rollup for the Layered tab chips
    (design spec 2026-10-08 §8.2)."""
    cache_key = cache.make_key("analysis:layered_summary_v1", month=month)
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)

    groups = (
        query.with_entities(
            LayeredOutlierResult.hospital_id,
            LayeredOutlierResult.outlier_type,
            func.count(LayeredOutlierResult.id),
        )
        .group_by(LayeredOutlierResult.hospital_id, LayeredOutlierResult.outlier_type)
        .all()
    )

    by_classification = {}
    by_hospital_counts = {}
    total = 0
    for hosp_id, otype, count in groups:
        count = int(count)
        total += count
        otype = otype or "UNKNOWN"
        by_classification[otype] = by_classification.get(otype, 0) + count
        by_hospital_counts[hosp_id] = by_hospital_counts.get(hosp_id, 0) + count

    hospital_names = {}
    if by_hospital_counts:
        hospital_names = dict(
            db.query(Hospital.id, Hospital.name)
            .filter(Hospital.id.in_(by_hospital_counts))
            .all()
        )

    result = {
        "month": month,
        "total": total,
        "by_classification": [
            {"outlier_type": t, "count": c}
            for t, c in sorted(by_classification.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_hospital": [
            {"hospital_id": hid, "hospital": hospital_names.get(hid, "Unknown"), "count": c}
            for hid, c in sorted(by_hospital_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
    cache.set(cache_key, result)
    return result


@router.get("/layered/trend")
def layered_trend(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital: Optional[int] = Query(None, description="Filter by hospital ID"),
    indicator: Optional[str] = Query(None, description="Filter by analysis code (indicator or rate code)"),
    classification: Optional[str] = Query(None, description="Filter by outlier_type"),
    level: Optional[str] = Query(None, description="Filter by outlier_level (NONE..VERY_HIGH)"),
    investigation: Optional[str] = Query(None, description="Filter by investigation_route (none|data_quality|clinical|contextual)"),
    db: Session = Depends(get_db),
):
    """Monthly raw-value series for the Layered tab trend chart.

    A raw value is only comparable within one indicator, so each series is one
    hospital's points for the chosen indicator across the sorted months. Every
    filter the table honors also narrows the points here, so the chart is a
    filter-driven view; a single hospital id collapses it to one line."""
    cache_key = cache.make_key(
        "analysis:layered_trend_v1",
        month=month,
        hospital=hospital,
        indicator=indicator,
        classification=classification,
        level=level,
        investigation=investigation,
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .options(selectinload(LayeredOutlierResult.hospital))
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)
    if hospital:
        query = query.filter(LayeredOutlierResult.hospital_id == hospital)
    if indicator:
        query = query.filter(LayeredOutlierResult.analysis_code == indicator)
    if classification:
        query = query.filter(LayeredOutlierResult.outlier_type == classification)
    if level:
        query = query.filter(LayeredOutlierResult.outlier_level == level)
    if investigation:
        query = query.filter(LayeredOutlierResult.investigation_route == investigation)

    rows = query.order_by(
        LayeredOutlierResult.month.asc(), LayeredOutlierResult.id.asc()
    ).all()

    series_map: dict = {}
    for r in rows:
        key = str(r.hospital_id)
        series = series_map.get(key)
        if series is None:
            series = {
                "key": key,
                "name": r.hospital.name if r.hospital else "Unknown",
                "points": [],
            }
            series_map[key] = series
        series["points"].append({
            "month": r.month,
            "raw_value": r.raw_value,
            "rate": r.rate,
            "outlier_type": r.outlier_type,
            "outlier_level": r.outlier_level,
        })

    result = {
        "months": sorted({r.month for r in rows}),
        "series": list(series_map.values()),
    }
    cache.set(cache_key, result)
    return result


@router.get("/layered/heatmap")
def layered_heatmap(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM (collapses columns to it)"),
    hospital: Optional[int] = Query(None, description="Filter by hospital ID"),
    indicator: Optional[str] = Query(None, description="Filter by analysis code (indicator or rate code)"),
    classification: Optional[str] = Query(None, description="Filter by outlier_type"),
    level: Optional[str] = Query(None, description="Filter by outlier_level (NONE..VERY_HIGH)"),
    investigation: Optional[str] = Query(None, description="Filter by investigation_route (none|data_quality|clinical|contextual)"),
    db: Session = Depends(get_db),
):
    """Hospital × month grid for the Layered tab, one cell per pair.

    The cell carries the WORST classification present in it (order below is a
    judgment call: the data-entry suspect — a finding that is most likely a
    fixable data bug — ranks highest, a verified investigation need next, then
    the statistical anomalies, then the contextual ones):
    NORMAL < HISTORICAL < PEER < VOLUME_DRIVEN < RAW_VALUE < RATE <
    CLINICAL_INVESTIGATION_REQUIRED < POSSIBLE_DATA_ENTRY_ERROR.
    Cells with no matching rows under the current filters are absent (leaf
    rows only) — the UI renders them as empty, not dangerous.
    """
    cache_key = cache.make_key(
        "analysis:layered_heatmap_v1",
        month=month,
        hospital=hospital,
        indicator=indicator,
        classification=classification,
        level=level,
        investigation=investigation,
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .options(selectinload(LayeredOutlierResult.hospital))
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)
    if hospital:
        query = query.filter(LayeredOutlierResult.hospital_id == hospital)
    if indicator:
        query = query.filter(LayeredOutlierResult.analysis_code == indicator)
    if classification:
        query = query.filter(LayeredOutlierResult.outlier_type == classification)
    if level:
        query = query.filter(LayeredOutlierResult.outlier_level == level)
    if investigation:
        query = query.filter(LayeredOutlierResult.investigation_route == investigation)

    rows = query.all()
    groups: dict = {}
    for r in rows:
        cell = groups.setdefault((r.hospital_id, r.month), {})
        otype = r.outlier_type or "UNKNOWN"
        count = cell.get(otype, 0) + 1
        cell[otype] = count

    _severity = {t: i for i, t in enumerate(
        ["NORMAL", "UNKNOWN", "HISTORICAL_ANOMALY", "PEER_ANOMALY",
         "VOLUME_DRIVEN_ANOMALY", "RAW_VALUE_ANOMALY", "RATE_ANOMALY",
         "CLINICAL_INVESTIGATION_REQUIRED", "POSSIBLE_DATA_ENTRY_ERROR"],
    )}
    worst = {
        key: (
            max(cell, key=lambda t: (_severity.get(t, -1), cell[t])),
            sum(cell.values()),
            dict(sorted(cell.items(), key=lambda kv: -kv[1])),
        )
        for key, cell in groups.items()
    }

    hosp_ids = {hid for hid, _m in groups}
    hospital_names = {}
    if hosp_ids:
        hospital_names = dict(
            db.query(Hospital.id, Hospital.name)
            .filter(Hospital.id.in_(hosp_ids))
            .all()
        )

    months = sorted({m for _hid, m in groups})
    data = [
        {
            "hospital_id": hid,
            "hospital": hospital_names.get(hid, "Unknown"),
            **{
                m: {
                    "type": worst[(hid, m)][0],
                    "count": worst[(hid, m)][1],
                    "breakdown": worst[(hid, m)][2],
                }
                for m in months
                if (hid, m) in worst
            },
        }
        for hid in sorted(hosp_ids, key=lambda i: str(hospital_names.get(i, "")))
    ]

    result = {"months": months, "data": data}
    cache.set(cache_key, result)
    return result


@router.get("/ml")
def get_ml_analysis(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Run ML analysis (clustering, anomaly detection, PCA) for a given month."""
    from app.config_utils import get_config_dict
    from app.engine.ml import run_ml_analysis
    from app.engine.pipeline import _build_ml_config

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

    # Default (All Hospitals) disabled for this month — inherited unless hospital overrides
    default_disabled_ids = set()
    for iid, in db.query(IndicatorDefaultConfig.indicator_id).filter(
        IndicatorDefaultConfig.month == month,
        IndicatorDefaultConfig.is_enabled.is_(False),
    ).all():
        default_disabled_ids.add(iid)
    override_ids_by_hospital: dict[int, set[int]] = {}
    for row in db.query(HospitalIndicatorConfig.hospital_id, HospitalIndicatorConfig.indicator_id).all():
        override_ids_by_hospital.setdefault(row.hospital_id, set()).add(row.indicator_id)
    for hid in [h.id for h in hospitals]:
        inherited = {iid for iid in default_disabled_ids if iid not in override_ids_by_hospital.get(hid, set())}
        for iid in inherited:
            disabled_ids.add((hid, iid))

    hosp_map = {h.id: h for h in hospitals}

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
        h = hosp_map.get(val.hospital_id)
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
    q: Optional[str] = Query(None, description="Free-text search over hospital name, rule code, description and details"),
    sort_by: Optional[str] = Query(None, description="Sort column: severity (default) | hospital | month | rule | type | description | details"),
    order: str = Query("asc", description="Sort direction for sort_by (asc | desc)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("analysis:rule-failures_v3", month=month, hospital_id=hospital_id, severity=severity, rule_type=rule_type, rule_code=rule_code, q=q, sort_by=sort_by, order=order, skip=skip, limit=limit)
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
    if q and q.strip():
        # One search box must reach every column the user can see: hospital
        # name (Arabic included), rule code, description and the failure
        # details. Month is searched too — "2026-08" is what people paste.
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Hospital.name.ilike(needle),
                ValidationResult.rule_code.ilike(needle),
                ValidationResult.rule_description.ilike(needle),
                ValidationResult.details.ilike(needle),
                ValidationResult.month.ilike(needle),
            )
        )
    total = query.count()
    sev_order = case(
        (ValidationResult.severity == "CRITICAL", 0),
        (ValidationResult.severity == "HIGH", 1),
        (ValidationResult.severity == "MEDIUM", 2),
        (ValidationResult.severity == "LOW", 3),
        else_=4,
    )
    desc = (order or "asc").lower() == "desc"
    # Allowlist: an unknown sort_by used to leave `column` unbound and blow up
    # with UnboundLocalError (HTTP 500) on the first row fetch. Unknown values
    # now fall back to the default severity ordering.
    sort_col = (sort_by or "").lower()
    _SORTS = {
        "hospital": lambda: Hospital.name,
        # YYYY-MM sorts correctly as text; a numeric sort would collapse every
        # month of a year into the same value (2026-08 parses to 2026).
        "month": lambda: ValidationResult.month,
        "rule": lambda: ValidationResult.rule_code,
        "rule_code": lambda: ValidationResult.rule_code,
        # Severity sorts by RANK, not alphabetically, so the user's asc/desc
        # applies to the case() and the tie-breaks stay ascending below.
        "severity": lambda: sev_order.desc() if desc else sev_order.asc(),
        "type": lambda: ValidationResult.rule_type,
        "rule_type": lambda: ValidationResult.rule_type,
        "description": lambda: ValidationResult.rule_description,
        "details": lambda: ValidationResult.details,
    }
    column = None
    if sort_col in _SORTS:
        column = _SORTS[sort_col]()
    else:
        sort_col = ""
    if sort_col and sort_col != "severity":
        column = column.desc() if desc else column.asc()
    if sort_col:
        # Stable tie-breaks so equal keys never shuffle between requests.
        query = query.order_by(column, ValidationResult.hospital_id, ValidationResult.month.desc(), ValidationResult.rule_code)
    else:
        # Default: worst severity first, then rule code.
        query = query.order_by(sev_order.asc(), ValidationResult.rule_code.asc())
    results = query.offset(skip).limit(limit).all()
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
    """Months that actually have data.

    Derived from IndicatorValue only — the tables where analysis results are
    persisted (QualityScore, ValidationResult, ConfidenceScore, AnomalyResult)
    are deliberately NOT unioned in. Those accumulate zero-score rows for
    months that were never analyzed (ghost rows), which used to leak into
    every month/year dropdown as months that have no data at all.
    """
    cache_key = "analysis:months"
    cached = cache.get(cache_key)
    if cached:
        return cached
    rows = db.query(IndicatorValue.month).distinct().all()
    # Defense in depth: only real YYYY-MM months pass. The synthetic '__all__'
    # selector (and any other malformed value) must never reach a dropdown —
    # a poisoned row used to surface as an '__all__' month and '__all__' year.
    import re as _re
    result = sorted({r[0] for r in rows if r[0] and _re.match(r"^\d{4}-\d{2}$", str(r[0]))})
    cache.set(cache_key, result)
    return result


def get_enabled_months(db: Session, hospital_id: int = None) -> list:
    """Get list of months enabled for analysis (filters out disabled months)."""
    from app.api.config_api import MONTH_SETTINGS_PREFIX
    from app.models import SystemSetting
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


def _run_reanalyze_all(hosp_list, frc, progress_cb=None):
    """Re-run run_full_analysis for every enabled month of the given hospitals.

    A failed month rolls the shared session back (PostgreSQL aborts the whole
    transaction on error — without rollback every later month fails with
    InFailedSqlTransaction, "This Session's transaction has been rolled back
    due to a previous exception", instead of its own real error) and is
    collected. If any month failed, RuntimeError is raised AFTER the loop with
    a summary so the caller (run_task) marks the task as 'error' and the
    settings screen shows it instead of a misleading "done".
    """
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
                    bg_db.rollback()
                    errors.append(f"H{h.id}/{m}: {e}")
                done += 1
                if progress_cb:
                    progress_cb(int(done / total_work * 100) if total_work > 0 else 0)
        # Clear cache after re-analysis so fresh data is served
        cache.invalidate()
        if errors:
            raise RuntimeError(
                f"{len(errors)} of {total + skipped + len(errors)} analyses failed. "
                f"First: {errors[0]}"
            )
        return {"analyzed": total, "skipped": skipped}
    finally:
        bg_db.close()


@router.post("/reanalyze-all", dependencies=[Depends(require_permission("dashboard.write"))])
def reanalyze_all(
    force: bool = Query(False, description="Force re-analysis even if cached results exist"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("dashboard.write")),
):
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    task_id = create_task("Re-analyze All", lambda: None)

    def _run(tid, hosp_list, frc):
        from app.tasks import set_progress
        # Returning the counts lets run_task store them as the task result;
        # on month failures _run_reanalyze_all raises and run_task marks the
        # task as 'error' with the summary message.
        return _run_reanalyze_all(hosp_list, frc, progress_cb=lambda pct: set_progress(tid, pct))

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
def heatmap_data(month: str = Query(None), hospital_id: int = Query(None), db: Session = Depends(get_db)):
    # NOTE: hospital_id is accepted (and ignored) for API compatibility. The
    # Quality Score heatmap is a network-wide view: it always shows every
    # active hospital regardless of the dashboard's selected hospital, so
    # users can compare the selected facility against its peers in place.
    # Deliberately NOT cached. The 24h TTLCache poisoned this endpoint twice:
    # an empty matrix written during a DB restore hid real data for a day,
    # and pytest runs leaked their in-memory-SQLite hospitals ("Central
    # Medical" etc.) into the shared data/cache files. The query is small
    # (one table, ~hundreds of rows) so it is always read fresh from the DB.
    import re as _re
    # Synthetic/stamped months (e.g. '__all__') must never become heatmap
    # columns — a legacy ghost row used to render a bogus '__all__' column
    # and shifted every real month into the wrong position. Filtered in
    # Python (not SQL REGEXP) so it also works on SQLite in tests.
    q = db.query(
        QualityScore.hospital_id,
        QualityScore.month,
        QualityScore.score,
    )
    if month:
        q = q.filter(QualityScore.month == month)
    # Deliberately NO hospital_id filter here — see note above: the heatmap
    # must not be narrowed by the dashboard's selected hospital.
    rows = [r for r in q.all() if r.month and _re.match(r"^\d{4}-\d{2}$", str(r.month))]

    # Get hospital names and active status
    hosp_map = {h.id: h for h in db.query(Hospital).all()}
    active_ids = {h.id for h in hosp_map.values() if h.is_active}

    # Months enabled per hospital (manual disable toggles in SystemSetting).
    # Queried fresh — NOT via get_enabled_months, whose month list comes from
    # a 24h-cached endpoint and would reintroduce the staleness this endpoint
    # just had removed.
    from app.api.config_api import MONTH_SETTINGS_PREFIX
    from app.models import SystemSetting
    all_months = {r[0] for r in db.query(IndicatorValue.month).distinct().all()}
    disabled_rows = db.query(SystemSetting).filter(
        SystemSetting.key.like(MONTH_SETTINGS_PREFIX + "%")
    ).all()
    disabled_by_hid: dict = {}
    for row in disabled_rows:
        if row.value != "false":
            continue
        # key format: month_enabled_<hid>_<YYYY-MM>
        rest = row.key[len(MONTH_SETTINGS_PREFIX):]
        hid_str, _, m = rest.partition("_")
        if not hid_str.isdigit() or not m:
            continue
        disabled_by_hid.setdefault(int(hid_str), set()).add(m)

    hospitals = sorted(h.name for h in hosp_map.values() if h.is_active)
    # Column months must have REAL indicator data (same ghost doctrine as
    # /analysis/months and the trend: a QualityScore row for a month that
    # was never analyzed is a zero-score sentinel, not data). QualityScore
    # rows arrive pre-filtered to YYYY-MM, and all_months is a fresh DB
    # query, so ghost months like '__all__' or reanalysis sentinels can
    # never become heatmap columns.
    months = sorted({r.month for r in rows} & all_months)
    if not months:
        return {"hospitals": hospitals, "months": [], "data": []}

    # A scored cell is shown unless its month was manually disabled for that
    # hospital (then rendered as "--"). Months a hospital never analyzed
    # (no IndicatorValue) also render as "--" through this gate.
    enabled_by_hid: dict = {}
    for hid in {r.hospital_id for r in rows}:
        if hid in active_ids:
            enabled_by_hid[hid] = all_months - disabled_by_hid.get(hid, set())

    matrix: dict = {}
    for r in rows:
        key = f"{r.hospital_id}||{r.month}"
        matrix[key] = round(float(r.score), 1)

    data = []
    # Every active hospital gets a row — hospital_id does not narrow the
    # matrix (see note at the top of this endpoint).
    active_hosp = sorted([(h.id, h.name) for h in hosp_map.values() if h.is_active])
    for hid, hname in active_hosp:
        row = {"hospital_id": hid, "hospital": hname}
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
    return result


@router.post("/generate-report", dependencies=[Depends(require_permission("smart_analytics.generate_report"))])
def generate_report(
    month: Optional[str] = Query(None, description="Month YYYY-MM, or omit for all months"),
    hospital_id: Optional[int] = Query(None, description="Hospital ID, or omit for all hospitals"),
    db: Session = Depends(get_db),
):
    hospitals = db.query(Hospital).order_by(Hospital.name).all()
    if hospital_id:
        hospitals = [h for h in hospitals if h.id == hospital_id]
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

    # Default (All Hospitals) disabled per month — inherited unless hospital overrides
    default_disabled_by_month: dict[str, set[int]] = {}
    default_rows = db.query(IndicatorDefaultConfig.month, IndicatorDefaultConfig.indicator_id).filter(
        IndicatorDefaultConfig.month.in_(months_list),
        IndicatorDefaultConfig.is_enabled.is_(False),
    ).all()
    for m, iid in default_rows:
        default_disabled_by_month.setdefault(m, set()).add(iid)
    override_ids_by_hospital: dict[int, set[int]] = {}
    override_rows = db.query(HospitalIndicatorConfig.hospital_id, HospitalIndicatorConfig.indicator_id).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
    ).all()
    for row in override_rows:
        override_ids_by_hospital.setdefault(row.hospital_id, set()).add(row.indicator_id)

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
        disabled = set(disabled_by_hospital.get(val.hospital_id, set()))
        for iid in default_disabled_by_month.get(val.month, ()):
            if iid not in override_ids_by_hospital.get(val.hospital_id, set()):
                disabled.add(iid)
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
                    session=db,  # مشاركة نفس التخزين المؤقت للـ AI (مفتاح: مستشفى + شهر) مع التحليل الفردي
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
