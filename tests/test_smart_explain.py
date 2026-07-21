import pytest
from app.engine.smart.schemas import SmartAnomalyResult
from app.engine.smart.explainability import explain_anomalies


@pytest.fixture
def sample_anomalies():
    return [
        SmartAnomalyResult(
            hospital_name="Hospital 0", hospital_id=0,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.8, severity="critical", is_outlier=True,
            method_scores={"isolation_forest": 0.9, "lof": 0.7, "mahalanobis": 0.6, "residual": 0.5},
        ),
        SmartAnomalyResult(
            hospital_name="Hospital 1", hospital_id=1,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.2, severity="normal", is_outlier=False,
            method_scores={"isolation_forest": 0.1, "lof": 0.2, "mahalanobis": 0.3, "residual": 0.1},
        ),
    ]


@pytest.fixture
def sample_data():
    import numpy as np
    np.random.seed(42)
    data = {}
    for i in range(8):
        data[f"Hospital {i}"] = {
            "hospital_id": i, "governorate": "Gaza", "hospital_type": "general",
            "values": {
                "cs_rate": 25.0 + i * 2 + np.random.normal(0, 1),
                "smm_total": 5.0 + np.random.normal(0, 0.5),
                "mat_deaths": 1.0 + np.random.normal(0, 0.2),
                "nd": 2.0 + np.random.normal(0, 0.3),
                "sb": 1.0, "preterm": 10.0, "lbw": 8.0,
                "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0,
            },
        }
    return data


def test_explanations_for_outliers_only(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results) == 1
    assert results[0].hospital_name == "Hospital 0"


def test_top_factors_present(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].top_factors) > 0
    assert len(results[0].top_factors) <= 3


def test_text_explanation_in_arabic(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].text_explanation) > 0


def test_disabled_returns_empty(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": False})
    assert results == []


def test_no_outliers_returns_empty(sample_data):
    anomalies = [
        SmartAnomalyResult(
            hospital_name="H", hospital_id=1, governorate="G", hospital_type="t",
            anomaly_score=0.1, severity="normal", is_outlier=False, method_scores={},
        )
    ]
    results = explain_anomalies(anomalies, sample_data, {"shap_enabled": True})
    assert results == []
