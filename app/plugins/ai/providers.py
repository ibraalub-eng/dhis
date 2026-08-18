import os
import json
import logging
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

AI_ENABLED = os.getenv("AI_RECOMMENDATIONS_ENABLED", "false").lower() == "true"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.5-flash-lite")
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
            AI_MODEL = cfg.get("ai_model", "gemini-3.5-flash-lite")
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
    # حقول عربية اختيارية — تملؤها التوليد المحلي أو استجابة AI عند توفرها
    category_ar: str = ""
    title_ar: str = ""
    description_ar: str = ""
    rationale_ar: str = ""
    action_items_ar: List[str] = field(default_factory=list)


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
            category_ar=str(item.get("category_ar", "")),
            title_ar=str(item.get("title_ar", "")),
            description_ar=str(item.get("description_ar", "")),
            rationale_ar=str(item.get("rationale_ar", "")),
            action_items_ar=[str(a) for a in item.get("action_items_ar", [])],
        ))
    return recs


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

    if classifications:
        elevated = [c for c in classifications if getattr(c, 'classification', '') in ('high', 'critical')]
        if elevated:
            names = [getattr(c, 'rate_name', '') or getattr(c, 'indicator_code', '') for c in elevated[:5]]
            p_clin = f"From a clinical perspective, {len(elevated)} indicator(s) are at elevated risk levels ({', '.join(names)}). "
            p_clin += "These thresholds indicate potential clinical performance concerns that warrant management attention."
            paragraphs.append(p_clin)

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


def _local_root_cause_fallback(report_data: dict) -> List[AIRuleDef]:
    """توصيات عامة ثنائية اللغة (عربي/إنجليزي) عند تعذر المزود الخارجي."""
    recs = []
    rs = report_data.get("overall_quality_score", 0)
    _cs = report_data.get("overall_confidence", "")
    rf = report_data.get("top_rule_failures") or []
    cg = report_data.get("confidence_gaps") or []
    ap = report_data.get("anomaly_patterns") or []

    if rf:
        critical_failures = [f for f in rf if (f.get("severity") or "").upper() in ("CRITICAL", "HIGH")]
        if critical_failures:
            recs.append(AIRuleDef(
                category="Data Validation",
                category_ar="التحقق من البيانات",
                priority="critical",
                title="Fix Critical Rule Failures",
                title_ar="معالجة فشل قواعد التحقق الحرج",
                description=f"{len(critical_failures)} critical rule failure(s) detected affecting data integrity.",
                description_ar=f"تم رصد {len(critical_failures)} فشل قاعدة حرج يؤثر على سلامة البيانات.",
                rationale="Critical validation rules failing means the submitted data does not meet minimum quality standards.",
                rationale_ar="فشل قواعد التحقق الحرجة يعني أن البيانات المُرسلة لا تستوفي الحد الأدنى لمعايير الجودة.",
                action_items=[
                    "Review each failed rule and correct the source data",
                    "Train data entry staff on the specific rule requirements",
                    "Implement pre-submission validation checks",
                ],
                action_items_ar=[
                    "راجع كل قاعدة فاشلة وصحّح البيانات المصدرية",
                    "درّب موظفي الإدخال على متطلبات القواعد المحددة",
                    "فعّل فحوصات تحقق قبل الإرسال",
                ],
                indicators_monitored=[f.get("rule_code", "") for f in critical_failures[:5]],
            ))

    if rs and rs < 60:
        recs.append(AIRuleDef(
            category="Data Quality",
            category_ar="جودة البيانات",
            priority="high",
            title="Improve Overall Data Quality Score",
            title_ar="تحسين درجة جودة البيانات الإجمالية",
            description=f"Quality score is {rs:.1f}/100, below the acceptable threshold of 60.",
            description_ar=f"درجة الجودة {rs:.1f}/100، وهي دون الحد المقبول 60.",
            rationale="Low quality scores indicate systemic issues with completeness, consistency, or compliance.",
            rationale_ar="درجات الجودة المنخفضة تشير إلى مشاكل منهجية في الاكتمال أو الاتساق أو الالتزام.",
            action_items=[
                "Audit data entry workflows for gaps",
                "Review indicator definitions with clinical staff",
                "Implement automated completeness checks before submission",
            ],
            action_items_ar=[
                "دقّق سير إدخال البيانات بحثاً عن الثغرات",
                "راجع تعريفات المؤشرات مع الكادر السريري",
                "فعّل فحوصات اكتمال آلية قبل الإرسال",
            ],
            indicators_monitored=[],
        ))

    low_conf = [g for g in cg if (g.get("level") or "").upper() in ("CRITICAL", "LOW")]
    if low_conf:
        recs.append(AIRuleDef(
            category="Confidence Improvement",
            category_ar="رفع الثقة",
            priority="high",
            title="Address Low Confidence Indicators",
            title_ar="معالجة مؤشرات الثقة المنخفضة",
            description=f"{len(low_conf)} indicator(s) have critically low confidence scores.",
            description_ar=f"يوجد {len(low_conf)} مؤشر بثقة منخفضة بشكل حرج.",
            rationale="Low confidence means the data lacks sufficient signals (historical, cross-hospital, trend) to be trusted.",
            rationale_ar="الثقة المنخفضة تعني أن البيانات تفتقر إلى الإشارات الكافية (تاريخية، عبر المستشفيات، اتجاه) لتُعتمد.",
            action_items=[
                "Collect additional historical data for affected indicators",
                "Cross-reference with peer hospitals for benchmarking",
                "Review data collection methodology for these indicators",
            ],
            action_items_ar=[
                "اجمع بيانات تاريخية إضافية للمؤشرات المتأثرة",
                "قارن مع المستشفيات النظيرة للقياس المرجعي",
                "راجع منهجية جمع البيانات لهذه المؤشرات",
            ],
            indicators_monitored=[g.get("indicator_name", "") for g in low_conf[:5]],
        ))

    severe_anomalies = [a for a in ap if a.get("pattern_type") == "severe"]
    if severe_anomalies:
        recs.append(AIRuleDef(
            category="Outlier Management",
            category_ar="إدارة الشذوذ",
            priority="high",
            title="Investigate Severe Statistical Anomalies",
            title_ar="التحقيق في الشذوذ الإحصائي الحاد",
            description=f"{len(severe_anomalies)} indicator(s) show severe outlier patterns (|z| > 2.5).",
            description_ar=f"يُظهر {len(severe_anomalies)} مؤشر أنماط شذوذ حادة (|z| > 2.5).",
            rationale="Severe anomalies may indicate data entry errors, reporting inconsistencies, or genuine clinical concerns that need investigation.",
            rationale_ar="الشذوذ الحاد قد يشير إلى أخطاء إدخال أو تناقضات في الإبلاغ أو مخاوف سريرية حقيقية تستدعي التحقيق.",
            action_items=[
                "Verify the source data for each flagged indicator",
                "Compare with previous months to identify sudden changes",
                "Investigate whether clinical practice changes explain the anomaly",
            ],
            action_items_ar=[
                "تحقق من البيانات المصدرية لكل مؤشر معلَّم",
                "قارن مع الأشهر السابقة لتحديد التغيرات المفاجئة",
                "حقق فيما إذا كانت تغييرات الممارسة السريرية تفسر الشذوذ",
            ],
            indicators_monitored=[a.get("rate_name", "") for a in severe_anomalies[:5]],
        ))

    if not recs:
        recs.append(AIRuleDef(
            category="Continuous Improvement",
            category_ar="التحسين المستمر",
            priority="low",
            title="Maintain Data Quality Standards",
            title_ar="المحافظة على معايير جودة البيانات",
            description="No critical issues detected. Continue regular monitoring and periodic reviews.",
            description_ar="لا توجد مشاكل حرجة. استمر في المراقبة الدورية والمراجعات.",
            rationale="Sustained data quality requires ongoing attention even when no immediate issues are present.",
            rationale_ar="الجودة المستدامة تتطلب متابعة مستمرة حتى عند غياب مشاكل فورية.",
            action_items=[
                "Continue monthly quality reviews",
                "Document best practices for data entry",
                "Schedule quarterly training refreshers",
            ],
            action_items_ar=[
                "استمر في المراجعات الشهرية",
                "وثّق أفضل الممارسات للإدخال",
                "نظّم تدريبات تنشيطية ربع سنوية",
            ],
            indicators_monitored=[],
        ))

    return recs


def _local_root_cause_fallback_enhanced(report_data: dict) -> List[AIRuleDef]:
    """توصيات ثنائية اللغة مع بيانات تاريخية ومقارنة النظير.

    ملاحظة: مؤشرات FEATURE_KEYS هي معدلات سلبية (ارتفاعها = تدهور)، لذا
    يُستدل على المشكلة من انحراف المستشفى **فوق** متوسط النظير (gap_pct موجب)
    لا من كون المئوية منخفضة (الانخفاض أداء جيد)."""
    recs = []

    def _ar_label(factor: str) -> str:
        from app.engine.root_cause import _rule_arabic_labels, INDICATOR_NAMES
        if factor.startswith("R"):
            return _rule_arabic_labels([factor])[0]
        return INDICATOR_NAMES.get(factor, factor)

    trends = report_data.get("historical_trends", {})
    for factor, trend_data in trends.items():
        if trend_data.get("direction") == "declining":
            slope = trend_data.get("slope", 0)
            ar_label = _ar_label(factor)
            if slope < -2:
                recs.append(AIRuleDef(
                    category="Historical Decline",
                    category_ar="الانحدار التاريخي",
                    priority="critical",
                    title=f"{factor} declining rapidly (slope={slope:.1f})",
                    title_ar=f"{ar_label} في انحدار سريع (الميل={slope:.1f})",
                    description=f"{factor} has been declining at {abs(slope):.1f} points/month over the last 6 months.",
                    description_ar=f"{ar_label} ينخفض بمعدل {abs(slope):.1f} نقطة شهرياً خلال آخر 6 أشهر.",
                    rationale="Rapid decline indicates systemic issue that will worsen without intervention.",
                    rationale_ar="الانحدار السريع يشير إلى مشكلة منهجية ستتفاقم دون تدخل.",
                    action_items=[
                        f"Investigate root cause of {factor} decline in the last 3 months",
                        "Compare with peer hospitals to identify unique factors",
                        "Implement corrective action within 2 weeks",
                        "Monitor weekly until trend reverses",
                    ],
                    action_items_ar=[
                        f"حقق في سبب انحدار {ar_label} خلال آخر 3 أشهر",
                        "قارن مع المستشفيات النظيرة لتحديد العوامل الفريدة",
                        "نفّذ إجراءً تصحيحياً خلال أسبوعين",
                        "راقب أسبوعياً حتى ينعكس الاتجاه",
                    ],
                    indicators_monitored=[factor],
                ))
            elif slope < -1:
                recs.append(AIRuleDef(
                    category="Historical Decline",
                    category_ar="الانحدار التاريخي",
                    priority="high",
                    title=f"{factor} showing gradual decline",
                    title_ar=f"{ar_label} في انحدار تدريجي",
                    description=f"{factor} is declining at {abs(slope):.1f} points/month.",
                    description_ar=f"{ar_label} ينخفض بمعدل {abs(slope):.1f} نقطة شهرياً.",
                    rationale="Gradual decline may indicate process drift or training gaps.",
                    rationale_ar="الانحدار التدريجي قد يشير إلى انحراف في العمليات أو ثغرات تدريبية.",
                    action_items=[
                        f"Review {factor} data entry procedures",
                        "Schedule refresher training for data entry staff",
                        "Set up monthly monitoring alerts",
                    ],
                    action_items_ar=[
                        f"راجع إجراءات إدخال بيانات {ar_label}",
                        "نظّم تدريباً تنشيطياً لموظفي الإدخال",
                        "أنشئ تنبيهات مراقبة شهرية",
                    ],
                    indicators_monitored=[factor],
                ))

    comparisons = report_data.get("peer_comparisons", {})
    for group, comp_data in comparisons.items():
        gap_pct = comp_data.get("gap_pct", 0)
        z_score = comp_data.get("hospital_z_score", 0)
        ind_name = comp_data.get("indicator_name", comp_data.get("indicator_code", group))
        ar_name = _ar_label(ind_name)

        # معدلات سلبية: الانحراف الموجب فوق النظير هو المشكلة الحقيقية
        if gap_pct and gap_pct > 20:
            recs.append(AIRuleDef(
                category="Peer Comparison",
                category_ar="مقارنة النظير",
                priority="high",
                title=f"{ind_name} is {gap_pct:.0f}% above peer mean",
                title_ar=f"{ar_name} أعلى من متوسط النظير بـ {gap_pct:.0f}%",
                description=f"Hospital value is {gap_pct:.0f}% above the peer mean for {ind_name}.",
                description_ar=f"قيمة المستشفى أعلى من متوسط النظير بنسبة {gap_pct:.0f}% لمؤشر {ar_name}.",
                rationale="Being consistently above peers on a negative-rate indicator signals worse outcomes that need investigation.",
                rationale_ar="الارتفاع المستمر فوق النظير في معدل سلبي يشير إلى نتائج أسوأ تستدعي التحقيق.",
                action_items=[
                    "Review the indicator value against source records",
                    "Compare data entry practices with peer hospitals",
                    "Investigate clinical causes with the care team",
                ],
                action_items_ar=[
                    "راجع قيمة المؤشر مقابل السجلات المصدرية",
                    "قارن ممارسات الإدخال مع المستشفيات النظيرة",
                    "حقق في الأسباب السريرية مع فريق الرعاية",
                ],
                indicators_monitored=[comp_data.get("indicator_code", "")],
            ))

        if abs(z_score) > 2:
            direction = "above" if z_score > 0 else "below"
            direction_ar = "أعلى" if z_score > 0 else "أدنى"
            recs.append(AIRuleDef(
                category="Peer Comparison",
                category_ar="مقارنة النظير",
                priority="medium",
                title=f"Significant deviation from {group} mean",
                title_ar=f"انحراف كبير عن متوسط مجموعة {ar_name}",
                description=f"Hospital is {abs(z_score):.1f} standard deviations {direction} the {group} mean.",
                description_ar=f"المستشفى يبعد {abs(z_score):.1f} انحراف معياري {direction_ar} متوسط {ar_name}.",
                rationale="Large deviation from peers suggests unique factors affecting this hospital.",
                rationale_ar="الانحراف الكبير عن النظير يشير إلى عوامل فريدة تؤثر على هذا المستشفى.",
                action_items=[
                    "Investigate what makes this hospital different from peers",
                    "Determine if deviation is positive (best practice) or negative (needs improvement)",
                    "Document and share any unique practices",
                ],
                action_items_ar=[
                    "حقق في ما يجعل هذا المستشفى مختلفاً عن النظير",
                    "حدد إن كان الانحراف إيجابياً (ممارسة جيدة) أو سلبياً (يحتاج تحسيناً)",
                    "وثّق وشارك أي ممارسات فريدة",
                ],
                indicators_monitored=[comp_data.get("indicator_code", "")],
            ))

    if not recs:
        recs.append(AIRuleDef(
            category="Continuous Improvement",
            category_ar="التحسين المستمر",
            priority="low",
            title="Maintain Data Quality Standards",
            title_ar="المحافظة على معايير جودة البيانات",
            description="No critical historical or comparative issues detected. Continue regular monitoring.",
            description_ar="لا توجد مشاكل تاريخية أو مقارنة حرجة. استمر في المراقبة الدورية.",
            rationale="Sustained data quality requires ongoing attention even when no immediate issues are present.",
            rationale_ar="الجودة المستدامة تتطلب متابعة مستمرة حتى عند غياب مشاكل فورية.",
            action_items=[
                "Continue monthly quality reviews",
                "Document best practices for data entry",
                "Schedule quarterly training refreshers",
            ],
            action_items_ar=[
                "استمر في المراجعات الشهرية",
                "وثّق أفضل الممارسات للإدخال",
                "نظّم تدريبات تنشيطية ربع سنوية",
            ],
            indicators_monitored=[],
        ))

    return recs
