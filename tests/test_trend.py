"""`trend` merges month_over and month_under into direction + factor.

Both legacy types asked the same question — how did this month move against the
previous one — and differed only in direction and threshold:

    {"direction": "over", "factor": 2.0, "codes": ["2"]}   # FAIL above 2x prev
    {"direction": "under", "factor": 0.5, "codes": ["2"]}  # FAIL below half

These tests document the merged contract:

* a converted rule gives the legacy type's status and details,
* the threshold is exact (equal to factor x previous passes),
* ``month_over`` and ``month_under`` keep working as aliases,
* a baseline that is **missing, zero or negative** PASSes: no baseline is not
  evidence of a spike or a drop, and a negative baseline flips the sign,
* several watched codes report the first failure with the code named.
"""
import json
from types import SimpleNamespace

from app.engine.confidence import _extract_codes_from_params
from app.engine.quality import RuleStatus, ValidationContext, dispatch_rule
from app.engine.quality.rules import (
    _get_rule_ref_codes_from_expr,
    normalize_trend_params,
    trend_params,
)

PASS = RuleStatus.PASS
FAIL = RuleStatus.FAIL
PREV = "2026-03"
CUR = "2026-04"


def _ctx(values, history):
    return ValidationContext(values=values, hospital_name="Test Hospital",
                             month=CUR, historical_data=history)


def _run(expr, params, values, history):
    rule = SimpleNamespace(
        code="RT", name="trend", rule_type="DATA_QUALITY", severity="HIGH",
        category="TREND_DATA_QUALITY", expression_type=expr,
        params=json.dumps(params), enabled=True, sort_order=0,
    )
    return dispatch_rule(rule, _ctx(values, history))


def _both(expr, params, values, history, expected):
    """Assert the legacy type and its `trend` conversion both give ``expected``."""
    legacy = _run(expr, params, values, history)
    assert legacy.status == expected, legacy.details
    converted = _run("trend", normalize_trend_params(expr, params), values, history)
    assert converted.status == legacy.status
    assert converted.details == legacy.details


# ── direction + factor boundaries ────────────────────────────────────

def test_over_fails_only_above_the_factor():
    params = {"code": "2", "factor": 2.0}
    # factor 2.0 means "more than +200%", so 3x the baseline is the boundary
    _both("month_over", params, {"2": 300}, {"2": 100}, PASS)
    _both("month_over", params, {"2": 301}, {"2": 100}, FAIL)
    _both("month_over", params, {"2": 250}, {"2": 100}, PASS)
    _both("month_over", params, {"2": 100}, {"2": 100}, PASS)


def test_under_fails_only_below_the_factor():
    params = {"code": "2", "factor": 0.5}
    # exactly half is not "less than half"
    _both("month_under", params, {"2": 50}, {"2": 100}, PASS)
    _both("month_under", params, {"2": 49}, {"2": 100}, FAIL)
    _both("month_under", params, {"2": 80}, {"2": 100}, PASS)


def test_a_stricter_factor_is_honoured():
    _both("month_over", {"code": "11", "factor": 4.0}, {"11": 50}, {"11": 10}, PASS)
    _both("month_over", {"code": "11", "factor": 4.0}, {"11": 51}, {"11": 10}, FAIL)


# ── baseline edge cases: the previous month is zero or unusable ──────

def test_missing_previous_month_passes():
    _both("month_over", {"code": "2", "factor": 2.0}, {"2": 900}, None, PASS)
    _both("month_under", {"code": "2", "factor": 0.5}, {"2": 0}, None, PASS)
    assert "no previous month" in _run("month_over", {"code": "2", "factor": 2.0},
                                       {"2": 900}, None).details.lower()


def test_previous_month_without_the_code_passes():
    _both("month_over", {"code": "2", "factor": 2.0}, {"2": 900}, {}, PASS)
    assert "missing or zero" in _run(
        "trend", {"direction": "over", "factor": 2.0, "codes": ["2"]},
        {"2": 900}, {}).details.lower()


def test_previous_month_zero_passes_and_never_divides_by_zero():
    for expr, params in (("month_over", {"code": "2", "factor": 2.0}),
                         ("month_under", {"code": "2", "factor": 0.5})):
        _both(expr, params, {"2": 500}, {"2": 0}, PASS)
        _both(expr, params, {"2": 0}, {"2": 0}, PASS)
    detail = _run("trend", {"direction": "under", "factor": 0.5, "codes": ["2"]},
                  {"2": 500}, {"2": 0}).details.lower()
    assert "missing or zero" in detail


def test_previous_month_negative_passes_because_the_sign_flips():
    """A negative baseline would invert the percentage: never alert on it."""
    for expr, params in (("month_over", {"code": "2", "factor": 2.0}),
                         ("month_under", {"code": "2", "factor": 0.5})):
        _both(expr, params, {"2": 1000}, {"2": -5}, PASS)
        _both(expr, params, {"2": -1000}, {"2": -5}, PASS)
    assert "negative" in _run("trend", {"direction": "over", "factor": 2.0,
                                        "codes": ["2"]},
                              {"2": 1000}, {"2": -5}).details.lower()


def test_missing_current_month_passes():
    _both("month_over", {"code": "2", "factor": 2.0}, {}, {"2": 1}, PASS)
    _both("month_under", {"code": "2", "factor": 0.5}, {}, {"2": 100}, PASS)


# ── the merged type itself ───────────────────────────────────────────

def test_direction_and_factor_drive_the_same_question():
    over = {"direction": "over", "factor": 2.0, "codes": ["2"]}
    under = {"direction": "under", "factor": 0.5, "codes": ["2"]}
    assert _run("trend", over, {"2": 400}, {"2": 100}).status == FAIL
    assert _run("trend", under, {"2": 400}, {"2": 100}).status == PASS
    assert _run("trend", under, {"2": 10}, {"2": 100}).status == FAIL


def test_several_codes_report_the_first_failure_with_its_code():
    params = {"direction": "over", "factor": 2.0, "codes": ["2", "6"]}
    calm = _run("trend", params, {"2": 120, "6": 220},
                {"2": 100, "6": 110})
    assert calm.status == PASS
    assert "All 2 trend checks passed" in calm.details

    spiking = _run("trend", params, {"2": 120, "6": 400},
                   {"2": 100, "6": 110})
    assert spiking.status == FAIL
    assert "[6]" in spiking.details


def test_single_code_details_are_the_legacy_ones():
    params = {"direction": "over", "factor": 2.0, "codes": ["2"]}
    result = _run("trend", params, {"2": 400}, {"2": 100})
    assert result.status == FAIL
    assert "400" in result.details and "%" in result.details


def test_aliases_normalize_to_the_merged_shape():
    assert normalize_trend_params("month_over", {"code": "2", "factor": 2.0}) == {
        "direction": "over", "factor": 2.0, "codes": ["2"]}
    assert normalize_trend_params("month_under", {"code": "6", "factor": 0.5}) == {
        "direction": "under", "factor": 0.5, "codes": ["6"]}
    assert normalize_trend_params("ge", {"parent": "2"}) is None
    assert normalize_trend_params("month_over", {}) is None


def test_trend_params_accepts_shorthand_and_defaults():
    assert trend_params({"direction": "under", "codes": ["2"]}) == {
        "direction": "under", "factor": 0.5, "codes": ["2"]}
    assert trend_params({"direction": "over", "code": "2"}) == {
        "direction": "over", "factor": 2.0, "codes": ["2"]}
    # A non-positive or unreadable factor falls back to the direction default.
    assert trend_params({"direction": "over", "factor": 0, "codes": ["2"]})["factor"] == 2.0
    assert trend_params({"direction": "under", "factor": "x", "codes": ["2"]})["factor"] == 0.5
    assert trend_params({"direction": "sideways", "codes": ["2"]}) is None
    assert trend_params({"direction": "over"}) is None


def test_invalid_trend_passes_instead_of_raising():
    result = _run("trend", {"direction": "sideways", "codes": ["2"]}, {"2": 500},
                  {"2": 1})
    assert result.status == PASS
    assert "direction" in result.details


def test_ref_codes_and_confidence_extraction():
    params = {"direction": "over", "factor": 2.0, "codes": ["2", "6"]}
    assert _get_rule_ref_codes_from_expr("trend", params) == ["2", "6"]
    assert _get_rule_ref_codes_from_expr("month_over", {"code": "2"}) == ["2"]
    assert _extract_codes_from_params("trend", params) == ["2", "6"]
