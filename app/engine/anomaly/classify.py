"""Layered classification: deterministic priority rule table over layer
outputs (spec section 6).

Detection -> Interpretation -> Investigation only. Never modifies the Data
Quality Score. First rule match wins; not-computable layers (None scores)
never count as evidence for a >= comparison, and always count as 'not above'
for <= comparisons.
"""
from dataclasses import dataclass, replace
from typing import Optional

from app.engine.anomaly.layered import (
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_NONE,
    LEVEL_RANK,
    METHOD_INSUFFICIENT_HISTORY,
    METHOD_PEER_ZSCORE,
    AnalysisSpec,
    is_small_denominator,
    level_for_score,
)

# ── Classification enum (spec section 3.1) ────────────────────────────────
TYPE_NORMAL = "NORMAL"
TYPE_RAW_VALUE_ANOMALY = "RAW_VALUE_ANOMALY"
TYPE_RATE_ANOMALY = "RATE_ANOMALY"
TYPE_HISTORICAL_ANOMALY = "HISTORICAL_ANOMALY"
TYPE_VOLUME_DRIVEN_ANOMALY = "VOLUME_DRIVEN_ANOMALY"
TYPE_PEER_ANOMALY = "PEER_ANOMALY"
TYPE_POSSIBLE_DATA_ENTRY_ERROR = "POSSIBLE_DATA_ENTRY_ERROR"
TYPE_CLINICAL_INVESTIGATION_REQUIRED = "CLINICAL_INVESTIGATION_REQUIRED"

_RATE_BASED_TYPES = frozenset({
    TYPE_RATE_ANOMALY,
    TYPE_VOLUME_DRIVEN_ANOMALY,
    TYPE_POSSIBLE_DATA_ENTRY_ERROR,
    TYPE_CLINICAL_INVESTIGATION_REQUIRED,
})

# Rule 2 magnitude guard: rate change >= +300% vs baseline (>= 4x baseline)
RULE2_MIN_CHANGE_PERCENT = 300.0

_INVESTIGATION_RULES = frozenset({2, 4, 6, 7})
_ROUTE_BY_RULE = {
    1: "none", 2: "data_quality", 3: "contextual", 4: "clinical",
    5: "contextual", 6: "contextual", 7: "contextual", 8: "contextual",
    9: "contextual", 10: "none",
}


@dataclass(frozen=True)
class InterpretationNumbers:
    """Actual numbers the text builder may cite (spec section 6)."""
    raw_value: Optional[float] = None
    previous_value: Optional[float] = None
    raw_change_percent: Optional[float] = None
    rate: Optional[float] = None
    denominator: Optional[float] = None
    denominator_change_percent: Optional[float] = None
    historical_mean: Optional[float] = None
    historical_change_percent: Optional[float] = None
    peer_mean: Optional[float] = None
    peer_count: int = 0


@dataclass(frozen=True)
class Classification:
    outlier_type: str
    outlier_level: str
    investigation_required: bool
    investigation_route: str
    rule_number: int
    method: str
    interpretation: str


def _at_least(score: Optional[float], min_level: str) -> bool:
    if score is None:
        return False
    return LEVEL_RANK[level_for_score(score)] >= LEVEL_RANK[min_level]


def _at_most(score: Optional[float], max_level: str) -> bool:
    if score is None:
        return True                      # not computable => not above
    return LEVEL_RANK[level_for_score(score)] <= LEVEL_RANK[max_level]


def _at_least_any(scores: tuple, min_level: str) -> bool:
    return any(_at_least(s, min_level) for s in scores)


def _max_level(*scores: Optional[float]) -> str:
    best = LEVEL_NONE
    for s in scores:
        if s is None:
            continue
        lvl = level_for_score(s)
        if LEVEL_RANK[lvl] > LEVEL_RANK[best]:
            best = lvl
    return best


def _method_for_rule(rule: int, raw_method: str, rate_method: str,
                     hist_method: str) -> str:
    if rule == 1:
        return METHOD_INSUFFICIENT_HISTORY
    if rule in (2, 4, 9):
        return rate_method
    if rule == 5:
        return hist_method
    if rule in (6, 7):
        return METHOD_PEER_ZSCORE
    return raw_method                      # rules 3, 8, 10


def build_interpretation(spec: AnalysisSpec, outlier_type: str,
                         rule_number: int, *, den_ok: bool,
                         numbers: InterpretationNumbers) -> str:
    """Compose the human-readable explanation from actual numbers (English;
    chrome i18n happens in the frontend, not here)."""
    if rule_number == 1:
        lead = (f"Not enough history: needs at least "
                f"{spec.minimum_history_period} prior months")
    elif rule_number == 10:
        lead = "No layer exceeded its threshold"
    elif outlier_type == TYPE_POSSIBLE_DATA_ENTRY_ERROR:
        lead = ("All layers spike together while the denominator is stable "
                "- consistent with a data-entry error; verify source values "
                "before acting")
    elif outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED:
        lead = ("Rate and history are both high with a stable denominator "
                "- consistent with a genuine clinical change; investigate "
                "clinically")
    elif outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY:
        lead = ("The jump tracks a denominator (activity-volume) shift "
                "- volume-driven, not a per-case change")
    elif outlier_type == TYPE_HISTORICAL_ANOMALY:
        lead = "Deviation from this hospital's own recent baseline"
    elif outlier_type == TYPE_PEER_ANOMALY and rule_number == 7:
        lead = ("Differs from peers and from its own recent history; both "
                "deviations are stated below")
    elif outlier_type == TYPE_PEER_ANOMALY:
        lead = ("Consistently differs from peers; review case mix, referral "
                "pattern, and indicator definition")
    elif outlier_type == TYPE_RATE_ANOMALY:
        lead = "Rate deviates from its recent pattern"
    else:
        lead = "Raw value deviates from its recent pattern"

    tails = []
    if numbers.raw_value is not None:
        if (numbers.previous_value is not None
                and numbers.raw_change_percent is not None):
            tails.append(
                f"{spec.name} {numbers.raw_value:g} vs "
                f"{numbers.previous_value:g} "
                f"({numbers.raw_change_percent:+.0f}% vs previous month)")
        else:
            tails.append(f"{spec.name} {numbers.raw_value:g}")
    if (numbers.historical_mean is not None
            and numbers.historical_change_percent is not None):
        direction = ("above" if numbers.historical_change_percent >= 0
                     else "below")
        tails.append(
            f"{abs(numbers.historical_change_percent):+.0f}% {direction} "
            f"baseline mean {numbers.historical_mean:g}")
    if numbers.rate is not None:
        tails.append(f"rate {numbers.rate:.1f}{spec.unit}")
    if numbers.denominator is not None:
        if numbers.denominator_change_percent is not None:
            tails.append(
                f"denominator {numbers.denominator:g} "
                f"({numbers.denominator_change_percent:+.0f}% vs previous)")
        else:
            tails.append(f"denominator {numbers.denominator:g}")
    if numbers.peer_mean is not None and numbers.peer_count:
        tails.append(f"peer average {numbers.peer_mean:.1f} across "
                     f"{numbers.peer_count} hospitals")
    if not den_ok:
        tails.append("denominator missing or zero - rate layers not "
                     "computable")
    # The cap applies only to rate-based types; a non-rate classification
    # must never claim its level was lowered by the guard.
    if (outlier_type in _RATE_BASED_TYPES
            and is_small_denominator(spec, numbers.denominator)):
        tails.append(
            f"small denominator ({numbers.denominator:g} < "
            f"{spec.minimum_denominator:g}) - confidence lowered, level "
            f"capped at LOW")

    if tails:
        return f"{lead}. " + "; ".join(tails) + "."
    return lead + "."


def classify_layered(
    spec: AnalysisSpec,
    *,
    raw_score: Optional[float],
    rate_score: Optional[float],
    hist_score: Optional[float],
    volume_score: Optional[float],
    peer_score: Optional[float],
    den_ok: bool,
    history_ok: bool,
    change_percent: Optional[float] = None,
    denominator: Optional[float] = None,
    raw_method: str = METHOD_INSUFFICIENT_HISTORY,
    rate_method: str = METHOD_INSUFFICIENT_HISTORY,
    hist_method: str = METHOD_INSUFFICIENT_HISTORY,
    numbers: Optional[InterpretationNumbers] = None,
) -> Classification:
    """Spec section 6 rule table: first match wins."""
    if not history_ok:
        rule, outlier_type = 1, TYPE_NORMAL
    elif (den_ok
          and _at_least(raw_score, LEVEL_HIGH)
          and _at_least(rate_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_HIGH)
          and _at_most(volume_score, LEVEL_LOW)
          and change_percent is not None
          and change_percent >= RULE2_MIN_CHANGE_PERCENT):
        rule, outlier_type = 2, TYPE_POSSIBLE_DATA_ENTRY_ERROR
    elif (_at_least(raw_score, LEVEL_HIGH)
          and _at_least(volume_score, LEVEL_HIGH)
          and _at_most(rate_score, LEVEL_MODERATE)):
        rule, outlier_type = 3, TYPE_VOLUME_DRIVEN_ANOMALY
    elif (den_ok
          and _at_least(rate_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_HIGH)
          and _at_most(volume_score, LEVEL_LOW)):
        rule, outlier_type = 4, TYPE_CLINICAL_INVESTIGATION_REQUIRED
    elif _at_least(hist_score, LEVEL_HIGH):
        rule, outlier_type = 5, TYPE_HISTORICAL_ANOMALY
    elif (_at_least(peer_score, LEVEL_HIGH)
          and _at_most(hist_score, LEVEL_LOW)):
        rule, outlier_type = 6, TYPE_PEER_ANOMALY
    elif (_at_least(peer_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_MODERATE)):
        rule, outlier_type = 7, TYPE_PEER_ANOMALY
    elif (_at_least(raw_score, LEVEL_MODERATE)
          and not _at_least_any((rate_score, hist_score, volume_score,
                                 peer_score), LEVEL_HIGH)):
        rule, outlier_type = 8, TYPE_RAW_VALUE_ANOMALY
    elif (_at_least(rate_score, LEVEL_MODERATE)
          and not _at_least_any((raw_score, hist_score, volume_score,
                                 peer_score), LEVEL_HIGH)):
        rule, outlier_type = 9, TYPE_RATE_ANOMALY
    else:
        rule, outlier_type = 10, TYPE_NORMAL

    level = LEVEL_NONE if rule == 1 else _max_level(
        raw_score, rate_score, hist_score, volume_score, peer_score)
    if (outlier_type in _RATE_BASED_TYPES
            and is_small_denominator(spec, denominator)):
        if LEVEL_RANK[level] > LEVEL_RANK[LEVEL_LOW]:
            level = LEVEL_LOW

    numbers = numbers or InterpretationNumbers()
    if numbers.denominator is None and denominator is not None:
        numbers = replace(numbers, denominator=denominator)

    return Classification(
        outlier_type=outlier_type,
        outlier_level=level,
        investigation_required=rule in _INVESTIGATION_RULES,
        investigation_route=_ROUTE_BY_RULE[rule],
        rule_number=rule,
        method=_method_for_rule(rule, raw_method, rate_method, hist_method),
        interpretation=build_interpretation(
            spec, outlier_type, rule, den_ok=den_ok, numbers=numbers),
    )
