from dotenv import load_dotenv

load_dotenv()

import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from alembic import command  # noqa: E402
from app.api import admin as admin_router
from app.api import (  # noqa: E402
    alerts,
    analysis,
    clinical,
    confidence,
    config_api,
    dashboard,
    file_ops,
    hospitals,
    indicator_config,
    reports,
    root_cause,
    tree_config,
    upload,
)
from app.api import audit as audit_api
from app.api import auth as auth_router
from app.api import comparative as comparative_router
from app.api import export as export_router
from app.api import facility_ownerships as facility_ownerships_api
from app.api import facility_types as facility_types_api
from app.api import governorates as governorates_api
from app.api import hospital_types as hospital_types_api
from app.api import indicator_definitions as indicator_definitions_router
from app.api import indicator_groups as indicator_groups_router
from app.api import menu as menu_router
from app.api import quality_alerts as quality_alerts_router
from app.api import regional as regional_router
from app.api import rules as rules_api
from app.api import server_logs as server_logs_router
from app.api import smart_analytics as smart_analytics_router
from app.config import (  # noqa: E402
    ADMIN_PASSWORD,
    BASE_DIR,
    DATABASE_URL,
    DEV_ADMIN_PASSWORD,
    IS_PRODUCTION,
    UPLOAD_DIR,
)
from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.engine.quality import QUALITY_WEIGHT_DEFAULTS, SEVERITY_WEIGHT_DEFAULTS  # noqa: E402
from app.engine.severity import TREND_SETTING_SPECS  # noqa: E402
from app.models import AppConfig, FacilityOwnership, FacilityType, Governorate, HospitalType  # noqa: E402
from app.monitoring import (  # noqa: E402
    CONTENT_TYPE_LATEST,
    REGISTRY,
    generate_latest,
    monitoring_middleware,
    setup_structured_logging,
)
from app.tasks import get_task  # noqa: E402
from scripts.seed_hospital_metadata import seed_hospital_metadata  # noqa: E402
from scripts.seed_indicators import (  # noqa: E402
    seed_indicators,
    seed_rate_config,
    seed_system_indicator_definitions,
)
from scripts.seed_menu import seed_menu  # noqa: E402
from scripts.seed_rules import remove_benchmark_validation_data, seed_rules  # noqa: E402

setup_structured_logging(logging.INFO)


APP_CONFIG_DEFAULTS = [
    ("quality_rule_compliance", QUALITY_WEIGHT_DEFAULTS["rule_compliance"], "quality", "Validation rule Weight"),
    ("quality_completeness", QUALITY_WEIGHT_DEFAULTS["completeness"], "quality", "Completeness Weight"),
    ("quality_consistency", QUALITY_WEIGHT_DEFAULTS["consistency"], "quality", "Consistency Weight"),
    ("quality_outlier_penalty", QUALITY_WEIGHT_DEFAULTS["outlier_penalty"], "quality", "Outlier Penalty Weight"),
    ("outlier_multiplier", 2.0, "quality", "Outlier Penalty Multiplier"),
    # Consistency severity weights. CRITICAL defaults to 1.0 — the value it
    # silently borrowed before the setting existed — so seeding it leaves
    # every stored score unchanged until an operator raises it.
    ("severity_critical", SEVERITY_WEIGHT_DEFAULTS["CRITICAL"], "quality", "Severity CRITICAL Weight"),
    ("severity_high", SEVERITY_WEIGHT_DEFAULTS["HIGH"], "quality", "Severity HIGH Weight"),
    ("severity_medium", SEVERITY_WEIGHT_DEFAULTS["MEDIUM"], "quality", "Severity MEDIUM Weight"),
    ("severity_low", SEVERITY_WEIGHT_DEFAULTS["LOW"], "quality", "Severity LOW Weight"),
    ("zscore_threshold", 2.5, "thresholds", "Z-Score Threshold"),
    ("confidence_high", 80.0, "thresholds", "HIGH Confidence Cutoff"),
    ("confidence_medium", 50.0, "thresholds", "MEDIUM Confidence Cutoff"),
    ("confidence_low", 25.0, "thresholds", "LOW Confidence Cutoff"),
    # Quality Alerts (category "alerts"): detection floors documented per
    # spec §4 "Make thresholds configurable and document their meaning".
    ("alerts_min_score", 0.5, "alerts", "Minimum Alert Score 0-1 (0.5 = MODERATE band)"),
    ("alerts_min_peers", 2.0, "alerts", "Minimum Peer Hospitals for a baseline"),
    ("alerts_min_history", 3.0, "alerts", "Minimum History Periods for a baseline"),
    ("alerts_history_window", 12.0, "alerts", "History Baseline Window (months)"),
    ("alerts_ml_enabled", 1.0, "alerts", "Enable Isolation-Forest Cross-check"),
    ("alerts_ml_min_samples", 12.0, "alerts", "Minimum Hospitals for ML Cross-check"),
    ("alerts_auto_scan", 1.0, "alerts", "Auto-scan alerts after each analysis (1=on, 0=off)"),
    ("eq_tolerance", 0.01, "rules", "Equality Tolerance"),
    ("month_over_factor", 2.0, "rules", "Month Over Factor"),
    ("month_under_factor", 0.5, "rules", "Month Under Factor"),
    ("maternal_over_factor", 4.0, "rules", "Maternal Deaths Over Factor"),
    ("neonatal_over_factor", 4.0, "rules", "Neonatal Deaths Over Factor"),
    ("clinical_cs_rate_critical", 40.0, "clinical", "C-Section Rate Critical (%)"),
    ("clinical_cs_rate_high", 25.0, "clinical", "C-Section Rate High (%)"),
    ("clinical_cs_rate_elevated", 15.0, "clinical", "C-Section Rate Elevated (%)"),
    ("clinical_mmr_critical", 300.0, "clinical", "Maternal Mortality Ratio Critical"),
    ("clinical_mmr_high", 150.0, "clinical", "Maternal Mortality Ratio High"),
    ("clinical_mmr_elevated", 50.0, "clinical", "Maternal Mortality Ratio Elevated"),
    ("clinical_nmr_critical", 45.0, "clinical", "Neonatal Mortality Rate Critical"),
    ("clinical_nmr_high", 30.0, "clinical", "Neonatal Mortality Rate High"),
    ("clinical_nmr_elevated", 15.0, "clinical", "Neonatal Mortality Rate Elevated"),
    ("clinical_smm_critical", 10.0, "clinical", "SMM Rate Critical (%)"),
    ("clinical_smm_high", 5.0, "clinical", "SMM Rate High (%)"),
    ("clinical_smm_elevated", 2.0, "clinical", "SMM Rate Elevated (%)"),
    ("clinical_preterm_critical", 20.0, "clinical", "Preterm Birth Rate Critical (%)"),
    ("clinical_preterm_high", 15.0, "clinical", "Preterm Birth Rate High (%)"),
    ("clinical_preterm_elevated", 10.0, "clinical", "Preterm Birth Rate Elevated (%)"),
    ("clinical_stillbirth_critical", 35.0, "clinical", "Stillbirth Rate Critical"),
    ("clinical_stillbirth_high", 22.0, "clinical", "Stillbirth Rate High"),
    ("clinical_stillbirth_elevated", 12.0, "clinical", "Stillbirth Rate Elevated"),
    ("clinical_nicu_critical", 40.0, "clinical", "NICU Admission Rate Critical (%)"),
    ("clinical_nicu_high", 25.0, "clinical", "NICU Admission Rate High (%)"),
    ("clinical_nicu_elevated", 15.0, "clinical", "NICU Admission Rate Elevated (%)"),
    ("clinical_lbw_critical", 20.0, "clinical", "Low Birth Weight Rate Critical (%)"),
    ("clinical_lbw_high", 15.0, "clinical", "Low Birth Weight Rate High (%)"),
    ("clinical_lbw_elevated", 10.0, "clinical", "Low Birth Weight Rate Elevated (%)"),
    ("clinical_bf_critical", 40.0, "clinical", "Breastfeeding Rate Critical (%)"),
    ("clinical_bf_high", 60.0, "clinical", "Breastfeeding Rate High (%)"),
    ("clinical_bf_elevated", 80.0, "clinical", "Breastfeeding Rate Elevated (%)"),
    ("clinical_avd_critical", 30.0, "clinical", "Assisted VD Rate Critical (%)"),
    ("clinical_avd_high", 20.0, "clinical", "Assisted VD Rate High (%)"),
    ("clinical_avd_elevated", 15.0, "clinical", "Assisted VD Rate Elevated (%)"),
    ("clinical_hemorrhage_critical", 70.0, "clinical", "Hemorrhage % of SMM Critical (%)"),
    ("clinical_hemorrhage_high", 55.0, "clinical", "Hemorrhage % of SMM High (%)"),
    ("clinical_hemorrhage_elevated", 40.0, "clinical", "Hemorrhage % of SMM Elevated (%)"),
    ("clinical_hypertensive_critical", 55.0, "clinical", "Hypertensive % of SMM Critical (%)"),
    ("clinical_hypertensive_high", 40.0, "clinical", "Hypertensive % of SMM High (%)"),
    ("clinical_hypertensive_elevated", 25.0, "clinical", "Hypertensive % of SMM Elevated (%)"),
    ("clinical_adolescent_critical", 30.0, "clinical", "Adolescent Pregnancy Rate Critical (%)"),
    ("clinical_adolescent_high", 20.0, "clinical", "Adolescent Pregnancy Rate High (%)"),
    ("clinical_adolescent_elevated", 10.0, "clinical", "Adolescent Pregnancy Rate Elevated (%)"),
    ("clinical_high_risk_critical", 50.0, "clinical", "High-Risk Delivery Rate Critical (%)"),
    ("clinical_high_risk_high", 35.0, "clinical", "High-Risk Delivery Rate High (%)"),
    ("clinical_high_risk_elevated", 20.0, "clinical", "High-Risk Delivery Rate Elevated (%)"),
    ("clinical_hysterectomy_critical", 2.0, "clinical", "Hysterectomy per 1000 Critical"),
    ("clinical_hysterectomy_high", 1.0, "clinical", "Hysterectomy per 1000 High"),
    ("clinical_hysterectomy_elevated", 0.5, "clinical", "Hysterectomy per 1000 Elevated"),
    ("risk_peer_multiplier_high", 1.2, "risk", "Peer Comparison Multiplier (High)"),
    ("risk_peer_multiplier_critical", 1.5, "risk", "Peer Comparison Multiplier (Critical)"),
    ("risk_high_risk_rate_moderate", 20.0, "risk", "High-Risk Rate Moderate (%)"),
    ("risk_high_risk_rate_high", 35.0, "risk", "High-Risk Rate High (%)"),
    ("risk_high_risk_rate_critical", 50.0, "risk", "High-Risk Rate Critical (%)"),
    ("risk_adolescent_moderate", 10.0, "risk", "Adolescent Pregnancy Moderate (%)"),
    ("risk_adolescent_high", 20.0, "risk", "Adolescent Pregnancy High (%)"),
    ("risk_adolescent_critical", 30.0, "risk", "Adolescent Pregnancy Critical (%)"),
    ("risk_emergency_cs_moderate", 50.0, "risk", "Emergency C/S Proportion Moderate (%)"),
    ("risk_emergency_cs_high", 70.0, "risk", "Emergency C/S Proportion High (%)"),
    ("risk_emergency_cs_critical", 85.0, "risk", "Emergency C/S Proportion Critical (%)"),
    ("risk_infacility_moderate", 80.0, "risk", "In-Facility Delivery Rate Moderate (%)"),
    ("risk_infacility_high", 60.0, "risk", "In-Facility Delivery Rate High (%)"),
    ("risk_infacility_critical", 40.0, "risk", "In-Facility Delivery Rate Critical (%)"),
    ("trend_slope_stable", 2.0, "trends", "Slope Stable Threshold (%)"),
    ("trend_slope_low", 5.0, "trends", "Slope Low Severity (%)"),
    ("trend_slope_moderate", 15.0, "trends", "Slope Moderate Severity (%)"),
    ("trend_slope_high", 30.0, "trends", "Slope High Severity (%)"),
    ("trend_r_squared", 0.5, "trends", "R-Squared Threshold"),
    ("trend_finding_slope", 5.0, "trends", "Finding Generated Slope (%)"),
    ("trend_finding_deviation", 20.0, "trends", "Finding Generated Deviation (%)"),
    ("trend_finding_cv", 30.0, "trends", "Finding Generated CV (%)"),
    ("trend_finding_r_squared", 0.7, "trends", "Finding Generated R-Squared"),
    ("rate_cs_benchmark", 50.0, "rates", "C-Section Rate Benchmark (%)"),
    ("rate_mmr_benchmark", 1.0, "rates", "MMR Benchmark"),
    ("rate_nmr_benchmark", 30.0, "rates", "NMR Benchmark"),
    ("rate_preterm_benchmark", 15.0, "rates", "Preterm Birth Rate Benchmark (%)"),
    ("rate_smm_benchmark", 10.0, "rates", "SMM Rate Benchmark (%)"),
    ("rate_stillbirth_benchmark", 5.0, "rates", "Stillbirth Rate Benchmark (%)"),
    ("rate_nicu_benchmark", 20.0, "rates", "NICU Admission Rate Benchmark (%)"),
    # Smart Analytics config
    ("smart_enabled", 1.0, "smart_analytics", "Smart Enabled"),
    ("smart_contamination", 0.05, "smart_analytics", "Smart Contamination"),
    ("smart_lof_neighbors", 5.0, "smart_analytics", "Smart LOF Neighbors"),
    ("smart_dbscan_eps", 1.5, "smart_analytics", "Smart DBSCAN EPS"),
    ("smart_dbscan_min_samples", 3.0, "smart_analytics", "Smart DBSCAN Min Samples"),
    ("smart_threshold_green", 0.3, "smart_analytics", "Smart Threshold Green"),
    ("smart_threshold_yellow", 0.6, "smart_analytics", "Smart Threshold Yellow"),
    ("smart_shap_enabled", 1.0, "smart_analytics", "Smart SHAP Enabled"),
    ("smart_ensemble_if_weight", 0.35, "smart_analytics", "Smart Ensemble IF Weight"),
    ("smart_ensemble_lof_weight", 0.3, "smart_analytics", "Smart Ensemble LOF Weight"),
    ("smart_ensemble_mahal_weight", 0.2, "smart_analytics", "Smart Ensemble Mahal Weight"),
    ("smart_ensemble_residual_weight", 0.15, "smart_analytics", "Smart Ensemble Residual Weight"),
    ("smart_xgboost_enabled", 1.0, "smart_analytics", "Smart XGBoost Enabled"),
    ("smart_xgb_n_estimators", 100.0, "smart_analytics", "Smart XGBoost N Estimators"),
    ("smart_xgb_max_depth", 4.0, "smart_analytics", "Smart XGBoost Max Depth"),
]

# The trend persistence knob is part of the shared severity/trend policy spec
# (app.engine.severity), so its seeded default cannot drift from the value the
# engine and System Control validate against. It remains an AppConfig key — the
# setting is reused, not duplicated.
_TREND_PERSISTENCE = TREND_SETTING_SPECS["trend_finding_consecutive"]
APP_CONFIG_DEFAULTS.append(
    (_TREND_PERSISTENCE.key, _TREND_PERSISTENCE.default, "trends",
     _TREND_PERSISTENCE.label))


def run_alembic_upgrade():
    alembic_cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    script = ScriptDirectory.from_config(alembic_cfg)
    _head_revision = script.get_current_head()

    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables_exist = len(inspector.get_table_names()) > 0

    has_version_table = "alembic_version" in inspector.get_table_names()

    if tables_exist and not has_version_table:
        # Dialect-aware: works on both SQLite and PostgreSQL
        if "hospitals" in inspector.get_table_names():
            command.stamp(alembic_cfg, "head")
            return

    command.upgrade(alembic_cfg, "head")


_startup_done = False

# Schema-sync state, surfaced via /health: None = unknown, True/False after check.
schema_in_sync = None


def _check_migration_sync():
    """Compare the DB's applied alembic revision to the code's head revision.
    Model/migration drift has caused production 500s (UndefinedColumn); make
    that state visible at startup and in /health instead of discovered via
    broken endpoints. Non-fatal by design."""
    global schema_in_sync
    try:
        alembic_cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()
        from sqlalchemy import text
        with engine.connect() as conn:
            try:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            except Exception:
                row = None
        applied = row[0] if row else None
        if applied == head_rev:
            schema_in_sync = True
            print(f"[startup] Schema in sync (revision {head_rev})")
        else:
            schema_in_sync = False
            msg = (
                f"[startup] *** SCHEMA DRIFT *** database revision {applied} != code head {head_rev}. "
                "Run 'alembic upgrade head' on this database. Endpoints touching "
                "newer columns may 500 until then."
            )
            print(msg)
            logging.getLogger("uvicorn.error").warning(msg)
    except Exception as e:
        schema_in_sync = None
        print(f"[startup] Migration-sync check skipped: {e}")


def _db_already_initialized(session):
    """Check if migrations + seeding have already run (idempotent startup).

    Returns True only when:
    1. alembic_version table exists AND is stamped at the head revision, AND
    2. at least one AppConfig row exists (seeding has run).

    A stale alembic stamp (e.g. after a failed migration) must NOT count as
    initialized, otherwise pending migrations are never retried and code that
    references the new tables 500s (e.g. /dashboard/overview).
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text
    try:
        inspector = sa_inspect(session.get_bind())
        tables = inspector.get_table_names()
        if "alembic_version" not in tables:
            return False
        if "app_config" not in tables:
            return False
        if session.query(AppConfig).first() is None:
            return False
        script = ScriptDirectory.from_config(Config(os.path.join(BASE_DIR, "alembic.ini")))
        current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return current == script.get_current_head()
    except Exception:
        return False


def _log_db_info():
    """Log database connection at startup."""
    # Mask password in URL for logging
    safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    print(f"[startup] Database: PostgreSQL ({safe_url})")


def _ensure_all_tables():
    """Create any model tables missing from the database (idempotent).

    Alembic can leave tables absent in two common cases:
      1. A DB created via create_all was later stamped to head (the stamp path
         in _run_migrations), so migrations never ran for tables added later.
      2. An earlier migration partially failed/rolled back on the target DB.

    Code referencing those newer tables (indicator_default_config,
    hospital_indicator_config, ...) then 500s (e.g. /dashboard/overview and the
    indicator tree). create_all with checkfirst is cheap and only creates the
    tables that are missing, so this safely heals such drift at every boot.
    """
    try:
        from app import models  # noqa: F401  register every model in metadata
        from app.database import Base as _Base
        _Base.metadata.create_all(engine, checkfirst=True)
        print("[startup] Missing model tables ensured (create_all checkfirst).")
    except Exception as e:
        print(f"[startup] Table ensure error (non-fatal): {e}")


def _ensure_required_columns(engine=None):
    """Add model columns missing from existing tables (idempotent, best-effort).

    create_all (see _ensure_all_tables) heals missing *tables* but never
    missing *columns* on tables that already exist. A database created before
    a column-adding migration and later stamped to head (or hit by a partial
    migration run) therefore stays on the old shape, and any endpoint whose
    ORM selects the new columns 500s — e.g. /analysis/outliers raised
    "no such column: peer_count" after the anomaly peer-metadata migrations.

    This safety net re-adds such columns directly from the ORM metadata:
      - only nullable columns (or ones with a server default) are added, so
        existing rows read as NULL/default and no data can be lost;
      - guarded per column, so it is safe to run at every startup;
      - alembic remains the primary mechanism — this only covers drift that
        alembic will never revisit because the DB is stamped at head.
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text
        from sqlalchemy.schema import CreateColumn

        from app.database import Base as _Base
        if engine is None:
            from app.database import engine as _db_engine
            engine = _db_engine
        if engine is None:
            return
        from app import models  # noqa: F401  register every model in metadata
        insp = sa_inspect(engine)
        preparer = engine.dialect.identifier_preparer
        existing_tables = set(insp.get_table_names())
        added = []
        with engine.begin() as conn:
            for table in _Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue  # missing tables are _ensure_all_tables' job
                existing_cols = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in existing_cols:
                        continue
                    if col.primary_key or not col.nullable:
                        continue  # unsafe to ADD COLUMN; leave to alembic
                    col_ddl = str(
                        CreateColumn(col).compile(dialect=engine.dialect)
                    ).strip()
                    stmt = text(
                        f"ALTER TABLE {preparer.quote(table.name)} "
                        f"ADD COLUMN {col_ddl}"
                    )
                    conn.execute(stmt)
                    added.append(f"{table.name}.{col.name}")
        if added:
            print(f"[startup] Added missing columns: {', '.join(added)}")
    except Exception as e:
        print(f"[startup] Column ensure error (non-fatal): {e}")


def seed_app_config(session):
    for key, value, category, label in APP_CONFIG_DEFAULTS:
        existing = session.query(AppConfig).filter(AppConfig.key == key).first()
        if not existing:
            session.add(AppConfig(key=key, value=value, category=category, label=label))
    session.commit()


def _seed_reference_data(session):
    """Seed governorates, hospital types, ownerships, facility types."""
    if not session.query(Governorate).first():
        for name in ["\u063a\u0632\u0629", "\u062e\u0627\u0646\u064a\u0648\u0646\u0633", "\u062f\u064a\u0631 \u0627\u0644\u0628\u0644\u062d", "\u062c\u0646\u0648\u0628 \u063a\u0632\u0629", "\u0634\u0645\u0627\u0644 \u063a\u0632\u0629", "\u0631\u0641\u062d"]:
            session.add(Governorate(name=name))
    if not session.query(HospitalType).first():
        for name in ["\u0639\u0627\u0645", "\u062a\u062e\u0635\u0635\u064a", "\u0645\u064a\u062f\u0627\u0646\u064a", "\u0645\u0631\u0636\u0636 \u0627\u0644\u0637\u0641\u0644"]:
            session.add(HospitalType(name=name))
    if not session.query(FacilityOwnership).first():
        for name in ["\u062d\u0639\u0648\u0645\u064a", "NGOs", "INGOs", "\u062e\u0627\u0635"]:
            session.add(FacilityOwnership(name=name))
    if not session.query(FacilityType).first():
        session.add(FacilityType(name="\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"))



def _ensure_auth_tables(session):
    """Create auth tables if they don't exist (handles partial migration failures)."""
    try:
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(session.get_bind())
        existing = set(insp.get_table_names())
        needed = {'users', 'roles', 'permissions', 'refresh_tokens', 'user_roles', 'role_permissions', 'user_hospitals'}
        missing = needed - existing
        if missing:
            print(f"[startup] Creating missing auth tables: {missing}")
            from app.database import Base
            # Create tables in dependency order: no FKs first, then with FKs
            create_order = ['permissions', 'roles', 'users', 'refresh_tokens', 'user_roles', 'role_permissions', 'user_hospitals']
            for tname in create_order:
                if tname in missing:
                    table = Base.metadata.tables.get(tname)
                    if table is not None:
                        table.create(bind=session.get_bind(), checkfirst=True)
            print("[startup] Auth tables created.")
        else:
            print("[startup] Auth tables already exist.")
    except Exception as e:
        print(f"[startup] Auth table creation error: {e}")


def _ensure_permission_rows(session, codenames):
    """Create missing Permission rows (self-heals partially-migrated DBs).

    Migrations can be stamped at head while row inserts were never actually
    applied (see deployed-Postgres condition described in 6128ff7). Permission
    grants only link existing rows, so missing rows silently produce 403s
    ("Missing permission: ...") for every non-superuser. Ensure the canonical
    rows exist before granting.
    """
    from app.models import Permission
    for codename in codenames:
        if session.query(Permission.id).filter(Permission.codename == codename).first() is None:
            session.add(Permission(codename=codename, description="Auto-granted permission"))
    session.commit()


CANONICAL_PERMISSION_CODENAMES = [
    # Base schema (c3a1d5e7f920)
    "dashboard.read", "analysis.read", "quality.read", "outliers.read",
    "clinical.read", "alerts.read", "hospitals.read", "smart_analytics.read",
    "rules.read", "root_cause.read", "audit.read", "settings.read",
    "data.upload", "data.export", "smart_analytics.generate_report",
    "system.manage_users",
    # Extended permissions (e2f3a4b5c6d7)
    # hospitals.unrestricted is not a route guard: it is the authorization that
    # makes get_user_hospital_ids() return None (every hospital) instead of an
    # empty assignment. It MUST be canonical, otherwise the row is never seeded,
    # the admin-role grant below finds nothing to attach, and every non-superuser
    # admin silently sees zero hospitals — i.e. an empty app.
    "hospitals.write", "hospitals.manage", "hospitals.unrestricted",
    "governorates.read", "governorates.write", "governorates.manage",
    "hospital_types.read", "hospital_types.write", "hospital_types.manage",
    "facility_ownerships.read", "facility_ownerships.write", "facility_ownerships.manage",
    "facility_types.read", "facility_types.write", "facility_types.manage",
    "data.read", "data.manage",
    "reports.read", "reports.export",
    "comparative.read", "regional.read",
    "dashboard.write",
    "rules.write", "rules.manage",
    "settings.write",
    "ai.read", "ai.write",
    "system.read_audit", "system.manage_data", "system.export_data",
    # Quality Alerts risk-outlier screen (q4a7e8f1b2c3)
    "quality_alerts.read", "quality_alerts.write",
    # Menu management (b6c7d8e9f0a1)
    "menu.manage",
]


def _ensure_admin_user(session):
    """Seed default admin user if users table is empty."""
    try:
        from app.models import Role, User
        _ensure_permission_rows(session, CANONICAL_PERMISSION_CODENAMES)

        admin = session.query(User).filter(User.username == "admin").first()
        if admin is None:
            from app.core.security import hash_password
            admin_pw = ADMIN_PASSWORD
            admin = User(
                username="admin", email="admin@health.local",
                full_name="System Administrator",
                password_hash=hash_password(admin_pw),
                is_active=True, is_superuser=True,
            )
            session.add(admin)
            session.flush()
            print("[startup] Default admin user created.")
        else:
            # Always enforce superuser + active on the built-in admin
            changed = False
            if not admin.is_superuser:
                admin.is_superuser = True
                changed = True
            if not admin.is_active:
                admin.is_active = True
                changed = True
            if changed:
                session.commit()
                print("[startup] Admin user flags corrected (is_superuser=True, is_active=True).")

        # Ensure admin has the superadmin role
        sa_role = session.query(Role).filter(Role.name == "superadmin").first()
        if sa_role and sa_role not in admin.roles:
            admin.roles.append(sa_role)
            session.commit()
            print("[startup] Superadmin role assigned to admin user.")
        elif not admin.roles and sa_role:
            admin.roles.append(sa_role)
            session.commit()
            print("[startup] Superadmin role assigned to admin user.")

        # Ensure superadmin role has ALL permissions
        from app.models import Permission
        all_perms = session.query(Permission).all()
        if sa_role and len(sa_role.permissions) < len(all_perms):
            sa_role.permissions = all_perms
            session.commit()
            print(f"[startup] Assigned {len(all_perms)} permissions to superadmin role.")

        # Assign new permissions to admin role
        admin_role = session.query(Role).filter(Role.name == "admin").first()
        if admin_role:
            admin_grant_codenames = [
                    "hospitals.write", "hospitals.manage", "hospitals.unrestricted",
                    "governorates.read", "governorates.write", "governorates.manage",
                    "hospital_types.read", "hospital_types.write", "hospital_types.manage",
                    "facility_ownerships.read", "facility_ownerships.write", "facility_ownerships.manage",
                    "facility_types.read", "facility_types.write", "facility_types.manage",
                    "data.read", "data.manage",
                    "reports.read", "reports.export",
                    "comparative.read", "regional.read",
                    "dashboard.write",
                    "rules.write", "rules.manage",
                    "settings.write",
                    "ai.read", "ai.write",
                    "system.read_audit", "system.manage_data", "system.export_data",
                    "menu.manage",
            ]
            write_manage_perms = session.query(Permission).filter(
                Permission.codename.in_(admin_grant_codenames)
            ).all()
            existing_ids = {p.id for p in admin_role.permissions}
            new_perms = [p for p in write_manage_perms if p.id not in existing_ids]
            if new_perms:
                admin_role.permissions.extend(new_perms)
                session.commit()
                print(f"[startup] Added {len(new_perms)} new permissions to admin role.")

        # Ensure superadmin user exists (separate from admin)
        sa_user = session.query(User).filter(User.username == "superadmin").first()
        if sa_user is None:
            from app.core.security import hash_password
            sa_user = User(
                username="superadmin", email="superadmin@health.local",
                full_name="Super Administrator",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_active=True, is_superuser=True,
            )
            session.add(sa_user)
            session.flush()
            if sa_role:
                sa_user.roles.append(sa_role)
            session.commit()
            print("[startup] Superadmin user created (username=superadmin).")

        # Development-only demo accounts (doctor/viewer). Never seeded in
        # production so no known-password login ships to a live deployment.
        if not IS_PRODUCTION:
            for uname, email, fname, rolename in [
                ("doctor", "doctor@health.local", "Dr. Ahmed", "doctor"),
                ("viewer", "viewer@health.local", "Viewer User", "viewer"),
            ]:
                if not session.query(User).filter(User.username == uname).first():
                    from app.core.security import hash_password
                    u = User(
                        username=uname, email=email, full_name=fname,
                        password_hash=hash_password(DEV_ADMIN_PASSWORD),
                        is_active=True, is_superuser=False,
                    )
                    session.add(u)
                    session.flush()
                    role = session.query(Role).filter(Role.name == rolename).first()
                    if role:
                        u.roles.append(role)
                    session.commit()
                    print(f"[startup] Dev user created: {uname} (role={rolename}).")

        print("[startup] Admin user verified.")
    except Exception as e:
        print(f"[startup] Admin user check/seed error: {e}")


@asynccontextmanager
def _deactivate_hospitals_without_data(session):
    """Mark hospitals as inactive if they have no indicator values loaded."""

    from app.models import Hospital, IndicatorValue

    # Get hospital IDs that have at least one *real* indicator value — the
    # importer stores NULL rows for empty upload cells, and those must not
    # count as data or a hospital whose whole report is blank stays active
    # while Settings shows it "has data".
    hospitals_with_data = set(
        row[0] for row in (
            session.query(IndicatorValue.hospital_id)
            .filter(IndicatorValue.value.isnot(None))
            .distinct()
            .all()
        )
    )

    all_hospitals = session.query(Hospital).all()
    deactivated = 0
    for h in all_hospitals:
        if h.is_active and h.id not in hospitals_with_data:
            h.is_active = False
            deactivated += 1

    if deactivated:
        print(f"[startup] Deactivated {deactivated} hospitals with no indicator data")


async def lifespan(app: FastAPI):
    global _startup_done
    from app.api.server_logs import install_buffer_handler
    install_buffer_handler(logging.WARNING)
    from app.database import _db_ready
    if not _db_ready:
        print("[startup] DATABASE_URL not configured — showing setup page")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        yield
        return
    init_db()
    _log_db_info()
    _check_migration_sync()
    _ensure_all_tables()
    # Heal missing columns too (create_all only creates missing tables; a DB
    # stamped at head with an older column shape would otherwise 500 endpoints
    # that select newer columns, e.g. /analysis/outliers → "no such column:
    # peer_count").
    _ensure_required_columns()
    if not _startup_done:
        session = SessionLocal()
        try:
            already_init = _db_already_initialized(session)
            if not already_init:
                print("[startup] Running migrations and seeding...")
                try:
                    run_alembic_upgrade()
                    print("[startup] Migrations complete.")
                except Exception as e:
                    print(f"[startup] Migration error (non-fatal): {e}")
                    import traceback
                    traceback.print_exc()
                # Fresh session after DDL changes
                session.close()
                session = SessionLocal()
                for label, fn in [("config", seed_app_config), ("indicators", seed_indicators), ("rules", seed_rules), ("menu", seed_menu)]:
                    try:
                        fn(session)
                        print(f"[startup] {label.capitalize()} seeded.")
                    except Exception as e:
                        print(f"[startup] {label} seed error: {e}")
                try:
                    _seed_reference_data(session)
                    session.commit()
                    print("[startup] Migrations and seeding complete.")
                except Exception as e:
                    print(f"[startup] Reference data error (non-fatal): {e}")
                    import traceback
                    traceback.print_exc()

            # Config defaults must reach EXISTING databases too: a key added
            # to APP_CONFIG_DEFAULTS later (e.g. alerts_auto_scan) would never
            # appear on a DB created before it existed, leaving Settings unable
            # to show or change it. seed_app_config inserts only missing keys,
            # so running it on every startup is idempotent and cheap.
            try:
                seed_app_config(session)
            except Exception as e:
                print(f"[startup] Config default backfill error (non-fatal): {e}")

            # Severity / temporal-trend controls: persist defaults for genuinely
            # new settings (insert-only) and drop the deprecated duplicate
            # Z-score SystemSetting. thresholds.zscore_threshold (2.5) remains
            # the single authoritative Z-score threshold.
            try:
                from app.api.config_api import (
                    reconcile_legacy_settings,
                    seed_severity_trend_settings,
                )
                created = seed_severity_trend_settings(session)
                if created:
                    print(f"[startup] Seeded {created} severity/trend setting(s).")
                removed = reconcile_legacy_settings(session)
                if removed:
                    print(f"[startup] Removed legacy duplicate setting(s): {removed}")
            except Exception as e:
                print(f"[startup] Severity/trend config backfill error (non-fatal): {e}")

            try:
                removed_rules, removed_results, removed_settings = remove_benchmark_validation_data(session)
                if removed_rules or removed_results or removed_settings:
                    session.commit()
                    print(
                        "[startup] Removed legacy benchmark validation data "
                        f"({removed_rules} rules, {removed_results} results, {removed_settings} settings)."
                    )
            except Exception as e:
                session.rollback()
                print(f"[startup] Benchmark validation cleanup failed: {e}")
                raise

            # Always ensure auth tables exist (migration may have partially failed)
            # Create a fresh session in case DDL changes were made
            try:
                _ensure_auth_tables(session)
            except Exception as e:
                print(f"[startup] Auth table creation error (non-fatal): {e}")
            session.close()
            session = SessionLocal()
            try:
                _ensure_admin_user(session)
            except Exception as e:
                print(f"[startup] Admin user setup error (non-fatal): {e}")

            # Backfill menu items for tabs added to the registry after this
            # database was first initialized (the full seed only runs on an
            # empty menu table). seed_menu is idempotent — a no-op when
            # nothing is missing — so this is safe on every startup.
            try:
                backfilled = seed_menu(session)
                if backfilled:
                    print(f"[startup] Menu backfilled: {', '.join(backfilled)}")
            except Exception as e:
                print(f"[startup] Menu backfill error (non-fatal): {e}")

            # Seed layered rate_config rows from the central registry
            # (idempotent insert-if-missing — same every-startup pattern as
            # the menu backfill above). The engine falls back to the builtin
            # registry when the table is empty, so a seed failure is non-fatal.
            try:
                seeded = seed_rate_config(session)
                if seeded:
                    print(f"[startup] Rate config seeded: {seeded} rows.")
            except Exception as e:
                print(f"[startup] Rate config seed error (non-fatal): {e}")
            try:
                seeded_definitions = seed_system_indicator_definitions(session)
                if seeded_definitions:
                    print(
                        "[startup] System indicator definitions migrated: "
                        f"{seeded_definitions} rows."
                    )
            except Exception as e:
                print(f"[startup] System indicator migration error (non-fatal): {e}")

            # Apply hospital metadata (OrgUnit ID, Ownership, Governorate, Type)
            # from scripts/hospital_metadata.json - safe to run every startup.
            try:
                updated = seed_hospital_metadata(session)
                if updated:
                    print(f"[startup] Applied metadata to {updated} hospitals")
            except Exception as e:
                print(f"[startup] Hospital metadata seeding skipped: {e}")

            # Auto-deactivate hospitals that have no indicator data
            try:
                _deactivate_hospitals_without_data(session)
            except Exception as e:
                print(f"[startup] Auto-inactive check skipped: {e}")

            session.commit()  # ensure clean state

            # Load logging setting
            from app.models import SystemSetting
            from app.monitoring import set_logging_enabled, set_slow_query_logging
            try:
                log_row = session.query(SystemSetting).filter(SystemSetting.key == "structured_logging_enabled").first()
                set_logging_enabled(log_row.value == "true" if log_row else True)
            except Exception:
                set_logging_enabled(True)
            try:
                sq_row = session.query(SystemSetting).filter(SystemSetting.key == "slow_query_logging_enabled").first()
                set_slow_query_logging(sq_row.value == "true" if sq_row else True)
            except Exception:
                set_slow_query_logging(True)
        finally:
            session.close()
        _startup_done = True

    # Data-epoch sweep: fingerprint the DB content, then drop every cache
    # file written under a different data state (dump restores, re-imports,
    # purges) or before epoch scoping existed. Without this, a restore while
    # the app ran left the app serving a day of phantom months/hospitals/
    # scores from stale files.
    try:
        from app.cache import cache as _epoch_cache
        from app.cache import get_data_epoch
        _epoch_cache.sweep_stale_epochs(get_data_epoch())
    except Exception as _epoch_exc:
        print(f"[startup] Cache epoch sweep skipped: {_epoch_exc}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    yield


app = FastAPI(
    title="Health AI - SRMNH Data Quality System",
    description="MVP for maternal and neonatal health indicator data quality analysis",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_env = os.getenv("CORS_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = [
        "http://localhost:9090", "http://127.0.0.1:9090",
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:8123", "http://127.0.0.1:8123",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # A wildcard origin cannot be combined with credentials (and doing so is a
    # CSRF-grade hole); only allow credentials for explicit origins.
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(monitoring_middleware)

app.include_router(upload.router)
app.include_router(hospitals.router)
app.include_router(indicator_config.router)
app.include_router(indicator_groups_router.router)
app.include_router(indicator_definitions_router.router)
app.include_router(tree_config.router)
app.include_router(reports.router)
app.include_router(analysis.router)
app.include_router(rules_api.router)
app.include_router(clinical.router)
app.include_router(alerts.router)
app.include_router(quality_alerts_router.router)
app.include_router(confidence.router)
app.include_router(config_api.router)
app.include_router(config_api.db_router)
app.include_router(root_cause.router)
app.include_router(dashboard.router)
app.include_router(file_ops.router)
app.include_router(audit_api.router)
app.include_router(governorates_api.router)
app.include_router(hospital_types_api.router)
app.include_router(facility_ownerships_api.router)
app.include_router(facility_types_api.router)
app.include_router(smart_analytics_router.router)
app.include_router(comparative_router.router)
app.include_router(export_router.router)
app.include_router(regional_router.router)
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(server_logs_router.router)
app.include_router(menu_router.router)

from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from sqlalchemy import func as _sa_func  # noqa: E402

from app.cache import get_data_epoch  # noqa: E402


@app.get("/health")
def health():
    """Liveness + readiness probe for Cloud Run / Cloud Build.

    Returns 200 only when the app can reach the database. Cloud Run startup
    probe uses this endpoint; Cloud Build CI curls it after deploy.
    """
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            db.execute(_sa_func.now())
        finally:
            db.close()
        return {"status": "ok", "database": "ok", "version": "0.1.0", "schema_in_sync": schema_in_sync, "data_epoch": get_data_epoch()}
    except Exception as exc:  # pragma: no cover - defensive for readiness
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable", "detail": str(exc)},
        )


def _build_version() -> str:
    """Best-effort build/commit identifier so users can tell if a deployed
    instance is running the latest code.

    Priority:
      1. Render injects RENDER_GIT_COMMIT for every deploy from GitHub.
      2. Local git checkout: HEAD commit short hash.
      3. Fallback: RENDER_DEPLOY_ID / RENDER_INSTANCE_ID, else "dev".
    """
    commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if commit:
        return commit[:12]
    try:
        head_file = os.path.join(BASE_DIR, ".git", "HEAD")
        if os.path.exists(head_file):
            with open(head_file, encoding="utf-8") as fh:
                ref = fh.read().strip()
            if ref.startswith("ref:"):
                ref_path = os.path.join(BASE_DIR, ".git", ref[5:].strip())
                if os.path.exists(ref_path):
                    with open(ref_path, encoding="utf-8") as fh:
                        return fh.read().strip()[:12]
                return ref[5:].strip()
            return ref[:12]
    except Exception:
        pass
    for var in ("RENDER_DEPLOY_ID", "RENDER_INSTANCE_ID"):
        val = os.getenv(var, "").strip()
        if val:
            return val[:12]
    return "dev"


@app.get("/api/version")
def version_info():
    """Return build metadata so the UI can show whether this deploy is up to date."""
    from datetime import datetime, timezone
    build_ts = None
    try:
        static_root = os.path.join(BASE_DIR, "static")
        latest = 0.0
        for _root, _dirs, files in os.walk(static_root):
            _dirs[:] = [d for d in _dirs if d not in ("node_modules", "vendor", "i18n")]
            for f in files:
                if f.endswith((".js", ".css", ".html")):
                    try:
                        latest = max(latest, os.path.getmtime(os.path.join(_root, f)))
                    except OSError:
                        continue
        if latest:
            build_ts = datetime.fromtimestamp(latest, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        build_ts = None
    try:
        from app.cache import get_data_epoch
        epoch = get_data_epoch()
    except Exception:
        epoch = None
    return {
        "version": "0.1.0",
        "build": _build_version(),
        "build_time": build_ts,
        "render": bool(os.getenv("RENDER_GIT_COMMIT", "").strip()),
        "data_epoch": epoch,
    }


def _resolve_is_arabic(request: Request) -> bool:
    """True when the user prefers Arabic.

    Priority: app_lang cookie written by the UI language toggle (same
    preference the dashboard uses, stored in localStorage which the server
    cannot see) → Accept-Language header when it explicitly mentions a
    language → default Arabic (the setup page's historical language).
    """
    try:
        cookie = request.cookies.get("app_lang", "").strip().lower()
        if cookie in ("ar", "en"):
            return cookie == "ar"
        accept = request.headers.get("accept-language", "").lower()
        if accept:
            # All languages starting with ar are Arabic (ar, ar-EG, ar-SA…).
            for part in accept.split(","):
                tag = part.split(";", 1)[0].strip()
                if tag:
                    return tag.startswith("ar")
    except Exception:
        pass
    return True   # default: Arabic (as before)


_SETUP_STYLES = """
    <style>
      body { font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 700px; margin: 40px auto; padding: 20px; background: #f8fafc; color: #1e293b; }
      h1 { color: #1a237e; } .step { background: white; border-radius: 10px; padding: 1.2rem; margin: 1rem 0; border: 1px solid #e2e8f0; }
      code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9rem; }
      .cmd { background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 8px; font-family: monospace; direction: ltr; text-align: left; margin: 0.5rem 0; }
    </style>
"""

_SETUP_HTML_AR = """
    <!DOCTYPE html>
    <html dir="rtl"><head><meta charset="utf-8">
    <title>Health AI — إعداد قاعدة البيانات</title>
    {STYLE}  </head><body>
    <h1>🗄️ إعداد قاعدة البيانات</h1>
    <p>يجب تعيين <code>DATABASE_URL</code> للاتصال بقاعدة بيانات PostgreSQL.</p>
    <div class="step"><h3>الخطوة 1: إنشاء قاعدة بيانات على Render</h3>
    <p>اذهب إلى <a href="https://dashboard.render.com">Render Dashboard</a> → New → PostgreSQL</p></div>
    <div class="step"><h3>الخطوة 2: تعيين DATABASE_URL</h3>
    <p>في Render: Environment → أضف متغير:</p>
    <div class="cmd">Key: DATABASE_URL<br>Value: postgresql://user:pass@host:5432/dbname</div></div>
    <div class="step"><h3>الخطوة 3: إعادة النشر</h3>
    <p>بعد تعيين DATABASE_URL، أعد نشر الخدمة. سيتم تشغيل الهجرات تلقائياً.</p></div>
    </body></html>
    """

_SETUP_HTML_EN = """
    <!DOCTYPE html>
    <html dir="ltr"><head><meta charset="utf-8">
    <title>Health AI — Database Setup</title>
    {STYLE}  </head><body>
    <h1>🗄️ Database Setup</h1>
    <p><code>DATABASE_URL</code> must be set to connect to a PostgreSQL database.</p>
    <div class="step"><h3>Step 1: Create a PostgreSQL database on Render</h3>
    <p>Go to the <a href="https://dashboard.render.com">Render Dashboard</a> → New → PostgreSQL</p></div>
    <div class="step"><h3>Step 2: Set DATABASE_URL</h3>
    <p>In Render: Environment → add a variable:</p>
    <div class="cmd">Key: DATABASE_URL<br>Value: postgresql://user:pass@host:5432/dbname</div></div>
    <div class="step"><h3>Step 3: Redeploy</h3>
    <p>After setting DATABASE_URL, redeploy the service. Migrations run automatically.</p></div>
    </body></html>
    """


@app.get("/setup")
def setup_page(request: Request):
    """Show setup instructions when DATABASE_URL is not configured.

    عربي/EN حسب لغة المستخدم: أولاً كوكيز app_lang التي تكتبها واجهة
    المستخدم عند تغيير اللغة، وإلا نستنتج من Accept-Language للمتصفح.
    """
    from app.database import _db_ready
    if _db_ready:
        return RedirectResponse(url="/dashboard")

    # 1) cookie written by the UI language toggle → 2) browser Accept-Language
    is_ar = _resolve_is_arabic(request)

    if is_ar:
        page = _SETUP_HTML_AR
    else:
        page = _SETUP_HTML_EN
    return HTMLResponse(
        content=page.replace("{STYLE}", _SETUP_STYLES),
    )


@app.get("/tasks/{task_id}")
def task_status(task_id: str):
    task = get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    return task

class CachedStaticFiles(StaticFiles):
    """Serve static assets with long-lived Cache-Control headers.

    Cache-busting is handled by ?v=<timestamp> query params rewritten
    into asset URLs by the /dashboard route. When any file changes the
    timestamp changes, forcing the browser to re-fetch.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # HTML should never be cached (served via /dashboard route anyway)
        if path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store"
        else:
            # JS modules imported inside other JS (e.g. hospitals.js via app.js)
            # never get ?v= cache-busting, so we use no-cache to force revalidation.
            # Static assets referenced in HTML get ?v= so they ARE fully cached.
            if path.endswith(".js"):
                response.headers["Cache-Control"] = "public, no-cache, must-revalidate"
            else:
                response.headers["Cache-Control"] = "public, max-age=31536000"
        return response


static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", CachedStaticFiles(directory=static_dir), name="static")

# بصمة إصدار لكل ملف على حدة: تعديل أي ملف JS/CSS يغيّر بصفته معامله ?v= فقط،
# فيجبر المتصفح على جلب النسخة الحديثة بدل نسخة مخزنة قديمة (cache-busting نهائي).
# كانت البصمة سابقاً رقمياً واحداً مشتركاً بين كل الأصول (أعلى mtime): ملف
# أُعيدت كتابته لكن mtime أقدم من أخ ملف آخر ظل URL القديم له فيستعمل المتصفح
# نسخة قديمة مخزنة — وهو ما فسّد جلسات auth.js أكثر من مرة.
_STATIC_ASSET_RE = re.compile(
    r'(?P<url>/static/(?:js|css|vendor)/[^"\' ]+\.(?:js|css))(?P<query>\?[^"\' ]*)?'
)

_ASSET_VERSIONS: dict = {}
_ASSET_SCAN_LATEST = 0.0


def _per_file_asset_versions() -> dict:
    """Per-asset cache-busting stamps keyed by URL path.

    The tree is rescanned only when the newest mtime changed — because any
    write bumps an mtime to "now", that catches every edit, while keeping
    repeated /dashboard requests cheap.
    """
    global _ASSET_VERSIONS, _ASSET_SCAN_LATEST
    latest = 0.0
    versions: dict = {}
    try:
        for root, _, files in os.walk(static_dir):
            for f in files:
                if not f.endswith((".js", ".css")):
                    continue
                path = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                latest = max(latest, mtime)
                rel = os.path.relpath(path, static_dir).replace("\\", "/")
                versions["/static/" + rel] = str(int(mtime * 1000))
    except OSError:
        pass
    if latest != _ASSET_SCAN_LATEST or not _ASSET_VERSIONS:
        _ASSET_SCAN_LATEST = latest
        _ASSET_VERSIONS = versions
    return _ASSET_VERSIONS


@app.get("/dashboard")
def dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        return {"error": "Dashboard not found"}
    with open(index_path, encoding="utf-8") as fh:
        html = fh.read()
    versions = _per_file_asset_versions()

    def _bust(match):
        url = match.group("url")
        # Editing one file only changes THAT file's stamp; unknown URLs fall
        # back to the tree-wide newest stamp so nothing ever loses busting.
        stamp = versions.get(url) or str(int(_ASSET_SCAN_LATEST * 1000) or 0)
        return url + "?v=" + stamp

    html = _STATIC_ASSET_RE.sub(_bust, html)
    return HTMLResponse(
        content=html,
        media_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/metrics")
def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root():
    from app.database import _db_ready
    if not _db_ready:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url="/dashboard")


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#1a237e"/><text x="16" y="22" text-anchor="middle" fill="white" font-size="16" font-family="sans-serif">H</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")
