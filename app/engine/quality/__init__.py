from typing import Dict, Optional

from .rules import (
    Severity,
    RuleType,
    RuleStatus,
    RuleResult,
    ValidationContext,
    ALL_RULES,
    RULE_REF_CODES,
    run_all_rules,
    run_rules_from_db,
    dispatch_rule,
    load_rules_from_db,
    set_rules_config,
)
from .scoring import calculate_quality_score
from .definitions import _RULES_CONFIG as _RULES_CONFIG, RULE_CATALOG


def run_quality_analysis(
    values: Dict[str, float],
    hospital_name: str = "",
    month: str = "",
    all_hospital_data: Optional[Dict[str, Dict[str, float]]] = None,
    historical_data: Optional[Dict[str, Dict[str, float]]] = None,
    anomaly_results: Optional[list] = None,
    active_indicator_count: int = 60,
    disabled_codes: Optional[set] = None,
    score_config: Optional[Dict[str, float]] = None,
) -> Dict:
    ctx = ValidationContext(
        values=values,
        hospital_name=hospital_name,
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data=historical_data,
        disabled_codes=disabled_codes or set(),
    )

    rule_results = run_all_rules(ctx)

    score = calculate_quality_score(
        rule_results=rule_results,
        values=values,
        anomaly_results=anomaly_results or [],
        active_indicator_count=active_indicator_count,
        config=score_config,
    )

    return {
        "rule_results": rule_results,
        "score": score,
    }


__all__ = [
    "Severity",
    "RuleType",
    "RuleStatus",
    "RuleResult",
    "ValidationContext",
    "ALL_RULES",
    "RULE_REF_CODES",
    "RULE_CATALOG",
    "run_all_rules",
    "run_rules_from_db",
    "dispatch_rule",
    "load_rules_from_db",
    "set_rules_config",
    "calculate_quality_score",
    "run_quality_analysis",
]
