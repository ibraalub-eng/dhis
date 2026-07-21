import pytest
from app.engine.smart.clustering import run_clustering


@pytest.fixture
def sample_data():
    return {
        "Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0, "smm_total": 5.0, "mat_deaths": 1.0, "nd": 2.0, "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0}},
        "Hospital B": {"hospital_id": 2, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 28.0, "smm_total": 4.5, "mat_deaths": 0.8, "nd": 1.8, "sb": 0.9, "preterm": 9.5, "lbw": 7.5, "total_births": 195.0, "high_risk": 14.0, "adolescent": 2.8}},
        "Hospital C": {"hospital_id": 3, "governorate": "North Gaza", "hospital_type": "general", "values": {"cs_rate": 32.0, "smm_total": 5.5, "mat_deaths": 1.2, "nd": 2.2, "sb": 1.1, "preterm": 10.5, "lbw": 8.5, "total_births": 205.0, "high_risk": 16.0, "adolescent": 3.2}},
        "Hospital D": {"hospital_id": 4, "governorate": "Khan Younis", "hospital_type": "specialist", "values": {"cs_rate": 15.0, "smm_total": 2.0, "mat_deaths": 0.0, "nd": 0.5, "sb": 0.2, "preterm": 5.0, "lbw": 4.0, "total_births": 120.0, "high_risk": 8.0, "adolescent": 1.0}},
        "Hospital E": {"hospital_id": 5, "governorate": "Rafah", "hospital_type": "general", "values": {"cs_rate": 18.0, "smm_total": 2.5, "mat_deaths": 0.1, "nd": 0.8, "sb": 0.3, "preterm": 5.5, "lbw": 4.5, "total_births": 130.0, "high_risk": 9.0, "adolescent": 1.2}},
    }


@pytest.fixture
def default_config():
    return {"dbscan_eps": 1.5, "dbscan_min_samples": 2}


def test_returns_clustering_result(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert result is not None
    assert result.n_clusters >= 1


def test_all_hospitals_assigned(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assigned = [c.hospital_name for c in result.clusters]
    noise = result.noise_hospitals
    all_names = assigned + noise
    assert set(all_names) == set(sample_data.keys())


def test_pca_coordinates_present(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    for name in sample_data:
        assert name in result.pca_coordinates
        assert "x" in result.pca_coordinates[name]
        assert "y" in result.pca_coordinates[name]


def test_too_few_returns_none(default_config):
    data = {"Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = run_clustering(data, default_config)
    assert result is None


def test_disabled_returns_none(default_config):
    result = run_clustering({}, default_config, enabled=False)
    assert result is None


def test_silhouette_score_valid(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert -1.0 <= result.silhouette_score <= 1.0
