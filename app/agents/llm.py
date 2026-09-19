"""Provider abstraction for the agent runtime.

The agent layer uses its own provider resolution (agents_provider +
agent_provider_roles) and MUST NOT disturb the existing single-shot ai_provider
path. Local (Ollama) is an OpenAI-compatible endpoint with no API key.
"""
import json
import socket
from dataclasses import dataclass

from app.config_utils import get_ai_config, AGENT_PROVIDERS


@dataclass
class ResolvedProvider:
    provider: str
    model: str
    base_url: str = ""
    needs_key: bool = True


@dataclass
class ChatResult:
    text: str | None
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _local_reachable(url: str, timeout: float = 1.0) -> bool:
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    port = 11434
    if ":" in url.split("://")[-1].split("/")[0]:
        try:
            port = int(url.split("://")[-1].split("/")[0].split(":")[1])
        except ValueError:
            pass
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _provider_viable(kind: str, cfg: dict) -> bool:
    """True when the provider is configured/reachable enough to attempt a run."""
    if kind == "local":
        return bool(cfg.get("local_model")) and _local_reachable(
            (cfg.get("local_url") or "http://localhost:11434").strip("/"))
    if kind == "gemini":
        return bool(cfg.get("ai_api_key"))
    if kind == "openai_compatible":
        return bool(cfg.get("ai_api_url"))
    return False


def _validate_roles_map(roles: dict) -> None:
    """Mirror validate_agents_config in app/config_utils.py: any unknown role
    or invalid provider value in the roles map is a hard error."""
    from app.config_utils import AGENT_PROFILES, AGENT_PROVIDERS
    for role, prov in roles.items():
        if role not in AGENT_PROFILES:
            raise ValueError(f"Unknown agent profile: {role}")
        if prov not in AGENT_PROVIDERS:
            raise ValueError(f"Invalid provider for {role}: {prov}")


def resolve_agent_provider(profile: str, db) -> ResolvedProvider:
    cfg = get_ai_config(db)
    roles_raw = cfg.get("agent_provider_roles") or "{}"
    try:
        roles = json.loads(roles_raw) if isinstance(roles_raw, str) else (roles_raw or {})
    except (TypeError, ValueError):
        roles = {}
    _validate_roles_map(roles)
    mapped = roles.get(profile)
    if mapped in AGENT_PROVIDERS and _provider_viable(mapped, cfg):
        return _build_provider(mapped, cfg)
    # mapped-but-down (or unmapped) falls through to the global agents_provider,
    # exactly per spec §3: "A mapped provider that is down degrades to step 2"
    global_provider = (cfg.get("agents_provider") or "auto").lower()
    if global_provider == "auto":
        return _resolve_auto(cfg)
    if global_provider in ("local", "gemini", "openai_compatible"):
        return _build_provider(global_provider, cfg)
    raise ValueError(f"Invalid agents_provider: {global_provider}")


def _resolve_auto(cfg: dict) -> ResolvedProvider:
    local_url = (cfg.get("local_url") or "http://localhost:11434").strip("/")
    if cfg.get("local_model") and _local_reachable(local_url):
        return _build_provider("local", cfg)
    if cfg.get("ai_api_key"):
        return _build_provider("gemini", cfg)
    if cfg.get("ai_api_url"):
        return _build_provider("openai_compatible", cfg)
    return _build_provider("local", cfg)   # runtime will fall back deterministically


def _build_provider(kind: str, cfg: dict) -> ResolvedProvider:
    if kind == "local":
        url = (cfg.get("local_url") or "http://localhost:11434").strip("/")
        return ResolvedProvider("local", cfg.get("local_model") or "qwen3:8b",
                                url + "/v1/chat/completions", needs_key=False)
    if kind == "gemini":
        return ResolvedProvider("gemini", cfg.get("ai_model") or "gemini-3.5-flash-lite", "", True)
    return ResolvedProvider("openai_compatible",
                            cfg.get("ai_model") or "deepseek-chat",
                            cfg.get("ai_api_url") or "", True)


def _lookup_api_key() -> str:
    """Return ai_api_key from SystemSetting without importing app.main."""
    from app.database import SessionLocal
    try:
        from app.models import SystemSetting
        with SessionLocal() as s:
            row = s.query(SystemSetting).filter(SystemSetting.key == "ai_api_key").first()
            return row.value if row and row.value else ""
    except Exception:
        return ""


def llm_chat(resolved: ResolvedProvider, system: str, user: str,
             max_output_tokens: int = 3000, timeout: float = 30.0) -> ChatResult | None:
    api_key = _lookup_api_key() if resolved.needs_key else ""
    if resolved.provider == "gemini":
        return _chat_gemini(resolved, system, user, max_output_tokens, timeout)
    return _chat_httpx(resolved, system, user, api_key, max_output_tokens, timeout)


def _chat_httpx(resolved, system, user, api_key, max_output_tokens, timeout):
    import httpx
    payload = {
        "model": resolved.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(resolved.base_url, json=payload, headers=headers)
            code = resp.status_code
            retry_after = resp.headers.get("Retry-After")
            if code == 429 and retry_after:
                import time as _t
                _t.sleep(min(float(retry_after.split()[0]), 5.0))
                resp = client.post(resolved.base_url, json=payload, headers=headers)
            elif code == 429:
                import time as _t
                _t.sleep(1.0)
                resp = client.post(resolved.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return ChatResult(content, resolved.provider, resolved.model,
                      usage.get("prompt_tokens", len(system) // 4),
                      usage.get("completion_tokens", len(content or "") // 4))