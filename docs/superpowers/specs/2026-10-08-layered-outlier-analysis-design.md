# Layered Outlier Analysis — Design

Date: 2026-10-08
Status: Approved (design sections reviewed in chat)
Scope: Multi-layer outlier detection, classification, and explainability for the DHIS / Health-AI Data Quality System.

## 1. Goal

Replace single-shot peer z-score outlier detection with a layered, sequential analysis pipeline:

```
DATA ELEMENTS → RAW VALUE ANALYSIS → NUMERATOR/DENOMINATOR → RATE ANALYSIS
→ HOSPITAL HISTORICAL ANALYSIS → VOLUME/DENOMINATOR ANALYSIS → PEER COMPARISON
→ CLINICAL/CONTEXTUAL INTERPRETATION → OUTLIER CLASSIFICATION
→ {DATA QUALITY INVESTIGATION | CLINICAL INVESTIGATION} → AI EXPLANATION → DASHBOARD
```

Core principles:

- An outlier is a **Signal for Investigation**, never proof of a data error.
- Always start with "What happened to this data element in this hospital?" — never with hospital-vs-hospital comparison.
- Raw Count Outliers and Rate Outliers are distinct results and must not be merged into a single value.
- Detection → Interpretation → Investigation. Classification must not change the Data Quality Score.
- Minimal change to the existing system: `anomaly_results`, `quality_scores`, and `hospital_indicator_config` behavior stay as they are.

## 2. Decisions (confirmed with user)

| # | Question | Decision |
|---|---|---|
| Q1 | Storage | **New table** `layered_outlier_results`; `anomaly_results` untouched |
| Q2 | Rate/indicator config | **Single central config**; migrate all 4 existing hardcoded rate-definition sites to it |
| Q3 | Quality score | **Unchanged** — outlier penalty still comes only from existing `anomaly_results` |
| Q4 | UI surface | **Both** — classification column in existing Outliers tab **and** a new Layered Analysis tab |
| Q5 | Compute timing | **Persisted in `_compute_full_analysis`** alongside `anomaly_results` |

## 3. Data Model

### 3.1 New table `layered_outlier_results`

One row per hospital × **analysis unit** × month. Unique constraint `(hospital_id, analysis_code, month)`.
Indexes: `(hospital_id, month)`, `(month, outlier_type)`.

**Amendment (2026-10-08, approved):** rates (`rate_cs`, …) are not rows in `indicators` — only data elements are. The row key is therefore `analysis_code` (String): the data-element code for count rows, or the synthetic rate code for rate rows. `indicator_id` becomes a nullable FK (set for count rows; for rate rows it points at the numerator indicator when resolvable, else `NULL`).

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `hospital_id` | FK hospitals | |
| `indicator_id` | FK indicators **nullable** | count rows: the data element; rate rows: numerator indicator or `NULL` |
| `analysis_code` | String, indexed | data-element code or synthetic rate code — the row's analysis unit |
| `month` | String `YYYY-MM` | |
| `raw_value` | Float nullable | data element value for the month |
| `previous_value` | Float nullable | prior month value |
| `numerator` | Float nullable | per formula; `NULL` for count indicators |
| `denominator` | Float nullable | |
| `rate` | Float nullable | `num/den × rate_multiplier`; `NULL` for count indicators |
| `previous_denominator` | Float nullable | |
| `denominator_change_percent` | Float nullable | |
| `historical_mean` | Float nullable | rolling baseline (window per config) |
| `historical_median` | Float nullable | |
| `historical_std` | Float nullable | |
| `historical_z_score` | Float nullable | |
| `historical_change_percent` | Float nullable | |
| `raw_value_outlier_score` | Float nullable | 0–1 severity; `NULL` = layer not applicable/not computable |
| `rate_outlier_score` | Float nullable | |
| `historical_outlier_score` | Float nullable | |
| `volume_anomaly_score` | Float nullable | |
| `peer_outlier_score` | Float nullable | |
| `peer_mean` | Float nullable | |
| `peer_count` | Int nullable | |
| `outlier_level` | String | `NONE / LOW / MODERATE / HIGH / VERY_HIGH` |
| `outlier_type` | String | classification enum (below) |
| `outlier_method` | String | method that fired: `zscore / iqr / rolling_median_mad / pct_change / trend_deviation / peer_zscore / insufficient_history` |
| `interpretation` | Text | human-readable explanation composed from actual numbers |
| `investigation_required` | Boolean | |
| `investigation_route` | String | `data_quality / clinical / contextual / none` |
| `created_at` | DateTime | |

Classification enum (`outlier_type`):

```
NORMAL
RAW_VALUE_ANOMALY
RATE_ANOMALY
HISTORICAL_ANOMALY
VOLUME_DRIVEN_ANOMALY
PEER_ANOMALY
POSSIBLE_DATA_ENTRY_ERROR
CLINICAL_INVESTIGATION_REQUIRED
```

### 3.2 `Indicator` table additions — count / raw-layer config

**Amendment:** numerator/denominator/multiplier moved to the `rate_config` table (§3.3) because rates have no `indicators` row. The `Indicator` table carries only raw/count-layer settings:

| Column | Type | Default |
|---|---|---|
| `indicator_type` | String | `count` — one of `count / rate / ratio / percentage` (rate* rows leave it `count`; rate semantics live in `rate_config`) |
| `minimum_history_period` | Int | `3` |
| `outlier_method` | String | `auto` — one of `auto / zscore / iqr / rolling_median_mad / pct_change / trend_deviation` |
| `historical_enabled` | Boolean | `True` |
| `peer_comparison_enabled` | Boolean | `True` |

`hospital_indicator_config` is **not** extended.

### 3.3 New table `rate_config` — rate definitions & rate-layer config

One row per rate spec. Unique `(rate_code)`.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `rate_code` | String unique | synthetic code (`rate_cs`, `rate_mmr`, …) used as `analysis_code` for rate rows |
| `rate_name` | String | display name (matches current `RATE_DEFINITIONS` names where applicable) |
| `indicator_type` | String | `rate / ratio / percentage` |
| `numerator_codes` | JSON list | e.g. `["5"]` |
| `denominator_codes` | JSON list | e.g. `["2"]` |
| `rate_multiplier` | Int | `100 / 1000 / 100000 / 1` |
| `minimum_denominator` | Int nullable | `NULL` (no behavior change until tuned) |
| `minimum_history_period` | Int default `3` | |
| `outlier_method` | String default `auto` | |
| `historical_enabled` | Boolean default `True` | |
| `peer_comparison_enabled` | Boolean default `True` | |
| `is_active` | Boolean default `True` | |

Seed from current definitions (§4).

### 3.4 Migration mechanics

- One alembic revision adding `layered_outlier_results`, `rate_config`, and the `Indicator` columns (follow existing idempotent patterns in `alembic/versions/`; current head `a9c8e7d6f5b4`).
- Register new `Indicator` columns in `app/main.py::_ensure_required_columns` self-heal.
- Seed `rate_config` rows in `scripts/seed_indicators.py` (idempotent, insert-if-missing).

## 4. Central Rate Config (`app/engine/rate_config.py`)

**Amendment (2026-10-08, approved):** the four existing sites *disagree* today (MMR denominator `2` vs `6`; stillbirth `2` vs `6`; multipliers ×1 / ×100 / ×1000). A single canonical value per conceptual rate would silently change behavior. The central config therefore guarantees a single **mechanism and location**, not a forced single value:

- `RateSpec` dataclass: `spec_key, site, rate_code, rate_name, indicator_code, indicator_type, numerator_codes (JSON), denominator_codes (JSON), rate_multiplier, unit, typical_pct, minimum_denominator, minimum_history_period, outlier_method, historical_enabled, peer_comparison_enabled`.
- `BUILTIN_RATE_SPECS: Dict[str, RateSpec]` — a **Python registry holding every spec from all 4 sites with its exact current values**, keyed per site where they disagree: `"zscore:C-section rate"`, `"clinical:rate_cs"`, `"forecast:cs_rate"`, `"rules:R043"`, … Zero numeric drift by construction; the disagreements become visible side-by-side and can be reconciled in a later, separate task.
- `load_rate_specs(db)` — returns the layered engine's spec set: **DB `rate_config` rows (runtime tunables) merged over the builtin zscore-slice defaults**; falls back entirely to builtin when the table is empty (pre-seed operation). In-process cache, invalidated on `rate_config` save.
- `get_spec(db, rate_code)` — single spec lookup for the layered engine.
- `compute_rate(spec, values)` — the one rate computation: sums `numerator_codes`, sums `denominator_codes`, applies `rate_multiplier`; returns `None` on missing/zero denominator. Replaces the ×100 hardcode in `zscore.compute_rate`.

### 4.1 Migration of the 4 existing hardcoded sites

| Site | Change |
|---|---|
| `app/engine/anomaly/zscore.py:37` `RATE_DEFINITIONS` | becomes a view over the registry's `"zscore:*"` slice, preserving the tuple shape `(rate_name, numerator_code, denominator_code, typical_pct)` so `explain.py` and existing tests keep working |
| `app/engine/clinical/thresholds.py` `ClinicalThreshold` | definitions constructed from the registry's `"clinical:*"` slice (ranges/guidelines stay in this module); `compute_rate` uses `rate_multiplier` instead of the `"% in unit"` test |
| `app/engine/smart/indicator_forecast.py:48` `INDICATOR_DEFS` *(the spec originally called this `RATE_SPECS`; no such symbol exists)* | dict built from the registry's `"forecast:*"` slice; `denominator: None` maps to count-type |
| `app/engine/quality/rules.py` R043–R050 | iterate the registry's `"rules:*"` slice instead of the hardcoded list |

### 4.2 Numeric parity guard

Parity is guaranteed structurally (registry = verbatim current values) and enforced by tests:

- Unit parity: for each site, old-vs-new outputs identical for all its rates across representative inputs (including the ×1 / ×100 / ×1000 cases and the disagreeing denominators).
- Seed parity: `rate_config` rows seeded from the `"zscore:*"` slice; test asserts DB seed == registry values.
- `rate_config.rate_multiplier` seeds as `100` for the 7 zscore rates.

## 5. Layered Engine (`app/engine/anomaly/layered.py`)

Pure functions; no DB writes (orchestrator persists).

Entry point:

```
analyze_layered_entry(spec, history, current_month, peer_rates, thresholds)
    -> LayerResult
```

`history` = prior months of the same hospital's numerator/denominator/value for this indicator.

### Layer 1 — Raw value

- Requires ≥ `minimum_history_period` (default 3) prior months of the same hospital's raw value for the indicator.
- Method selection (config `outlier_method`, or `auto`):
  - `auto`: `pct_change` if history ≥ 3 and CV < 0.5; `iqr` if ≥ 6 points; `zscore` fallback.
  - Rare-event indicators (`indicator_type=count` with low mean, e.g. maternal/neonatal/stillbirth) → **rolling median + MAD**, never plain z on small counts.
- Output: `raw_value_outlier_score` (0–1, scaled from the method's deviation), `historical_change_percent`, `outlier_method`.
- Severity bands: NONE / LOW / MODERATE / HIGH / VERY_HIGH.

### Layer 2 — Rate

- `rate = numerator / denominator × rate_multiplier`, only when `denominator_codes` is present.
- Scored against the hospital's **own historical rates** using the same method-selection logic as Layer 1.
- Output: `rate`, `rate_outlier_score`.
- Skipped entirely (`NULL`) for count indicators.

### Layer 3 — Historical baseline

- Rolling window stats: previous month, 3/6/12-month mean, median, IQR, std, z-score, % change.
- Trend slope (Theil-Sen) when ≥ 6 points.
- `trend_deviation` method: deviation of the current value from the linear projection (scaled by residual std) is scored and blended into `historical_outlier_score` when ≥ 6 points exist; otherwise the window-stat z/pct-change score is used.
- Output: `historical_mean`, `historical_median`, `historical_std`, `historical_z_score`, `historical_change_percent`, `historical_outlier_score`.
- Baseline series: rate history if the indicator has a rate; otherwise raw-value history.

### Layer 4 — Volume / denominator

- `previous_denominator`, `denominator_change_percent`, `volume_anomaly_score` (severity of denominator shift).
- Interpretation rule: raw score HIGH + volume score HIGH + rate score ≤ MODERATE → volume-driven.
- Missing or zero denominator → layer `NULL`; all rate-dependent layers marked **not computable** (never treated as normal, never treated as an outlier).

### Layer 5 — Peer comparison

- Reuses current peer logic: mean of *other* active hospitals, `ddof=1`, threshold from existing `AppConfig zscore_threshold` (default 2.5).
- Runs **after** the history layers (never first).
- Peer tier fallback (first tier with ≥ 2 members wins):
  1. Same hospital type → 2. Ownership → 3. Governorate → 4. All active hospitals.
- Insufficient peers in every tier → `peer_outlier_score = NULL`, `peer_count = 0`; peer layer marked unavailable — never force an outlier from no peers.

### Small-denominator guard

- `denominator < minimum_denominator` (when configured): rate score's confidence is lowered (recorded in `interpretation`), and the classification's `outlier_level` is capped at `LOW` for rate-based types. Data is never deleted or hidden.

### Severity bands (defaults)

Every layer produces a 0–1 score which maps to levels with these default cutoffs (module constants, unit-tested):

| Score | Level |
|---|---|
| < 0.25 | NONE |
| < 0.50 | LOW |
| < 0.75 | MODERATE |
| < 0.90 | HIGH |
| ≥ 0.90 | VERY_HIGH |

Score construction per method:

- z-based methods: `score = min(1, |z| / (2 × threshold))` — so `|z| = threshold` ⇒ 0.5 (MODERATE), `|z| = 2×threshold` ⇒ 1.0.
- IQR: `score = min(1, tukey_fence_distance / (2 × IQR))` (0 when inside fences).
- Percentage change: `score = min(1, |pct_change| / 100%)` — 100% change ⇒ 1.0.
- Rolling median + MAD (rare events): `score = min(1, |value − median| / (3 × 1.4826 × MAD))`; zero MAD ⇒ score 1.0 only if value ≠ median, else 0.
- Trend deviation: `score = min(1, |actual − projected| / (2 × residual_std))`.
- Peer: same z construction as z-based, using the peer distribution.

### Thresholds

- Peer z threshold: existing `AppConfig zscore_threshold` (2.5) — one shared knob; the band formula above derives layer severities from it.
- Method-selection thresholds (CV < 0.5, minimum points) are constants in the module.
- No new threshold knobs in this iteration beyond what the Indicator config already carries.

## 6. Classification (`app/engine/anomaly/classify.py`)

Deterministic priority rule table over layer outputs — no single-rule classification.

Inputs: `raw_score, rate_score, hist_score, volume_score, peer_score, den_ok, history_ok, spec`.

First match wins:

| # | Condition | Classification |
|---|---|---|
| 1 | `history_ok = false` (insufficient baseline / first month) | `NORMAL`, `outlier_level = NONE`, method `insufficient_history` |
| 2 | `raw ≥ HIGH` and `rate ≥ HIGH` and `hist ≥ HIGH` and `volume ≤ LOW` | `POSSIBLE_DATA_ENTRY_ERROR` (Scenario A) |
| 3 | `raw ≥ HIGH` and `volume ≥ HIGH` and `rate ≤ MODERATE` | `VOLUME_DRIVEN_ANOMALY` (Scenario B) |
| 4 | `rate ≥ HIGH` and `hist ≥ HIGH` and `volume ≤ LOW` | `CLINICAL_INVESTIGATION_REQUIRED` (Scenario C) |
| 5 | `hist ≥ HIGH` alone | `HISTORICAL_ANOMALY` |
| 6 | `peer ≥ HIGH` and `hist ≤ LOW` | `PEER_ANOMALY` — interpretation "consistently differs from peers; review case mix, referral pattern, and indicator definition" — **never** "data error" (Scenario D) |
| 7 | `peer ≥ HIGH` and `hist ≥ MODERATE` | `PEER_ANOMALY` flagged *combined*; both deviations stated in interpretation |
| 8 | `raw ≥ MODERATE` and no other layer ≥ HIGH | `RAW_VALUE_ANOMALY` |
| 9 | `rate ≥ MODERATE` and no other layer ≥ HIGH | `RATE_ANOMALY` |
| 10 | otherwise | `NORMAL` |

Additional outputs:

- `investigation_required = true` for rules 2, 4, 6, 7.
- `investigation_route`: `data_quality` (rule 2), `clinical` (rules 4), `contextual` (rules 5, 6, 7, 8, 9), `none` (rules 1, 10).
- `outlier_level` = max applicable layer level, capped by the small-denominator guard.
- `interpretation` composed by a pure `build_interpretation(...)` function from actual numbers (e.g. "+125% above baseline; admissions +117%; rate +24%; peer average 12.1"). Testable by content assertion.

Classification is Detection → Interpretation → Investigation only. **It never modifies the Data Quality Score.**

## 7. Pipeline Integration

In `app/engine/pipeline.py::_compute_full_analysis` (after `get_all_hospital_data_for_month` + historical fetch, alongside the existing anomaly step):

1. Build spec list from `rate_config.load_rate_specs()`.
2. Gather peer rates for the month (already fetched for `detect_anomalies`).
3. Run the layered orchestrator.
4. Persist via `_save_layered_results` — same delete-for-hospital+month → insert → commit pattern as `_save_anomaly_results` (pipeline.py:658).

Existing `detect_anomalies` / `detect_monthly_trend` / dedup runs **unchanged** → `anomaly_results` and the quality penalty are untouched (Q3).

Lifecycle parity with `anomaly_results`:

- `reanalyze-all`, `purge_derived_results`, `recompute_hospital_months` include the new table.
- Cache: new key namespace `analysis:layered_v1`; outliers endpoint join piggybacks on the existing `analysis:outliers_v3` key.

## 8. API

Additions to `app/api/analysis.py` (permission `analysis.read`, same as existing):

1. `GET /analysis/layered?month=&hospital=&indicator=&classification=&level=&page=&page_size=` — paged persisted rows + spec metadata (indicator name/type); server-side sort; active hospitals only (mirrors `GET /analysis/outliers` at analysis.py:353).
2. `GET /analysis/layered/summary?month=` — counts per classification and per-hospital rollup (tab header chips).
3. `GET /analysis/outliers` gains `layered_type` / `layered_level` via LEFT JOIN on the new table — powers the classification column with no second request.
4. Explain: extend the `app/engine/audit/explain.py` dispatcher with `kind=layered_outlier` → `explain_layered_outlier()`, returning the §9 payload using the existing `what/where/why/how/reproduce/chain/classification` contract so `explain.js` renders it without a new client framework.

## 9. Explainability Payload (Why popup)

`explain_layered_outlier()` returns:

- Current value, historical baseline (6-month average), previous month, absolute + percentage change.
- Current denominator, previous denominator, denominator change %.
- Current rate, historical rate, peer rate, rate change %.
- Deviation values for each layer, detection method(s), the classification rule chain that fired.
- Conclusion paragraph (the `interpretation` text).
- Reproduce section: all inputs needed to recompute every number (full precision), mirroring the existing anomaly explain behavior.

Dashboard block (Outliers tab badge tooltip + Layered tab Why):

```
Mortality Rate            25 / 1000
⚠ Historical Increase     ↑ 125% above hospital baseline
Patient Volume            ↑ 122%
Peer Comparison           Within peer range
Interpretation            The increase in mortality count coincides with a major
                          increase in admissions. The rate has increased
                          moderately. This is not sufficient evidence of a
                          data-entry error.
```

## 10. UI

### A. Outliers tab (extend)

- `static/tabs/outliers.html` + `static/js/outliers.js`: new **Classification** column from `layered_type` — colored badge per type (`POSSIBLE_DATA_ENTRY_ERROR` red, `CLINICAL_INVESTIGATION_REQUIRED` orange, `PEER_ANOMALY` blue, `VOLUME_DRIVEN_ANOMALY` amber, `NORMAL`/unmatched gray) with `title` tooltip = one-line interpretation.
- Existing Z-badge, peers popover, Why button unchanged.

### B. New Layered Analysis tab

- `static/tabs/layered.html` + `static/js/layered.js`, following the `outliers.js` idiom (same table/sort/filter/export structure).
- Filters: month, hospital, indicator, classification, level.
- Summary chips per classification (from `/analysis/layered/summary`).
- Columns: Hospital, Month, Indicator, Raw value (Δ%), Rate (Δ%), Denominator (Δ%), Peer, Level, Classification, Why.
- Why → `showWhyPopup('layered', ...)` reusing the existing modal.
- Tab registered in the tab bar; i18n keys added to `static/js/i18n.js` (en + ar), mirroring existing outlier keys.
- Classification badges support filtering the tab by `investigation_route` (data-quality vs clinical) — no new page.

## 11. Tests

### `tests/test_layered_engine.py` — required scenarios

| # | Scenario | Asserts |
|---|---|---|
| 1 | Normal historical value | all scores low, `NORMAL` |
| 2 | Raw value outlier (10→25) | `raw_value_outlier_score` HIGH, method recorded |
| 3 | Rate outlier, stable denominator | `rate_outlier_score` HIGH |
| 4 | High numerator + high denominator (10→25 / 900→2000) | `VOLUME_DRIVEN_ANOMALY`, interpretation mentions volume |
| 5 | High numerator + stable denominator (10→25 / 900→1000) | `CLINICAL_INVESTIGATION_REQUIRED` |
| 6 | Small denominator (2/5) | confidence lowered, level capped LOW, row kept |
| 7 | Historical outlier, normal peer comparison | `HISTORICAL_ANOMALY`, peer score low |
| 8 | Normal historical trend, peer outlier | `PEER_ANOMALY`, interpretation = differs from peers, never "data error" |
| 9 | Missing denominator | rate layers `NULL`, not computable; no false NORMAL/outlier |
| 10 | Zero denominator | same as 9, no division by zero |
| 11 | Missing historical data | `insufficient_history`, `NORMAL` |
| 12 | First month with no baseline | same as 11 |
| 13 | Rare-event indicator | rolling median + MAD path, plain z not applied |
| 14 | Current-month filtering | API returns only the requested month |
| 15 | Hospital filtering | API returns only the requested hospital |
| 16 | Peer fallback | tier order type → ownership → governorate → all; <2 everywhere → `peer_score NULL` |

### Additional suites

- `tests/test_rate_config.py` — parity test: all 7 current rates produce identical results old vs new; seeding defaults; spec fallback behavior.
- `tests/test_layered_api.py` — endpoints, permissions, summary chips, outliers join, explain payload contract, 404s.
- `tests/test_layered_pipeline.py` — persistence, reanalyze backfill, purge/recompute lifecycle, cache invalidation.
- `tests/test_layered_ui.py` — classification column, tab registration, Why popup wiring (mirrors `test_outliers_js.py`).

### Regression

Entire existing suite must pass unchanged — especially `test_anomaly.py`, `test_quality_score.py`, `test_explain*.py`, `test_pipeline.py`, `test_outliers_js.py`, `test_migrations.py`, `test_migration_guard.py`.

Runner: `pytest` (per `pyproject.toml`).

## 12. Explicit Non-Goals

- No change to `QualityScore` computation or the `outlier_penalty` weight (Q3). Gating the penalty on classification is a possible future task, not this one.
- No change to `hospital_indicator_config` semantics.
- No rewrite of `zscore.py` peer detection or `trends.py` — they continue to produce `anomaly_results` exactly as today.
- No removal or hiding of data under any classification.
- No new threshold knobs beyond `zscore_threshold` and the config fields in §3.2/§3.3.
- `minimum_denominator` seeds as `NULL` (no behavior change) until the user tunes it.
