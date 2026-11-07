"""Pure Confidence policy value and weight normalization.

This module is the single owner of the five Confidence signal weights, the
three Confidence level cutoffs, and the raw Confidence Z-score threshold. It is
deliberately dependency-free: it imports neither the database models nor the
resolver, so both the engine and the resolver can use it without a cycle.

Submitted weights are validated and then normalized for calculation:

``effective_weight = submitted_weight / sum(submitted_weights)``

The submitted values remain available on :attr:`ConfidencePolicy.submitted_weights`;
the calculation-facing fields, :meth:`weight_for` and :meth:`as_weight_mapping`
return the effective values. When the submitted total is exactly 1.00, the
values are preserved unchanged.

Weight arithmetic uses :class:`Decimal` with a fixed high internal precision.
No intermediate value is rounded to the two-decimal display precision, and no
last weight is adjusted to force a displayed total of 1.00.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Union

CONFIDENCE_POLICY_VERSION = "1.0.0"

WEIGHT_KEYS = (
    "rule_compliance",
    "historical",
    "cross_hospital",
    "trend",
    "completeness",
)

DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType({
    "rule_compliance": 0.55,
    "historical": 0.10,
    "cross_hospital": 0.10,
    "trend": 0.10,
    "completeness": 0.15,
})

DEFAULT_HIGH = 80.0
DEFAULT_MEDIUM = 50.0
DEFAULT_LOW = 25.0
DEFAULT_ZSCORE_THRESHOLD = 2.5

#: Internal division precision. This is deliberately much higher than the
#: two-decimal display quantum and is not used to round calculation weights.
DECIMAL_PRECISION = 28
DISPLAY_QUANTUM = Decimal("0.01")

_CUTOFF_FIELDS = ("high", "medium", "low", "zscore_threshold")


def _decimal(value: Any, field: str) -> Decimal:
    """Convert one JSON number to an exact decimal without rounding it.

    ``bool`` is rejected explicitly because it is an ``int`` subclass. Strings,
    ``Decimal`` objects and all other non-JSON-number types are rejected too:
    accepting them would make the API's number contract ambiguous.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a JSON number")
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise ValueError(f"{field} must be finite")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _nonnegative_float(value: Any, field: str) -> float:
    number = _decimal(value, field)
    if number < 0:
        raise ValueError(f"{field} must be non-negative")
    return float(number)


def validate_weight_values(weights: Mapping[str, Any]) -> Dict[str, float]:
    """Validate one complete five-weight submission without normalizing it.

    Unknown or missing keys, booleans, strings, non-finite numbers, negatives
    and an all-zero set are rejected. A positive total other than 1.0 is valid;
    normalization belongs to :class:`ConfidencePolicy` so the submitted values
    remain available separately.

    The returned mapping is a plain dict in :data:`WEIGHT_KEYS` order. Values
    are converted to floats for storage but are not rounded or normalized.
    """
    if not isinstance(weights, Mapping):
        raise ValueError("weights must be an object")
    unknown = sorted(set(weights) - set(WEIGHT_KEYS))
    if unknown:
        raise ValueError(f"unknown weight key(s): {', '.join(unknown)}")
    missing = [key for key in WEIGHT_KEYS if key not in weights]
    if missing:
        raise ValueError(f"missing weight key(s): {', '.join(missing)}")

    values = {
        key: _nonnegative_float(weights[key], f"weights.{key}")
        for key in WEIGHT_KEYS
    }
    total = sum((Decimal(str(values[key])) for key in WEIGHT_KEYS),
                Decimal("0"))
    if total == 0:
        raise ValueError("weights must not all be zero")
    return values


def _current_weights(
    current: Optional[Union["ConfidencePolicy", Mapping[str, Any]]],
) -> Dict[str, float]:
    if current is None:
        return dict(DEFAULT_WEIGHTS)
    if isinstance(current, ConfidencePolicy):
        return dict(current.submitted_weights)
    if not isinstance(current, Mapping):
        raise ValueError("current weights must be a ConfidencePolicy or object")
    unknown = sorted(set(current) - set(WEIGHT_KEYS))
    if unknown:
        raise ValueError(f"unknown current weight key(s): {', '.join(unknown)}")
    return validate_weight_values(current)


def validate_weight_update(
    payload: Mapping[str, Any],
    current: Optional[Union["ConfidencePolicy", Mapping[str, Any]]] = None,
) -> Dict[str, float]:
    """Merge a partial PUT payload into the effective policy and validate it.

    ``current`` is the effective policy (stored row or documented defaults).
    At least one known key is required. The returned complete five-value mapping
    contains the **submitted** values to persist; this function never normalizes,
    mutates ``current``, or repairs an invalid set.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("weights payload must be an object")
    if not payload:
        raise ValueError("at least one weight is required")

    unknown = sorted(set(payload) - set(WEIGHT_KEYS))
    if unknown:
        raise ValueError(f"unknown weight key(s): {', '.join(unknown)}")

    merged = _current_weights(current)
    for key in WEIGHT_KEYS:
        if key in payload:
            merged[key] = payload[key]
    return validate_weight_values(merged)


def _normalized_decimals(
    submitted: Mapping[str, float],
) -> tuple[Mapping[str, Decimal], bool]:
    """Return effective Decimal values and whether normalization occurred."""
    submitted_decimals = {
        key: Decimal(str(submitted[key])) for key in WEIGHT_KEYS
    }
    total = sum(submitted_decimals.values(), Decimal("0"))
    if total == Decimal("1.0"):
        return MappingProxyType(submitted_decimals), False

    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        effective = {
            key: submitted_decimals[key] / total
            for key in WEIGHT_KEYS
        }
    return MappingProxyType(effective), True


def format_weight(value: Any) -> str:
    """Format one user-facing weight with exactly two decimal places.

    ``ROUND_HALF_UP`` is explicit and independent of the process decimal
    context. This function is for display only and must not feed calculations.
    """
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("weight must be a finite number") from None
    if not number.is_finite():
        raise ValueError("weight must be a finite number")
    return format(number.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP),
                  "f")


def format_weights(
    weights: Union["ConfidencePolicy", Mapping[str, Any]],
) -> Dict[str, str]:
    """Format effective policy weights, or supplied values, for display.

    The values are formatted independently. No final entry is adjusted to make
    the displayed strings add up to ``1.00``.
    """
    source = (weights.effective_decimals
              if isinstance(weights, ConfidencePolicy) else weights)
    return {key: format_weight(source[key]) for key in WEIGHT_KEYS}


@dataclass(frozen=True)
class ConfidencePolicy:
    """The resolved Confidence inputs for one calculation or display path.

    The five public weight fields hold **effective** values. The constructor
    accepts submitted values and normalizes them when their positive total is
    not exactly 1.00. The original values stay available through
    :attr:`submitted_weights`; :attr:`normalization_applied` records whether
    the two views differ.

    Cutoffs and the raw Z threshold are scalars with no clamping or rounding
    applied here.
    """

    rule_compliance: float
    historical: float
    cross_hospital: float
    trend: float
    completeness: float
    high: float
    medium: float
    low: float
    zscore_threshold: float
    normalization_applied: bool = field(init=False, default=False,
                                        compare=False)
    _submitted_decimals: Mapping[str, Decimal] = field(
        init=False, repr=False, compare=False)
    _effective_decimals: Mapping[str, Decimal] = field(
        init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Validate the constructor inputs as submitted weights.
        submitted = validate_weight_values({
            key: getattr(self, key) for key in WEIGHT_KEYS
        })
        for field_name in _CUTOFF_FIELDS:
            object.__setattr__(
                self, field_name,
                _nonnegative_float(getattr(self, field_name),
                                   f"ConfidencePolicy.{field_name}"),
            )

        effective, normalized = _normalized_decimals(submitted)
        for key in WEIGHT_KEYS:
            object.__setattr__(self, key, float(effective[key]))
        object.__setattr__(
            self, "_submitted_decimals",
            MappingProxyType({key: Decimal(str(submitted[key]))
                              for key in WEIGHT_KEYS}),
        )
        object.__setattr__(self, "_effective_decimals", effective)
        object.__setattr__(self, "normalization_applied", normalized)

    @classmethod
    def defaults(cls) -> "ConfidencePolicy":
        return cls(
            rule_compliance=DEFAULT_WEIGHTS["rule_compliance"],
            historical=DEFAULT_WEIGHTS["historical"],
            cross_hospital=DEFAULT_WEIGHTS["cross_hospital"],
            trend=DEFAULT_WEIGHTS["trend"],
            completeness=DEFAULT_WEIGHTS["completeness"],
            high=DEFAULT_HIGH,
            medium=DEFAULT_MEDIUM,
            low=DEFAULT_LOW,
            zscore_threshold=DEFAULT_ZSCORE_THRESHOLD,
        )

    @property
    def submitted_weights(self) -> Mapping[str, float]:
        """Original validated input values, independent of normalization."""
        return MappingProxyType({
            key: float(self._submitted_decimals[key]) for key in WEIGHT_KEYS
        })

    @property
    def effective_weights(self) -> Mapping[str, float]:
        """Normalized values used by analytical consumers."""
        return MappingProxyType({
            key: float(self._effective_decimals[key]) for key in WEIGHT_KEYS
        })

    @property
    def effective_decimals(self) -> Mapping[str, Decimal]:
        """Read-only effective weights at internal Decimal precision."""
        return self._effective_decimals

    def weight_for(self, factor: str) -> float:
        """Return one effective signal weight; unknown factors contribute zero.

        The fallback preserves the legacy ``SIGNAL_WEIGHTS.get(factor, 0)``
        behaviour for an unexpected signal.
        """
        value = self._effective_decimals.get(factor)
        return float(value) if value is not None else 0.0

    def as_weight_mapping(self) -> Dict[str, float]:
        """Return a plain copy of the effective weights for consumers."""
        return {key: self.weight_for(key) for key in WEIGHT_KEYS}
