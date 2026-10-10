"""Layered outlier engine: scoring core (Task 7), layers (Tasks 8-10),
classification (Task 11), end-to-end scenarios (Task 12) — spec sections 5/6/11."""
import math

import pytest

from app.engine.anomaly.layered import (
    LEVELS,
    METHOD_AUTO,
    METHOD_IQR,
    METHOD_PCT_CHANGE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_ZSCORE,
    RARE_EVENT_MEAN_MAX,
    AnalysisSpec,
    Thresholds,
    coefficient_of_variation,
    level_for_score,
    level_gte,
    max_level,
    median,
    percent_change,
    quartiles,
    score_from_iqr,
    score_from_mad,
    score_from_pct_change,
    score_from_trend,
    score_from_z,
    select_method,
    std,
)

# ── Severity bands (spec §5 table: <0.25 NONE, <0.50 LOW, <0.75 MODERATE,
#    <0.90 HIGH, >=0.90 VERY_HIGH) ─────────────────────────────────────────

@pytest.mark.parametrize("score,level", [
    (0.0, "NONE"), (0.24, "NONE"), (0.2499, "NONE"),
    (0.25, "LOW"), (0.49, "LOW"), (0.4999, "LOW"),
    (0.50, "MODERATE"), (0.74, "MODERATE"),
    (0.75, "HIGH"), (0.89, "HIGH"),
    (0.90, "VERY_HIGH"), (1.0, "VERY_HIGH"),
])
def test_band_cutoffs(score, level):
    assert level_for_score(score) == level


def test_level_for_score_none_and_negative():
    assert level_for_score(None) is None
    assert level_for_score(-0.5) == "NONE"


def test_levels_ordering_and_helpers():
    assert LEVELS == ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH")
    assert level_gte("HIGH", "MODERATE") is True
    assert level_gte("LOW", "MODERATE") is False
    assert level_gte("HIGH", "HIGH") is True
    assert level_gte(None, "LOW") is False          # None never satisfies a minimum
    assert max_level([None, None]) == "NONE"
    assert max_level([]) == "NONE"
    assert max_level([None, "LOW", "HIGH", "MODERATE"]) == "HIGH"


def test_score_builders_match_spec_formulae():
    # z-based: |z| = threshold => 0.5; |z| = 2*threshold => 1.0
    assert score_from_z(2.5, 2.5) == 0.5
    assert score_from_z(5.0, 2.5) == 1.0
    assert score_from_z(-3.0, 2.5) == pytest.approx(0.6)
    assert score_from_z(0.0, 2.5) == 0.0
    # percentage change: 100% => 1.0
    assert score_from_pct_change(100.0) == 1.0
    assert score_from_pct_change(-150.0) == 1.0
    assert score_from_pct_change(25.0) == 0.25
    # rolling median + MAD: 3 * 1.4826 * MAD scaling; zero MAD edge cases
    assert score_from_mad(10.0, 5.0, 2.0) == pytest.approx(5.0 / (3 * 1.4826 * 2))
    assert score_from_mad(5.0, 5.0, 0.0) == 0.0
    assert score_from_mad(7.0, 5.0, 0.0) == 1.0
    # IQR tukey fences: q1=10 q3=20 => fences -5 / 35, 2*IQR = 20
    assert score_from_iqr(15.0, 10.0, 20.0) == 0.0                    # inside fences
    assert score_from_iqr(40.0, 10.0, 20.0) == pytest.approx(5.0 / 20.0)
    assert score_from_iqr(55.0, 10.0, 20.0) == 1.0                    # distance 20
    assert score_from_iqr(35.0, 10.0, 20.0) == 0.0                    # exactly on fence
    # trend deviation: |actual-projected| / (2 * residual_std)
    assert score_from_trend(12.0, 8.0, 2.0) == 1.0
    assert score_from_trend(9.0, 8.0, 2.0) == 0.25
    assert score_from_trend(8.0, 8.0, 0.0) == 0.0
    assert score_from_trend(9.0, 8.0, 0.0) == 1.0


def test_statistics_helpers():
    assert median([3, 1, 2]) == 2
    assert std([1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert std([1.0]) is None
    assert quartiles([1, 2, 3, 4]) == (1.75, 2.5, 3.25)   # inclusive method
    assert quartiles([7]) == (7.0, 7.0, 7.0)
    assert coefficient_of_variation([0.0, 0.0]) == math.inf
    assert coefficient_of_variation([100.0, 105.0, 98.0]) < 0.5
    assert percent_change(150, 100) == 50.0
    assert percent_change(50, 100) == -50.0
    assert percent_change(10, 0) is None
    assert percent_change(10, None) is None
    assert percent_change(None, 10) is None


# ── Method selection (spec §5 Layer 1 + rare-event rule) ──────────────────

def test_select_method_explicit_config_wins():
    assert select_method("iqr", [1.0, 2.0], "count") == METHOD_IQR
    assert select_method("pct_change", [], "rate") == METHOD_PCT_CHANGE
    assert select_method(None, [1.0, 2.0], "count") == METHOD_ZSCORE


def test_select_method_auto_chain():
    assert RARE_EVENT_MEAN_MAX == 10.0
    # rare-event counts (low mean): rolling median + MAD, never plain z
    rare = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    assert select_method(METHOD_AUTO, rare, "count") == METHOD_ROLLING_MEDIAN_MAD
    # identical series is NOT rare-event as a rate type -> falls to iqr (n>=6)
    assert select_method(METHOD_AUTO, rare, "rate") == METHOD_IQR
    # stable series (CV < 0.5, n >= 3) -> pct_change
    stable = [100.0, 105.0, 98.0, 103.0]
    assert select_method(METHOD_AUTO, stable, "count") == METHOD_PCT_CHANGE
    # volatile series with >= 6 points -> iqr
    volatile6 = [10.0, 100.0, 12.0, 90.0, 15.0, 80.0]
    assert select_method(METHOD_AUTO, volatile6, "rate") == METHOD_IQR
    # volatile series with < 6 points -> zscore fallback
    assert select_method(METHOD_AUTO, [10.0, 90.0], "rate") == METHOD_ZSCORE
    assert select_method(METHOD_AUTO, [10.0, 90.0, 15.0], "rate") == METHOD_ZSCORE
    # empty series -> zscore (scored None by the layer functions later)
    assert select_method(METHOD_AUTO, [], "rate") == METHOD_ZSCORE


def test_analysis_spec_defaults_and_rate_flag():
    spec = AnalysisSpec(analysis_code="5", name="C-sections")
    assert spec.is_rate is False
    assert spec.indicator_type == "count"
    assert spec.minimum_history_period == 3
    assert spec.outlier_method == METHOD_AUTO
    rate_spec = AnalysisSpec(
        analysis_code="rate_cs", name="C-section rate",
        indicator_type="percentage", numerator_codes=("5",),
        denominator_codes=("2",), rate_multiplier=100.0, unit="%",
    )
    assert rate_spec.is_rate is True


def test_thresholds_default_matches_appconfig():
    assert Thresholds().peer_z_threshold == 2.5
