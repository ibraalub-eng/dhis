"""Tests for the formula expression type (engine.quality.rules)."""
import json
from types import SimpleNamespace

from app.engine.quality import (
    ValidationContext,
    RuleStatus,
    Severity,
    RuleType,
    dispatch_rule,
)
from app.engine.quality.rules import (
    _eval_formula,
    _get_rule_ref_codes_from_expr,
    formula_referenced_codes,
    validate_formula_expression,
)


def _make_ctx(data: dict, **kw) -> ValidationContext:
    return ValidationContext(
        values=data,
        hospital_name="Test Hospital",
        month="2026-04",
        **kw,
    )


def _make_rule(code, expr, params, severity="HIGH", rule_type="LOGIC"):
    return SimpleNamespace(
        code=code,
        name=f"Test {expr} rule",
        rule_type=rule_type,
        severity=severity,
        category="BASIC_LOGIC",
        expression_type=expr,
        params=json.dumps(params),
        enabled=True,
        sort_order=0,
    )


def make_rule(formula, target, code="R072"):
    return _make_rule(code, "formula", {"formula": formula, "target": target})


# ── _eval_formula ──────────────────────────────────────────────────

def test_eval_addition():
    assert _eval_formula("{6.a} + {6.b}", {"6.a": 5, "6.b": 7}) == 12.0


def test_eval_subtraction():
    assert _eval_formula("({6.e} * 2) - {7}", {"6.e": 6, "7": 2}) == 10.0


def test_eval_multiplication():
    assert _eval_formula("{7} * {6}", {"7": 2, "6": 5}) == 10.0


def test_eval_division():
    assert _eval_formula("{6} / 2", {"6": 10}) == 5.0


def test_eval_parentheses():
    assert _eval_formula("({6} + {7}) * 2", {"6": 3, "7": 4}) == 14.0


def test_eval_constant_only():
    assert _eval_formula("2 * 3 + 1", {}) == 7.0


def test_eval_missing_indicator_returns_none():
    assert _eval_formula("{6} + {9}", {"6": 3}) is None


def test_eval_division_by_zero_returns_none():
    assert _eval_formula("{6} / 0", {"6": 3}) is None


def test_eval_malformed_formula_returns_none():
    assert _eval_formula("({6} * 2", {"6": 3}) is None


# ── _formula rule function ─────────────────────────────────────────

def test_formula_rule_passes_when_equal():
    rule = make_rule("({6.e} * 2) - {7}", "6")
    ctx = _make_ctx({"6": 11, "6.e": 6, "7": 1})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS
    assert "==" in result.details


def test_formula_rule_fails_when_not_equal():
    rule = make_rule("({6.e} * 2) - {7}", "6")
    ctx = _make_ctx({"6": 12, "6.e": 6, "7": 1})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_rule_passes_when_missing_formula_data():
    rule = make_rule("({6.e} * 2) - {7}", "6")
    ctx = _make_ctx({"6": 11, "6.e": 6})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_formula_rule_passes_when_target_missing():
    rule = make_rule("({6.e} * 2) - {7}", "6")
    ctx = _make_ctx({"6.e": 6, "7": 1})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_formula_rule_severity_and_type_preserved():
    rule = _make_rule("R072", "formula", {"formula": "({6.e})", "target": "6"}, severity="MEDIUM", rule_type="CLINICAL")
    ctx = _make_ctx({"6": 6, "6.e": 6})
    result = dispatch_rule(rule, ctx)
    assert result.severity == Severity.MEDIUM
    assert result.rule_type == RuleType.CLINICAL


# ── _get_rule_ref_codes_from_expr ──────────────────────────────────

def test_ref_codes_extracts_braces_and_target():
    codes = _get_rule_ref_codes_from_expr("formula", {"formula": "({6.e} * 2) - {7}", "target": "6"})
    assert codes == ["6.e", "7", "6"]


def test_ref_codes_empty_when_no_braces():
    codes = _get_rule_ref_codes_from_expr("formula", {"formula": "2 * 3", "target": "6"})
    assert codes == ["6"]


# ── formula comparison operators via dispatch_rule ─────────────────

def _make_op_rule(op):
    return _make_rule("R080", "formula", {"formula": "{6.e}", "target": "6", "op": op})


def test_formula_op_equal_pass_and_fail():
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule("="), ctx)
    assert result.status == RuleStatus.PASS
    assert "==" in result.details

    ctx = _make_ctx({"6": 5, "6.e": 6})
    result = dispatch_rule(_make_op_rule("="), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_not_equal_pass_and_fail():
    ctx = _make_ctx({"6": 5, "6.e": 6})
    result = dispatch_rule(_make_op_rule("!="), ctx)
    assert result.status == RuleStatus.PASS
    assert "!=" in result.details

    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule("!="), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_greater_than_pass_and_fail():
    ctx = _make_ctx({"6": 5, "6.e": 6})
    result = dispatch_rule(_make_op_rule(">"), ctx)
    assert result.status == RuleStatus.PASS
    assert ">" in result.details

    # strict: equal values must FAIL (this is the > without equality)
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule(">"), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_less_than_pass_and_fail():
    ctx = _make_ctx({"6": 5, "6.e": 4})
    result = dispatch_rule(_make_op_rule("<"), ctx)
    assert result.status == RuleStatus.PASS
    assert "<" in result.details

    # strict: equal values must FAIL (this is the < without equality)
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule("<"), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_greater_or_equal_pass_and_fail():
    # equality edge: >= must PASS where > fails
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule(">="), ctx)
    assert result.status == RuleStatus.PASS
    assert ">=" in result.details

    ctx = _make_ctx({"6": 5, "6.e": 4})
    result = dispatch_rule(_make_op_rule(">="), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_less_or_equal_pass_and_fail():
    # equality edge: <= must PASS where < fails
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule("<="), ctx)
    assert result.status == RuleStatus.PASS
    assert "<=" in result.details

    ctx = _make_ctx({"6": 5, "6.e": 6})
    result = dispatch_rule(_make_op_rule("<="), ctx)
    assert result.status == RuleStatus.FAIL


def test_formula_op_invalid_falls_back_to_equality():
    """An unrecognized op falls back to '=' (never crashes, never inverts)."""
    ctx = _make_ctx({"6": 5, "6.e": 5})
    result = dispatch_rule(_make_op_rule("~garbage~"), ctx)
    assert result.status == RuleStatus.PASS
    assert "==" in result.details  # fallback renders the legacy equality message


def test_formula_op_boundary_values_strictness_matrix():
    """Truth table over the three boundary offsets for every operator."""
    expectations = {
        "=":  {"lt": False, "eq": True,  "gt": False},
        "!=": {"lt": True,  "eq": False, "gt": True},
        ">":  {"lt": False, "eq": False, "gt": True},
        "<":  {"lt": True,  "eq": False, "gt": False},
        ">=": {"lt": False, "eq": True,  "gt": True},
        "<=": {"lt": True,  "eq": True,  "gt": False},
    }
    cases = {"lt": 4, "eq": 5, "gt": 6}  # formula value vs target 5
    for op, expected in expectations.items():
        for case, fval in cases.items():
            ctx = _make_ctx({"6": 5, "6.e": fval})
            result = dispatch_rule(_make_op_rule(op), ctx)
            assert result.status == (RuleStatus.PASS if expected[case] else RuleStatus.FAIL), (
                f"op={op!r} case={case} (formula={fval} vs target=5) -> {result.status}"
            )


# ── two-sided formula rules: expression <op> expression ─────────────
#
# The Rule Validation screen accepts a whole arithmetic expression on each
# side, typed by the user with indicator names and Unicode signs:
#
#   Live births (6) + Stillbirths >24w (7)
#   = Total deliveries (2) + [Babies from multiples (6.e) − Multiple pregnancies (6.d)]

_USER_LHS = "Live births (6) + Stillbirths >24w (7)"
_USER_RHS = (
    "Total deliveries (2) + [Babies from multiples (6.e) \u2212 "
    "Multiple pregnancies (6.d)]"
)
# left = 100 + 5 = 105, right = 5 + (100 - 0) = 105
_USER_VALUES = {"6": 100, "7": 5, "2": 5, "6.e": 100, "6.d": 0}


def _make_two_sided_rule(lhs=_USER_LHS, rhs=_USER_RHS, op="="):
    return _make_rule("R081", "formula", {"formula": lhs, "rhs": rhs, "op": op})


def test_two_sided_expression_parses_labels_brackets_and_unicode_minus():
    assert formula_referenced_codes(_USER_LHS) == ["6", "7"]
    assert formula_referenced_codes(_USER_RHS) == ["2", "6.e", "6.d"]
    assert _eval_formula(_USER_LHS, _USER_VALUES) == 105.0
    assert _eval_formula(_USER_RHS, _USER_VALUES) == 105.0


def test_validate_expression_accepts_both_user_sides():
    assert validate_formula_expression(_USER_LHS) is None
    assert validate_formula_expression(_USER_RHS) is None


def test_validate_expression_rejects_incomplete_sides():
    assert "ends with the operator" in validate_formula_expression(_USER_LHS + " +")
    assert "unbalanced" in validate_formula_expression(_USER_RHS[:-1])


def test_two_sided_formula_rule_passes_when_both_sides_equal():
    result = dispatch_rule(_make_two_sided_rule(op="="), _make_ctx(_USER_VALUES))
    assert result.status == RuleStatus.PASS
    assert "Left=105 == Right=105" in result.details


def test_two_sided_formula_rule_fails_when_sides_differ():
    values = {**_USER_VALUES, "7": 6}  # left becomes 106, right stays 105
    result = dispatch_rule(_make_two_sided_rule(op="="), _make_ctx(values))
    assert result.status == RuleStatus.FAIL
    assert "Left=106 = Right=105" in result.details
    assert "diff=1.00" in result.details


def test_two_sided_formula_rule_respects_the_operator():
    values = {**_USER_VALUES, "7": 6}
    result = dispatch_rule(_make_two_sided_rule(op=">"), _make_ctx(values))
    assert result.status == RuleStatus.PASS
    assert "Left=106 > Right=105" in result.details


def test_two_sided_formula_rule_passes_when_a_side_has_missing_data():
    values = {k: v for k, v in _USER_VALUES.items() if k != "6.d"}
    result = dispatch_rule(_make_two_sided_rule(), _make_ctx(values))
    assert result.status == RuleStatus.PASS
    assert "could not be evaluated" in result.details


def test_ref_codes_include_both_sides():
    codes = _get_rule_ref_codes_from_expr(
        "formula", {"formula": _USER_LHS, "rhs": _USER_RHS, "op": "="}
    )
    assert sorted(codes) == sorted(["6", "7", "2", "6.e", "6.d"])