"""Tests for the comprehensive smart report generator."""
import pytest
from unittest.mock import patch, MagicMock
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


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_generate_comprehensive_report_uses_gemini(mock_gemini, db_session):
    mock_gemini.return_value = "تقرير تجريبي بالعربية"
    result = generate_comprehensive_report(db_session, "2026-06")
    assert mock_gemini.called
    assert result["report"] == "تقرير تجريبي بالعربية"


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_generate_comprehensive_report_handles_gemini_failure(mock_gemini, db_session):
    mock_gemini.return_value = None
    result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report"] == "خطأ في توليد التقرير"


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_generate_comprehensive_report_error_handling(mock_gemini, db_session):
    mock_gemini.side_effect = Exception("API error")
    with pytest.raises(Exception, match="API error"):
        generate_comprehensive_report(db_session, "2026-06")


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


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_endpoint_uses_gemini(mock_gemini, client):
    mock_gemini.return_value = "تقرير تجريبي بالعربية"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert mock_gemini.called
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


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_uses_gemini(mock_gemini, client):
    mock_gemini.return_value = "تقرير تجريبي بالعربية"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert mock_gemini.called


@patch("app.engine.comparative.report_generator.run_smart_analytics")
def test_comprehensive_report_error_handling(mock_analytics, client):
    mock_analytics.side_effect = RuntimeError("Database error")
    response = client.get("/comparative/comprehensive-report/2026-99")
    assert response.status_code == 500
    assert "خطأ في توليد التقرير" in response.json()["detail"]


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_returns_arabic_report(mock_gemini, client):
    mock_gemini.return_value = "تقرير التحليل الشامل لشهر يونيو"
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert "تقرير" in response.json()["report"]


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_month_passthrough(mock_gemini, db_session):
    mock_gemini.return_value = "report"
    result = generate_comprehensive_report(db_session, "2026-03")
    assert result["month"] == "2026-03"


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_data_types(mock_gemini, db_session):
    mock_gemini.return_value = "test"
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


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_prompt_contains_all_sections(mock_gemini, db_session):
    mock_gemini.return_value = "report"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_gemini.call_args[0][0]
    assert "cs_rate" in prompt_arg
    assert "smm_total" in prompt_arg
    assert "mat_deaths" in prompt_arg
    assert "الملخص التنفيذي" in prompt_arg
    assert "تحليل الشذوذ" in prompt_arg
    assert "التجميع" in prompt_arg
    assert "الارتباطات" in prompt_arg


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_prompt_in_arabic(mock_gemini, db_session):
    mock_gemini.return_value = "report"
    generate_comprehensive_report(db_session, "2026-06")
    prompt_arg = mock_gemini.call_args[0][0]
    assert "أنت خبير" in prompt_arg
    assert "العربية" in prompt_arg


@patch("app.engine.comparative.report_generator.run_smart_analytics")
def test_comprehensive_report_propagates_analytics_error(mock_analytics, client):
    mock_analytics.side_effect = ValueError("Invalid data")
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 500


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_default_error_text(mock_gemini, db_session):
    mock_gemini.return_value = ""
    result = generate_comprehensive_report(db_session, "2026-06")
    assert result["report"] == "خطأ في توليد التقرير"


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
