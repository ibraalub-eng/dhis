"""Layered outlier engine: scoring core (Task 7), layers (Tasks 8-10),
classification (Task 11), end-to-end scenarios (Task 12) — spec sections 5/6/11."""
import math

import pytest

from app.engine.anomaly.layered import (
    LEVELS,
    METHOD_AUTO,
    METHOD_INSUFFICIENT_HISTORY,
    METHOD_IQR,
    METHOD_PCT_CHANGE,
    METHOD_PEER_ZSCORE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_TREND_DEVIATION,
    METHOD_ZSCORE,
    RARE_EVENT_MEAN_MAX,
    AnalysisSpec,
    Thresholds,
    coefficient_of_variation,
    compute_historical_layer,
    compute_peer_layer,
    compute_rate_layer,
    compute_raw_layer,
    compute_volume_layer,
    denominator_analysis_value,
    is_small_denominator,
    level_for_score,
    level_gte,
    max_level,
    median,
    percent_change,
    prior_months,
    quartiles,
    rate_analysis_value,
    raw_analysis_value,
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


# ── Input helpers (Task 8) ─────────────────────────────────────────────────

def test_prior_months_sorted_and_strictly_before_current():
    history = {"2026-04": {}, "2026-02": {}, "2026-01": {}, "2026-03": {}}
    assert prior_months(history, "2026-03") == ["2026-01", "2026-02"]
    assert prior_months(history, "2026-01") == []
    assert prior_months({}, "2026-03") == []


def test_analysis_value_helpers_split_rate_and_count_rows():
    rate_spec = AnalysisSpec(analysis_code="rate_cs", name="C-section rate",
                             indicator_type="percentage", numerator_codes=("5",),
                             denominator_codes=("2",), rate_multiplier=100.0, unit="%")
    count_spec = AnalysisSpec(analysis_code="5", name="C-sections")
    values = {"5": 80.0, "2": 300.0, "6": 250.0}
    assert raw_analysis_value(rate_spec, values) == 80.0          # numerator
    assert rate_analysis_value(rate_spec, values) == pytest.approx(80 / 300 * 100)
    assert denominator_analysis_value(rate_spec, values) == 300.0
    assert raw_analysis_value(count_spec, values) == 80.0         # the element itself
    assert rate_analysis_value(count_spec, values) is None
    assert denominator_analysis_value(count_spec, values) is None
    assert raw_analysis_value(count_spec, {"2": 1}) is None


# ── Layer 1: raw value (spec §5) ──────────────────────────────────────────

def _count_spec(**kw):
    return AnalysisSpec(analysis_code="5", name="C-sections", **kw)


def test_raw_layer_normal_series_is_none_band():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=10.0, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE      # CV = 0 < 0.5
    assert layer.score == 0.0
    assert layer.level == "NONE"
    assert layer.previous == 10.0
    assert layer.change_percent == 0.0
    assert layer.value == 10.0


def test_raw_layer_jump_is_very_high_and_records_method():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=25.0, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE
    assert layer.change_percent == 150.0
    assert layer.score == 1.0                    # |150%| / 100 capped at 1
    assert layer.level == "VERY_HIGH"


def test_raw_layer_boundary_score_maps_to_moderate():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=15.0, history_ok=True)
    assert layer.score == 0.5                    # +50% / 100
    assert layer.level == "MODERATE"             # 0.50 is not < 0.50


def test_raw_layer_insufficient_history_is_not_applicable():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 11.0], current=12.0,
                              history_ok=False)
    assert layer.score is None
    assert layer.level is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
    assert layer.value == 12.0 and layer.previous == 11.0   # values still reported


def test_raw_layer_volatile_series_uses_iqr():
    layer = compute_raw_layer(_count_spec(),
                              prior=[10.0, 100.0, 12.0, 90.0, 15.0, 80.0],
                              current=12.0, history_ok=True)
    assert layer.method == METHOD_IQR
    assert layer.score == 0.0                    # inside tukey fences


def test_raw_layer_missing_current_value():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0],
                              current=None, history_ok=True)
    assert layer.score is None and layer.value is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_raw_layer_zscore_method_and_shared_threshold():
    spec = _count_spec(outlier_method="zscore")
    layer = compute_raw_layer(spec, prior=[10.0, 12.0, 14.0, 16.0], current=20.0,
                              history_ok=True)
    assert layer.method == METHOD_ZSCORE
    # mean 13, sample stdev sqrt(20/3) => z = 7 / sqrt(20/3); score = z / (2 * 2.5)
    assert layer.score == pytest.approx(7 / math.sqrt(20 / 3) / 5.0)
    assert layer.level == "MODERATE"


# ── Layer 3: historical baseline (spec §5) ────────────────────────────────

def test_historical_layer_window_stats_and_pct_change_vs_mean():
    layer = compute_historical_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                                     current=25.0, history_ok=True)
    assert layer.mean == 10.0 and layer.median == 10.0
    assert layer.std == 0.0
    assert layer.z_score is None                  # std 0 -> no z in the DB
    assert layer.change_percent == 150.0          # vs baseline mean
    assert layer.method == METHOD_PCT_CHANGE
    assert layer.score == 1.0
    assert layer.level == "VERY_HIGH"
    assert layer.history_ok is True


def test_historical_layer_mean_zero_change_is_none():
    layer = compute_historical_layer(
        _count_spec(outlier_method="zscore"), prior=[0.0, 0.0, 0.0], current=5.0,
        history_ok=True)
    assert layer.mean == 0.0
    assert layer.change_percent is None           # never divide by zero
    assert layer.z_score is None                  # std 0
    assert layer.score == 1.0                     # std 0 but value != mean


def test_historical_layer_rare_event_uses_mad_path():
    spec = _count_spec()                          # count, mean < 10 => MAD
    layer = compute_historical_layer(spec, prior=[0.0, 1.0, 0.0, 1.0, 0.0],
                                     current=5.0, history_ok=True)
    assert layer.method == METHOD_ROLLING_MEDIAN_MAD
    assert layer.median == 0.0
    assert layer.score == 1.0                     # MAD 0, value != median
    layer_zero = compute_historical_layer(spec, prior=[0.0, 1.0, 0.0, 1.0, 0.0],
                                          current=0.0, history_ok=True)
    assert layer_zero.score == 0.0                # MAD 0, value == median


def test_historical_layer_insufficient_history():
    layer = compute_historical_layer(_count_spec(), prior=[10.0, 11.0],
                                     current=12.0, history_ok=False)
    assert layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
    assert layer.history_ok is False
    assert layer.mean == 10.5                     # stats still reported


def test_historical_layer_disabled_config_keeps_stats_but_no_score():
    spec = _count_spec(historical_enabled=False)
    layer = compute_historical_layer(spec, prior=[10.0, 10.0, 10.0],
                                     current=40.0, history_ok=True)
    assert layer.score is None                    # layer suppressed by config
    assert layer.history_ok is True               # entry waives rule 1 for it
    assert layer.mean == 10.0
    assert layer.change_percent == 300.0


def test_historical_trend_deviation_blended_with_window_score():
    spec = _count_spec(outlier_method="trend_deviation")
    layer = compute_historical_layer(spec, prior=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
                                     current=40.0, history_ok=True)
    assert layer.method == METHOD_TREND_DEVIATION
    assert layer.trend_projected == pytest.approx(16.0)   # Theil-Sen slope 1, intercept 10
    assert layer.trend_residual_std == pytest.approx(0.0)
    assert layer.score == 1.0                     # max(window, trend); trend = 1


def test_historical_trend_deviation_falls_back_below_six_points():
    spec = _count_spec(outlier_method="trend_deviation")
    layer = compute_historical_layer(spec, prior=[10.0, 11.0, 12.0],
                                     current=12.5, history_ok=True)
    assert layer.method != METHOD_TREND_DEVIATION
    assert layer.trend_projected is None
    assert layer.score is not None and layer.score <= 1.0


# ── Layer 2: rate (spec §5) ───────────────────────────────────────────────

def _rate_spec(**kw):
    return AnalysisSpec(analysis_code="rate_cs", name="C-section rate",
                        indicator_type="percentage",
                        numerator_codes=("5",), denominator_codes=("2",),
                        rate_multiplier=100.0, unit="%", **kw)


def test_rate_layer_null_for_count_rows():
    layer = compute_rate_layer(_count_spec(), prior_rates=[10.0, 11.0],
                               current_rate=12.0, history_ok=True)
    assert layer.rate is None and layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_rate_layer_normal_series_is_none_band():
    layer = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7, 26.7, 26.7],
                               current_rate=26.7, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE       # CV = 0 < 0.5
    assert layer.score == 0.0
    assert layer.level == "NONE"
    assert layer.rate == 26.7


def test_rate_layer_jump_is_very_high():
    layer = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7, 26.7, 26.7],
                               current_rate=375.0, history_ok=True)
    assert layer.score == 1.0                      # +1300% capped at 1
    assert layer.level == "VERY_HIGH"


def test_rate_layer_still_reports_rate_when_history_insufficient():
    gated = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7],
                               current_rate=40.0, history_ok=False)
    assert gated.rate == 40.0                      # value stored for the row
    assert gated.score is None
    assert gated.method == METHOD_INSUFFICIENT_HISTORY
    missing = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7],
                                 current_rate=None, history_ok=True)
    assert missing.rate is None and missing.score is None
    assert missing.method == METHOD_INSUFFICIENT_HISTORY


def test_rate_layer_respects_configured_zscore_method():
    layer = compute_rate_layer(_rate_spec(outlier_method="zscore"),
                               prior_rates=[20.0, 22.0, 24.0, 26.0],
                               current_rate=30.0, history_ok=True)
    assert layer.method == METHOD_ZSCORE
    # mean 23, stdev sqrt(20/3) ~= 2.5819889 => z ~= 2.7110886; score = z / (2 * 2.5)
    assert layer.score == pytest.approx(7 / math.sqrt(20 / 3) / 5.0)


# ── Layer 4: volume / denominator (spec §5) ───────────────────────────────

def test_volume_layer_is_none_for_count_rows():
    assert compute_volume_layer(_count_spec(), prior_denominators=[900.0],
                                current_denominator=1000.0) is None


def test_volume_layer_missing_and_zero_denominator_are_not_ok():
    missing = compute_volume_layer(_rate_spec(), prior_denominators=[900.0],
                                   current_denominator=None)
    assert missing.den_ok is False and missing.score is None
    assert missing.denominator is None
    zero = compute_volume_layer(_rate_spec(), prior_denominators=[900.0],
                                current_denominator=0.0)
    assert zero.den_ok is False and zero.score is None
    assert zero.denominator == 0.0                 # actual value reported


def test_volume_layer_stable_denominator_is_none_band():
    layer = compute_volume_layer(_rate_spec(), prior_denominators=[900.0],
                                 current_denominator=1000.0)
    assert layer.den_ok is True
    assert layer.previous == 900.0
    assert layer.change_percent == pytest.approx(11.1111, rel=1e-4)
    assert layer.score == pytest.approx(1.0 / 9.0)   # 11.111...% / 100
    assert layer.level == "NONE"


def test_volume_layer_exploding_denominator_is_very_high():
    layer = compute_volume_layer(_rate_spec(), prior_denominators=[100.0],
                                 current_denominator=2000.0)
    assert layer.change_percent == 1900.0
    assert layer.score == 1.0                      # +1900% capped at 1
    assert layer.level == "VERY_HIGH"


def test_volume_layer_without_previous_denominator():
    layer = compute_volume_layer(_rate_spec(), prior_denominators=[],
                                 current_denominator=900.0)
    assert layer.den_ok is True                    # denominator itself is fine
    assert layer.previous is None
    assert layer.change_percent is None and layer.score is None


def test_small_denominator_guard_predicate():
    strict = _rate_spec(minimum_denominator=10)
    assert is_small_denominator(strict, 5) is True
    assert is_small_denominator(strict, 10) is False   # equal passes the guard
    assert is_small_denominator(strict, 900) is False
    assert is_small_denominator(strict, None) is False
    dormant = _rate_spec()                         # minimum_denominator None
    assert is_small_denominator(dormant, 0) is False   # guard dormant


# ── Layer 5: peer comparison (spec §5) ────────────────────────────────────

def test_peer_layer_excludes_self_and_scores_z():
    spec = _count_spec()
    tiers = [("type:general", {1: 8.0, 2: 12.0, 3: 16.0})]     # 3 = self
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.method == METHOD_PEER_ZSCORE
    assert layer.tier == "type:general"
    assert layer.peer_count == 2
    # others [8, 12]: mean 10, stdev sqrt(8) ~= 2.8284271, z = 6/2.8284271 ~= 2.1213203
    # score = z / (2 * 2.5) ~= 0.4242641 -> LOW
    assert layer.score == pytest.approx(0.4242640687)
    assert layer.level == "LOW"
    assert layer.peer_mean == 10.0


def test_peer_layer_first_sufficient_tier_wins():
    spec = _count_spec()
    tiers = [
        ("type:general", {1: 10.0, 2: 10.0, 3: 16.0}),        # 2 others -> wins
        ("all", {1: 100.0, 2: 100.0, 3: 16.0}),                # never consulted
    ]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.tier == "type:general"
    assert layer.peer_mean == 10.0
    assert layer.peer_count == 2
    assert layer.score == 1.0                   # zero spread, value != mean
    assert layer.level == "VERY_HIGH"


def test_peer_layer_skips_thin_tiers():
    spec = _count_spec()
    tiers = [
        ("type:general", {3: 16.0}),                               # self only
        ("ownership:ministry", {1: 9.0, 3: 16.0}),                 # 1 other
        ("governorate:cairo", {1: 8.0, 2: 12.0, 3: 16.0}),         # 2 others
    ]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.tier == "governorate:cairo"
    assert layer.peer_count == 2
    assert layer.score == pytest.approx(0.4242640687)


def test_peer_layer_no_sufficient_tier_is_null():
    spec = _count_spec()
    tiers = [("all", {1: 10.0, 3: 16.0})]                          # 1 other only
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.score is None and layer.level is None
    assert layer.peer_mean is None and layer.peer_count == 0
    assert layer.tier is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_peer_layer_disabled_by_config():
    spec = _count_spec(peer_comparison_enabled=False)
    tiers = [("all", {1: 8.0, 2: 12.0, 3: 16.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.score is None and layer.peer_count == 0
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_peer_layer_zero_spread_at_mean_is_zero_score():
    spec = _count_spec()
    tiers = [("all", {1: 10.0, 2: 10.0, 3: 10.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=10.0, peer_tiers=tiers)
    assert layer.score == 0.0
    assert layer.level == "NONE"


def test_peer_layer_missing_current_value():
    spec = _count_spec()
    tiers = [("all", {1: 8.0, 2: 12.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=None, peer_tiers=tiers)
    assert layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
