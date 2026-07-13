from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.database import init_db
from app.monitoring import monitoring_middleware, setup_structured_logging, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops
from app.tasks import get_task, cleanup_old_tasks
from app.config import DATABASE_URL, UPLOAD_DIR, BASE_DIR
import os
import logging

setup_structured_logging(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_indicators()
    _seed_rules()
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

from fastapi import Query
from fastapi.responses import JSONResponse


@app.get("/tasks/{task_id}")
def task_status(task_id: str):
    task = get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    return task

static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard")
def dashboard():
    static_dir = os.path.join(BASE_DIR, "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "Dashboard not found"}


@app.get("/metrics")
def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def _seed_indicators():
    from app.database import SessionLocal
    from app.models import Indicator
    from app.indicators import INDICATOR_FLAT_LIST

    session = SessionLocal()
    try:
        existing = {ind.code for ind in session.query(Indicator).all()}
        if not existing:
            code_to_id = {}
            for ind in INDICATOR_FLAT_LIST:
                parent_id = None
                if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                    parent_id = code_to_id[ind["parent_id"]]
                db_ind = Indicator(
                    code=ind["code"],
                    name=ind["name"],
                    parent_id=parent_id,
                    level=ind["level"],
                    group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
                )
                session.add(db_ind)
                session.flush()
                code_to_id[ind["code"]] = db_ind.id
            session.commit()
        else:
            # Add any new indicators not yet in the DB (migration)
            code_to_id = {}
            for db_ind in session.query(Indicator).all():
                code_to_id[db_ind.code] = db_ind.id
            for ind in INDICATOR_FLAT_LIST:
                if ind["code"] in code_to_id:
                    continue
                parent_id = None
                if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                    parent_id = code_to_id[ind["parent_id"]]
                db_ind = Indicator(
                    code=ind["code"],
                    name=ind["name"],
                    parent_id=parent_id,
                    level=ind["level"],
                    group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
                )
                session.add(db_ind)
                session.flush()
                code_to_id[ind["code"]] = db_ind.id
            if session.new:
                session.commit()
    finally:
        session.close()


def _seed_rules():
    from app.database import SessionLocal
    from app.models import Rule

    session = SessionLocal()
    try:
        count = session.query(Rule).count()
        if count > 0:
            return
        from scripts.seed_rules import RULES
        for r in RULES:
            rule = Rule(
                code=r["code"],
                name=r["name"],
                rule_type=r["rule_type"],
                severity=r["severity"],
                category=r["category"],
                expression_type=r["expression_type"],
                params=r["params"],
                description=r["description"],
            )
            session.add(rule)
        session.commit()
    finally:
        session.close()


@app.get("/")
def root():
    return {
        "name": "Health AI - SRMNH Data Quality System",
        "version": "0.1.0",
        "endpoints": {
            "upload": "/upload/",
            "hospitals": "/hospitals/",
            "reports": "/reports/",
            "analysis": "/analysis/",
            "clinical": "/clinical/",
            "confidence": "/confidence/",
            "docs": "/docs",
        },
    }
