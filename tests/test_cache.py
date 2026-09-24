"""Regression tests for app.cache file persistence and invalidation.

Guards against the Windows/NTFS alternate-data-stream bug: cache keys like
"analysis:months" were written to files with colons in the name, so the
data landed in a hidden stream of a 0-byte file that never matched the
"*.json" filter — full cache invalidation silently missed it and stale
months/results were served for up to 24h after an upload.
"""
import os

import pytest

from app.cache import cache


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.invalidate()  # clear everything before and after
    yield
    cache.invalidate()


def _cache_dir():
    """Current cache dir (tests redirect it via conftest, read lazily)."""
    from app.cache import _CACHE_DIR
    return _CACHE_DIR


def _cache_files():
    """List cache files in the CURRENT _CACHE_DIR (tests redirect it to a
    temp dir via conftest._isolate_cache_dir, so it must be read lazily)."""
    try:
        return {f for f in os.listdir(_cache_dir()) if os.path.isfile(os.path.join(_cache_dir(), f))}
    except OSError:
        return set()


def test_set_get_roundtrip_colon_key():
    """Keys with colons/pipes must roundtrip and persist to a valid filename."""
    cache.set("analysis:months", ["2026-06", "2026-07"])
    assert cache.get("analysis:months") == ["2026-06", "2026-07"]
    # File must have a sanitized name (no colon => no NTFS alternate data stream)
    files = _cache_files()
    assert any(f.startswith("analysis_months") and f.endswith(".json") for f in files)
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
    legacy = os.path.join(_cache_dir(), "analysis")
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


def test_epoch_rotation_orphans_old_entries(monkeypatch):
    """THE poisoned-cache killer: rotating the data epoch (after a dump
    restore / wholesale re-import) must make every entry written under the
    previous data state unreachable — memory AND file — without deleting
    them one by one, and must never serve a pre-epoch legacy file."""
    import app.cache as cache_mod

    monkeypatch.setattr(cache_mod, "get_data_epoch", lambda: "epoch-A")
    cache.set("analysis:months", ["2026-01"])
    cache.set(cache.make_key("analysis:heatmap_v2"), {"months": ["2026-01"], "data": [[90]]})
    assert cache.get("analysis:months") == ["2026-01"]

    # DB restored → content fingerprint changes → new epoch
    monkeypatch.setattr(cache_mod, "get_data_epoch", lambda: "epoch-B")
    assert cache.get("analysis:months") is None
    assert cache.get(cache.make_key("analysis:heatmap_v2")) is None

    # New data can be cached under the new epoch without interference
    cache.set("analysis:months", ["2026-01", "2026-02"])
    assert cache.get("analysis:months") == ["2026-01", "2026-02"]
    # ...and the old-epoch file still exists on disk but is unreachable
    assert any("epoch-A" in f for f in _cache_files())


def test_sweep_stale_epochs_removes_other_epoch_files(monkeypatch):
    """Startup sweep deletes files from foreign/legacy epochs (disk garbage
    that no lookup can reach anymore) and keeps only the current epoch."""
    import app.cache as cache_mod

    monkeypatch.setattr(cache_mod, "get_data_epoch", lambda: "epoch-B")
    cache.set("analysis:months", ["2026-01"])
    # Simulate leftovers: a legacy pre-epoch file + another epoch's file
    legacy_name = cache_mod._safe_filename("analysis:months") + ".json"
    with open(os.path.join(_cache_dir(), legacy_name), "w") as f:
        f.write('["2027-01"]')
    other_name = cache_mod._safe_filename("analysis:months") + "__eepoch-X.json"
    with open(os.path.join(_cache_dir(), other_name), "w") as f:
        f.write('["2026-99"]')

    removed = cache.sweep_stale_epochs("epoch-B")
    assert removed >= 2
    files = _cache_files()
    assert other_name not in files
    assert legacy_name not in files
    # current-epoch file survives and stays readable
    assert cache.get("analysis:months") == ["2026-01"]


def test_legacy_unscoped_file_never_served(monkeypatch):
    """A cache file written before epoch scoping (no __e tag) must never be
    read — it could contain data from any previous data state."""
    import app.cache as cache_mod

    monkeypatch.setattr(cache_mod, "get_data_epoch", lambda: "epoch-B")
    legacy_name = cache_mod._safe_filename("analysis:months") + ".json"
    with open(os.path.join(_cache_dir(), legacy_name), "w") as f:
        f.write('["2027-01"]')
    assert cache.get("analysis:months") is None


def test_epoch_auto_refresh_detects_restore(monkeypatch):
    """A DB restored while the app keeps running must self-heal: when the
    fingerprint changes, get_data_epoch rotates the epoch and old-epoch
    memory entries become unreachable — even if nobody called
    refresh_data_epoch() (that path is tested above)."""
    import app.cache as cache_mod

    # Simulate: epoch computed at startup, months cached; then the DB is
    # restored and the next fingerprint sees different content.
    epochs = iter(["epoch-A", "epoch-B"])
    monkeypatch.setattr(cache_mod, "compute_data_epoch", lambda: next(epochs))
    monkeypatch.setattr(cache_mod, "_data_epoch", None)
    monkeypatch.setattr(cache_mod, "_last_epoch_check", 0.0)

    assert cache_mod.get_data_epoch() == "epoch-A"   # first compute
    cache.set("analysis:months", ["2026-01"])
    assert cache.get("analysis:months") == ["2026-01"]

    # Interval elapsed + DB content changed → fingerprint returns epoch-B
    cache_mod._last_epoch_check = 0.0  # backdate: 60s re-check window passed
    assert cache_mod.get_data_epoch() == "epoch-B"   # rotation detected
    assert cache.get("analysis:months") is None      # stale entry orphaned


def test_epoch_refresh_prunes_memory_only_new_epoch_survives(monkeypatch):
    """refresh_data_epoch() must prune other-epoch entries from memory so
    the cache dict does not grow unbounded across restorations."""
    import app.cache as cache_mod

    monkeypatch.setattr(cache_mod, "compute_data_epoch", lambda: "epoch-A")
    monkeypatch.setattr(cache_mod, "_data_epoch", None)
    monkeypatch.setattr(cache_mod, "_last_epoch_check", 0.0)
    cache.set("analysis:months", ["2026-01"])

    monkeypatch.setattr(cache_mod, "compute_data_epoch", lambda: "epoch-B")
    cache_mod.refresh_data_epoch()
    cache.set("analysis:months", ["2026-01", "2026-02"])

    monkeypatch.setattr(cache_mod, "compute_data_epoch", lambda: "epoch-C")
    cache_mod.refresh_data_epoch()
    # epoch-B memory entry pruned AND its epoch-B file unreachable (fresh
    # fingerprint never reads it), so the pre-C value cannot resurface.
    assert cache.get("analysis:months") is None
    cache.set("analysis:months", ["2026-03"])
    assert cache.get("analysis:months") == ["2026-03"]