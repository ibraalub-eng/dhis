"""Tests for gt / lt / ge_factor expression types (engine.quality.rules)."""
from types import SimpleNamespace

from app.engine.quality import (
    ValidationContext,
    RuleStatus,
    Severity,
    RuleType,
    dispatch_rule,
)
from app.engine.confidence import _extract_codes_from_params


def _make_ctx(data: dict, **kw) -> ValidationContext:
    return ValidationContext(
        values=data,
        hospital_name="Test Hospital",
        month="2026-04",
        **kw,
    )


def _make_rule(code: str, expr: str, params: dict, severity: str = "HIGH", rule_type: str = "LOGIC"):
    import json
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


# ── gt: parent > sum(children), strict (equality fails) ──────────────

def test_gt_passes_when_parent_exceeds_children_sum():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 110, "3": 50, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_gt_fails_on_equality():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 100, "3": 60, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_gt_fails_when_parent_below_children_sum():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 80, "3": 60, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_gt_passes_with_no_child_data():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 100})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


# ── lt: child < parent, strict (equality fails) ──────────────────────

def test_lt_passes_when_child_below_parent():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 30, "5": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_lt_fails_on_equality():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 50, "5": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_lt_fails_when_child_exceeds_parent():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 60, "5": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_lt_passes_with_missing_data():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 30})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


# ── ge_factor: parent * factor >= sum(children) ──────────────────────

def test_ge_factor_passes_within_tolerance():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.1})
    # allowed = 100 * 1.1 = 110; children sum = 105 -> OK
    ctx = _make_ctx({"2": 100, "3": 60, "4": 45})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_ge_factor_passes_when_children_within_parent():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.1})
    ctx = _make_ctx({"2": 100, "3": 50, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


def test_ge_factor_fails_beyond_tolerance():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.1})
    # allowed = 100 * 1.1 = 110; children sum = 120 -> FAIL
    ctx = _make_ctx({"2": 100, "3": 70, "4": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_ge_factor_with_factor_one_behaves_like_ge():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.0})
    ctx = _make_ctx({"2": 100, "3": 60, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS
    # exceed parent slightly -> FAIL
    ctx2 = _make_ctx({"2": 100, "3": 60, "4": 45})
    result2 = dispatch_rule(rule, ctx2)
    assert result2.status == RuleStatus.FAIL


def test_ge_factor_factor_below_one_requires_margin():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 0.9})
    # allowed = 100 * 0.9 = 90; children sum = 95 -> FAIL
    ctx = _make_ctx({"2": 100, "3": 55, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_ge_factor_passes_with_missing_parent():
    rule = _make_rule("X003", "ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.1})
    ctx = _make_ctx({"3": 50, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS


# ── Confidence engine code extraction ────────────────────────────────

def test_extract_codes_gt():
    codes = _extract_codes_from_params("gt", {"parent": "2", "children": ["3", "4"]})
    assert set(codes) == {"2", "3", "4"}


def test_extract_codes_lt():
    codes = _extract_codes_from_params("lt", {"child": "5.b.1", "parent": "5"})
    assert set(codes) == {"5.b.1", "5"}


def test_extract_codes_ge_factor():
    codes = _extract_codes_from_params("ge_factor", {"parent": "2", "children": ["3", "4"], "factor": 1.1})
    assert set(codes) == {"2", "3", "4"}
