import json
from sqlalchemy.orm import Session
from app.models import Hospital, IndicatorValue, Indicator, ValidationResult, QualityScore, AnomalyResult, HospitalIndicatorConfig, ConfidenceScore


def get_data_audit(db: Session, hospital_id: int, month: str) -> dict:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        return {"error": "Hospital not found"}

    all_indicators = db.query(Indicator).order_by(Indicator.code).all()
    values_q = db.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hospital_id,
        IndicatorValue.month == month,
    ).all()

    completeness = []
    missing_count = 0
    present_count = 0
    for ind in all_indicators:
        val_row = next((v for v in values_q if v.indicator_id == ind.id), None)
        is_present = val_row is not None and val_row.value is not None
        if is_present:
            present_count += 1
        else:
            missing_count += 1
        completeness.append({
            "indicator_code": ind.code,
            "indicator_name": ind.name,
            "value": val_row.value if val_row else None,
            "status": "present" if is_present else "missing",
        })

    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()

    rules = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
        ValidationResult.status == "FAIL",
    ).all()
    rule_impact = []
    for r in rules:
        sev_weight = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(r.severity, 0)
        rule_impact.append({
            "rule_code": r.rule_code,
            "description": r.rule_description,
            "severity": r.severity,
            "severity_weight": sev_weight,
            "details": r.details or "",
        })

    conf = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    conf_data = None
    if conf:
        conf_data = {
            "overall_confidence": conf.overall_confidence,
            "level": conf.level,
            "indicator_count": conf.indicator_count,
            "by_level": {
                "high": conf.high_count,
                "medium": conf.medium_count,
                "low": conf.low_count,
                "critical": conf.critical_count,
            },
        }

    outliers_q = db.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
        AnomalyResult.is_outlier.is_(True),
    ).all()
    outlier_details = []
    for o in outliers_q:
        outlier_details.append({
            "indicator_code": o.indicator_code,
            "rate_name": o.rate_name,
            "value": o.value,
            "benchmark": o.benchmark,
            "z_score": o.z_score,
        })

    qs_breakdown = None
    if qs:
        rc_w = round((qs.rule_compliance or 0) * 0.35, 4)
        comp_w = round((qs.completeness or 0) * 0.25, 4)
        cons_w = round((qs.consistency or 0) * 0.25, 4)
        op_inv = 1 - (qs.outlier_penalty or 0)
        op_w = round(op_inv * 0.15, 4)
        total_weighted = rc_w + comp_w + cons_w + op_w
        qs_breakdown = {
            "score": qs.score,
            "components": [
                {"name": "Rule Compliance", "raw": qs.rule_compliance, "weight": 0.35, "weighted": rc_w, "contribution_pct": round(rc_w / total_weighted * 100, 1) if total_weighted else 0},
                {"name": "Completeness", "raw": qs.completeness, "weight": 0.25, "weighted": comp_w, "contribution_pct": round(comp_w / total_weighted * 100, 1) if total_weighted else 0},
                {"name": "Consistency", "raw": qs.consistency, "weight": 0.25, "weighted": cons_w, "contribution_pct": round(cons_w / total_weighted * 100, 1) if total_weighted else 0},
                {"name": "Outlier (inverted)", "raw": op_inv, "weight": 0.15, "weighted": op_w, "contribution_pct": round(op_w / total_weighted * 100, 1) if total_weighted else 0},
            ],
        }

    return {
        "hospital": hospital.name,
        "month": month,
        "completeness": {
            "total": len(all_indicators),
            "present": present_count,
            "missing": missing_count,
            "indicators": completeness,
        },
        "rule_failures": {
            "total": len(rule_impact),
            "items": rule_impact,
        },
        "quality_score": qs_breakdown,
        "confidence": conf_data,
        "outliers": {
            "total": len(outlier_details),
            "items": outlier_details,
        },
    }
