from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Rule
from app.schemas import RuleOut, RuleCreate, RuleUpdate
from app.core.deps import require_permission

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(require_permission("rules.read"))])


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
