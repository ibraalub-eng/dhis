import hashlib
import json
from typing import Dict, List, Optional

from .rules import RuleResult, RuleStatus

# The ONE place the four Quality Score weight names + fallbacks live. Every
# surface (engine, dashboard KPI recalc, indicator-config recalc, audit tools,
# score repair) must resolve weights through quality_weights() so they cannot
# drift apart.
QUALITY_WEIGHT_KEYS = {
    "rule_compliance": "quality_rule_compliance",
    "completeness": "quality_completeness",
    "consistency": "quality_consistency",
    "outlier_penalty": "quality_outlier_penalty",
}

QUALITY_WEIGHT_DEFAULTS = {
    "rule_compliance": 0.35,
    "completeness": 0.25,
    "consistency": 0.25,
    "outlier_penalty": 0.15,
}

# Severity weights of the consistency component, keyed by Severity value and
# configured through AppConfig severity_<level>. CRITICAL MUST be listed:
# when it was absent, a CRITICAL failure fell through to the generic 1 and
# therefore counted LESS than a HIGH failure (3) — the one severity that
# blocks a facility lost 3x the impact of an ordinary HIGH one. Its default
# stays 1.0 so adding the setting cannot move any existing score; raise it
# (e.g. to 4) to make CRITICAL dominate.
SEVERITY_WEIGHT_DEFAULTS = {
    "CRITICAL": 1.0,
    "HIGH": 3.0,
    "MEDIUM": 2.0,
    "LOW": 1.0,
}

# One authoritative outlier multiplier. 2.0 is the approved value: it is what
# ``app/main.py`` seeds into AppConfig, what System Control displays, and what
# the engine computed before commit a85b3b3. That commit reduced only the
# HIDDEN FALLBACK to 1.5 without touching the seeded setting, so a path with no
# AppConfig row silently scored differently from every path that loaded it.
# Both penalty components (classic and layered) now share this default, and the
# read-only scoring audit uses PREVIOUS_OUTLIER_MULTIPLIER to recognise rows
# that were actually computed with the old fallback (never to assume they are
# wrong).
OUTLIER_MULTIPLIER_KEY = "outlier_multiplier"
OUTLIER_MULTIPLIER_DEFAULT = 2.0
PREVIOUS_OUTLIER_MULTIPLIER = 1.5

# Every AppConfig key that can change a stored Quality Score.
SEVERITY_WEIGHT_KEYS = {
    name: f"severity_{name.lower()}" for name in SEVERITY_WEIGHT_DEFAULTS
}
# Layered (Data-Tree) levels that count as an outlier for the Quality Score.
# The score's outlier component must cover the indicators the pipeline
# actually analyses — every non-synthetic Data Tree element plus the active
# rate specs — not only the Indicators-screen definitions. Anything milder
# than HIGH (LOW/MODERATE) is a deviation worth showing on the diagnostics
# screen but not a quality penalty.
FLAGGED_LEVELS = frozenset({"HIGH", "VERY_HIGH"})

# Cap on how many flagged layered rows are echoed into the score's issue list
# (a month can flag dozens of elements; the list is meant to be readable).
MAX_LAYERED_ISSUES = 10


def _as_float(value, default: float) -> float:
    """Config value as float; a missing/blank/bad entry keeps the default."""
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def resolve_scoring_config(config: Optional[Dict] = None) -> Dict[str, float]:
    """Every setting that can change a stored Quality Score, fully resolved.

    ``config`` is the AppConfig mapping for category ``quality`` (e.g. from
    ``get_config_dict(db, "quality")``). Missing keys take the canonical
    defaults — including the APPROVED outlier multiplier — so a DB without the
    rows and a DB with them produce the same configuration, and therefore the
    same fingerprint. Values are cast to float, so a config dict coming from a
    text source cannot turn a ratio into a string multiplication.
    """
    cfg = config or {}
    resolved: Dict[str, float] = {
        key: _as_float(cfg.get(key), QUALITY_WEIGHT_DEFAULTS[name])
        for name, key in QUALITY_WEIGHT_KEYS.items()
    }
    resolved[OUTLIER_MULTIPLIER_KEY] = _as_float(
        cfg.get(OUTLIER_MULTIPLIER_KEY), OUTLIER_MULTIPLIER_DEFAULT)
    for name, key in SEVERITY_WEIGHT_KEYS.items():
        resolved[key] = _as_float(cfg.get(key),
                                  SEVERITY_WEIGHT_DEFAULTS[name])
    return resolved


def scoring_config_with_multiplier(multiplier: float,
                                   config: Optional[Dict] = None) -> Dict[str, float]:
    """Current resolved config with the outlier multiplier replaced.

    Used by the audit to fingerprint the configuration the old hidden fallback
    produced, without pretending the rest of that configuration was different.
    """
    resolved = resolve_scoring_config(config)
    resolved[OUTLIER_MULTIPLIER_KEY] = float(multiplier)
    return resolved


def scoring_config_snapshot(config: Optional[Dict] = None) -> str:
    """Canonical JSON of the resolved configuration (the stored evidence)."""
    return json.dumps(resolve_scoring_config(config), sort_keys=True,
                      separators=(",", ":"))


def scoring_config_fingerprint(config: Optional[Dict] = None) -> str:
    """Stable digest of the resolved scoring configuration.

    Same shape as the Quality Alert policy fingerprint: a change to any weight,
    the outlier multiplier or a severity weight changes the digest, so a stored
    score can say which configuration produced it without guessing from
    current settings. Idempotent: passing an already-resolved config yields the
    same digest.
    """
    snapshot = scoring_config_snapshot(config)
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]


def quality_weights(config: Optional[Dict] = None) -> Dict[str, float]:
    """Resolve the four Quality Score weights from config.

    `config` is a mapping keyed by the AppConfig keys (e.g. the dict returned
    by get_config_dict(db, "quality") or {row.key: row.value}). Missing keys
    fall back to the canonical defaults above."""
    resolved = resolve_scoring_config(config)
    return {name: resolved[key] for name, key in QUALITY_WEIGHT_KEYS.items()}


def combine_quality_score(
    rule_compliance,
    completeness,
    consistency,
    outlier_penalty,
    config: Optional[Dict] = None,
) -> float:
    """THE single Quality Score formula.

    All four components are on the 0-100 scale, exactly as stored on a
    QualityScore row. `outlier_penalty` is inverted (a higher penalty lowers
    the score). Returns the final score on the 0-100 scale.
    """
    w = quality_weights(config)
    raw = (
        float(rule_compliance or 0) * w["rule_compliance"]
        + float(completeness or 0) * w["completeness"]
        + float(consistency or 0) * w["consistency"]
        + (100.0 - float(outlier_penalty or 0)) * w["outlier_penalty"]
    )
    return max(0.0, min(100.0, round(raw, 1)))


def compute_completeness(values: Dict[str, float], required_codes, covered_codes=None) -> float:
    """The single completeness formula, DB-free.

    numerator   = number of non-None values passed in `values` (a value of 0
                  counts as Filled; an Optional fill still counts here)
    denominator = required codes minus those covered-by-total that are
                  themselves required (covered Optional codes never shrink it)
    Empty denominator -> 0.0. Result is capped at 1.0.
    """
    required = set(required_codes or ())
    covered = set(covered_codes or ()) & required
    denom = len(required) - len(covered)
    if denom <= 0:
        return 0.0
    filled = sum(1 for v in values.values() if v is not None)
    return min(1.0, filled / denom)


def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    required_codes: set,
    config: Optional[Dict[str, float]] = None,
    covered_codes: Optional[set] = None,
    layered_results: Optional[list] = None,
    outlier_eligible_codes: Optional[set] = None,
    eligible_codes: Optional[set] = None,
) -> Dict:
    """Compute the four Quality Score components and the combined score.

    ``layered_results`` — the per-indicator LayerResult rows for this
    hospital+month (data-tree coverage). When supplied, the outlier component
    is the share of the APPROVED ELIGIBLE assessment units flagged
    HIGH/VERY_HIGH — see ``outlier_eligible_codes`` — so the score follows the
    indicators the engine is required to assess instead of only the rows that
    happened to be evaluated. ``anomaly_results`` stays the source when
    layered results are unavailable (registry-only legacy fallback).
    """
    cfg = config or {}
    # ``eligible_codes`` is the name the denominator policy was specified and
    # tested under; keep it as an alias so both spellings reach one policy.
    if outlier_eligible_codes is None:
        outlier_eligible_codes = eligible_codes

    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = compute_completeness(values, required_codes, covered_codes or set())
    consistency = _calc_consistency(rule_results, cfg)
    if layered_results is None:
        outlier_penalty = anomaly_outlier_penalty(anomaly_results, cfg)
        outlier_denominator = len(anomaly_results or ())
    else:
        outlier_penalty = layered_outlier_penalty(
            layered_results, cfg, eligible_codes=outlier_eligible_codes)
        outlier_denominator = (
            len({c for c in outlier_eligible_codes if c})
            if outlier_eligible_codes is not None
            else len(layered_results or ()))


    score = combine_quality_score(
        rule_compliance * 100,
        completeness * 100,
        consistency * 100,
        outlier_penalty * 100,
        cfg,
    )

    issues = []
    for r in rule_results:
        if r.status == RuleStatus.FAIL:
            issues.append(f"{r.rule_code}: {r.description}")
    if layered_results is None:
        for a in anomaly_results:
            if hasattr(a, "is_outlier") and a.is_outlier:
                # A comparison group too small to measure a spread carries no z
                # (layered.PEER_Z_POLICY): the issue names the peer count
                # rather than the word "None" or an invented magnitude.
                magnitude = (f"z={a.z_score}" if a.z_score is not None
                             else f"no z; {getattr(a, 'peer_count', None) or 'too few'} "
                                  "peer hospital(s) cannot measure a spread")
                issues.append(f"Anomaly: {a.rate_name} ({magnitude})")
    else:
        graded = [(r, layered_severity(r)) for r in layered_results]
        flagged = [(r, g) for r, g in graded if g["level"] in FLAGGED_LEVELS]
        for r, g in flagged[:MAX_LAYERED_ISSUES]:
            shown = g["level"]
            if g["stored_level"] != shown:
                # The cap/gate changed the band: both stay readable.
                shown = f"{shown}; stored {g['stored_level']}"
            issues.append(f"Anomaly: {_layered_name(r)} ({shown})")
        if len(flagged) > MAX_LAYERED_ISSUES:
            issues.append(
                f"... and {len(flagged) - MAX_LAYERED_ISSUES} more flagged indicator(s)")

    resolved = resolve_scoring_config(cfg)
    return {
        "score": score,
        "rule_compliance": round(rule_compliance * 100, 1),
        "completeness": round(completeness * 100, 1),
        "consistency": round(consistency * 100, 1),
        "outlier_penalty": round(outlier_penalty * 100, 1),
        # The assessment-unit denominator the penalty used. Exposed so a
        # stored score can be reproduced even when the eligible set is no
        # longer reconstructible from today's indicator configuration.
        "outlier_denominator": outlier_denominator,
        "issues": issues,
        # Provenance, persisted with the score so a later reader can tell which
        # configuration produced it without consulting today's AppConfig.
        "scoring_fingerprint": scoring_config_fingerprint(resolved),
        "scoring_config": resolved,
    }


def _calc_rule_compliance(rule_results: List[RuleResult]) -> float:
    if not rule_results:
        return 1.0
    passed = sum(1 for r in rule_results if r.status == RuleStatus.PASS)
    total = len(rule_results)
    return passed / total


def _severity_name(severity) -> str:
    """Severity as its upper-case value, whether an enum member or a string."""
    return str(getattr(severity, "value", severity) or "").upper()


def severity_weights(config: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Resolve every severity weight from config (severity_<level> keys).

    The single source of truth for the consistency component: every severity
    the engine can emit has an entry, so none can silently borrow another
    level's weight."""
    cfg = config or {}
    return {
        name: float(cfg.get(f"severity_{name.lower()}", default))
        for name, default in SEVERITY_WEIGHT_DEFAULTS.items()
    }


def _calc_consistency(rule_results: List[RuleResult], config: Optional[Dict[str, float]] = None) -> float:
    if not rule_results:
        return 1.0
    weights = severity_weights(config)
    total_weight = 0
    fail_weight = 0
    for r in rule_results:
        # Unknown severities still get the baseline 1; CRITICAL no longer does.
        w = weights.get(_severity_name(r.severity), 1.0)
        total_weight += w
        if r.status == RuleStatus.FAIL:
            fail_weight += w
    if total_weight == 0:
        return 1.0
    return 1.0 - (fail_weight / total_weight)


def _calc_outlier_penalty(anomaly_results: list, config: Optional[Dict[str, float]] = None) -> float:
    if not anomaly_results:
        return 0.0
    resolved = resolve_scoring_config(config)
    multiplier = resolved[OUTLIER_MULTIPLIER_KEY]
    outlier_count = sum(1 for a in anomaly_results if hasattr(a, "is_outlier") and a.is_outlier)
    total = len(anomaly_results)
    if total == 0:
        return 0.0
    ratio = outlier_count / total
    return min(1.0, ratio * multiplier)


def anomaly_outlier_penalty(anomaly_results: list,
                            config: Optional[Dict[str, float]] = None) -> float:
    """Public entry point for the classic (AnomalyResult) penalty."""
    return _calc_outlier_penalty(anomaly_results, config)


def layered_outlier_penalty(layered_results: list,
                            config: Optional[Dict[str, float]] = None,
                            eligible_codes: Optional[set] = None) -> float:
    """Public entry point for the data-tree (LayeredOutlierResult) penalty.

    ``eligible_codes`` is the approved assessment denominator (see
    ``quality.outlier_eligibility``). When it is omitted the denominator stays
    the number of evaluated rows, preserving the legacy engine contract for
    callers that only have live results.
    """
    return _calc_layered_outlier_penalty(layered_results, config,
                                         eligible_codes=eligible_codes)


def _layered_attr(result, name: str):
    """Read one classification attribute (None-safe).

    Accepts both a live LayerResult (``result.classification.outlier_level``)
    and a persisted LayeredOutlierResult row (``row.outlier_level``) so the
    same penalty can be recomputed from stored rows.
    """
    direct = getattr(result, name, None)
    if direct is not None:
        return direct
    classification = getattr(result, "classification", None)
    return getattr(classification, name, None) if classification is not None else None


def _layered_name(result) -> str:
    spec = getattr(result, "spec", None)
    return (getattr(spec, "name", None) or getattr(spec, "analysis_code", None)
            or getattr(result, "analysis_code", None) or "indicator")


def layered_severity(result) -> Dict[str, object]:
    """The CANONICAL band of one layered result, for scoring and its explanation.

    A LIVE ``LayerResult`` was classified by the engine, which already applies
    the approved caps and the top-band gate — its ``classification.outlier_level``
    IS the effective band. A STORED ``LayeredOutlierResult`` row keeps the band
    it was written with, so its effective band comes from the one policy entry
    point (``layered.row_level_assessment``). Quality Score must never apply a
    policy of its own: two severity scales are how a penalty starts disagreeing
    with the screens that display the same row.

    ``evidence_status`` says what the band rests on:

    ``canonical_layered``    the row's stored scores/provenance, resolved by the
                             approved caps and gate;
    ``stored_level_only``    the row carries its canonical band but none of the
                             layer scores the caps would need (written before
                             those were stored) — the band stands, nothing is
                             demoted and no band is invented;
    ``missing_layered_result``  the row has no band at all.
    """
    from app.engine.anomaly.layered import (
        ROW_LAYER_SCORE_FIELDS,
        row_level_assessment,
    )

    stored = _layered_attr(result, "outlier_level")
    if getattr(result, "classification", None) is not None:
        return {
            "level": stored or "NONE",
            "stored_level": stored or "NONE",
            "has_stored_level": bool(stored),
            "capped": False,
            "cap": None,
            "evidence_status": "canonical_layered",
        }
    if not stored:
        return {
            "level": "NONE",
            "stored_level": "NONE",
            "has_stored_level": False,
            "capped": False,
            "cap": None,
            "evidence_status": "missing_layered_result",
        }
    if all(getattr(result, field, None) is None
           for _name, field in ROW_LAYER_SCORE_FIELDS):
        return {
            "level": stored,
            "stored_level": stored,
            "has_stored_level": True,
            "capped": False,
            "cap": None,
            "evidence_status": "stored_level_only",
        }
    level, cap = row_level_assessment(result)
    return {
        "level": level,
        "stored_level": stored,
        "has_stored_level": True,
        "capped": cap is not None,
        "cap": cap,
        "evidence_status": "canonical_layered",
    }


def _calc_layered_outlier_penalty(layered_results: list,
                                  config: Optional[Dict[str, float]] = None,
                                  eligible_codes: Optional[set] = None) -> float:
    """Outlier penalty from the data-tree layered analysis.

    The numerator is the number of flagged HIGH/VERY_HIGH rows (every finding
    is counted, even in the defensive case where a row's code is not in the
    eligible set); the denominator is the approved eligible set. Missing
    required observations stay in the denominator but contribute no row, so
    incompleteness cannot shrink the denominator and inflate the penalty —
    completeness is already its own component. Zero-valued observations are
    ordinary rows and stay fully eligible.

    Without ``eligible_codes`` the denominator is the number of evaluated rows
    (legacy contract). The pipeline always supplies the approved set.
    """
    rows = list(layered_results or ())
    # The numerator counts the band the APPROVED POLICY assigns (caps and
    # top-band gate included), not the band a row happens to carry: a discarded,
    # capped or score-less row must be counted exactly as the diagnostics screen
    # displays it.
    flagged = sum(1 for r in rows
                  if layered_severity(r)["level"] in FLAGGED_LEVELS)
    if eligible_codes is None:
        denominator = len(rows)
    else:
        denominator = len({code for code in eligible_codes if code})
    if denominator <= 0:
        return 0.0
    multiplier = resolve_scoring_config(config)[OUTLIER_MULTIPLIER_KEY]
    # Findings are never dropped from the numerator, even in the defensive
    # case where a flagged row's code is missing from the eligible set.
    return min(1.0, flagged / denominator * multiplier)
