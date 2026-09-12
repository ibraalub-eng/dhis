"""Tests for the smart time-overview endpoint."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _data_skeleton():
    return {
        "kpi": {}, "anomalies": [], "clustering": None,
        "correlations": [], "residuals": [],
        "stratified": [], "explanations": [],
        "geo": None, "patterns": [],
        "lag_analysis": {}, "early_warnings": [],
        "healthy_hospitals": [], "xgboost": None,
    }


def _seed_overview_with_data(month):
    """Cache a computed envelope (hospitals_count>=1 + anomaly) so series is populated."""
    from app.cache import cache
    data = _data_skeleton()
    data["kpi"] = {
        "total_anomalies": 1, "critical_count": 1, "warning_count": 0,
        "affected_governorates": 1, "top_contributing_factor": "CS",
        "month_status": "critical",
    }
    data["anomalies"] = [
        {"hospital_id": 1, "hospital_name": "Test Hospital", "governorate": "Gaza",
         "hospital_type": "general", "anomaly_score": 0.8, "severity": "critical",
         "is_outlier": True,
         "method_scores": {"isolation_forest": 0.5, "lof": 0.5, "mahalanobis": 0.5, "residual": 0.5}},
    ]
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 1, "data": data},
        ttl=1800,
    )


def _seed_error(month, detail="boom"):
    """Cache a failed-computation envelope; the endpoint surfaces it as HTTP 500."""
    from app.cache import cache
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 0, "computing": False, "error": True,
         "message": "فشل التحليل الذكي لهذا الشهر", "detail": detail,
         "data": _data_skeleton()},
        ttl=300,
    )


def test_time_overview_structure(client, db_session):
    from app.cache import cache
    _seed_month(db_session)
    cache.invalidate("smart_overview_")
    cache.invalidate("smart_time_overview_")
    _seed_overview_with_data("2026-06")
    resp = client.get("/smart/time-overview")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("months"), list)
    assert "series" in data
    assert "avg_score" in data["series"]
    assert "critical_count" in data["series"]
    assert "warning_count" in data["series"]
    assert "affected_governorates" in data["series"]


def _seed_month(db_session, month="2026-06"):
    """إضافة صف جودة ليظهر الشهر في قائمة الأشهر المميزة."""
    from app.models import Hospital, QualityScore
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month=month, score=70))
    db_session.commit()


def test_time_overview_cached(client):
    from app.cache import cache
    cache.invalidate("smart_time_overview_")
    client.get("/smart/time-overview")
    assert any(k.startswith("smart_time_overview_") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_time_overview_error_arabic(mock_run, client, db_session):
    from app.cache import cache
    _seed_month(db_session)
    cache.invalidate("smart_overview_")
    cache.invalidate("smart_time_overview_")
    _seed_error("2026-06")
    resp = client.get("/smart/time-overview")
    assert resp.status_code == 500
    assert "خطأ في التحليل الزمني" in resp.json()["detail"]