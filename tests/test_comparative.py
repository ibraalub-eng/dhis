"""Tests for the comprehensive smart report generator."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from app.engine.comparative import generate_comprehensive_report
from app.engine.comparative.advanced_comparison import perform_advanced_comparison, AdvancedComparisonResult


def test_build_comprehensive_prompt_returns_string(db_session):
    from app.engine.comparative.report_generator import build_comprehensive_prompt
    from app.engine.smart import run_smart_analytics
    
    analytics = run_smart_analytics(db_session, "2026-06")
    prompt = build_comprehensive_prompt(analytics)
    assert isinstance(prompt, str)
    assert "أنت خبير" in prompt
    assert "cs_rate" in prompt


def test_generate_comprehensive_report_returns_data(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert "month" in result
    assert "report" in result
    assert "data" in result
    assert result["month"] == "2026-06"


def test_generate_comprehensive_report_data_sections(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    data = result["data"]
    assert "kpi" in data
    assert "anomalies" in data
    assert "clustering" in data
    assert "correlations" in data
    assert "residuals" in data
    assert "stratified" in data
    assert "explanations" in data
    assert "geo" in data
    assert "xgboost" in data
    assert "decision" in data
    assert "regional" in data


def test_comprehensive_report_includes_forecast_section(db_session):
    """التقرير الشامل يتضمن قسم توقعات الشهر القادم (مؤشرات قيادية صاعدة بأوزانها
    المكتشفة والنتائج المتوقعة) في النص وفي data."""
    result = generate_comprehensive_report(db_session, "2026-03", use_cache=False)
    assert "توقعات الشهر القادم" in result["report"]
    assert "forecast" in result["data"]
    fc = result["data"]["forecast"]
    assert "hospitals" in fc and "discovered" in fc and "total_hospitals" in fc
    # النص يتضمن مؤشراً قيادياً صاعداً بوزنه أو رسالة غياب صريحة
    assert ("وزن" in result["report"] or "لا يوجد أي مستشفى" in result["report"])


def test_comprehensive_report_strips_explanations_for_hidden(db_session):
    """عند تعطيل النصوص التوضيحية، تُفرَّغ الأقسام السردية والنص الكامل بينما
    تبقى البيانات البنيوية (data) سليمة — ولا يُغيَّر الكائن المخزَّن في الكاش."""
    from app.engine.comparative.report_generator import _with_explanations
    full = generate_comprehensive_report(db_session, "2026-06", use_cache=False)
    stripped = _with_explanations(full, False)
    assert stripped["report"] == ""
    assert stripped["sections"] and all(v == "" for v in stripped["sections"].values())
    assert stripped["data"] == full["data"]
    # الكائن الأصلي غير مُتغيّر (الكاش يحتفظ بالنص الكامل)
    assert full["report"] != ""
    # عند التمكين تُعاد النسخة كاملة
    assert _with_explanations(full, True)["report"] == full["report"]


def test_local_report_includes_regional_section(db_session):
    """التقرير المحلي يتضمن قسم الاستخبارات الإقليمية من بيانات المحافظات الفعلية."""
    from app.engine.comparative.report_generator import _build_local_report
    from app.engine.smart import run_smart_analytics

    analytics = run_smart_analytics(db_session, "2026-06")
    report_ar = _build_local_report(analytics, lang="ar")
    assert "الاستخبارات الإقليمية" in report_ar
    report_en = _build_local_report(analytics, lang="en")
    assert "Regional Health Intelligence" in report_en


@patch("app.engine.comparative.report_generator._call_api")
def test_generate_comprehensive_report_uses_ai(mock_api, db_session):
    mock_api.return_value = "تقرير تجريبي بالعربية"
    result = generate_comprehensive_report(db_session, "2026-06")
    assert mock_api.called
    # قسم القرارات التنفيذية يُدرج دائماً قبل نص الذكاء الاصطناعي
    assert "قرارات تنفيذية" in result["report"]
    assert "تقرير تجريبي بالعربية" in result["report"]
    assert result["report_source"] == "ai"


@patch("app.engine.comparative.report_generator._call_api")
def test_generate_comprehensive_report_handles_ai_failure(mock_api, db_session):
    mock_api.return_value = None
    result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report"] != "خطأ في توليد التقرير"
    assert "قرارات تنفيذية" in result["report"]
    assert "الملخص التنفيذي" in result["report"]
    assert result["report_source"] == "local"


def test_decision_brief_structure(db_session):
    from app.engine.smart import run_smart_analytics
    from app.engine.comparative.report_generator import _build_decision_brief

    analytics = run_smart_analytics(db_session, "2026-06")
    brief = _build_decision_brief(analytics, lang="ar")
    assert brief["verdict"] in ("critical", "attention", "normal")
    assert 0 <= brief["risk_score"] <= 100
    assert isinstance(brief["hotspots"], list)
    assert isinstance(brief["watchlist"], list)
    assert isinstance(brief["priorities"], list)
    assert brief["trend_direction"] in ("improving", "worsening", "stable")
    assert brief["trend_summary"]
    # كل إجراء أولوية له هدف وأثر
    for p in brief["priorities"]:
        assert p["action"] and p["target"]
        assert 0 <= p["impact"] <= 100


def test_decision_brief_english(db_session):
    from app.engine.smart import run_smart_analytics
    from app.engine.comparative.report_generator import _build_decision_brief, _decision_brief_lines

    analytics = run_smart_analytics(db_session, "2026-06")
    brief = _build_decision_brief(analytics, lang="en")
    lines = _decision_brief_lines(brief, "en")
    text = "\n".join(lines)
    assert "Executive Decisions" in text
    assert "Verdict" in text
    assert "risk" in text
    assert "Monthly trend" in text
    if brief["priorities"]:
        assert "Priority actions" in text


def test_decision_brief_trend_lower_is_better():
    """ارتفاع المؤشرات الخطرة (وفيات/مخاطر) = تدهور لا تحسّن."""
    from app.engine.comparative.report_generator import _build_decision_brief

    class _FakeAnomaly:
        def __init__(self, name, sev, gov, score):
            self.hospital_name, self.severity, self.governorate, self.anomaly_score = name, sev, gov, score

    class _FakeKPI:
        total_anomalies = 1
        affected_governorates = 1

    class _FakeAnalytics:
        hospitals_count = 5
        kpi = _FakeKPI()
        anomalies = [_FakeAnomaly("H1", "warning", "Gaza", 0.5)]
        geo = None
        xgboost_predictions = None
        stratified = []
        patterns = []

    # وفيات أمومية ارتفعت من 2 إلى 4 (ارتفاع = تدهور)
    stats = {"mat_deaths": {"prev_mean": 2.0, "mean": 4.0}}
    brief = _build_decision_brief(_FakeAnalytics(), indicator_stats=stats, prev_month="2026-05", lang="ar")
    assert brief["trend_direction"] == "worsening"
    # الإجمالي (total_births) انخفض بشكل طفيف — لا يؤثر في الاتجاه العام للوفيات
    stats2 = {"total_births": {"prev_mean": 190.0, "mean": 160.0}}
    brief2 = _build_decision_brief(_FakeAnalytics(), indicator_stats=stats2, prev_month="2026-05", lang="ar")
    assert brief2["trend_direction"] == "worsening"


def test_decision_brief_watchlist_filters_normal():
    """المستشفيات غير الشاذة (درجة 0) لا تظهر في قائمة المتابعة."""
    from app.engine.comparative.report_generator import _build_decision_brief

    class _FakeAnomaly:
        def __init__(self, name, sev, gov, score):
            self.hospital_name, self.severity, self.governorate, self.anomaly_score = name, sev, gov, score

    class _FakeKPI:
        total_anomalies = 0
        affected_governorates = 0

    class _FakeAnalytics:
        hospitals_count = 3
        kpi = _FakeKPI()
        anomalies = [
            _FakeAnomaly("Normal A", "normal", "Gaza", 0.0),
            _FakeAnomaly("Normal B", "normal", "Gaza", 0.0),
        ]
        geo = None
        xgboost_predictions = None
        stratified = []
        patterns = []

    brief = _build_decision_brief(_FakeAnalytics(), lang="ar")
    assert brief["watchlist"] == []
    assert brief["verdict"] == "normal"


def test_decision_brief_priorities_are_derived(db_session):
    """الإجراءات مشتقة من بيانات حقيقية (شذوذ/محافظات/انحرافات) وليست قوالب فارغة."""
    from app.engine.smart import run_smart_analytics
    from app.engine.comparative.report_generator import _build_decision_brief

    analytics = run_smart_analytics(db_session, "2026-06")
    brief = _build_decision_brief(analytics, lang="ar")
    # عند وجود شذوذات يجب ألا تكون قائمة الأولويات فارغة
    if analytics.kpi and analytics.kpi.total_anomalies > 0:
        assert len(brief["priorities"]) >= 1
        assert brief["verdict"] in ("critical", "attention")


@patch("app.engine.comparative.report_generator._call_api")
def test_generate_comprehensive_report_error_handling(mock_api, db_session):
    mock_api.side_effect = Exception("API error")
    result = generate_comprehensive_report(db_session, "2026-06")
    assert "الملخص التنفيذي" in result["report"]
    assert result["report_source"] == "local"


# --- API endpoint tests ---

@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_comprehensive_report_endpoint_returns_200(client):
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200


def test_comprehensive_report_endpoint_returns_data(client):
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "report" in data
    assert "data" in data
    assert data["month"] == "2026-06"


def test_comprehensive_report_endpoint_includes_all_sections(client):
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "kpi" in data
    assert "anomalies" in data
    assert "clustering" in data
    assert "correlations" in data
    assert "residuals" in data
    assert "stratified" in data
    assert "explanations" in data
    assert "geo" in data
    assert "xgboost" in data


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_endpoint_uses_gemini(mock_api, client):
    mock_api.return_value = "تقرير تجريبي بالعربية"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert mock_api.called
    assert "تقرير تجريبي بالعربية" in response.json()["report"]


@patch("app.engine.comparative.report_generator.run_smart_analytics")
def test_comprehensive_report_endpoint_error_handling(mock_analytics, client):
    mock_analytics.side_effect = RuntimeError("Database error")
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 500
    assert "خطأ في توليد التقرير" in response.json()["detail"]


# --- Plan Task 4: Comprehensive tests ---


def test_comprehensive_report_returns_data(client):
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "report" in data
    assert "data" in data


def test_comprehensive_report_includes_all_sections(client):
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "kpi" in data
    assert "anomalies" in data
    assert "clustering" in data
    assert "correlations" in data
    assert "residuals" in data
    assert "stratified" in data
    assert "explanations" in data
    assert "geo" in data
    assert "xgboost" in data


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_uses_gemini(mock_api, client):
    mock_api.return_value = "تقرير تجريبي بالعربية"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert mock_api.called


@patch("app.engine.comparative.report_generator.run_smart_analytics")
def test_comprehensive_report_error_handling(mock_analytics, client):
    mock_analytics.side_effect = RuntimeError("Database error")
    response = client.get("/comparative/comprehensive-report/2026-99")
    assert response.status_code == 500
    assert "خطأ في توليد التقرير" in response.json()["detail"]


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_returns_arabic_report(mock_api, client):
    mock_api.return_value = "تقرير التحليل الشامل لشهر يونيو"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert "تقرير" in response.json()["report"]


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_month_passthrough(mock_api, db_session):
    mock_api.return_value = "report"
    result = generate_comprehensive_report(db_session, "2026-03")
    assert result["month"] == "2026-03"


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_data_types(mock_api, db_session):
    mock_api.return_value = "test"
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result, dict)
    assert isinstance(result["month"], str)
    assert isinstance(result["report"], str)
    assert isinstance(result["data"], dict)


def test_comprehensive_report_kpi_structure(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    kpi = result["data"]["kpi"]
    assert "total_anomalies" in kpi
    assert "critical_count" in kpi
    assert "warning_count" in kpi
    assert "month_status" in kpi
    assert kpi["month_status"] in ("normal", "attention_needed", "critical")


def test_comprehensive_report_anomalies_is_list(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["anomalies"], list)


def test_comprehensive_report_residuals_is_list(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["residuals"], list)


def test_comprehensive_report_stratified_is_list(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["stratified"], list)


def test_comprehensive_report_explanations_is_list(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["explanations"], list)


def test_comprehensive_report_clustering_is_dict(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["clustering"], dict)


def test_comprehensive_report_correlations_is_dict(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["correlations"], dict)


def test_comprehensive_report_geo_is_dict(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["geo"], dict)


def test_comprehensive_report_xgboost_is_dict(db_session):
    result = generate_comprehensive_report(db_session, "2026-06")
    assert isinstance(result["data"]["xgboost"], dict)


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_prompt_contains_all_sections(mock_api, db_session):
    mock_api.return_value = "report"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_api.call_args[0][0]
    assert "cs_rate" in prompt_arg
    assert "smm_total" in prompt_arg
    assert "mat_deaths" in prompt_arg
    assert "الملخص التنفيذي" in prompt_arg
    assert "تحليل الشذوذ" in prompt_arg
    assert "التجميع" in prompt_arg
    assert "الارتباطات" in prompt_arg


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_prompt_in_arabic(mock_api, db_session):
    mock_api.return_value = "report"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_api.call_args[0][0]
    assert "أنت خبير" in prompt_arg
    assert "العربية" in prompt_arg


@patch("app.engine.comparative.report_generator.run_smart_analytics")
def test_comprehensive_report_propagates_analytics_error(mock_analytics, client):
    mock_analytics.side_effect = ValueError("Invalid data")
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 500


@patch("app.engine.comparative.report_generator._call_api")
def test_comprehensive_report_default_error_text(mock_api, db_session):
    mock_api.return_value = ""
    result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report"] != "خطأ في توليد التقرير"
    assert "الملخص التنفيذي" in result["report"]
    assert result["report_source"] == "local"


# --- Advanced Comparison Tests ---


def test_advanced_comparison_returns_data(db_session):
    """اختبار أن المقارنة تُعيد بيانات"""
    result = perform_advanced_comparison(db_session, "2026-06")
    assert isinstance(result, AdvancedComparisonResult)
    assert result.month == "2026-06"
    assert isinstance(result.trends, list)
    assert isinstance(result.peer_comparisons, list)
    assert isinstance(result.predictions, dict)
    assert isinstance(result.chart_config, dict)


def test_advanced_comparison_endpoint_returns_data(client):
    """اختبار endpoint المقارنة المتقدمة"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "comparison_data" in data
    assert "chart_config" in data


def test_advanced_comparison_includes_trends(client):
    """اختبار أن المقارنة تتضمن الاتجاهات"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "trends" in data["comparison_data"]


def test_advanced_comparison_includes_predictions(client):
    """اختبار أن المقارنة تتضمن التنبؤات"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "predictions" in data["comparison_data"]


def test_advanced_comparison_chart_config(client):
    """اختبار تكوين الرسم البياني"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "chart_config" in data
    assert "type" in data["chart_config"]
    assert "data" in data["chart_config"]
    assert "options" in data["chart_config"]


def test_advanced_comparison_with_hospital_id(client):
    """اختبار المقارنة مع معرف مستشفى محدد"""
    response = client.get("/comparative/advanced-comparison/2026-06?hospital_id=1")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data


def test_advanced_comparison_with_comparison_type(client):
    """اختبار المقارنة مع نوع مقارنة محدد"""
    response = client.get("/comparative/advanced-comparison/2026-06?comparison_type=governorate")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data


# --- Comprehensive Unit Tests for Advanced Comparison ---

from app.engine.comparative.advanced_comparison import (
    TrendData, PeerComparison, AdvancedComparisonResult,
    analyze_trends, generate_comparison_chart,
)


# --- Dataclass Tests ---

def test_trend_data_defaults():
    t = TrendData(hospital_id="h1", hospital_name="Hospital One")
    assert t.months == []
    assert t.values == {}


def test_trend_data_with_values():
    t = TrendData(
        hospital_id="h1", hospital_name="H1",
        months=["2026-01", "2026-02"],
        values={"total_cases": [100, 200]},
    )
    assert len(t.months) == 2
    assert t.values["total_cases"] == [100, 200]


def test_peer_comparison_fields():
    p = PeerComparison(
        hospital_id="h1", hospital_name="H1",
        percentile=25.0, rank=1, total_hospitals=4,
        comparison_label="حرج",
    )
    assert p.percentile == 25.0
    assert p.comparison_label == "حرج"


def test_advanced_comparison_result_defaults():
    r = AdvancedComparisonResult(month="2026-06")
    assert r.trends == []
    assert r.peer_comparisons == []
    assert r.predictions == {}
    assert r.chart_config == {}


def test_advanced_comparison_result_with_data():
    trends = [TrendData(hospital_id="h1", hospital_name="H1")]
    peers = [PeerComparison("h1", "H1", 50.0, 1, 2, "متوسط")]
    r = AdvancedComparisonResult(
        month="2026-06", trends=trends, peer_comparisons=peers,
        predictions={"next_month": 100}, chart_config={"type": "line"},
    )
    assert len(r.trends) == 1
    assert len(r.peer_comparisons) == 1
    assert r.predictions["next_month"] == 100


# --- analyze_trends Unit Tests ---

def test_analyze_trends_empty_data():
    trends = analyze_trends({})
    assert trends == []


def test_analyze_trends_none_data():
    trends = analyze_trends(None)
    assert trends == []


def test_analyze_trends_with_valid_data():
    historical = {
        "2026-01": {
            "kpi": {"total_cases": 100},
            "anomalies": [{"hospital_id": "h1"}],
            "predictions": {},
        },
        "2026-02": {
            "kpi": {"total_cases": 150},
            "anomalies": [{"hospital_id": "h1"}],
            "predictions": {},
        },
    }
    trends = analyze_trends(historical)
    assert len(trends) == 1
    assert trends[0].hospital_id == "h1"
    assert trends[0].months == ["2026-01", "2026-02"]
    assert trends[0].values["total_cases"] == [100, 150]


def test_analyze_trends_multiple_hospitals():
    historical = {
        "2026-01": {
            "kpi": {"total_cases": 100},
            "anomalies": [{"hospital_id": "h1"}, {"hospital_id": "h2"}],
            "predictions": {},
        },
    }
    trends = analyze_trends(historical)
    ids = {t.hospital_id for t in trends}
    assert "h1" in ids
    assert "h2" in ids


def test_analyze_trends_filter_by_hospital_id():
    historical = {
        "2026-01": {
            "kpi": {"total_cases": 100},
            "anomalies": [{"hospital_id": "h1"}, {"hospital_id": "h2"}],
            "predictions": {},
        },
    }
    trends = analyze_trends(historical, hospital_id="h1")
    assert len(trends) == 1
    assert trends[0].hospital_id == "h1"


def test_analyze_trends_skips_none_months():
    historical = {
        "2026-01": None,
        "2026-02": {"kpi": {"total_cases": 50}, "anomalies": [{"hospital_id": "h1"}], "predictions": {}},
    }
    trends = analyze_trends(historical)
    assert len(trends) == 1
    assert trends[0].months == ["2026-02"]
    assert trends[0].values["total_cases"] == [50]


def test_analyze_trends_skips_months_without_kpi():
    historical = {
        "2026-01": {"anomalies": [{"hospital_id": "h1"}], "predictions": {}},
        "2026-02": {"kpi": {"total_cases": 50}, "anomalies": [{"hospital_id": "h1"}], "predictions": {}},
    }
    trends = analyze_trends(historical)
    assert len(trends) == 1
    assert trends[0].months == ["2026-02"]


def test_analyze_trends_hospital_without_anomalies():
    historical = {
        "2026-01": {"kpi": {"total_cases": 100}, "anomalies": [], "predictions": {}},
    }
    trends = analyze_trends(historical)
    assert len(trends) == 0


def test_analyze_trends_default_total_cases_zero():
    historical = {
        "2026-01": {
            "kpi": {},
            "anomalies": [{"hospital_id": "h1"}],
            "predictions": {},
        },
    }
    trends = analyze_trends(historical)
    assert len(trends) == 1
    assert trends[0].values["total_cases"] == [0]


# --- generate_comparison_chart Unit Tests ---

def test_generate_comparison_chart_empty():
    chart = generate_comparison_chart([], [])
    assert chart["type"] == "line"
    assert chart["data"]["labels"] == []
    assert chart["data"]["datasets"] == []


def test_generate_comparison_chart_with_trends():
    trend = TrendData(
        hospital_id="h1", hospital_name="Hospital",
        months=["2026-01", "2026-02"],
        values={"total_cases": [100, 200]},
    )
    chart = generate_comparison_chart([trend], [])
    assert chart["data"]["labels"] == ["2026-01", "2026-02"]
    assert len(chart["data"]["datasets"]) == 1
    assert chart["data"]["datasets"][0]["label"] == "Hospital"
    assert chart["data"]["datasets"][0]["data"] == [100, 200]


def test_generate_comparison_chart_limits_to_five_trends():
    trends = [
        TrendData(hospital_id=f"h{i}", hospital_name=f"H{i}",
                  months=["2026-01"], values={"total_cases": [i * 10]})
        for i in range(8)
    ]
    chart = generate_comparison_chart(trends, [])
    assert len(chart["data"]["datasets"]) == 5


def test_generate_comparison_chart_has_options():
    chart = generate_comparison_chart([], [])
    assert "responsive" in chart["options"]
    assert "plugins" in chart["options"]
    assert "scales" in chart["options"]
    assert chart["options"]["plugins"]["title"]["display"] is True


def _chart_color_for_seed(hospital_id, seed):
    """تشغيل توليد اللون في عملية فرعية بذرعة hash معينة وإرجاع borderColor."""
    import os, subprocess, sys, json
    code = (
        "import sys, json\n"
        "from app.engine.comparative.advanced_comparison import TrendData, generate_comparison_chart\n"
        "t = TrendData(hospital_id=sys.argv[1], hospital_name='H', months=['2026-01'], values={'total_cases':[1]})\n"
        "c = generate_comparison_chart([t], [])\n"
        "print(json.dumps(c['data']['datasets'][0]['borderColor']))\n"
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    r = subprocess.run(
        [sys.executable, "-c", code, hospital_id],
        capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def test_generate_comparison_chart_color_is_stable_across_processes():
    """ألوان المقارنة يجب أن تكون ثابتة عبر عمليات/إعادة تشغيل مختلفة —
    لا تتغير بسبب عشوائية hash() في بيثون (PYTHONHASHSEED)."""
    color_a = _chart_color_for_seed("h1", seed=1)
    color_b = _chart_color_for_seed("h1", seed=999)
    assert color_a == color_b, (
        f"Color changed across processes with different hash seeds: {color_a} != {color_b}"
    )


def test_generate_comparison_chart_color_format():
    """borderColor يجب أن تكون صيغة rgb صالحة بقيم داخل النطاق [0,255]."""
    import re
    chart = generate_comparison_chart([
        TrendData(hospital_id="h1", hospital_name="Hospital",
                  months=["2026-01"], values={"total_cases": [100]}),
    ], [])
    color = chart["data"]["datasets"][0]["borderColor"]
    m = re.match(r"^rgb\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})\)$", color)
    assert m, f"Unexpected color format: {color}"
    assert all(0 <= int(g) <= 255 for g in m.groups())


def test_generate_comparison_chart_colors_stable_for_different_ids():
    """ألوان مستشفيات مختلفة يجب أن تبقى صالحة ومستقرة، مع تنوّع كافٍ للتمييز."""
    import re
    trends = [
        TrendData(hospital_id=f"h{i}", hospital_name=f"H{i}",
                  months=["2026-01"], values={"total_cases": [i * 10]})
        for i in range(5)
    ]
    chart = generate_comparison_chart(trends, [])
    colors = [d["borderColor"] for d in chart["data"]["datasets"]]
    assert len(colors) == 5
    for color in colors:
        m = re.match(r"^rgb\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})\)$", color)
        assert m
        assert all(0 <= int(g) <= 255 for g in m.groups())
    assert len(set(colors)) >= 3


# --- Peer Comparison v2: Risk-Based Label Tests ---

def test_peer_risk_label_thresholds():
    """حواف مئين المخاطرة: 75/50/25 -> critical/high/moderate/low (نصوص ضرورية)."""
    # نختبر دالة التسمية مباشرة إن وُجدت، وإلا نختبر عبر بناء صفوف
    from app.engine.comparative.advanced_comparison import _risk_label
    assert _risk_label(100.0, "ar") == "حرج"
    assert _risk_label(75.0, "ar") == "حرج"
    assert _risk_label(74.9, "ar") == "عالي"
    assert _risk_label(50.0, "ar") == "عالي"
    assert _risk_label(49.9, "ar") == "متوسط"
    assert _risk_label(25.0, "ar") == "متوسط"
    assert _risk_label(24.9, "ar") == "منخفض"
    assert _risk_label(0.0, "ar") == "منخفض"
    assert _risk_label(100.0, "en") == "critical"
    assert _risk_label(60.0, "en") == "high"


# --- Peer Comparison v2: Scope Filtering Tests ---

from app.engine.comparative.advanced_comparison import compare_peers
from app.engine.smart.schemas import (
    SmartAnalyticsResult, SmartAnomalyResult, GovernorateAgg, GeoAggregationResult,
)


def _make_scope_analytics(anomalies):
    """يبني SmartAnalyticsResult ثابتاً بقائمة شذوذ مُتحكَّم بها."""
    return SmartAnalyticsResult(
        month="2026-06",
        hospitals_count=len(anomalies),
        anomalies=anomalies,
        clustering=MagicMock(),
        correlations=MagicMock(),
        residuals=[],
        stratified=[],
        explanations=[],
        geo=GeoAggregationResult(governorates=[]),
        kpi=MagicMock(),
    )


def _make_scope_anomaly(hospital_id, name, score):
    """يبني SmartAnomalyResult بدرجة تحكم محددة."""
    from app.engine.smart.schemas import SmartAnomalyResult
    return SmartAnomalyResult(
        hospital_name=name,
        hospital_id=hospital_id,
        governorate="X",
        hospital_type="Y",
        anomaly_score=score,
        method_scores={},
        severity="warning",
        is_outlier=True,
    )


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_governorate_filters_by_fk(mock_analytics, db_session):
    """نطاق governorate يُعيد فقط المستشفيات التي تشارك نفس governorate_id للمستشفى المرجعي."""
    from app.models import Hospital, Governorate, HospitalType

    gov_a = Governorate(name="Gov A")
    gov_b = Governorate(name="Gov B")
    db_session.add_all([gov_a, gov_b])
    db_session.flush()

    ref = Hospital(name="Ref Scope", is_active=True, governorate_id=gov_a.id)
    same = Hospital(name="Same Gov", is_active=True, governorate_id=gov_a.id)
    diff = Hospital(name="Diff Gov", is_active=True, governorate_id=gov_b.id)
    db_session.add_all([ref, same, diff])
    db_session.flush()

    anomalies = [
        _make_scope_anomaly(ref.id, "Ref Scope", 0.9),
        _make_scope_anomaly(same.id, "Same Gov", 0.7),
        _make_scope_anomaly(diff.id, "Diff Gov", 0.5),
    ]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    result = compare_peers(db_session, "2026-06", "governorate",
                           hospital_id=str(ref.id), analytics=mock_analytics.return_value)

    ids = {int(p.hospital_id) for p in result}
    # المستشفى المرجعي + مستشفى نفس المحافظة فقط
    assert ids == {ref.id, same.id}


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_type_filters_by_fk(mock_analytics, db_session):
    """نطاق type يُعيد فقط المستشفيات التي تشارك نفس hospital_type_id للمستشفى المرجعي."""
    from app.models import Hospital, Governorate, HospitalType

    t_a = HospitalType(name="Type A")
    t_b = HospitalType(name="Type B")
    db_session.add_all([t_a, t_b])
    db_session.flush()

    ref = Hospital(name="Ref Type", is_active=True, hospital_type_id=t_a.id)
    same = Hospital(name="Same Type", is_active=True, hospital_type_id=t_a.id)
    diff = Hospital(name="Diff Type", is_active=True, hospital_type_id=t_b.id)
    db_session.add_all([ref, same, diff])
    db_session.flush()

    anomalies = [
        _make_scope_anomaly(ref.id, "Ref Type", 0.9),
        _make_scope_anomaly(same.id, "Same Type", 0.7),
        _make_scope_anomaly(diff.id, "Diff Type", 0.5),
    ]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    result = compare_peers(db_session, "2026-06", "type",
                           hospital_id=str(ref.id), analytics=mock_analytics.return_value)

    ids = {int(p.hospital_id) for p in result}
    assert ids == {ref.id, same.id}


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_requires_hospital_id(mock_analytics, db_session):
    """نطاق governorate/type بدون hospital_id يُعيد [] ولا يكلّف الاستعلام عن المستشفى المرجعي."""
    anomalies = [_make_scope_anomaly(1, "H1", 0.5)]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    assert compare_peers(db_session, "2026-06", "governorate",
                         analytics=mock_analytics.return_value) == []
    assert compare_peers(db_session, "2026-06", "type",
                         analytics=mock_analytics.return_value) == []


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_missing_hospital_returns_empty(mock_analytics, db_session):
    """معرف مستشفى غير موجود يُعيد [] بأمان."""
    anomalies = [_make_scope_anomaly(1, "H1", 0.5)]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    assert compare_peers(db_session, "2026-06", "governorate",
                         hospital_id="999999", analytics=mock_analytics.return_value) == []


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_non_numeric_hospital_returns_empty(mock_analytics, db_session):
    """معرف غير رقمي لا يرفع ValueError بل يُعيد [] بأمان."""
    anomalies = [_make_scope_anomaly(1, "H1", 0.5)]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    assert compare_peers(db_session, "2026-06", "governorate",
                         hospital_id="abc", analytics=mock_analytics.return_value) == []


@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_compare_peers_scope_null_governorate_does_not_match(mock_analytics, db_session):
    """مستشفى بلا محافظة (governorate_id=None) لا يطابق مستشفى بمحافظة محددة — مقارنة FK تفصل القيم الفارغة عن القيم الفعلية.

    ملاحظة: عند مقارنة مستشفيين كلاهما بلا محافظة (None != None -> False) يتطابقان؛
    هذا سلوك متأصل متساوٍ في المقارنة الجديدة (FK) والقديمة (كائن العلاقة)،
    وليس خطراً جديداً — نتحقق هنا فقط من أن القيمة الفارغة لا تطابق قيمة محددة."""
    from app.models import Hospital, Governorate

    gov_a = Governorate(name="Gov A")
    db_session.add(gov_a)
    db_session.flush()

    ref = Hospital(name="Ref No Gov", is_active=True)
    ref.governorate_id = None
    with_gov = Hospital(name="With Gov", is_active=True, governorate_id=gov_a.id)
    db_session.add_all([ref, with_gov])
    db_session.flush()

    anomalies = [
        _make_scope_anomaly(ref.id, "Ref No Gov", 0.9),
        _make_scope_anomaly(with_gov.id, "With Gov", 0.7),
    ]
    mock_analytics.return_value = _make_scope_analytics(anomalies)

    result = compare_peers(db_session, "2026-06", "governorate",
                           hospital_id=str(ref.id), analytics=mock_analytics.return_value)

    # المرجع بلا محافظة — مستشفيان فقط، فلن يشمل مستشفى بمحافظة مختلفة
    assert all(int(p.hospital_id) != with_gov.id for p in result)


# --- Endpoint Error Handling Tests ---

@patch("app.engine.comparative.advanced_comparison.run_smart_analytics")
def test_advanced_comparison_endpoint_error_handling(mock_analytics, client):
    mock_analytics.side_effect = RuntimeError("Database error")
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 500
    assert "خطأ في المقارنة" in response.json()["detail"]


def test_advanced_comparison_endpoint_response_structure(client):
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["comparison_data"], dict)
    assert isinstance(data["comparison_data"]["trends"], list)
    assert isinstance(data["comparison_data"]["peer_comparison"], list)
    assert isinstance(data["comparison_data"]["predictions"], dict)
    assert isinstance(data["chart_config"], dict)


def test_advanced_comparison_trends_structure(client):
    response = client.get("/comparative/advanced-comparison/2026-06")
    data = response.json()
    for trend in data["comparison_data"]["trends"]:
        assert "hospital_id" in trend
        assert "hospital_name" in trend
        assert "months" in trend
        assert "values" in trend
        assert isinstance(trend["months"], list)
        assert isinstance(trend["values"], dict)


def test_advanced_comparison_peer_comparison_structure(client):
    response = client.get("/comparative/advanced-comparison/2026-06")
    data = response.json()
    for peer in data["comparison_data"]["peer_comparison"]:
        assert "hospital_id" in peer
        assert "hospital_name" in peer
        assert "percentile" in peer
        assert "rank" in peer
        assert "total_hospitals" in peer
        assert "comparison_label" in peer


def test_advanced_comparison_chart_has_required_keys(client):
    response = client.get("/comparative/advanced-comparison/2026-06")
    data = response.json()
    chart = data["chart_config"]
    assert chart["type"] == "line"
    assert "labels" in chart["data"]
    assert "datasets" in chart["data"]
    assert isinstance(chart["data"]["labels"], list)
    assert isinstance(chart["data"]["datasets"], list)


# --- English Report Tests ---


def test_build_english_prompt_returns_string(db_session):
    """اختبار أن prompt الإنجليزية تُعيد نص"""
    from app.engine.comparative.report_generator import build_comprehensive_prompt
    from app.engine.smart import run_smart_analytics

    analytics = run_smart_analytics(db_session, "2026-06")
    prompt = build_comprehensive_prompt(analytics, "en")
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert "Executive Summary" in prompt


def test_generate_comprehensive_report_english(db_session):
    """اختبار توليد تقرير بالإنجليزية"""
    result = generate_comprehensive_report(db_session, "2026-06", lang="en")
    assert "month" in result
    assert "report" in result
    assert "data" in result


def test_comprehensive_report_endpoint_english(client):
    """اختبار endpoint بالإنجليزية"""
    response = client.get("/comparative/comprehensive-report/2026-06?lang=en")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data


# --- Local Fallback Report Tests ---

from app.engine.comparative.report_generator import _build_local_report


def test_local_fallback_report_arabic_has_sections(db_session):
    """اختبار أن التقرير المحلي يحتوي على الأقسام الرئيسية"""
    from app.engine.smart import run_smart_analytics
    analytics = run_smart_analytics(db_session, "2026-06")
    report = _build_local_report(analytics, "ar")
    assert "الملخص التنفيذي" in report
    assert "تحليل الشذوذ" in report
    assert "التجميع" in report
    assert "التوصيات" in report
    assert len(report) > 300


def test_local_fallback_report_english_has_sections(db_session):
    """اختبار أن التقرير المحلي بالإنجليزية يحتوي على الأقسام الرئيسية"""
    from app.engine.smart import run_smart_analytics
    analytics = run_smart_analytics(db_session, "2026-06")
    report = _build_local_report(analytics, "en")
    assert "Executive Summary" in report
    assert "Anomaly Analysis" in report
    assert "Clustering" in report
    assert "Recommendations" in report
    assert len(report) > 300


def test_local_fallback_report_contains_kpi_data(db_session):
    """اختبار أن التقرير المحلي يتضمن بيانات KPI الفعلية"""
    from app.engine.smart import run_smart_analytics
    analytics = run_smart_analytics(db_session, "2026-06")
    report = _build_local_report(analytics, "ar")
    assert str(analytics.kpi.total_anomalies) in report
    assert str(analytics.kpi.month_status) in report


def test_generate_report_falls_back_to_local_when_ai_fails(client):
    """اختبار أن التقرير يستخدم البديل المحلي عند فشل الذكاء الاصطناعي"""
    from app.engine.comparative.report_generator import _call_api
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "الملخص التنفيذي" in data["report"]
    assert data["report_source"] == "local"


def test_generate_report_falls_back_when_ai_raises(client):
    """اختبار أن التقرير يستخدم البديل المحلي عند استثناء الذكاء الاصطناعي"""
    from app.engine.comparative.report_generator import _call_api
    with patch("app.engine.comparative.report_generator._call_api", side_effect=Exception("API error")):
        response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "الملخص التنفيذي" in data["report"]
    assert data["report_source"] == "local"


# --- Frontend Structure Tests (Task 3) ---


def test_comparative_html_has_collapsible_sections():
    """اختبار أن HTML المدمج يحتوي على أقسام قابلة للطي"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'smart-analytics.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    sections = soup.find_all('div', class_='smart-section-card')
    assert len(sections) >= 5


def test_comparative_html_has_kpi_dashboard():
    """اختبار أن HTML المدمج يحتوي على لوحة تحكم التقرير"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'smart-analytics.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    kpi_grid = soup.find('div', id='smart-report-kpi-dashboard')
    assert kpi_grid is not None


def test_comparative_js_has_toggle_function():
    """اختبار أن وحدات smart تحتوي على دوال التحكم والمقارنة"""
    import os
    core_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'smart', 'core.js')
    with open(core_path, 'r', encoding='utf-8') as f:
        core = f.read()
    assert 'toggleSmartSection' in core
    assert 'setSmartMode' in core

    report_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'smart', 'report.js')
    with open(report_path, 'r', encoding='utf-8') as f:
        report = f.read()
    assert 'renderComparison' in report
    assert 'smart-comparison-type' in report
    assert 'window.smartGenerateComprehensiveReport' in report


# --- Report Persistence Cache Tests ---


def test_report_cache_store_and_get(db_session):
    from app.engine.comparative.report_cache import store_report, get_stored_report
    result = {"month": "2026-06", "report": "text", "report_source": "ai", "data": {"kpi": {}}}
    store_report(db_session, "2026-06", "ar", result)
    cached = get_stored_report(db_session, "2026-06", "ar")
    assert cached == result


def test_report_cache_get_missing(db_session):
    from app.engine.comparative.report_cache import get_stored_report
    assert get_stored_report(db_session, "2026-06", "ar") is None


def test_report_cache_separated_by_lang(db_session):
    from app.engine.comparative.report_cache import store_report, get_stored_report
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "ar"})
    store_report(db_session, "2026-06", "en", {"month": "2026-06", "report": "en"})
    assert get_stored_report(db_session, "2026-06", "ar")["report"] == "ar"
    assert get_stored_report(db_session, "2026-06", "en")["report"] == "en"


def test_report_cache_invalidate_month(db_session):
    from app.engine.comparative.report_cache import (
        store_report, get_stored_report, invalidate_report_cache,
    )
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "r"})
    store_report(db_session, "2026-05", "ar", {"month": "2026-05", "report": "r"})
    invalidate_report_cache(db_session, "2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is None
    assert get_stored_report(db_session, "2026-05", "ar") is not None


def test_report_cache_invalidate_all(db_session):
    from app.engine.comparative.report_cache import (
        store_report, get_stored_report, invalidate_report_cache,
    )
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "r"})
    store_report(db_session, "2026-05", "en", {"month": "2026-05", "report": "r"})
    invalidate_report_cache(db_session)
    assert get_stored_report(db_session, "2026-06", "ar") is None
    assert get_stored_report(db_session, "2026-05", "en") is None


def test_report_cache_sanitizes_numpy_types(db_session):
    import numpy as np
    from app.engine.comparative.report_cache import store_report, get_stored_report
    result = {
        "month": "2026-06",
        "report": "x",
        "report_source": "ai",
        "data": {
            "score": np.float64(0.45),
            "count": np.int64(7),
            "arr": np.array([1.0, 2.5, 3.0]),
        },
    }
    store_report(db_session, "2026-06", "ar", result)
    cached = get_stored_report(db_session, "2026-06", "ar")
    assert cached["data"]["score"] == 0.45
    assert isinstance(cached["data"]["score"], float)
    assert cached["data"]["count"] == 7
    assert isinstance(cached["data"]["count"], int)
    assert cached["data"]["arr"] == [1.0, 2.5, 3.0]
    assert isinstance(cached["data"]["arr"], list)
    assert all(isinstance(v, float) for v in cached["data"]["arr"])


# --- Report Persistence Generator Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_report_cache_hit_returns_stored_without_ai(mock_api, db_session):
    mock_api.return_value = "تقرير AI مخزن"
    first = generate_comprehensive_report(db_session, "2026-06")
    assert first["report_source"] == "ai"
    assert mock_api.call_count == 1
    second = generate_comprehensive_report(db_session, "2026-06")
    assert second["report"] == first["report"]
    assert second["report_source"] == first["report_source"]
    assert mock_api.call_count == 1


@patch("app.engine.comparative.report_generator._call_api")
def test_report_cache_separated_by_lang(mock_api, db_session):
    mock_api.return_value = "AI report"
    generate_comprehensive_report(db_session, "2026-06", lang="ar")
    generate_comprehensive_report(db_session, "2026-06", lang="en")
    assert mock_api.call_count == 2


@patch("app.engine.comparative.report_generator._call_api")
def test_local_fallback_not_stored(mock_api, db_session):
    mock_api.return_value = None
    first = generate_comprehensive_report(db_session, "2026-06")
    assert first["report_source"] == "local"
    mock_api.return_value = "تقرير AI"
    second = generate_comprehensive_report(db_session, "2026-06")
    assert second["report_source"] == "ai"
    assert mock_api.call_count == 2


@patch("app.engine.comparative.report_generator._call_api")
def test_use_cache_false_regenerates(mock_api, db_session):
    mock_api.return_value = "الأول"
    generate_comprehensive_report(db_session, "2026-06")
    mock_api.return_value = "الثاني"
    result = generate_comprehensive_report(db_session, "2026-06", use_cache=False)
    assert "الثاني" in result["report"]
    assert mock_api.call_count == 2


# --- Report Persistence Endpoint Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_report_endpoint_force_regenerates(mock_api, client):
    mock_api.return_value = "الأول"
    r1 = client.get("/comparative/comprehensive-report/2026-06")
    assert r1.status_code == 200
    assert "الأول" in r1.json()["report"]
    assert mock_api.call_count == 1
    mock_api.return_value = "الثاني"
    r2 = client.get("/comparative/comprehensive-report/2026-06?force=true")
    assert r2.status_code == 200
    assert "الثاني" in r2.json()["report"]
    assert mock_api.call_count == 2


# --- Report Persistence Upload Invalidation Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_upload_save_invalidates_report_cache(mock_api, client, db_session):
    from app.engine.comparative.report_cache import get_stored_report
    mock_api.return_value = "تقرير AI"
    client.get("/comparative/comprehensive-report/2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is not None
    resp = client.post(
        "/upload/data-entry/save",
        params={"hospital_id": 1, "month": "2026-06", "data": json.dumps({"2": 300})},
    )
    assert resp.status_code == 200
    assert get_stored_report(db_session, "2026-06", "ar") is None


@patch("app.engine.comparative.report_generator._call_api")
def test_upload_excel_invalidates_report_cache(mock_api, client, db_session):
    import io
    import pandas as pd
    from app.engine.comparative.report_cache import get_stored_report
    mock_api.return_value = "تقرير AI"
    client.get("/comparative/comprehensive-report/2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is not None
    df = pd.DataFrame({
        "organisationunitname": ["General Hospital"],
        "month": ["2026-06"],
        "Total Deliveries": [300],
        "Normal Vaginal Deliveries": [200],
        "Caesarean Sections": [80],
        "Live Births": [290],
        "Maternal Deaths": [1],
        "Neonatal deaths": [5],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    resp = client.post(
        "/upload/",
        files={"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert get_stored_report(db_session, "2026-06", "ar") is None
    uploaded = os.path.join(os.path.dirname(__file__), "..", "data", "uploads", "test.xlsx")
    try:
        if os.path.exists(uploaded):
            os.remove(uploaded)
    except OSError:
        pass  # Windows may briefly lock the file; cleanup is best-effort


# --- Composite Patterns in Report Tests ---

def _seed_pattern_hospitals(db_session, month="2026-06"):
    """بذر 8 مستشفيات: نصفها بارتفاع متزامن في القيصرية + الولادات المبكرة + وفيات المولودين."""
    from app.models import Hospital, IndicatorValue, Indicator
    code_to_id = {ind.code: ind.id for ind in db_session.query(Indicator).all()}
    hospitals = [h for h in db_session.query(Hospital).all()]
    for i in range(8):
        if i < len(hospitals):
            h = hospitals[i]
        else:
            h = Hospital(name=f"Pattern H{i}", is_active=True)
            db_session.add(h)
        h.is_active = True
        db_session.flush()
        high = i < 4
        vals = {"2": 200, "5": 80 if high else 24, "6": 190,
                "10": 5 if high else 1, "11": 1 if high else 0,
                "17": 5 if high else 0, "7": 2 if high else 0,
                "6.f": 40 if high else 8, "6.g": 30 if high else 6,
                "2.n": 10, "2.c": 3, "2.d": 2}
        for code, value in vals.items():
            ind_id = code_to_id.get(code)
            if ind_id is None:
                continue
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind_id, month=month, value=value
            ))
    db_session.commit()


def test_local_report_includes_composite_patterns_section(db_session):
    """التقرير المحلي يعرض قسم الأنماط المركبة مع توليفات المؤشرات بجملة عربية."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_pattern_hospitals(db_session)
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report_source"] == "local"
    report = result["report"]
    assert "الأنماط المركبة للمؤشرات" in report
    assert "نمط متكرر" in report
    assert "معدل القيصارية" in report
    assert "Lift" in report


@patch("app.engine.comparative.report_generator._call_api")
def test_prompt_includes_composite_patterns_section(mock_api, db_session):
    """الـ prompt يتضمن قسم الأنماط المركبة مع التوليفات والأرقام الفعلية."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_pattern_hospitals(db_session)
    mock_api.return_value = "تقرير تجريبي"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_api.call_args[0][0]
    assert "الأنماط المركبة للمؤشرات" in prompt_arg
    assert "نمط متكرر" in prompt_arg
    assert "Lift" in prompt_arg
    assert "مستشفى" in prompt_arg


def test_report_data_includes_patterns_field(db_session):
    """استجابة التقرير تتضمن حقل patterns كقائمة قواميس سليمة."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_pattern_hospitals(db_session)
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        result = generate_comprehensive_report(db_session, "2026-06")
    patterns = result["data"]["patterns"]
    assert isinstance(patterns, list)
    # بيانات البذر تُنتج أنماطاً فعلاً — لا نجعل الشرط اختيارياً حتى لا ينحدر صامتاً
    assert len(patterns) >= 1
    p = patterns[0]
    assert isinstance(p, dict)
    assert "indicators" in p and "support" in p and "lift" in p
    assert p["hospitals_count"] >= 2
    json.dumps(result, ensure_ascii=False)


def test_english_local_report_includes_composite_patterns(db_session):
    """التقرير المحلي الإنجليزي يعرض قسم الأنماط المركبة."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_pattern_hospitals(db_session)
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        result = generate_comprehensive_report(db_session, "2026-06", lang="en")
    report = result["report"]
    assert "Composite Indicator Patterns" in report
    assert "Recurring pattern" in report
    assert "Lift" in report


# --- Enriched Report Tests (real indicator stats + monthly trends) ---


def _seed_indicator_values(db_session, month, values_by_hospital):
    """بذر قيم مؤشرات خام لشهر معين: {hospital_name: {code: value}}"""
    from app.models import IndicatorValue, Indicator, Hospital
    code_to_id = {ind.code: ind.id for ind in db_session.query(Indicator).all()}
    hospitals = {h.name: h for h in db_session.query(Hospital).all()}
    for name, vals in values_by_hospital.items():
        if name not in hospitals:
            continue
        h = hospitals[name]
        h.is_active = True
        for code, value in vals.items():
            ind_id = code_to_id.get(code)
            if ind_id is None:
                continue
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind_id, month=month, value=value
            ))
    db_session.commit()


def test_local_report_includes_real_indicator_stats(db_session):
    """التقرير المحلي يعرض قيماً فعلية للمؤشرات (متوسط/أدنى/أعلى) بدل الأسماء فقط."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_indicator_values(db_session, "2026-06", {
        "General Hospital": {"2": 200, "5": 50, "6": 190},
        "Central Medical": {"2": 150, "5": 20, "6": 140},
        "Community Clinic": {"2": 100, "5": 15, "6": 95},
    })
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report_source"] == "local"
    report = result["report"]
    assert "القيم الفعلية لشهر التقرير" in report
    assert "معدل القيصارية" in report
    assert "المتوسط" in report
    # cs_rate = (5/2)*100: 25.0% و13.33% و15.0% → المتوسط ≈ 17.78%
    assert "17.78" in report


def test_local_report_includes_monthly_trends(db_session):
    """التقرير المحلي يعرض مقارنة بالأشهر السابقة عند توفر بيانات."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_indicator_values(db_session, "2026-05", {
        "General Hospital": {"2": 200, "5": 40, "6": 190},
        "Central Medical": {"2": 150, "5": 15, "6": 140},
        "Community Clinic": {"2": 100, "5": 10, "6": 95},
    })
    _seed_indicator_values(db_session, "2026-06", {
        "General Hospital": {"2": 200, "5": 60, "6": 190},
        "Central Medical": {"2": 150, "5": 25, "6": 140},
        "Community Clinic": {"2": 100, "5": 12, "6": 95},
    })
    with patch("app.engine.comparative.report_generator._call_api", return_value=None):
        result = generate_comprehensive_report(db_session, "2026-06")
    report = result["report"]
    assert "الاتجاهات الشهرية" in report
    assert "أسرع مؤشر ارتفاعاً" in report
    assert "2026-05" in report


@patch("app.engine.comparative.report_generator._call_api")
def test_prompt_includes_indicator_stats(mock_api, db_session):
    """الـ prompt يتضمن إحصاءات المؤشرات الفعلية والاتجاهات الشهرية."""
    from app.engine.comparative.report_generator import generate_comprehensive_report
    _seed_indicator_values(db_session, "2026-05", {
        "General Hospital": {"2": 200, "5": 40, "6": 190},
        "Central Medical": {"2": 150, "5": 15, "6": 140},
        "Community Clinic": {"2": 100, "5": 10, "6": 95},
    })
    _seed_indicator_values(db_session, "2026-06", {
        "General Hospital": {"2": 200, "5": 60, "6": 190},
        "Central Medical": {"2": 150, "5": 25, "6": 140},
        "Community Clinic": {"2": 100, "5": 12, "6": 95},
    })
    mock_api.return_value = "تقرير تجريبي"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_api.call_args[0][0]
    assert "بيانات المؤشرات الفعلية" in prompt_arg
    assert "الاتجاهات الشهرية" in prompt_arg
    assert "معدل القيصارية" in prompt_arg
    assert "المتوسط" in prompt_arg
