# Hospitals Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dedicated hospital management with governorates and hospital types as reference data linked via foreign keys.

**Architecture:** New `governorates` and `hospital_types` tables with CRUD API + extended `hospitals` table with FKs. New "Hospitals" tab in main nav with 3 sub-views (hospitals list, governorates, types).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite, vanilla JS

## Global Constraints
- Use same patterns as existing API routers (`app/api/hospitals.py`, `app/api/dashboard.py`)
- Use same SQLAlchemy declarative base (`app.database.Base`)
- Use same Alembic batch mode for SQLite migrations
- Frontend: vanilla JS, no frameworks
- Backend: Python 3.14+, FastAPI
- All new text in UI must support i18n (existing `__()` pattern)

---

### Task 1: Alembic Migration — New Tables + Columns

**Files:**
- Create: `alembic/versions/REVISION_add_governorates_hospital_types.py`

**Interfaces:**
- Consumes: existing `hospitals` table
- Produces: `governorates` table, `hospital_types` table, new columns on `hospitals`

- [ ] **Step 1: Generate empty migration**

Run: `alembic revision -m "add governorates and hospital types"`

Note the generated revision ID (e.g., `abc123def456`).

- [ ] **Step 2: Write upgrade/downgrade**

Replace the file content with:

```python
"""add governorates and hospital types

Revision ID: <REVISION>
Revises: e43bebf7f9e0
Create Date: 2026-07-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<REVISION>'
down_revision: Union[str, Sequence[str], None] = 'e43bebf7f9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('governorates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_governorates_name'), 'governorates', ['name'], unique=True)

    op.create_table('hospital_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_hospital_types_name'), 'hospital_types', ['name'], unique=True)

    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('governorate_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('hospital_type_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('address', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_hospitals_governorate', 'governorates', ['governorate_id'], ['id'])
        batch_op.create_foreign_key('fk_hospitals_type', 'hospital_types', ['hospital_type_id'], ['id'])

def downgrade() -> None:
    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.drop_constraint('fk_hospitals_type', type_='foreignkey')
        batch_op.drop_constraint('fk_hospitals_governorate', type_='foreignkey')
        batch_op.drop_column('address')
        batch_op.drop_column('hospital_type_id')
        batch_op.drop_column('governorate_id')

    op.drop_index(op.f('ix_hospital_types_name'), table_name='hospital_types')
    op.drop_table('hospital_types')
    op.drop_index(op.f('ix_governorates_name'), table_name='governorates')
    op.drop_table('governorates')
```

- [ ] **Step 3: Run migration**

```bash
alembic upgrade head
```

Expected: No errors, new tables created.

- [ ] **Step 4: Verify**

```bash
python -c "from app.database import engine; import sqlalchemy as sa; insp = sa.inspect(engine); print('governorates:', 'governorates' in insp.get_table_names()); print('hospital_types:', 'hospital_types' in insp.get_table_names()); print('hospitals cols:', [c['name'] for c in insp.get_columns('hospitals')])"
```

Expected: `governorates: True`, `hospital_types: True`, `hospitals cols` includes `governorate_id`, `hospital_type_id`, `address`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: add governorates and hospital_types tables"
```

---

### Task 2: SQLAlchemy Models

**Files:**
- Modify: `app/models.py`

**Interfaces:**
- Produces: `Governorate` model, `HospitalType` model, updated `Hospital` with `governorate_id`, `hospital_type_id`, `address`, `governorate` relationship, `hospital_type` relationship

- [ ] **Step 1: Add Governorate and HospitalType models before Hospital class**

```python
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
```

- [ ] **Step 2: Add new columns + relationships to Hospital model**

Add after `region`:
```python
    governorate_id = Column(Integer, ForeignKey("governorates.id"), nullable=True)
    hospital_type_id = Column(Integer, ForeignKey("hospital_types.id"), nullable=True)
    address = Column(Text, nullable=True)
```

Add after existing relationships:
```python
    governorate = relationship("Governorate", back_populates="hospitals")
    hospital_type = relationship("HospitalType", back_populates="hospitals")
```

Final `Hospital` class:
```python
class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    region = Column(String(100), nullable=True)
    governorate_id = Column(Integer, ForeignKey("governorates.id"), nullable=True)
    hospital_type_id = Column(Integer, ForeignKey("hospital_types.id"), nullable=True)
    address = Column(Text, nullable=True)
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
```

- [ ] **Step 3: Verify models load**

```bash
python -c "from app.models import Governorate, HospitalType, Hospital; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/models.py
git commit -m "feat: add Governorate and HospitalType models"
```

---

### Task 3: Pydantic Schemas

**Files:**
- Modify: `app/schemas.py`

**Interfaces:**
- Produces: `GovernorateOut`, `GovernorateCreate`, `HospitalTypeOut`, `HospitalTypeCreate`, updated `HospitalCreate`, updated `HospitalOut`

- [ ] **Step 1: Add governorate and hospital type schemas after HospitalOut**

```python
class GovernorateBase(BaseModel):
    name: str


class GovernorateCreate(GovernorateBase):
    pass


class GovernorateOut(GovernorateBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HospitalTypeBase(BaseModel):
    name: str


class HospitalTypeCreate(HospitalTypeBase):
    pass


class HospitalTypeOut(HospitalTypeBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Update HospitalBase and HospitalOut**

```python
class HospitalBase(BaseModel):
    name: str
    region: Optional[str] = None
    governorate_id: Optional[int] = None
    hospital_type_id: Optional[int] = None
    address: Optional[str] = None


class HospitalCreate(HospitalBase):
    pass


class HospitalOut(HospitalBase):
    id: int
    is_active: bool = True
    created_at: Optional[datetime] = None
    governorate_name: Optional[str] = None
    hospital_type_name: Optional[str] = None

    class Config:
        from_attributes = True
```

- [ ] **Step 3: Verify**

```bash
python -c "from app.schemas import HospitalOut, GovernorateOut, HospitalTypeOut; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/schemas.py
git commit -m "feat: add governorate/hospital_type schemas, extend hospital schemas"
```

---

### Task 4: API — Governorates Router

**Files:**
- Create: `app/api/governorates.py`

**Interfaces:**
- Consumes: `Governorate` model, `GovernorateCreate`, `GovernorateOut`
- Produces: router with LIST/CREATE/UPDATE/DELETE endpoints
- URL prefix: `/api/governorates`

- [ ] **Step 1: Create the router file**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import Governorate, Hospital
from app.schemas import GovernorateOut, GovernorateCreate

router = APIRouter(prefix="/governorates", tags=["governorates"])


@router.get("/", response_model=List[GovernorateOut])
def list_governorates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(Governorate).order_by(Governorate.name)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=GovernorateOut)
def create_governorate(data: GovernorateCreate, db: Session = Depends(get_db)):
    existing = db.query(Governorate).filter(Governorate.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Governorate already exists")
    gov = Governorate(name=data.name)
    db.add(gov)
    db.commit()
    db.refresh(gov)
    cache.invalidate()
    return gov


@router.put("/{governorate_id}", response_model=GovernorateOut)
def update_governorate(governorate_id: int, data: GovernorateCreate, db: Session = Depends(get_db)):
    gov = db.query(Governorate).filter(Governorate.id == governorate_id).first()
    if not gov:
        raise HTTPException(status_code=404, detail="Governorate not found")
    dup = db.query(Governorate).filter(Governorate.name == data.name, Governorate.id != governorate_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Governorate name already taken")
    gov.name = data.name
    db.commit()
    db.refresh(gov)
    cache.invalidate()
    return gov


@router.delete("/{governorate_id}")
def delete_governorate(governorate_id: int, db: Session = Depends(get_db)):
    gov = db.query(Governorate).filter(Governorate.id == governorate_id).first()
    if not gov:
        raise HTTPException(status_code=404, detail="Governorate not found")
    linked = db.query(Hospital).filter(Hospital.governorate_id == governorate_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete governorate with linked hospitals")
    db.delete(gov)
    db.commit()
    cache.invalidate()
    return {"ok": True}
```

- [ ] **Step 2: Verify imports work**

```bash
python -c "from app.api.governorates import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/api/governorates.py
git commit -m "feat: add governorates CRUD API"
```

---

### Task 5: API — Hospital Types Router

**Files:**
- Create: `app/api/hospital_types.py`

**Interfaces:**
- Consumes: `HospitalType` model, `HospitalTypeCreate`, `HospitalTypeOut`
- Produces: router with LIST/CREATE/UPDATE/DELETE endpoints
- URL prefix: `/api/hospital-types`

- [ ] **Step 1: Create the router file**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import HospitalType, Hospital
from app.schemas import HospitalTypeOut, HospitalTypeCreate

router = APIRouter(prefix="/hospital-types", tags=["hospital_types"])


@router.get("/", response_model=List[HospitalTypeOut])
def list_hospital_types(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(HospitalType).order_by(HospitalType.name)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=HospitalTypeOut)
def create_hospital_type(data: HospitalTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(HospitalType).filter(HospitalType.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Hospital type already exists")
    ht = HospitalType(name=data.name)
    db.add(ht)
    db.commit()
    db.refresh(ht)
    cache.invalidate()
    return ht


@router.put("/{type_id}", response_model=HospitalTypeOut)
def update_hospital_type(type_id: int, data: HospitalTypeCreate, db: Session = Depends(get_db)):
    ht = db.query(HospitalType).filter(HospitalType.id == type_id).first()
    if not ht:
        raise HTTPException(status_code=404, detail="Hospital type not found")
    dup = db.query(HospitalType).filter(HospitalType.name == data.name, HospitalType.id != type_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Hospital type name already taken")
    ht.name = data.name
    db.commit()
    db.refresh(ht)
    cache.invalidate()
    return ht


@router.delete("/{type_id}")
def delete_hospital_type(type_id: int, db: Session = Depends(get_db)):
    ht = db.query(HospitalType).filter(HospitalType.id == type_id).first()
    if not ht:
        raise HTTPException(status_code=404, detail="Hospital type not found")
    linked = db.query(Hospital).filter(Hospital.hospital_type_id == type_id).first()
    if linked:
        raise HTTPException(status_code=400, detail="Cannot delete hospital type with linked hospitals")
    db.delete(ht)
    db.commit()
    cache.invalidate()
    return {"ok": True}
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from app.api.hospital_types import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/api/hospital_types.py
git commit -m "feat: add hospital types CRUD API"
```

---

### Task 6: Extend Hospitals Router with POST/PUT/DELETE

**Files:**
- Modify: `app/api/hospitals.py`
- Modify: `app/schemas.py` (already done in Task 3)

**Interfaces:**
- Consumes: `HospitalCreate`, `HospitalOut`
- Produces: POST, PUT, DELETE endpoints for hospitals

- [ ] **Step 1: Add POST /hospitals/ endpoint before PUT /{hospital_id}/toggle-active**

```python
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
        address=data.address,
    )
    db.add(hosp)
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp
```

- [ ] **Step 2: Add PUT /hospitals/{hospital_id} before the POST /{hospital_id}/re-analyze**

```python
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
    hosp.address = data.address
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp
```

- [ ] **Step 3: Add DELETE /hospitals/{hospital_id} before re-analyze**

```python
@router.delete("/{hospital_id}")
def delete_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    db.delete(hosp)
    db.commit()
    cache.invalidate()
    return {"ok": True}
```

- [ ] **Step 4: Update GET /hospitals/ to include governorate and type names**

The existing `list_hospitals` returns `List[HospitalOut]`. Since `HospitalOut` now has `governorate_name` and `hospital_type_name`, we need to populate them. Modify the function to add these after the query:

```python
@router.get("/", response_model=List[HospitalOut])
def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    include_inactive: bool = Query(False, description="Include inactive hospitals"),
    db: Session = Depends(get_db),
):
    cache_key = cache.make_key("hospitals:list", skip=skip, limit=limit, include_inactive=include_inactive)
    cached = cache.get(cache_key)
    if cached:
        result = []
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
                    "address": item.address,
                    "is_active": item.is_active,
                    "created_at": item.created_at,
                    "governorate_name": item.governorate.name if item.governorate else None,
                    "hospital_type_name": item.hospital_type.name if item.hospital_type else None,
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
            "address": h.address,
            "is_active": h.is_active,
            "created_at": h.created_at,
            "governorate_name": h.governorate.name if h.governorate else None,
            "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
        })
    cache.set(cache_key, result)
    return result
```

Also update `get_hospital` similarly:

```python
@router.get("/{hospital_id}", response_model=HospitalOut)
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
        "address": h.address,
        "is_active": h.is_active,
        "created_at": h.created_at,
        "governorate_name": h.governorate.name if h.governorate else None,
        "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
    }
```

- [ ] **Step 5: Verify**

```bash
python -c "from app.api.hospitals import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/api/hospitals.py
git commit -m "feat: add hospital CRUD, extend list response with governorate/type names"
```

---

### Task 7: Register New Routers in main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add imports and include the new routers**

Add after the existing router includes (around line 211):

```python
app.include_router(governorates.router)
app.include_router(hospital_types.router)
```

Add with the other imports at the top of the file:

```python
from app.api.governorates import router as governorates_router
from app.api.hospital_types import router as hospital_types_router
```

Then update the include calls:

```python
app.include_router(governorates_router)
app.include_router(hospital_types_router)
```

- [ ] **Step 2: Verify**

```bash
python -c "from app.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: register governorates and hospital_types routers"
```

---

### Task 8a: Add apiDelete + fix apiPost for JSON in api.js

**Files:**
- Modify: `static/js/api.js`

**Note:** The existing `apiPost` doesn't set Content-Type: application/json. We need `apiDelete` for DELETE endpoints and a JSON-capable POST.

- [ ] **Step 1: Add apiDelete and apiPostJSON to api.js**

After `apiPut`:

```javascript
export async function apiDelete(path) {
    const res = await fetch(API() + path, { method: 'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
    return res.json();
}
export async function apiPostJSON(path, data) {
    const res = await fetch(API() + path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
    if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
    return res.json();
}
```

- [ ] **Step 2: Verify**

Check that `api.js` now exports `apiDelete` and `apiPostJSON` functions.

- [ ] **Step 3: Commit**

```bash
git add static/js/api.js
git commit -m "feat: add apiDelete and apiPostJSON helpers"
```

---

### Task 8b: UI — Hospitals Tab HTML

**Files:**
- Create: `static/tabs/hospitals.html`

- [ ] **Step 1: Create hospitals.html**

```html
<div style="max-width:1000px;">
    <h2 style="color:#1a237e;margin-bottom:0.5rem;">Hospitals Management</h2>

    <div style="display:flex;gap:0.3rem;margin-bottom:1rem;border-bottom:2px solid #e0e0e0;">
        <button class="hosp-subtab active" data-subtab="hospitals" onclick="switchHospSubtab('hospitals')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#1a237e;border-bottom:2px solid #1a237e;margin-bottom:-2px;cursor:pointer;">Hospitals</button>
        <button class="hosp-subtab" data-subtab="governorates" onclick="switchHospSubtab('governorates')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Governorates</button>
        <button class="hosp-subtab" data-subtab="types" onclick="switchHospSubtab('types')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Hospital Types</button>
    </div>

    <!-- Hospitals List -->
    <div id="hospSub-hospitals" class="hosp-subtab-content">
        <div style="display:flex;gap:0.5rem;margin-bottom:0.8rem;flex-wrap:wrap;align-items:center;">
            <button class="btn" onclick="showHospitalModal()" style="background:#1a237e;color:white;">+ Add Hospital</button>
            <input type="text" id="hospSearch" placeholder="Search by name..." oninput="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;width:200px;">
            <select id="hospFilterGov" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Governorates</option>
            </select>
            <select id="hospFilterType" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Types</option>
            </select>
        </div>
        <div id="hospList" style="font-size:0.85rem;"></div>
    </div>

    <!-- Governorates Management -->
    <div id="hospSub-governorates" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showGovModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Governorate</button>
        <div id="govList" style="font-size:0.85rem;"></div>
    </div>

    <!-- Hospital Types Management -->
    <div id="hospSub-types" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showTypeModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Hospital Type</button>
        <div id="typeList" style="font-size:0.85rem;"></div>
    </div>
</div>

<!-- Hospital Modal -->
<div id="hospModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:500px;width:90%;">
        <h3 id="hospModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Hospital</h3>
        <div style="display:flex;flex-direction:column;gap:0.6rem;">
            <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="hospFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
            <div><label style="font-size:0.8rem;color:#666;">Governorate</label><select id="hospFormGov" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
            <div><label style="font-size:0.8rem;color:#666;">Hospital Type</label><select id="hospFormType" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
            <div><label style="font-size:0.8rem;color:#666;">Address</label><textarea id="hospFormAddress" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;resize:vertical;" rows="2"></textarea></div>
        </div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeHospModal()">Cancel</button>
            <button class="btn" onclick="saveHospital()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>

<!-- Governorate Modal -->
<div id="govModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="govModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Governorate</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="govFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeGovModal()">Cancel</button>
            <button class="btn" onclick="saveGovernorate()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>

<!-- Hospital Type Modal -->
<div id="typeModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="typeModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Hospital Type</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="typeFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeTypeModal()">Cancel</button>
            <button class="btn" onclick="saveHospitalType()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add static/tabs/hospitals.html
git commit -m "feat: add hospitals tab HTML structure"
```

---

### Task 9: UI — Hospitals JS Logic

**Files:**
- Create: `static/js/hospitals.js`

- [ ] **Step 1: Create hospitals.js**

```javascript
import { apiGet, apiPut, apiDelete, apiPostJSON } from './api.js';

let _hospitals = [];
let _governorates = [];
let _types = [];
let _editHospId = null;
let _editGovId = null;
let _editTypeId = null;

export function loadHospitalsTab() {
    loadGovernorates();
    loadHospitalTypes();
    loadHospitalsList();
}

function switchHospSubtab(name) {
    document.querySelectorAll('.hosp-subtab').forEach(t => {
        t.style.color = t.dataset.subtab === name ? '#1a237e' : '#888';
        t.style.borderBottom = t.dataset.subtab === name ? '2px solid #1a237e' : '2px solid transparent';
    });
    document.querySelectorAll('.hosp-subtab-content').forEach(d => d.style.display = 'd-none');
    document.getElementById('hospSub-' + name).style.display = '';
}
window.switchHospSubtab = switchHospSubtab;

function loadHospitalsList() {
    apiGet('/hospitals/?include_inactive=true').then(data => {
        _hospitals = data || [];
        renderHospitals();
    });
}

function renderHospitals() {
    const search = (document.getElementById('hospSearch').value || '').toLowerCase();
    const filterGov = document.getElementById('hospFilterGov').value;
    const filterType = document.getElementById('hospFilterType').value;
    const filtered = _hospitals.filter(h => {
        if (search && !h.name.toLowerCase().includes(search)) return false;
        if (filterGov && String(h.governorate_id) !== filterGov) return false;
        if (filterType && String(h.hospital_type_id) !== filterType) return false;
        return true;
    });
    const container = document.getElementById('hospList');
    if (!filtered.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No hospitals found.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Governorate</th>' +
        '<th style="text-align:left;padding:0.4rem;">Type</th>' +
        '<th style="text-align:center;padding:0.4rem;">Status</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    filtered.forEach(h => {
        const govName = h.governorate_name || '';
        const typeName = h.hospital_type_name || '';
        const statusHtml = '<input type="checkbox" ' + (h.is_active ? 'checked' : '') + ' onchange="toggleHospitalActive(' + h.id + ', this.checked)"> ' + (h.is_active ? 'Active' : 'Inactive');
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(h.name) + (h.address ? '<br><span style="font-size:0.72rem;color:#999;">' + esc(h.address) + '</span>' : '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(govName) + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(typeName) + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' + statusHtml + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospital(' + h.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospital(' + h.id + ')" style="color:#c62828;">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}
window.filterHospitals = function() { renderHospitals(); };

function loadGovernorates() {
    apiGet('/governorates/').then(data => {
        _governorates = data || [];
        renderGovernorates();
        populateGovDropdowns();
    });
}

function renderGovernorates() {
    const container = document.getElementById('govList');
    if (!_governorates.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No governorates yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _governorates.forEach(g => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(g.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (g.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editGovernorate(' + g.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteGovernorate(' + g.id + ')" style="color:#c62828;">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateGovDropdowns() {
    const selects = ['hospFormGov', 'hospFilterGov'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormGov' ? '-- None --' : 'All Governorates') + '</option>' +
            _governorates.map(g => '<option value="' + g.id + '">' + esc(g.name) + '</option>').join('');
        sel.value = val;
    });
}

function loadHospitalTypes() {
    apiGet('/hospital-types/').then(data => {
        _types = data || [];
        renderHospitalTypes();
        populateTypeDropdowns();
    });
}

function renderHospitalTypes() {
    const container = document.getElementById('typeList');
    if (!_types.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No hospital types yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _types.forEach(t => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospitalType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospitalType(' + t.id + ')" style="color:#c62828;">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateTypeDropdowns() {
    const selects = ['hospFormType', 'hospFilterType'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormType' ? '-- None --' : 'All Types') + '</option>' +
            _types.map(t => '<option value="' + t.id + '">' + esc(t.name) + '</option>').join('');
        sel.value = val;
    });
}

// Hospital CRUD
function showHospitalModal(data) {
    _editHospId = data ? data.id : null;
    document.getElementById('hospModalTitle').textContent = data ? 'Edit Hospital' : 'Add Hospital';
    document.getElementById('hospFormName').value = data ? data.name : '';
    document.getElementById('hospFormGov').value = data ? data.governorate_id || '' : '';
    document.getElementById('hospFormType').value = data ? data.hospital_type_id || '' : '';
    document.getElementById('hospFormAddress').value = data ? data.address || '' : '';
    document.getElementById('hospModal').style.display = 'flex';
}
window.showHospitalModal = showHospitalModal;

function closeHospModal() {
    document.getElementById('hospModal').style.display = 'none';
    _editHospId = null;
}
window.closeHospModal = closeHospModal;

function saveHospital() {
    const name = document.getElementById('hospFormName').value.trim();
    if (!name) { alert('Name is required.'); return; }
    const data = {
        name: name,
        region: '',
        governorate_id: document.getElementById('hospFormGov').value ? parseInt(document.getElementById('hospFormGov').value) : null,
        hospital_type_id: document.getElementById('hospFormType').value ? parseInt(document.getElementById('hospFormType').value) : null,
        address: document.getElementById('hospFormAddress').value.trim() || null,
    };
    const promise = _editHospId ? apiPut('/hospitals/' + _editHospId, data) : apiPostJSON('/hospitals/', data);
    promise.then(() => {
        closeHospModal();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveHospital = saveHospital;

function editHospital(id) {
    const h = _hospitals.find(x => x.id === id);
    if (h) showHospitalModal(h);
}
window.editHospital = editHospital;

function deleteHospital(id) {
    if (!confirm('Delete this hospital? This cannot be undone.')) return;
    apiDelete('/hospitals/' + id).then(() => loadHospitalsList()).catch(err => alert('Failed: ' + err));
}
window.deleteHospital = deleteHospital;

function toggleHospitalActive(id, active) {
    apiPut('/hospitals/' + id + '/toggle-active').then(() => loadHospitalsList()).catch(err => alert('Failed: ' + err));
}
window.toggleHospitalActive = toggleHospitalActive;

// Governorate CRUD
function showGovModal(data) {
    _editGovId = data ? data.id : null;
    document.getElementById('govModalTitle').textContent = data ? 'Edit Governorate' : 'Add Governorate';
    document.getElementById('govFormName').value = data ? data.name : '';
    document.getElementById('govModal').style.display = 'flex';
}
window.showGovModal = showGovModal;

function closeGovModal() {
    document.getElementById('govModal').style.display = 'none';
    _editGovId = null;
}
window.closeGovModal = closeGovModal;

function saveGovernorate() {
    const name = document.getElementById('govFormName').value.trim();
    if (!name) { alert('Name is required.'); return; }
    const promise = _editGovId ? apiPut('/governorates/' + _editGovId, { name: name }) : apiPostJSON('/governorates/', { name: name });
    promise.then(() => {
        closeGovModal();
        loadGovernorates();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveGovernorate = saveGovernorate;

function editGovernorate(id) {
    const g = _governorates.find(x => x.id === id);
    if (g) showGovModal(g);
}
window.editGovernorate = editGovernorate;

function deleteGovernorate(id) {
    if (!confirm('Delete this governorate? Only possible if no hospitals are linked.')) return;
    apiDelete('/governorates/' + id).then(() => loadGovernorates()).catch(err => alert('Failed: ' + err));
}
window.deleteGovernorate = deleteGovernorate;

// Hospital Type CRUD
function showTypeModal(data) {
    _editTypeId = data ? data.id : null;
    document.getElementById('typeModalTitle').textContent = data ? 'Edit Hospital Type' : 'Add Hospital Type';
    document.getElementById('typeFormName').value = data ? data.name : '';
    document.getElementById('typeModal').style.display = 'flex';
}
window.showTypeModal = showTypeModal;

function closeTypeModal() {
    document.getElementById('typeModal').style.display = 'none';
    _editTypeId = null;
}
window.closeTypeModal = closeTypeModal;

function saveHospitalType() {
    const name = document.getElementById('typeFormName').value.trim();
    if (!name) { alert('Name is required.'); return; }
    const promise = _editTypeId ? apiPut('/hospital-types/' + _editTypeId, { name: name }) : apiPostJSON('/hospital-types/', { name: name });
    promise.then(() => {
        closeTypeModal();
        loadHospitalTypes();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveHospitalType = saveHospitalType;

function editHospitalType(id) {
    const t = _types.find(x => x.id === id);
    if (t) showTypeModal(t);
}
window.editHospitalType = editHospitalType;

function deleteHospitalType(id) {
    if (!confirm('Delete this hospital type? Only possible if no hospitals are linked.')) return;
    apiDelete('/hospital-types/' + id).then(() => loadHospitalTypes()).catch(err => alert('Failed: ' + err));
}
window.deleteHospitalType = deleteHospitalType;

// Helper
function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
```

- [ ] **Step 2: Commit**

```bash
git add static/js/hospitals.js
git commit -m "feat: add hospitals management JS logic"
```

---

### Task 10: Register Tab in Navigation + Wire Module

**Files:**
- Modify: `static/index.html`
- Modify: `static/js/main.js` (or app.js)
- Modify: `static/js/app.js` (or similar module loader)

- [ ] **Step 1: Add tab button to nav bar in index.html** (after AI Reports tab)

```html
<div class="tab" data-tab="hospitals" role="tab" aria-selected="false" aria-controls="tab-hospitals" tabindex="-1">Hospitals</div>
```

- [ ] **Step 2: Add tab content div** (after ai-reports tab content)

```html
<div id="tab-hospitals" class="tab-content" data-loaded="false" role="tabpanel" aria-labelledby="tab-hospitals" data-src="/static/tabs/hospitals.html"></div>
```

- [ ] **Step 3: Wire the module import + init in app.js (or similar entry)**

Find where other tab modules are imported and add:

```javascript
import { loadHospitalsTab } from './hospitals.js';
```

Find where tab init dispatches happen (search for `tab-` pattern) and add:

```javascript
if (name === 'hospitals') loadHospitalsTab();
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/js/app.js
git commit -m "feat: register hospitals tab in navigation"
```

---

### Task 11: Verify Full Flow

- [ ] **Step 1: Run Alembic migration**

```bash
alembic upgrade head
```

- [ ] **Step 2: Start the server**

```bash
python run.py
```

- [ ] **Step 3: Manual verification**
  1. Open the app in browser
  2. Click "Hospitals" tab in navigation
  3. Add a governorate (e.g., "Baghdad")
  4. Add a hospital type (e.g., "General Hospital")
  5. Add a hospital with governorate + type + address
  6. Verify hospital appears in list with governorate/type shown
  7. Edit the hospital, verify changes persist
  8. Delete the hospital, verify it's removed
  9. Toggle active/inactive, verify it works

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "feat: complete hospitals management feature"
```
