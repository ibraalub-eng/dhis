AI_CONFIG_KEYS = {
    "ai_enabled": "true",
    "ai_provider": "gemini",
    "ai_api_key": "",
    "ai_model": "gemini-2.0-flash-lite",
    "ai_api_url": "",
    "ai_max_recommendations": "8",
    "ai_timeout": "30",
}


def get_config_value(db, key: str, default: float = 0.0) -> float:
    from app.models import AppConfig
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    return row.value if row else default


def get_config_dict(db, category: str) -> dict:
    from app.models import AppConfig
    rows = db.query(AppConfig).filter(AppConfig.category == category).all()
    return {r.key: r.value for r in rows}


def get_ai_config(db) -> dict:
    from app.models import SystemSetting
    rows = db.query(SystemSetting).all()
    stored = {r.key: r.value for r in rows}
    result = {}
    for k, default in AI_CONFIG_KEYS.items():
        result[k] = stored.get(k, default)
    return result
