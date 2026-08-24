from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AppConfig, SystemSetting
from app.config_utils import AI_CONFIG_KEYS, get_ai_config
from app.core.deps import require_permission

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_permission("settings.read"))])

CONTROL_KEY = "auto_disable_null_indicators"
LOGGING_KEY = "structured_logging_enabled"
SLOW_QUERY_KEY = "slow_query_logging_enabled"
MONTH_SETTINGS_PREFIX = "month_enabled_"


@router.get("/database-status")
def get_database_status(db: Session = Depends(get_db)):
    """Check database connection and return stats."""
    from sqlalchemy import inspect as sa_inspect, func
    from app.models import Hospital, IndicatorValue, QualityScore, Indicator, Rule, AppConfig, SystemSetting
    try:
        db.execute(func.now())
        total_hospitals = db.query(func.count(Hospital.id)).scalar() or 0
        active_hospitals = db.query(func.count(Hospital.id)).filter(Hospital.is_active.is_(True)).scalar() or 0
        total_indicator_values = db.query(func.count(IndicatorValue.id)).scalar() or 0
        total_quality_scores = db.query(func.count(QualityScore.id)).scalar() or 0
        total_indicators = db.query(func.count(Indicator.id)).scalar() or 0
        total_rules = db.query(func.count(Rule.id)).scalar() or 0
        # Check key tables exist (portable: works on any database)
        tables = sa_inspect(db.get_bind()).get_table_names()
        return {
            "connected": True,
            "engine": "PostgreSQL",
            "total_hospitals": total_hospitals,
            "active_hospitals": active_hospitals,
            "total_indicator_values": total_indicator_values,
            "total_quality_scores": total_quality_scores,
            "total_indicators": total_indicators,
            "total_rules": total_rules,
            "tables": tables,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/control/settings")
def get_control_settings(db: Session = Depends(get_db)):
    row = db.query(SystemSetting).filter(SystemSetting.key == CONTROL_KEY).first()
    log_row = db.query(SystemSetting).filter(SystemSetting.key == LOGGING_KEY).first()
    slow_row = db.query(SystemSetting).filter(SystemSetting.key == SLOW_QUERY_KEY).first()
    return {
        "auto_disable_null_indicators": (row.value == "true") if row else False,
        "structured_logging_enabled": (log_row.value == "true") if log_row else True,
        "slow_query_logging_enabled": (slow_row.value == "true") if slow_row else True,
    }


@router.put("/control/settings")
def update_control_settings(updates: dict = Body(...), db: Session = Depends(get_db)):
    updated = {}
    for key in (CONTROL_KEY, LOGGING_KEY, SLOW_QUERY_KEY):
        if key in updates:
            val = str(updates[key]).lower()
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row:
                row.value = val
            else:
                db.add(SystemSetting(key=key, value=val))
            updated[key] = val == "true"
    db.commit()
    # Update runtime flags immediately
    if LOGGING_KEY in updated:
        from app.monitoring import set_logging_enabled
        set_logging_enabled(updated[LOGGING_KEY])
    if SLOW_QUERY_KEY in updated:
        from app.monitoring import set_slow_query_logging
        set_slow_query_logging(updated[SLOW_QUERY_KEY])
    return {"status": "ok", **updated}


@router.get("/")
def get_all_config(db: Session = Depends(get_db)):
    rows = db.query(AppConfig).all()
    result = {}
    for r in rows:
        if r.category not in result:
            result[r.category] = {}
        result[r.category][r.key] = {
            "value": r.value,
            "label": r.label,
        }
    return result


@router.get("/month-settings")
def get_month_settings(
    hospital_id: int = Query(..., description="Hospital ID"),
    db: Session = Depends(get_db),
):
    """Get list of enabled months for a specific hospital."""
    from app.api.analysis import list_months_with_data
    all_months = list_months_with_data(db)
    prefix = MONTH_SETTINGS_PREFIX + str(hospital_id) + "_"
    rows = db.query(SystemSetting).filter(
        SystemSetting.key.like(prefix + "%")
    ).all()
    disabled = {
        row.key[len(prefix):]
        for row in rows
        if row.value == "false"
    }
    enabled_months = [m for m in all_months if m not in disabled]
    return {"enabled_months": enabled_months}


@router.put("/month-settings")
def update_month_setting(updates: dict = Body(...), db: Session = Depends(get_db)):
    """Enable or disable a specific month for a specific hospital."""
    month = updates.get("month")
    hospital_id = updates.get("hospital_id")
    enabled = updates.get("enabled", True)
    if not month or hospital_id is None:
        raise HTTPException(status_code=400, detail="month and hospital_id are required")
    key = MONTH_SETTINGS_PREFIX + str(hospital_id) + "_" + month
    val = "true" if enabled else "false"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=key, value=val))
    db.commit()
    return {"status": "ok", "month": month, "hospital_id": hospital_id, "enabled": enabled}


@router.get("/{category}")
def get_config_by_category(category: str, db: Session = Depends(get_db)):
    rows = db.query(AppConfig).filter(AppConfig.category == category).all()
    return {r.key: {"value": r.value, "label": r.label} for r in rows}


@router.put("/")
def update_config(updates: dict, db: Session = Depends(get_db)):
    updated = 0
    for key, val in updates.items():
        row = db.query(AppConfig).filter(AppConfig.key == key).first()
        if row:
            try:
                row.value = float(val)
                updated += 1
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"Invalid numeric value for '{key}': {val}")
    db.commit()
    return {"status": "ok", "updated": updated}


@router.get("/ai/settings")
def get_ai_settings(db: Session = Depends(get_db)):
    try:
        return get_ai_config(db)
    except Exception:
        # Table may not exist yet (first deploy before migrations)
        return {k: v for k, v in AI_CONFIG_KEYS.items()}


@router.put("/ai/settings")
def update_ai_settings(updates: dict, db: Session = Depends(get_db)):
    try:
        for key, val in updates.items():
            if key not in AI_CONFIG_KEYS:
                continue
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row:
                row.value = str(val)
            else:
                db.add(SystemSetting(key=key, value=str(val)))
        db.commit()
        from app.plugins.ai import reload_ai_config
        reload_ai_config()
        return {"status": "ok", "updated": len(updates)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error saving AI settings: {str(e)}")
