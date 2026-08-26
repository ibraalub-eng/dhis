# Analytics Improvements — Design Spec

**Date:** 2026-08-25
**Goal:** Fix bugs/cleanup, add high-impact visualizations (SHAP waterfall, PCA biplot, Gaza SVG map, KPI drilldown), and add export/interactivity features.
**Approach:** 3-phase incremental delivery, each phase independently shippable.

---

## Phase 1: Bug Fixes & Cleanup

### 1a. Remove duplicate `changeSelfPassword`

**File:** `static/js/settings.js`
**Problem:** `changeSelfPassword` defined at lines 195-227 and again at 1782-1824. Second silently overwrites first.
**Action:** Delete lines 195-227 (first definition). Keep second (has "must be different from current" check).

### 1b. Delete dead `initDevHints()` call

**File:** `static/js/settings.js:1332`
**Problem:** `initDevHints()` is called but never defined. Throws ReferenceError on every settings load.
**Action:** Delete the call. If developer hints feature is needed later, implement it separately.

### 1c. Fix `outliers.js` raw `fetch()` bypass

**File:** `static/js/outliers.js:51-61`
**Problem:** Statistical mode uses raw `fetch()` instead of `apiGet()`, bypassing auth token injection.
**Action:** Replace `fetch(url)` with `apiGet(url)` in the statistical mode handler.

### 1d. Delete unused exports

**Files:**
- `static/js/table-utils.js:34` — `severityPill()` exported, never imported
- `static/js/table-utils.js:49` — `activePill()` exported, never imported
- `static/js/settings.js:1729` — `PARAM_TEMPLATES` exported, never imported
- `static/js/settings.js:1744` — `PARAM_HINTS` exported, never imported
- `static/js/settings.js:1584` — `loadHospitalToggles()` exported, never called

**Action:** Delete all dead exports.

### 1e. Unify `apiSmartGet()` auth pattern

**File:** `static/js/smart/core.js:39-51`
**Problem:** `apiSmartGet()` reimplements auth header injection manually instead of reusing the shared pattern from `api.js`.
**Action:** Replace manual `localStorage.getItem` with the existing `apiGet()` helper from `api.js`, or consolidate the auth injection.

### 1f. Delete duplicate `changeSelfPassword` (already covered by 1a)

---

## Phase 2: New Visualizations

### 2a. SHAP Waterfall Charts

**Current state:** `outliers.js:22-37` renders `contributing_features` as a comma-joined text string, discarding structured `{feature: shap_value}` data.

**Design:**
- Replace text rendering with a Plotly horizontal bar chart per anomaly
- Each bar = one feature, bar length = |SHAP value|, bar color = red (negative) or teal (positive)
- Show top 8 features max to avoid clutter
- Chart dimensions: ~300x200px, embedded in the anomaly card
- Use existing Plotly already loaded for smart analytics

**Data source:** `data.anomalies[].contributing_features` — already a `{feature_name: float_value}` map returned by `/smart/anomalies/{month}`.

**No backend changes needed.**

### 2b. PCA Biplot Visualization

**Current state:** `validation.js:331-363` loads PCA data from `/analysis/ml` but renders as simple horizontal bars showing explained variance.

**Design:**
- Replace horizontal bars with a Plotly scatter plot
- X-axis: PC1 (variance %), Y-axis: PC2 (variance %)
- Points = hospitals, colored by cluster assignment (from KMeans)
- Add cluster ellipses (1 std dev)
- Tooltip: hospital name, cluster, PC1, PC2 values
- Show total variance explained in axis labels
- Add loading arrows for top features (optional, complexity-dependent)

**Data source:** `/analysis/ml` endpoint returns `pca_coordinates` (hospital → PC1, PC2) and `pca_explained_variance` (per-component).

**No backend changes needed.**

### 2c. Gaza Governorate SVG Map

**Current state:** `smart/geo-regional.js:18-28` renders a bar chart in the "map" section. Comment says "Gaza governorates don't have ISO-3 codes."

**Design:**
- Create a simple inline SVG of 5 Gaza governorates (North Gaza, Gaza City, Deir al-Balah, Khan Younis, Rafah)
- Color-fill each governorate based on anomaly score (green → orange → red scale)
- Tooltip on hover: governorate name, anomaly score, hospital count, top indicator
- Click handler: opens regional detail modal (reuse existing `smart-drilldown-modal`)

**Data source:** `/regional/overview/{month}` already returns per-governorate data with `anomaly_score`, `hospital_count`.

**No backend changes needed.**

### 2d. Dashboard KPI Drilldown Modals

**Current state:** `settings.js:859-882` — clicking a KPI card does nothing.

**Design:**
- Add `onclick` handler to each KPI card
- On click, open a modal with:
  - Trend chart (quality score over time for the relevant metric)
  - Breakdown table (component contributions)
  - Compare button (links to comparison tab filtered to that metric — uses `window.location.hash` + `sessionStorage` to pass filter state)
- Reuse existing modal pattern from smart-analytics (`smart-kpi-modal`)
- Modal content fetched from existing API endpoints (no new backend)

**Data source:** Existing `/analysis/quality-trend/{id}` and `/dashboard/kpi` endpoints.

**No backend changes needed.**

---

## Phase 3: Export & Interactivity

### 3a. CSV Export for Outlier Tab

**File:** `static/js/outliers.js`
**Design:**
- Add "Export CSV" button to outlier tab header
- Client-side CSV generation from already-loaded outlier data
- Columns: Hospital, Month, Indicator, Z-Score, Severity, Contributing Features
- Trigger download via `Blob` + `URL.createObjectURL`

### 3b. CSV Export for Rule-Failure Tab

**File:** `static/js/outliers.js`
**Design:**
- Same pattern as 3a but for rule-failure data
- Columns: Hospital, Rule Code, Rule Description, Severity, Indicator, Failed Month

### 3c. Comparison Tab Column Sort

**File:** `static/js/validation.js:282-304`
**Design:**
- Add click handlers to comparison table `<th>` elements
- Sort by clicked column (ascending/descending toggle)
- Support: Hospital Name, Peer Mean, Hospital Value, Deviation %, Rank
- Use existing `sort` pattern from trend table

### 3d. Dashboard Month-Range Filter

**Files:** `static/js/settings.js`, `static/tabs/dashboard.html`
**Design:**
- Add a month-range selector (two `<select>` dropdowns: "From" and "To")
- Filter quality trend chart data to selected range
- KPI cards update to reflect selected range average
- Default: last 6 months

### 3e. Alert Filtering

**Files:** `static/js/alerts.js`, `static/tabs/alerts.html`
**Design:**
- Add filter bar with 3 dropdowns: Severity (All/Critical/High/Medium/Low), Hospital (All/list), Month (All/list)
- Client-side filtering on already-loaded data
- Update summary counts and bar charts when filters change

---

## Testing Strategy

- Phase 1: Run `python -m pytest tests/ -x -q` — should have no new failures
- Phase 2: Visual verification in browser (no new backend tests needed — frontend-only)
- Phase 3: Manual test of export (CSV downloads), sort (table reorders), filters (data subsets)

## Risk Assessment

- **Phase 1:** Very low risk — removing dead code, fixing existing bugs
- **Phase 2:** Medium risk — new Plotly charts depend on existing data structures; SVG map is new UI but data is existing
- **Phase 3:** Low risk — client-side filtering/export, no backend changes

## Dependencies

- Plotly.js (already loaded in smart-analytics)
- Chart.js (already loaded for classic tabs)
- No new npm packages or Python dependencies needed
