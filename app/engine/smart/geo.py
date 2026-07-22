from typing import List, Dict, Any
from collections import defaultdict

from app.engine.smart.schemas import GeoAggregationResult, GovernorateAgg, SmartAnomalyResult


GOVERNORATE_MAP = {
    "شمال غزة": "شمال غزة",
    "North Gaza": "شمال غزة",
    "north_gaza": "شمال غزة",
    "Gaza": "غزة",
    "غزة": "غزة",
    "gaza": "غزة",
    "Deir al-Balah": "دير البلح",
    "دير البلح": "دير البلح",
    "deir_al_balah": "دير البلح",
    "Khan Younis": "خانيونس",
    "خانيونس": "خانيونس",
    "khan_younis": "خانيونس",
    "Rafah": "رفح",
    "رفح": "رفح",
    "rafah": "رفح",
}


def aggregate_by_governorate(
    anomalies: List[SmartAnomalyResult],
    all_hospital_data: Dict[str, Any],
) -> GeoAggregationResult:
    gov_groups = defaultdict(list)
    for a in anomalies:
        normalized = GOVERNORATE_MAP.get(a.governorate, a.governorate)
        gov_groups[normalized].append(a)

    gov_indicator_sums = defaultdict(lambda: defaultdict(list))
    for name, entry in all_hospital_data.items():
        gov = GOVERNORATE_MAP.get(entry.get("governorate", "unknown"), entry.get("governorate", "unknown"))
        for k, v in entry.get("values", {}).items():
            if v is not None:
                gov_indicator_sums[gov][k].append(v)

    governorates = []
    for gov_name, anomaly_list in gov_groups.items():
        scores = [a.anomaly_score for a in anomaly_list]
        indicator_avgs = {}
        for ind, vals in gov_indicator_sums.get(gov_name, {}).items():
            if vals:
                indicator_avgs[ind] = sum(vals) / len(vals)

        governorates.append(GovernorateAgg(
            governorate=gov_name,
            hospital_count=len(anomaly_list),
            avg_anomaly_score=sum(scores) / len(scores) if scores else 0.0,
            max_anomaly_score=max(scores) if scores else 0.0,
            outlier_count=sum(1 for a in anomaly_list if a.is_outlier),
            avg_indicator_values=indicator_avgs,
        ))

    return GeoAggregationResult(governorates=governorates)