from typing import List, Dict, Optional

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


def quality_weights(config: Optional[Dict] = None) -> Dict[str, float]:
    """Resolve the four Quality Score weights from config.

    `config` is a mapping keyed by the AppConfig keys (e.g. the dict returned
    by get_config_dict(db, "quality") or {row.key: row.value}). Missing keys
    fall back to the canonical defaults above."""
    cfg = config or {}
    return {
        name: float(cfg.get(key, QUALITY_WEIGHT_DEFAULTS[name]))
        for name, key in QUALITY_WEIGHT_KEYS.items()
    }


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
) -> Dict:
    """Compute the four Quality Score components and the combined score.

    ``layered_results`` — the per-indicator LayerResult rows for this
    hospital+month (data-tree coverage). When supplied, the outlier component
    is the share of those rows flagged HIGH/VERY_HIGH, so the score follows
    the indicators the engine actually analyses instead of only the
    Indicators-screen definitions. ``anomaly_results`` stays the source when
    layered results are unavailable (registry-only legacy fallback).
    """
    cfg = config or {}

    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = compute_completeness(values, required_codes, covered_codes or set())
    consistency = _calc_consistency(rule_results, cfg)
    if layered_results is None:
        outlier_penalty = _calc_outlier_penalty(anomaly_results, cfg)
    else:
        outlier_penalty = _calc_layered_outlier_penalty(layered_results, cfg)

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
                issues.append(f"Anomaly: {a.rate_name} (z={a.z_score})")
    else:
        flagged = [r for r in layered_results
                   if _layered_attr(r, "outlier_level") in FLAGGED_LEVELS]
        for r in flagged[:MAX_LAYERED_ISSUES]:
            issues.append(
                f"Anomaly: {_layered_name(r)} ({_layered_attr(r, 'outlier_level')})")
        if len(flagged) > MAX_LAYERED_ISSUES:
            issues.append(
                f"... and {len(flagged) - MAX_LAYERED_ISSUES} more flagged indicator(s)")

    return {
        "score": score,
        "rule_compliance": round(rule_compliance * 100, 1),
        "completeness": round(completeness * 100, 1),
        "consistency": round(consistency * 100, 1),
        "outlier_penalty": round(outlier_penalty * 100, 1),
        "issues": issues,
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
    cfg = config or {}
    multiplier = cfg.get("outlier_multiplier", 1.5)
    outlier_count = sum(1 for a in anomaly_results if hasattr(a, "is_outlier") and a.is_outlier)
    total = len(anomaly_results)
    if total == 0:
        return 0.0
    ratio = outlier_count / total
    return min(1.0, ratio * multiplier)


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


def _calc_layered_outlier_penalty(layered_results: list,
                                  config: Optional[Dict[str, float]] = None) -> float:
    """Outlier penalty from the data-tree layered analysis.

    Same shape as the classic penalty — share of analysed indicators flagged,
    scaled by ``outlier_multiplier`` and capped at 1.0 — but the denominator
    is every element/rate the layered engine evaluated for this hospital+month
    (the Outlier Diagnostics rows), so the score no longer depends on how many
    definitions happen to be active in the Indicators screen.
    """
    total = len(layered_results or ())
    if total == 0:
        return 0.0
    flagged = sum(1 for r in layered_results
                  if _layered_attr(r, "outlier_level") in FLAGGED_LEVELS)
    multiplier = float((config or {}).get("outlier_multiplier", 1.5))
    return min(1.0, flagged / total * multiplier)
