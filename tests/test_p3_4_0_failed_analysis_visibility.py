"""P3.4.0 — failed-analysis identity is honoured by every consumer.

The pipeline persists a fallback ``QualityScore`` row when an analysis fails
(``is_fallback_quality_row``). Those rows are failures, not results: they must
never be averaged into dashboard KPIs/trends/rankings/peer populations, and
the Reports API must say so explicitly instead of serving score 0 as success.

Contract pinned here:
* report list/detail: stored fallback → ``failed`` / ``stored_fallback``;
  a genuine row (including a genuine zero) → ``ok``;
* detail with no stored row keeps the live run's own status/failure kind;
* dashboard mixed population (80 + fallback) averages to 80;
* a genuine successful zero-score result stays included;
* the excluded count is exposed and identical across dashboard sections;
* the ghost-row eligibility gate is unchanged;
* the list cache key was bumped so pre-change payloads cannot be served;
* the frontend consumers render an explicit failed state.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.engine import pipeline
from app.models import Hospital, Indicator, IndicatorValue, QualityScore

FALLBACK_ISSUES = json.dumps([pipeline.FALLBACK_ANALYSIS_ISSUE])
GENUINE_ISSUE = "R001: Total deliveries below the sum of children"
STATIC = Path(__file__).resolve().parents[1] / "static"


def _hospital(db, index=0):
    return db.query(Hospital).offset(index).first()


def _add_month(db, hospital, month, score, issues=None):
    """One analyzed hospital-month: an IndicatorValue plus its stored score."""
    ind = db.query(Indicator).first()
    db.add(IndicatorValue(hospital_id=hospital.id, month=month,
                          indicator_id=ind.id, value=10))
    db.add(QualityScore(
        hospital_id=hospital.id, month=month, score=score,
        rule_compliance=score, consistency=score, completeness=100.0,
        outlier_penalty=0.0, issues=issues,
    ))
    db.commit()


def _fallback(db, hospital, month):
    _add_month(db, hospital, month, 0, FALLBACK_ISSUES)


def _genuine(db, hospital, month, score):
    _add_month(db, hospital, month, score,
               json.dumps([GENUINE_ISSUE]) if score == 0 else None)


# ── 1-3: stored fallback in list / detail, genuine rows stay ok ─────────────
def test_report_list_identifies_stored_fallback(app, db_session):
    hospital = _hospital(db_session)
    _fallback(db_session, hospital, "2026-09")

    items = TestClient(app).get("/reports/", params={"hospital_id": hospital.id}).json()
    item = next(i for i in items if i["month"] == "2026-09")

    assert item["analysis_status"] == "failed"
    assert item["failure_kind"] == "stored_fallback"
    # The stored number is still carried (additive contract), but it is
    # explicitly labelled as a failure by the status fields.
    assert item["data_quality_score"] == 0


def test_report_list_keeps_genuine_zero_ok(app, db_session):
    hospital = _hospital(db_session)
    _genuine(db_session, hospital, "2026-10", 0)

    items = TestClient(app).get("/reports/", params={"hospital_id": hospital.id}).json()
    item = next(i for i in items if i["month"] == "2026-10")

    assert item["analysis_status"] == "ok"
    assert item["failure_kind"] is None
    assert item["data_quality_score"] == 0


def test_report_detail_identifies_stored_fallback(app, db_session):
    hospital = _hospital(db_session)
    _fallback(db_session, hospital, "2026-11")

    detail = TestClient(app).get(
        f"/reports/detail/{hospital.id}", params={"month": "2026-11"}).json()

    assert detail["analysis_status"] == "failed"
    assert detail["failure_kind"] == "stored_fallback"
    assert detail["data_quality_score"] == 0


# ── 4: live no-row detail keeps the run's own failure identity ──────────────
def test_report_detail_preserves_live_failure_kind(app, db_session, monkeypatch):
    from app.engine.config_resolver import PolicyUnavailable

    hospital = _hospital(db_session)
    ind = db_session.query(Indicator).first()
    # Analyzed data, but deliberately NO stored QualityScore row.
    db_session.add(IndicatorValue(hospital_id=hospital.id, month="2026-12",
                                  indicator_id=ind.id, value=10))
    db_session.commit()

    def boom(_db, **_kwargs):
        raise PolicyUnavailable("configuration store unavailable")

    monkeypatch.setattr(pipeline, "load_policy_snapshot", boom)

    detail = TestClient(app).get(
        f"/reports/detail/{hospital.id}", params={"month": "2026-12"}).json()

    assert detail["analysis_status"] == "failed"
    assert detail["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE
    assert detail["failure_kind"] != pipeline.FAILURE_STORED_FALLBACK


# ── 5-6: dashboard population excludes failures, genuine zeros stay ─────────
def test_dashboard_mixed_population_averages_only_valid_rows(app, db_session):
    hospital = _hospital(db_session)
    _genuine(db_session, hospital, "2027-03", 80)
    _fallback(db_session, hospital, "2027-04")

    overview = TestClient(app).get(
        "/dashboard/overview", params={"hospital_id": hospital.id}).json()
    kpi = TestClient(app).get(
        "/dashboard/kpi", params={"hospital_id": hospital.id}).json()

    assert overview["avg_quality_score"] == 80.0
    assert overview["total_reports"] == 1
    assert overview["excluded_failed_analysis"] == 1
    # The trend carries only the measured month.
    assert [p["month"] for p in overview["quality_trend"]] == ["2027-03"]
    assert [p["score"] for p in overview["quality_trend"]] == [80.0]
    # Hospital comparison is built from the same valid population.
    row = next(r for r in overview["hospital_compare"] if r["id"] == hospital.id)
    assert row["avg_score"] == 80.0
    assert row["report_count"] == 1
    # The KPI card and its excluded count agree with /overview.
    cards = {k["id"]: k for k in kpi["kpis"]}
    assert cards["quality_score"]["value"] == 80.0
    assert kpi["excluded_failed_analysis"] == overview["excluded_failed_analysis"]


def test_dashboard_genuine_zero_score_remains_included(app, db_session):
    hospital = _hospital(db_session)
    _genuine(db_session, hospital, "2027-05", 0)

    overview = TestClient(app).get(
        "/dashboard/overview", params={"hospital_id": hospital.id}).json()
    kpi = TestClient(app).get(
        "/dashboard/kpi", params={"hospital_id": hospital.id}).json()

    assert overview["avg_quality_score"] == 0.0
    assert overview["total_reports"] == 1
    assert overview["excluded_failed_analysis"] == 0
    cards = {k["id"]: k for k in kpi["kpis"]}
    assert cards["quality_score"]["value"] == 0.0
    assert kpi["has_data"] is True


# ── 7-8: cached payloads and the contract-version bump ──────────────────────
def test_cached_fallback_payload_stays_failed(app, db_session):
    hospital = _hospital(db_session)
    _fallback(db_session, hospital, "2027-06")

    client = TestClient(app)
    first = client.get("/reports/", params={"hospital_id": hospital.id}).json()
    second = client.get("/reports/", params={"hospital_id": hospital.id}).json()

    for payload in (first, second):
        item = next(i for i in payload if i["month"] == "2027-06")
        assert item["analysis_status"] == "failed"
        assert item["failure_kind"] == "stored_fallback"


def test_report_list_cache_key_carries_new_contract(app, db_session):
    """A payload cached under the old vue lacks the failure identity.

    The key was bumped to v6, and every served payload must carry the fields —
    including the second (cache-hit) call.
    """
    from app.api import reports as reports_api

    source = inspect.getsource(reports_api.list_reports)
    assert '"reports:list_v6"' in source
    assert '"reports:list_v5"' not in source

    hospital = _hospital(db_session)
    _fallback(db_session, hospital, "2027-07")
    client = TestClient(app)
    client.get("/reports/", params={"hospital_id": hospital.id})
    cached = client.get("/reports/", params={"hospital_id": hospital.id}).json()
    item = next(i for i in cached if i["month"] == "2027-07")
    assert "analysis_status" in item and "failure_kind" in item
    assert item["analysis_status"] == "failed"


# ── 9: the ghost-row gate itself is unchanged ───────────────────────────────
def test_ghost_rows_are_still_excluded_and_not_counted_as_failures(app, db_session):
    hospital = _hospital(db_session)
    # A stored score with NO IndicatorValue is a ghost row, not a fallback.
    db_session.add(QualityScore(hospital_id=hospital.id, month="2027-08",
                                score=15.0, rule_compliance=15.0,
                                consistency=15.0, completeness=0.0,
                                outlier_penalty=0.0, issues=None))
    db_session.commit()

    overview = TestClient(app).get(
        "/dashboard/overview", params={"hospital_id": hospital.id}).json()
    kpi = TestClient(app).get(
        "/dashboard/kpi", params={"hospital_id": hospital.id}).json()

    assert overview["avg_quality_score"] is None
    assert overview["total_reports"] == 0
    assert overview["excluded_failed_analysis"] == 0
    assert kpi["has_data"] is False


# ── 10: frontend consumers render an explicit failed state ──────────────────
def test_frontend_consumers_render_failure_state():
    upload = (STATIC / "js" / "upload.js").read_text(encoding="utf-8")
    rules = (STATIC / "js" / "rules-manager.js").read_text(encoding="utf-8")
    dashboard = (STATIC / "tabs" / "dashboard.html").read_text(encoding="utf-8")
    i18n = (STATIC / "js" / "i18n.js").read_text(encoding="utf-8")

    # Report list + detail: status-driven failure UI, never score-as-result.
    assert "r.analysis_status === 'failed'" in upload
    assert "analysis-failed-banner" in upload
    assert "The stored score is a failed-analysis placeholder" in upload
    # Dashboard: the excluded count is shown.
    assert "excluded_failed_analysis" in rules
    assert 'id="dashExcludedFailed"' in dashboard
    # Arabic/RTL translation exists for the new labels.
    assert "'Analysis failed': 'فشل التحليل'" in i18n
