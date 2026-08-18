# Task 2: Implement Historical Data Retrieval

## Status: DONE

## What was implemented

Two functions added to `app/engine/root_cause.py`:

1. **`get_historical_data()`** — Retrieves historical data for a specific indicator at a hospital. Queries `indicator_values` joined with `indicators`, `quality_scores`, and `confidence_scores`, plus a subquery for rule failure rate. Returns `List[MonthDataPoint]` ordered by month ascending.

2. **`get_peer_historical_data()`** — Retrieves historical data for peer hospitals (same `hospital_type_id`, excluding the input hospital, active only). Delegates to `get_historical_data()` per peer. Returns `Dict[str, List[MonthDataPoint]]` keyed by hospital name.

## What was tested

- `test_get_historical_data` — Creates a hospital, an indicator, and 3 months of data. Verifies correct count, types, and month ordering.
- `test_get_peer_historical_data` — Creates 3 hospitals of the same type, adds indicator data for each, then verifies that the peer function returns data for the 2 peers (excluding the input hospital).

## Test Results

```
tests/test_root_cause.py::test_get_historical_data PASSED
tests/test_root_cause.py::test_get_peer_historical_data PASSED
```

Full suite: **38/38 passing**, output pristine (only deprecation warnings from dependencies).

## Files changed

- `app/engine/root_cause.py` — Added `get_historical_data()` (lines 140-184) and `get_peer_historical_data()` (lines 187-218)
- `tests/test_root_cause.py` — Added `test_get_historical_data` (lines 456-484) and `test_get_peer_historical_data` (lines 487-517)

## Self-review findings

- Implementation adapted from task brief to match actual DB schema: `IndicatorValue` uses `indicator_id` (FK to `indicators` table) not a bare `indicator_code` column. Tests were similarly adapted to create `Indicator` records and use `indicator_id`.
- Uses `strftime('%Y-%m', 'now', :offset)` instead of `date('now', :offset)` for SQLite month comparison — correct for this database engine.
- No overbuilding, follows existing code patterns (raw SQL with `text()`, same style as other functions in the file).

## Commit

- `97c1967` feat(root-cause): add historical data retrieval functions
