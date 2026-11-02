"""Percentage change may not outrank the dispersion-aware score.

A percentage change divides by the baseline, never by the spread, so it used to
score 1.0 (VERY_HIGH) for any doubling — even when the same window's z-score put
the value squarely inside the hospital's normal range. Because a row's band is
the highest applicable layer, that change-only layer outranked the z computed
from the very same numbers: live rows carried VERY_HIGH on a value 0.2 sigma
from its own mean.

Approved policy (app.engine.anomaly.layered.PCT_CHANGE_CAP_POLICY): when the
same series also supports a z-score (>= 2 observations, non-zero sample std),
the percentage-change score is clamped to the score that z produces. Nothing is
hidden — the change is still reported and its pre-cap score is kept beside the
band. No threshold changes: the same configured z threshold grades both.
"""
import pytest

from app.engine.anomaly.layered import (
    LEVEL_VERY_HIGH,
    METHOD_PCT_CHANGE,
    AnalysisSpec,
    Thresholds,
    analyze_layered_entry,
    cap_pct_change,
    compute_historical_layer,
    dispersion_score,
    score_from_pct_change,
    score_from_z,
)
from app.engine.quality_alerts import _history_score, _severity_for_score

# The reported shape (Outlier Diagnostics, 2026-04): a value +93% on the
# previous month that sits inside a year-long 15-38 range. The percentage
# change screams, the distribution shrugs.
JUMPY_SERIES = [28.0, 31.0, 26.0, 34.0, 22.0, 19.0, 38.0, 24.0, 30.0, 15.0]
JUMPY_CURRENT = 29.0

SPEC = AnalysisSpec(analysis_code="MAL", name="Malaria cases",
                    indicator_type="count", minimum_history_period=3)


def test_pct_change_cannot_outrank_the_window_z():
    """+93% on a series that swings like that anyway is not a deviation."""
    layer = compute_historical_layer(SPEC, JUMPY_SERIES, JUMPY_CURRENT,
                                     history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE          # CV < 0.5, stable series
    pct = (JUMPY_CURRENT - JUMPY_SERIES[-1]) / JUMPY_SERIES[-1] * 100.0
    assert pct == pytest.approx(93.33, abs=0.01)

    # The change evidence is preserved, not discarded...
    assert layer.pct_change_score == pytest.approx(score_from_pct_change(pct))
    assert layer.pct_change_score == pytest.approx(0.933, abs=0.001)
    # ...but the band follows the spread: |z| is well under the threshold.
    assert abs(layer.z_score) < 1.0
    expected = dispersion_score(JUMPY_SERIES, JUMPY_CURRENT, 2.5)
    assert layer.score == pytest.approx(expected)
    assert layer.level == "NONE"                    # nowhere near VERY_HIGH


def test_pct_change_cap_keeps_the_row_out_of_the_top_band():
    """The row classification follows the clamped layer, not the change."""
    history = {f"2025-{m:02d}": {"MAL": v}
               for m, v in zip(range(1, 11), JUMPY_SERIES, strict=True)}
    history["2026-04"] = {"MAL": JUMPY_CURRENT}
    result = analyze_layered_entry(
        SPEC, history, "2026-04", [("all", {})], Thresholds(),
        self_id=1,
    )
    assert result.historical.method == METHOD_PCT_CHANGE
    assert result.classification.outlier_level != LEVEL_VERY_HIGH
    # Both layers score the same series, so both are clamped (the raw layer is
    # the numerator view of the same numbers on a count row).
    assert set(result.classification.pct_change_capped) == {"raw", "historical"}
    # A reader must be told why a +93% change is not a confirmed anomaly.
    assert "percentage change is not graded on its own" in (
        result.classification.interpretation)


def test_a_real_jump_still_reaches_the_top_band():
    """A value far outside a tight range is still VERY_HIGH: no false calm."""
    series = [14.0, 15.0, 16.0, 15.0, 14.0]
    layer = compute_historical_layer(SPEC, series, 45.0, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE          # CV < 0.5
    assert layer.pct_change_score is None             # cap did not bite
    assert layer.score == pytest.approx(1.0)
    assert layer.level == LEVEL_VERY_HIGH


def test_cap_is_the_same_z_score_every_other_layer_uses():
    """One z definition: the clamp equals score_from_z, no new threshold."""
    import statistics

    series = [10.0, 11.0, 9.0, 10.0, 12.0, 10.0]
    current = 12.4                                   # z = +2.0 on this window
    z = (current - statistics.fmean(series)) / statistics.stdev(series)
    assert z == pytest.approx(2.0, abs=0.01)
    limit = dispersion_score(series, current, 2.5)
    assert limit == pytest.approx(score_from_z(z, 2.5))
    assert limit == pytest.approx(0.4, abs=0.01)     # MODERATE, not top band
    assert cap_pct_change(0.99, series, current, 2.5) == pytest.approx(limit)


def test_no_spread_to_measure_never_clamps_the_change():
    """Documented carve-outs: no std (1 point) or std == 0 (identical values).

    A single-point window has no scale at all, and a flat window is already
    governed by the no-dispersion cap (HIGH), not by an imaginary z.
    """
    assert cap_pct_change(0.9, [10.0], 20.0, 2.5) == 0.9
    assert cap_pct_change(1.0, [5.0, 5.0, 5.0], 10.0, 2.5) == 1.0
    assert dispersion_score([5.0, 5.0, 5.0], 10.0, 2.5) is None


def test_cap_only_lowers_and_never_promotes():
    """A change score already below the z band is kept as it is."""
    series = [10.0, 11.0, 9.0, 10.0, 12.0, 10.0]
    assert cap_pct_change(0.05, series, 16.0, 2.5) == 0.05


def test_alerts_engine_grades_the_same_row_identically():
    """Quality Alerts and Outlier Diagnostics share the cap, not a copy."""
    alert_score, method, z, stats = _history_score(
        "count", JUMPY_SERIES, JUMPY_CURRENT, 2.5)
    layer = compute_historical_layer(SPEC, JUMPY_SERIES, JUMPY_CURRENT,
                                     history_ok=True)
    assert method == layer.method == METHOD_PCT_CHANGE
    assert alert_score == pytest.approx(layer.score)
    assert z == pytest.approx(layer.z_score)
    # The alert stores the pre-cap change and the z that overruled it
    # (rounded to 4 dp, like every other stored statistic).
    cap = stats["pct_change_capped"]
    assert cap["pct_change_score"] == pytest.approx(0.933, abs=0.001)
    assert cap["score"] == pytest.approx(layer.score, abs=1e-4)
    assert cap["z_score"] == pytest.approx(layer.z_score, abs=1e-4)
    assert cap["policy"]
    assert _severity_for_score(alert_score, 0.25) is None  # below the floor


def test_thresholds_are_unchanged():
    """Same z threshold, same bands: only the grading measurement changed."""
    assert Thresholds().peer_z_threshold == 2.5
    series = [10.0, 11.0, 9.0, 10.0, 12.0, 10.0]
    # |z| == 2 * threshold => 1.0 whether it arrives via z or via the cap.
    assert dispersion_score(series, 21.0, 2.5) == 1.0
