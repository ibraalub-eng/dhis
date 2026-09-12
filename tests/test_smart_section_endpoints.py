"""Tests for the new per-section smart analytics endpoints."""
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


def _seed_empty(month):
    """Cache a finished but empty envelope (hospitals_count=0, not computing)."""
    from app.cache import cache
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 0, "computing": False, "data": _data_skeleton()},
        ttl=1800,
    )


def _seed_error(month, detail="boom"):
    """Cache a failed-computation envelope; endpoints surface it as HTTP 500."""
    from app.cache import cache
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 0, "computing": False, "error": True,
         "message": "فشل التحليل الذكي لهذا الشهر", "detail": detail,
         "data": _data_skeleton()},
        ttl=300,
    )


def test_patterns_endpoint_returns_list(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/patterns/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert isinstance(data["patterns"], list)


def test_lag_analysis_endpoint_returns_dict(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/lag-analysis/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "lag_analysis" in data


def test_lag_analysis_empty_month(client):
    _seed_empty("2030-01")
    resp = client.get("/smart/lag-analysis/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True


def test_xgboost_endpoint(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/xgboost/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "xgboost" in data


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_section_endpoints_error_arabic(mock_run, client):
    from app.cache import cache
    cache.invalidate("smart_overview_")
    for path, msg in [
        ("/smart/patterns/2026-06", "خطأ في تحليل الأنماط"),
        ("/smart/lag-analysis/2026-06", "خطأ في تحليل العلاقات المتأخرة"),
        ("/smart/xgboost/2026-06", "خطأ في تحليل التنبؤات"),
    ]:
        _seed_error("2026-06")
        resp = client.get(path)
        assert resp.status_code == 500, path
        assert msg in resp.json()["detail"], path


def test_slice_endpoints_empty_month(client):
    _seed_empty("2030-01")
    for path in [
        "/smart/anomalies/2030-01",
        "/smart/clusters/2030-01",
        "/smart/correlations/2030-01",
        "/smart/residuals/2030-01",
        "/smart/stratified/2030-01",
        "/smart/geo/2030-01",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        data = resp.json()
        assert data.get("empty") is True, path
        assert "لا توجد بيانات" in data.get("message", ""), path


def test_months_endpoint_returns_list(client):
    resp = client.get("/smart/months")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_hospitals_endpoint_returns_id_name_list(client):
    resp = client.get("/smart/hospitals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert set(data[0].keys()) == {"id", "name"}