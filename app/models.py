from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Governorate(Base):
    __tablename__ = "governorates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospitals = relationship("Hospital", back_populates="governorate")


class HospitalType(Base):
    __tablename__ = "hospital_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospitals = relationship("Hospital", back_populates="hospital_type")


class FacilityOwnership(Base):
    __tablename__ = "facility_ownerships"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    hospitals = relationship("Hospital", back_populates="facility_ownership")


class FacilityType(Base):
    __tablename__ = "facility_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    hospitals = relationship("Hospital", back_populates="facility_type")


class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    region = Column(String(100), nullable=True)
    governorate_id = Column(Integer, ForeignKey("governorates.id"), nullable=True)
    hospital_type_id = Column(Integer, ForeignKey("hospital_types.id"), nullable=True)
    address = Column(Text, nullable=True)
    organisation_unit_id = Column(String(100), nullable=True)
    facility_ownership_id = Column(Integer, ForeignKey("facility_ownerships.id", ondelete="SET NULL"), nullable=True)
    facility_type_id = Column(Integer, ForeignKey("facility_types.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    indicator_values = relationship("IndicatorValue", back_populates="hospital")
    validation_results = relationship("ValidationResult", back_populates="hospital")
    anomaly_results = relationship("AnomalyResult", back_populates="hospital")
    quality_scores = relationship("QualityScore", back_populates="hospital")
    clinical_insights = relationship("ClinicalInsight", back_populates="hospital")
    indicator_configs = relationship("HospitalIndicatorConfig", back_populates="hospital", cascade="all, delete-orphan")
    governorate = relationship("Governorate", back_populates="hospitals")
    hospital_type = relationship("HospitalType", back_populates="hospitals")
    facility_ownership = relationship("FacilityOwnership", back_populates="hospitals")
    facility_type = relationship("FacilityType", back_populates="hospitals")


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    parent_id = Column(Integer, ForeignKey("indicators.id"), nullable=True)
    level = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    group_name = Column(String(100), nullable=True)
    formula = Column(Text, nullable=True)
    default_weight = Column(Float, default=1.0)
    # Completeness denominator gate (indicator-groups design rev 2):
    # 'Required' counts in the denominator, 'Optional' is excluded entirely.
    # server_default keeps the column safe for the startup
    # _ensure_required_columns() self-heal path; the backfill is 'Required'
    # so existing scores are preserved exactly.
    requirement_type = Column(String(10), nullable=False, server_default="Required", default="Required")

    # Layered-outlier analysis config (design spec 2026-10-08 §3.2): count /
    # raw-layer settings only — numerator/denominator/multiplier live in the
    # rate_config table. All nullable + server-defaulted so the startup
    # _ensure_required_columns() self-heal path can add them safely, and so
    # rows predating the migration read the same defaults.
    indicator_type = Column(String(20), nullable=True, server_default="count", default="count")
    minimum_history_period = Column(Integer, nullable=True, server_default="3", default=3)
    outlier_method = Column(String(30), nullable=True, server_default="auto", default="auto")
    historical_enabled = Column(Boolean, nullable=True, server_default=text("true"), default=True)
    peer_comparison_enabled = Column(Boolean, nullable=True, server_default=text("true"), default=True)

    parent = relationship("Indicator", remote_side=[id], backref="children")
    values = relationship("IndicatorValue", back_populates="indicator")
    hospital_configs = relationship("HospitalIndicatorConfig", back_populates="indicator", cascade="all, delete-orphan")
    default_configs = relationship("IndicatorDefaultConfig", back_populates="indicator", cascade="all, delete-orphan")


class HospitalIndicatorConfig(Base):
    __tablename__ = "hospital_indicator_config"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=False, index=True)
    is_enabled = Column(Boolean, default=True)
    weight_override = Column(Float, nullable=True)

    hospital = relationship("Hospital", back_populates="indicator_configs")
    indicator = relationship("Indicator", back_populates="hospital_configs")

    __table_args__ = (
        UniqueConstraint("hospital_id", "indicator_id", name="uq_hospital_indicator"),
    )


class IndicatorDefaultConfig(Base):
    """Default (All Hospitals) enabled/disabled state per indicator per month.
    A hospital's own HospitalIndicatorConfig row overrides this default."""
    __tablename__ = "indicator_default_config"

    id = Column(Integer, primary_key=True, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    is_enabled = Column(Boolean, default=True)
    weight_override = Column(Float, nullable=True)

    indicator = relationship("Indicator", back_populates="default_configs")

    __table_args__ = (
        UniqueConstraint("indicator_id", "month", name="uq_indicator_default_month"),
    )


class IndicatorGroup(Base):
    """Named set of indicators toggled together as a bulk-action macro.

    The group is NEVER consulted at runtime: toggling it upserts
    IndicatorDefaultConfig (scope='all') or HospitalIndicatorConfig
    (scope='hospital') rows for its members, and those config rows — not this
    table — are what the engines read (design rev 2). There is deliberately no
    stored is_enabled flag: the list view derives it from member config rows
    so it stays correct after single-indicator edits.

    month_from/month_to only ever APPLY when scope_type='all':
    HospitalIndicatorConfig has no month column, so a hospital-scoped override
    is month-agnostic by design (toggling a hospital group with a stored range
    is rejected with 422 — see the router).
    """
    __tablename__ = "indicator_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    scope_type = Column(String(20), nullable=False, default="all")  # 'all' | 'hospital'
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True, index=True)
    # Inclusive YYYY-MM range — saved for all scopes, applied only for 'all'.
    month_from = Column(String(7), nullable=True)
    month_to = Column(String(7), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital")
    members = relationship(
        "IndicatorGroupMember", back_populates="group",
        cascade="all, delete-orphan", order_by="IndicatorGroupMember.sort_order",
    )


class IndicatorGroupMember(Base):
    __tablename__ = "indicator_group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("indicator_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order = Column(Integer, default=0)

    group = relationship("IndicatorGroup", back_populates="members")
    indicator = relationship("Indicator")

    __table_args__ = (
        UniqueConstraint("group_id", "indicator_id", name="uq_group_indicator"),
    )


class IndicatorValue(Base):
    __tablename__ = "indicator_values"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    value = Column(Float, nullable=True)
    source_file = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital", back_populates="indicator_values")
    indicator = relationship("Indicator", back_populates="values")

    __table_args__ = (
        Index("ix_iv_hosp_month_ind", "hospital_id", "month", "indicator_id"),
        Index("ix_iv_month", "month"),
        UniqueConstraint("hospital_id", "indicator_id", "month", name="uq_indicator_value_hosp_ind_month"),
    )


class IndicatorDefinition(Base):
    """Managed derived-indicator definition (Indicators tab).

    A definition is a CONFIGURABLE, derived health metric (e.g. C-Section
    Rate) computed at read/recompute time from RAW IndicatorValue rows of
    other indicators — it never writes into indicator_values, and it never
    touches the Data Tree catalog (app.models.Indicator), so raw-data
    import, completeness denominators and existing dashboards are
    completely unaffected (Indicators-management design, 2026-10-18).

    Two formula shapes, both validated by the safe expression parser in
    app/engine/indicator_calc.py BEFORE they ever reach this table:

    * ``ratio``      — numerator_codes <operator> denominator_codes, times
                       multiplier (the C-Section Rate shape:
                       (5 / 2) x 100). Operator is one of / * + -.
    * ``expression`` — a strict arithmetic ``expression`` string using
                       {code} references only. Never executed as code: it
                       is tokenized and evaluated by a fixed-grammar
                       recursive-descent parser (same language as the
                       validation-rule formulas).

    All numeric columns are nullable/defaults so the startup
    _ensure_required_columns() self-heal path stays safe. ``version``
    increments on every content change; the full snapshot of each version
    lives in IndicatorDefinitionVersion, so historical results (which
    stamp the definition_version they were computed with in
    IndicatorResult) stay auditable after edits.
    """
    __tablename__ = "indicator_definitions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    group_name = Column(String(100), nullable=True)
    source_site = Column(String(20), nullable=True, index=True)
    legacy_code = Column(String(100), nullable=True, index=True)
    is_system = Column(Boolean, nullable=False, server_default=text("false"), default=False)

    # ── formula ──────────────────────────────────────────────────────────
    formula_type = Column(String(20), nullable=False, server_default="ratio", default="ratio")
    expression = Column(Text, nullable=True)          # expression-mode source ("{5} / {2} * 100")
    numerator_codes = Column(JSON, nullable=True)     # ["5"]
    denominator_codes = Column(JSON, nullable=True)   # ["2"]
    operator = Column(String(3), nullable=False, server_default="/", default="/")
    multiplier = Column(Float, nullable=False, server_default="1", default=1.0)
    aggregation = Column(String(10), nullable=False, server_default="sum", default="sum")

    # ── result semantics ─────────────────────────────────────────────────
    result_type = Column(String(20), nullable=False, server_default="percentage", default="percentage")
    unit = Column(String(30), nullable=True)
    # precision/rounding: how the computed value is rounded for storage and
    # display. precision NULL = keep the full float (legacy behaviour);
    # precision N = round to N decimal places with the given mode. Applied
    # ONLY by the shared engine at compute time — historical rows keep the
    # rounding they were stored with (no silent rewrite on config change).
    precision = Column(Integer, nullable=True)
    rounding = Column(String(10), nullable=False, server_default="half_up", default="half_up")
    direction = Column(String(20), nullable=True)     # higher/lower_is_better | target_range | none
    threshold_low = Column(Float, nullable=True)
    threshold_high = Column(Float, nullable=True)
    target_min = Column(Float, nullable=True)
    target_max = Column(Float, nullable=True)

    # ── lifecycle ────────────────────────────────────────────────────────
    is_active = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    results = relationship(
        "IndicatorResult", back_populates="definition",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("code", name="uq_indicator_definition_code"),
    )


class IndicatorDefinitionVersion(Base):
    """Audit trail for derived-indicator definition changes.

    Mirrors RuleHistory: rows outlive the definition — definition_id is
    SET NULL on deletion while definition_code keeps the trail queryable.
    ``snapshot`` is the full JSON of the definition AFTER the change, so
    any historical IndicatorResult stamped with ``version`` can be replayed
    against the exact formula that produced it.
    """
    __tablename__ = "indicator_definition_versions"

    id = Column(Integer, primary_key=True, index=True)
    definition_id = Column(
        Integer, ForeignKey("indicator_definitions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    definition_code = Column(String(50), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)       # created|updated|activated|deactivated|deleted
    snapshot = Column(Text, nullable=False)           # full definition JSON after the change
    changed_fields = Column(Text, nullable=True)      # JSON list of changed field names
    changed_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class IndicatorResult(Base):
    """Stored output of a derived indicator for one hospital x month.

    Deliberately a SEPARATE table from indicator_values (raw data): raw
    imports never overwrite these, these never masquerade as raw data, and
    completeness / Data Tree / rules engines — which only read
    indicator_values — cannot be silently affected by derived-indicator
    changes.

    ``value`` is NULL whenever ``status`` != 'ok'; ``status`` distinguishes
    missing data (no reported value) from a legitimate 0.0 result and from
    a zero denominator. ``definition_version`` records which formula
    version produced the row — a version mismatch against the current
    definition shows as "stale" until an EXPLICIT recompute, so editing a
    definition never silently rewrites historical results.
    """
    __tablename__ = "indicator_results"

    id = Column(Integer, primary_key=True, index=True)
    definition_id = Column(
        Integer, ForeignKey("indicator_definitions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    definition_code = Column(String(50), nullable=False, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    value = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, server_default="ok", default="ok")
    numerator = Column(Float, nullable=True)
    denominator = Column(Float, nullable=True)
    inputs = Column(Text, nullable=True)              # JSON breakdown {code: value|null}
    definition_version = Column(Integer, nullable=False, server_default="1", default=1)
    computed_at = Column(DateTime, default=datetime.utcnow)

    definition = relationship("IndicatorDefinition", back_populates="results")
    hospital = relationship("Hospital")

    __table_args__ = (
        Index("ix_ir_hosp_month", "hospital_id", "month"),
        UniqueConstraint("definition_id", "hospital_id", "month", name="uq_indicator_result_def_hosp_month"),
    )


class Rule(Base):
    __tablename__ = "rules"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    rule_type = Column(String(20), nullable=False)
    severity = Column(String(10), nullable=False)
    category = Column(String(50), nullable=False)
    expression_type = Column(String(50), nullable=False)
    params = Column(Text, default="{}")
    description = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class RuleHistory(Base):
    """Audit trail for rule changes (create/update/enable-toggle/delete).
    Rows outlive the rule itself: rule_id is SET NULL on rule deletion while
    rule_code keeps the trail queryable afterwards."""
    __tablename__ = "rule_history"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True, index=True)
    rule_code = Column(String(50), nullable=False, index=True)
    action = Column(String(20), nullable=False)  # created | updated | enabled | disabled | deleted
    snapshot = Column(Text, nullable=True)       # full rule JSON after the change
    changed_fields = Column(Text, nullable=True) # JSON list of changed field names
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    rule_code = Column(String(100), nullable=False)
    rule_description = Column(Text, nullable=False)
    status = Column(String(10), nullable=False)
    severity = Column(String(10), nullable=False)
    rule_type = Column(String(20), default="LOGIC")
    details = Column(Text, nullable=True)

    hospital = relationship("Hospital", back_populates="validation_results")

    __table_args__ = (
        Index("ix_vr_hosp_month", "hospital_id", "month"),
        Index("ix_vr_status", "status"),
    )


class AnomalyResult(Base):
    __tablename__ = "anomaly_results"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    indicator_code = Column(String(50), nullable=False)
    indicator_id = Column(String(100), nullable=True)
    formula = Column(Text, nullable=True)
    formula_version = Column(String(100), nullable=True)
    rate_name = Column(String(100), nullable=False)
    value = Column(Float, nullable=True)
    benchmark = Column(Float, nullable=True)
    z_score = Column(Float, nullable=True)
    is_outlier = Column(Boolean, default=False)
    # Peer metadata matching the audit benchmark screen (NULL for trend rows
    # and rows computed before peer metadata existed).
    peer_count = Column(Integer, nullable=True)
    peer_std = Column(Float, nullable=True)
    peer_min = Column(Float, nullable=True)
    peer_max = Column(Float, nullable=True)
    peer_median = Column(Float, nullable=True)
    # [{"hospital": name, "rate": rate}, ...] for the drill-down popover.
    peers_detail = Column(JSON, nullable=True)

    hospital = relationship("Hospital", back_populates="anomaly_results")

    __table_args__ = (
        Index("ix_ar_hosp_month", "hospital_id", "month"),
        Index("ix_ar_outlier", "is_outlier"),
    )


class RateConfig(Base):
    """Rate definitions & layered-engine tuning (design spec 2026-10-08 §3.3).

    Rows are seeded insert-if-missing from the registry's zscore slice
    (scripts/seed_indicators.py::seed_rate_config) and merged over the
    builtin defaults by app/engine/rate_config.py::load_rate_specs.
    """
    __tablename__ = "rate_config"

    id = Column(Integer, primary_key=True, index=True)
    rate_code = Column(String(50), nullable=False, index=True)
    rate_name = Column(String(200), nullable=True)
    indicator_type = Column(String(20), nullable=True)          # rate | ratio | percentage
    numerator_codes = Column(JSON, nullable=True)               # ["5"]
    denominator_codes = Column(JSON, nullable=True)             # ["2"]
    rate_multiplier = Column(Integer, nullable=True)            # 100 / 1000 / 1
    minimum_denominator = Column(Integer, nullable=True)        # NULL = guard dormant (§12)
    minimum_history_period = Column(Integer, nullable=True, server_default="3")
    outlier_method = Column(String(30), nullable=True, server_default="auto")
    historical_enabled = Column(Boolean, nullable=True, server_default=text("true"))
    peer_comparison_enabled = Column(Boolean, nullable=True, server_default=text("true"))
    is_active = Column(Boolean, nullable=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("rate_code", name="uq_rate_config_code"),
    )


class LayeredOutlierResult(Base):
    """One row per hospital x analysis unit x month (design spec 2026-10-08 §3.1).

    analysis_code is the row's analysis unit: the data-element code for count
    rows, the synthetic rate code (rate_cs, ...) for rate rows. Written by
    app/engine/pipeline.py::_save_layered_results; never mutated afterwards.
    """
    __tablename__ = "layered_outlier_results"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=True)
    analysis_code = Column(String(50), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    raw_value = Column(Float, nullable=True)
    previous_value = Column(Float, nullable=True)
    numerator = Column(Float, nullable=True)
    denominator = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    previous_denominator = Column(Float, nullable=True)
    denominator_change_percent = Column(Float, nullable=True)
    historical_mean = Column(Float, nullable=True)
    historical_median = Column(Float, nullable=True)
    historical_std = Column(Float, nullable=True)
    historical_z_score = Column(Float, nullable=True)
    historical_change_percent = Column(Float, nullable=True)
    raw_value_outlier_score = Column(Float, nullable=True)
    rate_outlier_score = Column(Float, nullable=True)
    historical_outlier_score = Column(Float, nullable=True)
    volume_anomaly_score = Column(Float, nullable=True)
    peer_outlier_score = Column(Float, nullable=True)
    peer_mean = Column(Float, nullable=True)
    peer_count = Column(Integer, nullable=True)
    outlier_level = Column(String(20), nullable=True)           # NONE/LOW/MODERATE/HIGH/VERY_HIGH
    outlier_type = Column(String(40), nullable=True)            # classification enum (§3.1)
    outlier_method = Column(String(30), nullable=True)
    interpretation = Column(Text, nullable=True)
    investigation_required = Column(Boolean, nullable=True, server_default=text("false"))
    investigation_route = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital")
    indicator = relationship("Indicator")

    __table_args__ = (
        UniqueConstraint("hospital_id", "analysis_code", "month", name="uq_layered_hosp_code_month"),
        Index("ix_lr_hosp_month", "hospital_id", "month"),
        Index("ix_lr_month_type", "month", "outlier_type"),
    )


class QualityScore(Base):
    __tablename__ = "quality_scores"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    score = Column(Float, nullable=False)
    rule_compliance = Column(Float, nullable=True)
    completeness = Column(Float, nullable=True)
    consistency = Column(Float, nullable=True)
    outlier_penalty = Column(Float, nullable=True)
    issues = Column(Text, nullable=True)

    hospital = relationship("Hospital", back_populates="quality_scores")

    __table_args__ = (
        Index("ix_qs_hosp_month", "hospital_id", "month"),
        Index("ix_qs_month", "month"),
    )


class ClinicalInsight(Base):
    __tablename__ = "clinical_insights"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    analysis_data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital")

    __table_args__ = (
        Index("ix_ci_hosp_month", "hospital_id", "month"),
    )


class ConfidenceScore(Base):
    __tablename__ = "confidence_scores"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    overall_confidence = Column(Float, nullable=False)
    level = Column(String(20), nullable=False)
    indicator_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    indicators_data = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_cs_hosp_month", "hospital_id", "month"),
        Index("ix_cs_level", "level"),
    )


class ConfidenceWeights(Base):
    __tablename__ = "confidence_weights"

    id = Column(Integer, primary_key=True, index=True)
    rule_compliance = Column(Float, nullable=False, default=0.55)
    historical = Column(Float, nullable=False, default=0.10)
    cross_hospital = Column(Float, nullable=False, default=0.10)
    trend = Column(Float, nullable=False, default=0.10)
    completeness = Column(Float, nullable=False, default=0.15)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Float, nullable=False)
    category = Column(String(50), nullable=False, default="general")
    label = Column(String(200), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String(200), unique=True, nullable=False, index=True)
    result_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Auth models ---

user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, index=True)
    codename = Column(String(80), unique=True, nullable=False)
    description = Column(String(200))


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200))
    is_system = Column(Boolean, default=False)
    permissions = relationship("Permission", secondary=role_permissions, backref="roles")


user_hospitals = Table(
    "user_hospitals", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("hospital_id", Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True),
)

user_permissions = Table(
    "user_permissions", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    password_hash = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    roles = relationship("Role", secondary=user_roles, backref="users")
    permissions = relationship("Permission", secondary=user_permissions, backref="users")
    hospitals = relationship("Hospital", secondary=user_hospitals, backref="users")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    token_jti = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SessionLog(Base):
    __tablename__ = "session_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(100), nullable=False)
    event = Column(String(20), nullable=False)  # login, logout, refresh, expired
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", backref="session_logs")


# --- Menu models ---

class MenuGroup(Base):
    __tablename__ = "menu_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    icon = Column(String(20), default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    items = relationship(
        "MenuItem", back_populates="group",
        cascade="all, delete-orphan",
        order_by="MenuItem.sort_order",
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("menu_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    tab_key = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)

    group = relationship("MenuGroup", back_populates="items")

    __table_args__ = (UniqueConstraint("group_id", "tab_key"),)


# --- Quality Alerts (risk-outlier monitoring, 2026-10-21) -------------------
# One row PER (hospital, indicator, month, PERSPECTIVE) — the evidence unit.
# The API groups rows of the same (hospital, indicator, month) into a single
# risk issue that shows every perspective which fired, so distinct evidence
# is preserved without cluttering the dashboard with duplicate alerts.
# Indicator values are NEVER recalculated here: rows are produced by
# app/engine/quality_alerts.py from the authoritative registry calculation
# (indicator_service.calculate_from_values), and severity uses the existing
# layered band cutoffs — no hardcoded clinical formulas in this module.

QUALITY_ALERT_SEVERITIES = ("LOW", "MODERATE", "HIGH", "VERY_HIGH")  # VERY_HIGH = RED ALERT — same bands as layered.BAND_CUTOFFS
QUALITY_ALERT_STATUSES = ("New", "Under Review", "Confirmed Issue", "False Positive", "Resolved")
QUALITY_ALERT_PERSPECTIVES = (
    "history",        # hospital vs its own prior periods
    "type",           # vs hospitals of the same hospital_type
    "ownership",      # vs hospitals of the same facility_ownership
    "facility_type",  # vs hospitals of the same facility_type
    "governorate",    # vs hospitals in the same governorate
    "all",            # vs all eligible hospitals with valid data
)


class QualityAlert(Base):
    __tablename__ = "quality_alerts"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    perspective = Column(String(20), nullable=False, index=True)

    # Registry provenance — the indicator is identified by its stable code in
    # the Indicators Registry (IndicatorDefinition); formula/unit/version are
    # copied at scan time so a later edit stays auditable.
    indicator_id = Column(Integer, ForeignKey("indicator_definitions.id", ondelete="SET NULL"), nullable=True)
    indicator_code = Column(String(50), nullable=False, index=True)
    indicator_name = Column(String(500), nullable=False)
    unit = Column(String(30), nullable=True)
    formula = Column(Text, nullable=True)
    formula_version = Column(String(64), nullable=True)

    # Statistical finding
    severity = Column(String(10), nullable=False, index=True)      # LOW..VERY_HIGH
    score = Column(Float, nullable=True)                           # 0-1, existing BAND_CUTOFFS currency
    method = Column(String(30), nullable=False, default="zscore")  # zscore | robust_z | iqr | pct_change | trend_deviation
    current_value = Column(Float, nullable=True)                   # authoritative calculated value
    baseline_value = Column(Float, nullable=True)                  # peer mean / own-history mean
    deviation_pct = Column(Float, nullable=True)
    z_score = Column(Float, nullable=True)
    peer_count = Column(Integer, nullable=True)

    # Clinical interpretation (registry direction metadata) — statistical
    # outlier status is NEVER relabelled harmful solely for being high.
    direction = Column(String(20), nullable=True)         # higher_is_better | lower_is_better | target_range | none
    interpretation = Column(String(30), nullable=True)    # high_is_concern | high_is_favorable | outside_target_range | statistical_only

    reason = Column(Text, nullable=True)                  # human-readable trigger explanation
    confidence = Column(String(10), nullable=True)        # high | low (small peer group / ML disagreement)
    evidence = Column(JSON, nullable=True)                # peers, history series, thresholds, ml cross-check

    status = Column(String(20), nullable=False, default="New", index=True)
    assignee = Column(String(120), nullable=True)
    active = Column(Boolean, nullable=False, server_default=text("true"), default=True, index=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    hospital = relationship("Hospital")
    definition = relationship("IndicatorDefinition")
    events = relationship("QualityAlertEvent", back_populates="alert",
                          cascade="all, delete-orphan", order_by="QualityAlertEvent.created_at")

    __table_args__ = (
        UniqueConstraint("hospital_id", "indicator_code", "month", "perspective",
                         name="uq_quality_alert_hosp_ind_month_perspective"),
        Index("ix_quality_alert_issue", "hospital_id", "indicator_code", "month"),
    )


class QualityAlertEvent(Base):
    """Investigation trail: status changes, notes, assignments (spec §10)."""

    __tablename__ = "quality_alert_events"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("quality_alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=True)   # NULL = note-only event
    note = Column(Text, nullable=True)
    actor = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("QualityAlert", back_populates="events")


class QualityAlertAudit(Base):
    """Durable record of a batch action that rewrote stored Quality Alerts.

    ``QualityAlertEvent`` covers the per-alert investigation workflow; a
    targeted recompute spans many alerts at once, so it is recorded here with
    who ran it, which months were touched and what each scope produced. Rows
    are append-only: nothing in the app updates or deletes them.
    """

    __tablename__ = "quality_alert_audit"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(40), nullable=False, index=True)   # e.g. rescan_stale
    actor = Column(String(120), nullable=False)
    months = Column(JSON, nullable=True)     # ["2026-08", "2026-09"]
    details = Column(JSON, nullable=True)    # hospitals / indicators / counters
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
