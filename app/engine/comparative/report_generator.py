from typing import Dict, Any
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
from app.plugins.ai.providers import _call_gemini_api


def build_comprehensive_prompt(analytics) -> str:
    """بناء Prompt شامل يتضمن جميع التحليلات"""
    
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


def generate_comprehensive_report(session: Session, month: str) -> Dict[str, Any]:
    """توليد تقرير ذكي شامل"""
    
    analytics = run_smart_analytics(session, month)
    
    prompt = build_comprehensive_prompt(analytics)
    
    report_text = _call_gemini_api(prompt)
    
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
    
    return {
        "month": month,
        "report": report_text or "خطأ في توليد التقرير",
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
