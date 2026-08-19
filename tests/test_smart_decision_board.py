"""Tests for the smart decision-board endpoint."""
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


def _seed_smart_data(db_session, month="2026-06"):
    """مستشفى نشط بقيم مؤشرات كاملة ليُرجع التحليل hospitals_count > 0."""
    from app.models import Hospital, Indicator, IndicatorValue

    hosp = Hospital(name="Smart Decision Hospital", is_active=True)
    db_session.add(hosp)
    db_session.flush()

    codes = ["2", "5", "6", "10", "11", "17", "7", "6.f", "6.g", "2.n", "2.c", "2.d"]
    inds = {}
    for code in codes:
        existing = db_session.query(Indicator).filter(Indicator.code == code).first()
        if existing:
            inds[code] = existing.id
            continue
        ind = Indicator(code=code, name=f"Ind {code}")
        db_session.add(ind)
        db_session.flush()
        inds[code] = ind.id

    values = {"2": 100.0, "5": 30.0, "6": 90.0, "10": 5.0, "11": 1.0, "17": 2.0,
              "7": 1.0, "6.f": 8.0, "6.g": 6.0, "2.n": 12.0, "2.c": 3.0, "2.d": 2.0}
    for code, val in values.items():
        db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=inds[code], month=month, value=val))
    db_session.commit()
    return hosp, inds


def test_decision_board_returns_subset(client, db_session):
    _seed_smart_data(db_session)
    resp = client.get("/smart/decision-board/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert "kpi" in data
    assert "anomalies" in data
    assert "early_warnings" in data
    assert "healthy_hospitals" in data
    assert "generated_at" in data
    assert data["hospitals_count"] >= 1
    # لا يحمل الحمولة الكاملة الثقيلة
    assert "correlations" not in data
    assert "clustering" not in data


def test_decision_board_empty_month(client):
    """شهر بلا مستشفيات يُرجع empty بدل خطأ خام."""
    resp = client.get("/smart/decision-board/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True
    assert "لا توجد بيانات" in data.get("message", "")


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_decision_board_error_arabic_and_invalidates(mock_run, client):
    from app.cache import cache
    cache.set("smart_overview_2026-06_v3", {"stale": True}, ttl=300)
    resp = client.get("/smart/decision-board/2026-06")
    assert resp.status_code == 500
    assert "خطأ في لوحة القرار" in resp.json()["detail"]
    assert cache.get("smart_overview_2026-06_v3") is None