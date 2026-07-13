import numpy as np
from typing import List, Dict, Optional
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
        std_rate = np.std(rate_values, ddof=1) if len(rate_values) > 1 else 0
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
        std_h = np.std(historical_rates, ddof=1) if len(historical_rates) > 1 else 0
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
