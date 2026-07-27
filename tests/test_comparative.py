"""Tests for the comprehensive smart report generator."""
import pytest
from unittest.mock import patch, MagicMock
from app.engine.comparative import generate_comprehensive_report


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
