# Task 4 Report: Deduplicate Seeding Logic

## Summary
Successfully removed duplicated seeding logic from `app/main.py` and `tests/conftest.py` by refactoring `scripts/seed_indicators.py` and `scripts/seed_rules.py` to export reusable functions.

## Changes Made

### 1. `scripts/seed_indicators.py`
- Added `seed_indicators(session)` function that accepts a session parameter
- Preserves migration logic (adds new indicators not yet in DB)
- Original `seed()` function now delegates to `seed_indicators(session)`

### 2. `scripts/seed_rules.py`
- Modified `seed_rules(session=None)` to accept an optional session parameter
- When called without a session, creates one (CLI mode)
- When called with a session, uses it directly (library mode)

### 3. `app/main.py`
- Removed `_seed_indicators()` (~50 lines) and `_seed_rules()` (~25 lines)
- Imports `seed_indicators` and `seed_rules` from scripts
- Creates a session in lifespan and passes it to both functions
- Reduced from 188 lines to 115 lines

### 4. `tests/conftest.py`
- Removed local `_seed_indicators(session)` and `_seed_rules(session)` functions
- Imports and uses the shared functions from scripts
- Reduced from 141 lines to 106 lines

## Test Results
All 19 integration tests pass:
- TestUploadFlow: 5/5 passed
- TestAnalysisFlow: 6/6 passed
- TestFullPipeline: 4/4 passed
- TestRegressionIndicators: 4/4 passed
