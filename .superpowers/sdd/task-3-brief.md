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
