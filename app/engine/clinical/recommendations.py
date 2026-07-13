import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    category: str
    priority: str
    title: str
    description: str
    rationale: str
    action_items: List[str] = field(default_factory=list)
    indicators_monitored: List[str] = field(default_factory=list)
    triggered_by_rules: List[str] = field(default_factory=list)
    data_reliable: bool = True


RECOMMENDATION_RULES = []


def _register(fn):
    RECOMMENDATION_RULES.append(fn)
    return fn


_RULE_FAILURE_CACHE = {"items": []}


def _extract_codes_from_text(text: str) -> set:
    return set(re.findall(r'\b(?:[1-9][0-9]?\.[a-z]+\.[0-9]+|[1-9][0-9]?\.[a-z]+|[1-9][0-9]?)\b', text))


def _match_rule_failures(indicators: List[str], rule_failures: List[dict]) -> List[str]:
    matched = []
    ind_set = set(indicators)
    for rf in rule_failures:
        codes_in_details = _extract_codes_from_text(rf.get("details", ""))
        if ind_set & codes_in_details:
            matched.append(rf["rule_code"])
    return matched


def _has_critical_failure(rule_failures: List[dict], indicators: List[str]) -> bool:
    ind_set = set(indicators)
    for rf in rule_failures:
        if rf.get("severity", "").upper() in ("CRITICAL", "HIGH"):
            codes_in_details = _extract_codes_from_text(rf.get("details", ""))
            if ind_set & codes_in_details:
                return True
    return False


def generate_recommendations(
    values: Dict[str, float],
    classifications: List,
    risk_profile,
    morbidity_profile,
    trend_analysis: Dict = None,
    quality_score: float = None,
    issues: List[str] = None,
    rule_failures: List[dict] = None,
) -> List[Recommendation]:
    _RULE_FAILURE_CACHE["items"] = rule_failures or []
    recs = []
    ctx = {
        "values": values,
        "classifications": classifications,
        "risk_profile": risk_profile,
        "morbidity_profile": morbidity_profile,
        "trends": trend_analysis or {},
        "quality_score": quality_score,
        "issues": issues or [],
    }
    for rule in RECOMMENDATION_RULES:
        try:
            result = rule(ctx)
            if result:
                recs.extend(result if isinstance(result, list) else [result])
        except Exception as e:
            logger.warning(f"Recommendation rule failed: {e}")
    try:
        from app.plugins.ai import generate as ai_generate
        ai_recs = ai_generate(values, classifications, risk_profile, morbidity_profile, quality_score)
        seen_titles = {r.title for r in recs}
        for a in ai_recs:
            if a.title not in seen_titles:
                recs.append(Recommendation(
                    category=a.category,
                    priority=a.priority,
                    title=a.title,
                    description=a.description,
                    rationale=a.rationale,
                    action_items=a.action_items,
                    indicators_monitored=a.indicators_monitored,
                ))
                seen_titles.add(a.title)
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"AI recommendations plugin error: {e}")
    for r in recs:
        r.triggered_by_rules = _match_rule_failures(r.indicators_monitored, _RULE_FAILURE_CACHE["items"])
        if not r.data_reliable:
            continue
        if _has_critical_failure(_RULE_FAILURE_CACHE["items"], r.indicators_monitored):
            r.data_reliable = False
    recs.sort(key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.priority, 99))
    return recs


@_register
def _cs_high_rate(ctx):
    vals = ctx["values"]
    cs = vals.get("5", 0) or 0
    total = vals.get("2", 0) or 0
    if total > 0:
        cs_rate = (cs / total) * 100
        if cs_rate > 25:
            items = ["Review all C-section indications against WHO Robson classification"]
            if cs_rate > 15:
                items.append("Audit planned vs emergency C-section ratio to identify modifiable factors")
            if cs_rate > 40:
                items.append("Conduct case-by-case C-section audit for the reporting period")
            priority = "critical" if cs_rate > 40 else "high" if cs_rate > 25 else "medium"
            return Recommendation(
                category="C-Section Management",
                priority=priority,
                title=f"High C-Section Rate ({cs_rate:.1f}%)",
                description="C-section rate exceeds WHO recommended range of 10-15%",
                rationale="WHO recommends C-section rates of 10-15%. Rates >25% suggest potential overuse without clear medical benefit.",
                action_items=items,
                indicators_monitored=["5", "5.b.1", "5.b.2", "5.c", "5.d"],
            )


@_register
def _maternal_mortality(ctx):
    vals = ctx["values"]
    deaths = vals.get("11", 0) or 0
    total = vals.get("2", 0) or 0
    if deaths > 0 and total > 0:
        mmr = (deaths / total) * 100000
        priority = "critical" if mmr > 300 else "high" if mmr > 150 else "medium"
        action = ["Conduct maternal death audit/review for each death"]
        if mmr > 300:
            action.append("Notify maternal health oversight committee immediately")
            action.append("Review referral pathways and emergency obstetric care readiness")
        action.append("Analyze cause of death patterns (hemorrhage, sepsis, hypertensive)")
        return Recommendation(
            category="Maternal Mortality",
            priority=priority,
            title=f"Maternal Mortality Alert ({deaths} deaths, MMR {mmr:.0f}/100k)",
            description=f"{deaths} maternal death(s) reported; MMR of {mmr:.0f} per 100,000 deliveries",
            rationale="Every maternal death requires thorough review. Elevated MMR indicates systemic gaps in emergency obstetric care.",
            action_items=action,
            indicators_monitored=["11", "11.a", "11.b", "11.c", "10", "10.m"],
        )


@_register
def _neonatal_mortality(ctx):
    vals = ctx["values"]
    nd = vals.get("17", 0) or 0
    lb = vals.get("6", 0) or 0
    if nd > 0 and lb > 0:
        nmr = (nd / lb) * 1000
        priority = "critical" if nmr > 45 else "high" if nmr > 30 else "medium"
        action = ["Review each neonatal death for preventability"]
        if nmr > 30:
            action.append("Assess newborn resuscitation capacity and protocols")
            action.append("Review antenatal steroid coverage for preterm labor")
        return Recommendation(
            category="Neonatal Mortality",
            priority=priority,
            title=f"Elevated Neonatal Mortality Rate ({nmr:.1f}/1000)",
            description=f"Neonatal mortality rate of {nmr:.1f} per 1,000 live births",
            rationale="Neonatal mortality is a key indicator of newborn care quality. High rates suggest gaps in intrapartum and immediate newborn care.",
            action_items=action,
            indicators_monitored=["17", "17.a", "17.b", "17.c", "17.d", "17.f"],
        )


@_register
def _smm_high(ctx):
    vals = ctx["values"]
    smm = vals.get("10", 0) or 0
    total = vals.get("2", 0) or 0
    if total > 0 and smm > 0:
        smm_rate = (smm / total) * 100
        if smm_rate > 5:
            components = {
                "Hemorrhage": vals.get("10.a", 0) or 0,
                "Hypertensive": vals.get("10.e", 0) or 0,
                "Sepsis": vals.get("10.f", 0) or 0,
            }
            dominant = max(components, key=components.get)
            action = [f"Review all SMM cases with focus on {dominant} cases"]
            if smm_rate > 10:
                action.append("Conduct comprehensive SMM audit with case reviews")
            action.append("Assess adherence to treatment protocols for severe cases")
            return Recommendation(
                category="Maternal Morbidity",
                priority="high" if smm_rate > 10 else "medium",
                title=f"Elevated SMM Rate ({smm_rate:.1f}%) - {dominant} dominant",
                description=f"SMM rate of {smm_rate:.1f}% exceeds expected <2% of deliveries",
                rationale=f"SMM rate >5% indicates systemic quality gaps. Dominant component: {dominant}.",
                action_items=action,
                indicators_monitored=["10", "10.a", "10.e", "10.f", "10.m"],
            )


@_register
def _stillbirth_high(ctx):
    vals = ctx["values"]
    sb = vals.get("7", 0) or 0
    total = vals.get("2", 0) or 0
    if total > 0 and sb > 0:
        sb_rate = (sb / total) * 1000
        if sb_rate > 22:
            fresh = vals.get("7.a", 0) or 0
            fresh_pct = (fresh / sb) * 100 if sb > 0 else 0
            action = ["Review stillbirth cases for preventability"]
            if fresh_pct > 50:
                action.append("High fresh stillbirth proportion - review intrapartum monitoring and fetal distress management")
            action.append("Audit labor management for all term stillbirths")
            return Recommendation(
                category="Perinatal Mortality",
                priority="high" if sb_rate > 35 else "medium",
                title=f"Elevated Stillbirth Rate ({sb_rate:.1f}/1000)",
                description=f"Stillbirth rate of {sb_rate:.1f} per 1,000 deliveries",
                rationale="High stillbirth rate, especially fresh stillbirths, indicates intrapartum care gaps.",
                action_items=action,
                indicators_monitored=["7", "7.a", "7.b"],
            )


@_register
def _preterm_high(ctx):
    vals = ctx["values"]
    preterm = vals.get("6.f", 0) or 0
    lb = vals.get("6", 0) or 0
    if lb > 0 and preterm > 0:
        pt_rate = (preterm / lb) * 100
        if pt_rate > 15:
            action = ["Review preterm prevention protocols (progesterone, cervical length screening)"]
            if pt_rate > 20:
                action.append("Assess antenatal steroid coverage for all preterm deliveries")
            return Recommendation(
                category="Preterm Birth Prevention",
                priority="high" if pt_rate > 20 else "medium",
                title=f"High Preterm Birth Rate ({pt_rate:.1f}%)",
                description="Preterm birth rate exceeds WHO target of <10%",
                rationale="Preterm birth is leading cause of neonatal mortality. High rates require preventive strategies.",
                action_items=action,
                indicators_monitored=["6.f", "17.c"],
            )


@_register
def _quality_score_low(ctx):
    qs = ctx.get("quality_score")
    if qs is not None and qs < 50:
        return Recommendation(
            category="Data Quality",
            priority="high",
            title=f"Critical Data Quality Score ({qs:.0f}/100)",
            description=f"Overall data quality score is critically low at {qs:.0f}%",
            rationale="Poor data quality undermines all clinical analyses. Data entry and validation processes need immediate strengthening.",
            action_items=[
                "Review data collection tools and training for completeness",
                "Implement real-time validation checks during data entry",
                "Assign data quality focal person at facility level",
            ],
            indicators_monitored=[],
        )


@_register
def _high_risk_rate(ctx):
    risk = ctx.get("risk_profile")
    if risk and risk.overall_risk_level in ("high", "critical"):
        high_risk_val = None
        for m in risk.metrics:
            if m.metric_name == "High-Risk Delivery Rate":
                high_risk_val = m.value
                break
        action = ["Ensure all high-risk deliveries are attended by skilled birth attendants"]
        if high_risk_val and high_risk_val > 35:
            action.append("Review referral criteria and ensure timely referral for high-risk pregnancies")
            action.append("Audit high-risk case management against standard protocols")
        return Recommendation(
            category="Risk Management",
            priority="critical" if risk.overall_risk_level == "critical" else "high",
            title=f"Elevated Risk Profile ({risk.overall_risk_level.upper()})",
            description=f"Hospital shows {risk.overall_risk_level} risk profile across multiple indicators",
            rationale="High-risk deliveries require specialized care. Elevated risk profile indicates need for strengthened risk Management.",
            action_items=action,
            indicators_monitored=["2.n", "2.m"],
        )


@_register
def _emergency_cs_high(ctx):
    vals = ctx["values"]
    cs_total = vals.get("5", 0) or 0
    cs_emerg = vals.get("5.b.1", 0) or 0
    if cs_total > 0 and cs_emerg > 0:
        emerg_pct = (cs_emerg / cs_total) * 100
        if emerg_pct > 70:
            return Recommendation(
                category="C-Section Management",
                priority="medium",
                title=f"High Emergency C/S Proportion ({emerg_pct:.0f}%)",
                description=f"Emergency C-sections account for {emerg_pct:.0f}% of all C-sections",
                rationale="High emergency C/S proportion suggests potentially avoidable emergencies. Review induction protocols and labor monitoring.",
                action_items=[
                    "Review emergency C-section indications",
                    "Assess induction of labor protocols",
                    "Evaluate labor monitoring and fetal distress diagnosis accuracy",
                ],
                indicators_monitored=["5.b.1", "5.b.2", "5.c"],
            )


@_register
def _adolescent_pregnancy_high(ctx):
    risk = ctx.get("risk_profile")
    if risk:
        for m in risk.metrics:
            if m.metric_name == "Adolescent Pregnancy Rate (10-19)" and m.severity in ("high", "critical"):
                return Recommendation(
                    category="Adolescent Health",
                    priority="high",
                    title=f"High Adolescent Pregnancy Rate ({m.value:.1f}%)",
                    description=f"Adolescent deliveries account for {m.value:.1f}% of all deliveries",
                    rationale="Adolescent pregnancies carry higher risks of complications. Targeted interventions needed.",
                    action_items=[
                        "Strengthen adolescent-friendly reproductive health services",
                        "Ensure all adolescent mothers receive enhanced antenatal care",
                        "Implement school-based sexual health education programs",
                    ],
                    indicators_monitored=["2.c", "2.d", "2.e", "2.f"],
                )


@_register
def _hemorrhage_preventable(ctx):
    morb = ctx.get("morbidity_profile")
    if morb and morb.mortality_preventability_signals:
        for signal in morb.mortality_preventability_signals:
            if "PPH" in signal or "Hemorrhage" in signal or "APH" in signal:
                return Recommendation(
                    category="Hemorrhage Management",
                    priority="high",
                    title="Hemorrhage Care Quality Signal Detected",
                    description=signal,
                    rationale="Obstetric hemorrhage is a leading cause of maternal mortality, yet largely preventable with active management.",
                    action_items=[
                        "Review active management of third stage of labor (AMTSL) compliance",
                        "Ensure uterotonic drugs available at all delivery points",
                        "Conduct hemorrhage simulation drills with maternity team",
                        "Audit all PPH cases for protocol adherence",
                    ],
                    indicators_monitored=["10.a", "10.a.1", "10.a.1.1", "10.a.1.2"],
                )


@_register
def _fresh_stillbirth_audit(ctx):
    vals = ctx["values"]
    sb_total = vals.get("7", 0) or 0
    fresh_sb = vals.get("7.a", 0) or 0
    if sb_total > 0 and (fresh_sb / sb_total) > 0.5:
        fresh_pct = (fresh_sb / sb_total) * 100
        return Recommendation(
            category="Intrapartum Care",
            priority="medium",
            title=f"Fresh Stillbirth Proportion {fresh_pct:.0f}% - Intrapartum Care Review",
            description=f"{fresh_pct:.0f}% of stillbirths are fresh (intrapartum) - potentially preventable",
            rationale="Fresh stillbirths represent babies alive at labor onset. High proportion suggests intrapartum monitoring gaps.",
            action_items=[
                "Review partograph use and compliance for all labor cases",
                "Audit intrapartum fetal monitoring practices",
                "Assess emergency C-section decision-to-incision time",
                "Review intrapartum stillbirth cases individually for preventability",
            ],
            indicators_monitored=["7", "7.a", "7.b"],
        )


@_register
def _early_nd_audit(ctx):
    vals = ctx["values"]
    nd = vals.get("17", 0) or 0
    nd_early = vals.get("17.a", 0) or 0
    if nd > 0 and nd_early > 0 and (nd_early / nd) > 0.6:
        return Recommendation(
            category="Newborn Care",
            priority="medium",
            title="Early Neonatal Deaths Prevalent - Review Newborn Care",
            description=f"{(nd_early/nd)*100:.0f}% of neonatal deaths occur in first 7 days",
            rationale="Early neonatal deaths are linked to intrapartum and immediate newborn care. Review resuscitation protocols.",
            action_items=[
                "Assess newborn resuscitation skills and equipment availability",
                "Review immediate newborn care protocols (thermal care, cord care, breastfeeding)",
                "Ensure all birth attendants trained in Helping Babies Breathe (HBB)",
            ],
            indicators_monitored=["17", "17.a", "17.b"],
        )
