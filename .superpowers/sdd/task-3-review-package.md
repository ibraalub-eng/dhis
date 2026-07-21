# Task 3 Review Package

## Commits
f50998a feat: create facility_ownerships/facility_types tables and seed data

## Diff Stats
 app/main.py | 12 +++++++++++-
 1 file changed, 11 insertions(+), 1 deletion(-)

## Full Diff
```
diff --git a/app/main.py b/app/main.py
index 972f391..24e39f3 100644
--- a/app/main.py
+++ b/app/main.py
@@ -3,21 +3,21 @@ load_dotenv()
 
 from contextlib import asynccontextmanager  # noqa: E402
 from fastapi import FastAPI  # noqa: E402
 from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
 from fastapi.staticfiles import StaticFiles  # noqa: E402
 from fastapi.responses import FileResponse  # noqa: E402
 from alembic.config import Config  # noqa: E402
 from alembic import command  # noqa: E402
 from alembic.script import ScriptDirectory  # noqa: E402
 from app.database import init_db, SessionLocal, engine  # noqa: E402
-from app.models import AppConfig  # noqa: E402
+from app.models import AppConfig, FacilityOwnership, FacilityType  # noqa: E402
 from app.monitoring import monitoring_middleware, setup_structured_logging, generate_latest, CONTENT_TYPE_LATEST, REGISTRY  # noqa: E402
 from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops, indicator_config, tree_config, audit as audit_api, governorates as governorates_api, hospital_types as hospital_types_api, facility_ownerships as facility_ownerships_api, facility_types as facility_types_api  # noqa: E402
 from app.tasks import get_task  # noqa: E402
 from app.config import DATABASE_URL, UPLOAD_DIR, BASE_DIR  # noqa: E402
 from scripts.seed_indicators import seed_indicators  # noqa: E402
 from scripts.seed_rules import seed_rules  # noqa: E402
 import os  # noqa: E402
 import logging  # noqa: E402
 
 setup_structured_logging(logging.INFO)
@@ -154,20 +154,30 @@ def seed_app_config(session):
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     init_db()
     run_alembic_upgrade()
     session = SessionLocal()
     try:
         seed_app_config(session)
         seed_indicators(session)
         seed_rules(session)
+
+        # Seed facility ownerships
+        if not session.query(FacilityOwnership).first():
+            for name in ["\u062d\u0643\u0648\u0645\u064a", "NGOs", "INGOs", "\u062e\u0627\u0635"]:
+                session.add(FacilityOwnership(name=name))
+
+        # Seed facility types
+        if not session.query(FacilityType).first():
+            session.add(FacilityType(name="\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"))
+
         # Load logging setting
         from app.models import SystemSetting
         from app.monitoring import set_logging_enabled
         log_row = session.query(SystemSetting).filter(SystemSetting.key == "structured_logging_enabled").first()
         set_logging_enabled(log_row.value == "true" if log_row else True)
     finally:
         session.close()
     os.makedirs(UPLOAD_DIR, exist_ok=True)
     yield
 
```
