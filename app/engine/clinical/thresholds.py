from dataclasses import dataclass
from typing import List, Optional

from app.engine import indicator_service
from app.engine.rate_config import iter_site, multiplier_for_unit


@dataclass
class ClinicalThreshold:
    indicator_code: str
    rate_name: str
    numerator_codes: List[str]
    denominator_code: str
    unit: str
    multiplier: float
    normal_range: tuple
    elevated_range: tuple
    high_range: tuple
    critical_threshold: float
    clinical_guideline: str
    higher_is_worse: bool = True
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None


# Clinical ranges/guidelines are display/classification metadata, NOT rate
# definitions — they live here; numerator/denominator/unit come from the
# central registry (rate_config, site "clinical").
_CLINICAL_META = {
    "rate_cs":  dict(normal_range=(10, 15), elevated_range=(15, 25), high_range=(25, 40),
                     critical_threshold=40, clinical_guideline="WHO: 10-15% optimal C-section rate",
                     higher_is_worse=True),
    "rate_mmr": dict(normal_range=(0, 50), elevated_range=(50, 150), high_range=(150, 300),
                     critical_threshold=300, clinical_guideline="WHO/SDG 3.1: <70 per 100,000 by 2030",
                     higher_is_worse=True),
    "rate_nmr": dict(normal_range=(0, 15), elevated_range=(15, 30), high_range=(30, 45),
                     critical_threshold=45, clinical_guideline="WHO/SDG: <12 per 1,000 live births",
                     higher_is_worse=True),
    "rate_preterm": dict(normal_range=(0, 10), elevated_range=(10, 15), high_range=(15, 20),
                         critical_threshold=20, clinical_guideline="WHO: <10% of live births",
                         higher_is_worse=True),
    "rate_smm": dict(normal_range=(0, 2), elevated_range=(2, 5), high_range=(5, 10),
                     critical_threshold=10, clinical_guideline="Published literature: <2% of deliveries",
                     higher_is_worse=True),
    "rate_stillbirth": dict(normal_range=(0, 12), elevated_range=(12, 22), high_range=(22, 35),
                            critical_threshold=35, clinical_guideline="WHO: <12 per 1,000 total births",
                            higher_is_worse=True),
    "rate_nicu": dict(normal_range=(0, 15), elevated_range=(15, 25), high_range=(25, 40),
                      critical_threshold=40, clinical_guideline="Literature: 10-15% of live births typical",
                      higher_is_worse=True),
    "rate_lbw": dict(normal_range=(0, 10), elevated_range=(10, 15), high_range=(15, 20),
                     critical_threshold=20, clinical_guideline="WHO: <10% of live births",
                     higher_is_worse=True),
    "rate_bf": dict(normal_range=(80, 100), elevated_range=(60, 80), high_range=(40, 60),
                    critical_threshold=40, clinical_guideline="WHO: >80% initiation within 1 hour",
                    higher_is_worse=False),
    "rate_avd": dict(normal_range=(5, 15), elevated_range=(15, 20), high_range=(20, 30),
                     critical_threshold=30, clinical_guideline="WHO: 5-15% of deliveries",
                     higher_is_worse=True),
    "rate_smm_hemorrhage_proportion": dict(normal_range=(0, 40), elevated_range=(40, 55), high_range=(55, 70),
                                            critical_threshold=70,
                                            clinical_guideline="Literature: Hemorrhage ~35-40% of SMM cases",
                                            higher_is_worse=True),
    "rate_smm_hypertensive_proportion": dict(normal_range=(0, 25), elevated_range=(25, 40), high_range=(40, 55),
                                              critical_threshold=55,
                                              clinical_guideline="Literature: Hypertensive ~20-25% of SMM cases",
                                              higher_is_worse=True),
    "rate_adolescent": dict(normal_range=(0, 10), elevated_range=(10, 20), high_range=(20, 30),
                            critical_threshold=30,
                            clinical_guideline="WHO: Reducing adolescent pregnancy is SDG target",
                            higher_is_worse=True),
    "rate_high_risk": dict(normal_range=(0, 20), elevated_range=(20, 35), high_range=(35, 50),
                           critical_threshold=50,
                           clinical_guideline="Depends on referral level; tertiary >30% expected",
                           higher_is_worse=True),
    "rate_hysterectomy": dict(normal_range=(0, 0.5), elevated_range=(0.5, 1), high_range=(1, 2),
                              critical_threshold=2,
                              clinical_guideline="Literature: 0.3-0.5 per 1,000 deliveries",
                              higher_is_worse=True),
}


def _build_clinical_thresholds() -> List[ClinicalThreshold]:
    out = []
    for spec in iter_site("clinical"):
        resolved = indicator_service.resolve_spec(spec)
        out.append(ClinicalThreshold(
            indicator_code=spec.rate_code,
            rate_name=spec.rate_name,
            numerator_codes=list(spec.numerator_codes),
            denominator_code=spec.denominator_codes[0],
            unit=spec.unit,
            multiplier=spec.rate_multiplier,
            indicator_id=resolved.indicator_id,
            formula=resolved.formula,
            formula_version=resolved.formula_version,
            **_CLINICAL_META[spec.rate_code],
        ))
    return out


def clinical_threshold_for_definition(resolved) -> Optional[ClinicalThreshold]:
    """Attach clinical interpretation metadata to a registry definition."""
    legacy_code = getattr(resolved.definition, "legacy_code", None)
    metadata = _CLINICAL_META.get(legacy_code)
    if metadata is None or not resolved.definition.denominator_codes:
        return None
    denominator_codes = list(resolved.definition.denominator_codes or [])
    return ClinicalThreshold(
        indicator_code=resolved.code,
        rate_name=resolved.name,
        numerator_codes=list(resolved.definition.numerator_codes or []),
        denominator_code=denominator_codes[0] if len(denominator_codes) == 1 else "",
        unit=resolved.unit or "",
        multiplier=float(resolved.definition.multiplier or 1),
        indicator_id=resolved.indicator_id,
        formula=resolved.formula,
        formula_version=resolved.formula_version,
        **metadata,
    )


CLINICAL_THRESHOLDS: List[ClinicalThreshold] = _build_clinical_thresholds()


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
    return (numerator_total / denominator) * multiplier_for_unit(unit)
