"""Layered outlier engine: scoring core (Task 7), layers (Tasks 8-10),
classification (Task 11), end-to-end scenarios (Task 12) — spec sections 5/6/11."""
import math

import pytest

from app.engine.anomaly.classify import (
    TYPE_CLINICAL_INVESTIGATION_REQUIRED,
    TYPE_HISTORICAL_ANOMALY,
    TYPE_NORMAL,
    TYPE_PEER_ANOMALY,
    TYPE_POSSIBLE_DATA_ENTRY_ERROR,
    TYPE_RATE_ANOMALY,
    TYPE_RAW_VALUE_ANOMALY,
    TYPE_VOLUME_DRIVEN_ANOMALY,
    InterpretationNumbers,
    build_interpretation,
    classify_layered,
)
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
    analyze_layered_entry,
    build_analysis_specs,
    build_peer_tiers,
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
    run_layered_analysis,
    score_from_iqr,
    score_from_mad,
    score_from_pct_change,
    score_from_trend,
    score_from_z,
    select_method,
    should_persist,
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


# ── Classification (spec §6) ───────────────────────────────────────────────

def _classify(**kw):
    defaults = dict(spec=_rate_spec(), raw_score=None, rate_score=None,
                    hist_score=None, volume_score=None, peer_score=None,
                    den_ok=True, history_ok=True)
    defaults.update(kw)
    return classify_layered(**defaults)


def test_classification_rule1_insufficient_history_is_first_match():
    c = _classify(history_ok=False, raw_score=0.95, hist_score=0.95)
    assert c.rule_number == 1
    assert c.outlier_type == TYPE_NORMAL
    assert c.outlier_level == "NONE"
    assert c.method == METHOD_INSUFFICIENT_HISTORY
    assert c.investigation_required is False
    assert c.investigation_route == "none"
    assert "Not enough history" in c.interpretation
    assert "3 prior months" in c.interpretation


def test_classification_rule2_possible_data_entry_error():
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=1300.0,
                  rate_method="pct_change")
    assert c.rule_number == 2
    assert c.outlier_type == TYPE_POSSIBLE_DATA_ENTRY_ERROR
    assert c.investigation_required is True
    assert c.investigation_route == "data_quality"
    assert c.outlier_level == "VERY_HIGH"
    assert c.method == "pct_change"
    assert "data-entry error" in c.interpretation


def test_classification_rule2_magnitude_guard_boundary():
    base = dict(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                volume_score=0.10)
    assert _classify(**base, change_percent=300.0).rule_number == 2
    assert _classify(**base, change_percent=299.9).rule_number == 4
    assert _classify(**base, change_percent=None).rule_number == 4


def test_classification_rule4_clinical_when_guard_fails():
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=125.0)
    assert c.rule_number == 4
    assert c.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert c.investigation_required is True
    assert c.investigation_route == "clinical"


def test_classification_rule3_volume_driven():
    c = _classify(raw_score=0.95, rate_score=0.40, hist_score=0.30,
                  volume_score=0.95)
    assert c.rule_number == 3
    assert c.outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY
    assert c.investigation_required is False    # spec: only rules 2/4/6/7
    assert c.investigation_route == "contextual"


def test_classification_rule5_historical_anomaly():
    c = _classify(raw_score=0.30, rate_score=0.30, hist_score=0.85,
                  volume_score=0.10, peer_score=0.20, hist_method="iqr")
    assert c.rule_number == 5
    assert c.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert c.investigation_route == "contextual"
    assert c.method == "iqr"


def test_classification_rule6_peer_anomaly_never_data_error():
    c = _classify(raw_score=0.20, hist_score=0.10, peer_score=0.95)
    assert c.rule_number == 6
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.investigation_required is True
    assert c.method == METHOD_PEER_ZSCORE
    assert "case mix" in c.interpretation
    assert "data-entry error" not in c.interpretation   # never a data-error claim


def test_classification_rule7_peer_plus_history_combined():
    c = _classify(raw_score=0.20, hist_score=0.60, peer_score=0.95)
    assert c.rule_number == 7
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.investigation_required is True
    assert "and from its own recent history" in c.interpretation


def test_classification_rule8_raw_value_anomaly():
    c = _classify(raw_score=0.55, hist_score=0.30, peer_score=0.20)
    assert c.rule_number == 8
    assert c.outlier_type == TYPE_RAW_VALUE_ANOMALY
    assert c.outlier_level == "MODERATE"
    assert c.investigation_route == "contextual"


def test_classification_rule9_rate_anomaly():
    c = _classify(rate_score=0.55, raw_score=0.30, hist_score=0.30,
                  volume_score=0.10)
    assert c.rule_number == 9
    assert c.outlier_type == TYPE_RATE_ANOMALY
    assert c.outlier_level == "MODERATE"


def test_classification_rule10_normal_when_nothing_exceeds():
    c = _classify(raw_score=0.10, rate_score=0.10, hist_score=0.10,
                  volume_score=0.05, peer_score=0.10)
    assert c.rule_number == 10
    assert c.outlier_type == TYPE_NORMAL
    assert c.outlier_level == "NONE"
    assert c.investigation_required is False
    assert c.investigation_route == "none"
    assert "No layer exceeded its threshold" in c.interpretation


def test_classification_count_row_volume_rule_never_fires():
    c = _classify(spec=_count_spec(), raw_score=0.95, hist_score=0.40,
                  peer_score=0.30)              # volume_score stays None
    assert c.rule_number == 8                   # rule 3 needs volume >= HIGH
    assert c.outlier_type == TYPE_RAW_VALUE_ANOMALY
    assert c.outlier_level == "VERY_HIGH"


def test_classification_small_denominator_caps_rate_based_types():
    spec = _rate_spec(minimum_denominator=10)
    c = _classify(spec=spec, raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=125.0, denominator=5)
    assert c.rule_number == 4
    assert c.outlier_level == "LOW"             # capped from VERY_HIGH
    assert "small denominator (5 < 10)" in c.interpretation
    assert "level capped at LOW" in c.interpretation


def test_classification_non_rate_type_not_capped_by_small_denominator():
    spec = _rate_spec(minimum_denominator=10)
    c = _classify(spec=spec, raw_score=0.20, rate_score=0.10, hist_score=0.30,
                  volume_score=0.10, peer_score=0.95, denominator=5)
    assert c.rule_number == 6                   # PEER_ANOMALY: not rate-based
    assert c.outlier_level == "VERY_HIGH"        # cap does not apply


def test_classification_missing_denominator_disclosed_not_computable():
    c = _classify(den_ok=False, raw_score=0.30, denominator=None)
    assert c.rule_number == 10
    assert c.outlier_type == TYPE_NORMAL         # computable layers are low
    assert "denominator missing or zero" in c.interpretation
    assert "not computable" in c.interpretation


def test_interpretation_composed_from_actual_numbers():
    numbers = InterpretationNumbers(
        raw_value=25.0, previous_value=10.0, raw_change_percent=150.0,
        rate=375.0, denominator=900.0, denominator_change_percent=11.0,
        historical_mean=26.7, historical_change_percent=1300.0,
        peer_mean=12.1, peer_count=18)
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=1300.0, numbers=numbers)
    text = c.interpretation
    assert "+1300% above baseline mean 26.7" in text
    assert "rate 375.0%" in text
    assert "peer average 12.1 across 18 hospitals" in text
    assert "C-section rate 25 vs 10 (+150% vs previous month)" in text
    assert "denominator 900 (+11% vs previous)" in text


def test_build_interpretation_below_baseline_direction():
    numbers = InterpretationNumbers(historical_mean=50.0,
                                    historical_change_percent=-40.0)
    text = build_interpretation(_rate_spec(), TYPE_NORMAL, 10, den_ok=True,
                                numbers=numbers)
    assert "+40% below baseline mean 50" in text


# ── End-to-end engine scenarios (spec §11) ────────────────────────────────

MONTHS5 = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
CURRENT = "2026-06"


def _history(prior_values, current, code="5"):
    h = {m: {code: float(v)} for m, v in zip(MONTHS5, prior_values, strict=True)}
    h[CURRENT] = {code: float(current)}
    return h


def _rate_history(prior_pairs, current_pair, num="5", den="2"):
    h = {m: {num: float(n), den: float(d)} for m, (n, d) in zip(MONTHS5, prior_pairs, strict=True)}
    n, d = current_pair
    cur = {num: float(n)}
    if d is not None:
        cur[den] = float(d)
    h[CURRENT] = cur
    return h


def _entry(spec, history, tiers=None, self_id=1, thresholds=None):
    return analyze_layered_entry(spec, history, CURRENT,
                                 tiers or [("all", {})],
                                 thresholds or Thresholds(), self_id=self_id)


def test_scenario1_normal_value_is_normal_with_low_scores():
    result = _entry(_count_spec(), _history([10] * 5, 10))
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.classification.outlier_level == "NONE"
    assert result.raw.score == 0.0
    assert result.historical.score == 0.0
    assert result.raw.method == METHOD_PCT_CHANGE
    assert result.history_ok is True


def test_scenario2_raw_value_outlier_records_high_score_and_method():
    result = _entry(_count_spec(), _history([10] * 5, 25))
    assert level_gte(result.raw.level, "HIGH")
    assert result.raw.method == METHOD_PCT_CHANGE
    assert result.raw.value == 25.0
    assert result.raw.previous == 10.0
    assert result.raw.change_percent == 150.0


def test_scenario3_rate_outlier_with_stable_denominator():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 1000)))
    assert level_gte(result.rate.level, "HIGH")
    assert result.rate.rate == pytest.approx(2.5)
    assert result.volume is not None
    assert not level_gte(result.volume.level, "MODERATE")   # stable denominator


def test_scenario4_high_numerator_and_denominator_is_volume_driven():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 2000)))
    assert result.classification.outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY
    assert "volume" in result.classification.interpretation.lower()
    assert level_gte(result.raw.level, "HIGH")
    assert level_gte(result.volume.level, "HIGH")


def test_scenario5_high_numerator_stable_denominator_is_clinical():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 1000)))
    assert result.classification.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert result.classification.investigation_route == "clinical"
    assert result.classification.investigation_required is True


def test_scenario6_small_denominator_caps_level_and_keeps_row():
    spec = _rate_spec(minimum_denominator=10)
    result = _entry(spec, _rate_history([(1, 5)] * 5, (2, 5)))
    assert result.classification.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert result.classification.outlier_level == "LOW"
    assert "small denominator (5 < 10)" in result.classification.interpretation
    assert "confidence lowered" in result.classification.interpretation
    assert should_persist(result) is True


def test_scenario7_historical_outlier_with_normal_peer():
    tiers = [("type:general", {1: 25.0, 2: 24.0, 3: 25.0, 4: 26.0})]
    result = _entry(_count_spec(), _history([10] * 5, 25), tiers=tiers)
    assert result.classification.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert result.peer.score is not None
    assert not level_gte(result.peer.level, "MODERATE")     # peers near self


def test_scenario8_peer_outlier_never_says_data_error():
    tiers = [("type:general", {1: 10.0, 2: 30.0, 3: 30.0})]
    result = _entry(_count_spec(), _history([10] * 5, 10), tiers=tiers)
    assert result.classification.outlier_type == TYPE_PEER_ANOMALY
    assert result.classification.rule_number == 6
    text = result.classification.interpretation.lower()
    assert "differs from peers" in text
    assert "error" not in text


def test_scenario9_missing_denominator_rate_layers_not_computable():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, None)))
    assert result.rate.rate is None
    assert result.rate.score is None
    assert result.volume is not None
    assert result.volume.den_ok is False
    assert result.volume.score is None
    assert result.historical.score is None
    assert result.classification.outlier_type != TYPE_RATE_ANOMALY
    assert "not computable" in result.classification.interpretation


def test_scenario10_zero_denominator_no_division_by_zero():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 0)))
    assert result.volume.denominator == 0.0
    assert result.volume.den_ok is False
    assert result.rate.rate is None and result.rate.score is None
    assert "not computable" in result.classification.interpretation


def test_scenario11_missing_historical_data_insufficient_history():
    result = _entry(_count_spec(), {CURRENT: {"5": 10.0}})
    assert result.history_ok is False
    assert result.classification.rule_number == 1
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.classification.outlier_level == "NONE"
    assert result.classification.method == METHOD_INSUFFICIENT_HISTORY
    assert result.raw.method == METHOD_INSUFFICIENT_HISTORY
    assert result.raw.score is None
    assert should_persist(result) is True


def test_scenario12_first_months_below_minimum_history():
    history = {"2026-05": {"5": 10.0}, CURRENT: {"5": 25.0}}
    result = _entry(_count_spec(), history)
    assert result.history_ok is False
    assert result.classification.rule_number == 1
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.raw.score is None            # not judged, never an outlier
    assert result.raw.value == 25.0            # value still reported


def test_scenario13_rare_event_indicator_uses_mad_not_z():
    history = {m: {"5": float(v)} for m, v in zip(MONTHS5, [0, 1, 0, 1, 0], strict=True)}
    history[CURRENT] = {"5": 1.0}
    result = _entry(_count_spec(), history)
    assert result.raw.method == METHOD_ROLLING_MEDIAN_MAD
    assert result.historical.method == METHOD_ROLLING_MEDIAN_MAD
    assert result.raw.score == 1.0             # MAD 0, value != median
    assert result.classification.method == METHOD_ROLLING_MEDIAN_MAD


def test_entry_splits_current_month_from_history():
    h = _history([10] * 5, 10)
    del h[CURRENT]
    result = _entry(_count_spec(), h)
    assert result.raw.value is None            # no current-month data
    assert result.history_ok is True           # 5 priors still counted
    assert should_persist(result) is False


def test_scenario16_peer_fallback_tier_order_and_null_without_peers():
    unit_values = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    attrs = {
        1: {"type": 1, "ownership": 7, "governorate": 100},
        2: {"type": 2, "ownership": 7, "governorate": 100},
        3: {"type": 2, "ownership": 8, "governorate": 101},
        4: {"type": None, "ownership": None, "governorate": None},
    }
    spec = _count_spec()
    tiers = build_peer_tiers(spec, 1, unit_values, attrs)
    assert [n for n, _ in tiers] == ["type:1", "ownership:7", "governorate:100", "all"]
    # typed tiers each hold only self + 1 other (<2 others) -> "all" fallback
    layer = compute_peer_layer(spec, 1, 10.0, tiers)
    assert layer.tier == "all"
    assert layer.peer_count == 3
    assert layer.peer_mean == pytest.approx(30.0)

    # first sufficient tier wins: type has 2 others (mean 25, not all's 30)
    attrs2 = {1: {"type": 1}, 2: {"type": 1}, 3: {"type": 1}, 4: {"type": 2}}
    tiers2 = build_peer_tiers(spec, 1, unit_values, attrs2)
    assert [n for n, _ in tiers2] == ["type:1", "all"]
    layer2 = compute_peer_layer(spec, 1, 10.0, tiers2)
    assert layer2.tier == "type:1"
    assert layer2.peer_mean == pytest.approx(25.0)

    # hospital with no attributes typed -> typed tiers skipped entirely
    tiers3 = build_peer_tiers(spec, 9, {9: 10.0}, {9: {"type": 1}})
    assert [n for n, _ in tiers3] == ["type:1", "all"]
    layer3 = compute_peer_layer(spec, 9, 10.0, tiers3)
    assert layer3.score is None and layer3.peer_count == 0   # <2 everywhere

    disabled = _count_spec(peer_comparison_enabled=False)
    assert build_peer_tiers(disabled, 1, unit_values, attrs) == []


def test_run_layered_analysis_one_result_per_spec_for_analyzed_hospital():
    spec = _count_spec()
    history = _history([10] * 5, 10)
    peers = {1: history, 2: {CURRENT: {"5": 10.0}}, 3: {CURRENT: {"5": 12.0}}}
    attrs = {hid: {"type": 1, "ownership": 1, "governorate": 1} for hid in (1, 2, 3)}
    results = run_layered_analysis([spec], history, CURRENT, 1, peers, attrs,
                                   Thresholds())
    assert len(results) == 1
    r = results[0]
    assert r.classification.outlier_type == TYPE_NORMAL
    assert r.peer.peer_count == 2
    assert r.peer.peer_mean == pytest.approx(11.0)


def test_build_analysis_specs_combines_indicators_and_rate_config(db_session):
    specs = build_analysis_specs(db_session)
    codes = [s.analysis_code for s in specs]
    assert "0" not in codes                    # synthetic label excluded
    assert "rate_cs" in codes                  # rate_config seed present
    rate = next(s for s in specs if s.analysis_code == "rate_cs")
    assert rate.is_rate
    assert rate.numerator_codes and rate.denominator_codes
    count = next(s for s in specs if not s.is_rate)
    assert count.indicator_id is not None
    assert not count.denominator_codes
