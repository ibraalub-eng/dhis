# Task 1: Fix Critical Bugs — Report

## Bugs Fixed

### 1. `app/engine/clinical.py:368` — Wrong variable in percentage calculation
**Before:**
```python
return (numerator_total / denominator) * (100 if "%" in str else 1)
```
**After:**
```python
return (numerator_total / denominator) * (100 if "%" in th.unit else 1)
```
**Impact:** The `compute_rate` function was checking `"%" in str` (the built-in `str` type), which always evaluates to `False` because the string `"%"` is never a substring of the string representation of the `str` type. This meant percentage-based rates were never multiplied by 100, producing values 100x too small.

### 2. `app/engine/quality_score.py:61` — Missing `Severity` qualifier
**Before:**
```python
severity_weights = {.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
```
**After:**
```python
severity_weights = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
```
**Impact:** `{.HIGH: 3}` is a syntax error (invalid dict key). This would cause the `_calc_consistency` function to crash at runtime when called.

## Test Results
- **151 passed**, 0 failed (unchanged from baseline)
- All existing tests continue to pass

## Notes
- No git repository available in this workspace, so changes are uncommitted.
- Both fixes are minimal one-line corrections with no behavioral changes beyond fixing the bugs.
