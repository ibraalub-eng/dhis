import numpy as np
from typing import Dict, Any, Optional
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from app.engine.smart.schemas import (
    SmartClusteringResult, HospitalClusterAssignment, ClusterProfile,
)
from app.engine.smart.anomaly import FEATURE_KEYS
from app.engine.smart.explainability import ARABIC_NAMES


def _build_cluster_profiles(all_hospital_data, labels, hospital_names) -> list:
    """ملف تعريف لكل عنقود: المؤشرات الأكثر انحرافاً عن المتوسط العام مع جملة عربية مختصرة."""
    features = [k for k in FEATURE_KEYS if any(
        k in all_hospital_data[h]["values"] for h in all_hospital_data
    )]

    overall = {}
    for f in features:
        vals = [all_hospital_data[h]["values"].get(f) for h in all_hospital_data]
        vals = [v for v in vals if v is not None]
        overall[f] = (sum(vals) / len(vals)) if vals else 0.0

    profiles = []
    for cid in sorted(int(c) for c in set(labels) - {-1}):
        members = [hospital_names[i] for i in range(len(hospital_names)) if labels[i] == cid]
        if not members:
            continue
        dist = []
        for f in features:
            vals = [all_hospital_data[m]["values"].get(f) for m in members]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            cmean = sum(vals) / len(vals)
            om = overall.get(f, 0.0)
            if om != 0:
                dev = (cmean - om) / om * 100
            else:
                dev = 100.0 if cmean > 0 else 0.0
            dist.append({
                "feature": f,
                "cluster_mean": round(cmean, 2),
                "overall_mean": round(om, 2),
                "deviation_pct": round(dev, 1),
                "direction": "above" if dev > 0 else "below",
            })
        dist.sort(key=lambda d: -abs(d["deviation_pct"]))
        top = dist[:3]
        parts = []
        for d in top:
            name = ARABIC_NAMES.get(d["feature"], d["feature"])
            if d["deviation_pct"] > 0:
                parts.append(f"{name} أعلى بـ {abs(d['deviation_pct']):.0f}%")
            else:
                parts.append(f"{name} أقل بـ {abs(d['deviation_pct']):.0f}%")
        profiles.append(ClusterProfile(
            cluster_id=cid,
            size=len(members),
            hospitals=members,
            distinguishing_features=top,
            summary_ar="، ".join(parts),
        ))
    return profiles


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
    # Columns where EVERY hospital is NaN would make SimpleImputer skip them AND
    # leave NaN that poisons StandardScaler + clustering. Zero-fill up-front.
    numeric_array[:, np.isnan(numeric_array).all(axis=0)] = 0.0
    imputer = SimpleImputer(strategy="median")
    numeric_imputed = imputer.fit_transform(numeric_array)
    scaler = StandardScaler()
    numeric_scaled = scaler.fit_transform(numeric_imputed)

    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    categorical_encoded = encoder.fit_transform(categorical_data)

    combined = np.hstack([numeric_scaled, categorical_encoded])
    return combined, hospital_names


def run_clustering(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    enabled: bool = True,
) -> Optional[SmartClusteringResult]:
    if not enabled or len(all_hospital_data) < 3:
        return None

    combined, hospital_names = _prepare_features(all_hospital_data)
    n = len(hospital_names)

    eps = float(config.get("dbscan_eps", 1.5))
    min_samples = int(min(config.get("dbscan_min_samples", 3), n - 1))

    dbscan = DBSCAN(eps=eps, min_samples=min_samples)
    labels = dbscan.fit_predict(combined)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    method = "dbscan"
    noise_hospitals = [
        hospital_names[i] for i in range(n) if labels[i] == -1
    ]

    if n_clusters < 2:
        method = "hierarchical"
        best_k = 2
        best_score = -1
        for k in range(2, min(7, n)):
            agg = AgglomerativeClustering(n_clusters=k, linkage="ward")
            k_labels = agg.fit_predict(combined)
            if len(set(k_labels)) > 1:
                score = float(silhouette_score(combined, k_labels))
                if score > best_score:
                    best_score = score
                    best_k = k
        agg = AgglomerativeClustering(n_clusters=best_k, linkage="ward")
        labels = agg.fit_predict(combined)
        n_clusters = best_k
        noise_hospitals = []

    unique_labels = set(labels)
    if len(unique_labels) > 1:
        non_noise_mask = labels != -1
        if non_noise_mask.sum() > 1:
            sil_score = float(silhouette_score(combined[non_noise_mask], labels[non_noise_mask]))
        else:
            sil_score = 0.0
    else:
        sil_score = 0.0

    pca = PCA(n_components=2)
    coords = pca.fit_transform(combined)
    pca_coordinates = {}
    for i, name in enumerate(hospital_names):
        pca_coordinates[name] = {"x": float(coords[i, 0]), "y": float(coords[i, 1])}

    clusters = []
    for i, name in enumerate(hospital_names):
        if labels[i] != -1:
            clusters.append(HospitalClusterAssignment(
                hospital_name=name,
                hospital_id=all_hospital_data[name]["hospital_id"],
                cluster_id=int(labels[i]),
                distance_to_centroid=0.0,
            ))

    profiles = _build_cluster_profiles(all_hospital_data, labels, hospital_names)

    return SmartClusteringResult(
        n_clusters=n_clusters,
        silhouette_score=sil_score,
        method=method,
        clusters=clusters,
        noise_hospitals=noise_hospitals,
        pca_coordinates=pca_coordinates,
        centroids=[],
        profiles=profiles,
    )
