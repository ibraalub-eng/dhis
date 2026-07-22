from typing import Dict, Any
from sqlalchemy.orm import Session

from app.engine.smart.schemas import SmartAnalyticsResult, KPISummary
from app.engine.smart.anomaly import detect_smart_anomalies
from app.engine.smart.clustering import run_clustering
from app.engine.smart.correlations import analyze_correlations
from app.engine.smart.residual import analyze_residuals
from app.engine.smart.stratified import run_stratified_analysis
from app.engine.smart.explainability import explain_anomalies
from app.engine.smart.geo import aggregate_by_governorate


def _load_hospital_data(session: Session, month: str) -> Dict[str, Any]:
    from app.models import Hospital, IndicatorValue, Indicator

    hospitals = session.query(Hospital).filter(Hospital.is_active).all()
    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}

    all_data = {}
    for hosp in hospitals:
        values = session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hosp.id,
            IndicatorValue.month == month,
        ).all()

        indicator_values = {}
        for iv in values:
            code = indicator_map.get(iv.indicator_id, "")
            if code and iv.value is not None:
                indicator_values[code] = float(iv.value)

        all_data[hosp.name] = {
            "hospital_id": hosp.id,
            "governorate": hosp.governorate.name if hosp.governorate else "unknown",
            "hospital_type": hosp.hospital_type.name if hosp.hospital_type else "unknown",
            "values": indicator_values,
        }

    return all_data


def _load_config(session: Session) -> Dict[str, Any]:
    from app.models import AppConfig

    configs = session.query(AppConfig).filter(
        AppConfig.category == "smart_analytics"
    ).all()

    config = {}
    for c in configs:
        key = c.key.replace("smart_", "")
        config[key] = c.value

    return config


def run_smart_analytics(session: Session, month: str) -> SmartAnalyticsResult:
    all_data = _load_hospital_data(session, month)
    config = _load_config(session)

    enabled = config.get("enabled", 1.0) > 0.5

    anomalies = detect_smart_anomalies(all_data, config, enabled=enabled)
    clustering = run_clustering(all_data, config, enabled=enabled)
    correlations = analyze_correlations(all_data, config)
    residuals = analyze_residuals(all_data, config)
    stratified = run_stratified_analysis(all_data, config)
    explanations = explain_anomalies(anomalies, all_data, config)
    geo = aggregate_by_governorate(anomalies, all_data)

    residual_by_hospital = {}
    for r in residuals:
        if r.indicator == "cs_rate":
            residual_by_hospital[r.hospital_name] = abs(r.residual_z_score) / 4.0

    for a in anomalies:
        if a.hospital_name in residual_by_hospital:
            a.method_scores["residual"] = residual_by_hospital[a.hospital_name]

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    affected_govs = len(set(a.governorate for a in anomalies if a.is_outlier))

    top_factor = ""
    if explanations:
        all_factors = []
        for e in explanations:
            all_factors.extend(e.top_factors)
        if all_factors:
            top_factor = max(all_factors, key=lambda f: abs(f.shap_value)).arabic_label

    if critical_count > 0:
        month_status = "critical"
    elif warning_count > 0:
        month_status = "attention_needed"
    else:
        month_status = "normal"

    kpi = KPISummary(
        total_anomalies=critical_count + warning_count,
        critical_count=critical_count,
        warning_count=warning_count,
        affected_governorates=affected_govs,
        top_contributing_factor=top_factor,
        month_status=month_status,
    )

    return SmartAnalyticsResult(
        month=month,
        hospitals_count=len(all_data),
        anomalies=anomalies,
        clustering=clustering,
        correlations=correlations,
        residuals=residuals,
        stratified=stratified,
        explanations=explanations,
        geo=geo,
        kpi=kpi,
    )
