# Hospitals Management — Design Spec

## Overview
Add dedicated hospital management interface with governorates and hospital types as reference data, linked to hospitals via foreign keys.

## Data Model

### New Tables

**governorates**
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, auto-increment |
| name | VARCHAR(255) | UNIQUE, NOT NULL |
| created_at | DATETIME | default utcnow |

**hospital_types**
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
| region | VARCHAR(100) | nullable, existing (kept for backward compat) |
| governorate_id | INTEGER | FK -> governorates.id, nullable, NEW |
| hospital_type_id | INTEGER | FK -> hospital_types.id, nullable, NEW |
| address | TEXT | nullable, NEW (optional detailed location) |
| is_active | BOOLEAN | default True (existing) |
| created_at | DATETIME | default utcnow (existing) |

Relationships:
- `governorate_id` -> `governorates.id` (SET NULL on delete)
- `hospital_type_id` -> `hospital_types.id` (SET NULL on delete)

## API Endpoints

### Governorates
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/governorates/ | List all governorates |
| POST | /api/governorates/ | Create governorate {name} |
| PUT | /api/governorates/{id} | Update governorate name |
| DELETE | /api/governorates/{id} | Delete governorate (fails if hospitals linked) |

### Hospital Types
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/hospital-types/ | List all types |
| POST | /api/hospital-types/ | Create type {name} |
| PUT | /api/hospital-types/{id} | Update type name |
| DELETE | /api/hospital-types/{id} | Delete type (fails if hospitals linked) |

### Hospitals (extended)
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/hospitals/ | Existing — now includes governorate_id, hospital_type_id, governorate_name, type_name |
| POST | /api/hospitals/ | NEW — create hospital {name, governorate_id, hospital_type_id, address} |
| PUT | /api/hospitals/{id} | NEW — update hospital fields |
| DELETE | /api/hospitals/{id} | NEW — delete hospital |
| PUT | /api/hospitals/{id}/toggle-active | Existing |

GET /hospitals/ response extended with:
```json
{
  "id": 1,
  "name": "Hospital A",
  "region": "...",
  "governorate_id": 5,
  "governorate_name": "Baghdad",
  "hospital_type_id": 2,
  "hospital_type_name": "General",
  "address": "Street 42, District 7",
  "is_active": true,
  "created_at": "..."
}
```

## UI: New "Hospitals" Tab

New tab in the main navigation bar after "AI Reports" (before Settings). Contains three sub-views managed via simple show/hide.

### View 1: Hospitals List (default)
- Table columns: Name, Governorate (dropdown name), Type (type name), Status (active/inactive), Actions
- Note: Old `region` field kept in DB for backward compat but not shown in new UI (governorate replaces it)
- Filter bar: Governorate dropdown + Type dropdown + search by name
- "Add Hospital" button -> modal with fields: name, governorate (dropdown), type (dropdown), address (textarea)
- Click "Edit" on row -> same modal pre-filled
- Click "Delete" -> confirmation dialog
- Toggle active/inactive inline (same as current Settings toggle)

### View 2: Governorates Management
- Table: Name, Created, Actions (Edit, Delete)
- "Add Governorate" button -> modal with name field
- Delete blocked if governorate has linked hospitals

### View 3: Hospital Types Management
- Table: Name, Created, Actions (Edit, Delete)
- "Add Type" button -> modal with name field
- Delete blocked if type has linked hospitals

### Navigation between views
Three buttons/tabs at top: "المستشفيات" | "المحافظات" | "أنواع المستشفيات"

### Hospital dropdowns across the app
All existing hospital `<select>` dropdowns across the app must now show **name** (same as before — no change), but the backend now includes governorate/type data for future use.

## Implementation Order
1. Database: Alembic migration for new tables + columns
2. Models: Governorate, HospitalType SQLAlchemy models + update Hospital model
3. Schemas: Pydantic models for new entities + update HospitalOut
4. API: governorates.py, hospital_types.py routers + extend hospitals.py
5. UI: hospitals.html tab + hospitals.js
6. Register new tab in main navigation (index.html)
7. Wire hospital dropdowns to use extended endpoint

## SQLAlchemy Cascade Rules
- Deleting governorate: SET NULL on hospital.governorate_id
- Deleting hospital_type: SET NULL on hospital.hospital_type_id
- Deleting hospital: CASCADE to related analysis data via existing relationships
