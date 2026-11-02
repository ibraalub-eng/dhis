# -*- coding: utf-8 -*-
"""Rule B for PEER top-band eligibility — the isolated function, step 1.

The policy is not wired into any read path yet. These tests pin the contract of
``layered.peer_very_high_eligibility`` on its own:

* a zero MAD is NOT a supporting measurement — the builders' ``1.0`` fallback is
  never used as evidence, and a valid IQR alone can still support the band;
* a refusal needs two usable scales that both refuse, so the single-scale
  refusal stays ``undecided``;
* a degenerate group is ``insufficient_robust_scale`` — a fifth decision, kept
  outside the eligible / ineligible / undecided counts;
* missing values, a missing current value and an unclosable definition are
  distinct reasons, never a refusal;
* the band, the threshold and every informational flag are returned untouched.

Nothing here reads or writes the database.
"""
import pytest

from app.engine.anomaly import layered

VH = layered.LEVEL_VERY_HIGH
F = layered.peer_very_high_eligibility

# Two usable scales, both at VERY_HIGH: MAD = 1, IQR = 2, current far outside.
BOTH_SUPPORT_PEERS = [10, 10, 11, 12, 12]
BOTH_SUPPORT_CURRENT = 19.0

# Two usable scales, both below VERY_HIGH.
BOTH_REFUSE_PEERS = [10, 12, 14, 16]
BOTH_REFUSE_CURRENT = 10.6

# MAD supports (score clamped at 1.0), IQR is inside its fences -> 0.
MIXED_PEERS = [0, 1, 2, 3, 4]
MIXED_CURRENT = 7.0

# MAD = 0, IQR = 10 -> the IQR is the only usable scale.
ONE_SCALE_PEERS = [0, 0, 0, 0, 10, 10]
ONE_SCALE_SUPPORTS_CURRENT = 45.0     # distance 20 >= 1.8 x IQR
ONE_SCALE_REFUSES_CURRENT = 30.0      # distance 5 -> MODERATE at best

# No spread at all: MAD = 0 and IQR = 0.
DEGENERATE_PEERS = [5, 5, 5, 5, 5]
DEGENERATE_CURRENT = 9.0


def test_two_usable_scales_supporting_is_eligible():
    out = F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT)
    assert out["decision"] == layered.DECISION_ELIGIBLE
    assert out["reason"] == layered.PEER_REASON_BOTH_SCALES_SUPPORT
    assert out["eligible"] is True
    assert out["applicable"] is True
    assert out["mad_usable"] and out["iqr_usable"]


def test_two_usable_scales_refusing_is_ineligible():
    out = F(VH, BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT)
    assert out["decision"] == layered.DECISION_INELIGIBLE
    assert out["reason"] == layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE
    assert out["eligible"] is False


def test_disagreement_stays_undecided():
    out = F(VH, MIXED_PEERS, MIXED_CURRENT)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_SCALES_DISAGREE
    assert out["eligible"] is None
    # the MAD really does support while the IQR refuses
    assert out["mad_level"] == VH
    assert out["iqr_level"] != VH


def test_zero_mad_is_not_a_supporting_measurement():
    """MAD = 0 must not become score 1.0 (the builder fallback)."""
    out = F(VH, ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT)
    assert out["mad"] == 0
    assert out["mad_usable"] is False
    assert out["mad_level"] is None
    assert out["iqr_usable"] is True


def test_single_usable_scale_supporting_is_eligible():
    """MAD = 0 + a valid IQR that supports -> eligible on the IQR alone."""
    out = F(VH, ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT)
    assert out["decision"] == layered.DECISION_ELIGIBLE
    assert out["reason"] == layered.PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS
    assert out["eligible"] is True


def test_single_usable_scale_refusing_is_not_a_refusal():
    """Rule B: one scale cannot refuse, so this stays undecided."""
    out = F(VH, ONE_SCALE_PEERS, ONE_SCALE_REFUSES_CURRENT)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES
    assert out["eligible"] is None


def test_degenerate_group_is_its_own_decision():
    out = F(VH, DEGENERATE_PEERS, DEGENERATE_CURRENT)
    assert out["decision"] == layered.DECISION_INSUFFICIENT_ROBUST_SCALE
    assert out["decision"] != layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_NO_ROBUST_SCALE
    assert out["eligible"] is None
    assert out["applicable"] is True
    assert out["band"] == VH


def test_definition_failure_wins_before_any_scale():
    out = F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT,
            definition_status="not_establishable")
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED
    assert out["eligible"] is None


@pytest.mark.parametrize("values", [None, [], "not-a-group", 42])
def test_missing_group_has_its_own_reason(values):
    out = F(VH, values, 12.0)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_NO_STORED_PEER_VALUES
    assert out["eligible"] is None


def test_missing_current_value_is_not_a_refusal():
    out = F(VH, BOTH_SUPPORT_PEERS, None)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_CURRENT_VALUE_MISSING
    assert out["band"] == VH


def test_too_few_finite_values_is_its_own_reason():
    out = F(VH, [5.0, float("nan"), float("inf")], 12.0)
    assert out["decision"] == layered.DECISION_UNDECIDED
    assert out["reason"] == layered.PEER_REASON_INSUFFICIENT_PEER_VALUES
    assert out["finite_peer_count"] == 1


def test_non_finite_values_are_filtered_not_imputed():
    cleaned = F(VH, ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT)
    dirty = F(VH, ONE_SCALE_PEERS + [float("nan"), float("inf"),
                                     float("-inf")],
              ONE_SCALE_SUPPORTS_CURRENT)
    assert dirty["finite_peer_count"] == len(ONE_SCALE_PEERS)
    assert (dirty["decision"], dirty["reason"], dirty["band"]) == (
        cleaned["decision"], cleaned["reason"], cleaned["band"])


def test_thin_group_is_not_applicable_and_leaves_the_band_alone():
    out = F(VH, [10, 12, 14], 20.0)
    assert out["decision"] == layered.DECISION_NOT_APPLICABLE
    assert out["reason"] == layered.PEER_REASON_THIN_PEER_GROUP
    assert out["band"] == VH


def test_below_the_top_band_is_not_applicable():
    out = F(layered.LEVEL_HIGH, DEGENERATE_PEERS, DEGENERATE_CURRENT)
    assert out["decision"] == layered.DECISION_NOT_APPLICABLE
    assert out["reason"] == layered.NOT_APPLICABLE


@pytest.mark.parametrize("peers,current", [
    (BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT),
    (BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT),
    (MIXED_PEERS, MIXED_CURRENT),
    (ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT),
    (ONE_SCALE_PEERS, ONE_SCALE_REFUSES_CURRENT),
    (DEGENERATE_PEERS, DEGENERATE_CURRENT),
])
def test_the_band_is_never_lowered(peers, current):
    out = F(VH, peers, current)
    assert out["band"] == VH
    assert out["original_band"] == VH


def test_zero_share_flag_is_informational_only():
    flagged = F(VH, ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT)
    assert flagged["zero_share"] == pytest.approx(4 / 6, abs=1e-4)
    assert flagged["zero_share_warning"] is True
    assert flagged["decision"] == layered.DECISION_ELIGIBLE

    clean = F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT)
    assert clean["zero_share"] == 0
    assert clean["zero_share_warning"] is False
    assert clean["decision"] == layered.DECISION_ELIGIBLE


def test_denominator_review_flag_is_informational_only():
    base = F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT)
    flagged = F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT,
                denominator_review=True)
    assert flagged["denominator_review"] is True
    assert base["denominator_review"] is False
    assert flagged["decision"] == base["decision"]


def test_threshold_comes_from_the_existing_gate_and_is_reported():
    assert F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT)["threshold"] == 2.5
    assert F(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT,
             threshold=3.5)["threshold"] == 3.5


def test_evaluation_is_idempotent():
    first = F(VH, MIXED_PEERS, MIXED_CURRENT)
    second = F(VH, MIXED_PEERS, MIXED_CURRENT)
    assert first == second


def test_rule_b_never_uses_rule_a_refusal_label():
    """``ALL_AVAILABLE_SCALES_REFUSE`` (Rule A) must never be emitted here."""
    forbidden = "ALL_AVAILABLE_SCALES_REFUSE"
    for peers, current in ((BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT),
                           (BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT),
                           (MIXED_PEERS, MIXED_CURRENT),
                           (ONE_SCALE_PEERS, ONE_SCALE_REFUSES_CURRENT),
                           (DEGENERATE_PEERS, DEGENERATE_CURRENT)):
        assert F(VH, peers, current)["reason"] != forbidden


def test_every_result_carries_exactly_one_known_reason():
    known = {
        layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED,
        layered.PEER_REASON_THIN_PEER_GROUP,
        layered.PEER_REASON_NO_STORED_PEER_VALUES,
        layered.PEER_REASON_CURRENT_VALUE_MISSING,
        layered.PEER_REASON_INSUFFICIENT_PEER_VALUES,
        layered.PEER_REASON_NO_ROBUST_SCALE,
        layered.PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES,
        layered.PEER_REASON_SCALES_DISAGREE,
        layered.PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS,
        layered.PEER_REASON_BOTH_SCALES_SUPPORT,
        layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE,
        layered.NOT_APPLICABLE,
    }
    decisions = {
        layered.DECISION_ELIGIBLE: {layered.PEER_REASON_BOTH_SCALES_SUPPORT,
                                    layered.PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS},
        layered.DECISION_INELIGIBLE: {layered.PEER_REASON_BOTH_USABLE_SCALES_REFUSE},
        layered.DECISION_UNDECIDED: {layered.PEER_REASON_SCALES_DISAGREE,
                                     layered.PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES,
                                     layered.PEER_REASON_DEFINITION_NOT_ESTABLISHED,
                                     layered.PEER_REASON_NO_STORED_PEER_VALUES,
                                     layered.PEER_REASON_CURRENT_VALUE_MISSING,
                                     layered.PEER_REASON_INSUFFICIENT_PEER_VALUES},
        layered.DECISION_INSUFFICIENT_ROBUST_SCALE: {layered.PEER_REASON_NO_ROBUST_SCALE},
        layered.DECISION_NOT_APPLICABLE: {layered.PEER_REASON_THIN_PEER_GROUP,
                                          layered.NOT_APPLICABLE},
    }
    cases = [(VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT, {}),
             (VH, BOTH_REFUSE_PEERS, BOTH_REFUSE_CURRENT, {}),
             (VH, MIXED_PEERS, MIXED_CURRENT, {}),
             (VH, ONE_SCALE_PEERS, ONE_SCALE_SUPPORTS_CURRENT, {}),
             (VH, ONE_SCALE_PEERS, ONE_SCALE_REFUSES_CURRENT, {}),
             (VH, DEGENERATE_PEERS, DEGENERATE_CURRENT, {}),
             (VH, [10, 12, 14], 20.0, {}),
             (VH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT,
              {"definition_status": "not_establishable"}),
             (layered.LEVEL_HIGH, BOTH_SUPPORT_PEERS, BOTH_SUPPORT_CURRENT, {})]
    for level, peers, current, kwargs in cases:
        out = F(level, peers, current, **kwargs)
        assert out["reason"] in known
        assert out["reason"] in decisions[out["decision"]]
