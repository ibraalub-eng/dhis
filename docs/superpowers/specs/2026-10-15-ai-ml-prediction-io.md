# AI/ML Prediction Input/Output Reference

Date: 2026-10-15
Related audit: `docs/superpowers/reports/2026-10-15-us10-ai-ml-audit.md`

This document is the canonical contract for every AI/ML result exposed by DHIS:
what goes in, what comes out, the model version/fingerprint, and the leakage
guarantee. It exists so a reviewer can audit any prediction without reading the
whole codebase.

Legend: **PIT** = point-in-time (no data after the target is used).

---

## 1. Forward forecast — XGBoost ensemble

**Entry point:** `app/engine/smart/xgboost_predictor.py::run_xgboost_predictions(session, current_month, config)`
**API:** `GET /smart/xgboost/{month}?horizon=…` (`app/api/smart_analytics.py`)

### Inputs
- `current_month` — the month being forecast from (ISO `YYYY-MM`).
- `session` — DB session. Loads active hospitals, indicators, and `IndicatorValue`
  rows for all months **up to and including `current_month + 1`** (the extra month
  supplies forward labels only).
- `config` — smart-analytics settings (also part of the training fingerprint).

### Feature generation (`_build_supervised_dataset`, `_compute_derived_features`)
For each (hospital, month) row:
- **Base** (`FEATURE_KEYS`, 10): `cs_rate, smm_total, mat_deaths, nd, sb, preterm,
  lbw, total_births, high_risk, adolescent`.
- **Derived** (NaN when the denominator is missing/zero — never a silent 0):
  `cs_per_birth, smm_per_1000, mat_mortality_rate, stillbirth_rate, preterm_rate,
  lbw_rate, high_risk_rate, adolescent_rate`, and interactions `cs_x_highrisk,
  preterm_x_lbw, smm_x_matdeaths, nd_x_sb`.
- **Deltas** (4): `cs_rate_delta, smm_delta, mat_deaths_delta, total_births_delta`.
- **Time-series superset**: `lag1_*`/`lag2_*` for `LAG_SOURCE_KEYS` (NaN when the
  prior month is absent) and `delta_{key}` for every `FEATURE_KEY`.
- **Categorical**: one-hot `governorate`, `hospital_type`.
- **Preprocessing**: `SimpleImputer(median)` then `StandardScaler`. Fully-NaN
  columns are zero-filled first.

### Target (leakage guarantee — PIT)
`target_scores` = forward deviation of month `m+1` vs month `m` (median-of-rates
ratio scaled to `[0,1]`). Row features at month `m` carry **no** information about
`m+1`. `current_scores` are descriptive only and never enter training. Rows with no
next month are excluded from training (`labels_defined=False`).

### Train / validation
- Feature-variant selection and reported R²/MAE use **walk-forward**: train on
  months `<= m`, validate on `m+1` (`_walk_forward_validation`).
- Ensemble = 3 `XGBRegressor` configs (Light/Medium/Deep), each `random_state=42`;
  best by R² is used for SHAP; a 3-class `XGBClassifier` (severity) is fit
  separately.
- Persistence: models saved under `SMART_XGB_MODEL_DIR` (default
  `data/models/smart_xgboost`). Reused when `data_fingerprint`,
  `current_month`, and `feature_schema_version` all match.
- **Version stamps:** `FEATURE_SCHEMA_VERSION` (`xgboost_predictor.py:23`) and
  `_data_fingerprint()` (hash of months, hospitals, indicator values, indicator
  configs, and smart settings).

### Output — `XGBoostPredictionResult` (`smart/schemas.py`)
| Field | Meaning |
|---|---|
| `model_r2`, `model_mae` | metrics of the best ensemble member |
| `training_months`, `hospitals_trained` | training size |
| `predictions[]` | one `XGBoostPrediction` per active hospital (see below) |
| `global_feature_importance[]` | `XGBoostGlobalExplanation` (feature, arabic_label, mean_abs_shap, rank) |
| `accuracy_note` | human-readable provenance/metrics |
| `trained_at`, `retrained`, `data_fingerprint`, `feature_variant` | model version/provenance |
| `walk_forward[]`, `fold_predictions[]` | per-fold metrics and row-level predictions |

`XGBoostPrediction`: `hospital_name, hospital_id, current_score,
predicted_next_score, predicted_severity (normal|warning|critical), risk_change
(increasing|stable|decreasing, ±0.05), confidence (1−MAE), top_drivers[]`.

`XGBoostDriver` (SHAP attribution of `predicted_next_score`):
`feature, arabic_label, shap_value, direction (increases_risk|decreases_risk),
magnitude (high>0.3|medium>0.1|low)`.

### Known caveats
- Scaler/imputer are fit on all loaded rows before the split (mild preprocessing
  leakage).
- Split index is positional (month-major), not grouped strictly by month.
- Absent count indicators default to `0`; deltas default to `0` when `prev<=0`.

---

## 2. Smart anomaly detection — ensemble

**Entry point:** `smart/anomaly.py::detect_smart_anomalies(all_hospital_data, config, enabled, residual_scores)`

### Inputs
`all_hospital_data`: `{hospital_name: {hospital_id, governorate, hospital_type,
values:{FEATURE_KEYS…}}}` — a **single cross-section** for one month.

### Method
Shared feature matrix from `_prepare_feature_matrix` (impute median →
standardize → one-hot). Components, each normalized to `[0,1]` then combined:

| Component | Weight (config key) | Notes |
|---|---|---|
| IsolationForest | 0.35 (`ensemble_if_weight`) | `random_state=42`, contamination default 0.05 |
| LocalOutlierFactor | 0.30 (`ensemble_lof_weight`) | deterministic |
| Mahalanobis | 0.20 (`ensemble_mahal_weight`) | `pinv(cov)`; failure → zeros |
| OLS residual | 0.15 (`ensemble_residual_weight`) | upstream `residual_scores` |

Ensemble score is re-normalized to `[0,1]`.

### Output — `SmartAnomalyResult` list
`hospital_name, hospital_id, governorate, hospital_type, anomaly_score
(ensemble, 0–1), method_scores {isolation_forest, lof, mahalanobis, residual},
severity (normal<0.3 | warning<0.6 | critical), is_outlier`.

### Caveats
Imputer/scaler/covariance are fit on the scored cross-section itself (no temporal
leakage). Output order follows `all_hospital_data` insertion order (not sorted).

---

## 3. Anomaly explanation — SHAP *(BUG 5 fix)*

**Entry point:** `smart/explainability.py::explain_anomalies(anomalies, all_hospital_data, config, stratified)`

### Inputs
The `detect_smart_anomalies` results plus the same cross-section and config.

### Method
Refits `IsolationForest(contamination=config.get("contamination", 0.05),
random_state=42)` on the **identical** matrix returned by
`_prepare_feature_matrix`, then `shap.TreeExplainer`. SHAP values explain the
IsolationForest `decision_function` output (negative contribution ⇒ pushes toward
anomaly).

### Output — `AnomalyExplanation` list
| Field | Meaning |
|---|---|
| `anomaly_score` | the ensemble score (unchanged, for display) |
| `explained_component` | always `"isolation_forest"` — what SHAP actually explains |
| `explained_score` | the IsolationForest component value for this hospital (`method_scores["isolation_forest"]`) |
| `shap_values` | per-feature SHAP (IF component) |
| `top_factors[]` | `FactorExplanation(feature, shap_value, direction, magnitude, arabic_label)` |
| `text_explanation` | Arabic narrative derived from real hospital-vs-peer values |

**Contract:** `top_factors`/`shap_values` describe `explained_score` (the IF
component), **not** `anomaly_score` (the ensemble). Both are reported so the
explanation is auditable.

---

## 4. OLS residual anomalies

**Entry point:** `smart/residual.py::analyze_residuals(all_hospital_data, config, threshold_z=2.0)`
Model: `indicator ~ C(governorate) + C(hospital_type)` via `statsmodels.ols`.
Output — `ResidualResult`: `hospital_name, hospital_id, indicator, actual_value,
predicted_value, residual, residual_z_score, is_anomaly, severity
(normal|warning>1.5|critical>2.0)`. Requires ≥5 hospitals; skips zero-variance.
Caveat: z-score standardized in-sample (recorded BUG 3, not fixed).

---

## 5. Clustering

**Entry point:** `smart/clustering.py::run_clustering(...)`
DBSCAN → Agglomerative(ward) fallback, `PCA(n_components=2)` for the biplot.
Output — `SmartClusteringResult`: `n_clusters, silhouette_score, method, clusters[]
(HospitalClusterAssignment), noise_hospitals[], pca_coordinates, centroids,
profiles[]`. Caveat: PCA has no `random_state` (recorded RISK).

---

## 6. Correlations & feature importance

**Entry point:** `smart/correlations.py::analyze_correlations(...)`
Pearson + Spearman with Benjamini–Hochberg FDR; strong pairs require FDR-significant
**and** `|r|>0.7`; RandomForest importances (`random_state=42`).
Output — `SmartCorrelationResult`: `matrix, indicators, strong_correlations[]
(CorrelationPair), feature_importance[]`.

---

## 7. Indicator forecast / early-warning signals

- `smart/indicator_forecast.py::run_indicator_forecast(db, month, indicator, ids, horizon)`
  — linear trend / moving average / quantiles over the series truncated to
  `<= base`; returns `available` + quantile bands. No future data.
- `smart/early_warning.py::compute_early_warning_signals(...)` — past vs present
  window slopes; every message carries an explicit estimate/causation disclaimer.

---

## 8. AI text outputs (LLM plugin)

**Entry points:** `plugins/ai/__init__.py`
- `generate(values, classifications, risk_profile, morbidity_profile, quality_score, session)` → `List[AIRuleDef]` (clinical recommendations).
- `generate_root_cause_ai(report_data, session)` → `List[AIRuleDef]`.
- `generate_executive_summary_ex(...)` → `(text, source)`; `generate_executive_summary(...)` → `text`.

### Inputs
Prompt strings built in `plugins/ai/prompts.py` from DB-derived values; provider,
model, timeout, and max-recommendations come from `plugins/ai/providers.py`
(overridable via the admin AI config, `reload_ai_config`).

### Outputs & provenance *(BUG 7 fix)*
- `AIRuleDef`: `category, priority, title, description, rationale,
  action_items[], indicators_monitored[], *_ar, source`.
  `source = "ai"` for model output, `"local"` for the deterministic fallback.
- `Recommendation` (clinical engine) carries the merged `source`.
- Executive summary provenance is returned by `..._ex` as `("ai"|"local")`.

### Caching & auditability *(BUG 6 fix)*
- AI cache key = `sha256("v{AI_PROMPT_SCHEMA_VERSION}|{AI_PROVIDER}|{AI_MODEL}\n" + prompt)`
  (`plugins/ai/cache.py`), TTL 24h. Only genuine model responses are cached, so a
  hit is always `"ai"`.
- Comparative report cache key = `comparative_report_v2:{month}:{lang}:{signature}`
  (`engine/comparative/report_cache.py`); invalidated on data change.
- Provider/model changes therefore cannot serve stale output.
- **Gap:** prompts/responses are not persisted to an audit log (no `AuditLog`
  table yet); only the response is cached, keyed by prompt hash.

---

## 9. Reproducibility summary

| Model | Seed | Reproducible |
|---|---|---|
| XGBoost (regressor/classifier) | `random_state=42` | yes |
| IsolationForest (detect & explain) | `random_state=42` | yes |
| LOF / Mahalanobis / OLS | deterministic | yes |
| KMeans / PCA (`ml/`) | `random_state=42` | yes |
| PCA (`smart/clustering.py:152`) | **none** | no (large-n) |
| LLM providers | temperature 0.3, no seed | no (cache-stabilized) |
