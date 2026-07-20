import pytest
from app.engine.ml.clustering import cluster_hospitals


def test_cluster_hospitals_basic():
    data = {
        "HospA": {"total_births": 100, "mat_deaths": 2, "nd": 5, "cs": 30, "smm_total": 8,
                   "sb": 3, "preterm": 12, "lbw": 8, "high_risk": 25, "adolescent": 5},
        "HospB": {"total_births": 200, "mat_deaths": 1, "nd": 3, "cs": 50, "smm_total": 4,
                   "sb": 1, "preterm": 18, "lbw": 10, "high_risk": 40, "adolescent": 8},
        "HospC": {"total_births": 50, "mat_deaths": 3, "nd": 8, "cs": 20, "smm_total": 10,
                   "sb": 5, "preterm": 8, "lbw": 6, "high_risk": 15, "adolescent": 3},
        "HospD": {"total_births": 300, "mat_deaths": 0, "nd": 2, "cs": 80, "smm_total": 3,
                   "sb": 2, "preterm": 25, "lbw": 15, "high_risk": 60, "adolescent": 12},
        "HospE": {"total_births": 150, "mat_deaths": 1, "nd": 4, "cs": 40, "smm_total": 5,
                   "sb": 2, "preterm": 14, "lbw": 9, "high_risk": 30, "adolescent": 6},
    }
    config = {"enabled": True, "min_k": 2, "max_k": 4, "features": [
        "total_births", "mat_deaths", "nd", "cs", "smm_total",
        "sb", "preterm", "lbw", "high_risk", "adolescent"
    ]}
    result = cluster_hospitals(data, config)
    assert result is not None
    assert 2 <= result.k <= 4
    assert len(result.clusters) == 5
    assert all(c.hospital_name in data for c in result.clusters)


def test_cluster_hospitals_too_few():
    data = {"HospA": {"total_births": 100}}
    config = {"enabled": True, "min_k": 2, "max_k": 4, "features": ["total_births"]}
    result = cluster_hospitals(data, config)
    assert result is None


def test_cluster_hospitals_disabled():
    result = cluster_hospitals({"HospA": {}}, {"enabled": False})
    assert result is None


def test_cluster_hospitals_missing_features():
    data = {"HospA": {"total_births": 100}, "HospB": {"total_births": 200}}
    config = {"enabled": True, "min_k": 1, "max_k": 3, "features": ["total_births", "cs"]}
    result = cluster_hospitals(data, config)
    assert result is not None
