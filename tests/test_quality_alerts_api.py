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
)


@pytest.fixture
def client(app):
    """TestClient over the conftest app — `_bypass_auth` already overrides
    get_current_user (superadmin) and get_db (db_session)."""
    return TestClient(app)


@pytest.fixture
def registry_dataset(db_session):
    """A registered ratio indicator with 3 hospitals x 4 months of data.

    Hospital 1's last month spikes (80% vs ~10% baseline); hospitals 2 and 3
    stay flat — so history, all-hospital and (borderline) peer comparisons
    have real evidence to work with.
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
    db_session.commit()
    return {"definition": definition, "hospitals": hospitals[:3],
            "months": months, "scan_month": months[-1]}


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


def test_summary_counts_red_alerts_and_hospitals(client, registry_dataset):
    _scan(client, registry_dataset["scan_month"])
    resp = client.get("/quality-alerts/summary",
                      params={"month": registry_dataset["scan_month"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["red_alerts"] >= 1
    assert data["hospitals_affected"] >= 1
    assert data["indicators_affected"] >= 1
    assert data["total_active"] >= data["red_alerts"]
    # Issue-unit fields are reported alongside, never instead of, row counts.
    assert data["total_issues"] <= data["total_active"]
    assert data["red_issues"] <= data["red_alerts"]


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
    # Every listed row is red here, so every grouped issue is a red issue.
    assert summary["red_issues"] == summary["total_issues"]
    assert (summary["red_only_issues"] + summary["mixed_severity_issues"]
            == summary["total_issues"])
    assert summary["total_active"] == summary["red_alerts"]

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


def test_dashboard_red_issue_card_matches_the_quality_alerts_screen(
        client, db_session, registry_dataset):
    """The dashboard card reports the screen's red count in the same unit.

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
    assert overview["red_quality_issues"] == summary["red_issues"]

    red_rows = (db_session.query(QualityAlert)
                .filter(QualityAlert.active.is_(True),
                        QualityAlert.month == month,
                        QualityAlert.severity == "VERY_HIGH").all())
    distinct = {(row.hospital_id, row.indicator_code, row.month)
                for row in red_rows}
    assert overview["red_quality_issues"] == len(distinct)
    assert overview["red_quality_issues"] < len(red_rows), \
        "the fixture's spike carries several perspectives on one issue"


def test_summary_splits_red_only_from_mixed_severity(client, db_session,
                                                     registry_dataset):
    """Red-only vs mixed describes the whole issue, not the filtered slice.

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
    red = [sevs for sevs in by_issue.values() if "VERY_HIGH" in sevs]

    assert summary["red_only_issues"] == sum(
        1 for sevs in red if sevs == {"VERY_HIGH"})
    assert summary["mixed_severity_issues"] == sum(
        1 for sevs in red if len(sevs) > 1)
    # On the pinned screen every listed issue is red, so the split is complete.
    assert (summary["red_only_issues"] + summary["mixed_severity_issues"]
            == summary["total_issues"])


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
    others = {h.id for h in registry_dataset["hospitals"][1:]}

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
