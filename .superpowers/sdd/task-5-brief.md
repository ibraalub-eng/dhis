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