import time
import json
import threading
import os
from typing import Any, Optional

# File-based cache directory for persistent caching across restarts
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


class TTLCache:
    def __init__(self, default_ttl: int = 86400):  # 24 hours default
        self._default_ttl = default_ttl
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            # Check memory cache first
            entry = self._cache.get(key)
            if entry is not None:
                expiry, json_str = entry
                if time.time() > expiry:
                    del self._cache[key]
                else:
                    return json.loads(json_str)

        # Fall back to file cache
        return self._get_file(key)

    def _get_file(self, key: str) -> Optional[Any]:
        try:
            safe_key = key.replace("/", "_").replace("|", "_")
            path = os.path.join(_CACHE_DIR, f"{safe_key}.json")
            if not os.path.exists(path):
                return None
            # Check file age
            age = time.time() - os.path.getmtime(path)
            if age > self._default_ttl:
                os.remove(path)
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Also set in memory cache
            with self._lock:
                self._cache[key] = (time.time() + self._default_ttl, json.dumps(data, default=str))
            return data
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        json_str = json.dumps(self._prepare(value), default=str)
        with self._lock:
            self._cache[key] = (time.time() + ttl, json_str)

        # Also persist to file for restart resilience
        try:
            safe_key = key.replace("/", "_").replace("|", "_")
            path = os.path.join(_CACHE_DIR, f"{safe_key}.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception:
            pass

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
                # Clear file cache too
                try:
                    for f in os.listdir(_CACHE_DIR):
                        if f.endswith(".json"):
                            os.remove(os.path.join(_CACHE_DIR, f))
                except Exception:
                    pass
            else:
                expired = [k for k in self._cache if k.startswith(key_prefix)]
                for k in expired:
                    del self._cache[k]
                # Clear matching file cache
                try:
                    for f in os.listdir(_CACHE_DIR):
                        if f.startswith(key_prefix.replace("/", "_").replace("|", "_")):
                            os.remove(os.path.join(_CACHE_DIR, f))
                except Exception:
                    pass

    @staticmethod
    def make_key(path: str, **params: Any) -> str:
        parts = [path]
        for k, v in sorted(params.items()):
            if v is not None:
                parts.append(f"{k}={v}")
        return "v2|" + "|".join(parts)


# 24-hour cache for smart analytics (persistent across restarts)
cache = TTLCache(default_ttl=86400)
