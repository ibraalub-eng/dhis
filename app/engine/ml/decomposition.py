from typing import List, Dict, Optional
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from .schemas import PCAResult


FEATURE_KEYS = [
    "cs", "smm_total", "mat_deaths", "nd", "sb",
    "preterm", "lbw", "total_births", "high_risk", "adolescent",
]


def run_pca(
    all_hospital_data: Dict[str, Dict[str, float]],
    config: dict,
) -> Optional[PCAResult]:
    if not config.get("enabled", True):
        return None

    hospital_names = sorted(all_hospital_data.keys())
    if len(hospital_names) < 3:
        return None

    X = []
    for h in hospital_names:
        row = [all_hospital_data[h].get(k, 0) or 0 for k in FEATURE_KEYS]
        X.append(row)
    X = np.array(X, dtype=float)

    if X.shape[1] < 2:
        return None

    scaler = StandardScaler()
    with np.errstate(invalid="ignore", divide="ignore"):
        X_scaled = scaler.fit_transform(X)
    # Zero-variance columns (identical values across hospitals) produce NaN after
    # scaling; PCA then emits NaN explained-variance which breaks JSON serialization.
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    n = min(config.get("max_components", 5), X_scaled.shape[0], X_scaled.shape[1])
    pca = PCA(n_components=n, random_state=42)
    # The divide (explained_variance / total_var) happens inside fit() itself, so
    # the errstate must wrap the fit call to silence the zero-variance warning.
    with np.errstate(invalid="ignore", divide="ignore"):
        pca.fit(X_scaled)

    raw_explained = pca.explained_variance_ratio_
    explained = [round(float(v), 4) if np.isfinite(v) else 0.0 for v in raw_explained]
    cumulative = []
    running = 0.0
    for v in explained:
        running += v
        cumulative.append(round(running, 4))

    threshold = config.get("variance_threshold", 0.8)
    n_selected = 1
    for i, v in enumerate(cumulative):
        if v >= threshold:
            n_selected = i + 1
            break
    n_selected = max(1, min(n_selected, len(explained)))

    loadings: Dict[int, Dict[str, float]] = {}
    top_features: Dict[int, List[str]] = {}
    for comp_idx in range(n_selected):
        comp_loadings = {}
        for feat_idx, feat_name in enumerate(FEATURE_KEYS):
            raw_val = pca.components_[comp_idx][feat_idx]
            comp_loadings[feat_name] = round(float(raw_val), 4) if np.isfinite(raw_val) else 0.0
        loadings[comp_idx + 1] = comp_loadings
        sorted_feats = sorted(comp_loadings.items(), key=lambda x: abs(x[1]), reverse=True)
        top_features[comp_idx + 1] = [f[0] for f in sorted_feats[:3]]

    return PCAResult(
        explained_variance=explained[:n_selected],
        cumulative_variance=cumulative[:n_selected],
        loadings={k: loadings[k] for k in range(1, n_selected + 1)},
        top_features={k: top_features[k] for k in range(1, n_selected + 1)},
        n_components=n_selected,
    )
