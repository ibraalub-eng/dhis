from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from scipy import stats as scipy_stats

from .zscore import RATE_DEFINITIONS, compute_rate


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
    comparison_p_value: Optional[float] = None
    hospital_id: Optional[int] = None
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None


def peer_significance(rate: float, other_rates: List[float]) -> Optional[float]:
    """Two-sided one-sample t-test of the peer rates against this hospital's value.

    Valid for >=2 peers with some spread (unlike a t-test with a single-observation
    group). Returns None when there is nothing meaningful to test.
    """
    if len(other_rates) < 2 or len(set(other_rates)) < 2:
        return None
    _, p_val = scipy_stats.ttest_1samp(other_rates, rate)
    return round(float(p_val), 4)


def compare_hospitals(
    all_hospital_data: Dict[str, Dict[str, Dict[str, float]]],
    month: str,
    additional_indicators=None,
) -> List[HospitalComparison]:
    results = []
    from app.engine import indicator_service

    candidates = additional_indicators
    if candidates is None:
        candidates = []
        for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
            candidates.append((None, rate_name, num_code, den_code))
    else:
        candidates = [(resolved, resolved.name, resolved.code, None)
                      for resolved in candidates]

    for resolved, rate_name, indicator_code, den_code in candidates:
        rates = {}
        for hospital_name, monthly_data in all_hospital_data.items():
            if month not in monthly_data:
                continue
            if resolved is None:
                value = compute_rate(
                    monthly_data[month], indicator_code, den_code)
            else:
                result = indicator_service.calculate_from_values(
                    resolved, monthly_data[month], hospital_id=0, month=month)
                value = result.value if result.status == "ok" else None
            if value is not None:
                rates[hospital_name] = value
        results.extend(_comparison_rows(
            rates,
            rate_name,
            indicator_code,
            indicator_id=resolved.indicator_id if resolved else None,
            formula=resolved.formula if resolved else None,
            formula_version=resolved.formula_version if resolved else None,
        ))

    return results


def _comparison_rows(
    rates: Dict[str, float],
    rate_name: str,
    indicator_code: str,
    indicator_id: Optional[str] = None,
    formula: Optional[str] = None,
    formula_version: Optional[str] = None,
) -> List[HospitalComparison]:
    if len(rates) < 2:
        return []
    rate_values = list(rates.values())
    results = []
    for hospital_name, rate in rates.items():
        other_rates = [
            value for name, value in rates.items() if name != hospital_name
        ]
        benchmark = (
            float(np.mean(other_rates))
            if other_rates else float(np.mean(rate_values))
        )
        if other_rates:
            below = sum(1 for peer in other_rates if peer < rate)
            equal = sum(1 for peer in other_rates if peer == rate)
            percentile = round((below + 0.5 * equal) / len(other_rates) * 100, 1)
        else:
            percentile = 50.0
        deviation = ((rate - benchmark) / benchmark * 100) if benchmark != 0 else 0.0
        p_value = peer_significance(rate, other_rates) if len(rate_values) >= 3 else None
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
            hospital=hospital_name,
            indicator_code=indicator_code,
            rate_name=rate_name,
            value=round(rate, 2),
            benchmark=round(benchmark, 2),
            deviation_pct=round(deviation, 2),
            percentile_rank=round(percentile, 1),
            comparison_label=label,
            comparison_p_value=p_value,
            hospital_id=None,
            indicator_id=indicator_id,
            formula=formula,
            formula_version=formula_version,
        ))
    return results
