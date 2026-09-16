import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Rule, Indicator, ValidationResult, Hospital
from app.schemas import RuleOut, RuleCreate, RuleUpdate
from app.core.deps import require_permission
from app.engine.quality.rules import _get_rule_ref_codes_from_expr
from app.engine.quality import ValidationContext, dispatch_rule
from app.engine.pipeline import (
    get_enabled_values_for_hospital_month,
    get_all_hospital_data_for_month,
    get_historical_months,
    get_disabled_indicator_ids,
)

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(require_permission("rules.read"))])


@router.get("/impact")
def rules_impact(
    months: int = None,
    db: Session = Depends(get_db),
):
    """Per-rule: referenced indicator codes/names + recent failure footprint
    from stored validation_results. By default spans every month with data;
    pass months=N to limit to the last N months."""
    month_rows = db.query(ValidationResult.month).distinct().all()
    all_months = sorted({r[0] for r in month_rows})
    if months and months > 0:
        recent = set(all_months[-months:]) if all_months else set()
    else:
        recent = set(all_months)

    rules = db.query(Rule).order_by(Rule.code).all()
    ind_map = {i.code: i.name for i in db.query(Indicator).all()}

    fail_counts = {}
    fail_hospitals = {}
    fail_details = {}
    if recent:
        rows = db.query(
            ValidationResult.rule_code,
            ValidationResult.hospital_id,
            ValidationResult.details,
        ).filter(
            ValidationResult.status == "FAIL",
            ValidationResult.month.in_(recent),
        ).all()
        for rc, hid, details in rows:
            fail_counts[rc] = fail_counts.get(rc, 0) + 1
            fail_hospitals.setdefault(rc, set()).add(hid)
            fail_details.setdefault(rc, {})[hid] = details

    hospital_map = {h.id: h.name for h in db.query(Hospital).all()}
    result = []
    for r in rules:
        params = {}
        try:
            params = json.loads(r.params) if isinstance(r.params, str) else (r.params or {})
        except Exception:
            params = {}
        ref_codes = _get_rule_ref_codes_from_expr(r.expression_type, params)
        affected = []
        for hid in sorted(fail_hospitals.get(r.code, set())):
            affected.append({
                "id": hid,
                "name": hospital_map.get(hid, f"Hospital #{hid}"),
                "details": fail_details.get(r.code, {}).get(hid),
            })
        result.append({
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "expression_type": r.expression_type,
            "rule_type": r.rule_type,
            "category": r.category,
            "ref_codes": ref_codes,
            "ref_names": [ind_map.get(c, c) for c in ref_codes],
            "failure_count": fail_counts.get(r.code, 0),
            "hospitals_affected": affected,
            "months_scope": len(recent),
        })
    return result


@router.post("/test")
def test_rule(body: dict, db: Session = Depends(get_db)):
    """Dry-run a rule definition against real data without saving.

    - month omitted  -> uses the most recent month that has data
    - hospital_id omitted -> evaluates every active hospital for the month
    Returns PASS/FAIL with a per-hospital breakdown and the actual values used.
    """
    from types import SimpleNamespace
    hospital_id = body.get("hospital_id")
    month = body.get("month")

    # Resolve month to the most recent month with data
    if not month:
        month_rows = db.query(ValidationResult.month).distinct().all()
        months_sorted = sorted({r[0] for r in month_rows})
        if not months_sorted:
            raise HTTPException(status_code=400, detail="No data months found in the system")
        month = months_sorted[-1]

    params = body.get("params")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = body.get("params") or {}
    params = params or {}

    rule_obj = SimpleNamespace(
        code=body.get("code") or "TEST",
        name=body.get("name") or body.get("code") or "Test Rule",
        rule_type=body.get("rule_type") or "LOGIC",
        severity=body.get("severity") or "HIGH",
        expression_type=body.get("expression_type"),
        params=json.dumps(params),
    )

    # Build the scope of hospitals
    if hospital_id:
        hosp = db.query(Hospital).filter(
            Hospital.id == hospital_id,
            Hospital.is_active.is_(True),
        ).first()
        if not hosp:
            raise HTTPException(status_code=404, detail="Hospital not found")
        hospitals = [hosp]
    else:
        hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()

    all_hospital_data = get_all_hospital_data_for_month(db, month) or {}
    ind_map = {i.code: i.name for i in db.query(Indicator).all()}
    ref_codes = _get_rule_ref_codes_from_expr(body.get("expression_type"), params)

    per_hospital = []
    failed_count = 0
    passed_count = 0
    no_data_count = 0
    for hosp in hospitals:
        values = get_enabled_values_for_hospital_month(db, hosp.id, month)
        if not values:
            per_hospital.append({
                "hospital_id": hosp.id,
                "hospital": hosp.name,
                "status": "NO_DATA",
                "details": "No indicator values found for this hospital/month.",
            })
            no_data_count += 1
            continue

        historical_data = get_historical_months(db, hosp.id, month)
        disabled_ids = get_disabled_indicator_ids(db, hosp.id, month)
        disabled_codes = set()
        if disabled_ids:
            ind_rows = db.query(Indicator).filter(Indicator.id.in_(disabled_ids)).all()
            disabled_codes = {ind.code for ind in ind_rows}

        ctx = ValidationContext(
            values=values,
            hospital_name=hosp.name,
            month=month,
            all_hospital_data=all_hospital_data,
            historical_data=historical_data or {},
            disabled_codes=disabled_codes,
        )

        try:
            result = dispatch_rule(rule_obj, ctx)
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"Missing required param: {e}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Evaluation error: {e}")

        if result is None:
            per_hospital.append({
                "hospital_id": hosp.id,
                "hospital": hosp.name,
                "status": "NO_DATA",
                "details": "Rule skipped: all referenced indicators are disabled for this month.",
            })
            no_data_count += 1
            continue

        ref_values = {}
        for c in ref_codes:
            val = values.get(c)
            if val is not None:
                ref_values[c] = {"name": ind_map.get(c, c), "value": val}

        per_hospital.append({
            "hospital_id": hosp.id,
            "hospital": hosp.name,
            "status": result.status.value,
            "details": result.details,
            "ref_values": ref_values,
        })
        if result.status.value == "FAIL":
            failed_count += 1
        else:
            passed_count += 1

    if failed_count:
        overall = "FAIL"
        details = f"The rule triggered in {failed_count} of {len(per_hospital)} hospital(s)."
    elif no_data_count == len(per_hospital):
        overall = "NO_DATA"
        details = "No evaluable data for any hospital this month."
    elif no_data_count:
        overall = "PASS"
        details = f"Passed in {passed_count} hospital(s); {no_data_count} hospital(s) had no data."
    else:
        overall = "PASS"
        details = f"Passed in all {passed_count} hospital(s)."

    return {
        "status": overall,
        "details": details,
        "month": month,
        "scope": "single" if hospital_id else "all",
        "hospital": per_hospital[0]["hospital"] if hospital_id and per_hospital else None,
        "passed": passed_count,
        "failed": failed_count,
        "no_data": no_data_count,
        "total": len(per_hospital),
        "ref_codes": ref_codes,
        "ref_names": [ind_map.get(c, c) for c in ref_codes],
        "hospitals": per_hospital,
    }


def _normalize_rule_params(params: dict) -> dict:
    """Stable dict comparison for duplicate/conflict detection."""
    out = {}
    for k, v in (params or {}).items():
        if isinstance(v, list):
            out[k] = sorted(str(x) for x in v)
        elif isinstance(v, float):
            out[k] = round(v, 6)
        else:
            out[k] = v
    return out


@router.post("/validate")
def validate_rule(body: dict, db: Session = Depends(get_db)):
    """Pre-save check: detect duplicate code, near-duplicate params, and
    logical conflicts with existing rules. Returns {errors: [], warnings: []}."""
    params_raw = body.get("params") or {}
    if isinstance(params_raw, str):
        try:
            params_raw = json.loads(params_raw)
        except Exception:
            params_raw = {}
    exclude_id = body.get("exclude_id")
    code = (body.get("code") or "").strip()

    errors = []
    warnings = []

    # 1. Duplicate code
    q = db.query(Rule).filter(Rule.code == code)
    if exclude_id:
        q = q.filter(Rule.id != exclude_id)
    if q.first():
        errors.append(f"Rule code '{code}' already exists. Choose a different code.")

    # 2. Near-duplicate & conflict detection
    existing = db.query(Rule).all()
    self_norm = json.dumps(_normalize_rule_params(params_raw), sort_keys=True) if params_raw else ""
    expr = body.get("expression_type")

    for other in existing:
        if exclude_id and other.id == exclude_id:
            continue
        try:
            other_params = json.loads(other.params) if isinstance(other.params, str) else (other.params or {})
        except Exception:
            other_params = {}
        other_norm = json.dumps(_normalize_rule_params(other_params), sort_keys=True)

        # Near-duplicate: same expression + identical params
        if self_norm and other.expression_type == expr and other_norm == self_norm:
            warnings.append(f"Identical to existing rule '{other.code}' ({other.name}).")
            continue

        # Conflict: month_over vs month_under on the same indicator code
        if expr in ("month_over", "month_under") and other.expression_type in ("month_over", "month_under") and expr != other.expression_type:
            if (params_raw.get("code") or "").strip() and params_raw.get("code") == other_params.get("code"):
                warnings.append(f"Conflicts with '{other.code}': opposite monthly trend directions on same indicator.")

        # Conflict: benchmark_rate vs benchmark_low_rate on the same numerator/denominator pair
        if expr in ("benchmark_rate", "benchmark_low_rate") and other.expression_type in ("benchmark_rate", "benchmark_low_rate") and expr != other.expression_type:
            if params_raw.get("num_code") == other_params.get("num_code") and params_raw.get("den_code") == other_params.get("den_code"):
                warnings.append(f"Conflicts with '{other.code}': opposite threshold directions on same rate.")

        # Conflict: ge vs gt on identical parent+children
        if expr in ("ge", "gt") and other.expression_type in ("ge", "gt") and expr != other.expression_type:
            same_parent = params_raw.get("parent") == other_params.get("parent") and params_raw.get("parent")
            same_children = sorted(params_raw.get("children") or []) == sorted(other_params.get("children") or [])
            if same_parent and same_children:
                warnings.append(f"Conflicts with '{other.code}': same comparison set, different strictness.")

    return {"errors": errors, "warnings": warnings}


@router.get("/failures")
def rule_failures(
    rule_code: str,
    hospital_id: int = None,
    db: Session = Depends(get_db),
):
    """Historical failures for a rule code (optionally filtered to one hospital).
    Returns the months in which the rule failed, sorted descending."""
    query = db.query(
        ValidationResult.month,
        ValidationResult.hospital_id,
        ValidationResult.details,
    ).filter(
        ValidationResult.rule_code == rule_code,
        ValidationResult.status == "FAIL",
    )
    if hospital_id:
        query = query.filter(ValidationResult.hospital_id == hospital_id)
    rows = query.order_by(ValidationResult.month.desc()).all()

    month_map = {}
    for month, hid, details in rows:
        entry = month_map.setdefault(month, {"month": month, "hospitals": []})
        entry["hospitals"].append({"hospital_id": hid, "details": details})

    return {
        "rule_code": rule_code,
        "hospital_id": hospital_id,
        "months": list(month_map.values()),
        "total_months": len(month_map),
    }


@router.get("/", response_model=List[RuleOut])
def list_rules(
    rule_type: str = None,
    category: str = None,
    enabled: bool = None,
    severity: str = None,
    db: Session = Depends(get_db),
):
    query = db.query(Rule)
    if rule_type:
        query = query.filter(Rule.rule_type == rule_type)
    if category:
        query = query.filter(Rule.category == category)
    if enabled is not None:
        query = query.filter(Rule.enabled == enabled)
    if severity:
        query = query.filter(Rule.severity == severity)
    rules = query.order_by(Rule.sort_order, Rule.code).all()
    # Auto-assign sort_order if all are 0
    if all(r.sort_order == 0 for r in rules):
        for i, r in enumerate(rules):
            r.sort_order = i
        db.commit()
        rules = query.order_by(Rule.sort_order, Rule.code).all()
    return rules


@router.put("/save-enabled")
def save_rules_enabled(body: dict, db: Session = Depends(get_db)):
    """Bulk save enabled states: {"items": [{"id": 1, "enabled": true}, ...]}"""
    items = body.get("items", [])
    count = 0
    for item in items:
        rule = db.query(Rule).filter(Rule.id == item.get("id")).first()
        if rule:
            rule.enabled = bool(item.get("enabled", True))
            count += 1
    db.commit()
    return {"message": f"Saved enabled state for {count} rule(s)"}


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.post("/", response_model=RuleOut)
def create_rule(rule: RuleCreate, db: Session = Depends(get_db)):
    existing = db.query(Rule).filter(Rule.code == rule.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Rule with code {rule.code} already exists")
    db_rule = Rule(
        code=rule.code,
        name=rule.name,
        rule_type=rule.rule_type,
        severity=rule.severity,
        category=rule.category,
        expression_type=rule.expression_type,
        params=rule.params,
        description=rule.description,
    )
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, rule: RuleUpdate, db: Session = Depends(get_db)):
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    update_data = rule.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(db_rule, key, val)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(db_rule)
    db.commit()
    return {"message": f"Rule {db_rule.code} deleted"}


@router.put("/reorder")
def bulk_reorder_rules(
    body: dict,
    db: Session = Depends(get_db),
):
    """Bulk reorder: pass {"items": [{"id": 1, "sort_order": 0}, {"id": 2, "sort_order": 1}, ...]}"""
    items = body.get("items", [])
    for item in items:
        rule = db.query(Rule).filter(Rule.id == item["id"]).first()
        if rule:
            rule.sort_order = item["sort_order"]
    db.commit()
    return {"message": f"{len(items)} rules reordered"}


@router.put("/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.enabled = not rule.enabled
    db.commit()
    db.refresh(rule)
    return {
        "id": rule.id,
        "code": rule.code,
        "enabled": rule.enabled,
        "message": f"Rule '{rule.code}' {'enabled' if rule.enabled else 'disabled'}",
    }
