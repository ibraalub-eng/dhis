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
from app.engine.smart.xgboost_predictor import run_xgboost_predictions
from app.engine.smart.patterns import detect_composite_patterns


def _load_hospital_data(session: Session, month: str) -> Dict[str, Any]:
    """Bulk-load hospital data for a month — 4 queries total instead of N*2."""
    from app.models import Hospital, IndicatorValue, Indicator, HospitalIndicatorConfig
    from app.engine.pipeline import _is_auto_disable_null

    hospitals = session.query(Hospital).filter(Hospital.is_active).all()
    if not hospitals:
        return {}

    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}
    all_indicator_ids = {ind.id for ind in indicators}

    # ── Bulk query 1: ALL indicator values for this month ──
    all_values = session.query(IndicatorValue).filter(
        IndicatorValue.month == month,
    ).all()
    values_by_hosp = {}
    for iv in all_values:
        values_by_hosp.setdefault(iv.hospital_id, []).append(iv)

    # ── Bulk query 2: ALL disabled configs (not per-hospital) ──
    all_disabled = session.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    disabled_map = {}
    for d in all_disabled:
        disabled_map.setdefault(d.hospital_id, set()).add(d.indicator_id)

    # ── Auto-disable: null values + missing indicators (bulk) ──
    auto_disabled_map = {}
    if _is_auto_disable_null(session):
        iv_ids_by_hosp = {}
        null_ids_by_hosp = {}
        for iv in all_values:
            iv_ids_by_hosp.setdefault(iv.hospital_id, set()).add(iv.indicator_id)
            if iv.value is None:
                null_ids_by_hosp.setdefault(iv.hospital_id, set()).add(iv.indicator_id)
        for hosp in hospitals:
            hid = hosp.id
            existing = iv_ids_by_hosp.get(hid, set())
            nulls = null_ids_by_hosp.get(hid, set())
            manually = disabled_map.get(hid, set())
            missing = all_indicator_ids - existing - manually
            auto_disabled_map[hid] = nulls | missing

    all_data = {}
    for hosp in hospitals:
        hid = hosp.id
        manually_disabled = disabled_map.get(hid, set())
        auto_disabled = auto_disabled_map.get(hid, set()) if auto_disabled_map else set()
        disabled_codes = {
            ind.code for ind in indicators
            if ind.id in (manually_disabled | auto_disabled)
        }

        hosp_values = values_by_hosp.get(hid, [])
        indicator_values = {}
        for iv in hosp_values:
            code = indicator_map.get(iv.indicator_id, "")
            if code and code not in disabled_codes and iv.value is not None:
                indicator_values[code] = float(iv.value)

        def _src(code: str) -> float:
            if code in disabled_codes:
                return None
            return indicator_values.get(code)

        total_deliveries = _src("2")
        cs_count = _src("5")

        derived = {}
        if total_deliveries is not None and total_deliveries > 0 and cs_count is not None:
            derived["cs_rate"] = cs_count / total_deliveries * 100
        for feature, src_code in [
            ("smm_total", "10"), ("mat_deaths", "11"), ("nd", "17"),
            ("sb", "7"), ("preterm", "6.f"), ("lbw", "6.g"),
            ("total_births", "6"), ("high_risk", "2.n"),
        ]:
            v = _src(src_code)
            if v is not None:
                derived[feature] = v
        a = _src("2.c")
        b = _src("2.d")
        if a is not None or b is not None:
            derived["adolescent"] = (a or 0) + (b or 0)

        indicator_values.update(derived)

        if not indicator_values:
            continue

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

    # Compute residuals FIRST so they can genuinely feed the anomaly ensemble.
    residuals = analyze_residuals(all_data, config)
    residual_scores = {}
    for r in residuals:
        if r.indicator == "cs_rate":
            residual_scores[r.hospital_name] = abs(r.residual_z_score) / 4.0

    anomalies = detect_smart_anomalies(
        all_data, config, residual_scores=residual_scores, enabled=enabled
    )
    clustering = run_clustering(all_data, config, enabled=enabled)
    correlations = analyze_correlations(all_data, config)
    stratified = run_stratified_analysis(all_data, config)
    explanations = explain_anomalies(anomalies, all_data, config, stratified=stratified)
    geo = aggregate_by_governorate(anomalies, all_data)
    try:
        patterns = detect_composite_patterns(all_data, config, enabled=enabled)
    except Exception:
        patterns = []

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

    xgb_predictions = None
    if config.get("xgboost_enabled", True):
        try:
            xgb_predictions = run_xgboost_predictions(session, month, config)
        except Exception:
            xgb_predictions = None

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
        patterns=patterns,
        xgboost_predictions=xgb_predictions,
    )
