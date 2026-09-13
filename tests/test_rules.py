"""Tests for validation rules engine (engine.quality)."""
from app.engine.quality import (
    ValidationContext,
    run_all_rules,
    RuleStatus,
    Severity,
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


def test_smm_eq_sum_of_sub_indicators():
    ctx = _make_ctx({"10": 25, "10.a": 10, "10.b": 5, "10.c": 3, "10.d": 7})
    results = run_all_rules(ctx)
    r61 = _find(results, "R061")
    assert r61 is not None
    assert r61.status == RuleStatus.PASS
    assert "SMM" in r61.description


def test_smm_ne_sum_of_sub_indicators():
    ctx = _make_ctx({"10": 30, "10.a": 10, "10.b": 5, "10.c": 3, "10.d": 7})
    results = run_all_rules(ctx)
    r61 = _find(results, "R061")
    assert r61 is not None
    assert r61.status == RuleStatus.FAIL


def test_smm_child_le_smm():
    ctx = _make_ctx({"10": 25, "10.g": 10})
    results = run_all_rules(ctx)
    r62 = _find(results, "R062")
    assert r62 is not None
    assert r62.status == RuleStatus.PASS


def test_smm_child_gt_smm_fails():
    ctx = _make_ctx({"10": 5, "10.g": 10})
    results = run_all_rules(ctx)
    r62 = _find(results, "R062")
    assert r62 is not None
    assert r62.status == RuleStatus.FAIL


def test_smm_other_morbidity_le_smm():
    ctx = _make_ctx({"10": 20, "10.o": 20})
    results = run_all_rules(ctx)
    r66 = _find(results, "R066")
    assert r66 is not None
    assert r66.status == RuleStatus.PASS


def test_hemorrhage_eq_sum_of_hemorrhage_types():
    ctx = _make_ctx({"10.a": 20, "10.a.1": 10, "10.a.2": 5, "10.a.5": 5})
    results = run_all_rules(ctx)
    r67 = _find(results, "R067")
    assert r67 is not None
    assert r67.status == RuleStatus.PASS


def test_hemorrhage_ne_sum_of_hemorrhage_types():
    ctx = _make_ctx({"10.a": 30, "10.a.1": 10, "10.a.2": 5, "10.a.5": 5})
    results = run_all_rules(ctx)
    r67 = _find(results, "R067")
    assert r67 is not None
    assert r67.status == RuleStatus.FAIL


def test_thromboembolism_eq_sum_of_embolism_types():
    ctx = _make_ctx({"10.j": 6, "10.j.1": 2, "10.j.2": 2, "10.j.3": 2})
    results = run_all_rules(ctx)
    r68 = _find(results, "R068")
    assert r68 is not None
    assert r68.status == RuleStatus.PASS


def test_pph_eq_sum_of_severity_types():
    ctx = _make_ctx({"10.a.1": 8, "10.a.1.1": 5, "10.a.1.2": 3})
    results = run_all_rules(ctx)
    r24 = _find(results, "R024")
    assert r24 is not None
    assert r24.status == RuleStatus.PASS


def test_pph_ne_sum_of_severity_types():
    ctx = _make_ctx({"10.a.1": 10, "10.a.1.1": 5, "10.a.1.2": 3})
    results = run_all_rules(ctx)
    r24 = _find(results, "R024")
    assert r24 is not None
    assert r24.status == RuleStatus.FAIL


def test_aph_eq_sum_of_causes():
    ctx = _make_ctx({"10.a.2": 6, "10.a.2.1": 4, "10.a.2.2": 2})
    results = run_all_rules(ctx)
    r25 = _find(results, "R025")
    assert r25 is not None
    assert r25.status == RuleStatus.PASS


def test_eph_ne_sum_of_causes():
    ctx = _make_ctx({"10.a.3": 9, "10.a.3.1": 3, "10.a.3.2": 3, "10.a.3.3": 4})
    results = run_all_rules(ctx)
    r26 = _find(results, "R026")
    assert r26 is not None
    assert r26.status == RuleStatus.FAIL