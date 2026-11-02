"""Layered outlier analysis engine — scoring core (design spec 2026-10-08 §5).

Pure functions and constants; no DB access, no I/O, no app imports at module
level. The pipeline (app/engine/pipeline.py) gathers history/peers and
persists results; classification lives in app/engine/anomaly/classify.py.

Every layer maps a deviation to a 0-1 score which maps to a severity band:
<0.25 NONE | <0.50 LOW | <0.75 MODERATE | <0.90 HIGH | >=0.90 VERY_HIGH.
"""
import math
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from scipy import stats as scipy_stats

from app.engine.comparison_policy import (
    MIN_PEERS_DEFAULT,
    HistoryPolicy,
    PeerPolicy,
)

if TYPE_CHECKING:
    from app.engine.anomaly.classify import Classification

# ── Severity bands (spec §5) ───────────────────────────────────────────────
LEVEL_NONE = "NONE"
LEVEL_LOW = "LOW"
LEVEL_MODERATE = "MODERATE"
LEVEL_HIGH = "HIGH"
LEVEL_VERY_HIGH = "VERY_HIGH"
LEVELS = (LEVEL_NONE, LEVEL_LOW, LEVEL_MODERATE, LEVEL_HIGH, LEVEL_VERY_HIGH)
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
# (exclusive upper bound, level): a score maps to the first bound it is <.
BAND_CUTOFFS: Tuple[Tuple[float, str], ...] = (
    (0.25, LEVEL_NONE),
    (0.50, LEVEL_LOW),
    (0.75, LEVEL_MODERATE),
    (0.90, LEVEL_HIGH),
    (math.inf, LEVEL_VERY_HIGH),
)

# ── Detection methods (spec §3.1 outlier_method enum) ─────────────────────
METHOD_AUTO = "auto"
METHOD_ZSCORE = "zscore"
METHOD_IQR = "iqr"
METHOD_ROLLING_MEDIAN_MAD = "rolling_median_mad"
METHOD_PCT_CHANGE = "pct_change"
METHOD_TREND_DEVIATION = "trend_deviation"
METHOD_PEER_ZSCORE = "peer_zscore"
METHOD_INSUFFICIENT_HISTORY = "insufficient_history"

# ── Method-selection constants (spec §5 "Thresholds": no new knobs) ───────
CV_MAX = 0.5                     # auto -> pct_change when CV below this
MIN_IQR_POINTS = 6               # auto -> iqr needs at least this many points
MIN_TREND_POINTS = 6             # trend_deviation / Theil-Sen need this many
RARE_EVENT_MEAN_MAX = 10.0       # count mean below this: MAD, never plain z
MAD_SCALE = 1.4826               # normal-consistent MAD -> sigma
DEFAULT_MINIMUM_HISTORY = 3      # Indicator.minimum_history_period default
PEER_Z_THRESHOLD_DEFAULT = 2.5   # AppConfig zscore_threshold default


@dataclass(frozen=True)
class Thresholds:
    """Runtime thresholds handed to the engine by the orchestrator."""
    peer_z_threshold: float = PEER_Z_THRESHOLD_DEFAULT
    # Shared peer-eligibility floor (app.engine.comparison_policy).
    min_peers: int = MIN_PEERS_DEFAULT


@dataclass(frozen=True)
class AnalysisSpec:
    """One analysis unit: a count-indicator row or a synthetic rate row.

    Built by build_analysis_specs() (Task 12) from Indicator rows (count)
    plus load_rate_specs() (rate). analysis_code is the
    layered_outlier_results row key.
    """
    analysis_code: str
    name: str
    indicator_type: str = "count"        # count | rate | ratio | percentage
    indicator_id: Optional[int] = None
    numerator_codes: Tuple[str, ...] = ()
    denominator_codes: Tuple[str, ...] = ()
    rate_multiplier: float = 1.0
    unit: str = ""
    minimum_denominator: Optional[float] = None   # None = guard dormant
    minimum_history_period: int = DEFAULT_MINIMUM_HISTORY
    outlier_method: str = METHOD_AUTO
    historical_enabled: bool = True
    peer_comparison_enabled: bool = True

    @property
    def is_rate(self) -> bool:
        return bool(self.denominator_codes)


# ── Statistics helpers ─────────────────────────────────────────────────────

def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


def median(values: Sequence[float]) -> float:
    return statistics.median(values)


def std(values: Sequence[float]) -> Optional[float]:
    """Sample std (ddof=1); None when fewer than 2 points."""
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def mad(values: Sequence[float]) -> float:
    """Median absolute deviation (unscaled)."""
    center = statistics.median(values)
    return statistics.median([abs(v - center) for v in values])


def quartiles(values: Sequence[float]) -> Tuple[float, float, float]:
    """(q1, median, q3), inclusive (numpy-percentile-compatible) method."""
    if not values:
        raise ValueError("quartiles() of empty series")
    if len(values) == 1:
        v = float(values[0])
        return v, v, v
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q1, q2, q3


def coefficient_of_variation(values: Sequence[float]) -> float:
    if not values:
        return math.inf
    m = statistics.fmean(values)
    if m == 0:
        return math.inf          # mean 0 => never pct_change
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / abs(m)


def percent_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Signed % change against |previous|; None when previous missing/zero."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


# ── Score builders (spec §5 "Score construction per method") ──────────────

def score_from_z(z: float, threshold: float) -> float:
    """|z| == threshold => 0.5 (MODERATE); |z| == 2*threshold => 1.0."""
    if threshold <= 0:
        threshold = PEER_Z_THRESHOLD_DEFAULT
    return min(1.0, abs(z) / (2.0 * threshold))


def score_from_pct_change(pct: float) -> float:
    return min(1.0, abs(pct) / 100.0)


# ── Percentage-change cap (dispersion-aware grading) ──────────────────────
# A percentage change divides by the BASELINE, never by the spread: doubling a
# value scores 1.0 (VERY_HIGH) whether the hospital has been flat for a year or
# routinely swings by 80% month to month. A row's band is the highest
# applicable layer, so a change-only layer used to outrank the z-score computed
# from the very same window — stored rows carried VERY_HIGH on a value 0.2 sigma
# from its own mean (live data: 875 of 1,244 history alerts were at a band above
# what their own z supported, 513 of them VERY_HIGH).
#
# Policy: when the same series also supports a z-score (>= 2 observations and a
# non-zero sample std), the percentage-change score is CLAMPED to the score that
# z produces. The dispersion-aware view grades the magnitude; the change itself
# is still reported (values, %, score before the cap, z) but it cannot claim a
# band the window's own spread does not support.
#
# Not applied when there is no spread to measure: std == 0 is governed by the
# zero-dispersion cap below (which already refuses the top band), and a 1-point
# window has no scale at all — there the raw change is the only evidence there
# is and is kept unchanged. Layer 4 (volume) is out of scope on purpose: it
# scores the denominator change, which has no dispersion-based sibling layer on
# the row, and answers a different question (did reporting volume collapse?).
PCT_CHANGE_CAP_POLICY = (
    "A percentage change ignores the spread of the series it is measured "
    "against, so it is clamped to the level the same window's z-score "
    "supports; the change itself is still reported"
)


def dispersion_score(series: Sequence[float], current: Optional[float],
                     threshold: float) -> Optional[float]:
    """The score this series' z-score would produce; None when it has no scale.

    One z definition for the whole engine (mean + sample std, ddof=1), so the
    cap and the zscore branch of the scorer can never disagree.
    """
    if current is None:
        return None
    values = [float(v) for v in series if v is not None]
    if len(values) < 2:
        return None
    sigma = std(values)
    if sigma in (None, 0):
        return None
    return score_from_z((float(current) - mean(values)) / sigma, threshold)


def cap_pct_change(score: Optional[float], series: Sequence[float],
                   current: Optional[float],
                   threshold: float) -> Optional[float]:
    """Clamp a percentage-change score to the dispersion-aware score.

    ``threshold`` is the same configured z threshold every other score uses, so
    no threshold changes — only which measurement grades the magnitude.
    """
    if score is None:
        return None
    limit = dispersion_score(series, current, threshold)
    return score if limit is None else min(float(score), limit)


def score_from_mad(value: float, center: float, mad_value: float) -> float:
    """Scaled by 3 * 1.4826 * MAD; MAD == 0 => 1.0 unless value == center."""
    if mad_value == 0:
        return 0.0 if value == center else 1.0
    return min(1.0, abs(value - center) / (3.0 * MAD_SCALE * mad_value))


def score_from_iqr(value: float, q1: float, q3: float) -> float:
    """Tukey-fence distance over 2*IQR; 0 inside the fences."""
    iqr = q3 - q1
    if iqr == 0:
        return 0.0 if q1 <= value <= q3 else 1.0
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    if value < lower:
        distance = lower - value
    elif value > upper:
        distance = value - upper
    else:
        return 0.0
    return min(1.0, distance / (2.0 * iqr))


def score_from_trend(actual: float, projected: float,
                      residual_std: Optional[float]) -> float:
    if residual_std is None or residual_std <= 0:
        return 0.0 if actual == projected else 1.0
    return min(1.0, abs(actual - projected) / (2.0 * residual_std))


# ── Bands ──────────────────────────────────────────────────────────────────

# ── Detection verdict ──────────────────────────────────────────────────────

# A level at or above this band means "an outlier was detected" (|z| > the
# configured threshold maps to MODERATE and up). The Quality Score applies a
# stricter floor of its own (HIGH) for its penalty; detection and penalty are
# two questions answered from the same stored levels.
OUTLIER_LEVEL_MIN = LEVEL_MODERATE


def is_detection_outlier(level: Optional[str]) -> bool:
    """Single rule for "is this row an outlier?" — used by the pipeline, the
    Quality report and the legacy AnomalyResult projection."""
    return LEVEL_RANK.get(level or LEVEL_NONE, 0) >= LEVEL_RANK[OUTLIER_LEVEL_MIN]


def level_for_score(score: Optional[float]) -> Optional[str]:
    """Band for a 0-1 score; None => layer not applicable (stays NULL)."""
    if score is None:
        return None
    s = max(0.0, float(score))
    for upper, name in BAND_CUTOFFS:
        if s < upper:
            return name
    return LEVEL_VERY_HIGH


def level_rank(level: Optional[str]) -> Optional[int]:
    return LEVEL_RANK.get(level) if level else None


def level_gte(level: Optional[str], minimum: str) -> bool:
    """None-safe: a not-applicable layer never satisfies a minimum."""
    rank = LEVEL_RANK.get(level) if level else None
    return rank is not None and rank >= LEVEL_RANK[minimum]


def max_level(levels: Iterable[Optional[str]]) -> str:
    """Highest applicable level; NONE when nothing is applicable."""
    best = LEVEL_NONE
    for level in levels:
        if level is not None and LEVEL_RANK[level] > LEVEL_RANK[best]:
            best = level
    return best


# ── Zero-dispersion (degenerate comparison) policy ────────────────────────
# A layer whose score is built FROM the spread — z, MAD, IQR, trend residual
# — has no scale when ITS OWN divisor is 0, so the builders' documented
# fallback is 1.0 ("maximal deviation"). That fallback is the right RAW
# evidence signal but not a measured magnitude. The divisor is the method's,
# not always the standard deviation: MAD and IQR can be 0 while the series
# still has a std (see spread_used), so the test must ask the method.
# Quality Alerts already caps such findings at HIGH; this module is the single
# implementation both engines share, so Diagnostics cannot promote a
# zero-dispersion comparison to VERY_HIGH while Alerts refuses to.
#
# The cap is applied to a LAYER band, never to the whole row: a degenerate
# peer group must not suppress a level another (measured) layer earned.
ZERO_SPREAD_LEVEL_CAP = LEVEL_HIGH
ZERO_SPREAD_POLICY = (
    "The comparison has no measurable spread for the method used, so the "
    f"deviation cannot be graded; the level is capped at {ZERO_SPREAD_LEVEL_CAP}"
)
# Scores built by dividing by the spread. pct_change divides by the baseline
# (measurable even when the series is flat); volume uses pct_change too.
DISPERSION_METHODS = frozenset({
    METHOD_ZSCORE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_IQR,
    METHOD_PEER_ZSCORE,
    METHOD_TREND_DEVIATION,
})


def spread_used(method: Optional[str], series: Sequence[float],
                *, std_value: Optional[float] = None,
                residual_std: Optional[float] = None
                ) -> Optional[Tuple[float, str]]:
    """``(spread, kind)`` — the scale this method's score actually divides by.

    The no-dispersion test must use the divisor the score uses. A robust
    method divides by MAD (``rolling_median_mad``) or by IQR (``iqr``), and
    either can be 0 while the series' standard deviation is not: for
    ``[0, 0, 0, 1, 4, 0, 0]`` MAD = 0, IQR = 0, std = 1.51. Testing std alone
    let such a row claim VERY_HIGH on a scale its own method did not have
    (533 stored Very High rows on the live store, 491 of them invisible to the
    std-only test).

    ``None`` when the method has no spread to divide by (``pct_change``,
    ``volume``) or the scale is not computable from what was supplied.
    """
    if method is None or method not in DISPERSION_METHODS:
        return None
    values = [float(v) for v in series if v is not None]
    if method == METHOD_ROLLING_MEDIAN_MAD:
        return (mad(values), "mad") if values else None
    if method == METHOD_IQR:
        if len(values) < 2:
            return None
        q1, _q2, q3 = quartiles(values)
        return q3 - q1, "iqr"
    if method == METHOD_TREND_DEVIATION:
        return (float(residual_std), "residual_std") if residual_std is not None else None
    if std_value is not None:
        return float(std_value), "std"
    return (std(values), "std") if len(values) >= 2 else None


def zero_dispersion(std_value: Optional[float],
                    method: Optional[str] = None,
                    *, spread: Optional[float] = None,
                    spread_kind: str = "std") -> bool:
    """True when a dispersion-based score had no dispersion to divide by.

    ``spread`` is the method's own divisor (:func:`spread_used`); when it is
    omitted the standard deviation is used, which is the divisor for the
    z-based methods. A method outside ``DISPERSION_METHODS`` is never
    degenerate: its score does not divide by a spread at all.
    """
    if method is not None and method not in DISPERSION_METHODS:
        return False
    value = std_value if spread is None else spread
    if value is None:
        return False
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def no_dispersion(method: Optional[str], series: Sequence[float],
                  *, std_value: Optional[float] = None,
                  residual_std: Optional[float] = None) -> bool:
    """Whether this method's score had no spread to divide by."""
    found = spread_used(method, series, std_value=std_value,
                        residual_std=residual_std)
    return zero_dispersion(std_value, method,
                           spread=found[0] if found else None)


def cap_zero_spread(level: Optional[str], std_value: Optional[float],
                    method: Optional[str] = None, *,
                    spread: Optional[float] = None,
                    spread_kind: str = "std"
                    ) -> Tuple[Optional[str], Optional[dict]]:
    """Cap one layer band at HIGH when its comparison had no dispersion.

    Returns ``(level, provenance)``; provenance is ``None`` when the comparison
    had real spread (nothing was capped). A band that is already at or below
    the cap is never lowered — the cap only refuses the top band to a
    comparison that cannot measure a magnitude.

    ``spread`` is the divisor the method used (MAD, IQR, residual std); the
    provenance records which one was zero, so a capped row says WHY it could
    not be graded instead of always reporting ``std = 0``.
    """
    if level is None or not zero_dispersion(std_value, method, spread=spread,
                                            spread_kind=spread_kind):
        return level, None
    capped = level
    if LEVEL_RANK.get(level, 0) > LEVEL_RANK[ZERO_SPREAD_LEVEL_CAP]:
        capped = ZERO_SPREAD_LEVEL_CAP
    value = spread if spread is not None else std_value
    return capped, {
        "zero_spread": True,
        "std": None if std_value is None else float(std_value),
        "dispersion": {"kind": spread_kind,
                       "value": float(value) if value is not None else None},
        "cap": ZERO_SPREAD_LEVEL_CAP,
        "resolved_level": level,
        "final_level": capped,
        "capped": capped != level,
        "policy": ZERO_SPREAD_POLICY,
    }


# ── Thin-comparison (too few peers) policy ────────────────────────────────
# A peer z-score divides by the spread of the OTHER hospitals' values, so its
# denominator is estimated from the group itself. With two peers that estimate
# is two numbers: whenever the pair happens to agree the spread collapses and
# the z explodes. Stored rows carry |z| = 224 from a 2-peer group (hospital 36,
# 2026-08, deliveries 15-19: a -18% deviation), and because the score saturates
# at 2 x threshold, everything past |z| ~ 5 is apparent precision rather than
# evidence. Quality Alerts already refuses to call such a group reliable —
# ``peer_count < 4`` records the row as low confidence — but the BAND still
# claimed the top level.
#
# Policy: a PEER comparison with fewer than MIN_PEERS_FOR_TOP_BAND other
# hospitals cannot claim VERY_HIGH. The finding, its score, its peer list and
# its low-confidence flag all stay exactly as computed; only the band it may
# claim is capped at HIGH, the same ceiling the zero-dispersion cap uses, and
# no z-score is produced for it (PEER_Z_POLICY below).
# Settings are untouched: min_peers still decides whether the layer EXISTS,
# the z threshold still decides whether it fired, and the band cutoffs are
# unchanged — this adds a sufficiency rule for the top band only.
#
# Applied per layer, never per row: a thin peer group must not suppress a band
# another (measured) layer earned.
MIN_PEERS_FOR_TOP_BAND = 4
THIN_PEER_LEVEL_CAP = LEVEL_HIGH
THIN_PEER_POLICY = (
    "The peer group is too small ({peers} peers) to measure a spread, so the "
    f"deviation cannot be graded; the level is capped at {THIN_PEER_LEVEL_CAP}"
)


def thin_peer_group(peer_count: Optional[int],
                    method: Optional[str] = None) -> bool:
    """True when a PEER comparison rests on fewer than the minimum peers.

    ``method`` narrows the check to peer comparisons; a history baseline's
    ``peer_count`` counts prior MONTHS, not hospitals, and is governed by the
    history-observation minimum instead.
    """
    if method is not None and method != METHOD_PEER_ZSCORE:
        return False
    try:
        count = int(peer_count)          # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return count < MIN_PEERS_FOR_TOP_BAND


def cap_thin_peer(level: Optional[str], peer_count: Optional[int],
                  method: Optional[str] = None
                  ) -> Tuple[Optional[str], Optional[dict]]:
    """Cap one PEER-comparison band at HIGH when the group is too small.

    Returns ``(level, provenance)``; provenance is ``None`` when the group is
    large enough (nothing was capped). A band already at or below the cap is
    never lowered — the cap only refuses the top band to a comparison whose
    spread cannot be measured from that few hospitals.
    """
    if level is None or not thin_peer_group(peer_count, method):
        return level, None
    capped = level
    if LEVEL_RANK.get(level, 0) > LEVEL_RANK[THIN_PEER_LEVEL_CAP]:
        capped = THIN_PEER_LEVEL_CAP
    return capped, {
        "thin_peer_group": True,
        "peer_count": int(peer_count),   # type: ignore[arg-type]
        "min_peers_for_top_band": MIN_PEERS_FOR_TOP_BAND,
        "cap": THIN_PEER_LEVEL_CAP,
        "resolved_level": level,
        "final_level": capped,
        "capped": capped != level,
        "policy": THIN_PEER_POLICY.format(peers=int(peer_count)),  # type: ignore[arg-type]
    }


# ── VERY_HIGH eligibility (top band only) ──────────────────────────────────
# The caps above refuse the top band when a comparison has NO scale at all.
# This one refuses it when a scale EXISTS but disagrees by a wide margin — the
# same question `cap_pct_change` already asks of a percentage change: "what
# band does the window's own z give?" and the same answer (`dispersion_score`),
# with no new threshold and no new cutoff.
#
# Why it is needed: the robust methods divide by MAD or IQR, and for integer
# counts those sit near the floor. MAD = 1 makes 4.45 counts a top-band
# distance at ANY level, while the same window's z needs 4.5 sigmas. On the
# live store, 108 of 125 MAD-scored history issues and all 15 IQR ones lose the
# top band when asked this question; the median window is over-dispersed
# (var/mean 2.08), so the robust scale is the outlier, not the dispersion.
#
# Applied to the TOP BAND ONLY, like the two caps above: a HIGH row is never
# lowered because VERY_HIGH was refused, so a rule written to gate the top band
# cannot quietly re-grade every alert on the screens. Nothing is rewritten —
# the stored band stays on the row, and the assessment says what the policy
# allows beside it.
VERY_HIGH_ELIGIBILITY_POLICY = (
    "VERY_HIGH requires the comparison's own dispersion to support the top "
    "band: a robust scale (MAD/IQR) can sit at its floor and grade any change "
    "as maximal, so the same window's dispersion-aware score decides whether "
    f"the top band may be claimed. Below it the band is {LEVEL_HIGH}"
)
ELIGIBLE = "ELIGIBLE"
INELIGIBLE_DISPERSION = "DISPERSION_BAND_BELOW_VERY_HIGH"
INSUFFICIENT_DATA = "INSUFFICIENT_DISPERSION_DATA"
NOT_APPLICABLE = "BAND_BELOW_VERY_HIGH"
# Why an otherwise applicable gate could not decide: the two inputs a window
# needs before it can measure anything. Reported apart from the band verdicts
# so "no window" is never read as "no deviation".
REASON_NO_WINDOW = "NO_STORED_HISTORY_WINDOW"
REASON_NO_CURRENT = "CURRENT_VALUE_MISSING"


def very_high_eligibility(level: Optional[str],
                          series: Sequence[float],
                          current: Optional[float],
                          threshold: Optional[float] = None) -> Dict[str, Any]:
    """Can this row claim VERY_HIGH? A top-band gate, never a re-grade.

    ``series`` is the comparison window (prior months or peers), ``current``
    the value being graded and ``threshold`` the configured z threshold — the
    same one every score uses, so no policy knob is introduced here.

    Returns a flat assessment:

    ``applicable``      the row is at VERY_HIGH (only those are gated)
    ``eligible``        True / False, or None when the window cannot decide
    ``reason``          ELIGIBLE, DISPERSION_BAND_BELOW_VERY_HIGH,
                        INSUFFICIENT_DISPERSION_DATA, BAND_BELOW_VERY_HIGH
    ``original_band``   the band that was assessed (never mutated)
    ``final_band``      what the policy allows: the original band unless the
                        top band was refused, in which case HIGH

    Three rules that are easy to get wrong and are deliberate:

    * A row below VERY_HIGH is returned untouched (``applicable`` False). The
      gate only decides whether the TOP band may be claimed.
    * A refused top band falls to HIGH, never lower: this is a sufficiency
      rule for one band, not a re-grading of the deviation. The cumulative
      methods' bands (see ``level_for_score``) would send most robust-method
      rows to NONE, which would report "no deviation" for a finding the
      engine still measured as an outlier.
    * A window with no measurable scale (fewer than 2 points, a missing
      current value, zero spread) returns ``eligible`` None and leaves the
      band alone. Unknown is not the same as unsupported, and an absent
      measurement must not become evidence of normality.
    """
    original = level
    base = {
        "applicable": False,
        "eligible": True,
        "reason": NOT_APPLICABLE,
        "original_band": original,
        "final_band": original,
        "dispersion_score": None,
        "dispersion_band": None,
        "cap": LEVEL_HIGH,
        "policy": VERY_HIGH_ELIGIBILITY_POLICY,
    }
    if level is None or LEVEL_RANK.get(level, 0) < LEVEL_RANK[LEVEL_VERY_HIGH]:
        return base
    values = [float(v) for v in series if v is not None]
    used = float(threshold) if threshold else PEER_Z_THRESHOLD_DEFAULT
    score = dispersion_score(values, current, used) if current is not None \
        else None
    band = level_for_score(score) if score is not None else None
    if band is None:
        return {
            **base,
            "applicable": True,
            "eligible": None,
            "reason": INSUFFICIENT_DATA,
            "final_band": original,
        }
    eligible = LEVEL_RANK[band] >= LEVEL_RANK[LEVEL_VERY_HIGH]
    return {
        **base,
        "applicable": True,
        "eligible": eligible,
        "reason": ELIGIBLE if eligible else INELIGIBLE_DISPERSION,
        "final_band": original if eligible else LEVEL_HIGH,
        "dispersion_score": score,
        "dispersion_band": band,
    }


def eligibility_provenance(assessment: Dict[str, Any]) -> Optional[dict]:
    """The cap block for a REFUSED top band, from ONE gate assessment.

    ``None`` when the gate did not apply or left the band alone: an undecidable
    window is not a refusal. Callers that already hold an assessment use this
    instead of re-running :func:`very_high_eligibility`, so the dispersion is
    measured once per row.
    """
    if not assessment.get("applicable"):
        return None
    final = assessment.get("final_band")
    original = assessment.get("original_band")
    if final is None or final == original:
        return None
    return {
        "eligible": assessment["eligible"],
        "reason": assessment["reason"],
        "cap": assessment.get("cap", LEVEL_HIGH),
        "resolved_level": original,
        "final_level": final,
        "dispersion_score": assessment.get("dispersion_score"),
        "dispersion_band": assessment.get("dispersion_band"),
        "capped": True,
        "policy": assessment["policy"],
    }


def cap_very_high_eligibility(level: Optional[str],
                              series: Optional[Sequence[float]],
                              current: Optional[float],
                              threshold: float
                              ) -> Tuple[Optional[str], Optional[dict]]:
    """Cap a band at HIGH when the window's dispersion refuses the top band.

    Same contract as :func:`cap_zero_spread` and :func:`cap_thin_peer`: returns
    ``(level, provenance)``, provenance is ``None`` when nothing was capped, and
    a band below VERY_HIGH is returned untouched.

    An UNDECIDABLE window (no series, no current value, no measurable spread)
    returns provenance ``None`` as well: nothing was capped because nothing was
    measured. Readers must not present an absent measurement as a refusal.
    """
    assessment = very_high_eligibility(
        level, list(series or ()), current, threshold)
    provenance = eligibility_provenance(assessment)
    if provenance is None:
        return level, None
    return assessment["final_band"], provenance


# ── Peer top-band eligibility (Rule B) ────────
# A FIFTH decision, not a flavour of ``undecided``: the comparison exists but
# its robust scales are DEGENERATE (MAD = 0 and IQR = 0), so the robust-scale
# policy cannot judge it at all. Kept outside the eligible / ineligible /
# undecided counts so the three judgement states keep their meaning.
DECISION_INSUFFICIENT_ROBUST_SCALE = "insufficient_robust_scale"

# Mutually exclusive: every row gets exactly one of these, in the precedence
# documented on ``peer_very_high_eligibility``.
PEER_REASON_DEFINITION_NOT_ESTABLISHED = "DEFINITION_NOT_ESTABLISHABLE"
PEER_REASON_THIN_PEER_GROUP = "THIN_PEER_GROUP"
PEER_REASON_NO_STORED_PEER_VALUES = "NO_STORED_PEER_VALUES"
PEER_REASON_CURRENT_VALUE_MISSING = "CURRENT_VALUE_MISSING"
PEER_REASON_INSUFFICIENT_PEER_VALUES = "INSUFFICIENT_PEER_VALUES"
PEER_REASON_NO_ROBUST_SCALE = "NO_ROBUST_SCALE"
PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES = "ONLY_AVAILABLE_SCALE_REFUSES"
PEER_REASON_SCALES_DISAGREE = "SCALES_DISAGREE"
PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS = "ONLY_AVAILABLE_SCALE_SUPPORTS"
PEER_REASON_BOTH_SCALES_SUPPORT = "BOTH_SCALES_SUPPORT"
# Rule B only: a refusal needs TWO usable scales that both refuse. The
# single-scale refusal above is deliberately NOT a refusal under Rule B, which
# is why ``ALL_AVAILABLE_SCALES_REFUSE`` (Rule A's label) is never emitted here.
PEER_REASON_BOTH_USABLE_SCALES_REFUSE = "BOTH_USABLE_SCALES_REFUSE"

# Informational only: a peer group this zero-heavy is flagged for display and
# never changes the decision, the band or the severity.
ZERO_SHARE_WARNING_THRESHOLD = 0.5
PEER_ELIGIBILITY_POLICY = (
    "Rule B grades a peer top band STATISTICALLY: the band is supported when "
    "every USABLE robust scale of the comparison group reaches VERY_HIGH; two "
    "usable scales that disagree leave the claim undecided; a single usable "
    "scale cannot refuse on its own; and a group whose robust scales are "
    "degenerate is reported as insufficient_robust_scale rather than refused "
    "or accepted. The indicator's definition must be established first (a row "
    "formula with a usable numerator and denominator, or a definition the live "
    "catalog resolves), and clinical/operational comparability between the "
    "hospitals stays not_verified — statistical eligibility is not evidence of "
    "comparability or of data quality"
)


# ── The peer DEFINITION gate (before any robust-scale decision) ────────────
# A peer comparison is not graded on its spread until the indicator's own
# definition can be established: a formula with a usable numerator/denominator,
# OR a definition resolvable in the live catalog. The catalog may only
# SUPPLEMENT a row, and a row that leans on it is marked, because peer-level
# unit / formula / denominator metadata is not stored — one row's definition
# says nothing about the other hospitals in the group.
PEER_DEFINITION_COMPLETE = "complete_from_row"
PEER_DEFINITION_SELF_CONTAINED = "self_contained_no_catalog"
PEER_DEFINITION_CATALOG_ONLY = "catalog_only"
PEER_DEFINITION_NOT_ESTABLISHABLE = "not_establishable"
PEER_DEFINITION_STATUSES = (
    PEER_DEFINITION_COMPLETE,
    PEER_DEFINITION_SELF_CONTAINED,
    PEER_DEFINITION_CATALOG_ONLY,
    PEER_DEFINITION_NOT_ESTABLISHABLE,
)
# Legitimate spellings a caller may hand over for an unclosable definition.
UNESTABLISHED_DEFINITION_STATUSES = frozenset({
    PEER_DEFINITION_NOT_ESTABLISHABLE, "not_established", "missing", "unknown",
})
# Group-wide comparability is a SEPARATE dimension from one row's definition:
# the stored evidence carries no peer-level units, formulas or denominators, so
# it stays unverified regardless of how complete the row's own definition is.
GROUP_COMPARABILITY_NOT_VERIFIED = "not_verified"


def peer_definition_status(*, formula=None, numerator=None,
                           denominator=None,
                           catalog_resolved: bool = False) -> str:
    """The definition evidence for ONE peer alert, as a single tier.

    ``complete_from_row``      formula + usable ratio, and the indicator also
                               resolves in the live catalog;
    ``self_contained_no_catalog`` the same row evidence without a catalog entry;
    ``catalog_only``           nothing on the row, but the catalog resolves it
                               (explicitly marked — not verified comparability);
    ``not_establishable``      neither exists, so the comparison is undecided.

    A denominator of 0 is not a usable denominator; an empty formula is not a
    formula. Nothing is inferred or imputed.
    """
    has_formula = bool(str(formula).strip()) if formula is not None else False
    has_ratio = False
    if numerator is not None and denominator is not None:
        try:
            has_ratio = math.isfinite(float(denominator)) \
                and float(denominator) != 0.0
        except (TypeError, ValueError):
            has_ratio = False
    if has_formula and has_ratio:
        return (PEER_DEFINITION_COMPLETE if catalog_resolved
                else PEER_DEFINITION_SELF_CONTAINED)
    if catalog_resolved:
        return PEER_DEFINITION_CATALOG_ONLY
    return PEER_DEFINITION_NOT_ESTABLISHABLE


def peer_definition_established(status) -> bool:
    """True when a definition tier is enough to grade the comparison.

    ``catalog_only`` counts as established (the approved gate lets the catalog
    supplement a row) but is never reported as verified comparability.
    """
    return str(status or "").strip().lower() not in UNESTABLISHED_DEFINITION_STATUSES


def _finite_peer_values(values) -> Tuple[List[float], int]:
    """``(finite values, stored entries)`` for one peer group.

    Non-numbers are dropped and non-finite values (NaN / ±inf) are dropped too:
    ``float("nan")`` succeeds, so a single NaN would otherwise poison the
    median, the MAD and every quantile. Dropping is not imputation; the stored
    count is returned so a MISSING group and a group whose values were all
    unusable get different reasons.
    """
    if values is None or isinstance(values, (str, bytes)):
        return [], 0
    if isinstance(values, dict):
        values = list(values.values())
    try:
        raw = list(values)
    except TypeError:
        return [], 0
    out: List[float] = []
    for value in raw:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out, len(raw)


def peer_very_high_eligibility(level: Optional[str],
                               values,
                               current: Optional[float],
                               *,
                               definition_status: str = "established",
                               threshold: Optional[float] = None,
                               denominator_review: bool = False
                               ) -> Dict[str, Any]:
    """Can a PEER comparison claim VERY_HIGH? (Rule B, read-only, isolated.)

    This is deliberately NOT wired into any read path yet: it computes and
    explains one verdict and touches no row, band, score or evidence.

    **Usable scale.** ``MAD`` is usable only when the group's MAD is strictly
    positive and ``IQR`` only when ``Q3 - Q1`` is strictly positive. The
    builders fall back to ``1.0`` on a zero divisor (``score_from_mad`` /
    ``score_from_iqr``), so they are never called unless the divisor is usable:
    a zero MAD must not become a supporting measurement. A single usable scale
    is judged on its own — MAD = 0 with a valid IQR uses the IQR alone.

    **Rule B.** Eligible when every usable scale supports; ``ineligible`` only
    when TWO usable scales both refuse; disagreement, or a refusal by the only
    usable scale, is ``undecided``. A degenerate group (neither scale usable) is
    ``insufficient_robust_scale`` — a distinct decision, not ``undecided``.

    **Precedence (one reason per row).**

    1. band below VERY_HIGH -> ``not_applicable``;
    2. no stored group at all -> ``undecided`` / ``NO_STORED_PEER_VALUES``;
    3. fewer than 2 finite values -> ``undecided`` /
       ``INSUFFICIENT_PEER_VALUES`` (all values unusable is this, not "thin");
    4. 2-3 finite values -> ``not_applicable`` / ``THIN_PEER_GROUP`` (the
       approved thin-peer cap owns the band);
    5. definition not establishable -> ``undecided``;
    6. no current value -> ``undecided`` / ``CURRENT_VALUE_MISSING``;
    7. neither robust scale usable -> ``insufficient_robust_scale``;
    8. Rule B on the usable scales.

    The returned ``band`` is ALWAYS the band passed in: eligibility is a third
    dimension, and neither this function nor its flags may lower a severity.
    ``zero_share_warning`` and ``denominator_review`` are display-only.
    """
    original = level
    used = gate_threshold(None, threshold)
    peers, stored_entries = _finite_peer_values(values)
    zero_share = (sum(1 for v in peers if v == 0.0) / len(peers)) if peers else 0.0
    base: Dict[str, Any] = {
        "original_band": original,
        "band": original,                 # never lowered by this policy
        "applicable": False,
        "eligible": None,
        "decision": DECISION_NOT_APPLICABLE,
        "reason": NOT_APPLICABLE,
        "policy": PEER_ELIGIBILITY_POLICY,
        "threshold": used,
        "peer_count": len(peers),
        "stored_peer_count": stored_entries,
        "finite_peer_count": len(peers),
        "mad": None,
        "iqr": None,
        "mad_usable": False,
        "iqr_usable": False,
        "mad_level": None,
        "iqr_level": None,
        "zero_share": round(zero_share, 4),
        "zero_share_warning": zero_share >= ZERO_SHARE_WARNING_THRESHOLD,
        "denominator_review": bool(denominator_review),
        "definition_status": definition_status,
        "group_comparability_status": GROUP_COMPARABILITY_NOT_VERIFIED,
    }

    def _verdict(decision: str, reason: str, *, applicable: bool,
                 eligible: Optional[bool], **extra) -> Dict[str, Any]:
        return {**base, "decision": decision, "reason": reason,
                "applicable": applicable, "eligible": eligible, **extra}

    if level is None or LEVEL_RANK.get(level, 0) < LEVEL_RANK[LEVEL_VERY_HIGH]:
        return _verdict(DECISION_NOT_APPLICABLE, NOT_APPLICABLE,
                        applicable=False, eligible=None)
    if not stored_entries:
        return _verdict(DECISION_UNDECIDED, PEER_REASON_NO_STORED_PEER_VALUES,
                        applicable=True, eligible=None)
    if len(peers) < 2:
        return _verdict(DECISION_UNDECIDED, PEER_REASON_INSUFFICIENT_PEER_VALUES,
                        applicable=True, eligible=None)
    if len(peers) < MIN_PEERS_FOR_TOP_BAND:
        return _verdict(DECISION_NOT_APPLICABLE, PEER_REASON_THIN_PEER_GROUP,
                        applicable=False, eligible=None)
    if not peer_definition_established(definition_status):
        return _verdict(DECISION_UNDECIDED,
                        PEER_REASON_DEFINITION_NOT_ESTABLISHED,
                        applicable=True, eligible=None)
    try:
        current_value = float(current) if current is not None else None
    except (TypeError, ValueError):
        current_value = None
    if current_value is None or not math.isfinite(current_value):
        return _verdict(DECISION_UNDECIDED, PEER_REASON_CURRENT_VALUE_MISSING,
                        applicable=True, eligible=None)

    center = median(peers)
    mad_value = mad(peers)
    q1, _q2, q3 = quartiles(peers)
    iqr_value = q3 - q1
    mad_usable = mad_value > 0
    iqr_usable = iqr_value > 0
    mad_level = (level_for_score(score_from_mad(current_value, center, mad_value))
                 if mad_usable else None)
    iqr_level = (level_for_score(score_from_iqr(current_value, q1, q3))
                 if iqr_usable else None)
    detail = {"mad": round(mad_value, 6), "iqr": round(iqr_value, 6),
              "mad_usable": mad_usable, "iqr_usable": iqr_usable,
              "mad_level": mad_level, "iqr_level": iqr_level}

    if not mad_usable and not iqr_usable:
        return _verdict(DECISION_INSUFFICIENT_ROBUST_SCALE,
                        PEER_REASON_NO_ROBUST_SCALE,
                        applicable=True, eligible=None, **detail)

    usable = [lv for lv in (mad_level, iqr_level) if lv is not None]
    supports = [lv == LEVEL_VERY_HIGH for lv in usable]
    if len(usable) == 1:
        if supports[0]:
            return _verdict(DECISION_ELIGIBLE,
                            PEER_REASON_ONLY_AVAILABLE_SCALE_SUPPORTS,
                            applicable=True, eligible=True, **detail)
        return _verdict(DECISION_UNDECIDED,
                        PEER_REASON_ONLY_AVAILABLE_SCALE_REFUSES,
                        applicable=True, eligible=None, **detail)
    if all(supports):
        return _verdict(DECISION_ELIGIBLE, PEER_REASON_BOTH_SCALES_SUPPORT,
                        applicable=True, eligible=True, **detail)
    if not any(supports):
        return _verdict(DECISION_INELIGIBLE,
                        PEER_REASON_BOTH_USABLE_SCALES_REFUSE,
                        applicable=True, eligible=False, **detail)
    return _verdict(DECISION_UNDECIDED, PEER_REASON_SCALES_DISAGREE,
                    applicable=True, eligible=None, **detail)


# ── Read-time cap for a STORED row (Outlier Diagnostics) ───────────────────
# Quality Alerts re-applies the approved caps when it READS a row
# (quality_alerts.effective_severity), so a row written before a cap existed is
# presented under the policy in effect now. Diagnostics served
# ``outlier_level`` verbatim, so the same stored finding could read HIGH on the
# alerts screen and VERY_HIGH here until its month was re-analysed.
#
# These two functions are that rule for a layered row: the same caps, applied
# per LAYER (a degenerate comparison must not suppress a band another measured
# layer earned) and decided from what the row itself stores. Nothing is
# rewritten — the stored band stays on the row, and readers show it beside the
# band the policy allows.
ROW_LAYER_SCORE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("raw", "raw_value_outlier_score"),
    ("rate", "rate_outlier_score"),
    ("historical", "historical_outlier_score"),
    ("volume", "volume_anomaly_score"),
    ("peer", "peer_outlier_score"),
)


def _stored_numbers(raw) -> List[float]:
    """Floats from a stored provenance list/dict; non-numbers dropped."""
    if isinstance(raw, dict):
        raw = list(raw.values())
    values: List[float] = []
    for value in raw or ():
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def row_capped_layers(row) -> Tuple[frozenset, frozenset]:
    """``(zero-spread layers, thin-peer layers)`` for one STORED row.

    A row written under the current policy names them in its
    ``classification_provenance``. A row written before that field existed is
    decided from the evidence it did store: the peer group's values (the peer
    layer, and the raw layer of a count analysis, which scores the same
    series) and the history window using the row's own method. A layer whose
    divisor cannot be recovered counts as MEASURED — unknown is not the same
    as degenerate.
    """
    provenance = getattr(row, "classification_provenance", None) or {}
    zero = set(provenance.get("zero_spread_layers") or ())
    thin = set(provenance.get("thin_peer_layers") or ())
    history = _stored_numbers(
        (getattr(row, "history_provenance", None) or {}).get("values"))
    method = getattr(row, "outlier_method", None)
    if history:
        # peer_zscore is the PEER layer's method, not the history one; a row
        # classified by a peer rule therefore falls back to the z-based test
        # on its own window (what the pre-divisor policy did).
        ask = method if (method and method != METHOD_PEER_ZSCORE) else METHOD_ZSCORE
        if no_dispersion(ask, history,
                         std_value=getattr(row, "historical_std", None)):
            zero.add("historical")
    peers = _stored_numbers(
        (getattr(row, "peer_provenance", None) or {}).get("values"))
    if len(peers) >= 2 and no_dispersion(METHOD_PEER_ZSCORE, peers):
        zero.add("peer")
        if getattr(row, "rate", None) is None:
            zero.add("raw")
    if thin_peer_group(getattr(row, "peer_count", None), METHOD_PEER_ZSCORE):
        thin.add("peer")
    return frozenset(zero), frozenset(thin)


def row_layer_bands(row) -> Tuple[Dict[str, Optional[str]], List[str], List[str]]:
    """``(per-layer band, zero-spread layers lowered, thin-peer layers lowered)``.

    The two approved caps are applied PER LAYER here, once, so every reader of
    a stored row sees the same layer bands: ``row_level_assessment`` uses this
    to resolve the row, and readers that must explain WHICH layer still holds a
    band (the consistency audit, the Why popup) use it instead of re-deriving
    the caps themselves. A layer whose score is ``None`` keeps ``None`` —
    "never ran" is never rendered as a band.

    Applying only the caps that were approved: the top-band eligibility gate
    (``cap_very_high_eligibility``) is deliberately NOT applied here.
    """
    zero, thin = row_capped_layers(row)
    bands: Dict[str, Optional[str]] = {}
    lowered_zero: List[str] = []
    lowered_thin: List[str] = []
    for name, score_field in ROW_LAYER_SCORE_FIELDS:
        band = level_for_score(getattr(row, score_field, None))
        if (band is not None and name in zero
                and LEVEL_RANK[band] > LEVEL_RANK[ZERO_SPREAD_LEVEL_CAP]):
            band = ZERO_SPREAD_LEVEL_CAP
            lowered_zero.append(name)
        if (band is not None and name == "peer" and name in thin
                and LEVEL_RANK[band] > LEVEL_RANK[THIN_PEER_LEVEL_CAP]):
            band = THIN_PEER_LEVEL_CAP
            lowered_thin.append(name)
        bands[name] = band
    return bands, lowered_zero, lowered_thin


# ── Routing the top-band gate (WHICH rule judges WHICH layer) ─────────────
# The eligibility gate answers ONE question: does this row's OWN-HISTORY
# window support the top band? It is routed PER LAYER, never applied to a row
# merely because the row carries the band:
#
# ``history`` (raw / rate / own-history months)
#     GATED. The window is the stored history series, the current value is the
#     row's own unit value (the rate for a rate analysis), the threshold is the
#     one stored on the row or the configured default — the same inputs the
#     scan used.
# ``peer`` (other hospitals)
#     NOT gated here. A peer z already divides by the group's own spread, and
#     the approved peer policies (no dispersion; fewer than 4 peers) are the
#     rules that judge it. The gate returns ``undecided`` and the band the
#     layer earned stands.
# ``volume`` (denominator change)
#     NOT gated here: it scores a percentage change of the denominator, which
#     stays measurable on a flat series. ``undecided``.
# ``raw`` on a RATE analysis
#     A count compared with a rate window is a unit mismatch, not evidence
#     about the rate. ``undecided`` with ``unit_compatible = False``.
#
# The four states are kept apart exactly as the policy defines them:
# ``not_applicable`` (the row is below the top band, or the approved caps
# already refused it), ``eligible`` / ``ineligible`` (the window measured a
# scale and supported / refused the top band) and ``undecided`` (the policy
# could not judge: no window, no current value, or a layer this policy does not
# govern). ``undecided`` is never a pass and never a refusal.
ROUTE_HISTORY = "history"
ROUTE_PEER = "peer"
ROUTE_VOLUME = "volume"
ROUTE_RAW_UNIT = "raw_count_on_rate"
ROUTE_NO_TOP_LAYER = "no_top_layer"

OWN_HISTORY_LAYERS = frozenset({"raw", "rate", "historical"})

DECISION_ELIGIBLE = "eligible"
DECISION_INELIGIBLE = "ineligible"
DECISION_UNDECIDED = "undecided"
DECISION_NOT_APPLICABLE = "not_applicable"
# The FIFTH decision (``insufficient_robust_scale``) and the peer reason codes
# are defined with ``peer_very_high_eligibility`` above, the only consumer, so
# this peer policy never references a name before its definition.

TOP_BAND_ROUTE_POLICY = {
    ROUTE_PEER: (
        "The top band rests on a peer comparison. Rule B judges it from the "
        "comparison group's own usable robust scales — a STATISTICAL verdict "
        "only: clinical/operational comparability between the hospitals stays "
        "not_verified, and nothing about their data quality is established. "
        f"The thin-peer limit (fewer than {MIN_PEERS_FOR_TOP_BAND} hospitals) "
        "and a zero-spread group are separate caps, not Rule B's verdict, and "
        "the history window's dispersion never decides a peer claim"
    ),
    ROUTE_VOLUME: (
        "The top band rests on a volume (denominator) comparison, which was "
        "not graded by a spread; the history window's dispersion does not "
        "decide it"
    ),
    ROUTE_RAW_UNIT: (
        "The top band rests on a raw COUNT layer of a RATE analysis: the "
        "history window holds rates, so it cannot judge the count"
    ),
    ROUTE_NO_TOP_LAYER: (
        "No measured layer holds the top band for this row"
    ),
}


def gate_threshold(stored: Optional[float] = None,
                   configured: Optional[float] = None) -> float:
    """The z threshold the top-band gate asks with.

    The value STORED with the comparison wins, so a row is always judged with
    the threshold its own scan used; the configured value is the fallback for a
    row written before the threshold was recorded, and the saved default
    (``PEER_Z_THRESHOLD_DEFAULT``) is the last resort. No new knob: this is
    ``thresholds.zscore_threshold`` either way.
    """
    for value in (stored, configured):
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return PEER_Z_THRESHOLD_DEFAULT


def top_band_route(layer: Optional[str], *,
                   raw_count_on_rate: bool = False) -> str:
    """Which rule judges a top band held by ``layer`` (see the block above)."""
    if layer == "peer":
        return ROUTE_PEER
    if layer == "volume":
        return ROUTE_VOLUME
    if layer == "raw" and raw_count_on_rate:
        return ROUTE_RAW_UNIT
    if layer in OWN_HISTORY_LAYERS:
        return ROUTE_HISTORY
    return ROUTE_NO_TOP_LAYER


def row_gate_threshold(row, configured: Optional[float] = None) -> float:
    """The threshold a STORED layered row recorded for its own comparison."""
    provenance = getattr(row, "classification_provenance", None) or {}
    return gate_threshold(provenance.get("zscore_threshold"), configured)


def row_very_high_eligibility(row, threshold: Optional[float] = None
                              ) -> Dict[str, Any]:
    """The read-time top-band verdict for ONE stored layered row.

    Returns ``band`` (what the policy allows), ``base_band`` (the band the
    approved caps allow), ``route`` (which rule judged it), ``top_layers`` (the
    layers holding the top band before the gate), ``decision`` (one of the four
    states) and ``assessment`` (the gate's own flat result, or ``None`` when the
    gate was not consulted). Nothing is mutated and nothing is written.

    Precedence is deliberate and mirrors the audit:

    1. below the top band, or already refused by an approved cap ->
       ``not_applicable``;
    2. a PEER layer holds the top band -> ``undecided`` (that layer has its own
       approved policies);
    3. a VOLUME layer holds it -> ``undecided``;
    4. only a raw COUNT of a RATE analysis holds it -> ``undecided`` (unit
       mismatch);
    5. an own-history layer holds it -> the gate decides;
    6. nothing holds it -> ``undecided``.

    The band only moves when the gate REFUSES the top band for a history
    claim, and it moves to HIGH, never lower.
    """
    stored = getattr(row, "outlier_level", None) or LEVEL_NONE
    bands, lowered_zero, lowered_thin = row_layer_bands(row)
    base = max_level(bands.values())
    holders = sorted(name for name, band in bands.items()
                     if band == LEVEL_VERY_HIGH)
    rate_is_set = getattr(row, "rate", None) is not None
    current = (float(row.rate) if rate_is_set
               else (float(row.raw_value)
                     if getattr(row, "raw_value", None) is not None else None))
    history = _stored_numbers(
        (getattr(row, "history_provenance", None) or {}).get("values"))
    unit_layers = {name for name in holders
                   if name == "raw" and rate_is_set}
    own_holders = [name for name in holders
                   if name in OWN_HISTORY_LAYERS and name not in unit_layers]
    used = row_gate_threshold(row, threshold)

    def _result(band: str, decision: str, route: str, reason: str,
                assessment: Optional[dict] = None, eligible=None,
                applicable: bool = False) -> Dict[str, Any]:
        return {
            "stored_band": stored,
            "band": band,
            "base_band": base,
            "decision": decision,
            "route": route,
            "reason": reason,
            "applicable": applicable,
            "eligible": eligible,
            "top_layers": holders,
            "capped_layers": sorted(set(lowered_zero) | set(lowered_thin)),
            "history_window": len(history),
            "current": current,
            "threshold": used,
            "unit_compatible": not unit_layers,
            "assessment": assessment,
            "policy": (assessment or {}).get("policy") or
                      TOP_BAND_ROUTE_POLICY.get(route, ""),
        }

    if (LEVEL_RANK.get(stored, 0) < LEVEL_RANK[LEVEL_VERY_HIGH]
            or LEVEL_RANK.get(base, 0) < LEVEL_RANK[LEVEL_VERY_HIGH]):
        return _result(base, DECISION_NOT_APPLICABLE, ROUTE_NO_TOP_LAYER,
                       NOT_APPLICABLE)
    for layer, route in (("peer", ROUTE_PEER),
                         ("volume", ROUTE_VOLUME)):
        if layer in holders:
            return _result(base, DECISION_UNDECIDED, route,
                           route.upper() + "_POLICY")
    if unit_layers and not own_holders:
        return _result(base, DECISION_UNDECIDED, ROUTE_RAW_UNIT,
                       DECISION_UNDECIDED.upper() + "_UNIT_MISMATCH")
    if not own_holders:
        return _result(base, DECISION_UNDECIDED, ROUTE_NO_TOP_LAYER,
                       ROUTE_NO_TOP_LAYER.upper())
    assessment = very_high_eligibility(base, history, current, used)
    decision = (DECISION_ELIGIBLE if assessment["eligible"]
                else DECISION_INELIGIBLE if assessment["eligible"] is False
                else DECISION_UNDECIDED)
    return _result(assessment["final_band"], decision, ROUTE_HISTORY,
                   assessment["reason"], assessment=assessment,
                   eligible=assessment["eligible"], applicable=True)


def row_level_assessment(row, threshold: Optional[float] = None
                         ) -> Tuple[str, Optional[dict]]:
    """``(band the policy allows, cap provenance)`` for one STORED row.

    The provenance block is ``None`` when nothing was capped. Every rule here
    only ever refuses the TOP band, so a row already at or below HIGH is
    returned untouched — and a band another measured layer still earns is never
    lowered, exactly like :func:`classify`.

    Two rules are composed, in this order:

    * the two APPROVED caps (a comparison with no spread; a peer group too
      small to measure one), applied per layer;
    * the top-band eligibility gate (:func:`row_very_high_eligibility`),
      applied only to the layers it governs — a peer, volume or raw-count-on-a-
      rate claim is left alone (``undecided``), because those have their own
      approved policies and the history window cannot judge them.

    Nothing is rewritten: the stored band stays on the row and the block says
    which rule refused it.
    """
    stored = getattr(row, "outlier_level", None) or LEVEL_NONE
    if LEVEL_RANK.get(stored, 0) < LEVEL_RANK[LEVEL_VERY_HIGH]:
        return stored, None
    verdict = row_very_high_eligibility(row, threshold)
    best = verdict["band"]
    if LEVEL_RANK.get(best, 0) >= LEVEL_RANK.get(stored, 0):
        # A measured layer still holds the stored band: nothing was lowered.
        return stored, None
    _bands, lowered_zero, lowered_thin = row_layer_bands(row)
    policies: List[str] = []
    if lowered_zero:
        policies.append(ZERO_SPREAD_POLICY)
    thin_block = None
    if lowered_thin:
        peers = getattr(row, "peer_count", None)
        thin_block = {
            "peer_count": peers,
            "min_peers_for_top_band": MIN_PEERS_FOR_TOP_BAND,
            "capped": True,
            "policy": THIN_PEER_POLICY.format(peers=peers),
        }
        policies.append(thin_block["policy"])
    gate_block = None
    if verdict["route"] == ROUTE_HISTORY:
        gate_block = {
            "eligible": verdict["eligible"],
            "reason": verdict["reason"],
            "cap": LEVEL_HIGH,
            "resolved_level": stored,
            "final_level": best,
            "dispersion_score": (verdict["assessment"] or {}).get(
                "dispersion_score"),
            "dispersion_band": (verdict["assessment"] or {}).get(
                "dispersion_band"),
            "history_window": verdict["history_window"],
            "current": verdict["current"],
            "threshold": verdict["threshold"],
            "capped": True,
            "policy": verdict["policy"],
        }
        policies.append(verdict["policy"])
    return best, {
        "stored_severity": stored,
        "severity": best,
        "resolved_level": stored,
        "final_level": best,
        "cap": best,
        "capped": True,
        "zero_spread_layers": lowered_zero,
        "thin_peer_group": thin_block,
        "very_high_eligibility": gate_block,
        "route": verdict["route"],
        "policy": " ".join(policies),
    }


def effective_row_level(row, threshold: Optional[float] = None) -> str:
    """The band the approved policy assigns to a STORED layered row."""
    return row_level_assessment(row, threshold)[0]


# A z-score divides by the group's own spread. With a group smaller than
# MIN_PEERS_FOR_TOP_BAND that spread is estimated from 2-3 numbers — a range,
# not a distribution — and the resulting z is not a measurement (the live store
# carried |z| = 224 from a 2-peer group, which the band cap alone could not
# stop: the band was refused while the z itself still read as a top-band
# magnitude on every screen that quoted it).
#
# Policy: such a comparison still EXISTS and is still SCORED — the peer values,
# their mean, the count, the deviation and the score are untouched, because "it
# differs from both hospitals that reported it" is real evidence. It simply
# does not produce a z-score: the layer's z is NULL and the row records why
# (``peer_z_provenance``), exactly as a no-dispersion comparison stores z = NULL
# while keeping its 1.0 score. Thresholds are unchanged; no band or cutoff
# moved.
PEER_Z_POLICY = (
    "A comparison group with fewer than {min_peers} peer hospitals cannot "
    "measure a spread, so no z-score is produced for it; the peer values, "
    "their mean, the count and the score are kept"
)


def peer_z_measurable(peer_count: Optional[int]) -> bool:
    """True when the comparison group can support a z-score.

    Same boundary as the top-band cap: a z divides by the group's spread, and
    fewer than MIN_PEERS_FOR_TOP_BAND other hospitals cannot measure one.
    """
    try:
        count = int(peer_count)          # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return count >= MIN_PEERS_FOR_TOP_BAND


def peer_z_provenance(peer_count: Optional[int]) -> dict:
    """Whether a z-score was produced for a peer comparison, and why not.

    Travels with every row/alert that could have carried a peer z, so a NULL z
    is explained instead of being read as a missing measurement.
    """
    measurable = peer_z_measurable(peer_count)
    return {
        "peer_count": int(peer_count) if peer_count is not None else None,
        "min_peers_for_z": MIN_PEERS_FOR_TOP_BAND,
        "z_produced": measurable,
        "policy": (None if measurable
                   else PEER_Z_POLICY.format(min_peers=MIN_PEERS_FOR_TOP_BAND)),
    }


# ── Method selection (spec §5 Layer 1) ────────────────────────────────────

def select_method(configured: Optional[str], series: Sequence[float],
                  indicator_type: str) -> str:
    """Pick the detection method for one series.

    auto: rare-event counts (mean < RARE_EVENT_MEAN_MAX) use rolling
    median + MAD — never plain z on small counts; then CV < CV_MAX =>
    pct_change; >= MIN_IQR_POINTS => iqr; else zscore. An explicit
    configured method always wins.
    """
    if configured and configured != METHOD_AUTO:
        return configured
    values = [float(v) for v in series]
    n = len(values)
    if n == 0:
        return METHOD_ZSCORE
    if (indicator_type == "count" and n >= 3
            and statistics.fmean(values) < RARE_EVENT_MEAN_MAX):
        return METHOD_ROLLING_MEDIAN_MAD
    if n >= 3 and coefficient_of_variation(values) < CV_MAX:
        return METHOD_PCT_CHANGE
    if n >= MIN_IQR_POINTS:
        return METHOD_IQR
    return METHOD_ZSCORE


# ── Input helpers: month history -> per-layer series ───────────────────────

def prior_months(history: Dict[str, Dict[str, float]], current_month: str,
                 window: Optional[int] = None) -> List[str]:
    """Sorted months strictly before current_month, newest ``window`` only.

    ``window=None`` keeps the legacy unbounded behaviour for callers that pass
    an already-prepared series; the engine always passes the shared policy
    window (see app.engine.comparison_policy).
    """
    months = sorted(m for m in history if m < current_month)
    return months[-window:] if window else months


def _sum_codes(values: Dict[str, float], codes: Sequence[str]) -> Optional[float]:
    total = 0.0
    for code in codes:
        v = values.get(code)
        if v is None:
            return None
        total += float(v)
    return total


def raw_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    """Raw analysis value for one month: summed numerator for rate rows,
    the indicator's own value for count rows."""
    if spec.is_rate:
        return _sum_codes(values, spec.numerator_codes)
    return values.get(spec.analysis_code)


def rate_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    num = _sum_codes(values, spec.numerator_codes)
    den = _sum_codes(values, spec.denominator_codes)
    if num is None or den is None or den == 0:
        return None
    return (num / den) * float(spec.rate_multiplier)


def denominator_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    return _sum_codes(values, spec.denominator_codes)


def score_window(method: str, series: Sequence[float], current: float,
                 previous: Optional[float], threshold: float) -> Optional[float]:
    """Public entry point: score `current` against a prepared window."""
    return _score_window(method, series, current, previous, threshold)


def score_window_detail(method: str, series: Sequence[float], current: float,
                        previous: Optional[float], threshold: float
                        ) -> Tuple[Optional[float], Optional[float]]:
    """Public: ``(score, percentage-change score before the cap)``.

    Both engines (Outlier Diagnostics and Quality Alerts) score through this
    one path, so a change-clamped comparison is graded identically on every
    screen and can record the underlying change evidence.
    """
    return _score_window_detail(method, series, current, previous, threshold)


def _score_window(method: str, series: Sequence[float], current: float,
                  previous: Optional[float], threshold: float) -> Optional[float]:
    """Score `current` against the prior window with the chosen method."""
    return _score_window_detail(method, series, current, previous, threshold)[0]


def _score_window_detail(method: str, series: Sequence[float], current: float,
                         previous: Optional[float], threshold: float
                         ) -> Tuple[Optional[float], Optional[float]]:
    """``(score, percentage-change score before the dispersion-aware cap)``.

    The second element is not None only when the cap actually lowered the
    score, so a caller can keep the underlying evidence beside the band it
    resolved to (see PCT_CHANGE_CAP_POLICY).
    """
    if method == METHOD_PCT_CHANGE:
        baseline = previous if previous is not None else mean(series)
        pct = percent_change(current, baseline)
        if pct is None:
            return None, None
        raw = score_from_pct_change(pct)
        capped = cap_pct_change(raw, series, current, threshold)
        return capped, (raw if capped is not None and capped < raw else None)
    if method == METHOD_ROLLING_MEDIAN_MAD:
        return score_from_mad(current, median(series), mad(series)), None
    if method == METHOD_IQR:
        q1, _q2, q3 = quartiles(series)
        return score_from_iqr(current, q1, q3), None
    # zscore (and any unknown value) — one shared threshold knob
    center = mean(series)
    sigma = std(series)
    if sigma is None:
        return score_from_mad(current, center, mad(series)), None
    if sigma == 0:
        return (0.0 if current == center else 1.0), None
    return score_from_z((current - center) / sigma, threshold), None


def _theil_sen(series: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """(slope, projected_next, residual_std) via Theil-Sen; None below
    MIN_TREND_POINTS. Residual std is 0 for a perfect line."""
    if len(series) < MIN_TREND_POINTS:
        return None
    x = list(range(len(series)))
    theil = getattr(scipy_stats, "theil_slopes", scipy_stats.theilslopes)
    slope, intercept, _, _ = theil(list(series), x)
    residuals = [y - (intercept + slope * i) for i, y in enumerate(series)]
    rstd = statistics.pstdev(residuals) if len(residuals) >= 2 else 0.0
    projected = intercept + slope * len(series)
    return float(slope), float(projected), float(rstd)


# ── Layer 1: raw value (spec §5) ──────────────────────────────────────────

@dataclass
class RawLayer:
    value: Optional[float]            # current raw analysis value
    previous: Optional[float]         # most recent non-None prior value
    change_percent: Optional[float]   # vs previous
    score: Optional[float]            # None = not applicable / not computable
    method: str
    # The score was built from a spread that is 0 (identical prior values), so
    # it cannot grade a magnitude (see cap_zero_spread).
    zero_spread: bool = False
    # The percentage-change score BEFORE the dispersion-aware cap (see
    # PCT_CHANGE_CAP_POLICY); None when that cap did not apply. Kept so the
    # change evidence stays readable when the level follows the z-score.
    pct_change_score: Optional[float] = None

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_raw_layer(spec: AnalysisSpec, prior: Sequence[Optional[float]],
                      current: Optional[float], history_ok: bool,
                      threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> RawLayer:
    """Layer 1 on the raw analysis value (numerator for rate rows).

    Not computable (history_ok False or current None) => score None and
    method insufficient_history; values are still reported for the row.
    """
    values = [float(v) for v in prior if v is not None]
    previous = values[-1] if values else None
    change = percent_change(current, previous)
    if not history_ok or current is None:
        return RawLayer(value=current, previous=previous, change_percent=change,
                        score=None, method=METHOD_INSUFFICIENT_HISTORY)
    if not values:
        return RawLayer(value=current, previous=None, change_percent=None,
                        score=None, method=METHOD_INSUFFICIENT_HISTORY)
    method = select_method(spec.outlier_method, values, spec.indicator_type)
    score, pct_before_cap = _score_window_detail(
        method, values, float(current), previous, threshold)
    return RawLayer(value=current, previous=previous, change_percent=change,
                    score=score, method=method,
                    zero_spread=no_dispersion(method, values,
                                              std_value=std(values)),
                    pct_change_score=pct_before_cap)


# ── Layer 3: historical baseline (spec §5) ────────────────────────────────

@dataclass
class HistoricalLayer:
    history_ok: bool
    series: List[float]               # baseline series (rate series for rate rows)
    current: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    std: Optional[float]
    z_score: Optional[float]          # None when std is None/0 (never inf)
    change_percent: Optional[float]   # current vs baseline mean
    score: Optional[float]
    method: str
    trend_slope: Optional[float] = None
    trend_projected: Optional[float] = None
    trend_residual_std: Optional[float] = None
    # Provenance: the exact window/observations this baseline used, so a stored
    # result can be reproduced without guessing today's policy.
    window: Optional[int] = None
    min_observations: Optional[int] = None
    window_months: List[str] = field(default_factory=list)
    skipped_months: List[str] = field(default_factory=list)
    # Percentage-change score before the dispersion-aware cap (see
    # RawLayer.pct_change_score); None when that cap did not apply.
    pct_change_score: Optional[float] = None

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)

    @property
    def zero_spread(self) -> bool:
        """The own-history baseline has no spread (see cap_zero_spread).

        Uses the method's own divisor: a MAD/IQR score is graded against MAD
        and IQR, which can be zero while the window's std is not, and
        trend_deviation against the residual spread.
        """
        return no_dispersion(self.method, self.series, std_value=self.std,
                             residual_std=self.trend_residual_std)


def compute_historical_layer(spec: AnalysisSpec, prior: Sequence[float],
                             current: Optional[float], history_ok: bool,
                             threshold: float = PEER_Z_THRESHOLD_DEFAULT,
                             *, policy: Optional[HistoryPolicy] = None,
                             months: Optional[Sequence[str]] = None) -> HistoricalLayer:
    """Layer 3 over the baseline series: window stats + method score, with
    optional Theil-Sen trend_deviation blending (spec §5 Layer 3).

    ``prior`` is already the policy window; ``months`` supplies the matching
    month labels purely for provenance.
    """
    series = [float(v) for v in prior if v is not None]
    window_months = [m for m, v in zip(months or (), prior, strict=False)
                     if v is not None]
    skipped_months = [m for m, v in zip(months or (), prior, strict=False)
                       if v is None]
    effective_policy = policy or HistoryPolicy(window=len(prior) or 0)
    provenance = dict(
        window=effective_policy.window,
        min_observations=effective_policy.min_observations,
        window_months=window_months,
        skipped_months=skipped_months,
    )
    win_mean = statistics.fmean(series) if series else None
    win_median = statistics.median(series) if series else None
    win_std = std(series)
    z: Optional[float] = None
    if win_std not in (None, 0) and current is not None and win_mean is not None:
        z = (float(current) - win_mean) / win_std
    change = percent_change(current, win_mean)

    if not spec.historical_enabled:
        return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                               mean=win_mean, median=win_median, std=win_std,
                               z_score=z, change_percent=change, score=None,
                               method=METHOD_INSUFFICIENT_HISTORY, **provenance)
    if not history_ok or current is None or not series:
        return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                               mean=win_mean, median=win_median, std=win_std,
                               z_score=z, change_percent=change, score=None,
                               method=METHOD_INSUFFICIENT_HISTORY, **provenance)

    window_method = select_method(spec.outlier_method, series, spec.indicator_type)
    window_score, pct_before_cap = _score_window_detail(
        window_method, series, float(current), series[-1], threshold)
    method, score = window_method, window_score

    if spec.outlier_method == METHOD_TREND_DEVIATION:
        trend = _theil_sen(series)
        if trend is not None:
            _slope, projected, rstd = trend
            trend_score = score_from_trend(float(current), projected, rstd)
            score = max(window_score if window_score is not None else 0.0, trend_score)
            return HistoricalLayer(
                history_ok=history_ok, series=series, current=current,
                mean=win_mean, median=win_median, std=win_std, z_score=z,
                change_percent=change, score=score,
                method=METHOD_TREND_DEVIATION,
                trend_slope=_slope, trend_projected=projected,
                trend_residual_std=rstd, **provenance)
        # < MIN_TREND_POINTS: window stats only (documented fallback)
        window_method = select_method(METHOD_AUTO, series, spec.indicator_type)
        method = window_method
        score, pct_before_cap = _score_window_detail(
            window_method, series, float(current), series[-1], threshold)

    return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                           mean=win_mean, median=win_median, std=win_std,
                           z_score=z, change_percent=change, score=score,
                           method=method, pct_change_score=pct_before_cap,
                           **provenance)


# ── Layer 2: rate (spec §5) ───────────────────────────────────────────────

@dataclass
class RateLayer:
    rate: Optional[float]            # observed rate for the month (always stored)
    score: Optional[float]           # None = not applicable / not computable
    method: str
    zero_spread: bool = False        # see RawLayer.zero_spread
    # See RawLayer.pct_change_score.
    pct_change_score: Optional[float] = None

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_rate_layer(spec: AnalysisSpec, prior_rates: Sequence[Optional[float]],
                       current_rate: Optional[float], history_ok: bool,
                       threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> RateLayer:
    """Layer 2: score the current rate against the hospital's own historical
    rates with the same method-selection logic as Layer 1. NULL layer for
    count rows; missing rate / insufficient history => score None."""
    if not spec.is_rate:
        return RateLayer(rate=None, score=None, method=METHOD_INSUFFICIENT_HISTORY)
    series = [float(v) for v in prior_rates if v is not None]
    if not history_ok or current_rate is None or not series:
        return RateLayer(rate=current_rate, score=None,
                         method=METHOD_INSUFFICIENT_HISTORY)
    method = select_method(spec.outlier_method, series, spec.indicator_type)
    score, pct_before_cap = _score_window_detail(
        method, series, float(current_rate), series[-1], threshold)
    return RateLayer(rate=current_rate, score=score, method=method,
                     zero_spread=no_dispersion(method, series,
                                               std_value=std(series)),
                     pct_change_score=pct_before_cap)


# ── Layer 4: volume / denominator (spec §5) ───────────────────────────────

@dataclass
class VolumeLayer:
    denominator: Optional[float]
    previous: Optional[float]       # most recent prior month with a denominator
    change_percent: Optional[float]
    score: Optional[float]
    den_ok: bool                    # denominator present and > 0

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_volume_layer(spec: AnalysisSpec,
                         prior_denominators: Sequence[Optional[float]],
                         current_denominator: Optional[float]) -> Optional[VolumeLayer]:
    """Layer 4: severity of the denominator shift. Returns None for count
    rows (no denominator concept — the entry records NULL and den_ok=True).
    Missing/zero denominator => den_ok False, score None: rate-dependent
    layers are not computable (never normal, never an outlier)."""
    if not spec.is_rate:
        return None
    series = [float(v) for v in prior_denominators if v is not None]
    previous = series[-1] if series else None
    if current_denominator is None:
        return VolumeLayer(denominator=None, previous=previous,
                           change_percent=None, score=None, den_ok=False)
    if float(current_denominator) <= 0:
        return VolumeLayer(denominator=float(current_denominator), previous=previous,
                           change_percent=None, score=None, den_ok=False)
    change = percent_change(float(current_denominator), previous)
    score = score_from_pct_change(change) if change is not None else None
    return VolumeLayer(denominator=float(current_denominator), previous=previous,
                       change_percent=change, score=score, den_ok=True)


def is_small_denominator(spec: AnalysisSpec, denominator: Optional[float]) -> bool:
    """Spec §5 small-denominator guard predicate. Dormant (False) until a
    minimum_denominator is configured on the spec."""
    if denominator is None or spec.minimum_denominator is None:
        return False
    return float(denominator) < float(spec.minimum_denominator)


# ── Layer 5: peer comparison (spec §5) ────────────────────────────────────

@dataclass
class PeerLayer:
    peer_mean: Optional[float]
    peer_count: int
    score: Optional[float]           # None = unavailable (no peers / disabled)
    method: str
    tier: Optional[str] = None       # tier that supplied the stats (not persisted)
    # The comparison group itself. Persistable stats (mean/count) lived here
    # alone, so every screen that had to NAME the peers rebuilt the group with
    # its own copy of the rule — and could name a different set than the one
    # that produced the score. The distribution travels with the result now.
    z: Optional[float] = None
    peer_std: Optional[float] = None
    peer_min: Optional[float] = None
    peer_max: Optional[float] = None
    peer_median: Optional[float] = None
    peer_values: Optional[Dict[Any, float]] = None   # hospital id -> value
    # Canonical group name + every eligible peer, even when fewer than the
    # minimum were available (provenance must show WHY the layer is NULL).
    group: Optional[str] = None
    eligible_ids: List[Any] = field(default_factory=list)
    eligible_count: int = 0
    min_peers: int = MIN_PEERS_DEFAULT

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)

    @property
    def zero_spread(self) -> bool:
        """Every member of the comparison group shares one value."""
        return zero_dispersion(self.peer_std, METHOD_PEER_ZSCORE)

    @property
    def z_measurable(self) -> bool:
        """Whether this group is large enough to produce a z-score."""
        return peer_z_measurable(self.peer_count)


def compute_peer_layer(spec: AnalysisSpec, self_id: Any,
                       current_value: Optional[float],
                       peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]],
                       threshold: float = PEER_Z_THRESHOLD_DEFAULT,
                       *, min_peers: Optional[int] = None) -> PeerLayer:
    """Layer 5: z-score of this hospital's value against OTHER active
    hospitals in the comparison group. Never forces an outlier from no peers.

    The caller decides the group (``peer_tiers``): the pipeline passes the one
    canonical group — every active hospital reporting the indicator this month
    — so no screen can quote a different baseline for the same month.
    ``min_peers`` is the shared eligibility floor; fewer peers means the layer
    is unavailable, and the eligible count is still recorded. A group that
    exists but cannot measure a spread is still scored — its z-score is not
    produced (PEER_Z_POLICY), so no screen can quote an unmeasured magnitude.
    """
    required = max(2, int(min_peers or MIN_PEERS_DEFAULT))
    if not spec.peer_comparison_enabled or current_value is None:
        return PeerLayer(peer_mean=None, peer_count=0, score=None,
                         method=METHOD_INSUFFICIENT_HISTORY, tier=None,
                         min_peers=required)
    eligible: Dict[Any, float] = {}
    eligible_group: Optional[str] = None
    for tier_name, tier_map in peer_tiers:
        others = {hid: float(v) for hid, v in tier_map.items()
                  if hid != self_id and v is not None}
        if len(others) > len(eligible):
            eligible, eligible_group = others, tier_name
        if len(others) >= required:
            values = list(others.values())
            peer_mean = statistics.fmean(values)
            peer_std = statistics.stdev(values)      # ddof=1 per spec
            if peer_std == 0:
                # Undefined (0/0), never 0.0: a z of zero means "at the mean",
                # which would contradict the 1.0 score below. Same rule as
                # HistoricalLayer.z_score, and the same NULL Quality Alerts
                # stores for a no-spread group.
                z = None
                score = 0.0 if float(current_value) == peer_mean else 1.0
            else:
                graded_z = (float(current_value) - peer_mean) / peer_std
                score = score_from_z(graded_z, threshold)
                # The deviation and its score stand; the z needs a measured
                # spread, which 2-3 peers cannot provide (PEER_Z_POLICY).
                z = graded_z if peer_z_measurable(len(values)) else None
            return PeerLayer(peer_mean=peer_mean, peer_count=len(values),
                             score=score, method=METHOD_PEER_ZSCORE,
                             tier=tier_name, z=z, peer_std=peer_std,
                             peer_min=min(values), peer_max=max(values),
                             peer_median=statistics.median(values),
                             peer_values=others, group=tier_name,
                             eligible_ids=sorted(others),
                             eligible_count=len(others),
                             min_peers=required)
    return PeerLayer(peer_mean=None, peer_count=0, score=None,
                     method=METHOD_INSUFFICIENT_HISTORY, tier=None,
                     group=eligible_group,
                     eligible_ids=sorted(eligible),
                     eligible_count=len(eligible),
                     min_peers=required)


# ── Entry point (spec §5) ──────────────────────────────────────────────────

@dataclass
class LayerResult:
    """All layer outputs + classification for one hospital x spec x month."""
    spec: AnalysisSpec
    month: str
    history_ok: bool
    raw: RawLayer
    rate: RateLayer
    historical: HistoricalLayer
    volume: Optional[VolumeLayer]       # None for count rows
    peer: PeerLayer
    classification: "Classification"


def analyze_layered_entry(
    spec: AnalysisSpec,
    history: Dict[str, Dict[str, float]],
    current_month: str,
    peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]],
    thresholds: Thresholds,
    *,
    self_id: Any = None,
    history_policy: Optional[HistoryPolicy] = None,
    peer_policy: Optional[PeerPolicy] = None,
) -> LayerResult:
    """Run the sequential layer pipeline for one analysis unit.

    `history` maps month -> indicator values and may include current_month
    (prior_months splits it). Layers run raw -> rate/volume -> historical ->
    peer -> classification (spec §5 ordering: peer never runs first).

    ``history_policy`` / ``peer_policy`` are the shared comparison policy.
    Omitting them keeps the documented defaults (last 12 reporting months,
    >= 3 valid observations, >= 2 peers), so a direct engine call can never
    silently use the retired unbounded window.
    """
    # Deferred: classify.py imports this module at top level.
    from app.engine.anomaly.classify import InterpretationNumbers, classify_layered

    policy = (history_policy or HistoryPolicy()).with_item_minimum(
        spec.minimum_history_period)
    peers = peer_policy or PeerPolicy()
    months = prior_months(history, current_month, policy.window)
    current_values = history.get(current_month, {})

    # Layer 1 — raw analysis value (numerator for rate rows).
    raw_series = [raw_analysis_value(spec, history[m]) for m in months]
    raw_value = raw_analysis_value(spec, current_values)
    baseline_series = (
        [rate_analysis_value(spec, history[m]) for m in months]
        if spec.is_rate else raw_series
    )

    # Minimum history counts VALID observations in the policy window, not
    # calendar months: three stored months with one computed value is not a
    # three-point baseline. The per-indicator floor is applied above.
    valid_observations = sum(1 for value in baseline_series if value is not None)
    history_ok = valid_observations >= policy.min_observations

    raw = compute_raw_layer(spec, raw_series, raw_value, history_ok,
                            thresholds.peer_z_threshold)

    # Layers 2 + 4 — rate and denominator (rate rows only).
    if spec.is_rate:
        rate_series = baseline_series
        current_rate = rate_analysis_value(spec, current_values)
        rate_layer = compute_rate_layer(spec, rate_series, current_rate,
                                        history_ok, thresholds.peer_z_threshold)
        den_series = [denominator_analysis_value(spec, history[m])
                      for m in months]
        current_den = denominator_analysis_value(spec, current_values)
        volume = compute_volume_layer(spec, den_series, current_den)
        baseline_current = current_rate
        den_ok = volume.den_ok                 # volume is not None for rates
        denominator_value = volume.denominator
        denominator_change = volume.change_percent
        rate_value = rate_layer.rate
    else:
        rate_layer = compute_rate_layer(spec, [], None, history_ok)
        volume = None
        baseline_current = raw_value
        den_ok = True
        denominator_value = None
        denominator_change = None
        rate_value = None

    # Layer 3 — historical baseline (rate history when the spec has a rate).
    historical = compute_historical_layer(spec, baseline_series,
                                          baseline_current, history_ok,
                                          thresholds.peer_z_threshold,
                                          policy=policy, months=months)

    # Layer 5 — peer comparison on this month's unit value.
    unit_value = rate_value if spec.is_rate else raw_value
    peer = compute_peer_layer(spec, self_id, unit_value, peer_tiers,
                              thresholds.peer_z_threshold,
                              min_peers=peers.min_peers)

    numbers = InterpretationNumbers(
        raw_value=raw_value,
        previous_value=raw.previous,
        raw_change_percent=raw.change_percent,
        rate=rate_value,
        denominator=denominator_value,
        denominator_change_percent=denominator_change,
        historical_mean=historical.mean,
        historical_change_percent=historical.change_percent,
        peer_mean=peer.peer_mean,
        peer_count=peer.peer_count,
        peer_score=peer.score,
    )
    # A layer whose score was built by dividing by a zero spread cannot grade
    # a magnitude; the classifier caps that layer's band at HIGH (per layer, so
    # a measured layer can still reach VERY_HIGH). Volume is absent on purpose:
    # it scores a percentage change, which stays measurable on a flat series.
    degenerate_layers = tuple(
        name for name, layer in (
            ("raw", raw), ("rate", rate_layer),
            ("historical", historical), ("peer", peer),
        ) if getattr(layer, "zero_spread", False)
    )
    # Layers whose percentage-change score was lowered to the score their own
    # window's z supports (PCT_CHANGE_CAP_POLICY). The classification explains
    # it, so a "+93% but not an outlier" row is never left unexplained.
    pct_change_capped = tuple(
        name for name, layer in (
            ("raw", raw), ("rate", rate_layer),
            ("historical", historical),
        ) if getattr(layer, "pct_change_score", None) is not None
    )
    # A peer comparison resting on fewer than MIN_PEERS_FOR_TOP_BAND other
    # hospitals cannot measure a spread, so its band is capped at HIGH
    # (THIN_PEER_POLICY). Only the peer layer: every other layer has its own
    # dispersion, and the peer score, z and peer list stay as computed.
    thin_peer_layers = (
        ("peer",)
        if peer.score is not None
        and thin_peer_group(peer.peer_count, METHOD_PEER_ZSCORE)
        else ()
    )
    classification = classify_layered(
        spec,
        raw_score=raw.score,
        rate_score=rate_layer.score,
        hist_score=historical.score,
        volume_score=volume.score if volume else None,
        peer_score=peer.score,
        den_ok=den_ok,
        history_ok=history_ok,
        change_percent=historical.change_percent,
        denominator=denominator_value,
        raw_method=raw.method,
        rate_method=rate_layer.method,
        hist_method=historical.method,
        peer_method=peer.method,
        numbers=numbers,
        degenerate_layers=degenerate_layers,
        pct_change_capped=pct_change_capped,
        thin_peer_layers=thin_peer_layers,
    )

    if spec.is_rate and rate_value is None:
        # A rate with no denominator (the required element was not reported)
        # has no unit value to compare. Its numerator jump is not evidence
        # about the rate, so the row must never be classified as an outlier —
        # otherwise an optional/missing source element produces a fake
        # VERY_HIGH finding and penalizes the Quality Score. The row itself is
        # still persisted (the gap stays visible in diagnostics).
        from dataclasses import replace as _replace

        from app.engine.anomaly.classify import TYPE_NORMAL
        classification = _replace(
            classification,
            outlier_level=LEVEL_NONE,
            outlier_type=TYPE_NORMAL,
            investigation_required=False,
            investigation_route="none",
            interpretation=(f"{classification.interpretation} "
                            "Rate not computable this month (denominator "
                            "missing or zero) - not classified as an outlier."),
        )

    return LayerResult(spec=spec, month=current_month, history_ok=history_ok,
                       raw=raw, rate=rate_layer, historical=historical,
                       volume=volume, peer=peer, classification=classification)


# ── Orchestration (spec §7: pipeline calls this per hospital/month) ────────


def canonical_peer_tiers(spec: AnalysisSpec,
                         unit_values: Dict[Any, Optional[float]]
                         ) -> List[Tuple[str, Dict[Any, Optional[float]]]]:
    """The comparison group for detection: every active hospital reporting the
    indicator this month (self included; ``compute_peer_layer`` drops it).

    Tiered comparison (type -> ownership -> governorate -> all) was retired: it
    made the same hospital/month an outlier on one screen and normal on another,
    because the Quality report, the Outlier screen, the audit benchmark and the
    Quality Score each quoted a different peer set. One baseline, one verdict.
    Quality Alerts keep their explicit multi-perspective comparisons — those are
    labelled comparisons, not the detection baseline.
    """
    if not spec.peer_comparison_enabled:
        return []
    return [("all", dict(unit_values))]


def run_layered_analysis(
    specs: Sequence[AnalysisSpec],
    history: Dict[str, Dict[str, float]],
    current_month: str,
    hospital_id: Any,
    peer_values_by_hospital: Dict[Any, Dict[str, Dict[str, float]]],
    peer_attributes: Dict[Any, Dict[str, Any]],
    thresholds: Thresholds,
    *,
    history_policy: Optional[HistoryPolicy] = None,
    peer_policy: Optional[PeerPolicy] = None,
) -> List[LayerResult]:
    """One LayerResult per spec for the analyzed hospital (the pipeline's
    per-hospital model). peer_values_by_hospital supplies the current-month
    values that form the canonical comparison group.

    ``peer_attributes`` is accepted for callers that still pass the hospital
    attributes the retired tiered comparison needed; it no longer influences
    detection.
    """
    results: List[LayerResult] = []
    for spec in specs:
        unit_values: Dict[Any, Optional[float]] = {}
        for hid, months_values in peer_values_by_hospital.items():
            current_values = months_values.get(current_month, {})
            if spec.is_rate:
                unit_values[hid] = rate_analysis_value(spec, current_values)
            else:
                unit_values[hid] = raw_analysis_value(spec, current_values)
        tiers = canonical_peer_tiers(spec, unit_values)
        results.append(analyze_layered_entry(
            spec, history, current_month, tiers, thresholds,
            self_id=hospital_id,
            history_policy=history_policy,
            peer_policy=peer_policy,
        ))
    return results


# Display names for the five detection layers, in evaluation order. One place
# so the Quality report strip, the Why popup and any future surface label a
# layer identically.
LAYER_LABELS: Dict[str, str] = {
    "raw": "Raw value",
    "rate": "Rate",
    "historical": "History",
    "volume": "Volume",
    "peer": "Peer comparison",
}


def layer_breakdown(row) -> List[Dict[str, Any]]:
    """The five layer scores stored on ONE outlier row, in evaluation order.

    ``row`` is a LayeredOutlierResult (or any object with the same column
    names). Nothing is recomputed: the scores and levels are the ones the
    engine persisted, and the level is mapped through ``level_for_score`` so
    the strip can never disagree with the stored classification. A layer that
    was not applicable/not computable keeps its entry with ``score=None``,
    ``level=None`` (the same NULL the engine stores) and ``applicable=False``
    — the report shows a complete strip instead of silently dropping a layer,
    and "never ran" is never rendered as "ran, found nothing".

    ``value`` is the number that layer actually looked at (raw value, rate,
    historical baseline mean, denominator volume, peer baseline mean); the
    richer peer statistics live next to it in the report payload.
    """
    if row is None:
        return []
    pairs = (
        ("raw", getattr(row, "raw_value", None),
         getattr(row, "raw_value_outlier_score", None)),
        ("rate", getattr(row, "rate", None),
         getattr(row, "rate_outlier_score", None)),
        ("historical", getattr(row, "historical_mean", None),
         getattr(row, "historical_outlier_score", None)),
        ("volume", getattr(row, "denominator", None),
         getattr(row, "volume_anomaly_score", None)),
        ("peer", getattr(row, "peer_mean", None),
         getattr(row, "peer_outlier_score", None)),
    )
    out: List[Dict[str, Any]] = []
    for key, value, score in pairs:
        out.append({
            "key": key,
            "name": LAYER_LABELS[key],
            "value": value,
            "score": score,
            "level": level_for_score(score),
            "applicable": score is not None,
        })
    return out


def should_persist(result: LayerResult) -> bool:
    """Keep rows where something was observed this month: the raw analysis
    value (numerator for rate rows) exists. A present numerator with a
    missing denominator still persists (scenario 9)."""
    return result.raw.value is not None


def _spec_key(spec: AnalysisSpec) -> tuple:
    """Canonical identity of the formula this spec evaluates.

    Delegates to the shared canonical identity (formula expression + unit
    scale) so a derived rate is deduplicated here and in Quality Alerts by the
    same rule, instead of each engine keeping its own key.
    """
    from app.engine.canonical_identity import ratio_identity

    return ratio_identity(spec.numerator_codes, spec.denominator_codes, "/",
                          spec.rate_multiplier, spec.unit)


def build_analysis_specs(session) -> List[AnalysisSpec]:
    """Every analysis unit: non-synthetic Indicator rows (data elements) plus
    the derived rates.

    Rates come from two places on purpose. ``rate_config`` holds the runtime
    tunables (thresholds, method, minimum denominator) and is the stable code
    space; the registry holds *which* derivative indicators exist and their
    editable formulas. Reading only rate_config made a clinical-only rate
    invisible to detection whenever its row had not been seeded, while the
    registry listed it — the scan must cover the catalog it claims to cover.
    A definition whose formula is already covered by a rate spec is skipped, so
    one rate never produces two rows.
    """
    from app.engine.rate_config import load_rate_specs
    from app.indicators import SYNTHETIC_INDICATOR_CODES
    from app.models import Indicator

    specs: List[AnalysisSpec] = []
    indicators = (
        session.query(Indicator)
        .filter(~Indicator.code.in_(SYNTHETIC_INDICATOR_CODES))
        .order_by(Indicator.id)
        .all()
    )
    for ind in indicators:
        specs.append(AnalysisSpec(
            analysis_code=ind.code,
            name=ind.name,
            indicator_type=ind.indicator_type or "count",
            indicator_id=ind.id,
            minimum_history_period=(ind.minimum_history_period
                                    or DEFAULT_MINIMUM_HISTORY),
            outlier_method=ind.outlier_method or METHOD_AUTO,
            historical_enabled=ind.historical_enabled is not False,
            peer_comparison_enabled=ind.peer_comparison_enabled is not False,
        ))
    covered: set = set()
    for rs in load_rate_specs(session).values():
        if not rs.is_active:
            continue
        spec = AnalysisSpec(
            analysis_code=rs.rate_code,
            name=rs.rate_name,
            indicator_type=rs.indicator_type,
            numerator_codes=tuple(rs.numerator_codes),
            denominator_codes=tuple(rs.denominator_codes),
            rate_multiplier=rs.rate_multiplier,
            unit=rs.unit,
            minimum_denominator=rs.minimum_denominator,
            minimum_history_period=rs.minimum_history_period,
            outlier_method=rs.outlier_method,
            historical_enabled=rs.historical_enabled,
            peer_comparison_enabled=rs.peer_comparison_enabled,
        )
        key = _spec_key(spec)
        if key in covered:
            # The registry stores one rate per analysis site (rate_cs, cs_rate)
            # with the same formula and scale; they compute the same number, so
            # a second row would only duplicate the same finding.
            continue
        covered.add(key)
        specs.append(spec)

    # Derivative definitions the rate_config slice does not know about.
    from app.engine import indicator_service
    for resolved in indicator_service.resolve_outlier_candidates(session):
        definition = getattr(resolved, "definition", None)
        if definition is None:
            continue
        numerators = tuple(definition.numerator_codes or ())
        denominators = tuple(definition.denominator_codes or ())
        if not numerators or not denominators:
            continue          # counts / expressions are not rate comparables
        spec = AnalysisSpec(
            analysis_code=resolved.code,
            name=resolved.name,
            indicator_type=(definition.result_type
                            or getattr(resolved, "indicator_type", None)
                            or "rate"),
            numerator_codes=numerators,
            denominator_codes=denominators,
            rate_multiplier=float(definition.multiplier or 1.0),
            unit=definition.unit or "",
        )
        if _spec_key(spec) in covered:
            continue
        covered.add(_spec_key(spec))
        specs.append(spec)
    return specs
