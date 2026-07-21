import numpy as np
from typing import List, Dict, Any
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from scipy.spatial.distance import mahalanobis

from app.engine.smart.schemas import SmartAnomalyResult

FEATURE_KEYS = [
    "cs_rate", "smm_total", "mat_deaths", "nd", "sb",
    "preterm", "lbw", "total_births", "high_risk", "adolescent",
]


def _prepare_features(all_hospital_data: Dict[str, Any]) -> tuple:
    hospital_names = list(all_hospital_data.keys())
    numeric_features = []
    categorical_data = []

    for name in hospital_names:
        entry = all_hospital_data[name]
        values = entry.get("values", {})
        row = [values.get(k, np.nan) for k in FEATURE_KEYS]
        numeric_features.append(row)
        categorical_data.append([
            entry.get("governorate", "unknown"),
            entry.get("hospital_type", "unknown"),
        ])

    numeric_array = np.array(numeric_features, dtype=float)
    imputer = SimpleImputer(strategy="median")
    numeric_imputed = imputer.fit_transform(numeric_array)
    scaler = StandardScaler()
    numeric_scaled = scaler.fit_transform(numeric_imputed)

    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    categorical_encoded = encoder.fit_transform(categorical_data)

    combined = np.hstack([numeric_scaled, categorical_encoded])
    return combined, hospital_names


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    min_s = scores.min()
    max_s = scores.max()
    if max_s - min_s < 1e-10:
        return np.zeros_like(scores)
    return (scores - min_s) / (max_s - min_s)


def detect_smart_anomalies(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    enabled: bool = True,
) -> List[SmartAnomalyResult]:
    if not enabled or len(all_hospital_data) < 3:
        return []

    combined, hospital_names = _prepare_features(all_hospital_data)
    n = len(hospital_names)

    contamination = config.get("contamination", 0.05)
    lof_neighbors = min(config.get("lof_neighbors", 5), n - 1)
    threshold_green = config.get("threshold_green", 0.3)
    threshold_yellow = config.get("threshold_yellow", 0.6)

    # Isolation Forest
    iforest = IsolationForest(contamination=contamination, random_state=42)
    iforest.fit(combined)
    if_scores_raw = -iforest.decision_function(combined)
    if_scores = _normalize_scores(if_scores_raw)

    # LOF
    lof = LocalOutlierFactor(n_neighbors=lof_neighbors, contamination=contamination)
    lof.fit(combined)
    lof_scores_raw = -lof.negative_outlier_factor_
    lof_scores = _normalize_scores(lof_scores_raw)

    # Mahalanobis
    try:
        cov = np.cov(combined.T)
        cov_inv = np.linalg.pinv(cov)
        centroid = combined.mean(axis=0)
        mahal_scores = np.array([
            mahalanobis(row, centroid, cov_inv) for row in combined
        ])
    except Exception:
        mahal_scores = np.zeros(n)
    mahal_norm = _normalize_scores(mahal_scores)

    # Ensemble
    w_if = config.get("ensemble_if_weight", 0.35)
    w_lof = config.get("ensemble_lof_weight", 0.30)
    w_mahal = config.get("ensemble_mahal_weight", 0.20)
    w_res = config.get("ensemble_residual_weight", 0.15)
    residual_scores = np.zeros(n)

    ensemble = (
        w_if * if_scores
        + w_lof * lof_scores
        + w_mahal * mahal_norm
        + w_res * residual_scores
    )
    ensemble = _normalize_scores(ensemble)

    results = []
    for i, name in enumerate(hospital_names):
        score = float(ensemble[i])
        if score < threshold_green:
            severity = "normal"
        elif score < threshold_yellow:
            severity = "warning"
        else:
            severity = "critical"

        results.append(SmartAnomalyResult(
            hospital_name=name,
            hospital_id=all_hospital_data[name]["hospital_id"],
            governorate=all_hospital_data[name].get("governorate", ""),
            hospital_type=all_hospital_data[name].get("hospital_type", ""),
            anomaly_score=score,
            method_scores={
                "isolation_forest": float(if_scores[i]),
                "lof": float(lof_scores[i]),
                "mahalanobis": float(mahal_norm[i]),
                "residual": float(residual_scores[i]),
            },
            severity=severity,
            is_outlier=severity in ("warning", "critical"),
        ))

    return results
