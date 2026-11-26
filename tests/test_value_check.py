"""`value_check` merges the four indicator-value check types.

neg_check, decimal_check, missing and all_zero asked questions about indicator
*values*. They are now one type:

    {"checks": [{"kind": "negative", "codes": ["2", "3"]}, …]}

These tests document the merged contract:

* a converted rule evaluates exactly like its legacy type (status **and**
  details, so the stored explanation does not change),
* checks run in order and the first failure is the rule's result,
* each kind keeps its own semantics and severity,
* `all_zero` with no codes keeps the key-indicator default,
* the legacy type names keep working as aliases,
* the migration script converts stored rules without changing their outcome
  and can be re-run.
"""
import json
from types import SimpleNamespace

import pytest

from app.engine.confidence import _extract_codes_from_params
from app.engine.quality import RuleStatus, ValidationContext, dispatch_rule
from app.engine.quality.rules import (
    _get_rule_ref_codes_from_expr,
    normalize_value_check_params,
    value_check_params,
)
from app.models import Rule
from scripts.migrate_value_check import migrate_rules

PASS = RuleStatus.PASS
FAIL = RuleStatus.FAIL
LEGACY_TYPES = ("neg_check", "decimal_check", "missing", "all_zero")


def _ctx(values):
    return ValidationContext(values=values, hospital_name="Test Hospital", month="2026-04")


def _rule(expr, params, code="RVC"):
    return SimpleNamespace(
        code=code,
        name="value check",
        rule_type="DATA_QUALITY",
        severity="HIGH",
        category="TREND_DATA_QUALITY",
        expression_type=expr,
        params=json.dumps(params),
        enabled=True,
        sort_order=0,
    )


def _run(expr, params, values, code="RVC"):
    return dispatch_rule(_rule(expr, params, code), _ctx(values))


# ── the merged type reproduces every legacy outcome ──────────────────

_CASES = [
    # negative: any listed value below zero fails
    ("neg_check", {"codes": ["2", "3"]}, {"2": -1, "3": 4}, FAIL),
    ("neg_check", {"codes": ["2", "3"]}, {"2": 1, "3": 4}, PASS),
    ("neg_check", {"codes": ["2"]}, {}, PASS),
    # decimal: counts must be whole numbers
    ("decimal_check", {"codes": ["2"]}, {"2": 5.5}, FAIL),
    ("decimal_check", {"codes": ["2"]}, {"2": 5}, PASS),
    ("decimal_check", {"codes": ["2"]}, {}, PASS),
    # missing: the code must carry a value
    ("missing", {"code": "2"}, {}, FAIL),
    ("missing", {"code": "2"}, {"2": 5}, PASS),
    # all_zero: every listed value zero means no activity
    ("all_zero", {"codes": ["2", "3"]}, {"2": 0, "3": 0}, FAIL),
    ("all_zero", {"codes": ["2", "3"]}, {"2": 0, "3": 1}, PASS),
    ("all_zero", {}, {"2": 70}, PASS),
]

_CASE_IDS = [
    f"{expr}-{'fail' if expected == FAIL else 'pass'}-{i}"
    for i, (expr, _p, _v, expected) in enumerate(_CASES)
]


@pytest.mark.parametrize("expr,params,values,expected", _CASES, ids=_CASE_IDS)
def test_legacy_type_and_value_check_agree_on_status_and_details(expr, params, values, expected):
    legacy = _run(expr, params, values)
    assert legacy.status == expected, legacy.details

    converted = _run("value_check", normalize_value_check_params(expr, params), values)
    assert converted.status == legacy.status
    assert converted.details == legacy.details


def test_each_legacy_type_normalizes_to_one_check():
    assert normalize_value_check_params("neg_check", {"codes": ["2", "3"]}) == {
        "checks": [{"kind": "negative", "codes": ["2", "3"]}]}
    assert normalize_value_check_params("decimal_check", {"codes": ["2"]}) == {
        "checks": [{"kind": "decimal", "codes": ["2"]}]}
    assert normalize_value_check_params("missing", {"code": "6"}) == {
        "checks": [{"kind": "missing", "codes": ["6"]}]}
    assert normalize_value_check_params("all_zero", {"codes": ["2"]}) == {
        "checks": [{"kind": "all_zero", "codes": ["2"]}]}
    # all_zero may name no code and keeps the key-indicator default
    assert normalize_value_check_params("all_zero", {}) == {
        "checks": [{"kind": "all_zero", "codes": []}]}


def test_normalizers_reject_what_cannot_be_checked():
    assert normalize_value_check_params("ge", {"parent": "2", "children": ["3"]}) is None
    assert normalize_value_check_params("missing", {}) is None
    assert normalize_value_check_params("neg_check", {"codes": []}) is None
    assert value_check_params({}) is None
    assert value_check_params({"checks": [{"kind": "bogus", "codes": ["2"]}]}) is None
    assert value_check_params({"checks": [{"kind": "negative", "codes": []}]}) is None


def test_value_check_params_accepts_the_one_check_shorthand():
    assert value_check_params({"kind": "missing", "code": "2"}) == [
        {"kind": "missing", "codes": ["2"]}]
    assert value_check_params({"checks": [{"kind": "decimal_check", "codes": ["2"]},
                                          {"kind": "all_zero"}]}) == [
        {"kind": "decimal", "codes": ["2"]},
        {"kind": "all_zero", "codes": []},
    ]


# ── a merged rule can run several checks ────────────────────────────

def test_checks_run_in_order_and_the_first_failure_is_reported():
    both_fail = {"2": -1.5}
    negative_first = {"checks": [{"kind": "negative", "codes": ["2"]},
                                 {"kind": "decimal", "codes": ["2"]}]}
    decimal_first = {"checks": [{"kind": "decimal", "codes": ["2"]},
                                {"kind": "negative", "codes": ["2"]}]}

    assert "negative" in _run("value_check", negative_first, both_fail).details
    assert "decimal" in _run("value_check", decimal_first, both_fail).details


def test_all_passing_checks_pass_with_a_count():
    params = {"checks": [{"kind": "negative", "codes": ["2"]},
                         {"kind": "missing", "codes": ["2"]}]}
    result = _run("value_check", params, {"2": 5})
    assert result.status == PASS
    assert "All 2 value checks passed" in result.details


def test_missing_check_reads_every_listed_code():
    params = {"checks": [{"kind": "missing", "codes": ["2", "6"]}]}
    assert _run("value_check", params, {"2": 5}).status == FAIL
    assert "6" in _run("value_check", params, {"2": 5}).details
    assert _run("value_check", params, {"2": 5, "6": 3}).status == PASS


def test_all_zero_without_codes_keeps_the_key_indicator_default():
    params = {"checks": [{"kind": "all_zero"}]}
    # No data at all is not "all zero".
    assert _run("value_check", params, {}).status == PASS
    # A reported key indicator at zero is.
    assert _run("value_check", params, {"2": 0}).status == FAIL
    # A non-zero key indicator is fine.
    assert _run("value_check", params, {"2": 70}).status == PASS


def test_decimal_and_all_zero_keep_their_intrinsic_severity():
    decimal = _run("value_check", {"checks": [{"kind": "decimal", "codes": ["2"]}]}, {"2": 1.5})
    assert decimal.status == FAIL and decimal.severity.value == "LOW"
    zero = _run("value_check", {"checks": [{"kind": "all_zero", "codes": ["2"]}]}, {"2": 0})
    assert zero.status == FAIL and zero.severity.value == "CRITICAL"


def test_invalid_value_check_passes_instead_of_raising():
    result = _run("value_check", {"checks": [{"kind": "negative", "codes": []}]}, {"2": -1})
    assert result.status == PASS
    assert "at least one check" in result.details


# ── references ───────────────────────────────────────────────────────

def test_ref_codes_cover_every_check_and_dedupe():
    codes = _get_rule_ref_codes_from_expr("value_check", {"checks": [
        {"kind": "negative", "codes": ["2", "3"]},
        {"kind": "missing", "codes": ["3", "6"]},
        {"kind": "decimal", "codes": ["2"]},
    ]})
    assert codes == ["2", "3", "6"]


def test_ref_codes_for_all_zero_without_codes_are_the_key_indicators():
    codes = _get_rule_ref_codes_from_expr("value_check", {"checks": [{"kind": "all_zero"}]})
    assert codes == ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]


def test_confidence_extraction_mirrors_the_engine():
    params = {"checks": [{"kind": "negative", "codes": ["2", "3"]},
                         {"kind": "all_zero"}]}
    codes = _extract_codes_from_params("value_check", params)
    assert codes[:2] == ["2", "3"]
    assert "17" in codes


# ── migration of stored rules ────────────────────────────────────────

def _legacy_row(code, expr, params):
    return Rule(
        code=code, name=f"{expr} rule", rule_type="DATA_QUALITY", severity="HIGH",
        category="TREND_DATA_QUALITY", expression_type=expr,
        params=json.dumps(params), description="legacy value check",
        enabled=True, sort_order=0,
    )


def _results_by_code(session, values):
    out = {}
    for rule in session.query(Rule).filter(Rule.code.like("RVC%")).all():
        result = dispatch_rule(rule, _ctx(values))
        out[rule.code] = (result.status.value, result.details)
    return out


def test_migration_converts_saved_rules_without_changing_their_outcome(db_session):
    rows = [
        _legacy_row("RVC01", "neg_check", {"codes": ["2", "3"]}),
        _legacy_row("RVC02", "decimal_check", {"codes": ["2", "3"]}),
        _legacy_row("RVC03", "missing", {"code": "2"}),
        _legacy_row("RVC04", "all_zero", {"codes": ["2", "3"]}),
    ]
    db_session.add_all(rows)
    db_session.commit()

    values = {"2": -1, "3": 2.5}
    before = _results_by_code(db_session, values)
    assert before["RVC01"][0] == "FAIL" and before["RVC02"][0] == "FAIL"

    # Dry run reports the conversions and writes nothing.
    planned = migrate_rules(db_session, apply=False)
    assert [code for code, _old, _params in planned] == ["RVC01", "RVC02", "RVC03", "RVC04"]
    assert all(rule.expression_type != "value_check" for rule in rows)

    converted = migrate_rules(db_session, apply=True)
    assert len(converted) == 4
    for rule in rows:
        assert rule.expression_type == "value_check"
        params = json.loads(rule.params)
        assert len(params["checks"]) == 1

    after = _results_by_code(db_session, values)
    assert after == before

    # Re-running finds nothing left to convert.
    assert migrate_rules(db_session, apply=True) == []


def test_migration_leaves_a_rule_without_codes_alone(db_session):
    row = _legacy_row("RVC05", "neg_check", {"codes": []})
    db_session.add(row)
    db_session.commit()

    assert migrate_rules(db_session, apply=True) == []
    assert row.expression_type == "neg_check"
