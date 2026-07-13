from typing import List, Dict, Tuple
from app.engine.quality import RuleResult, RuleStatus, Severity


def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    active_indicator_count: int,
) -> Dict:
    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = _calc_completeness(values, active_indicator_count)
    consistency = _calc_consistency(rule_results)
    outlier_penalty = _calc_outlier_penalty(anomaly_results)

    raw_score = (
        rule_compliance * 0.35
        + completeness * 0.25
        + consistency * 0.25
        + (1.0 - outlier_penalty) * 0.15
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


def _calc_consistency(rule_results: List[RuleResult]) -> float:
    if not rule_results:
        return 1.0
    severity_weights = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
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


def _calc_outlier_penalty(anomaly_results: list) -> float:
    if not anomaly_results:
        return 0.0
    outlier_count = sum(1 for a in anomaly_results if hasattr(a, "is_outlier") and a.is_outlier)
    total = len(anomaly_results)
    if total == 0:
        return 0.0
    ratio = outlier_count / total
    return min(1.0, ratio * 2)