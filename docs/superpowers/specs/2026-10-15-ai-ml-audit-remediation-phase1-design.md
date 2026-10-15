# AI/ML Audit Remediation — Phase 1 (BUGs 1–4 + low-risk RISK items) Design

Date: 2026-10-15
Related: `docs/superpowers/reports/2026-10-15-us10-ai-ml-audit.md`

## Goal

Fix the four confirmed correctness defects from the US-10 audit (BUGs 1–4) and
the low-risk RISK items that do **not** change reported model metrics, while
keeping every already-correct path (audit benchmark screen, anomaly engine)
consistent.

## Scope

**In scope (Phase 1):**
- BUG 1 — `trends.py` `key_findings` always empty.
- BUG 2 — `trends.py` trend projection ignores the fitted intercept.
- BUG 3 — `residual.py` in-sample residual z.
- BUG 4 — `comparison.py` self-inclusive benchmark, tie-collapsed percentile,
  invalid single-vs-many t-test (mirrored in `audit/explain.py`).
- RISK — `clustering.py` PCA without `random_state`.
- RISK — `zscore.py:detect_monthly_trend` excludes only `== current_month`.
- RISK — `regional.py:_explain_risk` contributions don't sum to `risk_score`.
- RISK — `governorate_analysis.py` no multiple-comparison correction + in-sample
  R² + no tests.

**Out of scope (deferred, documented in the audit report):**
- XGBoost preprocessing-leakage restructure, month-grouped split, degenerate
  `clf_accuracy`, absent-count NaN semantics (Phase 2 — changes reported
  metrics).
- `prompts.py` untrusted-text framing; provider `seed`.

## Global constraints

- TDD: failing test first for every change; watch it fail, then implement.
- Preserve public interfaces unless this spec says otherwise.
- No new dependencies (`scipy`, `statsmodels`, `sklearn` already used).
- Tests: `pytest`, run with `.\\.venv\\Scripts\\python.exe -m pytest`.
- Repo lint is pre-existing-dirty (I001 etc.); do not fix unrelated lint, and do
  not introduce new ruff errors in touched/new files.

## Design per item

### BUG 1 — `generate_historical_summary` key_findings (`trends.py:281-285`)

Root cause: the first comprehension is `["↑ " + f.finding for t in trends for f
in [] ...]` — `f` is bound from an empty iterable, so the group is always empty.

Fix: replace with `["↑ " + t.findings[0] for t in trends if t.is_significant and
t.findings][:5]`. No interface change.

Test: a summary over one significant `TrendResult` with non-empty `findings`
yields a `key_findings` entry starting with `"↑ "`.

### BUG 2 — trend projection (`trends.py:237-242`)

Root cause: `projected = slope * len(historical_rates) + historical_rates[0]`
uses the first observed value as the intercept instead of the fitted intercept
returned by `_linear_regression` (discarded via `slope, _, _`). `_mu`
(`:232`) is dead; the outlier check at `:234-235` duplicates `:230`.

Fix: keep `slope, intercept, _ = _linear_regression(...)`; project
`projected = slope * len(historical_rates) + intercept`; delete `_mu` and the
redundant `:234-235` block.

Test: construct history where the intercept clearly differs from
`historical_rates[0]`; assert the projection matches `slope*n + intercept`.

### BUG 3 — residual z (`residual.py:47`)

Root cause: `residual_z = (residuals - residuals.mean()) / residuals.std()`
standardizes in-sample, so a large residual inflates the std it is measured
against (and each point contributes to its own z).

Fix: use leverage-aware studentized residuals:
`influence = model.get_influence()`;
`residual_z = np.asarray(influence.resid_studentized_internal)`. Threshold
semantics (2.0 / 1.5) unchanged. `residual`/`predicted_value` unchanged.

Test: a single gross outlier among ≥5 hospitals has larger `|residual_z_score|`
under studentized residuals than under the in-sample z (assert the outlier is
flagged and its studentized |z| exceeds the old in-sample |z|).

### BUG 4 — `comparison.py` (and mirror in `audit/explain.py`)

Root causes:
1. `benchmark = mean(all rates)` includes the hospital itself (`:42`).
2. `sorted_rates.index(rate)` collapses ties to the first index (`:48`).
3. `ttest_ind([rate], other_rates)` has an n=1 group (`:55`) — invalid.

Fixes (align with the already-correct audit screen and anomaly engine):
1. `benchmark` = mean of **peer** rates (exclude the hospital).
2. Percentile via tie-aware ranking, matching `audit/benchmark.py:62-64`
   exactly: `below = #peers < rate`, `equal = #peers == rate`,
   `percentile = round((below + 0.5 * equal) / len(peers) * 100, 1)`.
   Full tie (all peers equal) → `50.0`; better than every peer → `100.0`.
3. Significance = one-sample t-test of the peers against this hospital's value:
   `stats.ttest_1samp(other_rates, rate)`. Rename `_p_value`→`p_value`
   (it is returned via `comparison_p_value`).
4. Mirror items 1–3 in `audit/explain.py:1134-1142` and update its caveat text
   (no longer a single-vs-many t-test).

Tests:
- Benchmark excludes self (compare against hand-computed peer mean).
- Full tie among peers → percentile 50 (not 100).
- p-value is finite for `n>=3` (no NaN from an n=1 group).
- `explain_comparison_row` p-value equals `compare_hospitals` p-value for the
  same data (consistency).

### RISK 5 — PCA reproducibility (`clustering.py:152`)

Fix: `PCA(n_components=2, random_state=42)`. Test: two runs on identical input
produce identical `pca_coordinates`.

### RISK 6 — future-month guard (`zscore.py:115-117`)

Root cause: `detect_monthly_trend` skips only `month == current_month`; any month
after `current_month` in the supplied mapping is used as "historical".

Fix: `if month >= current_month: continue` (ISO `YYYY-MM` lexicographic order).
Test: pass a mapping containing months after `current_month`; the z-score equals
that computed from the strictly-prior months only.

### RISK 7 — region risk decomposition (`regional.py:_explain_risk`)

Root cause: `_explain_risk` lists every elevated rate/clinical metric, each with
up to 15 points, but the score (`:757-800`) adds only the **single worst**
contributor per group (`rate_dev = max(...)`, `clinical = max(...)`). Reported
factors therefore overstate the score.

Fix: in `_explain_risk`, emit only the worst rate metric (contributing the group
maximum) and the worst clinical metric, so
`mortality + worst_rate + worst_clinical + quality ≈ risk_score` (within
rounding/cap). Keep the `note_ar`/`note_en` wording accurate.

Test: build `metrics_by_gov` + `benchmarks` where two rate metrics are elevated;
assert the sum of returned factor contributions equals the corresponding
`risk_score` (within 0.2), and only the worst rate metric appears.

### RISK 8 — governorate analysis (`governorate_analysis.py`)

Root causes: cross-governorate correlations use only `abs(r)>0.6 and p<0.1` with
no multiple-comparison control; `model_r2` is in-sample.

Fixes:
- Collect all pairwise p-values, apply Benjamini–Hochberg FDR (reuse the
  `_bh_significant` pattern from `correlations.py`), keep pairs passing
  `abs(r)>0.6` **and** BH-significant at `q=0.1`.
- Replace in-sample `model_r2` with `adjusted_r2 = 1-(1-R²)(n-1)/(n-p-1)`
  (p = number of features), reported as `model_r2_adj` alongside `model_r2`.
- Add `tests/test_smart_governorate.py` (currently none).

Tests: a synthetic multi-pair input where one pair is spuriously significant
before BH is dropped after correction; adjusted R² < R² for a small sample.

## Files touched

- `app/engine/anomaly/trends.py` (BUGs 1, 2)
- `app/engine/smart/residual.py` (BUG 3)
- `app/engine/anomaly/comparison.py` (BUG 4)
- `app/engine/audit/explain.py` (BUG 4 mirror)
- `app/engine/smart/clustering.py` (RISK 5)
- `app/engine/anomaly/zscore.py` (RISK 6)
- `app/engine/smart/regional.py` (RISK 7)
- `app/engine/smart/governorate_analysis.py` (RISK 8)
- Tests: `tests/test_anomaly.py`, `tests/test_smart_residuals.py`,
  `tests/test_smart_clustering.py`, tests for explain, new
  `tests/test_smart_governorate.py`

## Testing strategy

- New failing test per fix (verified RED), minimal implementation to GREEN.
- Existing suites that assert on the touched behaviors:
  `test_anomaly.py`, `test_benchmark.py`, `test_explain*.py`,
  `test_smart_residuals.py`, `test_smart_clustering.py`, `test_smart_*.py`.
- Re-run the full suite before completion.

## Risks

- Changing `compare_hospitals` benchmark/percentile/p-value touches `analysis.py`,
  `file_ops.py`, and `explain.py`; the mirror change in `explain.py` is required
  to keep "verified" consistent. Existing `test_anomaly` comparison tests assert
  labels/len only, not benchmark values, so they should stay green — verify.
- Studentized residuals change z magnitudes; `test_smart_residuals.py` asserts
  structure/flagging, not exact z — verify.
