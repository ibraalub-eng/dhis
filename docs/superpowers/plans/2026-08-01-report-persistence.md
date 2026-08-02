# Comprehensive Report Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the AI-generated comprehensive report once per month (per language) in the existing `analysis_cache` table so it is not regenerated on every request — keeping AI calls within quota.

**Architecture:** Reuse the existing `analysis_cache` table. Add a small `report_cache.py` module with get/store/invalidate helpers keyed by `comparative_report:{month}:{lang}`. `generate_comprehensive_report` checks the store first; on a hit it returns the stored result without running analytics or calling AI. Only AI-generated reports are stored — local fallback reports are returned but never persisted (so AI is retried on the next request). Upload endpoints invalidate the store so reports refresh when data changes.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (SQLite), pytest.

## Global Constraints

- Reuse the `analysis_cache` table (`app/models.py:269` — class `AnalysisCache`). No schema migration.
- Cache key format is exactly `comparative_report:{month}:{lang}`.
- Only `report_source == "ai"` results are stored. `report_source == "local"` results are never stored.
- Stored JSON must convert numpy scalars/arrays to native Python types (never strings).
- All new tests go in `tests/test_comparative.py`.
- Verify with: `python -m pytest tests/test_comparative.py -q` (all must pass).
- Commit after each task with the exact message given.

---

### Task 1: Report Cache Module

**Files:**
- Create: `app/engine/comparative/report_cache.py`
- Test: `tests/test_comparative.py` (append the cache tests section)

**Interfaces:**
- Produces (consumed by Task 2, Task 4):
  - `get_stored_report(session, month: str, lang: str) -> Optional[Dict[str, Any]]`
  - `store_report(session, month: str, lang: str, result: Dict[str, Any]) -> None`
  - `invalidate_report_cache(session, month: Optional[str] = None) -> int`
  - Constant `REPORT_CACHE_PREFIX = "comparative_report:"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_comparative.py`:

```python
# --- Report Persistence Cache Tests ---


def test_report_cache_store_and_get(db_session):
    from app.engine.comparative.report_cache import store_report, get_stored_report
    result = {"month": "2026-06", "report": "text", "report_source": "ai", "data": {"kpi": {}}}
    store_report(db_session, "2026-06", "ar", result)
    cached = get_stored_report(db_session, "2026-06", "ar")
    assert cached == result


def test_report_cache_get_missing(db_session):
    from app.engine.comparative.report_cache import get_stored_report
    assert get_stored_report(db_session, "2026-06", "ar") is None


def test_report_cache_separated_by_lang(db_session):
    from app.engine.comparative.report_cache import store_report, get_stored_report
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "ar"})
    store_report(db_session, "2026-06", "en", {"month": "2026-06", "report": "en"})
    assert get_stored_report(db_session, "2026-06", "ar")["report"] == "ar"
    assert get_stored_report(db_session, "2026-06", "en")["report"] == "en"


def test_report_cache_invalidate_month(db_session):
    from app.engine.comparative.report_cache import (
        store_report, get_stored_report, invalidate_report_cache,
    )
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "r"})
    store_report(db_session, "2026-05", "ar", {"month": "2026-05", "report": "r"})
    invalidate_report_cache(db_session, "2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is None
    assert get_stored_report(db_session, "2026-05", "ar") is not None


def test_report_cache_invalidate_all(db_session):
    from app.engine.comparative.report_cache import (
        store_report, get_stored_report, invalidate_report_cache,
    )
    store_report(db_session, "2026-06", "ar", {"month": "2026-06", "report": "r"})
    store_report(db_session, "2026-05", "en", {"month": "2026-05", "report": "r"})
    invalidate_report_cache(db_session)
    assert get_stored_report(db_session, "2026-06", "ar") is None
    assert get_stored_report(db_session, "2026-05", "en") is None


def test_report_cache_sanitizes_numpy_types(db_session):
    import numpy as np
    from app.engine.comparative.report_cache import store_report, get_stored_report
    result = {
        "month": "2026-06",
        "report": "x",
        "report_source": "ai",
        "data": {"score": np.float64(0.45), "count": np.int64(7)},
    }
    store_report(db_session, "2026-06", "ar", result)
    cached = get_stored_report(db_session, "2026-06", "ar")
    assert cached["data"]["score"] == 0.45
    assert isinstance(cached["data"]["score"], float)
    assert cached["data"]["count"] == 7
    assert isinstance(cached["data"]["count"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comparative.py -k "report_cache" -q`
Expected: ERROR at collection — `ModuleNotFoundError: No module named 'app.engine.comparative.report_cache'`

- [ ] **Step 3: Create the module**

Create `app/engine/comparative/report_cache.py`:

```python
"""Persistent storage for AI-generated comprehensive reports."""
import json
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.models import AnalysisCache

logger = logging.getLogger(__name__)

REPORT_CACHE_PREFIX = "comparative_report:"


def _cache_key(month: str, lang: str) -> str:
    return f"{REPORT_CACHE_PREFIX}{month}:{lang}"


def _sanitize(obj: Any) -> Any:
    """Convert numpy types and dataclasses to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (int, float, str, bool)):
        try:
            return obj.item()
        except (ValueError, AttributeError):
            return str(obj)
    if hasattr(obj, "tolist") and not isinstance(obj, (list, tuple)):
        return _sanitize(obj.tolist())
    if hasattr(obj, "__dict__") and not isinstance(obj, (int, float, str, bool)):
        return _sanitize(vars(obj))
    return obj


def get_stored_report(session: Session, month: str, lang: str) -> Optional[Dict[str, Any]]:
    """Return the stored report for a month/lang, or None if absent."""
    row = session.query(AnalysisCache).filter(
        AnalysisCache.cache_key == _cache_key(month, lang)
    ).first()
    if not row:
        return None
    try:
        return json.loads(row.result_json)
    except Exception as e:
        logger.warning(f"Error reading report cache: {e}")
        return None


def store_report(session: Session, month: str, lang: str, result: Dict[str, Any]) -> None:
    """Persist a report for a month/lang. No expiry (deleted on data change)."""
    key = _cache_key(month, lang)
    payload = json.dumps(_sanitize(result), default=str)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if row:
        row.result_json = payload
        row.expires_at = None
    else:
        row = AnalysisCache(cache_key=key, result_json=payload, expires_at=None)
        session.add(row)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to store report: {e}")


def invalidate_report_cache(session: Session, month: Optional[str] = None) -> int:
    """Delete cached reports for a month (or all months if month is None)."""
    if month is None:
        rows = session.query(AnalysisCache).filter(
            AnalysisCache.cache_key.like(f"{REPORT_CACHE_PREFIX}%")
        ).all()
    else:
        rows = session.query(AnalysisCache).filter(
            AnalysisCache.cache_key.like(f"{REPORT_CACHE_PREFIX}{month}:%")
        ).all()
    count = len(rows)
    for row in rows:
        session.delete(row)
    if count:
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to invalidate report cache: {e}")
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comparative.py -k "report_cache" -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/comparative/report_cache.py tests/test_comparative.py
git commit -m "feat: add persistent report cache module"
```

---

### Task 2: Cache Integration into Report Generator

**Files:**
- Modify: `app/engine/comparative/report_generator.py:319` (the `generate_comprehensive_report` function)
- Modify: `app/engine/comparative/report_generator.py:6` (imports)
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `get_stored_report(session, month, lang)`, `store_report(session, month, lang, result)` from Task 1.
- Produces: `generate_comprehensive_report(session, month, lang="ar", use_cache=True) -> Dict[str, Any]` with unchanged result shape (`month`, `report`, `report_source`, `data`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_comparative.py`:

```python
# --- Report Persistence Generator Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_report_cache_hit_returns_stored_without_ai(mock_api, db_session):
    mock_api.return_value = "تقرير AI مخزن"
    first = generate_comprehensive_report(db_session, "2026-06")
    assert first["report_source"] == "ai"
    assert mock_api.call_count == 1
    second = generate_comprehensive_report(db_session, "2026-06")
    assert second["report"] == first["report"]
    assert second["report_source"] == first["report_source"]
    assert mock_api.call_count == 1


@patch("app.engine.comparative.report_generator._call_api")
def test_report_cache_separated_by_lang(mock_api, db_session):
    mock_api.return_value = "AI report"
    generate_comprehensive_report(db_session, "2026-06", lang="ar")
    generate_comprehensive_report(db_session, "2026-06", lang="en")
    assert mock_api.call_count == 2


@patch("app.engine.comparative.report_generator._call_api")
def test_local_fallback_not_stored(mock_api, db_session):
    mock_api.return_value = None
    first = generate_comprehensive_report(db_session, "2026-06")
    assert first["report_source"] == "local"
    mock_api.return_value = "تقرير AI"
    second = generate_comprehensive_report(db_session, "2026-06")
    assert second["report_source"] == "ai"
    assert mock_api.call_count == 2


@patch("app.engine.comparative.report_generator._call_api")
def test_use_cache_false_regenerates(mock_api, db_session):
    mock_api.return_value = "الأول"
    generate_comprehensive_report(db_session, "2026-06")
    mock_api.return_value = "الثاني"
    result = generate_comprehensive_report(db_session, "2026-06", use_cache=False)
    assert result["report"] == "الثاني"
    assert mock_api.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comparative.py -k "report_cache_hit or report_cache_separated or local_fallback_not_stored or use_cache_false" -q`
Expected: FAIL — `TypeError: generate_comprehensive_report() got an unexpected keyword argument 'use_cache'` and the cache-hit test still calls AI twice.

- [ ] **Step 3: Implement the change**

Modify the import block at the top of `app/engine/comparative/report_generator.py` (currently lines 1-8):

```python
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
from app.engine.comparative.report_cache import get_stored_report, store_report
from app.plugins.ai.providers import _call_api
```

Replace the entire `generate_comprehensive_report` function (starts at line 319) with:

```python
def generate_comprehensive_report(session: Session, month: str, lang: str = "ar", use_cache: bool = True) -> Dict[str, Any]:
    """توليد تقرير ذكي شامل حسب اللغة مع تخزين للتقرير المولّد بالذكاء الاصطناعي"""

    if use_cache:
        cached = get_stored_report(session, month, lang)
        if cached:
            return cached

    analytics = run_smart_analytics(session, month)

    prompt = build_comprehensive_prompt(analytics, lang)

    report_text = None
    try:
        report_text = _call_api(prompt)
    except Exception:
        logger.error("AI report generation failed; using local fallback", exc_info=True)
    report_source = "ai" if report_text else "local"
    if not report_text:
        report_text = _build_local_report(analytics, lang)

    def _to_dict(obj):
        if obj is None:
            return {}
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return obj

    def _to_list(objs):
        if objs is None:
            return []
        return [_to_dict(o) for o in objs]

    result = {
        "month": month,
        "report": report_text,
        "report_source": report_source,
        "data": {
            "kpi": _to_dict(analytics.kpi),
            "anomalies": _to_list(analytics.anomalies),
            "clustering": _to_dict(analytics.clustering),
            "correlations": _to_dict(analytics.correlations),
            "residuals": _to_list(analytics.residuals),
            "stratified": _to_list(analytics.stratified),
            "explanations": _to_list(analytics.explanations),
            "geo": _to_dict(analytics.geo),
            "xgboost": _to_dict(analytics.xgboost_predictions),
        }
    }

    if report_source == "ai":
        store_report(session, month, lang, result)

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comparative.py -k "report_cache or local_fallback_not_stored or use_cache_false or comprehensive_report" -q`
Expected: all pass (cache tests + existing comprehensive report tests)

- [ ] **Step 5: Commit**

```bash
git add app/engine/comparative/report_generator.py tests/test_comparative.py
git commit -m "feat: cache AI comprehensive reports per month/lang"
```

---

### Task 3: API `force` Query Param

**Files:**
- Modify: `app/api/comparative.py:10-22` (the `get_comprehensive_report` endpoint)
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `generate_comprehensive_report(..., use_cache=...)` from Task 2.
- Produces: endpoint `GET /comparative/comprehensive-report/{month}?lang=ar|en&force=true|false`. When `force=true`, cache is bypassed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comparative.py`:

```python
# --- Report Persistence Endpoint Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_report_endpoint_force_regenerates(mock_api, client):
    mock_api.return_value = "الأول"
    r1 = client.get("/comparative/comprehensive-report/2026-06")
    assert r1.status_code == 200
    assert r1.json()["report"] == "الأول"
    assert mock_api.call_count == 1
    mock_api.return_value = "الثاني"
    r2 = client.get("/comparative/comprehensive-report/2026-06?force=true")
    assert r2.status_code == 200
    assert r2.json()["report"] == "الثاني"
    assert mock_api.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_comparative.py::test_report_endpoint_force_regenerates -q`
Expected: FAIL — the second request returns "الأول" (cached) instead of "الثاني", because the endpoint never passes `use_cache`.

- [ ] **Step 3: Implement the change**

Modify `app/api/comparative.py` (lines 10-22) to add the `force` param and pass `use_cache=not force`:

```python
@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(
    month: str,
    lang: str = Query("ar", description="لغة التقرير (ar/en)"),
    force: bool = Query(False, description="إعادة توليد التقرير وتجاوز التخزين"),
    db: Session = Depends(get_db)
):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month, lang, use_cache=not force)
        return result
    except Exception as e:
        error_msg = f"Error generating report: {str(e)}" if lang == "en" else f"خطأ في توليد التقرير: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_comparative.py::test_report_endpoint_force_regenerates -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/comparative.py tests/test_comparative.py
git commit -m "feat: add force param to bypass comprehensive report cache"
```

---

### Task 4: Invalidate Report Cache on Upload

**Files:**
- Modify: `app/api/upload.py:130-136` (in `save_manual_entry`)
- Modify: `app/api/upload.py:172-178` (in `/upload/`)
- Modify: `app/api/upload.py:215-221` (in `/upload/analyze`)
- Modify: `app/api/upload.py:14` (imports)
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `invalidate_report_cache(session, month=None)` from Task 1.
- Produces: report store is cleared for the affected month on manual save, and for all months on Excel upload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_comparative.py` (add `import json` to the file if not already present):

```python
# --- Report Persistence Upload Invalidation Tests ---


@patch("app.engine.comparative.report_generator._call_api")
def test_upload_save_invalidates_report_cache(mock_api, client, db_session):
    from app.engine.comparative.report_cache import get_stored_report
    mock_api.return_value = "تقرير AI"
    client.get("/comparative/comprehensive-report/2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is not None
    resp = client.post(
        "/upload/data-entry/save",
        params={"hospital_id": 1, "month": "2026-06", "data": json.dumps({"2": 300})},
    )
    assert resp.status_code == 200
    assert get_stored_report(db_session, "2026-06", "ar") is None


@patch("app.engine.comparative.report_generator._call_api")
def test_upload_excel_invalidates_report_cache(mock_api, client, db_session):
    import io
    import pandas as pd
    from app.engine.comparative.report_cache import get_stored_report
    mock_api.return_value = "تقرير AI"
    client.get("/comparative/comprehensive-report/2026-06")
    assert get_stored_report(db_session, "2026-06", "ar") is not None
    df = pd.DataFrame({
        "organisationunitname": ["General Hospital"],
        "month": ["2026-06"],
        "Total Deliveries": [300],
        "Normal Vaginal Deliveries": [200],
        "Caesarean Sections": [80],
        "Live Births": [290],
        "Maternal Deaths": [1],
        "Neonatal deaths": [5],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    resp = client.post(
        "/upload/",
        files={"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert get_stored_report(db_session, "2026-06", "ar") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comparative.py -k "upload_.*report_cache" -q`
Expected: FAIL — `get_stored_report(db_session, "2026-06", "ar") is not None` is True, but after upload it is still not None (cache not invalidated).

- [ ] **Step 3: Implement the change**

Modify the imports at the top of `app/api/upload.py` (around line 14):

```python
from app.cache import cache
from app.engine.comparative.report_cache import invalidate_report_cache
```

In `save_manual_entry`, after the existing `cache.invalidate("smart_geo_")` line (line 136), add:

```python
    invalidate_report_cache(db, month)
```

In `/upload/`, after the existing `cache.invalidate("smart_geo_")` line (line 178), add:

```python
    invalidate_report_cache(db)
```

In `/upload/analyze`, after the existing `cache.invalidate("smart_geo_")` line (line 221), add:

```python
    invalidate_report_cache(db)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comparative.py -k "upload_.*report_cache" -q`
Expected: 2 passed

- [ ] **Step 5: Run the full comparative suite**

Run: `python -m pytest tests/test_comparative.py -q`
Expected: all pass (80 total)

- [ ] **Step 6: Commit**

```bash
git add app/api/upload.py tests/test_comparative.py
git commit -m "feat: invalidate stored reports on data upload"
```

---

## Self-Review Notes

- **Spec coverage:** All spec sections map to tasks — cache module (T1), generator integration + store-only-AI rule (T2), `force` param (T3), upload invalidation across all three paths (T4), testing (all).
- **Type consistency:** `get_stored_report` / `store_report` / `invalidate_report_cache` signatures are identical across T1, T2, T4. `generate_comprehensive_report(..., use_cache=...)` matches between T2 and T3.
- **Numpy handling:** `store_report` uses `_sanitize` (numpy scalars → `.item()`, arrays → `.tolist()`, dataclasses → `vars()`), so cached `data` keeps numeric types and deep equality holds after round-trip.
