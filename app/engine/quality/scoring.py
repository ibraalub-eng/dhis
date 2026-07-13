from typing import List, Dict, Optional

from .rules import RuleResult, RuleStatus, Severity


def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    active_indicator_count: int,
    config: Optional[Dict[str, float]] = None,
) -> Dict:
    cfg = config or {}
    w_rc = cfg.get("quality_rule_compliance", 0.35)
    w_cp = cfg.get("quality_completeness", 0.25)
    w_co = cfg.get("quality_consistency", 0.25)
    w_op = cfg.get("quality_outlier_penalty", 0.15)

    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = _calc_completeness(values, active_indicator_count)
    consistency = _calc_consistency(rule_results, cfg)
    outlier_penalty = _calc_outlier_penalty(anomaly_results, cfg)

    raw_score = (
        rule_compliance * w_rc
        + completeness * w_cp
        + consistency * w_co
        + (1.0 - outlier_penalty) * w_op
    ) * 100

    score = max(0, min(100, round(raw_score, 1)))

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


def _calc_completeness(values: Dict[str, float], active_indicator_count: int) -> float:
    if active_indicator_count == 0:
        return 0.0
    filled = sum(1 for v in values.values() if v is not None)
    return filled / active_indicator_count


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
    multiplier = cfg.get("outlier_multiplier", 2.0)
    outlier_count = sum(1 for a in anomaly_results if hasattr(a, "is_outlier") and a.is_outlier)
    total = len(anomaly_results)
    if total == 0:
        return 0.0
    ratio = outlier_count / total
    return min(1.0, ratio * multiplier)
