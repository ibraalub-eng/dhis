# Hospital Performance Analytics Dashboard

## Objective

Transform the existing Dashboard tab into a comprehensive **Hospital Performance Analytics**
page — a single-page view providing quick visual reading and rapid analysis of all hospitals'
performance across all months. No sub-tabs, no redundancy with existing tabs.

## Design Principles

1. **One page, three sections** — no sub-tabs, no accordion
2. **Non-redundant** — every element fills a gap not covered by existing tabs
3. **Read-speed first** — glanceable summaries, sortable tables, drill-down on click

---

## Layout (top to bottom)

### Filter Bar (sticky at top)
- Hospital dropdown (existing, unchanged)
- Year dropdown (existing, unchanged)
- **Month range slider** — NEW: select start/end month to filter time window
- Loading indicator (existing)

### Section 1: Executive Summary Cards (existing, enhanced)
Keeps the 4 summary cards + 6 KPI cards, but adds:

- **Sparkline** on each summary card (last 12 months of that metric)
- **Trend arrow** (▲/▼/—) on each KPI card comparing current vs previous period
- **Threshold coloring** (green/amber/red) enhanced

### Section 2: Hospital Ranking Table — NEW
| Rank | Hospital | Avg Quality Score | Trend (12mo) | Avg Clinical Rate | Confidence | Completeness | Consistency | Reports | Alerts |

- **Sortable** by any column (click header)
- **Color-coded rows** (green ≥80%, amber ≥60%, red <60%)
- Each row is **clickable** → opens Section 3

Data source: `/dashboard/overview` (existing) + new endpoint for clinical rates and confidence
aggregates.

### Section 3: Hospital Scorecard — NEW (appears on row click)
A card/drawer below the table showing for the selected hospital:

- **Header**: Hospital name + overall grade badge (A/B/C/D)
- **KPI bar**: Quality Score | Confidence | Completeness | Consistency | Total Alerts (color-coded)
- **Left column**: Quality Score Trend chart (all months — line chart)
- **Right column**: 7 Clinical Rates bar chart (vs peer average)
- **Bottom**: Last 5 alerts (inline, expandable)

Data source: new API endpoint `/dashboard/hospital-performance/{id}`

---

## New API Endpoints

### `GET /dashboard/hospital-performance/{hospital_id}`
Returns per-hospital aggregate data for the scorecard:
- hospital name, overall grade
- avg quality score, confidence, completeness, consistency
- quality trend (all months)
- 7 clinical rates with peer averages
- total alerts, last 5 alerts

### `GET /dashboard/ranking`
Returns hospital ranking with all metrics needed for the sortable table
(all hospitals, aggregated across all months):
- Could extend `/dashboard/overview` instead of a new endpoint

---

## Implementation Plan

### Phase 1: Backend
1. Add `/dashboard/hospital-performance/{id}` endpoint in `app/api/dashboard.py`
2. Extend `/dashboard/overview` with clinical rate averages per hospital if needed

### Phase 2: Frontend
1. Rewrite `static/tabs/dashboard.html` with the three-section layout
2. Rewrite `initDashboard()` / `loadDashboard()` in `static/js/settings.js`
3. Add sparkline rendering (mini Chart.js line charts)
4. Add sortable ranking table with click handler
5. Add scorecard panel (shown/hidden on row click)

### Phase 3: Polish
1. Add month range slider to filter bar
2. Ensure all existing filter functionality works
3. Test with available data
