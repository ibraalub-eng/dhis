"""The contract of the unified comparison policy, before the types merge.

The nine parent/child comparison types (ge, gt, eq, ge_factor, le, lt, le_sum,
parent_le, parent_lt) and the new `compare` type are now one comparison with a
single policy:

* **Tolerance** — one epsilon, the rules policy's ``eq_tolerance``. It is the
  equality tolerance for ``=``/``!=`` and the slack that separates "equal" from
  "ordered" for ``>``, ``>=``, ``<``, ``<=`` (``>`` means "greater by more than
  epsilon"). Nothing is compared bit-exactly, because computed sums are rarely
  bit-exact.
* **Missing data** — a side that carries no value makes the comparison not
  evaluable, and it PASSes. An unreported total is never read as zero, so
  missing data never produces a FAIL.
* **Zero/zero** — both sides zero is "no activity" and PASSes for every type.

Each behavioural test checks the legacy type *and* the `compare` rule built by
``normalize_compare_params`` on the same values, so the conversion cannot drift
from the legacy path. The remaining tests pin the comparison itself: reference
codes, the legacy-shaped payload, invalid input and the coverage pass.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.quality import RuleStatus, ValidationContext, dispatch_rule
from app.engine.quality.definitions import RulesPolicy
from app.engine.quality.rules import (
    LEGACY_COMPARE_TYPES,
    _LEGACY_COMPARE_BLUEPRINT,
    _get_rule_ref_codes_from_expr,
    compute_covered_codes,
    normalize_compare_params,
)

PASS = RuleStatus.PASS
FAIL = RuleStatus.FAIL


def _ctx(values, eq_tolerance=None):
    return ValidationContext(
        values=values,
        hospital_name="Test Hospital",
        month="2026-04",
        rules=RulesPolicy(eq_tolerance=eq_tolerance) if eq_tolerance is not None else RulesPolicy(),
    )


def _rule(expr, params, code="RCMP"):
    return SimpleNamespace(
        code=code,
        name="compare policy",
        rule_type="LOGIC",
        severity="HIGH",
        category="BASIC_LOGIC",
        expression_type=expr,
        params=json.dumps(params),
        enabled=True,
        sort_order=0,
    )


def _run(expr, params, values, eq_tolerance=None):
    return dispatch_rule(_rule(expr, params), _ctx(values, eq_tolerance))


def _both(expr, params, values, expected, eq_tolerance=None):
    """Assert the legacy type and its `compare` conversion both give ``expected``."""
    legacy = _run(expr, params, values, eq_tolerance)
    assert legacy.status == expected, f"{expr} {values}: {legacy.details}"
    converted = _run("compare", normalize_compare_params(expr, params), values, eq_tolerance)
    assert converted.status == expected, (
        f"compare({expr}) {values}: {converted.details}"
    )


# ── operands ─────────────────────────────────────────────────────────
# Parent side 5; the compared quantity (children sum, or the child for le/lt)
# is the variable. `ge_factor` allows 5 x 1.2 = 6. Each type is compared on the
# values its own roles describe, so one value table serves all nine.

_PARENT_TYPES = ("ge", "gt", "eq", "ge_factor", "parent_le", "parent_lt")


def _params(expr):
    if expr in ("le", "lt"):
        return {"child": "6", "parent": "2"}
    if expr == "le_sum":
        return {"child": "6", "children": ["6.d", "6.e"]}
    params = {"parent": "2", "children": ["6.d", "6.e"]}
    if expr == "ge_factor":
        params["factor"] = 1.2
    return params


def _values(expr, n):
    """Values for which the compared quantity is ``n``."""
    if expr in ("le", "lt"):
        return {"6": n, "2": 5}
    if expr == "le_sum":
        return {"6": 5, "6.d": n / 2, "6.e": n / 2}
    return {"2": 5, "6.d": n / 2, "6.e": n / 2}


_BOUNDARY = [
    # ge: parent >= children sum
    ("ge", 4, PASS), ("ge", 5, PASS), ("ge", 6, FAIL),
    # gt: strictly greater by more than epsilon
    ("gt", 4, PASS), ("gt", 5, FAIL), ("gt", 6, FAIL),
    # eq: equal within epsilon
    ("eq", 4, FAIL), ("eq", 5, PASS), ("eq", 6, FAIL),
    # ge_factor: parent x 1.2 >= children sum
    ("ge_factor", 5, PASS), ("ge_factor", 6, PASS), ("ge_factor", 7, FAIL),
    # parent_le: children reach the parent
    ("parent_le", 4, FAIL), ("parent_le", 5, PASS), ("parent_le", 6, PASS),
    # parent_lt: children exceed the parent by more than epsilon
    ("parent_lt", 4, FAIL), ("parent_lt", 5, FAIL), ("parent_lt", 6, PASS),
    # le: child <= parent
    ("le", 4, PASS), ("le", 5, PASS), ("le", 6, FAIL),
    # lt: child < parent by more than epsilon
    ("lt", 4, PASS), ("lt", 5, FAIL), ("lt", 6, FAIL),
    # le_sum: child >= children sum
    ("le_sum", 4, PASS), ("le_sum", 5, PASS), ("le_sum", 6, FAIL),
]


@pytest.mark.parametrize("expr,n,expected", _BOUNDARY,
                         ids=[f"{e}-{n}" for e, n, _ in _BOUNDARY])
def test_boundaries_hold_for_the_legacy_type_and_for_compare(expr, n, expected):
    _both(expr, _params(expr), _values(expr, n), expected)


def test_every_replaced_type_has_a_blueprint():
    assert set(LEGACY_COMPARE_TYPES) == {
        "ge", "gt", "eq", "ge_factor", "le", "lt", "le_sum", "parent_le", "parent_lt",
    }


def test_each_type_keeps_only_its_roles_operator_and_factor():
    ge = normalize_compare_params("ge", {"parent": "2", "children": ["6.d"]})
    assert ge == {
        "left": {"codes": ["2"], "agg": "single"},
        "right": {"codes": ["6.d"], "agg": "sum"},
        "op": ">=",
    }
    # The old per-type switches are not part of the payload any more.
    assert "tolerance" not in ge and "require_right" not in ge and "zero_passes" not in ge

    only_factor = normalize_compare_params(
        "ge_factor", {"parent": "2", "children": ["6.d"], "factor": 1.5})
    assert only_factor["factor"] == 1.5
    assert only_factor["op"] == ">="

    le = normalize_compare_params("le", {"child": "6", "parent": "2"})
    assert le["left"] == {"codes": ["6"], "agg": "single"}
    assert le["right"] == {"codes": ["2"], "agg": "single"}


def test_normalizer_returns_none_for_unknown_or_incomplete_rules():
    assert normalize_compare_params("formula", {"formula": "{6}"}) is None
    assert normalize_compare_params("ge", {"parent": "2"}) is None
    assert normalize_compare_params("ge", {}) is None


# ── policy 1: one epsilon, applied by every type ─────────────────────

_EPSILON_CASES = [
    # (expr, values whose compared quantities differ by ~0.005, expected)
    # ge: an overflow of 0.005 is "equal" now (it used to fail bit-exactly).
    ("ge", {"2": 5, "6.d": 5.005}, PASS),
    # gt: exceeding by 0.005 is not "greater by more than epsilon".
    ("gt", {"2": 5, "6.d": 4.995}, FAIL),
    ("gt", {"2": 5, "6.d": 4.98}, PASS),
    # eq: 0.005 apart is equal.
    ("eq", {"2": 5, "6.d": 5.005}, PASS),
    # ge_factor: allowed = 6; 6.005 is within epsilon.
    ("ge_factor", {"2": 5, "6.d": 6.005}, PASS),
    # parent_le: the parent is 0.005 above the children, still reconciled.
    ("parent_le", {"2": 5, "6.d": 4.995}, PASS),
    # parent_lt: 0.005 above passes tolerance as "equal", 0.02 is a real gap.
    ("parent_lt", {"2": 5, "6.d": 5.005}, FAIL),
    ("parent_lt", {"2": 5, "6.d": 5.02}, PASS),
    # le: a child 0.005 above the parent is within epsilon.
    ("le", {"6": 5.005, "2": 5}, PASS),
    # lt: 0.005 below is "equal", 0.02 below is a real difference.
    ("lt", {"6": 4.995, "2": 5}, FAIL),
    ("lt", {"6": 4.98, "2": 5}, PASS),
    # le_sum: the child 0.005 below the children sum still passes >=.
    ("le_sum", {"6": 5, "6.d": 4.995}, PASS),
]


@pytest.mark.parametrize("expr,values,expected", _EPSILON_CASES,
                         ids=[f"{e}-{sorted(v.values())}" for e, v, _ in _EPSILON_CASES])
def test_one_epsilon_applies_to_every_comparison_type(expr, values, expected):
    _both(expr, _params(expr), values, expected)


@pytest.mark.parametrize("expr,values,strict_expected", [
    ("ge", {"2": 5, "6.d": 5.005}, FAIL),      # no epsilon: the overflow shows
    ("gt", {"2": 5, "6.d": 4.995}, PASS),      # no epsilon: any gap is "greater"
    ("le", {"6": 5.005, "2": 5}, FAIL),
    ("lt", {"6": 4.995, "2": 5}, PASS),
    ("eq", {"2": 5, "6.d": 5.005}, FAIL),
    ("parent_le", {"2": 5, "6.d": 4.995}, FAIL),
    ("parent_lt", {"2": 5, "6.d": 4.995}, FAIL),
    ("le_sum", {"6": 4.995, "6.d": 5}, FAIL),
    ("ge_factor", {"2": 5, "6.d": 6.005}, FAIL),
], ids=["ge", "gt", "le", "lt", "eq", "parent_le", "parent_lt", "le_sum", "ge_factor"])
def test_the_epsilon_comes_from_the_rules_policy(expr, values, strict_expected):
    """Zero tolerance is the same policy with epsilon 0 — not a second mode."""
    _both(expr, _params(expr), values, strict_expected, eq_tolerance=0.0)


def test_a_tighter_policy_tightens_the_loose_types_too():
    values = {"2": 5, "6.d": 5.005}
    _both("ge", {"parent": "2", "children": ["6.d"]}, values, PASS, eq_tolerance=0.01)
    _both("ge", {"parent": "2", "children": ["6.d"]}, values, FAIL, eq_tolerance=0.0)


# ── policy 2: missing data never fails ───────────────────────────────

_MISSING_CASES = [
    {},
    {"2": 5},                              # parent only
    {"6.d": 2, "6.e": 3},                  # children only
    {"6": 4},                              # child only (le/lt)
    {"6": 5, "6.d": 2, "6.e": 3},          # le_sum with its sum present
]


@pytest.mark.parametrize("expr", LEGACY_COMPARE_TYPES)
@pytest.mark.parametrize("values", _MISSING_CASES, ids=lambda v: ",".join(sorted(v)) or "empty")
def test_missing_data_passes_for_every_type(expr, values):
    """Either side carrying no value is "not evaluable" — and never a FAIL."""
    _both(expr, _params(expr), values, PASS)


def test_the_missing_side_is_named_in_the_details():
    """The unified skip is explained, not silently swallowed."""
    for expr, params in (("ge", {"parent": "2", "children": ["6.d"]}),
                         ("gt", {"parent": "2", "children": ["6.d"]}),
                         ("eq", {"parent": "2", "children": ["6.d"]})):
        result = _run(expr, params, {"2": 100})
        assert result.status == PASS
        assert "child data" in result.details.lower()
    # A single-code side says so plainly.
    assert "missing" in _run("le", {"child": "6", "parent": "2"}, {"2": 5}).details.lower()
    # A sum with no reported member is NOT read as zero: 100 >= 0 would pass
    # silently, but the rule must say it could not be evaluated.
    assert "no child data" in _run("le_sum", {"child": "6", "children": ["6.d"]},
                                   {"6": 100}).details.lower()


# ── policy 3: zero/zero is "no activity" for every type ──────────────

@pytest.mark.parametrize("expr", LEGACY_COMPARE_TYPES)
def test_both_sides_zero_passes_for_every_type(expr):
    zeros = {"2": 0, "6": 0, "6.d": 0, "6.e": 0}
    result = _run(expr, _params(expr), zeros)
    assert result.status == PASS, f"{expr} at 0/0: {result.details}"
    assert "zero" in result.details.lower()
    _both(expr, _params(expr), zeros, PASS)


# ── the two paths cannot drift ───────────────────────────────────────

_GRID = [
    {}, {"2": 0}, {"2": 0, "6.d": 0, "6.e": 0},
    {"2": 5, "6.d": 2, "6.e": 3}, {"2": 5, "6.d": 2.5, "6.e": 2.5},
    {"2": 5, "6.d": 2.495, "6.e": 2.5}, {"2": 5, "6.d": 2.51, "6.e": 2.5},
    {"6": 5, "2": 5}, {"6": 4.995, "2": 5}, {"6": 5.005, "2": 5},
]


@pytest.mark.parametrize("expr", LEGACY_COMPARE_TYPES)
def test_legacy_and_compare_agree_across_values_and_missing_data(expr):
    params = _params(expr)
    converted = normalize_compare_params(expr, params)
    for values in _GRID:
        legacy = _run(expr, params, values)
        compare = _run("compare", converted, values)
        assert compare.status == legacy.status, (
            f"{expr} vs compare on {values}: {legacy.details} / {compare.details}"
        )


# ── reference codes, compatibility and invalid input ─────────────────

def test_ref_codes_cover_both_sides_in_order():
    codes = _get_rule_ref_codes_from_expr("compare", {
        "left": {"codes": ["2"], "agg": "single"},
        "right": {"codes": ["6.e", "6.d"], "agg": "sum"},
        "op": "=",
    })
    assert codes == ["2", "6.e", "6.d"]


def test_compare_accepts_a_legacy_named_shape():
    """A migration that only renames expression_type leaves the old params."""
    values = {"2": 5, "6.d": 2, "6.e": 2}
    params = {"legacy": "ge", "parent": "2", "children": ["6.d", "6.e"]}
    assert _run("compare", params, values).status == _run(
        "ge", {"parent": "2", "children": ["6.d", "6.e"]}, values).status


def test_stored_per_rule_switches_cannot_divert_the_policy():
    """A payload carrying the old flags is normalized to the shared policy."""
    values = {"2": 5, "6.d": 5.005}
    params = {
        "left": {"codes": ["2"], "agg": "single"},
        "right": {"codes": ["6.d"], "agg": "sum"},
        "op": ">=",
        "tolerance": "none",
        "require_right": False,
        "zero_passes": False,
    }
    assert _run("compare", params, values).status == PASS      # epsilon still applies
    assert _run("compare", params, {"2": 0, "6.d": 0}).status == PASS  # 0/0 still passes
    stored = json.loads(_rule("compare", params).params)
    from app.engine.quality.rules import compare_params
    assert set(compare_params(stored)) == {"left", "right", "op", "factor"}


def test_invalid_compare_params_pass_instead_of_raising():
    result = _run("compare", {"left": {"codes": ["2"], "agg": "single"}}, {"2": 5})
    assert result.status == PASS
    assert "left and right" in result.details


def test_compare_feeds_the_coverage_pass(db_session):
    """A converted rule keeps covering unreported children in completeness."""
    from app.models import Rule

    db_session.add(Rule(
        code="RCMP_COVER", name="compare coverage", rule_type="LOGIC",
        severity="LOW", category="BASIC_LOGIC", expression_type="compare",
        params=json.dumps({
            "left": {"codes": ["2"], "agg": "single"},
            "right": {"codes": ["2.z"], "agg": "sum"},
            "op": ">=",
        }),
        description="parent contains its reported children",
        enabled=True,
        sort_order=0,
    ))
    db_session.commit()

    covered = compute_covered_codes({"2": 100}, set(), db_session)
    assert "2.z" in covered


# ── Stage 2: the UI offers compare only, and opens old rules in it ─────────

_ROOT = Path(__file__).resolve().parents[1]


def test_dropdown_offers_compare_only():
    html = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<option value="compare">compare — left operand op right operand</option>' in html
    for expr in LEGACY_COMPARE_TYPES:
        assert f'<option value="{expr}">' not in html


def test_reference_table_documents_compare_only():
    html = (_ROOT / "static" / "tabs" / "rules-manager.html").read_text(encoding="utf-8")
    assert "<code>compare</code>" in html
    for expr in LEGACY_COMPARE_TYPES:
        assert f"<code>{expr}</code>" not in html


def test_explanations_cover_compare_only():
    src = (_ROOT / "static" / "js" / "rules-manager.js").read_text(encoding="utf-8")
    assert "'compare': {title:" in src
    for expr in LEGACY_COMPARE_TYPES:
        assert f"'{expr}': {{title:" not in src


def test_builder_conversion_table_matches_the_engine():
    """The UI converter must read a legacy rule exactly as the engine does."""
    src = (_ROOT / "static" / "js" / "rules.js").read_text(encoding="utf-8")
    block = re.search(r"const LEGACY_COMPARE_BUILDER = \{(.*?)\n        \};", src, re.S)
    assert block, "rules.js no longer defines LEGACY_COMPARE_BUILDER"
    rows = re.findall(
        r"(\w+):\s*\['(\w+)',\s*'(\w+)',\s*'([<>=!]+)',\s*(null|'factor')\]",
        block.group(1),
    )
    js = {
        name: (left, right, op, None if factor == "null" else factor.strip("'"))
        for name, left, right, op, factor in rows
    }
    assert js == _LEGACY_COMPARE_BLUEPRINT


def test_editing_a_legacy_rule_opens_the_compare_builder():
    src = (_ROOT / "static" / "js" / "rules.js").read_text(encoding="utf-8")
    assert "const converted = _compareParamsFromLegacy(editExpr, editParams);" in src
    assert "editExpr = 'compare';" in src
    assert "_vbLoadExistingParams(editExpr, editParams);" in src
    # The builder turns the converted left/right operands back into params.
    assert "case 'compare': {" in src
    assert "left: side(_vbState.leftCodes, _vbState.leftAgg)," in src


# ── Stage 3: batch migration of the stored legacy rules ─────────────────────

def test_migrate_compare_converts_and_is_idempotent(db_session):
    from app.models import Rule
    from scripts.migrate_compare import apply_conversion, collect

    db_session.add(Rule(
        code="R_MIG_LE", name="migrate me", rule_type="LOGIC", severity="LOW",
        category="BASIC_LOGIC", expression_type="le",
        params=json.dumps({"child": "5.b.1", "parent": "5"}),
        description="", enabled=True, sort_order=0,
    ))
    db_session.commit()

    mine = [item for item in collect(db_session) if item.code == "R_MIG_LE"]
    assert len(mine) == 1
    assert mine[0].old_type == "le"
    assert mine[0].new_params == {
        "left": {"codes": ["5.b.1"], "agg": "single"},
        "right": {"codes": ["5"], "agg": "single"},
        "op": "<=",
    }

    apply_conversion(db_session, mine)
    db_session.expire_all()
    saved = db_session.query(Rule).filter(Rule.code == "R_MIG_LE").one()
    assert saved.expression_type == "compare"
    assert json.loads(saved.params) == mine[0].new_params

    # Idempotent: a second run has nothing left to convert for that rule.
    assert [item for item in collect(db_session) if item.code == "R_MIG_LE"] == []


def test_migrate_compare_keeps_rules_whose_params_cannot_convert(db_session):
    from app.models import Rule
    from scripts.migrate_compare import collect

    db_session.add(Rule(
        code="R_MIG_BAD", name="no children", rule_type="LOGIC", severity="LOW",
        category="BASIC_LOGIC", expression_type="ge",
        params=json.dumps({"parent": "2"}),
        description="", enabled=True, sort_order=0,
    ))
    db_session.commit()

    assert [item for item in collect(db_session) if item.code == "R_MIG_BAD"] == []
    untouched = db_session.query(Rule).filter(Rule.code == "R_MIG_BAD").one()
    assert untouched.expression_type == "ge"
