import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, QualityScore, ValidationResult
from app.engine.pipeline import get_enabled_values_for_hospital_month
from app.engine.clinical import run_clinical_analysis
from app.schemas import ClinicalAnalysisOut, ClinicalRiskProfileOut, ClinicalMorbidityProfileOut
from app.core.deps import require_permission

router = APIRouter(prefix="/clinical", tags=["clinical"], dependencies=[Depends(require_permission("clinical.read"))])


@router.get("/{hospital_id}", response_model=ClinicalAnalysisOut)
def get_clinical_analysis(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail=f"Hospital id {hospital_id} not found")

    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not values:
        raise HTTPException(status_code=404, detail=f"No data found for hospital {hospital.name} in {month}")

    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()

    quality_score = qs.score if qs else None
    issues = []
    if qs and qs.issues:
        issues = json.loads(qs.issues)

    rule_failures = [
        {"rule_code": vr.rule_code, "details": vr.details or "", "severity": vr.severity}
        for vr in db.query(ValidationResult).filter(
            ValidationResult.hospital_id == hospital_id,
            ValidationResult.month == month,
            ValidationResult.status == "FAIL",
        ).all()
    ]

    result = run_clinical_analysis(
        hospital=hospital.name,
        month=month,
        values=values,
        quality_score=quality_score,
        issues=issues,
        rule_failures=rule_failures,
        completeness=qs.completeness if qs else 0,
        consistency=qs.consistency if qs else 0,
        rule_compliance=qs.rule_compliance if qs else 0,
        outlier_penalty=qs.outlier_penalty if qs else 0,
        # الجلسة تُمكّن تخزين استجابات التوصيات المؤقت حسب (مستشفى، شهر)
        session=db,
    )

    return _result_to_schema(result)


@router.post("/analyze")
def analyze_clinical(
    hospital_id: int = Query(...),
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    return get_clinical_analysis(hospital_id, month, db)


def _result_to_schema(result):
    return ClinicalAnalysisOut(
        hospital=result.hospital,
        month=result.month,
        classifications=[
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
            for c in result.classifications
        ],
        risk_profile=ClinicalRiskProfileOut(
            hospital=result.risk_profile.hospital,
            month=result.risk_profile.month,
            total_deliveries=result.risk_profile.total_deliveries,
            overall_risk_level=result.risk_profile.overall_risk_level,
            key_findings=result.risk_profile.key_findings,
            metrics=[
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
                for m in result.risk_profile.metrics
            ],
        ),
        morbidity_profile=ClinicalMorbidityProfileOut(
            hospital=result.morbidity_profile.hospital,
            month=result.morbidity_profile.month,
            total_deliveries=result.morbidity_profile.total_deliveries,
            total_smm=result.morbidity_profile.total_smm,
            maternal_deaths=result.morbidity_profile.maternal_deaths,
            key_findings=result.morbidity_profile.key_findings,
            mortality_preventability_signals=result.morbidity_profile.mortality_preventability_signals,
            metrics=[
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
                for m in result.morbidity_profile.metrics
            ],
        ),
        recommendations=[
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
            for r in result.recommendations
        ],
        summary={
            "overview": result.summary.overview,
            "key_findings": result.summary.key_findings,
            "clinical_indicators": result.summary.clinical_indicators,
            "risk_assessment": result.summary.risk_assessment,
            "morbidity_assessment": result.summary.morbidity_assessment,
            "recommendations_text": result.summary.recommendations_text,
            "overall_assessment": result.summary.overall_assessment,
        },
    )
