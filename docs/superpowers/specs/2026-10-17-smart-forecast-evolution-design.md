# Smart Forecast Screen — Evolution Design

**Date:** 2026-10-17
**Status:** Approved (brainstorming complete)
**Related:** `static/tabs/smart-forecast.html`, `static/js/smart-forecast.js`, `static/js/smart/advanced.js`, `app/api/smart_analytics.py`, `app/engine/smart/early_warning.py`, `app/engine/smart/xgboost_predictor.py`, `app/engine/smart/trajectory.py`, `app/engine/smart/tracking.py`, `app/engine/smart/indicator_forecast.py`, `docs/superpowers/specs/2026-08-19-smart-analytics-redesign-design.md`

## Goal

Evolve the standalone **Smart Forecast** tab (split out of Smart Analytics in commit `e4885b4`) from a single long page that fires every request on open into a fast, decision-oriented screen:

1. **Phase 1 — Speed & structure:** sub-tabs with on-demand loading; a working horizon control; a sticky context bar.
2. **Phase 2 — Decision support:** a ranked "action board" ranking hospitals/indicators by predicted risk for the chosen horizon, each with a recommendation and confidence.
3. **Phase 3 — Trust & explainability:** surfaced confidence intervals, a model card, and a backtesting panel.
4. **Phase 4 — Export & integration:** CSV/print/PDF export, copy-summary, and linkage of top risks to the Alerts screen.

The screen owns its own month and horizon; nothing is registered in core's shared section registry, so Smart Analytics interactions never refetch this screen.

## Approved Decisions (from clarification)

1. **Separate tab retained.** Forecasting stays its own top-level tab (already done). This design does not revisit the split.
3. **Organization:** sub-tabs (not accordion, not lazy-on-scroll), patterned after the existing advanced-tabs mechanism but namespaced to avoid collisions.
4. **Scope:** one design doc covering the full four-phase roadmap; implementation planned per phase, starting with Phase 1.
5. **Sub-tab mechanism (approach أ):** reuse the `data-*` + hidden-panel pattern but with **new, scoped attributes** (`data-forecast-tab`, `.smart-forecast-panel`) — the analytics `initAdvancedTabs` uses global selectors `.smart-tab-btn` and `[id$="-tab"]`, so reusing them would collide.
6. **Action board backend:** a new additive endpoint `GET /smart/forecast-action-board/{month}?horizon=` (Approach A) that composes from the cached smart envelope so recommendation/ranking logic lives in one testable place instead of being duplicated in JS.
7. **Test-borderline policy:** each phase is independently shippable; additive only; no DB schema changes; no engine methodology changes.

## Non-Functional Constraints

- **Additive / non-breaking:** existing endpoints keep their response shape; the new endpoint is new. Existing element IDs are preserved so current tests/renderers keep working.
- **No engine changes:** do not modify XGBoost, trajectory, tracking, or indicator-forecast algorithms. This work reads their outputs.
- **No DB changes:** no new tables/columns.
- **Bilingual (AR primary + EN):** every new string goes through `_t()` / i18n keys; server text stays AR with AR/EN where the payload already does.
- **Permission:** reuse `smart_analytics.read`; no new permission.
- **No unrelated lint fixes;** do not introduce new ruff/eslint errors in touched files.
- **Lazy + idempotent:** panel loaders must be safe to re-call (language toggle re-runs init) and must not repaint charts into a hidden panel.
- **Graceful degradation:** missing data → explicit empty state, never silent zero.

## Current State (baseline)

`smart-forecast.html` holds two stacked `.smart-section-card` blocks and a header. On open, `smart-forecast.js` runs `loadMonths()` + `loadHospitals()`, and `loadMonths()` triggers `loadXGBoostTab()` — which fetches `/smart/xgboost/{month}?horizon=` and `/smart/forecast-signals/{month}?horizon=` and calls `initIndicatorForecast()` — plus `loadHospitalForecast()`. The horizon select is wired in `advanced.js::initHorizonSelect()` to `loadXGBoostTab` only; accuracy/tracking/walk-forward/scatter all render inside `renderXGBoost()`.

Data already available from `/smart/xgboost/{month}?horizon=`:
- `xgboost.predictions[]`: `hospital_name, current_score, prediction|predicted_next_score, predicted_severity, risk_change, confidence, top_drivers[{feature, arabic_label, shap_value}]`
- `xgboost.model_r2, model_mae, training_months, hospitals_trained, accuracy_note, walk_forward[]`
- `forecast_accuracy`: `overall{mae, rmse, direction_hit_rate, n_predictions, interval{p10,p90}}`, `rows[]`
- `trajectory.trajectories[]`: `hospital_name, model, anchor_applied, confidence, points[{month,value,lower,upper}], threshold_crossing, backtest, note`
- `peer_percentile{}`, `forecast_tracking`

From `/smart/forecast-signals/{month}?horizon=`: `signals[]`, `targets[]`, `blended[]`, `relationships[]`, `note`.
From `/smart/indicator-forecast/{month}`: `hospitals[]` with `series/points/blended/peer_percentiles/confidence`.

## Phase 1 — Speed & Structure

### 1.1 Sub-tab skeleton
Add a sub-tab bar at the top of `#tab-smart-forecast` using a **new namespace**:

```html
<div class="smart-forecast-subtabs" role="tablist">
  <button class="smart-forecast-tab-btn" data-forecast-tab="actions"  data-i18n="Actions">الإجراءات</button>
  <button class="smart-forecast-tab-btn active" data-forecast-tab="models"   data-i18n="Forecasts">التنبؤات</button>
  <button class="smart-forecast-tab-btn" data-forecast-tab="quality"  data-i18n="Accuracy and validation">الدقة والتحقق</button>
  <button class="smart-forecast-tab-btn" data-forecast-tab="signals"  data-i18n="Signals">الإشارات</button>
  <button class="smart-forecast-tab-btn" data-forecast-tab="indicator" data-i18n="Indicator forecast">تنبؤ المؤشر</button>
  <button class="smart-forecast-tab-btn" data-forecast-tab="hospital" data-i18n="Hospital forecast">تنبؤ مستشفى</button>
</div>
```

Each panel is `div.smart-forecast-panel` with `id="forecast-panel-<name>"` and `data-forecast-panel="<name>"`. All panels start `style="display:none"` except `models` (active/default); the `actions` panel is **deferred to Phase 2** and is not rendered in Phase 1. Existing element IDs move **unchanged** into their panels:

| Panel | Moves in (existing element IDs) |
|---|---|
| `actions` (Phase 2) | *new* action board container `#smart-action-board` + model card `#smart-model-card` (deferred) |
| `models` | `#smart-xgboost-predictions`, `#smart-forecast-timeline` |
| `quality` | `#smart-forecast-accuracy`, `#smart-forecast-tracking`, `#smart-walk-forward`, `#smart-predicted-scatter`, *new* `#smart-backtest` |
| `signals` | `#smart-forecast-signals` |
| `indicator` | indicator controls + `#smart-indicator-forecast-output` |
| `hospital` | `#smart-forecast-hospital-select` + `#smart-hospital-forecast` |

The loader/error/empty placeholders for `xgboost` stay in the `models` panel; `hospital-forecast` placeholders stay in `hospital`.

### 1.2 Loader contract (`smart-forecast.js`)
- `_loaded = new Set()` + `_panelLoaders` (a `name → loader` map). `_loadForecastPanel(name)` is idempotent per panel: it marks the panel loaded and, for `models`, toggles the section loader around the fetch. Switching to an already-loaded panel is a no-op.
- Loader map: `models → loadXGBoostTab(month)` (predictions + timeline + indicator init), `quality → loadForecastQuality(month)` (accuracy + tracking + walk-forward + scatter), `signals → loadForecastSignalsPanel(month)`, `indicator → initIndicatorForecast()`, `hospital → loadHospitalForecast(hospitalId)`. The `actions` loader lands in Phase 2.
- **Reactivity rule:** `HORIZON_PANELS = {models, quality, signals, indicator}`. On month change every panel's `loaded` flag is cleared (`_resetPanels(() => true)`); on horizon change only `HORIZON_PANELS` are cleared. In both cases only the **currently active** panel reloads immediately; the rest reload on next activation. `getForecastMonth()`/`setForecastMonth()` keep the screen's anchor month in `advanced.js`.
- Tab clicks (`[data-forecast-tab]`) call `_activate(name)` → `_showPanel` + `_loadForecastPanel`. Charts are not repainted into a hidden panel (load only for the visible one).
- `initHorizonSelect()` (in `advanced.js`) no longer reloads xgboost itself; it dispatches `new CustomEvent('smart-forecast:horizon-change', {detail:{horizon}})`, and `smart-forecast.js` listens and calls `_resetPanels(...)`. `advanced.js` stays reusable by the (now separate) analytics screen.
- `initSmartForecast()` guards with `if (_initDone) return;`; a language toggle re-runs init and refreshes the indicator panel's labels. Turning `loadXGBoostTab` into a per-panel loader must not break `loadAdvancedSection` in `advanced.js` (which defaults to clusters — unchanged).

### 1.3 Sticky context bar
`.smart-context-bar` (currently the month/horizon bar) becomes `position: sticky; top: 0; z-index` within the tab, with a background matching the panel so content scrolls under it.

### 1.4 Acceptance
- Opening the tab fires only `/smart/months` + `/smart/hospitals`; no `/smart/xgboost` until the `models` panel activates.
- First activation of each panel fires exactly its requests; switching back to a loaded panel fires none.
- Changing the horizon refreshes the active panel and marks the others stale (they reload on next activation).
- Changing the month refreshes the active panel; `quality`/`hospital` reflect the new month.
- `npm run check` clean; `tests/test_smart_forecast_tab.py` extended to assert panel containers + `data-forecast-tab` wiring + that the lazy loader references each panel ID.

**Files:** `static/tabs/smart-forecast.html`, `static/js/smart-forecast.js`, `static/js/smart/advanced.js` (split render/loader, replace horizon handler with callback), `static/js/i18n.js` (new keys), `tests/test_smart_forecast_tab.py`.

## Phase 2 — Action Board

### 2.1 Endpoint
`GET /smart/forecast-action-board/{month}?horizon={1|3|6|9|12}` — permission `smart_analytics.read`; `@safe_endpoint(...)`; built from `_get_envelope_or_empty`/`_get_smart_data` (no engine run). `horizon` validated like existing endpoints (422 otherwise). Reuses `early_warning.compute_early_warning_signals`/`rank_forecast_targets` for the signals side and the cached `xgboost.predictions` for the model side.

### 2.2 Contract
```jsonc
{
  "month": "YYYY-MM",
  "horizon": 3,
  "items": [
    {
      "hospital": "…", "hospital_id": 1,
      "axis": "quality",                 // "quality" | indicator key | "cs_rate"
      "direction": "rising",             // rising | falling | stable
      "current": 0.41, "expected": 0.62,
      "lower": 0.50, "upper": 0.70,
      "risk_score": 0.81,                // 0..1 composite
      "severity": "critical",            // critical | warning | normal
      "confidence": 0.77,                // 0..1
      "source": "xgboost",               // xgboost | early_warning | blended
      "recommendation": "…",             // localized (AR) text
      "recommendation_key": "monitor_rising_indicator",
      "drilldown": { "month": "YYYY-MM", "hospital_id": 1 }
    }
  ],
  "note": "… statistical disclaimer …"
}
```

### 2.3 Ranking & recommendation
- `risk_score` = normalized composite of `severity_weight × confidence × trend_factor` (rising > stable > falling), clamped 0..1. Items sorted desc by `risk_score`, then by `severity`.
- Recommendation derivation is extracted into a **backend helper** that mirrors the current JS rule in `advanced.js::_recommendationFor` (top driver + rising high/critical → targeted action). The endpoint calls it; JS renders `recommendation` as-is. The existing predictions table keeps its JS path for now; Phase 3 may unify it to the server helper (noted, not required).
- Empty envelope → `{month, horizon, items: [], note}` (never silent zero).

### 2.4 UI
`#smart-action-board` at the top of the `actions` panel: ranked table (Hospital, Axis, Direction, Expected, Range, Risk, Severity badge, Confidence, Recommendation) with each row's hospital linking to the `hospital` panel via drilldown (sets `#smart-forecast-hospital-select` and switches panel).

### 2.5 Acceptance
- `tests/test_forecast_action_board.py`: shape, `horizon` validation (422), permission (401/403), empty-month handling, sorted desc by `risk_score`, `risk_score ∈ [0,1]`, `severity` ∈ allowed set, each item has `recommendation` + `drilldown`.
- Opening `actions` fires exactly one action-board request for the current month+horizon.

**Files:** `app/api/smart_analytics.py`, `app/engine/smart/early_warning.py` (export a reusable recommendation helper, additive), `static/js/smart-forecast.js`, `static/js/smart/advanced.js` (action-board renderer, or a new `static/js/smart/forecast-board.js` if `advanced.js` grows), `static/js/i18n.js`, `tests/test_forecast_action_board.py`.

## Phase 3 — Confidence & Explainability

### 3.1 Uncertainty surfacing
- Accuracy card (`renderForecastAccuracy`) promotes `overall.interval{p10,p90}` and `confidence` to a prominent band/badge (data already present).
- Forecast timeline already draws the P10–P90 band; add the interval/confidence to the panel header text.

### 3.2 Model card (`#smart-model-card`, `actions` panel)
Expand the existing `accuracy_note` block into a card: `R²`, `MAE`, `training_months`, `hospitals_trained`, last trained/evaluated month, and top aggregated SHAP factors (reuse `renderFeatureImportance` aggregation over `/smart/anomalies/{month}` `explanations[].top_factors`). Backend: expose `last_trained_month` on the xgboost payload **if** already computable from the cached envelope; otherwise omit (no engine change).

### 3.3 Backtesting panel
New `#smart-backtest` in the `quality` panel: a table of model error by **horizon** and by **indicator/fold**, from `trajectory[].backtest` and `forecast_tracking` (`month, n, mae, direction_hit_rate, severity_hit_rate`) plus `walk_forward[].r2/mae`. This is frontend-only over existing payloads.

### 3.4 Acceptance
- `tests/test_smart_forecast_tab.py` (or a new test) asserts the model card and backtest containers exist and are populated by the quality/actions loaders using existing payload keys.
- No new engine calls introduced; `npm run check` clean.

**Files:** `static/js/smart/advanced.js` (render), `static/js/smart-forecast.js` (wire), `static/tabs/smart-forecast.html`, `static/js/i18n.js`, `app/api/smart_analytics.py` (only if `last_trained_month` is trivially exposed).

## Phase 4 — Export & Integration

### 4.1 Export
- **CSV:** client-side builders for the action board, predictions, and accuracy rows (a small `toCsv(rows, columns)` helper in `smart-forecast.js` or a shared `charts.js` util), downloaded via Blob.
- **Copy summary:** build a plain-text summary of the action board + model card into the clipboard.
- **Print / PDF:** a print stylesheet that shows the active panel (or all loaded panels) without the chrome; browser "Print to PDF". No new backend.

### 4.2 Alerts integration
Each top action-board item gets a "view alerts" deep-link to the alerts screen filtered by hospital (reuse existing alerts deep-link/route). Automatic push of forecast items into alerts is **out of scope** for this phase (listed under future).

### 4.3 Acceptance
- Unit test for `toCsv` (escaping commas/quotes/newlines) and the summary builder in the JS test harness (or `npm run check` + a DOM-free assertion test).
- i18n keys for all new labels/buttons exist in AR + EN.

**Files:** `static/js/smart-forecast.js`, `static/tabs/smart-forecast.html`, `static/css/*` (print styles; locate the existing smart stylesheet), `static/js/i18n.js`, tests.

## Testing Strategy (all phases)

- **JS:** `npm run check` (syntax + import validation) after every change; extend `tests/test_smart_forecast_tab.py`.
- **API (Phase 2):** new `tests/test_forecast_action_board.py` (shape, permission, horizon validation, ordering monotonicity, empty).
- **Regression killers:** existing `tests/test_smart_core_js.py` forecast assertions (repointed to `smart-forecast.*`) must stay green; `tests/test_menu_api.py::test_list_tabs` (18 tabs, `smart-forecast` present) must stay green; `tests/test_lag_analysis.py` unchanged.
- **Known environment failure:** `tests/test_deploy_cloudrun_supabase.py::test_script_is_valid_bash` fails on Windows (no `bash`) — pre-existing, unrelated.
- Full suite exceeds a single tool call (~65 min); run the affected files per phase and record results.

## Rollout / Shippability

Each phase ships independently:
- Phase 1: UI-only refactor, no API change.
- Phase 2: additive endpoint + UI.
- Phase 3: mostly frontend over existing payloads.
- Phase 4: client-side export + deep-links.

Each phase: `npm run check` + affected pytest files green; commit separately with a conventional message. No DB migration, no engine change, no permission change.

## Non-Goals

- No change to XGBoost / trajectory / tracking / indicator-forecast methodology or the statistical disclaimer.
- No new DB tables/columns.
- No moving recommendation logic into the frontend (Phase 2 moves it server-side instead).
- No automatic forecast→alerts push (future).
- No removal of the existing `/smart/xgboost/{month}` or `/smart/forecast-signals/{month}` contracts.

## Open Questions (future, not blocking)

- Whether `/smart/xgboost` should accept an `indicator` dimension for per-indicator model predictions (currently the model predicts the composite quality/anomaly score; per-indicator forecasting is the separate `/smart/indicator-forecast` path).
- Whether the action board should unify `quality` and per-indicator rows under one severity scale.
- Automatic alerting when an action-board item crosses `critical`.
