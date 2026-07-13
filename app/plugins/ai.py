# =============================================================================
# plugins/ai.py -- Merged AI recommendations + cache module
# =============================================================================

# Source: ai_cache.py

import json
import hashlib
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import AnalysisCache

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def _make_cache_key(prompt: str) -> str:
    return "ai:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:32]


def get_ai_cache(session: Session, prompt: str) -> str | None:
    key = _make_cache_key(prompt)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if not row:
        return None
    if row.expires_at and datetime.utcnow() > row.expires_at:
        session.delete(row)
        session.commit()
        return None
    try:
        data = json.loads(row.result_json)
        return data.get("response")
    except Exception as e:
        logger.warning(f"Error reading AI cache: {e}")
        return None


def set_ai_cache(session: Session, prompt: str, response: str):
    key = _make_cache_key(prompt)
    expires_at = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if row:
        row.result_json = json.dumps({"response": response})
        row.expires_at = expires_at
    else:
        row = AnalysisCache(
            cache_key=key,
            result_json=json.dumps({"response": response}),
            expires_at=expires_at,
        )
        session.add(row)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to cache AI response: {e}")


import os
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

AI_ENABLED = os.getenv("AI_RECOMMENDATIONS_ENABLED", "false").lower() == "true"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash-lite")
AI_API_URL = os.getenv("AI_API_URL", "")
AI_MAX_RECOMMENDATIONS = int(os.getenv("AI_MAX_RECOMMENDATIONS", "8"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))


def _try_load_db_config():
    global AI_ENABLED, AI_PROVIDER, AI_API_KEY, AI_MODEL, AI_API_URL, AI_MAX_RECOMMENDATIONS, AI_TIMEOUT
    try:
        from app.database import SessionLocal
        from app.config_utils import get_ai_config
        session = SessionLocal()
        try:
            cfg = get_ai_config(session)
            AI_ENABLED = cfg.get("ai_enabled", "true").lower() == "true"
            AI_PROVIDER = cfg.get("ai_provider", "gemini")
            AI_API_KEY = cfg.get("ai_api_key", "")
            AI_MODEL = cfg.get("ai_model", "gemini-2.0-flash-lite")
            AI_API_URL = cfg.get("ai_api_url", "")
            try:
                AI_MAX_RECOMMENDATIONS = int(cfg.get("ai_max_recommendations", "8"))
            except (ValueError, TypeError):
                AI_MAX_RECOMMENDATIONS = 8
            try:
                AI_TIMEOUT = int(cfg.get("ai_timeout", "30"))
            except (ValueError, TypeError):
                AI_TIMEOUT = 30
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"Could not load AI config from DB: {e}")


def reload_ai_config():
    _try_load_db_config()


_try_load_db_config()


@dataclass
class AIRuleDef:
    category: str
    priority: str
    title: str
    description: str
    rationale: str
    action_items: List[str] = field(default_factory=list)
    indicators_monitored: List[str] = field(default_factory=list)


def _build_prompt(
    values: Dict[str, float],
    classifications: List,
    risk_profile,
    morbidity_profile,
    quality_score: Optional[float],
) -> str:
    lines = []
    lines.append("You are a maternal health expert analyzing a hospital's monthly data.")
    lines.append("Generate actionable recommendations based on the following analysis.")
    lines.append("")

    ind_list = "\n".join([f"  {k}: {v}" for k, v in sorted(values.items()) if v is not None])
    lines.append(f"## Indicator Values\n{ind_list}\n")

    if classifications:
        lines.append("## Classifications")
        for c in classifications:
            lines.append(f"  {c.indicator_code} ({c.rate_name}): {c.value}{c.unit} \u2192 {c.classification}")
        lines.append("")

    if risk_profile:
        lines.append(f"## Risk Profile\n  Overall: {risk_profile.overall_risk_level}")
        for m in getattr(risk_profile, "metrics", []):
            lines.append(f"  {m.metric_name}: {m.value}{m.unit} ({m.interpretation}) [{m.severity}]")
        lines.append("")

    if morbidity_profile:
        lines.append(f"## Morbidity Profile\n  SMM: {morbidity_profile.total_smm}, Deaths: {morbidity_profile.maternal_deaths}")
        for signal in getattr(morbidity_profile, "mortality_preventability_signals", []):
            lines.append(f"  Preventability signal: {signal}")
        lines.append("")

    if quality_score is not None:
        lines.append(f"## Data Quality Score\n  {quality_score:.1f}/100\n")

    lines.append("""Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "C-Section Management", "Maternal Mortality", "Data Quality")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the issue)
- rationale: str (medical/public health rationale, 1-2 sentences)
- action_items: list[str] (3-6 specific actionable steps)
- indicators_monitored: list[str] (indicator codes that triggered this)

Analyze the numbers carefully:
- Check if rates exceed WHO thresholds (C-section >15%, SMM >2%, etc.)
- Look for data quality issues (missing values, zeros, inconsistencies)
- Consider risk profile severity
- Prioritize life-threatening conditions first

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)


def _parse_response(text: str) -> List[AIRuleDef]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("recommendations", data.get("choices", []))
    recs = []
    for item in data:
        recs.append(AIRuleDef(
            category=str(item.get("category", "General")),
            priority=str(item.get("priority", "medium")),
            title=str(item.get("title", ""))[:80],
            description=str(item.get("description", "")),
            rationale=str(item.get("rationale", "")),
            action_items=[str(a) for a in item.get("action_items", [])],
            indicators_monitored=[str(i) for i in item.get("indicators_monitored", [])],
        ))
    return recs


def _call_openai_api(prompt: str) -> Optional[str]:
    if not AI_API_KEY:
        logger.warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY not set")
        return None
    try:
        import httpx
        payload = {
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=AI_TIMEOUT) as client:
            resp = client.post(AI_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except ImportError:
        logger.error("httpx not installed. Run: pip install httpx")
        return None
    except Exception as e:
        logger.error(f"AI API call failed: {e}")
        return None


def _call_gemini_api(prompt: str) -> Optional[str]:
    if not AI_API_KEY:
        logger.warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY not set")
        return None
    try:
        from google import genai
        client = genai.Client(api_key=AI_API_KEY)
        response = client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config={
                "temperature": 0.3,
                "max_output_tokens": 2048,
            },
        )
        return response.text
    except ImportError:
        logger.error("google-genai not installed. Run: pip install google-genai")
        return None
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return None


def _call_minimax_api(prompt: str) -> Optional[str]:
    if not AI_API_KEY:
        logger.warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY not set")
        return None
    try:
        import httpx
        payload = {
            "model": AI_MODEL,
            "messages": [{"sender_type": "USER", "sender_name": "user", "text": prompt}],
            "tokens_to_generate": 2048,
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        }
        url = AI_API_URL or "https://api.minimax.chat/v1/text/chatcompletion_v2"
        with httpx.Client(timeout=AI_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if data.get("base_resp", {}).get("status_code") != 0:
            logger.error(f"MiniMax API error: {data}")
            return None
        return data.get("reply")
    except ImportError:
        logger.error("httpx not installed. Run: pip install httpx")
        return None
    except Exception as e:
        logger.error(f"MiniMax API call failed: {e}")
        return None


def _call_api(prompt: str) -> Optional[str]:
    provider = AI_PROVIDER.lower()
    if provider == "gemini":
        return _call_gemini_api(prompt)
    if provider == "minimax":
        return _call_minimax_api(prompt)
    return _call_openai_api(prompt)


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
        logger.warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    prompt = _build_prompt(values, classifications, risk_profile, morbidity_profile, quality_score)
    # Check cache first
    if session is not None:
        try:
            
            cached = get_ai_cache(session, prompt)
            if cached:
                try:
                    return _parse_response(cached)
                except Exception:
                    pass  # Cache parse failed, re-generate
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    # Save to cache
    if session is not None:
        try:
            
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    try:
        return _parse_response(response)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse AI response: {e}\nResponse: {response[:500]}")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)


def _build_executive_summary_prompt(
    hospital: str,
    month: str,
    values: Dict[str, float],
    quality_score: float,
    completeness: float,
    consistency: float,
    rule_compliance: float,
    outlier_penalty: float,
    rule_results: List,
    anomaly_results: List,
    trend_data: Dict,
    all_hospital_data: Dict,
    classifications: List = None,
    risk_profile=None,
    morbidity_profile=None,
) -> str:
    lines = []
    lines.append(f"You are a senior data quality analyst reviewing the monthly report for {hospital} ({month}).")
    lines.append("Write a concise executive narrative summary of the hospital's data quality status.")
    lines.append("Do NOT list individual recommendations. Write a flowing analytical report.")
    lines.append("")
    lines.append(f"## Quality Scores")
    lines.append(f"  Overall: {quality_score}/100")
    lines.append(f"  Completeness: {completeness}%")
    lines.append(f"  Consistency: {consistency}%")
    lines.append(f"  Rule Compliance: {rule_compliance}%")
    lines.append(f"  Outlier Penalty: {outlier_penalty}%")
    lines.append("")

    if rule_results:
        failed = [r for r in rule_results if getattr(r, 'status', None) and r.status.name == "FAIL"]
        passed = [r for r in rule_results if getattr(r, 'status', None) and r.status.name == "PASS"]
        lines.append(f"## Rule Engine Results")
        lines.append(f"  Total rules: {len(rule_results)}")
        lines.append(f"  Passed: {len(passed)}, Failed: {len(failed)}")
        for f in failed[:5]:
            desc = getattr(f, 'description', '') or getattr(f, 'details', '')
            code = getattr(f, 'rule_code', '')
            lines.append(f"  - {code}: {desc[:100]}")
        lines.append("")

    if anomaly_results:
        outliers = [a for a in anomaly_results if getattr(a, 'is_outlier', False)]
        if outliers:
            lines.append(f"## Outlier Detection")
            lines.append(f"  {len(outliers)} outlier(s) detected:")
            for o in outliers[:5]:
                name = getattr(o, 'rate_name', '') or getattr(o, 'indicator', '')
                z = getattr(o, 'z_score', '')
                lines.append(f"  - {name} (z={z})")
            lines.append("")

    if classifications:
        elevated = [c for c in classifications if getattr(c, 'classification', '') in ('high', 'critical')]
        if elevated:
            lines.append(f"## Clinical Threshold Analysis")
            lines.append(f"  {len(elevated)} indicator(s) at elevated clinical risk:")
            for c in elevated[:5]:
                lines.append(f"  - {getattr(c, 'rate_name', '') or getattr(c, 'indicator_code', '')}: {getattr(c, 'value', '')} ({getattr(c, 'classification', '')})")
            lines.append("")

    if risk_profile:
        rl = getattr(risk_profile, 'overall_risk_level', '')
        kf = getattr(risk_profile, 'key_findings', [])
        lines.append(f"## Risk Profile")
        if rl:
            lines.append(f"  Overall Risk Level: {rl}")
        if kf:
            for f in kf[:3]:
                lines.append(f"  - {f}")
        metrics = getattr(risk_profile, 'metrics', [])
        at_risk = [m for m in metrics if getattr(m, 'severity', '') in ('high', 'critical')]
        if at_risk:
            lines.append(f"  Elevated Risk Metrics:")
            for m in at_risk[:3]:
                lines.append(f"    - {getattr(m, 'metric_name', '')}: {getattr(m, 'severity', '')}")
        lines.append("")

    if morbidity_profile:
        smm = getattr(morbidity_profile, 'total_smm', 0)
        deaths = getattr(morbidity_profile, 'maternal_deaths', 0)
        kf = getattr(morbidity_profile, 'key_findings', [])
        lines.append(f"## Maternal Morbidity Profile")
        if smm is not None:
            lines.append(f"  Total SMM Events: {smm}")
        if deaths:
            lines.append(f"  Maternal Deaths: {deaths}")
        if kf:
            for f in kf[:3]:
                lines.append(f"  - {f}")
        lines.append("")

    if values:
        non_null = {k: v for k, v in values.items() if v is not None}
        if non_null:
            important = [(k, v) for k, v in sorted(non_null.items())][:10]
            if important:
                lines.append(f"## Key Indicator Values")
                for k, v in important:
                    lines.append(f"  {k}: {v}")
        lines.append("")

    if trend_data:
        lines.append(f"## Trend Analysis")
        for indicator, points in list(trend_data.items())[:5]:
            direction = "improving" if points.get("slope", 0) > 0 else "declining" if points.get("slope", 0) < 0 else "stable"
            lines.append(f"  {indicator}: {direction} (slope={points.get('slope', 0):.2f})")
        lines.append("")

    if all_hospital_data and len(all_hospital_data) > 1:
        lines.append(f"## Cross-Hospital Benchmarking")
        lines.append(f"  Compared to {len(all_hospital_data) - 1} other hospital(s)")
        lines.append("")

    lines.append("""Write a narrative executive summary covering:
1. Overall data quality status assessment
2. Most significant findings from the rule analysis
3. Patterns, trends, and relationships detected across indicators
4. Impact on data reliability and decision-making
5. Highest-priority actions for improvement
6. Overall assessment of data maturity and reporting performance

Write in clear, professional English. Keep it to 3-5 paragraphs. Do NOT use bullet points or numbered lists.
The summary should read like an executive analytical report written for hospital management — concise, insightful, and actionable.""")
    return "\n".join(lines)


def _local_executive_summary_fallback(
    hospital: str, month: str, quality_score: float, completeness: float,
    consistency: float, rule_compliance: float, outlier_penalty: float,
    rule_results, anomaly_results, classifications=None, risk_profile=None,
    morbidity_profile=None,
) -> str:
    paragraphs = []
    dq = quality_score or 0
    if dq >= 80:
        status = "good"
        status_desc = "meets acceptable standards"
    elif dq >= 60:
        status = "moderate"
        status_desc = "shows moderate concerns that require attention"
    else:
        status = "poor"
        status_desc = "falls below acceptable thresholds and requires urgent improvement"

    p1 = f"Data Quality Assessment for {hospital} ({month}): "
    p1 += f"The overall data quality score is {dq:.1f}/100, which is considered {status} and {status_desc}. "
    p1 += f"Completeness stands at {completeness:.1f}%, consistency at {consistency:.1f}%, "
    p1 += f"rule compliance at {rule_compliance:.1f}%, and the outlier penalty is {outlier_penalty:.1f}%."
    paragraphs.append(p1)

    failed_rules = [r for r in (rule_results or []) if getattr(r, 'status', None) and r.status.name == "FAIL"]
    if failed_rules:
        codes = [r.rule_code for r in failed_rules[:5]]
        p2 = f"The analysis identified {len(failed_rules)} rule violation(s), including: {', '.join(codes)}. "
        p2 += "These violations indicate inconsistencies or errors in the reported data that should be investigated and corrected."
        paragraphs.append(p2)
    else:
        paragraphs.append("No rule violations were detected, indicating the reported data is internally consistent.")

    outliers = [a for a in (anomaly_results or []) if getattr(a, 'is_outlier', False)]
    if outliers:
        names = [getattr(o, 'rate_name', '') or getattr(o, 'indicator', '') for o in outliers[:3]]
        p3 = f"{len(outliers)} statistical outlier(s) were detected ({', '.join(names)}), suggesting these indicators deviate significantly from hospital averages. "
        p3 += "These should be verified for data entry errors or investigated for genuine clinical variation."
        paragraphs.append(p3)

    # Clinical threshold analysis
    if classifications:
        elevated = [c for c in classifications if getattr(c, 'classification', '') in ('high', 'critical')]
        if elevated:
            names = [getattr(c, 'rate_name', '') or getattr(c, 'indicator_code', '') for c in elevated[:5]]
            p_clin = f"From a clinical perspective, {len(elevated)} indicator(s) are at elevated risk levels ({', '.join(names)}). "
            p_clin += "These thresholds indicate potential clinical performance concerns that warrant management attention."
            paragraphs.append(p_clin)

    # Risk profile
    if risk_profile:
        rl = getattr(risk_profile, 'overall_risk_level', '')
        kf = getattr(risk_profile, 'key_findings', [])
        if rl or kf:
            p_risk = "Risk assessment: "
            if rl:
                p_risk += f"The hospital's overall risk level is {rl}. "
            if kf:
                p_risk += "Key findings include: " + "; ".join(kf[:3]) + "."
            paragraphs.append(p_risk)

    # Morbidity profile
    if morbidity_profile:
        smm = getattr(morbidity_profile, 'total_smm', 0)
        deaths = getattr(morbidity_profile, 'maternal_deaths', 0)
        kf = getattr(morbidity_profile, 'key_findings', [])
        if smm or deaths or kf:
            p_morb = "Maternal morbidity assessment: "
            parts = []
            if smm is not None and smm > 0:
                parts.append(f"{smm} severe maternal morbidity event(s) reported")
            if deaths:
                parts.append(f"{deaths} maternal death(s) recorded")
            if kf:
                parts.append("findings: " + "; ".join(kf[:2]))
            if parts:
                p_morb += ". ".join(parts) + "."
                paragraphs.append(p_morb)

    # Priority actions
    if dq < 60:
        paragraphs.append("Priority actions include: improving data completeness through enhanced collection procedures, "
                          "verifying outlier values, addressing clinical threshold concerns, and conducting targeted training "
                          "for data entry staff on the most frequently violated rules.")
    elif dq < 80:
        paragraphs.append("Priority actions include: addressing the specific rule violations and clinical threshold concerns identified, "
                          "reviewing outlier indicators, and continuing regular quality monitoring to prevent regression.")
    else:
        paragraphs.append("Continue routine quality monitoring and periodic audits to maintain the current level of data quality, "
                          "with particular attention to sustaining clinical performance standards.")

    paragraphs.append(f"In summary, {hospital} demonstrates a {status} level of data maturity for {month}. "
                      f"{'While the foundation is solid, targeted improvements in the areas identified above would strengthen overall reporting reliability and clinical confidence.' if dq >= 60 else 'Immediate corrective action is recommended to bring data quality and clinical reporting to an acceptable level.'}")
    return "\n\n".join(paragraphs)


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


def _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score) -> List[AIRuleDef]:
    recs = []
    cs_rate = values.get("CS_rate", values.get("cs_rate", 0))
    if cs_rate and cs_rate > 15:
        recs.append(AIRuleDef(
            category="C-Section Management",
            priority="high",
            title=f"C-Section Rate Above WHO Threshold ({cs_rate:.1f}%)",
            description=f"Cesarean section rate of {cs_rate:.1f}% exceeds the WHO recommended maximum of 15%.",
            rationale="High C-section rates are associated with increased maternal morbidity without corresponding benefits in low-risk pregnancies.",
            action_items=[
                "Review clinical indications for C-sections",
                "Implement robson classification to monitor CS indications",
                "Promote trial of labor after cesarean (TOLAC) where appropriate",
                "Provide training on operative vaginal delivery options",
            ],
            indicators_monitored=["CS_rate"],
        ))

    smm = getattr(morbidity_profile, "total_smm", 0) if morbidity_profile else 0
    deliveries = getattr(morbidity_profile, "total_deliveries", 0) if morbidity_profile else 0
    if smm and deliveries and (smm / max(deliveries, 1)) * 100 > 2:
        recs.append(AIRuleDef(
            category="Maternal Morbidity",
            priority="high",
            title="Severe Maternal Morbidity Rate Elevated",
            description=f"SMM rate is {(smm/max(deliveries,1))*100:.1f}%, above the 2% warning threshold.",
            rationale="Elevated SMM rates may indicate quality of care issues during labor and delivery.",
            action_items=[
                "Conduct case reviews for all SMM cases",
                "Review obstetric emergency response protocols",
                "Ensure availability of blood products and emergency medications",
            ],
            indicators_monitored=["SMM_rate"],
        ))

    deaths = getattr(morbidity_profile, "maternal_deaths", 0) if morbidity_profile else 0
    if deaths and deaths > 0:
        recs.append(AIRuleDef(
            category="Maternal Mortality",
            priority="critical",
            title=f"{deaths} Maternal Death(s) Reported",
            description=f"{deaths} maternal death(s) occurred this reporting period.",
            rationale="Every maternal death warrants thorough review to identify preventable factors.",
            action_items=[
                "Conduct maternal death surveillance and response (MDSR)",
                "Review all antenatal, intrapartum, and postpartum care",
                "Identify delays in accessing care (3 delays model)",
                "Share findings with clinical team and implement corrective actions",
            ],
            indicators_monitored=["MMR"],
        ))

    risk_level = getattr(risk_profile, "overall_risk_level", "") if risk_profile else ""
    if risk_level and risk_level.lower() in ("critical", "high"):
        recs.append(AIRuleDef(
            category="Risk Management",
            priority="critical" if risk_level.lower() == "critical" else "high",
            title=f"Overall Risk Level: {risk_level}",
            description = f"The hospital's overall risk profile is classified as {risk_level}.",
            rationale="High risk levels indicate multiple indicators are outside acceptable ranges, requiring immediate attention.",
            action_items=[
                "Conduct a comprehensive risk assessment review",
                "Prioritize interventions for the highest-risk indicators",
                "Establish a quality improvement task force",
                "Monitor risk indicators weekly until improvement is sustained",
            ],
            indicators_monitored=[],
        ))

    if quality_score is not None and quality_score < 60:
        recs.append(AIRuleDef(
            category="Data Quality",
            priority="medium",
            title=f"Data Quality Score Low ({quality_score:.0f}/100)",
            description=f"Data quality score of {quality_score:.0f} indicates incomplete or inconsistent reporting.",
            rationale="Poor data quality undermines clinical decision-making and may mask actual quality issues.",
            action_items=[
                "Review data entry processes for completeness gaps",
                "Validate indicator definitions with clinical staff",
                "Implement automated pre-submission validation checks",
            ],
            indicators_monitored=[],
        ))

    if not recs:
        recs.append(AIRuleDef(
            category="General Monitoring",
            priority="low",
            title="Continue Routine Quality Monitoring",
            description="No critical clinical indicators exceeded thresholds. Maintain ongoing surveillance.",
            rationale="Sustained quality requires ongoing monitoring even when indicators are within acceptable ranges.",
            action_items=[
                "Continue monthly quality indicator reviews",
                "Document and share best practices",
                "Schedule next clinical audit",
            ],
            indicators_monitored=[],
        ))

    return recs


def _build_root_cause_prompt(report_data: dict) -> str:
    lines = []
    lines.append("You are a maternal health data quality expert. Analyze the Root Cause Analysis report below and provide actionable recommendations.")
    lines.append("Focus on data quality improvements, confidence gaps, and operational fixes for the specific hospital.")
    lines.append("")
    lines.append(f"Hospital: {report_data.get('hospital', 'Unknown')}")
    lines.append(f"Month: {report_data.get('month', 'Unknown')}")
    lines.append(f"Overall Quality Score: {report_data.get('overall_quality_score', 'N/A')}")
    lines.append(f"Overall Confidence: {report_data.get('overall_confidence', 'N/A')}")
    lines.append(f"Critical Issues Count: {report_data.get('critical_issues_count', 0)}")
    lines.append("")
    if report_data.get("top_rule_failures"):
        lines.append("## Top Rule Failures")
        for f in report_data["top_rule_failures"][:5]:
            lines.append(f"  {f.get('rule_code','')} ({f.get('severity','')}): {f.get('description','')}")
            lines.append(f"    Failure rate: {f.get('failure_rate','')}% | Cause: {f.get('primary_cause','')}")
        lines.append("")
    if report_data.get("quality_drivers"):
        lines.append("## Quality Drivers")
        for d in report_data["quality_drivers"]:
            lines.append(f"  {d.get('component','')}: {d.get('value','')}% ({d.get('status','')}) | Impact: {d.get('impact','')} pts")
        lines.append("")
    if report_data.get("confidence_gaps"):
        lines.append("## Confidence Gaps")
        for g in report_data["confidence_gaps"][:5]:
            lines.append(f"  {g.get('indicator_name','')} ({g.get('level','')}): confidence={g.get('confidence','')}, signal={g.get('weakest_signal','')}")
        lines.append("")
    if report_data.get("anomaly_patterns"):
        lines.append("## Anomaly Patterns")
        for a in report_data["anomaly_patterns"][:5]:
            lines.append(f"  {a.get('rate_name','')}: |z|={a.get('avg_z_score','')}, type={a.get('pattern_type','')} ({a.get('description','')})")
        lines.append("")

    lines.append("""Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "Data Entry Training", "Process Improvement", "System Configuration")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the root cause issue)
- rationale: str (why this matters for data quality, 1-2 sentences)
- action_items: list[str] (3-5 specific actionable steps)
- affected_indicators: list[str] (indicator codes or rule codes affected)

Give concrete, hospital-specific advice. Prioritize critical data quality issues first.

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)


def generate_root_cause_ai(report_data: dict, session=None) -> List[AIRuleDef]:
    if not AI_ENABLED:
        return _local_root_cause_fallback(report_data)
    if not AI_API_KEY:
        logger.warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        return _local_root_cause_fallback(report_data)
    prompt = _build_root_cause_prompt(report_data)
    # Check cache first
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
        return _local_root_cause_fallback(report_data)
    # Save to cache
    if session is not None:
        try:
            
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    try:
        return _parse_response(response)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse root cause AI response: {e}\nResponse: {response[:500]}")
        return _local_root_cause_fallback(report_data)


def _local_root_cause_fallback(report_data: dict) -> List[AIRuleDef]:
    recs = []
    rs = report_data.get("overall_quality_score", 0)
    cs = report_data.get("overall_confidence", "")
    rf = report_data.get("top_rule_failures") or []
    cg = report_data.get("confidence_gaps") or []
    ap = report_data.get("anomaly_patterns") or []

    if rf:
        critical_failures = [f for f in rf if (f.get("severity") or "").upper() in ("CRITICAL", "HIGH")]
        if critical_failures:
            recs.append(AIRuleDef(
                category="Data Validation",
                priority="critical",
                title="Fix Critical Rule Failures",
                description=f"{len(critical_failures)} critical rule failure(s) detected affecting data integrity.",
                rationale="Critical validation rules failing means the submitted data does not meet minimum quality standards.",
                action_items=[
                    "Review each failed rule and correct the source data",
                    "Train data entry staff on the specific rule requirements",
                    "Implement pre-submission validation checks",
                ],
                indicators_monitored=[f.get("rule_code", "") for f in critical_failures[:5]],
            ))

    if rs and rs < 60:
        recs.append(AIRuleDef(
            category="Data Quality",
            priority="high",
            title="Improve Overall Data Quality Score",
            description=f"Quality score is {rs:.1f}/100, below the acceptable threshold of 60.",
            rationale="Low quality scores indicate systemic issues with completeness, consistency, or compliance.",
            action_items=[
                "Audit data entry workflows for gaps",
                "Review indicator definitions with clinical staff",
                "Implement automated completeness checks before submission",
            ],
            indicators_monitored=[],
        ))

    low_conf = [g for g in cg if (g.get("level") or "").upper() in ("CRITICAL", "LOW")]
    if low_conf:
        recs.append(AIRuleDef(
            category="Confidence Improvement",
            priority="high",
            title="Address Low Confidence Indicators",
            description=f"{len(low_conf)} indicator(s) have critically low confidence scores.",
            rationale="Low confidence means the data lacks sufficient signals (historical, cross-hospital, trend) to be trusted.",
            action_items=[
                "Collect additional historical data for affected indicators",
                "Cross-reference with peer hospitals for benchmarking",
                "Review data collection methodology for these indicators",
            ],
            indicators_monitored=[g.get("indicator_name", "") for g in low_conf[:5]],
        ))

    severe_anomalies = [a for a in ap if a.get("pattern_type") == "severe"]
    if severe_anomalies:
        recs.append(AIRuleDef(
            category="Outlier Management",
            priority="high",
            title="Investigate Severe Statistical Anomalies",
            description=f"{len(severe_anomalies)} indicator(s) show severe outlier patterns (|z| > 2.5).",
            rationale="Severe anomalies may indicate data entry errors, reporting inconsistencies, or genuine clinical concerns that need investigation.",
            action_items=[
                "Verify the source data for each flagged indicator",
                "Compare with previous months to identify sudden changes",
                "Investigate whether clinical practice changes explain the anomaly",
            ],
            indicators_monitored=[a.get("rate_name", "") for a in severe_anomalies[:5]],
        ))

    if not recs:
        recs.append(AIRuleDef(
            category="Continuous Improvement",
            priority="low",
            title="Maintain Data Quality Standards",
            description="No critical issues detected. Continue regular monitoring and periodic reviews.",
            rationale="Sustained data quality requires ongoing attention even when no immediate issues are present.",
            action_items=[
                "Continue monthly quality reviews",
                "Document best practices for data entry",
                "Schedule quarterly training refreshers",
            ],
            indicators_monitored=[],
        ))

    return recs
