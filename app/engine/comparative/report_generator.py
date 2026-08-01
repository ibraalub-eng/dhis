import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
from app.engine.comparative.report_cache import get_stored_report, store_report
from app.plugins.ai.providers import _call_api

logger = logging.getLogger(__name__)


def build_comprehensive_prompt(analytics, lang: str = "ar") -> str:
    """بناء Prompt شامل حسب اللغة"""
    if lang == "en":
        return _build_english_prompt(analytics)
    return _build_arabic_prompt(analytics)


def _build_arabic_prompt(analytics) -> str:
    """Prompt عربي"""
    
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    clustering = analytics.clustering
    correlations = analytics.correlations
    residuals = analytics.residuals or []
    stratified = analytics.stratified or []
    explanations = analytics.explanations or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions
    
    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    
    strong_correlations = correlations.strong_correlations if correlations else []
    
    anomaly_details = []
    for a in anomalies[:10]:
        anomaly_details.append({
            "hospital": a.hospital_name,
            "score": a.anomaly_score,
            "severity": a.severity,
            "governorate": a.governorate,
        })
    
    correlation_details = []
    for c in strong_correlations[:5]:
        correlation_details.append({
            "a": c.indicator_a,
            "b": c.indicator_b,
            "r": round(c.pearson_r, 3),
            "strength": c.strength,
        })
    
    residual_details = []
    for r in residuals[:10]:
        residual_details.append({
            "hospital": r.hospital_name,
            "indicator": r.indicator,
            "actual": round(r.actual_value, 2),
            "predicted": round(r.predicted_value, 2),
            "z_score": round(r.residual_z_score, 2),
        })
    
    stratified_details = []
    for s in stratified[:10]:
        stratified_details.append({
            "hospital": s.hospital_name,
            "indicator": s.indicator,
            "value": round(s.hospital_value, 2),
            "peer_mean": round(s.peer_group_mean, 2),
            "deviation_pct": round(s.deviation_pct, 2),
        })
    
    explanation_details = []
    for e in explanations[:5]:
        top_factors = []
        for f in e.top_factors[:3]:
            top_factors.append({
                "feature": f.feature,
                "shap_value": round(f.shap_value, 4),
                "direction": f.direction,
            })
        explanation_details.append({
            "hospital": e.hospital_name,
            "severity": e.severity,
            "top_factors": top_factors,
        })
    
    geo_details = {}
    if geo and geo.governorates:
        for g in geo.governorates:
            geo_details[g.governorate] = {
                "hospital_count": g.hospital_count,
                "avg_anomaly_score": round(g.avg_anomaly_score, 3),
                "outlier_count": g.outlier_count,
            }
    
    xgboost_details = {}
    if xgboost:
        xgboost_details = {
            "model_r2": round(xgboost.model_r2, 3),
            "model_mae": round(xgboost.model_mae, 3),
            "hospitals_trained": xgboost.hospitals_trained,
            "accuracy_note": xgboost.accuracy_note,
        }
    
    prompt = f"""
    أنت خبير في تحليل بيانات الصحة في قطاع غزة.
    
    قم بإنشاء تقرير ذكي شامل بالعربية يتضمن:
    
    === الملخص التنفيذي ===
    - حالة النظام: {kpi.month_status if kpi else "غير محدد"}
    - عدد المستشفيات الشاذة: {kpi.total_anomalies if kpi else 0}
    - عدد المستشفيات الحرجة: {critical_count}
    - عدد المستشفيات بحاجة لتنبيه: {warning_count}
    - العامل الأكثر تأثيراً: {kpi.top_contributing_factor if kpi else "غير محدد"}
    
    === تحليل المؤشرات ===
    تحليل جميع المؤشرات السريرية:
    - معدل القيصارية (cs_rate)
    - المضاعفات الخطيرة (smm_total)
    - الوفيات الأمومية (mat_deaths)
    - وفيات المولودين (nd)
    - الولادات الميتة (sb)
    - الولادات السابقة لأوانها (preterm)
    - نقص وزن الولادة (lbw)
    - إجمالي المواليد (total_births)
    - حالات الخطر العالي (high_risk)
    - الحالات المراهقة (adolescent)
    
    === تحليل الشذوذ ===
    المستشفيات غير الطبيعية:
    {anomaly_details}
    
    === التجميع ===
    تقسيم المستشفيات لمجموعات:
    - عدد المجموعات: {clustering.n_clusters if clustering else 0}
    - جودة التجميع: {clustering.silhouette_score if clustering else 0:.2f}
    
    === الارتباطات ===
    العلاقات بين المؤشرات:
    {correlation_details}
    
    === البواقي ===
    الانحراف عن التوقعات:
    {residual_details}
    
    === المقارنة الطبقية ===
    مقارنة كل مستشفى بنظيره:
    {stratified_details}
    
    === شرح SHAP ===
    العوامل المسؤولة عن الشذوذ:
    {explanation_details}
    
    === الخريطة الجغرافية ===
    التوزيع الجغرافي:
    {geo_details}
    
    === التنبؤات ===
    توقعات XGBoost:
    {xgboost_details}
    
    التقرير يجب أن يكون:
    - بالعربية الفصحى
    - سهل الفهم
    - يتضمن أرقام وأحصائيات
    - يتضمن توصيات إجرائية واضحة
    - يغطي جميع الجوانب أعلاه
    """
    return prompt


def _build_english_prompt(analytics) -> str:
    """Build comprehensive prompt in English"""
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    clustering = analytics.clustering
    correlations = analytics.correlations
    residuals = analytics.residuals or []
    stratified = analytics.stratified or []
    explanations = analytics.explanations or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    strong_correlations = correlations.strong_correlations if correlations else []

    anomaly_details = []
    for a in anomalies[:10]:
        anomaly_details.append({
            "hospital": a.hospital_name,
            "score": a.anomaly_score,
            "severity": a.severity,
            "governorate": a.governorate,
        })

    residual_details = []
    for r in residuals[:10]:
        residual_details.append({
            "hospital": r.hospital_name,
            "indicator": r.indicator,
            "actual": round(r.actual_value, 2),
            "predicted": round(r.predicted_value, 2),
            "z_score": round(r.residual_z_score, 2),
        })

    stratified_details = []
    for s in stratified[:10]:
        stratified_details.append({
            "hospital": s.hospital_name,
            "indicator": s.indicator,
            "value": round(s.hospital_value, 2),
            "peer_mean": round(s.peer_group_mean, 2),
            "deviation_pct": round(s.deviation_pct, 2),
        })

    explanation_details = []
    for e in explanations[:5]:
        top_factors = []
        for f in e.top_factors[:3]:
            top_factors.append({
                "feature": f.feature,
                "shap_value": round(f.shap_value, 4),
                "direction": f.direction,
            })
        explanation_details.append({
            "hospital": e.hospital_name,
            "severity": e.severity,
            "top_factors": top_factors,
        })

    geo_details = {}
    if geo and geo.governorates:
        for g in geo.governorates:
            geo_details[g.governorate] = {
                "hospital_count": g.hospital_count,
                "avg_anomaly_score": round(g.avg_anomaly_score, 3),
                "outlier_count": g.outlier_count,
            }

    xgboost_details = {}
    if xgboost:
        xgboost_details = {
            "model_r2": round(xgboost.model_r2, 3),
            "model_mae": round(xgboost.model_mae, 3),
            "hospitals_trained": xgboost.hospitals_trained,
        }

    prompt = f"""
    You are a health data analysis expert for Gaza Strip hospitals.

    Generate a comprehensive smart report in English covering:

    === Executive Summary ===
    - System status: {kpi.month_status if kpi else "N/A"}
    - Anomalous hospitals: {kpi.total_anomalies if kpi else 0}
    - Critical hospitals: {critical_count}
    - Hospitals needing attention: {warning_count}
    - Top contributing factor: {kpi.top_contributing_factor if kpi else "N/A"}

    === Indicator Analysis ===
    All clinical indicators:
    - Caesarean rate (cs_rate)
    - Severe maternal morbidity (smm_total)
    - Maternal deaths (mat_deaths)
    - Neonatal deaths (nd)
    - Stillbirths (sb)
    - Preterm births (preterm)
    - Low birth weight (lbw)
    - Total births (total_births)
    - High risk cases (high_risk)
    - Adolescent cases (adolescent)

    === Anomaly Analysis ===
    Abnormal hospitals:
    {anomaly_details}

    === Clustering ===
    Hospital groups:
    - Number of clusters: {clustering.n_clusters if clustering else 0}
    - Clustering quality: {clustering.silhouette_score if clustering else 0:.2f}

    === Correlations ===
    Indicator relationships:
    {strong_correlations[:5]}

    === Residuals ===
    Deviation from predictions:
    {residual_details}

    === Stratified Comparison ===
    Hospital vs peer comparison:
    {stratified_details}

    === SHAP Explanations ===
    Factors responsible for anomalies:
    {explanation_details}

    === Geographic Map ===
    Geographic distribution:
    {geo_details}

    === Predictions ===
    XGBoost forecasts:
    {xgboost_details}

    The report MUST:
    - Be in English
    - Be easy to understand
    - Include numbers and statistics
    - Include actionable recommendations
    - Cover all sections above
    """
    return prompt


def generate_comprehensive_report(session: Session, month: str, lang: str = "ar", use_cache: bool = True) -> Dict[str, Any]:
    """توليد تقرير ذكي شامل حسب اللغة مع تخزين للتقرير المولّد بالذكاء الاصطناعي"""

    if use_cache:
        cached = get_stored_report(session, month, lang)
        if cached:
            return cached

    analytics = run_smart_analytics(session, month)
    
    prompt = build_comprehensive_prompt(analytics, lang)
    
    report_text = None
    try:
        report_text = _call_api(prompt)
    except Exception:
        logger.error("AI report generation failed; using local fallback", exc_info=True)
    report_source = "ai" if report_text else "local"
    if not report_text:
        report_text = _build_local_report(analytics, lang)
    
    def _to_dict(obj):
        if obj is None:
            return {}
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return obj
    
    def _to_list(objs):
        if objs is None:
            return []
        return [_to_dict(o) for o in objs]
    
    result = {
        "month": month,
        "report": report_text,
        "report_source": report_source,
        "data": {
            "kpi": _to_dict(analytics.kpi),
            "anomalies": _to_list(analytics.anomalies),
            "clustering": _to_dict(analytics.clustering),
            "correlations": _to_dict(analytics.correlations),
            "residuals": _to_list(analytics.residuals),
            "stratified": _to_list(analytics.stratified),
            "explanations": _to_list(analytics.explanations),
            "geo": _to_dict(analytics.geo),
            "xgboost": _to_dict(analytics.xgboost_predictions),
        }
    }

    if report_source == "ai":
        store_report(session, month, lang, result)

    return result


def _build_local_report(analytics, lang: str = "ar") -> str:
    """بناء تقرير محلي من بيانات التحليلات عند فشل الذكاء الاصطناعي"""
    if lang == "en":
        return _build_local_report_english(analytics)
    return _build_local_report_arabic(analytics)


def _build_local_report_arabic(analytics) -> str:
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    clustering = analytics.clustering
    correlations = analytics.correlations
    residuals = analytics.residuals or []
    stratified = analytics.stratified or []
    explanations = analytics.explanations or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    strong_correlations = correlations.strong_correlations if correlations else []

    lines = []

    lines.append("=== الملخص التنفيذي ===")
    lines.append(f"- حالة النظام: {kpi.month_status if kpi else 'غير محدد'}")
    lines.append(f"- عدد المستشفيات الشاذة: {kpi.total_anomalies if kpi else 0}")
    lines.append(f"- عدد المستشفيات الحرجة: {critical_count}")
    lines.append(f"- عدد المستشفيات بحاجة لتنبيه: {warning_count}")
    lines.append(f"- عدد المحافظات المتأثرة: {kpi.affected_governorates if kpi else 0}")
    lines.append(f"- العامل الأكثر تأثيراً: {kpi.top_contributing_factor if kpi else 'غير محدد'}")
    lines.append("")

    lines.append("=== تحليل المؤشرات ===")
    lines.append("تم تحليل المؤشرات السريرية التالية: معدل القيصارية (cs_rate)، المضاعفات الخطيرة (smm_total)، "
                 "الوفيات الأمومية (mat_deaths)، وفيات المولودين (nd)، الولادات الميتة (sb)، الولادات السابقة "
                 "لأوانها (preterm)، نقص وزن الولادة (lbw)، إجمالي المواليد (total_births)، حالات الخطر العالي "
                 "(high_risk)، والحالات المراهقة (adolescent).")
    if strong_correlations:
        lines.append("أبرز العلاقات بين المؤشرات:")
        for c in strong_correlations[:5]:
            lines.append(f"- {c.indicator_a} ↔ {c.indicator_b}: معامل ارتباط {c.pearson_r:.3f} ({c.strength})")
    lines.append("")

    lines.append("=== تحليل الشذوذ ===")
    if anomalies:
        for a in anomalies[:10]:
            lines.append(f"- {a.hospital_name}: الدرجة {a.anomaly_score:.3f} | الشدة: {a.severity} | المحافظة: {a.governorate}")
    else:
        lines.append("- لا توجد شذوذات مكتشفة في هذا الشهر.")
    lines.append("")

    lines.append("=== التجميع ===")
    lines.append(f"- عدد المجموعات: {clustering.n_clusters if clustering else 0}")
    lines.append(f"- جودة التجميع (silhouette): {clustering.silhouette_score if clustering else 0:.2f}")
    if clustering and clustering.clusters:
        for c in clustering.clusters[:10]:
            lines.append(f"- {c.hospital_name}: مجموعة {c.cluster_id}")
    if clustering and clustering.noise_hospitals:
        lines.append(f"- مستشفيات غير مصنفة: {', '.join(clustering.noise_hospitals[:5])}")
    lines.append("")

    lines.append("=== الارتباطات ===")
    if strong_correlations:
        for c in strong_correlations[:5]:
            lines.append(f"- {c.indicator_a} ↔ {c.indicator_b}: r={c.pearson_r:.3f} | القوة: {c.strength}")
    else:
        lines.append("- لا توجد ارتباطات قوية ملحوظة بين المؤشرات.")
    lines.append("")

    lines.append("=== البواقي ===")
    if residuals:
        for r in residuals[:10]:
            lines.append(f"- {r.hospital_name} | {r.indicator}: فعلي {r.actual_value:.2f} مقابل متوقع "
                         f"{r.predicted_value:.2f} | z={r.residual_z_score:.2f}")
    else:
        lines.append("- لا توجد انحرافات ملحوظة عن التوقعات.")
    lines.append("")

    lines.append("=== المقارنة الطبقية ===")
    if stratified:
        for s in stratified[:10]:
            lines.append(f"- {s.hospital_name} | {s.indicator}: {s.hospital_value:.2f} مقابل متوسط النظير "
                         f"{s.peer_group_mean:.2f} | الانحراف {s.deviation_pct:.2f}%")
    else:
        lines.append("- لا توجد مقارنات طبقية متاحة.")
    lines.append("")

    lines.append("=== شرح SHAP ===")
    if explanations:
        for e in explanations[:5]:
            factors = "، ".join(f"{f.feature} ({f.shap_value:.3f})" for f in e.top_factors[:3])
            lines.append(f"- {e.hospital_name} ({e.severity}): {factors}")
    else:
        lines.append("- لا توجد تفسيرات SHAP متاحة.")
    lines.append("")

    lines.append("=== الخريطة الجغرافية ===")
    if geo and geo.governorates:
        for g in geo.governorates:
            lines.append(f"- {g.governorate}: {g.hospital_count} مستشفى | متوسط الدرجة {g.avg_anomaly_score:.3f} "
                         f"| عدد الشاذ {g.outlier_count}")
    else:
        lines.append("- لا توجد بيانات جغرافية متاحة.")
    lines.append("")

    lines.append("=== التنبؤات ===")
    if xgboost and xgboost.predictions:
        for p in xgboost.predictions[:5]:
            lines.append(f"- {p.hospital_name}: الحالي {p.current_score:.3f} → المتوقع {p.predicted_next_score:.3f} "
                         f"| الحالة المتوقعة: {p.predicted_severity}")
    else:
        lines.append("- لا توجد تنبؤات متاحة.")
    lines.append("")

    lines.append("=== التوصيات ===")
    recommendations = _build_recommendations(
        kpi, anomalies, strong_correlations, clustering, xgboost, lang="ar"
    )
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")

    return "\n".join(lines)


def _build_local_report_english(analytics) -> str:
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    clustering = analytics.clustering
    correlations = analytics.correlations
    residuals = analytics.residuals or []
    stratified = analytics.stratified or []
    explanations = analytics.explanations or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    strong_correlations = correlations.strong_correlations if correlations else []

    lines = []

    lines.append("=== Executive Summary ===")
    lines.append(f"- System status: {kpi.month_status if kpi else 'N/A'}")
    lines.append(f"- Anomalous hospitals: {kpi.total_anomalies if kpi else 0}")
    lines.append(f"- Critical hospitals: {critical_count}")
    lines.append(f"- Hospitals needing attention: {warning_count}")
    lines.append(f"- Affected governorates: {kpi.affected_governorates if kpi else 0}")
    lines.append(f"- Top contributing factor: {kpi.top_contributing_factor if kpi else 'N/A'}")
    lines.append("")

    lines.append("=== Indicator Analysis ===")
    lines.append("The following clinical indicators were analyzed: Caesarean rate (cs_rate), severe maternal morbidity "
                 "(smm_total), maternal deaths (mat_deaths), neonatal deaths (nd), stillbirths (sb), preterm births "
                 "(preterm), low birth weight (lbw), total births (total_births), high risk cases (high_risk), and "
                 "adolescent cases (adolescent).")
    if strong_correlations:
        lines.append("Key indicator relationships:")
        for c in strong_correlations[:5]:
            lines.append(f"- {c.indicator_a} ↔ {c.indicator_b}: correlation {c.pearson_r:.3f} ({c.strength})")
    lines.append("")

    lines.append("=== Anomaly Analysis ===")
    if anomalies:
        for a in anomalies[:10]:
            lines.append(f"- {a.hospital_name}: score {a.anomaly_score:.3f} | severity: {a.severity} | governorate: {a.governorate}")
    else:
        lines.append("- No anomalies detected this month.")
    lines.append("")

    lines.append("=== Clustering ===")
    lines.append(f"- Number of clusters: {clustering.n_clusters if clustering else 0}")
    lines.append(f"- Clustering quality (silhouette): {clustering.silhouette_score if clustering else 0:.2f}")
    if clustering and clustering.clusters:
        for c in clustering.clusters[:10]:
            lines.append(f"- {c.hospital_name}: cluster {c.cluster_id}")
    if clustering and clustering.noise_hospitals:
        lines.append(f"- Unclustered hospitals: {', '.join(clustering.noise_hospitals[:5])}")
    lines.append("")

    lines.append("=== Correlations ===")
    if strong_correlations:
        for c in strong_correlations[:5]:
            lines.append(f"- {c.indicator_a} ↔ {c.indicator_b}: r={c.pearson_r:.3f} | strength: {c.strength}")
    else:
        lines.append("- No strong correlations between indicators were found.")
    lines.append("")

    lines.append("=== Residuals ===")
    if residuals:
        for r in residuals[:10]:
            lines.append(f"- {r.hospital_name} | {r.indicator}: actual {r.actual_value:.2f} vs predicted "
                         f"{r.predicted_value:.2f} | z={r.residual_z_score:.2f}")
    else:
        lines.append("- No notable deviations from predictions.")
    lines.append("")

    lines.append("=== Stratified Comparison ===")
    if stratified:
        for s in stratified[:10]:
            lines.append(f"- {s.hospital_name} | {s.indicator}: {s.hospital_value:.2f} vs peer mean "
                         f"{s.peer_group_mean:.2f} | deviation {s.deviation_pct:.2f}%")
    else:
        lines.append("- No stratified comparisons available.")
    lines.append("")

    lines.append("=== SHAP Explanations ===")
    if explanations:
        for e in explanations[:5]:
            factors = ", ".join(f"{f.feature} ({f.shap_value:.3f})" for f in e.top_factors[:3])
            lines.append(f"- {e.hospital_name} ({e.severity}): {factors}")
    else:
        lines.append("- No SHAP explanations available.")
    lines.append("")

    lines.append("=== Geographic Map ===")
    if geo and geo.governorates:
        for g in geo.governorates:
            lines.append(f"- {g.governorate}: {g.hospital_count} hospitals | avg score {g.avg_anomaly_score:.3f} "
                         f"| outliers {g.outlier_count}")
    else:
        lines.append("- No geographic data available.")
    lines.append("")

    lines.append("=== Predictions ===")
    if xgboost and xgboost.predictions:
        for p in xgboost.predictions[:5]:
            lines.append(f"- {p.hospital_name}: current {p.current_score:.3f} → predicted {p.predicted_next_score:.3f} "
                         f"| predicted severity: {p.predicted_severity}")
    else:
        lines.append("- No predictions available.")
    lines.append("")

    lines.append("=== Recommendations ===")
    recommendations = _build_recommendations(
        kpi, anomalies, strong_correlations, clustering, xgboost, lang="en"
    )
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")

    return "\n".join(lines)


def _build_recommendations(kpi, anomalies, strong_correlations, clustering, xgboost, lang: str = "ar"):
    """بناء توصيات إجرائية من بيانات التحليلات"""
    recommendations = []
    critical_count = sum(1 for a in anomalies if a.severity == "critical")

    if kpi and kpi.total_anomalies > 0:
        if lang == "ar":
            recommendations.append(
                f"يوجد {kpi.total_anomalies} مستشفى شاذة. يُوصى بالتحقق من بيانات المستشفيات "
                f"الحرجة وتصحيح أخطاء الإدخال قبل اعتماد التقارير."
            )
        else:
            recommendations.append(
                f"{kpi.total_anomalies} anomalous hospitals were detected. Verify critical hospital data "
                f"and correct entry errors before approving reports."
            )
    if critical_count > 0:
        if lang == "ar":
            recommendations.append(
                f"يوجد {critical_count} مستشفى بحالة حرجة. يُوصى بمراجعة فورية واتخاذ إجراءات تصحيحية عاجلة."
            )
        else:
            recommendations.append(
                f"{critical_count} hospitals are in critical condition. Immediate review and corrective "
                f"actions are recommended."
            )
    if strong_correlations:
        if lang == "ar":
            recommendations.append(
                "توجد ارتباطات قوية بين المؤشرات. يُوصى بمراقبة المؤشرات المترابطة للكشف المبكر عن التغيرات."
            )
        else:
            recommendations.append(
                "Strong correlations between indicators were found. Monitor correlated indicators "
                "for early detection of changes."
            )
    if clustering and clustering.noise_hospitals:
        if lang == "ar":
            recommendations.append(
                f"يوجد {len(clustering.noise_hospitals)} مستشفى غير مصنف في التجميع. يُوصى بمراجعة بياناتها."
            )
        else:
            recommendations.append(
                f"{len(clustering.noise_hospitals)} hospitals were not assigned to any cluster. "
                f"Review their data."
            )
    if xgboost and xgboost.predictions:
        high_risk = [p for p in xgboost.predictions if p.predicted_severity in ("critical", "high")]
        if high_risk:
            if lang == "ar":
                recommendations.append(
                    f"{len(high_risk)} مستشفى متوقع أن ترتفع درجة الخطورة لديها. يُوصى بوضع خطة وقائية استباقية."
                )
            else:
                recommendations.append(
                    f"{len(high_risk)} hospitals are predicted to escalate in severity. "
                    f"Develop a proactive prevention plan."
                )
    if not recommendations:
        if lang == "ar":
            recommendations.append("لا توجد شذوذات حرجة. يُوصى بمواصلة المراقبة الدورية لجودة البيانات.")
        else:
            recommendations.append("No critical anomalies found. Continue routine data quality monitoring.")

    return recommendations
