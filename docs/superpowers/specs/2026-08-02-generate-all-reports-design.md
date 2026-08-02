# Design: Generate Comprehensive Reports for All Months

**Date:** 2026-08-02

## Goal

Enable generating the AI comprehensive report (التقرير الشامل) for **all available months** at once — not month by month — from both the smart analytics screen (التحليل الذكي) and the comprehensive report screen (التقرير الشامل), then exporting the complete package via the existing export flow.

## Context

The export feature (committed) already provides a "تصدير البيانات" button with a scope selector (الشهر المحدد / كل الأشهر) on both screens, calling `GET /export/full-data?month=YYYY-MM|all&lang=ar|en`. The exported JSON includes `analysis[month].comprehensive_report` **only from the persistent cache** (`get_stored_report`) — the export never triggers AI generation. Consequently, months without a previously generated report appear with `comprehensive_report: null` in the export.

This feature fills that gap: a user can generate comprehensive reports for all months in one action (with progress), after which the existing "كل الأشهر" export includes every month's AI report text.

## Approach

Approach A (approved): a **background task with progress** (`app/tasks.py` — the established in-memory task system already used by `file_ops`, `reports`, and `analysis`) that generates missing reports sequentially, plus a new endpoint to start it and existing `GET /tasks/{task_id}` polling for progress. The existing export flow is unchanged and picks up the newly cached reports.

## Architecture

### Backend

**New engine function — `app/engine/export.py`:**

`generate_reports_for_months(session, months, lang, progress=None) -> dict`

- For each month in `months`:
  - If `get_stored_report(session, month, lang)` is not None → skip (no AI consumed, no smart analytics computed).
  - Else call `generate_comprehensive_report(session, month, lang)` (from `app/engine/comparative/report_generator.py`) — it computes smart analytics, calls the LLM (with local fallback), and stores the result in the cache.
  - Each month is wrapped in its own `try/except` — a single month's failure must not stop the rest.
  - After each month, call `progress(done, total)` if provided (for progress reporting).
- Returns `{"total": len(months), "generated": n, "skipped": m}` (n + m == total).

**New endpoint — `app/api/export.py`:**

`POST /export/generate-all-reports?lang=ar|en` → `200 {task_id, months, count}`
- `lang` is a `Query` param with `pattern="^(ar|en)$"` (invalid → 422).
- Compute months via `_get_available_months(db)`. If empty → `404` with bilingual message (same style as the export's `NoDataError` message).
- `task_id = create_task("Generate All Reports", lambda: None)`.
- Launch a daemon thread: `threading.Thread(target=run_task, args=(task_id, _run_generate_all, task_id, months, lang), daemon=True).start()` (exact pattern from `app/api/file_ops.py:242`).
- Return `{"task_id": task_id, "months": months, "count": len(months)}`.

**Worker — `app/api/export.py`:**

`_run_generate_all(task_id, months, lang)`
- Create a dedicated session: `bg_db = SessionLocal()` (background thread must not share the request session — same pattern as `file_ops.py:223`).
- `return generate_reports_for_months(bg_db, months, lang, progress=lambda done, total: set_progress(task_id, int(done / total * 100)))`.
- Close `bg_db` in `finally`.
- `set_progress`/`set_status` imported inside the worker to avoid circular imports (repo pattern). `run_task` sets status done/error and stores the returned summary as `result`.

Polling: existing `GET /tasks/{task_id}` in `app/main.py:251` returns `{status, progress, result, error}`.

### Frontend

Both `static/tabs/smart-analytics.html` and `static/tabs/comparative.html`, in the controls bar next to the existing export controls:

- Button "توليد تقارير كل الأشهر":
  - `#smart-generate-all-btn` → `onclick="smartGenerateAll()"`
  - `#comparative-generate-all-btn` → `onclick="comparativeGenerateAll()"`
  - Styled consistently with the export button (same gradient/border style).
- Progress element `#smart-gen-progress` / `#comparative-gen-progress`: a small progress bar + text "X من Y شهر".

**Handlers appended to `static/js/smart-analytics.js` and `static/js/comparative.js`:**

`smartGenerateAll()` / `comparativeGenerateAll()`:
1. `lang` = `'ar'` (smart) / `reportLang` (comparative).
2. `POST /export/generate-all-reports?lang=<lang>` → `{task_id, months, count}`.
3. Disable the button (prevent duplicates); show the progress element ("جاري توليد التقارير..." / "Generating reports...").
4. Poll `GET /tasks/<task_id>` every ~2 s: update progress bar + "X من Y شهر" from `task.progress` (and `months.length`).
5. On `status === 'done'`: show success (e.g. "تم توليد تقارير N شهر" / "Generated reports for N months"; if `generated === 0`: "التقارير موجودة بالفعل" / "Reports already exist"), hide progress, re-enable button.
6. On `status === 'error'`: show the error via `#smart-status` text (smart) or `showAlert(..., 'danger')` (comparative), hide progress, re-enable button.
7. Language of messages follows the page language (smart is Arabic; comparative uses `reportLang`).

The existing export button is unchanged: after generation completes, the user selects "كل الأشهر" and downloads the full package including every month's report.

### Error Handling

- No available months → 404 bilingual.
- Invalid lang → 422 (FastAPI pattern).
- Per-month generation failure → logged, skipped, others continue; the failed month appears in the export as before (`comprehensive_report: null`).
- Whole-task failure → task `status: "error"`, `error` message shown in the UI; button re-enabled.
- Duplicate start → prevented client-side by disabling the button while running. (No backend concurrency guard — YAGNI.)

## Testing

All new tests in `tests/test_export.py`.

1. **`generate_reports_for_months` (engine, direct with `db_session` fixture):**
   - Generates AI reports for months without a cached report (patch `app.engine.comparative.report_generator._call_api` to return text; assert `get_stored_report(session, month, lang)` is non-None afterwards and summary counts are correct).
   - Skips months that already have cached reports (seed via `store_report`; assert `_call_api` call count covers only the missing months).
   - Progress callback invoked with correct counts.
   - A failing month doesn't stop the others (patch `generate_comprehensive_report` to raise for one month; assert other months still generated).
2. **Endpoint `POST /export/generate-all-reports`:**
   - Success: returns `{task_id, months, count}` (patch `threading.Thread` so the background worker does not run against the real DB during the test).
   - `404` when no months available (delete hospital/indicator data).
   - `422` for invalid lang.
3. **Frontend structure:** buttons, progress elements, and handler functions exist in both pages.
4. **Regression:** `python -m pytest tests/test_export.py -q`, `python -m pytest tests/test_comparative.py tests/test_smart_analytics.py -q`.

## Non-Goals

- No PDF/Word/Human-readable report documents — the deliverable is the existing JSON export now including all months' AI report text.
- No "force regenerate" (overwrite existing cached reports) in v1 — only missing reports are generated, preserving AI quota.
- The export endpoint itself still never triggers AI generation — generation is an explicit, separate user action.
- No report viewer for browsing across months in the UI.
