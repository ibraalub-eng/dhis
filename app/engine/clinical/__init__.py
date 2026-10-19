from app.engine.clinical.thresholds import (
    ClinicalThreshold,
    CLINICAL_THRESHOLDS,
    CLASSIFICATION_LABELS,
    CLASSIFICATION_COLORS,
    CLASSIFICATION_SEVERITY as CLASSIFICATION_SEVERITY,
    get_threshold,
    classify_rate,
    compute_rate as compute_rate,
)
from app.engine.clinical.risk_profile import (
    RiskMetric as RiskMetric,
    RiskProfile,
    compute_risk_profile,
    correlate_risk_outcomes as correlate_risk_outcomes,
)
from app.engine.clinical.morbidity import (
    MorbidityMetric as MorbidityMetric,
    MorbidityProfile,
    compute_morbidity_profile,
)
from app.engine.clinical.recommendations import (
    Recommendation,
    generate_recommendations,
)
from app.engine.clinical.summary import (
    ClinicalSummary,
    LOW_TO_CRITICAL as LOW_TO_CRITICAL,
    generate_clinical_summary,
)
from dataclasses import dataclass
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
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None


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


def compute_all_classifications(
    values: Dict[str, float],
    disabled_codes: Optional[set] = None,
    additional_indicators=(),
    reporting_month: Optional[str] = None,
    session=None,
) -> List[ClinicalClassification]:
    from app.engine import indicator_calc
    from app.engine import indicator_service

    results = []
    if session is not None:
        from app.engine.clinical.thresholds import clinical_threshold_for_definition
        from app.engine.rate_config import SITE_CLINICAL

        additional_indicators = indicator_service.resolve_active_definitions(
            session, site=SITE_CLINICAL)
    else:
        for th in CLINICAL_THRESHOLDS:
            if disabled_codes:
                all_th_codes = set(th.numerator_codes) | {th.denominator_code}
                if all_th_codes <= disabled_codes:
                    continue
            outcome = indicator_calc.evaluate_ratio_values(
                numerator_codes=th.numerator_codes,
                denominator_codes=[th.denominator_code],
                raw=values,
                multiplier=th.multiplier,
            )
            rate_val = outcome.value if outcome.status == indicator_calc.STATUS_OK else None
            cls = classify_clinical_rate(rate_val, th.rate_name)
            cls.value = rate_val
            cls.indicator_id = th.indicator_id
            cls.formula = th.formula
            cls.formula_version = th.formula_version
            results.append(cls)

    for resolved in additional_indicators or ():
        if disabled_codes and set(resolved.ref_codes or ()) <= disabled_codes:
            continue
        indicator_calc_result = indicator_service.calculate_from_values(
            resolved, values, hospital_id=0,
            month=reporting_month or "provided")
        value = indicator_calc_result.value
        clinical_threshold = (
            clinical_threshold_for_definition(resolved)
            if session is not None and resolved.site == "clinical"
            else None
        )
        if clinical_threshold:
            classification = (
                classify_rate(value, clinical_threshold)
                if indicator_calc_result.status == indicator_calc.STATUS_OK
                else "unknown"
            )
            results.append(ClinicalClassification(
                indicator_code=resolved.code,
                rate_name=resolved.name,
                value=value,
                unit=resolved.unit or "",
                threshold=clinical_threshold,
                classification=classification,
                label=CLASSIFICATION_LABELS.get(classification, classification.title()),
                color=CLASSIFICATION_COLORS.get(classification, "#888"),
                narrative=_build_narrative(clinical_threshold, classification, value)
                if value is not None else
                f"{resolved.name} could not be calculated ({indicator_calc_result.status}).",
                indicator_id=resolved.indicator_id,
                formula=resolved.formula,
                formula_version=resolved.formula_version,
            ))
            continue
        direction = getattr(resolved.definition, "direction", None)
        low = getattr(resolved.definition, "threshold_low", None)
        high = getattr(resolved.definition, "threshold_high", None)
        target_min = getattr(resolved.definition, "target_min", None)
        target_max = getattr(resolved.definition, "target_max", None)
        classification = "unknown"
        label = "No Threshold"
        if indicator_calc_result.status == indicator_calc.STATUS_OK and value is not None:
            if direction == "target_range" and target_min is not None and target_max is not None:
                classification = "normal" if target_min <= value <= target_max else "elevated"
            elif direction == "higher_is_better" and low is not None:
                classification = "normal" if value >= low else "below_normal"
            elif direction == "lower_is_better" and high is not None:
                classification = "normal" if value <= high else "elevated"
            elif low is not None or high is not None:
                classification = (
                    "normal" if (low is None or value >= low) and (high is None or value <= high)
                    else "elevated"
                )
            if classification != "unknown":
                label = CLASSIFICATION_LABELS.get(classification, classification.title())
        results.append(ClinicalClassification(
            indicator_code=resolved.code,
            rate_name=resolved.name,
            value=value,
            unit=resolved.unit or "",
            threshold=None,
            classification=classification,
            label=label,
            color=CLASSIFICATION_COLORS.get(classification, "#888"),
            narrative=(
                f"{resolved.name} is {value:g} {resolved.unit or ''}."
                if value is not None else
                f"{resolved.name} could not be calculated ({indicator_calc_result.status})."
            ),
            indicator_id=resolved.indicator_id,
            formula=resolved.formula,
            formula_version=resolved.formula_version,
        ))
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
                    "indicator_id": c.indicator_id,
                    "formula": c.formula,
                    "formula_version": c.formula_version,
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
    include_ai: bool = True,
    disabled_codes: Optional[set] = None,
    session=None,
) -> ClinicalAnalysisResult:
    classifications = compute_all_classifications(
        values,
        disabled_codes=disabled_codes,
        reporting_month=month,
        session=session,
    )
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
        include_ai=include_ai,
        session=session,
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
