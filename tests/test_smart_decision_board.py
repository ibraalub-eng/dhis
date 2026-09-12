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


def _cache_smart_overview(db_session, month):
    """Run the real smart pipeline on the fixture DB and cache its envelope."""
    from app.cache import cache
    from app.engine.smart import run_smart_analytics
    from app.engine.smart.lag_analysis import run_lag_analysis, run_early_warnings
    from app.api.smart_analytics import _envelope, _healthy_hospitals, _sanitize
    result = run_smart_analytics(db_session, month)
    response = _envelope(result)
    anomalies = response["data"]["anomalies"]
    try:
        response["data"]["healthy_hospitals"] = _healthy_hospitals(db_session, month, anomalies)
    except Exception:
        response["data"]["healthy_hospitals"] = []
    try:
        lag_results = run_lag_analysis(db_session, month)
        response["data"]["lag_analysis"] = _sanitize(lag_results)
        response["data"]["early_warnings"] = _sanitize(run_early_warnings(db_session, month, lag_results))
    except Exception:
        response["data"]["lag_analysis"] = {}
        response["data"]["early_warnings"] = []
    cache.set(f"smart_overview_{month}_v3", response, ttl=1800)
    return response


def test_decision_board_returns_subset(client, db_session):
    from app.cache import cache
    _seed_smart_data(db_session)
    cache.invalidate("smart_overview_")
    _cache_smart_overview(db_session, "2026-06")
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
    _seed_empty("2030-01")
    resp = client.get("/smart/decision-board/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True
    assert "لا توجد بيانات" in data.get("message", "")


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_decision_board_error_arabic_and_invalidates(mock_run, client):
    from app.cache import cache
    _seed_error("2026-06")
    resp = client.get("/smart/decision-board/2026-06")
    assert resp.status_code == 500
    assert "خطأ في لوحة القرار" in resp.json()["detail"]
    assert cache.get("smart_overview_2026-06_v3") is None