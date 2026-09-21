"""Regression tests: dashboard aggregates must ignore never-analyzed (ghost) rows.

Ghost rows are QualityScore / ConfidenceScore rows persisted for a (hospital,
month) that has no IndicatorValue rows — i.e. months that were never really
analyzed. They used to drag down every KPI card, the trend chart, the ranking
averages, and the hospital scorecard.
"""
import pytest
from fastapi.testclient import TestClient

from app.models import (
    ConfidenceScore,
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    ValidationResult,
)


@pytest.fixture()
def ghost_data(db_session):
    """Hospital 1: one real analyzed month + one ghost month (never analyzed)."""
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "ANC.1").first() or \
        db_session.query(Indicator).first()

    # Real analyzed month: score 90 + indicator values exist
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-01", score=90.0,
                                rule_compliance=90.0, consistency=90.0))
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2026-01",
                                  indicator_id=ind.id, value=10))
    db_session.add(ConfidenceScore(hospital_id=hosp.id, month="2026-01",
                                   overall_confidence=80.0, level="HIGH"))
    # Ghost month: score 0, NO indicator values — must be ignored everywhere
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-02", score=0.0,
                                rule_compliance=0.0, consistency=0.0))
    db_session.add(ConfidenceScore(hospital_id=hosp.id, month="2026-02",
                                   overall_confidence=0.0, level="HIGH"))
    db_session.commit()
    # get_enabled_months reads the shared file cache — other test files may
    # have cached a different month list (house pattern: invalidate after seed)
    from app.cache import cache
    cache.invalidate("analysis:months")
    return hosp.id


def test_kpi_ignores_ghost_months(app, db_session, ghost_data):
    client = TestClient(app)
    r = client.get("/dashboard/kpi").json()
    kpis = {k["id"]: k["value"] for k in r["kpis"]}
    # ghost 2026-02 (0.0) must not drag the average below the real 90.0
    assert kpis["quality_score"] == 90.0
    # confidence likewise: ghost 0.0 ignored, real 80.0 kept
    assert kpis["conf_high"] == 80.0


def test_overview_avg_trend_and_reports_ignore_ghosts(app, db_session, ghost_data):
    client = TestClient(app)
    r = client.get("/dashboard/overview").json()
    # the analyzed month's real score — never (90+0)/2 = 45
    assert r["avg_quality_score"] == 90.0
    # one analyzed (hospital, month) pair — the ghost pair must not count
    assert r["total_reports"] == 1
    # trend shows the analyzed month at its real score, no 0.0 ghost point
    trend = {t["month"]: t["score"] for t in r["quality_trend"]}
    assert trend.get("2026-01") == 90.0
    assert trend.get("2026-02") is None


def test_ranking_ignores_ghost_months(app, db_session, ghost_data):
    client = TestClient(app)
    rows = client.get("/dashboard/ranking").json()
    by_id = {r["id"]: r for r in rows}
    # the hospital has 1 real month (90.0) + 1 ghost (0.0): reports 1, avg 90.0
    assert by_id[ghost_data]["reports"] == 1
    assert by_id[ghost_data]["avg_score"] == 90.0


def test_hospital_performance_ignores_ghost_months(app, db_session, ghost_data):
    client = TestClient(app)
    r = client.get(f"/dashboard/hospital-performance/{ghost_data}").json()
    months = [t["month"] for t in r["quality_trend"]]
    assert "2026-02" not in months          # ghost month not charted
    assert "2026-01" in months
    assert r["avg_score"] == 90.0           # ghost 0.0 not averaged in


def test_diagnostics_ignores_ghost_months(app, db_session, ghost_data):
    client = TestClient(app)
    r = client.get("/dashboard/component-diagnostics").json()
    comps = {c["key"]: c for c in r["components"]}
    # ghost 0.0 rows must not drag component averages down
    assert comps["rule_compliance"]["avg"] == 90.0
    # trend is built from analyzed months only
    trend_months = [t["month"] for t in r["trend"]]
    assert trend_months == ["2026-01"]


def test_diagnostics_range_overrides_year(app, db_session, ghost_data):
    """month_from/month_to must take precedence over ?year= (same as /kpi).

    The drilldown sends both; ANDing them emptied/distorted the drilldown
    whenever the year selector didn't match the selected interval.
    """
    client = TestClient(app)
    # range points at 2026-01 but year says 2027: range must win, data returned
    r = client.get("/dashboard/component-diagnostics?month_from=2026-01&month_to=2026-01&year=2027").json()
    comps = {c["key"]: c for c in r["components"]}
    assert comps["rule_compliance"]["avg"] == 90.0
    # and a year-only query still filters correctly
    r27 = client.get("/dashboard/component-diagnostics?year=2027").json()
    assert r27["components"] == []


def test_months_endpoint_excludes_ghost_months(app, db_session, ghost_data):
    """/analysis/months must list only months with real indicator data.

    The month/year dropdowns across the app feed from this endpoint — it used
    to union QualityScore/ValidationResult/ConfidenceScore/AnomalyResult, so
    zero-score ghost months showed up as selectable options with no data.
    """
    client = TestClient(app)
    months = client.get("/analysis/months").json()
    assert months == ["2026-01"]
    assert "2026-02" not in months  # ghost month: score rows exist, no data


def test_purge_ghost_results_spares_analyzed_zero_scores(db_session):
    """scripts/purge_ghost_results.py must delete only rows whose
    (hospital, month) has no indicator data. An analyzed month whose score is
    legitimately 0 (every rule failed) is real data and must survive — as must
    its ValidationResult/ConfidenceScore companions."""
    from scripts.purge_ghost_results import find_ghosts

    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "ANC.1").first() or \
        db_session.query(Indicator).first()

    # Analyzed month with a legitimate all-zero score + derived companions
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2026-05",
                                  indicator_id=ind.id, value=0))
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-05", score=0.0,
                                rule_compliance=0.0, completeness=0.0,
                                consistency=0.0))
    db_session.add(ValidationResult(hospital_id=hosp.id, month="2026-05",
                                    rule_code="R001", rule_description="Test rule",
                                    status="FAIL", severity="CRITICAL"))
    db_session.add(ConfidenceScore(hospital_id=hosp.id, month="2026-05",
                                   overall_confidence=0.0, level="LOW"))
    # Ghost month: score row only, no indicator data
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-06", score=0.0))
    db_session.commit()

    report = dict(find_ghosts(db_session))
    assert [r.month for r in report["quality_scores"]] == ["2026-06"]
    assert report["validation_results"] == []


def test_purge_ghost_results_catches_malformed_month_rows(db_session):
    """Rows stamped with the synthetic '__all__' month (leaked by the old
    tree All-Months save bug) are flagged by the purge script even when
    indicator data technically exists — a '__all__' month must never exist."""
    from scripts.purge_ghost_results import find_malformed_month_rows

    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "ANC.1").first() or \
        db_session.query(Indicator).first()

    # The poisoned production shape: '__all__' month WITH indicator values
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="__all__",
                                  indicator_id=ind.id, value=10))
    db_session.add(QualityScore(hospital_id=hosp.id, month="__all__", score=50.0))
    # A real month that must NOT be flagged
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2026-07",
                                  indicator_id=ind.id, value=5))
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-07", score=80.0))
    db_session.commit()

    report = find_malformed_month_rows(db_session)
    qs = next(rows for name, rows in report if name == "quality_scores")
    assert [r.month for r in qs] == ["__all__"]
    # no other table has malformed months
    assert all(not rows for name, rows in report if name != "quality_scores")


def test_months_endpoint_filters_malformed_month_values(app, db_session, ghost_data):
    """/analysis/months is the source for every month AND year dropdown — a
    malformed month value (e.g. '__all__') must never reach it, so the year
    dropdown can never show an '__all__' year."""
    from app.cache import cache
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "ANC.1").first() or \
        db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="__all__",
                                  indicator_id=ind.id, value=10))
    db_session.commit()
    cache.invalidate("analysis:months")

    client = TestClient(app)
    months = client.get("/analysis/months").json()
    assert months == ["2026-01"]  # only the real ghost_data month
    assert "__all__" not in months
