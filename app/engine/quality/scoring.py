from typing import List, Dict, Optional

from .rules import RuleResult, RuleStatus, Severity


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
) -> Dict:
    cfg = config or {}

    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = compute_completeness(values, required_codes, covered_codes or set())
    consistency = _calc_consistency(rule_results, cfg)
    outlier_penalty = _calc_outlier_penalty(anomaly_results, cfg)

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
    for a in anomaly_results:
        if hasattr(a, "is_outlier") and a.is_outlier:
            issues.append(f"Anomaly: {a.rate_name} (z={a.z_score})")

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


def _calc_consistency(rule_results: List[RuleResult], config: Optional[Dict[str, float]] = None) -> float:
    if not rule_results:
        return 1.0
    cfg = config or {}
    severity_weights = {
        Severity.HIGH: cfg.get("severity_high", 3),
        Severity.MEDIUM: cfg.get("severity_medium", 2),
        Severity.LOW: cfg.get("severity_low", 1),
    }
    total_weight = 0
    fail_weight = 0
    for r in rule_results:
        w = severity_weights.get(r.severity, 1)
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
