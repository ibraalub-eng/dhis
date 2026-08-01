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


@patch("app.engine.comparative.report_generator._call_api")
def test_generate_comprehensive_report_uses_ai(mock_api, db_session):
    mock_api.return_value = "تقرير تجريبي بالعربية"
    result = generate_comprehensive_report(db_session, "2026-06")
    assert mock_api.called
    assert result["report"] == "تقرير تجريبي بالعربية"
    assert result["report_source"] == "ai"


@patch("app.engine.comparative.report_generator._call_api")
def test_generate_comprehensive_report_handles_ai_failure(mock_api, db_session):
    mock_api.return_value = None
    result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report"] != "خطأ في توليد التقرير"
    assert "الملخص التنفيذي" in result["report"]
    assert result["report_source"] == "local"


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
    assert response.json()["report"] == "تقرير تجريبي بالعربية"


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
        comparison_label="متفوق",
    )
    assert p.percentile == 25.0
    assert p.comparison_label == "متفوق"


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


# --- Peer Comparison Label Tests ---

def test_peer_comparison_label_percentile_25():
    p = PeerComparison("h1", "H1", 25.0, 1, 4, "متفوق")
    assert p.comparison_label == "متفوق"


def test_peer_comparison_label_percentile_50():
    p = PeerComparison("h1", "H1", 50.0, 2, 4, "متوسط")
    assert p.comparison_label == "متوسط"


def test_peer_comparison_label_percentile_75():
    p = PeerComparison("h1", "H1", 75.0, 3, 4, "يحتاج تحسين")
    assert p.comparison_label == "يحتاج تحسين"


def test_peer_comparison_label_percentile_100():
    p = PeerComparison("h1", "H1", 100.0, 4, 4, "حرج")
    assert p.comparison_label == "حرج"


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
    """اختبار أن HTML يحتوي على أقسام قابلة للطي"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'comparative.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    sections = soup.find_all('div', class_='collapsible-section')
    assert len(sections) >= 5


def test_comparative_html_has_kpi_dashboard():
    """اختبار أن HTML يحتوي على لوحة تحكم"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'comparative.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    kpi_grid = soup.find('div', id='kpi-dashboard')
    assert kpi_grid is not None


def test_comparative_js_has_toggle_function():
    """اختبار أن JavaScript يحتوي على دوال التحكم"""
    js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'comparative.js')
    with open(js_path, 'r', encoding='utf-8') as f:
        content = f.read()

    assert 'function toggleSection' in content
    assert 'function showAlert' in content
    assert 'function updateKPIDashboard' in content
    assert 'function renderReportSections' in content


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
        "data": {"score": np.float64(0.45), "count": np.int64(7)},
    }
    store_report(db_session, "2026-06", "ar", result)
    cached = get_stored_report(db_session, "2026-06", "ar")
    assert cached["data"]["score"] == 0.45
    assert isinstance(cached["data"]["score"], float)
    assert cached["data"]["count"] == 7
    assert isinstance(cached["data"]["count"], int)


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
    assert result["report"] == "الثاني"
    assert mock_api.call_count == 2


# --- Report Persistence Endpoint Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_report_endpoint_force_regenerates(mock_api, client):
    mock_api.return_value = "الأول"
    r1 = client.get("/comparative/comprehensive-report/2026-06")
    assert r1.status_code == 200
    assert r1.json()["report"] == "الأول"
    assert mock_api.call_count == 1
    mock_api.return_value = "الثاني"
    r2 = client.get("/comparative/comprehensive-report/2026-06?force=true")
    assert r2.status_code == 200
    assert r2.json()["report"] == "الثاني"
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
    if os.path.exists(uploaded):
        os.remove(uploaded)
