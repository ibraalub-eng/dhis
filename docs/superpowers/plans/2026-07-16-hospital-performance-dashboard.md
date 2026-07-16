# Hospital Performance Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the existing Dashboard tab into a single-page Hospital Performance Analytics view with executive summary cards (with sparklines), a sortable hospital ranking table, and a click-to-open per-hospital scorecard showing quality trend, clinical rates vs peer average, and recent alerts.

**Architecture:** Extend existing `/dashboard/` API with two new endpoints in `app/api/dashboard.py`. Rewrite `static/tabs/dashboard.html` into 3 sections. Add rendering functions to `static/js/settings.js`. Add new CSS to `static/css/styles.css`. All existing charts (trend, YoY, confidence donut, radar, heatmap) remain in Section 1.

**Tech Stack:** FastAPI (Python 3.14+), Chart.js 3.x, vanilla JS, SQLAlchemy ORM

## Global Constraints

- All Python is 3.14+ with type hints
- Frontend uses vanilla JS (no frameworks), Chart.js for charts
- API base = `""` (relative), accessed via `apiGet()` from `api.js`
- No new npm/pip packages
- Server needs `--reload` to apply code changes
- Tests use pytest + in-memory SQLite via `conftest.py`

---

### Task 1: Backend — Add `/dashboard/ranking` endpoint

**Files:**
- Modify: `app/api/dashboard.py`

**Interfaces:**
- Consumes: `Hospital`, `QualityScore`, `ValidationResult`, `ConfidenceScore`, `ClinicalInsight` tables
- Produces: `GET /dashboard/ranking` → JSON array of `{id, name, avg_score, trend_direction, avg_clinical_rate, confidence, completeness, consistency, reports, alerts, rank}`

- [ ] **Step 1: Update imports in `app/api/dashboard.py`**

Add `ClinicalInsight` to the model import. Change line 5 from:
```python
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult
```
to:
```python
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult, ClinicalInsight
```

Add `json` import if not already present (line 1 is `import re`, so add `import json` above it).

- [ ] **Step 2: Add the ranking endpoint function after the last existing endpoint (after line 241)**

```python
@router.get("/ranking")
def dashboard_ranking(hospital_id: int | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db)

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    rows = []
    for h in hospitals:
        q = db.query(QualityScore).filter(QualityScore.hospital_id == h.id)
        if enabled_months:
            q = q.filter(QualityScore.month.in_(enabled_months))
        scores = q.order_by(QualityScore.month.asc()).all()

        if not scores:
            continue

        avg_score = round(sum(s.score for s in scores) / len(scores), 1)
        avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1)
        avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1)
        avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1)

        recent_3 = [s.score for s in scores[-3:]]
        if len(recent_3) >= 2:
            direction = "up" if recent_3[-1] > recent_3[0] else "down" if recent_3[-1] < recent_3[0] else "stable"
        else:
            direction = "stable"

        conf = db.query(ConfidenceScore).filter(
            ConfidenceScore.hospital_id == h.id
        ).order_by(ConfidenceScore.month.desc()).first()
        conf_score = round(conf.overall_confidence, 1) if conf else 0

        alerts_count = db.query(ValidationResult).filter(
            ValidationResult.hospital_id == h.id,
            ValidationResult.status == "FAIL"
        ).count()

        insights = db.query(ClinicalInsight).filter(
            ClinicalInsight.hospital_id == h.id
        ).all()
        rate_values = {}
        for ins in insights:
            try:
                data = json.loads(ins.analysis_data)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in data.get("classifications", []):
                rn = c.get("rate_name", "")
                val = c.get("value")
                if val is not None:
                    rate_values.setdefault(rn, []).append(val)
        clinical_rates = {}
        for rn, vals in rate_values.items():
            if vals:
                clinical_rates[rn] = round(sum(vals) / len(vals), 1)

        rows.append({
            "id": h.id,
            "name": h.name,
            "avg_score": avg_score,
            "trend_direction": direction,
            "avg_clinical_rate": round(sum(clinical_rates.values()) / len(clinical_rates), 1) if clinical_rates else 0,
            "confidence": conf_score,
            "completeness": avg_completeness,
            "consistency": avg_consistency,
            "reports": len(scores),
            "alerts": alerts_count,
        })

    rows.sort(key=lambda r: r["avg_score"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return rows
```

- [ ] **Step 3: Verify the endpoint loads**

```bash
cd C:\ibra\HEALTH-ai; python -c "from app.api.dashboard import router; print('dashboard router OK')"
```
Expected: `dashboard router OK`

---

### Task 2: Backend — Add `/dashboard/hospital-performance/{id}` endpoint

**Files:**
- Modify: `app/api/dashboard.py` (add after `/ranking` endpoint)

**Interfaces:**
- Consumes: Hospital ID, `QualityScore`, `ValidationResult`, `ClinicalInsight`, and `run_clinical_analysis()` from engine
- Produces: `GET /dashboard/hospital-performance/{id}` → `{id, name, grade, avg_score, avg_compliance, avg_completeness, avg_consistency, quality_trend, clinical_rates[], total_alerts, last_alerts[]}`

- [ ] **Step 1: Add import for `get_enabled_values_for_hospital_month` at top of file**

Add after existing imports:
```python
from app.engine.pipeline import get_enabled_values_for_hospital_month
```

- [ ] **Step 2: Add the hospital performance endpoint**

```python
@router.get("/hospital-performance/{hospital_id}")
def hospital_performance(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    scores = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id
    ).order_by(QualityScore.month.asc()).all()

    quality_trend = [{"month": s.month, "score": round(s.score, 1)} for s in scores]
    avg_score = round(sum(s.score for s in scores) / len(scores), 1) if scores else 0
    avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1) if scores else 0

    # Grade
    if avg_score >= 90: grade = "A"
    elif avg_score >= 75: grade = "B"
    elif avg_score >= 60: grade = "C"
    else: grade = "D"

    # Clinical rates — latest month
    latest_month = scores[-1].month if scores else None
    clinical_rates = []
    if latest_month:
        try:
            values = get_enabled_values_for_hospital_month(db, hospital_id, latest_month)
            if values:
                from app.engine.clinical import run_clinical_analysis
                result = run_clinical_analysis(hospital=hospital.name, month=latest_month, values=values)
                MAIN_RATES = {"C-Section Rate", "Maternal Mortality Ratio", "Neonatal Mortality Rate",
                              "Preterm Birth Rate", "Severe Maternal Morbidity Rate", "Stillbirth Rate",
                              "NICU Admission Rate"}
                for c in result.classifications:
                    if c.rate_name in MAIN_RATES:
                        clinical_rates.append({
                            "rate_name": c.rate_name,
                            "value": round(c.value, 1) if c.value else 0,
                            "unit": c.unit,
                            "classification": c.classification,
                        })
        except Exception:
            pass

    # Peer averages for clinical rates
    if latest_month and clinical_rates:
        try:
            peers = db.query(Hospital).filter(Hospital.is_active.is_(True), Hospital.id != hospital_id).all()
            peer_rate_vals = {r["rate_name"]: [] for r in clinical_rates}
            for ph in peers:
                pv = get_enabled_values_for_hospital_month(db, ph.id, latest_month)
                if not pv:
                    continue
                from app.engine.clinical import run_clinical_analysis as rca_peer
                try:
                    pr = rca_peer(hospital=ph.name, month=latest_month, values=pv)
                except Exception:
                    continue
                for c in pr.classifications:
                    if c.rate_name in peer_rate_vals and c.value is not None:
                        peer_rate_vals[c.rate_name].append(c.value)
            for r in clinical_rates:
                vals = peer_rate_vals.get(r["rate_name"], [])
                r["peer_avg"] = round(sum(vals) / len(vals), 1) if vals else None
        except Exception:
            pass

    # Alerts
    total_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).count()
    recent_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).order_by(ValidationResult.month.desc()).limit(5).all()
    last_alerts = [
        {"month": a.month, "rule_code": a.rule_code, "severity": a.severity, "details": (a.details or "")[:80]}
        for a in recent_alerts
    ]

    return {
        "id": hospital.id, "name": hospital.name, "grade": grade,
        "avg_score": avg_score, "avg_compliance": avg_compliance,
        "avg_completeness": avg_completeness, "avg_consistency": avg_consistency,
        "quality_trend": quality_trend, "clinical_rates": clinical_rates,
        "total_alerts": total_alerts, "last_alerts": last_alerts,
    }
```

- [ ] **Step 3: Verify endpoint loads**

```bash
cd C:\ibra\HEALTH-ai; python -c "from app.api.dashboard import router; print('dashboard router OK')"
```
Expected: `dashboard router OK`

---

### Task 3: Frontend — Rewrite `dashboard.html`

**Files:**
- Modify: `static/tabs/dashboard.html` (replace entire content)

**Interfaces:**
- Consumes: JS functions `loadDashboard()`, `loadRankingTable()`, `showHospitalScorecard()`, `closeScorecard()` defined in `settings.js`
- Produces: 3-section layout with filter bar, executive cards, ranking table, scorecard panel, and charts

- [ ] **Step 1: Replace the entire dashboard.html content**

```html
<div class="filter-bar">
    <label>Hospital:</label>
    <select id="dashHospital" onchange="loadDashboard()"><option value="">All Hospitals</option></select>
    <label>Year:</label>
    <select id="dashYear" onchange="loadDashboard()">
        <option value="">All Years</option>
    </select>
    <span id="dashLoading" class="status-loading hidden" style="padding:0.2rem 0.5rem;font-size:0.8rem;"><span class="spinner"></span> Loading...</span>
</div>

<!-- Section 1: Executive Summary -->
<div id="dashSummarySection">
    <div class="dashboard-grid" id="dashSummaryCards">
        <div class="card summary-card">
            <div class="value" id="dashHospitals">-</div>
            <div class="label">Hospitals</div>
            <canvas class="sparkline" id="sparkHospitals" height="24"></canvas>
        </div>
        <div class="card summary-card">
            <div class="value" id="dashReports">-</div>
            <div class="label">Reports</div>
            <canvas class="sparkline" id="sparkReports" height="24"></canvas>
        </div>
        <div class="card summary-card">
            <div class="value" id="dashAvgScore">-</div>
            <div class="label">Avg Quality Score</div>
            <canvas class="sparkline" id="sparkAvgScore" height="24"></canvas>
        </div>
        <div class="card summary-card">
            <div class="value" id="dashAlerts" style="color:#c62828;">-</div>
            <div class="label">Active Alerts</div>
            <canvas class="sparkline" id="sparkAlerts" height="24"></canvas>
        </div>
    </div>
    <div class="dashboard-grid" id="dashKpiCards"></div>
    <div class="charts-row" style="margin-top:1rem;">
        <div class="card chart-full"><h2>Quality Score Trend</h2><canvas id="trendChart"></canvas></div>
        <div class="card chart-full"><h2>Year-over-Year Comparison</h2><canvas id="yoyChart"></canvas></div>
        <div class="card"><h2>Confidence Distribution</h2><canvas id="confidenceChart"></canvas></div>
        <div class="card"><h2>Quality Components</h2><canvas id="radarChart"></canvas></div>
    </div>
    <div class="card" style="margin-top:1.5rem;"><h2>Quality Score Heatmap <span style="font-size:0.75rem;font-weight:400;color:#888;margin-left:0.5rem;">Hospital × Month</span></h2>
        <div style="overflow-x:auto;" id="heatmapContainer"></div>
    </div>
</div>

<!-- Section 2: Hospital Ranking -->
<div class="card" style="margin-top:1.5rem;">
    <h2>Hospital Performance Ranking <span style="font-size:0.75rem;font-weight:400;color:#888;margin-left:0.5rem;">Click a row for details</span></h2>
    <div style="overflow-x:auto;">
        <table id="rankingTable" class="ranking-table">
            <thead>
                <tr>
                    <th data-col="rank">#</th>
                    <th data-col="name" class="sortable">Hospital</th>
                    <th data-col="avg_score" class="sortable sort-desc">Quality Score</th>
                    <th data-col="trend_direction" class="sortable">Trend</th>
                    <th data-col="avg_clinical_rate" class="sortable">Avg Clinical Rate</th>
                    <th data-col="confidence" class="sortable">Confidence</th>
                    <th data-col="completeness" class="sortable">Completeness</th>
                    <th data-col="consistency" class="sortable">Consistency</th>
                    <th data-col="reports" class="sortable">Reports</th>
                    <th data-col="alerts" class="sortable">Alerts</th>
                </tr>
            </thead>
            <tbody id="rankingBody"></tbody>
        </table>
    </div>
</div>

<!-- Section 3: Hospital Scorecard (hidden until row click) -->
<div id="scorecardPanel" class="card" style="margin-top:1.5rem;display:none;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <h2 id="scorecardTitle">Hospital Scorecard</h2>
        <button class="btn btn-sm" onclick="closeScorecard()" style="background:#e0e0e0;border:none;cursor:pointer;padding:0.3rem 0.8rem;border-radius:4px;">Close</button>
    </div>
    <div id="scorecardContent">
        <p style="color:#888;text-align:center;padding:2rem;">Select a hospital from the ranking table above.</p>
    </div>
</div>
```

---

### Task 4: Frontend — Add CSS for new components

**Files:**
- Modify: `static/css/styles.css` (append at end)

- [ ] **Step 1: Add new CSS rules**

```css
.ranking-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
}
.ranking-table th {
    padding: 0.5rem 0.4rem;
    text-align: left;
    font-weight: 600;
    color: #555;
    border-bottom: 2px solid #e0e0e0;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
}
.ranking-table th:hover { color: #1a237e; }
.ranking-table th.sort-asc::after { content: ' \25B2'; opacity: 1; }
.ranking-table th.sort-desc::after { content: ' \25BC'; opacity: 1; }
.ranking-table td {
    padding: 0.5rem 0.4rem;
    border-bottom: 1px solid #f0f0f0;
    white-space: nowrap;
}
.ranking-table tr:hover { background: #f5f5ff; }
.ranking-table tr { cursor: pointer; }
.ranking-table .row-a { background: #e8f5e9; }
.ranking-table .row-b { background: #fff8e1; }
.ranking-table .row-c { background: #fff3e0; }
.ranking-table .row-d { background: #ffebee; }
.summary-card { position: relative; }
.sparkline {
    width: 100%;
    height: 24px;
    margin-top: 4px;
    display: block;
}
.trend-up { color: #2e7d32; }
.trend-down { color: #c62828; }
.trend-stable { color: #f9a825; }
.scorecard-kpi-bar {
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
}
.scorecard-kpi-item {
    flex: 1;
    min-width: 100px;
    text-align: center;
    padding: 0.6rem 0.3rem;
    background: #fafafa;
    border-radius: 6px;
    border-top: 3px solid #ccc;
}
.scorecard-grade {
    display: inline-block;
    font-size: 1.8rem;
    font-weight: 700;
    width: 50px;
    height: 50px;
    line-height: 50px;
    text-align: center;
    border-radius: 50%;
    color: #fff;
    margin-right: 0.8rem;
    vertical-align: middle;
}
.scorecard-alert {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0;
    font-size: 0.75rem;
    border-bottom: 1px solid #f0f0f0;
}
```

---

### Task 5: Frontend — Add Dashboard JS for ranking, scorecard, sparklines

**Files:**
- Modify: `static/js/settings.js`

- [ ] **Step 1: Add sparkline rendering helper**

Add after `renderKpiCards` function (after line 316):
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
    // Fill
    ctx.lineTo(pts[pts.length - 1].x, h - 3);
    ctx.lineTo(pts[0].x, h - 3);
    ctx.closePath();
    ctx.fillStyle = (color || '#3f51b5') + '18';
    ctx.fill();
}
```

- [ ] **Step 2: Add ranking table rendering**

Add after `renderSparkline`:
```javascript
let rankingData = [];
let rankingSortCol = 'avg_score';
let rankingSortAsc = false;

function loadRankingTable() {
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

// Sort handler (delegated)
document.addEventListener('click', function(e) {
    const th = e.target.closest('#rankingTable th.sortable');
    if (!th) return;
    const col = th.dataset.col;
    if (rankingSortCol === col) rankingSortAsc = !rankingSortAsc;
    else { rankingSortCol = col; rankingSortAsc = false; }
    renderRankingTable();
});
```

- [ ] **Step 3: Add scorecard panel functions**

Add after `renderRankingTable`:
```javascript
window.showHospitalScorecard = function(hospitalId) {
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

        // Trend chart
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

        // Clinical rates bar chart
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
};

window.closeScorecard = function() {
    document.getElementById('scorecardPanel').style.display = 'none';
};
```

- [ ] **Step 4: Register new functions as exports**

At the end of `settings.js`, add export declarations:
```javascript
export function loadRankingTable() { /* same body as step 2 */ }
export function showHospitalScorecard(hospitalId) { /* same body as step 3 */ }
export function closeScorecard() { /* same body as step 3 */ }
```

Then **remove** the `window.showHospitalScorecard =` and `window.closeScorecard =` assignments from the step 3 code above — those should just be regular function definitions. Only the sort event listener should remain as-is (it fires at module load time, not via onclick).

- [ ] **Step 5: Register globals in `app.js`**

In `app.js` line 8, add `loadRankingTable`, `showHospitalScorecard`, `closeScorecard` to the import:
```javascript
import { loadAllSettings, saveAllSettings, reanalyzeAll, showSettingsTab, saveAiSettings, loadAiSettings, onAiProviderChange, loadRulesManager, initRootCause, initDashboard, loadRootCause, populateMonthSelect, loadDashboard, saveControlSettings, updateWeightDisplay, updateCfgDisplay, updateCfgVal, loadRankingTable, showHospitalScorecard, closeScorecard } from './settings.js';
```

Then add to the window assignments (after line 63):
```javascript
window.loadRankingTable = loadRankingTable;
window.showHospitalScorecard = showHospitalScorecard;
window.closeScorecard = closeScorecard;
```

- [ ] **Step 6: Update `loadDashboard()` to call `loadRankingTable()`**

Find the `loadDashboard` function (line 352). At the end of its `.then()` callback, after the existing `loadHeatmap(hid);` line, add:
```javascript
                loadRankingTable();
```

Also ensure the summary cards' sparklines are rendered. Inside the `.then()` after setting the summary card text values, add:
```javascript
                if (data.quality_trend && data.quality_trend.length) {
                    const vals = data.quality_trend.map(d => d.score);
                    renderSparkline('sparkAvgScore', vals, '#3f51b5');
                }
```

The complete updated `loadDashboard()` should have these additions.

---

### Task 6: Self-review & test

- [ ] **Step 1: Check that the Python files load correctly**

```bash
cd C:\ibra\HEALTH-ai; python -c "
from app.api.dashboard import router
# Check we have 4 routes
routes = [r.path for r in router.routes]
print('Routes:', routes)
assert '/ranking' in routes, 'Missing /ranking'
assert '/hospital-performance/{hospital_id}' in routes, 'Missing /hospital-performance'
print('All routes OK')
"
```

- [ ] **Step 2: Start the server and verify frontend loads**

```bash
cd C:\ibra\HEALTH-ai; python app/main.py --reload
```

Open browser to http://localhost:8000, click Dashboard tab. Verify:
- Summary cards load with sparklines
- KPI cards load
- Charts render (trend, YoY, confidence, radar, heatmap)
- Ranking table loads with hospital rows
- Click a hospital row → scorecard panel appears with trend chart + clinical rates + alerts

- [ ] **Step 3: Run existing tests to confirm no regressions**

```bash
cd C:\ibra\HEALTH-ai; pytest tests/ -v --timeout=30 2>&1 | tail -30
```
Expected: All tests pass (or at least no new failures).
