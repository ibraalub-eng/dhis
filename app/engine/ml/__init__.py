"""ML-enhanced statistical analysis (clustering, anomaly detection, PCA)."""

from typing import List, Dict, Optional

from .clustering import cluster_hospitals
from .anomaly import detect_ml_anomalies
from .decomposition import run_pca
from .schemas import ClusteringResult, MLAnomalyResult, PCAResult


def run_ml_analysis(
    all_hospital_data: Dict[str, Dict[str, float]],
    ml_config: dict,
) -> dict:
    result: dict = {}
    if not ml_config.get("enabled", True):
        return result

    clustering_config = ml_config.get("clustering", {})
    if clustering_config.get("enabled", True):
        try:
            cr = cluster_hospitals(all_hospital_data, clustering_config)
            if cr is not None:
                result["ml_clustering"] = _clustering_to_dict(cr)
        except Exception:
            pass

    anomaly_config = ml_config.get("anomaly", {})
    if anomaly_config.get("enabled", True):
        try:
            anomalies = detect_ml_anomalies(all_hospital_data, anomaly_config)
            if anomalies:
                result["ml_anomalies"] = [_anomaly_to_dict(a) for a in anomalies]
        except Exception:
            pass

    pca_config = ml_config.get("pca", {})
    if pca_config.get("enabled", True):
        try:
            pca_result = run_pca(all_hospital_data, pca_config)
            if pca_result is not None:
                result["ml_pca"] = _pca_to_dict(pca_result)
        except Exception:
            pass

    return result


def _clustering_to_dict(cr: ClusteringResult) -> dict:
    return {
        "k": cr.k,
        "silhouette_score": cr.silhouette_score,
        "clusters": [
            {"hospital_name": c.hospital_name, "cluster_id": c.cluster_id,
             "distance_to_centroid": c.distance_to_centroid}
            for c in cr.clusters
        ],
        "features_used": cr.features_used,
    }


def _anomaly_to_dict(ma: MLAnomalyResult) -> dict:
    return {
        "hospital_name": ma.hospital_name,
        "anomaly_score": ma.anomaly_score,
        "is_outlier": ma.is_outlier,
        "method": ma.method,
        "contributing_features": ma.contributing_features,
    }


def _pca_to_dict(pr: PCAResult) -> dict:
    return {
        "n_components": pr.n_components,
        "explained_variance": pr.explained_variance,
        "cumulative_variance": pr.cumulative_variance,
        "top_features": {str(k): v for k, v in pr.top_features.items()},
    }
