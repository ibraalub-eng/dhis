from typing import List, Dict, Optional
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from .schemas import HospitalCluster, ClusteringResult


DEFAULT_FEATURES = [
    "total_births", "mat_deaths", "nd", "cs", "smm_total",
    "sb", "preterm", "lbw", "high_risk", "adolescent",
]


def cluster_hospitals(
    all_hospital_data: Dict[str, Dict[str, float]],
    config: dict,
) -> Optional[ClusteringResult]:
    if not config.get("enabled", True):
        return None

    features = config.get("features", DEFAULT_FEATURES)
    min_k = max(2, config.get("min_k", 2))
    max_k = min(config.get("max_k", 6), len(all_hospital_data))

    if len(all_hospital_data) < min_k or max_k < 2:
        return None

    hospital_names = sorted(all_hospital_data.keys())
    X = []
    for h in hospital_names:
        row = [all_hospital_data[h].get(f, 0) or 0 for f in features]
        X.append(row)
    X = np.array(X, dtype=float)

    if X.shape[0] < 2 or X.shape[1] < 1:
        return None

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    best_k = 2
    best_score = -1.0
    k_range = range(min_k, min(max_k, X.shape[0]) + 1)

    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(X_scaled)
        if len(set(labels)) < 2:
            continue
        if X_scaled.shape[0] <= k:
            best_k = k
            continue
        s = silhouette_score(X_scaled, labels)
        if s > best_score:
            best_score = s
            best_k = k

    final_kmeans = KMeans(n_clusters=best_k, random_state=42, n_init="auto")
    final_labels = final_kmeans.fit_predict(X_scaled)

    clusters = []
    for i, h in enumerate(hospital_names):
        dist = float(np.linalg.norm(X_scaled[i] - final_kmeans.cluster_centers_[final_labels[i]]))
        clusters.append(HospitalCluster(
            hospital_name=h,
            cluster_id=int(final_labels[i]),
            distance_to_centroid=round(dist, 4),
        ))

    centroids = []
    for c in range(best_k):
        centroid_dict = {}
        for j, f in enumerate(features):
            centroid_dict[f] = round(float(final_kmeans.cluster_centers_[c, j]), 4)
        centroids.append(centroid_dict)

    sil = float(best_score) if best_score > 0 else None

    return ClusteringResult(
        clusters=clusters,
        k=best_k,
        silhouette_score=sil,
        centroids=centroids,
        features_used=features,
    )
