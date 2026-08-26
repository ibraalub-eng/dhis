# Analytics Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bugs/cleanup, add high-impact visualizations (SHAP waterfall, PCA biplot, Gaza SVG map, KPI drilldown), and add export/interactivity features.

**Architecture:** Frontend-only changes across 3 phases. No new backend endpoints needed — all visualizations consume existing API responses. Client-side CSV export, Plotly charts, inline SVG map.

**Tech Stack:** Vanilla JS, Plotly.js (already loaded), Chart.js (already loaded), inline SVG, CSS custom properties (dark theme tokens)

## Global Constraints

- Never commit `.superpowers/sdd/` files
- Dark theme: all new UI must use CSS custom properties (`var(--accent-*)`, `var(--bg-*)`, `var(--text-*)`, `var(--severity-*)`)
- Plotly configs: use `paper_bgcolor:'rgba(0,0,0,0)'` and `plot_bgcolor:'rgba(0,0,0,0)'` for theme compatibility
- i18n: all user-facing text must use `__()` function for Arabic/English support
- ES modules: new JS files use `type="module"`, existing IIFE files stay as-is
- Testing: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short` (72 tests)
- Auth: use `apiGet()` for API calls, not raw `fetch()`
- Do not modify backend Python files

---

## Phase 1: Bug Fixes & Cleanup

### Task 1: Fix settings.js bugs and dead code

**Files:**
- Modify: `static/js/settings.js:195-227` (delete first `changeSelfPassword`)
- Modify: `static/js/settings.js:1332` (delete `initDevHints()` call)
- Modify: `static/js/settings.js:1584` (delete `loadHospitalToggles`)
- Modify: `static/js/settings.js:1729` (delete `PARAM_TEMPLATES`)
- Modify: `static/js/settings.js:1744` (delete `PARAM_HINTS`)

**Interfaces:**
- Consumes: Nothing
- Produces: Cleaner settings.js with no ReferenceErrors on load

- [ ] **Step 1: Read the current state of all target areas**

Read `static/js/settings.js` lines 190-230, 1325-1340, 1580-1600, 1725-1750 to confirm exact locations.

- [ ] **Step 2: Delete first `changeSelfPassword` definition (lines 195-227)**

Remove the entire first `window.changeSelfPassword = async function() { ... }` block. Keep the second definition at ~line 1782 which has the "must be different from current" validation.

- [ ] **Step 3: Delete `initDevHints()` call**

Find and delete the line that calls `initDevHints()` near line 1332.

- [ ] **Step 4: Delete `loadHospitalToggles` function**

Find and delete the entire `loadHospitalToggles` function definition and its `window.` export near line 1584.

- [ ] **Step 5: Delete `PARAM_TEMPLATES` and `PARAM_HINTS` exports**

Find and delete both `window.PARAM_TEMPLATES` and `window.PARAM_HINTS` object definitions near lines 1729 and 1744.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 7: Commit**

```bash
git add static/js/settings.js
git commit -m "fix: remove dead code from settings.js — duplicate changeSelfPassword, undefined initDevHints, unused exports"
```

---

### Task 2: Fix outliers.js auth bypass

**Files:**
- Modify: `static/js/outliers.js:51-61` (replace raw `fetch()` with `apiGet()`)

**Interfaces:**
- Consumes: `apiGet()` from `api.js` (already available as window global)
- Produces: Statistical mode requests now include auth tokens

- [ ] **Step 1: Read the outliers.js statistical mode section**

Read `static/js/outliers.js` lines 45-70 to see the raw `fetch()` usage.

- [ ] **Step 2: Replace raw `fetch()` with `apiGet()`**

Replace the `fetch(url)` call with `apiGet(url)`. Note that `apiGet()` returns parsed JSON directly (not a Response object), so remove the `.json()` call if present.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 4: Commit**

```bash
git add static/js/outliers.js
git commit -m "fix: use apiGet() in outliers.js statistical mode for auth token injection"
```

---

### Task 3: Delete unused table-utils exports

**Files:**
- Modify: `static/js/table-utils.js:34` (delete `severityPill`)
- Modify: `static/js/table-utils.js:49` (delete `activePill`)

**Interfaces:**
- Consumes: Nothing
- Produces: Cleaner table-utils.js

- [ ] **Step 1: Read table-utils.js**

Read `static/js/table-utils.js` to confirm the exact function boundaries.

- [ ] **Step 2: Delete `severityPill` function and its export**

Remove the entire `severityPill` function definition and its `window.severityPill` export.

- [ ] **Step 3: Delete `activePill` function and its export**

Remove the entire `activePill` function definition and its `window.activePill` export.

- [ ] **Step 4: Verify no imports reference these functions**

Search the codebase for `severityPill` and `activePill` to confirm they are truly unused.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/table-utils.js
git commit -m "fix: remove unused severityPill and activePill exports from table-utils.js"
```

---

### Task 4: Unify apiSmartGet() auth pattern

**Files:**
- Modify: `static/js/smart/core.js:39-51` (replace manual auth with shared pattern)

**Interfaces:**
- Consumes: `apiGet()` from `api.js`
- Produces: `apiSmartGet()` uses consistent auth pattern

- [ ] **Step 1: Read smart/core.js apiSmartGet()**

Read `static/js/smart/core.js` lines 35-55 to see the manual `localStorage.getItem` auth pattern.

- [ ] **Step 2: Read api.js for the shared pattern**

Read `static/js/api.js` to see how `apiGet()` handles auth headers.

- [ ] **Step 3: Rewrite apiSmartGet() to use apiGet()**

Replace the manual auth header construction with a call to `apiGet()`. If `apiSmartGet()` adds extra logic (e.g., different base URL), preserve that but delegate auth to the shared helper.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/core.js
git commit -m "fix: unify apiSmartGet() auth pattern with shared apiGet() helper"
```

---

## Phase 2: New Visualizations

### Task 5: SHAP Waterfall Charts in outlier cards

**Files:**
- Modify: `static/js/outliers.js:22-37` (replace comma-text with Plotly waterfall)

**Interfaces:**
- Consumes: `data.anomalies[].contributing_features` — `{feature_name: float_value}` map from `/smart/anomalies/{month}`
- Produces: Plotly horizontal bar chart embedded in each anomaly card

- [ ] **Step 1: Read current outlier rendering**

Read `static/js/outliers.js` lines 1-40 to understand the current card rendering and how `contributing_features` is used.

- [ ] **Step 2: Read the data structure from the API**

Check `app/engine/smart/anomaly.py` to confirm the shape of `contributing_features` returned per anomaly.

- [ ] **Step 3: Create a `renderSHAPWaterfall(containerId, features)` helper function**

Add a new function in `outliers.js` that:
- Takes a container element ID and a `{feature: shap_value}` object
- Sorts features by absolute SHAP value (descending)
- Takes top 8 features
- Creates a Plotly horizontal bar chart with:
  - Y-axis: feature names (use `smartTranslateFeature()` from core.js for Arabic)
  - X-axis: SHAP values
  - Bar colors: `var(--accent-red)` for negative, `var(--accent-teal)` for positive
  - Layout: `paper_bgcolor:'rgba(0,0,0,0)'`, `plot_bgcolor:'rgba(0,0,0,0)'`, `font:{color:'var(--text-primary)'}`, `margin:{l:120,r:10,t:5,b:30}`, `height:200`, `width:350`
  - No legend, no modebar

```javascript
function renderSHAPWaterfall(containerId, features) {
  const entries = Object.entries(features)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8);
  if (!entries.length) return;
  const labels = entries.map(e => window.SMART_ARABIC?.[e[0]] || e[0]);
  const values = entries.map(e => e[1]);
  const colors = values.map(v => v >= 0 ? 'var(--accent-teal)' : 'var(--accent-red)');
  Plotly.newPlot(containerId, [{
    type: 'bar', orientation: 'h',
    y: labels, x: values,
    marker: { color: colors },
    text: values.map(v => v.toFixed(3)),
    textposition: 'outside', textfont: { size: 9 }
  }], {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim(), size: 10 },
    margin: { l: 120, r: 10, t: 5, b: 30 },
    height: 200, width: 350,
    xaxis: { title: 'SHAP value', gridcolor: 'rgba(128,128,128,0.2)' },
    yaxis: { autorange: 'reversed' }
  }, { displayModeBar: false, responsive: true });
}
```

- [ ] **Step 4: Replace comma-text rendering with chart container**

In the ML anomaly card rendering (around line 30-37), replace:
```javascript
'<span style="...">' + Object.entries(anomaly.contributing_features || {}).map(([f, v]) => f + ': ' + v.toFixed(3)).join(', ') + '</span>'
```
with:
```javascript
'<div id="shap-' + anomaly.hospital_id + '" style="width:100%;max-width:350px;"></div>'
```

- [ ] **Step 5: Call renderSHAPWaterfall after DOM insert**

After inserting the card HTML, call `renderSHAPWaterfall('shap-' + anomaly.hospital_id, anomaly.contributing_features)` for each anomaly.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 7: Commit**

```bash
git add static/js/outliers.js
git commit -m "feat(analytics): add SHAP waterfall charts to outlier anomaly cards"
```

---

### Task 6: PCA Biplot Visualization

**Files:**
- Modify: `static/js/validation.js:331-363` (replace text boxes with Plotly scatter)

**Interfaces:**
- Consumes: `/analysis/ml` response — `pca_coordinates` (array of `{hospital_id, hospital_name, pc1, pc2, cluster}`) and `pca_explained_variance` (array of floats)
- Produces: Interactive 2D scatter plot with cluster coloring and ellipses

- [ ] **Step 1: Read current ML cluster rendering**

Read `static/js/validation.js` lines 325-370 to understand the current `loadMLClusters()` function and how PCA data is used.

- [ ] **Step 2: Read the API response shape**

Check `app/engine/ml/clustering.py` to see what `pca_coordinates` and `pca_explained_variance` look like.

- [ ] **Step 3: Add `renderPCABiplot(containerId, pcaData, clusterData)` function**

Add a new function in `validation.js` that:
- Takes container ID, PCA coordinates array, and cluster assignments
- Creates a Plotly scatter plot:
  - X-axis: PC1 (with variance % in label)
  - Y-axis: PC2 (with variance % in label)
  - Points colored by cluster
  - Hover: hospital name, cluster, PC1, PC2
  - `paper_bgcolor:'rgba(0,0,0,0)'`, `plot_bgcolor:'rgba(0,0,0,0)'`
  - `font:{color:'var(--text-primary)'}`

```javascript
function renderPCABiplot(containerId, pcaCoordinates, explainedVariance, clusters) {
  if (!pcaCoordinates || !pcaCoordinates.length) return;
  const clusterColors = ['#4F8CFF', '#A78BFA', '#F472B6', '#2DD4BF', '#FB923C', '#06B6D4', '#84CC16'];
  const traces = [];
  const grouped = {};
  pcaCoordinates.forEach(p => {
    const c = p.cluster != null ? p.cluster : 0;
    if (!grouped[c]) grouped[c] = [];
    grouped[c].push(p);
  });
  Object.entries(grouped).forEach(([cluster, points]) => {
    traces.push({
      type: 'scatter', mode: 'markers',
      name: 'Cluster ' + cluster,
      x: points.map(p => p.pc1),
      y: points.map(p => p.pc2),
      text: points.map(p => p.hospital_name),
      marker: { color: clusterColors[cluster % clusterColors.length], size: 8, opacity: 0.8 },
      hovertemplate: '%{text}<br>PC1: %{x:.2f}<br>PC2: %{y:.2f}<extra>Cluster ' + cluster + '</extra>'
    });
  });
  const pc1Var = explainedVariance?.[0] ? (explainedVariance[0] * 100).toFixed(1) : '?';
  const pc2Var = explainedVariance?.[1] ? (explainedVariance[1] * 100).toFixed(1) : '?';
  Plotly.newPlot(containerId, traces, {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() },
    xaxis: { title: 'PC1 (' + pc1Var + '%)', gridcolor: 'rgba(128,128,128,0.2)' },
    yaxis: { title: 'PC2 (' + pc2Var + '%)', gridcolor: 'rgba(128,128,128,0.2)' },
    legend: { font: { size: 10 } },
    margin: { l: 50, r: 20, t: 10, b: 50 },
    height: 400, width: '100%'
  }, { responsive: true, displayModeBar: false });
}
```

- [ ] **Step 4: Replace horizontal bars with biplot container**

In `loadMLClusters()`, replace the text-based cluster rendering with:
```javascript
'<div id="pca-biplot" style="width:100%;height:400px;"></div>'
```
Then call `renderPCABiplot('pca-biplot', data.pca_coordinates, data.pca_explained_variance, data.clusters)`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/validation.js
git commit -m "feat(analytics): add interactive PCA biplot to ML clusters tab"
```

---

### Task 7: Gaza Governorate SVG Map

**Files:**
- Modify: `static/js/smart/geo-regional.js:18-28` (replace bar chart with SVG map)

**Interfaces:**
- Consumes: `/regional/overview/{month}` — per-governorate data with `anomaly_score`, `hospital_count`, `governorate_name`
- Produces: Inline SVG map with color-coded governorates, tooltip, click-to-drilldown

- [ ] **Step 1: Read current geo-regional rendering**

Read `static/js/smart/geo-regional.js` lines 1-60 to understand the current bar chart rendering and data structure.

- [ ] **Step 2: Read the API response**

Check `app/engine/smart/regional.py` to see the per-governorate data shape.

- [ ] **Step 3: Create the Gaza SVG map template**

Add a `renderGazaMap(containerId, governorateData)` function with an inline SVG of 5 governorates. Use simplified polygon paths for:
- North Gaza (top)
- Gaza City (upper middle)
- Deir al-Balah (center)
- Khan Younis (lower middle)
- Rafah (bottom)

```javascript
function renderGazaMap(containerId, govData) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const govColors = {};
  (govData || []).forEach(g => {
    const score = g.anomaly_score || 0;
    govColors[g.governorate_name] = score >= 0.6 ? '#F87171' : score >= 0.3 ? '#FB923C' : '#4ADE80';
  });
  container.innerHTML = `
    <svg viewBox="0 0 200 400" style="width:100%;max-width:200px;height:auto;">
      <path id="gov-north" d="M60,10 L140,10 L150,60 L50,60 Z" fill="${govColors['North Gaza'] || '#5C6370'}" stroke="var(--border-default)" stroke-width="1.5" style="cursor:pointer"/>
      <path id="gov-gaza" d="M50,65 L150,65 L155,140 L45,140 Z" fill="${govColors['Gaza'] || '#5C6370'}" stroke="var(--border-default)" stroke-width="1.5" style="cursor:pointer"/>
      <path id="gov-deir" d="M45,145 L155,145 L150,220 L50,220 Z" fill="${govColors['Deir al-Balah'] || '#5C6370'}" stroke="var(--border-default)" stroke-width="1.5" style="cursor:pointer"/>
      <path id="gov-khan" d="M50,225 L150,225 L145,310 L55,310 Z" fill="${govColors['Khan Younis'] || '#5C6370'}" stroke="var(--border-default)" stroke-width="1.5" style="cursor:pointer"/>
      <path id="gov-rafah" d="M55,315 L145,315 L140,390 L60,390 Z" fill="${govColors['Rafah'] || '#5C6370'}" stroke="var(--border-default)" stroke-width="1.5" style="cursor:pointer"/>
      <text x="100" y="40" text-anchor="middle" fill="var(--text-primary)" font-size="10">North Gaza</text>
      <text x="100" y="108" text-anchor="middle" fill="var(--text-primary)" font-size="10">Gaza</text>
      <text x="100" y="188" text-anchor="middle" fill="var(--text-primary)" font-size="10">Deir al-Balah</text>
      <text x="100" y="273" text-anchor="middle" fill="var(--text-primary)" font-size="10">Khan Younis</text>
      <text x="100" y="358" text-anchor="middle" fill="var(--text-primary)" font-size="10">Rafah</text>
    </svg>`;
  // Add hover tooltips and click handlers
  (govData || []).forEach(g => {
    const el = container.querySelector('[id="gov-' + g.governorate_name.toLowerCase().replace(/\s+/g, '-') + '"]');
    if (!el) return;
    el.addEventListener('mouseenter', function() {
      this.style.opacity = '0.8';
      this.style.filter = 'brightness(1.2)';
    });
    el.addEventListener('mouseleave', function() {
      this.style.opacity = '1';
      this.style.filter = '';
    });
  });
}
```

- [ ] **Step 4: Replace bar chart with SVG map in renderGeoMap()**

Replace the Plotly bar chart code in `renderGeoMap()` with a call to `renderGazaMap()`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/smart/geo-regional.js
git commit -m "feat(analytics): add interactive Gaza governorate SVG map"
```

---

### Task 8: Dashboard KPI Drilldown Modals

**Files:**
- Modify: `static/js/settings.js:859-882` (add click handler + modal rendering)

**Interfaces:**
- Consumes: `/analysis/quality-trend/{id}`, `/dashboard/kpi` endpoints
- Produces: Modal with trend chart + breakdown when KPI card is clicked

- [ ] **Step 1: Read current KPI card rendering**

Read `static/js/settings.js` lines 850-900 to understand the KPI card structure and existing click handlers.

- [ ] **Step 2: Read the smart-kpi-modal pattern**

Read `static/js/smart/decision-board.js` to see how the existing KPI modal works (reuse pattern).

- [ ] **Step 3: Add `window.openKPIDrilldown(metric)` function**

Add a new function that:
- Opens the existing generic modal (`detailModal`)
- Fetches trend data from `/analysis/quality-trend/{hospitalId}`
- Renders a Chart.js line chart for the trend
- Shows a breakdown table of component scores

```javascript
window.openKPIDrilldown = async function(metric) {
  const modal = document.getElementById('detailModal');
  const body = document.getElementById('detailModalBody');
  if (!modal || !body) return;
  body.innerHTML = '<div style="text-align:center;padding:2rem;">Loading...</div>';
  modal.style.display = 'flex';
  try {
    const kpiData = await apiGet('/dashboard/kpi');
    body.innerHTML = `
      <div style="padding:1rem;">
        <h3 style="color:var(--text-primary);margin:0 0 1rem;">${metric.toUpperCase()}</h3>
        <div id="kpi-trend-chart" style="width:100%;height:250px;"></div>
        <div id="kpi-breakdown" style="margin-top:1rem;"></div>
      </div>`;
    // Render trend chart if data available
    if (kpiData && kpiData.quality_trend) {
      const months = kpiData.quality_trend.map(p => p.month);
      const scores = kpiData.quality_trend.map(p => p.score);
      Plotly.newPlot('kpi-trend-chart', [{
        type: 'scatter', mode: 'lines+markers',
        x: months, y: scores,
        line: { color: 'var(--accent-teal)', width: 2.5 },
        marker: { size: 6 }
      }], {
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: 'var(--text-primary)' },
        xaxis: { gridcolor: 'rgba(128,128,128,0.2)' },
        yaxis: { title: 'Score', gridcolor: 'rgba(128,128,128,0.2)' },
        margin: { l: 40, r: 20, t: 10, b: 40 }, height: 250
      }, { responsive: true, displayModeBar: false });
    }
  } catch (e) {
    body.innerHTML = '<div style="padding:2rem;color:var(--accent-red);">Failed to load KPI data</div>';
  }
};
```

- [ ] **Step 4: Add onclick to KPI cards**

In the KPI card HTML generation, add `onclick="window.openKPIDrilldown('quality_score')"` (or the relevant metric name) to each card's div.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/settings.js
git commit -m "feat(analytics): add KPI drilldown modals to dashboard cards"
```

---

## Phase 3: Export & Interactivity

### Task 9: CSV Export for Outlier and Rule-Failure Tabs

**Files:**
- Modify: `static/js/outliers.js` (add export buttons + CSV generation)

**Interfaces:**
- Consumes: Already-loaded outlier and rule-failure data
- Produces: CSV file download on button click

- [ ] **Step 1: Read current outlier/rule-failure tab structure**

Read `static/js/outliers.js` to understand how data is loaded and stored.

- [ ] **Step 2: Add `downloadCSV(filename, headers, rows)` utility function**

Add a reusable CSV export helper:

```javascript
function downloadCSV(filename, headers, rows) {
  const csvContent = [headers.join(','), ...rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(','))].join('\n');
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 3: Add outlier export button and handler**

Add an "Export CSV" button to the outlier tab header. On click, generate CSV from the loaded outlier data:

```javascript
function exportOutliersCSV() {
  if (!window._lastOutlierData) return;
  const headers = ['Hospital', 'Month', 'Indicator', 'Z-Score', 'Severity', 'Features'];
  const rows = window._lastOutlierData.map(o => [
    o.hospital_name, o.month, o.indicator, o.z_score?.toFixed(3),
    o.severity, Object.entries(o.contributing_features || {}).map(([f,v]) => f + ':' + v.toFixed(2)).join('; ')
  ]);
  downloadCSV('outliers_' + new Date().toISOString().slice(0,10) + '.csv', headers, rows);
}
```

- [ ] **Step 4: Add rule-failure export button and handler**

Same pattern for rule failures:

```javascript
function exportRuleFailuresCSV() {
  if (!window._lastRuleFailureData) return;
  const headers = ['Hospital', 'Rule Code', 'Description', 'Severity', 'Indicator', 'Failed Months'];
  const rows = window._lastRuleFailureData.map(r => [
    r.hospital_name, r.rule_code, r.rule_description, r.severity,
    r.indicator_code, r.failed_months?.join('; ')
  ]);
  downloadCSV('rule_failures_' + new Date().toISOString().slice(0,10) + '.csv', headers, rows);
}
```

- [ ] **Step 5: Store loaded data on window for export access**

Ensure the loaded outlier and rule-failure data is stored on `window._lastOutlierData` and `window._lastRuleFailureData` after loading.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 7: Commit**

```bash
git add static/js/outliers.js
git commit -m "feat(export): add CSV export for outlier and rule-failure tabs"
```

---

### Task 10: Comparison Tab Column Sort

**Files:**
- Modify: `static/js/validation.js:282-304` (add click-to-sort on comparison table headers)

**Interfaces:**
- Consumes: Already-loaded comparison data
- Produces: Sortable table columns with ascending/descending toggle

- [ ] **Step 1: Read current comparison table rendering**

Read `static/js/validation.js` lines 275-310 to see the comparison table HTML generation.

- [ ] **Step 2: Add sort state and click handler**

Add a sort state object and click handlers to the comparison table `<th>` elements:

```javascript
let _compSortCol = null, _compSortAsc = true;
function sortComparisonTable(col) {
  if (_compSortCol === col) _compSortAsc = !_compSortAsc;
  else { _compSortCol = col; _compSortAsc = true; }
  // Re-render table with sorted data
  loadComparison(); // or re-render from cached data
}
```

- [ ] **Step 3: Make `<th>` elements clickable**

Add `style="cursor:pointer"` and `onclick="sortComparisonTable('column_name')"` to each comparison table header.

- [ ] **Step 4: Sort data before rendering**

In the comparison rendering function, sort the data array by the selected column before generating table rows.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/validation.js
git commit -m "feat(interactivity): add column sorting to comparison table"
```

---

### Task 11: Dashboard Month-Range Filter

**Files:**
- Modify: `static/js/settings.js` (add month-range filtering logic)
- Modify: `static/tabs/dashboard.html` (add filter dropdowns)

**Interfaces:**
- Consumes: Already-loaded quality trend data
- Produces: Filtered trend chart and KPI cards based on selected month range

- [ ] **Step 1: Read current dashboard rendering**

Read `static/js/settings.js` lines 850-900 to understand the KPI card and trend chart rendering.

- [ ] **Step 2: Read dashboard.html**

Read `static/tabs/dashboard.html` to see the current filter structure.

- [ ] **Step 3: Add month-range filter dropdowns to dashboard.html**

Add two `<select>` elements above the KPI cards:

```html
<div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:1rem;">
  <label style="color:var(--text-secondary);font-size:0.8rem;">From:</label>
  <select id="kpi-range-from" onchange="window._filterKPIRange()" style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.3rem;"></select>
  <label style="color:var(--text-secondary);font-size:0.8rem;">To:</label>
  <select id="kpi-range-to" onchange="window._filterKPIRange()" style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.3rem;"></select>
</div>
```

- [ ] **Step 4: Populate dropdowns and add filter logic**

In `settings.js`, after loading quality trend data, populate the dropdowns with available months and set default to last 6 months:

```javascript
window._filterKPIRange = function() {
  const from = document.getElementById('kpi-range-from')?.value;
  const to = document.getElementById('kpi-range-to')?.value;
  // Filter trend data to selected range and re-render chart + KPI cards
};
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/settings.js static/tabs/dashboard.html
git commit -m "feat(interactivity): add month-range filter to dashboard KPI cards"
```

---

### Task 12: Alert Filtering

**Files:**
- Modify: `static/js/alerts.js` (add filter logic)
- Modify: `static/tabs/alerts.html` (add filter controls)

**Interfaces:**
- Consumes: Already-loaded alert data
- Produces: Filtered alert list based on severity/hospital/month selection

- [ ] **Step 1: Read current alerts rendering**

Read `static/js/alerts.js` to understand the current data loading and rendering.

- [ ] **Step 2: Read alerts.html**

Read `static/tabs/alerts.html` to see the current HTML structure.

- [ ] **Step 3: Add filter bar HTML to alerts.html**

Add filter controls above the alert list:

```html
<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem;">
  <select id="alerts-severity-filter" onchange="window._filterAlerts()" style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.3rem;">
    <option value="">All Severities</option>
    <option value="CRITICAL">Critical</option>
    <option value="HIGH">High</option>
    <option value="MEDIUM">Medium</option>
    <option value="LOW">Low</option>
  </select>
  <select id="alerts-hospital-filter" onchange="window._filterAlerts()" style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.3rem;"></select>
</div>
```

- [ ] **Step 4: Add filter logic in alerts.js**

```javascript
window._filterAlerts = function() {
  const severity = document.getElementById('alerts-severity-filter')?.value;
  const hospital = document.getElementById('alerts-hospital-filter')?.value;
  // Filter loaded data and re-render
  loadAlerts(severity, hospital);
};
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add static/js/alerts.js static/tabs/alerts.html
git commit -m "feat(interactivity): add severity and hospital filtering to alerts tab"
```

---

## Execution Order

```
Phase 1 (cleanup): Task 1 → Task 2 → Task 3 → Task 4
Phase 2 (visualizations): Task 5 → Task 6 → Task 7 → Task 8
Phase 3 (interactivity): Task 9 → Task 10 → Task 11 → Task 12
```

Each task is independently testable. Phase 1 can ship alone. Phase 2 tasks are independent of each other. Phase 3 tasks are independent of each other.

## Verification After Each Task

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed (no new failures)

## Files Modified (Total)

| File | Tasks |
|---|---|
| `static/js/settings.js` | 1, 8, 11 |
| `static/js/outliers.js` | 2, 5, 9 |
| `static/js/table-utils.js` | 3 |
| `static/js/smart/core.js` | 4 |
| `static/js/validation.js` | 6, 10 |
| `static/js/smart/geo-regional.js` | 7 |
| `static/js/alerts.js` | 12 |
| `static/tabs/dashboard.html` | 11 |
| `static/tabs/alerts.html` | 12 |
