# Task 5: Causal Chain Builder — Report

## What I Implemented

Added two functions to `app/engine/root_cause.py`:

1. **`find_correlated_factors(source, candidates)`** — Finds factors correlated with a source factor using Pearson correlation (|corr| > 0.6, p < 0.05), sorted by correlation strength.

2. **`build_causal_chains(nodes)`** — Builds causal chains by linking critical/high-severity rule factors with correlated quality and confidence factors. Returns chains sorted by confidence, with evidence lists, affected factors, impact estimates, and Arabic labels.

## Deviation from Task Brief

Changed `corr > 0.6` to `abs(corr) > 0.6` in `find_correlated_factors`. The test data has source values increasing [65, 67, 68, 70] while candidate values decrease [60, 58, 56, 55], producing a strong negative correlation (~-0.98). The test expects these to be found as correlated. Using absolute value captures strong relationships in either direction, which is the correct semantic for "find factors that move together."

## TDD Evidence

- **RED:** `pytest tests/test_root_cause.py::test_find_correlated_factors tests/test_root_cause.py::test_build_causal_chains -v` → 2 FAILED with `ImportError: cannot import name 'find_correlated_factors'` and `ImportError: cannot import name 'build_causal_chains'`
- **GREEN:** After implementation + abs() fix → 2 PASSED
- **Full suite:** 46/46 passed, 0 failures

## Files Changed

- `app/engine/root_cause.py` — Added `find_correlated_factors()` and `build_causal_chains()` (lines 380-461)
- `tests/test_root_cause.py` — Added `test_find_correlated_factors` and `test_build_causal_chains` (appended at end)

## Self-Review Findings

- The `abs(corr)` fix is the only deviation — it's a correctness improvement, not over-engineering.
- No edge cases missed: function handles insufficient data (min_len < 3), empty candidate lists, and no matches gracefully.
- Code follows existing patterns (scipy imports inline, dataclass usage consistent).

## Commit

`7232d3f` — `feat(root-cause): add causal chain builder with correlation analysis`
