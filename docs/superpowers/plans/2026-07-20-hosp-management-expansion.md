# Hospital Management Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `organisation_unit_id`, `facility_ownership_id`, and `facility_type_id` to the Hospital model, with FacilityOwnership and FacilityType as managed reference data.

**Architecture:** Follow the exact same CRUD pattern as Governorates and Hospital Types — new SQLAlchemy models, Pydantic schemas, API routers (1 per entity), and UI subtabs in the existing Hospitals Management page.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, vanilla JS

## Global Constraints
- No migrations system — use `ALTER TABLE ADD COLUMN` directly
- No Alembic — schema changes are manual SQL
- All existing tests must continue to pass
- All new API endpoints must include cache invalidation on write
- Frontend follows existing pattern: `hospitals.html` (4 subtabs now), `hospitals.js`
- All new reference tables use `SET NULL` on delete (same as governorates/hospital_types)

---

### Task 1: Backend Models + Schemas

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Test: `tests/test_api_ownership_types.py`

**Interfaces:**
- Produces: `FacilityOwnership`, `FacilityType` SQLAlchemy models; `FacilityOwnershipBase`, `FacilityOwnershipCreate`, `FacilityOwnershipOut`, `FacilityTypeBase`, `FacilityTypeCreate`, `FacilityTypeOut` Pydantic schemas; extended `Hospital`, `HospitalBase`, `HospitalOut` with new fields

- [ ] **Step 1: Add FacilityOwnership and FacilityType models**

Add to `app/models.py` after the `HospitalType` class:

```python
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
```

- [ ] **Step 2: Extend Hospital model**

Add these columns to the `Hospital` class:

```python
    organisation_unit_id = Column(String(100), nullable=True)
    facility_ownership_id = Column(Integer, ForeignKey("facility_ownerships.id", ondelete="SET NULL"), nullable=True)
    facility_type_id = Column(Integer, ForeignKey("facility_types.id", ondelete="SET NULL"), nullable=True)

    facility_ownership = relationship("FacilityOwnership", back_populates="hospitals")
    facility_type = relationship("FacilityType", back_populates="hospitals")
```

- [ ] **Step 3: Add Pydantic schemas**

Add to `app/schemas.py` after `HospitalTypeOut`:

```python
class FacilityOwnershipBase(BaseModel):
    name: str

class FacilityOwnershipCreate(FacilityOwnershipBase):
    pass

class FacilityOwnershipOut(FacilityOwnershipBase):
    id: int
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class FacilityTypeBase(BaseModel):
    name: str

class FacilityTypeCreate(FacilityTypeBase):
    pass

class FacilityTypeOut(FacilityTypeBase):
    id: int
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True
```

- [ ] **Step 4: Extend HospitalBase and HospitalOut**

Add to `HospitalBase`:
```python
    organisation_unit_id: Optional[str] = None
    facility_ownership_id: Optional[int] = None
    facility_type_id: Optional[int] = None
```

Add to `HospitalOut`:
```python
    facility_ownership_name: Optional[str] = None
    facility_type_name: Optional[str] = None
```

- [ ] **Step 5: Run tests to verify imports work**

Run: `python -c "from app.models import FacilityOwnership, FacilityType; from app.schemas import FacilityOwnershipOut, FacilityTypeOut; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/schemas.py
git commit -m "feat: add FacilityOwnership, FacilityType models and schemas"
```

---

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

### Task 3: Database Schema + Seed Data

**Files:**
- Modify: `app/main.py` (seed section)

**Interfaces:**
- Consumes: models from Task 1, API from Task 2
- Produces: facility_ownerships and facility_types tables with seed rows

- [ ] **Step 1: Create DB tables via SQL**

Run:
```python
cd C:\ibra\HEALTH-ai
python -c "
from app.database import engine
from app.models import FacilityOwnership, FacilityType
from sqlalchemy import create_engine, text

# Create new tables
Base.metadata.create_all(bind=engine, tables=[FacilityOwnership.__table__, FacilityType.__table__])

# ALTER TABLE for new columns on hospitals
with engine.connect() as conn:
    for col, typ in [('organisation_unit_id', 'VARCHAR(100)'), ('facility_ownership_id', 'INTEGER'), ('facility_type_id', 'INTEGER')]:
        try:
            conn.execute(text(f'ALTER TABLE hospitals ADD COLUMN {col} {typ}'))
            conn.commit()
        except Exception as e:
            print(f'Column {col} may already exist: {e}')
"
```
Expected: Tables created, columns added (or already exist)

- [ ] **Step 2: Seed default data**

Add seed rows to the seed section in `app/main.py` (around line 120, after hospital types seed):

```python
    # Seed facility ownerships
    if not db.query(FacilityOwnership).first():
        for name in ["\u062d\u0643\u0648\u0645\u064a", "NGOs", "INGOs", "\u062e\u0627\u0635"]:
            db.add(FacilityOwnership(name=name))

    # Seed facility types
    if not db.query(FacilityType).first():
        db.add(FacilityType(name="\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"))
```

Also add the imports:
```python
from app.models import FacilityOwnership, FacilityType
```

- [ ] **Step 3: Run seed + verify**

Run: `python -c "
from app.database import SessionLocal
from app.models import FacilityOwnership, FacilityType
db = SessionLocal()
print('Ownerships:', [(o.id, o.name) for o in db.query(FacilityOwnership).all()])
print('Types:', [(t.id, t.name) for t in db.query(FacilityType).all()])
db.close()
"`
Expected: 4 ownership rows, 1 type row

- [ ] **Step 4: Run full test suite to check no regressions**

Run: `python -m pytest --tb=short -q`
Expected: same count as before (should be 339+11=350 with the new test module)

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: create facility_ownerships/facility_types tables and seed data"
```

---

### Task 4: Frontend — Hospitals Page Extension

**Files:**
- Modify: `static/tabs/hospitals.html`
- Modify: `static/js/hospitals.js`

- [ ] **Step 1: Add subtab buttons for Facility Ownerships and Facility Types**

In `static/tabs/hospitals.html`, add two more buttons to the subtab bar (after the "Hospital Types" button):

```html
        <button class="hosp-subtab" data-subtab="ownerships" onclick="switchHospSubtab('ownerships')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Ownerships</button>
        <button class="hosp-subtab" data-subtab="facilitytypes" onclick="switchHospSubtab('facilitytypes')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Types</button>
```

- [ ] **Step 2: Add subtab content containers**

After the `#hospSub-types` div, add:

```html
    <div id="hospSub-ownerships" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showOwnershipModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Ownership</button>
        <div id="ownershipList" style="font-size:0.85rem;"></div>
    </div>

    <div id="hospSub-facilitytypes" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showFacilityTypeModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Facility Type</button>
        <div id="facilityTypeList" style="font-size:0.85rem;"></div>
    </div>
```

- [ ] **Step 3: Add modals for Ownership and Facility Type**

After the `#typeModal` div, add:

```html
<div id="ownershipModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="ownershipModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Ownership</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="ownershipFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeOwnershipModal()">Cancel</button>
            <button class="btn" onclick="saveOwnership()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>

<div id="facilityTypeModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="facilityTypeModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Type</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="facilityTypeFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeFacilityTypeModal()">Cancel</button>
            <button class="btn" onclick="saveFacilityType()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Extend hospital form modal with new fields**

In the `#hospModal` section, add fields before the Address field:

```html
            <div><label style="font-size:0.8rem;color:#666;">Organisation Unit ID</label><input id="hospFormOrgUnitId" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
            <div><label style="font-size:0.8rem;color:#666;">Facility Ownership</label><select id="hospFormOwnership" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
            <div><label style="font-size:0.8rem;color:#666;">Facility Type</label><select id="hospFormFacilityType" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
```

- [ ] **Step 5: Add new columns to hospitals table**

In `renderHospitals()` JS function, add columns after the "Name" column header:
```javascript
        '<th style="text-align:left;padding:0.4rem;">OrgUnit ID</th>' +
        '<th style="text-align:left;padding:0.4rem;">Ownership</th>' +
        '<th style="text-align:left;padding:0.4rem;">Facility Type</th>' +
```

And add cells in the row render loop (after the name cell):
```javascript
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + esc(h.organisation_unit_id || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_ownership_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_type_name || '') + '</td>' +
```

- [ ] **Step 6: Add ownership dropdown filter**

In the filter bar, add after the type filter:
```html
            <select id="hospFilterOwnership" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Ownerships</option>
            </select>
            <select id="hospFilterFacilityType" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Facility Types</option>
            </select>
```

And in `renderHospitals()` add filter logic:
```javascript
    const filterOwn = document.getElementById('hospFilterOwnership').value;
    const filterFacType = document.getElementById('hospFilterFacilityType').value;
    // ... add to filter: if (filterOwn && String(h.facility_ownership_id) !== filterOwn) return false;
    // ... if (filterFacType && String(h.facility_type_id) !== filterFacType) return false;
```

- [ ] **Step 7: Add JS CRUD functions for Ownerships**

In `static/js/hospitals.js`, add after `deleteHospitalType()`:

```javascript
// ── Facility Ownerships ──────────────────────────────────────────
let _ownerships = [];
let _editOwnId = null;

function loadOwnerships() {
    apiGet('/facility-ownerships/').then(data => {
        _ownerships = data || [];
        renderOwnerships();
        populateOwnershipDropdowns();
    });
}

function renderOwnerships() {
    const container = document.getElementById('ownershipList');
    if (!_ownerships.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No facility ownerships yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _ownerships.forEach(o => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(o.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (o.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editOwnership(' + o.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteOwnership(' + o.id + ')" style="color:#c62828;">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateOwnershipDropdowns() {
    const selects = ['hospFormOwnership', 'hospFilterOwnership'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormOwnership' ? '-- None --' : 'All Ownerships') + '</option>' +
            _ownerships.map(o => '<option value="' + o.id + '">' + esc(o.name) + '</option>').join('');
        sel.value = val;
    });
}

function showOwnershipModal(data) {
    _editOwnId = data ? data.id : null;
    document.getElementById('ownershipModalTitle').textContent = data ? 'Edit Facility Ownership' : 'Add Facility Ownership';
    document.getElementById('ownershipFormName').value = data ? data.name : '';
    document.getElementById('ownershipModal').style.display = 'flex';
}
window.showOwnershipModal = showOwnershipModal;

function closeOwnershipModal() {
    document.getElementById('ownershipModal').style.display = 'none';
    _editOwnId = null;
}
window.closeOwnershipModal = closeOwnershipModal;

function saveOwnership() {
    const name = document.getElementById('ownershipFormName').value.trim();
    if (!name) { alert('Name is required.'); return; }
    const promise = _editOwnId ? apiPut('/facility-ownerships/' + _editOwnId, { name: name }) : apiPostJSON('/facility-ownerships/', { name: name });
    promise.then(() => {
        closeOwnershipModal();
        loadOwnerships();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveOwnership = saveOwnership;

function editOwnership(id) {
    const o = _ownerships.find(x => x.id === id);
    if (o) showOwnershipModal(o);
}
window.editOwnership = editOwnership;

function deleteOwnership(id) {
    if (!confirm('Delete this facility ownership? Only possible if no hospitals are linked.')) return;
    apiDelete('/facility-ownerships/' + id).then(() => loadOwnerships()).catch(err => alert('Failed: ' + err));
}
window.deleteOwnership = deleteOwnership;
```

- [ ] **Step 8: Add JS CRUD functions for Facility Types**

Same pattern as Step 7, but for `/facility-types/`:
- `_facilityTypes = []`, `_editFacTypeId = null`
- `loadFacilityTypes()`, `renderFacilityTypes()`, `populateFacilityTypeDropdowns()`
- `showFacilityTypeModal()`, `closeFacilityTypeModal()`, `saveFacilityType()`, `editFacilityType(id)`, `deleteFacilityType(id)`
- Target container: `facilityTypeList`
- Form: `facilityTypeFormName`, `facilityTypeModal`, `facilityTypeModalTitle`
- API: `/facility-types/`

- [ ] **Step 9: Wire hospital form to include new fields**

In `showHospitalModal()` add:
```javascript
    document.getElementById('hospFormOrgUnitId').value = data ? data.organisation_unit_id || '' : '';
    document.getElementById('hospFormOwnership').value = data ? data.facility_ownership_id || '' : '';
    document.getElementById('hospFormFacilityType').value = data ? data.facility_type_id || '' : '';
```

In `saveHospital()` add to the data object:
```javascript
        organisation_unit_id: document.getElementById('hospFormOrgUnitId').value.trim() || null,
        facility_ownership_id: document.getElementById('hospFormOwnership').value ? parseInt(document.getElementById('hospFormOwnership').value) : null,
        facility_type_id: document.getElementById('hospFormFacilityType').value ? parseInt(document.getElementById('hospFormFacilityType').value) : null,
```

- [ ] **Step 10: Wire load functions in `loadHospitalsTab()`**

Add calls at the end of the function:
```javascript
    loadOwnerships();
    loadFacilityTypes();
```

- [ ] **Step 11: Add new filter load in `loadHospitalsTab()` (after populateTypeDropdowns)**

The dropdowns will be populated by `populateOwnershipDropdowns()` and `populateFacilityTypeDropdowns()` which are called from `loadOwnerships()` and `loadFacilityTypes()` respectively. The filter values should reset properly — the existing pattern already handles this via `sel.value = val`.

- [ ] **Step 12: Run full test suite to verify no regressions**

Run: `python -m pytest --tb=short -q`
Expected: all tests pass (should be ~350 with the new test module)

- [ ] **Step 13: Commit**

```bash
git add static/tabs/hospitals.html static/js/hospitals.js
git commit -m "feat: extend hospitals UI with ownership, facility type, org unit fields"
```

---

### Task 5: Final Verification

**Files:** (none — verification only)

- [ ] **Step 1: Verify all tests pass**

Run: `python -m pytest --tb=short -q`
Expected: all pass

- [ ] **Step 2: Verify app loads and all endpoints respond**

Run: `python -c "
from app.main import app
from app.database import SessionLocal
from app.models import FacilityOwnership, FacilityType
db = SessionLocal()
assert db.query(FacilityOwnership).count() >= 4
assert db.query(FacilityType).count() >= 1
print('Seed data OK')
print('Routes:', sum(1 for r in app.routes))
db.close()
"`
Expected: Seed data OK, Routes count shown

- [ ] **Step 3: Verify new columns exist on hospitals**

Run: `python -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('hospitals')]
assert 'organisation_unit_id' in cols
assert 'facility_ownership_id' in cols
assert 'facility_type_id' in cols
print('All new columns present:', cols)
"`
Expected: All new columns present

- [ ] **Step 4: Print commit log**

Run: `git log --oneline -6`
Expected: Shows the 4 new commits + previous work
