# Root Cause Chart Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the root cause analysis timeline chart from Plotly.js to Chart.js with improved colors and design.

**Architecture:** Replace Plotly.js library with Chart.js for the timeline chart, implementing custom CI band plugin and enhanced tooltips while maintaining all existing functionality.

**Tech Stack:** JavaScript, Chart.js v4.x, HTML5 Canvas

## Global Constraints

- Chart.js v4.x or later
- No npm dependencies (CDN only)
- Maintain existing API endpoint structure
- Preserve all current chart functionality
- Responsive design for mobile and desktop
- Bilingual support (Arabic/English) maintained

---

## File Structure

### Files to Create
- `static/js/chart-utils.js` - Chart.js configuration and CI band plugin

### Files to Modify
- `static/js/settings.js` - Replace Plotly.js functions with Chart.js implementation
- `static/tabs/root-cause.html` - Update CDN links and chart container

### Files to Test
- `tests/test_root_cause_chart.py` - Unit tests for chart functionality (if applicable)

---

## Task 1: Set Up Chart.js Dependencies

**Files:**
- Modify: `static/tabs/root-cause.html`

**Interfaces:**
- Consumes: None
- Produces: Chart.js library available globally

- [ ] **Step 1: Locate current Plotly.js CDN link**

Open `static/tabs/root-cause.html` and find the Plotly.js CDN script tag. It should be in the head or before closing body tag.

- [ ] **Step 2: Replace Plotly.js with Chart.js CDN**

Replace the Plotly.js script tag with Chart.js CDN:

```html
<!-- Remove this line -->
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>

<!-- Add this line -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
```

- [ ] **Step 3: Verify Chart.js is loaded**

Add a temporary test in browser console:
```javascript
console.log('Chart.js version:', Chart.version);
```

Expected output: Chart.js version number (e.g., "4.4.0")

- [ ] **Step 4: Commit changes**

```bash
git add static/tabs/root-cause.html
git commit -m "chore: replace Plotly.js with Chart.js CDN"
```

---

## Task 2: Create Chart Utilities Module

**Files:**
- Create: `static/js/chart-utils.js`

**Interfaces:**
- Consumes: None
- Produces: `CHART_COLORS` object, `ciBandPlugin` function

- [ ] **Step 1: Create chart-utils.js file**

Create new file `static/js/chart-utils.js` with color palette:

```javascript
// Chart color palette - unified design system
const CHART_COLORS = {
  primary: '#0d9488',      // Teal - hospital value line
  secondary: '#7c3aed',    // Purple - peer average line
  accent: '#c62828',       // Red - critical severity
  warning: '#e65100',      // Orange - high/medium severity
  success: '#2e7d32',      // Green - good status
  neutral: '#64748b',      // Gray - text and borders
  background: '#f8fafc',   // Light gray - chart background
  grid: '#e2e8f0',        // Light gray - grid lines
  ciBand: 'rgba(124,58,237,0.12)', // Purple with opacity - CI band
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.CHART_COLORS = CHART_COLORS;
}
```

- [ ] **Step 2: Add CI band plugin**

Add custom plugin for 95% confidence interval band:

```javascript
// Custom plugin for 95% confidence interval band
const ciBandPlugin = {
  id: 'ciBand',
  beforeDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    const ciData = chart.config.options.plugins.ciBand;
    
    if (!ciData || !ciData.upper || !ciData.lower) return;
    
    const { upper, lower } = ciData;
    const xScale = scales.x;
    const yScale = scales.y;
    
    ctx.save();
    ctx.fillStyle = CHART_COLORS.ciBand;
    ctx.beginPath();
    
    // Draw upper bound
    upper.forEach((value, index) => {
      const x = xScale.getPixelForValue(index);
      const y = yScale.getPixelForValue(value);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    // Draw lower bound in reverse
    lower.reverse().forEach((value, index) => {
      const x = xScale.getPixelForValue(lower.length - 1 - index);
      const y = yScale.getPixelForValue(value);
      ctx.lineTo(x, y);
    });
    
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.ciBandPlugin = ciBandPlugin;
}
```

- [ ] **Step 3: Add script tag to HTML**

Add the new script to `static/tabs/root-cause.html` before the Chart.js script:

```html
<script src="/static/js/chart-utils.js"></script>
```

- [ ] **Step 4: Commit changes**

```bash
git add static/js/chart-utils.js static/tabs/root-cause.html
git commit -m "feat: add chart utilities module with color palette and CI band plugin"
```

---

## Task 3: Update Timeline Chart Container

**Files:**
- Modify: `static/tabs/root-cause.html`

**Interfaces:**
- Consumes: None
- Produces: Updated chart container with proper styling

- [ ] **Step 1: Locate timeline chart container**

Find the timeline chart section in `static/tabs/root-cause.html`:

```html
<div id="rcTimelineChart" style="width:100%;height:320px;"></div>
```

- [ ] **Step 2: Add canvas element for Chart.js**

Replace the div with a canvas element:

```html
<!-- Replace this line -->
<div id="rcTimelineChart" style="width:100%;height:320px;"></div>

<!-- With this canvas element -->
<canvas id="rcTimelineChart" style="width:100%;height:320px;"></canvas>
```

- [ ] **Step 3: Verify container exists**

Add temporary console.log to verify:
```javascript
console.log('Chart canvas:', document.getElementById('rcTimelineChart'));
```

- [ ] **Step 4: Commit changes**

```bash
git add static/tabs/root-cause.html
git commit -m "fix: update timeline chart container to use canvas element"
```

---

## Task 4: Implement Chart.js Timeline Function

**Files:**
- Modify: `static/js/settings.js`

**Interfaces:**
- Consumes: `CHART_COLORS`, `ciBandPlugin` from chart-utils.js
- Produces: Updated `drawRcTimelineChart()` function

- [ ] **Step 1: Locate current drawRcTimelineChart function**

Find the function in `static/js/settings.js` (around line 137-190).

- [ ] **Step 2: Replace Plotly.js implementation with Chart.js**

Replace the entire `drawRcTimelineChart` function:

```javascript
function drawRcTimelineChart(ind) {
  const chartEl = document.getElementById('rcTimelineChart');
  const textEl = document.getElementById('rcTimelineText');
  if (!chartEl || !ind) return;
  
  const months = ind.series.map(p => p.month);
  const hv = ind.series.map(p => p.hospital_value);
  const pm = ind.series.map(p => p.peer_mean);
  
  // Extract CI band data
  const bandUpper = ind.series.map(p => p.peer_upper);
  const bandLower = ind.series.map(p => p.peer_lower);
  
  // Destroy existing chart if any
  if (window._rcTimelineChartInstance) {
    window._rcTimelineChartInstance.destroy();
  }
  
  // Create new Chart.js chart
  const ctx = chartEl.getContext('2d');
  window._rcTimelineChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        {
          label: (ind.indicator_name || ind.indicator_code) + ' — المستشفى',
          data: hv,
          borderColor: CHART_COLORS.primary,
          backgroundColor: CHART_COLORS.primary,
          borderWidth: 2.5,
          pointRadius: 5,
          pointHoverRadius: 7,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'متوسط النظير',
          data: pm,
          borderColor: CHART_COLORS.secondary,
          backgroundColor: CHART_COLORS.secondary,
          borderWidth: 2,
          borderDash: [5, 5],
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.3,
          fill: false,
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
          backgroundColor: '#1e293b',
          titleFont: { size: 11 },
          bodyFont: { size: 11 },
          padding: 12,
          cornerRadius: 6,
          callbacks: {
            title: function(items) {
              return items[0].label;
            },
            label: function(context) {
              const label = context.dataset.label || '';
              const value = context.parsed.y;
              return label + ': ' + value.toFixed(1);
            },
            afterBody: function(items) {
              const monthIndex = items[0].dataIndex;
              const peerCount = ind.series[monthIndex]?.peer_count;
              return peerCount ? 'Peer hospitals: ' + peerCount : '';
            }
          }
        },
        ciBand: {
          upper: bandUpper,
          lower: bandLower
        }
      },
      scales: {
        x: {
          grid: { color: CHART_COLORS.grid },
          ticks: { color: CHART_COLORS.neutral, font: { size: 10 } }
        },
        y: {
          grid: { color: CHART_COLORS.grid },
          ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
          beginAtZero: false,
        }
      },
      interaction: {
        intersect: false,
        mode: 'index'
      }
    },
    plugins: [ciBandPlugin]
  });
  
  if (textEl) {
    const withPeer = ind.series.filter(p => p.peer_count > 0);
    const avgPeers = withPeer.length
      ? Math.round(withPeer.reduce((a, p) => a + (p.peer_count || 0), 0) / withPeer.length)
      : 0;
    textEl.textContent = 'الخط الصلب: قيمة المستشفى شهراً بشهر. الخط المتقطع: متوسط النظير. النطاق المظلل: فاصل ثقة 95% حول متوسط النظير.'
      + (avgPeers ? ` متوسط عدد النظير في الشهر: ${avgPeers} مستشفى.` : '');
  }
}
```

- [ ] **Step 3: Test the function**

Add temporary console.log to verify:
```javascript
console.log('Chart instance:', window._rcTimelineChartInstance);
```

- [ ] **Step 4: Commit changes**

```bash
git add static/js/settings.js
git commit -m "feat: migrate timeline chart from Plotly.js to Chart.js"
```

---

## Task 5: Update renderRcTimeline Function

**Files:**
- Modify: `static/js/settings.js`

**Interfaces:**
- Consumes: Updated `drawRcTimelineChart()` function
- Produces: Updated `renderRcTimeline()` function

- [ ] **Step 1: Locate renderRcTimeline function**

Find the function in `static/js/settings.js` (around line 192-218).

- [ ] **Step 2: Update function to use Chart.js**

The function should remain mostly the same, but update the indicator selection logic:

```javascript
export function renderRcTimeline() {
  const sel = document.getElementById('rcTimelineIndicator');
  const chartEl = document.getElementById('rcTimelineChart');
  const textEl = document.getElementById('rcTimelineText');
  if (!sel || !chartEl) return;
  const inds = (_rcTimelineData.indicators || []).filter(i => (i.series || []).length >= 2);
  if (!inds.length) {
    sel.innerHTML = '<option value="">لا توجد بيانات زمنية كافية</option>';
    // Clear Chart.js chart
    if (window._rcTimelineChartInstance) {
      window._rcTimelineChartInstance.destroy();
      window._rcTimelineChartInstance = null;
    }
    if (textEl) textEl.textContent = 'لا توجد بيانات — تتطلب المقارنة الزمنية شهرين أو أكثر للمستشفى وللنظراء.';
    return;
  }
  sel.innerHTML = inds.map((i, idx) =>
    '<option value="' + idx + '">' + esc(i.indicator_name || i.indicator_code) + ' (' + esc(i.indicator_code) + ')</option>'
  ).join('');
  if (_rcTimelineSelCode != null) {
    const match = inds.findIndex(i => i.indicator_code === _rcTimelineSelCode);
    if (match >= 0) {
      sel.value = String(match);
    } else {
      _rcTimelineSelCode = inds[0] ? inds[0].indicator_code : null;
    }
  } else if (inds[0]) {
    _rcTimelineSelCode = inds[0].indicator_code;
  }
  drawRcTimelineChart(inds[parseInt(sel.value, 10) || 0]);
}
```

- [ ] **Step 3: Update renderRcTimelineChart function**

Update the chart rendering function:

```javascript
export function renderRcTimelineChart() {
  const sel = document.getElementById('rcTimelineIndicator');
  const inds = (_rcTimelineData.indicators || []).filter(i => (i.series || []).length >= 2);
  if (!sel || !inds.length) return;
  const idx = parseInt(sel.value, 10);
  if (!isNaN(idx) && inds[idx]) _rcTimelineSelCode = inds[idx].indicator_code;
  drawRcTimelineChart(inds[idx || 0]);
}
```

- [ ] **Step 4: Commit changes**

```bash
git add static/js/settings.js
git commit -m "feat: update renderRcTimeline functions for Chart.js"
```

---

## Task 6: Test Chart Migration

**Files:**
- Test: Browser console

**Interfaces:**
- Consumes: All previous tasks
- Produces: Verified chart functionality

- [ ] **Step 1: Open browser and navigate to root cause tab**

Navigate to the root cause analysis tab in the application.

- [ ] **Step 2: Select a hospital and month**

Choose a hospital and month from the dropdowns to trigger chart loading.

- [ ] **Step 3: Verify chart renders**

Check that:
- Chart displays with two lines (teal for hospital, purple for peer)
- CI band renders as purple shaded area
- Legend shows both datasets
- Tooltips appear on hover

- [ ] **Step 4: Test interactive features**

Test:
- Legend toggle (click to hide/show datasets)
- Hover effects (points enlarge on hover)
- Responsive behavior (resize browser window)

- [ ] **Step 5: Check console for errors**

Open browser console and verify no JavaScript errors.

- [ ] **Step 6: Commit final changes**

```bash
git add -A
git commit -m "test: verify Chart.js migration works correctly"
```

---

## Task 7: Clean Up Plotly.js References

**Files:**
- Modify: `static/js/settings.js`

**Interfaces:**
- Consumes: Verified Chart.js implementation
- Produces: Clean codebase without Plotly.js references

- [ ] **Step 1: Search for Plotly.js references**

Search for any remaining Plotly.js references:
```bash
grep -r "Plotly" static/
grep -r "plotly" static/
```

- [ ] **Step 2: Remove any Plotly.js specific code**

Remove any remaining Plotly.js specific functions or variables.

- [ ] **Step 3: Verify no Plotly.js references remain**

```bash
grep -r "Plotly" static/
# Should return no results
```

- [ ] **Step 4: Commit cleanup**

```bash
git add static/js/settings.js
git commit -m "chore: remove Plotly.js references"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `README.md` (if exists)

**Interfaces:**
- Consumes: Completed implementation
- Produces: Updated documentation

- [ ] **Step 1: Update dependencies section**

If README.md exists, update the dependencies section to reflect Chart.js instead of Plotly.js.

- [ ] **Step 2: Add migration notes**

Add a note about the chart migration in the changelog or updates section.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md
git commit -m "docs: update documentation for Chart.js migration"
```

---

## Verification Checklist

After completing all tasks, verify:

1. ✅ Chart.js CDN is loaded correctly
2. ✅ Timeline chart renders with Chart.js
3. ✅ Colors match unified color palette
4. ✅ CI band renders correctly
5. ✅ Tooltips show relevant information
6. ✅ Legend toggle works
7. ✅ Responsive on mobile and desktop
8. ✅ No JavaScript errors in console
9. ✅ All existing functionality preserved
10. ✅ Plotly.js references removed

---

## Rollback Plan

If issues arise:

1. Revert to Plotly.js CDN in `static/tabs/root-cause.html`
2. Restore original `drawRcTimelineChart()` function
3. Remove `static/js/chart-utils.js`
4. Test that original functionality works
