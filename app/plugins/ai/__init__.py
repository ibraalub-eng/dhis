from typing import List, Dict, Optional

from app.plugins.ai.cache import get_ai_cache, set_ai_cache
from app.plugins.ai.providers import (
    AI_ENABLED, AI_API_KEY,
    AIRuleDef,
    _call_api,
    _parse_response,
    _local_clinical_fallback,
    _local_executive_summary_fallback,
    _local_root_cause_fallback,
    _local_root_cause_fallback_enhanced,
)
from app.plugins.ai.prompts import (
    _build_prompt,
    _build_executive_summary_prompt,
    _build_root_cause_prompt,
    _build_root_cause_prompt_enhanced,
)


def generate(
    values: Dict[str, float],
    classifications: List,
    risk_profile,
    morbidity_profile,
    quality_score: Optional[float] = None,
    session=None,
) -> List[AIRuleDef]:
    if not AI_ENABLED:
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    if not AI_API_KEY:
        import logging
        logging.getLogger(__name__).warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    prompt = _build_prompt(values, classifications, risk_profile, morbidity_profile, quality_score)
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                try:
                    return _parse_response(cached)
                except Exception:
                    pass
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    try:
        return _parse_response(response)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to parse AI response: {e}")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)


def generate_executive_summary(
    hospital: str,
    month: str,
    values: Dict[str, float],
    quality_score: float,
    completeness: float = 0,
    consistency: float = 0,
    rule_compliance: float = 0,
    outlier_penalty: float = 0,
    rule_results: List = None,
    anomaly_results: List = None,
    trend_data: Dict = None,
    all_hospital_data: Dict = None,
    classifications: List = None,
    risk_profile=None,
    morbidity_profile=None,
    session=None,
) -> str:
    if not AI_ENABLED or not AI_API_KEY:
        return _local_executive_summary_fallback(
            hospital, month, quality_score, completeness, consistency,
            rule_compliance, outlier_penalty, rule_results, anomaly_results,
            classifications, risk_profile, morbidity_profile,
        )
    prompt = _build_executive_summary_prompt(
        hospital, month, values, quality_score, completeness, consistency,
        rule_compliance, outlier_penalty, rule_results or [],
        anomaly_results or [], trend_data or {}, all_hospital_data or {},
        classifications, risk_profile, morbidity_profile,
    )
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                return cached
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        return _local_executive_summary_fallback(
            hospital, month, quality_score, completeness, consistency,
            rule_compliance, outlier_penalty, rule_results, anomaly_results,
            classifications, risk_profile, morbidity_profile,
        )
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    return response.strip()


def generate_root_cause_ai(report_data: dict, session=None) -> List[AIRuleDef]:
    has_historical = bool(report_data.get("historical_trends") or report_data.get("peer_comparisons"))

    if not AI_ENABLED:
        if has_historical:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
    if not AI_API_KEY:
        import logging
        logging.getLogger(__name__).warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        if has_historical:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)

    prompt = _build_root_cause_prompt_enhanced(report_data) if has_historical else _build_root_cause_prompt(report_data)
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                try:
                    return _parse_response(cached)
                except Exception:
                    pass
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        if has_historical:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    try:
        return _parse_response(response)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to parse root cause AI response: {e}")
        if has_historical:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
