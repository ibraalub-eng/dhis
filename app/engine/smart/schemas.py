from dataclasses import dataclass
from typing import List, Dict


@dataclass
class SmartAnomalyResult:
    hospital_name: str
    hospital_id: int
    governorate: str
    hospital_type: str
    anomaly_score: float
    method_scores: Dict[str, float]
    severity: str
    is_outlier: bool


@dataclass
class HospitalClusterAssignment:
    hospital_name: str
    hospital_id: int
    cluster_id: int
    distance_to_centroid: float


@dataclass
class SmartClusteringResult:
    n_clusters: int
    silhouette_score: float
    method: str
    clusters: List[HospitalClusterAssignment]
    noise_hospitals: List[str]
    pca_coordinates: Dict[str, Dict[str, float]]
    centroids: List[Dict]


@dataclass
class CorrelationPair:
    indicator_a: str
    indicator_b: str
    pearson_r: float
    spearman_r: float
    p_value: float
    strength: str


@dataclass
class ImportanceEntry:
    feature_name: str
    importance: float
    rank: int


@dataclass
class FeatureImportance:
    target_indicator: str
    features: List[ImportanceEntry]


@dataclass
class SmartCorrelationResult:
    matrix: Dict[str, Dict[str, float]]
    indicators: List[str]
    strong_correlations: List[CorrelationPair]
    feature_importance: List[FeatureImportance]


@dataclass
class ResidualResult:
    hospital_name: str
    hospital_id: int
    indicator: str
    actual_value: float
    predicted_value: float
    residual: float
    residual_z_score: float
    is_anomaly: bool
    severity: str


@dataclass
class StratifiedComparison:
    hospital_name: str
    hospital_id: int
    indicator: str
    hospital_value: float
    peer_group_mean: float
    peer_group_std: float
    deviation_pct: float
    rank_in_peer_group: int
    peer_group_size: int
    label: str


@dataclass
class FactorExplanation:
    feature: str
    shap_value: float
    direction: str
    magnitude: str
    arabic_label: str


@dataclass
class AnomalyExplanation:
    hospital_name: str
    hospital_id: int
    anomaly_score: float
    severity: str
    shap_values: Dict[str, float]
    top_factors: List[FactorExplanation]
    text_explanation: str


@dataclass
class GovernorateAgg:
    governorate: str
    hospital_count: int
    avg_anomaly_score: float
    max_anomaly_score: float
    outlier_count: int
    avg_indicator_values: Dict[str, float]


@dataclass
class GeoAggregationResult:
    governorates: List[GovernorateAgg]


@dataclass
class KPISummary:
    total_anomalies: int
    critical_count: int
    warning_count: int
    affected_governorates: int
    top_contributing_factor: str
    month_status: str


@dataclass
class SmartAnalyticsResult:
    month: str
    hospitals_count: int
    anomalies: List[SmartAnomalyResult]
    clustering: SmartClusteringResult
    correlations: SmartCorrelationResult
    residuals: List[ResidualResult]
    stratified: List[StratifiedComparison]
    explanations: List[AnomalyExplanation]
    geo: GeoAggregationResult
    kpi: KPISummary
    xgboost_predictions: "XGBoostPredictionResult" = None


@dataclass
class XGBoostPrediction:
    hospital_name: str
    hospital_id: int
    current_score: float
    predicted_next_score: float
    predicted_severity: str
    risk_change: str
    confidence: float
    top_drivers: List["XGBoostDriver"]


@dataclass
class XGBoostDriver:
    feature: str
    arabic_label: str
    shap_value: float
    direction: str
    magnitude: str


@dataclass
class XGBoostGlobalExplanation:
    feature: str
    arabic_label: str
    mean_abs_shap: float
    rank: int


@dataclass
class XGBoostPredictionResult:
    model_r2: float
    model_mae: float
    training_months: int
    hospitals_trained: int
    predictions: List[XGBoostPrediction]
    global_feature_importance: List[XGBoostGlobalExplanation]
    accuracy_note: str
