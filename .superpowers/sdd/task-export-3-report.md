# Task Export-3 Report: Export API Endpoint

**Status:** DONE
**Commit:** `4580f47` — `feat: add full data export API endpoint`

## What I implemented

1. **`app/api/export.py`** (new) — FastAPI router `GET /export/full-data?month=YYYY-MM|all&lang=ar|en` returning a `StreamingResponse` JSON attachment. It consumes `build_full_export` / `NoDataError` from `app.engine.export`. Written verbatim per the brief, including the explicit `from fastapi.responses import StreamingResponse` import. `lang` uses `pattern="^(ar|en)$"` (422 on invalid), `month` is required (`Query(...)`). `NoDataError` → 404 with its message; any other exception → 500.
2. **`app/main.py`** — appended `, export as export_router` to the `app.api` import list at line 15 (after `comparative as comparative_router`, before `# noqa: E402`), and added `app.include_router(export_router.router)` immediately after `app.include_router(comparative_router.router)` at line 245/246.
3. **`tests/test_export.py`** — appended the 5 endpoint tests verbatim from the brief.

No frontend files were created or modified (Task 4 scope).

## TDD evidence

### RED — `python -m pytest tests/test_export.py -k "endpoint" -q`
```
FFFFF
FAILED ... test_export_endpoint_returns_json_download - assert 404 == 200
FAILED ... test_export_endpoint_all_months - assert 404 == 200
FAILED ... test_export_endpoint_invalid_lang_422 - assert 404 == 422
FAILED ... test_export_endpoint_no_data_404 - AssertionError ... 'Not Found'
FAILED ... test_export_endpoint_serializes_without_error - assert 404 == 200
5 failed, 14 deselected, 628 warnings in 8.46s
```
As expected: router not registered → `404 Not Found`.

### GREEN — `python -m pytest tests/test_export.py -k "endpoint" -q`
```
5 passed, 14 deselected, 632 warnings in 11.01s
```

### Full suite — `python -m pytest tests/test_export.py -q`
```
19 passed, 2361 warnings in 13.67s
```
Confirms the brief's expected 19 total (14 from Tasks 1–2 + 5 new).

## Files changed

- `app/api/export.py` (new, +45 lines)
- `app/main.py` (1 import-line edit + 1 added `include_router` line)
- `tests/test_export.py` (+48 lines: 5 tests)

## Self-review findings

- Diff of `app/main.py` and `tests/test_export.py` verified against the brief: byte-for-byte matches for the test block and the import/include edits.
- `app/api/export.py` matches the brief exactly; confirmed `NoDataError` (`class NoDataError(ValueError)` at `app/engine/export.py:14`) and `build_full_export` (`app/engine/export.py:170`) exist as consumed.
- Endpoint pattern (APIRouter prefix + `Depends(get_db)`) consistent with existing routers e.g. `app/api/comparative.py`.
- Test 422 case exercises the `pattern="^(ar|en)$"` validation; 404 case confirms the `NoDataError` → HTTPException(404) path with the Arabic `لا توجد بيانات` message.
- `git status` after commit shows only pre-existing `.superpowers/sdd/` artifacts from prior tasks (untouched); commit staged only the three intended files.
- No lint/typecheck command exists in this repo (confirmed by pattern of prior tasks; tests are the verification mechanism).

## Concerns

- None for this task. Warnings in output (StarletteDeprecationWarning re httpx, Pydantic V2 class-based `config` deprecations, `datetime.utcnow` deprecation, sklearn `explained_variance_ratio_` RuntimeWarning) are pre-existing and unrelated to this change.
