# System Control: Hide Forecast/Explanation Sentences

## Date
2026-08-30

## Status
Approved design (brainstorming complete)

## Problem
On the Intelligent Analysis (التحليل الذكي) / comprehensive report screen, narrative
"forecast/explanation sentences" are always shown. Admins want a System Control option to
hide these sentences app-wide, so they appear only for super admin users.

## Scope (user-confirmed)
Hide the per-hospital forecast narrative lines and the statistical disclaimer sentences:

- per-hospital forecast lines, e.g.
  `مستشفى مدينة الأمل/ PRCS: current 0.90 -> predicted 0.80 (critical)`
- disclaimer sentences, e.g.
  `(Prediction is a statistical estimate, not certainty.)`

All **tables, charts, KPIs, numbers remain visible**. Only the prose/explanation text is hidden.
Super admin always sees the text regardless of the toggle.

## Enforced mechanism (user-confirmed)
**Server-side filtering.** The report API response omits the narrative/disclaimer sentences for
non-super-admin users when the toggle is ON. The text never reaches the browser.

## Design

### 1. New SystemControl setting
New row in `system_settings` with the existing `SystemSetting` model, keyed into the same
`/config/control/settings` GET + PUT endpoints as `auto_disable_null_indicators`.

- Key: `hide_explanatory_text`
- Default: `false`
- GET `/config/control/settings` returns it with the other control settings.
- PUT `/config/control/settings` persists it.

Files:
- `app/api/config_api.py` — add key retrieval/save (alongside `CONTROL_KEY`/`LOGGING_KEY` handling).

### 2. API endpoint passes the user + resolves permission
The comprehensive report endpoint injects the current user and resolves whether explanations
are allowed for this request.

Files:
- `app/api/comparative.py` — add `user=Depends(get_current_user)` to
  `GET /comparative/comprehensive-report/{month}`; compute
  `can_view_explanations = user.is_superuser or not hide_explanatory_text`.
- Pass `include_explanations=can_view_explanations` into `generate_comprehensive_report`.
- Add `"can_view_explanations": can_view_explanations` to the API response body.

### 3. Generator strips narrative when explanations disabled
`generate_comprehensive_report` gains `include_explanations: bool = True`.

When `False`, the assembled **`sections`** prose (the 17 narrative strings) are set to `""`.
The structural `data` (analytics, indicators, charts, KPIs, decision board) is left untouched.
`report == "\n\n".join(sections[...])` becomes `""` — the Butterfly contract is preserved.

Files:
- `app/engine/comparative/report_generator.py` — signature + strip after local/AI section
  assembly, before caching.

### 4. Cache handling (preserves backward-compat contract)
The report cache key format `comparative_report_v2:{month}:{lang}` stays **unchanged**.

The full (richest) report is always stored in cache. Stripping is applied **after a cache hit**,
at response time, only when `include_explanations` is false:

- On cache hit: load the stored full report; if `include_explanations` is false, strip `sections`
  + `report` from the returned dict. Never mutate the cached copy.
- On cache miss: generate full, store full; then strip the returned dict if needed.

Rationale: prestoring only the stripped variant would poison the shared cache for super admins
(the full narrative would be lost). Keeping the full report cached and filtering on read
preserves the richest data and requires no key-format change.

Files:
- `app/engine/comparative/report_cache.py` — nothing to change (read-then-strip in generator).
- `app/engine/comparative/report_generator.py` — apply strip to both the freshly generated and
  the cache-hit paths.

### 5. API response flag for client-side disclaimers
Backend adds `can_view_explanations` to the response so the frontend can hide the **hardcoded**
`.bi-caution` disclaimer strings that live in JS constants (not in the response), e.g.
"Prediction is a statistical estimate, not certainty." and "Correlation does not imply causation."

Files:
- `app/api/comparative.py` — response body field.

### 6. Frontend rendering
The dashboard already renders tables/charts/KPIs from `data` independently of the narrative
`sectionShell` text; `sectionShell` suppresses an empty narrative. Applying the flag:

- `static/js/smart/report-sections.js` — skip rendering the `.bi-caution` disclaimer blocks when
  `can_view_explanations` is false.
- `static/js/smart/report.js` — when `can_view_explanations` is false, the full-screen prose
  report view is not shown; dashboard sections/cards/decision board remain visible.
- Section narrative comes from the stripped response (empty), so `sectionShell` renders headers/
  structure without prose.

### 7. System Control UI
New toggle labeled "إخفاء النصوص التوضيحية" (hide explanatory sentences) in the settings panel,
wired to the same `/config/control/settings` endpoints as the existing control toggles.

Files:
- `static/js/settings.js` — load/save the new setting (`loadAllSettings`, `saveAllSettings`,
  `showSettingsTab`).
- `static/js/admin.js` / HTML for the admin tab UI.

## Wording / statistical rules (unchanged)
- Never correlation = causation, Granger = causality, forecast = certainty.
- Anomaly Score remains separate from Indicator Deviation.
- Current Risk remains separate from Forecast Risk.
- "ارتباط زمني إحصائي" styling retained where text IS shown (super admin).
- Existing expected sentences are untouched for users who can see them.

## Scope restriction
Only:
- `app/api/config_api.py`
- `app/api/comparative.py`
- `app/engine/comparative/report_generator.py`
- `static/js/smart/report-sections.js`
- `static/js/smart/report.js`
- `static/js/settings.js`
- `static/js/admin.js` + admin tab HTML

Do NOT modify unrelated modules.

## Backward-compat contract (Butterfly)
- `report == "\n\n".join(sections[key] for key in SECTIONS)` — preserved (both become `""`
  when stripped).
- Cache prefix `comparative_report_v2:` — unchanged.

## Testing
- Backend: `python -m pytest tests/test_butterfly_report.py tests/test_chart_migration.py tests/test_auth.py -q --tb=short` (expect 79 pass).
- New checks: non-super-admin + toggle ON -> `sections`/`report` empty, `data` intact,
  `can_view_explanations` false. Super admin -> full narrative, `true`.
- Frontend commit hook (JS syntax + ES module import validation) must pass; `node --check` on
  any edited JS.
- `tests/test_smart_core_js.py` has 3 pre-existing failures on clean `main` — not a regression;
  do not chase.
