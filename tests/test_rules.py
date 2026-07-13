"""Tests for validation rules engine (engine.quality)."""
import pytest
from app.engine.quality import (
    ValidationContext,
    run_all_rules,
    RuleStatus,
    Severity,
    RuleType,
    set_rules_config,
)


def _make_ctx(data: dict, **kw) -> ValidationContext:
    return ValidationContext(
        values=data,
        hospital_name="Test Hospital",
        month="2026-04",
        **kw,
    )


def _find(results, code):
    matches = [r for r in results if r.rule_code == code]
    return matches[0] if matches else None


def test_total_deliveries_ge_delivery_types():
    ctx = _make_ctx({"2": 300, "3": 200, "4": 20, "5": 80})
    results = run_all_rules(ctx)
    r01 = _find(results, "R001")
    assert r01 is not None
    assert r01.status == RuleStatus.PASS


def test_total_deliveries_lt_delivery_types():
    ctx = _make_ctx({"2": 100, "3": 80, "4": 10, "5": 30})
    results = run_all_rules(ctx)
    r01 = _find(results, "R001")
    assert r01 is not None
    assert r01.status == RuleStatus.FAIL


def test_c_sections_eq_emergency_planned():
    ctx = _make_ctx({"5": 50, "5.b.1": 30, "5.b.2": 20})
    results = run_all_rules(ctx)
    r06 = _find(results, "R006")
    assert r06 is not None
    assert r06.status == RuleStatus.PASS


def test_c_sections_ne_emergency_planned():
    ctx = _make_ctx({"5": 50, "5.b.1": 30, "5.b.2": 25})
    results = run_all_rules(ctx)
    r06 = _find(results, "R006")
    assert r06 is not None
    assert r06.status == RuleStatus.FAIL


def test_live_births_eq_sex_split():
    ctx = _make_ctx({"6": 280, "6.a": 140, "6.b": 135, "6.c": 5})
    results = run_all_rules(ctx)
    r11 = _find(results, "R011")
    assert r11 is not None
    assert r11.status == RuleStatus.PASS


def test_csection_rate_high():
    ctx = _make_ctx({"5": 250, "2": 300})
    results = run_all_rules(ctx)
    r41 = _find(results, "R041")
    assert r41 is not None
    assert r41.status == RuleStatus.FAIL


def test_csection_rate_ok():
    ctx = _make_ctx({"5": 80, "2": 300})
    results = run_all_rules(ctx)
    r41 = _find(results, "R041")
    assert r41 is not None
    assert r41.status == RuleStatus.PASS


def test_missing_data_passes():
    ctx = _make_ctx({})
    results = run_all_rules(ctx)
    for r in results:
        assert r.status == RuleStatus.PASS or "missing" in r.details.lower() or "no data" in r.details.lower()


def test_total_deliveries_ge_sum():
    ctx = _make_ctx({"2": 300, "3": 200, "4": 20, "5": 80})
    results = run_all_rules(ctx)
    r01 = _find(results, "R001")
    assert r01 is not None
    assert r01.status == RuleStatus.PASS


def test_total_deliveries_lt_sum():
    ctx = _make_ctx({"2": 300, "3": 200, "4": 20, "5": 90})
    results = run_all_rules(ctx)
    r01 = _find(results, "R001")
    assert r01 is not None
    assert r01.status == RuleStatus.FAIL


def test_all_rules_return_rule_result():
    ctx = _make_ctx({"2": 300, "3": 200, "4": 20, "5": 80, "6": 280})
    results = run_all_rules(ctx)
    assert len(results) >= 50
    for r in results:
        assert r.rule_code
        assert r.description
        assert r.status in (RuleStatus.PASS, RuleStatus.FAIL)
        assert r.severity in Severity


def test_rules_config_override():
    original_config = {"cs_rate_threshold": 80.0}
    set_rules_config({"cs_rate_threshold": 5.0})
    # 30/300*100 = 10% which is > 5% threshold → FAIL
    ctx = _make_ctx({"5": 30, "2": 300})
    results = run_all_rules(ctx)
    r41 = _find(results, "R041")
    assert r41 is not None
    assert r41.status == RuleStatus.FAIL
    set_rules_config(original_config)