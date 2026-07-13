from pydantic import BaseModel
from typing import Generic, List, Optional, TypeVar
from datetime import datetime

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    skip: int
    limit: int
    data: List[T]


class PaginatedParams(BaseModel):
    skip: int = 0
    limit: int = 100


class HospitalBase(BaseModel):
    name: str
    region: Optional[str] = None


class HospitalCreate(HospitalBase):
    pass


class HospitalOut(HospitalBase):
    id: int
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IndicatorBase(BaseModel):
    code: str
    name: str
    parent_id: Optional[int] = None
    level: int = 0
    sort_order: int = 0
    group_name: Optional[str] = None


class IndicatorOut(IndicatorBase):
    id: int
    formula: Optional[str] = None
    default_weight: float = 1.0

    class Config:
        from_attributes = True


class IndicatorUpdate(BaseModel):
    name: Optional[str] = None
    formula: Optional[str] = None
    default_weight: Optional[float] = None


class HospitalIndicatorConfigOut(BaseModel):
    id: int
    hospital_id: int
    indicator_id: int
    indicator_code: str = ""
    indicator_name: str = ""
    is_enabled: bool = True
    weight_override: Optional[float] = None
    default_weight: float = 1.0

    class Config:
        from_attributes = True


class ConfigToggleOut(BaseModel):
    hospital_id: int
    indicator_id: int
    is_enabled: bool
    message: str


class IndicatorValueBase(BaseModel):
    hospital_name: str
    indicator_code: str
    month: str
    value: Optional[float] = None


class IndicatorValueOut(BaseModel):
    id: int
    hospital_id: int
    indicator_id: int
    month: str
    value: Optional[float] = None
    source_file: Optional[str] = None

    class Config:
        from_attributes = True


class RuleOut(BaseModel):
    id: int
    code: str
    name: str
    rule_type: str
    severity: str
    category: str
    expression_type: str
    params: str = "{}"
    description: str = ""
    enabled: bool = True
    sort_order: int = 0

    class Config:
        from_attributes = True


class RuleCreate(BaseModel):
    code: str
    name: str
    rule_type: str
    severity: str
    category: str
    expression_type: str
    params: str = "{}"
    description: str = ""


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    rule_type: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    expression_type: Optional[str] = None
    params: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class ValidationOut(BaseModel):
    id: int
    hospital_id: int
    month: str
    rule_code: str
    rule_description: str
    status: str
    severity: str
    rule_type: Optional[str] = "LOGIC"
    details: Optional[str] = None

    class Config:
        from_attributes = True


class AnomalyOut(BaseModel):
    id: Optional[int] = None
    hospital_id: Optional[int] = None
    month: Optional[str] = None
    indicator_code: str
    rate_name: str
    value: Optional[float] = None
    benchmark: Optional[float] = None
    z_score: Optional[float] = None
    is_outlier: bool = False

    class Config:
        from_attributes = True


class QualityScoreOut(BaseModel):
    id: int
    hospital_id: int
    month: str
    score: float
    rule_compliance: Optional[float] = None
    completeness: Optional[float] = None
    consistency: Optional[float] = None
    outlier_penalty: Optional[float] = None
    issues: Optional[str] = None

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    filename: str
    hospitals_processed: int
    rows_imported: int
    message: str
    hospitals: List[dict] = []
    months: List[str] = []


class AutoReportResponse(BaseModel):
    filename: str
    hospitals: List[dict]
    months: List[str]
    reports: List["ReportOut"]


class ConfidenceSummaryOut(BaseModel):
    overall_confidence: float
    level: str
    by_level: dict
    by_group: dict
    priority_verify: List[dict] = []
    summary: str = ""


class ReportOut(BaseModel):
    hospital: str
    month: str
    data_quality_score: float
    rule_compliance: Optional[float] = None
    completeness: Optional[float] = None
    consistency: Optional[float] = None
    outlier_penalty: Optional[float] = None
    issues: List[str]
    outliers: List[dict]
    confidence: Optional[ConfidenceSummaryOut] = None


class ReportSummaryOut(BaseModel):
    hospital: str
    month: str
    data_quality_score: float
    rule_compliance: Optional[float] = None
    completeness: Optional[float] = None
    consistency: Optional[float] = None
    outlier_penalty: Optional[float] = None
    issues: List[str]
    validation_results: List[ValidationOut]
    anomaly_results: List[AnomalyOut]
    confidence: Optional[ConfidenceSummaryOut] = None


class TrendPointOut(BaseModel):
    month: str
    value: float


class TrendResultOut(BaseModel):
    hospital: str
    indicator_code: str
    rate_name: str
    months: List[str]
    values: List[float]
    mean: float
    std: float
    slope: float
    slope_pct: float
    trend_direction: str
    trend_severity: str
    is_significant: bool
    cv: float
    last_vs_mean_pct_change: float
    consecutive_direction: str
    consecutive_count: int
    findings: List[str]


class HospitalComparisonOut(BaseModel):
    hospital: str
    indicator_code: str
    rate_name: str
    value: float
    benchmark: float
    deviation_pct: float
    percentile_rank: float
    comparison_label: str


class HistoricalAnalysisOut(BaseModel):
    hospital: str
    months_analyzed: List[str]
    trends: List[TrendResultOut]
    hospital_comparisons: List[HospitalComparisonOut]
    cross_hospital_anomalies: List[AnomalyOut]
    trend_anomalies: List[AnomalyOut]
    summary: dict


class MultiFileUploadResponse(BaseModel):
    files_processed: int
    hospitals_processed: int
    rows_imported: int
    months: List[str]
    hospitals: List[dict]
    message: str


class ClinicalClassificationOut(BaseModel):
    indicator_code: str
    rate_name: str
    value: Optional[float] = None
    unit: str
    classification: str
    label: str
    color: str
    narrative: str


class ClinicalMetricOut(BaseModel):
    metric_name: str
    description: str
    value: Optional[float] = None
    unit: str
    numerator: float = 0
    denominator: float = 0
    interpretation: str
    severity: str


class ClinicalRiskProfileOut(BaseModel):
    hospital: str
    month: str
    total_deliveries: int
    overall_risk_level: str
    key_findings: List[str] = []
    metrics: List[ClinicalMetricOut] = []


class ClinicalMorbidityProfileOut(BaseModel):
    hospital: str
    month: str
    total_deliveries: int
    total_smm: int
    maternal_deaths: int
    key_findings: List[str] = []
    mortality_preventability_signals: List[str] = []
    metrics: List[ClinicalMetricOut] = []


class ClinicalRecommendationOut(BaseModel):
    category: str
    priority: str
    title: str
    description: str
    rationale: str
    action_items: List[str] = []
    indicators_monitored: List[str] = []
    triggered_by_rules: List[str] = []
    data_reliable: bool = True


class ClinicalSummaryOut(BaseModel):
    overview: str
    key_findings: List[str] = []
    clinical_indicators: List[str] = []
    risk_assessment: str = ""
    morbidity_assessment: str = ""
    recommendations_text: List[str] = []
    overall_assessment: str = ""
    executive_summary: str = ""


class ClinicalAnalysisOut(BaseModel):
    hospital: str
    month: str
    classifications: List[ClinicalClassificationOut] = []
    risk_profile: ClinicalRiskProfileOut
    morbidity_profile: ClinicalMorbidityProfileOut
    recommendations: List[ClinicalRecommendationOut] = []
    summary: ClinicalSummaryOut


class ConfidenceSignalOut(BaseModel):
    factor: str
    passed: bool
    score: float
    detail: str


class IndicatorConfidenceOut(BaseModel):
    indicator_code: str
    indicator_name: str
    value: Optional[float] = None
    confidence: float
    level: str
    signals: List[ConfidenceSignalOut] = []
    recommendations: List[str] = []


class HospitalConfidenceOut(BaseModel):
    hospital: str
    month: str
    overall_confidence: float
    level: str
    indicator_count: int
    by_level: dict
    by_group: dict
    indicators: List[IndicatorConfidenceOut] = []
    priority_verify: List[IndicatorConfidenceOut] = []
    summary: str


class ConfidenceComparisonOut(BaseModel):
    hospital: str
    hospital_id: int
    overall_confidence: float
    level: str
    critical_count: int
    low_count: int
    medium_count: int
    high_count: int