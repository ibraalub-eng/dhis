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


def _disabled_maps(session: Session, month: str, hospitals, indicators, all_values):
    """خرائط المؤشرات المعطّلة لكل مستشفى لهذا الشهر.

    يعيد (combined_disabled_map, auto_disabled_map) بنفس منطق التحميل الرئيسي:
    معطّلات المستشفى اليدوية، ومعطّلات «كل المستشفيات» الوراثية إلا إذا عارضها
    المستشفى، ثم المعطّلات التلقائية (قيم null + مؤشرات بلا صف) عند تفعيلها.
    استُخرجت من _load_hospital_data لتعيدها لوحة تغطية المؤشرات بلا تكرار.
    """
    from app.models import HospitalIndicatorConfig, IndicatorDefaultConfig
    from app.engine.pipeline import _is_auto_disable_null

    all_indicator_ids = {ind.id for ind in indicators}

    # ── Manual disabled configs (not per-month) ──
    all_disabled = session.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.is_enabled.is_(False),
    ).all()
    disabled_map = {}
    for d in all_disabled:
        disabled_map.setdefault(d.hospital_id, set()).add(d.indicator_id)

    # Default (All Hospitals) disabled for this month — inherited unless hospital overrides ──
    from app.models import IndicatorDefaultConfig
    default_disabled = set(
        c.indicator_id for c in session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.month == month,
            IndicatorDefaultConfig.is_enabled.is_(False),
        ).all()
    )
    override_map = {}
    for c in session.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.is_enabled.is_(True),
    ).all():
        override_map.setdefault(c.hospital_id, set()).add(c.indicator_id)

    # Combine: hospital-explicit wins, otherwise inherit default for the month
    combined_disabled_map = {}
    for hid in [h.id for h in hospitals]:
        combined_disabled_map[hid] = set(disabled_map.get(hid, ())) | (
            default_disabled - override_map.get(hid, set())
        )

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
            manually = combined_disabled_map.get(hid, set())
            missing = all_indicator_ids - existing - manually
            auto_disabled_map[hid] = nulls | missing

    return combined_disabled_map, auto_disabled_map


# ── مصادر كل ميزة مشتقة من رموز قاعدة البيانات (نفس اشتقاق _load_hospital_data) ──
# تُستخدم في لوحة «المؤشرات التي يمكن للتحليل العمل عليها» لعرض ما يعتمد عليه
# المحرك فعلياً: القيصارية نسبة من رقمين، والباقي عدّادات من رمز واحد
# (المراهقتان مجموع رمزين). أي مؤشر خارج هذه القائمة لا يدخل نماذج الشذوذ.
FEATURE_SOURCE_CODES = {
    "cs_rate": ("5", "2"),
    "smm_total": ("10",),
    "mat_deaths": ("11",),
    "nd": ("17",),
    "sb": ("7",),
    "preterm": ("6.f",),
    "lbw": ("6.g",),
    "total_births": ("6",),
    "high_risk": ("2.n",),
    "adolescent": ("2.c", "2.d"),
}


# نوع كل ميزة كما يعرضها لوحة التغطية: نسبة مشتقة أم عدّاد خام
FEATURE_KINDS = {k: ("rate" if k == "cs_rate" else "count") for k in FEATURE_SOURCE_CODES}


def analysis_indicator_coverage(session: Session, month: str) -> Dict[str, Any]:
    """تغطية كل ميزة مشتقة يعتمد عليها التحليل الذكي في شهر معيّن.

    تجيب عن سؤال «ما المؤشرات التي يمكن العمل عليها؟»: لكل ميزة من
    FEATURE_KEYS عدد المستشفيات التي يمكن اشتقاق قيمتها هذا الشهر، والمعطّلة
    (مصدرها معطّل يدوياً/افتراضياً/تلقائياً)، والناقصة — بلا صفر صامت.
    تُطابق اشتقاق _load_hospital_data حرفياً (نفس الخرائط المعطّلة ونفس شروط
    المقام للقيصارية وشرط وجود رمز واحد على الأقل للمراهقتين).
    """
    from app.engine.smart.anomaly import FEATURE_KEYS
    from app.engine.smart.explainability import ARABIC_NAMES
    from app.models import Hospital, Indicator, IndicatorValue

    hospitals = session.query(Hospital).filter(Hospital.is_active).all()
    total = len(hospitals)
    indicators = session.query(Indicator).all()
    ind_map = {i.id: i.code for i in indicators}
    all_values = (
        session.query(IndicatorValue)
        .filter(IndicatorValue.month == month)
        .all()
    )
    combined_disabled_map, auto_disabled_map = _disabled_maps(
        session, month, hospitals, indicators, all_values
    )

    values_by_hosp: Dict[int, Dict[str, float]] = {}
    for iv in all_values:
        code = ind_map.get(iv.indicator_id)
        if code and iv.value is not None:
            values_by_hosp.setdefault(iv.hospital_id, {})[code] = float(iv.value)

    rows = []
    for feature in FEATURE_KEYS:
        codes = FEATURE_SOURCE_CODES.get(feature)
        if not codes:
            # ميزة بلا تعريف مصادر معروف — لا نكذب بتغطية مصطنعة
            rows.append({
                "key": feature, "label_ar": ARABIC_NAMES.get(feature, feature),
                "kind": "count", "sources": [],
                "hospitals_with_value": 0, "hospitals_disabled": 0,
                "hospitals_missing": total, "hospitals_total": total,
                "coverage_pct": 0.0, "status": "unavailable",
            })
            continue
        with_value = disabled_count = missing = 0
        for hosp in hospitals:
            dis_ids = combined_disabled_map.get(hosp.id, set()) | auto_disabled_map.get(hosp.id, set())
            dis_codes = {ind_map[i] for i in dis_ids if i in ind_map}
            if any(c in dis_codes for c in codes):
                # مصدر معطّل يعني أن القيمة المشتقة لا تُشتق أصلاً
                disabled_count += 1
                continue
            vals = values_by_hosp.get(hosp.id, {})
            if feature == "cs_rate":
                den = vals.get("2")
                derivable = vals.get("5") is not None and den is not None and den > 0
            elif feature == "adolescent":
                derivable = ("2.c" in vals) or ("2.d" in vals)
            else:
                derivable = codes[0] in vals
            if derivable:
                with_value += 1
            else:
                missing += 1
        pct = round(100.0 * with_value / total, 1) if total else 0.0
        if total == 0 or with_value == 0:
            status = "unavailable"
        elif with_value == total:
            status = "available"
        else:
            status = "partial"
        rows.append({
            "key": feature,
            "label_ar": ARABIC_NAMES.get(feature, feature),
            "kind": FEATURE_KINDS.get(feature, "count"),
            "sources": list(codes),
            "hospitals_with_value": with_value,
            "hospitals_disabled": disabled_count,
            "hospitals_missing": missing,
            "hospitals_total": total,
            "coverage_pct": pct,
            "status": status,
        })
    return {
        "month": month,
        "hospitals_total": total,
        "indicators": rows,
        "note": (
            "التحليل الذكي يعتمد على هذه الميزات المشتقة من رموز البيانات التالية "
            "فقط — أي مؤشر خارجها لا يدخل نماذج الشذوذ/التجميع/الارتباط. "
            "المستشفى بلا قيمة مشتقة هذا الشهر يظهر «ناقص» لا صفراً."
        ),
    }


def _registry_inactive_codes(session: Session) -> set:
    """Registry codes deactivated on the Indicators screen (is_active=False)
    — currently computed, cheap, and always fresh so a toggle applies on the
    next request without cache invalidation plumbing. Empty on any registry
    hiccup for pre-seed fallback behavior."""
    try:
        from app.engine.indicator_service import inactive_codes
        return inactive_codes(session)
    except Exception:
        return set()


def _load_hospital_data(
    session: Session, month: str, hospital_ids: list[int] | None = None,
) -> Dict[str, Any]:
    """Bulk-load hospital data for a month — 4 queries total instead of N*2."""
    from app.models import Hospital, IndicatorValue, Indicator
    from app.engine.smart.indicator_forecast import indicator_rate_from_values

    hospitals_query = session.query(Hospital).filter(Hospital.is_active)
    if hospital_ids is not None:
        if not hospital_ids:
            return {}
        hospitals_query = hospitals_query.filter(Hospital.id.in_(hospital_ids))
    hospitals = hospitals_query.all()
    if not hospitals:
        return {}

    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}

    # ── Bulk query 1: ALL indicator values for this month ──
    all_values = session.query(IndicatorValue).filter(
        IndicatorValue.month == month,
    ).all()
    values_by_hosp = {}
    for iv in all_values:
        values_by_hosp.setdefault(iv.hospital_id, []).append(iv)

    # ── Disabled maps (manual + default + auto-null), shared helper ──
    combined_disabled_map, auto_disabled_map = _disabled_maps(
        session, month, hospitals, indicators, all_values
    )

    all_data = {}
    for hosp in hospitals:
        hid = hosp.id
        manually_disabled = combined_disabled_map.get(hid, set())
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

        derived = {}
        # cs_rate is a seeded registry indicator; when it is deactivated on
        # the Indicators screen its smart-analytics features must not be
        # recomputed (historical data stays untouched).
        _inactive = _registry_inactive_codes(session)
        cs_rate = None if "cs_rate" in _inactive else \
            indicator_rate_from_values("cs_rate", indicator_values)
        if cs_rate is not None:
            derived["cs_rate"] = cs_rate
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
