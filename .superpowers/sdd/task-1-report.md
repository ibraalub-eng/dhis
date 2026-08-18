# Task 1 Report: Set Up Chart.js Dependencies

## Status: DONE_WITH_CONCERNS

## What I Found

**Chart.js is already available globally.** No changes were needed.

### Current State of Dependencies

In `static/index.html` (lines 7-8):
```html
<script src="/static/vendor/chart.umd.min.js"></script>
<script src="/static/vendor/plotly.min.js"></script>
```

Both libraries are loaded as local vendor files in the main HTML page, NOT as CDN links.

### Discrepancies with Task Brief

| Assumption in Task Brief | Actual Codebase |
|---|---|
| Plotly.js CDN in `root-cause.html` | Local vendor file in `index.html` line 8 |
| Chart.js CDN needs to be added | Already loaded in `index.html` line 7 |
| Replace `<script src="https://cdn.plot.ly/plotly-latest.min.js">` | Actual: `<script src="/static/vendor/plotly.min.js">` |
| Modify `static/tabs/root-cause.html` | `root-cause.html` is an HTML fragment with no script tags |

### Why Plotly.js Cannot Be Removed Yet

Plotly.js is used extensively across other features (43 `Plotly.*` calls in `static/js/`):
- `smart-analytics.js` — geo maps, scatter plots, correlation heatmaps, feature importance, SHAP waterfalls, trend lines, etc.
- `settings.js` — root cause timeline chart (the migration target)
- `validation.js` — validation charts

Removing the Plotly.js script tag would break all of these features. The root cause timeline is only one of many Plotly consumers.

## Conclusion

**Task 1 is already complete** — Chart.js v4.4.0 is loaded and available as `window.Chart`. No file changes or commits are needed.

The subsequent migration tasks (rewriting `drawRcTimelineChart` in `settings.js` to use Chart.js instead of Plotly.js) will be the actual work. Those tasks should target `static/js/settings.js` lines 137-190, not `root-cause.html`.

## Files Changed

None.

## Test Results

N/A — no code changes made.
