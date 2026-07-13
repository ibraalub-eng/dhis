from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class ClinicalSummary:
    hospital: str
    month: str
    overview: str
    key_findings: List[str] = field(default_factory=list)
    clinical_indicators: List[str] = field(default_factory=list)
    risk_assessment: str = ""
    morbidity_assessment: str = ""
    recommendations_text: List[str] = field(default_factory=list)
    overall_assessment: str = ""
    executive_summary: str = ""


def is_arabic_locale() -> bool:
    return False


LOW_TO_CRITICAL = {0: "normal", 1: "mild", 2: "moderate", 3: "high", 4: "critical"}


def generate_clinical_summary(
    hospital: str,
    month: str,
    values: Dict[str, float],
    classifications: list,
    risk_profile,
    morbidity_profile,
    recommendations: list,
    quality_score: float = None,
) -> ClinicalSummary:
    total = int(values.get("2", 0) or 0)
    live_births = int(values.get("6", 0) or 0)
    cs = int(values.get("5", 0) or 0)
    deaths = int(values.get("11", 0) or 0)
    nd = int(values.get("17", 0) or 0)
    smm = int(values.get("10", 0) or 0)
    sb = int(values.get("7", 0) or 0)
    preterm = int(values.get("6.f", 0) or 0)
    _lbw = int(values.get("6.g", 0) or 0)
    _nicu = int(values.get("16", 0) or 0)

    cs_rate = (cs / total * 100) if total > 0 else 0
    mmr = (deaths / total * 100000) if total > 0 else 0
    nmr = (nd / live_births * 1000) if live_births > 0 else 0
    smm_rate = (smm / total * 100) if total > 0 else 0
    sb_rate = (sb / total * 1000) if total > 0 else 0
    preterm_rate = (preterm / live_births * 100) if live_births > 0 else 0

    overview = _build_overview(hospital, month, total, live_births, cs_rate, deaths)

    key_findings = []
    if deaths > 0:
        key_findings.append(f"Maternal Deaths: {deaths} death(s) reported (MMR {mmr:.0f}/100,000)")
    if nd > 0:
        key_findings.append(f"Neonatal Deaths: {nd} death(s) reported (NMR {nmr:.1f}/1,000)")
    if smm > 0:
        key_findings.append(f"SMM: {smm} cases ({smm_rate:.1f}% of deliveries)")
    if sb > 0:
        key_findings.append(f"Stillbirths: {sb} cases ({sb_rate:.1f}/1,000)")
    if cs_rate > 25:
        key_findings.append(f"C-Section Rate: {cs_rate:.1f}% (exceeds WHO range of 10-15%)")
    if preterm_rate > 10:
        key_findings.append(f"Preterm Birth Rate: {preterm_rate:.1f}% ({preterm} cases)")
    if quality_score is not None:
        key_findings.append(f"Data Quality Score: {quality_score:.0f}/100")

    clinical_indicators = _build_indicator_list(total, live_births, cs, cs_rate, deaths, mmr, nd, nmr, smm, smm_rate)

    risk_assessment = _build_risk_text(risk_profile, total)
    morbidity_assessment = _build_morbidity_text(morbidity_profile, smm, deaths)

    recommendations_text = []
    for rec in recommendations[:5]:
        recommendations_text.append(f"[{rec.priority.upper()}] {rec.title}: {rec.description}")

    severity_count = sum(1 for r in recommendations if r.priority == "critical")
    high_count = sum(1 for r in recommendations if r.priority == "high")

    if severity_count > 0:
        overall = f"CRITICAL: {severity_count} critical and {high_count} high-priority recommendations require immediate action"
    elif high_count > 0:
        overall = f"ATTENTION: {high_count} high-priority clinical issues identified that need management review"
    elif quality_score is not None and quality_score < 60:
        overall = "Data quality concerns limit clinical interpretation. Improve data completeness first."
    else:
        overall = "No critical clinical signals detected. Continue routine monitoring and data quality maintenance."

    return ClinicalSummary(
        hospital=hospital,
        month=month,
        overview=overview,
        key_findings=key_findings,
        clinical_indicators=clinical_indicators,
        risk_assessment=risk_assessment,
        morbidity_assessment=morbidity_assessment,
        recommendations_text=recommendations_text,
        overall_assessment=overall,
    )


def _build_overview(hospital: str, month: str, total: int, live_births: int, cs_rate: float, deaths: int) -> str:
    parts = [f"In {month}, {hospital} reported {total} deliveries and {live_births} live births."]
    parts.append(f"The C-section rate was {cs_rate:.1f}%.")
    if deaths > 0:
        parts.append(f"Tragically, {deaths} maternal death(s) occurred during this period.")
    else:
        parts.append("No maternal deaths were reported.")
    return " ".join(parts)


def _build_indicator_list(total: int, lb: int, cs: int, cs_rate: float, deaths: int, mmr: float, nd: int, nmr: float, smm: int, smm_rate: float) -> List[str]:
    indicators = [
        f"Total Deliveries: {total}",
        f"Live Births: {lb}",
        f"C-Sections: {cs} ({cs_rate:.1f}%)",
        f"Maternal Deaths: {deaths} (MMR {mmr:.0f}/100k)",
        f"Neonatal Deaths: {nd} (NMR {nmr:.1f}/1000)",
        f"SMM Cases: {smm} ({smm_rate:.1f}%)",
    ]
    return indicators


def _build_risk_text(risk_profile, total: int) -> str:
    if not risk_profile:
        return "Risk analysis not available."
    level = risk_profile.overall_risk_level
    if level == "critical":
        return "CRITICAL RISK PROFILE: Multiple high-severity risk factors identified requiring immediate multisectoral intervention."
    elif level == "high":
        return "HIGH RISK PROFILE: Several clinical risk indicators elevated. Systematic review of high-risk case management recommended."
    elif level == "moderate":
        return "Moderate risk profile. Some indicators above optimal levels. Targeted monitoring recommended."
    else:
        return "Low risk profile. Most clinical risk indicators within acceptable ranges."


def _build_morbidity_text(morbidity_profile, smm: int, deaths: int) -> str:
    if not morbidity_profile:
        return "Morbidity analysis not available."
    if smm == 0 and deaths == 0:
        return "No severe maternal morbidity or mortality reported."
    if deaths > 0 and smm == 0:
        return f"Maternal deaths reported ({deaths}) without SMM documentation - verify morbidity data completeness."
    signals = morbidity_profile.mortality_preventability_signals
    if signals:
        return "; ".join(signals[:3])
    if smm > 0:
        return f"{smm} SMM cases reported. Review individual case management for quality improvement opportunities."
    return "Maternal morbidity indicators within expected range."
