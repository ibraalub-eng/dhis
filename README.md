# HEALTH-ai

SRMNH Data Quality System — an intelligent platform for analyzing Sexual, Reproductive, Maternal and Newborn Health (SRMNH) indicator data quality.

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Pandas, NumPy, scikit-learn
- **Frontend:** Vanilla JavaScript SPA, Bootstrap, Chart.js, Plotly.js
- **Database:** SQLite (development), PostgreSQL (production)

## Frontend Charting Libraries

| Library | Usage | Vendor File |
|---------|-------|-------------|
| **Chart.js v4.x** | Root cause timeline chart (line + CI band) | `static/vendor/chart.umd.min.js` |
| **Plotly.js** | Dashboard charts, Smart Analytics, comparative analysis, and other visualizations | `static/vendor/plotly.min.js` |

Chart.js utilities (color palette, CI band plugin) are in `static/js/chart-utils.js`.

## Migration Note

As of August 2026, the root cause analysis timeline chart was migrated from Plotly.js to Chart.js for improved performance and a lighter footprint. Plotly.js remains in use for all other charting features (43+ calls across the codebase). See `docs/superpowers/specs/2026-08-17-root-cause-chart-migration-design.md` for details.

## Project Structure

```
app/                  — FastAPI backend (API, engine, models)
static/               — Frontend assets (JS, CSS, vendor libs)
  vendor/             — Chart.js and Plotly.js libraries
  js/chart-utils.js   — Chart.js configuration and CI band plugin
  tabs/               — SPA tab templates
docs/                 — Documentation
tests/                — Test suite
```

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Start development server
python -m uvicorn app.main:app --reload
```

## Documentation

- `docs/PROJECT_DOCUMENTATION.md` — Full Arabic documentation (workflow, UI screens, KPIs, scoring)
- `docs/superpowers/plans/` — Design specs and implementation plans
- `docs/superpowers/reports/` — Task completion reports

## Repository Agents (`.agents/`)

Project-specific agent definitions that encode this repo's hard-won conventions. Point your coding agent at the relevant one before starting work. Definitions are linted by `scripts/check_agents.py` (a dedicated CI job and a pytest wrapper in `tests/test_agent_definitions.py`), so a malformed frontmatter fails both CI and the local suite:

| Agent | Use when |
|-------|----------|
| **`test-fixer`** | Fixing failing pytest runs — fixes code first, never deletes/weaken tests, knows the cache-test flake pattern |
| **`migration-guard`** | Changing `app/models.py` or Alembic — drift audit, hand-written migrations, up→down→up chain on a scratch DB |
| **`i18n-auditor`** | Adding/changing UI strings — sweeps `data-i18n` keys and `__()` usage for complete English + Arabic coverage |
| **`ui-debugger`** | Reproducing reported screen bugs live (autofill junk, silent API failures, module-load failures, render crashes) and applying the layered fixes this repo prefers |
| **`feature-builder`** | Implementing the approved Rules Manager plan (drawer, test-with-data, expression preview, history, export/import) with the exact repo patterns |
| **`release-checker`** | Preparing commits/pushes — full verification gauntlet (JS syntax, imports, scoped + full suite, live smoke) and clean scoped commits |
