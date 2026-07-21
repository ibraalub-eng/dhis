# Task 2 Review Package

## Commits
21d167d feat: add facility-ownerships and facility-types API endpoints

## Diff Stats
 app/api/facility_ownerships.py    |  69 ++++++++++++++++++++++++
 app/api/facility_types.py         |  69 ++++++++++++++++++++++++
 app/api/hospitals.py              |  21 ++++++++
 app/main.py                       |   4 +-
 tests/test_api_ownership_types.py | 108 ++++++++++++++++++++++++++++++++++++++
 5 files changed, 270 insertions(+), 1 deletion(-)

## Full Diff
```
diff --git a/app/api/facility_ownerships.py b/app/api/facility_ownerships.py
new file mode 100644
index 0000000..731c1b5
--- /dev/null
+++ b/app/api/facility_ownerships.py
@@ -0,0 +1,69 @@
+from fastapi import APIRouter, Depends, HTTPException, Query
+from sqlalchemy.orm import Session
+from typing import List
+from app.database import get_db
+from app.cache import cache
+from app.models import FacilityOwnership, Hospital
+from app.schemas import FacilityOwnershipOut, FacilityOwnershipCreate
+
+router = APIRouter(prefix="/facility-ownerships", tags=["facility_ownerships"])
+
+
+@router.get("/", response_model=List[FacilityOwnershipOut])
+def list_facility_ownerships(
+    skip: int = Query(0, ge=0),
+    limit: int = Query(100, ge=1, le=1000),
+    db: Session = Depends(get_db),
+):
+    q = db.query(FacilityOwnership).order_by(FacilityOwnership.name)
+    return q.offset(skip).limit(limit).all()
+
+
+@router.get("/{ownership_id}", response_model=FacilityOwnershipOut)
+def get_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
+    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
+    if not ow:
+        raise HTTPException(status_code=404, detail="Facility ownership not found")
+    return ow
+
+
+@router.post("/", response_model=FacilityOwnershipOut)
+def create_facility_ownership(data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
+    existing = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name).first()
+    if existing:
+        raise HTTPException(status_code=400, detail="Facility ownership already exists")
+    ow = FacilityOwnership(name=data.name)
+    db.add(ow)
+    db.commit()
+    db.refresh(ow)
+    cache.invalidate()
+    return ow
+
+
+@router.put("/{ownership_id}", response_model=FacilityOwnershipOut)
+def update_facility_ownership(ownership_id: int, data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
+    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
+    if not ow:
+        raise HTTPException(status_code=404, detail="Facility ownership not found")
+    dup = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name, FacilityOwnership.id != ownership_id).first()
+    if dup:
+        raise HTTPException(status_code=400, detail="Facility ownership name already taken")
+    ow.name = data.name
+    db.commit()
+    db.refresh(ow)
+    cache.invalidate()
+    return ow
+
+
+@router.delete("/{ownership_id}")
+def delete_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
+    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
+    if not ow:
+        raise HTTPException(status_code=404, detail="Facility ownership not found")
+    linked = db.query(Hospital).filter(Hospital.facility_ownership_id == ownership_id).first()
+    if linked:
+        raise HTTPException(status_code=400, detail="Cannot delete facility ownership with linked hospitals")
+    db.delete(ow)
+    db.commit()
+    cache.invalidate()
+    return {"ok": True}
diff --git a/app/api/facility_types.py b/app/api/facility_types.py
new file mode 100644
index 0000000..7b964e5
--- /dev/null
+++ b/app/api/facility_types.py
@@ -0,0 +1,69 @@
+from fastapi import APIRouter, Depends, HTTPException, Query
+from sqlalchemy.orm import Session
+from typing import List
+from app.database import get_db
+from app.cache import cache
+from app.models import FacilityType, Hospital
+from app.schemas import FacilityTypeOut, FacilityTypeCreate
+
+router = APIRouter(prefix="/facility-types", tags=["facility_types"])
+
+
+@router.get("/", response_model=List[FacilityTypeOut])
+def list_facility_types(
+    skip: int = Query(0, ge=0),
+    limit: int = Query(100, ge=1, le=1000),
+    db: Session = Depends(get_db),
+):
+    q = db.query(FacilityType).order_by(FacilityType.name)
+    return q.offset(skip).limit(limit).all()
+
+
+@router.get("/{type_id}", response_model=FacilityTypeOut)
+def get_facility_type(type_id: int, db: Session = Depends(get_db)):
+    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
+    if not ft:
+        raise HTTPException(status_code=404, detail="Facility type not found")
+    return ft
+
+
+@router.post("/", response_model=FacilityTypeOut)
+def create_facility_type(data: FacilityTypeCreate, db: Session = Depends(get_db)):
+    existing = db.query(FacilityType).filter(FacilityType.name == data.name).first()
+    if existing:
+        raise HTTPException(status_code=400, detail="Facility type already exists")
+    ft = FacilityType(name=data.name)
+    db.add(ft)
+    db.commit()
+    db.refresh(ft)
+    cache.invalidate()
+    return ft
+
+
+@router.put("/{type_id}", response_model=FacilityTypeOut)
+def update_facility_type(type_id: int, data: FacilityTypeCreate, db: Session = Depends(get_db)):
+    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
+    if not ft:
+        raise HTTPException(status_code=404, detail="Facility type not found")
+    dup = db.query(FacilityType).filter(FacilityType.name == data.name, FacilityType.id != type_id).first()
+    if dup:
+        raise HTTPException(status_code=400, detail="Facility type name already taken")
+    ft.name = data.name
+    db.commit()
+    db.refresh(ft)
+    cache.invalidate()
+    return ft
+
+
+@router.delete("/{type_id}")
+def delete_facility_type(type_id: int, db: Session = Depends(get_db)):
+    ft = db.query(FacilityType).filter(FacilityType.id == type_id).first()
+    if not ft:
+        raise HTTPException(status_code=404, detail="Facility type not found")
+    linked = db.query(Hospital).filter(Hospital.facility_type_id == type_id).first()
+    if linked:
+        raise HTTPException(status_code=400, detail="Cannot delete facility type with linked hospitals")
+    db.delete(ft)
+    db.commit()
+    cache.invalidate()
+    return {"ok": True}
diff --git a/app/api/hospitals.py b/app/api/hospitals.py
index a3e4759..47f6bba 100644
--- a/app/api/hospitals.py
+++ b/app/api/hospitals.py
@@ -24,60 +24,73 @@ def list_hospitals(
         for item in cached:
             if isinstance(item, dict):
                 result.append(item)
             else:
                 d = {
                     "id": item.id,
                     "name": item.name,
                     "region": item.region,
                     "governorate_id": item.governorate_id,
                     "hospital_type_id": item.hospital_type_id,
+                    "organisation_unit_id": item.organisation_unit_id,
+                    "facility_ownership_id": item.facility_ownership_id,
+                    "facility_type_id": item.facility_type_id,
                     "address": item.address,
                     "is_active": item.is_active,
                     "created_at": item.created_at,
                     "governorate_name": item.governorate.name if item.governorate else None,
                     "hospital_type_name": item.hospital_type.name if item.hospital_type else None,
+                    "facility_ownership_name": item.facility_ownership.name if item.facility_ownership else None,
+                    "facility_type_name": item.facility_type.name if item.facility_type else None,
                 }
                 result.append(d)
         return result
     q = db.query(Hospital)
     if not include_inactive:
         q = q.filter(Hospital.is_active.is_(True))
     hospitals = q.offset(skip).limit(limit).all()
     result = []
     for h in hospitals:
         result.append({
             "id": h.id,
             "name": h.name,
             "region": h.region,
             "governorate_id": h.governorate_id,
             "hospital_type_id": h.hospital_type_id,
+            "organisation_unit_id": h.organisation_unit_id,
+            "facility_ownership_id": h.facility_ownership_id,
+            "facility_type_id": h.facility_type_id,
             "address": h.address,
             "is_active": h.is_active,
             "created_at": h.created_at,
             "governorate_name": h.governorate.name if h.governorate else None,
             "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
+            "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
+            "facility_type_name": h.facility_type.name if h.facility_type else None,
         })
     cache.set(cache_key, result)
     return result
 
 
 @router.post("/", response_model=HospitalOut)
 def create_hospital(data: HospitalCreate, db: Session = Depends(get_db)):
     existing = db.query(Hospital).filter(Hospital.name == data.name).first()
     if existing:
         raise HTTPException(status_code=400, detail="Hospital already exists")
     hosp = Hospital(
         name=data.name,
         region=data.region,
         governorate_id=data.governorate_id,
         hospital_type_id=data.hospital_type_id,
+        organisation_unit_id=data.organisation_unit_id,
+        facility_ownership_id=data.facility_ownership_id,
+        facility_type_id=data.facility_type_id,
         address=data.address,
     )
     db.add(hosp)
     db.commit()
     db.refresh(hosp)
     cache.invalidate()
     return hosp
 
 
 @router.put("/{hospital_id}/toggle-active")
@@ -107,40 +120,48 @@ def list_all_indicators(db: Session = Depends(get_db)):
 def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
     h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
     if not h:
         raise HTTPException(status_code=404, detail="Hospital not found")
     return {
         "id": h.id,
         "name": h.name,
         "region": h.region,
         "governorate_id": h.governorate_id,
         "hospital_type_id": h.hospital_type_id,
+        "organisation_unit_id": h.organisation_unit_id,
+        "facility_ownership_id": h.facility_ownership_id,
+        "facility_type_id": h.facility_type_id,
         "address": h.address,
         "is_active": h.is_active,
         "created_at": h.created_at,
         "governorate_name": h.governorate.name if h.governorate else None,
         "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
+        "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
+        "facility_type_name": h.facility_type.name if h.facility_type else None,
     }
 
 
 @router.put("/{hospital_id}", response_model=HospitalOut)
 def update_hospital(hospital_id: int, data: HospitalCreate, db: Session = Depends(get_db)):
     hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
     if not hosp:
         raise HTTPException(status_code=404, detail="Hospital not found")
     dup = db.query(Hospital).filter(Hospital.name == data.name, Hospital.id != hospital_id).first()
     if dup:
         raise HTTPException(status_code=400, detail="Hospital name already taken")
     hosp.name = data.name
     hosp.region = data.region
     hosp.governorate_id = data.governorate_id
     hosp.hospital_type_id = data.hospital_type_id
+    hosp.organisation_unit_id = data.organisation_unit_id
+    hosp.facility_ownership_id = data.facility_ownership_id
+    hosp.facility_type_id = data.facility_type_id
     hosp.address = data.address
     db.commit()
     db.refresh(hosp)
     cache.invalidate()
     return hosp
 
 
 @router.delete("/{hospital_id}")
 def delete_hospital(hospital_id: int, db: Session = Depends(get_db)):
     hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
diff --git a/app/main.py b/app/main.py
index fbd8d48..972f391 100644
--- a/app/main.py
+++ b/app/main.py
@@ -5,21 +5,21 @@ from contextlib import asynccontextmanager  # noqa: E402
 from fastapi import FastAPI  # noqa: E402
 from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
 from fastapi.staticfiles import StaticFiles  # noqa: E402
 from fastapi.responses import FileResponse  # noqa: E402
 from alembic.config import Config  # noqa: E402
 from alembic import command  # noqa: E402
 from alembic.script import ScriptDirectory  # noqa: E402
 from app.database import init_db, SessionLocal, engine  # noqa: E402
 from app.models import AppConfig  # noqa: E402
 from app.monitoring import monitoring_middleware, setup_structured_logging, generate_latest, CONTENT_TYPE_LATEST, REGISTRY  # noqa: E402
-from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops, indicator_config, tree_config, audit as audit_api, governorates as governorates_api, hospital_types as hospital_types_api  # noqa: E402
+from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops, indicator_config, tree_config, audit as audit_api, governorates as governorates_api, hospital_types as hospital_types_api, facility_ownerships as facility_ownerships_api, facility_types as facility_types_api  # noqa: E402
 from app.tasks import get_task  # noqa: E402
 from app.config import DATABASE_URL, UPLOAD_DIR, BASE_DIR  # noqa: E402
 from scripts.seed_indicators import seed_indicators  # noqa: E402
 from scripts.seed_rules import seed_rules  # noqa: E402
 import os  # noqa: E402
 import logging  # noqa: E402
 
 setup_structured_logging(logging.INFO)
 
 
@@ -204,20 +204,22 @@ app.include_router(rules_api.router)
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
+app.include_router(facility_ownerships_api.router)
+app.include_router(facility_types_api.router)
 
 from fastapi.responses import JSONResponse  # noqa: E402
 
 
 @app.get("/tasks/{task_id}")
 def task_status(task_id: str):
     task = get_task(task_id)
     if not task:
         return JSONResponse(status_code=404, content={"error": "Task not found"})
     return task
diff --git a/tests/test_api_ownership_types.py b/tests/test_api_ownership_types.py
new file mode 100644
index 0000000..fcfdf7f
--- /dev/null
+++ b/tests/test_api_ownership_types.py
@@ -0,0 +1,108 @@
+"""Tests for facility-ownerships and facility-types API endpoints."""
+import pytest
+from fastapi.testclient import TestClient
+from app.main import app
+from app.database import get_db
+from app.models import Hospital
+
+
+@pytest.fixture
+def client(db_session):
+    def override_get_db():
+        try:
+            yield db_session
+        finally:
+            pass
+    app.dependency_overrides[get_db] = override_get_db
+    yield TestClient(app)
+    app.dependency_overrides.clear()
+
+
+class TestFacilityOwnerships:
+    def test_list_empty(self, client):
+        resp = client.get("/facility-ownerships/")
+        assert resp.status_code == 200
+        assert resp.json() == []
+
+    def test_create(self, client):
+        resp = client.post("/facility-ownerships/", json={"name": "\u062d\u0643\u0648\u0645\u064a"})
+        assert resp.status_code == 200
+        data = resp.json()
+        assert data["name"] == "\u062d\u0643\u0648\u0645\u064a"
+        assert "id" in data
+
+    def test_create_duplicate(self, client):
+        client.post("/facility-ownerships/", json={"name": "NGOs"})
+        resp = client.post("/facility-ownerships/", json={"name": "NGOs"})
+        assert resp.status_code == 400
+
+    def test_update(self, client):
+        client.post("/facility-ownerships/", json={"name": "OLD"})
+        resp = client.put("/facility-ownerships/1", json={"name": "NEW"})
+        assert resp.status_code == 200
+        assert resp.json()["name"] == "NEW"
+
+    def test_delete(self, client):
+        client.post("/facility-ownerships/", json={"name": "DELETE_ME"})
+        resp = client.delete("/facility-ownerships/1")
+        assert resp.status_code == 200
+
+    def test_delete_linked_hospital_fails(self, client, db_session):
+        client.post("/facility-ownerships/", json={"name": "GOV"})
+        h = db_session.query(Hospital).first()
+        h.facility_ownership_id = 1
+        db_session.commit()
+        resp = client.delete("/facility-ownerships/1")
+        assert resp.status_code == 400
+
+    def test_get_nonexistent(self, client):
+        resp = client.get("/facility-ownerships/999")
+        assert resp.status_code == 404
+
+
+class TestFacilityTypes:
+    def test_list_empty(self, client):
+        resp = client.get("/facility-types/")
+        assert resp.status_code == 200
+
+    def test_create(self, client):
+        resp = client.post("/facility-types/", json={"name": "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"})
+        assert resp.status_code == 200
+        assert resp.json()["name"] == "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"
+
+    def test_create_duplicate(self, client):
+        client.post("/facility-types/", json={"name": "X"})
+        resp = client.post("/facility-types/", json={"name": "X"})
+        assert resp.status_code == 400
+
+    def test_update(self, client):
+        client.post("/facility-types/", json={"name": "A"})
+        resp = client.put("/facility-types/1", json={"name": "B"})
+        assert resp.status_code == 200
+
+    def test_delete(self, client):
+        client.post("/facility-types/", json={"name": "DEL"})
+        resp = client.delete("/facility-types/1")
+        assert resp.status_code == 200
+
+    def test_delete_linked_hospital_fails(self, client, db_session):
+        client.post("/facility-types/", json={"name": "FT"})
+        h = db_session.query(Hospital).first()
+        h.facility_type_id = 1
+        db_session.commit()
+        resp = client.delete("/facility-types/1")
+        assert resp.status_code == 400
+
+
+class TestHospitalExtended:
+    def test_hospital_has_new_fields(self, client):
+        resp = client.get("/hospitals/")
+        assert resp.status_code == 200
+        data = resp.json()
+        if data:
+            h = data[0]
+            assert "organisation_unit_id" in h
+            assert "facility_ownership_id" in h
+            assert "facility_type_id" in h
+            assert "facility_ownership_name" in h
+            assert "facility_type_name" in h
```
