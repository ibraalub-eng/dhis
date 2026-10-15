# US-10 — AI/ML Audit Report

Date: 2026-10-15
Scope: independent scientific/technical audit of the DHIS AI/ML surface
(train/test split, data leakage, feature generation, XGBoost, SHAP, anomaly
models, future-data leakage, prediction I/O documentation, tests).

> This is a verification phase, not an assumption that defects exist. Findings
> were read directly from source; the highest-severity items were re-verified by
> hand. Items marked **[OK]** are explicitly cleared.

## 1. Method

- Read the core predictor (`app/engine/smart/xgboost_predictor.py`) in full.
- Audited anomaly, clustering/decomposition/regional, and AI-plugin modules in
  parallel by independent agents, then re-verified the top findings directly.
- Cross-checked the test suite for the behaviors each module claims.

## 2. Verified [OK] (no change required)

| Area | Evidence |
|---|---|
| XGBoost target has no temporal leakage | label of month `m` uses `m+1` outcomes; features use only `<= m` (`xgboost_predictor.py:298-371`) |
| Point-in-time month slicing | `train_months = all_months[:end_idx + 1]` (`:770-773`) |
| Deterministic estimators | `random_state=42` on every XGBoost / IsolationForest / KMeans / PCA in `ml/` |
| XGBoost SHAP internal consistency | `shap.TreeExplainer(best_model)` explains the same regressor used for `predicted_next_score` (`:932`, `:979`) |
| Layered outlier engine | Theil–Sen projected from prior window only; peer tier excludes self; formulas documented (`anomaly/layered.py`) |
| Forecast modules | strictly `m <= base`; one-step-ahead residual; explicit "estimate" disclaimers (`smart/indicator_forecast.py`, `smart/early_warning.py`) |
| Correlation FDR discipline | Benjamini–Hochberg + `|r|>0.7` gate (`smart/correlations.py`) |
| Lag direction | `A_t -> B_{t+lag}` controlling `B_t`; never uses the target's own future (`smart/lag_analysis.py`) |
| Zero-variance / NaN guards | present in `zscore.py`, `layered.py`, `residual.py`, `ml/anomaly.py` |

## 3. Confirmed defects

Severity: **[BUG]** = incorrect behavior; **[RISK]** = methodological/design concern.

### BUG 5 — SHAP attributions described a different quantity than the score *(FIXED)*
`smart/explainability.py` refit a *fresh* `IsolationForest` (contamination
default `0.10`) while the stored `anomaly_score` is a 4-method ensemble
(`smart/anomaly.py:109-120`, IF weight only `0.35`) computed with contamination
default `0.05`. The explanation did not describe the score it was attached to.

Fix: reuse the detector's exact preprocessing (`_prepare_feature_matrix`),
align the contamination default with detection (`0.05`), and record
`explained_component="isolation_forest"` plus `explained_score` (the IF
component) on `AnomalyExplanation` so the attribution's target is explicit.

### BUG 6 — AI caches did not invalidate on model/provider change *(FIXED)*
`plugins/ai/cache.py:_make_cache_key` hashed only the prompt; the comparative
report cache keyed only on `month:lang` with `expires_at=None`. Changing
`ai_model`/`ai_provider` served prior-model output for up to 24h (reports:
indefinitely).

Fix: embed `ai_config_signature()` (`v{prompt_schema}|{provider}|{model}`) in
both keys. `invalidate_report_cache` still matches via its prefix patterns.

### BUG 7 — AI output was not marked as model vs local fallback *(FIXED)*
Fallbacks were returned silently and were indistinguishable from genuine AI
output; no provenance field existed.

Fix: `AIRuleDef.source` (`"ai"` | `"local"`), `_mark_local()` tagging every local
fallback, `Recommendation.source` propagation, and
`generate_executive_summary_ex()` returning `(text, source)`.

### Bugs 1–4 — recorded, NOT fixed (out of the selected scope)
| # | Location | Issue |
|---|---|---|
| 1 | `anomaly/trends.py:282` | `for f in []` makes the significant-trend `key_findings` group always empty |
| 2 | `anomaly/trends.py:240` | trend projection ignores the fitted intercept; can add/remove outliers wrongly (dead `_mu` at :232; duplicate set at :234-235) |
| 3 | `smart/residual.py:47` | residual z standardized on mean/std that include the scored point -> outliers deflate their own z |
| 4 | `anomaly/comparison.py:55` | `ttest_ind` with a single-observation group (invalid); result unused; benchmark includes self (:42); percentile tie-collapse (:48) |

## 4. Open [RISK] items (design/method, not necessarily wrong)

- `xgboost_predictor.py:278-284` — `SimpleImputer`/`StandardScaler` fit on the
  full matrix before the split (`:846`); optimistic metrics (preprocessing
  leakage).
- `xgboost_predictor.py:846` — positional 80/20 split on month-major rows, not
  grouped by month; boundary can bisect a month. `clf_accuracy=1.0` on degenerate
  test labels (`:894`) overstates accuracy.
- `xgboost_predictor.py:133-141,257,271` — absent count indicators coerce to `0`
  and deltas to `0` when `prev<=0`, contradicting the NaN-by-design intent.
- `zscore.py:115-117` — `detect_monthly_trend` excludes only `current_month`
  (caller-dependent future-data exposure).
- `smart/anomaly.py:37-40,98-100` — in-sample scaler/Mahalanobis covariance.
- `smart/clustering.py:152` — `PCA` has no `random_state` (large-n
  non-reproducibility).
- `governorate_analysis.py` — no multiple-comparison correction, in-sample R²,
  no tests.
- `regional.py:364-389 vs 769-781` — `_explain_risk` contributions do not sum to
  the score it explains.
- `plugins/ai/prompts.py` — raw DB strings injected into prompts, no escaping or
  system-role separation; prompts unversioned (mitigated by
  `AI_PROMPT_SCHEMA_VERSION` now participating in cache keys).
- Providers use temperature `0.3` with no seed; reproducibility relies on cache.

## 5. Test coverage (added / remaining)

Added regression tests (`tests/test_ai_audit_us10.py`) covering BUGs 5–7.

Remaining gaps: `plugins/ai/cache.py` TTL internals, `_parse_response` malformed
input, `generate_executive_summary` content, provider HTTP error paths,
`smart/governorate_analysis.py`, `smart/geo.py`, and SHAP-vs-score numeric
consistency beyond the component-score assertion.
