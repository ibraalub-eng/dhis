## Task 6: Integrate Historical & Comparative Analysis into Main Function

### Status: DONE

### What was implemented
Modified `generate_root_cause_analysis()` in `app/engine/root_cause.py` to:
1. Accept new parameters: `include_history`, `compare_peers`, `months_back`
2. Build causal nodes from rule failures and quality drivers
3. Build causal chains from nodes using `build_causal_chains()`
4. Perform peer comparisons if requested using `identify_peer_groups()` and `calculate_peer_comparison()`
5. Calculate historical trends if requested using `get_historical_data()` and `calculate_trend()`
6. Generate Arabic summary using new `_generate_arabic_summary()` helper
7. Return enhanced `RootCauseReport` with new fields: `causal_tree`, `causal_chains`, `historical_trends`, `peer_comparisons`, `summary_arabic`

### TDD Evidence

**RED:**
```
tests/test_root_cause.py::test_generate_root_cause_with_historical FAILED
TypeError: generate_root_cause_analysis() got an unexpected keyword argument 'include_history'
```

**GREEN:**
```
tests/test_root_cause.py::test_generate_root_cause_with_historical PASSED
```

### Test Results
- 47/47 root cause tests passing
- 427/427 full suite tests passing

### Files Changed
- `app/engine/root_cause.py`: Added new fields to `RootCauseReport`, modified `generate_root_cause_analysis()`, added `_generate_arabic_summary()`
- `tests/test_root_cause.py`: Added `test_generate_root_cause_with_historical`

### Self-Review Findings
- All requirements fully implemented
- Code follows existing patterns and conventions
- No overbuilding or unnecessary features
- Test verifies actual behavior with database interactions
- Backward compatible (existing tests still pass)

### Commit
- `701f94b` feat(root-cause): integrate historical and comparative analysis into main function