# Root Cause All-Months Trend Chart: Rewrite Plotly → Chart.js

**Date:** 2026-08-31
**Status:** Approved
**Author:** AI Assistant

---

## Overview

Rewrite the "Monthly Quality & Confidence Trend" chart inside `_renderRootCauseResult` in `static/js/settings.js` from Plotly.js to Chart.js. This removes the three Plotly references (`typeof Plotly`, `Plotly.newPlot`, `Plotly.purge`) reintroduced by commit `72dcbe2`, which broke two existing migration tests. This is a course-correction to bring the all-months trend chart back in line with the approved Chart.js migration standard (`docs/superpowers/specs/2026-08-17-root-cause-chart-migration-design.md`).

---

## Background & Root Cause

Two pre-existing test failures on `main` (unrelated to the peer-comparison branch):
- `tests/test_chart_migration.py::TestDrawRcTimelineChart::test_no_plotly_in_draw_function`
- `tests/test_chart_migration.py::TestTimelineAPI::test_timeline_no_plotly_references`

Both scan `static/js/settings.js` and assert `"Plotly.newPlot" not in content` and `"Plotly.react" not in content`. Commit `72dcbe2` (2026-08-31, "feat: add month-by-month trend chart for all-months root cause view") added a real `Plotly.newPlot(...)` call at line 664 of `settings.js` inside `_renderRootCauseResult`, plus `Plotly.purge` at line 667 and a `typeof Plotly === 'undefined'` guard at line 615. This violates the migration test contract (approved at `2026-08-17-root-cause-chart-migration-design.md`), which requires no Plotly references remain in `settings.js`.

**Scope:** Single file (`static/js/settings.js`), single chart. No HTML, backend, or data changes.

---

## Current State (Plotly Implementation)

Located in `_renderRootCauseResult(d, hid, mth)` (line ~569), the trend block spans lines ~605–669:

- Builds a `trendContainer` div with a header and `<div id="rcTrendPlot" style="width:100%;height:280px;"></div>`.
- Uses `setTimeout(..., 100)` to ensure the DOM is ready.
- Guards with `typeof Plotly === 'undefined'` and returns early if absent.
- Reads theme colors directly from CSS variables via `getComputedStyle(document.documentElement)` for green/blue/red/orange/text/border — duplicating what `CHART_COLORS`/`getCSSVar` already provide.
- Data arrays: `months` (`d._months`), `qsValues` (`d._monthQs`), `confValues` (`d._monthConf`), `ciValues` (`d._monthCi`).
- Renders with `Plotly.newPlot`:
  - **Quality Score:** scatter lines+markers, spline `shape`, blue line, per-point colors (≥80 green, ≥50 orange, else red), on left y-axis.
  - **Confidence:** scatter lines+markers, green dotted line, diamond markers, on left y-axis.
  - **Critical Issues:** bar chart, red `rgba(239,68,68,0.35)` where value>0 else green `rgba(74,222,128,0.2)`, on right y-axis (`y2`).
  - Layout: dual axes, `yaxis.range=[0,105]` left, `yaxis2` right ("Issues"), x-axis month labels with `tickangle:-30`, unified hover, transparent paper/plot bg, theme-colored font/grid.
- `else if (trendContainer)` branch uses `Plotly.purge('rcTrendPlot')` and hides the container.

---

## Design: Chart.js Rewrite (Approach A — in-place)

Replace the Plotly block with a Chart.js chart mirroring the existing `drawRcTimelineChart` pattern (lines 233–362) so the codebase stays consistent.

### Data & Datasets
- **Quality Score** — line, `yAxisID: 'y'` (left), spline via `tension: 0.3`, `borderColor: CHART_COLORS.primary` (teal), `backgroundColor` matching, per-point `pointBackgroundColor` computed from value (≥80 `CHART_COLORS.success`, ≥50 `CHART_COLORS.warning`, else `CHART_COLORS.accent`), `pointRadius: 5`, `pointHoverRadius: 7`, `fill: false`.
- **Confidence** — line, `yAxisID: 'y'` (left), `borderDash: [5,5]`, `borderColor` `CHART_COLORS.success`, `pointRadius: 3`, `fill: false`, `tension: 0.3`.
- **Critical Issues** — `type: 'bar'` mixed via `new Chart(ctx, { data: { datasets: [...] } })` where the bar dataset has `type: 'bar'`; `yAxisID: 'y1'` (right); `backgroundColor` per-point `rgba(239,68,68,0.35)` where value>0 else `rgba(74,222,128,0.2)`.

> **Note on mixed charts:** Chart.js supports mixed charts by setting `type: 'bar'` on an individual dataset within a `'line'` chart. To keep this simple and robust, the chart uses `type: 'line'` with the bar dataset declaring its own `type: 'bar'`.

### Singleton Instance
- Use `window._rcTrendChartInstance`, destroying any existing instance before re-creating (same pattern as `window._rcTimelineChartInstance`).
- After creation: `if (window.registerChart) window.registerChart(window._rcTrendChartInstance);` so the theme toggle keeps it consistent.

### Scales (dual axis)
```
scales: {
  x: { grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.neutral, font: { size: 10 }, maxRotation: -30 } },
  y: { position: 'left', min: 0, max: 105, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.neutral, font: { size: 10 } }, title: { display: true, text: _t('Score (0-100)'), color: CHART_COLORS.neutral } },
  y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { color: CHART_COLORS.neutral, font: { size: 10 } }, title: { display: true, text: _t('Issues'), color: CHART_COLORS.neutral } }
}
```

### Options
- `responsive: true`, `maintainAspectRatio: false`.
- `plugins.legend`: `position: 'top'`, labels `font.size 10`, `color CHART_COLORS.neutral`, `usePointStyle: true`.
- `plugins.tooltip`: `backgroundColor: getCSSVar('--bg-elevated') || '#1e293b'`, theme-neutralization consistent with `drawRcTimelineChart`.
- `interaction: { intersect: false, mode: 'index' }`.

### No-Data / Empty Branch
Replace the `Plotly.purge` branch: if `trendContainer` exists and no plot should render, destroy any `_rcTrendChartInstance` and set `trendContainer.style.display = 'none'`.

### Removal of Plotly references
Remove all three Plotly references so `settings.js` contains no `Plotly` token (beyond any non-Plotly coincidence). Text assertions target `Plotly.newPlot` and `Plotly.react`.

---

## Out of Scope

- Removing `plotly.min.js` from `static/index.html` (it may still be referenced elsewhere; not needed for this chart but removing the script tag is a separate cleanup).
- Refactoring into a reusable extracted function (Approach B — rejected for smaller scope).
- Any backend/API/data changes.

---

## Testing (TDD)

Add a new test class `TestMonthlyTrendChart` to `tests/test_chart_migration.py`:

1. `test_monthly_trend_uses_chart_js` — `static/js/settings.js` contains `window._rcTrendChartInstance = new Chart(`.
2. `test_monthly_trend_uses_register_chart` — contains `registerChart(window._rcTrendChartInstance)`.
3. `test_monthly_trend_no_plotly` — `settings.js` contains neither `Plotly.newPlot` nor `Plotly.react`.
4. `test_monthly_trend_dual_axis` — contains `yAxisID` and a right-positioned second axis (`position: 'right'`).

Existing tests `test_no_plotly_in_draw_function` and `test_timeline_no_plotly_references` must pass unchanged.

---

## Success Criteria

1. `settings.js` contains no `Plotly.newPlot` / `Plotly.react` (and ideally no `Plotly` token at all).
2. Both previously-failing tests pass unchanged.
3. New TDD tests for the Chart.js pattern pass.
4. All-months trend chart preserves its behavior: dual axes, score/confidence lines, colored per-point markers, issue bars, empty-state hide.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Mixed line+bar dual-axis misconfiguration in Chart.js | Low | Bar dataset declares its own `type: 'bar'`; verify visually + tests assert `yAxisID`/`position: 'right'`. |
| Empty-data hide regression | Low | Preserve `display:none` branch without relying on Plotly. |
| Theme color mismatch after removing computed-style CSS reads | Low | Use `CHART_COLORS` + `getCSSVar`, consistent with `drawRcTimelineChart`. |
