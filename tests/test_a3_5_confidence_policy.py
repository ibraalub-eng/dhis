"""P3.3.1b — ConfidencePolicy normalization and display tests (no database)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext

import pytest

from app.engine.confidence_policy import (
    CONFIDENCE_POLICY_VERSION,
    DECIMAL_PRECISION,
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MEDIUM,
    DEFAULT_WEIGHTS,
    DEFAULT_ZSCORE_THRESHOLD,
    DISPLAY_QUANTUM,
    WEIGHT_KEYS,
    ConfidencePolicy,
    format_weight,
    format_weights,
    validate_weight_update,
    validate_weight_values,
)
from app.models import ConfidenceWeights


def _defaults(**overrides):
    values = dict(DEFAULT_WEIGHTS)
    values.update(overrides)
    return values


def _policy(**overrides):
    values = _defaults(**overrides)
    cutoffs = {
        key: values.pop(key)
        for key in ("high", "medium", "low", "zscore_threshold")
        if key in values
    }
    return ConfidencePolicy(
        **values,
        high=cutoffs.get("high", DEFAULT_HIGH),
        medium=cutoffs.get("medium", DEFAULT_MEDIUM),
        low=cutoffs.get("low", DEFAULT_LOW),
        zscore_threshold=cutoffs.get("zscore_threshold",
                                    DEFAULT_ZSCORE_THRESHOLD),
    )


def _ratio(value, total):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        return Decimal(str(value)) / Decimal(str(total))


def _assert_internal_sum(policy):
    assert abs(sum(policy.effective_decimals.values(), Decimal("0"))
               - Decimal("1")) < Decimal("1e-25")


def test_default_policy_is_exact_and_frozen():
    policy = ConfidencePolicy.defaults()
    assert policy.as_weight_mapping() == dict(DEFAULT_WEIGHTS)
    assert dict(policy.submitted_weights) == dict(DEFAULT_WEIGHTS)
    assert dict(policy.effective_weights) == dict(DEFAULT_WEIGHTS)
    assert policy.normalization_applied is False
    assert policy.high == 80.0
    assert policy.medium == 50.0
    assert policy.low == 25.0
    assert policy.zscore_threshold == 2.5
    assert policy.weight_for("rule_compliance") == 0.55
    assert policy.weight_for("unknown_factor") == 0.0
    assert CONFIDENCE_POLICY_VERSION == "1.0.0"
    assert DISPLAY_QUANTUM == Decimal("0.01")
    with pytest.raises(FrozenInstanceError):
        policy.rule_compliance = 0.60


def test_default_weight_mapping_cannot_be_mutated():
    assert tuple(DEFAULT_WEIGHTS) == WEIGHT_KEYS
    with pytest.raises(TypeError):
        DEFAULT_WEIGHTS["rule_compliance"] = 0.60
    assert dict(DEFAULT_WEIGHTS) == _defaults()


def test_policy_exposes_immutable_submitted_and_effective_views():
    policy = _policy(rule_compliance=0.54)
    assert policy.normalization_applied is True
    with pytest.raises(TypeError):
        policy.submitted_weights["rule_compliance"] = 0.60
    with pytest.raises(TypeError):
        policy.effective_weights["rule_compliance"] = 0.60
    copied = policy.as_weight_mapping()
    copied["rule_compliance"] = 0.60
    assert policy.weight_for("rule_compliance") != 0.60


def test_model_column_defaults_match_policy_constants():
    columns = ConfidenceWeights.__table__.c
    for key in WEIGHT_KEYS:
        assert columns[key].default.arg == DEFAULT_WEIGHTS[key]


def test_raw_z_and_cutoffs_are_not_clamped_or_rounded():
    policy = _policy(high=95.0, medium=55.0, low=30.0, zscore_threshold=99.0)
    assert (policy.high, policy.medium, policy.low) == (95.0, 55.0, 30.0)
    assert policy.zscore_threshold == 99.0


def test_unit_sum_preserves_submitted_values_without_normalization():
    policy = _policy()
    assert policy.normalization_applied is False
    assert dict(policy.submitted_weights) == dict(DEFAULT_WEIGHTS)
    assert dict(policy.effective_weights) == dict(DEFAULT_WEIGHTS)
    assert policy.as_weight_mapping() == dict(DEFAULT_WEIGHTS)
    assert policy.rule_compliance == 0.55

    equal = ConfidencePolicy(
        **{key: 0.2 for key in WEIGHT_KEYS},
        high=DEFAULT_HIGH,
        medium=DEFAULT_MEDIUM,
        low=DEFAULT_LOW,
        zscore_threshold=DEFAULT_ZSCORE_THRESHOLD,
    )
    assert equal.normalization_applied is False
    assert dict(equal.submitted_weights) == {key: 0.2 for key in WEIGHT_KEYS}
    assert dict(equal.effective_weights) == {key: 0.2 for key in WEIGHT_KEYS}


@pytest.mark.parametrize("rule,total", [
    (0.54, 0.99),
    (0.56, 1.01),
    (0.60, 1.05),
    (0.05, 0.50),
])
def test_nonunit_totals_are_normalized(rule, total):
    policy = _policy(rule_compliance=rule)
    assert policy.normalization_applied is True
    assert policy.submitted_weights["rule_compliance"] == rule
    assert policy.effective_weights["rule_compliance"] == pytest.approx(
        float(_ratio(rule, total)))
    assert policy.rule_compliance == pytest.approx(float(_ratio(rule, total)))
    assert policy.as_weight_mapping()["rule_compliance"] == pytest.approx(
        float(_ratio(rule, total)))
    _assert_internal_sum(policy)


def test_relative_proportions_are_preserved():
    policy = _policy(
        rule_compliance=2.0,
        historical=1.0,
        cross_hospital=1.0,
        trend=1.0,
        completeness=5.0,
    )
    assert policy.normalization_applied is True
    assert policy.submitted_weights == {
        "rule_compliance": 2.0,
        "historical": 1.0,
        "cross_hospital": 1.0,
        "trend": 1.0,
        "completeness": 5.0,
    }
    assert policy.effective_weights == {
        "rule_compliance": 0.2,
        "historical": 0.1,
        "cross_hospital": 0.1,
        "trend": 0.1,
        "completeness": 0.5,
    }
    _assert_internal_sum(policy)


def test_zero_weight_is_allowed_when_total_is_positive():
    policy = _policy(
        rule_compliance=1.0,
        historical=1.0,
        cross_hospital=1.0,
        trend=0.0,
        completeness=0.0,
    )
    assert policy.normalization_applied is True
    assert policy.effective_weights["trend"] == 0.0
    assert policy.effective_weights["completeness"] == 0.0
    _assert_internal_sum(policy)


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="all be zero"):
        _policy(rule_compliance=0.0, historical=0.0, cross_hospital=0.0,
                trend=0.0, completeness=0.0)


def test_negative_weights_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        _policy(rule_compliance=-0.1)
    with pytest.raises(ValueError, match="non-negative"):
        validate_weight_values({**_defaults(), "trend": -0.1})


def test_nan_and_infinity_are_rejected():
    with pytest.raises(ValueError, match="finite"):
        _policy(rule_compliance=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        _policy(rule_compliance=float("inf"))


def test_deterministic_decimal_results():
    first = _policy(rule_compliance=0.60)
    second = _policy(rule_compliance=0.60)
    assert dict(first.effective_decimals) == dict(second.effective_decimals)
    assert first.as_weight_mapping() == second.as_weight_mapping()
    assert format_weights(first) == format_weights(second)


def test_effective_internal_sum_and_accuracy():
    policy = _policy(
        rule_compliance=0.9,
        historical=0.8,
        cross_hospital=0.7,
        trend=0.6,
        completeness=0.5,
    )
    assert policy.normalization_applied is True
    _assert_internal_sum(policy)
    for key in WEIGHT_KEYS:
        assert policy.weight_for(key) == float(policy.effective_decimals[key])


def test_formatting_uses_half_up_and_two_decimal_places():
    assert format_weight(Decimal("0.125")) == "0.13"
    assert format_weight(Decimal("0.124")) == "0.12"
    assert format_weight(Decimal("1.005")) == "1.01"
    assert format_weight(0.0) == "0.00"
    assert format_weight(0.5) == "0.50"


def test_display_does_not_adjust_the_last_weight():
    # Three positive weights each become 1/3. The display is .33 each, and
    # zeros stay 0.00; the displayed total is intentionally .99, not repaired.
    policy = _policy(
        rule_compliance=1.0,
        historical=1.0,
        cross_hospital=1.0,
        trend=0.0,
        completeness=0.0,
    )
    displayed = format_weights(policy)
    assert displayed == {
        "rule_compliance": "0.33",
        "historical": "0.33",
        "cross_hospital": "0.33",
        "trend": "0.00",
        "completeness": "0.00",
    }
    assert sum(Decimal(value) for value in displayed.values()) == Decimal("0.99")
    # The calculation-facing values are not the two-decimal display values.
    assert policy.weight_for("rule_compliance") != 0.33
    assert policy.effective_decimals["rule_compliance"] > Decimal("0.333")


def test_partial_update_merges_submitted_defaults():
    result = validate_weight_update(
        {"rule_compliance": 0.50, "completeness": 0.20})
    assert result == {
        "rule_compliance": 0.50,
        "historical": 0.10,
        "cross_hospital": 0.10,
        "trend": 0.10,
        "completeness": 0.20,
    }


def test_partial_update_merges_custom_policy():
    current = ConfidencePolicy(
        **{key: 0.2 for key in WEIGHT_KEYS},
        high=95.0,
        medium=55.0,
        low=30.0,
        zscore_threshold=99.0,
    )
    result = validate_weight_update(
        {"historical": 0.10, "cross_hospital": 0.30}, current)
    assert result == {
        "rule_compliance": 0.20,
        "historical": 0.10,
        "cross_hospital": 0.30,
        "trend": 0.20,
        "completeness": 0.20,
    }


def test_validate_update_accepts_nonunit_submitted_total():
    result = validate_weight_update(_defaults(rule_compliance=0.54))
    assert result == _defaults(rule_compliance=0.54)
    assert sum(result.values()) == pytest.approx(0.99)


def test_validation_does_not_mutate_current():
    current = dict(DEFAULT_WEIGHTS)
    before = dict(current)
    validate_weight_update({"rule_compliance": 0.50,
                            "completeness": 0.20}, current)
    assert current == before


@pytest.mark.parametrize("payload", [
    None,
    {},
    {"not_a_weight": 0.10},
    {"rule_compliance": True},
    {"rule_compliance": "0.50"},
    {"rule_compliance": float("nan")},
    {"rule_compliance": float("inf")},
    {"rule_compliance": 10 ** 400},
    {"rule_compliance": -0.01},
    {key: 0.0 for key in WEIGHT_KEYS},
])
def test_invalid_updates_are_rejected(payload):
    with pytest.raises(ValueError):
        validate_weight_update(payload)


def test_complete_values_require_all_five_keys_and_reject_unknown_keys():
    with pytest.raises(ValueError, match="missing weight"):
        validate_weight_values({"rule_compliance": 0.55})
    with pytest.raises(ValueError, match="unknown weight"):
        validate_weight_values({**_defaults(), "extra": 0.0})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, True,
                                   "0.5"])
def test_policy_rejects_invalid_scalar_values(value):
    with pytest.raises(ValueError):
        replace(ConfidencePolicy.defaults(), zscore_threshold=value)
