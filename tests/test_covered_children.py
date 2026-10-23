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


def test_ge_sibling_covered_when_reported_fit_within_parent():
    """Containment doctrine (updated): ge/gt rules describe a NON-EXHAUSTIVE
    subset of the parent. When the reported children fit within the parent,
    unreported siblings mean "no activity in that category" — not missing
    data. (60 cases of live births breakdown + 40 unreported = the parent's
    100 is still consistent with the children that exist.)"""
    ctx = _ctx({"2": 100.0, "3": 60.0})
    covered = get_covered_child_codes(ctx)
    assert "4" in covered and "5" in covered


def test_ge_overflow_leaves_siblings_uncovered():
    """When the reported children EXCEED the parent, the rule cannot reconcile
    and the missing siblings may be exactly the missing pieces — stay flagged."""
    ctx = _ctx({"2": 100.0, "3": 140.0})
    covered = get_covered_child_codes(ctx)
    assert "4" not in covered and "5" not in covered


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

def test_parent_le_sibling_covered_when_children_reach_parent(monkeypatch):
    """Parent-accounting doctrine (new): parent_le rules describe children that
    must account for at least the whole parent. When the reported children
    already reach the parent (rule PASSes), unreported siblings mean "no such
    cases" — not missing data. Guards incident 5.3 (R061 10.x family)."""
    from types import SimpleNamespace
    from app.engine.quality import rules as rules_mod
    rule = SimpleNamespace(
        code="RCT", name="x", rule_type="LOGIC", severity="HIGH",
        category="BASIC_LOGIC", expression_type="parent_le",
        params='{"parent": "10", "children": ["10.a", "10.b"]}',
        enabled=True, sort_order=0,
    )
    monkeypatch.setattr(rules_mod, "load_rules_from_db", lambda s: [rule])
    covered = rules_mod.compute_covered_codes({"10": 100.0, "10.a": 120.0}, set(), session=object())
    assert "10.b" in covered


def test_parent_le_equal_sum_also_covers(monkeypatch):
    from types import SimpleNamespace
    from app.engine.quality import rules as rules_mod
    rule = SimpleNamespace(
        code="RCT", name="x", rule_type="LOGIC", severity="HIGH",
        category="BASIC_LOGIC", expression_type="parent_le",
        params='{"parent": "10", "children": ["10.a", "10.b"]}',
        enabled=True, sort_order=0,
    )
    monkeypatch.setattr(rules_mod, "load_rules_from_db", lambda s: [rule])
    covered = rules_mod.compute_covered_codes({"10": 100.0, "10.a": 100.0}, set(), session=object())
    assert "10.b" in covered


def test_parent_le_shortfall_leaves_siblings_uncovered(monkeypatch):
    """Reported children fall short of the parent (rule FAILs) — the gap may be
    exactly the missing siblings, so they stay flagged."""
    from types import SimpleNamespace
    from app.engine.quality import rules as rules_mod
    rule = SimpleNamespace(
        code="RCT", name="x", rule_type="LOGIC", severity="HIGH",
        category="BASIC_LOGIC", expression_type="parent_le",
        params='{"parent": "10", "children": ["10.a", "10.b"]}',
        enabled=True, sort_order=0,
    )
    monkeypatch.setattr(rules_mod, "load_rules_from_db", lambda s: [rule])
    covered = rules_mod.compute_covered_codes({"10": 100.0, "10.a": 60.0}, set(), session=object())
    assert "10.b" not in covered


def test_parent_lt_strict_does_not_cover_on_equality(monkeypatch):
    """parent_lt FAILs when parent == sum(children), so coverage must stay off
    there too — coverage mirrors the rule's own pass condition."""
    from types import SimpleNamespace
    from app.engine.quality import rules as rules_mod
    rule = SimpleNamespace(
        code="RCT", name="x", rule_type="LOGIC", severity="HIGH",
        category="BASIC_LOGIC", expression_type="parent_lt",
        params='{"parent": "10", "children": ["10.a", "10.b"]}',
        enabled=True, sort_order=0,
    )
    monkeypatch.setattr(rules_mod, "load_rules_from_db", lambda s: [rule])
    covered = rules_mod.compute_covered_codes({"10": 100.0, "10.a": 100.0}, set(), session=object())
    assert "10.b" not in covered


def test_parent_lt_covers_on_strict_exceedance(monkeypatch):
    from types import SimpleNamespace
    from app.engine.quality import rules as rules_mod
    rule = SimpleNamespace(
        code="RCT", name="x", rule_type="LOGIC", severity="HIGH",
        category="BASIC_LOGIC", expression_type="parent_lt",
        params='{"parent": "10", "children": ["10.a", "10.b"]}',
        enabled=True, sort_order=0,
    )
    monkeypatch.setattr(rules_mod, "load_rules_from_db", lambda s: [rule])
    covered = rules_mod.compute_covered_codes({"10": 100.0, "10.a": 120.0}, set(), session=object())
    assert "10.b" in covered
