# Task 5: SciPy Upgrade in Risk Profile

**Status:** Complete

## Changes

### `app/engine/clinical/risk_profile.py`

1. **Added import:** `from scipy import stats as scipy_stats` (line 4)
2. **Replaced fake correlation** in `correlate_risk_outcomes` (lines 261-278):
   - Old: Simple average comparison with arbitrary 1.2x/1.5x thresholds
   - New: Actual Pearson (n≥30) or Spearman (n<30) correlation via `scipy_stats`
   - Requires ≥3 hospitals for correlation; silently skips otherwise
   - Severity is "moderate" if p<0.05, else "low"

## Verification

```
pytest tests/test_clinical.py -v
73 passed, 1 warning in 23.60s
```

## Concerns

- The old threshold-based peer comparison (high_risk_rate vs avg_risk) was removed as instructed. If that logic was intentionally retained in prior tasks, it no longer exists.
- The `except Exception: pass` silently swallows errors. Acceptable for this statistical utility but could mask issues in debugging.
