"""Tests for "covered" children: siblings whose absence is explained by a reported total.

When a parent/child sum rule (parent == sum of children or parent >= sum of children)
is already satisfied by the reported children, any missing sibling must NOT be reported
as missing nor penalize completeness.
"""
from app.engine.quality import ValidationContext, get_covered_child_codes, set_rules_config


def _ctx(data: dict, disabled=None) -> ValidationContext:
    return ValidationContext(
        values=data,
        hospital_name="Test Hospital",
        month="2026-04",
        disabled_codes=set(disabled or []),
    )


def test_eq_sibling_covered_when_partial_sum_equals_total():
    # 2 == 2.a + 2.b ; 2.a alone equals total -> 2.b is covered.
    ctx = _ctx({"2": 100.0, "2.a": 100.0})
    covered = get_covered_child_codes(ctx)
    assert "2.b" in covered


def test_eq_sibling_not_covered_when_partial_sum_below_total():
    ctx = _ctx({"2": 100.0, "2.a": 60.0})
    covered = get_covered_child_codes(ctx)
    assert "2.b" not in covered


def test_ge_sibling_covered_when_partial_sum_equals_total():
    # R001: 2 >= 3 + 4 + 5 ; 3 alone equals total -> 4,5 covered.
    ctx = _ctx({"2": 100.0, "3": 100.0})
    covered = get_covered_child_codes(ctx)
    assert "4" in covered and "5" in covered


def test_ge_sibling_not_covered_when_partial_sum_below_total():
    ctx = _ctx({"2": 100.0, "3": 60.0})
    covered = get_covered_child_codes(ctx)
    assert "4" not in covered


def test_parent_missing_means_no_coverage():
    ctx = _ctx({"2.a": 100.0})
    covered = get_covered_child_codes(ctx)
    assert "2.b" not in covered


def test_disabled_child_never_covered():
    ctx = _ctx({"2": 100.0, "2.a": 100.0}, disabled=["2.b"])
    covered = get_covered_child_codes(ctx)
    assert "2.b" not in covered


def test_db_rules_path(db_session):
    # Seed rules include eq R002 (2 = 2.a + 2.b) and ge R001 (2 >= 3+4+5).
    ctx = _ctx({"2": 100.0, "3": 100.0, "2.a": 100.0})
    covered = get_covered_child_codes(ctx, db_session)
    assert "4" in covered and "5" in covered and "2.b" in covered


def test_tolerance_respected():
    original = {"eq_tolerance": 0.01}
    set_rules_config({"eq_tolerance": 10.0})
    try:
        ctx = _ctx({"2": 100.0, "2.a": 95.0})
        covered = get_covered_child_codes(ctx)
        assert "2.b" in covered
    finally:
        set_rules_config(original)