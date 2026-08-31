from datetime import datetime
from sqlalchemy import Table, Column, Integer, String, Float, Text, ForeignKey, DateTime, Boolean, UniqueConstraint, Index
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

    parent = relationship("Indicator", remote_side=[id], backref="children")
    values = relationship("IndicatorValue", back_populates="indicator")
    hospital_configs = relationship("HospitalIndicatorConfig", back_populates="indicator", cascade="all, delete-orphan")


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
    rate_name = Column(String(100), nullable=False)
    value = Column(Float, nullable=True)
    benchmark = Column(Float, nullable=True)
    z_score = Column(Float, nullable=True)
    is_outlier = Column(Boolean, default=False)

    hospital = relationship("Hospital", back_populates="anomaly_results")

    __table_args__ = (
        Index("ix_ar_hosp_month", "hospital_id", "month"),
        Index("ix_ar_outlier", "is_outlier"),
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