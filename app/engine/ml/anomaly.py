from typing import List, Dict
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from .schemas import MLAnomalyResult


FEATURE_KEYS = [
    "cs", "smm_total", "mat_deaths", "nd", "sb",
    "preterm", "lbw", "total_births", "high_risk", "adolescent",
]


def detect_ml_anomalies(
    all_hospital_data: Dict[str, Dict[str, float]],
    config: dict,
) -> List[MLAnomalyResult]:
    if not config.get("enabled", True):
        return []

    contamination = config.get("contamination", 0.05)
    hospital_names = sorted(all_hospital_data.keys())

    if len(hospital_names) < 3:
        return []

    X = []
    for h in hospital_names:
        row = [all_hospital_data[h].get(k, 0) or 0 for k in FEATURE_KEYS]
        X.append(row)
    X = np.array(X, dtype=float)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    adjusted_contamination = max(contamination, 1.0 / len(hospital_names))
    model = IsolationForest(
        n_estimators=100,
        contamination=adjusted_contamination,
        random_state=42,
    )
    labels = model.fit_predict(X_scaled)
    scores = model.score_samples(X_scaled)

    results = []
    for i, h in enumerate(hospital_names):
        is_outlier = labels[i] == -1
        results.append(MLAnomalyResult(
            hospital_name=h,
            anomaly_score=round(float(scores[i]), 4),
            is_outlier=bool(is_outlier),
            method="isolation_forest",
        ))

    return results
