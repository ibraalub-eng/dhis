### Task 5: Frontend — Add Dashboard JS for ranking, scorecard, sparklines

**Files:**
- Modify: `static/js/settings.js` (add functions after `renderKpiCards`)
- Modify: `static/js/app.js` (import + register globals)

**Important notes:**
- `esc` is already imported at the top of `settings.js` from `./tree.js` — DO NOT re-import it
- `apiGet` is already imported in settings.js from `./api.js` — DO NOT re-import it
- All functions will be exported and registered as globals via `app.js`

- [ ] Step 1: Add sparkline rendering helper in `settings.js`

Insert AFTER the `renderKpiCards` function (which ends around line 316 with `}`). Add:

```javascript
function renderSparkline(canvasId, dataPoints, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !dataPoints || dataPoints.length < 2) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    const w = Math.max(rect.width - 10, 60);
    const h = 24;
    canvas.width = w * 2;
    canvas.height = h * 2;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(2, 2);
    ctx.clearRect(0, 0, w, h);
    const max = Math.max(...dataPoints, 1);
    const min = Math.min(...dataPoints, 0);
    const range = max - min || 1;
    const pts = dataPoints.map((v, i) => ({
        x: (i / (dataPoints.length - 1)) * (w - 6) + 3,
        y: h - 3 - ((v - min) / range) * (h - 6),
    }));
    ctx.beginPath();
    ctx.strokeStyle = color || '#3f51b5';
    ctx.lineWidth = 1.2;
    pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
    ctx.stroke();
    ctx.lineTo(pts[pts.length - 1].x, h - 3);
    ctx.lineTo(pts[0].x, h - 3);
    ctx.closePath();
    ctx.fillStyle = (color || '#3f51b5') + '18';
    ctx.fill();
}
```

- [ ] Step 2: Add ranking table rendering in `settings.js`

Add after `renderSparkline`:

```javascript
let rankingData = [];
let rankingSortCol = 'avg_score';
let rankingSortAsc = false;

export function loadRankingTable() {
    const hid = document.getElementById('dashHospital').value;
    let url = '/dashboard/ranking?';
    if (hid) url += 'hospital_id=' + hid;
    apiGet(url).then(data => {
        rankingData = data || [];
        renderRankingTable();
    }).catch(() => {});
}

function renderRankingTable() {
    const tbody = document.getElementById('rankingBody');
    if (!tbody) return;
    const col = rankingSortCol;
    const asc = rankingSortAsc;
    const sorted = [...rankingData].sort((a, b) => {
        const va = a[col], vb = b[col];
        if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? (va - vb) : (vb - va);
    });
    sorted.forEach((r, i) => r.rank = i + 1);

    tbody.innerHTML = sorted.map(r => {
        const rc = r.avg_score >= 90 ? 'row-a' : r.avg_score >= 75 ? 'row-b' : r.avg_score >= 60 ? 'row-c' : 'row-d';
        const ti = r.trend_direction === 'up' ? '\u25B2' : r.trend_direction === 'down' ? '\u25BC' : '\u2014';
        const tc = 'trend-' + r.trend_direction;
        return '<tr class="' + rc + '" onclick="showHospitalScorecard(' + r.id + ')">' +
            '<td>' + r.rank + '</td>' +
            '<td><strong>' + esc(r.name) + '</strong></td>' +
            '<td>' + r.avg_score + '%</td>' +
            '<td class="' + tc + '">' + ti + '</td>' +
            '<td>' + r.avg_clinical_rate + '%</td>' +
            '<td>' + r.confidence + '%</td>' +
            '<td>' + r.completeness + '%</td>' +
            '<td>' + r.consistency + '%</td>' +
            '<td>' + r.reports + '</td>' +
            '<td>' + (r.alerts > 0 ? '<span style="color:#c62828;font-weight:600;">' + r.alerts + '</span>' : '0') + '</td>' +
        '</tr>';
    }).join('');

    document.querySelectorAll('#rankingTable th.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === col) th.classList.add(asc ? 'sort-asc' : 'sort-desc');
    });
}

document.addEventListener('click', function(e) {
    const th = e.target.closest('#rankingTable th.sortable');
    if (!th) return;
    const col = th.dataset.col;
    if (rankingSortCol === col) rankingSortAsc = !rankingSortAsc;
    else { rankingSortCol = col; rankingSortAsc = false; }
    renderRankingTable();
});
```

- [ ] Step 3: Add scorecard panel functions in `settings.js`

Add after the sort handler:

```javascript
export function showHospitalScorecard(hospitalId) {
    const panel = document.getElementById('scorecardPanel');
    panel.style.display = 'block';
    document.getElementById('scorecardTitle').textContent = 'Loading...';
    document.getElementById('scorecardContent').innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">Loading...</p>';

    apiGet('/dashboard/hospital-performance/' + hospitalId).then(d => {
        const gradeColors = {A:'#2e7d32', B:'#1565c0', C:'#e65100', D:'#c62828'};
        const gc = gradeColors[d.grade] || '#888';
        document.getElementById('scorecardTitle').innerHTML =
            '<span class="scorecard-grade" style="background:' + gc + ';">' + d.grade + '</span>' + esc(d.name);

        const qc = d.avg_score >= 75 ? '#2e7d32' : d.avg_score >= 50 ? '#e65100' : '#c62828';
        let html = '<div class="scorecard-kpi-bar">' +
            '<div class="scorecard-kpi-item" style="border-top-color:' + qc + ';background:#f0f8ff;">' +
                '<div style="font-size:0.65rem;color:#888;text-transform:uppercase;">Quality Score</div>' +
                '<div style="font-size:1.5rem;font-weight:700;color:' + qc + ';">' + d.avg_score + '%</div></div>' +
            '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:#888;text-transform:uppercase;">Compliance</div>' +
                '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_compliance + '%</div></div>' +
            '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:#888;text-transform:uppercase;">Completeness</div>' +
                '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_completeness + '%</div></div>' +
            '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:#888;text-transform:uppercase;">Consistency</div>' +
                '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_consistency + '%</div></div>' +
            '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:#888;text-transform:uppercase;">Alerts</div>' +
                '<div style="font-size:1.1rem;font-weight:600;color:' + (d.total_alerts > 0 ? '#c62828' : '#2e7d32') + ';">' + d.total_alerts + '</div></div>' +
        '</div>';

        html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">' +
            '<div class="card"><h3>Quality Score Trend</h3><canvas id="scorecardTrendChart" style="height:180px;"></canvas></div>' +
            '<div class="card"><h3>Clinical Rates <span style="font-size:0.7rem;font-weight:400;color:#888;">vs Peer Avg</span></h3><canvas id="scorecardRatesChart" style="height:180px;"></canvas></div>' +
        '</div>';

        html += '<div style="margin-top:1rem;"><h3>Recent Alerts</h3>';
        if (d.last_alerts && d.last_alerts.length) {
            html += d.last_alerts.map(a => {
                const sc = a.severity === 'CRITICAL' ? '#c62828' : a.severity === 'HIGH' ? '#e65100' : '#f9a825';
                return '<div class="scorecard-alert">' +
                    '<span style="width:8px;height:8px;border-radius:50%;background:' + sc + ';flex-shrink:0;"></span>' +
                    '<span style="font-weight:600;font-size:0.7rem;color:' + sc + ';">' + a.severity + '</span>' +
                    '<span style="font-size:0.75rem;">' + esc(a.rule_code) + '</span>' +
                    '<span style="color:#888;font-size:0.7rem;">' + esc(a.details) + '</span>' +
                    '<span style="color:#aaa;font-size:0.65rem;margin-left:auto;">' + a.month + '</span>' +
                '</div>';
            }).join('');
        } else {
            html += '<p style="color:#888;font-size:0.8rem;">No alerts for this hospital.</p>';
        }
        html += '</div>';

        document.getElementById('scorecardContent').innerHTML = html;

        const trendCtx = document.getElementById('scorecardTrendChart');
        if (trendCtx && d.quality_trend && d.quality_trend.length) {
            new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: d.quality_trend.map(p => p.month.slice(-2)),
                    datasets: [{
                        data: d.quality_trend.map(p => p.score),
                        borderColor: '#3f51b5',
                        backgroundColor: 'rgba(63,81,181,0.1)',
                        fill: true, tension: 0.3, pointRadius: 3,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                }
            });
        }

        const ratesCtx = document.getElementById('scorecardRatesChart');
        if (ratesCtx && d.clinical_rates && d.clinical_rates.length) {
            const labels = d.clinical_rates.map(r => r.rate_name.replace(' Rate', '').replace(' Ratio', ''));
            new Chart(ratesCtx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Hospital', data: d.clinical_rates.map(r => r.value), backgroundColor: '#3f51b5', borderRadius: 3 },
                        { label: 'Peer Avg', data: d.clinical_rates.map(r => r.peer_avg ?? null), backgroundColor: '#ff9800', borderRadius: 3 }
                    ]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: 'top', labels: { font: { size: 9 } } } },
                    scales: { y: { beginAtZero: true } }
                }
            });
        }
    }).catch(e => {
        document.getElementById('scorecardContent').innerHTML = '<p style="color:#c62828;">Error: ' + e.message + '</p>';
    });
}

export function closeScorecard() {
    document.getElementById('scorecardPanel').style.display = 'none';
}
```

- [ ] Step 4: Update `loadDashboard()` in `settings.js`

Find the `loadDashboard` function (around line 352). In its `.then()` callback, after the line `loadHeatmap(hid);` and before the `.catch()`, add:
```javascript
                loadRankingTable();
```

Also inside the `.then()`, after the summary card values are set (after `dashAlerts`), add:
```javascript
                if (data.quality_trend && data.quality_trend.length) {
                    const vals = data.quality_trend.map(d => d.score);
                    renderSparkline('sparkAvgScore', vals, '#3f51b5');
                }
```

- [ ] Step 5: Register new functions as globals in `app.js`

In `static/js/app.js` line 8, add `loadRankingTable`, `showHospitalScorecard`, `closeScorecard` to the import from `./settings.js`:
```javascript
import { loadAllSettings, saveAllSettings, reanalyzeAll, showSettingsTab, saveAiSettings, loadAiSettings, onAiProviderChange, loadRulesManager, initRootCause, initDashboard, loadRootCause, populateMonthSelect, loadDashboard, saveControlSettings, updateWeightDisplay, updateCfgDisplay, updateCfgVal, loadRankingTable, showHospitalScorecard, closeScorecard } from './settings.js';
```

After line 63 (`window.initDashboard = initDashboard;`), add:
```javascript
window.loadRankingTable = loadRankingTable;
window.showHospitalScorecard = showHospitalScorecard;
window.closeScorecard = closeScorecard;
```
