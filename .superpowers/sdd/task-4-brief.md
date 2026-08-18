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