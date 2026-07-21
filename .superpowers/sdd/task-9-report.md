# Task 9: ML PCA Decomposition Module — Report

## Status: ✅ Complete

## Files Created

| File | Purpose |
|------|---------|
| `app/engine/ml/decomposition.py` | PCA decomposition for root cause analysis |
| `tests/test_ml_decomposition.py` | 3 tests covering basic, disabled, and too-few-hospital cases |

## Test Results

```
tests/test_ml_decomposition.py::test_run_pca_basic PASSED
tests/test_ml_decomposition.py::test_run_pca_disabled PASSED
tests/test_ml_decomposition.py::test_run_pca_too_few PASSED
3 passed
```

Full ML suite (14 tests): **all passed**

## Implementation Summary

- `run_pca()` accepts hospital feature data dict and config dict
- Returns `Optional[PCAResult]` (None if disabled, <3 hospitals, or <2 features)
- Standardizes features with `StandardScaler` before PCA
- Respects `max_components` and `variance_threshold` config keys
- Extracts component loadings and top-3 contributing features per component
- Uses `random_state=42` for reproducibility
