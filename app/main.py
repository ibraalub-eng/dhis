from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic import command  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from app.database import init_db, SessionLocal, engine  # noqa: E402
from app.models import AppConfig, FacilityOwnership, FacilityType  # noqa: E402
from app.monitoring import monitoring_middleware, setup_structured_logging, generate_latest, CONTENT_TYPE_LATEST, REGISTRY  # noqa: E402
from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops, indicator_config, tree_config, audit as audit_api, governorates as governorates_api, hospital_types as hospital_types_api, facility_ownerships as facility_ownerships_api, facility_types as facility_types_api, smart_analytics as smart_analytics_router, comparative as comparative_router, export as export_router, regional as regional_router  # noqa: E402
from app.tasks import get_task  # noqa: E402
from app.config import DATABASE_URL, UPLOAD_DIR, BASE_DIR  # noqa: E402
from scripts.seed_indicators import seed_indicators  # noqa: E402
from scripts.seed_rules import seed_rules  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import logging  # noqa: E402

setup_structured_logging(logging.INFO)


APP_CONFIG_DEFAULTS = [
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


def seed_app_config(session):
    for key, value, category, label in APP_CONFIG_DEFAULTS:
        existing = session.query(AppConfig).filter(AppConfig.key == key).first()
        if not existing:
            session.add(AppConfig(key=key, value=value, category=category, label=label))
    session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    run_alembic_upgrade()
    session = SessionLocal()
    try:
        seed_app_config(session)
        seed_indicators(session)
        seed_rules(session)

        # Seed facility ownerships
        if not session.query(FacilityOwnership).first():
            for name in ["\u062d\u0643\u0648\u0645\u064a", "NGOs", "INGOs", "\u062e\u0627\u0635"]:
                session.add(FacilityOwnership(name=name))

        # Seed facility types
        if not session.query(FacilityType).first():
            session.add(FacilityType(name="\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"))

        session.commit()

        # Load logging setting
        from app.models import SystemSetting
        from app.monitoring import set_logging_enabled
        log_row = session.query(SystemSetting).filter(SystemSetting.key == "structured_logging_enabled").first()
        set_logging_enabled(log_row.value == "true" if log_row else True)
    finally:
        session.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    yield


app = FastAPI(
    title="Health AI - SRMNH Data Quality System",
    description="MVP for maternal and neonatal health indicator data quality analysis",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(monitoring_middleware)

app.include_router(upload.router)
app.include_router(hospitals.router)
app.include_router(indicator_config.router)
app.include_router(tree_config.router)
app.include_router(reports.router)
app.include_router(analysis.router)
app.include_router(rules_api.router)
app.include_router(clinical.router)
app.include_router(alerts.router)
app.include_router(confidence.router)
app.include_router(config_api.router)
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

from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from sqlalchemy import text as _sa_text  # noqa: E402


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
            db.execute(_sa_text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ok", "database": "ok", "version": "0.1.0"}
    except Exception as exc:  # pragma: no cover - defensive for readiness
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable", "detail": str(exc)},
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
            # JS, CSS, images, fonts — cache for 1 year (invalidated by ?v=)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", CachedStaticFiles(directory=static_dir), name="static")

# بصمة إصدار تلقائية للملفات الثابتة: أي تعديل على أي ملف JS/CSS/HTML يغيّر
# الرقم فتُعاد عناوين الأصول في index.html بمعامل ?v= جديد — فيجبر المتصفح
# على جلب النسخ الحديثة بدل العمل بنسخ قديمة مخزنة (cache-busting نهائي).
_STATIC_ASSET_RE = re.compile(
    r'(?P<url>/static/(?:js|css|vendor)/[^"\' ]+\.(?:js|css))(?P<query>\?[^"\' ]*)?'
)


def _static_assets_version() -> str:
    latest = 0.0
    try:
        for root, _, files in os.walk(static_dir):
            for f in files:
                if f.endswith((".js", ".css", ".html")):
                    try:
                        latest = max(latest, os.path.getmtime(os.path.join(root, f)))
                    except OSError:
                        continue
    except OSError:
        pass
    return str(int(latest * 1000))


@app.get("/dashboard")
def dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        return {"error": "Dashboard not found"}
    with open(index_path, encoding="utf-8") as fh:
        html = fh.read()
    v = _static_assets_version()
    html = _STATIC_ASSET_RE.sub(lambda m: m.group("url") + "?v=" + v, html)
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
    return RedirectResponse(url="/dashboard")


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#1a237e"/><text x="16" y="22" text-anchor="middle" fill="white" font-size="16" font-family="sans-serif">H</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")
