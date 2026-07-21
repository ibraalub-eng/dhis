import pytest
import numpy as np
from app.engine.smart.correlations import analyze_correlations


@pytest.fixture
def sample_data():
    np.random.seed(42)
    n = 10
    data = {}
    for i in range(n):
        cs_rate = np.random.uniform(20, 40)
        smm = cs_rate * 0.15 + np.random.normal(0, 1)
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": "Gaza",
            "hospital_type": "general",
            "values": {
                "cs_rate": cs_rate,
                "smm_total": max(0, smm),
                "mat_deaths": max(0, smm * 0.1),
                "nd": np.random.uniform(0, 5),
                "sb": np.random.uniform(0, 2),
                "preterm": np.random.uniform(5, 15),
                "lbw": np.random.uniform(4, 12),
                "total_births": np.random.uniform(100, 300),
                "high_risk": np.random.uniform(5, 25),
                "adolescent": np.random.uniform(1, 8),
            },
        }
    return data


@pytest.fixture
def default_config():
    return {}


def test_returns_correlation_result(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert result is not None
    assert len(result.indicators) > 0


def test_matrix_is_symmetric(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    for ind_a in result.matrix:
        for ind_b in result.matrix[ind_a]:
            if ind_b in result.matrix and ind_a in result.matrix[ind_b]:
                v1 = result.matrix[ind_a][ind_b]
                v2 = result.matrix[ind_b][ind_a]
                assert abs(v1 - v2) < 0.001


def test_strong_correlation_detected(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    strong = [c for c in result.strong_correlations if abs(c.pearson_r) > 0.5]
    assert len(strong) > 0


def test_feature_importance_present(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert len(result.feature_importance) > 0
    for fi in result.feature_importance:
        assert len(fi.features) > 0


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = analyze_correlations(data, {})
    assert result is not None
    assert len(result.strong_correlations) == 0