from app.engine.ml import run_ml_analysis


def test_orchestrator_disabled():
    result = run_ml_analysis({"HospA": {}}, {"enabled": False})
    assert result == {}


def test_orchestrator_enabled_but_small_data():
    data = {
        "HospA": {"cs": 30, "smm_total": 8, "total_births": 100, "mat_deaths": 2,
                   "nd": 5, "sb": 3, "preterm": 12, "lbw": 8, "high_risk": 25, "adolescent": 5},
        "HospB": {"cs": 50, "smm_total": 4, "total_births": 200, "mat_deaths": 1,
                   "nd": 3, "sb": 1, "preterm": 18, "lbw": 10, "high_risk": 40, "adolescent": 8},
        "HospC": {"cs": 20, "smm_total": 10, "total_births": 50, "mat_deaths": 3,
                   "nd": 8, "sb": 5, "preterm": 8, "lbw": 6, "high_risk": 15, "adolescent": 3},
    }
    config = {"enabled": True, "clustering": {"enabled": True, "min_k": 2, "max_k": 2},
              "anomaly": {"enabled": True}, "pca": {"enabled": True}}
    result = run_ml_analysis(data, config)
    assert "ml_clustering" in result
    assert "ml_anomalies" in result
    assert "ml_pca" in result
