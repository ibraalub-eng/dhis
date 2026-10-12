"""Unit tests for the DB-free completeness core."""
from app.engine.quality import compute_completeness


def test_all_required_filled_is_one():
    values = {"a": 1.0, "b": 2.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0


def test_zero_counts_as_filled():
    assert compute_completeness({"a": 0.0}, {"a"}) == 1.0


def test_none_is_missing():
    # One of two required present -> 50%.
    assert compute_completeness({"a": 1.0}, {"a", "b"}) == 0.5


def test_optional_not_in_denominator():
    # required {a,b,c,d}; values fill required "a" and one OPTIONAL "opt" ->
    # filled 2 / denom 4 = 0.5. If Optional wrongly entered the denominator it
    # would be 2/5 = 0.4, so this pins denominator exclusion (the fill still
    # counts in the numerator per doctrine).
    values = {"a": 1.0, "opt": 9.0}
    assert compute_completeness(values, {"a", "b", "c", "d"}) == 0.5


def test_optional_fill_contributes_to_numerator():
    # Both required filled AND an extra optional fill -> capped at 1.0.
    values = {"a": 1.0, "b": 1.0, "opt": 5.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0


def test_covered_required_removed_from_denominator():
    # required {a,b,c}; c is covered-by-total; a filled -> 1/2.
    values = {"a": 1.0}
    assert compute_completeness(values, {"a", "b", "c"}, {"c"}) == 0.5


def test_covered_optional_does_not_shrink_denominator():
    # "z" is covered but NOT required -> denominator stays {a,b} = 2 -> 1/2.
    values = {"a": 1.0}
    assert compute_completeness(values, {"a", "b"}, {"z"}) == 0.5


def test_empty_denominator_returns_zero():
    assert compute_completeness({"a": 1.0}, set()) == 0.0
    assert compute_completeness({}, set()) == 0.0


def test_all_covers_collapse_to_zero():
    # Every required code is covered -> denominator 0 -> 0.0.
    assert compute_completeness({}, {"a", "b"}, {"a", "b"}) == 0.0


def test_result_capped_at_one():
    values = {"a": 1.0, "b": 1.0, "c": 1.0, "opt1": 1.0, "opt2": 1.0}
    assert compute_completeness(values, {"a", "b"}) == 1.0
