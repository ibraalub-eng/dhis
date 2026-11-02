"""Shared temporal / peer policy for Diagnostics and Quality Alerts.

The reported defect: the same hospital+formula was scored 1.0 by one engine
and 0.11 by the other because Diagnostics used every recorded prior month while
Alerts used the last 12. These tests pin the approved policy, the regression
scenario, the minimum-peer/history behaviour, provenance, and the fact that
intentionally narrower alert perspectives remain distinct instead of being
silently folded into the detection baseline.
"""
import pytest

from app.engine.anomaly.layered import (
    METHOD_ZSCORE,
    AnalysisSpec,
    Thresholds,
    analyze_layered_entry,
    compute_historical_layer,
    compute_peer_layer,
)
from app.engine.comparison_policy import (
    DETECTION_PEER_GROUP,
    history_window,
    history_window_months,
    resolve_comparison_policy,
)
from app.engine.comparison_policy import (
    HistoryPolicy as SharedHistoryPolicy,
)
from app.engine.quality_alerts import (
    PERSPECTIVE_ALL,
    PERSPECTIVE_HISTORY,
    _history_score,
    _peer_members,
    _peer_score,
)
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
)

MONTHS = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]


def _spec(method=METHOD_ZSCORE, minimum=3):
    return AnalysisSpec(
        analysis_code="CP_COUNT", name="Policy count", indicator_type="count",
        minimum_history_period=minimum, outlier_method=method,
    )


def _history(values, code="CP_COUNT"):
    return {month: {code: value} for month, value in zip(MONTHS, values,
                                                         strict=False)}


# ── 1. The policy itself ────────────────────────────────────────────────

def test_window_is_bounded_and_minimums_have_one_source():
    policy = resolve_comparison_policy(
        {"alerts_history_window": 12, "alerts_min_history": 3,
         "alerts_min_peers": 2},
        trend_window=12)
    assert policy.history.window == 12
    assert policy.history.min_observations == 3
    assert policy.peer.min_peers == 2
    assert policy.as_dict()["version"]


def test_shorter_of_alert_and_system_windows_wins():
    assert resolve_comparison_policy(
        {"alerts_history_window": 12}, trend_window=6).history.window == 6
    assert resolve_comparison_policy(
        {"alerts_history_window": 6}, trend_window=12).history.window == 6


def test_policy_cannot_drop_below_safe_minimums():
    policy = resolve_comparison_policy(
        {"alerts_min_peers": 0, "alerts_min_history": 0},
        trend_window=12)
    assert policy.peer.min_peers == 2
    assert policy.history.min_observations == 2


def test_history_window_uses_last_reporting_months_and_records_gaps():
    history = {
        "2024-01": {"5": 1.0},
        "2024-03": {"5": 2.0},
        "2024-04": {},                 # stored month, no value
        "2024-05": {"5": 4.0},
        "2024-06": {"5": 5.0},         # analysed month
    }
    win = history_window(history, "2024-06", SharedHistoryPolicy(window=3),
                         lambda m: history[m].get("5"))
    assert win.months == ["2024-03", "2024-04", "2024-05"]
    assert win.observations == [("2024-03", 2.0), ("2024-05", 4.0)]
    assert win.skipped_months == ["2024-04"]
    assert win.values == [2.0, 4.0]
    assert history_window_months(history, "2024-06", 2) == ["2024-04", "2024-05"]


def test_minimum_history_counts_valid_observations_not_calendar_months():
    history = _history([10.0, None, None, None, 80.0])
    result = analyze_layered_entry(
        _spec(), history, MONTHS[-1], [], Thresholds(),
        self_id=1, history_policy=SharedHistoryPolicy(window=12, min_observations=3))
    assert result.history_ok is False
    assert result.historical.score is None
    assert result.classification.outlier_level == "NONE"


# ── 2. The reported 1.0 vs 0.11 discrepancy ─────────────────────────────

def test_long_unbounded_history_was_the_discrepancy_and_shared_window_fixes_it():
    """Old 12 high months + 12 recent 10s, current 80.

    Unbounded Diagnostics produced z~0.55 -> 0.11. Alerts (last 12, zero
    spread) produced 1.0. With the shared window both must produce 1.0.
    """
    older = [f"2024-{m:02d}" for m in range(1, 13)]
    recent = [f"2025-{m:02d}" for m in range(1, 13)]
    history = {month: {"CP_COUNT": 100.0} for month in older}
    history.update({month: {"CP_COUNT": 10.0} for month in recent})
    history["2026-01"] = {"CP_COUNT": 80.0}

    # The retired unbounded baseline, reproduced explicitly.
    old = compute_historical_layer(
        _spec(), [100.0] * 12 + [10.0] * 12, 80.0, True, 2.5,
        policy=SharedHistoryPolicy(window=24, min_observations=3))
    assert old.score == pytest.approx(0.11, abs=0.011)

    # Shared policy: same last-12 window on both engines.
    layered = analyze_layered_entry(
        _spec(), history, "2026-01", [], Thresholds(), self_id=1,
        history_policy=SharedHistoryPolicy(window=12, min_observations=3))
    assert layered.historical.score == pytest.approx(1.0)

    alert_score, method, _z, _stats = _history_score(
        "count", [10.0] * 12, 80.0, 2.5, outlier_method=METHOD_ZSCORE)
    assert method == METHOD_ZSCORE
    assert alert_score == pytest.approx(layered.historical.score)


# ── 3. Peer eligibility and minimum peer count ──────────────────────────

def test_peer_layer_records_eligible_peers_even_below_the_minimum():
    spec = _spec()
    one_peer = [("all", {1: 10.0, 2: 20.0})]
    layer = compute_peer_layer(spec, self_id=1, current_value=10.0,
                               peer_tiers=one_peer, min_peers=2)
    assert layer.score is None
    assert layer.peer_count == 0
    assert layer.eligible_count == 1
    assert layer.eligible_ids == [2]

    two_peers = [("all", {1: 10.0, 2: 20.0, 3: 30.0})]
    strict = compute_peer_layer(spec, self_id=1, current_value=10.0,
                                peer_tiers=two_peers, min_peers=3)
    assert strict.score is None and strict.eligible_count == 2

    ok = compute_peer_layer(spec, self_id=1, current_value=10.0,
                            peer_tiers=two_peers, min_peers=2)
    assert ok.score is not None
    assert ok.group == DETECTION_PEER_GROUP or ok.group == "all"
    assert ok.peer_count == 2 and ok.eligible_count == 2
    assert ok.peer_values == {2: 20.0, 3: 30.0}


def test_all_perspective_uses_the_same_peer_set_as_detection(db_session):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(3).all()
    directory = {h.id: h for h in hospitals}
    values = {hospitals[0].id: 80.0, hospitals[1].id: 10.0,
              hospitals[2].id: 10.0}

    alert_members = _peer_members(directory, hospitals[0].id, None, values)
    detection = compute_peer_layer(
        _spec(), hospitals[0].id, 80.0,
        [("all", values)], Thresholds(min_peers=2).peer_z_threshold,
        min_peers=2)

    assert {mid for mid, _v in alert_members} == set(detection.peer_values)
    alert_mean = sum(v for _mid, v in alert_members) / len(alert_members)
    assert alert_mean == pytest.approx(detection.peer_mean)

    _z, alert_score, _stats = _peer_score(
        80.0, [v for _mid, v in alert_members], 2.5)
    assert alert_score == pytest.approx(detection.score)


# ── 4. Alerts: generated rows carry window/peer provenance ─────────────

@pytest.fixture
def alert_dataset(db_session):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(3).all()
    assert len(hospitals) == 3
    extra = Hospital(name="Policy Fourth Hospital", region="Region A")
    db_session.add(extra)
    db_session.flush()
    hospitals.append(extra)
    # Distinct type for hospital 4, so the type perspective is intentionally
    # narrower than the all-hospital detection baseline.
    for index, hospital in enumerate(hospitals):
        hospital.hospital_type_id = 1 if index < 3 else 2
        hospital.governorate_id = 1
    element = Indicator(code="CP_ALERT_COUNT", name="Policy alert count",
                        indicator_type="count")
    db_session.add(element)
    db_session.flush()
    for index, hospital in enumerate(hospitals):
        for month in MONTHS[:-1]:
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=element.id,
                month=month, value=10.0))
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=element.id,
            month=MONTHS[-1], value=80.0 if index == 0 else 10.0))
    db_session.commit()
    return hospitals


def test_alert_rows_carry_window_peer_group_and_eligible_count(
        app, db_session, alert_dataset):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post("/quality-alerts/scan", json={"month": MONTHS[-1]})
    assert response.status_code == 200, response.text

    target = alert_dataset[0]
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=target.id, indicator_code="CP_ALERT_COUNT").all()
    history = [a for a in alerts if a.perspective == PERSPECTIVE_HISTORY]
    all_peer = [a for a in alerts if a.perspective == PERSPECTIVE_ALL]
    assert history and all_peer

    hist_policy = history[0].evidence["comparison_policy"]
    assert hist_policy["perspective_scope"] == "detection_baseline"
    assert hist_policy["history"]["window"] == 12
    assert hist_policy["history"]["min_observations"] >= 3
    assert hist_policy["history"]["months"]
    assert history[0].evidence["history"]

    peer_policy = all_peer[0].evidence["comparison_policy"]
    assert peer_policy["perspective_scope"] == "detection_baseline"
    peer = peer_policy["peer"]
    assert peer["group"] == DETECTION_PEER_GROUP
    assert peer["eligible_count"] == 3
    assert set(peer["peer_ids"]) == {alert_dataset[1].id,
                                     alert_dataset[2].id,
                                     alert_dataset[3].id}
    assert set(peer["values"]) == {str(alert_dataset[1].id),
                                   str(alert_dataset[2].id),
                                   str(alert_dataset[3].id)}


def test_narrower_alert_perspectives_are_labelled_not_forced_into_the_baseline(
        db_session, alert_dataset):
    from app.engine import quality_alerts as qa

    result = qa.scan(db_session, month=MONTHS[-1])
    assert isinstance(result, dict)

    target = alert_dataset[0]
    alerts = db_session.query(QualityAlert).filter_by(
        hospital_id=target.id, indicator_code="CP_ALERT_COUNT").all()
    by_perspective = {a.perspective: a for a in alerts}
    type_row = by_perspective.get("type")
    all_row = by_perspective[PERSPECTIVE_ALL]

    # Two same-type peers vs three all-hospital peers: different questions,
    # different groups, both explicitly labelled.
    assert type_row is not None
    type_policy = type_row.evidence["comparison_policy"]
    all_policy = all_row.evidence["comparison_policy"]
    type_peer = type_policy["peer"]
    all_peer = all_policy["peer"]
    assert type_peer["group"].startswith("stratified:type")
    assert type_policy["perspective_scope"] == "stratified"
    assert all_policy["perspective_scope"] == "detection_baseline"
    assert all_peer["group"] == DETECTION_PEER_GROUP
    assert set(type_peer["peer_ids"]) < set(all_peer["peer_ids"])


def test_alert_scan_does_not_remove_or_change_a_diagnostic_result(
        db_session, alert_dataset):
    """A row Diagnostics stored stays exactly as stored, regardless of what
    the alert scan does with its own window/peer gates."""
    from app.engine import quality_alerts as qa

    target = alert_dataset[0]
    row = LayeredOutlierResult(
        hospital_id=target.id, analysis_code="CP_ALERT_COUNT",
        month=MONTHS[-1], raw_value=80.0, outlier_level="HIGH",
        outlier_type="HISTORICAL_ANOMALY", outlier_method=METHOD_ZSCORE,
        historical_mean=10.0, historical_outlier_score=0.8,
        peer_mean=10.0, peer_count=3,
    )
    db_session.add(row)
    db_session.commit()
    before = (row.outlier_level, row.historical_outlier_score, row.peer_count)

    qa.scan(db_session, month=MONTHS[-1])

    db_session.refresh(row)
    assert (row.outlier_level, row.historical_outlier_score,
            row.peer_count) == before


# ── 5. Diagnostics persistence carries the same provenance ──────────────

def test_layered_rows_persist_history_and_peer_provenance(db_session):
    from app.engine.pipeline import run_full_analysis

    target = Hospital(name="Provenance Target", region="Region A")
    db_session.add(target)
    db_session.flush()
    for hospital in (
        Hospital(name="Provenance Peer B", region="Region A"),
        Hospital(name="Provenance Peer C", region="Region A"),
    ):
        db_session.add(hospital)
        db_session.flush()
        for month in MONTHS:
            for code, value in (("2", 100.0), ("5", 10.0)):
                ind = db_session.query(Indicator).filter_by(code=code).one()
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, indicator_id=ind.id,
                    month=month, value=value))
    for month in MONTHS[:-1]:
        for code, value in (("2", 100.0), ("5", 10.0)):
            ind = db_session.query(Indicator).filter_by(code=code).one()
            db_session.add(IndicatorValue(
                hospital_id=target.id, indicator_id=ind.id,
                month=month, value=value))
    for code, value in (("2", 100.0), ("5", 80.0)):
        ind = db_session.query(Indicator).filter_by(code=code).one()
        db_session.add(IndicatorValue(
            hospital_id=target.id, indicator_id=ind.id,
            month=MONTHS[-1], value=value))
    db_session.commit()

    run_full_analysis(db_session, target.id, MONTHS[-1], force=True)

    row = db_session.query(LayeredOutlierResult).filter_by(
        hospital_id=target.id, month=MONTHS[-1],
        analysis_code="rate_cs").one()
    assert row.history_provenance["window"] == 12
    assert row.history_provenance["min_observations"] >= 3
    assert row.history_provenance["months"] == MONTHS[:-1]
    assert len(row.history_provenance["values"]) == 4
    assert row.peer_provenance["group"] == DETECTION_PEER_GROUP
    assert row.peer_provenance["eligible_count"] == 2
    assert row.peer_provenance["peer_ids"]
    assert row.peer_provenance["values"]
    assert row.peer_provenance["scored_peer_count"] == 2
