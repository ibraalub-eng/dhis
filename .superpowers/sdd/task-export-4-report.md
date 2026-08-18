# Task 4 Report: Export Buttons on Both Pages

## Status: DONE

## What I implemented

Added a "تصدير البيانات" (Export Data) button + scope selector to the controls bar of both
frontend pages, wired to `GET /export/full-data` from Task 3:

- `static/tabs/smart-analytics.html`: inserted an export controls `div` (select `#smart-export-scope`
  + button `#smart-export-btn` with `onclick="smartExportData()"`) immediately after the refresh
  button `</div>` (line 25) and before the `<div style="align-self:flex-end;">` containing `#smart-status`.
- `static/tabs/comparative.html`: inserted an export controls `div` (select `#comparative-export-scope`
  + button `#comparative-export-btn` with `onclick="comparativeExportData()"`) immediately after the
  generate button `</div>` (line 41) and before the `<div style="align-self:flex-end;">` containing `#comparative-status`.
- `static/js/smart-analytics.js`: appended `async function smartExportData()` at the end of the file
  (uses `#smart-status`, `smartShowLoading()`/`smartHideLoading()`, `smartCurrentMonth` /
  `#smart-month-select` fallback; `base` falls back to `''` since no `#apiBase` element exists).
- `static/js/comparative.js`: appended `async function comparativeExportData()` at the end of the file
  (uses `comparativeCurrentMonth` / `#comparative-month`, `reportLang`, `compShowLoading()`/`compHideLoading()`,
  and `showAlert(...)` for errors).
- `tests/test_export.py`: appended the 4 frontend-structure tests exactly as the brief specified.

Both HTML inserts and both JS appends are byte-for-byte the code from the brief (verified via `git diff`
during self-review).

## TDD evidence

### RED (Step 2) — new tests fail before implementation
```
> python -m pytest tests/test_export.py -k "page_has_export or js_has_export" -q
4 failed, 19 deselected, 13 warnings in 7.90s
  FAILED tests/test_export.py::test_smart_page_has_export_button
  FAILED tests/test_export.py::test_comparative_page_has_export_button
  FAILED tests/test_export.py::test_smart_js_has_export_handler
  FAILED tests/test_export.py::test_comparative_js_has_export_handler
```
Confirmed: buttons/handlers did not exist yet.

### GREEN (Step 7) — tests pass after implementation
```
> python -m pytest tests/test_export.py -k "page_has_export or js_has_export" -q
4 passed, 19 deselected, 13 warnings in 5.45s
```

### Full export suite (Step 8)
```
> python -m pytest tests/test_export.py -q
23 passed, 2361 warnings in 13.56s
```
(23 total = 19 from Tasks 1-3 + 4 new frontend tests. Real count confirmed.)

### Regression suites (Step 9)
```
> python -m pytest tests/test_comparative.py tests/test_smart_analytics.py -q
105 passed, 10003 warnings in 92.96s (0:01:32)
```
Existing behavior unchanged.

## Files changed

- `static/tabs/smart-analytics.html` (+7)
- `static/tabs/comparative.html` (+7)
- `static/js/smart-analytics.js` (+26)
- `static/js/comparative.js` (+26)
- `tests/test_export.py` (+42)

## Commit

```
2a8d2de feat: add export data buttons to smart and comprehensive report pages
```
Only the 5 task files were staged. Pre-existing `.superpowers/sdd/*` working-tree changes
(CRLF/LF line-ending noise) were left untouched and unstaged.

## Self-review findings

- Spec coverage: both pages have export button + scope selector (`current`/`all`), both handlers call
  `/export/full-data?month=...&lang=...`, consume the Task 3 endpoint. Verified against the brief verbatim.
- Anchors verified before editing: refresh div lines 23-25, `#smart-status` div line 26;
  generate div lines 39-41, `#comparative-status` div line 43. All matched.
- No overwrite/reorder of existing JS — both handlers appended at EOF.
- No new dependencies; `bs4` was already imported in `tests/test_export.py`.
- TDD cycle followed: tests written first, failed (RED), implemented, passed (GREEN), regression green.

## Concerns

- None blocking. Minor note: the handlers use `document.getElementById('apiBase')?.value` which resolves
  to `''` (no such element on either page), producing a relative URL — correct as the brief states.
