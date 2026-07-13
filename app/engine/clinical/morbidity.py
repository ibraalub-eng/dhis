from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class MorbidityMetric:
    metric_name: str
    description: str
    value: Optional[float]
    unit: str
    numerator: float
    denominator: float
    interpretation: str
    severity: str


@dataclass
class MorbidityProfile:
    hospital: str
    month: str
    total_deliveries: int
    total_smm: int
    maternal_deaths: int
    metrics: List[MorbidityMetric] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    mortality_preventability_signals: List[str] = field(default_factory=list)


def _rate_severity(value: float, moderate: float, high: float, critical: float, higher_is_worse: bool) -> str:
    if value is None:
        return "unknown"
    if higher_is_worse:
        if value >= critical:
            return "critical"
        if value >= high:
            return "high"
        if value >= moderate:
            return "moderate"
        return "low"
    else:
        if value <= critical:
            return "critical"
        if value <= high:
            return "high"
        if value <= moderate:
            return "moderate"
        return "low"


def _rate_interpretation(value: float, moderate: float, high: float, critical: float, higher_is_worse: bool) -> str:
    sev = _rate_severity(value, moderate, high, critical, higher_is_worse)
    return {
        "low": "Within acceptable range",
        "moderate": "Requires monitoring",
        "high": "Clinical review recommended",
        "critical": "Critical - immediate action",
    }.get(sev, "Unable to assess")


def _component_interpretation(label: str, proportion: float) -> str:
    name = label.split("(")[0].strip()
    if "Hemorrhage" in name:
        return "Normal range" if proportion < 40 else "Elevated" if proportion < 55 else "High"
    if "Hypertensive" in name:
        return "Normal range" if proportion < 25 else "Elevated" if proportion < 40 else "High"
    if "Sepsis" in name:
        return "Normal range" if proportion < 10 else "Elevated" if proportion < 20 else "High"
    if "ICU" in name:
        return "Normal range" if proportion < 30 else "Elevated" if proportion < 50 else "High"
    return "Under review"


def _component_severity(label: str, proportion: float) -> str:
    name = label.split("(")[0].strip()
    if "Hemorrhage" in name:
        return "low" if proportion < 40 else "moderate" if proportion < 55 else "high" if proportion < 70 else "critical"
    if "Hypertensive" in name:
        return "low" if proportion < 25 else "moderate" if proportion < 40 else "high"
    if "Sepsis" in name:
        return "low" if proportion < 10 else "moderate" if proportion < 20 else "high"
    if "ICU" in name:
        return "low" if proportion < 30 else "moderate" if proportion < 50 else "high"
    return "moderate"


def _build_morbidity_findings(profile: MorbidityProfile):
    for m in profile.metrics:
        if m.severity in ("high", "critical"):
            profile.key_findings.append(f"{m.metric_name}: {m.value:.1f}{m.unit} ({m.interpretation})")
    if profile.maternal_deaths > 0 and profile.total_smm == 0:
        profile.mortality_preventability_signals.append(
            f"Maternal deaths reported ({profile.maternal_deaths}) but no SMM cases - verify completeness of morbidity reporting"
        )
    if profile.total_smm > 0 and profile.maternal_deaths > 0:
        smm_per_death = profile.total_smm / profile.maternal_deaths
        if smm_per_death < 10:
            profile.mortality_preventability_signals.append(
                f"Low SMM per maternal death ratio ({smm_per_death:.0f}:1) - suggests possible under-reporting of morbidity or high case fatality"
            )


def compute_morbidity_profile(hospital: str, month: str, values: Dict[str, float]) -> MorbidityProfile:
    total = values.get("2", 0) or 0
    smm_total = values.get("10", 0) or 0
    mat_deaths = values.get("11", 0) or 0

    profile = MorbidityProfile(
        hospital=hospital,
        month=month,
        total_deliveries=int(total),
        total_smm=int(smm_total),
        maternal_deaths=int(mat_deaths),
    )

    if total == 0:
        profile.key_findings.append("No delivery data available")
        return profile

    smm_rate = (smm_total / total) * 100 if total > 0 else 0
    profile.metrics.append(MorbidityMetric(
        metric_name="SMM Rate",
        description="Severe Maternal Morbidity per 100 deliveries",
        value=smm_rate, unit="%",
        numerator=smm_total, denominator=total,
        interpretation=_rate_interpretation(smm_rate, 2, 5, 10, higher_is_worse=True),
        severity=_rate_severity(smm_rate, 2, 5, 10, higher_is_worse=True),
    ))

    mmr = (mat_deaths / total) * 100000 if total > 0 else 0
    profile.metrics.append(MorbidityMetric(
        metric_name="Maternal Mortality Ratio",
        description="Maternal deaths per 100,000 deliveries",
        value=mmr, unit="/100k",
        numerator=mat_deaths, denominator=total,
        interpretation=_rate_interpretation(mmr, 50, 150, 300, higher_is_worse=True),
        severity=_rate_severity(mmr, 50, 150, 300, higher_is_worse=True),
    ))

    smm_components = {
        "Hemorrhage (10.a)": "10.a",
        "Uterine Rupture (10.b)": "10.b",
        "Relaparotomy (10.c)": "10.c",
        "Hysterectomy (10.d)": "10.d",
        "Hypertensive (10.e)": "10.e",
        "Sepsis (10.f)": "10.f",
        "Respiratory/ICU (10.g)": "10.g",
        "Cardiac ICU (10.h)": "10.h",
        "Renal (10.i)": "10.i",
        "Thromboembolism (10.j)": "10.j",
        "Neurological (10.k)": "10.k",
        "Anaesthesia (10.l)": "10.l",
        "Unplanned ICU (10.m)": "10.m",
        "SU/Self-Harm (10.n)": "10.n",
        "Surgical (10.o)": "10.o",
    }

    for label, code in smm_components.items():
        comp_val = values.get(code, 0) or 0
        if comp_val > 0 and smm_total > 0:
            proportion = (comp_val / smm_total) * 100
            profile.metrics.append(MorbidityMetric(
                metric_name=f"{label} % of SMM",
                description=f"Proportion of SMM cases due to {label.split('(')[0].strip()}",
                value=proportion, unit="%",
                numerator=comp_val, denominator=smm_total,
                interpretation=_component_interpretation(label, proportion),
                severity=_component_severity(label, proportion),
            ))

    if smm_total > 0 and mat_deaths > 0:
        smm_cfr = (mat_deaths / smm_total) * 100
        profile.metrics.append(MorbidityMetric(
            metric_name="SMM Case Fatality Rate",
            description="Maternal deaths per SMM case",
            value=smm_cfr, unit="%",
            numerator=mat_deaths, denominator=smm_total,
            interpretation=_rate_interpretation(smm_cfr, 5, 10, 20, higher_is_worse=True),
            severity=_rate_severity(smm_cfr, 5, 10, 20, higher_is_worse=True),
        ))

    icu = values.get("10.m", 0) or 0
    if smm_total > 0:
        icu_smm_ratio = (icu / smm_total) * 100
        profile.metrics.append(MorbidityMetric(
            metric_name="ICU Admissions % of SMM",
            description="Unplanned ICU admissions per SMM case",
            value=icu_smm_ratio, unit="%",
            numerator=icu, denominator=smm_total,
            interpretation=_rate_interpretation(icu_smm_ratio, 30, 50, 70, higher_is_worse=True),
            severity=_rate_severity(icu_smm_ratio, 30, 50, 70, higher_is_worse=True),
        ))

    hyst = values.get("10.d", 0) or 0
    hyst_rate = (hyst / total) * 1000 if total > 0 else 0
    profile.metrics.append(MorbidityMetric(
        metric_name="Hysterectomy per 1,000 Deliveries",
        description="Emergency hysterectomy rate",
        value=hyst_rate, unit="/1000",
        numerator=hyst, denominator=total,
        interpretation=_rate_interpretation(hyst_rate, 0.5, 1, 2, higher_is_worse=True),
        severity=_rate_severity(hyst_rate, 0.5, 1, 2, higher_is_worse=True),
    ))

    pph = values.get("10.a.1", 0) or 0
    aph = values.get("10.a.2", 0) or 0
    hemorrhage_total = values.get("10.a", 0) or 0
    if hemorrhage_total > 0:
        pph_proportion = (pph / hemorrhage_total) * 100
        aph_proportion = (aph / hemorrhage_total) * 100
        if pph_proportion > 80:
            profile.key_findings.append(f"PPH dominates hemorrhage cases ({pph_proportion:.0f}%) - review active management of 3rd stage")
        if aph_proportion > 40:
            profile.key_findings.append(f"APH is high proportion of hemorrhage ({aph_proportion:.0f}%) - review antenatal care quality")

    if fresh_sb := values.get("7.a", 0) or 0:
        sb_total = values.get("7", 0) or 0
        if sb_total > 0 and (fresh_sb / sb_total) > 0.6:
            profile.mortality_preventability_signals.append(
                f"High fresh stillbirth proportion ({(fresh_sb/sb_total)*100:.0f}%) suggests intrapartum care gaps"
            )

    nd_total = values.get("17", 0) or 0
    if nd_total > 0:
        nd_early = values.get("17.a", 0) or 0
        nd_early_pct = (nd_early / nd_total) * 100
        if nd_early_pct > 60:
            profile.mortality_preventability_signals.append(
                f"Early neonatal deaths dominate ({nd_early_pct:.0f}%) - review intrapartum and immediate newborn care"
            )
        nd_asphyxia = values.get("17.d", 0) or 0
        if nd_asphyxia > 0 and (nd_asphyxia / nd_total) > 0.3:
            profile.mortality_preventability_signals.append(
                f"Birth asphyxia accounts for {(nd_asphyxia/nd_total)*100:.0f}% of neonatal deaths - review labor monitoring and resuscitation"
            )

    _build_morbidity_findings(profile)
    return profile
