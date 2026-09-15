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
from app.engine.quality.rules import _eval_formula, _formula, _get_rule_ref_codes_from_expr


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