import math
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.database import get_db
from app.engine.smart import run_smart_analytics
from app.engine.smart.schemas import SmartAnalyticsResult

router = APIRouter(prefix="/smart", tags=["Smart Analytics"])


def _sanitize(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _envelope(result: SmartAnalyticsResult) -> dict:
    data = {
        "kpi": result.kpi.__dict__,
        "anomalies": [a.__dict__ for a in result.anomalies],
        "clustering": result.clustering.__dict__ if result.clustering else None,
        "correlations": result.correlations.__dict__ if result.correlations else None,
        "residuals": [r.__dict__ for r in result.residuals],
        "stratified": [s.__dict__ for s in result.stratified],
        "explanations": [
            {**e.__dict__, "top_factors": [f.__dict__ for f in e.top_factors]}
            for e in result.explanations
        ],
        "geo": {
            "governorates": [g.__dict__ for g in result.geo.governorates],
        } if result.geo else None,
    }

    if result.xgboost_predictions:
        xgb = result.xgboost_predictions
        data["xgboost"] = {
            "model_r2": xgb.model_r2,
            "model_mae": xgb.model_mae,
            "training_months": xgb.training_months,
            "hospitals_trained": xgb.hospitals_trained,
            "accuracy_note": xgb.accuracy_note,
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


@router.get("/overview/{month}")
def get_overview(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_overview_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        response = _envelope(result)
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل: {str(e)}")


@router.get("/governorate-analysis/{month}")
def get_governorate_analysis(month: str, db: Session = Depends(get_db)):
    from app.engine.smart.governorate_analysis import analyze_governorate_correlations
    from app.engine.smart import _load_hospital_data

    all_data = _load_hospital_data(db, month)
    if not all_data:
        return _sanitize({"governorate_profiles": [], "cross_governorate_correlations": [], "indicator_governorate_heatmap": {}, "xgboost_insights": {}})

    result = analyze_governorate_correlations(all_data, {})
    return _sanitize(result)


@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_anomalies_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "anomalies": data["anomalies"], "explanations": data["explanations"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_anomalies_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الشذوذ: {str(e)}")


@router.get("/clusters/{month}")
def get_clusters(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_clusters_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "clustering": data["clustering"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_clusters_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل التجمعات: {str(e)}")


@router.get("/correlations/{month}")
def get_correlations(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_correlations_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "correlations": data["correlations"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_correlations_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الارتباطات: {str(e)}")


@router.get("/residuals/{month}")
def get_residuals(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_residuals_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "residuals": data["residuals"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_residuals_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل البواقي: {str(e)}")


@router.get("/stratified/{month}")
def get_stratified(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_stratified_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "stratified": data["stratified"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_stratified_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الطبقى: {str(e)}")


@router.get("/geo/{month}")
def get_geo(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_geo_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "geo": data["geo"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_geo_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الجغرافي: {str(e)}")


@router.get("/trend/{hospital_id}")
def get_trend(hospital_id: int, db: Session = Depends(get_db)):
    from app.models import Hospital

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    from app.models import QualityScore
    months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]

    trend_data = []
    for m in months:
        result = run_smart_analytics(db, m)
        hospital_anomaly = next(
            (a for a in result.anomalies if a.hospital_id == hospital_id), None
        )
        if hospital_anomaly:
            trend_data.append({
                "month": m,
                "anomaly_score": hospital_anomaly.anomaly_score,
                "severity": hospital_anomaly.severity,
                "method_scores": hospital_anomaly.method_scores,
            })

    return {"hospital_id": hospital_id, "hospital_name": hospital.name, "trend": trend_data}


@router.get("/drilldown/{hospital_id}/{month}")
def get_drilldown(hospital_id: int, month: str, db: Session = Depends(get_db)):
    from app.models import Hospital

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    if month == "all":
        return _get_drilldown_all_months(db, hospital_id, hospital)

    result = run_smart_analytics(db, month)
    anomaly = next((a for a in result.anomalies if a.hospital_id == hospital_id), None)
    explanation = next((e for e in result.explanations if e.hospital_id == hospital_id), None)
    residuals = [r for r in result.residuals if r.hospital_id == hospital_id]
    stratified = [s for s in result.stratified if s.hospital_id == hospital_id]

    return {
        "hospital_id": hospital_id,
        "hospital_name": hospital.name,
        "month": month,
        "anomaly": anomaly.__dict__ if anomaly else None,
        "explanation": {
            **explanation.__dict__,
            "top_factors": [f.__dict__ for f in explanation.top_factors],
        } if explanation else None,
        "residuals": [r.__dict__ for r in residuals],
        "stratified": [s.__dict__ for s in stratified],
    }


def _get_drilldown_all_months(db, hospital_id, hospital):
    from app.models import QualityScore
    months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]

    all_anomalies = []
    all_explanations = []
    for m in months:
        result = run_smart_analytics(db, m)
        anomaly = next((a for a in result.anomalies if a.hospital_id == hospital_id), None)
        explanation = next((e for e in result.explanations if e.hospital_id == hospital_id), None)
        if anomaly:
            all_anomalies.append({"month": m, **anomaly.__dict__})
        if explanation:
            all_explanations.append({"month": m, **explanation.__dict__, "top_factors": [f.__dict__ for f in explanation.top_factors]})

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


@router.post("/run/{month}")
def trigger_analysis(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    return {"status": "completed", "month": month, "hospitals_count": result.hospitals_count}
