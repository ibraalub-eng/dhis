# Smart Analytics System — Design Specification

**Date:** 2026-07-21
**Status:** Approved
**Scope:** Full build — anomaly detection, clustering, correlations, explainability, visual analytics

---

## 1. Problem Statement

The current HEALTH-ai system provides descriptive statistical analysis (z-scores, trends, quality scores) for ~20 hospitals across 6 months. The goal is to add a **smart analytics layer** that:

- Discovers non-obvious anomalies using multiple ML methods (not just z-score)
- Clusters hospitals by actual indicator similarity (not just geography)
- Reveals hidden relationships between health indicators
- Adjusts for hospital location and type to avoid misleading "anomaly" flags
- Explains every finding in plain language for non-technical decision makers
- Presents everything through interactive visualizations

## 2. Constraints

- **Data volume:** ~20 hospitals × 6 months ≈ 120 data-point-months. No time-series forecasting (insufficient data). Focus on cross-sectional analysis.
- **Data characteristics:** Mixed numeric (indicator values) + categorical (governorate, hospital type). Some indicators are rates, some are counts.
- **Architecture:** Separate `app/engine/smart/` package (Approach A). Does not modify existing engine modules. New API router + new SPA tab.
- **Visualization:** Plotly.js client-side in existing vanilla JS SPA. Arabic labels where applicable.
- **Geographic:** Plotly choropleth for Gaza governorates. GeoJSON boundaries for 5 governorates (North Gaza, Gaza City, Deir al-Balah, Khan Younis, Rafah). Source: OSM/GADM open data, stored in `data/geo/gaza_governorates.geojson`.

---

## 3. Engine Layer — `app/engine/smart/`

### 3.1 Package Structure

```
app/engine/smart/
├── __init__.py          # Orchestrator: run_smart_analytics(session, month)
├── schemas.py           # Dataclasses for all outputs
├── anomaly.py           # LOF, DBSCAN outlier scoring, Mahalanobis distance, ensemble
├── clustering.py        # DBSCAN + Hierarchical clustering
├── correlations.py      # Correlation matrix + Random Forest feature importance
├── residual.py          # OLS regression-based residual analysis
├── stratified.py        # Stratified peer-group comparisons
├── explainability.py    # SHAP values for anomaly explanation
└── geo.py               # Governorate-level aggregation
```

### 3.2 Data Flow

```
run_smart_analytics(session, month)
│
├── Load all hospital indicator data for `month`
├── Load hospital metadata (governorate_id, hospital_type_id)
│
├── anomaly.detect(all_hospital_data, hospital_meta, config)
│   → List[SmartAnomalyResult]
│
├── clustering.run(all_hospital_data, hospital_meta, config)
│   → SmartClusteringResult
│
├── correlations.analyze(all_hospital_data, config)
│   → SmartCorrelationResult
│
├── residual.analyze(all_hospital_data, hospital_meta, config)
│   → List[ResidualResult]
│
├── stratified.compare(all_hospital_data, hospital_meta, config)
│   → List[StratifiedComparison]
│
├── explainability.explain(anomaly_results, all_hospital_data, config)
│   → List[AnomalyExplanation]
│
├── geo.aggregate(all_hospital_data, hospital_meta, anomaly_results)
│   → GeoAggregationResult
│
└── Return SmartAnalyticsResult (unified dict)
```

### 3.3 Schemas (`schemas.py`)

```python
@dataclass
class SmartAnomalyResult:
    hospital_name: str
    hospital_id: int
    governorate: str
    hospital_type: str
    anomaly_score: float          # 0.0 - 1.0 ensemble
    method_scores: dict           # {"isolation_forest": 0.8, "lof": 0.7, "mahalanobis": 0.6, "residual": 0.5}
    severity: str                 # "normal" | "warning" | "critical"
    is_outlier: bool              # anomaly_score > critical_threshold

@dataclass
class SmartClusteringResult:
    n_clusters: int
    silhouette_score: float
    method: str                   # "dbscan" | "hierarchical"
    clusters: List[HospitalClusterAssignment]
    noise_hospitals: List[str]    # DBSCAN noise points
    pca_coordinates: dict         # {hospital_name: {x: float, y: float}}
    centroids: List[dict]         # cluster centroid feature values

@dataclass
class HospitalClusterAssignment:
    hospital_name: str
    hospital_id: int
    cluster_id: int               # -1 for noise
    distance_to_centroid: float

@dataclass
class SmartCorrelationResult:
    matrix: dict                  # {indicator_a: {indicator_b: correlation_value}}
    indicators: List[str]
    strong_correlations: List[CorrelationPair]
    feature_importance: List[FeatureImportance]

@dataclass
class CorrelationPair:
    indicator_a: str
    indicator_b: str
    pearson_r: float
    spearman_r: float
    p_value: float
    strength: str                 # "strong_positive" | "moderate_positive" | "weak" | "moderate_negative" | "strong_negative"

@dataclass
class FeatureImportance:
    target_indicator: str
    features: List[ImportanceEntry]

@dataclass
class ImportanceEntry:
    feature_name: str
    importance: float
    rank: int

@dataclass
class ResidualResult:
    hospital_name: str
    hospital_id: int
    indicator: str
    actual_value: float
    predicted_value: float
    residual: float
    residual_z_score: float
    is_anomaly: bool              # |residual_z| > 2.0
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
    label: str                    # "above_average" | "average" | "below_average" | "significantly_above" | "significantly_below"

@dataclass
class AnomalyExplanation:
    hospital_name: str
    hospital_id: int
    anomaly_score: float
    severity: str
    shap_values: dict             # {feature_name: shap_value}
    top_factors: List[FactorExplanation]
    text_explanation: str          # Arabic plain-language explanation

@dataclass
class FactorExplanation:
    feature: str
    shap_value: float
    direction: str                # "increases_anomaly" | "decreases_anomaly"
    magnitude: str                # "high" | "medium" | "low"
    arabic_label: str             # human-readable Arabic name

@dataclass
class GeoAggregationResult:
    governorates: List[GovernorateAgg]

@dataclass
class GovernorateAgg:
    governorate: str
    hospital_count: int
    avg_anomaly_score: float
    max_anomaly_score: float
    outlier_count: int
    avg_indicator_values: dict    # {indicator: avg_value}

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

@dataclass
class KPISummary:
    total_anomalies: int
    critical_count: int
    warning_count: int
    affected_governorates: int
    top_contributing_factor: str
    month_status: str             # "normal" | "attention_needed" | "critical"
```

### 3.4 Anomaly Detection (`anomaly.py`)

**Methods:**

1. **Isolation Forest** (existing, enhanced)
   - Uses `sklearn.ensemble.IsolationForest`
   - Features: 10 key indicators (same as existing ML module)
   - `contamination` from config (default 0.05)
   - Returns anomaly score via `decision_function` → normalized to 0-1

2. **Local Outlier Factor (LOF)**
   - Uses `sklearn.neighbors.LocalOutlierFactor`
   - `n_neighbors` from config (default 5, min 3)
   - `novelty=False` (batch detection)
   - Returns negative outlier factor → normalized to 0-1

3. **Mahalanobis Distance**
   - Uses `scipy.spatial.distance.mahalanobis`
   - Computes distance of each hospital from the centroid of all hospitals in indicator space
   - Handles covariance matrix singularity via pseudoinverse when features > samples
   - Returns distance → normalized to 0-1 via min-max scaling

4. **Ensemble Score**
   - Weighted average: `0.35 * IF + 0.30 * LOF + 0.20 * Mahal + 0.15 * Residual`
   - Weights stored in AppConfig, adjustable
   - Severity: green (score < 0.3), yellow (0.3-0.6), red (> 0.6)

**Feature preparation:**
- Numeric indicators: StandardScaler normalization
- Categorical (governorate, hospital_type): One-Hot Encoding appended
- Missing values: Median imputation per feature

### 3.5 Clustering (`clustering.py`)

**Methods (auto-selected):**

1. **DBSCAN** (primary)
   - `eps` from config (default 1.5, tuned for standardized features)
   - `min_samples` from config (default 3)
   - Advantage: discovers noise points (potential outliers) automatically
   - Noise points (cluster_id=-1) flagged for investigation

2. **Hierarchical Clustering** (fallback if DBSCAN produces <2 clusters)
   - `scipy.cluster.hierarchy` with Ward linkage
   - Cut tree at optimal level via silhouette score

**Feature preparation:** Same as anomaly detection (StandardScaler + One-Hot).

**Dimensionality reduction for visualization:**
- PCA to 2 components for scatter plot coordinates
- Labels: PC1 (X axis), PC2 (Y axis), with explained variance % shown

### 3.6 Correlations (`correlations.py`)

**Correlation Matrix:**
- Pearson correlation for linear relationships
- Spearman correlation for monotonic relationships
- P-value computed for each pair
- Strong correlations: |r| > 0.7 with p < 0.05

**Feature Importance:**
- For each of the 10 key indicators, train `RandomForestRegressor(n_estimators=100)`
- Target: the indicator value
- Features: all other indicators + governorate (OHE) + hospital_type (OHE)
- Report top-5 features by Gini importance
- Use `cross_val_score` with 3-fold CV to validate model quality (skip if R² < 0.3)

### 3.7 Residual Analysis (`residual.py`)

**Model:**
```python
import statsmodels.api as sm
from statsmodels.formula.api import ols

model = ols('indicator_value ~ C(governorate) + C(hospital_type)', data=df).fit()
```

**Per-indicator analysis:**
- Run separate OLS for each of the 10 key indicators
- Compute residuals: `actual - predicted`
- Normalize residuals to z-scores
- Flag |residual_z| > 2.0 as anomaly (anomaly that persists after accounting for location + type)

**Interpretation:**
- Positive residual: hospital performs worse than expected for its location/type
- Negative residual: hospital performs better than expected
- This is the "true anomaly" — not confounded by geographic or structural factors

### 3.8 Stratified Analysis (`stratified.py`)

**Peer groups:**
- Group hospitals by `(governorate, hospital_type)`
- If a group has <3 hospitals, fall back to `(governorate,)` or `(hospital_type,)`
- If still <3, use all hospitals as the peer group

**Per-hospital comparison:**
- For each indicator, compute: hospital value vs peer group mean/std
- Rank hospital within its peer group
- Label: "significantly above" (>1.5σ), "above" (>0.5σ), "average" (-0.5σ to 0.5σ), "below" (<-0.5σ), "significantly below" (<-1.5σ)

### 3.9 SHAP Explainability (`explainability.py`)

**For each hospital flagged as anomaly (score > warning threshold):**

1. Train Isolation Forest on all hospital data for the month
2. Use `shap.TreeExplainer` on the fitted model
3. Compute SHAP values for the specific hospital
4. Rank features by |SHAP value|
5. Take top-3 contributing features

**Text generation:**
- Template-based Arabic text:
  ```
  "هذا المستشفى يظهر كشاذ بسبب: {factor1} ({direction1})، {factor2} ({direction2})، و{factor3} ({direction3})."
  ```
- Direction: "ارتفاع غير متوقع في" (unexpected increase) or "انخفاض غير متوقع في" (unexpected decrease)
- Feature names mapped from codes to Arabic via `INDICATOR_CODE_TO_NAME`

### 3.10 Geo Aggregation (`geo.py`)

- Group anomaly results by governorate
- Compute per-governorate: avg anomaly score, max score, outlier count, hospital count
- Compute per-governorate average of key indicators
- Return structured for Plotly choropleth (governorate name → score)

### 3.11 Configuration

New `AppConfig` entries (category `smart_analytics`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `smart_enabled` | bool | true | Master toggle |
| `smart_contamination` | float | 0.05 | Isolation Forest contamination |
| `smart_lof_neighbors` | int | 5 | LOF neighbor count |
| `smart_dbscan_eps` | float | 1.5 | DBSCAN epsilon |
| `smart_dbscan_min_samples` | int | 3 | DBSCAN min samples |
| `smart_threshold_green` | float | 0.3 | Below = normal |
| `smart_threshold_yellow` | float | 0.6 | Below = warning |
| `smart_shap_enabled` | bool | true | Enable SHAP explanations |
| `smart_ensemble_if_weight` | float | 0.35 | Isolation Forest ensemble weight |
| `smart_ensemble_lof_weight` | float | 0.30 | LOF ensemble weight |
| `smart_ensemble_mahal_weight` | float | 0.20 | Mahalanobis ensemble weight |
| `smart_ensemble_residual_weight` | float | 0.15 | Residual ensemble weight |

---

## 4. API Layer — `app/api/smart_analytics.py`

**Router prefix:** `/smart`

| Endpoint | Method | Description | Response Type |
|----------|--------|-------------|---------------|
| `/smart/overview/{month}` | GET | KPI summary for executive cards | `KPISummary` |
| `/smart/anomalies/{month}` | GET | All hospital anomaly scores + explanations | `List[SmartAnomalyResult]` + `List[AnomalyExplanation]` |
| `/smart/clusters/{month}` | GET | Clustering results + PCA coordinates | `SmartClusteringResult` |
| `/smart/correlations/{month}` | GET | Correlation matrix + feature importance | `SmartCorrelationResult` |
| `/smart/residuals/{month}` | GET | Residual analysis results | `List[ResidualResult]` |
| `/smart/stratified/{month}` | GET | Peer-group comparisons | `List[StratifiedComparison]` |
| `/smart/geo/{month}` | GET | Governorate aggregates for map | `GeoAggregationResult` |
| `/smart/trend/{hospital_id}` | GET | Hospital's anomaly trend across all months | `dict` |
| `/smart/drilldown/{hospital_id}/{month}` | GET | Full drill-down data for one hospital | `dict` |
| `/smart/run/{month}` | POST | Trigger analysis (background task) | `{"task_id": str}` |

**Response envelope:**
```json
{
  "month": "2026-06",
  "generated_at": "2026-07-21T10:30:00",
  "hospitals_count": 20,
  "data": { ... }
}
```

**Performance note:** All endpoints compute results on-demand from DB data. No caching needed for ~20 hospitals × 6 months. If computation exceeds 2 seconds, add in-memory caching via `app/cache.py`.

---

## 5. Frontend — New "Smart Analytics" Tab

### 5.1 Files

| File | Action | Purpose |
|------|--------|---------|
| `static/tabs/smart-analytics.html` | CREATE | Tab HTML template with Plotly chart containers |
| `static/js/smart-analytics.js` | CREATE | Tab initialization, API calls, Plotly chart rendering |
| `static/index.html` | MODIFY | Add "التحليل الذكي" tab button + tab-content div |
| `app/main.py` | MODIFY | Mount smart_analytics router |
| `app/main.py` | MODIFY | Seed `smart_analytics` AppConfig entries |
| `requirements.txt` | MODIFY | Add `shap` dependency |

### 5.2 Dashboard Layout

```
┌─────────────────────────────────────────────────────┐
│  ROW 1: KPI CARDS (4 cards)                         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐              │
│  │ حالات │ │محافظات│ │عامل  │ │حالة  │              │
│  │شاذة  │ │متأثرة│ │الشذوذ│ │الشهر │              │
│  └──────┘ └──────┘ └──────┘ └──────┘              │
├─────────────────────────────────────────────────────┤
│  ROW 2: GEO MAP (left 60%) + CLUSTER SCATTER (40%) │
│  ┌──────────────────────┐ ┌──────────────┐         │
│  │  Choropleth Mapbox   │ │ PCA Scatter  │         │
│  │  خريطة المحافظات    │ │ نقاط ملونة   │         │
│  │  hover: avg score    │ │ حسب العنقود  │         │
│  └──────────────────────┘ └──────────────┘         │
├─────────────────────────────────────────────────────┤
│  ROW 3: CORRELATION HEATMAP (50%) + RESIDUAL (50%)  │
│  ┌──────────────────┐ ┌──────────────────┐         │
│  │  مصفوفة الارتباط │ │  رسم البواقي     │         │
│  │  heatmap          │ │  residual scatter│         │
│  └──────────────────┘ └──────────────────┘         │
├─────────────────────────────────────────────────────┤
│  ROW 4: ANOMALY TABLE (60%) + FEATURE IMPORTANCE (40%)│
│  ┌──────────────────────┐ ┌──────────────┐         │
│  │  جدول الشذوذ         │ │ أهمية العوامل │         │
│  │  sortable, clickable │ │ bar chart     │         │
│  └──────────────────────┘ └──────────────┘         │
├─────────────────────────────────────────────────────┤
│  ROW 5: STRATIFIED COMPARISON (full width)          │
│  ┌─────────────────────────────────────────┐       │
│  │  مقارنة طبقية: المستشفى vs أقرانه       │       │
│  │  grouped bar chart                       │       │
│  └─────────────────────────────────────────┘       │
├─────────────────────────────────────────────────────┤
│  ROW 6: DRILL-DOWN PANEL (hidden until click)       │
│  ┌─────────────────────────────────────────┐       │
│  │  تفاصيل المستشفى: [اسم المستشفى]        │       │
│  │  SHAP Waterfall + Trend Line + Text      │       │
│  └─────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

### 5.3 Chart Specifications

#### Chart 1: Geographic Choropleth
- **Plotly type:** `choropleth_mapbox`
- **Data:** `/smart/geo/{month}` → governorates with avg anomaly score
- **Colors:** Green (#22c55e) → Yellow (#f59e0b) → Red (#ef4444) based on avg score
- **Hover:** Governorate name, hospital count, avg score, outlier count
- **Click:** Filter anomaly table to that governorate
- **Fallback:** If mapbox token unavailable, use `choropleth` with GeoJSON boundaries directly

#### Chart 2: Cluster Scatter (PCA)
- **Plotly type:** `scatter`
- **Data:** `/smart/clusters/{month}` → PCA coordinates + cluster assignments
- **X/Y:** PC1 (explains X% variance), PC2 (explains Y% variance)
- **Color:** Cluster ID (distinct palette), noise points in gray
- **Marker size:** Proportional to anomaly score (larger = more anomalous)
- **Hover:** Hospital name, cluster, anomaly score, governorate

#### Chart 3: Correlation Heatmap
- **Plotly type:** `heatmap`
- **Data:** `/smart/correlations/{month}` → correlation matrix
- **Color scale:** Diverging (blue negative → white zero → red positive)
- **Hover:** Indicator pair names + r value + p value
- **Annotations:** Only for |r| > 0.5

#### Chart 4: Residual Plot
- **Plotly type:** `scatter`
- **Data:** `/smart/residuals/{month}` → predicted vs residual per hospital
- **X axis:** Predicted value (from regression model)
- **Y axis:** Residual (actual - predicted)
- **Color:** Green (|residual_z| < 1), Yellow (1-2), Red (> 2)
- **Horizontal lines:** At y=0, y=±1σ, y=±2σ
- **Hover:** Hospital name, actual, predicted, residual, indicator
- **Dropdown:** Select which indicator to show

#### Chart 5: Anomaly Table
- **Type:** HTML table (sortable via JS)
- **Columns:** Hospital | Governorate | Type | Score | Severity | Top Factor | Action
- **Color coding:** Row background matches severity color
- **Click row:** Opens drill-down panel (Row 6)
- **Sort:** By score (default desc), name, governorate

#### Chart 6: Feature Importance Bar
- **Plotly type:** `bar` (horizontal)
- **Data:** `/smart/correlations/{month}` → feature importance
- **Y axis:** Feature names (Arabic)
- **X axis:** Importance value
- **Color:** Gradient from light to dark based on importance
- **Dropdown:** Select which target indicator to show

#### Chart 7: Stratified Comparison
- **Plotly type:** `bar` (grouped)
- **Data:** `/smart/stratified/{month}` → hospital vs peer group
- **Groups:** Each hospital
- **Bars per group:** Hospital value (colored) vs Peer mean (gray)
- **Error bars:** ±1σ of peer group
- **Dropdown:** Select which indicator to show

#### Chart 8: SHAP Waterfall (Drill-down)
- **Plotly type:** `waterfall`
- **Data:** `/smart/drilldown/{id}/{month}` → SHAP values
- **Features:** Top contributing features ranked by |SHAP|
- **Color:** Red for positive SHAP (increases anomaly), Blue for negative
- **Label:** Arabic feature names

#### Chart 9: Hospital Trend Line (Drill-down)
- **Plotly type:** `scatter` (line + markers)
- **Data:** `/smart/trend/{hospital_id}` → anomaly scores across months
- **X axis:** Months
- **Y axis:** Anomaly score
- **Shaded zones:** Green (normal), Yellow (warning), Red (critical)
- **Marker color:** Match severity at each point

### 5.4 Color Scheme

```javascript
const SMART_COLORS = {
  // Severity (consistent across ALL charts)
  normal: '#22c55e',
  warning: '#f59e0b',
  critical: '#ef4444',

  // Clusters
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],

  // Neutral
  noise: '#6b7280',
  predicted_line: '#94a3b8',
  peer_group: '#d1d5db',

  // SHAP
  shap_positive: '#ef4444',
  shap_negative: '#3b82f6',

  // Correlation
  corr_negative: '#3b82f6',
  corr_zero: '#ffffff',
  corr_positive: '#ef4444'
};
```

### 5.5 Auto-Generated Interpretations

Each chart includes a text interpretation below it, generated from data:

| Chart | Interpretation Template |
|-------|------------------------|
| KPI Cards | "{N} حالة شاذة هذا الشهر، في {M} محافظة. العامل الأبرز: {factor}" |
| Geo Map | "{N} محافظات تظهر انحرافات عن المعدل المتوقع" |
| Cluster Scatter | "تم تجميع المستشفيات إلى {K} مجموعات. {M} مستشفى خرج عن أي مجموعة (نقاط ضوضاء)" |
| Correlation Heatmap | "أقوى علاقة مكتشفة: {ind1} و{ind2} (r={value})" |
| Residual Plot | "{N} مستشفى يظهر انحرافاً حقيقياً بعد استبعاد تأثير الموقع والنوع" |
| Anomaly Table | "المستشفى الأكثر شذوذاً: {name} (درجة: {score})" |
| Feature Importance | "أهم عامل يؤثر على {indicator}: {feature}" |
| Stratified | "{N} مستشفى يختلف بشكل ملحوظ عن مجموعته النظيرة" |

---

## 6. Dependencies

New additions to `requirements.txt`:
```
shap>=0.42.0
plotly>=5.18.0
statsmodels>=0.14.0
```

Note: `scikit-learn`, `scipy`, `numpy`, `pandas` are already in requirements.txt. `statsmodels` is NOT currently listed and must be added.

---

## 7. Testing Strategy

### Unit Tests (`tests/test_smart_*.py`)

| Test File | Covers | Key Tests |
|-----------|--------|-----------|
| `test_smart_anomaly.py` | LOF, DBSCAN outlier, Mahalanobis, ensemble | Basic detection, disabled toggle, too few hospitals, score normalization, severity classification |
| `test_smart_clustering.py` | DBSCAN, hierarchical, PCA coordinates | Basic clustering, noise detection, too few hospitals, silhouette score |
| `test_smart_correlations.py` | Correlation matrix, feature importance | Strong correlation detection, RF importance, too few features |
| `test_smart_residuals.py` | OLS regression, residual scoring | Normal residuals, anomaly detection, confounding removal |
| `test_smart_stratified.py` | Peer group comparison | Group formation, fallback groups, ranking |
| `test_smart_explain.py` | SHAP values, text generation | Top factors, Arabic text, disabled toggle |
| `test_smart_schemas.py` | All dataclasses | Construction, defaults, serialization |

### Integration Tests

- `test_smart_pipeline.py`: Full `run_smart_analytics()` with synthetic data
- Verify all endpoints return valid JSON with correct structure

---

## 8. Limitations & Disclaimers

The following limitations must be clearly documented in the UI and API responses:

1. **Small sample size:** With ~20 hospitals, statistical power is limited. Results should be interpreted as indicative, not definitive.
2. **No time-series forecasting:** Linear trend lines are descriptive only, not predictive. Future months cannot be predicted reliably.
3. **Cluster instability:** With small N, cluster assignments may shift significantly with minor data changes. DBSCAN noise points are more reliable indicators than cluster boundaries.
4. **SHAP approximations:** TreeExplainer on Isolation Forest is approximate. SHAP values indicate direction and relative importance but should not be interpreted as precise causal contributions.
5. **Correlation ≠ causation:** Strong correlations between indicators may reflect confounding factors, not causal relationships.
6. **GeoJSON boundaries:** Gaza governorate boundaries are approximate. Results should not be used for precise sub-governorate analysis.

---

## 9. Future Extensibility

The architecture is designed for easy future extension:

- **12+ months data:** Add time-series forecasting module (`app/engine/smart/forecasting.py`) using Prophet or ARIMA
- **24+ months data:** Add seasonality detection
- **More hospitals:** Add DB persistence for smart analytics results
- **Real-time alerts:** Add webhook/push notification when anomaly score crosses critical threshold
- **Custom indicators:** Allow users to select which indicators to include in analysis via AppConfig
