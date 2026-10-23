"""Tests for the parent_lt expression type (strict parent < sum(children))."""
import json
from types import SimpleNamespace

from app.engine.quality import (
    ValidationContext,
    RuleStatus,
    Severity,
    RuleType,
    dispatch_rule,
)
from app.engine.quality.rules import _get_rule_ref_codes_from_expr


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


def _eval(expr, params, data):
    return dispatch_rule(_make_rule("RT01", expr, params), _make_ctx(data))


def test_parent_lt_passes_when_strictly_less():
    res = _eval("parent_lt", {"parent": "2", "children": ["3", "4"]}, {"2": 90, "3": 40, "4": 60})
    assert res.status == RuleStatus.PASS


def test_parent_lt_fails_on_equality():
    # parent == sum(children) must FAIL (strict — the whole point vs parent_le)
    res = _eval("parent_lt", {"parent": "2", "children": ["3", "4"]}, {"2": 100, "3": 40, "4": 60})
    assert res.status == RuleStatus.FAIL


def test_parent_lt_fails_when_parent_exceeds_children():
    res = _eval("parent_lt", {"parent": "2", "children": ["3", "4"]}, {"2": 120, "3": 40, "4": 60})
    assert res.status == RuleStatus.FAIL


def test_parent_lt_passes_without_parent_value():
    res = _eval("parent_lt", {"parent": "2", "children": ["3", "4"]}, {"3": 40, "4": 60})
    assert res.status == RuleStatus.PASS


def test_parent_lt_passes_with_no_child_data():
    res = _eval("parent_lt", {"parent": "2", "children": ["3", "4"]}, {"2": 100})
    assert res.status == RuleStatus.PASS


def test_parent_lt_ref_codes_cover_parent_and_children():
    codes = _get_rule_ref_codes_from_expr("parent_lt", {"parent": "2", "children": ["3", "4"]})
    assert codes == ["2", "3", "4"]
