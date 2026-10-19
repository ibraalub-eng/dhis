from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

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
    governorate_id: Optional[int] = None
    hospital_type_id: Optional[int] = None
    organisation_unit_id: Optional[str] = None
    facility_ownership_id: Optional[int] = None
    facility_type_id: Optional[int] = None
    address: Optional[str] = None


class HospitalCreate(HospitalBase):
    pass


class HospitalOut(HospitalBase):
    id: int
    is_active: bool = True
    created_at: Optional[datetime] = None
    governorate_name: Optional[str] = None
    hospital_type_name: Optional[str] = None
    facility_ownership_name: Optional[str] = None
    facility_type_name: Optional[str] = None

    class Config:
        from_attributes = True


class GovernorateBase(BaseModel):
    name: str


class GovernorateCreate(GovernorateBase):
    pass


class GovernorateOut(GovernorateBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HospitalTypeBase(BaseModel):
    name: str


class HospitalTypeCreate(HospitalTypeBase):
    pass


class HospitalTypeOut(HospitalTypeBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FacilityOwnershipBase(BaseModel):
    name: str

class FacilityOwnershipCreate(FacilityOwnershipBase):
    pass

class FacilityOwnershipOut(FacilityOwnershipBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class FacilityTypeBase(BaseModel):
    name: str

class FacilityTypeCreate(FacilityTypeBase):
    pass

class FacilityTypeOut(FacilityTypeBase):
    id: int
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


# ── Indicators management (derived-indicator definitions) ───────────────────

class IndicatorDefinitionBase(BaseModel):
    """Draft of a managed derived indicator (create/update payload)."""
    code: str
    name: str
    description: Optional[str] = None
    group_name: Optional[str] = None
    formula_type: str = "ratio"            # ratio | expression
    expression: Optional[str] = None       # expression mode source
    numerator_codes: Optional[List[str]] = None
    denominator_codes: Optional[List[str]] = None
    operator: str = "/"                    # / * + -
    multiplier: float = 1.0
    aggregation: str = "sum"               # sum | avg | max | min
    result_type: str = "percentage"        # percentage | rate | ratio | count
    unit: Optional[str] = None
    # display rounding: precision NULL = full float (legacy behaviour),
    # precision N = round stored/computed values to N decimals (mode below)
    precision: Optional[int] = None        # 0..6, validated in _validate_draft
    rounding: str = "half_up"              # half_up | half_even | down
    direction: Optional[str] = None        # none | higher/lower_is_better | target_range
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    is_active: bool = True


class IndicatorDefinitionCreate(IndicatorDefinitionBase):
    pass


class IndicatorDefinitionUpdate(BaseModel):
    """Partial update — ``code`` is intentionally immutable so indicator
    IDs referenced by history/results never change meaning."""
    name: Optional[str] = None
    description: Optional[str] = None
    group_name: Optional[str] = None
    formula_type: Optional[str] = None
    expression: Optional[str] = None
    numerator_codes: Optional[List[str]] = None
    denominator_codes: Optional[List[str]] = None
    operator: Optional[str] = None
    multiplier: Optional[float] = None
    aggregation: Optional[str] = None
    result_type: Optional[str] = None
    unit: Optional[str] = None
    precision: Optional[int] = None
    rounding: Optional[str] = None
    direction: Optional[str] = None
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    is_active: Optional[bool] = None


class IndicatorDefinitionOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    group_name: Optional[str] = None
    source_site: Optional[str] = None
    legacy_code: Optional[str] = None
    is_system: bool = False
    formula_type: str
    expression: Optional[str] = None
    numerator_codes: Optional[List[str]] = None
    denominator_codes: Optional[List[str]] = None
    operator: str = "/"
    multiplier: float = 1.0
    aggregation: str = "sum"
    result_type: str
    unit: Optional[str] = None
    precision: Optional[int] = None
    rounding: str = "half_up"
    direction: Optional[str] = None
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    is_active: bool = True
    version: int = 1
    formula_display: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IndicatorCatalogItem(BaseModel):
    """One row of the Indicators tab list: raw catalog entries, existing
    system rate definitions and managed derived definitions, unified."""
    kind: str                            # raw | derived
    ref_id: Optional[int] = None
    code: str
    name: str
    description: Optional[str] = None
    group_name: Optional[str] = None
    # Single catalog classification: the group name when set, otherwise a
    # fallback label derived from `kind` (see indicator_definitions.py).
    category: Optional[str] = None
    indicator_type: Optional[str] = None
    unit: Optional[str] = None
    formula: Optional[str] = None
    numerator_codes: Optional[List[str]] = None
    denominator_codes: Optional[List[str]] = None
    status: str = "active"               # active | inactive | catalog
    level: Optional[int] = None
    version: Optional[int] = None
    definition_id: Optional[int] = None
    site: Optional[str] = None           # registry scope: zscore | clinical | forecast
    is_system: bool = False


class IndicatorListOut(BaseModel):
    items: List[IndicatorCatalogItem]
    count: int
    categories: List[str] = []
    groups: List[str] = []               # kept for older clients
    types: List[str] = []


class IndicatorValidateIn(BaseModel):
    """A definition draft plus optional preview scope."""
    draft: IndicatorDefinitionBase
    exclude_id: Optional[int] = None     # definition being edited (code uniqueness)
    hospital_id: Optional[int] = None
    month: Optional[str] = None


class IndicatorRefInfo(BaseModel):
    code: str
    name: Optional[str] = None
    group_name: Optional[str] = None
    level: Optional[int] = None
    exists: bool = True
    data_count: Optional[int] = None     # rows in the preview period (if given)


class IndicatorPreviewOut(BaseModel):
    status: str
    value: Optional[float] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    inputs: List[dict] = []              # [{code, name, value, missing}]
    message: str = ""


class IndicatorValidateOut(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    expression: Optional[str] = None     # canonical parseable formula
    formula_display: Optional[str] = None
    refs: List[IndicatorRefInfo] = []
    preview: Optional[IndicatorPreviewOut] = None


class IndicatorToggleIn(BaseModel):
    is_active: bool


class IndicatorDefinitionVersionOut(BaseModel):
    id: int
    definition_code: str
    version: int
    action: str
    snapshot: Optional[dict] = None
    changed_fields: Optional[List[str]] = None
    changed_by: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IndicatorResultOut(BaseModel):
    id: int
    definition_id: Optional[int] = None
    definition_code: str
    hospital_id: int
    hospital_name: Optional[str] = None
    month: str
    value: Optional[float] = None
    status: str
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    definition_version: int = 1
    current_version: Optional[int] = None
    stale: bool = False
    computed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IndicatorPreviewIn(BaseModel):
    hospital_id: Optional[int] = None
    month: Optional[str] = None


class IndicatorGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    scope_type: str = "all"  # "all" | "hospital"
    hospital_id: Optional[int] = None
    month_from: Optional[str] = None  # YYYY-MM, inclusive — applied only for scope "all"
    month_to: Optional[str] = None
    indicator_ids: List[int] = []


class IndicatorGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope_type: Optional[str] = None
    hospital_id: Optional[int] = None
    month_from: Optional[str] = None
    month_to: Optional[str] = None


class IndicatorGroupMemberOut(BaseModel):
    indicator_id: int
    indicator_code: str = ""
    indicator_name: str = ""
    sort_order: int = 0

    class Config:
        from_attributes = True


class IndicatorGroupOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    scope_type: str
    hospital_id: Optional[int] = None
    hospital_name: Optional[str] = None
    month_from: Optional[str] = None
    month_to: Optional[str] = None
    member_count: int = 0
    members: List[IndicatorGroupMemberOut] = []
    # Derived from member config rows (rev 2: no stored is_enabled flag) —
    # stays correct after single-indicator edits outside the group.
    is_enabled: bool = True


class IndicatorGroupToggleIn(BaseModel):
    """Explicit target state — idempotent, unlike the flip semantics of the
    single-indicator toggle endpoints."""
    enabled: bool


class IndicatorGroupMembersIn(BaseModel):
    indicator_ids: List[int]


class IndicatorReorderIn(BaseModel):
    items: List[dict]


class RequirementTypeIn(BaseModel):
    """Body for PUT /hospitals/indicators/{id}/requirement-type."""
    requirement_type: str  # "Required" | "Optional"


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
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None
    rate_name: str
    value: Optional[float] = None
    benchmark: Optional[float] = None
    z_score: Optional[float] = None
    is_outlier: bool = False
    # Registry metadata (filled by the Quality report detail endpoint).
    # `formula_status` is current | stale | unverified | unregistered — a
    # stored value is never presented as current without this check.
    unit: Optional[str] = None
    formula_status: Optional[str] = None
    current_formula_version: Optional[str] = None
    # Peer metadata matching the audit benchmark screen (None for trend rows).
    peer_count: Optional[int] = None
    peer_std: Optional[float] = None
    peer_min: Optional[float] = None
    peer_max: Optional[float] = None
    peer_median: Optional[float] = None
    # [{hospital, rate}, ...] sorted by rate for the drill-down popover.
    peers_detail: Optional[list] = None

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
    new_indicators: List[dict] = []


class AutoReportResponse(BaseModel):
    filename: str
    hospitals: List[dict]
    months: List[str]
    reports: List["ReportOut"]
    new_indicators: List[dict] = []
    renamed_indicators: List[dict] = []


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
    is_enabled: bool = True


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
    hospital_id: Optional[int] = None
    hospital: str
    indicator_code: str
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None
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
    indicator_id: Optional[str] = None
    formula: Optional[str] = None
    formula_version: Optional[str] = None
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
    source: str = "rulebase"


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
