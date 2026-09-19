AI_CONFIG_KEYS = {
    "ai_enabled": "true",
    "ai_provider": "gemini",
    "ai_api_key": "",
    "ai_model": "gemini-3.5-flash-lite",
    "ai_api_url": "",
    "ai_max_recommendations": "8",
    "ai_timeout": "30",
    "agents_enabled": "false",
    "agents_provider": "auto",
    "agent_provider_roles": "{}",
    "local_runtime": "ollama",
    "local_model": "qwen3:8b",
    "local_url": "http://localhost:11434",
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


AGENT_PROFILES = ("qa", "explainer", "report_writer", "triage")
AGENT_PROVIDERS = ("local", "gemini", "openai_compatible")


def validate_agents_config(updates: dict) -> None:
    """Validate agent-layer settings. Raises ValueError on invalid input."""
    import json as _json
    provider = updates.get("agents_provider")
    if provider is not None and provider not in ("local", "gemini", "openai_compatible", "auto"):
        raise ValueError(f"Invalid agents_provider: {provider}")
    roles_raw = updates.get("agent_provider_roles")
    if roles_raw is not None:
        try:
            roles = _json.loads(roles_raw)
        except (TypeError, ValueError):
            raise ValueError("agent_provider_roles must be a JSON object")
        if not isinstance(roles, dict):
            raise ValueError("agent_provider_roles must be a JSON object")
        for role, prov in roles.items():
            if role not in AGENT_PROFILES:
                raise ValueError(f"Unknown agent profile: {role}")
            if prov not in AGENT_PROVIDERS:
                raise ValueError(f"Invalid provider for {role}: {prov}")
