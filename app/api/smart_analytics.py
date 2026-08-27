import math
import logging
from datetime import datetime
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.cache import cache
from app.database import get_db
from app.engine.smart import run_smart_analytics
from app.engine.smart.schemas import SmartAnalyticsResult
import threading
from app.core.deps import require_permission

router = APIRouter(prefix="/smart", tags=["Smart Analytics"], dependencies=[Depends(require_permission("smart_analytics.read"))])

SMART_CACHE_VERSION = "v3"


def _get_envelope_or_empty(db: Session, month: str) -> dict:
    """Common pre-check: returns envelope, or None if computing/empty."""
    envelope = _get_smart_data(db, month)
    if envelope.get("computing"):
        return {"computing": True, "message": "جاري التحليل...", "month": month}
    if envelope["hospitals_count"] == 0:
        return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
    return envelope


def _sanitize(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _clustering_to_dict(clustering):
    """تحويل عميق لبيانات التجميع بما فيها ملفات تعريف المجموعات."""
    if clustering is None:
        return None
    return _sanitize({
        "n_clusters": clustering.n_clusters,
        "silhouette_score": clustering.silhouette_score,
        "method": clustering.method,
        "clusters": [c.__dict__ for c in clustering.clusters],
        "noise_hospitals": clustering.noise_hospitals,
        "pca_coordinates": clustering.pca_coordinates,
        "centroids": clustering.centroids,
        "profiles": [
            {**p.__dict__, "distinguishing_features": p.distinguishing_features}
            for p in (clustering.profiles or [])
        ],
    })


def _correlations_to_dict(corr):
    """تحويل عميق لبيانات الارتباطات إلى قواميس JSON مع تنظيف القيم غير المنتهية.

    يُحوِّل strong_correlations و feature_importance إلى قواميس صريحة حتى يصلها
    _sanitize (الذي لا يتسلل داخل كائنات dataclass) وتصل الواجهة دائماً بمفاتيح
    pearson_r/spearman_r رقمية صالحة.
    """
    if corr is None:
        return None
    return _sanitize({
        "matrix": corr.matrix,
        "indicators": corr.indicators,
        "strong_correlations": [
            {"indicator_a": c.indicator_a, "indicator_b": c.indicator_b,
             "pearson_r": c.pearson_r, "spearman_r": c.spearman_r,
             "p_value": c.p_value, "strength": c.strength}
            for c in corr.strong_correlations
        ],
        "feature_importance": [
            {**f.__dict__, "features": [e.__dict__ for e in f.features]}
            for f in corr.feature_importance
        ],
    })


def _envelope(result: SmartAnalyticsResult) -> dict:
    data = {
        "kpi": result.kpi.__dict__,
        "anomalies": [a.__dict__ for a in result.anomalies],
        "clustering": _clustering_to_dict(result.clustering),
        "correlations": _correlations_to_dict(result.correlations),
        "residuals": [r.__dict__ for r in result.residuals],
        "stratified": [s.__dict__ for s in result.stratified],
        "explanations": [
            {**e.__dict__, "top_factors": [f.__dict__ for f in e.top_factors]}
            for e in result.explanations
        ],
        "geo": {
            "governorates": [g.__dict__ for g in result.geo.governorates],
        } if result.geo else None,
        "patterns": [p.__dict__ for p in result.patterns],
    }

    if result.xgboost_predictions:
        xgb = result.xgboost_predictions
        data["xgboost"] = {
            "model_r2": xgb.model_r2,
            "model_mae": xgb.model_mae,
            "training_months": xgb.training_months,
            "hospitals_trained": xgb.hospitals_trained,
            "accuracy_note": xgb.accuracy_note,
            "trained_at": xgb.trained_at,
            "retrained": xgb.retrained,
            "data_fingerprint": xgb.data_fingerprint,
            "walk_forward": xgb.walk_forward,
            "feature_variant": xgb.feature_variant,
            "predictions": [
                {
                    "hospital_name": p.hospital_name,
                    "hospital_id": p.hospital_id,
                    "current_score": p.current_score,
                    "predicted_next_score": p.predicted_next_score,
                    "predicted_severity": p.predicted_severity,
                    "risk_change": p.risk_change,
                    "confidence": p.confidence,
                    "top_drivers": [d.__dict__ for d in p.top_drivers],
                }
                for p in xgb.predictions
            ],
            "global_feature_importance": [fi.__dict__ for fi in xgb.global_feature_importance],
        }

    return _sanitize({
        "month": result.month,
        "generated_at": datetime.now().isoformat(),
        "hospitals_count": result.hospitals_count,
        "data": data,
    })


def _healthy_hospitals(db: Session, month: str, anomalies: list) -> list:
    """أفضل المستشفيات أداءً — نماذج يُحتذى بها في جودة الإبلاغ.

    تُحسب درجة مركّبة لكل مستشفى سليم (درجة شذوذ أقل من عتبة التنبيه):
    50% جودة البيانات + 30% الثقة + 20% (100 - شذوذ×100)، وتُرتَّب تنازلياً.
    """
    from app.models import QualityScore, ConfidenceScore

    quality = {
        q.hospital_id: q
        for q in db.query(QualityScore).filter(QualityScore.month == month).all()
    }
    confidence = {
        c.hospital_id: c
        for c in db.query(ConfidenceScore).filter(ConfidenceScore.month == month).all()
    }
    anomaly_map = {a["hospital_id"]: a for a in anomalies}

    # If no hospitals have quality/confidence scores for this month,
    # fall back to listing all non-critical hospitals from anomalies
    has_scores = bool(quality or confidence)

    rows = []
    for hid, a in anomaly_map.items():
        # فقط المستشفيات السليمة (غير شاذة) تدخل القائمة
        score = a.get("anomaly_score")
        sev = a.get("severity", "normal")
        if score is None or score >= 0.6 or sev == "critical":
            continue
        qs = quality.get(hid)
        cs = confidence.get(hid)
        if has_scores:
            # With scores: require at least quality score
            if qs is None:
                continue
            q = float(qs.score or 0)
            c_val = float(cs.overall_confidence or 0) if cs else 50.0
            completeness = float(qs.completeness or 0)
            consistency = float(qs.consistency or 0)
            compliance = float(qs.rule_compliance or 0)
        else:
            # No scores available: use anomaly-based ranking
            q = round((1 - score) * 100, 1)
            c_val = 50.0
            completeness = 0.0
            consistency = 0.0
            compliance = 0.0
        anom = float(score or 0)
        composite = round(0.5 * q + 0.3 * c_val + 0.2 * (100 - anom * 100), 1)
        rows.append({
            "hospital_id": hid,
            "hospital_name": a.get("hospital_name", ""),
            "governorate": a.get("governorate", ""),
            "hospital_type": a.get("hospital_type", ""),
            "quality_score": round(q, 1),
            "completeness": round(completeness, 1),
            "consistency": round(consistency, 1),
            "rule_compliance": round(compliance, 1),
            "confidence": round(c_val, 1),
            "anomaly_score": round(anom, 3),
            "composite_score": composite,
        })
    rows.sort(key=lambda r: (r["composite_score"], r["hospital_name"]), reverse=True)
    return _sanitize(rows[:5])


def _compute_smart_data(db, month: str) -> dict:
    """Heavy computation — runs in background thread.
    
    Always creates its own session (SessionLocal) to avoid
    issues with request-scoped sessions closing prematurely.
    """
    from app.database import SessionLocal
    bg_db = SessionLocal()
    try:
        logger.info(f"[smart] Starting computation for {month}...")
        try:
            result = run_smart_analytics(bg_db, month)
            logger.info(f"[smart] Computation result for {month}: hospitals={result.hospitals_count} anomalies={len(result.anomalies)} clusters={len(result.clustering.clusters) if result.clustering else 0}")
        except Exception as e:
            logger.error(f"[smart] Computation FAILED for {month}: {e}", exc_info=True)
            # Cache the error state so we don't keep retrying forever
            error_response = {
                "month": month,
                "generated_at": datetime.utcnow().isoformat(),
                "hospitals_count": 0,
                "data": {
                    "kpi": {}, "anomalies": [], "clusters": [],
                    "correlations": [], "lag_analysis": {},
                    "early_warnings": [], "healthy_hospitals": [],
                    "patterns": [],
                },
            }
            cache_key = f"smart_overview_{month}_{SMART_CACHE_VERSION}"
            cache.set(cache_key, error_response, ttl=300)  # cache error for 5min
            _compute_locks.pop(month, None)
            return
        response = _envelope(result)

        try:
            response["data"]["healthy_hospitals"] = _healthy_hospitals(
                bg_db, month, response["data"]["anomalies"]
            )
        except Exception as e:
            logger.warning(f"healthy_hospitals failed for {month}: {e}")
            response["data"]["healthy_hospitals"] = []

        from app.engine.smart.lag_analysis import run_lag_analysis, run_early_warnings
        try:
            lag_results = run_lag_analysis(bg_db, month)
            response["data"]["lag_analysis"] = _sanitize(lag_results)
        except Exception as e:
            logger.warning(f"lag_analysis failed for {month}: {e}")
            response["data"]["lag_analysis"] = {}
            lag_results = {}

        try:
            response["data"]["early_warnings"] = _sanitize(run_early_warnings(bg_db, month, lag_results))
        except Exception as e:
            logger.warning(f"early_warnings failed for {month}: {e}")
            response["data"]["early_warnings"] = []

        cache_key = f"smart_overview_{month}_{SMART_CACHE_VERSION}"
        cache.set(cache_key, response, ttl=1800)
        logger.info(f"[smart] Computation complete for {month} — cached for 30min")
        return response
    finally:
        _compute_locks.pop(month, None)
        bg_db.close()


import threading as _threading
_compute_locks = {}  # month -> bool to track if computation is in progress


def _get_smart_data(db: Session, month: str) -> dict:
    """Full smart-analysis envelope for a month, memoized per-month.

    If cached, returns immediately. If not cached, kicks off background
    computation and returns an empty response so the frontend can poll.
    """
    cache_key = f"smart_overview_{month}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    # Kick off background computation (thread creates its own session)
    if not _compute_locks.get(month):
        _compute_locks[month] = True
        t = threading.Thread(target=_compute_smart_data, args=(None, month), daemon=True)
        t.start()
    # Return empty envelope so caller gets a fast response
    return {
        "month": month,
        "generated_at": datetime.utcnow().isoformat(),
        "hospitals_count": 0,
        "computing": True,
        "data": {
            "kpi": {}, "anomalies": [], "clusters": [],
            "correlations": [], "lag_analysis": {},
            "early_warnings": [], "healthy_hospitals": [],
        },
    }
@router.get("/months")
def smart_months(db: Session = Depends(get_db)):
    """قائمة الأشهر المتاحة للتحليل الذكي (نفس مصدر analysis/months)."""
    from app.api.analysis import list_months_with_data
    try:
        return list_months_with_data(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في قائمة الأشهر: {str(e)}")


@router.get("/hospitals")
def smart_hospitals(db: Session = Depends(get_db)):
    """قائمة المستشفيات النشطة بصيغة {id, name} لاختيار وضع المستشفى."""
    from app.models import Hospital
    try:
        rows = db.query(Hospital).filter(Hospital.is_active == True).order_by(Hospital.name).all()  # noqa: E712
        return [{"id": h.id, "name": h.name} for h in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في قائمة المستشفيات: {str(e)}")


@router.get("/overview/{month}")
def get_overview(month: str, db: Session = Depends(get_db)):
    try:
        return _get_smart_data(db, month)
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل: {str(e)}")


@router.get("/decision-board/{month}")
def get_decision_board(month: str, db: Session = Depends(get_db)):
    """لوحة القرار: حمولة خفيفة سريعة (KPI + أولويات + إنذار مبكر) أعلى الصفحة.

    تُشتق من مذكّرة الشهر المشتركة (_get_smart_data) بلا إعادة حساب؛ يعرض فقط
    ما يحتاجه القرار الفوري. الشهر الخالي يُرجع empty مع رسالة عربية.
    """
    try:
        envelope = _get_smart_data(db, month)
        if envelope.get("computing"):
            return {"computing": True, "message": "جاري التحليل...", "month": month}
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        data = envelope["data"]
        order = {"critical": 0, "warning": 1, "normal": 2}
        anomalies = sorted(data["anomalies"], key=lambda a: (order.get(a["severity"], 2), -a["anomaly_score"]))
        return _sanitize({
            "month": month,
            "generated_at": envelope["generated_at"],
            "hospitals_count": envelope["hospitals_count"],
            "kpi": data["kpi"],
            "anomalies": anomalies,
            "early_warnings": data.get("early_warnings", []),
            "healthy_hospitals": data.get("healthy_hospitals", []),
        })
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في لوحة القرار: {str(e)}")


@router.get("/governorate-analysis/{month}")
def get_governorate_analysis(month: str, db: Session = Depends(get_db)):
    from app.engine.smart.governorate_analysis import analyze_governorate_correlations
    from app.engine.smart import _load_hospital_data

    cache_key = f"governorate_analysis_{month}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    all_data = _load_hospital_data(db, month)
    if not all_data:
        empty = _sanitize({"governorate_profiles": [], "cross_governorate_correlations": [], "indicator_governorate_heatmap": {}, "xgboost_insights": {}})
        cache.set(cache_key, empty, ttl=300)
        return empty

    result = _sanitize(analyze_governorate_correlations(all_data, {}))
    cache.set(cache_key, result, ttl=300)
    return result


@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        data = result["data"]
        response = {"month": month, "anomalies": data["anomalies"], "explanations": data["explanations"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الشذوذ: {str(e)}")


@router.get("/clusters/{month}")
def get_clusters(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        response = {"month": month, "clustering": result["data"]["clustering"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل التجمعات: {str(e)}")


@router.get("/correlations/{month}")
def get_correlations(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        response = {"month": month, "correlations": result["data"]["correlations"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الارتباطات: {str(e)}")


@router.get("/residuals/{month}")
def get_residuals(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        response = {"month": month, "residuals": result["data"]["residuals"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل البواقي: {str(e)}")


@router.get("/stratified/{month}")
def get_stratified(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        response = {"month": month, "stratified": result["data"]["stratified"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الطبقي: {str(e)}")


@router.get("/geo/{month}")
def get_geo(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        response = {"month": month, "geo": result["data"]["geo"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الجغرافي: {str(e)}")


@router.get("/patterns/{month}")
def get_patterns(month: str, db: Session = Depends(get_db)):
    try:
        data = _get_smart_data(db, month)["data"]
        return {"month": month, "patterns": data.get("patterns", [])}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الأنماط: {str(e)}")


@router.get("/lag-analysis/{month}")
def get_lag_analysis(month: str, db: Session = Depends(get_db)):
    try:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            result.setdefault("lag_analysis", {})
            return result
        return {"month": month, "lag_analysis": result["data"].get("lag_analysis", {})}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل العلاقات المتأخرة: {str(e)}")


@router.get("/xgboost/{month}")
def get_xgboost(month: str, db: Session = Depends(get_db)):
    try:
        data = _get_smart_data(db, month)["data"]
        xgb = data.get("xgboost")
        if not xgb or not xgb.get("predictions"):
            return {"month": month, "empty": True,
                    "message": "لا توجد تنبؤات كافية لهذا الشهر", "xgboost": None}
        return {"month": month, "xgboost": xgb}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل التنبؤات: {str(e)}")


@router.get("/trend/{hospital_id}")
def get_trend(hospital_id: int, db: Session = Depends(get_db)):
    cache_key = f"smart_trend_{hospital_id}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from app.models import Hospital
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        from app.models import QualityScore
        months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]
        trend_data = []
        for m in months:
            try:
                data = _get_smart_data(db, m)["data"]
                hospital_anomaly = next(
                    (a for a in data["anomalies"] if a["hospital_id"] == hospital_id), None
                )
                if hospital_anomaly:
                    trend_data.append({
                        "month": m,
                        "anomaly_score": hospital_anomaly["anomaly_score"],
                        "severity": hospital_anomaly["severity"],
                        "method_scores": hospital_anomaly["method_scores"],
                    })
            except Exception:
                logger.warning(f"Failed to load trend data for month {m}")
                continue
        response = _sanitize({
            "hospital_id": hospital_id,
            "hospital_name": hospital.name,
            "trend": trend_data,
        })
        cache.set(cache_key, response, ttl=1800)
        return response
    except HTTPException:
        raise
    except Exception as e:
        cache.invalidate(f"smart_trend_{hospital_id}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الاتجاه: {str(e)}")


@router.get("/drilldown/{hospital_id}/{month}")
def get_drilldown(hospital_id: int, month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_drilldown_{hospital_id}_{month}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from app.models import Hospital
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        if month == "all":
            response = _get_drilldown_all_months(db, hospital_id, hospital)
            cache.set(cache_key, response, ttl=1800)
            return response
        data = _get_smart_data(db, month)["data"]
        anomaly = next((a for a in data["anomalies"] if a["hospital_id"] == hospital_id), None)
        explanation = next((e for e in data["explanations"] if e["hospital_id"] == hospital_id), None)
        residuals = [r for r in data["residuals"] if r["hospital_id"] == hospital_id]
        stratified = [s for s in data["stratified"] if s["hospital_id"] == hospital_id]
        from app.engine.smart.lag_analysis import run_hospital_forecast
        forecast = run_hospital_forecast(db, hospital_id, month, data.get("lag_analysis"))
        response = _sanitize({
            "hospital_id": hospital_id,
            "hospital_name": hospital.name,
            "month": month,
            "anomaly": anomaly,
            "explanation": explanation,
            "residuals": residuals,
            "stratified": stratified,
            "forecast": _sanitize(forecast) if forecast else {},
        })
        cache.set(cache_key, response, ttl=1800)
        return response
    except HTTPException:
        raise
    except Exception as e:
        cache.invalidate(f"smart_drilldown_{hospital_id}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل المستشفى: {str(e)}")


def _get_drilldown_all_months(db, hospital_id, hospital):
    from app.models import QualityScore
    months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]

    all_anomalies = []
    all_explanations = []
    for m in months:
        data = _get_smart_data(db, m)["data"]
        anomaly = next((a for a in data["anomalies"] if a["hospital_id"] == hospital_id), None)
        explanation = next((e for e in data["explanations"] if e["hospital_id"] == hospital_id), None)
        if anomaly:
            all_anomalies.append({"month": m, **anomaly})
        if explanation:
            all_explanations.append({"month": m, **explanation})

    return {
        "hospital_id": hospital_id,
        "hospital_name": hospital.name,
        "month": "all",
        "all_months": True,
        "anomalies": all_anomalies,
        "explanations": all_explanations,
        "anomaly": all_anomalies[-1] if all_anomalies else None,
        "explanation": all_explanations[-1] if all_explanations else None,
        "residuals": [],
        "stratified": [],
    }


@router.get("/anomaly-timeline")
def get_anomaly_timeline(db: Session = Depends(get_db)):
    """تطور درجات الشذوذ عبر الأشهر لكل المستشفيات (لرسم متحرك)."""
    try:
        cache_key = f"smart_timeline_{SMART_CACHE_VERSION}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        from app.models import QualityScore
        months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]

        hospital_map = {}
        for m in months:
            envelope = _get_smart_data(db, m)
            # Skip months where computation is still in progress
            if envelope.get("computing") or envelope.get("hospitals_count", 0) == 0:
                continue
            data = envelope["data"]
            for a in data["anomalies"]:
                if a["hospital_id"] not in hospital_map:
                    hospital_map[a["hospital_id"]] = {
                        "hospital_id": a["hospital_id"],
                        "hospital_name": a["hospital_name"],
                        "scores": {},
                        "severities": {},
                    }
                hospital_map[a["hospital_id"]]["scores"][m] = a["anomaly_score"]
                hospital_map[a["hospital_id"]]["severities"][m] = a["severity"]

        hospitals = sorted(hospital_map.values(), key=lambda h: h["hospital_name"])
        # Filter months to only those that have data
        populated_months = sorted(set(m for h in hospital_map.values() for m in h["scores"]))
        response = _sanitize({"months": populated_months or months, "hospitals": hospitals})
        cache.set(cache_key, response, ttl=1800)
        return response
    except Exception as e:
        cache.invalidate("smart_timeline")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الخط الزمني: {str(e)}")


@router.get("/time-overview")
def get_time_overview(db: Session = Depends(get_db)):
    """نظرة زمنية عبر الأشهر: تطور متوسط الدرجة وتوزيع الشدة والمحافظات المتأثرة.

    يُبني من مذكّرات الشهور المخزّنة (نفس مصدر anomaly-timeline) وتُخزَّن
    النتيجة مؤقتاً كاملة تحت مفتاح معنوَّن بالإصدار.
    """
    try:
        cache_key = f"smart_time_overview_{SMART_CACHE_VERSION}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        from app.models import QualityScore
        months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]
        if not months:
            response = {"empty": True, "message": "لا توجد بيانات بعد", "months": []}
            cache.set(cache_key, response, ttl=1800)
            return response

        series = {
            "avg_score": [], "critical_count": [], "warning_count": [],
            "affected_governorates": [],
        }
        populated_months = []
        for m in months:
            envelope = _get_smart_data(db, m)
            # Skip months where computation is still in progress or no data
            if envelope.get("computing") or envelope.get("hospitals_count", 0) == 0:
                continue
            data = envelope["data"]
            kpi = data.get("kpi", {})
            anomalies = data.get("anomalies", [])
            avg = round(sum(a["anomaly_score"] for a in anomalies) / len(anomalies), 3) if anomalies else 0.0
            series["avg_score"].append({"month": m, "value": avg})
            series["critical_count"].append({"month": m, "value": kpi.get("critical_count", 0)})
            series["warning_count"].append({"month": m, "value": kpi.get("warning_count", 0)})
            series["affected_governorates"].append({"month": m, "value": kpi.get("affected_governorates", 0)})
            populated_months.append(m)

        if not populated_months:
            return {"empty": True, "message": "جاري التحليل... أعد المحاولة بعد قليل", "months": months}
        response = _sanitize({"months": populated_months, "series": series})
        cache.set(cache_key, response, ttl=1800)
        return response
    except Exception as e:
        cache.invalidate("smart_time_overview_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الزمني: {str(e)}")


@router.post("/run/{month}")
def trigger_analysis(month: str, db: Session = Depends(get_db)):
    data = _get_smart_data(db, month)
    return {"status": "completed", "month": month, "hospitals_count": data["hospitals_count"]}
