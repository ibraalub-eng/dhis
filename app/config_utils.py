AI_CONFIG_KEYS = {
    "ai_enabled": "true",
    "ai_provider": "gemini",
    "ai_api_key": "",
    "ai_model": "gemini-3.5-flash-lite",
    "ai_api_url": "",
    "ai_max_recommendations": "8",
    "ai_timeout": "30",
}


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
