import pytest
from app.engine.ml.decomposition import run_pca


def test_run_pca_basic():
    data = {
        "HospA": {"cs": 30, "smm_total": 8, "mat_deaths": 2, "nd": 5, "sb": 3,
                   "preterm": 12, "lbw": 8, "total_births": 100, "high_risk": 25, "adolescent": 5},
        "HospB": {"cs": 50, "smm_total": 4, "mat_deaths": 1, "nd": 3, "sb": 1,
                   "preterm": 18, "lbw": 10, "total_births": 200, "high_risk": 40, "adolescent": 8},
        "HospC": {"cs": 20, "smm_total": 10, "mat_deaths": 3, "nd": 8, "sb": 5,
                   "preterm": 8, "lbw": 6, "total_births": 50, "high_risk": 15, "adolescent": 3},
        "HospD": {"cs": 80, "smm_total": 3, "mat_deaths": 0, "nd": 2, "sb": 2,
                   "preterm": 25, "lbw": 15, "total_births": 300, "high_risk": 60, "adolescent": 12},
        "HospE": {"cs": 40, "smm_total": 5, "mat_deaths": 1, "nd": 4, "sb": 2,
                   "preterm": 14, "lbw": 9, "total_births": 150, "high_risk": 30, "adolescent": 6},
    }
    config = {"enabled": True, "variance_threshold": 0.8, "max_components": 5}
    result = run_pca(data, config)
    assert result is not None
    assert 1 <= result.n_components <= 5
    assert len(result.explained_variance) == result.n_components
    assert len(result.cumulative_variance) == result.n_components
    assert all(0 <= v <= 1 for v in result.explained_variance)
    assert len(result.top_features) == result.n_components


def test_run_pca_disabled():
    result = run_pca({"HospA": {}}, {"enabled": False})
    assert result is None


def test_run_pca_too_few():
    result = run_pca({"HospA": {"cs": 30}}, {"enabled": True})
    assert result is None
