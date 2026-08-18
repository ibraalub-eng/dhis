## Task 9: Enhance Local Fallback with Comparative Logic

### Summary
Added `_local_root_cause_fallback_enhanced()` to `app/plugins/ai/providers.py` that generates recommendations using historical trends and peer comparison data when AI is unavailable.

### Files Modified
- `app/plugins/ai/providers.py` — Added enhanced fallback function
- `tests/test_ai_providers.py` — Created test file

### Implementation
The enhanced fallback analyzes two data sources:
1. **Historical trends** — Detects rapidly declining (slope < -2) and gradually declining (slope < -1) indicators, generating appropriate priority recommendations
2. **Peer comparisons** — Identifies hospitals in bottom quartile (percentile < 25) and significant deviations from peer mean (|z| > 2)

Falls back to a general "Maintain Data Quality Standards" recommendation if no issues detected.

### TDD Cycle
- RED: Test failed with ImportError as expected
- GREEN: Implementation added, test passes
- All tests green

### Commit
`8f36544` — feat(ai): enhance local fallback with historical and comparative logic
