from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_schema():
    """Add missing columns/tables for schema upgrades without dropping data."""
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))

        # Check if rule_type column exists in validation_results
        result = conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('validation_results') WHERE name='rule_type'")
        )
        if result.scalar() == 0:
            conn.execute(text("ALTER TABLE validation_results ADD COLUMN rule_type VARCHAR(20) DEFAULT 'LOGIC'"))
            conn.commit()

        # Check if rules table exists
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='rules'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(500) NOT NULL,
                    rule_type VARCHAR(20) NOT NULL,
                    severity VARCHAR(10) NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    expression_type VARCHAR(50) NOT NULL,
                    params TEXT DEFAULT '{}',
                    description TEXT DEFAULT '',
                    enabled BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

        # Check/add formula column to indicators
        result = conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('indicators') WHERE name='formula'")
        )
        if result.scalar() == 0:
            conn.execute(text("ALTER TABLE indicators ADD COLUMN formula TEXT"))
            conn.commit()

        # Check/add default_weight column to indicators
        result = conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('indicators') WHERE name='default_weight'")
        )
        if result.scalar() == 0:
            conn.execute(text("ALTER TABLE indicators ADD COLUMN default_weight FLOAT DEFAULT 1.0"))
            conn.commit()

        # Check/create hospital_indicator_config table
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='hospital_indicator_config'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE hospital_indicator_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
                    indicator_id INTEGER NOT NULL REFERENCES indicators(id),
                    is_enabled BOOLEAN DEFAULT 1,
                    weight_override FLOAT,
                    UNIQUE(hospital_id, indicator_id)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hospital_indicator_config_hospital_id ON hospital_indicator_config(hospital_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hospital_indicator_config_indicator_id ON hospital_indicator_config(indicator_id)"))
            conn.commit()

        # Check/add sort_order column to rules table
        result = conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('rules') WHERE name='sort_order'")
        )
        if result.scalar() == 0:
            conn.execute(text("ALTER TABLE rules ADD COLUMN sort_order INTEGER DEFAULT 0"))
            conn.commit()

        # Check/create confidence_scores table
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='confidence_scores'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE confidence_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
                    month VARCHAR(7) NOT NULL,
                    overall_confidence FLOAT NOT NULL,
                    level VARCHAR(20) NOT NULL,
                    indicator_count INTEGER DEFAULT 0,
                    high_count INTEGER DEFAULT 0,
                    medium_count INTEGER DEFAULT 0,
                    low_count INTEGER DEFAULT 0,
                    critical_count INTEGER DEFAULT 0,
                    indicators_data TEXT,
                    summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_confidence_scores_hospital_id ON confidence_scores(hospital_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_confidence_scores_month ON confidence_scores(month)"))
            conn.commit()

        # Check/create confidence_weights table
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='confidence_weights'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE confidence_weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_compliance FLOAT NOT NULL DEFAULT 0.55,
                    historical FLOAT NOT NULL DEFAULT 0.10,
                    cross_hospital FLOAT NOT NULL DEFAULT 0.10,
                    trend FLOAT NOT NULL DEFAULT 0.10,
                    completeness FLOAT NOT NULL DEFAULT 0.15,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("INSERT INTO confidence_weights (rule_compliance, historical, cross_hospital, trend, completeness) VALUES (0.55, 0.10, 0.10, 0.10, 0.15)"))
            conn.commit()

        # Check/seeds app_config table
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='app_config'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE app_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key VARCHAR(100) UNIQUE NOT NULL,
                    value FLOAT NOT NULL,
                    category VARCHAR(50) NOT NULL DEFAULT 'general',
                    label VARCHAR(200),
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_config_key ON app_config(key)"))

        # Seed defaults (always runs, uses INSERT OR IGNORE so existing rows are preserved)
        defaults = [
                ("quality_rule_compliance", 0.35, "quality", "Rule Compliance Weight"),
                ("quality_completeness", 0.25, "quality", "Completeness Weight"),
                ("quality_consistency", 0.25, "quality", "Consistency Weight"),
                ("quality_outlier_penalty", 0.15, "quality", "Outlier Penalty Weight"),
                ("outlier_multiplier", 2.0, "quality", "Outlier Penalty Multiplier"),
                ("severity_high", 3.0, "quality", "Severity HIGH Weight"),
                ("severity_medium", 2.0, "quality", "Severity MEDIUM Weight"),
                ("severity_low", 1.0, "quality", "Severity LOW Weight"),
                ("zscore_threshold", 2.5, "thresholds", "Z-Score Threshold"),
                ("confidence_high", 80.0, "thresholds", "HIGH Confidence Cutoff"),
                ("confidence_medium", 50.0, "thresholds", "MEDIUM Confidence Cutoff"),
                ("confidence_low", 25.0, "thresholds", "LOW Confidence Cutoff"),
                ("eq_tolerance", 0.01, "rules", "Equality Tolerance"),
                ("cs_rate_threshold", 80.0, "rules", "C-Section Rate Threshold (%)"),
                ("nvd_rate_threshold", 10.0, "rules", "NVD Rate Threshold (%)"),
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
                ("trend_finding_consecutive", 3, "trends", "Finding Generated Consecutive Months"),
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
            ]
        for key, value, category, label in defaults:
            conn.execute(text(f"INSERT OR IGNORE INTO app_config (key, value, category, label) VALUES ('{key}', {value}, '{category}', '{label}')"))
        conn.commit()

        # Create analysis_cache table if not exists
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='analysis_cache'")
        )
        if result.scalar() == 0:
            conn.execute(text("""
                CREATE TABLE analysis_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key VARCHAR(200) UNIQUE NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_cache_key ON analysis_cache(cache_key)"))
            conn.commit()
        # Create system_settings table for text-based config (AI provider, etc.)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

        # Composite indexes for frequent query patterns
        # The most common query: WHERE hospital_id = X AND month = Y
        # Composite indexes are far more efficient than single-column indexes
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_qs_hosp_month ON quality_scores(hospital_id, month)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vr_hosp_month ON validation_results(hospital_id, month)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ar_hosp_month ON anomaly_results(hospital_id, month)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cs_hosp_month ON confidence_scores(hospital_id, month)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ci_hosp_month ON clinical_insights(hospital_id, month)"))
        # Indicator values: most queried by (hospital_id, month, indicator_id)
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_iv_hosp_month_ind ON indicator_values(hospital_id, month, indicator_id)"))
        # Filter indexes: status='FAIL' on validation_results, is_outlier on anomaly_results
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vr_status ON validation_results(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ar_outlier ON anomaly_results(is_outlier)"))
        # Confidence level filter (used in dashboard confidence distribution)
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cs_level ON confidence_scores(level)"))
        # Month-only queries (trends, comparisons, dashboard overview)
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_qs_month ON quality_scores(month)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_iv_month ON indicator_values(month)"))
        conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_schema()