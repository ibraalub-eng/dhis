import json
from sqlalchemy.orm import Session
from app.models import Hospital, QualityScore, ConfidenceScore, Indicator, IndicatorValue
from app.engine.clinical import compute_all_classifications, CLINICAL_THRESHOLDS
from app.engine.clinical.risk_profile import compute_risk_profile
from app.engine.clinical.morbidity import compute_morbidity_profile
from app.engine.pipeline import get_enabled_values_for_hospital_month
from app.indicators import INDICATOR_CODE_TO_NAME


def _name(code):
    return INDICATOR_CODE_TO_NAME.get(code, code)


def get_calculation_steps(db: Session, hospital_id: int, month: str) -> dict:
    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not values:
        return {"error": f"No data for hospital {hospital_id} / {month}"}

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    hospital_name = hospital.name if hospital else str(hospital_id)

    # Clinical classifications
    classifications = compute_all_classifications(values)
    cls_steps = []
    for c in classifications:
        threshold = None
        for t in CLINICAL_THRESHOLDS:
            if t.indicator_code == c.indicator_code:
                threshold = t
                break
        num_codes = list(threshold.numerator_codes) if threshold else []
        den_code = threshold.denominator_code if threshold else None
        num_val = sum(values.get(code, 0) or 0 for code in num_codes)
        den_val = values.get(den_code, 0) if den_code else 0
        num_names = [_name(c) for c in num_codes]
        den_name = _name(den_code) if den_code else None
        raw_numerators = {code: values.get(code, 0) or 0 for code in num_codes}
        cls_steps.append({
            "indicator_code": c.indicator_code,
            "rate_name": c.rate_name,
            "formula": _rate_formula(c.indicator_code, threshold),
            "formula_readable": _rate_formula_readable(threshold),
            "numerator_codes": num_codes,
            "numerator_names": num_names,
            "raw_numerators": raw_numerators,
            "denominator_code": den_code,
            "denominator_name": den_name,
            "numerator_value": num_val,
            "denominator_value": den_val,
            "unit": c.unit,
            "raw_rate": round(c.value, 4) if c.value is not None else None,
            "classification": c.classification,
            "label": c.label,
            "color": c.color,
            "narrative": c.narrative,
        })

    # Quality score (from DB — already computed)
    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    quality_score_steps = None
    if qs:
        from app.config_utils import get_config_dict
        _qcfg = get_config_dict(db, "quality")
        w_rc = float(_qcfg.get("quality_rule_compliance", 0.35))
        w_cp = float(_qcfg.get("quality_completeness", 0.25))
        w_co = float(_qcfg.get("quality_consistency", 0.25))
        w_op = float(_qcfg.get("quality_outlier_penalty", 0.15))
        rc_w = round((qs.rule_compliance or 0) * w_rc, 4)
        comp_w = round((qs.completeness or 0) * w_cp, 4)
        cons_w = round((qs.consistency or 0) * w_co, 4)
        # outlier_penalty is stored on the same 0-100 scale as the other components
        op_inv = 100.0 - (qs.outlier_penalty or 0)
        op_w = round(op_inv * w_op, 4)
        quality_score_steps = {
            "final_score": qs.score,
            "components": [
                {"name": "Validation rule", "weight": w_rc, "value": qs.rule_compliance, "weighted": rc_w, "formula": "passed_rules / total_rules"},
                {"name": "Completeness", "weight": w_cp, "value": qs.completeness, "weighted": comp_w, "formula": "filled_indicators / active_indicators"},
                {"name": "Consistency", "weight": w_co, "value": qs.consistency, "weighted": cons_w, "formula": "1.0 - (weighted_fail / total_weight)"},
                {"name": "Outlier Penalty (inverted)", "weight": w_op, "value": op_inv, "weighted": op_w, "formula": "100 - min(100, (outliers / total) * multiplier * 100)"},
            ],
        }

    # Confidence score (from DB)
    conf = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    conf_steps = None
    if conf:
        conf_steps = {
            "overall": conf.overall_confidence,
            "level": conf.level,
            "signal_weights": {"rule_compliance": 0.55, "historical": 0.10, "cross_hospital": 0.10, "trend": 0.10, "completeness": 0.15},
        }

    # Risk profile
    risk = compute_risk_profile(hospital_name, month, values)
    risk_steps = []
    for m in (risk.metrics if risk else []):
        risk_steps.append({
            "metric_name": m.metric_name,
            "value": round(m.value, 4) if m.value is not None else None,
            "unit": m.unit,
            "numerator": m.numerator,
            "denominator": m.denominator,
            "interpretation": m.interpretation,
            "severity": m.severity,
            "formula": f"{m.metric_name} = {m.numerator} / {m.denominator}",
        })

    # Morbidity profile
    morb = compute_morbidity_profile(hospital_name, month, values)
    morb_steps = []
    for m in (morb.metrics if morb else []):
        morb_steps.append({
            "metric_name": m.metric_name,
            "value": round(m.value, 4) if m.value is not None else None,
            "unit": m.unit,
            "numerator": m.numerator,
            "denominator": m.denominator,
            "interpretation": m.interpretation,
            "severity": m.severity,
        })

    # Raw data store — all indicators with names and values
    raw_data = []
    for code in sorted(values.keys(), key=lambda c: (len(c), c)):
        raw_data.append({
            "name": _name(code),
            "code": code,
            "value": values[code],
        })

    return {
        "hospital": hospital_name,
        "month": month,
        "classifications": cls_steps,
        "quality_score": quality_score_steps,
        "confidence": conf_steps,
        "risk_profile": {
            "metrics": risk_steps,
            "overall_risk_level": risk.overall_risk_level if risk else None,
        },
        "morbidity_profile": {
            "metrics": morb_steps,
            "total_smm": morb.total_smm if morb else 0,
            "maternal_deaths": morb.maternal_deaths if morb else 0,
        },
        "raw_data": raw_data,
    }


def _rate_formula(code, threshold):
    if not threshold:
        return ""
    num = " + ".join(threshold.numerator_codes) if len(threshold.numerator_codes) > 1 else threshold.numerator_codes[0]
    den = threshold.denominator_code
    mult = "100" if threshold.unit == "%" else "1,000" if "1,000" in threshold.unit else "100,000"
    return f"({num}) / ({den}) x {mult}"


def _rate_formula_readable(threshold):
    if not threshold:
        return ""
    num = " + ".join(_name(c) for c in threshold.numerator_codes)
    den = _name(threshold.denominator_code)
    mult = "100" if threshold.unit == "%" else "1,000" if "1,000" in threshold.unit else "100,000"
    return f"({num}) / ({den}) x {mult}"
