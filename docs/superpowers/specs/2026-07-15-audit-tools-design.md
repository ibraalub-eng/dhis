# Audit & Calculation Verification Tools

## Overview

New "Audit" tab in the HEALTH-ai application providing four verification tools:
1. **Calculation Steps** — step-by-step breakdown of every computed metric
2. **Benchmark Comparison** — hospital rates vs peer averages with statistical context
3. **Data Auditor** — raw inputs vs computed outputs, missing indicators, rule/outlier impact
4. **Audit Report** — comprehensive report that aggregates all above, downloadable as JSON/CSV

## Files

### Backend (new)
```
app/
  api/audit.py                    — APIRouter(prefix="/audit")
  engine/audit/
    __init__.py
    calculation_steps.py          — step-by-step for each calculation
    benchmark.py                  — cross-hospital benchmark comparisons
    data_auditor.py               — input/output integrity checks
    report_generator.py           — comprehensive audit report assembly
```

### Frontend (new)
```
static/
  tabs/audit.html                 — HTML structure for the Audit tab
  js/audit.js                     — all JavaScript logic
```

### Modified files
```
static/js/main.js                 — register new "audit" tab in tab system
static/index.html                 — add tab button and content container
app/main.py                       — register audit.router
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/audit/calculation-steps/{hospital_id}` | Step-by-step calculation breakdown |
| GET | `/audit/benchmark/{hospital_id}` | Cross-hospital benchmark comparison |
| GET | `/audit/data-auditor/{hospital_id}` | Data integrity audit |
| GET | `/audit/report/{hospital_id}` | Comprehensive audit report |

All support `?month=` query parameter.

## Section Details

### 1. Calculation Steps

Displays for each metric:
- **Formula** (e.g., `Numerator ÷ Denominator × 100`)
- **Raw inputs** (indicator codes, descriptions, values)
- **Intermediate values** (sums, rates before classification)
- **Final result** with classification/status
- **Thresholds applied** (for clinical rates)

Metrics covered:
- 7 Clinical Rates (CS Rate, MMR, NMR, Preterm, SMM, Stillbirth, NICU)
- Quality Score (4 components with weights)
- Confidence Score (5 signals with weights)
- Risk Profile (11 risk metrics)
- Morbidity Profile (SMM rate, MMR, component proportions)

### 2. Benchmark Comparison

For each of 7 tracked rates:
- Hospital value with visual bar
- Peer average, median, min/max range
- Percentage deviation from average
- Percentile rank
- Z-score vs peers
- Status indicator: 🟢 normal / 🟡 elevated / 🔴 critical

### 3. Data Auditor

Three sub-sections:
- **Completeness**: all required indicators with present/missing status
- **Rule Failure Impact**: each FAIL rule → effect on quality score (consistency component)
- **Anomaly Impact**: each outlier → outlier_penalty calculation → score reduction

### 4. Audit Report

Aggregates all three above sections into a single structured JSON response.
Download buttons: JSON, CSV.
Frontend renders the same data as a printable report view.

## Frontend Tab

- New tab `Audit` with red color (`#d32f2f`) to distinguish from analytics tabs
- Hospital select + Month select at top
- "Generate Audit" button
- Four collapsible sections below
- Each section loads on-demand when expanded (lazy fetch from API)
- Same tab-persistence pattern as other tabs (save/restore hospital+month selection)

## Data Sources

All calculations reuse existing engine functions:
- Clinical classifications: `app/engine/clinical/thresholds.py`
- Quality score: `app/engine/quality/scoring.py`
- Confidence: `app/engine/confidence.py`
- Risk profile: `app/engine/clinical/risk_profile.py`
- Morbidity profile: `app/engine/clinical/morbidity.py`
- Anomaly detection: `app/engine/anomaly/zscore.py`
- Benchmark comparison: `app/engine/anomaly/comparison.py`
- Rules: `app/engine/quality/rules.py`

No new calculation logic — only **presentation** of existing calculation steps with raw inputs shown.

## Verification Status

Each calculation step ends with:
- ✅ Verified (result matches expected formula)
- Or detailed discrepancy if mismatch found

## Future Extensions

- PDF export of Audit Report
- Scheduled audit reports (cron/background task)
- Multi-hospital comparison in benchmark section
