"""Layered classification: deterministic priority rule table over layer
outputs (spec section 6).

Detection -> Interpretation -> Investigation only. Never modifies the Data
Quality Score. First rule match wins; not-computable layers (None scores)
never count as evidence for a >= comparison, and always count as 'not above'
for <= comparisons.

Insufficient-history policy (rule 1 / rule 11)
---------------------------------------------
A month whose own-history baseline is not evaluable used to be classified as
NORMAL/NONE, which silently discarded an independent peer deviation. The
approved policy is explicit and peer-aware:

* **No strong peer evidence** (peer layer unavailable, or its band below
  HIGH) -> ``INSUFFICIENT_HISTORY`` with level NONE. This is an assessment
  that could not be made, not evidence of normal behaviour. The peer score
  stays stored so a MODERATE deviation is still visible in the layer strip.
* **Strong peer evidence** (peer band HIGH or VERY_HIGH) -> ``PEER_ANOMALY``
  (rule 11). The deviation is confirmed against the peer baseline even though
  the hospital's own history is too short to compare with; the type and the
  NULL history score keep it distinct from a history-confirmed anomaly.

The HIGH boundary is the same one rules 6/7 already require, and levels are
the stored bands -- a peer score is never promoted beyond its own band. As
for every other rule, the overall level is the highest applicable layer
band (a volume shift can therefore outrank the peer band; the type still
names peer evidence as the reason).

Conflicting evidence is resolved by the rule table's precedence and stated
in the interpretation: history HIGH with quiet peers stays
``HISTORICAL_ANOMALY`` (rule 5), peer HIGH with quiet history is
``PEER_ANOMALY`` (rule 6), both HIGH keeps rules 2/4/5 (a confirmed anomaly,
not a conflict).
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
    MIN_PEERS_FOR_TOP_BAND,
    THIN_PEER_LEVEL_CAP,
    ZERO_SPREAD_LEVEL_CAP,
    AnalysisSpec,
    is_small_denominator,
    level_for_score,
)

# ── Classification enum (spec section 3.1) ────────────────────────────────
TYPE_NORMAL = "NORMAL"
# Assessment withheld: the own-history baseline is not evaluable and no
# independent peer deviation reached HIGH (see the module docstring).
TYPE_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
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

_INVESTIGATION_RULES = frozenset({2, 4, 6, 7, 11})
_ROUTE_BY_RULE = {
    1: "none", 2: "data_quality", 3: "contextual", 4: "clinical",
    5: "contextual", 6: "contextual", 7: "contextual", 8: "contextual",
    9: "contextual", 10: "none", 11: "contextual",
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
    peer_score: Optional[float] = None


@dataclass(frozen=True)
class Classification:
    outlier_type: str
    outlier_level: str
    investigation_required: bool
    investigation_route: str
    rule_number: int
    method: str
    interpretation: str
    # Degenerate comparisons (comparison values all identical): their band was
    # capped at HIGH, and ``level_capped_from`` keeps the band the raw scores
    # alone implied. Empty/None on every measured comparison.
    zero_spread_layers: tuple = ()
    level_capped_from: Optional[str] = None
    # Layers whose percentage-change score was clamped to the score their own
    # window's z supports (layered.PCT_CHANGE_CAP_POLICY).
    pct_change_capped: tuple = ()
    # Peer comparisons with fewer than layered.MIN_PEERS_FOR_TOP_BAND other
    # hospitals: the peer spread cannot be measured from that few, so their
    # band was capped at HIGH and no z-score was produced for them
    # (layered.PEER_Z_POLICY). The peer score and peer list are unchanged.
    thin_peer_layers: tuple = ()


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


# Layer name -> human label used to explain a zero-dispersion cap.
_LAYER_LABELS = {
    "raw": "raw-value comparison",
    "rate": "rate comparison",
    "historical": "own-history baseline",
    "volume": "denominator shift",
    "peer": "peer comparison",
}


def _layer_band(name: str, score: Optional[float],
                degenerate: frozenset,
                thin_peer: frozenset = frozenset()) -> Optional[str]:
    """One layer's band, capped when its comparison cannot grade a magnitude.

    Two caps apply, both per layer and never per row — a degenerate or thin
    comparison must not suppress a level another, measured layer earned:
    zero dispersion (all comparison values identical) and too few peers
    (the peer spread cannot be measured from 2-3 hospitals).
    """
    band = level_for_score(score)
    if band is None:
        return None
    if name in degenerate and LEVEL_RANK[band] > LEVEL_RANK[ZERO_SPREAD_LEVEL_CAP]:
        return ZERO_SPREAD_LEVEL_CAP
    if name in thin_peer and LEVEL_RANK[band] > LEVEL_RANK[THIN_PEER_LEVEL_CAP]:
        return THIN_PEER_LEVEL_CAP
    return band


def _capped_layers(scores, degenerate: frozenset) -> tuple:
    """Degenerate layers whose own band exceeded the cap."""
    names = []
    for name, score in scores:
        band = level_for_score(score)
        if (name in degenerate and band is not None
                and LEVEL_RANK[band] > LEVEL_RANK[ZERO_SPREAD_LEVEL_CAP]):
            names.append(name)
    return tuple(names)


def _thin_peer_capped_layers(scores, thin_peer: frozenset) -> tuple:
    """Thin-peer layers whose own band exceeded the cap."""
    names = []
    for name, score in scores:
        band = level_for_score(score)
        if (name in thin_peer and band is not None
                and LEVEL_RANK[band] > LEVEL_RANK[THIN_PEER_LEVEL_CAP]):
            names.append(name)
    return tuple(names)


def _method_for_rule(rule: int, raw_method: str, rate_method: str,
                     hist_method: str,
                     peer_method: str = METHOD_PEER_ZSCORE) -> str:
    if rule == 1:
        return METHOD_INSUFFICIENT_HISTORY
    if rule in (2, 4, 9):
        return rate_method
    if rule == 5:
        return hist_method
    if rule == 11:
        return peer_method                 # peer-only evidence
    if rule in (6, 7):
        return METHOD_PEER_ZSCORE
    return raw_method                      # rules 3, 8, 10


def _peer_evidence_phrase(peer_level: Optional[str],
                          peer_score: Optional[float]) -> str:
    """One clause stating what the peer layer contributed (never promotion)."""
    score_text = (f" (score {peer_score:.2f})"
                  if peer_score is not None else "")
    if peer_level is None:
        return ("peer comparison unavailable - no independent peer evidence "
                "either way")
    if LEVEL_RANK[peer_level] < LEVEL_RANK[LEVEL_MODERATE]:
        return f"peer comparison {peer_level}{score_text} - no peer deviation"
    if LEVEL_RANK[peer_level] < LEVEL_RANK[LEVEL_HIGH]:
        return (f"peer comparison {peer_level}{score_text} is below the HIGH "
                "threshold - not enough to classify without history")
    return f"peer comparison {peer_level}{score_text}"


def build_interpretation(spec: AnalysisSpec, outlier_type: str,
                         rule_number: int, *, den_ok: bool,
                         numbers: InterpretationNumbers,
                         hist_level: Optional[str] = None,
                         peer_level: Optional[str] = None,
                         zero_spread_layers: tuple = (),
                         pct_change_capped: tuple = (),
                         thin_peer_layers: tuple = ()) -> str:
    """Compose the human-readable explanation from actual numbers (English;
    chrome i18n happens in the frontend, not here).

    ``hist_level`` / ``peer_level`` are the stored bands of the two evidence
    sources, used to state an agreement or a conflict explicitly.
    """
    if rule_number == 1:
        lead = (f"Not enough history: needs at least "
                f"{spec.minimum_history_period} prior months - this month is "
                "not assessable against its own baseline, so it is not a "
                "confirmed normal result")
    elif rule_number == 11:
        lead = (f"Not enough history: needs at least "
                f"{spec.minimum_history_period} prior months, but the peer "
                "comparison is significant - a peer deviation is confirmed "
                "while the hospital's own baseline is not assessable")
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
    if rule_number in (1, 11):
        # The peer layer is the ONLY evidence available when history is too
        # short, so the interpretation must say what it found and why it did
        # or did not change the verdict.
        tails.append(_peer_evidence_phrase(peer_level, numbers.peer_score))
    elif rule_number == 5 and peer_level is not None:
        tails.append("peer comparison also " + peer_level
                     if LEVEL_RANK[peer_level] >= LEVEL_RANK[LEVEL_MODERATE]
                     else "peer comparison " + peer_level
                     + " - peers do not share this deviation")
    elif rule_number == 6:
        tails.append((f"own history {hist_level} - no deviation from its own "
                      "baseline") if hist_level is not None else
                     "own history not assessable - the peer comparison is the "
                     "evidence")
    if not den_ok:
        tails.append("denominator missing or zero - rate layers not "
                     "computable")
    # A degenerate comparison cannot grade a magnitude: the score builders
    # fall back to 1.0 when the spread is 0, so the band must say so instead of
    # quoting an unmeasurable maximum.
    if zero_spread_layers:
        labels = ", ".join(_LAYER_LABELS.get(name, name)
                           for name in zero_spread_layers)
        tails.append(
            f"{labels} has no spread (all values identical) - the deviation "
            f"cannot be graded, so the level is capped at {ZERO_SPREAD_LEVEL_CAP}")
    # A percentage change is not a measured magnitude: it divides by the
    # baseline, so it is clamped to the band the same window's z supports.
    # Say so, otherwise "+93% but no outlier" reads like a contradiction.
    if pct_change_capped:
        labels = ", ".join(_LAYER_LABELS.get(name, name)
                           for name in pct_change_capped)
        tails.append(
            f"{labels}: the percentage change is not graded on its own - it "
            "is clamped to the level the same window's z-score supports, "
            "because a relative change ignores how much the series normally "
            "varies"
        )
    # A peer z-score divides by the spread of the other hospitals' values: with
    # 2-3 of them that spread is barely measurable, so the peer comparison is
    # not allowed to claim the top band on it. Say so, and say what the
    # comparison DID find, so "differs from peers but only HIGH" is explained.
    if thin_peer_layers:
        labels = ", ".join(_LAYER_LABELS.get(name, name)
                           for name in thin_peer_layers)
        tails.append(
            f"{labels} has fewer than {MIN_PEERS_FOR_TOP_BAND} peer hospitals "
            "- too few to measure a spread, so the level is capped at "
            f"{THIN_PEER_LEVEL_CAP} and no z-score is produced for it; the "
            "deviation itself is still reported"
        )
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
    peer_method: str = METHOD_PEER_ZSCORE,
    numbers: Optional[InterpretationNumbers] = None,
    degenerate_layers: tuple = (),
    pct_change_capped: tuple = (),
    thin_peer_layers: tuple = (),
) -> Classification:
    """Spec section 6 rule table: first match wins.

    Rule 1 (insufficient history) is split by peer evidence: a HIGH peer band
    classifies as PEER_ANOMALY (rule 11), everything else as
    INSUFFICIENT_HISTORY with no level. See the module docstring.
    """
    if not history_ok:
        if _at_least(peer_score, LEVEL_HIGH):
            rule, outlier_type = 11, TYPE_PEER_ANOMALY
        else:
            rule, outlier_type = 1, TYPE_INSUFFICIENT_HISTORY
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

    layer_scores = (
        ("raw", raw_score),
        ("rate", rate_score),
        ("historical", hist_score),
        ("volume", volume_score),
        ("peer", peer_score),
    )
    degenerate = frozenset(degenerate_layers or ())
    thin_peer = frozenset(thin_peer_layers or ())
    level_from_layers = LEVEL_NONE if rule == 1 else _max_level(
        raw_score, rate_score, hist_score, volume_score, peer_score)
    level = LEVEL_NONE
    if rule != 1:
        for name, score in layer_scores:
            band = _layer_band(name, score, degenerate, thin_peer)
            if band is not None and LEVEL_RANK[band] > LEVEL_RANK[level]:
                level = band
    zero_spread_layers = _capped_layers(layer_scores, degenerate)
    if LEVEL_RANK[level] >= LEVEL_RANK[level_from_layers]:
        zero_spread_layers = ()          # nothing was actually capped
    # A thin peer group is reported only when it actually lowered the level: a
    # row another measured layer holds at VERY_HIGH is not a capped-thin-peer
    # row and must not be explained as one.
    thin_capped = _thin_peer_capped_layers(layer_scores, thin_peer)
    if thin_capped:
        uncapped = LEVEL_NONE
        for name, score in layer_scores:
            band = _layer_band(name, score, degenerate)
            if band is not None and LEVEL_RANK[band] > LEVEL_RANK[uncapped]:
                uncapped = band
        if LEVEL_RANK[level] >= LEVEL_RANK[uncapped]:
            thin_capped = ()
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
        method=_method_for_rule(rule, raw_method, rate_method, hist_method,
                                peer_method),
        interpretation=build_interpretation(
            spec, outlier_type, rule, den_ok=den_ok, numbers=numbers,
            hist_level=_layer_band("historical", hist_score, degenerate,
                                   thin_peer),
            peer_level=_layer_band("peer", peer_score, degenerate, thin_peer),
            zero_spread_layers=zero_spread_layers,
            pct_change_capped=pct_change_capped,
            thin_peer_layers=thin_capped),
        zero_spread_layers=zero_spread_layers,
        level_capped_from=(level_from_layers
                           if (zero_spread_layers or thin_capped) else None),
        pct_change_capped=tuple(pct_change_capped or ()),
        thin_peer_layers=thin_capped,
    )
