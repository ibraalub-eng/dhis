"""A disabled hospital/month is one rule everywhere.

Months switched off in month settings must disappear from every active
dashboard/report/export/drilldown, stay available in the explicitly documented
historical/audit views, and never be deleted. Re-enabling must restore them
without rebuilding the score rows.
"""
import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.eligibility import disabled_pairs, month_disabled, parse_month_setting
from app.models import (
    AnomalyResult,
    AppConfig,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
    QualityScore,
    Rule,
    SystemSetting,
    ValidationResult,
)


def _seed_scores(db, hospital_id, months, indicator):
    for month, score in months.items():
        db.add(QualityScore(
            hospital_id=hospital_id,
            month=month,
            score=score,
            rule_compliance=score,
            completeness=score,
            consistency=score,
            outlier_penalty=0.0,
        ))
        db.add(IndicatorValue(
            hospital_id=hospital_id,
            month=month,
            indicator_id=indicator.id,
            value=10,
        ))
    db.commit()
    cache.invalidate()


@pytest.fixture()
def disabled_scores(db_session):
    """Hospital 1: January active, February disabled AFTER both scores exist."""
    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    ind = db_session.query(Indicator).order_by(Indicator.id).first()
    _seed_scores(db_session, hosp.id, {"2026-01": 90.0, "2026-02": 20.0}, ind)
    db_session.add(SystemSetting(key=f"month_enabled_{hosp.id}_2026-02", value="false"))
    db_session.commit()
    cache.invalidate()
    return {"hospital_id": hosp.id, "indicator_id": ind.id}


def _score_count(db, hospital_id):
    return (
        db.query(QualityScore)
        .filter(QualityScore.hospital_id == hospital_id)
        .count()
    )


def test_rule_parser_only_accepts_real_hospital_months():
    assert parse_month_setting("month_enabled_7_2026-02") == (7, "2026-02")
    assert parse_month_setting("month_enabled_7_all") is None
    assert parse_month_setting("month_enabled_x_2026-02") is None
    assert parse_month_setting("month_enabled_7_2026-13") is None
    assert parse_month_setting("unrelated") is None


def test_shared_rule_identifies_only_the_exact_pair(db_session, disabled_scores):
    hid = disabled_scores["hospital_id"]
    pairs = disabled_pairs(db_session)
    assert (hid, "2026-02") in pairs
    assert month_disabled(db_session, hid, "2026-02", pairs=pairs)
    assert not month_disabled(db_session, hid, "2026-01", pairs=pairs)
    assert not month_disabled(db_session, hid + 1, "2026-02", pairs=pairs)


def test_dashboard_readers_exclude_disabled_month(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]

    kpi = client.get("/dashboard/kpi", params={"hospital_id": hid}).json()
    assert {k["id"]: k["value"] for k in kpi["kpis"]}["quality_score"] == 90.0

    overview = client.get("/dashboard/overview", params={"hospital_id": hid}).json()
    assert overview["avg_quality_score"] == 90.0
    assert overview["total_reports"] == 1
    assert [p["month"] for p in overview["quality_trend"]] == ["2026-01"]

    trend = client.get("/dashboard/trend").json()["quality_trend"]
    assert [p["month"] for p in trend] == ["2026-01"]

    ranking = {r["id"]: r for r in client.get("/dashboard/ranking").json()}
    assert ranking[hid]["reports"] == 1
    assert ranking[hid]["avg_score"] == 90.0

    performance = client.get(f"/dashboard/hospital-performance/{hid}").json()
    assert [p["month"] for p in performance["quality_trend"]] == ["2026-01"]
    assert performance["avg_score"] == 90.0

    diagnostics = client.get(
        "/dashboard/component-diagnostics", params={"hospital_id": hid}
    ).json()
    assert [p["month"] for p in diagnostics["trend"]] == ["2026-01"]


def test_disabling_one_hospital_does_not_hide_the_month_for_peers(app, db_session, disabled_scores):
    """Eligibility is a PAIR, not a global month switch.

    Hospital 19's February is disabled; hospital 2 still reports February and
    must stay visible in the network trend, heatmap and report list.
    """
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]
    peer = db_session.query(Hospital).filter(Hospital.id != hid).first()
    ind = db_session.query(Indicator).filter(Indicator.id == disabled_scores["indicator_id"]).one()
    _seed_scores(db_session, peer.id, {"2026-02": 70.0}, ind)

    reports = client.get("/reports/").json()
    by_pair = {(r["hospital"], r["month"]): r for r in reports}
    assert any(month == "2026-02" for (_name, month) in by_pair)
    assert by_pair[(peer.name, "2026-02")]["is_enabled"] is True

    trend = {p["month"]: p["score"] for p in client.get("/dashboard/trend").json()["quality_trend"]}
    assert trend["2026-02"] == 70.0  # disabled hospital row excluded, peer kept

    heatmap = client.get("/analysis/heatmap").json()
    disabled_row = next(r for r in heatmap["data"] if r["hospital_id"] == hid)
    peer_row = next(r for r in heatmap["data"] if r["hospital_id"] == peer.id)
    assert disabled_row["2026-02"] is None
    assert peer_row["2026-02"] == 70.0

    peer_trend = client.get(f"/analysis/quality-trend/{peer.id}").json()
    assert [p["month"] for p in peer_trend["data"]] == ["2026-02"]
    assert peer_trend["data"][0]["peer_avg"] == 70.0  # the disabled row cannot pull it


def test_report_trend_and_heatmap_readers_agree(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]

    reports = client.get("/reports/", params={"hospital_id": hid}).json()
    assert [r["month"] for r in reports] == ["2026-01"]
    assert all(r["is_enabled"] for r in reports)

    trend = client.get(f"/analysis/quality-trend/{hid}").json()
    assert [p["month"] for p in trend["data"]] == ["2026-01"]
    assert trend["current_score"] == 90.0

    heatmap = client.get("/analysis/heatmap").json()
    row = next(r for r in heatmap["data"] if r["hospital_id"] == hid)
    assert row["2026-01"] == 90.0
    assert row["2026-02"] is None


def test_active_detail_generate_export_and_drilldowns_reject_disabled_month(
    app, db_session, disabled_scores
):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]
    before = _score_count(db_session, hid)

    for url in (
        f"/reports/detail/{hid}",
        f"/reports/generate/{hid}",
        f"/reports/export/{hid}/excel",
        f"/reports/export/{hid}/pdf",
        f"/clinical/{hid}",
        f"/root-cause/{hid}/timeline",
        f"/root-cause/{hid}",
    ):
        response = client.get(url, params={"month": "2026-02"})
        assert response.status_code == 404, (url, response.status_code, response.text)
        assert "disabled" in response.json()["detail"].lower()

    # Rejecting an active request must not rewrite or delete stored evidence.
    assert _score_count(db_session, hid) == before


def test_historical_view_returns_disabled_rows_without_deleting(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]
    before = _score_count(db_session, hid)

    reports = client.get(
        "/reports/", params={"hospital_id": hid, "include_disabled": "true"}
    ).json()
    by_month = {r["month"]: r for r in reports}
    assert set(by_month) == {"2026-01", "2026-02"}
    assert by_month["2026-01"]["is_enabled"] is True
    assert by_month["2026-02"]["is_enabled"] is False
    assert by_month["2026-02"]["data_quality_score"] == 20.0

    detail = client.get(
        f"/reports/detail/{hid}",
        params={"month": "2026-02", "include_disabled": "true"},
    )
    assert detail.status_code == 200
    assert detail.json()["data_quality_score"] == 20.0

    export = client.get(
        f"/reports/export/{hid}/excel",
        params={"month": "2026-02", "include_disabled": "true"},
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    trend = client.get(
        f"/analysis/quality-trend/{hid}", params={"include_disabled": "true"}
    ).json()
    assert [p["month"] for p in trend["data"]] == ["2026-01", "2026-02"]

    heatmap = client.get(
        "/analysis/heatmap", params={"include_disabled": "true"}
    ).json()
    row = next(r for r in heatmap["data"] if r["hospital_id"] == hid)
    assert row["2026-02"] == 20.0

    assert _score_count(db_session, hid) == before


def test_dashboard_and_export_agree_on_active_month(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]

    dashboard_months = {
        p["month"] for p in client.get(
            f"/dashboard/hospital-performance/{hid}"
        ).json()["quality_trend"]
    }
    report_months = {
        r["month"] for r in client.get("/reports/", params={"hospital_id": hid}).json()
    }
    assert dashboard_months == report_months == {"2026-01"}

    active_export = client.get(
        f"/reports/export/{hid}/excel", params={"month": "2026-01"}
    )
    assert active_export.status_code == 200
    disabled_export = client.get(
        f"/reports/export/{hid}/excel", params={"month": "2026-02"}
    )
    assert disabled_export.status_code == 404


def test_audit_inventory_reports_disabled_scores_read_only(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]
    before = _score_count(db_session, hid)

    response = client.get(
        "/admin/quality-scores/disabled-month-inventory",
        params={"hospital_id": hid},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["deleted"] == 0
    assert body["count"] == 1
    assert body["pairs"][0]["hospital_id"] == hid
    assert body["pairs"][0]["month"] == "2026-02"
    assert body["pairs"][0]["scores"][0]["score"] == 20.0
    assert _score_count(db_session, hid) == before


def test_reenabling_restores_eligibility_without_reconstruction(app, db_session, disabled_scores):
    client = TestClient(app)
    hid = disabled_scores["hospital_id"]
    before = _score_count(db_session, hid)

    row = (
        db_session.query(SystemSetting)
        .filter(SystemSetting.key == f"month_enabled_{hid}_2026-02")
        .one()
    )
    row.value = "true"
    db_session.commit()
    cache.invalidate()

    reports = client.get("/reports/", params={"hospital_id": hid}).json()
    assert {r["month"] for r in reports} == {"2026-01", "2026-02"}
    assert all(r["is_enabled"] for r in reports)

    kpi = client.get("/dashboard/kpi", params={"hospital_id": hid}).json()
    assert {k["id"]: k["value"] for k in kpi["kpis"]}["quality_score"] == 55.0

    # Both stored rows are the original evidence — nothing was rebuilt/deleted.
    assert _score_count(db_session, hid) == before


# ── Outlier diagnostics / layered / rule-failure / quality-alert readers ─────
# These screens read STORED results, so the pair rule has to be applied when
# the rows are selected. Stored rows are never deleted: they stay available to
# the audit views and come back the moment the month is re-enabled.

@pytest.fixture()
def disabled_analysis_rows(db_session, disabled_scores):
    """Stored outlier, layered, rule-failure and quality-alert rows (Jan/Feb).

    Hospital 1's February is disabled by ``disabled_scores``. A peer hospital
    reports both months, so each assertion can prove the rule is a PAIR: the
    disabled row disappears while the peer's identical month stays.
    """
    hid = disabled_scores["hospital_id"]
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()
    peers = [h for h in hospitals if h.id != hid]
    peer = peers[0]
    ind = db_session.query(Indicator).filter(
        Indicator.id == disabled_scores["indicator_id"]).one()

    # A third, ENABLED month of raw data: the historical analysis must still
    # have enough history once February is removed. Every peer keeps reporting
    # the disabled month, so network views must keep their February.
    db_session.add(IndicatorValue(hospital_id=hid, month="2026-03",
                                  indicator_id=ind.id, value=12))
    for index, other in enumerate(peers):
        db_session.add(IndicatorValue(hospital_id=other.id, month="2026-03",
                                      indicator_id=ind.id, value=13 + index))
        for month in ("2026-01", "2026-02"):
            db_session.add(IndicatorValue(hospital_id=other.id, month=month,
                                          indicator_id=ind.id, value=11 + index))

    rule = db_session.query(Rule).filter(Rule.code == "TU_ELIG").first()
    if rule is None:
        rule = Rule(code="TU_ELIG", name="Eligibility guard",
                    rule_type="LOGIC", severity="CRITICAL",
                    category="LOGIC", expression_type="range")
        db_session.add(rule)
        db_session.flush()

    for month in ("2026-01", "2026-02"):
        for hospital_id in (hid, peer.id):
            db_session.add(AnomalyResult(
                hospital_id=hospital_id, month=month, indicator_code="ELIG",
                rate_name="Eligibility rate", value=99.0, benchmark=10.0,
                z_score=4.5, is_outlier=True,
            ))
            db_session.add(LayeredOutlierResult(
                hospital_id=hospital_id, month=month, analysis_code="ELIG",
                raw_value=99.0, rate=99.0, historical_outlier_score=1.0,
                outlier_level="VERY_HIGH",
                outlier_type="HISTORICAL_ANOMALY",
                interpretation="Exceeds its own history.",
                investigation_route="clinical",
            ))
            db_session.add(QualityAlert(
                hospital_id=hospital_id, month=month, perspective="history",
                indicator_code="ELIG", indicator_name="Eligibility rate",
                severity="VERY_HIGH", method="pct_change", status="New",
                active=True,
            ))
            db_session.add(ValidationResult(
                hospital_id=hospital_id, month=month, rule_code=rule.code,
                rule_description="Eligibility guard", status="FAIL",
                severity="CRITICAL", rule_type="LOGIC",
            ))
    db_session.commit()
    cache.invalidate()
    return {"hospital_id": hid, "peer_id": peer.id,
            "hospital_name": next(h.name for h in hospitals if h.id == hid)}


def _stored(db, model, hospital_id, month):
    return (db.query(model)
            .filter(model.hospital_id == hospital_id, model.month == month)
            .count())


def test_outlier_diagnostics_hides_disabled_pairs(app, db_session,
                                                  disabled_analysis_rows):
    client = TestClient(app)
    hid = disabled_analysis_rows["hospital_id"]
    peer = disabled_analysis_rows["peer_id"]

    listed = client.get("/analysis/outliers", params={"limit": 100}).json()
    pairs = {(r["hospital_id"], r["month"]) for r in listed["data"]}
    assert (hid, "2026-02") not in pairs
    assert (hid, "2026-01") in pairs
    assert (peer, "2026-02") in pairs, "the peer keeps its enabled month"
    assert listed["total"] == len(pairs) == 3

    narrowed = client.get("/analysis/outliers",
                          params={"hospital_id": hid, "limit": 100}).json()
    assert {r["month"] for r in narrowed["data"]} == {"2026-01"}
    assert narrowed["total"] == 1

    # Hidden, never deleted: the stored row is still there for audit.
    assert _stored(db_session, AnomalyResult, hid, "2026-02") == 1


def test_layered_screen_endpoints_apply_the_same_rule(app, db_session,
                                                      disabled_analysis_rows):
    client = TestClient(app)
    hid = disabled_analysis_rows["hospital_id"]
    peer = disabled_analysis_rows["peer_id"]

    table = client.get("/analysis/layered", params={"page_size": 100}).json()
    pairs = {(r["hospital_id"], r["month"]) for r in table["data"]}
    assert (hid, "2026-02") not in pairs
    assert table["total"] == len(pairs) == 3
    narrowed = client.get("/analysis/layered",
                          params={"hospital": hid, "page_size": 100}).json()
    assert narrowed["total"] == 1

    summary = client.get("/analysis/layered/summary").json()
    assert summary["total"] == 3
    assert {r["hospital_id"]: r["count"] for r in summary["by_hospital"]} == {
        hid: 1, peer: 2}

    trend = client.get("/analysis/layered/trend").json()
    assert trend["months"] == ["2026-01", "2026-02"]
    series = {int(s["key"]): [p["month"] for p in s["points"]]
              for s in trend["series"]}
    assert series[hid] == ["2026-01"]
    assert series[peer] == ["2026-01", "2026-02"]

    heatmap = client.get("/analysis/layered/heatmap").json()
    rows = {r["hospital_id"]: r for r in heatmap["data"]}
    assert "2026-02" not in rows[hid]
    assert rows[peer]["2026-02"]["type"] == "HISTORICAL_ANOMALY"

    assert _stored(db_session, LayeredOutlierResult, hid, "2026-02") == 1


def test_rule_failure_readers_agree_on_eligibility(app, db_session,
                                                   disabled_analysis_rows):
    client = TestClient(app)
    hid = disabled_analysis_rows["hospital_id"]
    peer = disabled_analysis_rows["peer_id"]

    failures = client.get("/analysis/rule-failures",
                          params={"limit": 100}).json()
    pairs = {(r["hospital_id"], r["month"]) for r in failures["data"]}
    assert (hid, "2026-02") not in pairs
    assert (peer, "2026-02") in pairs
    assert failures["total"] == 3

    overview = client.get("/alerts/overview").json()
    assert overview["total_alerts"] == 3
    assert overview["by_severity"]["CRITICAL"]["count"] == 3
    assert {(h["hospital_id"], h["alert_count"])
            for h in overview["top_hospitals"]} == {(hid, 1), (peer, 2)}

    alerts = client.get("/alerts/list", params={"hospital_id": hid}).json()
    assert {i["month"] for i in alerts["items"]} == {"2026-01"}
    assert alerts["total"] == 1

    drill = client.get("/rules/failures",
                       params={"rule_code": "TU_ELIG"}).json()
    assert [m["month"] for m in drill["months"]] == ["2026-02", "2026-01"]
    february = next(m for m in drill["months"] if m["month"] == "2026-02")
    assert [h["hospital_id"] for h in february["hospitals"]] == [peer]

    only = client.get("/rules/failures", params={
        "rule_code": "TU_ELIG", "hospital_id": hid}).json()
    assert [m["month"] for m in only["months"]] == ["2026-01"]

    assert _stored(db_session, ValidationResult, hid, "2026-02") == 1


def test_quality_alerts_screen_excludes_disabled_pairs(app, db_session,
                                                       disabled_analysis_rows):
    client = TestClient(app)
    hid = disabled_analysis_rows["hospital_id"]
    peer = disabled_analysis_rows["peer_id"]

    issues = client.get("/quality-alerts/issues",
                        params={"page_size": 100}).json()
    pairs = {(i["hospital_id"], i["month"]) for i in issues["items"]}
    assert (hid, "2026-02") not in pairs
    assert (peer, "2026-02") in pairs
    assert issues["total"] == len(pairs) == 3

    summary = client.get("/quality-alerts/summary").json()
    assert summary["total_issues"] == 3

    assert _stored(db_session, QualityAlert, hid, "2026-02") == 1


def test_historical_analysis_and_ml_use_only_eligible_pairs(
        app, db_session, disabled_analysis_rows, monkeypatch):
    client = TestClient(app)
    hid = disabled_analysis_rows["hospital_id"]
    name = disabled_analysis_rows["hospital_name"]

    # Trends and cross-hospital anomalies computed from raw values.
    historical = client.get(f"/analysis/historical/{hid}")
    assert historical.status_code == 200, historical.text
    assert historical.json()["months_analyzed"] == ["2026-01", "2026-03"]

    # ML input: the disabled pair contributes no row, without hiding the month
    # for the hospitals that still report it.
    db_session.add(AppConfig(category="ml", key="ml_enabled", value="1"))
    db_session.commit()
    cache.invalidate()

    import app.engine.ml as ml

    captured = {}

    def fake_run(data, config):
        captured["hospitals"] = sorted(data)
        return {"ok": True}

    monkeypatch.setattr(ml, "run_ml_analysis", fake_run)
    response = client.get("/analysis/ml", params={"month": "2026-02"})
    assert response.status_code == 200, response.text
    assert name not in captured["hospitals"], "disabled pair excluded from ML"
    assert len(captured["hospitals"]) >= 2, "the month survives for peers"
