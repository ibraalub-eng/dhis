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


def test_time_overview_structure(client, db_session):
    _seed_month(db_session)
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
    resp = client.get("/smart/time-overview")
    assert resp.status_code == 500
    assert "خطأ في التحليل الزمني" in resp.json()["detail"]