from app.engine.clinical.thresholds import (
    ClinicalThreshold,
    CLINICAL_THRESHOLDS,
    CLASSIFICATION_LABELS,
    CLASSIFICATION_COLORS,
    CLASSIFICATION_SEVERITY,
    get_threshold,
    classify_rate,
    compute_rate,
)
from app.engine.clinical.risk_profile import (
    RiskMetric,
    RiskProfile,
    compute_risk_profile,
    correlate_risk_outcomes,
)
from app.engine.clinical.morbidity import (
    MorbidityMetric,
    MorbidityProfile,
    compute_morbidity_profile,
)
from app.engine.clinical.recommendations import (
    Recommendation,
    generate_recommendations,
)
from app.engine.clinical.summary import (
    ClinicalSummary,
    LOW_TO_CRITICAL,
    generate_clinical_summary,
)
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ClinicalClassification:
    indicator_code: str
    rate_name: str
    value: float
    unit: str
    threshold: Optional[ClinicalThreshold]
    classification: str
    label: str
    color: str
    narrative: str


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
            return f"{th.rate_name} of {value:.1f}{th.unit} is CRITICAL (>={th.critical_threshold}{th.unit}). Immediate clinical investigation required."
        elif cls == "below_normal":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below normal range ({th.normal_range[0]}-{th.normal_range[1]}{th.unit}). Verify data accuracy."
    else:
        if cls == "normal":
            return f"{th.rate_name} of {value:.1f}{th.unit} meets target (>={th.normal_range[0]}{th.unit}). {th.clinical_guideline}."
        elif cls == "critical":
            return f"{th.rate_name} of {value:.1f}{th.unit} is critically low (<{th.critical_threshold}{th.unit}). Immediate action needed."
        elif cls == "high":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below target. Needs improvement."
        elif cls == "elevated":
            return f"{th.rate_name} of {value:.1f}{th.unit} is below optimal. Requires monitoring."
    return f"{th.rate_name} of {value:.1f}{th.unit}. {th.clinical_guideline}"


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
    risk_prof = compute_risk_profile(hospital, month, values)
    morbidity_prof = compute_morbidity_profile(hospital, month, values)
    recommendations = generate_recommendations(
        values=values,
        classifications=classifications,
        risk_profile=risk_prof,
        morbidity_profile=morbidity_prof,
        quality_score=quality_score,
        issues=issues,
        rule_failures=rule_failures,
    )
    summary = generate_clinical_summary(
        hospital=hospital,
        month=month,
        values=values,
        classifications=classifications,
        risk_profile=risk_prof,
        morbidity_profile=morbidity_prof,
        recommendations=recommendations,
        quality_score=quality_score,
    )
    return ClinicalAnalysisResult(
        hospital=hospital,
        month=month,
        classifications=classifications,
        risk_profile=risk_prof,
        morbidity_profile=morbidity_prof,
        recommendations=recommendations,
        summary=summary,
    )
