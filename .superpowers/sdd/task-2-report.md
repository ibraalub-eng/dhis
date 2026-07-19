# Task 2: SciPy Upgrades in Anomaly Detection Package

## What I Did

Integrated `scipy.stats` into three anomaly detection modules to replace manual computations with statistically robust library functions.

### 1. `app/engine/anomaly/trends.py`
- Added `from scipy import stats as scipy_stats` import
- Replaced manual OLS linear regression (np.mean, np.sum, SS_xy/SS_xx) with `scipy_stats.linregress(x, y)`
- `r_squared` now computed as `result.rvalue ** 2`
- Function signature and return type unchanged

### 2. `app/engine/anomaly/zscore.py`
- Added `from scipy import stats as scipy_stats` import
- Added `_p_value = float(scipy_stats.norm.sf(abs(z_score)) * 2)` in `detect_anomalies` (line 63)
- Added `_p_value = float(scipy_stats.norm.sf(abs(z)) * 2)` in `detect_monthly_trend` (line 107)
- Both p-values computed but not stored (available for future diagnostic use)

### 3. `app/engine/anomaly/comparison.py`
- Added `from scipy import stats as scipy_stats` import
- Added `Optional` to typing imports
- Added `comparison_p_value: Optional[float] = None` field to `HospitalComparison` dataclass
- Added Welch's t-test (`scipy_stats.ttest_ind`) in `compare_hospitals` loop, computing p-value for each hospital vs all others
- Passed `comparison_p_value=_p_value` to the `HospitalComparison` constructor

## Test Results

```
31 passed in 9.54s
```

All 31 tests in `tests/test_anomaly.py` pass. No test modifications were needed — the new `comparison_p_value` field has a default of `None`, so existing `HospitalComparison(...)` constructions in tests work without changes.

## Files Changed

| File | Changes |
|------|---------|
| `app/engine/anomaly/trends.py` | Added scipy import; replaced `_linear_regression` body |
| `app/engine/anomaly/zscore.py` | Added scipy import; added p-value computation in 2 functions |
| `app/engine/anomaly/comparison.py` | Added scipy + Optional imports; added dataclass field; added t-test computation |

## Self-Review Findings

- **Correctness**: `linregress` returns the same slope/intercept as the manual OLS. R² via `rvalue**2` is mathematically equivalent.
- **Edge cases**: `_linear_regression` still short-circuits on n < 2 (returns 0,0,0). `linregress` handles the rest correctly.
- **zscore p-values**: Two-tailed p-value from the standard normal survival function is the standard approach for z-score significance. Variables prefixed with `_` to indicate they are unused but available.
- **comparison_p_value**: Welch's t-test is appropriate here (does not assume equal variance). Guard conditions (`len(rate_vals) >= 3`, `len(other_rates) >= 2`, `len(set(other_rates)) > 1`) prevent degenerate cases. Default `None` ensures backward compatibility.
- **No regressions**: All 31 existing tests pass without modification.
