# Task 5: SHAP Waterfall Charts in Outlier Cards

## What Was Implemented

Replaced the plain-text rendering of `contributing_features` in ML anomaly cards with Plotly horizontal bar charts showing SHAP values.

### Changes

**`static/js/outliers.js`:**
1. Added `renderSHAPWaterfall(containerId, features)` function that:
   - Takes a container element ID and a `{feature: shap_value}` object
   - Sorts features by absolute SHAP value (descending), takes top 8
   - Creates a Plotly horizontal bar chart with:
     - Y-axis: feature names (translated via `window.SMART_ARABIC` if available)
     - X-axis: SHAP values
     - Bar colors: `var(--accent-teal)` for positive, `var(--accent-red)` for negative
     - Layout: transparent backgrounds, dark-theme-compatible, margins `{l:120,r:10,t:5,b:30}`, height 200, width 350
     - No legend, no modebar
   - Handles empty/missing features gracefully (no chart rendered)
   - Checks `typeof Plotly === 'undefined'` before rendering (Plotly is globally available via `index.html`)

2. Modified the ML anomaly card rendering to:
   - Replace the comma-text `<td>` with a `<div id="shap-{hospital_id}">` container
   - After inserting card HTML, call `renderSHAPWaterfall()` for each anomaly with `contributing_features`

## Testing

- Ran `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
- **Result: 72 passed** (all expected tests pass)

## Files Changed

- `static/js/outliers.js` — added `renderSHAPWaterfall` function, replaced text rendering with Plotly chart containers

## Notes

- Plotly.js is globally loaded via `<script src="/static/vendor/plotly.min.js">` in `index.html`
- The function gracefully handles missing Plotly (no-op) and empty features (no chart)
- Each chart has a unique container ID (`shap-{hospital_id}`) to avoid collisions
