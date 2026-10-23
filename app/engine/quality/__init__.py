from typing import Dict, Optional

from sqlalchemy.orm import Session

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
    get_covered_child_codes,
    compute_covered_codes,
    set_rules_config,
)
from .scoring import (
    calculate_quality_score,
    compute_completeness,
    quality_weights,
    combine_quality_score,
    QUALITY_WEIGHT_KEYS,
    QUALITY_WEIGHT_DEFAULTS,
    SEVERITY_WEIGHT_DEFAULTS,
    severity_weights,
    FLAGGED_LEVELS,
)
from .definitions import _RULES_CONFIG as _RULES_CONFIG, RULE_CATALOG


def run_quality_analysis(
    values: Dict[str, float],
    hospital_name: str = "",
    month: str = "",
    all_hospital_data: Optional[Dict[str, Dict[str, float]]] = None,
    historical_data: Optional[Dict[str, Dict[str, float]]] = None,
    anomaly_results: Optional[list] = None,
    required_codes: Optional[set] = None,
    disabled_codes: Optional[set] = None,
    score_config: Optional[Dict[str, float]] = None,
    session: Optional["Session"] = None,
    layered_results: Optional[list] = None,
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

    # doctrine §2: always pass db so user rules (e.g. parent_le R061) drive coverage
    covered_codes = compute_covered_codes(values, disabled_codes or set(), session)

    score = calculate_quality_score(
        rule_results=rule_results,
        values=values,
        anomaly_results=anomaly_results or [],
        required_codes=required_codes or set(),
        config=score_config,
        covered_codes=covered_codes,
        layered_results=layered_results,
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
    "get_covered_child_codes",
    "compute_covered_codes",
    "set_rules_config",
    "calculate_quality_score",
    "compute_completeness",
    "quality_weights",
    "combine_quality_score",
    "QUALITY_WEIGHT_KEYS",
    "QUALITY_WEIGHT_DEFAULTS",
    "SEVERITY_WEIGHT_DEFAULTS",
    "severity_weights",
    "FLAGGED_LEVELS",
    "run_quality_analysis",
]
