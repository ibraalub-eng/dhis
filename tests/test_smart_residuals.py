import pytest
import numpy as np
from app.engine.smart.residual import analyze_residuals


@pytest.fixture
def sample_data():
    np.random.seed(42)
    data = {}
    governorates = ["Gaza", "Gaza", "Gaza", "North Gaza", "North Gaza",
                    "Khan Younis", "Khan Younis", "Rafah", "Deir al-Balah", "Deir al-Balah"]
    types = ["general", "general", "specialist", "general", "general",
             "general", "specialist", "general", "general", "general"]
    for i in range(10):
        base = 25.0
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": governorates[i],
            "hospital_type": types[i],
            "values": {
                "cs_rate": base + np.random.normal(0, 3),
                "smm_total": 5.0 + np.random.normal(0, 1),
                "mat_deaths": 1.0 + np.random.normal(0, 0.3),
                "nd": 2.0 + np.random.normal(0, 0.5),
                "sb": 1.0 + np.random.normal(0, 0.3),
                "preterm": 10.0 + np.random.normal(0, 2),
                "lbw": 8.0 + np.random.normal(0, 1.5),
                "total_births": 200.0 + np.random.normal(0, 20),
                "high_risk": 15.0 + np.random.normal(0, 3),
                "adolescent": 3.0 + np.random.normal(0, 1),
            },
        }
    data["Hospital 0"]["values"]["cs_rate"] = 60.0
    return data


def test_returns_list_of_residual_results(sample_data):
    results = analyze_residuals(sample_data, {})
    assert isinstance(results, list)
    assert len(results) > 0


def test_outlier_detected(sample_data):
    results = analyze_residuals(sample_data, {})
    hospital_0 = [r for r in results if r.hospital_name == "Hospital 0" and r.indicator == "cs_rate"]
    assert len(hospital_0) > 0
    assert hospital_0[0].is_anomaly is True


def test_normal_hospital_not_flagged(sample_data):
    results = analyze_residuals(sample_data, {})
    hospital_5 = [r for r in results if r.hospital_name == "Hospital 5" and r.indicator == "cs_rate"]
    assert len(hospital_5) > 0
    assert hospital_5[0].is_anomaly is False


def test_residual_equals_actual_minus_predicted(sample_data):
    results = analyze_residuals(sample_data, {})
    for r in results:
        expected = r.actual_value - r.predicted_value
        assert abs(r.residual - expected) < 0.001


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = analyze_residuals(data, {})
    assert results == []
