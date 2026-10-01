from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import zlib
import numpy as np
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
from app.models import Hospital


@dataclass
class TrendData:
    """بيانات الاتجاه لمستشفى"""
    hospital_id: str
    hospital_name: str
    months: List[str] = field(default_factory=list)
    values: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class PeerComparison:
    """مقارنة الأقران"""
    hospital_id: str
    hospital_name: str
    percentile: float
    rank: int
    total_hospitals: int
    comparison_label: str
    anomaly_score: float = 0.0


@dataclass
class AdvancedComparisonResult:
    """نتيجة المقارنة المتقدمة"""
    month: str
    trends: List[TrendData] = field(default_factory=list)
    peer_comparisons: List[PeerComparison] = field(default_factory=list)
    predictions: Dict[str, Any] = field(default_factory=dict)
    chart_config: Dict[str, Any] = field(default_factory=dict)


def get_historical_data(session: Session, current_month: str, hospital_id: Optional[str] = None) -> Dict[str, Any]:
    """جلب البيانات التاريخية للمقارنة"""
    from datetime import datetime, timedelta

    current_date = datetime.strptime(current_month, "%Y-%m")

    months = []
    for i in range(6):
        month_date = current_date - timedelta(days=30 * i)
        months.append(month_date.strftime("%Y-%m"))

    months.reverse()

    historical_data = {}
    for month in months:
        try:
            analytics = run_smart_analytics(session, month)
            historical_data[month] = {
                "kpi": analytics.kpi.__dict__ if analytics.kpi else {},
                "anomalies": [a.__dict__ for a in analytics.anomalies] if analytics.anomalies else [],
                "predictions": analytics.xgboost_predictions.__dict__ if analytics.xgboost_predictions else {}
            }
        except Exception:
            historical_data[month] = None

    return historical_data


def perform_advanced_comparison(
    session: Session,
    month: str,
    hospital_id: Optional[str] = None,
    comparison_type: str = "all",
    lang: str = "ar",
) -> AdvancedComparisonResult:
    """إجراء مقارنة متقدمة"""

    historical_data = get_historical_data(session, month, hospital_id)

    trends = analyze_trends(historical_data, hospital_id)

    current_analytics = run_smart_analytics(session, month)
    predictions = current_analytics.xgboost_predictions.__dict__ if current_analytics.xgboost_predictions else {}

    peer_comparisons = compare_peers(
        session, month, comparison_type, hospital_id=hospital_id, lang=lang,
        analytics=current_analytics,
    )

    chart_config = generate_comparison_chart(trends, peer_comparisons)

    return AdvancedComparisonResult(
        month=month,
        trends=trends,
        peer_comparisons=peer_comparisons,
        predictions=predictions,
        chart_config=chart_config
    )


def analyze_trends(historical_data: Dict[str, Any], hospital_id: Optional[str] = None) -> List[TrendData]:
    """تحليل الاتجاهات عبر الأشهر"""
    trends = []

    if not historical_data:
        return trends

    hospitals = set()
    for month_data in historical_data.values():
        if month_data and "anomalies" in month_data:
            for anomaly in month_data["anomalies"]:
                hospitals.add(anomaly.get("hospital_id"))

    if hospital_id:
        hospitals = {hospital_id}

    for hosp_id in hospitals:
        trend = TrendData(hospital_id=str(hosp_id), hospital_name=str(hosp_id))

        for month in sorted(historical_data.keys()):
            month_data = historical_data[month]
            if month_data and "kpi" in month_data:
                trend.months.append(month)
                value = month_data["kpi"].get("total_cases", 0)
                if "total_cases" not in trend.values:
                    trend.values["total_cases"] = []
                trend.values["total_cases"].append(value)

        if trend.months:
            trends.append(trend)

    return trends


_RISK_LABELS = {
    "ar": {"critical": "حرج", "high": "عالي", "moderate": "متوسط", "low": "منخفض"},
    "en": {"critical": "critical", "high": "high", "moderate": "moderate", "low": "low"},
}


def _risk_label(risk_percentile: float, lang: str = "ar") -> str:
    """تسمية مستوى الخطر حسب مئين المخاطرة الصاعد (الأعلى = الأخطر)."""
    labels = _RISK_LABELS.get(lang, _RISK_LABELS["ar"])
    if risk_percentile >= 75:
        return labels["critical"]
    if risk_percentile >= 50:
        return labels["high"]
    if risk_percentile >= 25:
        return labels["moderate"]
    return labels["low"]


def _anomaly_map(analytics) -> Dict[int, dict]:
    """خريطة hospital_id -> {name, score} من نتائج التحليل."""
    out = {}
    for a in (analytics.anomalies or []) if analytics else []:
        out[a.hospital_id] = {
            "name": a.hospital_name,
            "score": a.anomaly_score,
        }
    return out


def _size_tiers(session, month: str, n_tiers: int = 3) -> Dict[int, int]:
    """شرائح حجم المستشفيات من متوسط الإنجاز التاريخي (ثلاثيات total_births).

    الحجم غير مخزّن في المخطط — يُشتق من متوسط قيمة المؤشر «6» (المواليد
    الأحياء) عبر كل الأشهر لكل مستشفى، ثم يُقسّم إلى n_tiers شرائح متساوية
    العدد (0 = الأصغر). التعريف موثّق ومُختبَر وبلا أي تغيير في المخطط.
    """
    from app.models import IndicatorValue, Indicator

    ind = session.query(Indicator).filter(Indicator.code == "6").first()
    if ind is None:
        return {}
    rows = (
        session.query(IndicatorValue.hospital_id, IndicatorValue.value)
        .filter(IndicatorValue.indicator_id == ind.id, IndicatorValue.value.isnot(None))
        .all()
    )
    sums: Dict[int, float] = {}
    counts: Dict[int, int] = {}
    for hid, v in rows:
        sums[hid] = sums.get(hid, 0.0) + float(v)
        counts[hid] = counts.get(hid, 0) + 1
    avgs = {hid: s / counts[hid] for hid, s in sums.items() if counts[hid] > 0}
    if len(avgs) < n_tiers:
        # بيانات غير كافية للتقسيم => شريحة واحدة موحدة (لا تمييز حجم)
        return {hid: 0 for hid in avgs}
    # حدود الكمّيات على متوسطات الحجم: كل مستشفى يأخذ عدد الحدود التي بلغها
    # أو تجاوزها (≥) — الأكبر شريحة عليا والأصغر دنيا دون اكتظاظ سفلي.
    vals = sorted(avgs.values())
    thresholds = [float(np.quantile(vals, k / n_tiers)) for k in range(1, n_tiers)]
    return {hid: sum(1 for q in thresholds if v >= q) for hid, v in avgs.items()}


def compare_peers(
    session: Session,
    month: str,
    comparison_type: str = "all",
    hospital_id: Optional[str] = None,
    lang: str = "ar",
    analytics=None,
) -> List[PeerComparison]:
    """مقارنة المستشفيات بدرجة الخطر (anomaly_score) داخل مجموعة النظير.

    - المعيار: anomaly_score تنازلياً (الرتبة 1 = الأخطر).
    - مئين المخاطرة صاعد: الرتبة 1 -> 100.
    - النطاق: all = كل النشطة؛ governorate/type/ownership/size تتطلب
      hospital_id وتفلتر بالمحافظة/النوع/الملكية/شريحة الحجم المشتقة.
    """
    ana_map = _anomaly_map(analytics)

    hospitals = session.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    # الفلتر حسب النطاق أولاً
    ref = None
    if comparison_type in ("governorate", "type", "ownership", "size"):
        if not hospital_id:
            return []
        try:
            ref = session.query(Hospital).get(int(hospital_id))
        except ValueError:
            return []
        if ref is None:
            return []

    size_tiers = _size_tiers(session, month) if comparison_type == "size" else None

    candidates = []
    for h in hospitals:
        info = ana_map.get(h.id)
        if info is None:
            continue  # لا بيانات للمستشفى هذا الشهر
        if comparison_type == "governorate" and h.governorate_id != ref.governorate_id:
            continue
        if comparison_type == "type" and h.hospital_type_id != ref.hospital_type_id:
            continue
        if comparison_type == "ownership" and h.facility_ownership_id != ref.facility_ownership_id:
            continue
        if comparison_type == "size" and size_tiers.get(h.id) != size_tiers.get(ref.id):
            continue
        candidates.append((h.id, info["name"], info["score"]))

    if len(candidates) < 2:
        return []

    # ترتيب تنازلي بالدرجة، وكسر تعادل حتمي بالاسم
    candidates.sort(key=lambda c: (-c[2], c[1]))

    total = len(candidates)
    comparisons = []
    for rank, (hosp_id, name, score) in enumerate(candidates, 1):
        risk_percentile = round(100.0 * (total - rank + 1) / total, 1)
        comparisons.append(PeerComparison(
            hospital_id=str(hosp_id),
            hospital_name=name,
            percentile=risk_percentile,
            rank=rank,
            total_hospitals=total,
            comparison_label=_risk_label(risk_percentile, lang),
            anomaly_score=round(score, 4),
        ))
    return comparisons


def generate_comparison_chart(trends: List[TrendData], peer_comparisons: List[PeerComparison]) -> Dict[str, Any]:
    """تكوين الرسم البياني للمقارنة"""

    chart_data = {
        "type": "line",
        "data": {
            "labels": [],
            "datasets": []
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": "مقارنة أداء المستشفيات عبر الأشهر"
                },
                "legend": {
                    "position": "bottom"
                }
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "title": {
                        "display": True,
                        "text": "إجمالي الحالات"
                    }
                },
                "x": {
                    "title": {
                        "display": True,
                        "text": "الشهر"
                    }
                }
            }
        }
    }

    if trends:
        first_trend = trends[0]
        chart_data["data"]["labels"] = first_trend.months

        for trend in trends[:5]:
            dataset = {
                "label": trend.hospital_name,
                "data": trend.values.get("total_cases", []),
                "borderColor": _stable_hospital_color(trend.hospital_id),
                "tension": 0.1
            }
            chart_data["data"]["datasets"].append(dataset)

    return chart_data


def _stable_hospital_color(hospital_id: str) -> str:
    """لون ثابت للمستشفى عبر كل العمليات/إعادة التشغيل.

    يعتمد على crc32 (حتمي عبر العمليات) بدل hash() المدمج في بيثون
    الذي يختلف باختلاف PYTHONHASHSEED فيغير الألوان مع كل إعادة تشغيل."""
    h = zlib.crc32(str(hospital_id).encode("utf-8")) & 0xFFFFFFFF
    r = h & 0xFF
    g = (h >> 8) & 0xFF
    b = (h >> 16) & 0xFF
    return f"rgb({r}, {g}, {b})"
