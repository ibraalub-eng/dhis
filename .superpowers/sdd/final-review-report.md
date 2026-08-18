# Final Review Fix Report — "Full Data Export"

**Date:** 2026-08-02
**Commit:** `0f31019` — `fix: patch real AI entry point in export test and log export failures`

## What Changed

### Finding 1 — `test_export_never_calls_ai` patched a nonexistent symbol
- `tests/test_export.py`: changed the patch target from `app.engine.comparative.report_cache._call_api` (with `create=True`, against a nonexistent attribute — vacuously green) to `app.engine.comparative.report_generator._call_api`, the real LLM entry point imported into the report generator (matches the pattern in `tests/test_comparative.py:44`). Dropped `create=True`. Test body unchanged (`build_full_export(db_session, "all", "ar")`; `mock_api.call_count == 0`).

### Finding 2 — 500 handler leaked error text with no logging; 500 path untested
- `app/api/export.py`: added `import logging` and module-level `logger = logging.getLogger(__name__)`; added `logger.exception("Export failed")` **before** the `raise HTTPException(status_code=500, ...)` line so the traceback is preserved server-side. The `detail` message `f"خطأ في التصدير: {str(e)}"` is plan-mandated and kept as-is.
- `tests/test_export.py`: added `test_export_endpoint_500_on_engine_failure` — patches `app.api.export.build_full_export` with `side_effect=RuntimeError("boom")`, calls `client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})`, asserts `resp.status_code == 500`. The `client` fixture already uses `raise_server_exceptions=False`, so the 500 is returned instead of raised. (`patch` was already imported.)

## Test Commands & Output

`python -m pytest tests/test_export.py -q`
```
24 passed, 2484 warnings in 17.77s
```
(23 pre-existing tests + the corrected never-calls-ai test + the new 500 test.)

`python -m pytest tests/test_comparative.py tests/test_smart_analytics.py -q`
```
105 passed, 10003 warnings in 93.09s (0:01:33)
```

All green. Warnings are pre-existing deprecation/`sklearn` RuntimeWarnings unrelated to these changes.

## Self-Review

Diff contained only the two fixes (2 files, +12/−1). No other working-tree files (`.superpowers/sdd/*`) were staged.
