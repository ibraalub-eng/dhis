"""The VERY_HIGH eligibility gate, WIRED into the three read seams.

The gate refuses the top band to a history comparison whose own window's
dispersion does not support it. It is deliberately NOT applied to peer, volume
or raw-count-on-a-rate claims: those have their own approved policies, and the
history window cannot judge them.

What these tests protect:

* routing — history is gated, peer / volume / raw-on-rate stay ``undecided``
  and keep the band they earned;
* the three seams return the SAME band for the same row (Quality Alerts and the
  Dashboard share ``engine.effective_severity``; Diagnostics uses
  ``layered.row_level_assessment``);
* the four states are never folded together: ``not_applicable`` (the row is not
  a top-band claim), ``undecided`` (the policy could not judge), and
  ``eligible`` / ``ineligible`` (it judged);
* nothing is written: the stored band, the evidence and the classification
  provenance all survive every read, and the rescan write-back still targets
  only the two approved caps.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.api import quality_alerts as qa
from app.api.analysis import _stale_layered_rows
from app.api.dashboard import _quality_issue_counts
from app.engine.anomaly.layered import (
    DECISION_INELIGIBLE,
    DECISION_NOT_APPLICABLE,
    DECISION_UNDECIDED,
    LEVEL_HIGH,
    LEVEL_VERY_HIGH,
    METHOD_PEER_ZSCORE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_ZSCORE,
    PEER_Z_THRESHOLD_DEFAULT,
    ROUTE_HISTORY,
    ROUTE_PEER,
    ROUTE_RAW_UNIT,
    ROUTE_VOLUME,
    row_gate_threshold,
    row_level_assessment,
    row_very_high_eligibility,
)
from app.engine.pipeline import _save_layered_results
from app.engine.quality_alerts import (
    alert_route,
    effective_severity,
    severity_cap,
)
from app.models import Hospital, LayeredOutlierResult, QualityAlert

MONTH = "2027-09"
# A window whose own z at 40 is ~59 sigmas: the top band is supported.
SUPPORTING_WINDOW = (10.0, 10.0, 11.0, 10.0)
# A wide window: 24 is above nothing the window has not already seen (30), and
# its z is ~1.1 — the robust score saturates, the dispersion does not.
WIDE_WINDOW = (1.0, 30.0, 0.0, 4.0)


def _alert_row(db, hospital_id, *, code, history, current,
               perspective="history", method=METHOD_ZSCORE, severity=LEVEL_VERY_HIGH,
               month=MONTH, threshold=None):
    evidence = {
        "history": [[f"2027-0{i + 1}", value] for i, value in enumerate(history)],
        "stats": {"mean": sum(history) / len(history), "std": 1.0, "points": len(history)},
    }
    if threshold is not None:
        evidence["z_threshold"] = threshold
    row = QualityAlert(
        hospital_id=hospital_id, month=month, perspective=perspective,
        indicator_code=code, indicator_name=f"{code} rate", unit="%",
        formula=f"{code}_num / {code}_den * 100",
        severity=severity, score=1.0, method=method,
        current_value=current, baseline_value=history[0] if history else None,
        z_score=None, peer_count=len(history), status="New", active=True,
        direction="lower_is_better", interpretation="statistical_only",
        confidence="high", evidence=evidence,
    )
    db.add(row)
    db.commit()
    return row


def _layered_row(*, stored=LEVEL_VERY_HIGH, scores=None, history=WIDE_WINDOW,
                 current=24.0, rate=None, raw_value=None, peers=None,
                 peer_count=6, provenance=None, row_id=1):
    default = {"raw": None, "rate": None, "historical": None,
               "volume": None, "peer": None}
    default.update(scores or {})
    return SimpleNamespace(
        id=row_id, hospital_id=7, month=MONTH, analysis_code="10.i",
        outlier_level=stored, outlier_method=METHOD_ZSCORE,
        raw_value=raw_value if raw_value is not None else current,
        rate=rate, peer_count=peer_count,
        peer_mean=(sum(peers) / len(peers)) if peers else None,
        raw_value_outlier_score=default["raw"],
        rate_outlier_score=default["rate"],
        historical_outlier_score=default["historical"],
        volume_anomaly_score=default["volume"],
        peer_outlier_score=default["peer"],
        historical_std=None,
        history_provenance={"values": list(history)} if history else None,
        peer_provenance={"values": dict(enumerate(peers))} if peers else None,
        classification_provenance=provenance,
    )


# ── Routing ────────────────────────────────────────────────────────────────

def test_only_the_history_perspective_is_gated():
    assert alert_route("history", METHOD_ZSCORE) == ROUTE_HISTORY
    for label in ("all", "type", "ownership", "facility_type", "governorate"):
        assert alert_route(label, METHOD_PEER_ZSCORE) == ROUTE_PEER
    # Rows written before the perspective was read alongside the band.
    assert alert_route(None, METHOD_PEER_ZSCORE) == ROUTE_PEER
    assert alert_route(None, METHOD_ROLLING_MEDIAN_MAD) == ROUTE_HISTORY


def test_a_peer_perspective_keeps_the_band_the_history_gate_would_refuse():
    common = dict(stats={"std": 4.4}, method=METHOD_PEER_ZSCORE, peer_count=6,
                  series=list(WIDE_WINDOW), current=24.0)
    peer = effective_severity("VERY_HIGH", perspective="all", **common)
    history = effective_severity("VERY_HIGH", perspective="history", **common)
    assert peer == LEVEL_VERY_HIGH, "peer claims are judged by the peer policies"
    assert history == LEVEL_HIGH, "the same window does not support the top band"


def test_a_supporting_window_keeps_the_top_band():
    assert effective_severity(
        "VERY_HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(SUPPORTING_WINDOW), current=40.0,
        perspective="history") == LEVEL_VERY_HIGH


# ── The four states, kept apart ────────────────────────────────────────────

def test_the_states_are_reported_separately():
    ineligible = qa.engine.eligibility_assessment(
        "VERY_HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=24.0, perspective="history")
    assert ineligible["decision"] == DECISION_INELIGIBLE
    assert ineligible["reason"] == "DISPERSION_BAND_BELOW_VERY_HIGH"

    peer = qa.engine.eligibility_assessment(
        "VERY_HIGH", method=METHOD_PEER_ZSCORE, peer_count=6,
        series=[], current=24.0, perspective="all")
    assert peer["decision"] == DECISION_UNDECIDED
    assert peer["route"] == ROUTE_PEER

    below = qa.engine.eligibility_assessment(
        "HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=24.0, perspective="history")
    assert below["decision"] == DECISION_NOT_APPLICABLE
    assert below["eligible"] is None


def test_missing_current_value_is_undecided_not_a_refusal():
    assessment = qa.engine.eligibility_assessment(
        "VERY_HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=None, perspective="history")
    assert assessment["decision"] == DECISION_UNDECIDED
    assert assessment["reason"] == "CURRENT_VALUE_MISSING"
    assert effective_severity(
        "VERY_HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=None,
        perspective="history") == LEVEL_VERY_HIGH


def test_a_missing_window_is_undecided_and_named():
    assessment = qa.engine.eligibility_assessment(
        "VERY_HIGH", method=METHOD_ZSCORE, peer_count=0,
        series=[], current=24.0, perspective="history")
    assert assessment["decision"] == DECISION_UNDECIDED
    assert assessment["reason"] == "NO_STORED_HISTORY_WINDOW"


# ── The layered row: peer / volume / raw-on-rate stay undecided ────────────

def test_a_peer_layer_is_not_gated_even_when_the_window_refuses():
    row = _layered_row(scores={"peer": 1.0}, history=WIDE_WINDOW, current=24.0)
    verdict = row_very_high_eligibility(row)
    assert verdict["decision"] == DECISION_UNDECIDED
    assert verdict["route"] == ROUTE_PEER
    assert verdict["band"] == LEVEL_VERY_HIGH
    assert row_level_assessment(row) == (LEVEL_VERY_HIGH, None)


def test_a_volume_layer_is_not_gated():
    row = _layered_row(scores={"volume": 1.0})
    verdict = row_very_high_eligibility(row)
    assert verdict["decision"] == DECISION_UNDECIDED
    assert verdict["route"] == ROUTE_VOLUME
    assert verdict["band"] == LEVEL_VERY_HIGH


def test_a_raw_count_on_a_rate_analysis_is_a_unit_mismatch():
    row = _layered_row(scores={"raw": 1.0}, rate=25.0, raw_value=90.0)
    verdict = row_very_high_eligibility(row)
    assert verdict["decision"] == DECISION_UNDECIDED
    assert verdict["route"] == ROUTE_RAW_UNIT
    assert verdict["unit_compatible"] is False
    assert verdict["band"] == LEVEL_VERY_HIGH


def test_a_history_layer_is_gated_on_the_row():
    row = _layered_row(scores={"historical": 1.0}, history=WIDE_WINDOW,
                       current=24.0)
    verdict = row_very_high_eligibility(row)
    assert verdict["decision"] == DECISION_INELIGIBLE
    assert verdict["route"] == ROUTE_HISTORY
    assert verdict["band"] == LEVEL_HIGH
    assert row_level_assessment(row)[0] == LEVEL_HIGH


def test_a_measured_layer_keeps_the_band_a_gated_layer_cannot():
    """The gate is per layer: a refused history layer does not lower a band a
    peer layer legitimately holds."""
    row = _layered_row(scores={"historical": 1.0, "peer": 1.0},
                       history=WIDE_WINDOW, current=24.0, peers=[10.0, 20.0, 30.0])
    verdict = row_very_high_eligibility(row)
    assert verdict["decision"] == DECISION_UNDECIDED
    assert verdict["route"] == ROUTE_PEER
    assert verdict["band"] == LEVEL_VERY_HIGH


# ── The top band only ──────────────────────────────────────────────────────

def test_the_gate_never_lowers_below_high():
    row = _layered_row(scores={"historical": 1.0}, history=(0.0, 1.0, 2.0, 1.0, 8.0, 0.0),
                       current=9.0)
    band, cap = row_level_assessment(row)
    assert band == LEVEL_HIGH
    assert cap["very_high_eligibility"]["eligible"] is False


def test_a_row_below_the_top_band_is_untouched():
    assert effective_severity(
        "HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=24.0,
        perspective="history") == "HIGH"
    assert severity_cap(
        "HIGH", method=METHOD_ZSCORE, peer_count=4,
        series=list(WIDE_WINDOW), current=24.0, perspective="history") is None


def test_the_gate_is_idempotent():
    once = effective_severity("VERY_HIGH", method=METHOD_ZSCORE, peer_count=4,
                              series=list(WIDE_WINDOW), current=24.0,
                              perspective="history")
    twice = effective_severity(once, method=METHOD_ZSCORE, peer_count=4,
                               series=list(WIDE_WINDOW), current=24.0,
                               perspective="history")
    assert (once, twice) == (LEVEL_HIGH, LEVEL_HIGH)


# ── The threshold the gate asks with ───────────────────────────────────────

def test_the_gate_prefers_the_threshold_the_row_recorded():
    row = _layered_row(scores={"historical": 1.0},
                       provenance={"zscore_threshold": 3.0})
    assert row_gate_threshold(row) == 3.0
    legacy = _layered_row(scores={"historical": 1.0}, provenance=None)
    assert row_gate_threshold(legacy) == PEER_Z_THRESHOLD_DEFAULT


def test_saved_rows_record_the_threshold_they_were_classified_with(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    _save_layered_results(db_session, hospital.id, MONTH, [_result_stub()],
                          zscore_threshold=3.0)
    row = (db_session.query(LayeredOutlierResult)
           .filter(LayeredOutlierResult.hospital_id == hospital.id,
                   LayeredOutlierResult.month == MONTH)
           .one())
    assert row.classification_provenance["zscore_threshold"] == 3.0
    assert row_gate_threshold(row) == 3.0


def _result_stub(code="stub_rate"):
    """The attribute surface ``_save_layered_results`` reads, nothing more."""
    spec = SimpleNamespace(indicator_id=None, analysis_code=code, is_rate=True)
    classification = SimpleNamespace(
        outlier_level=LEVEL_HIGH, outlier_type="RATE_ANOMALY",
        method=METHOD_ZSCORE, interpretation="statistical_only",
        investigation_required=False, investigation_route="none",
        zero_spread_layers=(), thin_peer_layers=(), level_capped_from=None)
    return SimpleNamespace(
        spec=spec, classification=classification,
        raw=SimpleNamespace(value=25.0, previous=10.0, score=1.0),
        rate=SimpleNamespace(rate=25.0, score=1.0),
        historical=SimpleNamespace(
            mean=10.0, median=10.0, std=1.0, z_score=15.0, change_percent=150.0,
            score=1.0, window=4, min_observations=3,
            window_months=["2027-05", "2027-06", "2027-07", "2027-08"],
            series=[10.0, 10.0, 11.0, 10.0], skipped_months=[]),
        volume=SimpleNamespace(denominator=100.0, previous=100.0,
                               change_percent=0.0, score=0.0),
        peer=SimpleNamespace(score=None, peer_mean=None, peer_count=None,
                             group="all", min_peers=4, eligible_count=0,
                             eligible_ids=[], peer_values={}),
    )


# ── The screens ────────────────────────────────────────────────────────────

def test_dashboard_and_quality_alerts_report_the_same_very_high_count(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    refused = _alert_row(db_session, hospital.id, code="WIRE_REFUSED",
                         history=WIDE_WINDOW, current=24.0, threshold=2.5)
    kept = _alert_row(db_session, hospital.id, code="WIRE_KEPT",
                      history=SUPPORTING_WINDOW, current=40.0, threshold=2.5)

    assert qa._effective_severity(refused) == LEVEL_HIGH
    assert qa._effective_severity(kept) == LEVEL_VERY_HIGH

    counts = _quality_issue_counts(db_session, None, None, None, None, None)
    assert counts["total"] == 2
    assert counts["very_high"] == 1, "the Dashboard reads the same policy band"


def test_the_alert_payload_states_the_routing_decision(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    row = _alert_row(db_session, hospital.id, code="WIRE_PAYLOAD",
                     history=WIDE_WINDOW, current=24.0, threshold=2.5)
    payload = qa._alert_dict(row)
    assert payload["severity"] == LEVEL_HIGH
    assert payload["stored_severity"] == LEVEL_VERY_HIGH
    assert payload["top_band_eligibility"]["decision"] == DECISION_INELIGIBLE
    assert payload["top_band_eligibility"]["route"] == ROUTE_HISTORY
    assert payload["severity_cap"]["very_high_eligibility"]["capped"] is True


def test_a_peer_alert_payload_says_undecided(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    row = _alert_row(db_session, hospital.id, code="WIRE_PEER",
                     history=WIDE_WINDOW, current=24.0, perspective="all",
                     method=METHOD_PEER_ZSCORE)
    payload = qa._alert_dict(row)
    assert payload["severity"] == LEVEL_VERY_HIGH
    assert payload["top_band_eligibility"]["decision"] == DECISION_UNDECIDED
    assert payload["severity_cap"] is None


# ── Nothing is written ─────────────────────────────────────────────────────

def _fingerprint(db):
    alerts = [(row_id, severity, json.dumps(evidence, sort_keys=True))
              for row_id, severity, evidence in db.query(
                  QualityAlert.id, QualityAlert.severity, QualityAlert.evidence)
              .order_by(QualityAlert.id).all()]
    layered = [(row_id, level, json.dumps(provenance, sort_keys=True))
               for row_id, level, provenance in db.query(
                   LayeredOutlierResult.id, LayeredOutlierResult.outlier_level,
                   LayeredOutlierResult.classification_provenance)
               .order_by(LayeredOutlierResult.id).all()]
    return alerts, layered


def test_reading_a_row_changes_nothing(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    _alert_row(db_session, hospital.id, code="WIRE_FROZEN",
               history=WIDE_WINDOW, current=24.0, threshold=2.5)
    _save_layered_results(db_session, hospital.id, MONTH, [_result_stub()],
                          zscore_threshold=2.5)

    before = _fingerprint(db_session)
    for alert in db_session.query(QualityAlert).all():
        qa._alert_dict(alert)
    for row in db_session.query(LayeredOutlierResult).all():
        row_level_assessment(row)
        row_very_high_eligibility(row)
        _stale_layered_rows(db_session)
    db_session.expire_all()
    assert _fingerprint(db_session) == before


def test_the_rescan_write_back_still_targets_only_the_approved_caps(db_session):
    """A gate-only refusal is presented, never rewritten: re-banding an
    investigated issue is a separate, reviewed change."""
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()

    def _row(code, scores, provenance):
        row = LayeredOutlierResult(
            hospital_id=hospital.id, analysis_code=code, month=MONTH,
            raw_value=24.0, previous_value=10.0, rate=24.0,
            raw_value_outlier_score=scores.get("raw"),
            rate_outlier_score=scores.get("rate"),
            historical_outlier_score=scores.get("historical"),
            peer_outlier_score=scores.get("peer"),
            outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
            outlier_method=METHOD_ZSCORE, interpretation="statistical_only",
            investigation_route="none",
            history_provenance={"values": list(WIDE_WINDOW)},
            classification_provenance=provenance,
        )
        db_session.add(row)
        db_session.commit()
        return row

    gate_only = _row("GATE_ONLY", {"historical": 1.0}, {"zero_spread_layers": []})
    capped = _row("CAPPED_ONLY", {"peer": 1.0, "historical": 1.0},
                  {"zero_spread_layers": ["peer"]})

    stale = _stale_layered_rows(db_session)
    stale_ids = {row.id for row, _cap in stale}
    assert gate_only.id not in stale_ids, "the gate has no write-back path"
    assert capped.id in stale_ids, "the approved caps still do"


# ── Threshold provenance ────────────────────────────────────────────────────
# The gate asks with the threshold the SCAN recorded, never with a value read
# from the settings screen later. Legacy rows (written before the threshold was
# stored) fall back to the saved default (2.5) — the documented, unchanged
# behaviour — so an operator changing `zscore_threshold` does not silently
# re-judge history that was graded at 2.5.

def _assessment(threshold, *, current=24.0, window=WIDE_WINDOW):
    return qa.engine.eligibility_assessment(
        LEVEL_VERY_HIGH, stats={"mean": 1.0, "std": 1.0},
        method=METHOD_ZSCORE, peer_count=4, series=list(window),
        current=current, perspective="history", threshold=threshold)


def test_a_row_with_a_stored_historical_threshold_uses_it():
    verdict = _assessment(3.5)
    assert verdict["threshold"] == 3.5
    assert verdict["route"] == ROUTE_HISTORY


def test_a_legacy_row_without_a_threshold_uses_the_saved_default():
    verdict = _assessment(None)
    assert verdict["threshold"] == PEER_Z_THRESHOLD_DEFAULT
    # Identical to passing the default explicitly: nothing else is consulted.
    explicit = _assessment(PEER_Z_THRESHOLD_DEFAULT)
    assert verdict["final_band"] == explicit["final_band"]
    assert verdict["decision"] == explicit["decision"]


def test_a_configured_threshold_different_from_the_stored_one_does_not_win():
    stored = _assessment(3.5)
    legacy = _assessment(None)
    assert stored["threshold"] == 3.5
    assert legacy["threshold"] == PEER_Z_THRESHOLD_DEFAULT != 3.5
    # The read path takes no "configured" argument at all: the resolved value
    # is either the stored one or the saved default.
    assert legacy["threshold"] != stored["threshold"]


def test_threshold_resolution_agrees_on_alerts_dashboard_and_diagnostics(
        db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    alert = _alert_row(db_session, hospital.id, code="THR_PARITY",
                       history=WIDE_WINDOW, current=24.0, threshold=3.5)
    row = LayeredOutlierResult(
        hospital_id=hospital.id, analysis_code="THR_ROW", month=MONTH,
        raw_value=24.0, previous_value=24.0, rate=24.0,
        historical_outlier_score=1.0, raw_value_outlier_score=1.0,
        outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
        outlier_method=METHOD_ZSCORE, interpretation="statistical_only",
        investigation_route="none",
        history_provenance={"values": list(WIDE_WINDOW)},
        classification_provenance={"zscore_threshold": 3.5},
    )
    db_session.add(row)
    db_session.commit()

    alert_threshold = qa.engine.stored_threshold(alert.evidence)
    row_threshold = row_gate_threshold(row)
    assert alert_threshold == row_threshold == 3.5
    assert qa._effective_severity(alert) == row_level_assessment(row)[0]
    counts = _quality_issue_counts(db_session, None, None, None, None, None)
    assert counts["very_high"] == sum(
        1 for band in (qa._effective_severity(alert),)
        if band == LEVEL_VERY_HIGH)


def test_a_legacy_diagnostics_row_is_gated_at_the_saved_default(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    row = LayeredOutlierResult(
        hospital_id=hospital.id, analysis_code="THR_LEGACY", month=MONTH,
        raw_value=24.0, previous_value=24.0, rate=24.0,
        historical_outlier_score=1.0, raw_value_outlier_score=1.0,
        outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
        outlier_method=METHOD_ZSCORE, interpretation="statistical_only",
        investigation_route="none",
        history_provenance={"values": list(WIDE_WINDOW)},
        classification_provenance=None,
    )
    db_session.add(row)
    db_session.commit()
    level, cap = row_level_assessment(row)
    assert row_gate_threshold(row) == PEER_Z_THRESHOLD_DEFAULT
    assert level == LEVEL_HIGH
    assert cap["very_high_eligibility"]["threshold"] == PEER_Z_THRESHOLD_DEFAULT


# ── One dispersion assessment per row ──────────────────────────────────────

def test_the_dispersion_is_assessed_once_per_row(monkeypatch):
    import app.engine.anomaly.layered as layered_mod

    calls = []
    original = layered_mod.very_high_eligibility

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(layered_mod, "very_high_eligibility", counting)
    from app.engine.quality_alerts import top_band_gate

    level, provenance, assessment = top_band_gate(
        LEVEL_VERY_HIGH, method=METHOD_ZSCORE, perspective="history",
        series=list(WIDE_WINDOW), current=24.0, threshold=2.5)
    assert len(calls) == 1, "the window must be measured once, not twice"
    assert level == LEVEL_HIGH
    assert provenance["capped"] is True
    assert assessment["decision"] == DECISION_INELIGIBLE


def test_the_single_assessment_changes_no_output():
    from app.engine.anomaly.layered import cap_very_high_eligibility
    from app.engine.quality_alerts import top_band_gate

    level, provenance, assessment = top_band_gate(
        LEVEL_VERY_HIGH, method=METHOD_ZSCORE, perspective="history",
        series=list(WIDE_WINDOW), current=24.0, threshold=2.5)
    capped, direct = cap_very_high_eligibility(
        LEVEL_VERY_HIGH, WIDE_WINDOW, 24.0, 2.5)
    assert level == capped
    assert provenance == direct
    assert assessment["reason"] == direct["reason"]
    assert assessment["final_band"] == level


def test_an_undecidable_window_is_still_not_a_refusal(monkeypatch):
    import app.engine.anomaly.layered as layered_mod
    from app.engine.quality_alerts import top_band_gate

    calls = []
    original = layered_mod.very_high_eligibility
    monkeypatch.setattr(
        layered_mod, "very_high_eligibility",
        lambda *a, **k: (calls.append(1), original(*a, **k))[1])

    level, provenance, assessment = top_band_gate(
        LEVEL_VERY_HIGH, method=METHOD_ZSCORE, perspective="history",
        series=[], current=24.0, threshold=2.5)
    assert len(calls) == 1
    assert provenance is None
    assert level == LEVEL_VERY_HIGH
    assert assessment["decision"] == DECISION_UNDECIDED
    assert assessment["reason"] == "NO_STORED_HISTORY_WINDOW"
