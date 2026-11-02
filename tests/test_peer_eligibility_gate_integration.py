# -*- coding: utf-8 -*-
"""Rule B + definition gate through ``quality_alerts.top_band_gate`` — step 2.

Every peer alert goes through the SAME gate the history perspective uses, so
these tests pin the integration rather than the policy internals:

* the definition gate runs BEFORE any robust-scale decision, so a comparison
  whose indicator definition cannot be established is never eligible;
* a catalog-only definition is enough to grade the comparison but is marked and
  never claims verified group comparability;
* the five decisions pass through the gate unchanged, ``ineligible`` included;
* the band, the score and the stored severity NEVER move — Rule B only labels
  the evidence, it does not re-grade the alert;
* a caller that supplies no peer evidence keeps the previous answer verbatim;
* the zero-share and denominator-review flags are informational only.

Nothing here reads or writes the database.
"""
import pytest

from app.engine import quality_alerts
from app.engine.anomaly import layered

VH = layered.LEVEL_VERY_HIGH
GATE = quality_alerts.top_band_gate

BOTH_SUPPORT_PEERS = [10, 10, 11, 12, 12]
BOTH_SUPPORT_CURRENT = 19.0
BOTH_REFUSE_PEERS = [10, 12, 14, 16]
BOTH_REFUSE_CURRENT = 10.6
MIXED_PEERS = [0, 1, 2, 3, 4]
MIXED_CURRENT = 7.0
ONE_SCALE_PEERS = [0, 0, 0, 0, 10, 10]
ONE_SCALE_SUPPORTS_CURRENT = 45.0
ONE_SCALE_REFUSES_CURRENT = 30.0
DEGENERATE_PEERS = [5, 5, 5, 5, 5]
DEGENERATE_CURRENT = 9.0

SELF_CONTAINED = {"formula": "numerator / denominator",
                  "numerator": 3, "denominator": 10,
                  "catalog_resolved": False}
CATALOG_ONLY = {"catalog_resolved": True}
COMPLETE = {"formula": "numerator / denominator", "numerator": 3,
            "denominator": 10, "catalog_resolved": True}


def _peer(peers, current, definition=COMPLETE, **kwargs):
    """The gate exactly as a peer reader would call it."""
    return GATE(VH, method=layered.METHOD_PEER_ZSCORE, perspective="all",
                current=current, peer_values=peers, peer_definition=definition,
                **kwargs)


# ── the legacy answer is preserved when no evidence is supplied ────────────

def test_peer_without_evidence_keeps_the_previous_answer():
    level, provenance, assessment = GATE(
        VH, method=layered.METHOD_PEER_ZSCORE, perspective="all", current=19.0)
    assert level == VH
    assert provenance is None
    assert assessment["decision"] == layered.DECISION_UNDECIDED
    assert assessment["reason"] == "PEER_POLICY"
    assert assessment["route"] == layered.ROUTE_PEER
    assert assessment["policy"] == layered.TOP_BAND_ROUTE_POLICY[layered.ROUTE_PEER]


def test_history_route_is_untouched_by_the_peer_arguments():
    level, _provenance, assessment = GATE(
        VH, method="zscore", perspective="history", series=[], current=12.0,
        peer_values=BOTH_SUPPORT_PEERS, peer_definition=COMPLETE)
    assert level == VH
    assert assessment["route"] == layered.ROUTE_HISTORY
    assert assessment["reason"] in (layered.REASON_NO_WINDOW,
                                    layered.REASON_NO_CURRENT,
                                    layered.PEER_REASON_CURRENT_VALUE_MISSING)


# ── the definition gate precedes every scale ───────────────────────────────

def test_missing_definition_precedes_a_supporting_group():
    level, provenance, assessment = _peer(BOTH_SUPPORT_PEERS,
                                          BOTH_SUPPORT_CURRENT,
                                          definition=None)
    assert level == VH
    assert provenance is None
    assert assessment["decision"] == layered.DECISION_UNDECIDED
    assert assessment["reason"] == layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED
    assert assessment["eligible"] is None
    assert assessment["definition_status"] == layered.PEER_DEFINITION_NOT_ESTABLISHABLE


def test_unclosable_definition_never_becomes_eligible():
    shapes = [
        (BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT),       # scales support
        (ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT),    # one scale supports
        (BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT),         # scales refuse
        (MIXED_PEERS, MIXED_CURRENT),                     # scales disagree
        (DEGENERATE_PEERS, DEGENERATE_CURRENT),           # no robust scale
    ]
    for peers, current in shapes:
        for definition in (None, {"formula": "", "numerator": None,
                                  "denominator": None, "catalog_resolved": False},
                           layered.PEER_DEFINITION_NOT_ESTABLISHABLE):
            _level, _provenance, assessment = _peer(peers, current,
                                                    definition=definition)
            assert assessment["decision"] == layered.DECISION_UNDECIDED
            assert assessment["reason"] == (
                layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED)
            assert assessment["eligible"] is not True


def test_catalog_only_definition_grades_but_stays_marked():
    _level, _provenance, assessment = _peer(BOTH_SUPPORT_PEERS,
                                            BOTH_SUPPORT_CURRENT,
                                            definition=CATALOG_ONLY)
    assert assessment["decision"] == layered.DECISION_ELIGIBLE
    assert assessment["definition_status"] == layered.PEER_DEFINITION_CATALOG_ONLY
    assert assessment["group_comparability_status"] == (
        layered.GROUP_COMPARABILITY_NOT_VERIFIED)


def test_group_comparability_is_never_claimed_verified():
    for definition in (SELF_CONTAINED, CATALOG_ONLY, COMPLETE):
        _level, _provenance, assessment = _peer(BOTH_SUPPORT_PEERS,
                                                BOTH_SUPPORT_CURRENT,
                                                definition=definition)
        assert assessment["group_comparability_status"] == (
            layered.GROUP_COMPARABILITY_NOT_VERIFIED)


@pytest.mark.parametrize("evidence,expected", [
    ({"formula": "a/b", "numerator": 3, "denominator": 10,
      "catalog_resolved": True}, layered.PEER_DEFINITION_COMPLETE),
    ({"formula": "a/b", "numerator": 3, "denominator": 10,
      "catalog_resolved": False}, layered.PEER_DEFINITION_SELF_CONTAINED),
    ({"formula": "a/b", "numerator": 3, "denominator": 0,
      "catalog_resolved": False}, layered.PEER_DEFINITION_NOT_ESTABLISHABLE),
    ({"formula": "   ", "numerator": 3, "denominator": 10,
      "catalog_resolved": False}, layered.PEER_DEFINITION_NOT_ESTABLISHABLE),
    ({"catalog_resolved": True}, layered.PEER_DEFINITION_CATALOG_ONLY),
    ({}, layered.PEER_DEFINITION_NOT_ESTABLISHABLE),
])
def test_definition_tiers(evidence, expected):
    assert layered.peer_definition_status(**evidence) == expected


def test_zero_denominator_is_not_a_usable_ratio():
    status = layered.peer_definition_status(formula="a/b", numerator=3,
                                            denominator=0)
    assert status == layered.PEER_DEFINITION_NOT_ESTABLISHABLE
    assert layered.peer_definition_established(status) is False


# ── the five decisions pass through the gate ──────────────────────────────

@pytest.mark.parametrize("peers,current,decision,reason", [
    (BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT,
     layered.DECISION_ELIGIBLE, layered.PEER_REASON_BOTH_SCALES_SUPPORT),
    (ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT,
     layered.DECISION_ELIGIBLE, layered.PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS),
    (BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT,
     layered.DECISION_INELIGIBLE, layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE),
    (MIXED_PEERS, MIXED_CURRENT,
     layered.DECISION_UNDECIDED, layered.PEER_REASON_SCALES_DISAGREE),
    (ONE_SCALE_PEERS, ONE_SCALE_REFUSES_CURRENT,
     layered.DECISION_UNDECIDED, layered.PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES),
    (DEGENERATE_PEERS, DEGENERATE_CURRENT,
     layered.DECISION_INSUFFICIENT_ROBUST_SCALE, layered.PEER_REASON_NO_ROBUST_SCALE),
])
def test_every_peer_decision_through_the_gate(peers, current, decision, reason):
    _level, _provenance, assessment = _peer(peers, current)
    assert assessment["decision"] == decision
    assert assessment["reason"] == reason
    assert assessment["peer_eligibility"]["reason"] == reason


def test_ineligible_does_not_lower_the_band_or_the_severity():
    level, provenance, assessment = _peer(BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT)
    assert level == VH
    assert provenance is None
    assert assessment["final_band"] == VH
    assert assessment["decision"] == layered.DECISION_INELIGIBLE


@pytest.mark.parametrize("peers,current", [
    (BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT),
    (BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT),
    (MIXED_PEERS, MIXED_CURRENT),
    (ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT),
    (DEGENERATE_PEERS, DEGENERATE_CURRENT),
])
def test_the_gate_never_moves_a_peer_band(peers, current):
    level, provenance, assessment = _peer(peers, current)
    assert level == VH
    assert assessment["final_band"] == VH
    assert assessment["original_band"] == VH
    assert provenance is None


def test_stored_band_survives_the_effective_severity_reader():
    """The reader every screen counts with does not change for a peer row."""
    assert quality_alerts.effective_severity(
        VH, method=layered.METHOD_PEER_ZSCORE, peer_count=6) == VH
    assert quality_alerts.severity_cap(
        VH, method=layered.METHOD_PEER_ZSCORE, peer_count=6) is None


def test_below_the_top_band_is_not_judged():
    level, provenance, assessment = GATE(
        layered.LEVEL_HIGH, method=layered.METHOD_PEER_ZSCORE, perspective="all",
        current=BOTH_SUPPORT_CURRENT, peer_values=BOTH_SUPPORT_PEERS,
        peer_definition=COMPLETE)
    assert level == layered.LEVEL_HIGH
    assert provenance is None
    assert assessment["decision"] == layered.DECISION_NOT_APPLICABLE


def test_thin_peer_group_is_not_applicable_and_keeps_the_band():
    level, _provenance, assessment = _peer([10, 12, 14], 20.0)
    assert level == VH
    assert assessment["decision"] == layered.DECISION_NOT_APPLICABLE
    assert assessment["reason"] == layered.PEER_REASON_THIN_PEER_GROUP


# ── informational flags, threshold, idempotency ───────────────────────────

def test_zero_share_flag_is_informational_only():
    _level, _provenance, assessment = _peer(ONE_SCALE_PEERS,
                                            ONE_SCALE_SUPPORTS_CURRENT)
    assert assessment["zero_share_warning"] is True
    assert assessment["decision"] == layered.DECISION_ELIGIBLE
    assert assessment["final_band"] == VH


def test_denominator_review_flag_is_informational_only():
    _level, _provenance, base = _peer(BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT)
    _level, _provenance, flagged = _peer(BOTH_SUPPORT_PEERS,
                                         BOTH_SUPPORT_CURRENT,
                                         denominator_review=True)
    assert flagged["denominator_review"] is True
    assert base["denominator_review"] is False
    assert flagged["decision"] == base["decision"]
    assert flagged["final_band"] == base["final_band"] == VH


def test_threshold_is_the_existing_gate_threshold():
    _level, _provenance, default = _peer(BOTH_SUPPORT_PEERS,
                                         BOTH_SUPPORT_CURRENT)
    assert default["threshold"] == 2.5
    _level, _provenance, configured = _peer(BOTH_SUPPORT_PEERS,
                                            BOTH_SUPPORT_CURRENT,
                                            threshold=3.5)
    assert configured["threshold"] == 3.5


def test_applying_the_gate_twice_changes_nothing():
    first = _peer(MIXED_PEERS, MIXED_CURRENT)
    second = GATE(first[0], method=layered.METHOD_PEER_ZSCORE,
                  perspective="all", current=MIXED_CURRENT,
                  peer_values=MIXED_PEERS, peer_definition=COMPLETE)
    assert first[0] == second[0] == VH
    assert first[2]["decision"] == second[2]["decision"]
    assert first[2]["reason"] == second[2]["reason"]
