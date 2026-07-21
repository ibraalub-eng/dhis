import pytest
from app.engine.smart.anomaly import detect_smart_anomalies


@pytest.fixture
def sample_data():
    return {
        "Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0, "smm_total": 5.0, "mat_deaths": 1.0, "nd": 2.0, "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0}},
        "Hospital B": {"hospital_id": 2, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 25.0, "smm_total": 3.0, "mat_deaths": 0.0, "nd": 1.0, "sb": 0.5, "preterm": 8.0, "lbw": 6.0, "total_births": 180.0, "high_risk": 12.0, "adolescent": 2.0}},
        "Hospital C": {"hospital_id": 3, "governorate": "North Gaza", "hospital_type": "general", "values": {"cs_rate": 28.0, "smm_total": 4.0, "mat_deaths": 0.5, "nd": 1.5, "sb": 0.8, "preterm": 9.0, "lbw": 7.0, "total_births": 190.0, "high_risk": 13.0, "adolescent": 2.5}},
        "Hospital D": {"hospital_id": 4, "governorate": "Khan Younis", "hospital_type": "specialist", "values": {"cs_rate": 22.0, "smm_total": 2.0, "mat_deaths": 0.0, "nd": 0.5, "sb": 0.3, "preterm": 6.0, "lbw": 5.0, "total_births": 150.0, "high_risk": 10.0, "adolescent": 1.5}},
        "Hospital E": {"hospital_id": 5, "governorate": "Rafah", "hospital_type": "general", "values": {"cs_rate": 60.0, "smm_total": 15.0, "mat_deaths": 3.0, "nd": 8.0, "sb": 4.0, "preterm": 25.0, "lbw": 20.0, "total_births": 100.0, "high_risk": 30.0, "adolescent": 10.0}},
    }


@pytest.fixture
def default_config():
    return {
        "contamination": 0.05,
        "lof_neighbors": 5,
        "threshold_green": 0.3,
        "threshold_yellow": 0.6,
        "ensemble_if_weight": 0.35,
        "ensemble_lof_weight": 0.30,
        "ensemble_mahal_weight": 0.20,
        "ensemble_residual_weight": 0.15,
    }


def test_returns_list_of_smart_anomaly_result(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    assert isinstance(results, list)
    assert len(results) == 5


def test_outlier_hospital_flagged(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    hospital_e = next(r for r in results if r.hospital_name == "Hospital E")
    assert hospital_e.is_outlier is True
    assert hospital_e.severity in ("warning", "critical")


def test_normal_hospital_not_flagged(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    hospital_b = next(r for r in results if r.hospital_name == "Hospital B")
    assert hospital_b.severity == "normal"


def test_anomaly_score_between_0_and_1(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert 0.0 <= r.anomaly_score <= 1.0


def test_method_scores_present(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert "isolation_forest" in r.method_scores
        assert "lof" in r.method_scores
        assert "mahalanobis" in r.method_scores


def test_disabled_returns_empty(default_config):
    results = detect_smart_anomalies({}, default_config, enabled=False)
    assert results == []


def test_too_few_hospitals_returns_empty(default_config):
    data = {"Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = detect_smart_anomalies(data, default_config)
    assert results == []


def test_severity_classification(sample_data, default_config):
    results = detect_smart_anomalies(sample_data, default_config)
    for r in results:
        assert r.severity in ("normal", "warning", "critical")
