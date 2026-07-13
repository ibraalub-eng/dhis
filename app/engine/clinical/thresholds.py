from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ClinicalThreshold:
    indicator_code: str
    rate_name: str
    numerator_codes: List[str]
    denominator_code: str
    unit: str
    normal_range: tuple
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


def compute_rate(numerator_total: float, denominator: float, unit: str = "") -> Optional[float]:
    if denominator is None or denominator == 0:
        return None
    return (numerator_total / denominator) * (100 if "%" in unit else 1)
