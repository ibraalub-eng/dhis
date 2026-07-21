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
