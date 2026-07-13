# =============================================================================
# engine/clinical.py -- Merged clinical analysis module
# Generated from: clinical_thresholds, clinical_risk, clinical_morbidity,
#                   clinical_recommendations, clinical_summary, clinical_analysis
# =============================================================================


from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class ClinicalThreshold:
    indicator_code: str
    rate_name: str
    numerator_codes: List[str]
    denominator_code: str
    unit: str
    normal_range: tuple  # (low, high) inclusive
    elevated_range: tuple
    high_range: tuple
    critical_threshold: float
    clinical_guideline: str
    higher_is_worse: bool = True


CLINICAL_THRESHOLDS: List[ClinicalThreshold] = [
    ClinicalThreshold(
        indicator_code="rate_cs",
        rate_name="C-Section Rate",
        numerator_codes=["5"],
        denominator_code="2",
        unit="%",
        normal_range=(10, 15),
        elevated_range=(15, 25),
        high_range=(25, 40),
        critical_threshold=40,
        clinical_guideline="WHO: 10-15% optimal C-section rate",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_mmr",
        rate_name="Maternal Mortality Ratio",
        numerator_codes=["11"],
        denominator_code="2",
        unit="per 100,000",
        normal_range=(0, 50),
        elevated_range=(50, 150),
        high_range=(150, 300),
        critical_threshold=300,
        clinical_guideline="WHO/SDG 3.1: <70 per 100,000 by 2030",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_nmr",
        rate_name="Neonatal Mortality Rate",
        numerator_codes=["17"],
        denominator_code="6",
        unit="per 1,000",
        normal_range=(0, 15),
        elevated_range=(15, 30),
        high_range=(30, 45),
        critical_threshold=45,
        clinical_guideline="WHO/SDG: <12 per 1,000 live births",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_preterm",
        rate_name="Preterm Birth Rate",
        numerator_codes=["6.f"],
        denominator_code="6",
        unit="%",
        normal_range=(0, 10),
        elevated_range=(10, 15),
        high_range=(15, 20),
        critical_threshold=20,
        clinical_guideline="WHO: <10% of live births",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_smm",
        rate_name="Severe Maternal Morbidity Rate",
        numerator_codes=["10"],
        denominator_code="2",
        unit="%",
        normal_range=(0, 2),
        elevated_range=(2, 5),
        high_range=(5, 10),
        critical_threshold=10,
        clinical_guideline="Published literature: <2% of deliveries",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_stillbirth",
        rate_name="Stillbirth Rate",
        numerator_codes=["7"],
        denominator_code="2",
        unit="per 1,000",
        normal_range=(0, 12),
        elevated_range=(12, 22),
        high_range=(22, 35),
        critical_threshold=35,
        clinical_guideline="WHO: <12 per 1,000 total births",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_nicu",
        rate_name="NICU Admission Rate",
        numerator_codes=["16"],
        denominator_code="6",
        unit="%",
        normal_range=(0, 15),
        elevated_range=(15, 25),
        high_range=(25, 40),
        critical_threshold=40,
        clinical_guideline="Literature: 10-15% of live births typical",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_lbw",
        rate_name="Low Birth Weight Rate",
        numerator_codes=["6.g"],
        denominator_code="6",
        unit="%",
        normal_range=(0, 10),
        elevated_range=(10, 15),
        high_range=(15, 20),
        critical_threshold=20,
        clinical_guideline="WHO: <10% of live births",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_bf",
        rate_name="Breastfeeding within 1 Hour",
        numerator_codes=["13"],
        denominator_code="6",
        unit="%",
        normal_range=(80, 100),
        elevated_range=(0, 0),
        high_range=(0, 0),
        critical_threshold=40,
        clinical_guideline="WHO: >80% initiation within 1 hour",
        higher_is_worse=False,
    ),
    ClinicalThreshold(
        indicator_code="rate_avd",
        rate_name="Assisted Vaginal Delivery Rate",
        numerator_codes=["4"],
        denominator_code="2",
        unit="%",
        normal_range=(5, 15),
        elevated_range=(15, 20),
        high_range=(20, 30),
        critical_threshold=30,
        clinical_guideline="WHO: 5-15% of deliveries",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_smm_hemorrhage_proportion",
        rate_name="Hemorrhage Proportion of SMM",
        numerator_codes=["10.a"],
        denominator_code="10",
        unit="%",
        normal_range=(0, 40),
        elevated_range=(40, 55),
        high_range=(55, 70),
        critical_threshold=70,
        clinical_guideline="Literature: Hemorrhage ~35-40% of SMM cases",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_smm_hypertensive_proportion",
        rate_name="Hypertensive Proportion of SMM",
        numerator_codes=["10.e"],
        denominator_code="10",
        unit="%",
        normal_range=(0, 25),
        elevated_range=(25, 40),
        high_range=(40, 55),
        critical_threshold=55,
        clinical_guideline="Literature: Hypertensive ~20-25% of SMM cases",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_adolescent",
        rate_name="Adolescent Pregnancy Rate (10-19)",
        numerator_codes=["2.c", "2.d"],
        denominator_code="2",
        unit="%",
        normal_range=(0, 10),
        elevated_range=(10, 20),
        high_range=(20, 30),
        critical_threshold=30,
        clinical_guideline="WHO: Reducing adolescent pregnancy is SDG target",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_high_risk",
        rate_name="High-Risk Delivery Rate",
        numerator_codes=["2.n"],
        denominator_code="2",
        unit="%",
        normal_range=(0, 20),
        elevated_range=(20, 35),
        high_range=(35, 50),
        critical_threshold=50,
        clinical_guideline="Depends on referral level; tertiary >30% expected",
        higher_is_worse=True,
    ),
    ClinicalThreshold(
        indicator_code="rate_hysterectomy",
        rate_name="Hysterectomy per 1,000 Deliveries",
        numerator_codes=["10.d"],
        denominator_code="2",
        unit="per 1,000",
        normal_range=(0, 0.5),
        elevated_range=(0.5, 1),
        high_range=(1, 2),
        critical_threshold=2,
        clinical_guideline="Literature: 0.3-0.5 per 1,000 deliveries",
        higher_is_worse=True,
    ),
]


def get_threshold(rate_name: str) -> Optional[ClinicalThreshold]:
    for t in CLINICAL_THRESHOLDS:
        if t.rate_name == rate_name or t.indicator_code == rate_name:
            return t
    return None


def classify_rate(value: float, threshold: ClinicalThreshold) -> str:
    if value is None:
        return "unknown"
    if threshold.higher_is_worse:
        if value >= threshold.critical_threshold:
            return "critical"
        low_h, high_h = threshold.high_range
        if low_h <= value < high_h:
            return "high"
        low_e, high_e = threshold.elevated_range
        if low_e <= value < high_e:
            return "elevated"
        low_n, high_n = threshold.normal_range
        if low_n <= value < high_n:
            return "normal"
        if value < low_n:
            return "below_normal"
        return "elevated"
    else:
        if value < threshold.critical_threshold:
            return "critical"
        low_h, high_h = threshold.high_range
        if low_h <= value < high_h:
            return "high"
        low_e, high_e = threshold.elevated_range
        if low_e <= value < high_e:
            return "elevated"
        low_n, high_n = threshold.normal_range
        if low_n <= value <= high_n:
            return "normal"
        if value > high_n:
            return "above_normal"
        return "elevated"


CLASSIFICATION_LABELS = {
    "normal": "Normal",
    "elevated": "Elevated",
    "high": "High",
    "critical": "Critical",
    "below_normal": "Below Normal",
    "above_normal": "Above Normal",
    "unknown": "Unknown",
}

CLASSIFICATION_COLORS = {
    "normal": "#2e7d32",
    "elevated": "#e65100",
    "high": "#c62828",
    "critical": "#b71c1c",
    "below_normal": "#1565c0",
    "above_normal": "#1565c0",
    "unknown": "#888",
}

CLASSIFICATION_SEVERITY = {
    "normal": 0,
    "below_normal": 1,
    "above_normal": 1,
    "elevated": 2,
    "high": 3,
    "critical": 4,
}


@dataclass
class ClinicalClassification:
    indicator_code: str
    rate_name: str
    value: float
    unit: str
    threshold: ClinicalThreshold
    classification: str
    label: str
    color: str
    narrative: str


def classify_clinical_rate(value: float, rate_name: str, indicator_code: str = "") -> ClinicalClassification:
    th = get_threshold(rate_name) or get_threshold(indicator_code)
    if not th:
        return ClinicalClassification(
            indicator_code=indicator_code,
            rate_name=rate_name,
            value=value,
            unit="%",
            threshold=None,
            classification="unknown",
            label="No Threshold",
            color="#888",
            narrative=f"No clinical threshold defined for {rate_name}",
        )
    cls = classify_rate(value, th)
    return ClinicalClassification(
        indicator_code=th.indicator_code,
        rate_name=th.rate_name,
        value=value,
        unit=th.unit,
        threshold=th,
        classification=cls,
        label=CLASSIFICATION_LABELS.get(cls, cls),
        color=CLASSIFICATION_COLORS.get(cls, "#888"),
        narrative=_build_narrative(th, cls, value),
    )


def _build_narrative(th: ClinicalThreshold, cls: str, value: float) -> str:
    if cls == "unknown":
        return "Unable to classify due to missing data"
    if th.higher_is_worse:
        if cls == "normal":
            return f"{th.rate_name} of {value:.1f}{th.unit} is within normal range ({th.normal_range[0]}-{th.normal_range[1]}{th.unit}). {th.clinical_guideline}."
        elif cls == "elevated":
            return f"{th.rate_name} of {value:.1f}{th.unit} is elevated (range {th.elevated_range[0]}-{th.elevated_range[1]}{th.unit}). Requires monitoring."
        elif cls == "high":
            return f"{th.rate_name} of {value:.1f}{th.unit} is HIGH (range {th.high_range[0]}-{th.high_range[1]}{th.unit}). Clinical review recommended."
        elif cls == "critical":
            return f"{th.rate_name} of {value:.1f}{th.unit} is CRITICAL (≥{th.critical_threshold}{th.unit}). Immediate clinical investigation required."
        elif cls == "below_normal":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below normal range ({th.normal_range[0]}-{th.normal_range[1]}{th.unit}). Verify data accuracy."
    else:
        if cls == "normal":
            return f"{th.rate_name} of {value:.1f}{th.unit} meets target (≥{th.normal_range[0]}{th.unit}). {th.clinical_guideline}."
        elif cls == "critical":
            return f"{th.rate_name} of {value:.1f}{th.unit} is critically low (<{th.critical_threshold}{th.unit}). Immediate action needed."
        elif cls == "high":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below target. Needs improvement."
        elif cls == "elevated":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below optimal. Requires monitoring."
    return f"{th.rate_name} of {value:.1f}{th.unit}. {th.clinical_guideline}"


def compute_rate(numerator_total: float, denominator: float, unit: str = "") -> Optional[float]:
    if denominator is None or denominator == 0:
        return None
    return (numerator_total / denominator) * (100 if "%" in unit else 1)


def compute_all_classifications(values: Dict[str, float]) -> List[ClinicalClassification]:
    results = []
    for th in CLINICAL_THRESHOLDS:
        num_sum = sum(values.get(c, 0) or 0 for c in th.numerator_codes)
        denom = values.get(th.denominator_code, 0)
        rate_val = None
        if denom and denom > 0:
            if th.unit == "per 100,000":
                rate_val = (num_sum / denom) * 100000
            elif th.unit == "per 1,000":
                rate_val = (num_sum / denom) * 1000
            else:
                rate_val = (num_sum / denom) * 100
        cls = classify_clinical_rate(rate_val, th.rate_name)
        cls.value = rate_val
        results.append(cls)
    return results


from typing import List, Dict, Optional


@dataclass
class RiskMetric:
    metric_name: str
    description: str
    value: Optional[float]
    unit: str
    numerator: float
    denominator: float
    interpretation: str
    severity: str  # low / moderate / high / critical


@dataclass
class RiskProfile:
    hospital: str
    month: str
    total_deliveries: int
    metrics: List[RiskMetric] = field(default_factory=list)
    overall_risk_level: str = "low"
    key_findings: List[str] = field(default_factory=list)


def compute_risk_profile(hospital: str, month: str, values: Dict[str, float]) -> RiskProfile:
    profile = RiskProfile(hospital=hospital, month=month, total_deliveries=int(values.get("2", 0) or 0))
    total = values.get("2", 0) or 0
    live_births = values.get("6", 0) or 0

    if total == 0:
        profile.overall_risk_level = "unknown"
        return profile

    # High-risk delivery proportion
    high_risk = values.get("2.n", 0) or 0
    high_risk_rate = (high_risk / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="High-Risk Delivery Rate",
        description="Deliveries flagged as high-risk",
        value=high_risk_rate, unit="%",
        numerator=high_risk, denominator=total,
        interpretation=_interpret_rate(high_risk_rate, 20, 35, 50, higher_is_worse=True),
        severity=_rate_severity(high_risk_rate, 20, 35, 50, higher_is_worse=True),
    ))

    # Adolescent pregnancy (age 10-19)
    teen_codes = ["2.c", "2.d"]
    teen_sum = sum(values.get(c, 0) or 0 for c in teen_codes)
    teen_rate = (teen_sum / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Adolescent Pregnancy Rate (10-19)",
        description="Deliveries to mothers aged 10-19",
        value=teen_rate, unit="%",
        numerator=teen_sum, denominator=total,
        interpretation=_interpret_rate(teen_rate, 10, 20, 30, higher_is_worse=True),
        severity=_rate_severity(teen_rate, 10, 20, 30, higher_is_worse=True),
    ))

    # Advanced maternal age (35+)
    ama_codes = ["2.h", "2.i", "2.j"]
    ama_sum = sum(values.get(c, 0) or 0 for c in ama_codes)
    ama_rate = (ama_sum / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Advanced Maternal Age Rate (35+)",
        description="Deliveries to mothers aged 35+",
        value=ama_rate, unit="%",
        numerator=ama_sum, denominator=total,
        interpretation=_interpret_rate(ama_rate, 15, 25, 35, higher_is_worse=True),
        severity=_rate_severity(ama_rate, 15, 25, 35, higher_is_worse=True),
    ))

    # Primigravida rate
    primigravida = values.get("2.a", 0) or 0
    primi_rate = (primigravida / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Primigravida Rate",
        description="First-time mothers",
        value=primi_rate, unit="%",
        numerator=primigravida, denominator=total,
        interpretation=_interpret_rate(primi_rate, 25, 40, 50, higher_is_worse=False),
        severity=_rate_severity(primi_rate, 25, 40, 50, higher_is_worse=False),
    ))

    # Emergency C/S as proportion of all C-sections
    cs_total = values.get("5", 0) or 0
    cs_emergency = values.get("5.b.1", 0) or 0
    cs_emergency_rate = (cs_emergency / cs_total * 100) if cs_total > 0 else None
    if cs_emergency_rate is not None:
        profile.metrics.append(RiskMetric(
            metric_name="Emergency C/S Proportion",
            description="Emergency C-sections as % of all C-sections",
            value=cs_emergency_rate, unit="%",
            numerator=cs_emergency, denominator=cs_total,
            interpretation=_interpret_rate(cs_emergency_rate, 50, 70, 85, higher_is_worse=True),
            severity=_rate_severity(cs_emergency_rate, 50, 70, 85, higher_is_worse=True),
        ))

    # Primary C/S as proportion of all C-sections
    cs_primary = values.get("5.c", 0) or 0
    cs_primary_rate = (cs_primary / cs_total * 100) if cs_total > 0 else None
    if cs_primary_rate is not None:
        profile.metrics.append(RiskMetric(
            metric_name="Primary C/S Proportion",
            description="First-time C-sections as % of all C-sections",
            value=cs_primary_rate, unit="%",
            numerator=cs_primary, denominator=cs_total,
            interpretation=_interpret_rate(cs_primary_rate, 40, 60, 75, higher_is_worse=False),
            severity=_rate_severity(cs_primary_rate, 40, 60, 75, higher_is_worse=False),
        ))

    # Primigravida C/S rate (proxy: if primigravida rate high + CS rate high)
    # We can't directly link individual patients, but can note correlation

    # In-facility vs out-of-facility delivery
    in_facility = values.get("2.k", 0) or 0
    out_facility = values.get("2.l", 0) or 0
    facility_rate = (in_facility / total * 100) if total > 0 else 0
    profile.metrics.append(RiskMetric(
        metric_name="In-Facility Delivery Rate",
        description="Deliveries occurring in health facility",
        value=facility_rate, unit="%",
        numerator=in_facility, denominator=total,
        interpretation=_interpret_rate(facility_rate, 80, 60, 40, higher_is_worse=False),
        severity=_rate_severity(facility_rate, 80, 60, 40, higher_is_worse=False),
    ))

    # Preterm + LBW composite risk
    preterm = values.get("6.f", 0) or 0
    lbw = values.get("6.g", 0) or 0
    preterm_rate = (preterm / live_births * 100) if live_births > 0 else 0
    lbw_rate = (lbw / live_births * 100) if live_births > 0 else 0
    profile.metrics.append(RiskMetric(
        metric_name="Preterm Birth Rate",
        description="Live births before 37 weeks",
        value=preterm_rate, unit="%",
        numerator=preterm, denominator=live_births,
        interpretation=_interpret_rate(preterm_rate, 10, 15, 20, higher_is_worse=True),
        severity=_rate_severity(preterm_rate, 10, 15, 20, higher_is_worse=True),
    ))
    profile.metrics.append(RiskMetric(
        metric_name="Low Birth Weight Rate",
        description="Live births <2500g",
        value=lbw_rate, unit="%",
        numerator=lbw, denominator=live_births,
        interpretation=_interpret_rate(lbw_rate, 10, 15, 20, higher_is_worse=True),
        severity=_rate_severity(lbw_rate, 10, 15, 20, higher_is_worse=True),
    ))

    # Stillbirth to fresh/macerated breakdown
    stillbirth = values.get("7", 0) or 0
    fresh_sb = values.get("7.a", 0) or 0
    macerated_sb = values.get("7.b", 0) or 0
    if stillbirth > 0 and fresh_sb > 0:
        fresh_proportion = (fresh_sb / stillbirth) * 100
        profile.metrics.append(RiskMetric(
            metric_name="Fresh Stillbirth Proportion",
            description="Fresh stillbirths as % of all stillbirths (intrapartum deaths)",
            value=fresh_proportion, unit="%",
            numerator=fresh_sb, denominator=stillbirth,
            interpretation=_interpret_rate(fresh_proportion, 30, 50, 70, higher_is_worse=True),
            severity=_rate_severity(fresh_proportion, 30, 50, 70, higher_is_worse=True),
        ))

    # Neonatal death cause breakdown (where available)
    nd_total = values.get("17", 0) or 0
    if nd_total > 0:
        nd_preterm = values.get("17.c", 0) or 0
        nd_asphyxia = values.get("17.d", 0) or 0
        nd_sepsis = values.get("17.f", 0) or 0
        nd_asphyxia_rate = (nd_asphyxia / nd_total * 100) if nd_total > 0 else 0
        profile.metrics.append(RiskMetric(
            metric_name="Birth Asphyxia % of Neonatal Deaths",
            description="Neonatal deaths due to birth asphyxia",
            value=nd_asphyxia_rate, unit="%",
            numerator=nd_asphyxia, denominator=nd_total,
            interpretation=_interpret_rate(nd_asphyxia_rate, 20, 30, 40, higher_is_worse=True),
            severity=_rate_severity(nd_asphyxia_rate, 20, 30, 40, higher_is_worse=True),
        ))

    severity_scores = {
        "low": 0, "moderate": 1, "high": 2, "critical": 3, "unknown": 0
    }
    avg_severity = 0
    count = 0
    for m in profile.metrics:
        s = severity_scores.get(m.severity, 0)
        avg_severity += s
        count += 1
    avg_severity = avg_severity / count if count > 0 else 0

    if avg_severity >= 2.5:
        profile.overall_risk_level = "critical"
    elif avg_severity >= 1.5:
        profile.overall_risk_level = "high"
    elif avg_severity >= 0.5:
        profile.overall_risk_level = "moderate"
    else:
        profile.overall_risk_level = "low"

    _build_key_findings(profile)
    return profile


def _interpret_rate(value: float, moderate_thresh: float, high_thresh: float, critical_thresh: float, higher_is_worse: bool) -> str:
    sev = _rate_severity(value, moderate_thresh, high_thresh, critical_thresh, higher_is_worse)
    if sev == "low":
        return "Acceptable level"
    elif sev == "moderate":
        return "Moderate - requires monitoring"
    elif sev == "high":
        return "High - clinical review recommended"
    elif sev == "critical":
        return "Critical - immediate action required"
    return "Unable to assess"


def _rate_severity(value: float, moderate_thresh: float, high_thresh: float, critical_thresh: float, higher_is_worse: bool) -> str:
    if value is None:
        return "unknown"
    if higher_is_worse:
        if value >= critical_thresh:
            return "critical"
        if value >= high_thresh:
            return "high"
        if value >= moderate_thresh:
            return "moderate"
        return "low"
    else:
        if value <= critical_thresh:
            return "critical"
        if value <= high_thresh:
            return "high"
        if value <= moderate_thresh:
            return "moderate"
        return "low"


def _build_key_findings(profile: RiskProfile):
    for m in profile.metrics:
        if m.severity in ("high", "critical"):
            profile.key_findings.append(f"{m.metric_name}: {m.value:.1f}{m.unit} ({m.interpretation})")
    if profile.overall_risk_level == "critical":
        profile.key_findings.insert(0, f"Overall risk profile CRITICAL for {profile.hospital}")
    elif profile.overall_risk_level == "high":
        profile.key_findings.insert(0, f"Overall risk profile HIGH for {profile.hospital}")


def correlate_risk_outcomes(values: Dict[str, float], all_hospital_data: Dict[str, Dict[str, float]]) -> List[Dict]:
    findings = []
    total = values.get("2", 0) or 0
    if total == 0:
        return findings

    high_risk = values.get("2.n", 0) or 0
    high_risk_rate = (high_risk / total) * 100

    other_hospitals = {h: v for h, v in all_hospital_data.items()}
    if len(other_hospitals) >= 2:
        risk_rates = []
        preterm_rates = []
        for h, v in other_hospitals.items():
            ht = v.get("2", 0) or 0
            if ht > 0:
                hr = v.get("2.n", 0) or 0
                risk_rates.append((hr / ht) * 100)
                lb = v.get("6", 0) or 0
                pt = v.get("6.f", 0) or 0
                preterm_rates.append((pt / lb * 100) if lb > 0 else 0)

        if risk_rates and preterm_rates:
            avg_risk = sum(risk_rates) / len(risk_rates)
            avg_preterm = sum(preterm_rates) / len(preterm_rates)
            if high_risk_rate > avg_risk * 1.2:
                findings.append({
                    "finding": "High-risk proportion significantly above peer average",
                    "detail": f"{high_risk_rate:.1f}% vs peer avg {avg_risk:.1f}%",
                    "severity": "high" if high_risk_rate > avg_risk * 1.5 else "moderate",
                })

    return findings




@dataclass
class MorbidityMetric:
    metric_name: str
    description: str
    value: Optional[float]
    unit: str
    numerator: float
    denominator: float
    interpretation: str
    severity: str  # low / moderate / high / critical


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

    # SMM rate
    smm_rate = (smm_total / total) * 100 if total > 0 else 0
    profile.metrics.append(MorbidityMetric(
        metric_name="SMM Rate",
        description="Severe Maternal Morbidity per 100 deliveries",
        value=smm_rate, unit="%",
        numerator=smm_total, denominator=total,
        interpretation=_rate_interpretation(smm_rate, 2, 5, 10, higher_is_worse=True),
        severity=_rate_severity(smm_rate, 2, 5, 10, higher_is_worse=True),
    ))

    # Maternal Mortality Ratio (per 100,000)
    mmr = (mat_deaths / total) * 100000 if total > 0 else 0
    profile.metrics.append(MorbidityMetric(
        metric_name="Maternal Mortality Ratio",
        description="Maternal deaths per 100,000 deliveries",
        value=mmr, unit="/100k",
        numerator=mat_deaths, denominator=total,
        interpretation=_rate_interpretation(mmr, 50, 150, 300, higher_is_worse=True),
        severity=_rate_severity(mmr, 50, 150, 300, higher_is_worse=True),
    ))

    # SMM sub-component proportions
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

    # SMM CFR (deaths per SMM case)
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

    # ICU admission as % of SMM
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

    # Hysterectomy per 1000 deliveries
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

    # Hemorrhage sub-analysis: PPH vs APH
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

    # Prevention quality signals
    if fresh_sb := values.get("7.a", 0) or 0:
        sb_total = values.get("7", 0) or 0
        if sb_total > 0 and (fresh_sb / sb_total) > 0.6:
            profile.mortality_preventability_signals.append(
                f"High fresh stillbirth proportion ({(fresh_sb/sb_total)*100:.0f}%) suggests intrapartum care gaps"
            )

    # Neonatal death sub-analysis
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


def _rate_interpretation(value: float, moderate: float, high: float, critical: float, higher_is_worse: bool) -> str:
    sev = _rate_severity(value, moderate, high, critical, higher_is_worse)
    return {
        "low": "Within acceptable range", "moderate": "Requires monitoring",
        "high": "Clinical review recommended", "critical": "Critical - immediate action",
    }.get(sev, "Unable to assess")


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


import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    category: str
    priority: str  # critical / high / medium / low
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
    # AI plugin recommendations (optional)
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
                description=f"C-section rate exceeds WHO recommended range of 10-15%",
                rationale=f"WHO recommends C-section rates of 10-15%. Rates >25% suggest potential overuse without clear medical benefit.",
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
            # Find dominant SMM component
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
                description=f"Preterm birth rate exceeds WHO target of <10%",
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
    lbw = int(values.get("6.g", 0) or 0)
    nicu = int(values.get("16", 0) or 0)

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
        return f"CRITICAL RISK PROFILE: Multiple high-severity risk factors identified requiring immediate multisectoral intervention."
    elif level == "high":
        return f"HIGH RISK PROFILE: Several clinical risk indicators elevated. Systematic review of high-risk case management recommended."
    elif level == "moderate":
        return f"Moderate risk profile. Some indicators above optimal levels. Targeted monitoring recommended."
    else:
        return f"Low risk profile. Most clinical risk indicators within acceptable ranges."


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

class ClinicalAnalysisResult:
    def __init__(
        self,
        hospital: str,
        month: str,
        classifications: List[ClinicalClassification],
        risk_profile: RiskProfile,
        morbidity_profile: MorbidityProfile,
        recommendations: List[Recommendation],
        summary: ClinicalSummary,
    ):
        self.hospital = hospital
        self.month = month
        self.classifications = classifications
        self.risk_profile = risk_profile
        self.morbidity_profile = morbidity_profile
        self.recommendations = recommendations
        self.summary = summary

    def to_dict(self) -> dict:
        return {
            "hospital": self.hospital,
            "month": self.month,
            "classifications": [
                {
                    "indicator_code": c.indicator_code,
                    "rate_name": c.rate_name,
                    "value": c.value,
                    "unit": c.unit,
                    "classification": c.classification,
                    "label": c.label,
                    "color": c.color,
                    "narrative": c.narrative,
                }
                for c in self.classifications
            ],
            "risk_profile": {
                "hospital": self.risk_profile.hospital,
                "month": self.risk_profile.month,
                "total_deliveries": self.risk_profile.total_deliveries,
                "overall_risk_level": self.risk_profile.overall_risk_level,
                "key_findings": self.risk_profile.key_findings,
                "metrics": [
                    {
                        "metric_name": m.metric_name,
                        "description": m.description,
                        "value": m.value,
                        "unit": m.unit,
                        "numerator": m.numerator,
                        "denominator": m.denominator,
                        "interpretation": m.interpretation,
                        "severity": m.severity,
                    }
                    for m in self.risk_profile.metrics
                ],
            },
            "morbidity_profile": {
                "hospital": self.morbidity_profile.hospital,
                "month": self.morbidity_profile.month,
                "total_deliveries": self.morbidity_profile.total_deliveries,
                "total_smm": self.morbidity_profile.total_smm,
                "maternal_deaths": self.morbidity_profile.maternal_deaths,
                "key_findings": self.morbidity_profile.key_findings,
                "mortality_preventability_signals": self.morbidity_profile.mortality_preventability_signals,
                "metrics": [
                    {
                        "metric_name": m.metric_name,
                        "description": m.description,
                        "value": m.value,
                        "unit": m.unit,
                        "numerator": m.numerator,
                        "denominator": m.denominator,
                        "interpretation": m.interpretation,
                        "severity": m.severity,
                    }
                    for m in self.morbidity_profile.metrics
                ],
            },
            "recommendations": [
                {
                    "category": r.category,
                    "priority": r.priority,
                    "title": r.title,
                    "description": r.description,
                    "rationale": r.rationale,
                    "action_items": r.action_items,
                    "indicators_monitored": r.indicators_monitored,
                    "triggered_by_rules": r.triggered_by_rules,
                    "data_reliable": r.data_reliable,
                }
                for r in self.recommendations
            ],
            "summary": {
                "overview": self.summary.overview,
                "key_findings": self.summary.key_findings,
                "clinical_indicators": self.summary.clinical_indicators,
                "risk_assessment": self.summary.risk_assessment,
                "morbidity_assessment": self.summary.morbidity_assessment,
                "recommendations_text": self.summary.recommendations_text,
                "overall_assessment": self.summary.overall_assessment,
                "executive_summary": self.summary.executive_summary,
            },
        }


def run_clinical_analysis(
    hospital: str,
    month: str,
    values: Dict[str, float],
    quality_score: float = None,
    issues: List[str] = None,
    all_hospital_data: Optional[Dict[str, Dict[str, float]]] = None,
    rule_failures: List[dict] = None,
    completeness: float = 0,
    consistency: float = 0,
    rule_compliance: float = 0,
    outlier_penalty: float = 0,
) -> ClinicalAnalysisResult:
    classifications = compute_all_classifications(values)
    risk_profile = compute_risk_profile(hospital, month, values)
    morbidity_profile = compute_morbidity_profile(hospital, month, values)
    recommendations = generate_recommendations(
        values=values,
        classifications=classifications,
        risk_profile=risk_profile,
        morbidity_profile=morbidity_profile,
        quality_score=quality_score,
        issues=issues,
        rule_failures=rule_failures,
    )
    summary = generate_clinical_summary(
        hospital=hospital,
        month=month,
        values=values,
        classifications=classifications,
        risk_profile=risk_profile,
        morbidity_profile=morbidity_profile,
        recommendations=recommendations,
        quality_score=quality_score,
    )
    # Generate executive AI summary
    try:
        from app.plugins.ai import generate_executive_summary as gen_exec
        summary.executive_summary = gen_exec(
            hospital=hospital,
            month=month,
            values=values,
            quality_score=quality_score or 0,
            completeness=completeness,
            consistency=consistency,
            rule_compliance=rule_compliance,
            outlier_penalty=outlier_penalty,
            rule_results=rule_failures,
            anomaly_results=None,
            classifications=classifications,
            risk_profile=risk_profile,
            morbidity_profile=morbidity_profile,
        )
    except Exception as e:
        logger.warning(f"Executive summary generation failed: {e}")
    return ClinicalAnalysisResult(
        hospital=hospital,
        month=month,
        classifications=classifications,
        risk_profile=risk_profile,
        morbidity_profile=morbidity_profile,
        recommendations=recommendations,
        summary=summary,
    )
