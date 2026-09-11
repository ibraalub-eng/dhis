import re
from typing import List, Dict
from app.engine.quality import ValidationContext, run_all_rules, run_rules_from_db, RuleResult, set_rules_config, calculate_quality_score, get_covered_child_codes
from app.engine.anomaly import detect_anomalies, detect_monthly_trend, set_trends_config

from app.engine.confidence import calculate_confidence, build_indicator_rule_map
from app.engine.ml import run_ml_analysis

from app.models import (
    Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig,
    IndicatorDefaultConfig,
    ValidationResult, AnomalyResult, QualityScore, ConfidenceScore,
)
from sqlalchemy.orm import Session
import json

from app.indicators import PARENT_CHILD_MAP, INDICATOR_CODE_TO_NAME
import logging

logger = logging.getLogger(__name__)

USE_DB_RULES = True

KEY_INDICATOR_CODES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "17", "18", "26"]


def _build_ml_config(flat: dict) -> dict:
    return {
        "enabled": bool(flat.get("ml_enabled", 0)),
        "clustering": {
            "enabled": bool(flat.get("ml_clustering_enabled", 1)),
            "min_k": int(flat.get("ml_clustering_min_k", 2)),
            "max_k": int(flat.get("ml_clustering_max_k", 6)),
        },
        "anomaly": {
            "enabled": bool(flat.get("ml_anomaly_enabled", 1)),
            "contamination": float(flat.get("ml_anomaly_contamination", 0.05)),
        },
        "pca": {
            "enabled": bool(flat.get("ml_pca_enabled", 1)),
            "variance_threshold": flat.get("ml_pca_variance_threshold", 0.95),
        },
    }


def get_values_for_hospital_month(session: Session, hospital_id: int, month: str) -> Dict[str, float]:
    rows = (
        session.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(IndicatorValue.hospital_id == hospital_id, IndicatorValue.month == month)
        .all()
    )
    return {row[1].code: row[0].value for row in rows if row[0].value is not None}


def _is_auto_disable_null(session):
    from app.models import SystemSetting
    row = session.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
    return bool(row and row.value == "true")


def get_default_disabled_indicator_ids(session, month):
    """Return indicator IDs disabled by the default (All Hospitals) config for a month.
    Month '__all__' disables an indicator if it is disabled in ANY month."""
    if month == "__all__":
        return [
            indicator_id
            for (indicator_id, enabled) in session.query(
                IndicatorDefaultConfig.indicator_id, IndicatorDefaultConfig.is_enabled
            ).all()
            if not enabled
        ]
    return [
        c.indicator_id
        for c in session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.month == month,
            IndicatorDefaultConfig.is_enabled.is_(False),
        ).all()
    ]


def get_hospital_override_indicator_ids(session, hospital_id):
    """Return indicator IDs that have an explicit per-hospital config (override) — any state."""
    return [
        c.indicator_id
        for c in session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id,
        ).all()
    ]


def get_effective_manual_disabled_ids(session, hospital_id, month):
    """Return the effective manually-disabled indicator IDs for a hospital/month.
    A hospital's own config (whether enabled or disabled) always overrides the
    default (All Hospitals) config for that month."""
    hospital_disabled = {
        c.indicator_id
        for c in session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id,
            HospitalIndicatorConfig.is_enabled.is_(False),
        ).all()
    }
    override_ids = set(get_hospital_override_indicator_ids(session, hospital_id))
    default_disabled = set(get_default_disabled_indicator_ids(session, month))
    return list(hospital_disabled | (default_disabled - override_ids))


def get_enabled_values_for_hospital_month(session: Session, hospital_id: int, month: str) -> Dict[str, float]:
    disabled_ids = set(get_effective_manual_disabled_ids(session, hospital_id, month))
    rows = (
        session.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.month == month,
        )
        .all()
    )
    result = {}
    for val, ind in rows:
        if ind.id in disabled_ids:
            continue
        if val.value is not None:
            result[ind.code] = val.value
    return result


def get_disabled_indicator_ids(session, hospital_id, month):
    """Return all indicator IDs that should be considered disabled — manual + auto (null values + missing rows)."""
    manually_disabled = get_effective_manual_disabled_ids(session, hospital_id, month)
    if _is_auto_disable_null(session):
        null_rows = (
            session.query(IndicatorValue.indicator_id)
            .filter(
                IndicatorValue.hospital_id == hospital_id,
                IndicatorValue.month == month,
                IndicatorValue.value.is_(None),
            )
            .all()
        )
        null_ids = [r[0] for r in null_rows if r[0] not in manually_disabled]

        # Also disable indicators that have NO row at all for this hospital/month
        existing_ids = [
            r[0] for r in session.query(IndicatorValue.indicator_id).filter(
                IndicatorValue.hospital_id == hospital_id,
                IndicatorValue.month == month,
            ).distinct().all()
        ]
        all_indicator_ids = [r[0] for r in session.query(Indicator.id).all()]
        missing_ids = [
            iid for iid in all_indicator_ids
            if iid not in manually_disabled and iid not in existing_ids
        ]

        return manually_disabled + null_ids + missing_ids
    return manually_disabled


def get_all_hospital_data_for_month(session: Session, month: str) -> Dict[str, Dict[str, float]]:
    hospitals = session.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    result = {}
    for hosp in hospitals:
        vals = get_enabled_values_for_hospital_month(session, hosp.id, month)
        if vals:
            result[hosp.name] = vals
    return result


def get_historical_months(session: Session, hospital_id: int, current_month: str) -> Dict[str, Dict[str, float]]:
    rows = (
        session.query(IndicatorValue.month)
        .filter(IndicatorValue.hospital_id == hospital_id)
        .distinct()
        .all()
    )
    months = [r[0] for r in rows if r[0] != current_month]
    result = {}
    for m in months:
        vals = get_enabled_values_for_hospital_month(session, hospital_id, m)
        if vals:
            result[m] = vals
    return result


def check_analysis_exists(session: Session, hospital_id: int, month: str) -> bool:
    """Check if analysis results already exist for a hospital/month."""
    return session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first() is not None


def _compute_full_analysis(session: Session, hospital_id: int, month: str, force: bool = False) -> Dict:
    hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise ValueError(f"Hospital id {hospital_id} not found")

    # Skip analysis if results already exist and not forced
    if not force and check_analysis_exists(session, hospital_id, month):
        existing_qs = session.query(QualityScore).filter(
            QualityScore.hospital_id == hospital_id,
            QualityScore.month == month,
        ).first()
        return {
            "hospital": hospital.name,
            "month": month,
            "data_quality_score": existing_qs.score,
            "rule_compliance": existing_qs.rule_compliance,
            "completeness": existing_qs.completeness,
            "consistency": existing_qs.consistency,
            "outlier_penalty": existing_qs.outlier_penalty,
            "issues": json.loads(existing_qs.issues) if existing_qs.issues else [],
            "outliers": [],
            "cached": True,
        }

    values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    if not values:
        # Purge stale stored results so screens don't show data for a
        # hospital/month that now has no enabled data.
        session.query(ValidationResult).filter(
            ValidationResult.hospital_id == hospital_id,
            ValidationResult.month == month,
        ).delete(synchronize_session=False)
        session.query(AnomalyResult).filter(
            AnomalyResult.hospital_id == hospital_id,
            AnomalyResult.month == month,
        ).delete(synchronize_session=False)
        session.query(ConfidenceScore).filter(
            ConfidenceScore.hospital_id == hospital_id,
            ConfidenceScore.month == month,
        ).delete(synchronize_session=False)
        session.commit()
        return {
            "hospital": hospital.name,
            "month": month,
            "data_quality_score": 0,
            "issues": ["No data found for this hospital/month"],
            "outliers": [],
        }

    all_hospital_data = get_all_hospital_data_for_month(session, month)
    historical = get_historical_months(session, hospital_id, month)

    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
    disabled_codes = set()
    if disabled_ids:
        ind_rows = session.query(Indicator).filter(Indicator.id.in_(disabled_ids)).all()
        disabled_codes = {ind.code for ind in ind_rows}

    ctx = ValidationContext(
        values=values,
        hospital_name=hospital.name,
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data=historical if historical else {},
        disabled_codes=disabled_codes,
    )

    from app.config_utils import get_config_dict
    rules_config = get_config_dict(session, "rules")
    set_rules_config(rules_config)

    trends_config = get_config_dict(session, "trends")
    rates_config = get_config_dict(session, "rates")
    trends_config.update(rates_config)
    if "zscore_threshold" not in trends_config:
        thresh_config = get_config_dict(session, "thresholds")
        trends_config["zscore_threshold"] = thresh_config.get("zscore_threshold", 2.5)
    set_trends_config(trends_config)

    anomaly_config = {"zscore_threshold": trends_config["zscore_threshold"]}

    ml_config = get_config_dict(session, "ml")
    ml_config_nested = _build_ml_config(ml_config)
    ml_results = {}
    if ml_config_nested.get("enabled", False):
        try:
            ml_results = run_ml_analysis(all_hospital_data, ml_config_nested) or {}
        except Exception:
            logger.exception("ML analysis failed for %s/%s; continuing without ML results", hospital.name, month)

    if USE_DB_RULES:
        rule_results = run_rules_from_db(session, ctx)
        if not rule_results:
            import logging
            logging.getLogger(__name__).warning("No rules returned from DB, falling back to compiled rules")
            rule_results = run_all_rules(ctx)
    else:
        rule_results = run_all_rules(ctx)

    # Build indicator code-to-name mapping from DB
    all_indicators = session.query(Indicator.code, Indicator.name).all()
    code_to_name = {ind.code: ind.name for ind in all_indicators}
    codes_sorted = sorted(code_to_name.keys(), key=len, reverse=True)
    if codes_sorted:
        code_pattern = r'(?<!\d)(' + '|'.join(re.escape(c) for c in codes_sorted) + r')(?![.\d])'
        def _resolve_codes(text):
            return re.sub(code_pattern, lambda m: code_to_name[m.group(1)], text)
        for r in rule_results:
            if r.details:
                r.details = _resolve_codes(r.details)

    anomaly_results = detect_anomalies(all_hospital_data, hospital.name, month, anomaly_config)
    trend_anomalies = detect_monthly_trend(historical, month, values, anomaly_config)

    # Deduplicate by indicator_code — prefer cross-hospital anomaly over trend
    seen_codes: set = set()
    deduped_anomalies: list = []
    for a in anomaly_results + trend_anomalies:
        code = getattr(a, "indicator_code", None)
        if code and code not in seen_codes:
            seen_codes.add(code)
            deduped_anomalies.append(a)
    anomaly_results = deduped_anomalies

    total_indicators = session.query(Indicator).count()
    all_disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
    active_indicator_count = total_indicators - len(all_disabled_ids)
    from app.config_utils import get_config_dict
    quality_config = get_config_dict(session, "quality")
    covered_codes = get_covered_child_codes(ctx, session)
    quality = calculate_quality_score(rule_results, values, anomaly_results, active_indicator_count, quality_config, covered_codes=covered_codes)

    indicator_rule_map = build_indicator_rule_map(session)
    all_indicators_db = session.query(Indicator.code, Indicator.name).all()
    indicator_map = {ind.code: ind.name for ind in all_indicators_db}
    indicator_map.update(INDICATOR_CODE_TO_NAME)

    confidence_data = {}
    try:
        confidence_result = calculate_confidence(
            hospital_name=hospital.name,
            month=month,
            values=values,
            rule_results=rule_results,
            historical_data=historical if historical else {},
            all_hospital_data=all_hospital_data,
            indicator_map=indicator_map,
            indicator_children=PARENT_CHILD_MAP,
            indicator_rule_map=indicator_rule_map,
            key_indicator_codes=KEY_INDICATOR_CODES,
            disabled_codes=disabled_codes,
            session=session,
        )
        confidence_data = confidence_result.to_dict()
    except Exception:
        logger.exception("Confidence analysis failed for %s/%s; continuing with core results", hospital.name, month)

    _save_validation_results(session, hospital_id, month, rule_results)
    _save_anomaly_results(session, hospital_id, month, anomaly_results)
    _save_quality_score(session, hospital_id, month, quality)
    if confidence_data:
        try:
            _save_confidence_score(session, hospital_id, month, confidence_data)
        except Exception:
            logger.exception("Saving confidence score failed for %s/%s", hospital.name, month)

    outliers = []
    for a in anomaly_results:
        if a.is_outlier:
            outliers.append({
                "indicator": a.rate_name,
                "value": float(a.value) if a.value is not None else None,
                "benchmark": float(a.benchmark) if a.benchmark is not None else None,
                "z_score": float(a.z_score) if a.z_score is not None else None,
            })

    return {
        "hospital": hospital.name,
        "month": month,
        "data_quality_score": quality["score"],
        "rule_compliance": quality["rule_compliance"],
        "completeness": quality["completeness"],
        "consistency": quality["consistency"],
        "outlier_penalty": quality["outlier_penalty"],
        "issues": quality["issues"],
        "outliers": outliers,
        "cached": False,
        "confidence": {
            "overall_confidence": confidence_data.get("overall_confidence", 0),
            "level": confidence_data.get("level", "UNKNOWN"),
            "by_level": confidence_data.get("by_level", {}),
            "by_group": confidence_data.get("by_group", {}),
            "priority_verify": [
                {
                    "indicator_code": i.get("indicator_code"),
                    "indicator_name": i.get("indicator_name"),
                    "value": i.get("value"),
                    "confidence": i.get("confidence"),
                    "level": i.get("level"),
                    "recommendations": i.get("recommendations", []),
                }
                for i in (confidence_data.get("priority_verify") or [])
            ],
            "summary": confidence_data.get("summary", ""),
        },
        **ml_results,
    }


def run_full_analysis(session: Session, hospital_id: int, month: str, force: bool = False) -> Dict:
    """Run full analysis for a hospital/month, guaranteeing a QualityScore row is
    persisted so the report always appears in /reports/ and /analysis/months.

    If analysis reports that no data was found, a score-0 QualityScore is still
    saved (so detected-but-empty months stay visible). If any analysis step
    raises, a minimal quality report is persisted with the error recorded in the
    issues list, instead of the month silently disappearing.
    """
    try:
        result = _compute_full_analysis(session, hospital_id, month, force=force)
        # Empty/missing-data path returns early without persisting — persist it
        # so the detected month still shows a report row.
        if not result.get("cached") and not check_analysis_exists(session, hospital_id, month):
            _save_quality_score(session, hospital_id, month, {
                "score": result.get("data_quality_score", 0),
                "rule_compliance": result.get("rule_compliance", 0),
                "completeness": result.get("completeness", 0),
                "consistency": result.get("consistency", 0),
                "outlier_penalty": result.get("outlier_penalty", 0),
                "issues": result.get("issues") or [],
            })
        return result
    except ValueError:
        raise
    except Exception:
        logger.exception("Full analysis failed for %s/%s; saving fallback quality report", hospital_id, month)
        try:
            _save_quality_score(session, hospital_id, month, {
                "score": 0,
                "rule_compliance": 0,
                "completeness": 0,
                "consistency": 0,
                "outlier_penalty": 0,
                "issues": ["Analysis failed during report generation"],
            })
        except Exception:
            logger.exception("Could not save fallback quality report for %s/%s", hospital_id, month)
        hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
        return {
            "hospital": hospital.name if hospital else None,
            "month": month,
            "data_quality_score": 0,
            "rule_compliance": 0,
            "completeness": 0,
            "consistency": 0,
            "outlier_penalty": 0,
            "issues": ["Analysis failed during report generation"],
            "outliers": [],
            "cached": False,
        }


def _save_validation_results(session: Session, hospital_id: int, month: str, results: List[RuleResult]):
    session.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
    ).delete()
    for r in results:
        rule_type = r.rule_type.value if hasattr(r.rule_type, 'value') else str(r.rule_type)
        vr = ValidationResult(
            hospital_id=hospital_id,
            month=month,
            rule_code=r.rule_code,
            rule_description=r.description,
            status=r.status.value,
            severity=r.severity.value,
            rule_type=rule_type,
            details=r.details,
        )
        session.add(vr)
    session.commit()


def _save_anomaly_results(session: Session, hospital_id: int, month: str, results: list):
    session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
    ).delete()
    for a in results:
        ar = AnomalyResult(
            hospital_id=hospital_id,
            month=month,
            indicator_code=a.indicator_code,
            rate_name=a.rate_name,
            value=float(a.value) if a.value is not None else None,
            benchmark=float(a.benchmark) if a.benchmark is not None else None,
            z_score=float(a.z_score) if a.z_score is not None else None,
            is_outlier=bool(a.is_outlier),
        )
        session.add(ar)
    session.commit()


def _save_quality_score(session: Session, hospital_id: int, month: str, quality: Dict):
    existing = session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    if existing:
        existing.score = quality["score"]
        existing.rule_compliance = quality["rule_compliance"]
        existing.completeness = quality["completeness"]
        existing.consistency = quality["consistency"]
        existing.outlier_penalty = quality["outlier_penalty"]
        existing.issues = json.dumps(quality["issues"])
    else:
        qs = QualityScore(
            hospital_id=hospital_id,
            month=month,
            score=quality["score"],
            rule_compliance=quality["rule_compliance"],
            completeness=quality["completeness"],
            consistency=quality["consistency"],
            outlier_penalty=quality["outlier_penalty"],
            issues=json.dumps(quality["issues"]),
        )
        session.add(qs)
    session.commit()


def _save_confidence_score(session: Session, hospital_id: int, month: str, confidence_data: Dict):
    existing = session.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if existing:
        existing.overall_confidence = confidence_data["overall_confidence"]
        existing.level = confidence_data["level"]
        existing.indicator_count = confidence_data["indicator_count"]
        existing.high_count = confidence_data["by_level"].get("HIGH", 0)
        existing.medium_count = confidence_data["by_level"].get("MEDIUM", 0)
        existing.low_count = confidence_data["by_level"].get("LOW", 0)
        existing.critical_count = confidence_data["by_level"].get("CRITICAL", 0)
        existing.indicators_data = json.dumps(confidence_data["indicators"])
        existing.summary = confidence_data["summary"]
    else:
        cs = ConfidenceScore(
            hospital_id=hospital_id,
            month=month,
            overall_confidence=confidence_data["overall_confidence"],
            level=confidence_data["level"],
            indicator_count=confidence_data["indicator_count"],
            high_count=confidence_data["by_level"].get("HIGH", 0),
            medium_count=confidence_data["by_level"].get("MEDIUM", 0),
            low_count=confidence_data["by_level"].get("LOW", 0),
            critical_count=confidence_data["by_level"].get("CRITICAL", 0),
            indicators_data=json.dumps(confidence_data["indicators"]),
            summary=confidence_data["summary"],
        )
        session.add(cs)
    session.commit()
