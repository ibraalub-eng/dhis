from app.engine.smart.schemas import (
    SmartAnomalyResult, SmartClusteringResult, HospitalClusterAssignment,
    SmartCorrelationResult, CorrelationPair, FeatureImportance, ImportanceEntry,
    ResidualResult, StratifiedComparison, AnomalyExplanation, FactorExplanation,
    GeoAggregationResult, GovernorateAgg, SmartAnalyticsResult, KPISummary,
)


def test_smart_anomaly_result():
    r = SmartAnomalyResult(
        hospital_name="Test Hospital", hospital_id=1, governorate="Gaza",
        hospital_type="general", anomaly_score=0.75,
        method_scores={"isolation_forest": 0.8, "lof": 0.7},
        severity="critical", is_outlier=True,
    )
    assert r.hospital_name == "Test Hospital"
    assert r.anomaly_score == 0.75
    assert r.severity == "critical"
    assert r.is_outlier is True


def test_smart_clustering_result():
    c = SmartClusteringResult(
        n_clusters=3, silhouette_score=0.45, method="dbscan",
        clusters=[], noise_hospitals=["Hospital A"],
        pca_coordinates={"Hospital A": {"x": 1.0, "y": 2.0}}, centroids=[{"f": 0.5}],
    )
    assert c.n_clusters == 3
    assert c.method == "dbscan"
    assert len(c.noise_hospitals) == 1


def test_hospital_cluster_assignment():
    a = HospitalClusterAssignment(hospital_name="T", hospital_id=1, cluster_id=0, distance_to_centroid=0.5)
    assert a.cluster_id == 0


def test_smart_correlation_result():
    r = SmartCorrelationResult(matrix={"a": {"b": 0.8}}, indicators=["a", "b"], strong_correlations=[], feature_importance=[])
    assert len(r.indicators) == 2


def test_correlation_pair():
    p = CorrelationPair(indicator_a="cs_rate", indicator_b="smm", pearson_r=0.85, spearman_r=0.82, p_value=0.001, strength="strong_positive")
    assert p.strength == "strong_positive"


def test_feature_importance():
    fi = FeatureImportance(target_indicator="cs_rate", features=[ImportanceEntry(feature_name="total_births", importance=0.3, rank=1)])
    assert fi.features[0].rank == 1


def test_residual_result():
    r = ResidualResult(hospital_name="T", hospital_id=1, indicator="cs_rate", actual_value=35.0, predicted_value=28.0, residual=7.0, residual_z_score=2.5, is_anomaly=True, severity="warning")
    assert r.is_anomaly is True


def test_stratified_comparison():
    s = StratifiedComparison(hospital_name="T", hospital_id=1, indicator="cs_rate", hospital_value=35.0, peer_group_mean=28.0, peer_group_std=3.0, deviation_pct=25.0, rank_in_peer_group=1, peer_group_size=5, label="significantly_above")
    assert s.rank_in_peer_group == 1


def test_anomaly_explanation():
    e = AnomalyExplanation(
        hospital_name="T", hospital_id=1, anomaly_score=0.8, severity="critical",
        shap_values={"cs_rate": 0.3}, top_factors=[FactorExplanation(feature="cs_rate", shap_value=0.3, direction="increases_anomaly", magnitude="high", arabic_label="معدل القيصارية")],
        text_explanation="شاذ بسبب ارتفاع معدل القيصارية",
    )
    assert len(e.top_factors) == 1
    assert e.top_factors[0].direction == "increases_anomaly"


def test_geo_aggregation():
    g = GeoAggregationResult(governorates=[GovernorateAgg(governorate="Gaza", hospital_count=5, avg_anomaly_score=0.4, max_anomaly_score=0.8, outlier_count=1, avg_indicator_values={"cs_rate": 30.0})])
    assert len(g.governorates) == 1


def test_kpi_summary():
    k = KPISummary(total_anomalies=5, critical_count=2, warning_count=3, affected_governorates=3, top_contributing_factor="cs_rate", month_status="attention_needed")
    assert k.total_anomalies ==5


def test_smart_analytics_result():
    r = SmartAnalyticsResult(
        month="2026-06", hospitals_count=20, anomalies=[],
        clustering=SmartClusteringResult(n_clusters=0, silhouette_score=0.0, method="dbscan", clusters=[], noise_hospitals=[], pca_coordinates={}, centroids=[]),
        correlations=SmartCorrelationResult(matrix={}, indicators=[], strong_correlations=[], feature_importance=[]),
        residuals=[], stratified=[], explanations=[],
        geo=GeoAggregationResult(governorates=[]),
        kpi=KPISummary(total_anomalies=0, critical_count=0, warning_count=0, affected_governorates=0, top_contributing_factor="", month_status="normal"),
    )
    assert r.month == "2026-06"
    assert r.hospitals_count == 20
