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
) -> List[HospitalComparison]:
    results = []
    for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
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

        for hosp_name, rate in rates.items():
            # Benchmark and percentile are peer-relative: the hospital itself is
            # excluded, matching the audit benchmark screen and anomaly engine.
            other_rates = [v for h, v in rates.items() if h != hosp_name]
            benchmark = float(np.mean(other_rates)) if other_rates else float(np.mean(rate_vals))

            if other_rates:
                below = sum(1 for p in other_rates if p < rate)
                equal = sum(1 for p in other_rates if p == rate)
                percentile = round((below + 0.5 * equal) / len(other_rates) * 100, 1)
            else:
                percentile = 50.0

            deviation = ((rate - benchmark) / benchmark * 100) if benchmark != 0 else 0.0
            p_value = peer_significance(rate, other_rates) if len(rate_vals) >= 3 else None

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
                comparison_p_value=p_value,
                hospital_id=None,
            ))

    return results
