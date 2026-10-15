from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats as scipy_stats

from app.engine.rate_config import compute_rate as _registry_compute_rate
from app.engine.rate_config import zscore_spec_for, zscore_specs


@dataclass
class AnomalyResultData:
    indicator_code: str
    rate_name: str
    value: Optional[float]
    benchmark: Optional[float]
    z_score: Optional[float]
    is_outlier: bool
    # Peer metadata — matches the audit benchmark screen so both views agree
    # on where the benchmark came from. None for trend anomalies (benchmark
    # is the hospital's own historical mean, not a peer set).
    peer_count: Optional[int] = None
    peer_std: Optional[float] = None
    peer_min: Optional[float] = None
    peer_max: Optional[float] = None
    peer_median: Optional[float] = None
    # [{"hospital": name, "rate": rounded_rate}, ...] sorted by rate — powers
    # the peer drill-down popover on the outliers screen. None for trend
    # anomalies and rows computed before this field existed.
    peers_detail: Optional[List[Dict[str, Any]]] = None


def compute_rate(values: Dict[str, float], numerator_code: str, denominator_code: str) -> Optional[float]:
    spec = zscore_spec_for(numerator_code, denominator_code)
    multiplier = spec.rate_multiplier if spec else 100.0
    return _registry_compute_rate(values, (numerator_code,), (denominator_code,), multiplier)


# View over the registry's "zscore:*" slice — tuple shape kept so explain.py
# (line 497-501), trends.py, comparison.py and confidence.py keep working.
RATE_DEFINITIONS = [
    (s.rate_name, s.numerator_codes[0], s.denominator_codes[0], s.typical_pct)
    for s in zscore_specs()
]


def detect_anomalies(
    all_hospital_data: Dict[str, Dict[str, float]],
    current_hospital: str,
    month: str,
    config: Optional[dict] = None,
) -> List[AnomalyResultData]:
    results = []
    z_thresh = (config or {}).get("zscore_threshold", 2.5)
    for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
        rates = {}
        for hosp_name, hosp_values in all_hospital_data.items():
            rate = compute_rate(hosp_values, num_code, den_code)
            if rate is not None:
                rates[hosp_name] = rate
        current_values = all_hospital_data.get(current_hospital, {})
        current_rate = compute_rate(current_values, num_code, den_code)
        if current_rate is None:
            continue
        # Benchmark = peer mean EXCLUDING the hospital itself (same as audit screen)
        peers_map = {h: r for h, r in rates.items() if h != current_hospital}
        peers = list(peers_map.values())
        if len(peers) < 1:
            continue
        mean_rate = np.mean(peers)
        std_rate = np.std(peers, ddof=1) if len(peers) > 1 else 0
        if std_rate == 0:
            z_score = 0.0
        else:
            z_score = (current_rate - mean_rate) / std_rate
        _p_value = float(scipy_stats.norm.sf(abs(z_score)) * 2)
        is_outlier = abs(z_score) > z_thresh
        results.append(
            AnomalyResultData(
                indicator_code=num_code,
                rate_name=rate_name,
                value=round(current_rate, 2),
                benchmark=round(mean_rate, 2),
                z_score=round(z_score, 2),
                is_outlier=is_outlier,
                peer_count=len(peers),
                peer_std=round(float(std_rate), 2) if std_rate else 0.0,
                peer_min=round(float(min(peers)), 2),
                peer_max=round(float(max(peers)), 2),
                peer_median=round(float(np.median(peers)), 2),
                peers_detail=[
                    {"hospital": h, "rate": round(float(r), 4)}
                    for h, r in sorted(peers_map.items(), key=lambda kv: kv[1])
                ],
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
    for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
        current_rate = compute_rate(current_values, num_code, den_code)
        if current_rate is None:
            continue
        historical_rates = []
        for month, m_values in historical_months.items():
            if month >= current_month:
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
        _p_value = float(scipy_stats.norm.sf(abs(z)) * 2)
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
