import time
import json
import threading
from typing import Any, Optional


class TTLCache:
    def __init__(self, default_ttl: int = 300):
        self._default_ttl = default_ttl
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expiry, json_str = entry
            if time.time() > expiry:
                del self._cache[key]
                return None
            return json.loads(json_str)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            expiry = time.time() + (ttl if ttl is not None else self._default_ttl)
            self._cache[key] = (expiry, json.dumps(self._prepare(value), default=str))

    @staticmethod
    def _prepare(obj: Any) -> Any:
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if isinstance(obj, list):
            return [TTLCache._prepare(item) for item in obj]
        if isinstance(obj, dict):
            return {k: TTLCache._prepare(v) for k, v in obj.items()}
        if hasattr(obj, "__table__"):
            return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
        return obj

    def invalidate(self, key_prefix: str = "") -> None:
        with self._lock:
            if not key_prefix:
                self._cache.clear()
            else:
                expired = [k for k in self._cache if k.startswith(key_prefix)]
                for k in expired:
                    del self._cache[k]

    @staticmethod
    def make_key(path: str, **params: Any) -> str:
        parts = [path]
        for k, v in sorted(params.items()):
            if v is not None:
                parts.append(f"{k}={v}")
        return "v2|" + "|".join(parts)


cache = TTLCache(default_ttl=300)
