# ML Visualization & Configuration UI

**Date:** 2026-07-20
**Status:** Design (approved)

## 1. Objective

Expose the existing ML engine (KMeans clustering, IsolationForest anomaly detection, PCA decomposition) through the application UI — add configuration controls in Settings and surface results in existing tabs (Compare, Outliers, Root Cause).

## 2. Scope

- **New subtab:** "ML Analysis" in Settings page (configure clustering, anomaly, PCA parameters)
- **Compare tab:** Show hospital peer clusters (KMeans groups) above the comparison table
- **Outliers tab:** Add ML anomaly toggle alongside statistical (z-score) outliers
- **Root Cause tab:** Add PCA feature importance as a fifth diagnostic dimension
- **Backend:** Flat-to-nested config conversion in pipeline.py

## 3. Architecture

### 3.1 Config Storage

8 parameters stored in `AppConfig` table with `category='ml'` (Float column, same as all existing settings):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ml_enabled` | Float (0/1) | 0 | Master toggle for ML analysis |
| `ml_clustering_enabled` | Float (0/1) | 1 | Enable KMeans clustering |
| `ml_clustering_min_k` | Float (2-10) | 2 | Minimum cluster count |
| `ml_clustering_max_k` | Float (2-15) | 6 | Maximum cluster count |
| `ml_anomaly_enabled` | Float (0/1) | 1 | Enable IsolationForest anomaly detection |
| `ml_anomaly_contamination` | Float (0.01-0.50) | 0.10 | Expected proportion of outliers |
| `ml_pca_enabled` | Float (0/1) | 1 | Enable PCA decomposition |
| `ml_pca_variance_threshold` | Float (0.50-1.00) | 0.95 | Cumulative variance threshold |

### 3.2 Backend — Config Conversion

Add `_build_ml_config(flat: dict) -> dict` in `app/engine/pipeline.py`. Converts flat `AppConfig` rows (e.g. `ml_clustering_min_k=2.0`) to the nested dict expected by `run_ml_analysis()`:

```python
def _build_ml_config(flat: dict) -> dict:
    return {
        "enabled": bool(flat.get("ml_enabled", 0)),
        "clustering": {
            "enabled": bool(flat.get("ml_clustering_enabled", 1)),
            "min_k": int(flat.get("ml_clustering_min_k", 2)),
            "max_k": int(flat.get("ml_clustering_max_k", 6)),
        },
        "anomaly": {
            "enabled": bool(flat.get("ml_anomaly_enabled", 1)),
            "contamination": flat.get("ml_anomaly_contamination", 0.1),
        },
        "pca": {
            "enabled": bool(flat.get("ml_pca_enabled", 1)),
            "variance_threshold": flat.get("ml_pca_variance_threshold", 0.95),
        },
    }
```

Update `pipeline.py` to use this function.

### 3.3 Pipeline Integration

The pipeline already calls `run_ml_analysis()` and merges results into the response dict. No structural change — the ML data flows through existing endpoints that read the analysis result.

### 3.4 Frontend — ML Settings Subtab

Add a new button in `settings.html` tab bar:
```html
<button class="btn btn-sm btn-outline" onclick="showSettingsTab('ml')" id="stbtn-ml">ML Analysis</button>
```

Add a new `<div id="settings-ml" class="settings-section">` containing 8 slider/toggle controls with descriptions. Follows the same pattern as existing settings (IDs: `cfg_ml_enabled`, `cfgval_ml_enabled`, etc.).

In `settings.js`:
- Add `'ml'` to `showSettingsTab()` tab list
- Add ML keys to `saveAllSettings()` key list
- `loadAllSettings()` auto-picks up `cfg_ml_*` elements via the existing iteration

### 3.5 Frontend — Compare Tab (Clustering)

Load clusters from `/analysis/ml?month=X` alongside the comparison data:

- Fetch ML data for selected month via `apiGet('/analysis/ml?month=' + month)`
- Extract `ml_clustering` from response
- Render cluster cards above comparison table: cluster ID, color swatch, hospital names, distance to centroid
- Show silhouette score as quality indicator

### 3.6 Frontend — Outliers Tab (ML Anomalies)

Add a filter toggle row to choose between "Statistical" and "ML" anomaly views:

- **Statistical mode** (existing): Shows z-score based anomalies from `AnomalyResult` table via `/analysis/outliers`
- **ML mode** (new): Fetch `/analysis/ml?month=X`, render `ml_anomalies` in the same table format

Extend the table columns to show ML anomaly score and is_outlier flag when in ML mode. Hospitals flagged by both methods are highlighted as "double-confirmed".

### 3.7 Frontend — Root Cause Tab (PCA)

Add a "PCA Feature Importance" section to the root cause diagnostic grid:

- Fetch root cause analysis for selected hospital/month (existing)  
- Also fetch `/analysis/ml?month=X` for PCA data
- Render horizontal bar chart showing top features by explained variance ratio
- Show cumulative variance percentage

### 3.8 API — New `/analysis/ml` Endpoint

Add `GET /analysis/ml?month=` in `app/api/analysis.py`:

1. Loads all hospital indicator values for the given month (same data as compare endpoint)
2. Reads ML config from `AppConfig` where `category='ml'`
3. Calls `run_ml_analysis(all_hospital_data, ml_config)`
4. Returns `{ ml_clustering, ml_anomalies, ml_pca }`

This keeps ML computation independent of existing endpoints. Each tab fetches ML data when needed.

### 3.9 Frontend — Data Flow

Each tab makes an additional API call to `/analysis/ml?month=X` when the user selects a month:

- **Compare tab:** Loads comparison data (existing) + ML clusters (new). Renders cluster cards above the table.
- **Outliers tab:** Toggle switches between `/analysis/outliers` (z-score) and `/analysis/ml` (IsolationForest anomalies).
- **Root Cause tab:** Calls `/root-cause/{id}?month=X` (existing) + `/analysis/ml?month=X` (new). Adds PCA section to diagnostic grid.

## 4. Files Changed

| File | Change |
|------|--------|
| `app/engine/pipeline.py` | Add `_build_ml_config()`, update ML config section in `run_full_analysis` |
| `app/api/analysis.py` | Add `GET /analysis/ml?month=` endpoint that computes ML results |
| `static/tabs/settings.html` | Add ML subtab button + settings section (8 controls) |
| `static/js/settings.js` | Register 'ml' tab, add ML keys to save list |
| `static/tabs/compare.html` | Add cluster results section + fetch `/analysis/ml` |
| `static/tabs/outliers.html` | Add ML/statistical toggle, ML anomaly table columns |
| `static/js/outliers.js` | Add ML anomaly fetch + render logic |
| `static/tabs/root-cause.html` | Add PCA feature importance section |
| `static/js/settings.js` (loadRootCause) | Fetch `/analysis/ml` alongside root cause data, render PCA |

## 5. Non-Goals

- No new database tables or migrations
- No changes to ML engine modules themselves
- No authentication/authorization changes
- No modification of existing settings behavior
- Existing endpoints remain unchanged — ML is additive
