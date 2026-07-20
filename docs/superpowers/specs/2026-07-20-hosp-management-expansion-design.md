# Hospital Management Expansion — Design Spec

## Overview
Add `organisation_unit_id`, `facility_ownership_id`, and `facility_type_id` fields to the Hospital model, with Facility Ownerships and Facility Types as managed reference data (same pattern as Governorates and Hospital Types).

## Data Model

### New Tables

**facility_ownerships**
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, auto-increment |
| name | VARCHAR(255) | UNIQUE, NOT NULL |
| created_at | DATETIME | default utcnow |

**facility_types**
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, auto-increment |
| name | VARCHAR(255) | UNIQUE, NOT NULL |
| created_at | DATETIME | default utcnow |

### Modified Table: hospitals

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK (existing) |
| name | VARCHAR(255) | UNIQUE, NOT NULL (existing) |
| region | VARCHAR(100) | nullable (existing) |
| organisation_unit_id | VARCHAR(100) | nullable, NEW (DHIS2 external ID) |
| governorate_id | INTEGER | FK -> governorates.id, nullable (existing) |
| facility_ownership_id | INTEGER | FK -> facility_ownerships.id, nullable, NEW |
| facility_type_id | INTEGER | FK -> facility_types.id, nullable, NEW |
| hospital_type_id | INTEGER | FK -> hospital_types.id, nullable (existing) |
| address | TEXT | nullable (existing) |
| is_active | BOOLEAN | default True (existing) |
| created_at | DATETIME | default utcnow (existing) |

Relationships:
- `facility_ownership_id` -> `facility_ownerships.id` (SET NULL on delete)
- `facility_type_id` -> `facility_types.id` (SET NULL on delete)

## API Endpoints

### Facility Ownerships (same pattern as `/api/governorates/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/facility-ownerships/ | List all ownerships |
| POST | /api/facility-ownerships/ | Create ownership {name} |
| PUT | /api/facility-ownerships/{id} | Update ownership name |
| DELETE | /api/facility-ownerships/{id} | Delete ownership (fails if hospitals linked) |

### Facility Types (same pattern as `/api/hospital-types/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/facility-types/ | List all types |
| POST | /api/facility-types/ | Create type {name} |
| PUT | /api/facility-types/{id} | Update type name |
| DELETE | /api/facility-types/{id} | Delete type (fails if hospitals linked) |

### Hospitals (extended)
- `GET /api/hospitals/` — now includes `organisation_unit_id`, `facility_ownership_id`, `facility_type_id`, `facility_ownership_name`, `facility_type_name`
- `POST /api/hospitals/` — accepts new fields
- `PUT /api/hospitals/{id}` — accepts new fields

## Pydantic Schemas

**HospitalBase** extended:
- `organisation_unit_id: Optional[str]`
- `facility_ownership_id: Optional[int]`
- `facility_type_id: Optional[int]`

**HospitalOut** extended:
- `facility_ownership_name: Optional[str]`
- `facility_type_name: Optional[str]`

## Frontend: Hospitals Tab (hospitals.html + hospitals.js)

### Table columns (new)
- Add "OrgUnit ID" column
- Add "Ownership" column (renders `facility_ownership_name`)
- Add "Facility Type" column (renders `facility_type_name`)

### Add/Edit modal (new fields)
- Organisation Unit ID: text input
- Facility Ownership: dropdown (from `/api/facility-ownerships/`)
- Facility Type: dropdown (from `/api/facility-types/`)

### New subtabs: Facility Ownerships + Facility Types
Add two more subtab buttons to the existing 3-tab layout:
- "Facility Ownerships" — same CRUD pattern as Governorates
- "Facility Types" — same CRUD pattern as Hospital Types

## SQLite Schema Changes
Schema change via `ALTER TABLE ADD COLUMN`:
```sql
ALTER TABLE hospitals ADD COLUMN organisation_unit_id VARCHAR(100);
ALTER TABLE hospitals ADD COLUMN facility_ownership_id INTEGER REFERENCES facility_ownerships(id);
ALTER TABLE hospitals ADD COLUMN facility_type_id INTEGER REFERENCES facility_types(id);
```

## Seed Data
Pre-populate facility_ownerships and facility_types from the provided DHIS2 table:

**Facility Ownerships:** حكومي, NGOs, INGOs, خاص

**Facility Types:** مستشفيات (only value observed in source data)

## SQLAlchemy Cascade Rules
- Deleting facility_ownership: SET NULL on hospital.facility_ownership_id
- Deleting facility_type: SET NULL on hospital.facility_type_id
- Deleting hospital: CASCADE to related analysis data via existing relationships

## Implementation Order
1. Models: FacilityOwnership, FacilityType + update Hospital model
2. Schemas: Pydantic models + update HospitalBase/HospitalOut
3. API: facility_ownerships.py, facility_types.py routers + extend hospitals.py
4. DB schema: seed data + ALTER TABLE
5. Frontend: extend hospitals.html/hospitals.js with new fields and subtabs
6. Register new subtab filters in hospitals.js
7. Tests: new endpoints + extended hospital CRUD
