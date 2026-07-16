### Task 1: Backend — Add `/dashboard/ranking` endpoint

**Files:**
- Modify: `app/api/dashboard.py`

**Interfaces:**
- Consumes: `Hospital`, `QualityScore`, `ValidationResult`, `ConfidenceScore`, `ClinicalInsight` tables
- Produces: `GET /dashboard/ranking` → JSON array of `{id, name, avg_score, trend_direction, avg_clinical_rate, confidence, completeness, consistency, reports, alerts, rank}`

- [ ] Step 1: Update imports in `app/api/dashboard.py`

Add `ClinicalInsight` to the model import. Change line 5 from:
```python
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult
```
to:
```python
from app.models import Hospital, QualityScore, ConfidenceScore, ValidationResult, ClinicalInsight
```

Add `import json` at the top (line 1 is `import re`, add `import json` before it).

- [ ] Step 2: Add the ranking endpoint function after the last existing endpoint (after line 241)

```python
@router.get("/ranking")
def dashboard_ranking(hospital_id: int | None = None, db: Session = Depends(get_db)):
    from app.api.analysis import get_enabled_months
    enabled_months = get_enabled_months(db)

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    rows = []
    for h in hospitals:
        q = db.query(QualityScore).filter(QualityScore.hospital_id == h.id)
        if enabled_months:
            q = q.filter(QualityScore.month.in_(enabled_months))
        scores = q.order_by(QualityScore.month.asc()).all()

        if not scores:
            continue

        avg_score = round(sum(s.score for s in scores) / len(scores), 1)
        avg_compliance = round(sum(s.rule_compliance or 0 for s in scores) / len(scores), 1)
        avg_completeness = round(sum(s.completeness or 0 for s in scores) / len(scores), 1)
        avg_consistency = round(sum(s.consistency or 0 for s in scores) / len(scores), 1)

        recent_3 = [s.score for s in scores[-3:]]
        if len(recent_3) >= 2:
            direction = "up" if recent_3[-1] > recent_3[0] else "down" if recent_3[-1] < recent_3[0] else "stable"
        else:
            direction = "stable"

        conf = db.query(ConfidenceScore).filter(
            ConfidenceScore.hospital_id == h.id
        ).order_by(ConfidenceScore.month.desc()).first()
        conf_score = round(conf.overall_confidence, 1) if conf else 0

        alerts_count = db.query(ValidationResult).filter(
            ValidationResult.hospital_id == h.id,
            ValidationResult.status == "FAIL"
        ).count()

        insights = db.query(ClinicalInsight).filter(
            ClinicalInsight.hospital_id == h.id
        ).all()
        rate_values = {}
        for ins in insights:
            try:
                data = json.loads(ins.analysis_data)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in data.get("classifications", []):
                rn = c.get("rate_name", "")
                val = c.get("value")
                if val is not None:
                    rate_values.setdefault(rn, []).append(val)
        clinical_rates = {}
        for rn, vals in rate_values.items():
            if vals:
                clinical_rates[rn] = round(sum(vals) / len(vals), 1)

        rows.append({
            "id": h.id,
            "name": h.name,
            "avg_score": avg_score,
            "trend_direction": direction,
            "avg_clinical_rate": round(sum(clinical_rates.values()) / len(clinical_rates), 1) if clinical_rates else 0,
            "confidence": conf_score,
            "completeness": avg_completeness,
            "consistency": avg_consistency,
            "reports": len(scores),
            "alerts": alerts_count,
        })

    rows.sort(key=lambda r: r["avg_score"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return rows
```

- [ ] Step 3: Verify the endpoint loads

```bash
cd C:\ibra\HEALTH-ai; python -c "from app.api.dashboard import router; print('dashboard router OK')"
```
Expected: `dashboard router OK`
