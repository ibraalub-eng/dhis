from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AppConfig, SystemSetting
from app.config_utils import AI_CONFIG_KEYS, get_ai_config

router = APIRouter(prefix="/config", tags=["config"])

CONTROL_KEY = "auto_disable_null_indicators"
LOGGING_KEY = "structured_logging_enabled"
MONTH_SETTINGS_PREFIX = "month_enabled_"


@router.get("/control/settings")
def get_control_settings(db: Session = Depends(get_db)):
    row = db.query(SystemSetting).filter(SystemSetting.key == CONTROL_KEY).first()
    log_row = db.query(SystemSetting).filter(SystemSetting.key == LOGGING_KEY).first()
    return {
        "auto_disable_null_indicators": (row.value == "true") if row else False,
        "structured_logging_enabled": (log_row.value == "true") if log_row else True,
    }


@router.put("/control/settings")
def update_control_settings(updates: dict = Body(...), db: Session = Depends(get_db)):
    updated = {}
    for key in (CONTROL_KEY, LOGGING_KEY):
        if key in updates:
            val = str(updates[key]).lower()
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row:
                row.value = val
            else:
                db.add(SystemSetting(key=key, value=val))
            updated[key] = val == "true"
    db.commit()
    # Update runtime logging flag immediately
    if LOGGING_KEY in updated:
        from app.monitoring import set_logging_enabled
        set_logging_enabled(updated[LOGGING_KEY])
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
    return get_ai_config(db)


@router.put("/ai/settings")
def update_ai_settings(updates: dict, db: Session = Depends(get_db)):
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
