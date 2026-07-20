# Task 8 Report: ML Anomaly Detection Module

**Status:** COMPLETE

## Summary

Implemented IsolationForest-based multivariate anomaly detection module for hospital data analysis.

## Files Created

| File | Description |
|------|-------------|
| `app/engine/ml/anomaly.py` | ML anomaly detection using IsolationForest |
| `tests/test_ml_anomaly.py` | 3 test cases covering basic, disabled, and edge cases |

## Implementation Details

- Uses `sklearn.ensemble.IsolationForest` with `StandardScaler` preprocessing
- Analyzes 10 features: cs, smm_total, mat_deaths, nd, sb, preterm, lbw, total_births, high_risk, adolescent
- Returns `List[MLAnomalyResult]` with hospital name, anomaly score, outlier flag, and method
- Configurable via `enabled` and `contamination` parameters
- Minimum 3 hospitals required for analysis
- Contamination auto-adjusts to `max(config, 1/n)` to avoid degenerate cases

## Test Results

```
tests/test_ml_anomaly.py::test_detect_ml_anomalies_basic PASSED
tests/test_ml_anomaly.py::test_detect_ml_anomalies_disabled PASSED
tests/test_ml_anomaly.py::test_detect_ml_anomaly_too_few PASSED

3 passed in 4.97s
```

## Dependencies

- `app/engine/ml/schemas.py` — `MLAnomalyResult` dataclass (pre-existing)
- `sklearn.ensemble.IsolationForest`
- `sklearn.preprocessing.StandardScaler`
- `numpy`
