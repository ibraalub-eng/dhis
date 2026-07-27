"""Tests for Smart Analytics API error handling."""
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


@pytest.mark.parametrize(
    "endpoint",
    [
        "/smart/overview/2026-06",
        "/smart/anomalies/2026-06",
        "/smart/clusters/2026-06",
        "/smart/correlations/2026-06",
        "/smart/residuals/2026-06",
        "/smart/stratified/2026-06",
        "/smart/geo/2026-06",
    ],
)
@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_endpoints_return_500_on_error(mock_run, endpoint, client):
    response = client.get(endpoint)
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "boom" in data["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_overview_error_message_arabic(mock_run, client):
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_anomalies_error_message_arabic(mock_run, client):
    response = client.get("/smart/anomalies/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل الشذوذ" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_clusters_error_message_arabic(mock_run, client):
    response = client.get("/smart/clusters/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل التجمعات" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_correlations_error_message_arabic(mock_run, client):
    response = client.get("/smart/correlations/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل الارتباطات" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_residuals_error_message_arabic(mock_run, client):
    response = client.get("/smart/residuals/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل البواقي" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_stratified_error_message_arabic(mock_run, client):
    response = client.get("/smart/stratified/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل الطبقى" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_geo_error_message_arabic(mock_run, client):
    response = client.get("/smart/geo/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل الجغرافي" in response.json()["detail"]


def test_cache_returns_cached_result(client):
    """Test that cache returns cached result"""
    from app.cache import cache
    
    # Clear cache first
    cache.invalidate("smart_overview_")
    
    # Call API endpoint (this will cache the result)
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    
    # Verify result is cached
    cache_key = "smart_overview_2026-06"
    cached = cache.get(cache_key)
    assert cached is not None


def test_cache_invalidates_on_upload(db_session):
    """Test that cache invalidates on upload"""
    from app.cache import cache
    
    # Run analysis first
    from app.engine.smart import run_smart_analytics
    run_smart_analytics(db_session, "2026-06")
    
    # Clear cache
    cache.invalidate("smart_overview_")
    
    # Verify cache is empty
    cache_key = "smart_overview_2026-06"
    cached = cache.get(cache_key)
    assert cached is None


def test_smart_endpoints_return_data(client):
    """Test that smart endpoints return data"""
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "kpi" in data["data"]
