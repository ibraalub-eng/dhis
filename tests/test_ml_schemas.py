from app.engine.ml.schemas import HospitalCluster, ClusteringResult, MLAnomalyResult, PCAResult


def test_hospital_cluster():
    c = HospitalCluster("TestHosp", 0, 1.5)
    assert c.hospital_name == "TestHosp"
    assert c.cluster_id == 0
    assert c.distance_to_centroid == 1.5


def test_clustering_result_defaults():
    r = ClusteringResult(clusters=[], k=0, silhouette_score=None, centroids=[], features_used=[])
    assert r.silhouette_score is None
    assert len(r.clusters) == 0


def test_ml_anomaly_result_defaults():
    r = MLAnomalyResult("Hosp", -0.5, True, "isolation_forest")
    assert r.contributing_features == []
    assert r.is_outlier is True
    assert r.anomaly_score == -0.5


def test_pca_result():
    r = PCAResult([0.5, 0.3], [0.5, 0.8], {1: {"a": 0.9}}, {1: ["a"]}, 2)
    assert r.n_components == 2
    assert len(r.explained_variance) == 2
