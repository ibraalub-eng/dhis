from typing import List, Dict, Tuple
from dataclasses import dataclass
import numpy as np

from .zscore import compute_rate, RATE_DEFINITIONS, AnomalyResultData
from .comparison import HospitalComparison


_TRENDS_CONFIG = {
    "trend_slope_stable": 2.0,
    "trend_slope_low": 5.0,
    "trend_slope_moderate": 15.0,
    "trend_slope_high": 30.0,
    "trend_r_squared": 0.5,
    "trend_finding_slope": 5.0,
    "trend_finding_consecutive": 3,
    "trend_finding_deviation": 20.0,
    "trend_finding_cv": 30.0,
    "trend_finding_r_squared": 0.7,
    "zscore_threshold": 2.5,
}


def set_trends_config(config: dict):
    _TRENDS_CONFIG.update(config)


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


def _linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    x_arr = np.array(x, dtype=float)
    y_arr = np.array(y, dtype=float)
    x_mean = np.mean(x_arr)
    y_mean = np.mean(y_arr)
    ss_xy = np.sum((x_arr - x_mean) * (y_arr - y_mean))
    ss_xx = np.sum((x_arr - x_mean) ** 2)
    if ss_xx == 0:
        return 0.0, 0.0, 0.0
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    y_pred = slope * x_arr + intercept
    ss_res = np.sum((y_arr - y_pred) ** 2)
    ss_tot = np.sum((y_arr - y_mean) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, r_squared


def _compute_trend_direction(slope: float, mean: float, r_squared: float, slope_pct: float) -> Tuple[str, str]:
    stable_thresh = _TRENDS_CONFIG["trend_slope_stable"]
    low_thresh = _TRENDS_CONFIG["trend_slope_low"]
    mod_thresh = _TRENDS_CONFIG["trend_slope_moderate"]
    high_thresh = _TRENDS_CONFIG["trend_slope_high"]
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
) -> List[TrendResult]:
    results = []
    if len(monthly_data) < 2:
        return results

    sorted_months = sorted(monthly_data.keys())

    for rate_name, num_code, den_code, typical_pct in RATE_DEFINITIONS:
        rate_values = []
        valid_months = []
        for month in sorted_months:
            vals = monthly_data[month]
            rate = compute_rate(vals, num_code, den_code)
            if rate is not None:
                rate_values.append(rate)
                valid_months.append(month)

        if len(rate_values) < 2:
            continue

        mean_val = float(np.mean(rate_values))
        std_val = float(np.std(rate_values))
        cv = (std_val / mean_val * 100) if mean_val != 0 else 0.0

        x = list(range(len(rate_values)))
        slope, intercept, r_squared = _linear_regression(x, rate_values)

        slope_pct = (slope / mean_val * 100) if mean_val != 0 else 0.0
        trend_direction, trend_severity = _compute_trend_direction(slope, mean_val, r_squared, slope_pct)

        is_significant = r_squared > _TRENDS_CONFIG["trend_r_squared"] or abs(slope_pct) > _TRENDS_CONFIG["trend_finding_slope"]

        last_val = rate_values[-1]
        last_vs_mean_pct = ((last_val - mean_val) / mean_val * 100) if mean_val != 0 else 0.0

        consec_dir, consec_count = _compute_consecutive_trend(rate_values)

        findings = []
        if abs(slope_pct) > _TRENDS_CONFIG["trend_finding_slope"]:
            direction_word = "increasing" if slope > 0 else "decreasing"
            findings.append(f"{rate_name} shows a {direction_word} trend ({slope_pct:+.1f}% per month)")
        if consec_count >= _TRENDS_CONFIG["trend_finding_consecutive"]:
            findings.append(f"{consec_count} consecutive {consec_dir} months detected for {rate_name}")
        if abs(last_vs_mean_pct) > _TRENDS_CONFIG["trend_finding_deviation"]:
            findings.append(f"Last month deviates {last_vs_mean_pct:+.1f}% from mean for {rate_name}")
        if cv > _TRENDS_CONFIG["trend_finding_cv"]:
            findings.append(f"High variability (CV={cv:.1f}%) for {rate_name}")
        if r_squared > _TRENDS_CONFIG["trend_finding_r_squared"]:
            findings.append(f"Strong trend (R²={r_squared:.2f}) for {rate_name}")

        results.append(TrendResult(
            hospital=hospital_name,
            indicator_code=num_code,
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
        ))

    return results


def detect_trend_anomalies(
    hospital_name: str,
    monthly_data: Dict[str, Dict[str, float]],
) -> List[AnomalyResultData]:
    results = []
    if len(monthly_data) < 3:
        return results

    sorted_months = sorted(monthly_data.keys())
    current_month = sorted_months[-1]
    current_values = monthly_data[current_month]

    for rate_name, num_code, den_code, typical_pct in RATE_DEFINITIONS:
        current_rate = compute_rate(current_values, num_code, den_code)
        if current_rate is None:
            continue

        historical_rates = []
        for m in sorted_months[:-1]:
            rate = compute_rate(monthly_data[m], num_code, den_code)
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

        is_outlier = abs(z) > _TRENDS_CONFIG["zscore_threshold"]

        _mu = float(np.mean(historical_rates[:-1])) if len(historical_rates) > 2 else mean_h

        if abs(z) > _TRENDS_CONFIG["zscore_threshold"]:
            is_outlier = True

        if len(historical_rates) >= 3:
            x = list(range(len(historical_rates)))
            slope, _, _ = _linear_regression(x, historical_rates)
            projected = slope * len(historical_rates) + (historical_rates[0] if historical_rates else mean_h)
            if std_h > 0 and abs(current_rate - projected) > 2 * std_h:
                is_outlier = True

        results.append(AnomalyResultData(
            indicator_code=num_code,
            rate_name=f"{rate_name} (trend)",
            value=round(current_rate, 2),
            benchmark=round(mean_h, 2),
            z_score=round(float(z), 2),
            is_outlier=is_outlier,
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
            *["\u2191 " + f.finding for t in trends for f in [] if t.findings for f in [t.findings[0]] if t.is_significant][:5],
            *[f"{a.rate_name}: value={a.value}, benchmark={a.benchmark}, z={a.z_score}" for a in trend_anomalies if a.is_outlier][:3],
            *[f"{c.hospital} {c.rate_name}: {c.comparison_label} ({c.deviation_pct:+.1f}%)" for c in critical_comparisons[:3]],
        ],
    }
