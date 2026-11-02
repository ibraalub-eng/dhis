# -*- coding: utf-8 -*-
"""A comparison group too small to measure a spread produces no z-score.

A peer z divides by the group's own spread. With 2-3 other hospitals that
spread is estimated from 2-3 numbers — a range, not a distribution — and the
stored rows carried |z| = 224 from a **2-peer** group. Capping the band was not
enough: the band was refused while the z itself still read as a top-band
magnitude on every screen that quoted it.

The shared policy (``layered.PEER_Z_POLICY``) keeps the finding, its score, its
peer list and its peer count, and stops producing a z-score for such a group:

* the peer layer / alert stores ``z = NULL`` with provenance saying why;
* the projected ``anomaly_results`` row never substitutes the hospital's own
  history z for a peer comparison that was not graded;
* the Why popup and the Quality Alerts detail explain the dash instead of
  leaving it to guesswork.

Bands, thresholds and score formulas are unchanged.
"""
from types import SimpleNamespace

import pytest

from app.engine.anomaly.classify import TYPE_PEER_ANOMALY
from app.engine.anomaly.layered import (
    MIN_PEERS_FOR_TOP_BAND,
    AnalysisSpec,
    Thresholds,
    analyze_layered_entry,
    compute_peer_layer,
    peer_z_measurable,
    peer_z_provenance,
)
from app.engine.anomaly.projection import row_z_score
from app.engine.audit.explain import explain_layered_outlier
from app.engine.pipeline import _save_layered_results
from app.engine.quality_alerts import _peer_score, scan
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
)

CURRENT = "2027-04"
PRIOR = ["2027-01", "2027-02", "2027-03"]


def _count_spec() -> AnalysisSpec:
    return AnalysisSpec(analysis_code="17", name="Neonatal deaths",
                        indicator_type="count")


# ── The shared boundary ────────────────────────────────────────────────────

def test_boundary_is_the_shared_top_band_minimum():
    assert MIN_PEERS_FOR_TOP_BAND == 4
    # 2 and 3 peers cannot measure a spread; 4 can.
    assert peer_z_measurable(2) is False
    assert peer_z_measurable(3) is False
    assert peer_z_measurable(4) is True
    assert peer_z_measurable(None) is False

    withheld = peer_z_provenance(2)
    assert withheld["z_produced"] is False
    assert withheld["min_peers_for_z"] == MIN_PEERS_FOR_TOP_BAND
    assert "no z-score is produced" in withheld["policy"]
    assert peer_z_provenance(5) == {"peer_count": 5, "min_peers_for_z": 4,
                                    "z_produced": True, "policy": None}


# ── The peer layer: score kept, z withheld ────────────────────────────────

def test_two_peer_group_keeps_its_score_and_produces_no_z():
    layer = compute_peer_layer(
        _count_spec(), self_id=1, current_value=90.0,
        peer_tiers=[("all", {1: 90.0, 2: 10.0, 3: 10.4})],
    )
    # The deviation is real evidence and is preserved verbatim.
    assert layer.peer_count == 2
    assert layer.peer_values == {2: 10.0, 3: 10.4}
    assert layer.peer_mean == pytest.approx(10.2)
    assert layer.peer_std == pytest.approx(0.282842, abs=1e-6)
    assert layer.score == pytest.approx(1.0)
    # The graded z is not produced: |z| here would be ~282, not a measurement.
    assert layer.z is None
    assert layer.z_measurable is False


def test_four_peer_group_still_produces_its_z():
    layer = compute_peer_layer(
        _count_spec(), self_id=1, current_value=12.0,
        peer_tiers=[("all", {1: 12.0, 2: 10.0, 3: 11.0, 4: 9.0, 5: 10.0})],
    )
    assert layer.peer_count == 4
    assert layer.z is not None
    assert layer.z_measurable is True
    peers = [10.0, 11.0, 9.0, 10.0]
    mean = sum(peers) / len(peers)
    std = (sum((p - mean) ** 2 for p in peers) / (len(peers) - 1)) ** 0.5
    assert layer.z == pytest.approx((12.0 - mean) / std)


# ── Entry point: the row a scan stores ────────────────────────────────────

def test_two_peer_row_caps_the_band_and_reports_no_z():
    # The hospital's own history is flat at 90 (no history anomaly), while the
    # only two peers that reported sit at ~10: the peer deviation is the finding.
    history = {month: {"17": 90} for month in PRIOR}
    history[CURRENT] = {"17": 90}
    peers = [("all", {1: 90.0, 2: 10.0, 3: 10.4})]

    result = analyze_layered_entry(_count_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=1)

    assert result.peer.score == pytest.approx(1.0)
    assert result.peer.z is None
    classification = result.classification
    assert classification.outlier_type == TYPE_PEER_ANOMALY
    assert classification.rule_number == 6, "the peer evidence still classifies"
    assert classification.thin_peer_layers == ("peer",)
    assert classification.outlier_level == "HIGH", "top band refused"
    assert classification.level_capped_from == "VERY_HIGH"
    assert "no z-score is produced for it" in classification.interpretation
    assert f"fewer than {MIN_PEERS_FOR_TOP_BAND} peer hospitals" \
        in classification.interpretation


def test_peer_z_threshold_unchanged_for_large_groups():
    """No threshold moved: 4 peers grade exactly as before."""
    history = {month: {"17": 90} for month in PRIOR}
    history[CURRENT] = {"17": 90}
    peers = [("all", {1: 90.0, 2: 10.0, 3: 10.4, 4: 10.6, 5: 10.2})]
    result = analyze_layered_entry(_count_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=1)
    assert result.peer.peer_count == 4
    assert result.peer.z is not None
    assert result.peer.z > 2.5, "far outside the group: still a real deviation"
    assert result.classification.outlier_level == "VERY_HIGH"


# ── Persistence + Why popup ───────────────────────────────────────────────

@pytest.fixture
def stored_two_peer_row(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    indicator = db_session.query(Indicator).filter_by(code="17").first()
    assert indicator is not None, "conftest seeds indicator 17"
    for month in PRIOR + [CURRENT]:
        db_session.add(IndicatorValue(hospital_id=hospital.id, month=month,
                                      indicator_id=indicator.id, value=90.0))
    db_session.commit()

    history = {month: {"17": 90} for month in PRIOR}
    history[CURRENT] = {"17": 90}
    peers = [("all", {hospital.id: 90.0, hospital.id + 1: 10.0,
                      hospital.id + 2: 10.4})]
    result = analyze_layered_entry(_count_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=hospital.id)
    _save_layered_results(db_session, hospital.id, CURRENT, [result])
    return hospital


def test_pipeline_persists_the_thin_peer_marker(db_session, stored_two_peer_row):
    row = (db_session.query(LayeredOutlierResult)
           .filter_by(hospital_id=stored_two_peer_row.id, month=CURRENT,
                      analysis_code="17").one())
    provenance = row.classification_provenance
    assert provenance["thin_peer_layers"] == ["peer"]
    assert provenance["min_peers_for_top_band"] == MIN_PEERS_FOR_TOP_BAND
    assert row.outlier_level == "HIGH"
    assert row.peer_outlier_score == pytest.approx(1.0)


def test_popup_reports_the_withheld_peer_z(db_session, stored_two_peer_row):
    payload = explain_layered_outlier(db_session, stored_two_peer_row.id,
                                      CURRENT, "17")
    assert payload["reproduce"]["peer_z"]["z_produced"] is False
    peer_layer = next(layer for layer in payload["layers"]
                      if layer["key"] == "peer")
    assert peer_layer["peer_z_withheld"] is True
    assert peer_layer["score"] == pytest.approx(1.0)
    assert "no z-score is produced" in peer_layer["detail"]


# ── Quality Alerts: the same rule for every perspective ───────────────────

def test_alert_peer_score_withholds_the_z_for_a_two_peer_group():
    z, score, stats = _peer_score(90.0, [10.0, 10.4], 2.5)
    assert z is None
    assert score == pytest.approx(1.0), "the deviation is still scored"
    assert stats["z_provenance"]["z_produced"] is False
    assert stats["z_provenance"]["min_peers_for_z"] == MIN_PEERS_FOR_TOP_BAND
    assert stats["mean"] == pytest.approx(10.2)


def test_scan_stores_the_capped_band_for_a_thin_peer_group(db_session):
    """The scan writes the capped band, not just the readers.

    Three hospitals report, so the peer group is two other hospitals — enough
    to compare against (``min_peers``) but too small to measure a spread. The
    finding is stored as HIGH with the cap recorded on the row itself; a row
    that kept the top band until somebody rescanned the month made the store
    disagree with every screen that reads it.
    """
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:3]
    indicator = db_session.query(Indicator).filter_by(code="17").one()
    values = {0: 90.0, 1: 10.0, 2: 10.4}
    for index, hospital in enumerate(hospitals):
        for month in PRIOR + [CURRENT]:
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, month=month,
                indicator_id=indicator.id, value=values[index]))
    db_session.commit()

    scan(db_session, CURRENT)

    rows = (db_session.query(QualityAlert)
            .filter_by(hospital_id=hospitals[0].id, indicator_code="17",
                       month=CURRENT).all())
    peers = next(a for a in rows if a.perspective == "all")
    assert peers.peer_count == 2
    assert peers.score == pytest.approx(1.0), "the deviation is still scored"
    assert peers.severity == "HIGH", "the top band is refused"
    assert peers.z_score is None, "a two-peer group measures no spread"

    thin = peers.evidence["thin_peer_group"]
    assert thin["capped"] is True
    assert thin["peer_count"] == 2
    assert thin["resolved_level"] == "VERY_HIGH"
    assert thin["final_level"] == "HIGH"
    assert "capped at HIGH" in (peers.reason or "")


def test_alert_peer_score_produces_the_z_for_a_large_group():
    z, score, stats = _peer_score(90.0, [10.0, 10.4, 10.6, 10.2], 2.5)
    assert z is not None and z > 2.5
    assert stats["z_provenance"]["z_produced"] is True
    assert stats["z_provenance"]["policy"] is None


# ── Root cause: the peer comparison withholds the z ─────────────────

def test_root_cause_peer_comparison_withholds_the_z_for_two_peers():
    """The root-cause peer comparison keeps percentile/mean/gap, no z."""
    from app.engine.root_cause import calculate_peer_comparison

    comp = calculate_peer_comparison(90.0, [10.0, 10.4], "Hospital")
    assert comp.peer_count == 2
    assert comp.hospital_z_score is None
    # The comparison itself is untouched: it is still fully readable.
    assert comp.mean_value == pytest.approx(10.2)
    assert comp.hospital_percentile == 100.0
    assert comp.gap_to_benchmark == pytest.approx(round(10.4 - 90.0, 2))


def test_root_cause_peer_comparison_grades_four_peers_as_before():
    from app.engine.root_cause import calculate_peer_comparison

    comp = calculate_peer_comparison(12.0, [10.0, 11.0, 9.0, 10.0], "Hospital")
    assert comp.peer_count == 4
    assert comp.hospital_z_score is not None, "no threshold moved"


# ── The legacy peer detector (Outliers screen / Audit benchmark source) ───

def test_legacy_detector_keeps_the_verdict_and_withholds_the_z():
    """`detect_anomalies` is what the Outliers screen and the Audit benchmark's
    parity test read: the finding and its benchmark stay, the z does not."""
    from app.engine.anomaly.zscore import detect_anomalies

    rows = detect_anomalies(
        {"Target": {"5": 90, "2": 100}, "A": {"5": 30, "2": 100},
         "B": {"5": 40, "2": 100}},
        "Target", "2026-04",
    )
    cs = next(r for r in rows if r.rate_name == "C-section rate")
    assert cs.peer_count == 2
    assert cs.z_score is None
    assert bool(cs.is_outlier) is True, "the finding is kept"
    assert cs.benchmark == 35.0
    assert cs.peer_std is not None
    assert cs.z_provenance["z_produced"] is False
    assert cs.z_provenance["min_peers_for_z"] == MIN_PEERS_FOR_TOP_BAND


def test_legacy_detector_still_grades_a_large_group():
    from app.engine.anomaly.zscore import detect_anomalies

    data = {"Target": {"5": 90, "2": 100}}
    for i, rate in enumerate((30, 40, 35, 45, 38)):
        data[f"P{i}"] = {"5": rate, "2": 100}
    rows = detect_anomalies(data, "Target", "2026-04")
    cs = next(r for r in rows if r.rate_name == "C-section rate")
    assert cs.peer_count == 5
    assert cs.z_score is not None
    assert cs.z_provenance["z_produced"] is True


# ── Quality Alerts: the read-time gate on STORED rows ─────────────────────
# Rows written before the policy still carry the uncapped z. The screen reads
# them through the same rule the scan applies (engine.effective_z_score), so a
# pre-policy row stops quoting a z its group cannot support — and the stored
# value is reported as stored_z_score rather than being rewritten.

def test_read_time_z_gate_only_governs_peer_comparisons():
    from app.engine.quality_alerts import effective_z_score, z_score_provenance

    assert effective_z_score(224.3, method="peer_zscore", peer_count=2) is None
    assert effective_z_score(224.3, method="peer_zscore", peer_count=3) is None
    assert effective_z_score(224.3, method="peer_zscore", peer_count=4) == 224.3
    # A history baseline's peer_count counts MONTHS: never withheld here.
    assert effective_z_score(3.1, method="zscore", peer_count=2) == 3.1
    assert effective_z_score(3.1, method="pct_change", peer_count=1) == 3.1

    withheld = z_score_provenance(224.3, method="peer_zscore", peer_count=2)
    assert withheld["z_produced"] is False
    assert withheld["scope"] == "peer"
    assert withheld["min_peers_for_z"] == MIN_PEERS_FOR_TOP_BAND
    assert "no z-score is produced" in withheld["policy"]
    graded = z_score_provenance(3.4, method="peer_zscore", peer_count=4)
    assert graded["z_produced"] is True and graded["policy"] is None
    assert z_score_provenance(3.1, method="zscore", peer_count=2) is None, (
        "a history z must not borrow the peer explanation")


def _pre_policy_alert(db_session, *, month="2027-05", perspective="all",
                      method="peer_zscore", peer_count=2, z_score=224.3):
    """A row written BEFORE the policy: z stored, no z_provenance block."""
    from app.models import QualityAlert

    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    row = QualityAlert(
        hospital_id=hospital.id, month=month, perspective=perspective,
        indicator_code="QA_THIN_Z", indicator_name="Thin peer z rate",
        unit="%", formula="a / b * 100", formula_version="1",
        severity="HIGH", score=1.0, method=method,
        current_value=90.0, baseline_value=10.2, deviation_pct=782.35,
        z_score=z_score, peer_count=peer_count, confidence="low",
        status="New", active=True,
        evidence={"stats": {"mean": 10.2, "std": 0.2828, "median": 10.2,
                            "min": 10.0, "max": 10.4}},
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_detail_withholds_a_pre_policy_thin_peer_z(app, db_session):
    from fastapi.testclient import TestClient

    row = _pre_policy_alert(db_session)
    client = TestClient(app)

    resp = client.get(f"/quality-alerts/{row.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    alert = body["alert"]

    assert alert["z_score"] is None, "224 from 2 peers is not a measurement"
    assert alert["stored_z_score"] == pytest.approx(224.3)
    assert alert["z_provenance"]["z_produced"] is False
    assert alert["z_provenance"]["peer_count"] == 2
    assert alert["thin_peer_group"] is True
    # The same gate covers the issue's perspective list …
    sibling = next(p for p in body["issue"]["perspectives"]
                   if p["id"] == row.id)
    assert sibling["z_score"] is None
    assert sibling["stored_z_score"] == pytest.approx(224.3)
    # … and the evidence copy states why, so the detail explains the dash.
    assert body["evidence"]["stats"]["z_provenance"]["z_produced"] is False
    assert body["evidence"]["stats"]["mean"] == pytest.approx(10.2)

    # A read never rewrites the row: the stored z and its evidence stand.
    db_session.refresh(row)
    assert row.z_score == pytest.approx(224.3)
    assert "z_provenance" not in (row.evidence.get("stats") or {})


def test_detail_keeps_the_z_a_measurable_group_and_a_history_row_earned(
        app, db_session):
    from fastapi.testclient import TestClient

    graded = _pre_policy_alert(db_session, month="2027-06", peer_count=4,
                               z_score=3.4)
    history = _pre_policy_alert(db_session, month="2027-07",
                                perspective="history", method="zscore",
                                peer_count=3, z_score=2.9)
    client = TestClient(app)

    body = client.get(f"/quality-alerts/{graded.id}").json()
    assert body["alert"]["z_score"] == pytest.approx(3.4), "no threshold moved"
    assert body["alert"]["z_provenance"]["z_produced"] is True

    body = client.get(f"/quality-alerts/{history.id}").json()
    assert body["alert"]["z_score"] == pytest.approx(2.9), (
        "3 prior MONTHS is a history baseline, not a 3-peer group")
    assert body["alert"]["z_provenance"] is None


def test_quality_issue_text_does_not_print_a_null_z():
    """The score's issue list is a screen surface: no "z=None" for a group that
    could not measure a spread — it names the peer count instead."""
    from app.engine.quality.scoring import calculate_quality_score

    row = SimpleNamespace(rate_name="C-section rate", z_score=None,
                          peer_count=2, is_outlier=True)
    out = calculate_quality_score([], {"2": 100.0}, [row], {"2"})
    joined = " ".join(out["issues"])
    assert "z=None" not in joined
    assert "no z; 2 peer hospital(s)" in joined


# ── The projected legacy row ──────────────────────────────────────────────

def test_projected_row_never_borrows_the_history_z():
    peer = compute_peer_layer(
        _count_spec(), self_id=1, current_value=90.0,
        peer_tiers=[("all", {1: 90.0, 2: 10.0, 3: 10.4})],
    )
    historical = SimpleNamespace(z_score=3.7)
    assert row_z_score(peer, historical) is None, (
        "the row's benchmark is the PEER mean; a history z would describe a "
        "different comparison")

    # No peer comparison at all: the history z is the row's own measurement.
    unavailable = compute_peer_layer(
        _count_spec(), self_id=1, current_value=90.0,
        peer_tiers=[("all", {1: 90.0, 2: 10.0})],   # below the minimum
    )
    assert unavailable.score is None
    assert row_z_score(unavailable, historical) == 3.7


# ── The legacy anomaly popup with a NULL peer z ───────────────────────────

def test_anomaly_popup_explains_a_withheld_peer_z(db_session):
    """A 2-peer row written by the current policy stores z = NULL: the popup
    must check the population and say the z was not produced — not claim a
    missing measurement, and not raise on the NULL."""
    from app.engine.audit.explain import explain_anomaly
    from app.models import AnomalyResult

    month = "2027-07"
    codes = {}
    for code in ("17", "6"):
        ind = db_session.query(Indicator).filter(Indicator.code == code).first()
        assert ind is not None
        codes[code] = ind.id

    # Two peers (0% and 0.14%) and a target far above them. The peer check
    # rebuilds the population from the stored values, so these must be real
    # hospitals with real values.
    target, peer_a, peer_b = (
        db_session.query(Hospital).order_by(Hospital.id).limit(3).all())
    raw = {target.id: (1, 50), peer_a.id: (0, 50), peer_b.id: (1, 700)}
    for hid, (num, den) in raw.items():
        db_session.add(IndicatorValue(hospital_id=hid, month=month,
                                      indicator_id=codes["17"], value=num))
        db_session.add(IndicatorValue(hospital_id=hid, month=month,
                                      indicator_id=codes["6"], value=den))
    db_session.commit()

    peers = [
        {"hospital": peer_a.name, "rate": 0.0},
        {"hospital": peer_b.name, "rate": round(1 / 700 * 100, 4)},
    ]
    peer_rates = [p["rate"] for p in peers]
    peer_mean = sum(peer_rates) / len(peer_rates)
    peer_std = ((sum((r - peer_mean) ** 2 for r in peer_rates)
                 / (len(peer_rates) - 1)) ** 0.5)
    row = AnomalyResult(
        hospital_id=target.id, month=month, indicator_code="17",
        rate_name="Neonatal mortality rate", value=2.0,
        benchmark=round(peer_mean, 2),
        z_score=None,                     # the policy produced no z
        is_outlier=True, peer_count=2,
        peer_std=round(peer_std, 2),
        peer_min=0.0, peer_max=0.14, peer_median=round(peer_mean, 2),
        peers_detail=peers,
    )
    db_session.add(row)
    db_session.commit()

    payload = explain_anomaly(db_session, target.id, month,
                              rate_name=row.rate_name)
    peer_check = payload["peer_check"]
    assert peer_check["z_produced"] is False
    assert peer_check["expected_z"] is None
    assert peer_check["z_provenance"]["z_produced"] is False
    assert "produces no z-score" in peer_check["note"]
    assert peer_check["peer_set_matches"] is True
    # The population is what can be verified: a NULL z withheld by policy is
    # not reported as a failed reproduction.
    assert payload["reproduce"]["verified"] is True
