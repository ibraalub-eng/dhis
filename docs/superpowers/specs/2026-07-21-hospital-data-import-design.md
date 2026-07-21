# Import Hospital Reference Data from Table

## Objective
Import facility ownership, facility type, hospital type, and governorate data from a provided table into existing hospitals, and add any new hospitals from the table as inactive.

## Data Source
A table with columns: `organisationunitid`, `name`, `facility_ownership`, `facilitytype`, `hostype`, `orgunitlevel2`.

## Steps

### 1. Seed Reference Tables
Populate four reference tables with unique values extracted from the source data:

| Table | Values |
|-------|--------|
| `facility_ownerships` | حكومي, INGOs, NGOs, خاص |
| `facility_types` | مستشفيات |
| `hospital_types` | مستشفى تخصصي, مستشفى ميداني, مستشفى عام |
| `governorates` | محافظة غزة, محافظة خان يونس, محافظة الوسطى, محافظة الشمال |

Each entry created via the existing model (name + created_at).

### 2. Process Each Row
For each row in the source table:
- Match by `name` against `Hospital.name`
- **If found:** Update `organisation_unit_id`, `facility_ownership_id`, `facility_type_id`, `hospital_type_id`, `governorate_id`
- **If not found:** Create a new Hospital with all fields populated and `is_active=False`
- When `orgunitlevel2` is NULL, leave `governorate_id` as NULL

### 3. Handle Duplicates
The organisationunitid `13135` (مستشفى الخير) appears twice with different `hostype` values. Take only the first occurrence and ignore the duplicate.

## Implementation
A single Python script `scripts/import_hospital_data.py` that:
1. Runs inside the app context (uses `SessionLocal`, models)
2. Seeds reference tables (skip if value already exists)
3. Processes each row with match-by-name logic
4. Commits all changes in a single transaction
5. Outputs summary counts (created, updated, skipped)

## Rollback
Delete the script after execution. No migration needed — this is a one-time data import.
