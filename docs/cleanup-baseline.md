# Code Cleanup Baseline

Date: 2026-11-07
Branch: `chore/code-cleanup`
Base commit: `2f8845c` (main, includes the `.gitignore` commit)

This file records the "before" state for the dead-code / duplicate-code cleanup.
It is intentionally read-only evidence: it does not change application behavior.

## Scope

- `app/` — production Python
- `static/js/`, `static/tabs/` — frontend
- `tests/`, `scripts/` — test and tooling code
- Excluded: `.venv/`, `data/`, `backups/`, `.worktrees/`, generated artifacts, `qa-*/` reports

## Inventory

| Metric | Value |
|---|---|
| Python files (`app`, `tests`, `scripts`, `alembic`) | 403 |
| JavaScript files (`static/js`) | 40 |
| HTML tab partials (`static/tabs`) | 21 |
| Ruff issues in `app` | 265 |
| Ruff issues in `tests` + `scripts` | 447 |

### Ruff breakdown — `app`

| Code | Count | Auto-fixable |
|---|---|---|
| I001 unsorted-imports | 125 | yes |
| F401 unused-import | 33 | yes |
| W293 blank-line-with-whitespace | 28 | yes |
| B904 raise-without-from-inside-except | 21 | no |
| F841 unused-variable | 12 | no |
| B905 zip-without-explicit-strict | 12 | no |
| B007 unused-loop-control-variable | 10 | no |
| W292 missing-newline-at-end-of-file | 7 | yes |
| F541 f-string-missing-placeholders | 4 | yes |
| E701 multiple-statements-on-one-line-colon | 4 | no |
| E401 multiple-imports-on-one-line | 2 | yes |
| E712 true-false-comparison | 2 | no |
| B023 function-uses-loop-variable | 2 | no |
| E741 ambiguous-variable-name | 1 | no |
| B009 get-attr-with-constant | 1 | yes |
| F811 redefined-while-unused | 1 | yes |

### Ruff breakdown — `tests` + `scripts`

| Code | Count |
|---|---|
| I001 unsorted-imports | 254 |
| F401 unused-import | 79 |
| F541 f-string-missing-placeholders | 24 |
| W292 missing-newline-at-end-of-file | 20 |
| F841 unused-variable | 19 |
| B905 zip-without-explicit-strict | 17 |
| F811 redefined-while-unused | 9 |
| B007 unused-loop-control-variable | 9 |
| E401 multiple-imports-on-one-line | 7 |
| W293 blank-line-with-whitespace | 4 |
| E712 true-false-comparison | 2 |
| F821 undefined-name | 2 |
| B033 duplicate-value | 1 |

## Static checks (baseline, all green)

| Check | Result |
|---|---|
| `python -m compileall app alembic tests` | OK |
| `python -c "import app.main"` | OK |
| `node scripts/validate-imports.js` | OK (40 files) |
| `node --check` on every `static/js/**/*.js` | OK (0 failures) |
| `python scripts/check_agents.py` | OK (6/6) |

## Tests (baseline)

- Collection: **3770 tests**.
- Focused regression run (pipeline, confidence, quality, rules, smart, root cause,
  dashboard trends, config resolver, A3.5 suites): **626 passed** in 24:42 on the
  same code as this branch's base.
- Full local suite is not run per cleanup step: at the observed rate it takes
  roughly 2–2.5 hours. It belongs in CI and in the final verification pass.

## Known findings to carry into later phases

1. **Latent `F821`** in `tests/test_recalc_scores.py:998-999`:
   `_engine_style_completeness` references `Indicator` without importing it.
   The branch is only evaluated when `disabled_ids` is non-empty, which is why
   the current tests do not explode. Fix in Phase 1.
2. **Shadowed test** in `tests/test_comparative.py`:
   `test_report_cache_separated_by_lang` is defined at line 1269 and again at
   line 1339; the second definition hides the first. Review in Phase 3.
3. **Duplicate top-level function names** (14) — candidates only, behavior must
   be compared before merging:
   `cap_thin_peer`, `cap_zero_spread`, `effective_severity`, `max_level`
   (`quality_alerts.py` vs `anomaly/layered.py`);
   `canonical_code_index`, `canonical_formula_index`
   (`indicator_service.py` vs `quality_alerts.py`);
   `create_group`, `update_group`, `delete_group`
   (`indicator_groups.py` vs `menu.py`);
   `compute_rate` (3 modules); `generate_report` (`analysis.py` vs `reports.py`);
   `get_historical_data`, `set_status`, `toggle_indicator`.
4. **Repeated `app` fixture names** in tests (`test_hospital_authorization_scope.py`,
   `test_hospital_filtering.py`, `test_reanalyze_permissions.py`) reported as
   `F811`; verify they are intentional local fixtures before touching.
