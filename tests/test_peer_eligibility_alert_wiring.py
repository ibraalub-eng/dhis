# -*- coding: utf-8 -*-
"""Peer eligibility (Rule B) WIRED into the Quality Alerts read path — step 3.

What these tests protect:

* the peer group the SCAN stored on the row
  (``evidence["comparison_policy"]["peer"]["values"]``) is what the gate judges
  — never a recomputed group, never the live configuration;
* the definition gate runs first, resolved from ``build_analysis_specs``, so a
  synthetic forecast indicator the scan does not analyse stays ``undecided``;
* the peer policy is applied to the PEER route only: a history row carrying a
  peer block beside its window is still judged by its window;
* a row with no stored peer evidence keeps exactly the answer it had before
  (``undecided`` / ``PEER_POLICY``) — nothing is inferred or backfilled;
* NO band moves: the stored severity, the score, the z-score and the evidence
  are untouched, and ``_effective_severity`` returns what it always returned;
* the stored evidence is 4-decimal rounded, which is a documented tolerance:
  the one row that sits exactly on a scale boundary is pinned below.
"""
from __future__ import annotations

import json

import pytest

from app.api import quality_alerts as qa
from app.engine import quality_alerts as engine
from app.engine.anomaly import layered
from app.models import Hospital, QualityAlert

MONTH = "2027-09"
METHOD = "peer_zscore"
VH = layered.LEVEL_VERY_HIGH

# Two usable scales, both support: MAD = 1, IQR = 2, current far outside.
SUPPORTING_PEERS = [10.0, 10.0, 11.0, 12.0, 12.0]
# Two usable scales, both refuse.
REFUSING_PEERS = [10.0, 12.0, 14.0, 16.0]
# MAD supports (and saturates), IQR is inside its fences.
MIXED_PEERS = [0.0, 1.0, 2.0, 3.0, 4.0]
# No spread at all.
DEGENERATE_PEERS = [5.0, 5.0, 5.0, 5.0, 5.0]


def _peer_alert(db, hospital_id, *, code, peers, current,
                perspective="all", severity=VH, formula=None,
                numerator=120.0, denominator=1000.0, evidence_extra=None,
                peer_block=True, month=MONTH):
    """A stored PEER alert with the evidence the scan writes."""
    values = {str(i + 1): float(v) for i, v in enumerate(peers)} if peers else {}
    evidence = {
        "baseline_label": "All hospitals",
        "stats": {"mean": (sum(peers) / len(peers)) if peers else None,
                  "std": 1.0, "points": len(peers)},
        "z_threshold": 2.5,
        "numerator": numerator,
        "denominator": denominator,
        "canonical": {"key": f"key_{code}", "code": code,
                      "registered_codes": [code]},
    }
    if peer_block:
        evidence["comparison_policy"] = {
            "perspective_scope": "detection_baseline",
            "peer": {
                "group": "detection_baseline",
                "month": month,
                "min_peers": 2,
                "eligible_count": len(peers),
                "peer_ids": list(range(1, len(peers) + 1)),
                "values": values,
            },
        }
    evidence.update(evidence_extra or {})
    row = QualityAlert(
        hospital_id=hospital_id, month=month, perspective=perspective,
        indicator_code=code, indicator_name=f"{code} indicator", unit="%",
        formula=formula if formula is not None else f"{code}_num / {code}_den * 100",
        severity=severity, score=1.0, method=METHOD,
        current_value=current, baseline_value=(sum(peers) / len(peers)) if peers else None,
        z_score=None, peer_count=len(peers), status="New", active=True,
        direction="lower_is_better", interpretation="statistical_only",
        confidence="high", evidence=evidence,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def hospital_id(db_session):
    return db_session.query(Hospital).order_by(Hospital.id).first().id


def _eligibility(db_session, alert, catalog_codes=None):
    return qa._alert_dict(alert, catalog_codes=catalog_codes)["top_band_eligibility"]


# ── 1. The stored peer evidence decides ────────────────────────────────────

def test_stored_peer_evidence_produces_the_rule_b_verdict(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_PEER_OK",
                        peers=SUPPORTING_PEERS, current=19.0)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["route"] == layered.ROUTE_PEER
    assert verdict["decision"] == layered.DECISION_ELIGIBLE
    assert verdict["reason"] == layered.PEER_REASON_BOTH_SCALES_SUPPORT
    assert verdict["definition_status"] == layered.PEER_DEFINITION_COMPLETE
    assert verdict["policy"] == layered.PEER_ELIGIBILITY_POLICY
    assert verdict["group_comparability_status"] == \
        layered.GROUP_COMPARABILITY_NOT_VERIFIED
    # the group the scan stored is the one that was judged
    assert verdict["peer_eligibility"]["peer_count"] == len(SUPPORTING_PEERS)
    assert verdict["peer_eligibility"]["stored_peer_count"] == len(SUPPORTING_PEERS)


def test_two_usable_scales_refusing_is_ineligible(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_PEER_NO",
                        peers=REFUSING_PEERS, current=10.6)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["decision"] == layered.DECISION_INELIGIBLE
    assert verdict["reason"] == layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE
    assert verdict["eligible"] is False


# ── 2. The approved resolver, and what it refuses ──────────────────────────

def test_synthetic_forecast_indicator_stays_undecided(db_session, hospital_id):
    """``sys_forecast_adolescent`` is absent from ``build_analysis_specs``."""
    catalog = engine.peer_definition_codes(db_session)
    assert "sys_forecast_adolescent" not in catalog

    alert = _peer_alert(db_session, hospital_id,
                        code="sys_forecast_adolescent",
                        peers=SUPPORTING_PEERS, current=19.0,
                        formula="({2.c} + {2.d})", denominator=None)
    verdict = _eligibility(db_session, alert, catalog)
    assert verdict["decision"] == layered.DECISION_UNDECIDED
    assert verdict["reason"] == layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED
    assert verdict["definition_status"] == \
        layered.PEER_DEFINITION_NOT_ESTABLISHABLE


def test_a_catalog_only_definition_is_marked_not_verified(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_PEER_CATALOG",
                        peers=SUPPORTING_PEERS, current=19.0,
                        numerator=None, denominator=None)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["definition_status"] == layered.PEER_DEFINITION_CATALOG_ONLY
    assert verdict["decision"] == layered.DECISION_ELIGIBLE
    assert verdict["group_comparability_status"] == \
        layered.GROUP_COMPARABILITY_NOT_VERIFIED


def test_the_row_definition_wins_without_a_catalog_entry(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_PEER_SELF",
                        peers=SUPPORTING_PEERS, current=19.0)
    verdict = _eligibility(db_session, alert, set())
    assert verdict["definition_status"] == \
        layered.PEER_DEFINITION_SELF_CONTAINED
    assert verdict["decision"] == layered.DECISION_ELIGIBLE


# ── 3. The peer policy never reaches another route ─────────────────────────

def test_history_route_ignores_peer_evidence(db_session, hospital_id):
    alert = _peer_alert(
        db_session, hospital_id, code="WIRE_HISTORY_PEER_BLOCK",
        peers=SUPPORTING_PEERS, current=24.0, perspective="history")
    alert.method = "zscore"
    alert.evidence = dict(alert.evidence or {})
    alert.evidence["history"] = [["2027-05", 1.0], ["2027-06", 30.0],
                                 ["2027-07", 0.0], ["2027-08", 4.0]]
    db_session.commit()

    # The row carries a peer block, yet no peer evidence may be handed over.
    assert engine.peer_gate_inputs(alert, {alert.indicator_code}) == {}
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["route"] == layered.ROUTE_HISTORY
    assert "peer_eligibility" not in verdict
    assert verdict["reason"] not in {
        layered.PEER_REASON_BOTH_SCALES_SUPPORT,
        layered.PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS,
        layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE,
        layered.PEER_REASON_SCALES_DISAGREE,
    }


def test_a_peer_row_without_a_perspective_is_still_the_peer_route():
    """Rows written before the perspective was read alongside the band."""
    from types import SimpleNamespace

    alert = SimpleNamespace(
        perspective=None, method=METHOD, indicator_code="WIRE_NO_PERSPECTIVE",
        formula="f", evidence={
            "comparison_policy": {"peer": {
                "values": {str(i): v for i, v in enumerate(SUPPORTING_PEERS)}}},
            "numerator": 1.0, "denominator": 2.0,
        })
    assert engine.alert_route(None, METHOD) == layered.ROUTE_PEER
    assert engine.peer_gate_inputs(alert, {"WIRE_NO_PERSPECTIVE"})
    out = layered.peer_very_high_eligibility(
        VH, engine.stored_peer_group(alert.evidence), 19.0,
        definition_status=layered.peer_definition_status(
            **engine.alert_peer_definition(alert, {"WIRE_NO_PERSPECTIVE"})))
    assert out["decision"] == layered.DECISION_ELIGIBLE


# ── 4. Legacy rows, missing values ─────────────────────────────────────────

def test_legacy_row_without_peer_evidence_keeps_undecided(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_LEGACY",
                        peers=SUPPORTING_PEERS, current=19.0, peer_block=False)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["decision"] == layered.DECISION_UNDECIDED
    assert verdict["reason"] == "PEER_POLICY"
    assert "peer_eligibility" not in verdict
    assert engine.stored_peer_group(alert.evidence) == {}


def test_missing_current_value_returns_current_value_missing(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_NO_CURRENT",
                        peers=SUPPORTING_PEERS, current=19.0)
    alert.current_value = None
    db_session.commit()
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["decision"] == layered.DECISION_UNDECIDED
    assert verdict["reason"] == layered.PEER_REASON_CURRENT_VALUE_MISSING
    assert verdict["final_band"] == VH


# ── 5-6. No band, score or stored value moves ──────────────────────────────

@pytest.mark.parametrize("peers,current", [
    (SUPPORTING_PEERS, 19.0),      # eligible
    (REFUSING_PEERS, 10.6),        # ineligible
    (MIXED_PEERS, 7.0),            # undecided
    (DEGENERATE_PEERS, 9.0),       # insufficient_robust_scale
])
def test_severity_and_stored_severity_are_unchanged(db_session, hospital_id,
                                                    peers, current):
    alert = _peer_alert(db_session, hospital_id,
                        code=f"WIRE_BAND_{len(peers)}_{current}",
                        peers=peers, current=current)
    payload = qa._alert_dict(alert, catalog_codes={alert.indicator_code})
    assert payload["severity"] == VH
    assert payload["stored_severity"] == VH
    assert payload["top_band_eligibility"]["final_band"] == VH
    assert payload["score"] == 1.0
    # a peer row is never capped by this gate, so no cap block is produced
    assert payload["severity_cap"] is None


def test_effective_severity_matches_the_original_final_band(db_session, hospital_id):
    for index, (peers, current) in enumerate(((SUPPORTING_PEERS, 19.0),
                                              (REFUSING_PEERS, 10.6),
                                              (DEGENERATE_PEERS, 9.0))):
        alert = _peer_alert(db_session, hospital_id,
                            code=f"WIRE_EFFECTIVE_{index}",
                            peers=peers, current=current)
        payload = qa._alert_dict(alert, catalog_codes={alert.indicator_code})
        assert qa._effective_severity(alert) == VH
        assert payload["severity"] == qa._effective_severity(alert)
        assert payload["top_band_eligibility"]["final_band"] == \
            qa._effective_severity(alert)


def test_alert_dict_does_not_write(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_FROZEN",
                        peers=SUPPORTING_PEERS, current=19.0)

    def snapshot():
        return (alert.severity, alert.score, alert.z_score, alert.peer_count,
                alert.status, alert.current_value,
                json.dumps(alert.evidence, sort_keys=True),
                alert.detected_at, alert.updated_at)

    before = snapshot()
    qa._alert_dict(alert, catalog_codes={alert.indicator_code})
    qa._alert_dict(alert, catalog_codes=engine.peer_definition_codes(db_session))
    db_session.expire_all()
    assert snapshot() == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted


# ── 7. Evidence shapes ─────────────────────────────────────────────────────

def test_string_keyed_and_integer_keyed_peer_values_agree(db_session, hospital_id):
    string_keyed = _peer_alert(db_session, hospital_id, code="WIRE_KEYS_STR",
                               peers=SUPPORTING_PEERS, current=19.0)
    integer_keyed = _peer_alert(db_session, hospital_id, code="WIRE_KEYS_INT",
                                peers=SUPPORTING_PEERS, current=19.0)
    integer_keyed.evidence = dict(integer_keyed.evidence)
    integer_keyed.evidence["comparison_policy"] = {
        "peer": {"values": {i: float(v)
                            for i, v in enumerate(SUPPORTING_PEERS)}}}
    db_session.commit()

    a = _eligibility(db_session, string_keyed, {"WIRE_KEYS_STR"})
    b = _eligibility(db_session, integer_keyed, {"WIRE_KEYS_INT"})
    assert (a["decision"], a["reason"]) == (b["decision"], b["reason"])
    assert a["decision"] == layered.DECISION_ELIGIBLE


@pytest.mark.parametrize("values", [None, [], "not-a-group", 42, {"a": "x"}])
def test_malformed_peer_blocks_never_become_eligible(values):
    out = layered.peer_very_high_eligibility(VH, values, 19.0,
                                            definition_status="complete_from_row")
    assert out["decision"] in (layered.DECISION_UNDECIDED,
                              layered.DECISION_INSUFFICIENT_ROBUST_SCALE)
    assert out["eligible"] is not True


# ── 8. The approved reason codes survive the wiring ────────────────────────

def test_thin_group_is_owned_by_the_approved_cap(db_session, hospital_id):
    """3 peers: the thin-peer CAP decides the band, so the gate is not applicable.

    The peer policy's own ``THIN_PEER_GROUP`` reason is for a top band that
    reached the gate with a small group (peer count unknown to the cap); with a
    stored count of 3 the cap runs first and keeps the band at HIGH — unchanged
    by this step.
    """
    alert = _peer_alert(db_session, hospital_id, code="WIRE_THIN",
                        peers=[10.0, 12.0, 14.0], current=20.0)
    payload = qa._alert_dict(alert, catalog_codes={alert.indicator_code})
    verdict = payload["top_band_eligibility"]
    assert verdict["decision"] == layered.DECISION_NOT_APPLICABLE
    assert verdict["reason"] == layered.NOT_APPLICABLE
    assert payload["severity"] == layered.LEVEL_HIGH
    assert payload["stored_severity"] == VH, "the row keeps what it was written with"
    # and the policy's own code for a small group still holds inside it
    direct = layered.peer_very_high_eligibility(
        VH, {str(i): v for i, v in enumerate([10.0, 12.0, 14.0])}, 20.0,
        definition_status=layered.PEER_DEFINITION_COMPLETE)
    assert direct["reason"] == layered.PEER_REASON_THIN_PEER_GROUP


def test_zero_scale_group_keeps_insufficient_robust_scale(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_ZERO_SCALE",
                        peers=DEGENERATE_PEERS, current=9.0)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["decision"] == layered.DECISION_INSUFFICIENT_ROBUST_SCALE
    assert verdict["reason"] == layered.PEER_REASON_NO_ROBUST_SCALE
    assert verdict["decision"] != layered.DECISION_UNDECIDED


def test_single_usable_scale_refusal_stays_undecided(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_LONE_REFUSAL",
                        peers=[0.0, 0.0, 0.0, 0.0, 10.0, 10.0], current=30.0)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["decision"] == layered.DECISION_UNDECIDED
    assert verdict["reason"] == layered.PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES


def test_zero_share_warning_is_informational(db_session, hospital_id):
    alert = _peer_alert(db_session, hospital_id, code="WIRE_ZERO_SHARE",
                        peers=[0.0, 0.0, 0.0, 0.0, 10.0, 10.0], current=45.0)
    verdict = _eligibility(db_session, alert, {alert.indicator_code})
    assert verdict["zero_share"] == pytest.approx(4 / 6, abs=1e-4)
    assert verdict["zero_share_warning"] is True
    assert verdict["decision"] == layered.DECISION_ELIGIBLE
    assert verdict["final_band"] == VH


# ── 9. The four-decimal storage boundary (alert id 692) ────────────────────
# The scan stores peer values rounded to 4 decimals. One live row sits exactly
# on the IQR scale's top-band boundary: its stored group already flips what the
# unrounded value would decide. This is the documented tolerance — the policy
# is NOT changed to absorb it.

ALERT_692_PEERS = [28.0, 33.0, 36.0, 40.0, 47.0, 67.0, 70.0, 71.0]
ALERT_692_CURRENT = 175.0


def _gate_for(values):
    return layered.peer_very_high_eligibility(
        VH, values, ALERT_692_CURRENT,
        definition_status=layered.PEER_DEFINITION_COMPLETE, threshold=2.5)


def test_alert_692_stored_group_is_eligible_as_written():
    """Values exactly as alert 692 stores them (code ``2.f``, ownership)."""
    out = _gate_for({str(i): v for i, v in enumerate(ALERT_692_PEERS)})
    assert out["decision"] == layered.DECISION_ELIGIBLE
    assert out["reason"] == layered.PEER_REASON_BOTH_SCALES_SUPPORT
    assert out["mad"] == pytest.approx(13.0)
    assert out["iqr"] == pytest.approx(32.5)


def test_alert_692_sits_on_the_rounding_boundary():
    """+5e-5 (the 4-dp rounding bound) on every value flips the IQR scale.

    Documented, not fixed: the stored evidence is what the row was scored from,
    and the policy reads it as-is.
    """
    shifted = {str(i): v + 5e-5 for i, v in enumerate(ALERT_692_PEERS)}
    out = _gate_for(shifted)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_SCALES_DISAGREE
    assert out["mad_level"] == VH and out["iqr_level"] != VH
    # the same evidence minus the shift is eligible, so the boundary — not the
    # policy — is what changes
    assert _gate_for({str(i): v for i, v in enumerate(ALERT_692_PEERS)})[
        "decision"] == layered.DECISION_ELIGIBLE
    # and the band is identical on both sides
    assert out["band"] == VH


# ── 10. Baseline reconciliation ────────────────────────────────────────────
# Read-only against the live store, and only when that store really holds the
# approved baseline population (1,130 peer rows that are top-band and not
# already refused by an approved cap): a fixture database is skipped explicitly
# rather than asserting a number it cannot contain.

BASELINE_TOTAL = 1130
BASELINE = {
    layered.DECISION_ELIGIBLE: 784,
    layered.DECISION_INELIGIBLE: 0,
    layered.DECISION_UNDECIDED: 134,
    layered.DECISION_INSUFFICIENT_ROBUST_SCALE: 212,
}


def test_baseline_reconciliation_on_the_live_store():
    from collections import Counter

    from app.engine.quality_alerts import cap_thin_peer, cap_zero_spread

    try:
        from app.database import SessionLocal
        db = SessionLocal()
    except Exception:  # pragma: no cover - no database configured
        pytest.skip("no database configured")

    try:
        rows = []
        for alert in db.query(QualityAlert).filter(QualityAlert.active.is_(True)).all():
            if alert.severity != VH:
                continue
            if engine.alert_route(alert.perspective, alert.method) != layered.ROUTE_PEER:
                continue
            evidence = alert.evidence or {}
            base, _ = cap_zero_spread(alert.severity, evidence.get("stats"),
                                      alert.method, engine.stored_series(evidence))
            base, _ = cap_thin_peer(base, alert.peer_count, alert.method)
            if base != VH:
                continue
            rows.append(alert)
        if len(rows) != BASELINE_TOTAL:
            pytest.skip(f"live population is {len(rows)}, not the {BASELINE_TOTAL}-row "
                        "baseline (fixture database)")
        catalog = engine.peer_definition_codes(db)
        counts = Counter()
        for alert in rows:
            verdict = engine.eligibility_assessment(
                alert.severity, stats=(alert.evidence or {}).get("stats"),
                method=alert.method, peer_count=alert.peer_count,
                series=engine.stored_series(alert.evidence),
                current=alert.current_value, perspective=alert.perspective,
                threshold=engine.stored_threshold(alert.evidence),
                **engine.peer_gate_inputs(alert, catalog))
            counts[verdict["decision"]] += 1
            assert verdict["final_band"] == VH
        assert dict(counts) == BASELINE
        assert sum(counts.values()) == BASELINE_TOTAL
    finally:
        db.close()
