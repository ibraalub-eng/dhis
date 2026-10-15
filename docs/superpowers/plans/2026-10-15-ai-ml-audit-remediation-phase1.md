# AI/ML Audit Remediation — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix US-10 audit BUGs 1–4 and low-risk RISK items 5–8 without changing reported model metrics.

**Architecture:** Targeted fixes to existing anomaly/smart modules; statistical methods corrected and made consistent with the already-correct audit benchmark screen. No new dependencies.

**Tech Stack:** Python 3.12, pytest, scipy, statsmodels, scikit-learn, xgboost.

**Spec:** `docs/superpowers/specs/2026-10-15-ai-ml-audit-remediation-phase1-design.md`

## Global Constraints

- TDD: write the failing test, watch it fail for the expected reason, then implement.
- Tests run with `.\\.venv\\Scripts\\python.exe -m pytest`.
- No new dependencies; use existing `scipy`/`statsmodels`.
- Do not introduce new ruff errors in touched/new files (repo is pre-existing-dirty).
- Preserve public signatures except where stated.

---

### Task 1: BUG 1 — significant-trend key_findings

**Files:** Modify `app/engine/anomaly/trends.py:281-285`; Test `tests/test_anomaly.py`.

- [ ] **Step 1: Failing test** — append to `tests/test_anomaly.py`:

```python
def test_historical_summary_includes_significant_trend_finding():
    trends = [TrendResult(
        hospital="H", indicator_code="5", rate_name="C-section rate",
        months=["2026-01", "2026-02"], values=[25, 30],
        mean=27.5, std=2.5, slope=2.5, slope_pct=9.1,
        trend_direction="increasing", trend_severity="moderate",
        is_significant=True, cv=9.1, last_vs_mean_pct_change=9.1,
        consecutive_direction="increasing", consecutive_count=2,
        findings=["C-section rate shows a increasing trend"],
    )]
    summary = generate_historical_summary(trends, [], [], [])
    assert any(f.startswith("\u2191 ") for f in summary["key_findings"])
```

- [ ] **Step 2: Run & verify fail** — `pytest tests/test_anomaly.py::test_historical_summary_includes_significant_trend_finding -v` → FAIL (empty key_findings).
- [ ] **Step 3: Implement** — replace the broken comprehension (line 282) with:

```python
            *["\u2191 " + t.findings[0] for t in trends if t.is_significant and t.findings][:5],
```

- [ ] **Step 4: Run & verify pass** — same command → PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(anomaly): populate significant-trend key findings in historical summary"`.

---

### Task 2: BUG 2 — trend projection uses fitted intercept

**Files:** Modify `app/engine/anomaly/trends.py:237-242`; Test `tests/test_anomaly.py`.

- [ ] **Step 1: Failing test** — append:

```python
def test_trend_projection_uses_fitted_intercept():
    # history rates [10,10,10,20]; linregress slope=3, intercept=8, std=4.33
    # current rate 12: |12-(3*4+8)|=8 < 2*std => NOT an outlier.
    # Buggy code used historical_rates[0]=10 => |12-22|=10 > 2*std => falsely flagged.
    monthly = {
        "2026-01": {"5": 20, "2": 200},
        "2026-02": {"5": 20, "2": 200},
        "2026-03": {"5": 20, "2": 200},
        "2026-04": {"5": 40, "2": 200},
        "2026-05": {"5": 24, "2": 200},
    }
    results = detect_trend_anomalies("TestHosp", monthly)
    cs = [r for r in results if "C-section" in r.rate_name][0]
    assert cs.is_outlier is False
```

- [ ] **Step 2: Run & verify fail** → FAIL (`is_outlier` True).
- [ ] **Step 3: Implement** — at `trends.py`:

```python
        if abs(z) > _TRENDS_CONFIG["zscore_threshold"]:
            is_outlier = True

        if len(historical_rates) >= 3:
            x = list(range(len(historical_rates)))
            slope, intercept, _ = _linear_regression(x, historical_rates)
            projected = slope * len(historical_rates) + intercept
            if std_h > 0 and abs(current_rate - projected) > 2 * std_h:
                is_outlier = True
```

(delete the dead `_mu` line 232 and the duplicate `:234-235` block.)

- [ ] **Step 4: Run & verify pass** → PASS (and existing `test_detect_trend_anomalies_outlier` still passes).
- [ ] **Step 5: Commit** — `git commit -m "fix(anomaly): project trend from fitted intercept, drop dead code"`.

---

### Task 3: BUG 3 — leave-one-out residual z

**Files:** Modify `app/engine/smart/residual.py:47`; Test `tests/test_smart_residuals.py`.

- [ ] **Step 1: Failing test** — append:

```python
def test_outlier_z_excludes_scored_point(sample_data):
    results = analyze_residuals(sample_data, {})
    rows = [r for r in results if r.indicator == "cs_rate"]
    outlier = next(r for r in rows if r.hospital_name == "Hospital 0")
    res = np.array([r.residual for r in rows])
    in_sample_z = (outlier.residual - res.mean()) / res.std()
    assert abs(outlier.residual_z_score) > abs(in_sample_z)
    assert outlier.is_anomaly is True
```

- [ ] **Step 2: Run & verify fail** → FAIL (equal, not greater).
- [ ] **Step 3: Implement** — replace line 47 with leave-one-out standardization:

```python
        resid_arr = np.asarray(residuals, dtype=float)
        n_res = len(resid_arr)
        adj_z = np.zeros(n_res)
        for pos in range(n_res):
            others = np.delete(resid_arr, pos)
            if len(others) < 2 or others.std() < 1e-12:
                adj_z[pos] = 0.0
            else:
                adj_z[pos] = (resid_arr[pos] - others.mean()) / others.std()
        residual_z = pd.Series(adj_z, index=residuals.index)
```

(add `import numpy as np` at top.)

- [ ] **Step 4: Run & verify pass** → PASS (existing residual tests still pass).
- [ ] **Step 5: Commit** — `git commit -m "fix(smart): standardize residuals leave-one-out so outliers don't deflate their own z"`.

---

### Task 4: BUG 4 — comparison benchmark/percentile/p-value (+ explain mirror)

**Files:** Modify `app/engine/anomaly/comparison.py`, `app/engine/audit/explain.py:1132-1142`; Test `tests/test_anomaly.py`.

**Interfaces:**
- Produces `peer_significance(rate: float, other_rates: List[float]) -> Optional[float]`.

- [ ] **Step 1: Failing tests** — append to `tests/test_anomaly.py`:

```python
def test_compare_hospitals_benchmark_excludes_self():
    all_data = {
        "H1": {"2026-04": {"5": 20, "2": 200}},   # 10%
        "H2": {"2026-04": {"5": 40, "2": 200}},   # 20%
        "H3": {"2026-04": {"5": 60, "2": 200}},   # 30%
    }
    comps = compare_hospitals(all_data, "2026-04")
    h1 = next(c for c in comps if c.hospital == "H1" and "C-section" in c.rate_name)
    assert h1.benchmark == 25.0  # mean(20, 30), excludes self


def test_compare_hospitals_percentile_full_tie_is_median():
    all_data = {f"H{i}": {"2026-04": {"5": 30, "2": 200}} for i in range(3)}
    comps = compare_hospitals(all_data, "2026-04")
    cs = [c for c in comps if "C-section" in c.rate_name]
    assert cs and all(c.percentile_rank == 50.0 for c in cs)


def test_compare_hospitals_pvalue_matches_one_sample_ttest():
    from scipy import stats as _s
    all_data = {
        "H1": {"2026-04": {"5": 20, "2": 200}},
        "H2": {"2026-04": {"5": 40, "2": 200}},
        "H3": {"2026-04": {"5": 60, "2": 200}},
        "H4": {"2026-04": {"5": 50, "2": 200}},
    }
    comps = compare_hospitals(all_data, "2026-04")
    h1 = next(c for c in comps if c.hospital == "H1" and "C-section" in c.rate_name)
    others = [20.0, 30.0, 25.0]  # H2,H3,H4 rates
    expected = round(float(_s.ttest_1samp(others, 10.0).pvalue), 4)
    assert h1.comparison_p_value == expected
```

- [ ] **Step 2: Run & verify fail** → all three FAIL.
- [ ] **Step 3: Implement** in `comparison.py` — add helper and rewrite the per-hospital block:

```python
def peer_significance(rate: float, other_rates: List[float]) -> Optional[float]:
    """Two-sided one-sample t-test of the peer rates against this hospital's value."""
    if len(other_rates) < 2 or len(set(other_rates)) < 2:
        return None
    _, p_val = scipy_stats.ttest_1samp(other_rates, rate)
    return round(float(p_val), 4)
```

```python
        for hosp_name, rate in rates.items():
            other_rates = [v for h, v in rates.items() if h != hosp_name]
            benchmark = float(np.mean(other_rates)) if other_rates else float(np.mean(rate_vals))

            if other_rates:
                below = sum(1 for p in other_rates if p < rate)
                equal = sum(1 for p in other_rates if p == rate)
                percentile = round((below + 0.5 * equal) / len(other_rates) * 100, 1)
            else:
                percentile = 50.0

            deviation = ((rate - benchmark) / benchmark * 100) if benchmark != 0 else 0.0
            p_value = peer_significance(rate, other_rates) if len(rate_vals) >= 3 else None
            ...  # labels unchanged; build HospitalComparison(..., comparison_p_value=p_value)
```

- [ ] **Step 4: Implement explain mirror** — in `audit/explain.py:1132-1142` replace the manual `ttest_ind` with:

```python
    from app.engine.anomaly.comparison import peer_significance
    p_value = peer_significance(peer_rates[hospital_name], others) if n_all >= 3 else None
```

and update the docstring/caveat wording (no longer a single-vs-many t-test).

- [ ] **Step 5: Run & verify pass** — `pytest tests/test_anomaly.py tests/test_explain.py tests/test_benchmark.py -q` → PASS.
- [ ] **Step 6: Commit** — `git commit -m "fix(anomaly): peer-excluding benchmark, tie-aware percentile, one-sample t-test (mirrored in explain)"`.

---

### Task 5: RISK 5 — PCA reproducibility

**Files:** Modify `app/engine/smart/clustering.py:152`; Test `tests/test_smart_clustering.py`.

- [ ] **Step 1: Failing test** — append:

```python
def test_pca_coordinates_deterministic(sample_data, default_config):
    a = run_clustering(sample_data, default_config).pca_coordinates
    b = run_clustering(sample_data, default_config).pca_coordinates
    assert a == b
```

- [ ] **Step 2: Run & verify fail** → FAIL (floating-point sign flips vary run to run).
- [ ] **Step 3: Implement** — `PCA(n_components=2, random_state=42)`.
- [ ] **Step 4: Run & verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(smart): seed PCA for reproducible cluster coordinates"`.

---

### Task 6: RISK 6 — future-month guard in detect_monthly_trend

**Files:** Modify `app/engine/anomaly/zscore.py:115-117`; Test `tests/test_anomaly.py`.

- [ ] **Step 1: Failing test** — append:

```python
def test_detect_monthly_trend_ignores_future_months():
    hist = {
        "2026-01": {"5": 20, "2": 200},
        "2026-02": {"5": 20, "2": 200},
        "2026-03": {"5": 40, "2": 200},   # future relative to current
        "2099-12": {"5": 80, "2": 200},   # far future
    }
    with_future = detect_monthly_trend(hist, "2026-02", {"5": 20, "2": 200})
    without_future = detect_monthly_trend(
        {"2026-01": {"5": 20, "2": 200}}, "2026-02", {"5": 20, "2": 200})
    z_future = next(r for r in with_future if "C-section" in r.rate_name).z_score
    z_clean = next(r for r in without_future if "C-section" in r.rate_name).z_score
    assert z_future == z_clean
```

- [ ] **Step 2: Run & verify fail** → FAIL (future months change the mean/std).
- [ ] **Step 3: Implement** — change `if month == current_month:` to `if month >= current_month:`.
- [ ] **Step 4: Run & verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(anomaly): detect_monthly_trend uses strictly prior months"`.

---

### Task 7: RISK 7 — region risk decomposition sums to score

**Files:** Modify `app/engine/smart/regional.py:_explain_risk`; Test `tests/test_regional.py`.

- [ ] **Step 1: Failing test** — append:

```python
def test_explain_risk_contributions_sum_to_score():
    bm = {m: {"mean": 10.0, "std": 5.0} for m in (
        "nmr", "mmr", "stillbirth_rate", "cs_rate", "preterm_rate",
        "smm_rate", "high_risk_rate", "adolescent_rate")}
    metrics = {"G": {
        "nmr": 10.0, "mmr": 20.0, "stillbirth_rate": 10.0, "cs_rate": 40.0,
        "preterm_rate": 10.0, "smm_rate": 20.0, "high_risk_rate": 40.0,
        "adolescent_rate": 10.0}}
    # score = mortality(0) + max_rate(min(15,300/10)=15) + max_clinical(min(15,300/12)=15) + quality(0)
    risks = [{"governorate": "G", "risk_score": 30.0, "level": "high", "completeness": 100.0}]
    factors = _explain_risk(metrics, bm, risks)[0]["factors"]
    total = sum(f["contribution"] for f in factors)
    assert abs(total - 30.0) <= 0.5
    feats = {f["feature"] for f in factors}
    assert "cs_rate" in feats and "mmr" not in feats          # only worst rate
    assert "high_risk_rate" in feats and "smm_rate" not in feats  # only worst clinical
```

- [ ] **Step 2: Run & verify fail** → FAIL (old code adds mmr + smm_rate too; total 48.3).
- [ ] **Step 3: Implement** — in `_explain_risk`, replace the two per-metric loops with a "worst contributor" selection:

```python
        rate_candidates = []
        for metric in ("mmr", "stillbirth_rate", "cs_rate", "preterm_rate"):
            bm_m = benchmarks.get(metric, {})
            mv, bmean = m.get(metric), bm_m.get("mean")
            if mv is not None and bmean and bmean > 0:
                dev = (mv - bmean) / bmean * 100
                if dev > 0:
                    rate_candidates.append((min(15.0, dev / 10.0), metric, dev, mv, bmean))
        if rate_candidates:
            contrib, metric, dev, mv, bmean = max(rate_candidates, key=lambda t: t[0])
            factors.append({"feature": metric, "arabic_label": METRIC_NAMES_AR[metric],
                            "contribution": round(contrib, 1), "deviation_pct": round(float(dev), 1),
                            "observed": round(float(mv), 3), "benchmark": round(float(bmean), 3)})
```

(the clinical loop mirrors this with `/12.0` and `("smm_rate","high_risk_rate","adolescent_rate")`.)

- [ ] **Step 4: Run & verify pass** — `pytest tests/test_regional.py -q` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(smart): region risk factors report only the worst contributor per group so they sum to the score"`.

---

### Task 8: RISK 8 — governorate FDR correction + adjusted R²

**Files:** Modify `app/engine/smart/governorate_analysis.py`; Create `tests/test_smart_governorate.py`.

**Interfaces:**
- Consumes `app.engine.smart.correlations._bh_significant(p_values, q)`.

- [ ] **Step 1: Failing test** — create `tests/test_smart_governorate.py`:

```python
import numpy as np
from app.engine.smart.governorate_analysis import (
    analyze_governorate_correlations, _apply_cross_gov_fdr,
)


def test_cross_gov_fdr_drops_marginal_pair():
    pairs = [
        {"indicator_a": "a", "indicator_b": "b", "correlation": 0.9, "p_value": 0.001},
        {"indicator_a": "a", "indicator_b": "c", "correlation": 0.7, "p_value": 0.09},
    ]
    kept = _apply_cross_gov_fdr(pairs, q=0.05)
    assert [p["indicator_b"] for p in kept] == ["b"]


def test_governorate_insights_report_adjusted_r2():
    rng = np.random.default_rng(0)
    data = {}
    for i in range(6):
        data[f"H{i}"] = {
            "hospital_id": i,
            "governorate": ["G1", "G1", "G2", "G2", "G3", "G3"][i],
            "hospital_type": "general",
            "values": {"cs_rate": 30 + rng.normal(), "smm_total": 5 + rng.normal(),
                       "mat_deaths": 1 + 0.1 * rng.normal(), "nd": 2 + rng.normal(),
                       "sb": 1 + 0.1 * rng.normal(), "preterm": 10 + rng.normal(),
                       "lbw": 8 + rng.normal(), "total_births": 200 + rng.normal(),
                       "high_risk": 15 + rng.normal(), "adolescent": 3 + rng.normal()},
        }
    out = analyze_governorate_correlations(data, {})
    insights = out.get("xgboost_insights", {})
    for target, info in insights.items():
        if "model_r2" in info:
            assert "model_r2_adj" in info
            assert info["model_r2_adj"] <= info["model_r2"] + 1e-9
```

- [ ] **Step 2: Run & verify fail** → FAIL (`_apply_cross_gov_fdr` missing; no `model_r2_adj`).
- [ ] **Step 3: Implement** — in `governorate_analysis.py`:

```python
from app.engine.smart.correlations import _bh_significant


def _apply_cross_gov_fdr(pairs, q=0.1):
    if not pairs:
        return []
    pvals = [p["p_value"] for p in pairs]
    mask = _bh_significant(pvals, q)
    return [p for p, keep in zip(pairs, mask) if keep]
```

In `analyze_governorate_correlations`, after collecting `cross_correlations` (with `abs(r) > 0.6` only — drop the inline `p < 0.1`), apply `cross_correlations = _apply_cross_gov_fdr(cross_correlations, q=0.1)` before the sort/slice.

In `_compute_xgboost_governorate_insights`, add:

```python
        n = len(y)
        p = X.shape[1]
        r2 = float(model.score(X, y))
        adj = 1 - (1 - r2) * (n - 1) / (n - p - 1) if n - p - 1 > 0 else r2
        ...
        "model_r2": round(r2, 4),
        "model_r2_adj": round(float(adj), 4),
```

- [ ] **Step 4: Run & verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(smart): FDR-correct governorate correlations and report adjusted R^2"`.

---

### Task 9: Full verification

- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/ -q -p no:warnings --no-header` → all pass except the known env-only `test_script_is_valid_bash`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m ruff check <touched files>` → no new errors.
- [ ] Commit any remaining changes / push.

## Self-Review

- Spec coverage: BUGs 1–4 → Tasks 1–4; RISK 5–8 → Tasks 5–8. Out-of-scope C/D excluded.
- Types consistent: `peer_significance` defined in Task 4 and consumed by `explain.py` there.
- No placeholders.
