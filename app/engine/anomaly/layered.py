"""Layered outlier analysis engine — scoring core (design spec 2026-10-08 §5).

Pure functions and constants; no DB access, no I/O, no app imports at module
level. The pipeline (app/engine/pipeline.py) gathers history/peers and
persists results; classification lives in app/engine/anomaly/classify.py.

Every layer maps a deviation to a 0-1 score which maps to a severity band:
<0.25 NONE | <0.50 LOW | <0.75 MODERATE | <0.90 HIGH | >=0.90 VERY_HIGH.
"""
import math
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from scipy import stats as scipy_stats

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

def prior_months(history: Dict[str, Dict[str, float]], current_month: str) -> List[str]:
    """Sorted months strictly before current_month."""
    return sorted(m for m in history if m < current_month)


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


def _score_window(method: str, series: Sequence[float], current: float,
                  previous: Optional[float], threshold: float) -> Optional[float]:
    """Score `current` against the prior window with the chosen method."""
    if method == METHOD_PCT_CHANGE:
        pct = percent_change(current, previous if previous is not None else mean(series))
        return None if pct is None else score_from_pct_change(pct)
    if method == METHOD_ROLLING_MEDIAN_MAD:
        return score_from_mad(current, median(series), mad(series))
    if method == METHOD_IQR:
        q1, _q2, q3 = quartiles(series)
        return score_from_iqr(current, q1, q3)
    # zscore (and any unknown value) — one shared threshold knob
    center = mean(series)
    sigma = std(series)
    if sigma is None:
        return score_from_mad(current, center, mad(series))
    if sigma == 0:
        return 0.0 if current == center else 1.0
    return score_from_z((current - center) / sigma, threshold)


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
    score = _score_window(method, values, float(current), previous, threshold)
    return RawLayer(value=current, previous=previous, change_percent=change,
                    score=score, method=method)


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

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_historical_layer(spec: AnalysisSpec, prior: Sequence[float],
                             current: Optional[float], history_ok: bool,
                             threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> HistoricalLayer:
    """Layer 3 over the baseline series: window stats + method score, with
    optional Theil-Sen trend_deviation blending (spec §5 Layer 3)."""
    series = [float(v) for v in prior if v is not None]
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
                               method=METHOD_INSUFFICIENT_HISTORY)
    if not history_ok or current is None or not series:
        return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                               mean=win_mean, median=win_median, std=win_std,
                               z_score=z, change_percent=change, score=None,
                               method=METHOD_INSUFFICIENT_HISTORY)

    window_method = select_method(spec.outlier_method, series, spec.indicator_type)
    window_score = _score_window(window_method, series, float(current),
                                 series[-1], threshold)
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
                trend_residual_std=rstd)
        # < MIN_TREND_POINTS: window stats only (documented fallback)
        window_method = select_method(METHOD_AUTO, series, spec.indicator_type)
        method = window_method
        score = _score_window(window_method, series, float(current),
                              series[-1], threshold)

    return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                           mean=win_mean, median=win_median, std=win_std,
                           z_score=z, change_percent=change, score=score,
                           method=method)


# ── Layer 2: rate (spec §5) ───────────────────────────────────────────────

@dataclass
class RateLayer:
    rate: Optional[float]            # observed rate for the month (always stored)
    score: Optional[float]           # None = not applicable / not computable
    method: str

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
    score = _score_window(method, series, float(current_rate), series[-1], threshold)
    return RateLayer(rate=current_rate, score=score, method=method)


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

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_peer_layer(spec: AnalysisSpec, self_id: Any,
                       current_value: Optional[float],
                       peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]],
                       threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> PeerLayer:
    """Layer 5: z-score of this hospital's value against OTHER active
    hospitals, first tier with >= 2 other members wins (type -> ownership ->
    governorate -> all). Never forces an outlier from no peers."""
    if not spec.peer_comparison_enabled or current_value is None:
        return PeerLayer(peer_mean=None, peer_count=0, score=None,
                         method=METHOD_INSUFFICIENT_HISTORY, tier=None)
    for tier_name, tier_map in peer_tiers:
        others = [float(v) for hid, v in tier_map.items()
                  if hid != self_id and v is not None]
        if len(others) >= 2:
            peer_mean = statistics.fmean(others)
            peer_std = statistics.stdev(others)      # ddof=1 per spec
            if peer_std == 0:
                score = 0.0 if float(current_value) == peer_mean else 1.0
            else:
                score = score_from_z((float(current_value) - peer_mean) / peer_std,
                                     threshold)
            return PeerLayer(peer_mean=peer_mean, peer_count=len(others),
                             score=score, method=METHOD_PEER_ZSCORE, tier=tier_name)
    return PeerLayer(peer_mean=None, peer_count=0, score=None,
                     method=METHOD_INSUFFICIENT_HISTORY, tier=None)


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
) -> LayerResult:
    """Run the sequential layer pipeline for one analysis unit.

    `history` maps month -> indicator values and may include current_month
    (prior_months splits it). Layers run raw -> rate/volume -> historical ->
    peer -> classification (spec §5 ordering: peer never runs first).
    """
    # Deferred: classify.py imports this module at top level.
    from app.engine.anomaly.classify import InterpretationNumbers, classify_layered

    months = prior_months(history, current_month)
    current_values = history.get(current_month, {})
    history_ok = len(months) >= spec.minimum_history_period

    # Layer 1 — raw analysis value (numerator for rate rows).
    raw_series = [raw_analysis_value(spec, history[m]) for m in months]
    raw_value = raw_analysis_value(spec, current_values)
    raw = compute_raw_layer(spec, raw_series, raw_value, history_ok,
                            thresholds.peer_z_threshold)

    # Layers 2 + 4 — rate and denominator (rate rows only).
    if spec.is_rate:
        rate_series = [rate_analysis_value(spec, history[m]) for m in months]
        current_rate = rate_analysis_value(spec, current_values)
        rate_layer = compute_rate_layer(spec, rate_series, current_rate,
                                        history_ok, thresholds.peer_z_threshold)
        den_series = [denominator_analysis_value(spec, history[m])
                      for m in months]
        current_den = denominator_analysis_value(spec, current_values)
        volume = compute_volume_layer(spec, den_series, current_den)
        baseline_series, baseline_current = rate_series, current_rate
        den_ok = volume.den_ok                 # volume is not None for rates
        denominator_value = volume.denominator
        denominator_change = volume.change_percent
        rate_value = rate_layer.rate
    else:
        rate_layer = compute_rate_layer(spec, [], None, history_ok)
        volume = None
        baseline_series, baseline_current = raw_series, raw_value
        den_ok = True
        denominator_value = None
        denominator_change = None
        rate_value = None

    # Layer 3 — historical baseline (rate history when the spec has a rate).
    historical = compute_historical_layer(spec, baseline_series,
                                          baseline_current, history_ok,
                                          thresholds.peer_z_threshold)

    # Layer 5 — peer comparison on this month's unit value.
    unit_value = rate_value if spec.is_rate else raw_value
    peer = compute_peer_layer(spec, self_id, unit_value, peer_tiers,
                              thresholds.peer_z_threshold)

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
        numbers=numbers,
    )
    return LayerResult(spec=spec, month=current_month, history_ok=history_ok,
                       raw=raw, rate=rate_layer, historical=historical,
                       volume=volume, peer=peer, classification=classification)


# ── Orchestration (spec §7: pipeline calls this per hospital/month) ────────

_PEER_TIER_KEYS = (("type", "type"), ("ownership", "ownership"),
                   ("governorate", "governorate"))


def build_peer_tiers(spec: AnalysisSpec, self_id: Any,
                     unit_values: Dict[Any, Optional[float]],
                     peer_attributes: Dict[Any, Dict[str, Any]]
                     ) -> List[Tuple[str, Dict[Any, Optional[float]]]]:
    """Ordered tier list type -> ownership -> governorate -> all.

    A typed tier is skipped when the hospital's own attribute is None; all
    hospitals in unit_values belong to the 'all' tier. Returns [] when the
    spec disables peer comparison.
    """
    if not spec.peer_comparison_enabled:
        return []
    attrs_self = peer_attributes.get(self_id, {})
    tiers: List[Tuple[str, Dict[Any, Optional[float]]]] = []
    for key, label in _PEER_TIER_KEYS:
        value = attrs_self.get(key)
        if value is None:
            continue
        members = {
            hid: unit_values.get(hid)
            for hid in unit_values
            if peer_attributes.get(hid, {}).get(key) == value
        }
        tiers.append((f"{label}:{value}", members))
    tiers.append(("all", dict(unit_values)))
    return tiers


def run_layered_analysis(
    specs: Sequence[AnalysisSpec],
    history: Dict[str, Dict[str, float]],
    current_month: str,
    hospital_id: Any,
    peer_values_by_hospital: Dict[Any, Dict[str, Dict[str, float]]],
    peer_attributes: Dict[Any, Dict[str, Any]],
    thresholds: Thresholds,
) -> List[LayerResult]:
    """One LayerResult per spec for the analyzed hospital (the pipeline's
    per-hospital model). peer_values_by_hospital supplies the current-month
    values used to build each spec's peer tiers."""
    results: List[LayerResult] = []
    for spec in specs:
        unit_values: Dict[Any, Optional[float]] = {}
        for hid, months_values in peer_values_by_hospital.items():
            current_values = months_values.get(current_month, {})
            if spec.is_rate:
                unit_values[hid] = rate_analysis_value(spec, current_values)
            else:
                unit_values[hid] = raw_analysis_value(spec, current_values)
        tiers = build_peer_tiers(spec, hospital_id, unit_values,
                                 peer_attributes)
        results.append(analyze_layered_entry(spec, history, current_month,
                                             tiers, thresholds,
                                             self_id=hospital_id))
    return results


def should_persist(result: LayerResult) -> bool:
    """Keep rows where something was observed this month: the raw analysis
    value (numerator for rate rows) exists. A present numerator with a
    missing denominator still persists (scenario 9)."""
    return result.raw.value is not None


def build_analysis_specs(session) -> List[AnalysisSpec]:
    """Count specs from non-synthetic Indicator rows + rate specs from the
    rate_config registry (Task 6)."""
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
    for rs in load_rate_specs(session).values():
        if not rs.is_active:
            continue
        specs.append(AnalysisSpec(
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
        ))
    return specs
