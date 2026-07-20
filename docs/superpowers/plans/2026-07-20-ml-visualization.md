# ML Visualization & Configuration UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) for syntax tracking.

**Goal:** Expose ML engine (clustering, anomaly detection, PCA) through Settings UI and existing tabs (Compare, Outliers, Root Cause).

**Architecture:** Flat `AppConfig` entries (`category='ml'`) are converted to nested ML config via `_build_ml_config()` in pipeline.py. A new `GET /analysis/ml?month=` API computes ML on-the-fly from all hospital data for a month. Three frontend tabs fetch this endpoint to render ML results alongside existing data.

**Tech Stack:** Python 3.14.6, FastAPI, SQLAlchemy, scikit-learn 1.9.0, vanilla JS

**Spec:** `docs/superpowers/specs/2026-07-20-ml-visualization-design.md`

## Global Constraints

- All new code follows existing patterns (no new DB tables, no auth changes)
- ML disabled by default (`ml_enabled` defaults to 0 in `AppConfig`)
- ML engine modules (`app/engine/ml/`) remain unchanged
- All existing tests must continue to pass
- Settings follow the existing pattern: `AppConfig` with `category='ml'`, sliders with `id="cfg_{key}"` and `id="cfgval_{key}"`

---
### Task 1: Backend — ML config conversion + `/analysis/ml` API

**Files:**
- Modify: `app/engine/pipeline.py` (add `_build_ml_config`, update ML block)
- Modify: `app/api/analysis.py` (add `GET /analysis/ml` endpoint)
- Test: `tests/test_ml_api.py`

**Interfaces:**
- Produces: `_build_ml_config(flat: dict) -> dict` converts AppConfig flat keys to nested ML config
- Produces: `GET /analysis/ml?month=YYYY-MM` returns `{"ml_clustering": {...}, "ml_anomalies": [...], "ml_pca": {...}}` or `{}` if disabled

- [ ] **Step 1: Add `_build_ml_config()` to pipeline.py**

Add after imports in `app/engine/pipeline.py`:

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

- [ ] **Step 2: Update pipeline.py ML block to use `_build_ml_config`**

Replace the existing ML block in `run_full_analysis`:

```python
    ml_config = get_config_dict(session, "ml")
    ml_config_nested = _build_ml_config(ml_config)
    ml_results = run_ml_analysis(all_hospital_data, ml_config_nested) if ml_config_nested.get("enabled", False) else {}
```

- [ ] **Step 3: Add `/analysis/ml` endpoint in `analysis.py`**

Add after the `/analysis/outliers` endpoint in `app/api/analysis.py`:

```python
@router.get("/ml")
def get_ml_analysis(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Run ML analysis (clustering, anomaly detection, PCA) for a given month."""
    from app.engine.pipeline import _build_ml_config
    from app.engine.ml import run_ml_analysis
    from app.config_utils import get_config_dict

    ml_config_flat = get_config_dict(db, "ml")
    ml_config = _build_ml_config(ml_config_flat)
    if not ml_config.get("enabled", False):
        return {}

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    if not hospitals:
        return {}

    enabled_months = get_enabled_months(db)
    if month not in enabled_months:
        return {}

    disabled_ids = set()
    from app.models import HospitalIndicatorConfig
    disabled_rows = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    for dr in disabled_rows:
        disabled_ids.add((dr.hospital_id, dr.indicator_id))

    value_rows = (
        db.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(IndicatorValue.month == month)
        .all()
    )
    all_hospital_data: dict[str, dict[str, float]] = {}
    for val, ind in value_rows:
        if (val.hospital_id, ind.id) in disabled_ids or val.value is None:
            continue
        h = next((h for h in hospitals if h.id == val.hospital_id), None)
        if not h:
            continue
        all_hospital_data.setdefault(h.name, {})[ind.code] = val.value

    if len(all_hospital_data) < 2:
        return {}

    result = run_ml_analysis(all_hospital_data, ml_config)
    return result
```

- [ ] **Step 4: Add test for the ML API endpoint**

Create `tests/test_ml_api.py`:

```python
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, SessionLocal, engine
from app.models import Base, Hospital, Indicator, IndicatorValue
from sqlalchemy.orm import Session

client = TestClient(app)


def test_ml_api_no_month():
    resp = client.get("/analysis/ml")
    assert resp.status_code == 422


def test_ml_api_no_data():
    resp = client.get("/analysis/ml?month=2099-12")
    assert resp.status_code == 200
    assert resp.json() == {}
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_ml_api.py tests/test_pipeline.py -v`

Expected: All tests pass (including existing pipeline tests).

- [ ] **Step 6: Commit**

```bash
git add app/engine/pipeline.py app/api/analysis.py tests/test_ml_api.py
git commit -m "feat: add ML config conversion and /analysis/ml API"
```

---
### Task 2: Frontend — ML Settings subtab

**Files:**
- Modify: `static/tabs/settings.html` (add ML button + settings section)
- Modify: `static/js/settings.js` (register 'ml' tab, add keys to save list, seed defaults)

**Interfaces:**
- Consumes: `GET /config/` returns `{"ml": {"ml_enabled": {"value": 0, "label": ...}, ...}}`
- Consumes: `PUT /config/` accepts `{"ml_enabled": 1, ...}`

- [ ] **Step 1: Add ML subtab button to `settings.html`**

Add after the Hospitals button (line 14):
```html
<button class="btn btn-sm btn-outline" onclick="showSettingsTab('ml')" id="stbtn-ml">ML Analysis</button>
```

- [ ] **Step 2: Add ML settings section before closing `</div>` of settings container**

Add after the hospitals settings section before the end of the settings tab:

```html
                    <!-- ML Analysis Settings -->
                    <div id="settings-ml" class="settings-section" style="display:none;">
                        <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;margin-bottom:0.8rem;">
                            <button class="btn" onclick="saveAllSettings()" style="background:#1a237e;color:white;">Save All Settings</button>
                            <button class="btn btn-outline" onclick="loadAllSettings()">Reload</button>
                            <span id="settingsStatus" style="font-size:0.8rem;"></span>
                        </div>
                        <h3 style="font-size:0.95rem;color:#333;margin-bottom:0.5rem;">ML Analysis Settings</h3>
                        <div style="background:#fef3e2;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>ML Engine:</strong> scikit-learn (IsolationForest, KMeans, PCA).<br>
                            <strong>Used in:</strong> Compare tab (clustering), Outliers tab (ML anomalies), Root Cause tab (PCA).<br>
                            <strong>Requires:</strong> At least 2 hospitals with data for the selected month.
                        </div>
                        <div style="display:flex;flex-direction:column;gap:0.8rem;max-width:700px;">
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Enable ML Analysis:</label>
                                    <input type="range" id="cfg_ml_enabled" min="0" max="1" step="1" style="flex:1;" oninput="updateCfgVal('ml_enabled')">
                                    <span id="cfgval_ml_enabled" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">0</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Master toggle. When disabled, no ML analysis runs and no ML results appear in tabs.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/pipeline.py</code> &rarr; <code>_build_ml_config()</code></span>
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Clustering Enabled:</label>
                                    <input type="range" id="cfg_ml_clustering_enabled" min="0" max="1" step="1" style="flex:1;" oninput="updateCfgVal('ml_clustering_enabled')">
                                    <span id="cfgval_ml_clustering_enabled" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">1</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Group similar hospitals by performance indicators using KMeans. Results shown in Compare tab.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/ml/clustering.py</code></span>
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Min Clusters (k):</label>
                                    <input type="range" id="cfg_ml_clustering_min_k" min="2" max="10" step="1" style="flex:1;" oninput="updateCfgVal('ml_clustering_min_k')">
                                    <span id="cfgval_ml_clustering_min_k" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">2</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Minimum number of hospital groups. Lower = broader groups. Higher = finer distinctions.
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Max Clusters (k):</label>
                                    <input type="range" id="cfg_ml_clustering_max_k" min="2" max="15" step="1" style="flex:1;" oninput="updateCfgVal('ml_clustering_max_k')">
                                    <span id="cfgval_ml_clustering_max_k" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">6</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Maximum number of hospital groups. The optimal k is auto-selected via silhouette score within this range.
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Anomaly Detection Enabled:</label>
                                    <input type="range" id="cfg_ml_anomaly_enabled" min="0" max="1" step="1" style="flex:1;" oninput="updateCfgVal('ml_anomaly_enabled')">
                                    <span id="cfgval_ml_anomaly_enabled" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">1</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Detect multivariate outliers using IsolationForest. Results shown in Outliers tab.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/ml/anomaly.py</code></span>
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">Contamination:</label>
                                    <input type="range" id="cfg_ml_anomaly_contamination" min="0.01" max="0.50" step="0.01" style="flex:1;" oninput="updateCfgVal('ml_anomaly_contamination')">
                                    <span id="cfgval_ml_anomaly_contamination" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">0.10</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Expected proportion of outliers in the data. 0.10 = expect 10% of hospitals to be anomalous.
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">PCA Enabled:</label>
                                    <input type="range" id="cfg_ml_pca_enabled" min="0" max="1" step="1" style="flex:1;" oninput="updateCfgVal('ml_pca_enabled')">
                                    <span id="cfgval_ml_pca_enabled" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">1</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Identify which indicators drive the most variance across hospitals. Results shown in Root Cause tab.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/ml/decomposition.py</code></span>
                                </div>
                            </div>
                            <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                                <div style="display:flex;align-items:center;gap:0.5rem;">
                                    <label style="width:200px;font-size:0.82rem;font-weight:600;">PCA Variance Threshold:</label>
                                    <input type="range" id="cfg_ml_pca_variance_threshold" min="0.50" max="1.00" step="0.01" style="flex:1;" oninput="updateCfgVal('ml_pca_variance_threshold')">
                                    <span id="cfgval_ml_pca_variance_threshold" style="width:45px;text-align:right;font-weight:700;font-size:0.85rem;">0.95</span>
                                </div>
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    Cumulative variance threshold for selecting PCA components. 0.95 = keep enough components to explain 95% of variance.
                                </div>
                            </div>
                        </div>
                    </div>
```

- [ ] **Step 3: Register 'ml' tab in `settings.js`**

In `showSettingsTab()` (line 66), add `'ml'` to the tab list:

```javascript
['quality', 'confidence', 'thresholds', 'rules', 'clinical', 'risk', 'trends', 'rates', 'ai', 'control', 'hospitals', 'ml'].forEach(s => {
```

In `saveAllSettings()` (line 752), add ML keys to the keys list:

Add inside the `.concat([...])` chain, after the rates keys:
```javascript
// ml
]).concat([
 'ml_enabled', 'ml_clustering_enabled', 'ml_clustering_min_k', 'ml_clustering_max_k',
 'ml_anomaly_enabled', 'ml_anomaly_contamination',
 'ml_pca_enabled', 'ml_pca_variance_threshold'
```

- [ ] **Step 4: Seed default ML config in seed script**

Run in Python to create ML config rows if they don't exist:

```python
from app.database import SessionLocal
from app.models import AppConfig
db = SessionLocal()
defaults = [
    ("ml_enabled", 0.0, "Enable ML Analysis"),
    ("ml_clustering_enabled", 1.0, "Enable Clustering"),
    ("ml_clustering_min_k", 2.0, "Min Clusters"),
    ("ml_clustering_max_k", 6.0, "Max Clusters"),
    ("ml_anomaly_enabled", 1.0, "Enable ML Anomaly Detection"),
    ("ml_anomaly_contamination", 0.1, "Contamination"),
    ("ml_pca_enabled", 1.0, "Enable PCA"),
    ("ml_pca_variance_threshold", 0.95, "PCA Variance Threshold"),
]
for key, val, label in defaults:
    exists = db.query(AppConfig).filter(AppConfig.key == key).first()
    if not exists:
        db.add(AppConfig(key=key, value=val, category="ml", label=label))
db.commit()
db.close()
print("ML config seeded")
```

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_ml_api.py tests/test_pipeline.py tests/test_api_config.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add static/tabs/settings.html static/js/settings.js
git commit -m "feat: add ML Analysis subtab to Settings page"
```

---
### Task 3: Frontend — Compare tab clustering visualization

**Files:**
- Modify: `static/tabs/compare.html` (add cluster card container)
- Modify: `static/js/validation.js` (add `loadMLClusters()` in `loadComparison()`)

**Interfaces:**
- Consumes: `GET /analysis/ml?month=X` → `{"ml_clustering": {"k": 3, "silhouette_score": 0.72, "clusters": [...], "features_used": [...]}}`

- [ ] **Step 1: Add cluster results container to `compare.html`**

Add before `id="compareContent"`:
```html
                    <div id="mlClusters" style="display:none;margin-bottom:1rem;"></div>
```

- [ ] **Step 2: Add `loadMLClusters()` to `validation.js`**

`loadComparison()` is in `static/js/validation.js:235`. After `loadComparison`, add:

```javascript
        export function loadMLClusters() {
            const month = document.getElementById('compareMonthSelect').value;
            const container = document.getElementById('mlClusters');
            if (!month) { container.style.display = 'none'; return; }
            apiGet('/analysis/ml?month=' + month).then(data => {
                if (!data || !data.ml_clustering || !data.ml_clustering.clusters) {
                    container.style.display = 'none';
                    return;
                }
                const c = data.ml_clustering;
                const colors = ['#2e7d32','#f57f17','#c62828','#1565c0','#6a1b9a','#00838f','#4e342e','#37474f','#558b2f','#e65100'];
                let html = '<div class="card" style="padding:0.8rem;"><h3 style="font-size:0.9rem;margin:0 0 0.4rem;">Performance Clusters <span style="font-size:0.75rem;color:#888;font-weight:400;">(silhouette: ' + c.silhouette_score.toFixed(2) + ', k=' + c.k + ')</span></h3>';
                const groups = {};
                c.clusters.forEach(cl => {
                    if (!groups[cl.cluster_id]) groups[cl.cluster_id] = [];
                    groups[cl.cluster_id].push(cl);
                });
                Object.keys(groups).sort().forEach(cid => {
                    const members = groups[cid];
                    const color = colors[parseInt(cid) % colors.length];
                    html += '<div style="display:inline-block;margin:0.3rem;padding:0.4rem 0.6rem;border-radius:4px;border-left:4px solid ' + color + ';background:#fafafa;vertical-align:top;min-width:160px;">';
                    html += '<div style="font-size:0.78rem;font-weight:600;color:' + color + ';">Cluster ' + cid + ' (' + members.length + ')</div>';
                    members.forEach(m => {
                        html += '<div style="font-size:0.72rem;color:#555;margin:0.1rem 0;">' + esc(m.hospital_name) + ' <span style="color:#999;">(' + m.distance_to_centroid.toFixed(2) + ')</span></div>';
                    });
                    html += '</div>';
                });
                html += '<div style="font-size:0.7rem;color:#999;margin-top:0.3rem;">Features: ' + (c.features_used || []).join(', ') + '</div>';
                html += '</div>';
                container.innerHTML = html;
                container.style.display = '';
            }).catch(() => { container.style.display = 'none'; });
        }
```

Also update the Compare button in compare.html to call both functions:
```html
<button class="btn btn-sm" onclick="loadComparison();loadMLClusters();" style="font-size:0.78rem;padding:0.3rem 0.8rem;">Compare</button>
```

- [ ] **Step 3: Export `loadMLClusters` in `app.js`**

In `static/js/app.js`, add to the import line:
```javascript
import { initTrends, initCompare, filterComparison, loadClinical, initClinical, renderClinical,
loadTrends, loadComparison, loadMLClusters } from './validation.js';
```
And add:
```javascript
window.loadMLClusters = loadMLClusters;
```

- [ ] **Step 4: Manually verify**

Restart server, open Compare tab, select month, click Compare. Verify cluster cards appear above the comparison table.

- [ ] **Step 5: Commit**

```bash
git add static/tabs/compare.html static/js/validation.js static/js/app.js
git commit -m "feat: show hospital clusters in Compare tab"
```

---
### Task 4: Frontend — Outliers tab ML anomaly toggle

**Files:**
- Modify: `static/js/outliers.js` (update `loadOutliers()` for ML mode)
- Modify: `static/tabs/outliers.html` (add mode toggle and ML columns)

**Interfaces:**
- Consumes: `GET /analysis/ml?month=X` → `{"ml_anomalies": [{"hospital_name": "...", "anomaly_score": 0.15, "is_outlier": true, "method": "isolation_forest", "contributing_features": {}}]}`

- [ ] **Step 1: Add mode toggle to `outliers.html`**

Add after the month filter in the filter row:
```html
                                <label style="font-size:0.75rem;color:#666;">Mode:</label>
                                <select id="outlierMode" onchange="loadOutliers()" style="font-size:0.78rem;padding:0.2rem 0.4rem;">
                                    <option value="statistical">Statistical (Z-Score)</option>
                                    <option value="ml">ML (IsolationForest)</option>
                                </select>
```

- [ ] **Step 2: Add ML anomaly columns to `outliers.html`**

Update the table header to add columns (show in both modes, populated only in ML mode):
```html
                                    <th class="sortable" data-col="hospital">Hospital</th>
                                    <th class="sortable" data-col="month">Month</th>
                                    <th class="sortable" data-col="rate_name">Indicator</th>
                                    <th class="sortable" data-col="value">Value / Score</th>
                                    <th class="sortable" data-col="benchmark">Status</th>
                                    <th class="sortable" data-col="z_score">Z-Score / ML Score</th>
```

- [ ] **Step 3: Update `loadOutliers()` in `outliers.js`**

Replace the existing `loadOutliers()` function:

```javascript
        export function loadOutliers() {
            const mode = document.getElementById('outlierMode').value;
            const month = document.getElementById('outlierMonthFilter').value;
            document.getElementById('outlierLoading').classList.remove('hidden');
            if (mode === 'ml') {
                if (!month) {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#888;">Select a month.</td></tr>';
                    document.getElementById('outlierCount').textContent = '';
                    return;
                }
                apiGet('/analysis/ml?month=' + month).then(data => {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    const anomalies = (data && data.ml_anomalies) || [];
                    document.getElementById('outlierCount').textContent = anomalies.length + ' hospital(s) analyzed';
                    const tbody = document.getElementById('outlierTbody');
                    if (!anomalies.length) {
                        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">No ML anomaly data.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = anomalies.map(a => {
                        const rowClass = a.is_outlier ? 'style="background:#fff3e0;"' : '';
                        return '<tr ' + rowClass + '>' +
                            '<td>' + esc(a.hospital_name) + '</td>' +
                            '<td>' + month + '</td>' +
                            '<td>Multi-variate</td>' +
                            '<td>' + (a.anomaly_score ? a.anomaly_score.toFixed(3) : '--') + '</td>' +
                            '<td>' + (a.is_outlier ? '<span class="badge badge-critical">Outlier</span>' : '<span class="badge badge-pass">Normal</span>') + '</td>' +
                            '<td style="font-size:0.7rem;color:#888;">' + esc(Object.keys(a.contributing_features || {}).join(', ')) + '</td>' +
                            '</tr>';
                    }).join('');
                }).catch(err => {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="color:red;">Error: ' + err.message + '</td></tr>';
                });
                return;
            }
            // statistical mode — existing code
            const hosp = document.getElementById('outlierHospitalFilter').value;
            const rate = document.getElementById('outlierRateFilter').value;
            document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#888;">Loading outliers...</td></tr>';
            let url = API() + '/analysis/outliers?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (month) url += 'month=' + encodeURIComponent(month) + '&';
            if (rate) url += 'rate_name=' + encodeURIComponent(rate) + '&';
            fetch(url).then(r => r.json()).then(data => {
                document.getElementById('outlierLoading').classList.add('hidden');
                updateOutlierUI(data, hosp, month, rate);
            }).catch(err => {
                document.getElementById('outlierLoading').classList.add('hidden');
                document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="color:red;">Error: ' + err.message + '</td></tr>';
            });
        }
```

- [ ] **Step 4: Manually verify**

Restart server, open Outliers tab, switch mode to "ML (IsolationForest)", verify ML anomalies appear. Switch back to Statistical — existing behavior preserved.

- [ ] **Step 5: Commit**

```bash
git add static/tabs/outliers.html static/js/outliers.js
git commit -m "feat: add ML anomaly mode to Outliers tab"
```

---
### Task 5: Frontend — Root Cause tab PCA feature importance

**Files:**
- Modify: `static/tabs/root-cause.html` (add PCA section)
- Modify: `static/js/settings.js` (update `loadRootCause` to fetch ML data)

**Interfaces:**
- Consumes: `GET /analysis/ml?month=X` → `{"ml_pca": {"n_components": 3, "explained_variance": [0.42, 0.28, 0.08], "cumulative_variance": 0.78, "top_features": {"C-Section Rate": 0.42, "MMR": 0.28}}}`

- [ ] **Step 1: Add PCA section to root-cause.html**

Add after the anomaly patterns section in the diagnostic grid:

```html
                    <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                        <h4 style="margin:0 0 0.3rem;font-size:0.82rem;color:#333;">PCA Feature Importance</h4>
                        <div id="pcaFeatures" style="font-size:0.78rem;color:#888;">Not available</div>
                    </div>
```

- [ ] **Step 2: Update `loadRootCause()` in `settings.js`**

After the existing root cause fetch (line 110-130 in settings.js), add:

```javascript
// Fetch ML data for PCA
const mlUrl = '/analysis/ml?month=' + mth;
apiGet(mlUrl).then(mlData => {
    if (mlData && mlData.ml_pca) {
        const pca = mlData.ml_pca;
        const features = pca.top_features || {};
        const entries = Object.entries(features).sort((a, b) => b[1] - a[1]);
        const maxVal = Math.max(...entries.map(e => e[1]), 0.01);
        let html = '<div style="margin-top:0.3rem;">';
        html += '<div style="font-size:0.72rem;color:#666;margin-bottom:0.3rem;">Cumulative variance explained: ' + (pca.cumulative_variance * 100).toFixed(0) + '%</div>';
        entries.forEach(([name, variance]) => {
            const pct = (variance / maxVal * 100).toFixed(0);
            html += '<div style="display:flex;align-items:center;gap:0.3rem;margin:0.15rem 0;">';
            html += '<span style="width:120px;font-size:0.72rem;">' + esc(name) + '</span>';
            html += '<div style="flex:1;height:14px;background:#eee;border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:#1a237e;border-radius:3px;"></div></div>';
            html += '<span style="width:40px;text-align:right;font-size:0.7rem;color:#555;">' + (variance * 100).toFixed(0) + '%</span>';
            html += '</div>';
        });
        html += '</div>';
        document.getElementById('pcaFeatures').innerHTML = html;
    }
}).catch(() => {});
```

- [ ] **Step 3: Manually verify**

Restart server, open Root Cause tab, select hospital/month with data. Verify PCA feature importance bars appear in the diagnostic grid.

- [ ] **Step 4: Commit**

```bash
git add static/tabs/root-cause.html static/js/settings.js
git commit -m "feat: add PCA feature importance to Root Cause tab"
```

---
### Task 6: Seed defaults + final verification

- [ ] **Step 1: Seed ML config defaults**

Run seed script from Task 2 Step 4.

- [ ] **Step 2: Run all tests**

Run: `python -m pytest -v`

Expected: All 337+ tests pass (no regressions).

- [ ] **Step 3: Verify final build**

Run: `python -c "from app.main import app; print('App loads OK')"`

Expected: No import errors.

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: seed ML config and final fixes"
```
