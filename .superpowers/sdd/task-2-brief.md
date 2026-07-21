### Task 2: Backend API Endpoints

**Files:**
- Create: `app/api/facility_ownerships.py`
- Create: `app/api/facility_types.py`
- Modify: `app/api/hospitals.py`
- Modify: `app/main.py`
- Test: `tests/test_api_ownership_types.py`

**Interfaces:**
- Produces: `GET/POST/PUT/DELETE /api/facility-ownerships/`, `GET/POST/PUT/DELETE /api/facility-types/`, extended `GET/POST/PUT /api/hospitals/` with new fields
- Consumes: `FacilityOwnership`, `FacilityType` models and schemas from Task 1

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api_ownership_types.py`:

```python
"""Tests for facility-ownerships and facility-types API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Hospital


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestFacilityOwnerships:
    def test_list_empty(self, client):
        resp = client.get("/facility-ownerships/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create(self, client):
        resp = client.post("/facility-ownerships/", json={"name": "\u062d\u0643\u0648\u0645\u064a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "\u062d\u0643\u0648\u0645\u064a"
        assert "id" in data

    def test_create_duplicate(self, client):
        client.post("/facility-ownerships/", json={"name": "NGOs"})
        resp = client.post("/facility-ownerships/", json={"name": "NGOs"})
        assert resp.status_code == 400

    def test_update(self, client):
        client.post("/facility-ownerships/", json={"name": "OLD"})
        resp = client.put("/facility-ownerships/1", json={"name": "NEW"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "NEW"

    def test_delete(self, client):
        client.post("/facility-ownerships/", json={"name": "DELETE_ME"})
        resp = client.delete("/facility-ownerships/1")
        assert resp.status_code == 200

    def test_delete_linked_hospital_fails(self, client, db_session):
        client.post("/facility-ownerships/", json={"name": "GOV"})
        h = db_session.query(Hospital).first()
        h.facility_ownership_id = 1
        db_session.commit()
        resp = client.delete("/facility-ownerships/1")
        assert resp.status_code == 400

    def test_get_nonexistent(self, client):
        resp = client.get("/facility-ownerships/999")
        assert resp.status_code == 404


class TestFacilityTypes:
    def test_list_empty(self, client):
        resp = client.get("/facility-types/")
        assert resp.status_code == 200

    def test_create(self, client):
        resp = client.post("/facility-types/", json={"name": "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"

    def test_create_duplicate(self, client):
        client.post("/facility-types/", json={"name": "X"})
        resp = client.post("/facility-types/", json={"name": "X"})
        assert resp.status_code == 400

    def test_update(self, client):
        client.post("/facility-types/", json={"name": "A"})
        resp = client.put("/facility-types/1", json={"name": "B"})
        assert resp.status_code == 200

    def test_delete(self, client):
        client.post("/facility-types/", json={"name": "DEL"})
        resp = client.delete("/facility-types/1")
        assert resp.status_code == 200

    def test_delete_linked_hospital_fails(self, client, db_session):
        client.post("/facility-types/", json={"name": "FT"})
        h = db_session.query(Hospital).first()
        h.facility_type_id = 1
        db_session.commit()
        resp = client.delete("/facility-types/1")
        assert resp.status_code == 400


class TestHospitalExtended:
    def test_hospital_has_new_fields(self, client):
        resp = client.get("/hospitals/")
        assert resp.status_code == 200
        data = resp.json()
        if data:
            h = data[0]
            assert "organisation_unit_id" in h
            assert "facility_ownership_id" in h
            assert "facility_type_id" in h
            assert "facility_ownership_name" in h
            assert "facility_type_name" in h
```

- [ ] **Step 2: Run tests — expect failures**

Run: `python -m pytest tests/test_api_ownership_types.py -v`
Expected: ImportError or 404 — endpoints don't exist yet

- [ ] **Step 3: Create `app/api/facility_ownerships.py`**

Copy the exact pattern from `app/api/governorates.py`, replacing:
- `Governorate` → `FacilityOwnership`
- `governorate` → `facility-ownership`
- `GovernorateOut` → `FacilityOwnershipOut`
- `GovernorateCreate` → `FacilityOwnershipCreate`
- error messages: "Governorate" → "Facility ownership"
- linked query: `Hospital.facility_ownership_id`

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import FacilityOwnership, Hospital
from app.schemas import FacilityOwnershipOut, FacilityOwnershipCreate

router = APIRouter(prefix="/facility-ownerships", tags=["facility_ownerships"])


@router.get("/", response_model=List[FacilityOwnershipOut])
def list_facility_ownerships(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(FacilityOwnership).order_by(FacilityOwnership.name)
    return q.offset(skip).limit(limit).all()


@router.get("/{ownership_id}", response_model=FacilityOwnershipOut)
def get_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    return ow


@router.post("/", response_model=FacilityOwnershipOut)
def create_facility_ownership(data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
    existing = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Facility ownership already exists")
    ow = FacilityOwnership(name=data.name)
    db.add(ow)
    db.commit()
    db.refresh(ow)
    cache.invalidate()
    return ow


@router.put("/{ownership_id}", response_model=FacilityOwnershipOut)
def update_facility_ownership(ownership_id: int, data: FacilityOwnershipCreate, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    dup = db.query(FacilityOwnership).filter(FacilityOwnership.name == data.name, FacilityOwnership.id != ownership_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Facility ownership name already taken")
    ow.name = data.name
    db.commit()
    db.refresh(ow)
    cache.invalidate()
    return ow


@router.delete("/{ownership_id}")
def delete_facility_ownership(ownership_id: int, db: Session = Depends(get_db)):
    ow = db.query(FacilityOwnership).filter(FacilityOwnership.id == ownership_id).first()
    if not ow:
        raise HTTPException(status_code=404, detail="Facility ownership not found")
    linked = db.query(Hospital).filter(Hospital.facility_ownership_id == ownership_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete facility ownership with linked hospitals")
    db.delete(ow)
    db.commit()
    cache.invalidate()
    return {"ok": True}
```

- [ ] **Step 4: Create `app/api/facility_types.py`**

Same pattern as `app/api/hospital_types.py`, replacing:
- `HospitalType` → `FacilityType`
- `hospital-types` → `facility-types`
- `HospitalTypeOut` → `FacilityTypeOut`
- `HospitalTypeCreate` → `FacilityTypeCreate`
- linked query: `Hospital.facility_type_id`

- [ ] **Step 5: Register routers in `app/main.py`**

Add import:
```python
from app.api import facility_ownerships as facility_ownerships_api, facility_types as facility_types_api
```

Add after `app.include_router(hospital_types_api.router)`:
```python
app.include_router(facility_ownerships_api.router)
app.include_router(facility_types_api.router)
```

- [ ] **Step 6: Extend hospitals.py list/get/create/update**

In `app/api/hospitals.py`:

**list_hospitals** — add to each result dict:
```python
    "organisation_unit_id": h.organisation_unit_id,
    "facility_ownership_id": h.facility_ownership_id,
    "facility_type_id": h.facility_type_id,
    "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
    "facility_type_name": h.facility_type.name if h.facility_type else None,
```

**get_hospital** — same additions.

**create_hospital** — add new fields to `Hospital(...)` constructor:
```python
    organisation_unit_id=data.organisation_unit_id,
    facility_ownership_id=data.facility_ownership_id,
    facility_type_id=data.facility_type_id,
```

**update_hospital** — add new fields to assignment:
```python
    hosp.organisation_unit_id = data.organisation_unit_id
    hosp.facility_ownership_id = data.facility_ownership_id
    hosp.facility_type_id = data.facility_type_id
```

- [ ] **Step 7: Run tests — expect pass**

Run: `python -m pytest tests/test_api_ownership_types.py -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add app/api/facility_ownerships.py app/api/facility_types.py app/api/hospitals.py app/main.py tests/test_api_ownership_types.py
git commit -m "feat: add facility-ownerships and facility-types API endpoints"
```

---
