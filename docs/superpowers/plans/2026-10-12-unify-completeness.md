# Unify Completeness Calculation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every completeness calculation through one DB-free core function so pipeline, dashboard, reports and toggles always report the same number.

**Architecture:** Add a pure `compute_completeness(values, required_codes, covered_codes)` to `app/engine/quality/scoring.py`. `calculate_quality_score`, `pipeline.compute_hospital_completeness`, `quality.run_quality_analysis` and `dashboard.component_diagnostics` all delegate to it. `reports.py` and `find_data_problems` are unchanged (they already match).

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-12-unify-completeness-design.md`

## Global Constraints

- Run all tests with `.\.venv\Scripts\python.exe -m pytest`. The system `python` has no pytest.
- Run lint with `.\.venv\Scripts\python.exe -m ruff check <paths>`.
- Commit messages follow the repo's Conventional Commits style, e.g. `feat(quality): ...`.
- Doctrine (must hold in every task): **Required** = denominator base (`enabled ∧ requirement_type=='Required'`, synthetic codes excluded); **Optional** never enters the denominator but a filled Optional counts in the numerator; **Covered** is removed from the denominator **only when Required**; **Filled** = non-`None` (a value of `0` is Filled, `None` is Missing); empty/zero denominator → `0.0`; result capped at `1.0`.
- We are executing on a repo with pre-existing uncommitted changes in `static/js/*`, `static/tabs/layered.html`, `tests/test_layered_ui.py`. Do **not** stage or commit those files; stage only the files named in each task.
- Pre-existing unrelated failure: `tests/test_deploy_cloudrun_supabase.py::test_script_is_valid_bash` (bash missing on Windows). Ignore it.

---

### Task 1: The DB-free core function

**Files:**
- Modify: `app/engine/quality/scoring.py` (add function near the top, after imports)
- Modify: `app/engine/quality/__init__.py` (export it)
- Test: `tests/test_completeness_core.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `compute_completeness(values: Dict[str, float], required_codes, covered_codes=None) -> float` (fraction in `[0.0, 1.0]`), importable as `from app.engine.quality import compute_completeness`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_completeness_core.py`:

```python
"""Unit tests for the DB-free completeness core."""
from app.engine.quality import compute_completeness


def test_all_required_filled_is_one():
    values = {"a": 1.0, "b": 2.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0


def test_zero_counts_as_filled():
    assert compute_completeness({"a": 0.0}, {"a"}) == 1.0


def test_none_is_missing():
    # One of two required present -> 50%.
    assert compute_completeness({"a": 1.0}, {"a", "b"}) == 0.5


def test_optional_not_in_denominator():
    # required {a,b,c,d}; values fill required "a" and one OPTIONAL "opt" ->
    # filled 2 / denom 4 = 0.5. If Optional wrongly entered the denominator it
    # would be 2/5 = 0.4, so this pins denominator exclusion (the fill still
    # counts in the numerator per doctrine).
    values = {"a": 1.0, "opt": 9.0}
    assert compute_completeness(values, {"a", "b", "c", "d"}) == 0.5


def test_optional_fill_contributes_to_numerator():
    # Both required filled AND an extra optional fill -> capped at 1.0.
    values = {"a": 1.0, "b": 1.0, "opt": 5.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0


def test_covered_required_removed_from_denominator():
    # required {a,b,c}; c is covered-by-total; a filled -> 1/2.
    values = {"a": 1.0}
    assert compute_completeness(values, {"a", "b", "c"}, {"c"}) == 0.5


def test_covered_optional_does_not_shrink_denominator():
    # "z" is covered but NOT required -> denominator stays {a,b} = 2 -> 1/2.
    values = {"a": 1.0}
    assert compute_completeness(values, {"a", "b"}, {"z"}) == 0.5


def test_empty_denominator_returns_zero():
    assert compute_completeness({"a": 1.0}, set()) == 0.0
    assert compute_completeness({}, set()) == 0.0


def test_all_covers_collapse_to_zero():
    # Every required code is covered -> denominator 0 -> 0.0.
    assert compute_completeness({}, {"a", "b"}, {"a", "b"}) == 0.0


def test_result_capped_at_one():
    values = {"a": 1.0, "b": 1.0, "c": 1.0, "opt1": 1.0, "opt2": 1.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_completeness_core.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_completeness'`.

- [ ] **Step 3: Write minimal implementation**

In `app/engine/quality/scoring.py`, add after the imports (line 3):

```python
def compute_completeness(values: Dict[str, float], required_codes, covered_codes=None) -> float:
    """The single completeness formula, DB-free.

    numerator   = number of non-None values passed in `values` (a value of 0
                  counts as Filled; an Optional fill still counts here)
    denominator = required codes minus those covered-by-total that are
                  themselves required (covered Optional codes never shrink it)
    Empty denominator -> 0.0. Result is capped at 1.0.
    """
    required = set(required_codes or ())
    covered = set(covered_codes or ()) & required
    denom = len(required) - len(covered)
    if denom <= 0:
        return 0.0
    filled = sum(1 for v in values.values() if v is not None)
    return min(1.0, filled / denom)
```

In `app/engine/quality/__init__.py`, change line 19 to export it:

```python
from .scoring import calculate_quality_score, compute_completeness
```

and add `"compute_completeness",` to the `__all__` list (after `"calculate_quality_score",`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_completeness_core.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/quality/scoring.py app/engine/quality/__init__.py tests/test_completeness_core.py
git commit -m "feat(quality): add DB-free compute_completeness core"
```

---

### Task 2: `calculate_quality_score` and `run_quality_analysis` delegate to the core

**Files:**
- Modify: `app/engine/quality/scoring.py:6-67`
- Modify: `app/engine/quality/__init__.py:23-59`
- Modify: `app/engine/pipeline.py:161-200` (add helper) and `:433-445` (call site)
- Test: `tests/test_quality_score.py` (rewrite)

**Interfaces:**
- Consumes: `compute_completeness` from Task 1.
- Produces:
  - `calculate_quality_score(rule_results, values, anomaly_results, required_codes: set, config=None, covered_codes=None) -> Dict` (the 4th positional argument is now `required_codes`, a `set` of codes).
  - `run_quality_analysis(..., required_codes: Optional[set] = None, disabled_codes=None, score_config=None) -> Dict`.
  - `pipeline.get_required_indicator_codes(session, hospital_id, month) -> set[str]`.

- [ ] **Step 1: Rewrite the failing tests**

Replace the entire body of `tests/test_quality_score.py` with:

```python
"""Tests for quality score calculation (engine.quality)."""
from app.engine.quality import (
    calculate_quality_score,
    RuleResult,
    RuleStatus,
    Severity,
    RuleType,
)


def _rr(code, desc, status, sev, rtype=RuleType.LOGIC):
    return RuleResult(code, desc, status, sev, rtype, "detail")


def test_perfect_score():
    results = [_rr("R01", "Test rule", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] >= 70
    assert score["rule_compliance"] == 100.0


def test_all_fail():
    results = [
        _rr("R01", "Test", RuleStatus.FAIL, Severity.HIGH),
        _rr("R02", "Test", RuleStatus.FAIL, Severity.MEDIUM),
    ]
    values = {"2": 100.0, "6": 100.0}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] < 80
    assert score["rule_compliance"] == 0.0
    assert len(score["issues"]) == 2


def test_completeness_low():
    results = []
    values = {"2": 100.0}
    required = {str(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], required)
    assert score["completeness"] == 1.0


def test_completeness_high():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["completeness"] == 100.0


def test_completeness_zero_indicators():
    results = []
    values = {"2": 100.0}
    score = calculate_quality_score(results, values, [], set())
    assert score["completeness"] == 0.0


def test_completeness_covered_children_not_penalized():
    # required = total "2" + siblings "2.a", "2.b"; "2.b" missing but covered.
    results = []
    values = {"2": 100.0, "2.a": 100.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.b"})
    assert score["completeness"] == 100.0


def test_completeness_covered_counted_from_required():
    # 3 required, 1 filled, 1 covered -> denominator 2 -> 50%.
    results = []
    values = {"2": 10.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.a"})
    assert score["completeness"] == 50.0


def test_completeness_no_covered_change():
    results = []
    values = {"2": 10.0}
    required = {"2", "2.a", "2.b"}
    before = calculate_quality_score(results, values, [], required)
    after = calculate_quality_score(results, values, [], required, covered_codes=set())
    assert before["completeness"] == after["completeness"]


def test_score_clamps_to_100():
    results = [_rr("R01", "Test", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] <= 100.0


def test_score_never_negative():
    results = [_rr(f"R{i}", "Test", RuleStatus.FAIL, Severity.CRITICAL) for i in range(30)]
    values = {}
    score = calculate_quality_score(results, values, [], set())
    assert score["score"] >= 0.0


def test_outlier_penalty_zero():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["outlier_penalty"] == 0.0


def test_outlier_penalty_with_anomalies():
    from app.engine.anomaly import AnomalyResultData
    anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 3.5, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 2.8, True),
    ]
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, anomalies, set(values))
    assert score["outlier_penalty"] > 0.0


def test_issues_list_from_failures():
    results = [
        _rr("R001", "Total deliveries", RuleStatus.FAIL, Severity.HIGH),
        _rr("R041", "CS rate high", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    values = {"2": 100}
    score = calculate_quality_score(results, values, [], {str(i) for i in range(60)})
    assert any("R001" in i for i in score["issues"])
    assert any("R041" in i for i in score["issues"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_quality_score.py -q`
Expected: FAIL — most tests error because `calculate_quality_score` still expects an `int` and calls `_calc_completeness`.

- [ ] **Step 3: Update `calculate_quality_score`**

In `app/engine/quality/scoring.py`, replace the signature and the completeness line:

```python
def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    required_codes: set,
    config: Optional[Dict[str, float]] = None,
    covered_codes: Optional[set] = None,
) -> Dict:
```

and replace line 21 with:

```python
    completeness = compute_completeness(values, required_codes, covered_codes or set())
```

Then delete the whole `_calc_completeness` function (lines 60-67).

- [ ] **Step 4: Update `run_quality_analysis`**

In `app/engine/quality/__init__.py`, replace `active_indicator_count: int = 60,` (line 30) with:

```python
    required_codes: Optional[set] = None,
```

and replace the `calculate_quality_score(...)` call (lines 47-54) with:

```python
    score = calculate_quality_score(
        rule_results=rule_results,
        values=values,
        anomaly_results=anomaly_results or [],
        required_codes=required_codes or set(),
        config=score_config,
        covered_codes=covered_codes,
    )
```

- [ ] **Step 5: Add `get_required_indicator_codes` and fix the pipeline call site**

In `app/engine/pipeline.py`, add immediately after `get_required_indicator_ids` (after line 200):

```python
def get_required_indicator_codes(session, hospital_id, month):
    """Required indicators as CODES, for the DB-free compute_completeness core."""
    required_ids = get_required_indicator_ids(session, hospital_id, month)
    if not required_ids:
        return set()
    return {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(required_ids)).all()
    }
```

Replace the block at lines 433-445 with:

```python
    # Rev 2 denominator: enabled ∧ requirement_type=='Required' as codes, via
    # the shared helper. Falls back to all non-synthetic, non-disabled codes if
    # the helper fails (e.g. requirement_type column not yet migrated).
    try:
        required_codes = get_required_indicator_codes(session, hospital_id, month)
    except Exception:
        from app.indicators import SYNTHETIC_INDICATOR_CODES
        disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
        required_codes = {
            code for (iid, code) in session.query(Indicator.id, Indicator.code).all()
            if iid not in disabled_ids and code not in SYNTHETIC_INDICATOR_CODES
        }
    from app.config_utils import get_config_dict
    quality_config = get_config_dict(session, "quality")
    covered_codes = get_covered_child_codes(ctx, session)
    quality = calculate_quality_score(rule_results, values, anomaly_results, required_codes, quality_config, covered_codes=covered_codes)
```

- [ ] **Step 6: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_quality_score.py tests/test_pipeline.py tests/test_integration.py tests/test_layered_pipeline.py -q`
Expected: PASS. (Pipeline tests exercise the changed `calculate_quality_score` call end-to-end.)

- [ ] **Step 7: Lint and commit**

Run: `.\.venv\Scripts\python.exe -m ruff check app/engine/quality app/engine/pipeline.py tests/test_quality_score.py`
Expected: no new errors.

```bash
git add app/engine/quality/scoring.py app/engine/quality/__init__.py app/engine/pipeline.py tests/test_quality_score.py
git commit -m "refactor(quality): delegate scoring to compute_completeness core"
```

---

### Task 3: `compute_hospital_completeness` composes the core

**Files:**
- Modify: `app/engine/pipeline.py:203-231`
- Test: `tests/test_recalc_scores.py:986-1005` (simplify helper)

**Interfaces:**
- Consumes: `compute_completeness` (Task 1), `get_required_indicator_codes` (Task 2).
- Produces: `compute_hospital_completeness(session, hospital_id, month) -> float` (0-100), now implemented via the core (same signature as before).

- [ ] **Step 1: Simplify the reference helper test first**

In `tests/test_recalc_scores.py`, replace the body of `_engine_style_completeness` (lines 986-1005) with a call to the shared core:

```python
def _engine_style_completeness(db, hospital_id, month):
    """Reference completeness via the single shared core — every production
    site must agree with this."""
    from app.engine.pipeline import (
        get_disabled_indicator_ids,
        get_enabled_values_for_hospital_month,
        get_required_indicator_codes,
    )
    from app.engine.quality import compute_covered_codes, compute_completeness
    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    disabled_ids = get_disabled_indicator_ids(db, hospital_id, month)
    disabled_codes = {
        c for (c,) in db.query(Indicator.code)
        .filter(Indicator.id.in_(disabled_ids)).all()
    } if disabled_ids else set()
    covered = compute_covered_codes(values, disabled_codes, db)
    required_codes = get_required_indicator_codes(db, hospital_id, month)
    return compute_completeness(values, required_codes, covered) * 100.0
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recalc_scores.py -q`
Expected: PASS — the helper is equivalent to the current inline formula for these fixtures.

- [ ] **Step 2: Rewrite `compute_hospital_completeness` to use the core**

In `app/engine/pipeline.py`, replace `compute_hospital_completeness` (lines 203-231) with:

```python
def compute_hospital_completeness(session, hospital_id, month):
    """Rev-2 completeness for one hospital/month (0-100), via the single
    DB-free compute_completeness core — so the stored QualityScore rows, the
    dashboard KPI-card recalc and the indicator-config recalc cannot drift:

      numerator   = enabled non-null values (Optional fills included; capped)
      denominator = required indicators minus covered-by-total (required only)
    """
    from app.engine.quality import compute_covered_codes, compute_completeness
    values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
    disabled_codes = {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(disabled_ids)).all()
    } if disabled_ids else set()
    covered_codes = compute_covered_codes(values, disabled_codes, session)
    required_codes = get_required_indicator_codes(session, hospital_id, month)
    return compute_completeness(values, required_codes, covered_codes) * 100.0
```

- [ ] **Step 3: Run the completeness/recalc suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recalc_scores.py tests/test_covered_children.py tests/test_audit_quality_breakdown.py -q`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

Run: `.\.venv\Scripts\python.exe -m ruff check app/engine/pipeline.py tests/test_recalc_scores.py`
Expected: no new errors.

```bash
git add app/engine/pipeline.py tests/test_recalc_scores.py
git commit -m "refactor(pipeline): compose compute_hospital_completeness from the core"
```

---

### Task 4: Fix the `component_diagnostics` denominator

**Files:**
- Modify: `app/api/dashboard.py:1301-1308` (prefetch requirement type) and `:1379-1391` (the divergent loop)
- Test: `tests/test_recalc_scores.py` (extend the existing drilldown tests with an Optional case)

**Interfaces:**
- Consumes: `compute_completeness` (Task 1), `Indicator.requirement_type`.
- Produces: `GET /dashboard/component-diagnostics` completeness number is required-only and equals the KPI card.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recalc_scores.py`:

```python
def test_component_diagnostics_completeness_excludes_optional(client, db_session):
    """An Optional indicator WITH a value must not affect the drilldown
    completeness number — the KPI card and the drilldown must agree."""
    from app.models import QualityScore, Indicator, IndicatorValue
    from app.engine.pipeline import compute_hospital_completeness

    month = "2027-12"
    _insert_indicator_value(db_session, 1, month, "2", 100)
    _insert_indicator_value(db_session, 1, month, "2.a", 60)
    opt = db_session.query(Indicator).filter(Indicator.code == "16").first()
    db_session.add(IndicatorValue(hospital_id=1, month=month, indicator_id=opt.id, value=5))
    db_session.query(Indicator).filter(Indicator.id == opt.id).update(
        {"requirement_type": "Optional"}, synchronize_session=False)
    db_session.add(QualityScore(hospital_id=1, month=month, score=50.0))
    db_session.commit()

    resp = client.get(
        "/dashboard/component-diagnostics",
        params={"hospital_id": 1, "month_from": month, "month_to": month,
                "metric": "completeness"},
    )
    assert resp.status_code == 200
    comp = resp.json()["components"][0]
    engine = round(compute_hospital_completeness(db_session, 1, month), 1)
    assert comp["avg"] == pytest.approx(engine, abs=0.05), (
        f"drilldown {comp['avg']} != engine {engine}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recalc_scores.py::test_component_diagnostics_completeness_excludes_optional -q`
Expected: FAIL — the drilldown denominator currently includes the Optional indicator, so its value is lower than the engine's.

- [ ] **Step 3: Prefetch requirement type**

In `app/api/dashboard.py`, replace lines 1301-1308:

```python
    all_ind_rows = [
        r for r in db.query(
            Indicator.id, Indicator.code, Indicator.name, Indicator.requirement_type
        ).all()
        if r[1] not in _SYN_DG
    ]
    all_ind_ids = [r[0] for r in all_ind_rows]
    id_to_code = {r[0]: r[1] for r in all_ind_rows}
    code_to_id = {r[1]: r[0] for r in all_ind_rows}
    all_ind_names_map = {r[0]: r[2] for r in all_ind_rows}
    required_ind_ids = {
        r[0] for r in all_ind_rows if (r[3] or "Required") == "Required"
    }
```

- [ ] **Step 4: Replace the divergent completeness loop**

In `app/api/dashboard.py`, replace lines 1379-1391 with:

```python
    from app.engine.quality import compute_completeness as _completeness
    cp_vals = []
    for s in scores:
        try:
            disabled = _fast_disabled(s.hospital_id, s.month)
            covered = _fast_covered(s.hospital_id, s.month)
            iv_map = iv_index.get((s.hospital_id, s.month), {})
            values = {
                id_to_code[iid]: v
                for iid, v in iv_map.items()
                if iid in id_to_code and iid not in disabled and v is not None
            }
            required_codes = {
                id_to_code[iid] for iid in required_ind_ids
                if iid in id_to_code and iid not in disabled
            }
            covered_codes = {id_to_code[iid] for iid in covered if iid in id_to_code}
            if not required_codes:
                cp_vals.append(round(float(s.completeness or 0), 1))
                continue
            cp_vals.append(round(_completeness(values, required_codes, covered_codes) * 100, 1))
        except Exception:
            cp_vals.append(round(float(s.completeness or 0), 1))
```

- [ ] **Step 5: Run the drilldown/recalc tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recalc_scores.py tests/test_dashboard_ghost_rows.py tests/test_ui_dashboard_drilldown.py -q`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run: `.\.venv\Scripts\python.exe -m ruff check app/api/dashboard.py tests/test_recalc_scores.py`
Expected: no new errors.

```bash
git add app/api/dashboard.py tests/test_recalc_scores.py
git commit -m "fix(dashboard): use required-only completeness in component diagnostics"
```

---

### Task 5: Cross-site parity regression test

**Files:**
- Test: `tests/test_completeness_parity.py` (create)

**Interfaces:**
- Consumes: everything above plus `run_full_analysis`, `compute_hospital_completeness`, `_recalc_hospital_scores`, and the `/dashboard/kpi` + `/dashboard/component-diagnostics` endpoints.
- Produces: a regression test proving one fixture yields the same completeness everywhere.

- [ ] **Step 1: Write the test**

Create `tests/test_completeness_parity.py`:

```python
"""One fixture with Required, Optional, covered, zero and missing values must
produce the same completeness at every site (US-04)."""
import pytest


def _insert(db, hospital_id, month, code, value):
    from app.models import Indicator, IndicatorValue
    ind = db.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    db.add(IndicatorValue(hospital_id=hospital_id, month=month,
                          indicator_id=ind.id, value=value))


def test_completeness_parity_across_all_sites(client, db_session):
    from app.models import Indicator, QualityScore
    from app.engine.pipeline import compute_hospital_completeness, run_full_analysis
    from app.api.indicator_config import _recalc_hospital_scores

    month = "2028-01"
    # Required total "2" filled; child "2.a" filled so "2.b" becomes covered.
    _insert(db_session, 1, month, "2", 100)
    _insert(db_session, 1, month, "2.a", 60)
    # A required indicator that is genuinely missing ("3" left absent).
    # A required indicator with an explicit zero ("4") -> Filled.
    _insert(db_session, 1, month, "4", 0)
    # An Optional indicator WITH a value -> numerator only, never denominator.
    opt = db_session.query(Indicator).filter(Indicator.code == "16").first()
    from app.models import IndicatorValue
    db_session.add(IndicatorValue(hospital_id=1, month=month,
                                  indicator_id=opt.id, value=7))
    db_session.query(Indicator).filter(Indicator.id == opt.id).update(
        {"requirement_type": "Optional"}, synchronize_session=False)
    db_session.commit()

    # 1. Engine persists a QualityScore row.
    run_full_analysis(db_session, 1, month, force=True)
    stored = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month).first()
    assert stored is not None
    engine = stored.completeness

    # 2. Shared DB wrapper.
    wrapper = round(compute_hospital_completeness(db_session, 1, month), 1)

    # 3. KPI card.
    kpi = {x["id"]: x["value"] for x in client.get(
        "/dashboard/kpi", params={"hospital_id": 1, "month": month}).json()["kpis"]}

    # 4. Component-diagnostics drilldown.
    comp = client.get(
        "/dashboard/component-diagnostics",
        params={"hospital_id": 1, "month_from": month, "month_to": month,
                "metric": "completeness"},
    ).json()["components"][0]["avg"]

    # 5. Toggle recalc writes the same number.
    _recalc_hospital_scores(db_session, 1)
    toggled = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month).first().completeness

    assert wrapper == pytest.approx(engine, abs=0.1), (wrapper, engine)
    assert kpi["completeness"] == pytest.approx(engine, abs=0.2), (kpi["completeness"], engine)
    assert comp == pytest.approx(engine, abs=0.2), (comp, engine)
    assert toggled == pytest.approx(engine, abs=0.1), (toggled, engine)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_completeness_parity.py -q`
Expected: PASS.

- [ ] **Step 3: Lint and commit**

Run: `.\.venv\Scripts\python.exe -m ruff check tests/test_completeness_parity.py`
Expected: no new errors.

```bash
git add tests/test_completeness_parity.py
git commit -m "test(quality): cross-site completeness parity regression"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass except the pre-existing `tests/test_deploy_cloudrun_supabase.py::test_script_is_valid_bash` env failure. If any other test fails, fix it (fold the fix into the relevant task and re-commit) before declaring done.

- [ ] **Step 2: Lint the touched packages**

Run: `.\.venv\Scripts\python.exe -m ruff check app/engine/quality app/engine/pipeline.py app/api/dashboard.py`
Expected: no new errors relative to the pre-change baseline.

- [ ] **Step 3: Confirm the acceptance criteria explicitly**

Verify by reading the parity test's assertions that all five criteria hold:
- Pipeline/dashboard/reports agree (reports reads the same stored row).
- Optional present does not change the number.
- `0` is Filled and `None` is Missing (covered by Task 1 core tests).
- No divergence between calculation methods.

---

## Self-Review

**Spec coverage:**
- One DB-free core → Task 1. ✓
- `calculate_quality_score` delegates → Task 2. ✓
- Pipeline helper + `compute_hospital_completeness` + `_compute_full_analysis` → Tasks 2-3. ✓
- `run_quality_analysis` delegates → Task 2. ✓
- `component_diagnostics` required-only fix → Task 4. ✓
- Out of scope (`find_data_problems`, `reports.py`) → untouched. ✓
- Tests (core unit, parity, helper simplification) → Tasks 1, 3, 5. ✓

**Placeholder scan:** none — every code step shows the full code.

**Type consistency:** `compute_completeness(values, required_codes, covered_codes)` is used identically in Tasks 2, 3, 4. `get_required_indicator_codes` returns `set[str]` in Tasks 2 and 3. `calculate_quality_score`'s 4th positional is `required_codes: set` in Task 2 and its pipeline caller.
