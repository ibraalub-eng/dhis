# Task 1 Report: Backend Models + Schemas

## Status: DONE

## What was implemented

### Models (`app/models.py`)
- **FacilityOwnership** model: `facility_ownerships` table with `id`, `name` (unique), `created_at`, and `hospitals` relationship
- **FacilityType** model: `facility_types` table with `id`, `name` (unique), `created_at`, and `hospitals` relationship
- **Hospital** model extended with:
  - `organisation_unit_id` (String(100), nullable)
  - `facility_ownership_id` (FK to `facility_ownerships.id`, ondelete SET NULL, nullable)
  - `facility_type_id` (FK to `facility_types.id`, ondelete SET NULL, nullable)
  - `facility_ownership` and `facility_type` relationships (back_populates)

### Schemas (`app/schemas.py`)
- **FacilityOwnershipBase**, **FacilityOwnershipCreate**, **FacilityOwnershipOut** schemas
- **FacilityTypeBase**, **FacilityTypeCreate**, **FacilityTypeOut** schemas
- **HospitalBase** extended with `organisation_unit_id`, `facility_ownership_id`, `facility_type_id` (all Optional)
- **HospitalOut** extended with `facility_ownership_name`, `facility_type_name` (both Optional[str])

## What was tested
- Import verification: `python -c "from app.models import FacilityOwnership, FacilityType; from app.schemas import FacilityOwnershipOut, FacilityTypeOut; print('OK')"` - **OK**
- Full test suite: **49 passed, 1 failed** (pre-existing Windows file-locking issue in `test_with_valid_file`, unrelated to changes)

## Files changed
- `app/models.py` (+23 lines)
- `app/schemas.py` (+32 lines)

## Self-review findings
- All new models follow the exact same pattern as existing Governorate/HospitalType models
- FK ondelete="SET NULL" is correct for optional reference data
- All imports work correctly
- No comments added (per code style)

## Commits
- `7a36ff7` - `feat: add FacilityOwnership, FacilityType models and schemas`
