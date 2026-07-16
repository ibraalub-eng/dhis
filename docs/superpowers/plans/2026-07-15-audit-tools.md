# Audit & Calculation Verification Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Audit" tab with 4 sections showing step-by-step calculation details, benchmark comparisons, data integrity checks, and a comprehensive audit report.

**Architecture:** New backend package `app/engine/audit/` extracts and formats existing calculation results; new `app/api/audit.py` exposes 4 endpoints; new frontend files `static/js/audit.js` + `static/tabs/audit.html` render the data.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, vanilla JS (no framework)

## Global Constraints

- All API responses are JSON
- Frontend uses same patterns as existing tabs (tab registration, lazy loading, hospital/month selectors)
- No new calculation logic — only present existing computed data with raw inputs shown

---

### Task 1: Backend engine package + calculation steps

**Files:**
- Create: `app/engine/audit/__init__.py`
- Create: `app/engine/audit/calculation_steps.py`

**Interfaces:**
- Consumes: `app/engine/clinical/thresholds.py` (compute_all_classifications, CLINICAL_THRESHOLDS), `app/engine/quality/scoring.py` (calculate_quality_score), `app/engine/confidence.py` (calculate_confidence), `app/engine/clinical/risk_profile.py` (compute_risk_profile), `app/engine/clinical/morbidity.py` (compute_morbidity_profile), `app/models` (QualityScore, ConfidenceScore, ValidationResult)
- Produces: `get_calculation_steps(db, hospital_id, month) -> dict` — structured breakdown of all calculations

- [ ] **Step 1: Create `app/engine/audit/__init__.py`**

```python
from .calculation_steps import get_calculation_steps
from .benchmark import get_benchmark
from .data_auditor import get_data_audit
from .report_generator import generate_audit_report

__all__ = ["get_calculation_steps", "get_benchmark", "get_data_audit", "generate_audit_report"]
```

- [ ] **Step 2: Create `app/engine/audit/calculation_steps.py`**

```python
import json
from sqlalchemy.orm import Session
from app.models import QualityScore, ConfidenceScore, ValidationResult, IndicatorValue, Indicator
from app.engine.clinical.thresholds import compute_all_classifications, CLINICAL_THRESHOLDS
from app.engine.clinical.risk_profile import compute_risk_profile
from app.engine.clinical.morbidity import compute_morbidity_profile
from app.engine.quality.scoring import calculate_quality_score
from app.engine.confidence import calculate_confidence
from app.engine.pipeline import get_enabled_values_for_hospital_month, get_all_hospital_data_for_month, get_historical_months

def get_calculation_steps(db: Session, hospital_id: int, month: str) -> dict:
    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not values:
        return {"error": f"No data for hospital {hospital_id} / {month}"}

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    hospital_name = hospital.name if hospital else str(hospital_id)

    # Clinical classifications
    classifications = compute_all_classifications(values)
    cls_steps = []
    for c in classifications:
        threshold = None
        for t in CLINICAL_THRESHOLDS:
            if t.indicator_code == c.indicator_code:
                threshold = t
                break
        step = {
            "indicator_code": c.indicator_code,
            "rate_name": c.rate_name,
            "formula": _rate_formula(c.indicator_code, threshold),
            "numerator_codes": list(threshold.numerator_codes) if threshold else [],
            "denominator_code": threshold.denominator_code if threshold else None,
            "numerator_value": sum(values.get(c, 0) for c in (threshold.numerator_codes if threshold else [])),
            "denominator_value": values.get(threshold.denominator_code, 0) if threshold else 0,
            "unit": c.unit,
            "raw_rate": c.value,
            "classification": c.classification,
            "label": c.label,
            "color": c.color,
            "narrative": c.narrative,
        }
        cls_steps.append(step)

    # Quality score
    all_hospital_data = get_all_hospital_data_for_month(db, month)
    historical = get_historical_months(db, hospital_id, month)
    ctx = _build_context(values, hospital_name, month, all_hospital_data, historical)
    from app.engine.quality.rules import run_all_rules
    rule_results = run_all_rules(ctx)
    qs_result = calculate_quality_score(rule_results, values, list(values.keys()), [])
    quality_score_steps = {
        "components": [
            {
                "name": "Rule Compliance",
                "weight": 0.35,
                "value": qs_result.get("rule_compliance", 0),
                "weighted": round(qs_result.get("rule_compliance", 0) * 0.35, 4),
                "formula": "passed_rules / total_rules",
                "detail": f"{qs_result.get('rule_compliance_pass', 0)}/{qs_result.get('rule_compliance_total', 0)} rules passed"
            },
            {
                "name": "Completeness",
                "weight": 0.25,
                "value": qs_result.get("completeness", 0),
                "weighted": round(qs_result.get("completeness", 0) * 0.25, 4),
                "formula": "filled_indicators / active_indicators",
                "detail": f"{qs_result.get('completeness_filled', 0)}/{qs_result.get('completeness_total', 0)} indicators"
            },
            {
                "name": "Consistency",
                "weight": 0.25,
                "value": qs_result.get("consistency", 0),
                "weighted": round(qs_result.get("consistency", 0) * 0.25, 4),
                "formula": "1.0 - (weighted_fail / total_weight)",
            },
            {
                "name": "Outlier Penalty (inverted)",
                "weight": 0.15,
                "value": 1 - qs_result.get("outlier_penalty", 0),
                "weighted": round((1 - qs_result.get("outlier_penalty", 0)) * 0.15, 4),
                "formula": "1 - min(1.0, (outliers / total) * multiplier)",
            },
        ],
        "final_score": qs_result.get("score", 0),
    }

    # Confidence
    all_hosp_rates = _compute_hospital_rates(db, month)
    all_hospitals_raw = _get_all_hospitals_confidence_data(db, month)
    confidence = calculate_confidence(values, rule_results, historical, all_hospitals_raw, hospital_name, month)
    conf = confidence or {}
    signals = conf.get("indicators_data", [])
    conf_steps = {
        "overall": conf.get("overall_confidence"),
        "level": conf.get("level"),
        "signal_weights": {"rule_compliance": 0.55, "historical": 0.10, "cross_hospital": 0.10, "trend": 0.10, "completeness": 0.15},
    }

    # Risk profile
    risk = compute_risk_profile(values, hospital_name, month)
    risk_steps = []
    for m in (risk.metrics if risk else []):
        risk_steps.append({
            "metric_name": m.metric_name,
            "value": m.value,
            "unit": m.unit,
            "numerator": m.numerator,
            "denominator": m.denominator,
            "interpretation": m.interpretation,
            "severity": m.severity,
            "formula": f"{m.metric_name} = {m.numerator} / {m.denominator} * 100"
        })

    # Morbidity profile
    morb = compute_morbidity_profile(values, hospital_name, month)
    morb_steps = []
    for m in (morb.metrics if morb else []):
        morb_steps.append({
            "metric_name": m.metric_name,
            "value": m.value,
            "unit": m.unit,
            "numerator": m.numerator,
            "denominator": m.denominator,
            "interpretation": m.interpretation,
            "severity": m.severity,
        })

    return {
        "hospital": hospital_name,
        "month": month,
        "classifications": cls_steps,
        "quality_score": quality_score_steps,
        "confidence": conf_steps,
        "risk_profile": {"metrics": risk_steps, "overall_risk_level": risk.overall_risk_level if risk else None},
        "morbidity_profile": {"metrics": morb_steps, "total_smm": morb.total_smm if morb else 0, "maternal_deaths": morb.maternal_deaths if morb else 0},
    }


def _rate_formula(code, threshold):
    if not threshold:
        return ""
    num = " + ".join(threshold.numerator_codes) if len(threshold.numerator_codes) > 1 else threshold.numerator_codes[0]
    den = threshold.denominator_code
    mult = "100" if threshold.unit == "%" else "1000" if "1,000" in threshold.unit else "100000"
    return f"({num}) / ({den}) × {mult}"


def _build_context(values, hospital_name, month, all_hospital_data, historical):
    from app.engine.quality.rules import ValidationContext
    return ValidationContext(values, hospital_name, month, all_hospital_data, historical, set())


def _compute_hospital_rates(db, month):
    from app.engine.anomaly.zscore import RATE_DEFINITIONS, compute_rate
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    result = {}
    for h in hospitals:
        vals = get_enabled_values_for_hospital_month(db, h.id, month)
        if vals:
            result[h.name] = vals
    return result


def _get_all_hospitals_confidence_data(db, month):
    from app.models import IndicatorValue, Hospital
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    data = {}
    for h in hospitals:
        vals = get_enabled_values_for_hospital_month(db, h.id, month)
        if vals:
            data[h.name] = vals
    return data
```

- [ ] **Step 3: Verify Python syntax**

Run: `python -c "import py_compile; py_compile.compile('app/engine/audit/__init__.py', doraise=True); py_compile.compile('app/engine/audit/calculation_steps.py', doraise=True)"`
Expected: no output (success)

- [ ] **Step 4: Commit**

```bash
git add app/engine/audit/
git commit -m "feat: add audit engine package with calculation steps"
```

---

### Task 2: Backend benchmark + data_auditor

**Files:**
- Create: `app/engine/audit/benchmark.py`
- Create: `app/engine/audit/data_auditor.py`

**Interfaces:**
- Consumes: `app/engine/anomaly/zscore.py` (RATE_DEFINITIONS, compute_rate), `app/engine/anomaly/comparison.py` (compare_hospitals), `app/models` (IndicatorValue, ValidationResult, QualityScore, AnomalyResult, Hospital)
- Produces: `get_benchmark(db, hospital_id, month) -> dict`, `get_data_audit(db, hospital_id, month) -> dict`

- [ ] **Step 1: Create `app/engine/audit/benchmark.py`**

```python
import numpy as np
from sqlalchemy.orm import Session
from app.models import Hospital, IndicatorValue, Indicator
from app.engine.anomaly.zscore import RATE_DEFINITIONS, compute_rate
from app.engine.pipeline import get_enabled_values_for_hospital_month

def get_benchmark(db: Session, hospital_id: int, month: str) -> dict:
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()
    target_hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not target_hospital:
        return {"error": "Hospital not found"}

    target_vals = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not target_vals:
        return {"error": f"No data for {target_hospital.name} / {month}"}

    all_rates = {}  # {hospital_name: {rate_name: rate_value}}
    for h in hospitals:
        vals = get_enabled_values_for_hospital_month(db, h.id, month)
        if not vals:
            continue
        rates = {}
        for rd in RATE_DEFINITIONS:
            num = sum(vals.get(c, 0) for c in rd["numerator"])
            den = vals.get(rd["denominator"], 0)
            if den:
                rates[rd["name"]] = round((num / den) * (100 if rd.get("unit") == "%" else 1000 if "1,000" in rd.get("unit", "") else 100000), 2)
        if rates:
            all_rates[h.name] = rates

    comparisons = {}
    target_rates = all_rates.get(target_hospital.name, {})
    for rname in target_rates:
        peers = [v[rname] for hname, v in all_rates.items() if rname in v and hname != target_hospital.name]
        if not peers:
            continue
        avg = round(np.mean(peers), 2)
        med = round(np.median(peers), 2)
        std = np.std(peers, ddof=1) if len(peers) > 1 else 0
        tval = target_rates[rname]
        z = round((tval - avg) / std, 2) if std > 0 else 0
        pct_dev = round(((tval - avg) / avg) * 100, 1) if avg else 0
        percentile = round(sum(1 for p in peers if p <= tval) / len(peers) * 100, 0) if peers else 50
        status = "critical" if abs(z) >= 3 else ("high" if abs(z) >= 2 else ("elevated" if abs(z) >= 1.5 else "normal"))

        comparisons[rname] = {
            "hospital_value": tval,
            "peer_average": avg,
            "peer_median": med,
            "peer_min": round(min(peers), 2),
            "peer_max": round(max(peers), 2),
            "peer_count": len(peers),
            "z_score": z,
            "percent_deviation": pct_dev,
            "percentile": percentile,
            "status": status,
        }

    return {
        "hospital": target_hospital.name,
        "month": month,
        "comparisons": comparisons,
    }
```

- [ ] **Step 2: Create `app/engine/audit/data_auditor.py`**

```python
import json
from sqlalchemy.orm import Session
from app.models import Hospital, IndicatorValue, Indicator, ValidationResult, QualityScore, AnomalyResult, HospitalIndicatorConfig

def get_data_audit(db: Session, hospital_id: int, month: str) -> dict:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        return {"error": "Hospital not found"}

    # All indicators defined in the system
    all_indicators = db.query(Indicator).order_by(Indicator.code).all()
    # Values present for this hospital/month
    values_q = db.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hospital_id,
        IndicatorValue.month == month,
    ).all()
    present_codes = {v.indicator_id for v in values_q}

    completeness = []
    missing_count = 0
    present_count = 0
    for ind in all_indicators:
        val_row = next((v for v in values_q if v.indicator_id == ind.id), None)
        is_present = val_row is not None and val_row.value is not None
        if is_present:
            present_count += 1
        else:
            missing_count += 1
        completeness.append({
            "indicator_code": ind.code,
            "indicator_name": ind.name,
            "value": val_row.value if val_row else None,
            "status": "present" if is_present else "missing",
        })

    # Rule failures with impact analysis
    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    rules = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
        ValidationResult.status == "FAIL",
    ).all()
    rule_impact = []
    for r in rules:
        sev_weight = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(r.severity, 0)
        rule_impact.append({
            "rule_code": r.rule_code,
            "description": r.rule_description,
            "severity": r.severity,
            "severity_weight": sev_weight,
            "details": r.details or "",
        })

    # Confidence data
    from app.models import ConfidenceScore
    conf = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    conf_data = None
    if conf:
        conf_data = {
            "overall_confidence": conf.overall_confidence,
            "level": conf.level,
            "indicator_count": conf.indicator_count,
            "by_level": {
                "high": conf.high_count,
                "medium": conf.medium_count,
                "low": conf.low_count,
                "critical": conf.critical_count,
            },
        }

    # Anomaly impact
    outliers = db.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
        AnomalyResult.is_outlier.is_(True),
    ).all()
    outlier_details = []
    for o in outliers:
        outlier_details.append({
            "indicator_code": o.indicator_code,
            "rate_name": o.rate_name,
            "value": o.value,
            "benchmark": o.benchmark,
            "z_score": o.z_score,
        })

    # Quality score breakdown
    qs_breakdown = None
    if qs:
        total_weight = 0.35 + 0.25 + 0.25 + 0.15
        rc_weighted = (qs.rule_compliance or 0) * 0.35
        comp_weighted = (qs.completeness or 0) * 0.25
        cons_weighted = (qs.consistency or 0) * 0.25
        op_weighted = (1 - (qs.outlier_penalty or 0)) * 0.15
        qs_breakdown = {
            "score": qs.score,
            "components": [
                {"name": "Rule Compliance", "raw": qs.rule_compliance, "weight": 0.35, "weighted": round(rc_weighted, 4), "contribution_pct": round(rc_weighted / (total_weight if total_weight else 1) * 100, 1)},
                {"name": "Completeness", "raw": qs.completeness, "weight": 0.25, "weighted": round(comp_weighted, 4), "contribution_pct": round(comp_weighted / (total_weight if total_weight else 1) * 100, 1)},
                {"name": "Consistency", "raw": qs.consistency, "weight": 0.25, "weighted": round(cons_weighted, 4), "contribution_pct": round(cons_weighted / (total_weight if total_weight else 1) * 100, 1)},
                {"name": "Outlier (inverted)", "raw": 1 - (qs.outlier_penalty or 0), "weight": 0.15, "weighted": round(op_weighted, 4), "contribution_pct": round(op_weighted / (total_weight if total_weight else 1) * 100, 1)},
            ],
        }

    return {
        "hospital": hospital.name,
        "month": month,
        "completeness": {
            "total": len(all_indicators),
            "present": present_count,
            "missing": missing_count,
            "indicators": completeness,
        },
        "rule_failures": {
            "total": len(rule_impact),
            "items": rule_impact,
        },
        "quality_score": qs_breakdown,
        "confidence": conf_data,
        "outliers": {
            "total": len(outlier_details),
            "items": outlier_details,
        },
    }
```

- [ ] **Step 3: Create `app/engine/audit/report_generator.py`**

```python
from sqlalchemy.orm import Session
from .calculation_steps import get_calculation_steps
from .benchmark import get_benchmark
from .data_auditor import get_data_audit

def generate_audit_report(db: Session, hospital_id: int, month: str) -> dict:
    steps = get_calculation_steps(db, hospital_id, month)
    if "error" in steps:
        return steps
    bench = get_benchmark(db, hospital_id, month)
    if "error" in bench:
        bench = {"error": bench["error"]}
    audit = get_data_audit(db, hospital_id, month)
    if "error" in audit:
        audit = {"error": audit["error"]}

    return {
        "hospital": steps.get("hospital"),
        "month": steps.get("month"),
        "calculation_steps": steps,
        "benchmark_comparison": bench,
        "data_auditor": audit,
        "verification": _verify_calculations(steps, audit),
    }


def _verify_calculations(steps, audit):
    checks = []
    qs_steps = steps.get("quality_score", {})
    qs_audit = audit.get("quality_score", {})
    if qs_steps.get("final_score") and qs_audit.get("score"):
        match = abs(qs_steps["final_score"] - qs_audit["score"]) < 0.01
        checks.append({
            "check": "Quality Score Consistency",
            "expected": qs_steps.get("final_score"),
            "found": qs_audit.get("score"),
            "status": "verified" if match else "mismatch",
        })
    return {"checks": checks, "all_passed": all(c["status"] == "verified" for c in checks)}
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('app/engine/audit/benchmark.py', doraise=True); py_compile.compile('app/engine/audit/data_auditor.py', doraise=True); py_compile.compile('app/engine/audit/report_generator.py', doraise=True)"`
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/
git commit -m "feat: add benchmark, data auditor, and report generator"
```

---

### Task 3: API endpoints

**Files:**
- Create: `app/api/audit.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `app/engine/audit` (get_calculation_steps, get_benchmark, get_data_audit, generate_audit_report)
- Produces: 4 GET endpoints with JSON responses

- [ ] **Step 1: Create `app/api/audit.py`**

```python
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital
from app.engine.audit import get_calculation_steps, get_benchmark, get_data_audit, generate_audit_report

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/calculation-steps/{hospital_id}")
def api_calculation_steps(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_calculation_steps(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/benchmark/{hospital_id}")
def api_benchmark(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_benchmark(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/data-auditor/{hospital_id}")
def api_data_auditor(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = get_data_audit(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/report/{hospital_id}")
def api_report(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active.is_(True)).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    result = generate_audit_report(db, hospital_id, month)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
```

- [ ] **Step 2: Register router in `app/main.py`**

Find the line where other routers are registered (e.g., `app.include_router(dashboard.router)`) and add after it:
```python
from app.api import audit as audit_api
app.include_router(audit_api.router)
```

- [ ] **Step 3: Verify and test**

Run: `python -c "import py_compile; py_compile.compile('app/api/audit.py', doraise=True)"`
Expected: no output

Start server and verify endpoint responds:
```bash
# Start server, then:
curl -s "http://127.0.0.1:8000/audit/calculation-steps/1?month=2026-03" | head -c 200
```
Expected: JSON response with classification data

- [ ] **Step 4: Commit**

```bash
git add app/api/audit.py app/main.py
git commit -m "feat: add audit API endpoints"
```

---

### Task 4: Frontend — audit.html + audit.js

**Files:**
- Create: `static/js/audit.js`
- Create: `static/tabs/audit.html`

**Interfaces:**
- Consumes: API endpoints from Task 3
- Produces: Rendered HTML inside the audit tab container

- [ ] **Step 1: Create `static/tabs/audit.html`**

```html
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
                        <div>
                            <h2 style="margin:0;">Audit & Verification</h2>
                            <span style="font-size:0.82rem;color:#888;">Step-by-step calculation verification and data integrity checks</span>
                        </div>
                    </div>
                    <div class="card" style="padding:0.6rem 0.8rem;margin-bottom:1rem;">
                        <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">
                            <label style="font-size:0.75rem;color:#666;">Hospital:</label>
                            <select id="auditHospitalSelect" style="font-size:0.8rem;padding:0.25rem 0.4rem;"><option value="">Select hospital</option></select>
                            <label style="font-size:0.75rem;color:#666;">Month:</label>
                            <select id="auditMonthSelect" style="font-size:0.8rem;padding:0.25rem 0.4rem;"><option value="">Select month</option></select>
                            <button class="btn btn-sm" onclick="loadAudit()" id="auditBtn" style="background:#d32f2f;color:#fff;border:none;padding:0.3rem 0.8rem;border-radius:4px;cursor:pointer;font-size:0.78rem;">Generate Audit</button>
                            <span id="auditLoading" class="hidden" style="font-size:0.75rem;color:#888;"><span class="spinner"></span></span>
                        </div>
                    </div>
                    <div id="auditResults"></div>
```

- [ ] **Step 2: Create `static/js/audit.js`**

```javascript
import { API, apiGet } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';

let _auditData = null;

function riskColor(level) {
    if (!level) return '#888';
    const l = level.toLowerCase();
    if (l === 'critical') return '#b71c1c';
    if (l === 'high') return '#c62828';
    if (l === 'moderate' || l === 'elevated') return '#e65100';
    if (l === 'low' || l === 'normal') return '#2e7d32';
    return '#888';
}

function pill(label, value, color) {
    return '<span style="display:inline-flex;align-items:center;gap:0.2rem;font-size:0.7rem;background:' + color + '11;border:1px solid ' + color + '44;border-radius:4px;padding:0.1rem 0.45rem;"><strong style="color:' + color + ';">' + esc(value) + '</strong><span style="color:' + color + '88;">' + esc(label) + '</span></span>';
}

export function initAudit() {
    const hSel = document.getElementById('auditHospitalSelect');
    const mSel = document.getElementById('auditMonthSelect');
    if (hSel.options.length > 1 && mSel.options.length > 1) return;
    Promise.all([
        apiGet('/hospitals/').then(d => {
            const list = d.value || d || [];
            hSel.innerHTML = '<option value="">Select hospital</option>' + list.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
        }).catch(() => {}),
        fetch(API() + '/analysis/months').then(r => r.json()).then(d => {
            const months = d.months || d || [];
            mSel.innerHTML = '<option value="">Select month</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
        }).catch(() => {}),
    ]);
}

export function loadAudit() {
    const hid = document.getElementById('auditHospitalSelect').value;
    const month = document.getElementById('auditMonthSelect').value;
    if (!hid || !month) { alert('Please select hospital and month.'); return; }
    document.getElementById('auditLoading').classList.remove('hidden');
    document.getElementById('auditBtn').disabled = true;
    const container = document.getElementById('auditResults');
    container.innerHTML = '';

    Promise.all([
        fetch(API() + '/audit/calculation-steps/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/benchmark/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/data-auditor/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/report/' + hid + '?month=' + month).then(r => r.json()),
    ]).then(([steps, bench, dataAudit, report]) => {
        _auditData = { steps, bench, dataAudit, report };
        document.getElementById('auditLoading').classList.add('hidden');
        document.getElementById('auditBtn').disabled = false;
        renderAudit();
    }).catch(err => {
        document.getElementById('auditLoading').classList.add('hidden');
        document.getElementById('auditBtn').disabled = false;
        container.innerHTML = '<p style="color:#c62828;">Error: ' + esc(err.message) + '</p>';
    });
}

function renderAudit() {
    const d = _auditData;
    if (!d) return;
    const container = document.getElementById('auditResults');
    let html = '';

    // ── Section 1: Calculation Steps ──
    const steps = d.steps || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details open>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:#1a237e;">1. Calculation Steps</summary>';

    // Classifications
    if (steps.classifications && steps.classifications.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Clinical Rates</div>';
        steps.classifications.forEach(c => {
            const f = c.formula || '';
            const color = c.color || '#888';
            html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:#fafafa;border-left:3px solid ' + color + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(c.rate_name) + '</strong>';
            html += '<span style="color:' + color + ';font-weight:600;">' + esc(c.label) + '</span>';
            html += '</div>';
            if (f) html += '<div style="font-size:0.72rem;color:#666;margin:0.1rem 0;">Formula: ' + f + '</div>';
            html += '<div style="font-size:0.72rem;color:#555;">Inputs: ' + esc(c.numerator_codes.join(' + ') + ' / ' + (c.denominator_code || '?')) + ' = ' + esc(c.numerator_value + ' / ' + c.denominator_value) + ' = <strong>' + (c.raw_rate != null ? Number(c.raw_rate).toFixed(2) : '--') + '</strong> ' + esc(c.unit) + '</div>';
            if (c.narrative) html += '<div style="font-size:0.7rem;color:#777;margin:0.1rem 0;">' + esc(c.narrative) + '</div>';
            html += '</div>';
        });
    }

    // Quality score
    if (steps.quality_score) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Quality Score</div>';
        const qs = steps.quality_score;
        html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:#fafafa;border-left:3px solid ' + riskColor(qs.final_score < 50 ? 'critical' : qs.final_score < 70 ? 'high' : 'normal') + ';border-radius:3px;font-size:0.78rem;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;"><strong>Final Score</strong><span style="font-weight:700;font-size:1rem;">' + (qs.final_score != null ? Number(qs.final_score).toFixed(1) : '--') + '</span></div>';
        if (qs.components) {
            qs.components.forEach(c => {
                html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#555;padding:0.1rem 0;border-top:1px solid #eee;">';
                html += '<span>' + esc(c.name) + ' (×' + c.weight + ')</span>';
                html += '<span>' + (c.value != null ? Number(c.value).toFixed(3) : '--') + ' → ' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + '</span>';
                html += '</div>';
            });
        }
        html += '</div>';
    }

    // Risk profile
    if (steps.risk_profile && steps.risk_profile.metrics && steps.risk_profile.metrics.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Risk Profile <span style="font-weight:400;color:' + riskColor(steps.risk_profile.overall_risk_level) + ';">(' + esc(steps.risk_profile.overall_risk_level || '') + ')</span></div>';
        steps.risk_profile.metrics.forEach(m => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#555;padding:0.1rem 0.4rem;border-bottom:1px solid #f0f0f0;">';
            html += '<span>' + esc(m.metric_name) + '</span>';
            html += '<span>' + (m.value != null ? Number(m.value).toFixed(1) : '--') + m.unit + ' <span style="color:' + riskColor(m.severity) + ';font-weight:600;">' + esc(m.severity || '') + '</span></span>';
            html += '</div>';
        });
    }

    // Morbidity profile
    if (steps.morbidity_profile && steps.morbidity_profile.metrics && steps.morbidity_profile.metrics.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Morbidity Profile</div>';
        html += '<div style="font-size:0.72rem;color:#555;padding:0.2rem 0.4rem;">SMM: ' + (steps.morbidity_profile.total_smm || 0) + ' | Maternal Deaths: ' + (steps.morbidity_profile.maternal_deaths || 0) + '</div>';
    }

    html += '</details></div>';

    // ── Section 2: Benchmark Comparison ──
    const bench = d.bench || d.benchmark || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:#1a237e;">2. Benchmark Comparison</summary>';
    if (bench.comparisons) {
        Object.keys(bench.comparisons).sort().forEach(rname => {
            const c = bench.comparisons[rname];
            const barW = Math.min(Math.abs(c.percent_deviation || 0) / 2, 50);
            const barColor = riskColor(c.status);
            const arrow = (c.percent_deviation || 0) > 0 ? '↑' : '↓';
            html += '<div style="margin:0.4rem 0;padding:0.3rem 0.5rem;background:#fafafa;border-left:3px solid ' + barColor + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(rname) + '</strong>';
            html += '<span style="color:' + barColor + ';font-weight:600;">' + arrow + ' ' + Math.abs(c.percent_deviation || 0).toFixed(1) + '% vs avg</span>';
            html += '</div>';
            html += '<div style="margin:0.2rem 0;height:0.5rem;background:#eee;border-radius:3px;position:relative;">';
            html += '<div style="height:100%;width:' + Math.min(Math.abs(c.percent_deviation || 0), 100) + '%;background:' + barColor + ';border-radius:3px;opacity:0.6;"></div>';
            html += '</div>';
            html += '<div style="font-size:0.72rem;color:#555;">Hospital: <strong>' + (c.hospital_value || 0) + '</strong> | Avg: ' + (c.peer_average || 0) + ' | Median: ' + (c.peer_median || 0) + ' | Range: [' + (c.peer_min || 0) + ' – ' + (c.peer_max || 0) + ']</div>';
            html += '<div style="font-size:0.72rem;color:#555;">Z-score: ' + (c.z_score || 0) + ' | Percentile: ' + (c.percentile || 0) + 'th | Peers: ' + (c.peer_count || 0) + '</div>';
            html += '</div>';
        });
    } else {
        html += '<p style="color:#888;text-align:center;padding:1rem;">No benchmark data available.</p>';
    }
    html += '</details></div>';

    // ── Section 3: Data Auditor ──
    const da = d.dataAudit || d.data_audit || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:#1a237e;">3. Data Auditor</summary>';

    // Completeness
    if (da.completeness) {
        const comp = da.completeness;
        const pct = comp.total > 0 ? Math.round(comp.present / comp.total * 100) : 0;
        html += '<div style="margin:0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Completeness <span style="font-weight:400;color:' + (pct >= 80 ? '#2e7d32' : pct >= 50 ? '#e65100' : '#c62828') + ';">(' + pct + '%)</span></div>';
        html += '<div style="font-size:0.72rem;color:#555;margin-bottom:0.3rem;">' + comp.present + ' / ' + comp.total + ' indicators present (' + comp.missing + ' missing)</div>';

        // Show missing indicators only (compact table)
        const missing = (comp.indicators || []).filter(i => i.status === 'missing');
        if (missing.length) {
            html += '<details style="margin:0.2rem 0;font-size:0.72rem;">';
            html += '<summary style="cursor:pointer;color:#c62828;">' + missing.length + ' missing indicators</summary>';
            missing.forEach(i => {
                html += '<div style="padding:0.1rem 0.5rem;color:#555;">' + esc(i.indicator_code) + ' — ' + esc(i.indicator_name) + '</div>';
            });
            html += '</details>';
        }
    }

    // Rule failures
    if (da.rule_failures && da.rule_failures.items && da.rule_failures.items.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Rule Failures (' + da.rule_failures.total + ')</div>';
        da.rule_failures.items.slice(0, 10).forEach(r => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid ' + riskColor(r.severity) + ';margin:0.15rem 0;background:' + riskColor(r.severity) + '06;border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(r.rule_code) + '</strong> — ' + esc(r.description) + '</span><span style="color:' + riskColor(r.severity) + ';font-weight:600;">' + esc(r.severity) + '</span></div>';
            if (r.details) html += '<div style="font-size:0.7rem;color:#666;">' + esc(r.details) + '</div>';
            html += '</div>';
        });
        if (da.rule_failures.items.length > 10) {
            html += '<div style="font-size:0.72rem;color:#888;text-align:center;">... and ' + (da.rule_failures.items.length - 10) + ' more</div>';
        }
    }

    // Quality score breakdown
    if (da.quality_score && da.quality_score.components) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Quality Score Impact</div>';
        da.quality_score.components.forEach(c => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#555;padding:0.1rem 0.5rem;border-bottom:1px solid #f0f0f0;">';
            html += '<span>' + esc(c.name) + '</span>';
            html += '<span>' + (c.raw != null ? (c.raw * 100).toFixed(1) + '%' : '--') + ' × ' + c.weight + ' = ' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + ' (' + (c.contribution_pct || 0) + '%)</span>';
            html += '</div>';
        });
    }

    // Outliers
    if (da.outliers && da.outliers.items && da.outliers.items.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Outliers (' + da.outliers.total + ')</div>';
        da.outliers.items.forEach(o => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid #b71c1c;margin:0.15rem 0;background:#b71c1c06;border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(o.rate_name) + '</strong> (' + esc(o.indicator_code) + ')</span><span style="color:#b71c1c;font-weight:600;">z=' + (o.z_score != null ? Number(o.z_score).toFixed(2) : '--') + '</span></div>';
            html += '<div style="font-size:0.7rem;color:#666;">Value: ' + (o.value != null ? Number(o.value).toFixed(2) : '--') + ' | Benchmark: ' + (o.benchmark != null ? Number(o.benchmark).toFixed(2) : '--') + '</div>';
            html += '</div>';
        });
    }

    // Confidence
    if (da.confidence) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:#333;">Confidence</div>';
        const cf = da.confidence;
        html += '<div style="font-size:0.74rem;color:#555;padding:0.2rem 0.5rem;">Overall: <strong>' + esc(cf.overall_confidence != null ? Number(cf.overall_confidence).toFixed(1) : '--') + '</strong> (' + esc(cf.level || '') + ') | Indicators: ' + (cf.indicator_count || 0) + ' | HIGH: ' + (cf.by_level?.high || 0) + ' MED: ' + (cf.by_level?.medium || 0) + ' LOW: ' + (cf.by_level?.low || 0) + ' CRIT: ' + (cf.by_level?.critical || 0) + '</div>';
    }

    html += '</details></div>';

    // ── Section 4: Audit Report ──
    const rpt = d.report || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:#1a237e;">4. Audit Report</summary>';

    // Verification status
    if (rpt.verification) {
        const v = rpt.verification;
        const allOk = v.all_passed;
        html += '<div style="margin:0.3rem 0;padding:0.3rem 0.5rem;background:' + (allOk ? '#e8f5e9' : '#ffebee') + ';border-radius:4px;font-size:0.8rem;font-weight:600;color:' + (allOk ? '#2e7d32' : '#c62828') + ';">';
        html += allOk ? '✓ All calculations verified' : '⚠ Some calculations have discrepancies';
        html += '</div>';
        if (v.checks) {
            v.checks.forEach(c => {
                html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#555;padding:0.1rem 0.5rem;">';
                html += '<span>' + esc(c.check) + '</span>';
                html += '<span style="color:' + (c.status === 'verified' ? '#2e7d32' : '#c62828') + ';">' + esc(c.status) + '</span>';
                html += '</div>';
            });
        }
    }

    // Download buttons
    html += '<div style="margin:0.5rem 0;display:flex;gap:0.5rem;">';
    html += '<button class="btn btn-sm" onclick="downloadAuditJSON()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">Download JSON</button>';
    html += '<button class="btn btn-sm" onclick="downloadAuditCSV()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">Download CSV</button>';
    html += '</div>';

    html += '</details></div>';

    container.innerHTML = html;
}

export function downloadAuditJSON() {
    if (!_auditData) return;
    const blob = new Blob([JSON.stringify(_auditData.report || _auditData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-report.json';
    a.click();
    URL.revokeObjectURL(url);
}

export function downloadAuditCSV() {
    if (!_auditData) return;
    const steps = _auditData.steps || {};
    const cls = steps.classifications || [];
    let csv = 'rate_name,value,unit,classification,label\n';
    cls.forEach(c => {
        csv += '"' + c.rate_name + '",' + (c.raw_rate != null ? c.raw_rate : '') + ',' + (c.unit || '') + ',' + (c.classification || '') + ',' + (c.label || '') + '\n';
    });
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-classifications.csv';
    a.click();
    URL.revokeObjectURL(url);
}
```

- [ ] **Step 3: Register in main.js and index.html**

In `static/js/main.js`, add the tab registration (similar to other tabs):
```javascript
// At the top imports:
import { initAudit, loadAudit, downloadAuditJSON, downloadAuditCSV } from './audit.js';

// In the init function or tab registration:
window.initAudit = initAudit;
window.loadAudit = loadAudit;
window.downloadAuditJSON = downloadAuditJSON;
window.downloadAuditCSV = downloadAuditCSV;

// In the tab-switch handler (around line 89-93), add:
if (name === 'audit') window.initAudit();
```

In `static/index.html`, add after an existing tab entry:
```html
<div class="tab" data-tab="audit" role="tab" aria-selected="false" aria-controls="tab-audit" tabindex="-1" style="color:#d32f2f;font-weight:600;">Audit</div>
```
And the content container:
```html
<div id="tab-audit" class="tab-content" data-loaded="false" role="tabpanel" aria-labelledby="tab-audit" data-src="/static/tabs/audit.html"></div>
```

- [ ] **Step 4: Test frontend loads without errors**

Open browser (Ctrl+F5 hard refresh), navigate to app, click "Audit" tab.
Expected: Tab loads with hospital/month selectors. Selecting hospital+month and clicking "Generate Audit" shows all 4 sections.

- [ ] **Step 5: Commit**

```bash
git add static/js/audit.js static/tabs/audit.html static/js/main.js static/index.html
git commit -m "feat: add audit tab with 4 verification sections"
```
