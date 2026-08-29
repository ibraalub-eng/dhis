import logging
from typing import Dict, Any, List, Optional
import numpy as np
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics, _load_hospital_data
from app.engine.smart.anomaly import FEATURE_KEYS
from app.engine.comparative.report_cache import get_stored_report, store_report
from app.plugins.ai.providers import _call_api
from app.models import IndicatorValue

logger = logging.getLogger(__name__)

# --- أقسام التقرير الشامل (الترتيب النهائي) ---
SECTIONS: List[str] = [
    "exec_summary",        # الملخص التنفيذي + الحالة العامة
    "key_messages",        # أهم الرسائل التنفيذية
    "priority_hospitals",  # المستشفيات ذات الأولوية
    "geo_risk",            # التوزيع الجغرافي للمخاطر
    "early_warnings",      # إشارات الإنذار المبكر
    "current_trends",      # الاتجاهات الشهرية
    "forecast",            # التنبؤ بالمخاطر المستقبلية
    "clinical_relations",  # تحليل المؤشرات والعلاقات
    "composite_patterns",  # الأنماط المركبة
    "anomaly_intel",       # تحليل الحالات الشاذة
    "top_deviations",      # أكبر الانحرافات
    "regional_intel",      # الاستخبارات الإقليمية
    "deterioration",       # تدهور مستمر
    "data_quality",        # تنبيهات جودة البيانات
    "recommendations",     # توصيات + مصفوفة الأولويات
    "conclusion",          # الخلاصة التنفيذية
    "appendix",            # الملحق الفني
]

# أسماء المؤشرات المشتقة (مطابقة لواجهة المستخدم)
INDICATOR_NAMES_AR = {
    "cs_rate": "معدل القيصارية",
    "smm_total": "المضاعفات الخطيرة",
    "mat_deaths": "الوفيات الأمومية",
    "nd": "وفيات المولودين",
    "sb": "الولادات الميتة",
    "preterm": "الولادات السابقة لأوانها",
    "lbw": "نقص وزن الولادة",
    "total_births": "إجمالي المواليد",
    "high_risk": "حالات الخطر العالي",
    "adolescent": "الحالات المراهقة",
}
INDICATOR_NAMES_EN = {
    "cs_rate": "Caesarean rate",
    "smm_total": "Severe maternal morbidity",
    "mat_deaths": "Maternal deaths",
    "nd": "Neonatal deaths",
    "sb": "Stillbirths",
    "preterm": "Preterm births",
    "lbw": "Low birth weight",
    "total_births": "Total births",
    "high_risk": "High risk cases",
    "adolescent": "Adolescent cases",
}
INDICATOR_UNITS = {"cs_rate": "%"}
# معيار مرجعي إرشادي: المعدل السكاني للقيصارية (منظمة الصحة العالمية 10-15%)
BENCHMARKS = {"cs_rate": 15.0}


def _get_previous_month(session: Session, month: str) -> Optional[str]:
    """الشهر السابق المتوفر في قاعدة البيانات قبل الشهر المحدد."""
    rows = session.query(IndicatorValue.month).distinct().order_by(IndicatorValue.month).all()
    months = sorted(r[0] for r in rows)
    if month in months:
        idx = months.index(month)
        if idx > 0:
            return months[idx - 1]
    return None


def _load_indicator_stats(session: Session, month: str, prev_month: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """إحصاءات فعلية لكل مؤشر (متوسط/أدنى/أعلى/انحراف معياري) مع مقارنة بمتوسط الشهر السابق."""
    current = _load_hospital_data(session, month)
    prev = _load_hospital_data(session, prev_month) if prev_month else {}
    stats: Dict[str, Dict[str, float]] = {}
    for code in FEATURE_KEYS:
        vals = [h["values"].get(code) for h in current.values()]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        entry = {
            "count": len(vals),
            "mean": mean,
            "min": min(vals),
            "max": max(vals),
            "std": (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5,
        }
        if prev:
            prev_vals = [h["values"].get(code) for h in prev.values()]
            prev_vals = [v for v in prev_vals if v is not None]
            if prev_vals:
                prev_mean = sum(prev_vals) / len(prev_vals)
                entry["prev_mean"] = prev_mean
                entry["mean_delta"] = mean - prev_mean
                if prev_mean != 0:
                    entry["mean_delta_pct"] = (mean - prev_mean) / prev_mean * 100
        stats[code] = entry
    return stats


def _indicator_stats_lines_ar(stats) -> List[str]:
    lines = []
    for code, s in stats.items():
        name = INDICATOR_NAMES_AR.get(code, code)
        unit = INDICATOR_UNITS.get(code, "")
        line = f"- {name}: المتوسط {s['mean']:.2f}{unit} (الأدنى {s['min']:.2f}{unit} – الأعلى {s['max']:.2f}{unit}) من {s['count']} مستشفى"
        if "prev_mean" in s:
            line += f" | الشهر السابق {s['prev_mean']:.2f}{unit} (التغير {s['mean_delta']:+.2f}{unit})"
        bench = BENCHMARKS.get(code)
        if bench and s["mean"] > bench:
            line += f" | ⚠ فوق المعيار المرجعي {bench:.1f}{unit}"
        lines.append(line)
    return lines


def _indicator_stats_lines_en(stats) -> List[str]:
    lines = []
    for code, s in stats.items():
        name = INDICATOR_NAMES_EN.get(code, code)
        unit = INDICATOR_UNITS.get(code, "")
        line = f"- {name}: mean {s['mean']:.2f}{unit} (min {s['min']:.2f}{unit} – max {s['max']:.2f}{unit}) across {s['count']} hospitals"
        if "prev_mean" in s:
            line += f" | previous month {s['prev_mean']:.2f}{unit} (change {s['mean_delta']:+.2f}{unit})"
        bench = BENCHMARKS.get(code)
        if bench and s["mean"] > bench:
            line += f" | ⚠ above reference benchmark {bench:.1f}{unit}"
        lines.append(line)
    return lines


def _trend_lines_ar(prev_month: str, stats) -> List[str]:
    lines = [f"- مقارنة مع الشهر السابق: {prev_month}"]
    movers = [s for s in stats.values() if "mean_delta_pct" in s]
    if not movers:
        lines.append("- لا توجد بيانات من الشهر السابق لإجراء المقارنة.")
        return lines
    fastest = max(movers, key=lambda s: s["mean_delta_pct"])
    slowest = min(movers, key=lambda s: s["mean_delta_pct"])
    if fastest["mean_delta_pct"] > 0:
        fastest_code = next(c for c, s in stats.items() if s is fastest)
        lines.append(f"- أسرع مؤشر ارتفاعاً: {INDICATOR_NAMES_AR.get(fastest_code, fastest_code)} ({fastest['mean_delta_pct']:+.1f}%)")
    if slowest["mean_delta_pct"] < 0:
        slowest_code = next(c for c, s in stats.items() if s is slowest)
        lines.append(f"- أكبر انخفاض: {INDICATOR_NAMES_AR.get(slowest_code, slowest_code)} ({slowest['mean_delta_pct']:+.1f}%)")
    return lines


def _trend_lines_en(prev_month: str, stats) -> List[str]:
    lines = [f"- Compared with previous month: {prev_month}"]
    movers = [s for s in stats.values() if "mean_delta_pct" in s]
    if not movers:
        lines.append("- No previous-month data available for comparison.")
        return lines
    fastest = max(movers, key=lambda s: s["mean_delta_pct"])
    slowest = min(movers, key=lambda s: s["mean_delta_pct"])
    if fastest["mean_delta_pct"] > 0:
        fastest_code = next(c for c, s in stats.items() if s is fastest)
        lines.append(f"- Fastest rising indicator: {INDICATOR_NAMES_EN.get(fastest_code, fastest_code)} ({fastest['mean_delta_pct']:+.1f}%)")
    if slowest["mean_delta_pct"] < 0:
        slowest_code = next(c for c, s in stats.items() if s is slowest)
        lines.append(f"- Largest drop: {INDICATOR_NAMES_EN.get(slowest_code, slowest_code)} ({slowest['mean_delta_pct']:+.1f}%)")
    return lines


def _composite_patterns_lines_ar(patterns) -> List[str]:
    """سطور عربية للأنماط المركبة المتكررة (Apriori + Lift)."""
    if not patterns:
        return ["- لا توجد أنماط مركبة واضحة: لا تتكرر توليفات مؤشرات معاً أكثر من المتوقع."]
    lines = []
    for p in patterns[:5]:
        parts = []
        for i, ind in enumerate(p.indicators):
            up = (p.statuses or [])[i] != "lowered"
            verb = "ارتفاع" if up else "انخفاض"
            parts.append(f"{verb} {INDICATOR_NAMES_AR.get(ind, ind)}")
        lines.append(
            f"- نمط متكرر في {p.hospitals_count} مستشفى ({p.support * 100:.0f}%): "
            f"{' مع '.join(parts)} — قوة الارتباط (Lift) {p.lift:.2f}"
        )
    return lines


def _composite_patterns_lines_en(patterns) -> List[str]:
    """English lines for recurring composite indicator patterns."""
    if not patterns:
        return ["- No clear composite patterns: no indicator combinations co-occur more than expected."]
    lines = []
    for p in patterns[:5]:
        parts = []
        for i, ind in enumerate(p.indicators):
            up = (p.statuses or [])[i] != "lowered"
            verb = "Elevated" if up else "Low"
            parts.append(f"{verb} {INDICATOR_NAMES_EN.get(ind, ind)}")
        lines.append(
            f"- Recurring pattern in {p.hospitals_count} hospitals ({p.support * 100:.0f}%): "
            f"{' with '.join(parts)} — Lift {p.lift:.2f}"
        )
    return lines


def _regional_lines_ar(regional) -> List[str]:
    """سطور عربية لقسم الاستخبارات الإقليمية (محافظات × معايير × مخاطر)."""
    if not regional or not regional.get("governorates"):
        return ["- لا توجد بيانات كافية للتحليل الإقليمي على مستوى المحافظات."]
    lines = []
    risks = {r["governorate"]: r for r in (regional.get("risk_scores") or [])}
    for g in regional["governorates"]:
        nmr = g.get("rates", {}).get("nmr", {})
        mmr = g.get("rates", {}).get("mmr", {})
        sb = g.get("rates", {}).get("stillbirth_rate", {})
        cs = g.get("rates", {}).get("cs_rate", {})
        risk = risks.get(g["governorate"])
        bits = []
        bits.append(f"{g['governorate']}: {g.get('hospital_count')} مستشفى، {int(g.get('births') or 0):,} مولود")
        if nmr.get("value") is not None:
            dev = nmr.get("deviation_pct")
            dev_txt = f" ({dev:+.1f}% عن معيار الإقليم)" if dev is not None else ""
            bits.append(f"معدل وفيات المواليد {nmr['value']:.1f}/1000{dev_txt}")
        if mmr.get("value") is not None:
            bits.append(f"نسبة الوفيات الأمومية {mmr['value']:.1f}/100000")
        if sb.get("value") is not None:
            bits.append(f"الولادات الميتة {sb['value']:.1f}/1000")
        if cs.get("value") is not None:
            bits.append(f"القيصرية {cs['value']:.1f}%")
        if risk:
            conf = risk["confidence_label_ar"]
            warn = " ⚠ " + "؛ ".join(risk["warnings"]) if risk.get("warnings") else ""
            bits.append(f"خطر {risk['level_label_ar']} ({risk['risk_score']}/100، ثقة {conf}){warn}")
        lines.append("- " + " | ".join(bits))
    mort = regional.get("mortality") or []
    high = [m for m in mort if m.get("risk") == "high"]
    if high:
        lines.append(f"- محافظات ذات وفيات مرتفعة: " + "، ".join(m["governorate"] for m in high))
    oe = regional.get("observed_expected") or {}
    oe_high = [r for r in (oe.get("results") or []) if (r.get("oe_ratio") or 0) > 1.2]
    if oe_high:
        lines.append("- وفيات أعلى من المتوقع (O/E > 1.2): " +
                     "، ".join(f"{r['governorate']} ({r['oe_ratio']})" for r in oe_high))
    for t in (regional.get("trends") or [])[:3]:
        if t.get("summary_ar"):
            lines.append(f"- {t['summary_ar']}")
    return lines


def _regional_lines_en(regional) -> List[str]:
    """English lines for the regional intelligence section."""
    if not regional or not regional.get("governorates"):
        return ["- Insufficient data for governorate-level regional analysis."]
    lines = []
    risks = {r["governorate"]: r for r in (regional.get("risk_scores") or [])}
    for g in regional["governorates"]:
        nmr = g.get("rates", {}).get("nmr", {})
        mmr = g.get("rates", {}).get("mmr", {})
        sb = g.get("rates", {}).get("stillbirth_rate", {})
        cs = g.get("rates", {}).get("cs_rate", {})
        risk = risks.get(g["governorate"])
        bits = [f"{g['governorate']}: {g.get('hospital_count')} hospitals, {int(g.get('births') or 0):,} births"]
        if nmr.get("value") is not None:
            dev = nmr.get("deviation_pct")
            dev_txt = f" ({dev:+.1f}% vs regional benchmark)" if dev is not None else ""
            bits.append(f"NMR {nmr['value']:.1f}/1000{dev_txt}")
        if mmr.get("value") is not None:
            bits.append(f"MMR {mmr['value']:.1f}/100000")
        if sb.get("value") is not None:
            bits.append(f"stillbirth {sb['value']:.1f}/1000")
        if cs.get("value") is not None:
            bits.append(f"C-section {cs['value']:.1f}%")
        if risk:
            warn = " ⚠ " + "; ".join(risk["warnings"]) if risk.get("warnings") else ""
            bits.append(f"risk {risk['level_label_en']} ({risk['risk_score']}/100, {risk['confidence_label_en']}){warn}")
        lines.append("- " + " | ".join(bits))
    mort = regional.get("mortality") or []
    high = [m for m in mort if m.get("risk") == "high"]
    if high:
        lines.append("- High-mortality governorates: " + ", ".join(m["governorate"] for m in high))
    oe = regional.get("observed_expected") or {}
    oe_high = [r for r in (oe.get("results") or []) if (r.get("oe_ratio") or 0) > 1.2]
    if oe_high:
        lines.append("- Deaths above expectation (O/E > 1.2): " +
                     ", ".join(f"{r['governorate']} ({r['oe_ratio']})" for r in oe_high))
    for t in (regional.get("trends") or [])[:3]:
        if t.get("summary_en"):
            lines.append(f"- {t['summary_en']}")
    return lines


def build_comprehensive_prompt(analytics, lang: str = "ar", indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
    """بناء Prompt شامل حسب اللغة مع إحصاءات المؤشرات الفعلية والاتجاهات الشهرية"""
    if lang == "en":
        return _build_english_prompt(analytics, indicator_stats, prev_month, regional)
    return _build_arabic_prompt(analytics, indicator_stats, prev_month, regional)


def _build_arabic_prompt(analytics, indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
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

    indicator_stats_text = "لا توجد بيانات كافية لعرض إحصاءات المؤشرات."
    trends_text = "- لا يوجد شهر سابق متوفر للمقارنة."
    composite_patterns_text = "\n".join(_composite_patterns_lines_ar(analytics.patterns))
    regional_text = "\n".join(_regional_lines_ar(regional))
    if indicator_stats:
        indicator_stats_text = "\n".join(_indicator_stats_lines_ar(indicator_stats))
        if prev_month:
            trends_text = "\n".join(_trend_lines_ar(prev_month, indicator_stats))
    
    prompt = f"""
    أنت خبير في تحليل بيانات الصحة في قطاع غزة.
    
    اكتب التقرير لصانع القرار (مدير قطاع صحي)، لا لعالم بيانات: ركّز على
    «ماذا يحدث، وأين نتدخل أولاً، وما العمل المطلوب» بدل سرد الأرقام الخام.
    لاحظ أن قسم «=== قرارات تنفيذية ===» يُدرج تلقائياً قبل نصك بحسابات
    حقيقية — لا تكرره بنفس العنوان، بل عمّق التحليل في الأقسام التالية.
    
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
    
    === بيانات المؤشرات الفعلية ===
    {indicator_stats_text}

    === الاتجاهات الشهرية ===
    {trends_text}

    === الأنماط المركبة للمؤشرات ===
    توليفات المؤشرات المتكررة معاً في عدة مستشفيات:
    {composite_patterns_text}

    === الاستخبارات الإقليمية ===
    تحليل على مستوى المحافظة (معدلات، انحراف عن معيار الإقليم، مخاطر، O/E، اتجاهات):
    {regional_text}

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


def _build_english_prompt(analytics, indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
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

    correlation_details = []
    for c in strong_correlations[:5]:
        correlation_details.append({
            "a": c.indicator_a,
            "b": c.indicator_b,
            "r": round(c.pearson_r, 3),
            "strength": c.strength,
        })

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

    indicator_stats_text = "Insufficient data to show indicator statistics."
    trends_text = "- No previous month available for comparison."
    composite_patterns_text = "\n".join(_composite_patterns_lines_en(analytics.patterns))
    regional_text = "\n".join(_regional_lines_en(regional))
    if indicator_stats:
        indicator_stats_text = "\n".join(_indicator_stats_lines_en(indicator_stats))
        if prev_month:
            trends_text = "\n".join(_trend_lines_en(prev_month, indicator_stats))

    prompt = f"""
    You are a health data analysis expert for Gaza Strip hospitals.

    Write for a decision-maker (health sector director), not a data scientist:
    focus on \"what is happening, where to intervene first, and what action is
    needed\" instead of listing raw numbers. Note that an
    \"=== Executive Decisions ===\" section is inserted automatically before
    your text with real computed figures — do not repeat that heading, but go
    deeper in the sections below.

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

    === Actual Indicator Statistics ===
    {indicator_stats_text}

    === Monthly Trends ===
    {trends_text}

    === Composite Indicator Patterns ===
    Indicator combinations recurring together across hospitals:
    {composite_patterns_text}

    === Regional Health Intelligence ===
    Governorate-level analysis (rates, benchmark deviation, risks, O/E, trends):
    {regional_text}

    === Anomaly Analysis ===
    Abnormal hospitals:
    {anomaly_details}

    === Clustering ===
    Hospital groups:
    - Number of clusters: {clustering.n_clusters if clustering else 0}
    - Clustering quality: {clustering.silhouette_score if clustering else 0:.2f}

    === Correlations ===
    Indicator relationships:
    {correlation_details}

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


def _parse_sections(ai_text: str, keys: List[str]) -> Dict[str, str]:
    """تقسيم نص الذكاء الاصطناعي إلى أقسام بحسب ترويسات `## key`."""
    result: Dict[str, str] = {}
    # TODO: filled in Task 3
    return result


def _build_local_sections(analytics, lang: str = "ar", indicator_stats=None,
                          prev_month: Optional[str] = None, regional=None,
                          decision=None, forecast=None) -> Dict[str, str]:
    """توليد سرد لكل قسم بشكل حتمي (عند عدم توفر AI)."""
    # TODO: filled in Task 2
    return {key: "" for key in SECTIONS}


def generate_comprehensive_report(session: Session, month: str, lang: str = "ar", use_cache: bool = True) -> Dict[str, Any]:
    """توليد تقرير ذكي شامل حسب اللغة مع تخزين للتقرير المولّد بالذكاء الاصطناعي"""

    if use_cache:
        cached = get_stored_report(session, month, lang)
        if cached:
            return cached

    analytics = run_smart_analytics(session, month)

    prev_month = _get_previous_month(session, month)
    indicator_stats = _load_indicator_stats(session, month, prev_month)

    # التحليل الإقليمي: يُعيد استخدام الكاش الشهري (نفس مفتاح واجهة /regional)
    # حتى لا يُعاد تجميع المحافظات مع كل توليد تقرير.
    from app.cache import cache
    from app.engine.smart.regional import run_regional_analysis
    regional = cache.get(f"regional_{month}_6")
    if regional is None:
        regional = run_regional_analysis(session, month)
        cache.set(f"regional_{month}_6", regional, ttl=300)

    prompt = build_comprehensive_prompt(
        analytics, lang, indicator_stats=indicator_stats, prev_month=prev_month,
        regional=regional,
    )

    decision_brief = _build_decision_brief(
        analytics, indicator_stats=indicator_stats, prev_month=prev_month, lang=lang,
        regional=regional,
    )

    report_text = None
    try:
        report_text = _call_api(prompt)
    except Exception:
        logger.error("AI report generation failed; using local fallback", exc_info=True)
    report_source = "ai" if report_text else "local"
    if not report_text:
        report_text = _build_local_report(
            analytics, lang, indicator_stats=indicator_stats, prev_month=prev_month,
            regional=regional,
        )
    # قسم القرارات التنفيذية دائماً في مقدمة التقرير (بيانات حقيقية محسوبة لا
    # تخمين AI) — مع إبقاء الموجز في data للوحة القرارات في الواجهة.
    report_text = "\n".join(_decision_brief_lines(decision_brief, lang)) + "\n\n" + report_text

    # توقعات الشهر القادم: مؤشرات قيادية صاعدة بأوزانها المكتشفة والنتائج المتوقعة
    # (قسم محسوب من العلاقات المتأخرة — يظهر في النص المُصدَّر بغض النظر عن AI).
    forecast_brief = _build_forecast_brief(session, month, lang)
    forecast_lines = _forecast_brief_lines(forecast_brief, lang)
    if forecast_lines:
        report_text = "\n".join(forecast_lines) + "\n\n" + report_text
    
    def _to_dict(obj):
        # تحويل عميق مع تنظيف قيم numpy حتى يسلسل JSON بسلامة
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_to_dict(v) for v in obj]
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if hasattr(obj, "__dict__"):
            return {k: _to_dict(v) for k, v in obj.__dict__.items()}
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
            "hospitals_count": analytics.hospitals_count,
            "kpi": _to_dict(analytics.kpi),
            "anomalies": _to_list(analytics.anomalies),
            "clustering": _to_dict(analytics.clustering),
            "correlations": _to_dict(analytics.correlations),
            "residuals": _to_list(analytics.residuals),
            "stratified": _to_list(analytics.stratified),
            "explanations": _to_list(analytics.explanations),
            "geo": _to_dict(analytics.geo),
            "patterns": _to_list(analytics.patterns),
            "xgboost": _to_dict(analytics.xgboost_predictions),
            "regional": _to_dict(regional),
            "decision": decision_brief,
            "forecast": _to_dict(forecast_brief),
        }
    }

    if report_source == "ai":
        store_report(session, month, lang, result)

    return result


def _build_decision_brief(
    analytics,
    indicator_stats=None,
    prev_month: Optional[str] = None,
    lang: str = "ar",
    regional=None,
) -> Dict:
    """
    بناء موجز قرارات تنفيذي من بيانات التحليلات: الحكم، نقاط التركيز،
    قائمة الأولويات، والاتجاه الشهري — بدل سرد الإحصاءات الخام.
    """
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions
    stratified = analytics.stratified or []
    patterns = analytics.patterns or []

    total = max(1, analytics.hospitals_count)
    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    total_anomalies = kpi.total_anomalies if kpi else 0
    affected_govs = kpi.affected_governorates if kpi else 0

    # ── الحكم ودرجة الخطر (0-100) ──
    anomaly_ratio = total_anomalies / total
    risk_score = round(
        min(100.0, anomaly_ratio * 40 + (critical_count * 12) + (warning_count * 5) + (affected_govs * 4)),
        1,
    )
    if risk_score >= 50 or critical_count > 0:
        verdict = "critical"
    elif risk_score >= 20 or total_anomalies > 0:
        verdict = "attention"
    else:
        verdict = "normal"

    # ── نقاط التركيز الجغرافية ──
    hotspots = []
    if geo and geo.governorates:
        for g in geo.governorates:
            if g.outlier_count > 0:
                hotspots.append({
                    "governorate": g.governorate,
                    "outliers": g.outlier_count,
                    "avg_score": round(g.avg_anomaly_score, 3),
                    "risk_pct": round(min(100, (g.avg_anomaly_score * 30) + (g.outlier_count * 15)), 1),
                })
        hotspots.sort(key=lambda h: h["risk_pct"], reverse=True)
    hotspots = hotspots[:5]

    # ── قائمة المستشفيات الأهم (watchlist) — فقط الشاذ فعلاً (لا درجة 0) ──
    watchlist = []
    real_anomalies = [
        a for a in anomalies
        if a.severity in ("critical", "warning") and a.anomaly_score > 0
    ]
    for a in sorted(real_anomalies, key=lambda x: x.anomaly_score, reverse=True)[:5]:
        watchlist.append({
            "hospital": a.hospital_name,
            "severity": a.severity,
            "governorate": a.governorate,
            "score": round(a.anomaly_score, 3),
        })

    # ── الإجراءات ذات الأولوية (مشتقة، مع هدف محدد) ──
    priorities = []
    if critical_count:
        crit_names = [a.hospital_name for a in anomalies if a.severity == "critical"][:3]
        priorities.append({
            "action": ("تدخل عاجل في المستشفيات الحرجة" if lang == "ar" else "Urgent intervention in critical hospitals"),
            "target": "، ".join(crit_names) if lang == "ar" else ", ".join(crit_names),
            "priority": "critical",
            "impact": min(100, critical_count * 15),
        })
    if hotspots:
        top_gov = hotspots[0]["governorate"]
        priorities.append({
            "action": (f"مراجعة جودة البيانات في محافظة {top_gov}" if lang == "ar" else f"Review data quality in {top_gov} governorate"),
            "target": f"{hotspots[0]['outliers']} {('مستشفى شاذ' if lang == 'ar' else 'anomalous hospitals')}",
            "priority": "high",
            "impact": hotspots[0]["risk_pct"],
        })
    if stratified:
        top_dev = max(stratified, key=lambda s: abs(s.deviation_pct))
        ind_name = (INDICATOR_NAMES_AR if lang == "ar" else INDICATOR_NAMES_EN).get(top_dev.indicator, top_dev.indicator)
        priorities.append({
            "action": (f"التحقق من مؤشر {ind_name} في {top_dev.hospital_name}" if lang == "ar"
                       else f"Verify {ind_name} at {top_dev.hospital_name}"),
            "target": f"{top_dev.deviation_pct:+.1f}% {'انحراف عن النظير' if lang == 'ar' else 'vs peer mean'}",
            "priority": "medium",
            "impact": min(100, abs(top_dev.deviation_pct)),
        })
    if patterns:
        p = patterns[0]
        priorities.append({
            "action": ("فحص النمط المركب المتكرر بين المستشفيات" if lang == "ar"
                       else "Investigate recurring composite pattern across hospitals"),
            "target": p.summary_ar if lang == "ar" else p.indicators[0],
            "priority": "medium",
            "impact": min(100, round(p.support * 100)),
        })
    # ── الأولوية الإقليمية: محافظات عالية الخطر (من الاستخبارات الإقليمية) ──
    if regional and regional.get("risk_scores"):
        high_govs = [r for r in regional["risk_scores"] if r.get("level") == "high"]
        if high_govs:
            top_gov = high_govs[0]
            priorities.append({
                "action": (f"تدخل إقليمي في محافظة {top_gov['governorate']} "
                           "(خطر مرتفع)" if lang == "ar" else
                           f"Regional intervention in {top_gov['governorate']} governorate (high risk)"),
                "target": (f"درجة {top_gov['risk_score']}/100 — ثقة {top_gov['confidence_label_ar']}" if lang == "ar"
                           else f"score {top_gov['risk_score']}/100 — {top_gov['confidence_label_en']} confidence"),
                "priority": "high",
                "impact": top_gov["risk_score"],
            })
    if xgboost and xgboost.predictions:
        escalations = [p for p in xgboost.predictions if p.predicted_severity in ("critical", "high")]
        if escalations:
            priorities.append({
                "action": ("خطة وقائية استباقية للمستشفيات المتوقع تدهورها" if lang == "ar"
                           else "Proactive prevention plan for hospitals predicted to escalate"),
                "target": f"{len(escalations)} {('مستشفى' if lang == 'ar' else 'hospitals')}",
                "priority": "high",
                "impact": min(100, len(escalations) * 12),
            })
    priorities = priorities[:5]

    # ── الاتجاه الشهري ──
    # مؤشرات «الانخفاض فيها تحسّن» (نتائج سريرية ووفيات ومخاطر)
    _LOWER_IS_BETTER = {
        "cs_rate", "smm_total", "mat_deaths", "nd", "sb",
        "preterm", "lbw", "high_risk", "adolescent",
    }
    trend_direction = "stable"
    trend_summary = ("استقرار عام في مؤشرات الجودة" if lang == "ar" else "Overall stability in quality indicators")
    if prev_month and indicator_stats:
        changed = []
        for code, s in indicator_stats.items():
            prev = s.get("prev_mean")
            cur = s.get("mean")
            if prev is None or cur is None:
                continue
            delta = cur - prev
            if abs(delta) >= (abs(prev) * 0.15 + 1e-9):
                name = (INDICATOR_NAMES_AR if lang == "ar" else INDICATOR_NAMES_EN).get(code, code)
                # ارتفاع المؤشرات الخطرة = تدهور (انخفاضها = تحسّن)
                if code in _LOWER_IS_BETTER:
                    direction = "down" if delta > 0 else "up"
                else:
                    direction = "up" if delta > 0 else "down"
                changed.append((name, direction, round(delta, 1)))
        if changed:
            improved = [c for c in changed if c[1] == "up"]
            worsened = [c for c in changed if c[1] == "down"]
            if len(worsened) > len(improved):
                trend_direction = "worsening"
                trend_summary = ("تدهور ملحوظ هذا الشهر" if lang == "ar" else "Notable worsening this month")
            elif len(improved) > len(worsened):
                trend_direction = "improving"
                trend_summary = ("تحسّن ملحوظ هذا الشهر" if lang == "ar" else "Notable improvement this month")
            top_changes = sorted(changed, key=lambda c: abs(c[2]), reverse=True)[:3]
        else:
            top_changes = []
    else:
        top_changes = []

    verdict_map = {
        "critical": ("حرج — يتطلب تدخلاً فورياً" if lang == "ar" else "Critical — requires immediate action"),
        "attention": ("يتطلب انتباهاً" if lang == "ar" else "Needs attention"),
        "normal": ("مستقر" if lang == "ar" else "Stable"),
    }

    return {
        "verdict": verdict,
        "verdict_label": verdict_map[verdict],
        "risk_score": risk_score,
        "hotspots": hotspots,
        "watchlist": watchlist,
        "priorities": priorities,
        "trend_direction": trend_direction,
        "trend_summary": trend_summary,
        "trend_changes": top_changes,
    }


def _decision_brief_lines(brief: Dict, lang: str = "ar") -> List[str]:
    """تحويل موجز القرار إلى سطور نصية للقسم التنفيذي."""
    if lang == "en":
        lines = ["=== Executive Decisions ===",
                 f"- Verdict: {brief['verdict_label']} (risk {brief['risk_score']}/100)"]
        if brief["hotspots"]:
            lines.append("- Focus areas:")
            for h in brief["hotspots"]:
                lines.append(f"  • {h['governorate']}: {h['outliers']} anomalous hospitals (risk {h['risk_pct']}%)")
        if brief["watchlist"]:
            lines.append("- Hospital watchlist:")
            for w in brief["watchlist"]:
                lines.append(f"  • {w['hospital']} ({w['severity']}, {w['governorate']}, score {w['score']})")
        if brief["priorities"]:
            lines.append("- Priority actions:")
            for i, p in enumerate(brief["priorities"], 1):
                lines.append(f"  {i}. [{p['priority']}] {p['action']} → {p['target']} (impact {p['impact']}%)")
        lines.append(f"- Monthly trend: {brief['trend_summary']}")
        for name, direction, delta in brief.get("trend_changes", [])[:3]:
            arrow = "▲" if direction == "up" else "▼"
            lines.append(f"  {arrow} {name}: {delta:+.1f}")
        return lines

    lines = ["=== قرارات تنفيذية ===",
             f"- الحكم: {brief['verdict_label']} (مؤشر خطر {brief['risk_score']}/100)"]
    if brief["hotspots"]:
        lines.append("- نقاط التركيز:")
        for h in brief["hotspots"]:
            lines.append(f"  • {h['governorate']}: {h['outliers']} مستشفى شاذ (خطر {h['risk_pct']}%)")
    if brief["watchlist"]:
        lines.append("- قائمة المستشفيات الأهم:")
        for w in brief["watchlist"]:
            lines.append(f"  • {w['hospital']} ({w['severity']} — {w['governorate']}، الدرجة {w['score']})")
    if brief["priorities"]:
        lines.append("- إجراءات الأولوية:")
        for i, p in enumerate(brief["priorities"], 1):
            lines.append(f"  {i}. [{p['priority']}] {p['action']} ← {p['target']} (أثر {p['impact']}%)")
    lines.append(f"- الاتجاه الشهري: {brief['trend_summary']}")
    for name, direction, delta in brief.get("trend_changes", [])[:3]:
        arrow = "▲" if direction == "up" else "▼"
        lines.append(f"  {arrow} {name}: {delta:+.1f}")
    return lines


def _build_forecast_brief(session: Session, month: str, lang: str = "ar") -> Dict:
    """ملخص توقعات الشهر القادم لكل مستشفى: المؤشرات القيادية الصاعدة بأوزانها
    المكتشفة (FDR + غرانجر) والنتائج المتوقعة التي تسبقها.

    يُحمَّل سياق السلاسل مرة واحدة ويُشارك عبر المستشفيات (لا إعادة جلب لكل
    مستشفى). أي فشل يُعيد موجزاً فارغاً دون تعطيل توليد التقرير.
    """
    try:
        from app.engine.smart.lag_analysis import (
            _load_series,
            run_hospital_forecast,
            run_lag_analysis,
        )

        lag_results = run_lag_analysis(session, month)
        series, meta, window = _load_series(session, month, months_back=3)
        if len(window) < 2:
            return {"month": month, "discovered": False, "total_hospitals": 0,
                    "hospitals": []}

        hospitals = []
        for name, m in meta.items():
            hid = m.get("hospital_id")
            if hid is None:
                continue
            f = run_hospital_forecast(session, hid, month, lag_results,
                                      series=series, meta=meta, window=window)
            if f and f.get("leading_rising"):
                hospitals.append(f)

        hospitals.sort(key=lambda h: h.get("score", 0) or 0, reverse=True)
        return {
            "month": month,
            "discovered": any(h.get("discovered_leads") for h in hospitals),
            "total_hospitals": len(meta),
            "hospitals": hospitals,
        }
    except Exception:
        logger.exception("Forecast brief generation failed")
        return {"month": month, "discovered": False, "total_hospitals": 0,
                "hospitals": []}


def _forecast_brief_lines(brief: Dict, lang: str = "ar") -> List[str]:
    """تحويل موجز التوقعات إلى سطور نصية لقسم «توقعات الشهر القادم»."""
    hospitals = brief.get("hospitals") or []
    total = brief.get("total_hospitals") or 0
    discovered = brief.get("discovered")

    if lang == "en":
        lines = ["=== Next-Month Forecast ==="]
        if not hospitals:
            lines.append("- No hospital has rising leading indicators this month.")
            lines.append("- Leading indicators: rising indicators that statistically precede outcomes (discovered lead-lag relationships, FDR + Granger).")
            return lines
        src = ("discovered lead-lag relationships (FDR + Granger)"
               if discovered else "the default indicator list (insufficient data for discovery)")
        lines.append(
            f"- {len(hospitals)} of {total} hospitals have rising leading indicators this month — based on {src}."
        )
        for h in hospitals[:8]:
            prob = int((h.get("probability") or 0) * 100)
            conf = h.get("confidence_label_ar") or h.get("confidence") or "—"
            lines.append(f"- {h.get('hospital_name')} ({h.get('severity')}, probability {prob}%, confidence {conf}):")
            for r in h.get("leading_rising", [])[:4]:
                outcomes = ("، ".join(f"{o.get('outcome_ar')} after {o.get('lag_word')}"
                                      for o in r.get("leads_to", [])[:2])
                            or "no reliable outcome linked")
                delta = r.get("delta_pct")
                d = f" (+{delta:.1f}%)" if delta is not None else ""
                lines.append(f"  • {r.get('metric_ar')} (weight {r.get('weight')}){d}: leads to {outcomes}")
        lines.append("- Note: correlation is not causation — these are statistical lead signals, not certain forecasts.")
        return lines

    lines = ["=== توقعات الشهر القادم ==="]
    if not hospitals:
        lines.append("- لا يوجد أي مستشفى لديه مؤشرات قيادية صاعدة هذا الشهر.")
        lines.append("- المؤشرات القيادية: مؤشرات ترتفع غالباً قبل تفاقم النتائج (علاقات متأخرة مكتشفة — FDR + غرانجر).")
        return lines
    src = ("علاقات متأخرة مكتشفة (FDR + غرانجر)"
           if discovered else "القائمة الافتراضية (بيانات غير كافية لاكتشاف العلاقات)")
    lines.append(
        f"- {len(hospitals)} من {total} مستشفى لديها مؤشرات قيادية صاعدة هذا الشهر — مبنية على {src}."
    )
    severity_ar = {"critical": "حرج", "warning": "تحذير", "info": "متابعة", "none": "طبيعي"}
    for h in hospitals[:8]:
        sev = severity_ar.get(h.get("severity"), h.get("severity"))
        prob = int((h.get("probability") or 0) * 100)
        conf = h.get("confidence_label_ar") or h.get("confidence") or "—"
        lines.append(f"- {h.get('hospital_name')} ({sev} — احتمال {prob}%، ثقة {conf}):")
        for r in h.get("leading_rising", [])[:4]:
            outcomes = ("، ".join(f"{o.get('outcome_ar')} بعد {o.get('lag_word')}"
                                  for o in r.get("leads_to", [])[:2])
                        or "لا نتيجة موثوقة مرتبطة")
            delta = r.get("delta_pct")
            d = f" (+{delta:.1f}%)" if delta is not None else ""
            lines.append(f"  • {r.get('metric_ar')} (وزن {r.get('weight')}){d}: يُتوقع {outcomes}")
    lines.append("- تنبيه: الارتباط لا يعني سببّية — هذه إشارات استباقية إحصائية لا توقعات مؤكدة.")
    return lines


def _build_local_report(analytics, lang: str = "ar", indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
    """بناء تقرير محلي من بيانات التحليلات عند فشل الذكاء الاصطناعي"""
    if lang == "en":
        return _build_local_report_english(analytics, indicator_stats, prev_month, regional)
    return _build_local_report_arabic(analytics, indicator_stats, prev_month, regional)


def _build_local_report_arabic(analytics, indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
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
    if stratified:
        top = max(stratified, key=lambda s: abs(s.deviation_pct))
        lines.append(
            f"- أبرز انحراف فردي: {top.hospital_name} في "
            f"{INDICATOR_NAMES_AR.get(top.indicator, top.indicator)}: "
            f"{top.hospital_value:.1f} مقابل متوسط نظير {top.peer_group_mean:.1f} "
            f"(انحراف {top.deviation_pct:+.1f}%)"
        )
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
    if indicator_stats:
        lines.append("")
        lines.append("القيم الفعلية لشهر التقرير:")
        lines.extend(_indicator_stats_lines_ar(indicator_stats))
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

    if prev_month and indicator_stats:
        lines.append("")
        lines.append("=== الاتجاهات الشهرية ===")
        lines.extend(_trend_lines_ar(prev_month, indicator_stats))
        lines.append("")

    lines.append("")
    lines.append("=== الأنماط المركبة للمؤشرات ===")
    lines.extend(_composite_patterns_lines_ar(analytics.patterns))
    lines.append("")

    lines.append("=== الاستخبارات الإقليمية ===")
    lines.extend(_regional_lines_ar(regional))
    lines.append("")

    lines.append("=== التوصيات ===")
    recommendations = _build_recommendations(
        kpi, anomalies, strong_correlations, clustering, xgboost, lang="ar"
    )
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")

    return "\n".join(lines)


def _build_local_report_english(analytics, indicator_stats=None, prev_month: Optional[str] = None, regional=None) -> str:
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
    if stratified:
        top = max(stratified, key=lambda s: abs(s.deviation_pct))
        lines.append(
            f"- Largest single deviation: {top.hospital_name} in "
            f"{INDICATOR_NAMES_EN.get(top.indicator, top.indicator)}: "
            f"{top.hospital_value:.1f} vs peer mean {top.peer_group_mean:.1f} "
            f"(deviation {top.deviation_pct:+.1f}%)"
        )
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
    if indicator_stats:
        lines.append("")
        lines.append("Actual values for the report month:")
        lines.extend(_indicator_stats_lines_en(indicator_stats))
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

    if prev_month and indicator_stats:
        lines.append("")
        lines.append("=== Monthly Trends ===")
        lines.extend(_trend_lines_en(prev_month, indicator_stats))
        lines.append("")

    lines.append("")
    lines.append("=== Composite Indicator Patterns ===")
    lines.extend(_composite_patterns_lines_en(analytics.patterns))
    lines.append("")

    lines.append("=== Regional Health Intelligence ===")
    lines.extend(_regional_lines_en(regional))
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
