"""VERY_HIGH eligibility: a top-band gate, never a re-grade.

The zero-dispersion and thin-peer caps refuse the top band when a comparison has
NO scale. The robust methods (MAD, IQR) can have a scale that is technically
non-zero and still meaningless for integer counts: at MAD = 1 the top band is a
distance of 4.45 counts at any level, while the same window's z needs 4.5
sigmas. The live store showed 123 of 182 history-only Very High issues losing
the top band once the window's own dispersion was asked, so the band gets a
sufficiency rule — the same question `cap_pct_change` already asks of a
percentage change.

The boundaries this file pins:

* only VERY_HIGH is gated — HIGH and below are returned untouched;
* a refused top band falls to HIGH, never to NONE (a sufficiency rule for one
  band must not report "no deviation" for a measured outlier);
* an unmeasurable window (one point, missing value, zero spread) leaves the
  band alone: unknown is not unsupported;
* no threshold is introduced — the band comes from ``level_for_score`` at the
  configured z threshold.
"""
import pytest

from app.engine.anomaly.layered import (
    ELIGIBLE,
    INELIGIBLE_DISPERSION,
    INSUFFICIENT_DATA,
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_NONE,
    LEVEL_VERY_HIGH,
    NOT_APPLICABLE,
    very_high_eligibility,
)

THRESHOLD = 2.5

# The live case that motivated the gate: 24 is below a peak the hospital
# already produced, and the window's own spread puts it 1.1 sigma from the mean.
SPIKED_WINDOW = [1.0, 30.0, 0.0, 4.0]
SPIKED_CURRENT = 24.0

# A rising, evenly spaced window: z is exactly 4.0 / 5.0 for these currents,
# which straddle the 0.90 band cutoff (4.5 sigma) with no new constant.
LINEAR_WINDOW = [0.0, 1.0, 2.0, 3.0]          # mean 1.5, sample std 1.29099
FOUR_SIGMA = 1.5 + 4.0 * 1.2909944487358056
FIVE_SIGMA = 1.5 + 5.0 * 1.2909944487358056


def test_supported_top_band_keeps_very_high():
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW,
                                    FIVE_SIGMA, THRESHOLD)
    assert verdict["applicable"] is True
    assert verdict["eligible"] is True
    assert verdict["reason"] == ELIGIBLE
    assert verdict["original_band"] == LEVEL_VERY_HIGH
    assert verdict["final_band"] == LEVEL_VERY_HIGH


def test_refused_top_band_falls_to_high_never_lower():
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, SPIKED_WINDOW,
                                    SPIKED_CURRENT, THRESHOLD)
    assert verdict["eligible"] is False
    assert verdict["reason"] == INELIGIBLE_DISPERSION
    # The dispersion band here is NONE (the value is 1.1 sigma from the mean),
    # but the gate refuses ONE band; it does not call the finding normal.
    assert verdict["dispersion_band"] == LEVEL_NONE
    assert verdict["final_band"] == LEVEL_HIGH
    assert verdict["original_band"] == LEVEL_VERY_HIGH
    assert verdict["cap"] == LEVEL_HIGH


def test_four_sigma_is_below_the_top_band_cutoff():
    refused = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW,
                                   FOUR_SIGMA, THRESHOLD)
    allowed = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW,
                                   FIVE_SIGMA, THRESHOLD)
    assert refused["dispersion_band"] == LEVEL_HIGH
    assert refused["final_band"] == LEVEL_HIGH
    assert allowed["final_band"] == LEVEL_VERY_HIGH


@pytest.mark.parametrize("band", [LEVEL_HIGH, LEVEL_MODERATE, LEVEL_LOW,
                                  LEVEL_NONE])
def test_bands_below_the_top_are_never_touched(band):
    verdict = very_high_eligibility(band, SPIKED_WINDOW, SPIKED_CURRENT,
                                    THRESHOLD)
    assert verdict["applicable"] is False
    assert verdict["reason"] == NOT_APPLICABLE
    assert verdict["final_band"] == band


def test_missing_level_is_untouched():
    verdict = very_high_eligibility(None, SPIKED_WINDOW, SPIKED_CURRENT,
                                    THRESHOLD)
    assert verdict["applicable"] is False
    assert verdict["final_band"] is None


def test_one_point_window_cannot_decide_and_leaves_the_band_alone():
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, [4.0], 12.0, THRESHOLD)
    assert verdict["applicable"] is True
    assert verdict["eligible"] is None
    assert verdict["reason"] == INSUFFICIENT_DATA
    assert verdict["final_band"] == LEVEL_VERY_HIGH


def test_missing_current_value_cannot_decide():
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW, None,
                                    THRESHOLD)
    assert verdict["eligible"] is None
    assert verdict["reason"] == INSUFFICIENT_DATA
    assert verdict["final_band"] == LEVEL_VERY_HIGH


def test_zero_spread_window_is_not_this_gate_s_business():
    # A flat window has no sigma, so this gate cannot decide; the zero-spread
    # cap owns that case and still refuses the top band on its own.
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, [5.0, 5.0, 5.0], 9.0,
                                    THRESHOLD)
    assert verdict["eligible"] is None
    assert verdict["final_band"] == LEVEL_VERY_HIGH


def test_configured_threshold_is_the_only_scale_knob():
    # Raising the threshold makes the same deviation score lower: no constant
    # lives in this function, it delegates to score_from_z / level_for_score.
    loose = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW, FOUR_SIGMA,
                                  2.5)
    strict = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW, FOUR_SIGMA,
                                   5.0)
    assert loose["dispersion_score"] > strict["dispersion_score"]
    assert loose["final_band"] == LEVEL_HIGH
    assert strict["final_band"] == LEVEL_HIGH


def test_cap_helper_matches_the_assessment():
    """The cap wrapper reports exactly what the assessment decided.

    Readers adopt the gate through ``cap_very_high_eligibility``, so the two
    must never disagree about whether anything was capped.
    """
    from app.engine.anomaly.layered import cap_very_high_eligibility

    band, provenance = cap_very_high_eligibility(
        LEVEL_VERY_HIGH, SPIKED_WINDOW, SPIKED_CURRENT, THRESHOLD)
    assessment = very_high_eligibility(LEVEL_VERY_HIGH, SPIKED_WINDOW,
                                      SPIKED_CURRENT, THRESHOLD)
    assert band == assessment["final_band"] == LEVEL_HIGH
    assert provenance["reason"] == assessment["reason"]
    assert provenance["resolved_level"] == LEVEL_VERY_HIGH
    assert provenance["capped"] is True


def test_final_band_is_never_below_high_when_refused():
    for current in (1e6, -1e6, 30.0):
        verdict = very_high_eligibility(LEVEL_VERY_HIGH, LINEAR_WINDOW,
                                        current, THRESHOLD)
        if verdict["eligible"] is False:
            assert verdict["final_band"] == LEVEL_HIGH
        else:
            assert verdict["final_band"] == LEVEL_VERY_HIGH
