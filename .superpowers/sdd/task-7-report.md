# Task 7 Report: Add Alembic Migrations

## Summary

Replaced the raw SQL `_migrate_schema()` function in `app/database.py` with Alembic migrations for proper schema versioning.

## Changes Made

### 1. `requirements.txt`
- Added `alembic` dependency

### 2. Alembic Initialization
- Ran `alembic init alembic` to create migration infrastructure
- Created `alembic/` directory with `env.py`, `script.py.mako`, and `versions/`
- Created `alembic.ini` configuration file

### 3. `alembic.ini`
- Configured `sqlalchemy.url = sqlite:///data/health_ai.db`

### 4. `alembic/env.py`
- Added `sys.path` manipulation to import from project root
- Imported `Base` from `app.database` and all models from `app.models`
- Set `target_metadata = Base.metadata` for autogenerate support
- Added `render_as_batch=True` for SQLite compatibility

### 5. Initial Migration
- Generated `alembic/versions/f25afbb94bc7_initial_schema.py` via `alembic revision --autogenerate`
- Contains CREATE TABLE statements for all 14 tables:
  - `hospitals`, `indicators`, `rules`, `system_settings`
  - `indicator_values`, `hospital_indicator_config`
  - `validation_results`, `anomaly_results`, `quality_scores`, `clinical_insights`
  - `confidence_scores`, `confidence_weights`, `app_config`, `analysis_cache`
- Includes all indexes and constraints defined in SQLAlchemy models

### 6. `app/database.py`
- Removed entire `_migrate_schema()` function (~290 lines of raw SQL)
- Removed `text` import from sqlalchemy (no longer needed)
- Kept `init_db()` with `Base.metadata.create_all()` for test compatibility
- Kept `get_db()` unchanged

### 7. `app/main.py`
- Added `alembic.config.Config` and `alembic.command` imports
- Added `run_alembic_upgrade()` function that:
  - Loads `alembic.ini` config
  - Overrides `sqlalchemy.url` with runtime `DATABASE_URL`
  - Runs `command.upgrade(cfg, "head")`
- Updated `lifespan()` to call `run_alembic_upgrade()` after `init_db()`

## Test Results

All 19 integration tests passed:
```
====================== 19 passed, 1981 warnings in 3.82s ======================
```

## Notes

- Tests continue to use `Base.metadata.create_all()` directly via conftest.py fixture (in-memory SQLite), which is unaffected by Alembic changes
- Production startup now runs both `Base.metadata.create_all()` and `alembic upgrade head` — the former creates tables if missing, the latter tracks schema version for future migrations
- Future schema changes should be made to models and generated via `alembic revision --autogenerate`
