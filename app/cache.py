import time
import json
import threading
import os
from typing import Any, Optional

# File-based cache directory for persistent caching across restarts
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


_ILLEGAL_FILENAME_CHARS = ("/", "|", ":", "\\", "*", "?", '"', "<", ">")


def _safe_filename(key: str) -> str:
    """Make a cache key safe as a filename on Windows.

    Cache keys contain colons and pipes (e.g. "analysis:months" or
    "v2|reports|month=2026-08"). On Windows/NTFS a colon in a filename
    creates an alternate data stream, so the data is hidden in a 0-byte
    "base" file that never matches "*.json" — which broke cache
    invalidation after uploads (stale months/results kept being served).
    """
    for ch in _ILLEGAL_FILENAME_CHARS:
        key = key.replace(ch, "_")
    return key


def _epoch_tag(epoch: Any) -> str:
    """Short filename-safe tag for an epoch value (None -> legacy)."""
    if epoch is None:
        return "legacy"
    return _safe_filename(str(epoch))[-40:]


class TTLCache:
    """Process-wide TTL cache with memory + file persistence.

    Every entry is scoped to a *data epoch* — a fingerprint of the database
    content captured when the cache was written. Any wholesale DB change
    (dump restore, re-import, purge) produces a different epoch, so all
    previously cached entries become unreachable without touching them:
    restoring a snapshot can no longer leave the app serving a day of
    phantom months/hospitals/scores from stale files.
    """

    def __init__(self, default_ttl: int = 86400):  # 24 hours default
        self._default_ttl = default_ttl
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    # ---- data epoch -------------------------------------------------
    def _epoch(self) -> Optional[str]:
        from app.cache import get_data_epoch
        return get_data_epoch()

    # ---- memory layer ----------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        epoch = self._epoch()
        with self._lock:
            entry = self._cache.get((epoch, key))
            if entry is not None:
                expiry, json_str = entry
                if time.time() > expiry:
                    del self._cache[(epoch, key)]
                else:
                    return json.loads(json_str)

        # Fall back to file cache
        return self._get_file(key, epoch)

    def _get_file(self, key: str, epoch: Optional[str]) -> Optional[Any]:
        try:
            safe_key = _safe_filename(key)
            tag = _epoch_tag(epoch)
            # Current epoch first, then the legacy (un-scoped) file — a cache
            # written before epochs existed must never be trusted.
            tag = _epoch_tag(epoch)
            current_name = f"{safe_key}__e{tag}.json" if tag != "legacy" else f"{safe_key}.json"
            for fname in (current_name,):
                path = os.path.join(_CACHE_DIR, fname)
                if not os.path.exists(path):
                    continue
                # Check file age
                age = time.time() - os.path.getmtime(path)
                if age > self._default_ttl:
                    os.remove(path)
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Also set in memory cache
                with self._lock:
                    self._cache[(epoch, key)] = (time.time() + self._default_ttl, json.dumps(data, default=str))
                return data
            return None
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        json_str = json.dumps(self._prepare(value), default=str)
        epoch = self._epoch()
        with self._lock:
            self._cache[(epoch, key)] = (time.time() + ttl, json_str)

        # Also persist to file for restart resilience
        try:
            safe_key = _safe_filename(key)
            tag = _epoch_tag(epoch)
            path = os.path.join(_CACHE_DIR, f"{safe_key}__e{tag}.json")
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
                # Clear the whole file cache. Delete every file (not only
                # "*.json"): older cache files created before filename
                # sanitization may not end in .json on Windows.
                try:
                    for name in os.listdir(_CACHE_DIR):
                        path = os.path.join(_CACHE_DIR, name)
                        if os.path.isfile(path):
                            os.remove(path)
                except Exception:
                    pass
            else:
                expired = [k for k in self._cache if k[1].startswith(key_prefix)]
                for k in expired:
                    del self._cache[k]
                # Clear matching file cache (prefix sanitized the same way
                # as file names so colon/pipe keys match)
                try:
                    file_prefix = _safe_filename(key_prefix)
                    for name in os.listdir(_CACHE_DIR):
                        if name.startswith(file_prefix):
                            os.remove(os.path.join(_CACHE_DIR, name))
                except Exception:
                    pass

    def sweep_stale_epochs(self, keep_epoch: Optional[str]) -> int:
        """Delete cache files belonging to other/legacy epochs.

        Runs at startup after the epoch fingerprint is computed: cache files
        written by a previous data state (or before epochs existed) are
        garbage — no endpoint can ever read them again because lookups are
        epoch-scoped, so they are removed instead of lingering for a day.
        """
        removed = 0
        keep_tag = _epoch_tag(keep_epoch)
        with self._lock:
            dead = [k for k in self._cache if k[0] != keep_epoch]
            for k in dead:
                del self._cache[k]
        try:
            for name in os.listdir(_CACHE_DIR):
                if not name.endswith(".json"):
                    continue  # legacy ADS base files handled by invalidate()
                base = name[:-5]
                if "__e" not in base:
                    os.remove(os.path.join(_CACHE_DIR, name))  # legacy file
                    removed += 1
                    continue
                tag = base.rsplit("__e", 1)[1]
                if tag != keep_tag:
                    os.remove(os.path.join(_CACHE_DIR, name))
                    removed += 1
        except Exception:
            pass
        return removed

    @staticmethod
    def make_key(path: str, **params: Any) -> str:
        parts = [path]
        for k, v in sorted(params.items()):
            if v is not None:
                parts.append(f"{k}={v}")
        return "v2|" + "|".join(parts)


# ---------------------------------------------------------------------------
# Data epoch — fingerprint of the database content.
#
# Computed once per process after startup (and refreshable via
# refresh_data_epoch()); the cache keys/files are scoped to it. If the
# database is restored/replaced while the app runs (or between runs), the
# fingerprint changes and every previously cached entry becomes unreachable
# — the class of "poisoned cache" bugs (restore left an empty heatmap,
# phantom months in the trend, stale hospitals lists) is eliminated at the
# cache layer instead of endpoint by endpoint.
# ---------------------------------------------------------------------------
_data_epoch: Optional[str] = None
_epoch_lock = threading.Lock()
_EPOCH_CHECK_INTERVAL = 60.0  # seconds between re-fingerprints
_last_epoch_check = 0.0


def compute_data_epoch() -> Optional[str]:
    """Fingerprint the current database content.

    Cheap single-row query over the tables cache payloads are derived from:
    max updated timestamps where available + counts of the small dimension
    tables that change identity (hospitals, rules) + the volatile result
    months. Tolerates missing tables (first boot / partial migrations).
    """
    from sqlalchemy import text
    from app.database import SessionLocal

    parts = []
    try:
        db = SessionLocal()
        try:
            # Monotonic content stamps (NULL if the DB is empty)
            for sql in (
                "SELECT COALESCE(MAX(month), '') FROM indicator_values",
                "SELECT COALESCE(COUNT(*), 0) FROM indicator_values",
                "SELECT COALESCE(COUNT(*), 0) FROM quality_scores",
                "SELECT COALESCE(COUNT(*), 0) FROM hospitals",
                "SELECT COALESCE(COUNT(*), 0) FROM rules",
                "SELECT COALESCE(COUNT(*), 0) FROM users",
            ):
                try:
                    parts.append(str(db.execute(text(sql)).scalar()))
                except Exception:
                    parts.append("?")
        finally:
            db.close()
    except Exception:
        return None  # DB unreachable — caller keeps previous epoch / None
    return "e-" + "-".join(parts)


def get_data_epoch() -> Optional[str]:
    """Return the process-wide epoch, computing/refreshing it lazily.

    Re-fingerprints at most once per _EPOCH_CHECK_INTERVAL so a database
    restored while the app keeps running self-heals within a minute even
    if nobody calls refresh_data_epoch(). The fingerprint is a handful of
    indexed COUNT/MAX queries — negligible next to any cached payload.
    """
    global _data_epoch, _last_epoch_check
    now = time.time()
    if _data_epoch is not None and now - _last_epoch_check < _EPOCH_CHECK_INTERVAL:
        return _data_epoch
    with _epoch_lock:
        # Re-check under the lock (another thread may have refreshed)
        now = time.time()
        if _data_epoch is None or now - _last_epoch_check >= _EPOCH_CHECK_INTERVAL:
            new_epoch = compute_data_epoch()
            if new_epoch is not None:
                if new_epoch != _data_epoch and _data_epoch is not None:
                    _prune_memory_except(new_epoch)
                _data_epoch = new_epoch
            _last_epoch_check = now
    return _data_epoch


def _prune_memory_except(new_epoch: Optional[str]) -> None:
    """Drop in-memory entries that belong to another epoch (best effort)."""
    try:
        cache_inst = globals().get("cache")
        if cache_inst is None:
            return
        with cache_inst._lock:
            dead = [k for k in cache_inst._cache if k[0] != new_epoch]
            for k in dead:
                del cache_inst._cache[k]
    except Exception:
        pass


def refresh_data_epoch() -> Optional[str]:
    """Recompute the epoch immediately after a known wholesale DB change.

    Callers: restore scripts, purge_ghost_results, big imports. Every cache
    entry written under the previous epoch becomes instantly unreachable.
    """
    global _data_epoch, _last_epoch_check
    new_epoch = compute_data_epoch()
    with _epoch_lock:
        if new_epoch is not None:
            if new_epoch != _data_epoch and _data_epoch is not None:
                _prune_memory_except(new_epoch)
            _data_epoch = new_epoch
        _last_epoch_check = time.time()
    return _data_epoch


def reset_data_epoch_for_tests() -> None:
    """Tests: drop back to lazy computation with an isolated cache dir."""
    global _data_epoch, _last_epoch_check
    with _epoch_lock:
        _data_epoch = None
        _last_epoch_check = 0.0


# 24-hour cache for smart analytics (persistent across restarts)
cache = TTLCache(default_ttl=86400)
