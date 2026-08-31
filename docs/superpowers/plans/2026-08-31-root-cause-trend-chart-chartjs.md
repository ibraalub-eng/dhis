# All-Months Trend Chart Rewrite (Plotly → Chart.js) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plotly-based "Monthly Quality & Confidence Trend" chart in `_renderRootCauseResult` (static/js/settings.js) with a Chart.js dual-axis chart, removing all Plotly references and restoring the two failing migration tests to green.

**Architecture:** In-place rewrite (Approach A, per spec). Mirror the existing `drawRcTimelineChart` Chart.js pattern — singleton instance `window._rcTrendChartInstance` with `.destroy()` before rebuild, `CHART_COLORS`/`getCSSVar` for theme colors, `registerChart()` for theme refresh, `responsive: true`/`maintainAspectRatio: false`, and a dual-axis `scales` config (`y` left = Score/Confidence, `y1` right = Critical Issues bars).

**Tech Stack:** JavaScript (vanilla, ESM-style module `static/js/settings.js`), Chart.js v4 (UMD build via `static/vendor/chart.umd.min.js`), pytest for structural JS assertions.

## Global Constraints

- `static/js/settings.js` MUST NOT contain the tokens `Plotly.newPlot`, `Plotly.react`, or the identifier `Plotly` after this work (tests assert on `Plotly.newPlot`/`Plotly.react`).
- Reuse `CHART_COLORS` (keys: `primary`, `secondary`, `accent`, `warning`, `success`, `neutral`, `background`, `grid`, `ciBand`) and `getCSSVar('--bg-elevated')` — do NOT read CSS vars manually via `getComputedStyle`.
- Chart container element remains `rcTrendPlot`; parent card id remains `rcTrendChart`. Data keys consumed are `d._months`, `d._monthQs`, `d._monthConf`, `d._monthCi` (do not change).
- Data-driven point/bar colors: Quality point ≥80 → `CHART_COLORS.success`; ≥50 → `CHART_COLORS.warning`; else `CHART_COLORS.accent`. Critical Issues bar >0 → `rgba(239,68,68,0.35)`; else `rgba(74,222,128,0.2)`.
- Dual axes preserved: left `y` (`min:0, max:105`, title `_t('Score (0-100)')`), right `y1` (`position:'right'`, title `_t('Issues')`, `grid.drawOnChartArea:false`).
- Tests run from the repo root with `python -m pytest`.
- Commit hook validates JS syntax (do not commit broken JS).

---

### Task 1: Write failing Chart.js tests + remove Plotly token

**Files:**
- Modify: `tests/test_chart_migration.py` (add class `TestMonthlyTrendChart`)
- Modify: `static/js/settings.js:610-669` (rewrite Plotly block to Chart.js)

**Interfaces:**
- Consumes: existing `_read(rel_path)` helper in `tests/test_chart_migration.py` (path relative to repo root, e.g. `"static/js/settings.js"`).
- Produces: a Chart.js chart stored in `window._rcTrendChartInstance` (singleton, registered via `window.registerChart` where available).

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/test_chart_migration.py` (after `TestTimelineAPIEdgeCases`, at end of file):

```python
class TestMonthlyTrendChart:
    """The all-months 'Monthly Quality & Confidence Trend' chart must use
    Chart.js (not Plotly) with a dual-axis setup."""

    def test_monthly_trend_uses_chart_js(self):
        content = _read("static/js/settings.js")
        assert "window._rcTrendChartInstance = new Chart(" in content

    def test_monthly_trend_uses_register_chart(self):
        content = _read("static/js/settings.js")
        assert "registerChart(window._rcTrendChartInstance)" in content

    def test_monthly_trend_no_plotly(self):
        content = _read("static/js/settings.js")
        assert "Plotly.newPlot" not in content
        assert "Plotly.react" not in content

    def test_monthly_trend_dual_axis(self):
        content = _read("static/js/settings.js")
        assert "yAxisID: 'y1'" in content
        assert "position: 'right'" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chart_migration.py::TestMonthlyTrendChart -q --tb=short`
Expected: FAIL — all four fail (no `window._rcTrendChartInstance`, no `yAxisID: 'y1'`), except `test_monthly_trend_no_plotly` which currently FAILS because `Plotly.newPlot` exists at line 664.

- [ ] **Step 3: Write minimal implementation (rewrite the Plotly block)**

Replace lines 610-669 of `static/js/settings.js` (the `trendContainer.innerHTML = ...` through the `} else if (trendContainer) { ... }` block, i.e. everything from the `trendContainer.style.display = 'block';` line through line 669) with:

```javascript
                trendContainer.style.display = 'block';
                trendContainer.innerHTML = '<div style="font-size:0.82rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">📈 ' + _t('Monthly Quality & Confidence Trend') + '</div><div id="rcTrendPlot" style="width:100%;height:280px;"></div>';
                // Use setTimeout to ensure DOM is ready
                setTimeout(() => {
                    const plotEl = document.getElementById('rcTrendPlot');
                    if (!plotEl) return;
                    const months = d._months;
                    const qsValues = d._monthQs;
                    const confValues = d._monthConf;
                    const ciValues = d._monthCi;
                    // Per-point quality colors
                    const qsPointColors = qsValues.map(v => v >= 80 ? CHART_COLORS.success : v >= 50 ? CHART_COLORS.warning : CHART_COLORS.accent);
                    const barColors = ciValues.map(v => v > 0 ? 'rgba(239,68,68,0.35)' : 'rgba(74,222,128,0.2)');
                    // Destroy existing chart if any
                    if (window._rcTrendChartInstance) {
                        window._rcTrendChartInstance.destroy();
                        window._rcTrendChartInstance = null;
                    }
                    const chartCtx = plotEl.getContext('2d');
                    window._rcTrendChartInstance = new Chart(chartCtx, {
                        type: 'line',
                        data: {
                            labels: months,
                            datasets: [
                                {
                                    label: _t('Quality Score'),
                                    data: qsValues,
                                    borderColor: CHART_COLORS.primary,
                                    backgroundColor: CHART_COLORS.primary,
                                    _colorRole: 'primary',
                                    pointBackgroundColor: qsPointColors,
                                    pointBorderColor: 'rgba(255,255,255,0.3)',
                                    borderWidth: 2.5,
                                    pointRadius: 5,
                                    pointHoverRadius: 7,
                                    tension: 0.3,
                                    fill: false,
                                    yAxisID: 'y',
                                },
                                {
                                    label: _t('Confidence'),
                                    data: confValues,
                                    borderColor: CHART_COLORS.success,
                                    backgroundColor: CHART_COLORS.success,
                                    _colorRole: 'success',
                                    borderDash: [5, 5],
                                    borderWidth: 2,
                                    pointRadius: 3,
                                    pointHoverRadius: 5,
                                    tension: 0.3,
                                    fill: false,
                                    yAxisID: 'y',
                                },
                                {
                                    type: 'bar',
                                    label: _t('Critical Issues'),
                                    data: ciValues,
                                    backgroundColor: barColors,
                                    borderWidth: 1,
                                    borderColor: 'rgba(0,0,0,0)',
                                    yAxisID: 'y1',
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    position: 'top',
                                    labels: {
                                        font: { size: 10 },
                                        color: CHART_COLORS.neutral,
                                        usePointStyle: true,
                                    }
                                },
                                tooltip: {
                                    backgroundColor: getCSSVar('--bg-elevated') || '#1e293b',
                                    titleFont: { size: 11 },
                                    bodyFont: { size: 11 },
                                    padding: 12,
                                    cornerRadius: 6,
                                }
                            },
                            scales: {
                                x: {
                                    grid: { color: CHART_COLORS.grid },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 }, maxRotation: -30 }
                                },
                                y: {
                                    position: 'left',
                                    min: 0,
                                    max: 105,
                                    grid: { color: CHART_COLORS.grid },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
                                    title: { display: true, text: _t('Score (0-100)'), color: CHART_COLORS.neutral }
                                },
                                y1: {
                                    position: 'right',
                                    beginAtZero: true,
                                    grid: { drawOnChartArea: false },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
                                    title: { display: true, text: _t('Issues'), color: CHART_COLORS.neutral }
                                }
                            },
                            interaction: {
                                intersect: false,
                                mode: 'index'
                            }
                        }
                    });
                    if (window.registerChart) window.registerChart(window._rcTrendChartInstance);
                }, 100);
            } else if (trendContainer) {
                if (window._rcTrendChartInstance) {
                    window._rcTrendChartInstance.destroy();
                    window._rcTrendChartInstance = null;
                }
                trendContainer.style.display = 'none';
            }
```

Important: preserve the surrounding context. The block starts at the `trendContainer.style.display = 'block';` line (610) and the `} else if (trendContainer) {` + closing `}` (666-669) must remain as the else-branch of the same `if (isAll && ...)`. Remove the `typeof Plotly === 'undefined'` guard (line 615) and replace `Plotly.purge(...)` (line 667) with the singleton `.destroy()` shown.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chart_migration.py::TestMonthlyTrendChart tests/test_chart_migration.py::TestDrawRcTimelineChart::test_no_plotly_in_draw_function tests/test_chart_migration.py::TestTimelineAPI::test_timeline_no_plotly_references -q --tb=short`
Expected: PASS — all six (4 new + 2 restored).

- [ ] **Step 5: Commit**

```bash
git add tests/test_chart_migration.py static/js/settings.js
git commit -m "feat: rewrite all-months trend chart from Plotly to Chart.js (dual-axis)"
```

---

### Task 2: Full regression verification

**Files:**
- No code changes. Verification only.

**Interfaces:**
- Consumes: state produced by Task 1.
- Produces: verified, mergeable result.

- [ ] **Step 1: Run the chart-migration test module fully**

Run: `python -m pytest tests/test_chart_migration.py -q --tb=short`
Expected: All tests in the module PASS (this module previously had the 2 failing tests; there should be 0 failures).

- [ ] **Step 2: Run the canonical regression trio**

Run: `python -m pytest tests/test_chart_migration.py tests/test_butterfly_report.py tests/test_auth.py -q --tb=short`
Expected: PASS for these files (no new failures introduced). The trend-chart rewrite touches only `static/js/settings.js` and `tests/test_chart_migration.py`; other suites should be unaffected.

- [ ] **Step 3: Confirm no Plotly token remains**

Run: `git grep -n "Plotly" -- static/js/settings.js`
Expected: no output (empty), confirming zero `Plotly` references remain in `settings.js`.

---

## Self-Review

**1. Spec coverage:**
- §Data & Datasets (Quality/Confidence/Critical Issues) → Task 1 Step 3 datasets. ✓
- §Singleton Instance (`window._rcTrendChartInstance` + destroy + registerChart) → Task 1 Step 3. ✓
- §Scales (dual axis y/y1) → Task 1 Step 3 scales block. ✓
- §Options (responsive, legend, tooltip, interaction) → Task 1 Step 3. ✓
- §No-Data/Empty branch (destroy + hide, no Plotly) → Task 1 Step 3 else-branch. ✓
- §Removal of Plotly references → Task 1 Step 3 (removes `typeof Plotly`, `Plotly.newPlot`, `Plotly.purge`). ✓
- §Testing (4 tests `TestMonthlyTrendChart` + existing 2 must pass) → Task 1 Steps 1/4, Task 2. ✓
- Success criterion "both previously-failing tests pass unchanged" → Task 1 Step 4 / Task 2 Step 1. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows exact code; exact paths and commands given. ✓

**3. Type consistency:** `_rcTrendChartInstance`, `yAxisID: 'y1'`, `scale y/y1`, `CHART_COLORS.success/.warning/.accent/.primary/.neutral/.grid` all consistently named between the test assertions (Task 1 Step 1) and the implementation (Task 1 Step 3). `_read` helper usage matches existing convention. ✓
