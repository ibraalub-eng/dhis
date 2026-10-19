# Quality section — indicator centralization audit (2026-10-19)

Scope: every screen, sub-tab, API endpoint, export and background task reachable
from the application's Quality section. Navigation was read from
`app/menu_registry.py`, `static/js/renderSidebar.js`, `static/index.html` and
`static/js/app.js`; each tab was traced to its JS module and API endpoint.

The Quality section is a single top-level tab, **Quality Reports**
(`tab-quality`, permission `quality.read`, group *Oversight*), backed by
`static/tabs/quality.html` + the quality-report block of `static/js/upload.js`.
Its sub-tabs are rendered inside the report-detail modal.

## 1. Inventory

| # | Tab / component | Indicators & rates displayed | Current source | Formula/multiplier hardcoded? | Raw data processed directly? | Required change | Test coverage / status |
|---|---|---|---|---|---|---|---|
| 1 | Report grid (`#reportsGrid`, `filterQualityReports`) | Data Quality Score, issues count, outlier count, disabled-month note | `GET /reports/` → stored `QualityScore` + stored `AnomalyResult` (outlier rows) | No clinical math. Score is the statistical composite from `engine/quality/scoring.py` (allowed, non-clinical) | No; reads stored results | None for formulas; keep score source single (`combine_quality_score`) | `test_quality_single_source.py`, `test_ui_quality_reports.py` — pass |
| 2 | Detail header (`renderDetail`) | Score + 4 score components, issue list, confidence | `GET /reports/detail/{hospital_id}?month=` → stored `QualityScore`/`ValidationResult`/`AnomalyResult` | No; components are statistical | No | None | `test_quality_single_source.py` — pass |
| 2a | Sub-tab **Validation Results** (`rerenderVal`) | Rule code/description/status/severity/type/details | Stored `ValidationResult` rows produced by `engine/quality/rules.py` | No clinical rates remain: R041–R050 benchmark-rate rules were removed; `load_rules_from_db`/`dispatch_rule` reject legacy BENCHMARK rows | Rules validate raw elements only (sum/inequality/trend checks) | Benchmark-rate rules must stay out of the rule catalogue and DB loader | `test_rate_config.py::test_quality_validation_has_no_benchmark_rules` — pass |
| 2b | Sub-tab **Anomaly Detection** (`rerenderAnom`) | C-section rate, MMR, NMR, preterm, SMM, stillbirth, NICU + user-managed shared definitions; value, peer benchmark, z-score, peer count/range, outlier flag | `engine/anomaly/zscore.py` → `indicator_service` → `indicator_calc` using registry definitions (`IndicatorDefinition`, `source_site` zscore/shared); values persisted on `AnomalyResult` with `indicator_id`, `formula`, `formula_version` | **Before:** rate list + `*100` multiplier hardcoded in `zscore.py`; benchmark rules duplicated formulas in `quality/rules.py`. **Now:** rate specs come from `engine/rate_config.py` and the seeded registry definitions; one ratio evaluator in `indicator_calc` | No: indicators are derived from raw `IndicatorValue` rows by the engine | Add unit from registry metadata; add formula-freshness (`current` / `stale` / `unverified` / `unregistered`) so a stored value is never presented as current after a registry edit | New `test_quality_indicators_centralized.py` |
| 2c | Sub-tab **Completeness** (`loadQrCompleteness`) | Completeness %, causes, missing indicators | `GET /dashboard/component-diagnostics` | No clinical rate; completeness formula lives in `engine/quality/scoring.compute_completeness` | Reads stored indicator values through the diagnostic API | None | `test_completeness_core.py`, `test_completeness_parity.py` — pass |
| 3 | PDF export (`/reports/export/{id}/pdf`) | Score + components, issues, validation rows, anomaly rates | `_get_export_data` → `run_full_analysis` + stored rows | No formula; but a missing score was defaulted to `0` | No | Show `--` for missing score; add Unit and Formula-status columns to the anomaly table | New test asserts no score fallback |
| 4 | Excel export (`/reports/export/{id}/xlsx`) | Same as PDF | Same | No formula | No | Add Unit and Formula-status columns | New test |
| 5 | Background generation (`POST /reports/generate/{id}`, `GET /reports/generate/{id}`) | Recomputes the full report | `engine/pipeline.run_full_analysis` → validation, anomalies, quality score | No formula in the API; all math inside the engine | Yes, the engine reads raw `IndicatorValue` rows — correct owner | None | `test_pipeline.py` — pass |
| 6 | Report list cache | Cached `ReportOut` list | `app/cache` key `reports:list_v2` | No | No | Registry edits already invalidate `reports:` + `analysis:` caches (`indicator_definitions._invalidate_indicator_consumers`) | `test_cache.py` — pass |
| 7 | Quality engine (`app/engine/quality/`) | Quality score, rule compliance, completeness, consistency, outlier penalty | Rule engine + `scoring.py` | Generic statistical/validation arithmetic only (`*100` for 0–1 → 0–100; `(cur-prev)/prev*100` for trend rules) | Receives raw values from the pipeline | Retain: not clinical indicators, and the single scoring source is required by design | `test_quality_score.py`, `test_quality_single_source.py` — pass |

## 2. Hardcoded formulas found

### Removed by the centralization work already in this working tree

* `app/engine/quality/rules.py` — `_rate()`, `_benchmark_rate()`, `_rate_low()`,
  `_cross_hospital_rate()` and rules **R041–R050** computed
  `(numerator / denominator) * 100` directly from indicator codes, duplicating
  the rates already defined in `rate_config`/the registry.
  Removed; the rule catalogue, `RULE_REF_CODES`, `dispatch_rule` and
  `load_rules_from_db` no longer accept BENCHMARK rate rules.
* `app/engine/quality/definitions.py` — `cs_rate_threshold`,
  `nvd_rate_threshold`, `zscore_threshold` and the R041–R050 catalogue entries
  were the settings behind those duplicated rates. Removed.
* `app/engine/rate_config.py` — the `rules` site (R043–R050 numerator/
  denominator literals) was a fourth copy of the same clinical rates. Removed.

### Remaining findings and dispositions

| Finding | Location | Disposition |
|---|---|---|
| `multiplier = spec.rate_multiplier if spec else 100.0` | `engine/anomaly/zscore.py::compute_rate` | **Justified exception.** Only reached when no registry spec matches; the Quality path always passes a resolved registry indicator (`indicator_service`), so this fallback is never used for a Quality display. It is retained because other legacy callers/tests rely on the historical x100 contract. |
| `(cur - prev) / prev * 100` | `engine/quality/rules.py` (`_month_over`, `_month_under`) | **Legitimate generic arithmetic.** Month-over-month data-quality guard on raw counts, not a clinical rate. |
| `* 100` on 0–1 components | `engine/quality/scoring.py` | **Legitimate.** Converts statistical score components to the stored 0–100 scale. |
| `score = r.get("data_quality_score", 0)` in the PDF export | `app/api/reports.py` | **Removed.** A missing score now renders as `--`, never `0`. |
| Anomaly value/benchmark rendered without unit | `static/js/upload.js`, PDF/Excel exports | **Fixed.** Unit comes from the registry definition; values render as `12.34%` / `12.34 per 1,000`. |
| Stored anomaly shown without version check | `static/js/upload.js` + `/reports/detail` | **Fixed.** Each row carries `formula_status` (`current`/`stale`/`unverified`/`unregistered`) and the current formula version. |

## 3. Separation of responsibilities (verified)

* **Data Tree** — raw `Indicator` elements only; the Quality tab does not create
  or rename them.
* **Indicators Registry** — `IndicatorDefinition` rows (versioned); the
  Quality anomaly candidates are resolved from this registry (`resolve_active_definitions`).
* **Calculation engine** — `indicator_calc` / `indicator_service`; one ratio
  evaluator, zero-denominator and missing-value semantics in one place.
* **Quality tabs** — presentation only: they read `/reports/` and
  `/reports/detail/` and never compute a clinical rate client-side.
* **Validation rules** — raw-element consistency only; no rate rules.
* **Outlier analysis** — statistical z-score/trend algorithms on top of the
  centralized indicator values.

## 4. Remediation delivered

1. `indicator_service.resolve_ref()` / `registry_provenance()` resolve a stored
   `indicator_id` back to the live registry row and compare stored vs current
   formula version.
2. `/reports/detail` attaches `unit`, `formula_status` and
   `current_formula_version` to every anomaly row.
3. PDF/Excel exports carry the same unit and status.
4. The Quality Reports anomaly table shows the value/benchmark with units,
   an explicit *unavailable* state when a value is null, and a stale/unverified
   badge instead of silently presenting an outdated value as current.
5. PDF no longer substitutes `0` for a missing quality score.
6. Fixed two leftover regressions in the shared anomaly path uncovered while
   auditing the Quality dependencies:
   - `engine/anomaly/trends.py` referenced an undefined `num_code` when building
     `TrendResult` (NameError); it now uses the resolved indicator code.
   - `engine/audit/benchmark.py` re-added migrated **system** definitions from
     every site, duplicating zscore rates under a second name/unit. Shared
     user-managed definitions are still included; system definitions are not
     double-counted.
7. Tests in `tests/test_quality_indicators_centralized.py` cover the registry
   path, cross-tab consistency, formula-version staleness, zero denominators,
   missing values and the static "no hardcoded clinical formula in Quality"
   guard, plus real PDF/Excel export checks.

## 5. Verification

| Command | Result |
|---|---|
| `pytest tests/test_quality_indicators_centralized.py tests/test_ui_quality_reports.py` | **21 passed** (18 new + 3 existing UI) |
| Focused suite: quality single-source/score, central consumers, rate config, export, pipeline, benchmark, anomaly, regional, menu, indicator-definition migration, layered schema, terminology, smart-core JS, explain-comparative | **315 passed, 1 skipped** |
| `pytest tests/test_api.py tests/test_layered_api.py tests/test_layered_engine.py tests/test_layered_ui.py tests/test_cross_tenant_scope.py tests/test_indicator_definitions_api.py` | **181 passed** |
| `npm run check` (`check:js` + `check:imports`) | 37 files pass syntax + import validation |

A full-suite run on the initial audit snapshot reported 17 failures. After the
fixes above, every failing file was rerun green except the three
`test_clinical.py` classification cases listed below.

### Remaining failures and justifications

* **Resolved 2026-10-19 (same day, after this audit was written)** — the 3 ×
  `test_clinical.py::TestClinicalIndicatorRegression` cases (MMR/NMR/stillbirth
  "elevated" classification) were a genuine regression, not a policy
  disagreement. Before the centralization, `compute_all_classifications`
  derived the display scaling from the unit string inline (`per 1,000 →
  x1,000`, `per 100,000 → x100,000`); the rewrite moved onto
  `spec.rate_multiplier` / `multiplier_for_unit()`, which carried a legacy
  `x1 for non-%` rule — so classification saw `0.015` instead of `15`.
  Fix: the clinical slice now stores the real display scaling beside its
  unit (the convention the forecast slice already used),
  `multiplier_for_unit()` derives the true scaling from the normalized unit
  string, and `seed_system_indicator_definitions()` syncs existing system
  rows with a version bump + full history snapshot — never a silent
  rewrite: stored results keep their own `formula_version` and are flagged
  stale until recomputed (`tests/test_seed_system_definitions_sync.py`
  pins the heal + idempotency). `test_clinical.py` and the full
  rate_config matrix are green.
* Test-housekeeping updated where the expectation was objectively stale:
  alembic head `d7e8f9a0b1c2`/`c2d3e4f5a6b7` → `e3f4a5b6c7d8`, menu tab count
  18 → 19 (the new Indicators tab), and `test_regional.py` now exercises the
  registry denominator gate instead of the removed `_safe_rate` helper.
