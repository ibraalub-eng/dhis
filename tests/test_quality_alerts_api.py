"""API + engine tests for the Quality Alerts risk-outlier screen (2026-10-21).

The fixture builds its OWN registered indicator (raw codes + a shared
IndicatorDefinition) so the tests prove the screen is registry-driven end to
end: scan -> grouped issues -> evidence -> investigation workflow — with no
hardcoded clinical formula anywhere.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.engine.quality_alerts import (
    INTERP_HIGH_CONCERN,
    INTERP_HIGH_FAVORABLE,
    INTERP_OUTSIDE_TARGET,
    INTERP_STATISTICAL_ONLY,
    INTERP_WITHIN_TARGET,
    interpret_deviation,
    resolve_direction,
)
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    QualityAlert,
    ValidationResult,
)


@pytest.fixture
def client(app):
    """TestClient over the conftest app — `_bypass_auth` already overrides
    get_current_user (superadmin) and get_db (db_session)."""
    return TestClient(app)


@pytest.fixture
def registry_dataset(db_session):
    """A registered ratio indicator with 5 hospitals x 4 months of data.

    Hospital 1's last month spikes (80% vs ~10% baseline); the other four stay
    flat — so history, all-hospital and peer comparisons all have real
    evidence to work with.

    Four flat peers, not two: a peer comparison resting on fewer than 4 other
    hospitals cannot claim the top band (``THIN_PEER_POLICY``), so a
    3-hospital universe could not produce a multi-perspective Very High issue
    — and
    the tests below that prove the reporting unit is the issue, not the
    perspective row, need exactly that.
    """
    num = Indicator(code="QA_NUM", name="QA numerator")
    den = Indicator(code="QA_DEN", name="QA denominator")
    db_session.add_all([num, den])
    db_session.flush()

    definition = IndicatorDefinition(
        code="QA_TEST_RATE",
        name="QA Test Rate",
        description="Registry-driven test indicator",
        formula_type="ratio",
        numerator_codes=["QA_NUM"],
        denominator_codes=["QA_DEN"],
        operator="/",
        multiplier=100.0,
        result_type="percentage",
        unit="%",
        direction="lower_is_better",
        is_active=True,
    )
    db_session.add(definition)
    db_session.flush()

    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()
    assert len(hospitals) >= 3, "conftest seeds 3 hospitals"
    months = ["2026-05", "2026-06", "2026-07", "2026-08"]
    # (hospital index, month index) -> numerator value; denominator always 100
    spikes = {(0, 3): 80.0}   # hospital 1 spikes in the scan month
    base = {0: 10.0, 1: 10.0, 2: 9.0}
    for hi, hospital in enumerate(hospitals[:3]):
        for mi, month in enumerate(months):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=num.id, month=month,
                value=spikes.get((hi, mi), base[hi])))
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=den.id, month=month,
                value=100.0))
    # Two more flat reporters, so the spike hospital has a measurable peer
    # group and its peer perspectives can legitimately reach the top band.
    flat_peers = []
    for index in range(2):
        peer = Hospital(name=f"QA Flat Peer {index + 1}", is_active=True)
        db_session.add(peer)
        db_session.flush()
        flat_peers.append(peer)
        for month in months:
            db_session.add(IndicatorValue(
                hospital_id=peer.id, indicator_id=num.id, month=month,
                value=10.0))
            db_session.add(IndicatorValue(
                hospital_id=peer.id, indicator_id=den.id, month=month,
                value=100.0))
    db_session.commit()
    return {"definition": definition, "hospitals": hospitals[:3],
            "peers": flat_peers, "months": months,
            "scan_month": months[-1]}


def _scan(client, month, hospital_id=None):
    return client.post("/quality-alerts/scan",
                       json={"month": month, "hospital_id": hospital_id})


# ── Engine: direction / interpretation (spec §4 clinical rule) ──────────────

def test_interpretation_never_claims_harm_from_magnitude_alone():
    # Statistical high + favorable direction -> favorable label, not harm.
    assert interpret_deviation("higher_is_better", 90.0, 50.0) == INTERP_HIGH_FAVORABLE
    assert interpret_deviation("lower_is_better", 90.0, 50.0) == INTERP_HIGH_CONCERN
    # Target range: inside stays "within", outside flags the range only.
    assert interpret_deviation("target_range", 50.0, 10.0,
                               target_min=40.0, target_max=60.0) == INTERP_WITHIN_TARGET
    assert interpret_deviation("target_range", 90.0, 10.0,
                               target_min=40.0, target_max=60.0) == INTERP_OUTSIDE_TARGET
    # No configured direction -> purely statistical, never clinical.
    assert interpret_deviation("none", 90.0, 50.0) == INTERP_STATISTICAL_ONLY


def test_resolve_direction_prefers_definition_metadata(db_session, registry_dataset):
    from app.engine import indicator_service
    resolved = indicator_service.resolve(db_session, "QA_TEST_RATE")
    direction, tmin, tmax = resolve_direction(db_session, resolved)
    assert direction == "lower_is_better"


# ── Scan + grouping ─────────────────────────────────────────────────────────

def test_scan_produces_registry_driven_alerts(client, db_session, registry_dataset):
    resp = _scan(client, registry_dataset["scan_month"])
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["created"] >= 1
    assert payload["hospitals_scanned"] >= 3

    spike_hospital = registry_dataset["hospitals"][0]
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id,
        indicator_code="QA_TEST_RATE",
        month=registry_dataset["scan_month"]).all()
    assert alerts, "the spiking hospital must carry at least one alert"
    # Provenance: values/formula come from the registry definition.
    for alert in alerts:
        assert alert.indicator_name == "QA Test Rate"
        assert alert.formula  # stored from the resolved definition
        assert alert.current_value == pytest.approx(80.0)
        assert alert.direction == "lower_is_better"
        assert alert.interpretation == INTERP_HIGH_CONCERN
        assert alert.severity in ("MODERATE", "HIGH", "VERY_HIGH")


def test_issues_group_perspectives_into_one_risk_issue(client, db_session, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    resp = client.get("/quality-alerts/issues",
                      params={"month": registry_dataset["scan_month"],
                              "indicator": "QA_TEST_RATE"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    spike_hospital = registry_dataset["hospitals"][0]
    mine = [i for i in items if i["hospital_id"] == spike_hospital.id]
    assert len(mine) == 1, "one issue per hospital+indicator+month (spec §8)"
    issue = mine[0]
    assert issue["perspective_count"] >= 2, \
        "history + all-hospital perspectives must both be preserved"
    keys = {p["perspective"] for p in issue["perspectives"]}
    assert "history" in keys and "all" in keys
    assert issue["primary_severity"] == "VERY_HIGH", "spike dominates severity"


def test_issue_rows_carry_inline_trend(client, registry_dataset):
    """Each list row carries its own monthly series, so the table can draw the
    trend without opening the detail (and without peer scans)."""
    _scan(client, registry_dataset["scan_month"])
    resp = client.get("/quality-alerts/issues",
                      params={"month": registry_dataset["scan_month"],
                              "indicator": "QA_TEST_RATE"})
    assert resp.status_code == 200
    spike_hospital = registry_dataset["hospitals"][0]
    items = resp.json()["items"]
    issue = next(i for i in items if i["hospital_id"] == spike_hospital.id)

    spark = issue["sparkline"]
    assert spark, "every issue row must carry its trend"
    assert spark["months"] and spark["values"]
    assert len(spark["months"]) == len(spark["values"])
    # The series is the hospital's own values, ending at the flagged month.
    assert spark["months"][-1] == registry_dataset["scan_month"]
    assert spark["alert_month"] == registry_dataset["scan_month"]
    assert spark["values"][-1] == pytest.approx(80.0)
    assert spark["min"] == pytest.approx(10.0)
    assert spark["max"] == pytest.approx(80.0)


def test_summary_counts_very_high_issues_and_hospitals(client, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    resp = client.get("/quality-alerts/summary",
                      params={"month": registry_dataset["scan_month"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["very_high_issues"] >= 1
    assert data["hospitals_affected"] >= 1
    assert data["indicators_affected"] >= 1
    assert data["total_active"] >= data["very_high_rows"]
    # One band, one name: the screen publishes no "red" vocabulary at all, so
    # no client can read a red number beside the Very High severity.
    for legacy in ("red_alerts", "red_issues", "red_only_issues"):
        assert legacy not in data, f"{legacy} must not come back"
    # Issue-unit fields are reported alongside, never instead of, row counts.
    assert data["total_issues"] <= data["total_active"]
    # One issue can carry several Very High rows, never fewer.
    assert data["very_high_rows"] >= data["very_high_issues"]


def test_summary_issue_counts_match_the_paged_table(client, registry_dataset):
    """The KPI cards and the pager count grouped issues, not perspective rows.

    Same filters, same grouping: ``total_issues`` must equal the ``total``
    the issues endpoint pages through, or the pager advertises pages that
    hold nothing while the cards overstate how many findings exist.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]
    params = {"month": month, "severity": "VERY_HIGH", "page_size": 200}

    summary = client.get("/quality-alerts/summary", params=params).json()
    issues = client.get("/quality-alerts/issues", params=params).json()

    assert summary["total_issues"] == issues["total"]
    # Every listed row is Very High here, so every grouped issue is too.
    assert summary["very_high_issues"] == summary["total_issues"]
    assert (summary["very_high_only_issues"] + summary["mixed_severity_issues"]
            == summary["total_issues"])
    # Under this filter every row is Very High, so the row count is the same
    # as the evidence count while the issue count stays the smaller unit.
    assert summary["total_active"] == summary["very_high_rows"]
    assert summary["very_high_issues"] == summary["total_issues"]

    # Same rollup as the table's Status cell, so the status cards agree.
    statuses = [item["status"] for item in issues["items"]]
    assert summary["new_issues"] == statuses.count("New")
    assert summary["unresolved_issues"] == sum(
        1 for s in statuses if s not in ("Resolved", "False Positive"))

    # Row counts stay available as the evidence unit, and rows outnumber
    # issues whenever an issue fired more than one perspective.
    unfiltered = client.get("/quality-alerts/summary",
                            params={"month": month}).json()
    assert unfiltered["total_active"] > unfiltered["total_issues"], \
        "the fixture's spike carries several perspectives on one issue"


def test_dashboard_very_high_issue_card_matches_the_quality_alerts_screen(
        client, db_session, registry_dataset):
    """The dashboard card reports the screen's Very High count in the same unit.

    It replaced a policy-drift counter that could only read 0 once no stored
    row carried a policy fingerprint. Perspective rows would overstate the
    replacement, so the card must agree with the issue-level KPI.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]

    summary = client.get("/quality-alerts/summary",
                         params={"month": month}).json()
    overview = client.get("/dashboard/overview",
                          params={"month_from": month,
                                  "month_to": month}).json()
    # One band, one unit everywhere: the dashboard card and the screen's KPI
    # both count Very High ISSUES, never the perspective rows behind them.
    assert summary["very_high_issues"] == overview["very_high_quality_issues"], \
        "both cards count Very High issues"
    assert summary["very_high_rows"] >= summary["very_high_issues"], \
        "rows are evidence: one issue can carry several"

    stored_rows = (db_session.query(QualityAlert)
                   .filter(QualityAlert.active.is_(True),
                           QualityAlert.month == month,
                           QualityAlert.severity == "VERY_HIGH").all())
    distinct = {(row.hospital_id, row.indicator_code, row.month)
                for row in stored_rows}
    assert overview["very_high_quality_issues"] == len(distinct)
    assert overview["very_high_quality_issues"] < len(stored_rows), \
        "the fixture's spike carries several perspectives on one issue"


def test_dashboard_active_alert_card_reports_the_screen_volume(
        client, db_session, registry_dataset):
    """The dashboard's Active Alerts card is the open-alert volume, not rules.

    It used to print the stored validation-rule failure count (4 on the live
    store, beside 1,217 Very High issues) under a label that reads as alert
    volume, so the headline alert number had nothing to do with the alerts the
    app lists. The card now counts the same open issues as
    ``/quality-alerts/summary``; rule failures keep their own card and unit.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]

    summary = client.get("/quality-alerts/summary",
                         params={"month": month}).json()
    overview = client.get("/dashboard/overview",
                          params={"month_from": month,
                                  "month_to": month}).json()

    assert overview["active_quality_issues"] == summary["total_issues"]
    assert overview["active_quality_issues"] > 0
    # Perspective rows outnumber issues, so the card is the smaller (screen)
    # unit and can never present the alert volume as more findings than exist.
    assert overview["active_quality_issues"] <= summary["total_active"]
    # The Very High card is a subset of the total card, same fold.
    assert (overview["very_high_quality_issues"]
            <= overview["active_quality_issues"])

    # Rule failures remain a separate number: a stored FAIL row per
    # hospital-month-rule, never mixed into the alert count.
    failures = (db_session.query(ValidationResult)
                .filter(ValidationResult.status == "FAIL",
                        ValidationResult.month == month).count())
    assert overview["total_alerts"] == failures
    if failures == 0 and overview["active_quality_issues"]:
        assert overview["total_alerts"] != overview["active_quality_issues"], (
            "the two cards must never collapse into one number")


def test_summary_splits_very_high_only_from_mixed_severity(client, db_session,
                                                           registry_dataset):
    """Very-High-only vs mixed describes the whole issue, not the filtered
    slice.

    The screen filters rows to VERY_HIGH before grouping, so neither bucket
    can be derived from those rows alone: an issue is mixed only when a lower
    band also fired on it.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]
    summary = client.get("/quality-alerts/summary",
                         params={"month": month,
                                 "severity": "VERY_HIGH"}).json()

    rows = db_session.query(QualityAlert).filter_by(active=True,
                                                    month=month).all()
    by_issue: dict = {}
    for alert in rows:
        by_issue.setdefault(
            (alert.hospital_id, alert.indicator_code, alert.month), set()
        ).add(alert.severity)
    very_high = [sevs for sevs in by_issue.values() if "VERY_HIGH" in sevs]

    assert summary["very_high_only_issues"] == sum(
        1 for sevs in very_high if sevs == {"VERY_HIGH"})
    assert summary["mixed_severity_issues"] == sum(
        1 for sevs in very_high if len(sevs) > 1)
    # On the pinned screen every listed issue is Very High, so the split is
    # complete.
    assert (summary["very_high_only_issues"] + summary["mixed_severity_issues"]
            == summary["total_issues"])

    # Very-High-only is also true of an issue where only ONE perspective fired
    # (nothing else was compared, so nothing came out lower). Those are counted
    # apart, per perspective, so the bucket is never read as agreement between
    # comparisons — the live store is mostly hospital-history findings.
    singles = summary["very_high_single_perspective_issues"]
    by_label = summary["very_high_single_perspective_by_perspective"]
    assert sum(by_label.values()) == singles
    assert singles <= summary["very_high_only_issues"]

    # The same bucket by the SET of comparisons that fired, so an issue backed
    # by one comparison is never counted as agreeing with another.
    fired_sets = summary["very_high_only_by_perspectives"]
    assert sum(entry["issues"] for entry in fired_sets) == (
        summary["very_high_only_issues"])
    assert sum(entry["issues"] for entry in fired_sets
               if len(entry["perspectives"]) == 1) == singles
    assert summary["very_high_only_corroborated_issues"] == sum(
        entry["issues"] for entry in fired_sets
        if len(entry["perspectives"]) > 1)
    assert (singles + summary["very_high_only_corroborated_issues"]
            == summary["very_high_only_issues"])
    # A set is a set: the same perspective never appears twice in one entry.
    for entry in fired_sets:
        assert len(set(entry["perspectives"])) == len(entry["perspectives"])


def test_severity_filter_widens_and_low_confidence_skip_is_server_side(
        client, db_session, registry_dataset):
    """The screen's two scope controls: a lower band lists only that band, and
    "skip low confidence" drops small-peer-group rows without dropping rows
    that predate confidence provenance."""
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]

    everything = client.get("/quality-alerts/summary",
                            params={"month": month}).json()
    very_high = client.get("/quality-alerts/summary",
                           params={"month": month,
                                   "severity": "VERY_HIGH"}).json()
    assert very_high["total_issues"] <= everything["total_issues"]
    assert very_high["very_high_issues"] == very_high["total_issues"]
    assert everything["total_issues"] >= very_high["total_issues"]

    # A band filter decides which ROWS matched, not what the issue contains: the
    # row is listed for its moderate perspective and its other perspectives stay
    # visible, so a multi-perspective issue cannot look single-perspective just
    # because a lower band is selected.
    moderate = client.get("/quality-alerts/issues",
                          params={"month": month, "severity": "MODERATE"}).json()
    for item in moderate["items"]:
        assert item["primary_severity"] == "MODERATE"
        assert "MODERATE" in {p["severity"] for p in item["perspectives"]}

    rows = db_session.query(QualityAlert).filter_by(active=True,
                                                    month=month).all()
    assert len(rows) >= 2
    legacy, low = rows[0], rows[1]
    legacy.confidence = None   # written before provenance existed
    low.confidence = "low"     # small comparison group / ML disagreement
    db_session.commit()

    kept = client.get("/quality-alerts/issues",
                      params={"month": month, "confidence": "high",
                              "page_size": 200}).json()["items"]
    kept_ids = {aid for item in kept for aid in item["alert_ids"]}
    assert legacy.id in kept_ids, \
        "NULL confidence is displayed as high, so the filter must keep it"
    assert low.id not in kept_ids


def test_detail_returns_evidence_definition_and_audit_link(client, db_session, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    spike_hospital = registry_dataset["hospitals"][0]
    # Explicit code: data elements now produce rows too, so the query must
    # target the registered rate this test's assertions are about.
    alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id, perspective="history",
        indicator_code="QA_TEST_RATE").first()
    assert alert is not None
    resp = client.get(f"/quality-alerts/{alert.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["evidence"]["history"], "history evidence series stored"
    assert data["evidence"]["stats"]["mean"] is not None
    assert data["definition"]["code"] == "QA_TEST_RATE"
    assert data["definition"]["direction"] == "lower_is_better"
    assert data["audit_link"]["hospital_id"] == spike_hospital.id
    assert data["issue"]["perspectives"], "sibling perspectives included"


# ── Safeguards (spec §9) ────────────────────────────────────────────────────

def test_detail_lists_peer_hospitals_with_values(client, db_session,
                                                registry_dataset):
    """The detail must name the comparison group and show each peer's value —
    and it must do so even when the opened row happens to be the history
    perspective, whose own baseline is the hospital's prior months."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    others = ({h.id for h in registry_dataset["hospitals"][1:]}
              | {h.id for h in registry_dataset["peers"]})

    history = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, perspective="history",
        indicator_code="QA_TEST_RATE").first()
    assert history is not None
    data = client.get(f"/quality-alerts/{history.id}").json()

    groups = data["peer_groups"]
    assert groups, "a history alert must still expose the issue's peer groups"
    peers = {p["id"] for g in groups for p in g["peers"]}
    assert peers == others
    values = [p["value"] for p in groups[0]["peers"]]
    assert all(v is not None for v in values), "peer values are computed, not blank"
    assert 80.0 not in values, "the flagged hospital is not its own peer"

    peer_alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, perspective="all",
        indicator_code="QA_TEST_RATE").first()
    assert peer_alert is not None
    peer_data = client.get(f"/quality-alerts/{peer_alert.id}").json()
    assert peer_data["peers"], "flat peer list remains for the opened alert"
    assert {p["id"] for p in peer_data["peers"]} == others
    top = peer_data["peer_groups"][0]
    assert top["perspective"] == "all"
    assert {p["value"] for p in top["peers"]} == {10.0, 9.0}


def test_scan_skips_hospitals_without_data(client, db_session, registry_dataset):
    # A hospital with no values must never receive an alert.
    _scan(client, registry_dataset["scan_month"])
    # spike hospital has data; assert the OTHER flat hospitals at ~10% with
    # zero spread do not get peer alerts from a zero-std baseline.
    flat = db_session.query(QualityAlert).filter_by(
        hospital_id=registry_dataset["hospitals"][2].id,
        month=registry_dataset["scan_month"]).all()
    # hospital 3 is flat at 9% with peers at 10/10% -> tiny deviation, no alert
    assert all(a.perspective != "all" or a.severity in ("LOW", "MODERATE")
               for a in flat)


def test_rescan_keeps_investigation_state(client, db_session, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    spike_hospital = registry_dataset["hospitals"][0]
    alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id, perspective="history").first()
    resp = client.post(f"/quality-alerts/{alert.id}/status",
                       json={"status": "Under Review", "note": "checking uploads",
                             "assignee": "dr-hassan"})
    assert resp.status_code == 200, resp.text
    # Rescan: statistics refresh, human state survives.
    _scan(client, registry_dataset["scan_month"])
    db_session.expire_all()
    refreshed = db_session.query(QualityAlert).filter_by(id=alert.id).first()
    assert refreshed.status == "Under Review"
    assert refreshed.assignee == "dr-hassan"


def test_status_workflow_validates_and_records_events(client, db_session, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    alert = db_session.query(QualityAlert).first()
    bad = client.post(f"/quality-alerts/{alert.id}/status",
                      json={"status": "Not A Status"})
    assert bad.status_code == 422
    ok = client.post(f"/quality-alerts/{alert.id}/status",
                     json={"status": "Confirmed Issue", "note": "real spike"})
    assert ok.status_code == 200
    detail = client.get(f"/quality-alerts/{alert.id}").json()
    statuses = [e["to_status"] for e in detail["events"]]
    assert "Confirmed Issue" in statuses
    note = client.post(f"/quality-alerts/{alert.id}/note", json={"note": " "})
    assert note.status_code == 422, "empty notes rejected"


# ── Open vs closed investigation scope (spec §10) ─────────────────────────────
#
# STATUS_CHANGE: Resolved and False Positive (skip) are CLOSED states. Before
# this policy the row kept alerting forever — it stayed in the list with 5,330
# other open rows and only a coloured badge said it had been dealt with.

def _scope(registry_dataset):
    return {"month": registry_dataset["scan_month"],
            "indicator": "QA_TEST_RATE"}


def _issues(client, **params):
    resp = client.get("/quality-alerts/issues", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _close_every_perspective(client, db_session, hospital_id, month, status):
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=hospital_id, indicator_code="QA_TEST_RATE",
        month=month).all()
    assert alerts
    for alert in alerts:
        resp = client.post(f"/quality-alerts/{alert.id}/status",
                           json={"status": status, "note": "reviewed"})
        assert resp.status_code == 200, resp.text
    db_session.expire_all()
    return alerts


def test_resolved_alert_leaves_the_open_list_and_counts(
        client, db_session, registry_dataset):
    """Marking Resolved must stop the alert alerting — without losing it."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    scope = _scope(registry_dataset)
    assert any(i["hospital_id"] == spike.id
               for i in _issues(client, **scope)["items"])
    before = client.get("/quality-alerts/summary", params=scope).json()

    alerts = _close_every_perspective(client, db_session, spike.id,
                                      registry_dataset["scan_month"],
                                      "Resolved")

    after = _issues(client, **scope)
    assert all(i["hospital_id"] != spike.id for i in after["items"]), \
        "a resolved finding must leave the open alert list"
    summary = client.get("/quality-alerts/summary", params=scope).json()
    assert summary["total_issues"] == before["total_issues"] - 1
    assert summary["unresolved_issues"] == summary["total_issues"], \
        "the open view counts only findings that still need attention"
    assert summary["very_high_issues"] == before["very_high_issues"] - 1

    # Closed, not deleted: the row is still reachable and still audited.
    resolved = _issues(client, **{**scope, "status": "Resolved"})
    spike_items = [i for i in resolved["items"] if i["hospital_id"] == spike.id]
    assert spike_items and spike_items[0]["status"] == "Resolved"
    closed = _issues(client, **{**scope, "include_closed": "true"})
    assert any(i["hospital_id"] == spike.id for i in closed["items"])

    for alert in alerts:
        detail = client.get(f"/quality-alerts/{alert.id}").json()
        assert any(e["to_status"] == "Resolved" for e in detail["events"])
        stored = db_session.query(QualityAlert).filter_by(id=alert.id).first()
        assert stored.active is True, \
            "closed is an investigation state, not a detection state"


def test_false_positive_skip_also_clears_the_alert(
        client, db_session, registry_dataset):
    """'Skip' is a decision too: the finding must stop being raised."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    scope = _scope(registry_dataset)

    _close_every_perspective(client, db_session, spike.id,
                             registry_dataset["scan_month"], "False Positive")

    assert all(i["hospital_id"] != spike.id
               for i in _issues(client, **scope)["items"])
    skipped = _issues(client, **{**scope, "status": "False Positive"})
    mine = [i for i in skipped["items"] if i["hospital_id"] == spike.id]
    assert mine and mine[0]["status"] == "False Positive", \
        "the skip stays visible under its own status, not hidden or rewritten"


def test_rescan_keeps_a_closed_alert_closed(client, db_session, registry_dataset):
    """A later scan refreshes statistics; it must not resurrect the alert."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    scope = _scope(registry_dataset)
    _close_every_perspective(client, db_session, spike.id, month, "Resolved")

    _scan(client, month)
    db_session.expire_all()

    stored = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_TEST_RATE", month=month).all()
    assert stored and all(a.status == "Resolved" for a in stored)
    assert all(i["hospital_id"] != spike.id
               for i in _issues(client, **scope)["items"]), \
        "re-detection refreshes the finding but does not reopen the alert"


def test_partly_closed_issue_stays_open_for_its_open_evidence(
        client, db_session, registry_dataset):
    """One resolved perspective does not close an issue another still raises."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    scope = _scope(registry_dataset)
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_TEST_RATE",
        month=registry_dataset["scan_month"]).all()
    assert len(alerts) >= 2, "the fixture's spike fires on several perspectives"

    first = alerts[0]
    assert client.post(f"/quality-alerts/{first.id}/status",
                       json={"status": "Resolved"}).status_code == 200

    items = [i for i in _issues(client, **scope)["items"]
             if i["hospital_id"] == spike.id]
    assert items, "the issue is still open through its remaining perspectives"
    assert items[0]["status"] != "Resolved"
    assert first.id not in items[0]["alert_ids"]


def test_dashboard_very_high_card_ignores_closed_alerts(
        client, db_session, registry_dataset):
    """The Very High Issues card is an open-alert count, like the screen."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    before = client.get("/dashboard/overview", params={
        "month_from": month, "month_to": month}).json()["very_high_quality_issues"]

    _close_every_perspective(client, db_session, spike.id, month, "Resolved")

    overview = client.get("/dashboard/overview", params={
        "month_from": month, "month_to": month}).json()
    summary = client.get("/quality-alerts/summary",
                         params={"month": month}).json()
    assert overview["very_high_quality_issues"] == summary["very_high_issues"]
    assert overview["very_high_quality_issues"] == before - 1


# ── Meta + permissions ──────────────────────────────────────────────────────

def test_meta_reports_governance_as_unavailable(client):
    meta = client.get("/quality-alerts/meta").json()
    governance = next(p for p in meta["perspectives"] if p["key"] == "governance")
    assert governance["available"] is False
    assert "ownership" in governance["unavailable_reason"]
    available = {p["key"] for p in meta["perspectives"] if p["available"]}
    assert {"history", "type", "ownership", "governorate", "all"} <= available
    assert "New" in meta["statuses"] and "Resolved" in meta["statuses"]


def test_endpoints_require_auth_when_protection_is_active(app, db_session):
    """With the auth bypass stripped, requests must401 (regression guard for
    the router's permission dependency)."""
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    assert client.get("/quality-alerts/summary").status_code == 401
    assert client.get("/quality-alerts/issues").status_code == 401
    assert client.post("/quality-alerts/scan",
                       json={"month": "2026-08"}).status_code == 401


# ── Default-on auto-scan (pipeline) + scan-all-periods ────────────────────
def test_scan_without_month_covers_every_period(client, db_session, registry_dataset):
    """POST /scan with no month = catch-up scan over all periods with data."""
    resp = client.post("/quality-alerts/scan", json={})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["months_scanned"] >= 1
    assert payload["created"] >= 1
    # The scan month's spike must have been detected by the catch-up scan.
    spike_hospital = registry_dataset["hospitals"][0]
    assert db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id,
        month=registry_dataset["scan_month"]).count() >= 1


def test_pipeline_auto_scans_alerts_by_default(db_session, registry_dataset):
    """run_full_analysis must raise Quality Alerts without anyone pressing
    Run Scan (config alerts_auto_scan defaults to 1)."""
    from app.engine.pipeline import run_full_analysis
    hospital = registry_dataset["hospitals"][0]
    month = registry_dataset["scan_month"]
    run_full_analysis(db_session, hospital.id, month)
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=hospital.id, month=month, active=True).all()
    assert alerts, "fresh analysis must auto-generate alerts for the month"
    assert any(a.severity == "VERY_HIGH" for a in alerts)


def test_pipeline_auto_scan_can_be_disabled(client, db_session, registry_dataset):
    """alerts_auto_scan=0 turns the automatic scan off; the manual scan
    endpoint keeps working."""
    from app.engine.pipeline import run_full_analysis
    from app.models import AppConfig
    db_session.add(AppConfig(key="alerts_auto_scan", value=0.0,
                             category="alerts", label="Auto-scan off"))
    db_session.commit()
    hospital = registry_dataset["hospitals"][0]
    month = registry_dataset["scan_month"]
    run_full_analysis(db_session, hospital.id, month)
    assert db_session.query(QualityAlert).filter_by(month=month).count() == 0, \
        "no alerts when the auto-scan config is off"
    # Manual scan still works.
    resp = _scan(client, month)
    assert resp.status_code == 200, resp.text
    assert db_session.query(QualityAlert).filter_by(month=month).count() >= 1


# ── Coverage: every catalog kind gets an outlier search ────────────────────
def test_scan_covers_raw_data_elements(client, db_session, registry_dataset):
    """Data Elements (raw indicators) are scanned like any other kind:
    QA_NUM spikes 10 -> 80 in the scan month, so its own alert rows must
    exist alongside the registered rate's."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    raw_alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_NUM",
        month=registry_dataset["scan_month"]).all()
    assert raw_alerts, "data elements must be scanned for outliers too"
    assert any(a.severity == "VERY_HIGH" for a in raw_alerts)
    # Read as-is, never recomputed: the stored spike is the alert's value.
    assert all(a.current_value == pytest.approx(80.0) for a in raw_alerts)
    assert all(a.indicator_name == "QA numerator" for a in raw_alerts)


def test_scan_covers_derivative_definitions(client, db_session, registry_dataset):
    """Non-system (kind=derived) definitions get the same peer/history
    evidence as system rate specs."""
    derived = IndicatorDefinition(
        code="QA_DERIVED_RATE", name="QA Derived",
        formula_type="ratio", numerator_codes=["QA_NUM"],
        denominator_codes=["QA_DEN"], operator="/", multiplier=100.0,
        result_type="percentage", unit="%", is_system=False, is_active=True)
    db_session.add(derived)
    db_session.commit()
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    assert db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_DERIVED_RATE",
        month=registry_dataset["scan_month"]).count() >= 1, \
        "derivative indicators must be scanned too"


def test_detail_works_for_raw_element_alerts(client, db_session, registry_dataset):
    """Data-element alerts carry no registry definition row — the detail
    endpoint must still return evidence, siblings and the audit link."""
    _scan(client, registry_dataset["scan_month"])
    spike = registry_dataset["hospitals"][0]
    raw = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_NUM",
        month=registry_dataset["scan_month"]).first()
    assert raw is not None
    resp = client.get(f"/quality-alerts/{raw.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["definition"] is None, "raw element has no definition row"
    assert data["alert"]["indicator_name"] == "QA numerator"
    assert data["evidence"], "evidence still returned"
    assert data["audit_link"]["hospital_id"] == spike.id
    assert data["issue"]["perspectives"]


def test_history_fetched_once_per_hospital(monkeypatch, client, db_session,
                                            registry_dataset):
    """100+ data elements share ONE history fetch per hospital — the scan
    must not re-query the same months once per element."""
    from app.engine import quality_alerts as qa
    calls = []
    original = qa.get_historical_months

    def counting(session, hospital_id, month):
        calls.append(hospital_id)
        return original(session, hospital_id, month)

    monkeypatch.setattr(qa, "get_historical_months", counting)
    _scan(client, registry_dataset["scan_month"])
    assert calls, "history perspective must have run"
    assert len(calls) == len(set(calls)), \
        f"history fetched {len(calls)} times for {len(set(calls))} hospitals"


# ── No-hardcoded-formula contract (spec §10) ────────────────────────────────

def test_engine_source_has_no_indicator_formula_math():
    """The Alerts module must compute nothing itself: indicator values come
    from indicator_service.calculate_from_values only."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    engine_src = (root / "app" / "engine" / "quality_alerts.py").read_text(encoding="utf-8")
    api_src = (root / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")
    # Values come from the shared calculation engine — never inline math.
    assert "calculate_from_values" in engine_src
    assert "indicator_service" in engine_src
    for src in (engine_src, api_src):
        # No data-tree code literals or rate-formula shapes. (Percent-style
        # deviation math for DISPLAY is allowed — it is not an indicator.)
        for forbidden in ("{2}", "{5}", "{6}", "{10}", "deliveries",
                          "live_births", "c_section", "cs_rate =",
                          "numerator / denominator"):
            assert forbidden not in src, f"hardcoded formula hint: {forbidden!r}"


def test_very_high_cards_are_filters_over_one_population(client, db_session,
                                                         registry_dataset):
    """Clicking a Very High card lists exactly the issues that card counts.

    The filter and the two cards used to count the same issues three different
    ways with no way to see which row belonged to which card. Each scope now
    narrows the list AND the totals to the card's own number, while both cards
    keep describing the whole Very High population — so the number the operator
    clicked stays beside the list it produced.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]
    base = {"month": month, "severity": "VERY_HIGH", "page_size": 200}

    # The fixture's spike is Very High on every perspective, so give one of its
    # issues a lower band on a further perspective: that is what "mixed" means.
    spike = db_session.query(QualityAlert).filter_by(
        active=True, month=month, indicator_code="QA_TEST_RATE").all()
    assert spike, "the scan must have stored the spike"
    sample = spike[0]
    taken = {a.perspective for a in spike
             if a.hospital_id == sample.hospital_id}
    free = next(p for p in ("ownership", "governorate", "facility_type",
                            "type", "all") if p not in taken)
    db_session.add(QualityAlert(
        hospital_id=sample.hospital_id, month=month, perspective=free,
        indicator_id=sample.indicator_id, indicator_code=sample.indicator_code,
        indicator_name=sample.indicator_name, unit=sample.unit,
        formula=sample.formula, severity="HIGH", method=sample.method,
        current_value=sample.current_value, baseline_value=sample.baseline_value,
        deviation_pct=sample.deviation_pct, peer_count=sample.peer_count,
        status="New", active=True))
    db_session.commit()

    summary = client.get("/quality-alerts/summary", params=base).json()
    only = summary["very_high_only_issues"]
    mixed = summary["mixed_severity_issues"]
    assert only + mixed == summary["total_issues"] == summary["very_high_issues"]
    assert only >= 1, "the fixture's spike must be Very High on every perspective"
    assert mixed >= 1, "and at least one issue must carry a lower band too"

    for scope, expected in (("only", only), ("mixed", mixed)):
        scoped = client.get("/quality-alerts/summary",
                            params={**base, "very_high_scope": scope}).json()
        issues = client.get("/quality-alerts/issues",
                            params={**base, "very_high_scope": scope}).json()
        assert scoped["total_issues"] == expected
        assert issues["total"] == expected, \
            "the card's number and the filtered table must be one population"
        # Both cards keep the unscoped split: a card must not read 0 because it
        # is the one being applied.
        assert scoped["very_high_only_issues"] == only
        assert scoped["mixed_severity_issues"] == mixed

        # Every listed row agrees with the scope it was filed under, and its
        # whole evidence travels with it (that is what the chips render).
        for item in issues["items"]:
            bands = {p["severity"] for p in item["perspectives"]}
            assert "VERY_HIGH" in bands
            assert (bands == {"VERY_HIGH"}) is (scope == "only"), item["indicator_code"]
            assert item["primary_severity"] == "VERY_HIGH"


def test_corroborated_card_lists_only_what_a_second_perspective_agreed(
        client, db_session, registry_dataset):
    """The third card is the non-vacuous reading of "Very High only".

    A single fired perspective satisfies that bucket without anything having
    been compared against it, so the corroborated subset — two or more
    perspectives all grading the issue Very High — is the part where the band
    was actually agreed on.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]
    base = {"month": month, "severity": "VERY_HIGH", "page_size": 200}

    summary = client.get("/quality-alerts/summary", params=base).json()
    corroborated = summary["very_high_only_corroborated_issues"]
    assert corroborated == sum(
        entry["issues"] for entry in summary["very_high_only_by_perspectives"]
        if len(entry["perspectives"]) > 1)
    assert corroborated <= summary["very_high_only_issues"]

    scoped = client.get("/quality-alerts/summary",
                        params={**base, "very_high_scope": "corroborated"}).json()
    issues = client.get("/quality-alerts/issues",
                        params={**base, "very_high_scope": "corroborated"}).json()
    assert scoped["total_issues"] == corroborated == issues["total"], \
        "the card's number and the filtered table must be one population"
    # The bucket counts keep describing the whole population, like the other
    # cards, so the number that was clicked stays on screen.
    assert scoped["very_high_only_issues"] == summary["very_high_only_issues"]
    assert scoped["very_high_only_corroborated_issues"] == corroborated
    assert scoped["mixed_severity_issues"] == summary["mixed_severity_issues"]

    for item in issues["items"]:
        assert {p["severity"] for p in item["perspectives"]} == {"VERY_HIGH"}
        fired = {p.get("perspective") or p.get("label")
                 for p in item["perspectives"]}
        assert len(fired) > 1, item["indicator_code"]


def test_very_high_only_breakdown_states_the_two_subgroups_it_is_made_of(
        client, db_session, registry_dataset):
    """The Very High only card is a total, so it publishes its two parts.

    "Every fired perspective is Very High" covers two different shapes: an
    issue where ONE comparison fired (nothing was there to disagree with it)
    and an issue where two or more did and every one of them agreed. The card
    shows both, with their shares of the bucket, so its number is never read as
    agreement between comparisons — and the two parts partition the bucket
    exactly, which is the arithmetic the card states.
    """
    _scan(client, registry_dataset["scan_month"])
    month = registry_dataset["scan_month"]
    base = {"month": month, "severity": "VERY_HIGH", "page_size": 200}

    summary = client.get("/quality-alerts/summary", params=base).json()
    split = summary["very_high_only_breakdown"]
    only = summary["very_high_only_issues"]
    corroborated = summary["very_high_only_corroborated_issues"]
    single = summary["very_high_single_perspective_issues"]

    # The card's extra numbers are the existing counts, not a second opinion.
    assert split["total"] == only
    assert split["corroborated"] == corroborated
    assert split["single_perspective"] == single
    assert split["corroborated"] + split["single_perspective"] == split["total"]
    # And the bucket plus mixed severity is still the whole Very High population.
    assert (split["total"] + summary["mixed_severity_issues"]
            == summary["very_high_issues"])

    # Shares are computed server-side, one decimal, and add up to 100 on a
    # non-empty bucket; no NaN, no division by zero, no 0.0% on nothing.
    if split["total"]:
        assert split["corroborated_pct"] == round(
            100.0 * split["corroborated"] / split["total"], 1)
        assert round(split["corroborated_pct"]
                     + split["single_perspective_pct"], 1) == 100.0
    else:
        assert split["corroborated_pct"] == 0.0
        assert split["single_perspective_pct"] == 0.0
    assert 0.0 <= split["corroborated_pct"] <= 100.0
    assert 0.0 <= split["single_perspective_pct"] <= 100.0

    # Each filter lists exactly the subgroup it counts, and applying one does
    # not change the card's split (the number clicked stays beside its list).
    for scope, expected in (("only", split["total"]),
                            ("corroborated", split["corroborated"]),
                            ("mixed", summary["mixed_severity_issues"])):
        scoped = client.get("/quality-alerts/summary",
                            params={**base, "very_high_scope": scope}).json()
        issues = client.get("/quality-alerts/issues",
                            params={**base, "very_high_scope": scope}).json()
        assert scoped["total_issues"] == expected == issues["total"]
        assert scoped["very_high_only_breakdown"] == split
        assert scoped["very_high_only_issues"] == only
        assert scoped["very_high_only_corroborated_issues"] == corroborated

    # "Corroborated" is the multi-perspective part of the bucket: every issue
    # it lists fired on 2+ perspectives, all Very High, and it lists exactly
    # the subset of Very High only that did — never a single-perspective issue.
    only_issues = client.get("/quality-alerts/issues",
                             params={**base, "very_high_scope": "only"}).json()
    multi = [item for item in only_issues["items"]
             if len({p.get("perspective") or p.get("label")
                     for p in item["perspectives"]}) > 1]
    corroborated_issues = client.get(
        "/quality-alerts/issues",
        params={**base, "very_high_scope": "corroborated"}).json()
    assert corroborated_issues["total"] == len(multi) == corroborated
    for item in corroborated_issues["items"]:
        assert {p["severity"] for p in item["perspectives"]} == {"VERY_HIGH"}
        assert len({p.get("perspective") or p.get("label")
                    for p in item["perspectives"]}) > 1

    # Pagination still counts ISSUES, independently of the page size.
    paged = client.get("/quality-alerts/issues",
                       params={**base, "page_size": 1, "page": 1}).json()
    assert paged["total"] == summary["total_issues"]
    assert len(paged["items"]) == (1 if summary["total_issues"] else 0)

    # An empty scope reports zeros, not a share of nothing.
    empty = client.get("/quality-alerts/summary",
                       params={"month": "1900-01",
                               "severity": "VERY_HIGH"}).json()
    assert empty["very_high_only_breakdown"] == {
        "total": 0, "corroborated": 0, "single_perspective": 0,
        "corroborated_pct": 0.0, "single_perspective_pct": 0.0}


def test_very_high_scope_rejects_an_unknown_value(client):
    resp = client.get("/quality-alerts/issues",
                      params={"very_high_scope": "mostly"})
    assert resp.status_code == 422


# ── Closed review states + the Very High cards (Step 11B-1) ────────────────

def _clone_row(sample, **overrides):
    """A stored alert copying one scanned row, for evidence the scan can't make."""
    fields = dict(
        hospital_id=sample.hospital_id, month=sample.month,
        perspective=sample.perspective, indicator_id=sample.indicator_id,
        indicator_code=sample.indicator_code,
        indicator_name=sample.indicator_name, unit=sample.unit,
        formula=sample.formula, severity=sample.severity,
        method=sample.method, current_value=sample.current_value,
        baseline_value=sample.baseline_value,
        deviation_pct=sample.deviation_pct, peer_count=sample.peer_count,
        status="New", active=True)
    fields.update(overrides)
    return QualityAlert(**fields)


def _resolve(client, alerts):
    for alert in alerts:
        resp = client.post(f"/quality-alerts/{alert.id}/status",
                           json={"status": "Resolved"})
        assert resp.status_code == 200, resp.text


def test_closed_status_with_a_very_high_scope_lists_the_resolved_issues(
        client, db_session, registry_dataset):
    """A reviewed issue must still be gradeable by the Very High cards.

    ``status=Resolved`` returns rows the open view hides, so the evidence map
    has to be built with the same review state. When it was not, every issue in
    the response was missing from that map and the scope lookup raised
    KeyError: the table answered 500 instead of listing the resolved issues.
    """
    month = registry_dataset["scan_month"]
    _scan(client, month)
    base = {"month": month, "severity": "VERY_HIGH", "page_size": 200}

    spike = registry_dataset["hospitals"][0]
    spike_rows = db_session.query(QualityAlert).filter_by(
        active=True, month=month, indicator_code="QA_TEST_RATE",
        hospital_id=spike.id).all()
    assert len(spike_rows) >= 2, "the spike fires several perspectives"
    sample = spike_rows[0]

    # A second, MIXED issue (Very High beside a lower band) so both card scopes
    # are exercised with real data, not an empty result that hides the bug.
    peer = registry_dataset["peers"][0]
    free = next(p for p in ("ownership", "governorate", "facility_type",
                            "type", "all")
                if p not in {r.perspective for r in spike_rows})
    db_session.add_all([
        _clone_row(sample, hospital_id=peer.id, perspective="history",
                   severity="VERY_HIGH"),
        _clone_row(sample, hospital_id=peer.id, perspective=free,
                   severity="HIGH")])
    db_session.commit()
    peer_alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=peer.id, month=month,
        indicator_code="QA_TEST_RATE").all()

    open_summary = client.get("/quality-alerts/summary", params=base).json()
    assert open_summary["very_high_only_issues"] >= 1
    assert open_summary["mixed_severity_issues"] >= 1

    _resolve(client, spike_rows)
    _resolve(client, peer_alerts)
    db_session.expire_all()

    # Reviewing closes both issues; it never deletes them.
    after_open = client.get("/quality-alerts/summary", params=base).json()
    assert after_open["total_issues"] == open_summary["total_issues"] - 2

    resolved = {"status": "Resolved", **base}
    closed = client.get("/quality-alerts/summary", params=resolved).json()
    assert closed["total_issues"] == 2, "both reviewed issues must be listed"

    totals = {}
    for scope in ("only", "mixed", "corroborated"):
        params = {**resolved, "very_high_scope": scope}
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 200, resp.text
        listed = resp.json()
        summary = client.get("/quality-alerts/summary", params=params).json()
        totals[scope] = listed["total"]
        # The card's number and the filtered table stay one population.
        assert listed["total"] == summary["total_issues"]
        for item in listed["items"]:
            assert item["status"] == "Resolved"
            assert item["primary_severity"] == "VERY_HIGH"
            # Evidence is the stored evidence, never fabricated: every chip is
            # a real resolved perspective and the count matches them.
            assert item["perspectives"], "a listed issue carries its evidence"
            # ``perspective_count`` counts the rows THIS band filter let
            # through; ``perspectives`` is the issue's whole evidence, so it
            # can only be the larger of the two.
            assert item["perspective_count"] >= 1
            assert len(item["perspectives"]) >= item["perspective_count"]
            assert item["alert_ids"]
            assert all(p["status"] == "Resolved"
                       for p in item["perspectives"])
            bands = {p["severity"] for p in item["perspectives"]}
            assert "VERY_HIGH" in bands
            if scope == "mixed":
                assert bands != {"VERY_HIGH"}
            else:
                assert bands == {"VERY_HIGH"}
            if scope == "corroborated":
                assert len({p["perspective"]
                            for p in item["perspectives"]}) > 1

    # The scopes still partition the closed Very High population, and the
    # corroborated card is still the multi-perspective part of "only".
    assert totals["only"] + totals["mixed"] == closed["very_high_issues"]
    assert totals["corroborated"] <= totals["only"]
    assert totals["only"] == 1 and totals["mixed"] == 1

    # The open view is untouched: a Resolved row appears under status=New for
    # no scope, and its totals agree with the summary.
    for scope in ("only", "mixed", "corroborated"):
        params = {"month": month, "severity": "VERY_HIGH", "status": "New",
                  "very_high_scope": scope, "page_size": 200}
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == client.get(
            "/quality-alerts/summary", params=params).json()["total_issues"]
        assert all(item["status"] == "New" for item in body["items"])
        assert all(item["hospital_id"] != peer.id for item in body["items"])

    # include_closed reaches the same issues through the other switch, and its
    # totals agree with the summary too.
    for scope in ("only", "mixed", "corroborated"):
        params = {**base, "include_closed": "true",
                  "very_high_scope": scope}
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == client.get(
            "/quality-alerts/summary", params=params).json()["total_issues"]
        assert body["total"] >= totals[scope],             "including closed never hides an issue"
        assert any(item["status"] == "Resolved" for item in body["items"])

# ── Multi-perspective filtering (Step 11B-2, D5) ───────────────────────────
# The expected populations below are built from the stored rows with a plain
# group-by, never from the endpoint's own filters.

def _rows_by_issue(db, month, keys=None, hospital_id=None):
    """Issue -> the alert rows a perspective selection keeps, from the DB."""
    groups = {}
    for row in db.query(QualityAlert).filter(
            QualityAlert.active.is_(True), QualityAlert.month == month).all():
        if hospital_id and row.hospital_id != hospital_id:
            continue
        groups.setdefault((row.hospital_id, row.formula, row.unit,
                           row.indicator_code, row.month), []).append(row)
    out = set()
    for rows in groups.values():
        ids = frozenset(r.id for r in rows
                        if keys is None or r.perspective in keys)
        if ids:
            out.add(ids)
    return out


def _listed_issue_ids(payload):
    return {frozenset(item["alert_ids"]) for item in payload["items"]}


def _multi_perspective_dataset(client, db_session, registry_dataset):
    """Scan, then add two issues with known, different perspective sets."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    sample = db_session.query(QualityAlert).filter_by(
        active=True, month=month, hospital_id=spike.id).first()
    assert sample is not None, "the scan must store the spike"
    peers = registry_dataset["peers"]
    db_session.add_all([
        _clone_row(sample, hospital_id=peers[0].id, perspective="history",
                   severity="VERY_HIGH"),
        _clone_row(sample, hospital_id=peers[0].id, perspective="ownership",
                   severity="HIGH"),
        _clone_row(sample, hospital_id=peers[1].id,
                   perspective="governorate", severity="VERY_HIGH"),
    ])
    db_session.commit()
    return month, sample, peers


def test_multi_perspective_filter_is_the_union_of_the_chips(
        client, db_session, registry_dataset):
    """Two or more chips must filter server-side, not just the loaded page."""
    month, sample, peers = _multi_perspective_dataset(
        client, db_session, registry_dataset)
    base = {"month": month, "page_size": 0}

    everything = client.get("/quality-alerts/issues", params=base).json()
    all_ids = _rows_by_issue(db_session, month)
    assert _listed_issue_ids(everything) == all_ids
    assert everything["total"] == len(all_ids) == len(everything["items"])

    def listed(keys):
        params = {**base, "perspective": list(keys)}
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == len(body["items"]), \
            "the whole population, not one page"
        summary = client.get("/quality-alerts/summary", params=params).json()
        assert body["total"] == summary["total_issues"], \
            "list total and KPI total are one population"
        return body

    # No chip: unchanged.
    assert _listed_issue_ids(everything) == all_ids

    # One chip, for each key: exactly that perspective's issues.
    for keys in (("history",), ("governorate",), ("all",)):
        body = listed(keys)
        assert _listed_issue_ids(body) == _rows_by_issue(
            db_session, month, set(keys))

    # Two chips: the union, and strictly more than an AND would keep.
    pair = ("history", "governorate")
    union = _rows_by_issue(db_session, month, set(pair))
    body2 = listed(pair)
    assert _listed_issue_ids(body2) == union
    # OR, not AND: one selected comparison is enough to be in scope, so the
    # population is every issue carrying at least one of them.
    fired = {}
    for row in db_session.query(QualityAlert).filter(
            QualityAlert.active.is_(True), QualityAlert.month == month).all():
        fired.setdefault((row.hospital_id, row.formula, row.unit,
                          row.indicator_code, row.month), set()).add(
                              row.perspective)
    selected = set(pair)
    or_issues = sum(1 for p in fired.values() if p & selected)
    and_issues = sum(1 for p in fired.values() if selected <= p)
    assert or_issues > and_issues, "the fixture must distinguish OR from AND"
    assert body2["total"] == or_issues

    # Three chips: still the union.
    three = ("history", "governorate", "all")
    body3 = listed(three)
    assert _listed_issue_ids(body3) == _rows_by_issue(
        db_session, month, set(three))
    assert body3["total"] >= body2["total"]

    # A repeated or comma-separated key is the same selection, not a wider one.
    assert _listed_issue_ids(listed(("history", "history"))) == \
        _rows_by_issue(db_session, month, {"history"})
    comma = client.get("/quality-alerts/issues",
                       params={**base, "perspective": "history,governorate"})
    assert comma.status_code == 200, comma.text
    assert _listed_issue_ids(comma.json()) == union

    # No matching perspective: an empty population everywhere, no 500.
    empty_params = {**base, "hospital_id": peers[0].id,
                    "perspective": "governorate"}
    empty = client.get("/quality-alerts/issues", params=empty_params).json()
    assert empty["total"] == 0 and empty["items"] == []
    empty_sum = client.get("/quality-alerts/summary",
                           params=empty_params).json()
    assert empty_sum["total_issues"] == 0
    # The Very High card is not narrowed by a perspective selection (D2), so
    # the hospital's Very High finding is still counted here while the table,
    # which IS narrowed, is empty.
    assert empty_sum["very_high_issues"] == 1

    # An unknown key is a validation error, never a silently ignored filter.
    bad = client.get("/quality-alerts/issues",
                     params={**base, "perspective": "nonsense"})
    assert bad.status_code == 422

    # Whole-evidence classification survives the row-level filter: the issue
    # lists one matching row but still shows every perspective it fired.
    hist = client.get("/quality-alerts/issues",
                      params={**base, "hospital_id": peers[0].id,
                              "perspective": "history"}).json()
    assert hist["total"] == 1
    item = hist["items"][0]
    assert {p["perspective"] for p in item["perspectives"]} == {
        "history", "ownership"}
    assert {p["perspective"] for p in item["perspectives"]
            if p["id"] in item["alert_ids"]} == {"history"}


def test_multi_perspective_pages_and_combines_with_the_other_filters(
        client, db_session, registry_dataset):
    """Paging, band, confidence, card scope and geography all narrow together."""
    month, sample, peers = _multi_perspective_dataset(
        client, db_session, registry_dataset)
    keys = ["history", "governorate"]
    base = {"month": month, "perspective": keys}

    full = client.get("/quality-alerts/issues",
                      params={**base, "page_size": 0}).json()
    expected = _rows_by_issue(db_session, month, set(keys))
    assert _listed_issue_ids(full) == expected
    assert full["total"] == len(expected) >= 2

    # Walk one-issue pages: no duplicate, no gap, total stable on every page.
    seen = set()
    pages = 0
    while len(seen) < full["total"]:
        pages += 1
        chunk = client.get("/quality-alerts/issues",
                           params={**base, "page_size": 1,
                                   "page": pages}).json()
        assert chunk["total"] == full["total"]
        ids = _listed_issue_ids(chunk)
        assert not (ids & seen), "an issue must appear on exactly one page"
        seen |= ids
    assert seen == expected and pages == full["total"] > 1

    # Band filter: the same population narrowed, and the KPI follows it.
    vh = client.get("/quality-alerts/issues",
                    params={**base, "severity": "VERY_HIGH",
                            "page_size": 0}).json()
    vh_summary = client.get("/quality-alerts/summary",
                            params={**base, "severity": "VERY_HIGH"}).json()
    assert vh["total"] == vh_summary["total_issues"] <= full["total"]
    assert all(item["primary_severity"] == "VERY_HIGH"
               for item in vh["items"])
    assert _listed_issue_ids(vh) <= _listed_issue_ids(full)

    # Confidence filter: same rule.
    conf = client.get("/quality-alerts/issues",
                      params={**base, "confidence": "high",
                              "page_size": 0}).json()
    conf_summary = client.get("/quality-alerts/summary",
                              params={**base, "confidence": "high"}).json()
    assert conf["total"] == conf_summary["total_issues"] <= full["total"]
    assert _listed_issue_ids(conf) <= _listed_issue_ids(full)

    # Card scope: still graded from the whole evidence of each issue.
    mixed = client.get("/quality-alerts/issues",
                       params={**base, "severity": "VERY_HIGH",
                               "very_high_scope": "mixed",
                               "page_size": 0}).json()
    mixed_summary = client.get("/quality-alerts/summary",
                               params={**base, "severity": "VERY_HIGH",
                                       "very_high_scope": "mixed"}).json()
    assert mixed["total"] == mixed_summary["total_issues"] <= full["total"]
    for item in mixed["items"]:
        bands = {p["severity"] for p in item["perspectives"]}
        assert "VERY_HIGH" in bands and bands != {"VERY_HIGH"}

    # Month + hospital stay conjunctive with the chip selection.
    scoped = client.get("/quality-alerts/issues",
                        params={"month": month, "hospital_id": peers[0].id,
                                "perspective": ["history", "ownership"],
                                "page_size": 0}).json()
    assert scoped["total"] == 1
    assert _listed_issue_ids(scoped) == _rows_by_issue(
        db_session, month, {"history", "ownership"},
        hospital_id=peers[0].id)
# ── KPI scope: two populations (Step 11B-2, D2) ────────────────────────────
# The oracle below groups the stored rows itself; it never calls the endpoint's
# filter helpers or its issue-key helper, so the expected populations are
# independently constructed. Every request is scoped to the registry indicator
# so that alerts the scan also raises on the raw data elements cannot widen the
# comparison.

_D2_IND = "QA_TEST_RATE"
_CLOSED_STATUSES = ("Resolved", "False Positive")


def _oracle_issue_rows(db, *, month=None, hospital_id=None, status=None,
                       include_closed=False):
    """issue key -> [(stored band, perspective)] under the GENERAL filters."""
    groups = {}
    for row in db.query(QualityAlert).filter(QualityAlert.active.is_(True)).all():
        if row.indicator_code != _D2_IND:
            continue
        if month and row.month != month:
            continue
        if hospital_id and row.hospital_id != hospital_id:
            continue
        if status and row.status != status:
            continue
        if not status and not include_closed and row.status in _CLOSED_STATUSES:
            continue
        key = (row.hospital_id, row.formula, row.unit, row.indicator_code,
               row.month)
        groups.setdefault(key, []).append((row.severity, row.perspective))
    return groups


def _oracle_filtered_total(issues, severity=None, perspectives=None):
    """The FILTERED ISSUE population: ONE row must satisfy both selections.

    The band and the perspective narrow WHICH ROWS matched, so an issue is
    listed when a single stored row is both in the selected band and on a
    selected perspective — never when the issue carries each of them on
    different rows.
    """
    total = 0
    for rows in issues.values():
        if any((not severity or band == severity)
               and (not perspectives or p in perspectives)
               for band, p in rows):
            total += 1
    return total


def _oracle_very_high(issues):
    """(very high, only, mixed) from each issue's whole evidence."""
    only = mixed = 0
    for rows in issues.values():
        bands = {band for band, _ in rows}
        if "VERY_HIGH" not in bands:
            continue
        if bands == {"VERY_HIGH"}:
            only += 1
        else:
            mixed += 1
    return only + mixed, only, mixed


def _oracle_scope(issues, scope):
    """Issue count for a card scope, from the whole evidence of each issue."""
    hit = 0
    for rows in issues.values():
        bands = {band for band, _ in rows}
        if "VERY_HIGH" not in bands:
            continue
        fired = {p for _, p in rows}
        if scope == "mixed":
            hit += 1 if bands != {"VERY_HIGH"} else 0
        elif bands == {"VERY_HIGH"}:
            if scope == "only" or len(fired) > 1:
                hit += 1
    return hit


def _d2_dataset(client, db_session, registry_dataset):
    """Scan, then add one issue per band plus one mixed Very High issue."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    sample = db_session.query(QualityAlert).filter_by(
        active=True, month=month, hospital_id=spike.id,
        indicator_code=_D2_IND).first()
    assert sample is not None
    # hospitals[0] is the spike; the other two registered hospitals and the
    # two flat peers give four hospitals with no finding of their own, one per
    # band plus the mixed issue.
    others = list(registry_dataset["hospitals"][1:]) + list(
        registry_dataset["peers"])
    assert len(others) >= 4, "need a hospital per band"
    # others[0] HIGH only, others[1] MODERATE only, others[2] LOW only,
    # others[3] Very High + HIGH (mixed). None of them reports a VH finding.
    db_session.add_all([
        _clone_row(sample, hospital_id=others[0].id, perspective="history",
                   severity="HIGH"),
        _clone_row(sample, hospital_id=others[1].id, perspective="history",
                   severity="MODERATE"),
        _clone_row(sample, hospital_id=others[2].id, perspective="history",
                   severity="LOW"),
        _clone_row(sample, hospital_id=others[3].id, perspective="history",
                   severity="VERY_HIGH"),
        _clone_row(sample, hospital_id=others[3].id, perspective="ownership",
                   severity="HIGH"),
    ])
    db_session.commit()
    return month, sample, others


def test_very_high_kpis_do_not_follow_the_severity_filter(
        client, db_session, registry_dataset):
    """Choosing HIGH moves the table and the total, never the Very High cards."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)
    corroborated = _oracle_scope(issues, "corroborated")
    assert vh >= 2 and only >= 1 and mixed >= 1

    seen = {}
    for severity in (None, "VERY_HIGH", "HIGH", "MODERATE", "LOW"):
        params = {"month": month, "indicator": _D2_IND}
        if severity:
            params["severity"] = severity
        summary = client.get("/quality-alerts/summary", params=params).json()
        listed = client.get("/quality-alerts/issues",
                            params={**params, "page_size": 0}).json()
        expected_total = _oracle_filtered_total(issues, severity=severity)
        assert summary["total_issues"] == listed["total"] == expected_total, \
            f"total_issues must follow the band filter ({severity})"
        assert summary["very_high_issues"] == vh
        assert summary["very_high_only_issues"] == only
        assert summary["mixed_severity_issues"] == mixed
        assert summary["very_high_only_corroborated_issues"] == corroborated
        seen[severity] = (summary["very_high_issues"],
                          summary["very_high_only_issues"],
                          summary["mixed_severity_issues"],
                          summary["very_high_only_corroborated_issues"])

    # One Very High population, five band selections.
    assert len(set(seen.values())) == 1, "Very High KPIs must be band-stable"

    totals = {
        severity: client.get("/quality-alerts/summary",
                             params={"month": month, "indicator": _D2_IND,
                                     "severity": severity}).json()["total_issues"]
        for severity in ("VERY_HIGH", "HIGH", "MODERATE", "LOW")
    }
    assert totals == {severity: _oracle_filtered_total(issues, severity=severity)
                      for severity in totals}
    assert len(set(totals.values())) >= 2, "the band filter must move total_issues"

    # A hospital with no Very High finding: the table counts its High issue,
    # and the Very High card does not invent one for it.
    high_only = client.get("/quality-alerts/summary",
                           params={"month": month, "indicator": _D2_IND,
                                   "hospital_id": others[0].id,
                                   "severity": "HIGH"}).json()
    assert high_only["total_issues"] == 1
    assert high_only["very_high_issues"] == 0

    # The spike hospital: no HIGH row at all, yet its Very High finding is
    # still counted while HIGH is the selected band.
    no_high = client.get("/quality-alerts/summary",
                         params={"month": month, "indicator": _D2_IND,
                                 "hospital_id": sample.hospital_id,
                                 "severity": "HIGH"}).json()
    assert no_high["total_issues"] == 0
    assert no_high["very_high_issues"] == 1, \
        "a Very High finding is still Very High when HIGH is selected"
    assert no_high["very_high_only_issues"] == 1


def test_card_scope_narrows_the_list_but_not_the_kpi_population(
        client, db_session, registry_dataset):
    """A clicked card filters the table; the cards keep describing the scope."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)
    base = {"month": month, "indicator": _D2_IND, "severity": "VERY_HIGH"}

    for scope in ("only", "mixed", "corroborated"):
        params = {**base, "very_high_scope": scope}
        summary = client.get("/quality-alerts/summary", params=params).json()
        listed = client.get("/quality-alerts/issues",
                            params={**params, "page_size": 0}).json()
        assert summary["total_issues"] == listed["total"] == _oracle_scope(
            issues, scope)
        # The three cards describe one population whatever is active.
        assert summary["very_high_issues"] == vh
        assert summary["very_high_only_issues"] == only
        assert summary["mixed_severity_issues"] == mixed
        assert summary["very_high_only_corroborated_issues"] == \
            _oracle_scope(issues, "corroborated")

    # Card scope combined with a LOWER band: the list keeps both filters, the
    # cards still follow neither of them.
    for severity in ("HIGH", "MODERATE"):
        for scope in ("only", "mixed", "corroborated"):
            params = {"month": month, "indicator": _D2_IND,
                      "severity": severity, "very_high_scope": scope}
            summary = client.get("/quality-alerts/summary",
                                 params=params).json()
            listed = client.get("/quality-alerts/issues",
                                params={**params, "page_size": 0}).json()
            expected = 0
            for rows in issues.values():
                bands = {band for band, _ in rows}
                fired = {p for _, p in rows}
                if severity not in bands:
                    continue
                if scope == "mixed":
                    expected += 1 if "VERY_HIGH" in bands else 0
                elif bands == {"VERY_HIGH"}:
                    expected += 1 if (scope == "only"
                                      or len(fired) > 1) else 0
            assert summary["total_issues"] == listed["total"] == expected, \
                f"{severity}+{scope}"
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed


def test_very_high_kpis_ignore_the_perspective_selection(
        client, db_session, registry_dataset):
    """Perspective narrows the table (D5 OR) and never the Very High cards."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)
    corroborated = _oracle_scope(issues, "corroborated")

    selections = (["history"], ["ownership"], ["history", "ownership"],
                  ["all", "type", "history"])
    for selection in selections:
        for severity in (None, "HIGH"):
            params = {"month": month, "indicator": _D2_IND,
                      "perspective": selection}
            if severity:
                params["severity"] = severity
            summary = client.get("/quality-alerts/summary",
                                 params=params).json()
            listed = client.get("/quality-alerts/issues",
                                params={**params, "page_size": 0}).json()
            expected = _oracle_filtered_total(issues, severity=severity,
                                              perspectives=set(selection))
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed
            assert summary["very_high_only_corroborated_issues"] == corroborated


def test_kpi_scope_with_month_hospital_closed_status_and_paging(
        client, db_session, registry_dataset):
    """The KPI population follows the general scope, and paging never drifts."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)

    # Month + hospital + band: the table is band-narrowed, the cards are the
    # Very High findings of that hospital and month.
    scoped = {"month": month, "indicator": _D2_IND,
              "hospital_id": others[3].id, "severity": "HIGH"}
    summary = client.get("/quality-alerts/summary", params=scoped).json()
    listed = client.get("/quality-alerts/issues",
                        params={**scoped, "page_size": 0}).json()
    scoped_issues = _oracle_issue_rows(db_session, month=month,
                                       hospital_id=others[3].id)
    s_vh, s_only, s_mixed = _oracle_very_high(scoped_issues)
    assert (s_vh, s_only, s_mixed) == (1, 0, 1)
    assert summary["total_issues"] == listed["total"] == 1
    assert summary["very_high_issues"] == 1
    assert summary["mixed_severity_issues"] == 1

    # Closed status + band: reviewed rows leave the open view, and the cards
    # describe the reviewed Very High findings once that status is asked for.
    for row in db_session.query(QualityAlert).filter_by(
            hospital_id=others[3].id, month=month, status="New",
            indicator_code=_D2_IND).all():
        resp = client.post(f"/quality-alerts/{row.id}/status",
                           json={"status": "Resolved"})
        assert resp.status_code == 200, resp.text
    db_session.expire_all()

    closed = {"month": month, "indicator": _D2_IND, "status": "Resolved",
              "severity": "HIGH"}
    closed_summary = client.get("/quality-alerts/summary",
                                params=closed).json()
    closed_list = client.get("/quality-alerts/issues",
                             params={**closed, "page_size": 0}).json()
    closed_issues = _oracle_issue_rows(db_session, month=month,
                                       status="Resolved")
    c_vh, c_only, c_mixed = _oracle_very_high(closed_issues)
    assert (c_vh, c_only, c_mixed) == (1, 0, 1), "one reviewed mixed issue"
    assert closed_summary["total_issues"] == closed_list["total"] == 1
    assert closed_summary["very_high_issues"] == c_vh == 1
    assert closed_summary["very_high_only_issues"] == 0
    assert closed_summary["mixed_severity_issues"] == 1

    # Open view again: the reviewed issue is gone from both populations.
    open_issues = _oracle_issue_rows(db_session, month=month,
                                     hospital_id=others[3].id)
    assert open_issues == {}
    open_summary = client.get("/quality-alerts/summary",
                              params={"month": month, "indicator": _D2_IND,
                                      "hospital_id": others[3].id}).json()
    assert open_summary["total_issues"] == 0
    assert open_summary["very_high_issues"] == 0

    # Paging: every page repeats the same totals and the same Very High cards.
    page = 0
    seen = set()
    while True:
        page += 1
        params = {"month": month, "indicator": _D2_IND,
                  "page_size": 1, "page": page}
        chunk = client.get("/quality-alerts/issues", params=params).json()
        summary = client.get("/quality-alerts/summary",
                             params={"month": month,
                                     "indicator": _D2_IND}).json()
        all_issues = _oracle_issue_rows(db_session, month=month)
        vh, only, mixed = _oracle_very_high(all_issues)
        expected = _oracle_filtered_total(all_issues)
        assert chunk["total"] == summary["total_issues"] == expected
        assert summary["very_high_issues"] == vh
        assert summary["very_high_only_issues"] == only
        assert summary["mixed_severity_issues"] == mixed
        ids = {tuple(item["alert_ids"]) for item in chunk["items"]}
        assert not (ids & seen)
        seen |= ids
        if not chunk["items"] or len(seen) >= chunk["total"]:
            break
    assert len(seen) == expected and page > 1, "several pages were walked"

# ── D3: indicator_type parameter validation ────────────────────────────────
# The screen offers exactly two type tokens. Data Element rows are scanned from
# the raw catalog and carry no IndicatorDefinition FK; Derivative Indicator rows
# always carry one. The oracle below re-groups the stored rows itself — it never
# imports the production filter — and treats the parameter as a ROW-level
# selection: an issue is in scope when at least one of its rows is of the asked
# kind, exactly like the perspective chips.

_D3_ELEMENT = "QA_D3_ELEMENT"
_D3_DERIVATIVE = "QA_D3_DERIVATIVE"
_D3_BAD_VALUES = ("bogus", "ELEMENT", "Element", "elements",
                  "element,derivative", "all")


def _oracle_type_rows(db, month, hospital_id=None):
    """issue key -> stored rows of that month, under the general scope."""
    groups = {}
    for row in db.query(QualityAlert).filter(
            QualityAlert.active.is_(True),
            QualityAlert.month == month).all():
        if hospital_id and row.hospital_id != hospital_id:
            continue
        groups.setdefault((row.hospital_id, row.formula, row.unit,
                           row.indicator_code, row.month), []).append(row)
    return groups


def _oracle_type_issues(groups, indicator_type=None):
    """Issue keys whose rows include the asked registration kind."""
    if indicator_type is None:
        return set(groups)
    return {key for key, rows in groups.items()
            if any((row.indicator_id is None) == (indicator_type == "element")
                   for row in rows)}


def _oracle_type_total(groups, indicator_type=None, severity=None,
                       perspectives=None, scope=None):
    """The filtered issue count: row-level selections, then whole-evidence scope."""
    def kind_ok(row):
        if not indicator_type:
            return True
        return (row.indicator_id is None) == (indicator_type == "element")

    total = 0
    for rows in groups.values():
        scoped = [row for row in rows if kind_ok(row)]
        if not scoped:
            continue
        if not any((not severity or row.severity == severity)
                   and (not perspectives or row.perspective in perspectives)
                   for row in scoped):
            continue
        if scope:
            bands = {row.severity for row in scoped}
            if "VERY_HIGH" not in bands:
                continue
            if scope == "mixed" and bands == {"VERY_HIGH"}:
                continue
            if scope in ("only", "corroborated") and bands != {"VERY_HIGH"}:
                continue
            if scope == "corroborated" and len(
                    {row.perspective for row in scoped}) < 2:
                continue
        total += 1
    return total


def _oracle_type_very_high(groups, indicator_type=None):
    """(very high, only, mixed) for the type-scoped population."""
    vh = only = mixed = 0
    for rows in groups.values():
        scoped = [row for row in rows
                  if not indicator_type
                  or (row.indicator_id is None) == (indicator_type == "element")]
        bands = {row.severity for row in scoped}
        if "VERY_HIGH" not in bands:
            continue
        vh += 1
        if bands == {"VERY_HIGH"}:
            only += 1
        else:
            mixed += 1
    return vh, only, mixed


def _d3_dataset(client, db_session, registry_dataset):
    """Scan, then add one guaranteed issue of each registration kind."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    sample = db_session.query(QualityAlert).filter_by(
        active=True, month=month, hospital_id=spike.id,
        indicator_code=_D2_IND).first()
    assert sample is not None, "the scan must store the spike"
    assert sample.indicator_id is not None, "the spike is a derivative finding"
    others = list(registry_dataset["hospitals"][1:]) + list(
        registry_dataset["peers"])
    element_hospital, derivative_hospital = others[0], others[1]
    db_session.add_all([
        # A Data Element finding: no registry definition behind the row.
        _clone_row(sample, hospital_id=element_hospital.id,
                   perspective="history", indicator_id=None,
                   indicator_code=_D3_ELEMENT,
                   indicator_name="QA D3 data element", severity="VERY_HIGH"),
        # A Derivative finding: the definition FK is what makes it one.
        _clone_row(sample, hospital_id=derivative_hospital.id,
                   perspective="history", indicator_code=_D3_DERIVATIVE,
                   indicator_name="QA D3 derivative", severity="HIGH"),
    ])
    db_session.commit()
    return month, sample, others


def test_indicator_type_omitted_and_empty_are_the_unfiltered_scope(
        client, db_session, registry_dataset):
    """No value, an empty value and a blank value all mean "no type filter"."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)
    groups = _oracle_type_rows(db_session, month)
    expected = _oracle_type_total(groups)
    assert expected > 0

    def snapshot(params):
        listed = client.get("/quality-alerts/issues", params=params)
        summary = client.get("/quality-alerts/summary", params=params)
        assert listed.status_code == 200, listed.text
        assert summary.status_code == 200, summary.text
        body = listed.json()
        assert body["total"] == summary.json()["total_issues"] == expected
        return _listed_issue_ids(body), body["total"]

    base = {"month": month, "page_size": 0}
    omitted_ids, omitted_total = snapshot(base)
    assert omitted_ids == _rows_by_issue(db_session, month)
    assert snapshot({**base, "indicator_type": ""}) == (omitted_ids,
                                                        omitted_total)
    # Whitespace is trimmed, so a blank value is still "no filter".
    assert snapshot({**base, "indicator_type": "  "}) == (omitted_ids,
                                                          omitted_total)


def test_indicator_type_valid_values_select_by_registration_kind(
        client, db_session, registry_dataset):
    """Both offered tokens filter by how the indicator is registered."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)
    groups = _oracle_type_rows(db_session, month)
    all_ids = _rows_by_issue(db_session, month)

    populations = {}
    for indicator_type in ("element", "derivative"):
        params = {"month": month, "indicator_type": indicator_type,
                  "page_size": 0}
        listed = client.get("/quality-alerts/issues", params=params)
        summary = client.get("/quality-alerts/summary",
                             params={"month": month,
                                     "indicator_type": indicator_type})
        assert listed.status_code == 200, listed.text
        assert summary.status_code == 200, summary.text
        body = listed.json()
        # Oracle population, from the stored rows only.
        oracle_keys = _oracle_type_issues(groups, indicator_type)
        expected_total = _oracle_type_total(groups, indicator_type)
        assert body["total"] == summary.json()["total_issues"] == expected_total
        assert body["total"] == len(oracle_keys) == len(body["items"])
        assert _listed_issue_ids(body) == _issue_ids_of(groups, indicator_type)
        assert body["total"] > 0, f"{indicator_type} population must be real"
        populations[indicator_type] = body["total"]

    # The two kinds together are every issue: every row is one or the other.
    assert sum(populations.values()) == len(all_ids)
    # Each kind is narrower than the whole month, so the filter does something.
    assert min(populations.values()) < len(all_ids)

    # The explicitly built findings land on exactly one side each.
    element_only = client.get("/quality-alerts/issues",
                              params={"month": month,
                                      "indicator_type": "element",
                                      "indicator": _D3_ELEMENT,
                                      "page_size": 0}).json()
    assert element_only["total"] == 1
    derivative_only = client.get("/quality-alerts/issues",
                                 params={"month": month,
                                         "indicator_type": "derivative",
                                         "indicator": _D3_DERIVATIVE,
                                         "page_size": 0}).json()
    assert derivative_only["total"] == 1

    # Surrounding whitespace is trimmed; the token's case is NOT folded.
    padded = client.get("/quality-alerts/issues",
                        params={"month": month,
                                "indicator_type": " element ",
                                "page_size": 0})
    assert padded.status_code == 200, padded.text
    assert padded.json()["total"] == populations["element"]


def _issue_ids_of(groups, indicator_type):
    """Alert-id sets for the issues of one kind, for the list comparison."""
    out = set()
    for rows in groups.values():
        if any((row.indicator_id is None) == (indicator_type == "element")
               for row in rows):
            out.add(frozenset(row.id for row in rows))
    return out


def test_indicator_type_rejects_unknown_values_on_both_endpoints(
        client, db_session, registry_dataset):
    """An unknown token is a 422 that names it and the supported values."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)
    unfiltered = client.get("/quality-alerts/summary",
                            params={"month": month}).json()["total_issues"]
    assert unfiltered > 0, "the silent-ignore bug would have returned this"

    for value in _D3_BAD_VALUES:
        for path in ("/quality-alerts/summary", "/quality-alerts/issues"):
            resp = client.get(path, params={"month": month,
                                            "indicator_type": value})
            assert resp.status_code == 422, \
                f"{path}?indicator_type={value!r} -> {resp.status_code}"
            detail = resp.json()["detail"]
            assert "indicator_type" in detail, detail
            assert value in detail, f"the error must name {value!r}: {detail}"
            for valid in ("element", "derivative"):
                assert valid in detail, f"the error must list {valid}: {detail}"
            # An error body carries no population: nothing was silently served.
            assert "total_issues" not in resp.json()
            assert "items" not in resp.json()

    # The valid values still answer 200 on both endpoints.
    for path in ("/quality-alerts/summary", "/quality-alerts/issues"):
        for valid in ("element", "derivative"):
            assert client.get(path, params={"month": month,
                                            "indicator_type": valid}
                              ).status_code == 200


def test_indicator_type_combines_with_band_perspective_and_card_scope(
        client, db_session, registry_dataset):
    """A valid type keeps every other filter, and D2/D5 still hold."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)

    # Type + month + hospital: the table and the totals are one population.
    hospital_id = others[0].id
    groups = _oracle_type_rows(db_session, month, hospital_id=hospital_id)
    for indicator_type in (None, "element", "derivative"):
        params = {"month": month, "hospital_id": hospital_id}
        if indicator_type:
            params["indicator_type"] = indicator_type
        summary = client.get("/quality-alerts/summary", params=params).json()
        listed = client.get("/quality-alerts/issues",
                            params={**params, "page_size": 0}).json()
        expected = _oracle_type_total(groups, indicator_type)
        assert summary["total_issues"] == listed["total"] == expected

    # Back to the month-wide population for the remaining combinations.
    groups = _oracle_type_rows(db_session, month)

    # Type + band + perspective: row-level conjunction, exactly like D5.
    for indicator_type in ("element", "derivative"):
        for selection in (["history"], ["history", "ownership"], ["all"]):
            for severity in (None, "VERY_HIGH", "HIGH", "MODERATE"):
                params = {"month": month, "indicator_type": indicator_type,
                          "perspective": selection}
                if severity:
                    params["severity"] = severity
                summary = client.get("/quality-alerts/summary",
                                     params=params).json()
                listed = client.get("/quality-alerts/issues",
                                    params={**params, "page_size": 0}).json()
                expected = _oracle_type_total(
                    groups, indicator_type, severity=severity,
                    perspectives=set(selection))
                assert summary["total_issues"] == listed["total"] == expected, \
                    f"{indicator_type} + {selection} + {severity}"

    # Type + card scope: the list narrows, the cards stay one population.
    for indicator_type in ("element", "derivative"):
        vh, only, mixed = _oracle_type_very_high(groups, indicator_type)
        for scope in ("only", "mixed", "corroborated"):
            params = {"month": month, "indicator_type": indicator_type,
                      "severity": "VERY_HIGH", "very_high_scope": scope}
            summary = client.get("/quality-alerts/summary",
                                 params=params).json()
            listed = client.get("/quality-alerts/issues",
                                params={**params, "page_size": 0}).json()
            expected = _oracle_type_total(groups, indicator_type,
                                          scope=scope)
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed


def test_indicator_type_keeps_d2_very_high_kpis_off_the_band_filter(
        client, db_session, registry_dataset):
    """A valid type is a general filter: cards follow it, not the band/chips."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)
    groups = _oracle_type_rows(db_session, month)

    for indicator_type in ("element", "derivative"):
        vh, only, mixed = _oracle_type_very_high(groups, indicator_type)
        seen = set()
        totals = set()
        for severity in (None, "VERY_HIGH", "HIGH", "MODERATE"):
            summary = client.get("/quality-alerts/summary",
                                 params={**({"month": month,
                                             "indicator_type": indicator_type}),
                                         **({"severity": severity}
                                            if severity else {})}).json()
            listed = client.get("/quality-alerts/issues",
                                params={"month": month,
                                        "indicator_type": indicator_type,
                                        "severity": severity,
                                        "page_size": 0}).json()
            expected = _oracle_type_total(groups, indicator_type,
                                          severity=severity)
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed
            seen.add((summary["very_high_issues"],
                      summary["very_high_only_issues"],
                      summary["mixed_severity_issues"]))
            totals.add(summary["total_issues"])
        assert len(seen) == 1, "the cards must not follow the band"
        assert len(totals) > 1, "the band must still move total_issues"

        # Perspective chips move the list (D5 OR) and never the cards.
        for selection in (["history"], ["history", "ownership"],
                          ["all", "type"]):
            summary = client.get("/quality-alerts/summary",
                                 params={"month": month,
                                         "indicator_type": indicator_type,
                                         "perspective": selection}).json()
            listed = client.get("/quality-alerts/issues",
                                params={"month": month,
                                        "indicator_type": indicator_type,
                                        "perspective": selection,
                                        "page_size": 0}).json()
            expected = _oracle_type_total(groups, indicator_type,
                                          perspectives=set(selection))
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed

        # D5 is still OR: two chips keep at least what each keeps alone.
        one = client.get("/quality-alerts/issues",
                         params={"month": month, "page_size": 0,
                                 "indicator_type": indicator_type,
                                 "perspective": ["history"]}).json()["total"]
        two = client.get("/quality-alerts/issues",
                         params={"month": month, "page_size": 0,
                                 "indicator_type": indicator_type,
                                 "perspective": ["history", "ownership"]}
                         ).json()["total"]
        assert two >= one


def test_indicator_type_without_matches_is_empty_not_an_error(
        client, db_session, registry_dataset):
    """A valid type that matches nothing is an empty population, not a 422."""
    month, sample, others = _d3_dataset(client, db_session, registry_dataset)
    for indicator_type, indicator in (("derivative", _D3_ELEMENT),
                                      ("element", _D3_DERIVATIVE)):
        params = {"month": month, "indicator_type": indicator_type,
                  "indicator": indicator}
        summary = client.get("/quality-alerts/summary", params=params)
        listed = client.get("/quality-alerts/issues",
                            params={**params, "page_size": 0})
        assert summary.status_code == 200, summary.text
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 0 and body["items"] == []
        assert summary.json()["total_issues"] == 0
        assert summary.json()["very_high_issues"] == 0

# ── D4: severity × Very High card scope ────────────────────────────────────
# The two are independent concepts (see the KPI SCOPE contract): the Very High
# cards describe the scope and ignore the band, the chips and the card; the
# list is the INTERSECTION of the selected band, the selected comparisons and
# the card scope. The oracle below applies exactly that rule to the stored
# rows, without calling any production filter.

def _oracle_intersection(issues, severity=None, scope=None, perspectives=None):
    """Issues with a row in the band AND the whole evidence inside the scope.

    The band and the perspectives narrow WHICH ROWS matched (one row must carry
    both), while a card scope grades the issue's whole evidence — so the pair is
    an intersection: neither filter replaces the other, and an empty result is
    a legitimate answer rather than a reason to widen either one.
    """
    total = 0
    for rows in issues.values():
        bands = {band for band, _ in rows}
        if not any((not severity or band == severity)
                   and (not perspectives or p in perspectives)
                   for band, p in rows):
            continue
        if scope == "mixed":
            inside = "VERY_HIGH" in bands and bands != {"VERY_HIGH"}
        elif scope in ("only", "corroborated"):
            inside = bands == {"VERY_HIGH"}
            if inside and scope == "corroborated":
                inside = len({p for _, p in rows}) > 1
        else:
            inside = True
        total += 1 if inside else 0
    return total


def _d4_matrix(client, month, severity, scope, perspectives=None, **extra):
    """Both endpoints for one band × scope combination, status-checked."""
    params = {"month": month, "indicator": _D2_IND}
    if severity:
        params["severity"] = severity
    if scope:
        params["very_high_scope"] = scope
    if perspectives:
        params["perspective"] = list(perspectives)
    params.update(extra)
    summary = client.get("/quality-alerts/summary", params=params)
    listed = client.get("/quality-alerts/issues",
                        params={**params, "page_size": 0})
    assert summary.status_code == listed.status_code == 200, \
        (params, summary.text, listed.text)
    return summary.json(), listed.json()


def test_severity_and_card_scope_intersect_at_every_band(
        client, db_session, registry_dataset):
    """Every band × scope pair is an intersection, including the empty ones."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)
    corroborated = _oracle_scope(issues, "corroborated")
    assert vh >= 2 and only >= 1 and mixed >= 1

    empties = []
    for severity in (None, "VERY_HIGH", "HIGH", "MODERATE", "LOW"):
        for scope in (None, "only", "mixed", "corroborated"):
            summary, listed = _d4_matrix(client, month, severity, scope)
            expected = _oracle_intersection(issues, severity, scope)
            assert summary["total_issues"] == listed["total"] == expected, \
                f"{severity}+{scope}"
            # D2: one Very High population in every combination.
            assert summary["very_high_issues"] == vh
            assert summary["very_high_only_issues"] == only
            assert summary["mixed_severity_issues"] == mixed
            assert summary["very_high_only_corroborated_issues"] == corroborated
            if expected == 0:
                empties.append((severity, scope))
                assert listed["items"] == []
                # Not an error, and never an implied zero Very High population.
                assert summary["very_high_issues"] == vh > 0

    # The matrix really contains the empty intersections the screen can
    # produce — a lower band with a Very High-only card — and they are only
    # empty because of the pair, not because the band has no findings at all.
    assert ("HIGH", "only") in empties
    assert ("MODERATE", "only") in empties
    assert any(severity == "LOW" for severity, _ in empties)
    assert (None, "only") not in empties
    assert _oracle_intersection(issues, "VERY_HIGH", "only") > 0


def test_lower_band_with_a_card_scope_stays_an_intersection(
        client, db_session, registry_dataset):
    """HIGH/MODERATE + a card never falls back to the card's own population."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)

    for severity in ("HIGH", "MODERATE"):
        for scope in ("only", "mixed", "corroborated"):
            summary, listed = _d4_matrix(client, month, severity, scope)
            expected = _oracle_intersection(issues, severity, scope)
            assert summary["total_issues"] == listed["total"] == expected
            # The scope's own population is NOT what the list shows.
            assert summary["total_issues"] <= _oracle_scope(issues, scope)
            assert summary["very_high_issues"] == vh

    # Concretely: HIGH + only is empty (an every-perspective Very High issue
    # never carries a High row), while HIGH + mixed keeps the mixed issues
    # that do carry one.
    high_only_summary, high_only_list = _d4_matrix(client, month, "HIGH",
                                                   "only")
    assert high_only_summary["total_issues"] == high_only_list["total"] == 0
    assert high_only_summary["very_high_issues"] == vh
    high_mixed_summary, high_mixed_list = _d4_matrix(client, month, "HIGH",
                                                     "mixed")
    expected = _oracle_intersection(issues, "HIGH", "mixed")
    assert expected > 0
    assert high_mixed_summary["total_issues"] == high_mixed_list["total"] == \
        expected


def test_band_scope_and_perspective_or_together(
        client, db_session, registry_dataset):
    """D5 OR inside each chip set still intersects with band and card scope."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)

    combos = [(None, None), ("HIGH", None), (None, "only"), ("HIGH", "only"),
              ("VERY_HIGH", "mixed"), ("MODERATE", "mixed")]
    for severity, scope in combos:
        for selection in (("history",), ("history", "ownership")):
            summary, listed = _d4_matrix(client, month, severity, scope,
                                         perspectives=selection)
            expected = _oracle_intersection(
                issues, severity, scope, perspectives=set(selection))
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == vh

    # OR, not AND: adding a chip never narrows the same band+scope selection.
    for severity, scope in combos:
        one = _d4_matrix(client, month, severity, scope,
                         perspectives=("history",))[1]["total"]
        two = _d4_matrix(client, month, severity, scope,
                         perspectives=("history", "ownership"))[1]["total"]
        assert two >= one


def test_closed_status_with_a_band_and_a_card_scope(
        client, db_session, registry_dataset):
    """D1 still grades closed views, including a band + scope intersection."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    target = others[3]
    for row in db_session.query(QualityAlert).filter_by(
            hospital_id=target.id, month=month, status="New",
            indicator_code=_D2_IND).all():
        resp = client.post(f"/quality-alerts/{row.id}/status",
                           json={"status": "Resolved"})
        assert resp.status_code == 200, resp.text
    db_session.expire_all()

    closed = _oracle_issue_rows(db_session, month=month, status="Resolved")
    c_vh, c_only, c_mixed = _oracle_very_high(closed)
    assert c_vh == 1 and c_mixed == 1, "one reviewed mixed Very High issue"
    for severity in ("VERY_HIGH", "HIGH"):
        for scope in ("only", "mixed", "corroborated"):
            summary, listed = _d4_matrix(client, month, severity, scope,
                                         status="Resolved")
            expected = _oracle_intersection(closed, severity, scope)
            assert summary["total_issues"] == listed["total"] == expected
            assert summary["very_high_issues"] == c_vh
            assert summary["mixed_severity_issues"] == c_mixed

    # Open view: the reviewed issue is gone, so the pair is empty and the
    # cards are empty too — that is a real zero, not a filtered-out one.
    assert _oracle_issue_rows(db_session, month=month,
                              hospital_id=target.id) == {}
    summary, listed = _d4_matrix(client, month, "HIGH", "mixed",
                                 hospital_id=target.id)
    assert summary["total_issues"] == listed["total"] == 0
    assert summary["very_high_issues"] == 0

# ── D6: status and include_closed ──────────────────────────────────────────
# One vocabulary: the five stored review states. ``status`` selects exactly one
# of them; with no status the OPEN view applies (everything except the closed
# states), which ``include_closed`` can widen. An explicit status is
# authoritative, so status+include_closed is deterministic. All expectations
# below are rebuilt from stored rows, never from the production filter.

_D6_IND = "QA_D6_STATUS"
_D6_STATUSES = ("Under Review", "Confirmed Issue", "False Positive", "Resolved")
_D6_BAD = ("bogus", "resolved", "Open", "Resolved,New", "CLOSED")


def _oracle_status_issues(db, month, status=None, include_closed=False,
                          indicator_code=_D6_IND):
    """issue key -> rows of that month under the requested review scope."""
    groups = {}
    for row in db.query(QualityAlert).filter(
            QualityAlert.active.is_(True),
            QualityAlert.month == month,
            QualityAlert.indicator_code == indicator_code).all():
        if status:
            if row.status != status:
                continue
        elif not include_closed and row.status in _CLOSED_STATUSES:
            continue
        groups.setdefault((row.hospital_id, row.formula, row.unit,
                           row.indicator_code, row.month), []).append(row)
    return groups


def _d6_get(client, month, status=None, include_closed=None,
            severity=None, scope=None, perspectives=None):
    params = {"month": month, "indicator": _D6_IND}
    if status is not None:
        params["status"] = status
    if include_closed is not None:
        params["include_closed"] = "true" if include_closed else "false"
    if severity:
        params["severity"] = severity
    if scope:
        params["very_high_scope"] = scope
    if perspectives:
        params["perspective"] = list(perspectives)
    summary = client.get("/quality-alerts/summary", params=params)
    listed = client.get("/quality-alerts/issues",
                        params={**params, "page_size": 0})
    return summary, listed


def _d6_dataset(client, db_session, registry_dataset):
    """Scan, then one issue per status, same indicator, four hospitals."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    sample = db_session.query(QualityAlert).filter_by(
        active=True, month=month, hospital_id=spike.id,
        indicator_code=_D2_IND).first()
    assert sample is not None
    others = list(registry_dataset["hospitals"][1:]) + list(
        registry_dataset["peers"])
    assert len(others) >= len(_D6_STATUSES)
    db_session.add_all([
        _clone_row(sample, hospital_id=hospital.id, perspective="history",
                   indicator_code=_D6_IND,
                   indicator_name="QA D6 status issue",
                   severity="VERY_HIGH", status=status)
        for status, hospital in zip(_D6_STATUSES, others, strict=True)
    ])
    db_session.commit()
    return month, sample, others


def test_status_omitted_and_empty_mean_the_open_view(
        client, db_session, registry_dataset):
    """No status is the open scope; an empty value is the same request."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    open_groups = _oracle_status_issues(db_session, month)
    # Four stored issues, two of them closed: the open view keeps two.
    assert len(open_groups) == 2

    def totals(**kw):
        summary, listed = _d6_get(client, month, **kw)
        assert summary.status_code == listed.status_code == 200, kw
        body = listed.json()
        assert body["total"] == summary.json()["total_issues"]
        return body["total"], body["items"]

    omitted, omitted_items = totals()
    assert omitted == 2
    assert totals(status="") == (omitted, omitted_items)
    assert totals(include_closed=False) == (omitted, omitted_items)
    # The open view lists exactly the statuses the KPI cards call open.
    statuses = {issue["status"] for issue in omitted_items}
    assert statuses == {"Under Review", "Confirmed Issue"}


def test_every_supported_status_is_listed_exactly(
        client, db_session, registry_dataset):
    """Each stored state selects its own issue, one at a time."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    from app.api import quality_alerts as api_mod
    supported = list(api_mod.STATUS_VALUES)
    assert supported == ["New", "Under Review", "Confirmed Issue",
                         "False Positive", "Resolved"]

    for status in supported:
        expected = _oracle_status_issues(db_session, month, status=status)
        summary, listed = _d6_get(client, month, status=status)
        assert summary.status_code == listed.status_code == 200, status
        body = listed.json()
        assert body["total"] == summary.json()["total_issues"] == len(expected)
        assert body["total"] == (1 if status in _D6_STATUSES else 0), status
        assert {issue["status"] for issue in body["items"]} == {status} \
            if body["items"] else True

    # include_closed widens the open view to every stored state at once.
    every = _oracle_status_issues(db_session, month, include_closed=True)
    summary, listed = _d6_get(client, month, include_closed=True)
    assert listed.json()["total"] == summary.json()["total_issues"] == \
        len(every) == 4


def test_invalid_status_is_rejected_on_both_endpoints(
        client, db_session, registry_dataset):
    """An unknown status is a 422 naming it and the supported values."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    for value in _D6_BAD:
        for path in ("/quality-alerts/summary", "/quality-alerts/issues"):
            resp = client.get(path, params={"month": month,
                                            "indicator": _D6_IND,
                                            "status": value})
            assert resp.status_code == 422, (path, value, resp.status_code)
            detail = resp.json()["detail"]
            assert "status" in detail and value in detail, detail
            for valid in _STATUS_VALUES_FOR_TEST:
                assert valid in detail, (valid, detail)
            assert "total_issues" not in resp.json()
            assert "items" not in resp.json()

    # Whitespace is trimmed, so a padded valid name is accepted; the case is
    # NOT folded, and "resolved" is one of the rejected values above.
    resp = client.get("/quality-alerts/summary",
                      params={"month": month, "indicator": _D6_IND,
                              "status": "  Resolved  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_issues"] == 1


_STATUS_VALUES_FOR_TEST = ("New", "Under Review", "Confirmed Issue",
                           "False Positive", "Resolved")


def test_status_combines_with_band_scope_perspective_and_type(
        client, db_session, registry_dataset):
    """The status scope intersects with D2/D3/D4/D5 and never moves the cards."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    for status in ("Under Review", "Confirmed Issue", "False Positive",
                   "Resolved"):
        groups = _oracle_status_issues(db_session, month, status=status)
        per_status = len(groups)
        assert per_status == 1

        # D2/D4: this population is Very High only, so HIGH empties the list
        # while the cards keep describing the status population.
        summary, listed = _d6_get(client, month, status=status,
                                  severity="HIGH", scope="only")
        assert listed.json()["total"] == summary.json()["total_issues"] == 0
        assert summary.json()["very_high_issues"] == per_status

        summary, listed = _d6_get(client, month, status=status,
                                  severity="VERY_HIGH", scope="only")
        assert listed.json()["total"] == 1
        assert summary.json()["very_high_issues"] == 1
        assert summary.json()["very_high_only_issues"] == 1

        # D5: one chip and two chips both keep the status scope; the OR can
        # only widen inside it.
        one = _d6_get(client, month, status=status,
                      perspectives=("history",))[1].json()["total"]
        two = _d6_get(client, month, status=status,
                      perspectives=("history", "ownership"))[1].json()["total"]
        assert one == two == 1

        # D3: the clone keeps its registry FK, so it is a derivative finding.
        resp = client.get("/quality-alerts/issues",
                          params={"month": month, "indicator": _D6_IND,
                                  "status": status, "indicator_type":
                                  "derivative", "page_size": 0})
        assert resp.status_code == 200 and resp.json()["total"] == 1
        element = client.get("/quality-alerts/issues",
                             params={"month": month, "indicator": _D6_IND,
                                     "status": status,
                                     "indicator_type": "element",
                                     "page_size": 0})
        assert element.json()["total"] == 0


def test_closed_status_evidence_reconciles_and_the_detail_loads(
        client, db_session, registry_dataset):
    """Resolved / False Positive grade and open without a KeyError (D1)."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    for status in ("Resolved", "False Positive"):
        groups = _oracle_status_issues(db_session, month, status=status)
        assert len(groups) == 1
        rows = next(iter(groups.values()))
        summary, listed = _d6_get(client, month, status=status)
        assert summary.status_code == listed.status_code == 200
        body = listed.json()
        assert body["total"] == summary.json()["total_issues"] == 1
        # Whole-evidence grading of a closed issue is available, so a card
        # scope narrows the closed population instead of failing.
        scoped = client.get("/quality-alerts/issues",
                            params={"month": month, "indicator": _D6_IND,
                                    "status": status,
                                    "very_high_scope": "only",
                                    "page_size": 0})
        assert scoped.status_code == 200 and scoped.json()["total"] == 1
        # The stored row is still readable through the detail endpoint.
        detail = client.get(f"/quality-alerts/{rows[0].id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["alert"]["status"] == status
        # And it is still excluded from the open view.
        open_total = client.get("/quality-alerts/issues",
                                params={"month": month, "indicator": _D6_IND,
                                        "page_size": 0}).json()["total"]
        assert open_total == 2


def test_an_explicit_status_wins_over_include_closed(
        client, db_session, registry_dataset):
    """The two parameters are deterministic: one status, closed flag ignored."""
    month, sample, others = _d6_dataset(client, db_session,
                                        registry_dataset)
    for status in ("Resolved", "New"):
        plain = _d6_get(client, month, status=status)
        both = _d6_get(client, month, status=status, include_closed=True)
        assert plain[1].json()["total"] == both[1].json()["total"]
        assert plain[0].json()["total_issues"] == \
            both[0].json()["total_issues"]
    # include_closed alone is the widened OPEN view: every stored state.
    assert _d6_get(client, month, include_closed=True)[1].json()["total"] == 4
    # ...and it does not resurrect anything the status excludes.
    assert _d6_get(client, month, status="New",
                   include_closed=True)[1].json()["total"] == 0

# ── D7: strict query-parameter validation ──────────────────────────────────
# One rule for every optional filter: absent and empty mean "not set", and any
# other value must be an accepted form or the request is a 422 that names the
# parameter. Both endpoints run the same helpers, so the two can never disagree.

_D7_BAD_MONTHS = ("2026-8", "2026-13", "2026-00", "abc", "2026/08", "2026-08-01")
_D7_BAD_SEVERITIES = ("high", "CRITICAL", "VERY HIGH", "0")
_D7_BAD_SCOPES = ("mostly", "only,mixed", "ONLY")
_D7_BAD_CONFIDENCES = ("medium", "HIGH", "low,high")


def _json_text(resp):
    import json
    return json.dumps(resp.json()).lower()


def _d7_issue_rows(db, month):
    """issue key -> [(stored band, perspective)] for the WHOLE month.

    The D2 oracle is indicator-scoped; the pagination and band checks here are
    month-wide, so this rebuilds the same shape over every stored row.
    """
    groups = {}
    for row in db.query(QualityAlert).filter(
            QualityAlert.active.is_(True),
            QualityAlert.month == month).all():
        groups.setdefault((row.hospital_id, row.formula, row.unit,
                           row.indicator_code, row.month), []).append(
                               (row.severity, row.perspective))
    return groups


def test_invalid_query_values_are_rejected_by_both_endpoints(
        client, registry_dataset):
    """Every rule answers the same 422 on summary and on issues."""
    cases = [({"month": value}, "month") for value in _D7_BAD_MONTHS]
    cases += [({"severity": value}, "severity") for value in _D7_BAD_SEVERITIES]
    cases += [({"very_high_scope": value}, "very_high_scope")
              for value in _D7_BAD_SCOPES]
    cases += [({"confidence": value}, "confidence")
              for value in _D7_BAD_CONFIDENCES]
    cases += [({"hospital_id": value}, "hospital_id")
              for value in (0, -3)]
    cases += [({"ownership_id": 0}, "ownership_id"),
              ({"governorate_id": -1}, "governorate_id"),
              ({"hospital_type_id": 0}, "hospital_type_id"),
              ({"hospital_id": "abc"}, "hospital_id")]

    for params, name in cases:
        for path in ("/quality-alerts/summary", "/quality-alerts/issues"):
            resp = client.get(path, params=params)
            assert resp.status_code == 422, (path, params, resp.status_code)
            assert name in _json_text(resp), (path, params, resp.text)
            body = resp.json()
            assert "total_issues" not in body and "items" not in body

    # Pagination exists on the LIST only (the summary is not paged), so those
    # boundary rules are asserted there, once.
    for params, name in (({"page": 0}, "page"), ({"page": -2}, "page"),
                         ({"page_size": -1}, "page_size"),
                         ({"page_size": 201}, "page_size")):
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 422, (params, resp.status_code)
        assert name in _json_text(resp), (params, resp.text)

    # sort/order exist on the list only; unknown values are refused there.
    for params, name in (({"sort": "bogus"}, "sort"),
                         ({"order": "sideways"}, "order")):
        resp = client.get("/quality-alerts/issues", params=params)
        assert resp.status_code == 422, (params, resp.text)
        assert name in _json_text(resp)


def test_zero_and_negative_ids_are_rejected_not_silently_ignored(
        client, db_session, registry_dataset):
    """``hospital_id=0`` used to disable the filter and return everything."""
    month = registry_dataset["scan_month"]
    _scan(client, month)

    # 0 and negatives are invalid identifiers on all four id filters.
    for param in ("hospital_id", "ownership_id", "governorate_id",
                  "hospital_type_id"):
        for value in (0, -1):
            resp = client.get("/quality-alerts/issues",
                              params={param: value})
            assert resp.status_code == 422, (param, value, resp.status_code)

    # A positive id that simply has no rows is an empty result, not an error.
    for param in ("hospital_id", "ownership_id", "governorate_id",
                  "hospital_type_id"):
        resp = client.get("/quality-alerts/issues",
                          params={param: 999999, "page_size": 0})
        assert resp.status_code == 200, (param, resp.text)
        assert resp.json()["total"] == 0
        summary = client.get("/quality-alerts/summary",
                             params={param: 999999}).json()
        assert summary["total_issues"] == 0

    # A real id filters to that hospital's issues, per the stored rows.
    hospital = registry_dataset["hospitals"][0]
    listed = client.get("/quality-alerts/issues",
                        params={"hospital_id": hospital.id,
                                "month": month, "page_size": 0}).json()
    expected = _rows_by_issue(db_session, month, hospital_id=hospital.id)
    assert _listed_issue_ids(listed) == expected
    assert listed["total"] == len(expected) > 0
    every = client.get("/quality-alerts/issues",
                       params={"month": month, "page_size": 0}).json()["total"]
    # Scoped equality is the proof of filtering; one hospital may legitimately
    # hold every issue of the month, so no strict narrowing is assumed here.
    assert 0 < listed["total"] <= every
    other = registry_dataset["hospitals"][1]
    other_listed = client.get("/quality-alerts/issues",
                              params={"hospital_id": other.id,
                                      "month": month,
                                      "page_size": 0}).json()
    assert _listed_issue_ids(other_listed) == _rows_by_issue(
        db_session, month, hospital_id=other.id)
    assert not (_listed_issue_ids(other_listed) & _listed_issue_ids(listed)),         "two hospitals must not share an issue"


def test_month_and_severity_validation_preserves_valid_filtering(
        client, db_session, registry_dataset):
    """Valid months and bands filter exactly as before; empty means unset."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    all_groups = _d7_issue_rows(db_session, month)

    def total(**params):
        summary = client.get("/quality-alerts/summary", params=params)
        listed = client.get("/quality-alerts/issues",
                            params={**params, "page_size": 0})
        assert summary.status_code == listed.status_code == 200, params
        assert summary.json()["total_issues"] == listed.json()["total"]
        return listed.json()["total"]

    everything = total()
    assert everything == len(_rows_by_issue(db_session, month))
    # Empty month/severity are "not set", not an error and not a filter.
    assert total(month="") == everything
    assert total(severity="") == everything
    assert total(month=month) == everything
    assert total(month="2026-07") == 0, "a valid month with no rows is empty"

    # Each valid band counts the issues that carry a row in it.
    for band in ("VERY_HIGH", "HIGH", "MODERATE", "LOW"):
        expected = sum(1 for rows in all_groups.values()
                       if any(sev == band for sev, _ in rows))
        assert total(month=month, severity=band) == expected, band
    very_high = total(month=month, severity="VERY_HIGH")
    assert very_high == _oracle_very_high(all_groups)[0]
    # D2: the cards do not follow the band.
    for band in ("HIGH", "MODERATE"):
        summary = client.get("/quality-alerts/summary",
                             params={"month": month,
                                     "severity": band}).json()
        assert summary["very_high_issues"] == very_high


def test_pagination_boundaries_and_defaults(
        client, registry_dataset):
    """page >= 1, 0 <= page_size <= 200; 0 still means "all"."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    total = client.get("/quality-alerts/issues",
                      params={"month": month, "page_size": 0}).json()["total"]
    assert total > 0

    every = client.get("/quality-alerts/issues",
                       params={"month": month, "page_size": 0}).json()
    assert len(every["items"]) == every["total"] == total

    capped = client.get("/quality-alerts/issues",
                        params={"month": month, "page_size": 200}).json()
    assert capped["total"] == total and len(capped["items"]) <= 200

    beyond = client.get("/quality-alerts/issues",
                        params={"month": month, "page_size": 5,
                                "page": 999}).json()
    assert beyond["items"] == [] and beyond["total"] == total

    assert total >= 2, "the fixture must have more than one issue"
    first = client.get("/quality-alerts/issues",
                       params={"month": month, "page_size": 1,
                               "page": 1}).json()["items"]
    second = client.get("/quality-alerts/issues",
                        params={"month": month, "page_size": 1,
                                "page": 2}).json()["items"]
    first_ids = {tuple(i["alert_ids"]) for i in first}
    second_ids = {tuple(i["alert_ids"]) for i in second}
    assert first_ids and second_ids and not (first_ids & second_ids)


def test_search_whitespace_is_treated_as_absent(
        client, db_session, registry_dataset):
    """A blank search is "not set"; a padded one is trimmed, not literal."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    base = {"month": month, "page_size": 0}
    plain = _listed_issue_ids(
        client.get("/quality-alerts/issues", params=base).json())

    blank = client.get("/quality-alerts/issues",
                       params={**base, "q": "   "})
    assert blank.status_code == 200
    assert _listed_issue_ids(blank.json()) == plain, \
        "a whitespace-only search must not filter"
    assert client.get("/quality-alerts/summary",
                      params={"month": month, "q": "  "}
                      ).json()["total_issues"] == len(plain)

    term = _D2_IND  # a stored indicator code: matches only those issues
    padded = client.get("/quality-alerts/issues",
                        params={**base, "q": "  " + term + "  "}).json()
    trimmed = client.get("/quality-alerts/issues",
                         params={**base, "q": term}).json()
    assert _listed_issue_ids(padded) == _listed_issue_ids(trimmed)
    assert padded["total"] == trimmed["total"]
    assert 0 < trimmed["total"] < len(plain), "the search must still narrow"
    assert client.get("/quality-alerts/summary",
                      params={"month": month, "q": " " + term + " "}
                      ).json()["total_issues"] == trimmed["total"]


def test_confidence_scope_sort_and_order_values(
        client, db_session, registry_dataset):
    """Enumerated values are exact; empty is "not set"; sorting is ordered."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    base = {"month": month, "page_size": 0}

    everything = client.get("/quality-alerts/issues", params=base).json()["total"]
    high = client.get("/quality-alerts/issues",
                      params={**base, "confidence": "high"}).json()
    low = client.get("/quality-alerts/issues",
                     params={**base, "confidence": "low"}).json()
    # Expected populations straight from the stored rows: "high" includes the
    # NULL provenance the screen presents as high, "low" is the literal mark.
    groups = {}
    for row in db_session.query(QualityAlert).filter(
            QualityAlert.active.is_(True),
            QualityAlert.month == month).all():
        groups.setdefault((row.hospital_id, row.formula, row.unit,
                           row.indicator_code, row.month), []).append(row)
    expected_high = sum(1 for rows in groups.values()
                        if any((r.confidence or "high") == "high"
                               for r in rows))
    expected_low = sum(1 for rows in groups.values()
                       if any(r.confidence == "low" for r in rows))
    assert high["total"] == expected_high
    assert low["total"] == expected_low
    assert high["total"] <= everything and low["total"] <= everything

    # An empty card scope is "not set" (D7), like every other empty value.
    empty_scope = client.get("/quality-alerts/summary",
                             params={"month": month,
                                     "very_high_scope": ""}).json()
    assert empty_scope["total_issues"] == everything
    only = client.get("/quality-alerts/summary",
                      params={"month": month,
                              "very_high_scope": "only"}).json()
    assert only["total_issues"] == _oracle_scope(
        _d7_issue_rows(db_session, month), "only")

    ascending = client.get("/quality-alerts/issues",
                           params={**base, "sort": "hospital",
                                   "order": "asc"}).json()["items"]
    descending = client.get("/quality-alerts/issues",
                            params={**base, "sort": "hospital",
                                    "order": "desc"}).json()["items"]
    names_up = [item["hospital"] for item in ascending]
    assert names_up == sorted(names_up)
    assert [item["hospital"] for item in descending] == list(reversed(names_up))


def test_d7_keeps_the_d1_to_d6_contracts(
        client, db_session, registry_dataset):
    """The new validation did not change any accepted contract."""
    month, sample, others = _d2_dataset(client, db_session, registry_dataset)
    issues = _oracle_issue_rows(db_session, month=month)
    vh, only, mixed = _oracle_very_high(issues)

    # D3: the type filter still validates and still splits the population.
    for value in ("bogus", "ELEMENT"):
        assert client.get("/quality-alerts/summary",
                          params={"indicator_type": value}).status_code == 422
    element = client.get("/quality-alerts/summary",
                         params={"indicator_type": "element"}).json()
    derivative = client.get("/quality-alerts/summary",
                            params={"indicator_type": "derivative"}).json()
    assert element["total_issues"] + derivative["total_issues"] == \
        client.get("/quality-alerts/summary").json()["total_issues"]

    # D6: status still validates, and the open view is still the default.
    for value in ("bogus", "resolved"):
        assert client.get("/quality-alerts/issues",
                          params={"status": value}).status_code == 422
    assert client.get("/quality-alerts/summary",
                      params={"status": "New"}).json()["total_issues"] == \
        len(_rows_by_issue(db_session, month))

    # D5: chips still OR, and a status still intersects with them.
    scoped = {"month": month, "indicator": _D2_IND, "page_size": 0}
    one = client.get("/quality-alerts/issues",
                     params={**scoped, "perspective": ["history"]}
                     ).json()["total"]
    two = client.get("/quality-alerts/issues",
                     params={**scoped, "perspective": ["history", "ownership"]}
                     ).json()["total"]
    assert two >= one > 0

    # D4: band × card scope still intersects, cards unchanged.
    high_only = client.get("/quality-alerts/summary",
                           params={"month": month, "indicator": _D2_IND,
                                   "severity": "HIGH",
                                   "very_high_scope": "only"}).json()
    assert high_only["total_issues"] == 0
    assert high_only["very_high_issues"] == vh
    assert high_only["very_high_only_issues"] == only
    assert high_only["mixed_severity_issues"] == mixed

# ── D8: audit-link integrity ────────────────────────────────────────────────
# The alert detail's audit_link must identify the SAME hospital, month and
# indicator the finding came from. The audit screen's existing contract is
# newtab.js `screenUrl` + audit.js `_trailQuery`: screen/mode/kind/hospital_id/
# month/indicator_code. No parameter outside it may be invented.

_D8_LINK_KEYS = ("kind", "hospital_id", "month", "indicator_code")


def _d8_audit_url(link):
    """The new-tab URL a Quality Alert opens for its ``audit_link``."""
    from urllib.parse import urlencode
    pairs = [("screen", "audit"), ("mode", "trail")]
    for key in _D8_LINK_KEYS:
        value = link.get(key)
        if value is None or value == "":      # screenUrl drops empty context
            continue
        pairs.append((key, value))
    return "/dashboard?" + urlencode(pairs)


def _d8_query(url):
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def test_audit_link_carries_the_indicator_identity(client, db_session,
                                                   registry_dataset):
    """Derivative and element alerts both identify their indicator."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]

    rate = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_TEST_RATE", month=month).first()
    link = client.get(f"/quality-alerts/{rate.id}").json()["audit_link"]
    assert link["kind"] == "quality_score"
    assert link["hospital_id"] == spike.id
    assert link["month"] == month
    assert link["indicator_code"] == "QA_TEST_RATE"
    assert link["indicator_id"] == rate.indicator_id
    assert isinstance(link["indicator_id"], int), "derivative has a definition"

    # A data element has a code but no registry definition (indicator_id NULL).
    raw = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_NUM", month=month).first()
    raw_link = client.get(f"/quality-alerts/{raw.id}").json()["audit_link"]
    assert raw_link["indicator_code"] == "QA_NUM"
    assert raw_link["indicator_id"] is None
    assert (raw_link["hospital_id"], raw_link["month"]) == (spike.id, month)


def test_generated_link_and_parsed_parameters_agree(client, db_session,
                                                    registry_dataset):
    """What the API writes is what the audit URL carries back."""
    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_TEST_RATE", month=month).first()

    link = client.get(f"/quality-alerts/{alert.id}").json()["audit_link"]
    query = _d8_query(_d8_audit_url(link))
    assert query["screen"] == ["audit"] and query["mode"] == ["trail"]
    assert query["kind"] == [link["kind"]]
    assert query["hospital_id"] == [str(alert.hospital_id)]
    assert query["month"] == [alert.month]
    assert query["indicator_code"] == [alert.indicator_code]


def test_audit_url_encoding_and_special_characters():
    """Codes with URL metacharacters survive the round trip unchanged."""
    code = "QA & RATE+1/2 %#?"
    link = {"kind": "quality_score", "hospital_id": 7, "month": "2026-08",
            "indicator_code": code, "indicator_id": None}
    url = _d8_audit_url(link)
    query = _d8_query(url)
    assert query["indicator_code"] == [code]
    assert "#" not in url, "a raw # would truncate the query"
    assert " " not in url
    # No parameter the audit screen does not define travels with the link.
    assert set(query) == {"screen", "mode", *_D8_LINK_KEYS}


def test_missing_optional_context_is_dropped_not_stringified():
    """Absent month/code are omitted, never sent as '' or 'None'."""
    link = {"kind": "quality_score", "hospital_id": 7, "month": "",
            "indicator_code": None, "indicator_id": None}
    query = _d8_query(_d8_audit_url(link))
    assert "month" not in query and "indicator_code" not in query
    assert query["hospital_id"] == ["7"]
    assert "None" not in _d8_audit_url(link)


def test_audit_navigation_resolves_the_linked_hospital_and_month(
        client, db_session, registry_dataset):
    """The destination opens the alert's own audit, not a neighbour's."""
    from app.models import QualityScore

    month = registry_dataset["scan_month"]
    _scan(client, month)
    spike = registry_dataset["hospitals"][0]
    alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike.id, indicator_code="QA_TEST_RATE", month=month).first()
    # The audit screen explains the score stored behind the month.
    db_session.add(QualityScore(hospital_id=spike.id, month=month, score=72.0,
                                rule_compliance=80.0, completeness=90.0,
                                consistency=70.0, outlier_penalty=2.0))
    db_session.commit()

    link = client.get(f"/quality-alerts/{alert.id}").json()["audit_link"]
    resp = client.get("/audit/explain",
                      params={k: link[k] for k in _D8_LINK_KEYS
                              if link.get(k) not in (None, "")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    resolved = body.get("hospital_id") or (body.get("where") or {}).get("hospital_id")
    assert resolved == spike.id
    assert body.get("month") in (None, alert.month)


def test_audit_navigation_rejects_an_unknown_hospital(client):
    """A stale id must surface an error, never an unrelated hospital's audit."""
    resp = client.get("/audit/explain", params={
        "kind": "quality_score", "hospital_id": 9876543,
        "month": "2026-08", "indicator_code": "QA_TEST_RATE"})
    assert resp.status_code == 404
    assert "hospital not found" in resp.text.lower()


# ── D10 follow-up: the effective band is published by name ───────────────────

def test_detail_publishes_effective_severity_and_keeps_stored(
        client, db_session, registry_dataset):
    """The detail names the authoritative band; the stored one stays traceable.

    The modal reads ``effective_severity`` (cap applied). ``severity`` remains
    the same value for existing consumers, and ``stored_severity`` is only used
    to explain a cap — never as the band the screen reports.
    """
    _scan(client, registry_dataset["scan_month"])
    alert = db_session.query(QualityAlert).filter_by(
        indicator_code="QA_TEST_RATE").first()
    assert alert is not None
    payload = client.get(f"/quality-alerts/{alert.id}").json()
    data = payload["alert"]
    assert data["effective_severity"] == data["severity"]
    assert data["stored_severity"] == alert.severity
    for sibling in payload["issue"]["perspectives"]:
        assert sibling["effective_severity"] == sibling["severity"]
        assert "stored_severity" in sibling


def test_issue_payload_keeps_primary_effective_and_stored_severity(
        client, db_session, registry_dataset):
    """D10 compatibility: the three names still agree on every listed issue."""
    _scan(client, registry_dataset["scan_month"])
    page = client.get("/quality-alerts/issues",
                      params={"month": registry_dataset["scan_month"],
                              "page_size": 5}).json()
    assert page["items"]
    for item in page["items"]:
        assert item["primary_severity"] == item["effective_severity"]
        assert "stored_severity" in item
