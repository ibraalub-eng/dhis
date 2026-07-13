# HEALTH-ai Architecture Improvement Design

**Date**: 2026-07-13
**Status**: Draft — awaiting review
**Scope**: Backend refactoring, bug fixes, testing, database migrations

---

## 1. Bug Fixes

### 1.1 `app/engine/clinical.py` — Wrong variable in rate calculation
**Location**: Line 368
**Bug**: `(100 if "%" in str else 1)` — `str` is the built-in type, not a variable. Always evaluates to 100.
**Fix**: Replace `str` with the correct variable (`indicator` or `rate_name` depending on context).
**Impact**: Clinical rate percentage calculations are incorrect for all indicators.

### 1.2 `app/engine/quality_score.py` — Missing class prefix on Severity enum
**Location**: Line 61
**Bug**: `.HIGH` used instead of `Severity.HIGH` — causes `AttributeError`.
**Fix**: Already partially fixed in previous session (import corrected from `app.engine.rules` to `app.engine.quality`). Verify line 61 uses `Severity.HIGH`.
**Impact**: Quality score calculation crashes when HIGH severity rules are present.

### 1.3 Duplicate `calculate_quality_score` function
**Current**: Exists in both `engine/quality.py:584` and `engine/quality_score.py:5`.
**Fix**: Keep only the version in `quality_score.py`. Remove from `quality.py`. Update all imports to use `from app.engine.quality_score import calculate_quality_score`.
**Impact**: Eliminates confusion, ensures single source of truth.

### 1.4 Duplicated seeding logic
**Current**: `_seed_indicators()` and `_seed_rules()` in `main.py` duplicate `scripts/seed_indicators.py` and `scripts/seed_rules.py`.
**Fix**: Import seeding functions from `scripts/` module and call them in `main.py` lifespan. Remove duplicated code from `main.py`.
**Impact**: Reduces `main.py` by ~80 lines, single source of truth for seeding.

---

## 2. File Splitting — Engine Layer

### 2.1 `app/engine/clinical.py` → `app/engine/clinical/` package
```
app/engine/clinical/
├── __init__.py          # re-exports: run_clinical_analysis, generate_recommendations
├── thresholds.py        # 15 WHO/FIGO thresholds, classify_rate, get_threshold
├── risk_profile.py      # compute_risk_profile, risk metrics, severity calculation
├── morbidity.py         # compute_morbidity_profile, mortality signals
├── recommendations.py   # recommendation engine, registered rules, action items
└── summary.py           # generate_clinical_summary, key findings, overview
```
**Dependencies**: `thresholds.py` (no internal deps), `risk_profile.py` → `thresholds.py`, `morbidity.py` → `thresholds.py`, `recommendations.py` → `thresholds.py, risk_profile.py`, `summary.py` → all above.

### 2.2 `app/engine/quality.py` → `app/engine/quality/` package
```
app/engine/quality/
├── __init__.py          # re-exports: run_quality_analysis, ALL_RULES, dispatch_rule
├── rules.py             # ALL_RULES, dispatch_rule, rule execution, RuleResult, Severity
├── scoring.py           # calculate_quality_score (moved from quality_score.py)
└── definitions.py       # RATE_DEFINITIONS, indicator mappings, unit configurations
```
**Dependencies**: `rules.py` (no internal deps), `definitions.py` (no internal deps), `scoring.py` → `rules.py`, `__init__.py` → all above.

### 2.3 `app/engine/anomaly_trends.py` → `app/engine/anomaly/` package
```
app/engine/anomaly/
├── __init__.py          # re-exports: detect_anomalies, analyze_trends
├── zscore.py            # cross-hospital z-score anomaly detection
├── trends.py            # linear regression, trend analysis, consecutive months
└── comparison.py        # hospital-to-hospital comparison logic
```
**Dependencies**: `zscore.py` (no internal deps), `trends.py` (no internal deps), `comparison.py` → `zscore.py`.

### 2.4 `app/plugins/ai.py` → `app/plugins/ai/` package
```
app/plugins/ai/
├── __init__.py          # re-exports: get_ai_provider, generate_recommendations
├── providers.py         # OpenAI, Anthropic, local provider classes
├── prompts.py           # prompt builders, templates, formatting
└── cache.py             # AI response caching with TTL
```

### 2.5 `app/api/hospitals.py` → split into focused routers
```
app/api/
├── hospitals.py         # Hospital CRUD only (~150 lines)
├── indicator_config.py  # Indicator enable/disable, bulk toggle (~200 lines)
└── tree_config.py       # Tree configuration, reparent, save (~200 lines)
```

---

## 3. Database Migrations — Alembic

### 3.1 Setup
- Initialize Alembic: `alembic init alembic`
- Configure `alembic.ini` for SQLite (`sqlite:///data/health_ai.db`)
- Configure `alembic/env.py` to import models from `app.models`

### 3.2 Migration Strategy
- Generate initial migration from current schema: `alembic revision --autogenerate -m "initial schema"`
- Review generated migration SQL against `_migrate_schema()` output
- Replace `_migrate_schema()` call in `database.py` with `alembic upgrade head`
- Keep `init_db()` for engine/session setup only (no schema creation)

### 3.3 Migration Files (expected)
1. `initial_schema` — all tables, indexes, constraints
2. `seed_indicators` — indicator tree data (if not in scripts)
3. `seed_rules` — rule definitions (if not in scripts)

### 3.4 Startup Flow Change
**Before**: `init_db()` → `_migrate_schema()` → `_seed_indicators()` → `_seed_rules()`
**After**: `init_db()` → `alembic upgrade head` → seed from scripts

---

## 4. Testing Improvements

### 4.1 Backend Unit Tests (new files)
| File | Tests |
|---|---|
| `tests/test_pipeline.py` | `run_full_analysis()` orchestrator, caching, error handling |
| `tests/test_confidence.py` | All 5 confidence signals, weight calculation, missing data |
| `tests/test_root_cause.py` | Root cause analysis with various data patterns |
| `tests/test_quality_score.py` | Score calculation, edge cases, severity weighting |
| `tests/test_api_hospitals.py` | CRUD endpoints, filtering, indicator config |
| `tests/test_api_rules.py` | Rule CRUD, toggle, reorder |
| `tests/test_api_config.py` | Settings API, AI config, control settings |
| `tests/test_api_file_ops.py` | Multi-file upload, saved files, analyze |

### 4.2 Frontend Tests (new)
| File | Tests |
|---|---|
| `tests/js/test_api.js` | apiGet caching, error handling, API() resolution |
| `tests/js/test_main.js` | switchTab, _initTab, _saveUIState, _restoreUIState |
| `tests/js/test_validation.js` | loadClinical, renderClinical, initClinical |

### 4.3 Coverage
- Target: 80%+ backend coverage
- Add `pytest-cov` to requirements
- Configure `pyproject.toml` or `setup.cfg` for coverage reporting

---

## 5. Additional Improvements

### 5.1 Remove orphaned files
- `app/parsers/` directory (already removed)
- Root-level `health_ai.db` (already removed)
- `app/data/uploads/` (already removed)

### 5.2 Code quality
- Add `ruff` or `flake8` for linting
- Add `mypy` for type checking
- Add pre-commit hooks

### 5.3 Error handling
- Standardize error responses (all endpoints use `HTTPException` with consistent format)
- Add request validation middleware for Query params (YYYY-MM format)
- Add global exception handler for uncaught errors

---

## Implementation Order

1. **Bug fixes** (Section 1) — immediate, low risk
2. **File splitting** (Section 2) — one package at a time, test after each
3. **Alembic migrations** (Section 3) — after file splitting is stable
4. **Testing** (Section 4) — parallel with file splitting, test new code as it's written
5. **Additional improvements** (Section 5) — after core refactoring is complete

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking existing API | Low | High | Run full test suite after each change |
| Migration data loss | Low | Critical | Backup DB before running migrations |
| Import cycles after splitting | Medium | Medium | Plan dependency graph before splitting |
| Tests slow down CI | Medium | Low | Use fixtures efficiently, mock where possible |
