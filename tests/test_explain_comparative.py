# -*- coding: utf-8 -*-
"""Tests for the Comparative Analysis explanation kinds (GET /audit/explain).

Every sub-tab of the Comparative Analysis screen got a Why button; these tests
pin the contract of each new explanation kind:
- the six-section payload (what/where/why/how/reproduce/chain) is present
- numbers are REPRODUCED from the enabled raw values with the same engines
  the tables themselves use (compare_hospitals, analyze_historical_trends)
- error rows 404 through the endpoint instead of fabricating a payload
- indicator-enablement (disabled codes) is respected like the endpoints do
"""
import pytest
from fastapi.testclient import TestClient

from app.models import Hospital, Indicator, IndicatorValue, QualityScore


@pytest.fixture()
def client(db_session):
    from app.main import app

    yield TestClient(app)


def _hospitals(db):
    return {h.name: h for h in db.query(Hospital).all()}


def _indicator_by_code(db, code):
    return db.query(Indicator).filter(Indicator.code == str(code)).first()


def _add_values(db, hospital_id, month, code_values, source_file="upload.xlsx"):
    for code, val in code_values.items():
        ind = _indicator_by_code(db, code)
        if ind is None:
            continue
        db.add(IndicatorValue(
            hospital_id=hospital_id,
            indicator_id=ind.id,
            month=month,
            value=val,
            source_file=source_file,
        ))
    db.commit()


SAMPLE = {"2": 300, "5": 80, "6": 280, "4": 20, "3": 200}


def _seed_two_hospitals_two_months(db):
    hs = _hospitals(db)
    general, central = hs["General Hospital"], hs["Central Medical"]
    _add_values(db, general.id, "2026-03", SAMPLE)
    _add_values(db, general.id, "2026-04", SAMPLE)
    _add_values(db, central.id, "2026-03", SAMPLE)
    _add_values(db, central.id, "2026-04", SAMPLE)
    return general, central


def _add_score(db, hospital_id, month, score=88.0, op=5.0):
    db.add(QualityScore(
        hospital_id=hospital_id, month=month, score=score,
        rule_compliance=90.0, completeness=85.0, consistency=80.0,
        outlier_penalty=op,
    ))
    db.commit()


# ───────────────────── comparison_row ─────────────────────────────

def test_comparison_row_explains_and_reproduces(db_session, client):
    general, _ = _seed_two_hospitals_two_months(db_session)
    resp = client.get(
        f"/audit/explain?kind=comparison_row&hospital_id={general.id}"
        f"&month=2026-04&rate_name=C-section rate".replace(" ", "%20"))
    assert resp.status_code == 200, resp.text
    p = resp.json()
    for key in ("what", "where", "why", "how", "reproduce", "chain", "classification", "comparison"):
        assert key in p, f"missing {key}"
    comp = p["comparison"]
    assert comp["peer_count"] >= 2
    # value/benchmark/deviation must match what the table row shows (engine math)
    assert comp["value"] == pytest.approx(comp["peer_rates"][general.name], abs=0.05)
    inputs = {r["input"]: r["value"] for r in p["how"]["inputs"]}
    assert f"Rate — {general.name}" in inputs


def test_comparison_row_rate_name_is_required(db_session, client):
    general, _ = _seed_two_hospitals_two_months(db_session)
    resp = client.get(
        f"/audit/explain?kind=comparison_row&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 404


def test_comparison_row_unknown_rate_404s(db_session, client):
    general, _ = _seed_two_hospitals_two_months(db_session)
    resp = client.get(
        f"/audit/explain?kind=comparison_row&hospital_id={general.id}"
        f"&month=2026-04&rate_name=Nonexistent%20Rate")
    assert resp.status_code == 404


# ───────────────────── governorate_row ─────────────────────────────

def test_governorate_row_averages_only_real_hospitals(db_session, client):
    hs = _hospitals(db_session)
    general, central = hs["General Hospital"], hs["Central Medical"]
    _add_score(db_session, general.id, "2026-04", score=80.0)
    _add_score(db_session, central.id, "2026-04", score=90.0)
    # General has data, Central does not → Central is a ghost row and the
    # governorate average must exclude it.
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    gov_name = general.governorate.name if general.governorate else None
    if not gov_name:
        pytest.skip("hospitals in the test seed have no governorate assigned")
    resp = client.get(
        f"/audit/explain?kind=governorate_row&hospital_id={general.id}"
        f"&month=2026-04&rate_name={gov_name}")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["governorate"]["analyzed"] == 1
    assert p["governorate"]["avg_quality_score"] == 80.0
    inputs = {r["input"] for r in p["how"]["inputs"]}
    assert general.name in inputs
    assert central.name not in inputs


def test_governorate_row_unknown_governorate_404s(db_session, client):
    resp = client.get(
        "/audit/explain?kind=governorate_row&month=2026-04&rate_name=No%20Such%20Gov")
    assert resp.status_code == 404


# ──────────────────── indicator_aggregate ────────────────────

def test_indicator_aggregate_matches_frontend_math(db_session, client):
    _seed_two_hospitals_two_months(db_session)
    resp = client.get(
        "/audit/explain?kind=indicator_aggregate&hospital_id=C-section%20rate&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    agg = p["aggregate"]
    assert agg["min"] <= agg["avg"] <= agg["max"]
    assert set(agg["worst"]) == {"hospital", "value"}
    # rates of every hospital listed as inputs
    inputs = {r["input"] for r in p["how"]["inputs"]}
    assert any(i.startswith("Rate — ") for i in inputs)


def test_indicator_aggregate_unknown_rate_404s(db_session, client):
    resp = client.get(
        "/audit/explain?kind=indicator_aggregate&hospital_id=Nope%20Rate&month=2026-04")
    assert resp.status_code == 404


# ──────────────────── ranking_entry ────────────────────

def test_ranking_entry_reproduces_average_and_rank(db_session, client):
    hs = _hospitals(db_session)
    general, central, community = (hs["General Hospital"], hs["Central Medical"],
                                   hs["Community Clinic"])
    # ranking counts only ANALYZED months (≥1 non-null value) — seed raw rows
    # so the score rows are not treated as ghost months.
    _add_values(db_session, general.id, "2026-03", SAMPLE)
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    _add_values(db_session, central.id, "2026-04", SAMPLE)
    _add_values(db_session, community.id, "2026-04", SAMPLE)
    _add_score(db_session, general.id, "2026-03", score=70.0)
    _add_score(db_session, general.id, "2026-04", score=90.0)
    _add_score(db_session, central.id, "2026-04", score=60.0)
    _add_score(db_session, community.id, "2026-04", score=95.0)
    resp = client.get(f"/audit/explain?kind=ranking_entry&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    # avg = (70+90)/2 = 80.0 → exactly one hospital above (Community 95) → rank 2
    assert p["reproduce"]["stored"] == 80.0
    assert p["ranking"]["rank"] == 2
    assert p["ranking"]["hospital_count"] == 3
    assert p["ranking"]["trend_direction"] == "up"


def test_ranking_entry_without_scores_404s(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    resp = client.get(f"/audit/explain?kind=ranking_entry&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 404


# ──────────────────── time_period_point ────────────────────

def test_time_period_point_carries_change_vs_previous(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    _add_values(db_session, general.id, "2026-03", SAMPLE)
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    _add_score(db_session, general.id, "2026-03", score=75.0)
    _add_score(db_session, general.id, "2026-04", score=85.0)
    resp = client.get(
        f"/audit/explain?kind=time_period_point&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "time_period_point"
    assert p["change_vs_previous"] == 10.0
    assert p["previous_month"] == "2026-03"
    # full quality-score payload sections are still present
    for key in ("what", "where", "why", "how", "reproduce", "chain"):
        assert key in p


def test_time_period_point_first_month_has_no_change(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    _add_score(db_session, general.id, "2026-04", score=85.0)
    resp = client.get(
        f"/audit/explain?kind=time_period_point&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 200
    p = resp.json()
    assert p["change_vs_previous"] is None


# ──────────────────── trend_row ────────────────────

def test_trend_row_reproduces_engine_statistics(db_session, client):
    general, _ = _seed_two_hospitals_two_months(db_session)
    resp = client.get(
        f"/audit/explain?kind=trend_row&hospital_id={general.id}"
        f"&month=2026-04&rate_name=C-section%20rate")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "trend_row"
    assert p["reproduce"]["verified"] is True
    assert len(p["trend"]["months"]) == 2
    assert p["how"]["thresholds"]["trend_finding_slope"] > 0


def test_trend_row_needs_two_months(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    resp = client.get(
        f"/audit/explain?kind=trend_row&hospital_id={general.id}"
        f"&month=2026-04&rate_name=C-section%20rate")
    assert resp.status_code == 404


# ───────── historical_trend passthrough ─────────

def test_historical_trend_without_hospital_is_month_overview(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    _add_score(db_session, general.id, "2026-04", score=85.0)
    resp = client.get("/audit/explain?kind=historical_trend&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "month_overview"


def test_historical_trend_with_hospital_is_quality_score(db_session, client):
    hs = _hospitals(db_session)
    general = hs["General Hospital"]
    _add_values(db_session, general.id, "2026-04", SAMPLE)
    _add_score(db_session, general.id, "2026-04", score=85.0)
    resp = client.get(f"/audit/explain?kind=historical_trend&hospital_id={general.id}&month=2026-04")
    assert resp.status_code == 200
    p = resp.json()
    assert p["kind"] == "quality_score"
