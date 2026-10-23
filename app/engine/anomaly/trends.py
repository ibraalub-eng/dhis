from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import numpy as np
from scipy import stats as scipy_stats

from app.engine import severity as severity_policy

from .comparison import HospitalComparison
from .zscore import compute_rate, RATE_DEFINITIONS, AnomalyResultData


_TRENDS_CONFIG = {
    "trend_slope_stable": 2.0,
    "trend_slope_low": 5.0,
    "trend_slope_moderate": 15.0,
    "trend_slope_high": 30.0,
    "trend_r_squared": 0.5,
    "trend_finding_slope": 5.0,
    # Reused persistence setting: its default lives in the shared spec so the
    # engine default, the seed and System Control validation cannot drift.
    "trend_finding_consecutive": severity_policy.TREND_SETTING_SPECS[
        "trend_finding_consecutive"].default,
    "trend_finding_deviation": 20.0,
    "trend_finding_cv": 30.0,
    "trend_finding_r_squared": 0.7,
    "zscore_threshold": 2.5,
}


def set_trends_config(config: dict):
    _TRENDS_CONFIG.update(config)


def _resolved_settings(config: Optional[dict] = None):
    """Effective trend controls for one call.

    The engine keeps its historical module-level defaults for callers that do
    not load the database, but every configured value (AppConfig category
    ``trends``) overrides them. Validation/defaults live in
    ``app.engine.severity`` so the engine, Quality Alerts and System Control
    cannot disagree about what a setting means.
    """
    merged = dict(_TRENDS_CONFIG)
    if config:
        merged.update(config)
    return severity_policy.resolve_trend_settings(merged)


def _resolved_bands(config: Optional[dict] = None) -> Dict[str, float]:
    merged = dict(_TRENDS_CONFIG)
    if config:
        merged.update(config)
    bands = severity_policy.default_trend_bands()
    for name, key, _default in severity_policy.BAND_KEYS:
        try:
            if key in merged:
                bands[name] = max(0.0, float(merged[key]))
        except (TypeError, ValueError):
            pass
    return bands


def _indicator_direction(resolved) -> Optional[str]:
    definition = getattr(resolved, "definition", None)
    direction = getattr(definition, "direction", None) if definition else None
    return direction or None


@dataclass
class TrendPoint:
    month: str
    value: float


@dataclass
class TrendResult:
    hospital: str
    indicator_code: str
    rate_name: str
    months: List[str]
    values: List[float]
    mean: float
    std: float
    slope: float
    slope_pct: float
    trend_direction: str
    trend_severity: str
    is_significant: bool
    cv: float
    last_vs_mean_pct_change: float
    consecutive_direction: str
    consecutive_count: int
    findings: List[str]
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None
    # Trend assessment under the saved System Control policy (direction gate,
    # persistence, cumulative change). None only for callers that build the
    # dataclass by hand; the engine always fills it.
    trend_assessment: Optional[Dict] = None


def _linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    result = scipy_stats.linregress(x, y)
    r_squared = result.rvalue ** 2
    return result.slope, result.intercept, r_squared


def _compute_trend_direction(slope: float, mean: float, r_squared: float, slope_pct: float,
                            bands: Optional[Dict[str, float]] = None) -> Tuple[str, str]:
    bands = bands or severity_policy.default_trend_bands()
    stable_thresh = bands["stable"]
    low_thresh = bands["low"]
    mod_thresh = bands["moderate"]
    high_thresh = bands["high"]
    if abs(slope_pct) < stable_thresh:
        direction = "stable"
    elif slope > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    abs_pct = abs(slope_pct)
    if abs_pct < stable_thresh:
        severity = "negligible"
    elif abs_pct < low_thresh:
        severity = "low"
    elif abs_pct < mod_thresh:
        severity = "moderate"
    elif abs_pct < high_thresh:
        severity = "high"
    else:
        severity = "critical"

    return direction, severity


def _compute_consecutive_trend(values: List[float]) -> Tuple[str, int]:
    if len(values) < 2:
        return "none", 0
    direction_counts = {"increasing": 0, "decreasing": 0}
    last_dir = None
    max_consecutive = 0
    current_consecutive = 0
    for i in range(len(values) - 1):
        diff = values[i + 1] - values[i]
        if abs(diff) < 0.001:
            continue
        current_dir = "increasing" if diff > 0 else "decreasing"
        if last_dir == current_dir:
            current_consecutive += 1
        else:
            current_consecutive = 1
            last_dir = current_dir
        if current_consecutive > max_consecutive:
            max_consecutive = current_consecutive
            direction_counts[current_dir] = max(direction_counts[current_dir], current_consecutive)
    if direction_counts["increasing"] >= 3:
        return "increasing", direction_counts["increasing"]
    elif direction_counts["decreasing"] >= 3:
        return "decreasing", direction_counts["decreasing"]
    best_dir = "increasing" if direction_counts["increasing"] >= direction_counts["decreasing"] else "decreasing"
    return best_dir, max_consecutive


def analyze_historical_trends(
    hospital_name: str,
    monthly_data: Dict[str, Dict[str, float]],
    additional_indicators=None,
    config: Optional[dict] = None,
) -> List[TrendResult]:
    """Analyse the configured window of months for trend results.

    ``config`` is the saved AppConfig ``trends`` slice (pipeline) or the
    validated slice returned by ``severity.load_analysis_config`` (API paths).
    Only the most recent ``trend_analysis_window`` months are used, at least
    ``trend_min_history_months`` usable periods are required, and the trend
    assessment attached to each row states whether the configured direction,
    persistence and cumulative-change gates were met.
    """
    results = []
    settings = _resolved_settings(config)
    bands = _resolved_bands(config)
    raw = dict(_TRENDS_CONFIG)
    if config:
        raw.update(config)
    if not settings.enabled:
        return results
    if not monthly_data:
        return results

    sorted_months = sorted(monthly_data.keys())[-settings.window:]
    if len(sorted_months) < settings.min_history:
        return results

    if additional_indicators is None:
        candidates = [
            (None, rate_name, num_code, den_code)
            for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS
        ]
    else:
        candidates = [
            (resolved, resolved.name, resolved.code, None)
            for resolved in additional_indicators
        ]

    from app.engine import indicator_service

    for resolved, rate_name, indicator_code, den_code in candidates:
        rate_values = []
        valid_months = []
        for month in sorted_months:
            vals = monthly_data[month]
            if resolved is None:
                rate = compute_rate(vals, indicator_code, den_code)
            else:
                result = indicator_service.calculate_from_values(
                    resolved, vals, hospital_id=0, month=month)
                rate = result.value if result.status == "ok" else None
            if rate is not None:
                rate_values.append(rate)
                valid_months.append(month)

        if len(rate_values) < settings.min_history:
            continue

        mean_val = float(np.mean(rate_values))
        std_val = float(np.std(rate_values))
        cv = (std_val / mean_val * 100) if mean_val != 0 else 0.0

        x = list(range(len(rate_values)))
        slope, intercept, r_squared = _linear_regression(x, rate_values)

        slope_pct = (slope / mean_val * 100) if mean_val != 0 else 0.0
        trend_direction, trend_severity = _compute_trend_direction(
            slope, mean_val, r_squared, slope_pct, bands=bands)

        is_significant = (r_squared > raw["trend_r_squared"]
                          or abs(slope_pct) > raw["trend_finding_slope"])
        trend_assessment = severity_policy.assess_trend(
            rate_values, valid_months, config=settings, bands=bands,
            indicator_direction=_indicator_direction(resolved),
        )
        # The configured direction gate also scopes "significant": a trend
        # moving the wrong way stays visible but is not reported as one. The
        # default ("any") leaves the historical significance rule untouched.
        if settings.trend_direction != "any" and not trend_assessment.direction_relevant:
            is_significant = False

        last_val = rate_values[-1]
        last_vs_mean_pct = ((last_val - mean_val) / mean_val * 100) if mean_val != 0 else 0.0

        consec_dir, consec_count = _compute_consecutive_trend(rate_values)

        findings = []
        if abs(slope_pct) > raw["trend_finding_slope"]:
            direction_word = "increasing" if slope > 0 else "decreasing"
            findings.append(f"{rate_name} shows a {direction_word} trend ({slope_pct:+.1f}% per month)")
        if consec_count >= raw["trend_finding_consecutive"]:
            findings.append(f"{consec_count} consecutive {consec_dir} months detected for {rate_name}")
        if abs(last_vs_mean_pct) > raw["trend_finding_deviation"]:
            findings.append(f"Last month deviates {last_vs_mean_pct:+.1f}% from mean for {rate_name}")
        if cv > raw["trend_finding_cv"]:
            findings.append(f"High variability (CV={cv:.1f}%) for {rate_name}")
        if r_squared > raw["trend_finding_r_squared"]:
            findings.append(f"Strong trend (R²={r_squared:.2f}) for {rate_name}")

        results.append(TrendResult(
            hospital=hospital_name,
            indicator_code=indicator_code,
            rate_name=rate_name,
            months=valid_months,
            values=[round(v, 2) for v in rate_values],
            mean=round(mean_val, 2),
            std=round(std_val, 2),
            slope=round(float(slope), 4),
            slope_pct=round(slope_pct, 2),
            trend_direction=trend_direction,
            trend_severity=trend_severity,
            is_significant=is_significant,
            cv=round(cv, 2),
            last_vs_mean_pct_change=round(last_vs_mean_pct, 2),
            consecutive_direction=consec_dir,
            consecutive_count=consec_count,
            findings=findings,
            indicator_id=resolved.indicator_id if resolved else None,
            formula=resolved.formula if resolved else None,
            formula_version=resolved.formula_version if resolved else None,
            trend_assessment=trend_assessment.as_dict(),
        ))

    return results


def detect_trend_anomalies(
    hospital_name: str,
    monthly_data: Dict[str, Dict[str, float]],
    additional_indicators=None,
    config: Optional[dict] = None,
) -> List[AnomalyResultData]:
    """Current month vs its own prior history, within the configured window."""
    results = []
    settings = _resolved_settings(config)
    if not settings.enabled:
        return results

    sorted_months = sorted(monthly_data.keys())[-settings.window:]
    if len(sorted_months) < max(3, settings.min_history):
        return results
    current_month = sorted_months[-1]
    current_values = monthly_data[current_month]

    if additional_indicators is None:
        candidates = [
            (None, rate_name, num_code, den_code)
            for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS
        ]
    else:
        candidates = [
            (resolved, resolved.name, resolved.code, None)
            for resolved in additional_indicators
        ]

    from app.engine import indicator_service

    for resolved, rate_name, indicator_code, den_code in candidates:
        if resolved is None:
            current_rate = compute_rate(current_values, indicator_code, den_code)
        else:
            current = indicator_service.calculate_from_values(
                resolved, current_values, hospital_id=0, month=current_month)
            current_rate = current.value if current.status == "ok" else None
        if current_rate is None:
            continue

        historical_rates = []
        for m in sorted_months[:-1]:
            if resolved is None:
                rate = compute_rate(monthly_data[m], indicator_code, den_code)
            else:
                result = indicator_service.calculate_from_values(
                    resolved, monthly_data[m], hospital_id=0, month=m)
                rate = result.value if result.status == "ok" else None
            if rate is not None:
                historical_rates.append(rate)

        if len(historical_rates) < 2:
            continue

        mean_h = float(np.mean(historical_rates))
        std_h = float(np.std(historical_rates))

        if std_h == 0:
            z = 0.0
        else:
            z = (current_rate - mean_h) / std_h

        z_threshold = float((config or {}).get(
            "zscore_threshold", _TRENDS_CONFIG["zscore_threshold"]))
        is_outlier = abs(z) > z_threshold

        if len(historical_rates) >= 3:
            x = list(range(len(historical_rates)))
            slope, intercept, _ = _linear_regression(x, historical_rates)
            projected = slope * len(historical_rates) + intercept
            if std_h > 0 and abs(current_rate - projected) > 2 * std_h:
                is_outlier = True

        results.append(AnomalyResultData(
            indicator_code=indicator_code,
            rate_name=f"{rate_name} (trend)",
            value=round(current_rate, 2),
            benchmark=round(mean_h, 2),
            z_score=round(float(z), 2),
            is_outlier=is_outlier,
            indicator_id=resolved.indicator_id if resolved else None,
            formula=resolved.formula if resolved else None,
            formula_version=resolved.formula_version if resolved else None,
        ))

    return results


def generate_historical_summary(
    trends: List[TrendResult],
    comparisons: List["HospitalComparison"],
    trend_anomalies: List[AnomalyResultData],
    cross_hospital_anomalies: List[AnomalyResultData],
) -> Dict:
    significant_trends = [t for t in trends if t.is_significant]
    increasing = [t for t in trends if t.trend_direction == "increasing"]
    decreasing = [t for t in trends if t.trend_direction == "decreasing"]
    stable = [t for t in trends if t.trend_direction == "stable"]

    critical_comparisons = [c for c in comparisons if "critically" in c.comparison_label]
    outlier_count = len([a for a in trend_anomalies if a.is_outlier])
    cross_outlier_count = len([a for a in cross_hospital_anomalies if a.is_outlier])

    return {
        "total_rates_analyzed": len(trends),
        "increasing_trends": len(increasing),
        "decreasing_trends": len(decreasing),
        "stable_trends": len(stable),
        "significant_trends": len(significant_trends),
        "critical_trends": len([t for t in trends if t.trend_severity == "critical"]),
        "trend_outliers": outlier_count,
        "cross_hospital_outliers": cross_outlier_count,
        "hospital_comparison_flags": len(critical_comparisons),
        "key_findings": [
            *["\u2191 " + t.findings[0] for t in trends if t.is_significant and t.findings][:5],
            *[f"{a.rate_name}: value={a.value}, benchmark={a.benchmark}, z={a.z_score}" for a in trend_anomalies if a.is_outlier][:3],
            *[f"{c.hospital} {c.rate_name}: {c.comparison_label} ({c.deviation_pct:+.1f}%)" for c in critical_comparisons[:3]],
        ],
    }
