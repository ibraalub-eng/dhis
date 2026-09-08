"""Regression tests for app.cache file persistence and invalidation.

Guards against the Windows/NTFS alternate-data-stream bug: cache keys like
"analysis:months" were written to files with colons in the name, so the
data landed in a hidden stream of a 0-byte file that never matched the
"*.json" filter — full cache invalidation silently missed it and stale
months/results were served for up to 24h after an upload.
"""
import os

import pytest

from app.cache import _CACHE_DIR, cache


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.invalidate()  # clear everything before and after
    yield
    cache.invalidate()


def _cache_files():
    try:
        return {f for f in os.listdir(_CACHE_DIR) if os.path.isfile(os.path.join(_CACHE_DIR, f))}
    except OSError:
        return set()


def test_set_get_roundtrip_colon_key():
    """Keys with colons/pipes must roundtrip and persist to a valid filename."""
    cache.set("analysis:months", ["2026-06", "2026-07"])
    assert cache.get("analysis:months") == ["2026-06", "2026-07"]
    # File must have a sanitized name (no colon => no NTFS alternate data stream)
    files = _cache_files()
    assert "analysis_months.json" in files
    assert not any(":" in f for f in files)


def test_make_key_colon_sanitized():
    """make_key() output (contains '|' and ':') must roundtrip through the cache."""
    key = cache.make_key("v2|analysis:quality-trend", hospital_id=1)
    cache.set(key, {"month": "2026-08"})
    assert cache.get(key) == {"month": "2026-08"}
    assert not any(":" in f for f in _cache_files())


def test_full_invalidate_clears_memory_and_file():
    """invalidate() with no prefix must clear memory AND every cache file."""
    cache.set("analysis:months", ["2026-06"])
    assert cache.get("analysis:months") == ["2026-06"]
    # Plant a fake legacy artifact that does not end in .json (the old
    # Windows ADS base file) — full invalidation must remove it too.
    legacy = os.path.join(_CACHE_DIR, "analysis")
    with open(legacy, "w") as f:
        f.write("")
    cache.invalidate()
    assert cache.get("analysis:months") is None
    assert _cache_files() == set()


def test_prefix_invalidate_clears_file_for_colon_keys():
    """Prefix invalidation must remove the on-disk file for colon keys."""
    cache.set("analysis:months", ["2026-06"])
    cache.set("analysis:quality-trend|hospital_id=1", {"month": "2026-06"})
    cache.invalidate("analysis")
    assert cache.get("analysis:months") is None
    assert cache.get("analysis:quality-trend|hospital_id=1") is None
    assert not any(f.startswith("analysis") for f in _cache_files())