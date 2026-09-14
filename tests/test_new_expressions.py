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


# ── Zero guards: all-zero reports must PASS (R060 flags those facilities) ─

def test_gt_passes_when_all_zero():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 0, "3": 0, "4": 0})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS
    assert "zero" in result.details.lower()


def test_gt_still_fails_on_inverted_values_after_zero_guard():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 80, "3": 60, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_gt_still_fails_on_equality_after_zero_guard():
    rule = _make_rule("X001", "gt", {"parent": "2", "children": ["3", "4"]})
    ctx = _make_ctx({"2": 100, "3": 60, "4": 40})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_lt_passes_when_both_zero():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 0, "5": 0})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.PASS
    assert "zero" in result.details.lower()


def test_lt_still_fails_on_equality_after_zero_guard():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 50, "5": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


def test_lt_still_fails_when_child_exceeds_after_zero_guard():
    rule = _make_rule("X002", "lt", {"child": "5.b.1", "parent": "5"})
    ctx = _make_ctx({"5.b.1": 60, "5": 50})
    result = dispatch_rule(rule, ctx)
    assert result.status == RuleStatus.FAIL


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


# ── Seeded rules R069/R070/R071 (scripts/seed_rules.py) ──────────────


def _seeded_rule(code: str):
    """Build a rule-like object from the seeded catalog entry."""
    import json
    from scripts.seed_rules import RULES
    entry = next(r for r in RULES if r["code"] == code)
    return SimpleNamespace(
        code=entry["code"],
        name=entry["name"],
        rule_type=entry["rule_type"],
        severity=entry["severity"],
        category=entry["category"],
        expression_type=entry["expression_type"],
        params=entry["params"],
        enabled=True,
        sort_order=0,
    )


def test_seed_catalog_contains_new_rules():
    from scripts.seed_rules import RULES
    codes = {r["code"] for r in RULES}
    assert {"R069", "R070", "R071"} <= codes


def test_r069_ge_factor_passes_on_sample_values(sample_values):
    # sample_values: 2=300 deliveries, 6=280 live births -> 280 <= 315
    result = dispatch_rule(_seeded_rule("R069"), _make_ctx(sample_values))
    assert result.status == RuleStatus.PASS


def test_r069_fails_when_live_births_exceed_105pct_of_deliveries():
    result = dispatch_rule(_seeded_rule("R069"), _make_ctx({"2": 100, "6": 110}))
    assert result.status == RuleStatus.FAIL


def test_r070_gt_passes_on_sample_values(sample_values):
    # sample_values: 2=300 deliveries, 7=10 fetal deaths -> 300 > 10
    result = dispatch_rule(_seeded_rule("R070"), _make_ctx(sample_values))
    assert result.status == RuleStatus.PASS


def test_r070_fails_when_deliveries_equal_fetal_deaths():
    result = dispatch_rule(_seeded_rule("R070"), _make_ctx({"2": 10, "7": 10}))
    assert result.status == RuleStatus.FAIL


def test_r071_lt_passes_on_sample_values(sample_values):
    # sample_values: 6=280 live births, 17=5 neonatal deaths -> 5 < 280
    result = dispatch_rule(_seeded_rule("R071"), _make_ctx(sample_values))
    assert result.status == RuleStatus.PASS


def test_r071_fails_when_neonatal_deaths_reach_live_births():
    result = dispatch_rule(_seeded_rule("R071"), _make_ctx({"6": 5, "17": 5}))
    assert result.status == RuleStatus.FAIL


def test_seeded_rules_pass_on_minimal_values(sample_values_minimal):
    # sample_values_minimal: 2=100, 6=95, 7=3, 17=2
    for code in ("R069", "R070", "R071"):
        result = dispatch_rule(_seeded_rule(code), _make_ctx(sample_values_minimal))
        assert result.status == RuleStatus.PASS, f"{code} failed on minimal fixture: {result.details}"


def test_seeded_rules_pass_on_third_hospital_fixture():
    # Community Clinic values from conftest all_hospital_data
    values = {"2": 250, "3": 160, "4": 15, "5": 75, "6": 235,
              "7": 8, "10": 12, "11": 1, "16": 8, "17": 4}
    for code in ("R069", "R070", "R071"):
        result = dispatch_rule(_seeded_rule(code), _make_ctx(values))
        assert result.status == RuleStatus.PASS, f"{code} failed on community clinic fixture: {result.details}"


def test_registry_contains_new_rules():
    from app.engine.quality.definitions import RULE_REF_CODES, RULE_CATALOG
    assert RULE_REF_CODES["R069"] == ["2", "6"]
    assert RULE_REF_CODES["R070"] == ["2", "7"]
    assert RULE_REF_CODES["R071"] == ["17", "6"]
    catalog_codes = {c["code"]: c for c in RULE_CATALOG}
    assert catalog_codes["R069"]["type"] == "LOGIC"
    assert catalog_codes["R069"]["severity"] == "MEDIUM"
    assert catalog_codes["R070"]["type"] == "LOGIC"
    assert catalog_codes["R070"]["severity"] == "HIGH"
    assert catalog_codes["R071"]["type"] == "CLINICAL"
    assert catalog_codes["R071"]["severity"] == "HIGH"


def test_disabled_codes_suppress_seeded_rules():
    from app.engine.quality.definitions import RULE_REF_CODES
    rule = _seeded_rule("R070")
    # When ALL referenced codes are disabled, dispatch_rule returns None (suppressed)
    ctx = _make_ctx({"2": 10, "7": 10}, disabled_codes={"2", "7"})
    assert dispatch_rule(rule, ctx) is None
    # With only one of the referenced codes disabled, the rule still runs
    ctx_partial = _make_ctx({"2": 10, "7": 10}, disabled_codes={"7"})
    assert dispatch_rule(rule, ctx_partial) is not None
    # Ref codes from expr params match the registry entry
    from app.engine.quality.rules import _get_rule_ref_codes_from_expr
    import json as _json
    codes = _get_rule_ref_codes_from_expr(rule.expression_type, _json.loads(rule.params))
    assert set(codes) == set(RULE_REF_CODES["R070"])
