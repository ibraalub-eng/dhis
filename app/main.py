from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.database import init_db, SessionLocal
from app.monitoring import monitoring_middleware, setup_structured_logging, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops
from app.tasks import get_task, cleanup_old_tasks
from app.config import DATABASE_URL, UPLOAD_DIR, BASE_DIR
from scripts.seed_indicators import seed_indicators
from scripts.seed_rules import seed_rules
import os
import logging

setup_structured_logging(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    session = SessionLocal()
    try:
        seed_indicators(session)
        seed_rules(session)
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
