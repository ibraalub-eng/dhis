## Task 10: Update AI Init to Use Enhanced Functions

### Summary
Updated `generate_root_cause_ai()` in `app/plugins/ai/__init__.py` to detect `historical_trends` or `peer_comparisons` in `report_data` and use the enhanced prompt (`_build_root_cause_prompt_enhanced`) and enhanced fallback (`_local_root_cause_fallback_enhanced`) when available, falling back to basic versions otherwise.

### Files Modified
- `app/plugins/ai/__init__.py` — Added imports for enhanced functions, added `has_historical` detection, wired enhanced prompt/fallback through all paths
- `tests/test_ai_providers.py` — Added 2 tests for enhanced and basic routing

### Implementation
The key change: `generate_root_cause_ai()` now checks `report_data.get("historical_trends")` and `report_data.get("peer_comparisons")` to determine if historical/comparative data is present. When present:
- Uses `_build_root_cause_prompt_enhanced()` for AI prompt construction
- Uses `_local_root_cause_fallback_enhanced()` for local fallback

When absent, falls back to the basic versions. This check is applied consistently across all 3 failure paths (AI disabled, API key missing, API call failed) and the prompt selection path.

### TDD Cycle
- RED: Test `test_generate_root_cause_ai_uses_enhanced_prompt_with_historical_data` failed (got basic fallback results instead of enhanced)
- GREEN: Implementation added, all 3 AI tests pass
- Full suite: 436 passed, 1 pre-existing failure (PermissionError, unrelated)

### Commit
`27c192d` — feat(ai): update generate_root_cause_ai to use enhanced functions when historical data is available
