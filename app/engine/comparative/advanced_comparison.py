from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import zlib
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics


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

    peer_comparisons = compare_peers(session, month, comparison_type, lang=lang)

    current_analytics = run_smart_analytics(session, month)
    predictions = current_analytics.xgboost_predictions.__dict__ if current_analytics.xgboost_predictions else {}

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


def compare_peers(session: Session, month: str, comparison_type: str, lang: str = "ar") -> List[PeerComparison]:
    """مقارنة المستشفيات ببعضها"""
    from app.models import Hospital, IndicatorValue

    _labels = {
        "ar": {"top": "متفوق", "mid": "متوسط", "low": "يحتاج تحسين", "crit": "حرج"},
        "en": {"top": "Excellent", "mid": "Average", "low": "Needs improvement", "crit": "Critical"},
    }
    labels = _labels.get(lang, _labels["ar"])

    hospitals = session.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    if len(hospitals) < 2:
        return []

    month_data = {}
    for hospital in hospitals:
        values = session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == month
        ).all()

        if values:
            total_cases = sum(v.value for v in values if v.value)
            month_data[hospital.id] = {
                "hospital_name": hospital.name,
                "total_cases": total_cases
            }

    if not month_data:
        return []

    sorted_hospitals = sorted(month_data.items(), key=lambda x: x[1]["total_cases"], reverse=True)

    comparisons = []
    total = len(sorted_hospitals)

    for rank, (hosp_id, data) in enumerate(sorted_hospitals, 1):
        percentile = (rank / total) * 100

        if percentile <= 25:
            label = labels["top"]
        elif percentile <= 50:
            label = labels["mid"]
        elif percentile <= 75:
            label = labels["low"]
        else:
            label = labels["crit"]

        comparisons.append(PeerComparison(
            hospital_id=str(hosp_id),
            hospital_name=data["hospital_name"],
            percentile=percentile,
            rank=rank,
            total_hospitals=total,
            comparison_label=label
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
