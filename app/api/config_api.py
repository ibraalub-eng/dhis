from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AppConfig, SystemSetting
from app.config_utils import AI_CONFIG_KEYS, get_ai_config

router = APIRouter(prefix="/config", tags=["config"])

CONTROL_KEY = "auto_disable_null_indicators"


@router.get("/control/settings")
def get_control_settings(db: Session = Depends(get_db)):
    row = db.query(SystemSetting).filter(SystemSetting.key == CONTROL_KEY).first()
    return {"auto_disable_null_indicators": (row.value == "true") if row else False}


@router.put("/control/settings")
def update_control_settings(updates: dict, db: Session = Depends(get_db)):
    val = str(updates.get(CONTROL_KEY, "false")).lower()
    row = db.query(SystemSetting).filter(SystemSetting.key == CONTROL_KEY).first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=CONTROL_KEY, value=val))
    db.commit()
    return {"status": "ok", CONTROL_KEY: val == "true"}


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
