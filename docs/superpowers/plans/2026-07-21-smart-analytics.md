# Smart Analytics System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a smart analytics layer with anomaly detection (LOF, DBSCAN, Mahalanobis, ensemble), clustering, correlations, residual analysis, SHAP explainability, and interactive Plotly.js visualizations in a new SPA tab.

**Architecture:** Separate `app/engine/smart/` package with 8 modules + orchestrator. New API router at `/smart/`. New "Smart Analytics" tab in existing SPA with 9 Plotly.js charts. On-demand computation, no DB persistence.

**Tech Stack:** Python (scikit-learn, scipy, statsmodels, shap, pandas, numpy), FastAPI, Plotly.js, vanilla JS SPA

## Global Constraints

- ~20 hospitals × 6 months ≈ 120 data-point-months. No time-series forecasting.
- Mixed numeric + categorical features. Some indicators are rates, some counts.
- Arabic labels for all user-facing text. RTL layout.
- Severity color scheme: green (#22c55e) < 0.3, yellow (#f59e0b) 0.3-0.6, red (#ef4444) > 0.6 — consistent across ALL charts.
- All new AppConfig entries use category `smart_analytics`.
- Existing engine modules (`app/engine/ml/`, `app/engine/anomaly/`) are NOT modified.
- `requirements.txt` must be updated with: `shap>=0.42.0`, `plotly>=5.18.0`, `statsmodels>=0.14.0`

---

## File Structure

### Create

| File | Responsibility |
|------|---------------|
| `app/engine/smart/__init__.py` | Orchestrator: `run_smart_analytics()` |
| `app/engine/smart/schemas.py` | All dataclasses for outputs |
| `app/engine/smart/anomaly.py` | LOF, DBSCAN outlier, Mahalanobis, ensemble scoring |
| `app/engine/smart/clustering.py` | DBSCAN + Hierarchical clustering, PCA coords |
| `app/engine/smart/correlations.py` | Correlation matrix + RF feature importance |
| `app/engine/smart/residual.py` | OLS regression residual analysis |
| `app/engine/smart/stratified.py` | Peer-group stratified comparisons |
| `app/engine/smart/explainability.py` | SHAP values + Arabic text generation |
| `app/engine/smart/geo.py` | Governorate aggregation for map |
| `app/api/smart_analytics.py` | 10 API endpoints under `/smart` |
| `static/tabs/smart-analytics.html` | Tab HTML template |
| `static/js/smart-analytics.js` | Tab logic + Plotly charts |
| `data/geo/gaza_governorates.geojson` | Gaza governorate boundaries |
| `tests/test_smart_schemas.py` | Schema dataclass tests |
| `tests/test_smart_anomaly.py` | Anomaly detection tests |
| `tests/test_smart_clustering.py` | Clustering tests |
| `tests/test_smart_correlations.py` | Correlation + feature importance tests |
| `tests/test_smart_residuals.py` | Residual analysis tests |
| `tests/test_smart_stratified.py` | Stratified comparison tests |
| `tests/test_smart_explain.py` | SHAP explainability tests |
| `tests/test_smart_pipeline.py` | Full integration test |

### Modify

| File | Change |
|------|--------|
| `requirements.txt:1-17` | Add `shap>=0.42.0`, `plotly>=5.18.0`, `statsmodels>=0.14.0` |
| `app/main.py:1` | Mount `smart_analytics` router, seed smart_analytics AppConfig entries |
| `static/index.html` | Add tab button + tab-content div for "التحليل الذكي" |

---

## Tasks

### Task 1: Dependencies + Config Seeding

**Files:**
- Modify: `requirements.txt`
- Modify: `app/main.py`
- Test: `pip install -r requirements.txt` succeeds

**Interfaces:**
- Produces: 12 new `AppConfig` rows with `category='smart_analytics'` in DB

- [ ] **Step 1: Update requirements.txt**

Add three new lines to `requirements.txt`:
```
shap>=0.42.0
plotly>=5.18.0
statsmodels>=0.14.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install without errors

- [ ] **Step 3: Seed smart_analytics config in main.py**

In `app/main.py`, find the existing `seed_app_config_defaults()` function (or the config seeding block in the lifespan). Add the following entries to the defaults dict:

```python
# Smart Analytics config
"smart_enabled": {"value": 1.0, "category": "smart_analytics"},
"smart_contamination": {"value": 0.05, "category": "smart_analytics"},
"smart_lof_neighbors": {"value": 5.0, "category": "smart_analytics"},
"smart_dbscan_eps": {"value": 1.5, "category": "smart_analytics"},
"smart_dbscan_min_samples": {"value": 3.0, "category": "smart_analytics"},
"smart_threshold_green": {"value": 0.3, "category": "smart_analytics"},
"smart_threshold_yellow": {"value": 0.6, "category": "smart_analytics"},
"smart_shap_enabled": {"value": 1.0, "category": "smart_analytics"},
"smart_ensemble_if_weight": {"value": 0.35, "category": "smart_analytics"},
"smart_ensemble_lof_weight": {"value": 0.3, "category": "smart_analytics"},
"smart_ensemble_mahal_weight": {"value": 0.2, "category": "smart_analytics"},
"smart_ensemble_residual_weight": {"value": 0.15, "category": "smart_analytics"},
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt app/main.py
git commit -m "feat(smart): add dependencies and config seeding for smart analytics"
```

---

### Task 2: Schemas

**Files:**
- Create: `app/engine/smart/__init__.py` (empty initially)
- Create: `app/engine/smart/schemas.py`
- Create: `tests/test_smart_schemas.py`

**Interfaces:**
- Produces: All dataclasses consumed by Tasks 3-9

- [ ] **Step 1: Create package init**

Create `app/engine/smart/__init__.py` with empty content (just a comment):
```python
# Smart Analytics Engine Package
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_smart_schemas.py`:
```python
from app.engine.smart.schemas import (
    SmartAnomalyResult,
    SmartClusteringResult,
    HospitalClusterAssignment,
    SmartCorrelationResult,
    CorrelationPair,
    FeatureImportance,
    ImportanceEntry,
    ResidualResult,
    StratifiedComparison,
    AnomalyExplanation,
    FactorExplanation,
    GeoAggregationResult,
    GovernorateAgg,
    SmartAnalyticsResult,
    KPISummary,
)


def test_smart_anomaly_result():
    r = SmartAnomalyResult(
        hospital_name="Test Hospital",
        hospital_id=1,
        governorate="Gaza",
        hospital_type="general",
        anomaly_score=0.75,
        method_scores={"isolation_forest": 0.8, "lof": 0.7},
        severity="critical",
        is_outlier=True,
    )
    assert r.hospital_name == "Test Hospital"
    assert r.anomaly_score == 0.75
    assert r.severity == "critical"
    assert r.is_outlier is True


def test_smart_clustering_result():
    c = SmartClusteringResult(
        n_clusters=3,
        silhouette_score=0.45,
        method="dbscan",
        clusters=[],
        noise_hospitals=["Hospital A"],
        pca_coordinates={"Hospital A": {"x": 1.0, "y": 2.0}},
        centroids=[{"feature1": 0.5}],
    )
    assert c.n_clusters == 3
    assert c.method == "dbscan"
    assert len(c.noise_hospitals) == 1


def test_hospital_cluster_assignment():
    a = HospitalClusterAssignment(
        hospital_name="Test",
        hospital_id=1,
        cluster_id=0,
        distance_to_centroid=0.5,
    )
    assert a.cluster_id == 0


def test_smart_correlation_result():
    r = SmartCorrelationResult(
        matrix={"a": {"b": 0.8}},
        indicators=["a", "b"],
        strong_correlations=[],
        feature_importance=[],
    )
    assert len(r.indicators) == 2


def test_correlation_pair():
    p = CorrelationPair(
        indicator_a="cs_rate",
        indicator_b="smm_total",
        pearson_r=0.85,
        spearman_r=0.82,
        p_value=0.001,
        strength="strong_positive",
    )
    assert p.strength == "strong_positive"


def test_feature_importance():
    fi = FeatureImportance(
        target_indicator="cs_rate",
        features=[
            ImportanceEntry(feature_name="total_births", importance=0.3, rank=1),
        ],
    )
    assert fi.features[0].rank == 1


def test_residual_result():
    r = ResidualResult(
        hospital_name="Test",
        hospital_id=1,
        indicator="cs_rate",
        actual_value=35.0,
        predicted_value=28.0,
        residual=7.0,
        residual_z_score=2.5,
        is_anomaly=True,
        severity="warning",
    )
    assert r.is_anomaly is True


def test_stratified_comparison():
    s = StratifiedComparison(
        hospital_name="Test",
        hospital_id=1,
        indicator="cs_rate",
        hospital_value=35.0,
        peer_group_mean=28.0,
        peer_group_std=3.0,
        deviation_pct=25.0,
        rank_in_peer_group=1,
        peer_group_size=5,
        label="significantly_above",
    )
    assert s.rank_in_peer_group == 1


def test_anomaly_explanation():
    e = AnomalyExplanation(
        hospital_name="Test",
        hospital_id=1,
        anomaly_score=0.8,
        severity="critical",
        shap_values={"cs_rate": 0.3, "smm_total": 0.2},
        top_factors=[
            FactorExplanation(
                feature="cs_rate",
                shap_value=0.3,
                direction="increases_anomaly",
                magnitude="high",
                arabic_label="معدل العمليات القيصارية",
            )
        ],
        text_explanation="هذا المستشفى شاذ بسبب ارتفاع معدل العمليات القيصارية",
    )
    assert len(e.top_factors) == 1
    assert e.top_factors[0].direction == "increases_anomaly"


def test_geo_aggregation():
    g = GeoAggregationResult(
        governorates=[
            GovernorateAgg(
                governorate="Gaza",
                hospital_count=5,
                avg_anomaly_score=0.4,
                max_anomaly_score=0.8,
                outlier_count=1,
                avg_indicator_values={"cs_rate": 30.0},
            )
        ]
    )
    assert len(g.governorates) == 1


def test_kpi_summary():
    k = KPISummary(
        total_anomalies=5,
        critical_count=2,
        warning_count=3,
        affected_governorates=3,
        top_contributing_factor="cs_rate",
        month_status="attention_needed",
    )
    assert k.total_anomalies == 5


def test_smart_analytics_result():
    r = SmartAnalyticsResult(
        month="2026-06",
        hospitals_count=20,
        anomalies=[],
        clustering=SmartClusteringResult(
            n_clusters=0, silhouette_score=0.0, method="dbscan",
            clusters=[], noise_hospitals=[], pca_coordinates={}, centroids=[],
        ),
        correlations=SmartCorrelationResult(
            matrix={}, indicators=[], strong_correlations=[], feature_importance=[],
        ),
        residuals=[],
        stratified=[],
        explanations=[],
        geo=GeoAggregationResult(governorates=[]),
        kpi=KPISummary(
            total_anomalies=0, critical_count=0, warning_count=0,
            affected_governorates=0, top_contributing_factor="", month_status="normal",
        ),
    )
    assert r.month == "2026-06"
    assert r.hospitals_count == 20
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_smart_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.smart.schemas'`

- [ ] **Step 4: Write schemas.py**

Create `app/engine/smart/schemas.py`:
```python
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class SmartAnomalyResult:
    hospital_name: str
    hospital_id: int
    governorate: str
    hospital_type: str
    anomaly_score: float
    method_scores: Dict[str, float]
    severity: str
    is_outlier: bool


@dataclass
class HospitalClusterAssignment:
    hospital_name: str
    hospital_id: int
    cluster_id: int
    distance_to_centroid: float


@dataclass
class SmartClusteringResult:
    n_clusters: int
    silhouette_score: float
    method: str
    clusters: List[HospitalClusterAssignment]
    noise_hospitals: List[str]
    pca_coordinates: Dict[str, Dict[str, float]]
    centroids: List[Dict]


@dataclass
class CorrelationPair:
    indicator_a: str
    indicator_b: str
    pearson_r: float
    spearman_r: float
    p_value: float
    strength: str


@dataclass
class ImportanceEntry:
    feature_name: str
    importance: float
    rank: int


@dataclass
class FeatureImportance:
    target_indicator: str
    features: List[ImportanceEntry]


@dataclass
class SmartCorrelationResult:
    matrix: Dict[str, Dict[str, float]]
    indicators: List[str]
    strong_correlations: List[CorrelationPair]
    feature_importance: List[FeatureImportance]


@dataclass
class ResidualResult:
    hospital_name: str
    hospital_id: int
    indicator: str
    actual_value: float
    predicted_value: float
    residual: float
    residual_z_score: float
    is_anomaly: bool
    severity: str


@dataclass
class StratifiedComparison:
    hospital_name: str
    hospital_id: int
    indicator: str
    hospital_value: float
    peer_group_mean: float
    peer_group_std: float
    deviation_pct: float
    rank_in_peer_group: int
    peer_group_size: int
    label: str


@dataclass
class FactorExplanation:
    feature: str
    shap_value: float
    direction: str
    magnitude: str
    arabic_label: str


@dataclass
class AnomalyExplanation:
    hospital_name: str
    hospital_id: int
    anomaly_score: float
    severity: str
    shap_values: Dict[str, float]
    top_factors: List[FactorExplanation]
    text_explanation: str


@dataclass
class GovernorateAgg:
    governorate: str
    hospital_count: int
    avg_anomaly_score: float
    max_anomaly_score: float
    outlier_count: int
    avg_indicator_values: Dict[str, float]


@dataclass
class GeoAggregationResult:
    governorates: List[GovernorateAgg]


@dataclass
class KPISummary:
    total_anomalies: int
    critical_count: int
    warning_count: int
    affected_governorates: int
    top_contributing_factor: str
    month_status: str


@dataclass
class SmartAnalyticsResult:
    month: str
    hospitals_count: int
    anomalies: List[SmartAnomalyResult]
    clustering: SmartClusteringResult
    correlations: SmartCorrelationResult
    residuals: List[ResidualResult]
    stratified: List[StratifiedComparison]
    explanations: List[AnomalyExplanation]
    geo: GeoAggregationResult
    kpi: KPISummary
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_smart_schemas.py -v`
Expected: All 12 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/engine/smart/__init__.py app/engine/smart/schemas.py tests/test_smart_schemas.py
git commit -m "feat(smart): add dataclass schemas for smart analytics"
```

---

### Task 3: Anomaly Detection

**Files:**
- Create: `app/engine/smart/anomaly.py`
- Create: `tests/test_smart_anomaly.py`

**Interfaces:**
- Consumes: `app.indicators.INDICATOR_CODE_TO_NAME` for Arabic labels
- Consumes: Config dict from AppConfig
- Produces: `List[SmartAnomalyResult]`

**Data format (all_hospital_data):**
```python
{
    "Hospital Name": {
        "hospital_id": 1,
        "governorate": "Gaza",
        "hospital_type": "general",
        "values": {"cs_rate": 30.0, "smm_total": 5.0, ...}
    }
}
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_anomaly.py`:
```python
import pytest
from app.engine.smart.anomaly import detect_smart_anomalies


@pytest.fixture
def sample_data():
    return {
        "Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0, "smm_total": 5.0, "mat_deaths": 1.0, "nd": 2.0, "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0}},
        "Hospital B": {"hospital_id": 2, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 25.0, "smm_total": 3.0, "mat_deaths": 0.0, "nd": 1.0, "sb": 0.5, "preterm": 8.0, "lbw": 6.0, "total_births": 180.0, "high_risk": 12.0, "adolescent": 2.0}},
        "Hospital C": {"hospital_id": 3, "governorate": "North Gaza", "hospital_type": "general", "values": {"cs_rate": 28.0, "smm_total": 4.0, "mat_deaths": 0.5, "nd": 1.5, "sb": 0.8, "preterm": 9.0, "lbw": 7.0, "total_births": 190.0, "high_risk": 13.0, "adolescent": 2.5}},
        "Hospital D": {"hospital_id": 4, "governorate": "Khan Younis", "hospital_type": "specialist", "values": {"cs_rate": 22.0, "smm_total": 2.0, "mat_deaths": 0.0, "nd": 0.5, "sb": 0.3, "preterm": 6.0, "lbw": 5.0, "total_births": 150.0, "high_risk": 10.0, "adolescent": 1.5}},
        "Hospital E": {"hospital_id": 5, "governorate": "Rafah", "hospital_type": "general", "values": {"cs_rate": 60.0, "smm_total": 15.0, "mat_deaths": 3.0, "nd": 8.0, "sb": 4.0, "preterm": 25.0, "lbw": 20.0, "total_births": 100.0, "high_risk": 30.0, "adolescent": 10.0}},
    }


@pytest.fixture
def default_config():
    return {
        "contamination": 0.05,
        "lof_neighbors": 5,
        "threshold_green": 0.3,
        "threshold_yellow": 0.6,
        "ensemble_if_weight": 0.35,
        "ensemble_lof_weight": 0.30,
        "ensemble_mahal_weight": 0.20,
        "ensemble_residual_weight": 0.15,
    }


def test_returns_list_of_smart_anomaly_result(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    assert isinstance(results, list)
    assert len(results) == 5


def test_outlier_hospital_flagged(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    hospital_e = next(r for r in results if r.hospital_name == "Hospital E")
    assert hospital_e.is_outlier is True
    assert hospital_e.severity in ("warning", "critical")


def test_normal_hospital_not_flagged(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    hospital_b = next(r for r in results if r.hospital_name == "Hospital B")
    assert hospital_b.severity == "normal"


def test_anomaly_score_between_0_and_1(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert 0.0 <= r.anomaly_score <= 1.0


def test_method_scores_present(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert "isolation_forest" in r.method_scores
        assert "lof" in r.method_scores
        assert "mahalanobis" in r.method_scores


def test_disabled_returns_empty(default_config):
    results = detect_smart_anomalies({}, default_config, enabled=False)
    assert results == []


def test_too_few_hospitals_returns_empty(default_config):
    data = {"Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = detect_smart_anomalies(data, default_config)
    assert results == []


def test_severity_classification(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert r.severity in ("normal", "warning", "critical")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_anomaly.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write anomaly.py**

Create `app/engine/smart/anomaly.py`:
```python
import numpy as np
from typing import List, Dict, Any
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from scipy.spatial.distance import mahalanobis
from scipy.stats import zscore

from app.engine.smart.schemas import SmartAnomalyResult

FEATURE_KEYS = [
    "cs_rate", "smm_total", "mat_deaths", "nd", "sb",
    "preterm", "lbw", "total_births", "high_risk", "adolescent",
]


def _prepare_features(all_hospital_data: Dict[str, Any]) -> tuple:
    """Prepare numeric + categorical feature matrix."""
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
    """Normalize scores to 0-1 range."""
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
    """Detect anomalies using Isolation Forest, LOF, Mahalanobis, and ensemble."""
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

    # Residual scores filled in later by residual.py; use 0 for now
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_anomaly.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/anomaly.py tests/test_smart_anomaly.py
git commit -m "feat(smart): add anomaly detection with LOF, DBSCAN outlier, Mahalanobis, ensemble"
```

---

### Task 4: Clustering

**Files:**
- Create: `app/engine/smart/clustering.py`
- Create: `tests/test_smart_clustering.py`

**Interfaces:**
- Consumes: Same `all_hospital_data` format as Task 3
- Produces: `SmartClusteringResult`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_clustering.py`:
```python
import pytest
from app.engine.smart.clustering import run_clustering


@pytest.fixture
def sample_data():
    return {
        "Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0, "smm_total": 5.0, "mat_deaths": 1.0, "nd": 2.0, "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0}},
        "Hospital B": {"hospital_id": 2, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 28.0, "smm_total": 4.5, "mat_deaths": 0.8, "nd": 1.8, "sb": 0.9, "preterm": 9.5, "lbw": 7.5, "total_births": 195.0, "high_risk": 14.0, "adolescent": 2.8}},
        "Hospital C": {"hospital_id": 3, "governorate": "North Gaza", "hospital_type": "general", "values": {"cs_rate": 32.0, "smm_total": 5.5, "mat_deaths": 1.2, "nd": 2.2, "sb": 1.1, "preterm": 10.5, "lbw": 8.5, "total_births": 205.0, "high_risk": 16.0, "adolescent": 3.2}},
        "Hospital D": {"hospital_id": 4, "governorate": "Khan Younis", "hospital_type": "specialist", "values": {"cs_rate": 15.0, "smm_total": 2.0, "mat_deaths": 0.0, "nd": 0.5, "sb": 0.2, "preterm": 5.0, "lbw": 4.0, "total_births": 120.0, "high_risk": 8.0, "adolescent": 1.0}},
        "Hospital E": {"hospital_id": 5, "governorate": "Rafah", "hospital_type": "general", "values": {"cs_rate": 18.0, "smm_total": 2.5, "mat_deaths": 0.1, "nd": 0.8, "sb": 0.3, "preterm": 5.5, "lbw": 4.5, "total_births": 130.0, "high_risk": 9.0, "adolescent": 1.2}},
    }


@pytest.fixture
def default_config():
    return {"dbscan_eps": 1.5, "dbscan_min_samples": 2}


def test_returns_clustering_result(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert result is not None
    assert result.n_clusters >= 1


def test_all_hospitals_assigned(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assigned = [c.hospital_name for c in result.clusters]
    noise = result.noise_hospitals
    all_names = assigned + noise
    assert set(all_names) == set(sample_data.keys())


def test_pca_coordinates_present(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    for name in sample_data:
        assert name in result.pca_coordinates
        assert "x" in result.pca_coordinates[name]
        assert "y" in result.pca_coordinates[name]


def test_too_few_returns_none(default_config):
    data = {"Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = run_clustering(data, default_config)
    assert result is None


def test_disabled_returns_none(default_config):
    result = run_clustering({}, default_config, enabled=False)
    assert result is None


def test_silhouette_score_valid(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert -1.0 <= result.silhouette_score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_clustering.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write clustering.py**

Create `app/engine/smart/clustering.py`:
```python
import numpy as np
from typing import Dict, Any, Optional
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from app.engine.smart.schemas import SmartClusteringResult, HospitalClusterAssignment
from app.engine.smart.anomaly import FEATURE_KEYS


def _prepare_features(all_hospital_data: Dict[str, Any]) -> tuple:
    """Same preparation as anomaly.py."""
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


def run_clustering(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    enabled: bool = True,
) -> Optional[SmartClusteringResult]:
    """Run DBSCAN clustering with hierarchical fallback."""
    if not enabled or len(all_hospital_data) < 3:
        return None

    combined, hospital_names = _prepare_features(all_hospital_data)
    n = len(hospital_names)

    eps = config.get("dbscan_eps", 1.5)
    min_samples = min(config.get("dbscan_min_samples", 3), n - 1)

    # Try DBSCAN first
    dbscan = DBSCAN(eps=eps, min_samples=min_samples)
    labels = dbscan.fit_predict(combined)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    method = "dbscan"
    noise_hospitals = [
        hospital_names[i] for i in range(n) if labels[i] == -1
    ]

    # Fallback to hierarchical if DBSCAN produces <2 clusters
    if n_clusters < 2:
        method = "hierarchical"
        best_k = 2
        best_score = -1
        for k in range(2, min(7, n)):
            agg = AgglomerativeClustering(n_clusters=k, linkage="ward")
            k_labels = agg.fit_predict(combined)
            if len(set(k_labels)) > 1:
                score = silhouette_score(combined, k_labels)
                if score > best_score:
                    best_score = score
                    best_k = k
        agg = AgglomerativeClustering(n_clusters=best_k, linkage="ward")
        labels = agg.fit_predict(combined)
        n_clusters = best_k
        noise_hospitals = []

    # Compute silhouette score
    unique_labels = set(labels)
    if len(unique_labels) > 1:
        non_noise_mask = labels != -1
        if non_noise_mask.sum() > 1:
            sil_score = float(silhouette_score(combined[non_noise_mask], labels[non_noise_mask]))
        else:
            sil_score = 0.0
    else:
        sil_score = 0.0

    # PCA for visualization
    pca = PCA(n_components=2)
    coords = pca.fit_transform(combined)
    pca_coordinates = {}
    for i, name in enumerate(hospital_names):
        pca_coordinates[name] = {"x": float(coords[i, 0]), "y": float(coords[i, 1])}

    # Build cluster assignments
    clusters = []
    for i, name in enumerate(hospital_names):
        if labels[i] != -1:
            clusters.append(HospitalClusterAssignment(
                hospital_name=name,
                hospital_id=all_hospital_data[name]["hospital_id"],
                cluster_id=int(labels[i]),
                distance_to_centroid=0.0,
            ))

    return SmartClusteringResult(
        n_clusters=n_clusters,
        silhouette_score=sil_score,
        method=method,
        clusters=clusters,
        noise_hospitals=noise_hospitals,
        pca_coordinates=pca_coordinates,
        centroids=[],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_clustering.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/clustering.py tests/test_smart_clustering.py
git commit -m "feat(smart): add DBSCAN + hierarchical clustering with PCA coordinates"
```

---

### Task 5: Correlations + Feature Importance

**Files:**
- Create: `app/engine/smart/correlations.py`
- Create: `tests/test_smart_correlations.py`

**Interfaces:**
- Consumes: Same `all_hospital_data` format
- Produces: `SmartCorrelationResult`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_correlations.py`:
```python
import pytest
import numpy as np
from app.engine.smart.correlations import analyze_correlations


@pytest.fixture
def sample_data():
    np.random.seed(42)
    n = 10
    data = {}
    for i in range(n):
        cs_rate = np.random.uniform(20, 40)
        smm = cs_rate * 0.15 + np.random.normal(0, 1)
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": "Gaza",
            "hospital_type": "general",
            "values": {
                "cs_rate": cs_rate,
                "smm_total": max(0, smm),
                "mat_deaths": max(0, smm * 0.1),
                "nd": np.random.uniform(0, 5),
                "sb": np.random.uniform(0, 2),
                "preterm": np.random.uniform(5, 15),
                "lbw": np.random.uniform(4, 12),
                "total_births": np.random.uniform(100, 300),
                "high_risk": np.random.uniform(5, 25),
                "adolescent": np.random.uniform(1, 8),
            },
        }
    return data


@pytest.fixture
def default_config():
    return {}


def test_returns_correlation_result(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert result is not None
    assert len(result.indicators) > 0


def test_matrix_is_symmetric(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    for ind_a in result.matrix:
        for ind_b in result.matrix[ind_a]:
            if ind_b in result.matrix and ind_a in result.matrix[ind_b]:
                v1 = result.matrix[ind_a][ind_b]
                v2 = result.matrix[ind_b][ind_a]
                assert abs(v1 - v2) < 0.001


def test_strong_correlation_detected(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    strong = [c for c in result.strong_correlations if abs(c.pearson_r) > 0.5]
    assert len(strong) > 0


def test_feature_importance_present(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert len(result.feature_importance) > 0
    for fi in result.feature_importance:
        assert len(fi.features) > 0


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = analyze_correlations(data, {})
    assert result is not None
    assert len(result.strong_correlations) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_correlations.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write correlations.py**

Create `app/engine/smart/correlations.py`:
```python
import numpy as np
import pandas as pd
from typing import Dict, Any
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer

from app.engine.smart.schemas import (
    SmartCorrelationResult, CorrelationPair, FeatureImportance, ImportanceEntry,
)
from app.engine.smart.anomaly import FEATURE_KEYS


def _build_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    """Build DataFrame from hospital data."""
    rows = []
    for name, entry in all_hospital_data.items():
        row = {"hospital_name": name}
        row.update(entry.get("values", {}))
        row["governorate"] = entry.get("governorate", "unknown")
        row["hospital_type"] = entry.get("hospital_type", "unknown")
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_correlations(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> SmartCorrelationResult:
    """Compute correlation matrix and feature importance."""
    if len(all_hospital_data) < 3:
        available = [k for k in FEATURE_KEYS if any(
            k in v.get("values", {}) for v in all_hospital_data.values()
        )]
        return SmartCorrelationResult(
            matrix={}, indicators=available, strong_correlations=[], feature_importance=[],
        )

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]

    # Correlation matrix
    matrix = {}
    strong_correlations = []

    for i, ind_a in enumerate(numeric_cols):
        matrix[ind_a] = {}
        for j, ind_b in enumerate(numeric_cols):
            valid = df[[ind_a, ind_b]].dropna()
            if len(valid) < 3:
                matrix[ind_a][ind_b] = 0.0
                continue
            r, p = pearsonr(valid[ind_a], valid[ind_b])
            matrix[ind_a][ind_b] = float(r)

            if j > i and abs(r) > 0.7 and p < 0.05:
                s_r, _ = spearmanr(valid[ind_a], valid[ind_b])
                if abs(r) > 0.9:
                    strength = "strong_positive" if r > 0 else "strong_negative"
                elif abs(r) > 0.7:
                    strength = "moderate_positive" if r > 0 else "moderate_negative"
                else:
                    strength = "weak"
                strong_correlations.append(CorrelationPair(
                    indicator_a=ind_a,
                    indicator_b=ind_b,
                    pearson_r=float(r),
                    spearman_r=float(s_r),
                    p_value=float(p),
                    strength=strength,
                ))

    # Feature importance via RandomForest
    feature_importance = []
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    cat_data = df[["governorate", "hospital_type"]].fillna("unknown")
    cat_encoded = encoder.fit_transform(cat_data)

    for target in numeric_cols:
        available = df.dropna(subset=[target])
        if len(available) < 5:
            continue

        y = available[target].values
        X_numeric = available[numeric_cols].drop(columns=[target]).fillna(0).values

        cat_idx = [i for i, name in enumerate(
            list(encoder.get_feature_names_out(["governorate", "hospital_type"]))
        )]
        X_cat = cat_encoded[available.index]

        X = np.hstack([X_numeric, X_cat])

        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        cv_scores = cross_val_score(rf, X, y, cv=min(3, len(available)), scoring="r2")

        if cv_scores.mean() < 0.3:
            continue

        rf.fit(X, y)
        importances = rf.feature_importances_

        feature_names = [c for c in numeric_cols if c != target]
        feature_names += list(encoder.get_feature_names_out(["governorate", "hospital_type"]))

        ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
        features = [
            ImportanceEntry(feature_name=name, importance=float(imp), rank=rank + 1)
            for rank, (name, imp) in enumerate(ranked[:5])
        ]
        feature_importance.append(FeatureImportance(target_indicator=target, features=features))

    return SmartCorrelationResult(
        matrix=matrix,
        indicators=numeric_cols,
        strong_correlations=strong_correlations,
        feature_importance=feature_importance,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_correlations.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/correlations.py tests/test_smart_correlations.py
git commit -m "feat(smart): add correlation matrix + RF feature importance"
```

---

### Task 6: Residual Analysis

**Files:**
- Create: `app/engine/smart/residual.py`
- Create: `tests/test_smart_residuals.py`

**Interfaces:**
- Consumes: Same `all_hospital_data` format
- Produces: `List[ResidualResult]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_residuals.py`:
```python
import pytest
import numpy as np
from app.engine.smart.residual import analyze_residuals


@pytest.fixture
def sample_data():
    np.random.seed(42)
    data = {}
    governorates = ["Gaza", "Gaza", "Gaza", "North Gaza", "North Gaza",
                    "Khan Younis", "Khan Younis", "Rafah", "Deir al-Balah", "Deir al-Balah"]
    types = ["general", "general", "specialist", "general", "general",
             "general", "specialist", "general", "general", "general"]
    for i in range(10):
        base = 25.0
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": governorates[i],
            "hospital_type": types[i],
            "values": {
                "cs_rate": base + np.random.normal(0, 3),
                "smm_total": 5.0 + np.random.normal(0, 1),
                "mat_deaths": 1.0 + np.random.normal(0, 0.3),
                "nd": 2.0 + np.random.normal(0, 0.5),
                "sb": 1.0 + np.random.normal(0, 0.3),
                "preterm": 10.0 + np.random.normal(0, 2),
                "lbw": 8.0 + np.random.normal(0, 1.5),
                "total_births": 200.0 + np.random.normal(0, 20),
                "high_risk": 15.0 + np.random.normal(0, 3),
                "adolescent": 3.0 + np.random.normal(0, 1),
            },
        }
    # Make Hospital 0 an outlier
    data["Hospital 0"]["values"]["cs_rate"] = 60.0
    return data


def test_returns_list_of_residual_results(sample_data):
    results = analyze_residuals(sample_data, {})
    assert isinstance(results, list)
    assert len(results) > 0


def test_outlier_detected(sample_data):
    results = analyze_residuals(sample_data, {})
    hospital_0 = [r for r in results if r.hospital_name == "Hospital 0" and r.indicator == "cs_rate"]
    assert len(hospital_0) > 0
    assert hospital_0[0].is_anomaly is True


def test_normal_hospital_not_flagged(sample_data):
    results = analyze_residuals(sample_data, {})
    hospital_5 = [r for r in results if r.hospital_name == "Hospital 5" and r.indicator == "cs_rate"]
    assert len(hospital_5) > 0
    assert hospital_5[0].is_anomaly is False


def test_residual_equals_actual_minus_predicted(sample_data):
    results = analyze_residuals(sample_data, {})
    for r in results:
        expected = r.actual_value - r.predicted_value
        assert abs(r.residual - expected) < 0.001


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = analyze_residuals(data, {})
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_residuals.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write residual.py**

Create `app/engine/smart/residual.py`:
```python
import numpy as np
import pandas as pd
from typing import Dict, Any, List
import statsmodels.api as sm
from statsmodels.formula.api import ols

from app.engine.smart.schemas import ResidualResult
from app.engine.smart.anomaly import FEATURE_KEYS


def _build_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, entry in all_hospital_data.items():
        row = {"hospital_name": name, "hospital_id": entry.get("hospital_id", 0)}
        row.update(entry.get("values", {}))
        row["governorate"] = entry.get("governorate", "unknown")
        row["hospital_type"] = entry.get("hospital_type", "unknown")
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_residuals(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    threshold_z: float = 2.0,
) -> List[ResidualResult]:
    """Run OLS regression per indicator, flag residuals > threshold_z sigma."""
    if len(all_hospital_data) < 5:
        return []

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]
    results = []

    for indicator in numeric_cols:
        valid = df.dropna(subset=[indicator]).copy()
        if len(valid) < 5:
            continue

        try:
            formula = f'{indicator} ~ C(governorate) + C(hospital_type)'
            model = ols(formula, data=valid).fit()
            residuals = model.resid
        except Exception:
            continue

        if residuals.std() < 1e-10:
            continue

        residual_z = (residuals - residuals.mean()) / residuals.std()

        for idx in valid.index:
            name = valid.loc[idx, "hospital_name"]
            hospital_id = all_hospital_data[name].get("hospital_id", 0)
            actual = float(valid.loc[idx, indicator])
            predicted = float(model.fittedvalues[idx])
            resid = float(residuals[idx])
            z = float(residual_z[idx])
            is_anomaly = abs(z) > threshold_z

            if abs(z) > threshold_z:
                severity = "critical"
            elif abs(z) > 1.5:
                severity = "warning"
            else:
                severity = "normal"

            results.append(ResidualResult(
                hospital_name=name,
                hospital_id=hospital_id,
                indicator=indicator,
                actual_value=actual,
                predicted_value=predicted,
                residual=resid,
                residual_z_score=z,
                is_anomaly=is_anomaly,
                severity=severity,
            ))

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_residuals.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/residual.py tests/test_smart_residuals.py
git commit -m "feat(smart): add OLS residual analysis for location/type adjustment"
```

---

### Task 7: Stratified Analysis

**Files:**
- Create: `app/engine/smart/stratified.py`
- Create: `tests/test_smart_stratified.py`

**Interfaces:**
- Consumes: Same `all_hospital_data` format
- Produces: `List[StratifiedComparison]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_stratified.py`:
```python
import pytest
import numpy as np
from app.engine.smart.stratified import run_stratified_analysis


@pytest.fixture
def sample_data():
    data = {}
    for i in range(8):
        gov = ["Gaza", "Gaza", "Gaza", "Gaza", "North Gaza", "North Gaza", "Khan Younis", "Khan Younis"][i]
        typ = ["general", "general", "general", "general", "general", "general", "specialist", "specialist"][i]
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": gov,
            "hospital_type": typ,
            "values": {
                "cs_rate": 25.0 + i * 2 + np.random.normal(0, 1),
                "smm_total": 5.0 + np.random.normal(0, 0.5),
                "mat_deaths": 1.0 + np.random.normal(0, 0.2),
                "nd": 2.0 + np.random.normal(0, 0.3),
                "sb": 1.0 + np.random.normal(0, 0.1),
                "preterm": 10.0 + np.random.normal(0, 1),
                "lbw": 8.0 + np.random.normal(0, 0.5),
                "total_births": 200.0 + np.random.normal(0, 10),
                "high_risk": 15.0 + np.random.normal(0, 2),
                "adolescent": 3.0 + np.random.normal(0, 0.5),
            },
        }
    return data


def test_returns_list_of_comparisons(sample_data):
    results = run_stratified_analysis(sample_data, {})
    assert isinstance(results, list)
    assert len(results) > 0


def test_peer_group_size(sample_data):
    results = run_stratified_analysis(sample_data, {})
    for r in results:
        assert r.peer_group_size >= 1


def test_rank_within_peer_group(sample_data):
    results = run_stratified_analysis(sample_data, {})
    for r in results:
        assert 1 <= r.rank_in_peer_group <= r.peer_group_size


def test_label_valid(sample_data):
    results = run_stratified_analysis(sample_data, {})
    valid_labels = {"above_average", "average", "below_average", "significantly_above", "significantly_below"}
    for r in results:
        assert r.label in valid_labels


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = run_stratified_analysis(data, {})
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_stratified.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write stratified.py**

Create `app/engine/smart/stratified.py`:
```python
import numpy as np
import pandas as pd
from typing import Dict, Any, List

from app.engine.smart.schemas import StratifiedComparison
from app.engine.smart.anomaly import FEATURE_KEYS


def _build_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, entry in all_hospital_data.items():
        row = {"hospital_name": name, "hospital_id": entry.get("hospital_id", 0)}
        row.update(entry.get("values", {}))
        row["governorate"] = entry.get("governorate", "unknown")
        row["hospital_type"] = entry.get("hospital_type", "unknown")
        rows.append(row)
    return pd.DataFrame(rows)


def _get_peer_group(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    """Get peer group: same governorate + type, fallback to same governorate, fallback to all."""
    gov = df.loc[idx, "governorate"]
    typ = df.loc[idx, "hospital_type"]

    # Try exact match
    mask = (df["governorate"] == gov) & (df["hospital_type"] == typ)
    if mask.sum() >= 3:
        return df[mask]

    # Fallback: same governorate
    mask = df["governorate"] == gov
    if mask.sum() >= 3:
        return df[mask]

    # Fallback: same type
    mask = df["hospital_type"] == typ
    if mask.sum() >= 3:
        return df[mask]

    # Fallback: all hospitals
    return df


def run_stratified_analysis(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> List[StratifiedComparison]:
    """Compare each hospital against its peer group for each indicator."""
    if len(all_hospital_data) < 3:
        return []

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]
    results = []

    for indicator in numeric_cols:
        if indicator not in df.columns:
            continue

        for idx in df.index:
            peer = _get_peer_group(df, idx)
            peer_values = peer[indicator].dropna()
            if len(peer_values) < 2:
                continue

            hospital_value = df.loc[idx, indicator]
            if pd.isna(hospital_value):
                continue

            mean = peer_values.mean()
            std = peer_values.std()
            if std < 1e-10:
                continue

            deviation_pct = ((hospital_value - mean) / mean * 100) if mean != 0 else 0.0
            rank = int(peer_values.rank(ascending=False)[idx])

            z = (hospital_value - mean) / std
            if z > 1.5:
                label = "significantly_above"
            elif z > 0.5:
                label = "above_average"
            elif z < -1.5:
                label = "significantly_below"
            elif z < -0.5:
                label = "below_average"
            else:
                label = "average"

            results.append(StratifiedComparison(
                hospital_name=df.loc[idx, "hospital_name"],
                hospital_id=int(df.loc[idx, "hospital_id"]),
                indicator=indicator,
                hospital_value=float(hospital_value),
                peer_group_mean=float(mean),
                peer_group_std=float(std),
                deviation_pct=float(deviation_pct),
                rank_in_peer_group=rank,
                peer_group_size=len(peer_values),
                label=label,
            ))

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_stratified.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/stratified.py tests/test_smart_stratified.py
git commit -m "feat(smart): add stratified peer-group comparison analysis"
```

---

### Task 8: SHAP Explainability

**Files:**
- Create: `app/engine/smart/explainability.py`
- Create: `tests/test_smart_explain.py`

**Interfaces:**
- Consumes: `List[SmartAnomalyResult]` from Task 3, `all_hospital_data`
- Produces: `List[AnomalyExplanation]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_explain.py`:
```python
import pytest
from app.engine.smart.schemas import SmartAnomalyResult
from app.engine.smart.explainability import explain_anomalies


@pytest.fixture
def sample_anomalies():
    return [
        SmartAnomalyResult(
            hospital_name="Hospital A", hospital_id=1,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.8, severity="critical", is_outlier=True,
            method_scores={"isolation_forest": 0.9, "lof": 0.7, "mahalanobis": 0.6, "residual": 0.5},
        ),
        SmartAnomalyResult(
            hospital_name="Hospital B", hospital_id=2,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.2, severity="normal", is_outlier=False,
            method_scores={"isolation_forest": 0.1, "lof": 0.2, "mahalanobis": 0.3, "residual": 0.1},
        ),
    ]


@pytest.fixture
def sample_data():
    import numpy as np
    data = {}
    for i in range(8):
        data[f"Hospital {i}"] = {
            "hospital_id": i, "governorate": "Gaza", "hospital_type": "general",
            "values": {
                "cs_rate": 25.0 + i * 2 + np.random.normal(0, 1),
                "smm_total": 5.0 + np.random.normal(0, 0.5),
                "mat_deaths": 1.0 + np.random.normal(0, 0.2),
                "nd": 2.0 + np.random.normal(0, 0.3),
                "sb": 1.0, "preterm": 10.0, "lbw": 8.0,
                "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0,
            },
        }
    return data


def test_explanations_for_outliers_only(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results) == 1
    assert results[0].hospital_name == "Hospital A"


def test_top_factors_present(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].top_factors) > 0
    assert len(results[0].top_factors) <= 3


def test_text_explanation_in_arabic(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].text_explanation) > 0


def test_disabled_returns_empty(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": False})
    assert results == []


def test_no_outliers_returns_empty(sample_data):
    anomalies = [
        SmartAnomalyResult(
            hospital_name="H", hospital_id=1, governorate="G", hospital_type="t",
            anomaly_score=0.1, severity="normal", is_outlier=False,
            method_scores={}, 
        )
    ]
    results = explain_anomalies(anomalies, sample_data, {"shap_enabled": True})
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_explain.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write explainability.py**

Create `app/engine/smart/explainability.py`:
```python
import numpy as np
from typing import Dict, Any, List
import shap
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer

from app.engine.smart.schemas import SmartAnomalyResult, AnomalyExplanation, FactorExplanation
from app.engine.smart.anomaly import FEATURE_KEYS, _prepare_features

ARABIC_NAMES = {
    "cs_rate": "معدل العمليات القيصارية",
    "smm_total": "المضاعفات الخطيرة",
    "mat_deaths": "الوفيات الأمومية",
    "nd": "الوفيات新生儿",
    "sb": "الولادات الميتة",
    "preterm": "الولادات السابقة لأوانها",
    "lbw": "نقص وزن الولادة",
    "total_births": "إجمالي المواليد",
    "high_risk": "حالات الخطر العالي",
    "adolescent": "الحالات المراهقة",
    "governorate": "المحافظة",
    "hospital_type": "نوع المستشفى",
}


def explain_anomalies(
    anomalies: List[SmartAnomalyResult],
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> List[AnomalyExplanation]:
    """Generate SHAP explanations for outlier hospitals."""
    if not config.get("shap_enabled", True):
        return []

    outliers = [a for a in anomalies if a.is_outlier]
    if not outliers or len(all_hospital_data) < 3:
        return []

    combined, hospital_names = _prepare_features(all_hospital_data)
    feature_names = list(FEATURE_KEYS)

    # Add one-hot encoded feature names
    categorical_data = []
    for name in hospital_names:
        entry = all_hospital_data[name]
        categorical_data.append([
            entry.get("governorate", "unknown"),
            entry.get("hospital_type", "unknown"),
        ])
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    encoder.fit(categorical_data)
    feature_names += list(encoder.get_feature_names_out(["governorate", "hospital_type"]))

    # Train Isolation Forest
    iforest = IsolationForest(contamination=0.1, random_state=42)
    iforest.fit(combined)

    # SHAP
    explainer = shap.TreeExplainer(iforest)
    shap_values = explainer.shap_values(combined)

    explanations = []
    for outlier in outliers:
        idx = hospital_names.index(outlier.hospital_name) if outlier.hospital_name in hospital_names else -1
        if idx < 0:
            continue

        sv = shap_values[idx]
        feature_shap = dict(zip(feature_names, sv.tolist()))

        # Top 3 factors
        sorted_features = sorted(feature_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        top_factors = []
        for feat, val in sorted_features:
            direction = "increases_anomaly" if val > 0 else "decreases_anomaly"
            magnitude = "high" if abs(val) > 0.5 else "medium" if abs(val) > 0.2 else "low"
            arabic = ARABIC_NAMES.get(feat, feat)
            top_factors.append(FactorExplanation(
                feature=feat, shap_value=float(val),
                direction=direction, magnitude=magnitude, arabic_label=arabic,
            ))

        # Text explanation
        factors_text = []
        for f in top_factors:
            direction_ar = "ارتفاع غير متوقع في" if f.direction == "increases_anomaly" else "انخفاض غير متوقع في"
            factors_text.append(f"{direction_ar} {f.arabic_label}")
        text = f"يظهر هذا المستشفى كشاذ بسبب: {'، '.join(factors_text)}."

        explanations.append(AnomalyExplanation(
            hospital_name=outlier.hospital_name,
            hospital_id=outlier.hospital_id,
            anomaly_score=outlier.anomaly_score,
            severity=outlier.severity,
            shap_values=feature_shap,
            top_factors=top_factors,
            text_explanation=text,
        ))

    return explanations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_explain.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/explainability.py tests/test_smart_explain.py
git commit -m "feat(smart): add SHAP explainability with Arabic text generation"
```

---

### Task 9: Geo Aggregation

**Files:**
- Create: `app/engine/smart/geo.py`
- Create: `data/geo/gaza_governorates.geojson`

**Interfaces:**
- Consumes: `List[SmartAnomalyResult]`, `all_hospital_data`
- Produces: `GeoAggregationResult`

- [ ] **Step 1: Create GeoJSON**

Create `data/geo/gaza_governorates.geojson` with approximate boundaries for 5 Gaza governorates. This is a standard GeoJSON FeatureCollection:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {"name": "شمال غزة", "name_en": "North Gaza"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[34.45, 31.55], [34.55, 31.55], [34.55, 31.45], [34.45, 31.45], [34.45, 31.55]]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": " غزة", "name_en": "Gaza"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[34.40, 31.50], [34.50, 31.50], [34.50, 31.40], [34.40, 31.40], [34.40, 31.50]]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "دير البلح", "name_en": "Deir al-Balah"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[34.35, 31.45], [34.45, 31.45], [34.45, 31.35], [34.35, 31.35], [34.35, 31.45]]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "خانيونس", "name_en": "Khan Younis"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[34.30, 31.38], [34.40, 31.38], [34.40, 31.28], [34.30, 31.28], [34.30, 31.38]]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "رفح", "name_en": "Rafah"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[34.25, 31.30], [34.35, 31.30], [34.35, 31.20], [34.25, 31.20], [34.25, 31.30]]]
      }
    }
  ]
}
```

- [ ] **Step 2: Write geo.py**

Create `app/engine/smart/geo.py`:
```python
from typing import List, Dict, Any
from collections import defaultdict

from app.engine.smart.schemas import GeoAggregationResult, GovernorateAgg, SmartAnomalyResult
from app.engine.smart.anomaly import FEATURE_KEYS


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
    """Aggregate anomaly results by governorate for map visualization."""
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
```

- [ ] **Step 3: Commit**

```bash
git add app/engine/smart/geo.py data/geo/gaza_governorates.geojson
git commit -m "feat(smart): add governorate geo aggregation + Gaza GeoJSON"
```

---

### Task 10: Orchestrator

**Files:**
- Modify: `app/engine/smart/__init__.py`
- Create: `tests/test_smart_pipeline.py`

**Interfaces:**
- Consumes: SQLAlchemy `session`, `month: str`
- Produces: `SmartAnalyticsResult`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_pipeline.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from app.engine.smart.schemas import SmartAnalyticsResult


def test_orchestrator_returns_result():
    from app.engine.smart import run_smart_analytics

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    result = run_smart_analytics(mock_session, "2026-06")
    # With no data, should return a minimal result
    assert isinstance(result, SmartAnalyticsResult)
    assert result.month == "2026-06"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_pipeline.py -v`
Expected: FAIL with import error or function signature mismatch

- [ ] **Step 3: Write orchestrator**

Rewrite `app/engine/smart/__init__.py`:
```python
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.engine.smart.schemas import SmartAnalyticsResult, KPISummary
from app.engine.smart.anomaly import detect_smart_anomalies
from app.engine.smart.clustering import run_clustering
from app.engine.smart.correlations import analyze_correlations
from app.engine.smart.residual import analyze_residuals
from app.engine.smart.stratified import run_stratified_analysis
from app.engine.smart.explainability import explain_anomalies
from app.engine.smart.geo import aggregate_by_governorate


def _load_hospital_data(session: Session, month: str) -> Dict[str, Any]:
    """Load all hospital data for a month from DB."""
    from app.models import Hospital, IndicatorValue, Indicator

    hospitals = session.query(Hospital).filter(Hospital.is_active == True).all()
    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}

    all_data = {}
    for hosp in hospitals:
        values = session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hosp.id,
            IndicatorValue.month == month,
        ).all()

        indicator_values = {}
        for iv in values:
            code = indicator_map.get(iv.indicator_id, "")
            if code and iv.value is not None:
                indicator_values[code] = float(iv.value)

        all_data[hosp.name] = {
            "hospital_id": hosp.id,
            "governorate": hosp.governorate.name if hosp.governorate else "unknown",
            "hospital_type": hosp.hospital_type.name if hosp.hospital_type else "unknown",
            "values": indicator_values,
        }

    return all_data


def _load_config(session: Session) -> Dict[str, Any]:
    """Load smart_analytics config from AppConfig."""
    from app.models import AppConfig

    configs = session.query(AppConfig).filter(
        AppConfig.category == "smart_analytics"
    ).all()

    config = {}
    for c in configs:
        key = c.key.replace("smart_", "")
        config[key] = c.value

    return config


def run_smart_analytics(session: Session, month: str) -> SmartAnalyticsResult:
    """Run the full smart analytics pipeline for a given month."""
    all_data = _load_hospital_data(session, month)
    config = _load_config(session)

    enabled = config.get("enabled", 1.0) > 0.5

    anomalies = detect_smart_anomalies(all_data, config, enabled=enabled)
    clustering = run_clustering(all_data, config, enabled=enabled)
    correlations = analyze_correlations(all_data, config)
    residuals = analyze_residuals(all_data, config)
    stratified = run_stratified_analysis(all_data, config)
    explanations = explain_anomalies(anomalies, all_data, config)
    geo = aggregate_by_governorate(anomalies, all_data)

    # Update ensemble scores with residual data
    residual_by_hospital = {}
    for r in residuals:
        if r.indicator == "cs_rate":
            residual_by_hospital[r.hospital_name] = abs(r.residual_z_score) / 4.0

    for a in anomalies:
        if a.hospital_name in residual_by_hospital:
            a.method_scores["residual"] = residual_by_hospital[a.hospital_name]

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    affected_govs = len(set(a.governorate for a in anomalies if a.is_outlier))

    top_factor = ""
    if explanations:
        all_factors = []
        for e in explanations:
            all_factors.extend(e.top_factors)
        if all_factors:
            top_factor = max(all_factors, key=lambda f: abs(f.shap_value)).arabic_label

    if critical_count > 0:
        month_status = "critical"
    elif warning_count > 0:
        month_status = "attention_needed"
    else:
        month_status = "normal"

    kpi = KPISummary(
        total_anomalies=critical_count + warning_count,
        critical_count=critical_count,
        warning_count=warning_count,
        affected_governorates=affected_govs,
        top_contributing_factor=top_factor,
        month_status=month_status,
    )

    return SmartAnalyticsResult(
        month=month,
        hospitals_count=len(all_data),
        anomalies=anomalies,
        clustering=clustering,
        correlations=correlations,
        residuals=residuals,
        stratified=stratified,
        explanations=explanations,
        geo=geo,
        kpi=kpi,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smart_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/smart/__init__.py tests/test_smart_pipeline.py
git commit -m "feat(smart): add orchestrator run_smart_analytics()"
```

---

### Task 11: API Router

**Files:**
- Create: `app/api/smart_analytics.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `run_smart_analytics()` from Task 10
- Produces: JSON responses for all `/smart/*` endpoints

- [ ] **Step 1: Write smart_analytics.py**

Create `app/api/smart_analytics.py`:
```python
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.smart import run_smart_analytics
from app.engine.smart.schemas import SmartAnalyticsResult

router = APIRouter(prefix="/smart", tags=["Smart Analytics"])


def _envelope(result: SmartAnalyticsResult) -> dict:
    return {
        "month": result.month,
        "generated_at": datetime.now().isoformat(),
        "hospitals_count": result.hospitals_count,
        "data": {
            "kpi": result.kpi.__dict__,
            "anomalies": [a.__dict__ for a in result.anomalies],
            "clustering": result.clustering.__dict__ if result.clustering else None,
            "correlations": result.correlations.__dict__ if result.correlations else None,
            "residuals": [r.__dict__ for r in result.residuals],
            "stratified": [s.__dict__ for s in result.stratified],
            "explanations": [
                {**e.__dict__, "top_factors": [f.__dict__ for f in e.top_factors]}
                for e in result.explanations
            ],
            "geo": result.geo.__dict__ if result.geo else None,
        },
    }


@router.get("/overview/{month}")
def get_overview(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    return _envelope(result)


@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {
        "month": month,
        "anomalies": data["anomalies"],
        "explanations": data["explanations"],
    }


@router.get("/clusters/{month}")
def get_clusters(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {"month": month, "clustering": data["clustering"]}


@router.get("/correlations/{month}")
def get_correlations(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {"month": month, "correlations": data["correlations"]}


@router.get("/residuals/{month}")
def get_residuals(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {"month": month, "residuals": data["residuals"]}


@router.get("/stratified/{month}")
def get_stratified(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {"month": month, "stratified": data["stratified"]}


@router.get("/geo/{month}")
def get_geo(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    return {"month": month, "geo": data["geo"]}


@router.get("/trend/{hospital_id}")
def get_trend(hospital_id: int, db: Session = Depends(get_db)):
    from app.models import Hospital
    from app.api.analysis import get_analysis_months

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    months = [m["month"] for m in get_analysis_months(db)]
    trend_data = []
    for m in months:
        result = run_smart_analytics(db, m)
        hospital_anomaly = next(
            (a for a in result.anomalies if a.hospital_id == hospital_id), None
        )
        if hospital_anomaly:
            trend_data.append({
                "month": m,
                "anomaly_score": hospital_anomaly.anomaly_score,
                "severity": hospital_anomaly.severity,
                "method_scores": hospital_anomaly.method_scores,
            })

    return {"hospital_id": hospital_id, "hospital_name": hospital.name, "trend": trend_data}


@router.get("/drilldown/{hospital_id}/{month}")
def get_drilldown(hospital_id: int, month: str, db: Session = Depends(get_db)):
    from app.models import Hospital

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    result = run_smart_analytics(db, month)
    anomaly = next((a for a in result.anomalies if a.hospital_id == hospital_id), None)
    explanation = next((e for e in result.explanations if e.hospital_id == hospital_id), None)
    residuals = [r for r in result.residuals if r.hospital_id == hospital_id]
    stratified = [s for s in result.stratified if s.hospital_id == hospital_id]

    return {
        "hospital_id": hospital_id,
        "hospital_name": hospital.name,
        "month": month,
        "anomaly": anomaly.__dict__ if anomaly else None,
        "explanation": {
            **explanation.__dict__,
            "top_factors": [f.__dict__ for f in explanation.top_factors],
        } if explanation else None,
        "residuals": [r.__dict__ for r in residuals],
        "stratified": [s.__dict__ for s in stratified],
    }


@router.post("/run/{month}")
def trigger_analysis(month: str, db: Session = Depends(get_db)):
    result = run_smart_analytics(db, month)
    return {"status": "completed", "month": month, "hospitals_count": result.hospitals_count}
```

- [ ] **Step 2: Mount router in main.py**

In `app/main.py`, find where other routers are mounted (e.g., `app.include_router(...)`) and add:
```python
from app.api.smart_analytics import router as smart_analytics_router
app.include_router(smart_analytics_router)
```

- [ ] **Step 3: Commit**

```bash
git add app/api/smart_analytics.py app/main.py
git commit -m "feat(smart): add /smart API router with 10 endpoints"
```

---

### Task 12: Frontend Tab

**Files:**
- Create: `static/tabs/smart-analytics.html`
- Create: `static/js/smart-analytics.js`
- Modify: `static/index.html`

**Interfaces:**
- Consumes: All `/smart/*` API endpoints from Task 11
- Produces: Interactive Plotly.js dashboard

- [ ] **Step 1: Create tab HTML**

Create `static/tabs/smart-analytics.html`:
```html
<div class="smart-analytics-tab" dir="rtl">
  <!-- Month selector -->
  <div class="smart-controls">
    <label>الشهر:</label>
    <select id="smart-month-select" class="form-control"></select>
    <button id="smart-refresh" class="btn btn-primary">تحديث</button>
  </div>

  <!-- Row 1: KPI Cards -->
  <div class="smart-kpi-row" id="smart-kpi-container"></div>

  <!-- Row 2: Map + Cluster -->
  <div class="smart-row">
    <div class="smart-col-60">
      <h3>خريطة المحافظات</h3>
      <div id="smart-geo-map" style="height:400px;"></div>
      <p class="smart-interpretation" id="smart-geo-text"></p>
    </div>
    <div class="smart-col-40">
      <h3>تجميع المستشفيات</h3>
      <div id="smart-cluster-scatter" style="height:400px;"></div>
      <p class="smart-interpretation" id="smart-cluster-text"></p>
    </div>
  </div>

  <!-- Row 3: Correlation + Residuals -->
  <div class="smart-row">
    <div class="smart-col-50">
      <h3>مصفوفة الارتباط</h3>
      <div id="smart-correlation-heatmap" style="height:400px;"></div>
      <p class="smart-interpretation" id="smart-corr-text"></p>
    </div>
    <div class="smart-col-50">
      <h3>رسم البواقي</h3>
      <div id="smart-residual-plot" style="height:400px;"></div>
      <p class="smart-interpretation" id="smart-residual-text"></p>
    </div>
  </div>

  <!-- Row 4: Anomaly Table + Feature Importance -->
  <div class="smart-row">
    <div class="smart-col-60">
      <h3>جدول الشذوذ</h3>
      <div id="smart-anomaly-table"></div>
      <p class="smart-interpretation" id="smart-table-text"></p>
    </div>
    <div class="smart-col-40">
      <h3>أهمية العوامل</h3>
      <div id="smart-feature-importance" style="height:400px;"></div>
      <p class="smart-interpretation" id="smart-fi-text"></p>
    </div>
  </div>

  <!-- Row 5: Stratified Comparison -->
  <div class="smart-row-full">
    <h3>مقارنة طبقية</h3>
    <div id="smart-stratified-chart" style="height:400px;"></div>
    <p class="smart-interpretation" id="smart-strat-text"></p>
  </div>

  <!-- Row 6: Drill-down (hidden) -->
  <div class="smart-drilldown" id="smart-drilldown-panel" style="display:none;">
    <h3>تفاصيل المستشفى: <span id="smart-drilldown-name"></span></h3>
    <div class="smart-row">
      <div class="smart-col-50">
        <h4>عوامل SHAP</h4>
        <div id="smart-shap-waterfall" style="height:300px;"></div>
      </div>
      <div class="smart-col-50">
        <h4>الاتجاه الزمني</h4>
        <div id="smart-trend-line" style="height:300px;"></div>
      </div>
    </div>
    <p class="smart-interpretation" id="smart-drilldown-text"></p>
    <button id="smart-close-drilldown" class="btn btn-secondary">إغلاق</button>
  </div>
</div>
```

- [ ] **Step 2: Create smart-analytics.js**

Create `static/js/smart-analytics.js` with full Plotly chart implementations. This is the largest file. Key functions:

```javascript
const SMART_COLORS = {
  normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444',
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],
  noise: '#6b7280', shap_positive: '#ef4444', shap_negative: '#3b82f6',
};

let currentMonth = null;

export async function initSmartAnalytics() {
  const months = await apiGet('/analysis/months');
  const select = document.getElementById('smart-month-select');
  months.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.month; opt.textContent = m.month;
    select.appendChild(opt);
  });
  select.addEventListener('change', () => loadSmartData(select.value));
  document.getElementById('smart-refresh').addEventListener('click', () => loadSmartData(select.value));
  document.getElementById('smart-close-drilldown').addEventListener('click', () => {
    document.getElementById('smart-drilldown-panel').style.display = 'none';
  });
  if (months.length > 0) {
    select.value = months[months.length - 1].month;
    loadSmartData(select.value);
  }
}

async function loadSmartData(month) {
  currentMonth = month;
  const data = await apiGet(`/smart/overview/${month}`);
  renderKPIs(data.data.kpi);
  renderGeoMap(data.data.geo, month);
  renderClusterScatter(data.data.clustering, data.data.anomalies);
  renderCorrelationHeatmap(data.data.correlations);
  renderResidualPlot(data.data.residuals);
  renderAnomalyTable(data.data.anomalies, data.data.explanations);
  renderFeatureImportance(data.data.correlations);
  renderStratifiedComparison(data.data.stratified);
}

function renderKPIs(kpi) {
  const container = document.getElementById('smart-kpi-container');
  container.innerHTML = `
    <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.total_anomalies}</div><div class="smart-kpi-label">حالات شاذة</div></div>
    <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.affected_governorates}</div><div class="smart-kpi-label">محافظات متأثرة</div></div>
    <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.top_contributing_factor || '-'}</div><div class="smart-kpi-label">العامل الأبرز</div></div>
    <div class="smart-kpi-card smart-kpi-${kpi.month_status}"><div class="smart-kpi-value">${kpi.month_status === 'critical' ? 'حرج' : kpi.month_status === 'attention_needed' ? 'يحتاج مراقبة' : 'طبيعي'}</div><div class="smart-kpi-label">حالة الشهر</div></div>
  `;
}

function renderGeoMap(geo, month) {
  if (!geo || !geo.governorates) return;
  const data = [{
    type: 'choropleth',
    locations: geo.governorates.map(g => g.governorate),
    z: geo.governorates.map(g => g.avg_anomaly_score),
    text: geo.governorates.map(g => `${g.governorate}<br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${g.avg_anomaly_score.toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`),
    colorscale: [[0, SMART_COLORS.normal], [0.3, SMART_COLORS.normal], [0.3, SMART_COLORS.warning], [0.6, SMART_COLORS.warning], [0.6, SMART_COLORS.critical], [1, SMART_COLORS.critical]],
    showscale: true,
  }];
  Plotly.newPlot('smart-geo-map', data, {geo: {scope: 'asia', center: {lat: 31.4, lon: 34.4}, projection: {scale: 8000}}, margin: {t: 0, b: 0, l: 0, r: 0}});
  const affected = geo.governorates.filter(g => g.avg_anomaly_score > 0.3).length;
  document.getElementById('smart-geo-text').textContent = `${affected} محافظات تظهر انحرافات عن المعدل المتوقع هذا الشهر.`;
}

function renderClusterScatter(clustering, anomalies) {
  if (!clustering || !clustering.pca_coordinates) return;
  const coords = clustering.pca_coordinates;
  const anomalyMap = {};
  anomalies.forEach(a => { anomalyMap[a.hospital_name] = a; });

  const traces = [];
  const clusterColors = {};
  let ci = 0;

  clustering.clusters.forEach(c => {
    if (!(c.cluster_id in clusterColors)) {
      clusterColors[c.cluster_id] = SMART_COLORS.clusters[ci % SMART_COLORS.clusters.length];
      ci++;
    }
  });

  // Group by cluster
  const grouped = {};
  clustering.clusters.forEach(c => {
    if (!grouped[c.cluster_id]) grouped[c.cluster_id] = [];
    grouped[c.cluster_id].push(c);
  });

  Object.entries(grouped).forEach(([cid, hospitals]) => {
    const x = hospitals.map(h => coords[h.hospital_name]?.x || 0);
    const y = hospitals.map(h => coords[h.hospital_name]?.y || 0);
    const sizes = hospitals.map(h => {
      const a = anomalyMap[h.hospital_name];
      return a ? 8 + a.anomaly_score * 20 : 8;
    });
    const colors = hospitals.map(h => {
      const a = anomalyMap[h.hospital_name];
      if (a && a.severity === 'critical') return SMART_COLORS.critical;
      if (a && a.severity === 'warning') return SMART_COLORS.warning;
      return clusterColors[cid];
    });
    traces.push({
      x, y, mode: 'markers', type: 'scatter', name: `عنقود ${cid}`,
      marker: { size: sizes, color: colors },
      text: hospitals.map(h => `${h.hospital_name}<br>عنقود: ${cid}<br>شذوذ: ${(anomalyMap[h.hospital_name]?.anomaly_score || 0).toFixed(2)}`),
      hoverinfo: 'text',
    });
  });

  // Noise
  if (clustering.noise_hospitals.length > 0) {
    const nx = clustering.noise_hospitals.map(h => coords[h]?.x || 0);
    const ny = clustering.noise_hospitals.map(h => coords[h]?.y || 0);
    traces.push({
      x: nx, y: ny, mode: 'markers', type: 'scatter', name: 'نقاط ضوضاء',
      marker: { size: 10, color: SMART_COLORS.noise, symbol: 'x' },
      text: clustering.noise_hospitals.map(h => `${h}<br>خارج أي عنقود`),
      hoverinfo: 'text',
    });
  }

  Plotly.newPlot('smart-cluster-scatter', traces, {
    xaxis: {title: 'المكون الرئيسي الأول'}, yaxis: {title: 'المكون الرئيسي الثاني'},
    margin: {t: 20, b: 40, l: 60, r: 20},
  });

  const noiseCount = clustering.noise_hospitals.length;
  document.getElementById('smart-cluster-text').textContent =
    `تم تجميع المستشفيات إلى ${clustering.n_clusters} مجموعات.${noiseCount > 0 ? ` ${noiseCount} مستشفى خرج عن أي مجموعة.` : ''}`;
}

// ... (remaining chart functions follow same pattern)
```

- [ ] **Step 3: Add tab to index.html**

In `static/index.html`, add the tab button and content div following the pattern of existing tabs.

- [ ] **Step 4: Commit**

```bash
git add static/tabs/smart-analytics.html static/js/smart-analytics.js static/index.html
git commit -m "feat(smart): add Smart Analytics tab with Plotly.js charts"
```

---

### Task 13: Integration Tests + Verification

**Files:**
- Run all existing tests
- Run new tests
- Verify linting

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run linting**

Run: `ruff check app/engine/smart/ app/api/smart_analytics.py`
Expected: No errors

- [ ] **Step 3: Run type checking**

Run: `ruff check --select=E,F app/engine/smart/`
Expected: No errors

- [ ] **Step 4: Verify API starts**

Run: `python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(smart): complete smart analytics system with visualizations"
```
