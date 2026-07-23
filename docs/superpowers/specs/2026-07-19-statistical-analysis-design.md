# Statistical Analysis with SciPy + Scikit-learn

## Objective

Complete the "Statistical Analysis (Pandas + SciPy + Scikit-learn)" component of the HEALTH-ai tech stack. Currently all statistical computations are hand-rolled with NumPy. This spec covers:

1. Replacing manual stats with proper SciPy functions
2. Adding ML capabilities via Scikit-learn (clustering, anomaly detection, PCA)
3. Integrating into the existing pipeline

## Approach

**Approach B:** New `app/engine/ml/` module + SciPy upgrades in-place. Clean separation, togglable via config, minimal risk to existing analysis.

---

## Section 1: SciPy Upgrades (In-Place)

Replace hand-rolled NumPy implementations with `scipy.stats` equivalents. Behavioral changes: adds p-values, confidence intervals, and proper statistical tests. No breaking changes to existing outputs.

### `app/engine/anomaly/trends.py`
- Replace manual OLS (`_linear_regression` at line 55) with `scipy.stats.linregress(x, y)`
- Returns: slope, intercept, rvalue, pvalue, stderr (adds p-value + std_err vs current slope/intercept/r_squared only)
- `pvalue` used for trend significance classification (p < 0.05 = significant)
- Keep existing `_compute_trend_direction` and `_compute_consecutive_trend` unchanged

### `app/engine/confidence.py`
- Replace manual z-score computation (lines 205-212, 245-250) with `scipy.stats.zscore(a, ddof=1)` where `a` is array of values
- Replace manual OLS in `_signal_trend` (lines 294-304) with `scipy.stats.linregress(x, y)`
- Add p-value from `scipy.stats.norm.sf(abs(z))` as optional diagnostic (not used in score calc)

### `app/engine/anomaly/zscore.py`
- Replace manual mean + std + z-score chain (lines 52-61, 99-104) with `scipy.stats.zscore(a, ddof=1)` where `a` is the array of hospital rate values
- Keep existing threshold-based outlier flag (`abs(z) > z_thresh`)

### `app/engine/audit/benchmark.py`
- Replace manual mean/std/z-score/percentile (lines 38-44) with SciPy equivalents
- Add 95% confidence interval: `scipy.stats.norm.interval(0.95, loc=mean, scale=std/sqrt(n))`
- CI returned in benchmark dict (not displayed, available for API consumers)

### `app/engine/clinical/risk_profile.py`
- Replace fake "correlation" in `correlate_risk_outcomes` (line 237, currently just peer avg comparison) with `scipy.stats.pearsonr(x, y)` or `scipy.stats.spearmanr(x, y)` if data is non-normal
- Decision rule: if n ≥ 30 use Pearson, otherwise Spearman
- Returns r-value and p-value alongside existing peer comparison

### `app/engine/anomaly/comparison.py`
- Add `scipy.stats.ttest_ind(hospital_vals, peer_vals)` to comparison output
- Returns p-value indicating whether hospital's rate differs significantly from peers
- Not used in scoring, available as diagnostic field

---

## Section 2: ML Module (`app/engine/ml/`)

New package structure:

```
app/engine/ml/
├── __init__.py          # run_ml_analysis() orchestrator
├── schemas.py           # ML result dataclasses
├── clustering.py        # Hospital peer grouping via KMeans
├── anomaly.py           # Multivariate anomaly detection (IsolationForest/LOF)
└── decomposition.py     # PCA for root cause driver analysis
```

### `schemas.py` — Dataclasses

```python
@dataclass
class HospitalCluster:
    hospital_name: str
    cluster_id: int
    distance_to_centroid: float

@dataclass
class ClusteringResult:
    clusters: List[HospitalCluster]
    k: int                          # selected number of clusters
    silhouette_score: float         # quality of clustering (0-1)
    centroids: List[Dict[str, float]]  # per-cluster center values
    features_used: List[str]        # indicator codes used

@dataclass
class MLAnomalyResult:
    hospital_name: str
    anomaly_score: float            # -1 to 1 (lower = more anomalous)
    is_outlier: bool
    method: str                     # "isolation_forest" or "lof"
    contributing_features: List[str]  # top features driving anomaly

@dataclass
class PCAResult:
    explained_variance: List[float]         # per-component variance ratio
    cumulative_variance: List[float]         # cumulative
    loadings: Dict[int, Dict[str, float]]   # component -> {feature: loading}
    top_features: Dict[int, List[str]]      # component -> top-3 features
    n_components: int
```

### `clustering.py` — Hospital Peer Grouping

**Algorithm:** `sklearn.cluster.KMeans` with `sklearn.preprocessing.StandardScaler`

**Features (10 indicators):**
- `total_births` — delivery volume (proxy for hospital size/level)
- `mat_deaths` — maternal deaths
- `nd` — neonatal deaths
- `cs` — C-section count
- `smm_total` — severe maternal morbidity
- `sb` — stillbirths
- `preterm` — preterm deliveries
- `lbw` — low birth weight
- `high_risk` — high-risk pregnancies
- `adolescent` — adolescent pregnancies

**Process:**
1. Build feature matrix from `all_hospital_data` (counts, not rates — captures volume + complexity)
2. StandardScaler fit_transform
3. For k in range(min_k, max_k+1): fit KMeans, compute silhouette_score
4. Select k with highest silhouette score (fallback to k=2 if all scores negative)
5. Refit KMeans with best k
6. Compute per-hospital distance to cluster centroid (Euclidean in scaled space)

**Edge cases:**
- Fewer hospitals than min_k: return single cluster, silhouette = None
- Identical feature vectors: handled by KMeans (same cluster)
- Missing features per hospital: fill with 0 (absence == no events)

### `anomaly.py` — Multivariate Anomaly Detection

**Primary:** `sklearn.ensemble.IsolationForest`
- n_estimators=100, contamination=0.05 (configurable), random_state=42
- Trained on same feature matrix as clustering
- Returns anomaly score + outlier flag per hospital

**Secondary:** `sklearn.neighbors.LocalOutlierFactor`
- n_neighbors=min(20, n_samples-1), contamination=0.05
- Runs only if n_samples >= 3
- Returns LOF score + outlier flag

**Output:** one `MLAnomalyResult` per hospital per method. If both methods agree, confidence is higher.

**Integration with existing z-score anomalies:**
- ML anomalies are ADDITIONAL, not replacements
- Existing z-score anomalies continue unchanged
- ML anomalies flagged in pipeline output as `ml_anomalies`

**Edge cases:**
- n_samples < 3: skip LOF, run IsolationForest with adjusted contamination
- All hospitals identical: IsolationForest returns all as inliers (correct)
- Contamination > 1/n: clamp to 1/n

### `decomposition.py` — PCA for Variance Analysis

**Algorithm:** `sklearn.decomposition.PCA` with `sklearn.preprocessing.StandardScaler`

**Process:**
1. Build feature matrix (same as clustering, using rates instead of counts for comparability)
2. StandardScaler fit_transform
3. PCA fit with min(n_components, n_features, n_samples)
4. Select components explaining ≥80% cumulative variance (max 5)
5. For each component, extract top-3 features by absolute loading

**Output:**
- Explained variance ratio per component
- Feature loadings per component
- Top-3 features driving each component

**Integration:** PCA results stored in pipeline output. Used by root cause analysis as an additional signal — components with high loadings for specific indicators indicate those indicators drive most variance across hospitals.

**Edge cases:**
- n_features > n_samples: PCA still works (n_components capped at min(n_samples, n_features))
- Zero-variance features: StandardScaler handles (returns 0s), PCA ignores them

---

## Section 3: Pipeline Integration

### `app/engine/pipeline.py` changes

After data loading (after line 200), before anomaly detection:

```python
if config.get("ml", {}).get("enabled", False):
    ml_results = run_ml_analysis(all_hospital_data, config.get("ml", {}))
else:
    ml_results = {}
```

### ML Orchestrator (`ml/__init__.py`)

```python
def run_ml_analysis(all_hospital_data: List, ml_config: dict) -> dict:
    result = {}
    if ml_config.get("clustering", {}).get("enabled", True):
        result["clustering"] = cluster_hospitals(all_hospital_data, ml_config["clustering"])
    if ml_config.get("anomaly", {}).get("enabled", True):
        result["anomalies"] = detect_ml_anomalies(all_hospital_data, ml_config["anomaly"])
    if ml_config.get("pca", {}).get("enabled", True):
        result["pca"] = run_pca(all_hospital_data, ml_config["pca"])
    return result
```

### Configuration

```python
ML_CONFIG = {
    "enabled": False,  # opt-in until validated
    "clustering": {
        "enabled": True,
        "min_k": 2,
        "max_k": 6,
        "features": ["total_births", "mat_deaths", "nd", "cs", "smm_total", "sb", "preterm", "lbw", "high_risk", "adolescent"]
    },
    "anomaly": {
        "enabled": True,
        "contamination": 0.05,
        "method": "isolation_forest"
    },
    "pca": {
        "enabled": True,
        "variance_threshold": 0.8,
        "max_components": 5
    }
}
```

### Output shape

ML results stored in the analysis output dict alongside existing keys:

```python
{
    "ml_clustering": ClusteringResult,
    "ml_anomalies": List[MLAnomalyResult],
    "ml_pca": PCAResult
}
```

Downstream consumers can access these via the analysis dict returned by `run_full_analysis()`.

### Downstream use (future, not in this implementation)
- `benchmark.py`: filter peers to same cluster
- `confidence.py`: cluster-aware cross-hospital signal
- `root_cause.py`: PCA loadings as additional signal
- API: expose cluster info and ML anomaly flags in hospital response

This implementation stores results only — downstream consumption will be a separate effort.

---

## Requirements

Add to `requirements.txt`:
```
scipy>=1.14.0
scikit-learn>=1.6.0
```

No other dependency changes needed (numpy and pandas already present).

---

## Files Changed

| File | Change |
|---|---|
| `requirements.txt` | Add scipy, scikit-learn |
| `app/engine/anomaly/trends.py` | Replace manual OLS with `scipy.stats.linregress` |
| `app/engine/confidence.py` | Replace manual z-score + OLS with SciPy |
| `app/engine/anomaly/zscore.py` | Replace manual z-score with `scipy.stats.zscore` |
| `app/engine/audit/benchmark.py` | SciPy replacements + confidence intervals |
| `app/engine/clinical/risk_profile.py` | Replace fake correlation with `pearsonr`/`spearmanr` |
| `app/engine/anomaly/comparison.py` | Add `ttest_ind` as diagnostic |
| `app/engine/ml/__init__.py` | NEW — orchestrator |
| `app/engine/ml/schemas.py` | NEW — dataclasses |
| `app/engine/ml/clustering.py` | NEW — KMeans clustering |
| `app/engine/ml/anomaly.py` | NEW — IsolationForest/LOF |
| `app/engine/ml/decomposition.py` | NEW — PCA |
| `app/engine/pipeline.py` | Add ML analysis call |
