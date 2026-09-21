"""Regression tests: the Quality Score Trend widget must be immune to the
dashboard's filters (hospital, year, From/To date range) and always show every
analyzed month.

/dashboard/overview narrows its own quality_trend by month_from / month_to /
year / hospital_id so the KPI cards stay consistent with the applied range.
The dedicated /dashboard/trend endpoint instead returns the full all-months
trend with no filters applied — the frontend feeds the Quality Score Trend
chart and the Avg Quality Score sparkline from it.
"""
import pytest
from fastapi.testclient import TestClient

from app.models import Hospital, Indicator, IndicatorValue, QualityScore


@pytest.fixture()
def trend_data(db_session):
    """Two analyzed months (2026-01 score 70, 2027-01 score 90) + a ghost
    month (2026-02, score 0, never analyzed) that must be excluded."""
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "ANC.1").first() or \
        db_session.query(Indicator).first()

    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-01", score=70.0))
    db_session.add(QualityScore(hospital_id=hosp.id, month="2027-01", score=90.0))
    # ghost month: QualityScore row but NO indicator values — never analyzed
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-02", score=0.0))
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2026-01",
                                  indicator_id=ind.id, value=1))
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01",
                                  indicator_id=ind.id, value=1))
    db_session.commit()
    # get_enabled_months reads the shared file cache — invalidate after seed
    from app.cache import cache
    cache.invalidate("analysis:months")
    return hosp.id


def test_trend_returns_all_analyzed_months(app, db_session, trend_data):
    """Every analyzed month appears once, ascending, at its real score; the
    never-analyzed ghost month is excluded."""
    client = TestClient(app)
    r = client.get("/dashboard/trend").json()
    trend = {t["month"]: t["score"] for t in r["quality_trend"]}
    assert list(trend) == ["2026-01", "2027-01"]
    assert trend == {"2026-01": 70.0, "2027-01": 90.0}


def test_trend_ignores_hospital_year_and_date_range(app, db_session, trend_data):
    """No dashboard filter may narrow the trend: hospital, year and From/To
    must all return the identical all-months series."""
    client = TestClient(app)
    baseline = client.get("/dashboard/trend").json()["quality_trend"]
    for params in (
        f"hospital_id={trend_data}",
        "year=2026",
        "month_from=2027-01&month_to=2027-01",
        f"hospital_id={trend_data}&year=2026&month_from=2027-01&month_to=2027-01",
    ):
        r = client.get("/dashboard/trend?" + params).json()
        assert r["quality_trend"] == baseline, f"{params} must not narrow the trend"


def test_overview_trend_still_limited_by_date_range(app, db_session, trend_data):
    """Contrast: /dashboard/overview keeps honoring the range so the drilldown
    modal's Quality Trend stays consistent with the filtered KPI cards."""
    client = TestClient(app)
    r = client.get("/dashboard/overview?month_from=2027-01&month_to=2027-01").json()
    months = [t["month"] for t in r["quality_trend"]]
    assert months == ["2027-01"]


def test_trend_empty_database_returns_empty_list(app, db_session):
    """No quality scores yet must yield an empty series, not a 500."""
    client = TestClient(app)
    r = client.get("/dashboard/trend").json()
    assert r == {"quality_trend": []}
