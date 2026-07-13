from typing import List, Dict
from dataclasses import dataclass
import numpy as np

from .zscore import compute_rate, RATE_DEFINITIONS


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
