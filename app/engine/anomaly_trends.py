# =============================================================================
# engine/anomaly_trends.py -- Merged anomaly + trends module
# =============================================================================

# Source: anomaly.py

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class AnomalyResultData:
    indicator_code: str
    rate_name: str
    value: Optional[float]
    benchmark: Optional[float]
    z_score: Optional[float]
    is_outlier: bool


def compute_rate(values: Dict[str, float], numerator_code: str, denominator_code: str) -> Optional[float]:
    num = values.get(numerator_code)
    den = values.get(denominator_code)
    if num is None or den is None or den == 0:
        return None
    return (num / den) * 100


RATE_DEFINITIONS = [
    ("C-section rate", "5", "2", 50.0),
    ("Maternal mortality ratio", "11", "2", 1.0),
    ("Neonatal mortality rate", "17", "6", 30.0),
    ("Preterm birth rate", "6.f", "6", 15.0),
    ("SMM rate", "10", "2", 10.0),
    ("Stillbirth rate", "7", "2", 5.0),
    ("NICU admission rate", "16", "6", 20.0),
]


def detect_anomalies(
    all_hospital_data: Dict[str, Dict[str, float]],
    current_hospital: str,
    month: str,
    config: Optional[dict] = None,
) -> List[AnomalyResultData]:
    results = []
    z_thresh = (config or {}).get("zscore_threshold", 2.5)
    for rate_name, num_code, den_code, typical_pct in RATE_DEFINITIONS:
        rates = {}
        for hosp_name, hosp_values in all_hospital_data.items():
            rate = compute_rate(hosp_values, num_code, den_code)
            if rate is not None:
                rates[hosp_name] = rate
        if len(rates) < 2:
            continue
        rate_values = list(rates.values())
        mean_rate = np.mean(rate_values)
        std_rate = np.std(rate_values)
        current_values = all_hospital_data.get(current_hospital, {})
        current_rate = compute_rate(current_values, num_code, den_code)
        if current_rate is None:
            continue
        if std_rate == 0:
            z_score = 0.0
        else:
            z_score = (current_rate - mean_rate) / std_rate
        is_outlier = abs(z_score) > z_thresh
        results.append(
            AnomalyResultData(
                indicator_code=num_code,
                rate_name=rate_name,
                value=round(current_rate, 2),
                benchmark=round(mean_rate, 2),
                z_score=round(z_score, 2),
                is_outlier=is_outlier,
            )
        )
    return results


def detect_monthly_trend(
    historical_months: Dict[str, Dict[str, float]],
    current_month: str,
    current_values: Dict[str, float],
    config: Optional[dict] = None,
) -> List[AnomalyResultData]:
    results = []
    z_thresh = (config or {}).get("zscore_threshold", 2.5)
    if len(historical_months) < 2:
        return results
    for rate_name, num_code, den_code, typical_pct in RATE_DEFINITIONS:
        current_rate = compute_rate(current_values, num_code, den_code)
        if current_rate is None:
            continue
        historical_rates = []
        for month, m_values in historical_months.items():
            if month == current_month:
                continue
            rate = compute_rate(m_values, num_code, den_code)
            if rate is not None:
                historical_rates.append(rate)
        if len(historical_rates) < 2:
            continue
        mean_h = np.mean(historical_rates)
        std_h = np.std(historical_rates)
        if std_h == 0:
            z = 0.0
        else:
            z = (current_rate - mean_h) / std_h
        is_outlier = abs(z) > z_thresh
        results.append(
            AnomalyResultData(
                indicator_code=num_code,
                rate_name=f"{rate_name} (trend)",
                value=round(current_rate, 2),
                benchmark=round(mean_h, 2),
                z_score=round(z, 2),
                is_outlier=is_outlier,
            )
        )
    return results


from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


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


@dataclass
class HospitalComparison:
    hospital: str
    indicator_code: str
    rate_name: str
    value: float
    benchmark: float
    deviation_pct: float
    percentile_rank: float
    comparison_label: str


@dataclass
class HistoricalAnalysisResult:
    hospital: str
    months_analyzed: List[str]
    trends: List[TrendResult]
    hospital_comparisons: List[HospitalComparison]
    cross_hospital_anomalies: List[AnomalyResultData]
    trend_anomalies: List[AnomalyResultData]
    summary: Dict


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


def compare_hospitals(
    all_hospital_data: Dict[str, Dict[str, Dict[str, float]]],
    month: str,
) -> List[HospitalComparison]:
    results = []
    for rate_name, num_code, den_code, typical_pct in RATE_DEFINITIONS:
        rates = {}
        for hosp_name, monthly_data in all_hospital_data.items():
            if month in monthly_data:
                vals = monthly_data[month]
                rate = compute_rate(vals, num_code, den_code)
                if rate is not None:
                    rates[hosp_name] = rate

        if len(rates) < 2:
            continue

        rate_vals = list(rates.values())
        benchmark = float(np.mean(rate_vals))

        sorted_rates = sorted(rate_vals)
        n = len(sorted_rates)

        for hosp_name, rate in rates.items():
            rank_idx = sorted_rates.index(rate) if rate in sorted_rates else 0
            percentile = (rank_idx / (n - 1) * 100) if n > 1 else 50.0
            deviation = ((rate - benchmark) / benchmark * 100) if benchmark != 0 else 0.0

            if abs(deviation) < 10:
                label = "normal"
            elif deviation > 0:
                label = "above average"
            else:
                label = "below average"

            if abs(deviation) > 50:
                label = "critically " + label
            elif abs(deviation) > 25:
                label = "significantly " + label

            results.append(HospitalComparison(
                hospital=hosp_name,
                indicator_code=num_code,
                rate_name=rate_name,
                value=round(rate, 2),
                benchmark=round(benchmark, 2),
                deviation_pct=round(deviation, 2),
                percentile_rank=round(percentile, 1),
                comparison_label=label,
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
    historical_months = {m: monthly_data[m] for m in sorted_months[:-1]}

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

        mu = float(np.mean(historical_rates[:-1])) if len(historical_rates) > 2 else mean_h
        sigma = float(np.std(historical_rates[:-1])) if len(historical_rates) > 2 else std_h
        drift_pct = ((current_rate - mu) / mu * 100) if mu != 0 else 0.0

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
    comparisons: List[HospitalComparison],
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

    high_severity_trends = [t for t in trends if t.trend_severity in ("high", "critical")]

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
            *["↑ " + f.finding for t in trends for f in [] if t.findings for f in [t.findings[0]] if t.is_significant][:5],
            *[f"{a.rate_name}: value={a.value}, benchmark={a.benchmark}, z={a.z_score}" for a in trend_anomalies if a.is_outlier][:3],
            *[f"{c.hospital} {c.rate_name}: {c.comparison_label} ({c.deviation_pct:+.1f}%)" for c in critical_comparisons[:3]],
        ],
    }
