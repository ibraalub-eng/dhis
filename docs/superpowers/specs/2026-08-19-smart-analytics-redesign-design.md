# Smart Analytics Screen — Production-Ready Redesign

**Date:** 2026-08-19
**Status:** Approved design
**Scope:** Full redesign of the smart analytics screen (التحليل الذكي) — frontend rewrite, per-section API splitting, performance, backend robustness, maintenance, quality, and bilingual AR/EN support.

---

## 1. Context

The current smart analytics screen is a single scrolling page (`static/tabs/smart-analytics.html`, 658 lines + `static/js/smart-analytics.js`, 2845 lines) that renders results of `run_smart_analytics()` for one month, refreshing everything on month change. Diagnosis is documented in `docs/SMART_ANALYTICS_UI_REVIEW.md`:

- **Information overload:** ~20 sections visible at once, 15–18 Plotly charts rendered on every month load, technical terms (SHAP, XGBoost, Apriori) as primary headings.
- **Redundancy:** anomaly distribution, SHAP importance, correlations, XGBoost, methodology each duplicated in 3–6 places.
- **Performance:** no lazy rendering, duplicate `/smart/overview/{month}` fetch, fragile `setTimeout` sequencing, heavy animated timeline built eagerly.
- **Maintenance:** inline styles everywhere, single 2845-line JS file, duplicate `_smartEscapeHtml`, spelling errors, contradictory methodology text.
- **Accessibility:** no `role="dialog"`, focus trap, Escape handling, or aria-labels.

The backend (`app/api/smart_analytics.py`, 12 endpoints) returns one big envelope per month, with per-slice endpoints that read from a shared TTL cache. All 127 smart tests currently pass.

## 2. Goals

1. **Decision-first experience:** decision board above the fold, analysis progressively disclosed.
2. **Logical scope modes** that reflect month/hospital/all-months filters in the UI.
3. **Per-section data loading** with independent loaders.
4. **Performance:** lazy rendering, no duplicate requests, real sequencing.
5. **Backend robustness:** strong error handling, clean empty states, smarter caching.
6. **Maintenance:** modular JS, CSS extraction, typo fixes, unified methodology.
7. **Full Arabic/English support** across the whole screen.
8. **Accessibility** improvements.

## 3. Design

### 3.1 Three Logical Modes

The screen is organized by analysis scope. A mode bar at the top switches between three modes:

```
┌─────────────────────────────────────────────────────────┐
│  Mode bar:  [شهري | زمني | مستشفى]                      │
│  ─────────────────────────────────────────────────────  │
│  شهري:  month selector → decision board + month sections │
│  زمني:  (no month) → all-months trends                  │
│  مستشفى: hospital selector + month/all → hospital board  │
└─────────────────────────────────────────────────────────┘
```

| Mode | Logic | Data |
|------|-------|------|
| **شهري (Monthly)** | All hospitals × one month | Decision board (fast single payload) + per-section endpoints |
| **زمني (Time)** | All hospitals × all months | `anomaly-timeline` + new `time-overview` (score evolution, severity distribution, early-warning trends across months) |
| **مستشفى (Hospital)** | One hospital × (one month or all months) | Existing `drilldown/{hospital_id}/{month}` (supports `month=all`) + `trend/{hospital_id}` |

Monthly is the default mode on tab open.

### 3.2 API Structure

The shared backend compute cache (`_get_smart_data`, TTL 5 min) stays as-is. Per-section endpoints already read from it; the network split below adds no recomputation. `/smart/overview` remains fully supported for backward compatibility.

#### Decision board (fast, above-the-fold)
- **`GET /smart/decision-board/{month}`** — KPI cards, critical hospitals, early warnings, healthy hospitals, month status. New endpoint; becomes the primary month load in the new frontend.
- **`GET /smart/overview/{month}`** — KEPT for backward compatibility. Existing tests depend on it (14 references across test files); it remains the full-envelope source. The shared backend compute cache means `decision-board` reuses the same computation without extra cost.

#### Per-section analytic endpoints (each with its own loader)
Existing slice endpoints stay: `/anomalies/{month}`, `/clusters/{month}`, `/correlations/{month}`, `/residuals/{month}`, `/stratified/{month}`, `/geo/{month}`, `/governorate-analysis/{month}`.

New per-section endpoints (extracted from the overview envelope so each loads independently):
- **`GET /smart/patterns/{month}`** — composite patterns (Apriori)
- **`GET /smart/lag-analysis/{month}`** — lead-lag relationships
- **`GET /smart/xgboost/{month}`** — XGBoost predictions + walk-forward validation
- **`GET /smart/time-overview`** — all-months trends for the time mode (cached like the others; depends on `anomaly-timeline` data shape)

#### On-demand
- Existing `GET /smart/trend/{hospital_id}` and `GET /smart/drilldown/{hospital_id}/{month}` for hospital mode.

#### Data flow
1. Month opens → fetch **decision board only** (fast), render immediately.
2. Each analytic section below fetches its own endpoint when it enters the viewport (IntersectionObserver), with an **independent loader**.
3. Backend compute cache (`_get_smart_data`) is shared — per-section endpoints hit the same cache, so the split is network-only, no recomputation.
4. A failing section shows its own error and does not take down the rest of the page.

### 3.3 Frontend Structure

#### Layout — modern card-based

```
┌─────────────────────────────────────────────────────────────┐
│ Top bar: [logo] [التحليل الذكي] [شهري|زمني|مستشفى]  ⓘ      │
│ Context bar: (per mode) filters + actions (report/export/lang)│
├─────────────────────────────────────────────────────────────┤
│ Decision board (above fold — monthly mode)                  │
│  [Month status] [4 KPI cards] [Priority/critical list]      │
│  [Early warnings if present]                                │
├─────────────────────────────────────────────────────────────┤
│ Analytic sections (collapsible, heavy ones folded)          │
│  ▸ Hospitals: anomaly table + healthy hospitals             │
│  ▸ Geography: map + regional + governorates                 │
│  ▸ Advanced models [tabs: clusters | correlation/residuals |│
│    patterns/lead-lag | feature importance]                  │
│  ▸ Forecasts: XGBoost + walk-forward                        │
├─────────────────────────────────────────────────────────────┤
│ On demand: methodology modal ⓘ | hospital modal | report    │
└─────────────────────────────────────────────────────────────┘
```

#### Design principles
1. **Decision first:** decision board (month status, KPI, priorities) leads the page without scrolling.
2. **Progressive disclosure:** technical sections (SHAP/XGBoost/Apriori) folded by default; technical terms appear parenthetically after the Arabic phrase.
3. **Card-based visual:** shadows, distinct accents, responsive grids `repeat(auto-fit,minmax(...))`.
4. **Bilingual:** full AR/EN toggle reusing the existing `i18n.js` system; all screen chrome, section titles, and labels translated.
5. **Accessibility:** `role="dialog"` + `aria-modal` + focus trap + Escape for modals, `aria-label` on icon buttons, min font size 0.75rem.

### 3.4 Performance

1. Remove the duplicate `/smart/overview` fetch in `updateHospitalList` — read the already-loaded payload.
2. Lazy rendering via IntersectionObserver; `Plotly.purge` on collapse to free memory.
3. Replace `setTimeout` sequencing with viewport-driven rendering.
4. Defer the animated all-months timeline until first visibility.
5. Reduce default chart heights (~260px) with zoom-on-demand.

### 3.5 Backend Robustness

1. **Stronger error handling:** every endpoint wraps computation in try/except → Arabic error response + cache invalidation (the existing pattern in `/smart/overview` is generalized to all section endpoints). Section failure is isolated.
2. **Clean empty states:** month/hospital with no data → clean response + Arabic UI message, never a raw error.
3. **Smarter caching:**
   - `/smart/trend`, `/smart/drilldown`, `/smart/anomaly-timeline` cached with the same TTL (5 min).
   - Cache keys include a schema/algorithm version so stale data is never served after algorithm changes.

### 3.6 Maintenance & Quality

1. **Split `smart-analytics.js`** (2845 lines) into logical modules under `static/js/smart/`:
   - `core.js` — shared state, fetch, loaders, modes
   - `decision-board.js` — decision board, KPI, priorities, early warnings
   - `charts.js` — analytic sections (anomalies/clusters/correlations/residuals/stratified/patterns/lead-lag)
   - `advanced.js` — XGBoost, walk-forward, feature importance
   - `geo-regional.js` — map, governorates, regional
   - `hospital.js` — hospital board/modal
   - `report.js` — comprehensive report, export
2. **Move inline styles to `styles.css`** (cards, responsive grids, badges, tables, loaders).
3. **Fix spelling errors** («المتأضعة» → «المتأثرة», «المتوسطقة» → «المتوسطة») and delete the duplicate `_smartEscapeHtml`.
4. **Unify methodology text** in a single ⓘ modal instead of 6 duplicated locations.
5. **Keep Plotly.js** (only the smart screen uses it); no new chart libraries.

## 4. Data Structures

No schema changes to engine dataclasses. API envelope changes only:

- New `decision-board` payload: subset of current overview (kpi, anomalies top-N, early_warnings, healthy_hospitals, month status, hospitals_count, generated_at).
- New `patterns`, `lag-analysis`, `xgboost`, `time-overview` payloads: slices of the existing envelope fields.
- Existing slice endpoints unchanged in shape.

## 5. Error Handling

- Each endpoint: try/except → `{error: "رسالة عربية واضحة", detail: ...}` + cache invalidation.
- Empty month/hospital → `{empty: true, message: "لا توجد بيانات لهذا الشهر/المستشفى"}`.
- Frontend: per-section error banner (Arabic), retry button; decision board failure shows a global error state.

## 6. Testing

| Area | Tests |
|------|-------|
| **Backend** | new endpoints (`/decision-board`, `/patterns`, `/lag-analysis`, `/xgboost`, `/time-overview`) — correct data, errors, empty states |
| **Caching** | TTL, invalidation on error, version in key |
| **Frontend static** | existing pattern: verify HTML/JS structure (three modes, loaders, folded sections, methodology modal) |
| **Regression** | all `tests/test_smart_*.py` (127) stay green |
| **Language** | AR/EN section titles and labels |

## 7. Implementation Order

1. Backend first (endpoints, caching, error handling) — the frontend depends on it.
2. Frontend rewrite (HTML + modular JS + CSS).
3. Quality pass (modularization, spelling, a11y, methodology) — interleaved with the rewrite.

## 8. Out of Scope

- Changing smart analytics algorithms (anomaly, clustering, XGBoost, etc.).
- New chart libraries.
- Changes to other screens' behavior.
- Database schema changes.

## 9. Success Criteria

1. Decision board loads fast and renders above the fold with a single lightweight request.
2. Three modes (monthly/time/hospital) work and reflect their filters in the UI.
3. Each analytic section loads independently with its own loader; a failing section does not break the page.
4. No duplicate network requests; charts lazy-render on visibility; timeline deferred.
5. All 127 existing smart tests pass; new endpoint/cache/empty-state tests pass.
6. Full AR/EN toggle; no spelling errors; single methodology source.
7. Modals accessible (dialog role, focus trap, Escape).