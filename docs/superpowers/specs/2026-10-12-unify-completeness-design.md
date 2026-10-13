# US-04 — Unify Completeness Calculation

Date: 2026-10-12
Status: Approved (design) — pending spec review

## Problem

Completeness is displayed in several places and each place must produce
the **same** number for the same (hospital, month):

- the analysis engine (`app/engine/pipeline.py` → `run_full_analysis`),
  whose result is persisted on `QualityScore.completeness` and served by
  `/reports`;
- the dashboard KPI cards / ranking / radar
  (`dashboard._recalc_completeness`);
- the indicator-config / group toggle recalculation
  (`indicator_config._recalc_hospital_scores`);
- the `POST /dashboard/recalculate-completeness` button;
- the **component-diagnostics drilldown**
  (`dashboard.component_diagnostics`).

A prior "rev-2" effort routed most of these through
`pipeline.compute_hospital_completeness(session, hospital_id, month)`, but
divergence remains:

1. `scoring._calc_completeness` is a **separate but hand-kept-identical**
   implementation of the same formula (fed `active_indicator_count` +
   `covered_codes` by the engine). Parity is maintained by discipline, and
   even the regression tests re-implement the formula
   (`test_recalc_scores._engine_style_completeness`).
2. `dashboard.component_diagnostics` (lines ~1358-1391) computes the
   completeness **number** over **all** indicators minus disabled/covered
   — i.e. **Optional indicators are in the denominator**. Whenever a
   hospital has Optional indicators this value disagrees with the KPI
   cards (which use Required only). This is a real, observable violation
   of the acceptance criteria.
3. `quality.run_quality_analysis` computes completeness from a bare
   `active_indicator_count` count.
4. The formula subtracts every covered code from the denominator without
   intersecting with Required, so a covered **Optional** code can shrink
   the denominator.

Acceptance criteria (from the ticket):

- Pipeline, Dashboard and Reports give the same completeness.
- Optional indicators do not affect the denominator.
- Zero counts as Filled.
- Missing counts as Missing.
- There is no difference between calculation methods.

## Decisions (agreed with requester)

- **Scope:** full — one pure core shared by the DB wrapper (pipeline),
  the engine scoring path, `run_quality_analysis`, and the dashboard
  drilldown.
- **Contract:** a DB-free, code-based core function. `calculate_quality_score`
  stops computing completeness itself and delegates to the core.
- **audit/explain:** `find_data_problems(values, db)` is left **as-is**.
  It already calls the shared `compute_covered_codes`; its empty
  disabled-set controls which raw `None` rows are flagged as problems, a
  separate concern from the completeness number. Its signature is pinned
  by `tests/test_ui_doctrine_docs.py`.
- **reports.py:** serves stored `QualityScore.completeness`; no change
  needed — it matches automatically once the engine is unified.

## Design

### 1. The one core function (DB-free)

New in `app/engine/quality/scoring.py`, exported via
`app/engine/quality/__init__.py`:

```python
def compute_completeness(values, required_codes, covered_codes=None) -> float:
    required = set(required_codes or ())
    covered  = set(covered_codes or ()) & required
    denom = len(required) - len(covered)
    if denom <= 0:
        return 0.0
    filled = sum(1 for v in values.values() if v is not None)
    return min(1.0, filled / denom)
```

Semantics (the four concepts the ticket asks to distinguish):

- **Required** — denominator base: indicators whose effective state is
  enabled **and** `requirement_type == 'Required'` (plus the existing
  auto-disable / synthetic-code exclusions already applied by
  `pipeline.get_required_indicator_ids`).
- **Optional** — never enters the denominator (excluded from
  `required_codes`), but a filled Optional value still counts in the
  numerator (existing rev-2 doctrine, capped at 100%).
- **Covered** — absent sibling codes explained by a reported total; removed
  from the denominator **only when Required** (`& required`), so a covered
  Optional code can never shrink it.
- **Filled** — non-`None` values; `0` is Filled, `None` is Missing.

Returns a fraction in `[0, 1]`; callers multiply by 100 and round.

Behaviour preserved for existing edge cases: empty/zero denominator → `0.0`;
`min(1.0, …)` cap; `test_quality_score` percentage outputs unchanged modulo
the new argument type.

### 2. `calculate_quality_score` delegates

In `app/engine/quality/scoring.py`, replace the
`active_indicator_count: int` parameter with `required_codes: set` (keep
`covered_codes`), and replace the call to `_calc_completeness` with
`compute_completeness(values, required_codes, covered_codes)`. Delete
`_calc_completeness`. Only `pipeline.py` and `tests/test_quality_score.py`
call this function.

### 3. Pipeline

`app/engine/pipeline.py`:

- Add `get_required_indicator_codes(session, hospital_id, month) -> set[str]`
  that maps `get_required_indicator_ids(...)` to indicator codes.
- `compute_hospital_completeness` composes the core:
  `compute_completeness(values, get_required_indicator_codes(...), covered_codes) * 100.0`.
- `_compute_full_analysis` builds `required_codes` via the new helper (with a
  fallback of "all non-synthetic codes − disabled" if the helper raises) and
  passes it to `calculate_quality_score`.
- `run_quality_analysis` (`app/engine/quality/__init__.py`) accepts
  `required_codes` / `covered_codes` and delegates. It has no production
  callers (only exported).

### 4. Dashboard `component_diagnostics` (the actual bug)

`app/api/dashboard.py` lines ~1358-1391: the batch path prefetches
`Indicator.requirement_type` into a per-id map, and the completeness number
becomes `required ∧ ¬disabled ∧ ¬covered` — computed with the shared core
(or a byte-identical inline expression) — replacing
`all_ind_ids - disabled - covered`. Missing-indicator **lists** keep using
all enabled indicators for display; only the **number** becomes
required-based. Line ~1439 ("covered children treated as filled") stays as
display logic.

### 5. Out of scope

- `find_data_problems` (audit/explain) — unchanged.
- `reports.py` — unchanged (reads stored values).
- No schema/migration changes.

## Testing

- Rewrite `tests/test_quality_score.py` for the new argument type and add
  core unit tests:
  - Required-only denominator; Optional never affects it.
  - `0` counts as Filled; `None` counts as Missing.
  - Covered Required code lowers denominator; Covered Optional does **not**.
  - Zero/empty denominator → `0.0`; result capped at `1.0`.
- New `tests/test_completeness_parity.py`: a fixture containing Required,
  Optional, a covered-by-total sibling, an explicit zero, and a genuine
  missing value; assert equality across:
  - stored `QualityScore.completeness` written by `run_full_analysis`;
  - `compute_hospital_completeness`;
  - `GET /dashboard/kpi` completeness;
  - `GET /dashboard/component-diagnostics` completeness;
  - `indicator_config._recalc_hospital_scores` output.
- Simplify `tests/test_recalc_scores.py::_engine_style_completeness` to call
  the shared core instead of re-implementing the formula.

## Rollout / risk

- Behaviour change is limited to the covered-**Optional** denominator edge
  and the `component_diagnostics` Optional-in-denominator bug — both
  corrections required by the acceptance criteria. Hospitals with no
  Optional indicators, and all existing parity tests, are unaffected.
- No persisted data is migrated; stored completeness values are rewritten
  on the next analysis / recalc (both already exist).
