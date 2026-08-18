from dataclasses import dataclass, field
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
class ClusterProfile:
    """ملف تعريف عنقود: حجمه وأعضاؤه وأبرز المؤشرات التي تميزه عن المتوسط العام."""
    cluster_id: int
    size: int
    hospitals: List[str]
    distinguishing_features: List[Dict]  # {feature, cluster_mean, overall_mean, deviation_pct, direction}
    summary_ar: str


@dataclass
class SmartClusteringResult:
    n_clusters: int
    silhouette_score: float
    method: str
    clusters: List[HospitalClusterAssignment]
    noise_hospitals: List[str]
    pca_coordinates: Dict[str, Dict[str, float]]
    centroids: List[Dict]
    profiles: List[ClusterProfile] = field(default_factory=list)


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
    governorate: str = ""
    hospital_type: str = ""


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
class CompositePattern:
    """نمط مركب: مجموعة مؤشرات مرتفعة/منخفضة تتكرر معاً في عدة مستشفيات."""
    indicators: List[str]          # رموز المؤشرات المكونة للنمط
    arabic_names: List[str]        # الأسماء العربية المقابلة
    statuses: List[str]            # elevated / lowered لكل مؤشر
    hospitals_count: int           # عدد المستشفيات المطبِّقة للنمط
    support: float                 # نسبة المستشفيات الحاملة للنمط
    lift: float                    # قوة الارتباط الفائق (تجاوز التواجد المستقل)
    summary_ar: str
    hospitals: List[str] = field(default_factory=list)  # أسماء المستشفيات الحاملة للنمط


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
    patterns: List[CompositePattern] = field(default_factory=list)
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
    trained_at: str = ""            # متى دُرِّب النموذج المحفوظ (ISO)
    retrained: bool = False          # هل أُعيد تدريبه في هذه الجولة (أم حُمّل من القرص)
    data_fingerprint: str = ""      # بصمة بيانات المصدر التي دُرِّب عليها
    walk_forward: List[Dict] = field(default_factory=list)  # تحقق زمني: R²/MAE لكل شهر تالٍ
    feature_variant: str = "baseline"  # مجموعة الميزات المختارة عبر walk-forward
