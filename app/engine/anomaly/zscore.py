from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats as scipy_stats

from app.engine import indicator_service
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
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None


def compute_rate(values: Dict[str, float], numerator_code: str, denominator_code: str) -> Optional[float]:
    spec = zscore_spec_for(numerator_code, denominator_code)
    multiplier = spec.rate_multiplier if spec else 100.0
    return _registry_compute_rate(values, (numerator_code,), (denominator_code,), multiplier)


def _indicator_candidates(additional_indicators=None):
    if additional_indicators is not None:
        for resolved in additional_indicators:
            yield resolved, resolved.code, resolved.name, None, None
        return
    for rate_name, numerator_code, denominator_code, _typical_pct in RATE_DEFINITIONS:
        spec = zscore_spec_for(numerator_code, denominator_code)
        resolved = indicator_service.resolve_spec(spec) if spec else None
        yield resolved, numerator_code, rate_name, numerator_code, denominator_code
    for resolved in additional_indicators or ():
        yield resolved, resolved.code, resolved.name, None, None


def _calculate_candidate(resolved, values, numerator_code, denominator_code, month):
    if resolved is None:
        return compute_rate(values, numerator_code, denominator_code)
    result = indicator_service.calculate_from_values(
        resolved, values, hospital_id=0, month=month)
    return result.value if result.status == "ok" else None


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
    additional_indicators=None,
) -> List[AnomalyResultData]:
    results = []
    z_thresh = (config or {}).get("zscore_threshold", 2.5)
    for resolved, indicator_code, rate_name, num_code, den_code in _indicator_candidates(additional_indicators):
        rates = {}
        for hosp_name, hosp_values in all_hospital_data.items():
            rate = _calculate_candidate(
                resolved, hosp_values, num_code, den_code, month)
            if rate is not None:
                rates[hosp_name] = rate
        current_values = all_hospital_data.get(current_hospital, {})
        current_rate = _calculate_candidate(
            resolved, current_values, num_code, den_code, month)
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
                indicator_code=indicator_code,
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
                indicator_id=resolved.indicator_id if resolved else None,
                formula=resolved.formula if resolved else None,
                formula_version=resolved.formula_version if resolved else None,
            )
        )
    return results


def detect_monthly_trend(
    historical_months: Dict[str, Dict[str, float]],
    current_month: str,
    current_values: Dict[str, float],
    config: Optional[dict] = None,
    additional_indicators=None,
) -> List[AnomalyResultData]:
    results = []
    z_thresh = (config or {}).get("zscore_threshold", 2.5)
    if len(historical_months) < 2:
        return results
    for resolved, indicator_code, rate_name, num_code, den_code in _indicator_candidates(additional_indicators):
        current_rate = _calculate_candidate(
            resolved, current_values, num_code, den_code, current_month)
        if current_rate is None:
            continue
        historical_rates = []
        for month, m_values in historical_months.items():
            if month >= current_month:
                continue
            rate = _calculate_candidate(
                resolved, m_values, num_code, den_code, month)
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
                indicator_code=indicator_code,
                rate_name=f"{rate_name} (trend)",
                value=round(current_rate, 2),
                benchmark=round(mean_h, 2),
                z_score=round(z, 2),
                is_outlier=is_outlier,
                indicator_id=resolved.indicator_id if resolved else None,
                formula=resolved.formula if resolved else None,
                formula_version=resolved.formula_version if resolved else None,
            )
        )
    return results
