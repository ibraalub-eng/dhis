### Task 2: Backend — Add `/dashboard/hospital-performance/{id}` endpoint

**Files:**
- Modify: `app/api/dashboard.py` (add after `/ranking` endpoint)

**Interfaces:**
- Consumes: Hospital ID, `QualityScore`, `ValidationResult`, `ClinicalInsight`, and `run_clinical_analysis()` from engine
- Produces: `GET /dashboard/hospital-performance/{id}` → `{id, name, grade, avg_score, avg_compliance, avg_completeness, avg_consistency, quality_trend, clinical_rates[], total_alerts, last_alerts[]}`

- [ ] Step 1: Add missing imports at top of file

Add `HTTPException` to the FastAPI import (line 3). Change:
```python
from fastapi import APIRouter, Depends
```
to:
```python
from fastapi import APIRouter, Depends, HTTPException
```

Add import for `get_enabled_values_for_hospital_month` after existing imports:
```python
from app.engine.pipeline import get_enabled_values_for_hospital_month
```

- [ ] Step 2: Add the hospital performance endpoint

```python
@router.get("/hospital-performance/{hospital_id}")
def hospital_performance(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    scores = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id
    ).order_by(QualityScore.month.asc()).all()

    quality_trend = [{"month": s.month, "score": round(s.score, 1)} for s in scores]
    avg_score = round(sum(s.score for s in scores) / len(scores), 1) if scores else 0
    avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1) if scores else 0
    avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1) if scores else 0

    # Grade
    if avg_score >= 90: grade = "A"
    elif avg_score >= 75: grade = "B"
    elif avg_score >= 60: grade = "C"
    else: grade = "D"

    # Clinical rates — latest month
    latest_month = scores[-1].month if scores else None
    clinical_rates = []
    if latest_month:
        try:
            values = get_enabled_values_for_hospital_month(db, hospital_id, latest_month)
            if values:
                from app.engine.clinical import run_clinical_analysis
                result = run_clinical_analysis(hospital=hospital.name, month=latest_month, values=values)
                MAIN_RATES = {"C-Section Rate", "Maternal Mortality Ratio", "Neonatal Mortality Rate",
                              "Preterm Birth Rate", "Severe Maternal Morbidity Rate", "Stillbirth Rate",
                              "NICU Admission Rate"}
                for c in result.classifications:
                    if c.rate_name in MAIN_RATES:
                        clinical_rates.append({
                            "rate_name": c.rate_name,
                            "value": round(c.value, 1) if c.value else 0,
                            "unit": c.unit,
                            "classification": c.classification,
                        })
        except Exception:
            pass

    # Peer averages for clinical rates
    if latest_month and clinical_rates:
        try:
            peers = db.query(Hospital).filter(Hospital.is_active.is_(True), Hospital.id != hospital_id).all()
            peer_rate_vals = {r["rate_name"]: [] for r in clinical_rates}
            for ph in peers:
                pv = get_enabled_values_for_hospital_month(db, ph.id, latest_month)
                if not pv:
                    continue
                from app.engine.clinical import run_clinical_analysis as rca_peer
                try:
                    pr = rca_peer(hospital=ph.name, month=latest_month, values=pv)
                except Exception:
                    continue
                for c in pr.classifications:
                    if c.rate_name in peer_rate_vals and c.value is not None:
                        peer_rate_vals[c.rate_name].append(c.value)
            for r in clinical_rates:
                vals = peer_rate_vals.get(r["rate_name"], [])
                r["peer_avg"] = round(sum(vals) / len(vals), 1) if vals else None
        except Exception:
            pass

    # Alerts
    total_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).count()
    recent_alerts = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL"
    ).order_by(ValidationResult.month.desc()).limit(5).all()
    last_alerts = [
        {"month": a.month, "rule_code": a.rule_code, "severity": a.severity, "details": (a.details or "")[:80]}
        for a in recent_alerts
    ]

    return {
        "id": hospital.id, "name": hospital.name, "grade": grade,
        "avg_score": avg_score, "avg_compliance": avg_compliance,
        "avg_completeness": avg_completeness, "avg_consistency": avg_consistency,
        "quality_trend": quality_trend, "clinical_rates": clinical_rates,
        "total_alerts": total_alerts, "last_alerts": last_alerts,
    }
```

- [ ] Step 3: Verify endpoint loads

```bash
cd C:\ibra\HEALTH-ai; python -c "from app.api.dashboard import router; print('dashboard router OK')"
```
Expected: `dashboard router OK`
