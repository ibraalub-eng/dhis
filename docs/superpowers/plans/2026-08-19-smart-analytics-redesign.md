# Smart Analytics Screen Production-Ready Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the smart analytics screen (التحليل الذكي) into a production-ready experience: decision-first layout with three logical scope modes (شهري/زمني/مستشفى), per-section API splitting with independent loaders, performance (lazy rendering, no duplicate requests), backend robustness (strong errors, clean empty states, versioned caching), modular maintainable frontend, and full AR/EN support.

**Architecture:** Backend (`app/api/smart_analytics.py`) keeps the shared `_get_smart_data` compute cache (TTL 5 min) and gains 5 new endpoints: `/decision-board/{month}`, `/patterns/{month}`, `/lag-analysis/{month}`, `/xgboost/{month}`, `/time-overview`. All cache keys get a schema version suffix and `/trend`, `/drilldown`, `/anomaly-timeline` gain response caching. Frontend (`static/tabs/smart-analytics.html` + `static/js/smart-analytics.js`) is rewritten: HTML becomes a three-mode layout with a decision board and collapsible sections; the 2845-line JS is split into ES modules under `static/js/smart/` (`core`, `decision-board`, `charts`, `advanced`, `geo-regional`, `hospital`, `report`); inline styles move to `static/css/styles.css`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / SQLite, vanilla JS (ES modules), Plotly.js (kept), pytest, BeautifulSoup static tests.

## Global Constraints

- Do NOT remove Plotly.js from `static/index.html` — the smart screen still uses it.
- Keep `/smart/overview/{month}` fully supported (14 test references depend on it).
- Keep all 127 existing `tests/test_smart_*.py` passing; keep existing frontend static-test element IDs (list in Task 7).
- Tests run with `python -m pytest tests/... -q`; full suite `python -m pytest tests/ -q` (793 tests).
- `.superpowers/sdd/` files are tracked — NEVER `git add -A`/`git add .`; stage explicit paths only, and never commit `.superpowers/` files.
- Working on `master` directly (user-approved pattern).
- Arabic default UI; all screen chrome/labels bilingual via existing `i18n.js` (`data-i18n` attributes + `__()` helper).
- Empty-state contract: month/hospital with no data returns `{empty: true, message: "..."}` (Arabic), never a raw 500.
- Error contract: every endpoint wraps computation in try/except → `HTTPException(500)` with Arabic detail + cache invalidation.

---

### Task 1: Versioned cache keys + response caching for trend/drilldown/timeline

**Files:**
- Modify: `app/api/smart_analytics.py`
- Modify: `tests/test_smart_analytics.py` (2 cache-key literals)
- Test: `tests/test_smart_analytics.py`

**Interfaces:**
- Produces: module constant `SMART_CACHE_VERSION = "v3"`.
- Produces: cache keys `smart_overview_{month}_{v}`, `governorate_analysis_{month}_{v}`, `smart_timeline_{v}`, `smart_trend_{hospital_id}_{v}`, `smart_drilldown_{hospital_id}_{month}_{v}` (version suffix keeps prefix-based `cache.invalidate("smart_overview_")` working).
- Consumes: `cache` from `app.cache` (existing `TTLCache`).

- [ ] **Step 1: Write the failing test for versioned keys and trend caching**

Add to `tests/test_smart_analytics.py`:

```python
def test_cache_keys_include_version(client):
    from app.cache import cache
    cache.invalidate("smart_overview_")
    client.get("/smart/overview/2026-06")
    assert any(k.startswith("smart_overview_") and k.endswith("_v3") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_trend_response_cached(mock_run, client, db_session):
    from app.cache import cache
    from app.models import Hospital, QualityScore
    cache.invalidate("smart_trend_")
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=70))
    db_session.commit()
    r1 = client.get(f"/smart/trend/{h.id}")
    r2 = client.get(f"/smart/trend/{h.id}")
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert any(k.startswith("smart_trend_") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_drilldown_response_cached(mock_run, client, db_session):
    from app.cache import cache
    from app.models import Hospital
    cache.invalidate("smart_drilldown_")
    h = db_session.query(Hospital).first()
    r1 = client.get(f"/smart/drilldown/{h.id}/2027-01")
    r2 = client.get(f"/smart/drilldown/{h.id}/2027-01")
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert any(k.startswith("smart_drilldown_") for k in cache._cache)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_smart_analytics.py -q`
Expected: FAIL — no `_v3` suffix in keys; trend/drilldown not cached.

- [ ] **Step 3: Add version constant and update `_get_smart_data`, governorate, timeline keys**

In `app/api/smart_analytics.py`, add after the `router = ...` line:

```python
SMART_CACHE_VERSION = "v3"
```

Change in `_get_smart_data`:

```python
    cache_key = f"smart_overview_{month}_{SMART_CACHE_VERSION}"
```

Change in `get_governorate_analysis`:

```python
    cache_key = f"governorate_analysis_{month}_{SMART_CACHE_VERSION}"
```

Change in `get_anomaly_timeline`:

```python
        cache_key = f"smart_timeline_{SMART_CACHE_VERSION}"
```

and its error handler stays `cache.invalidate("smart_timeline")` (prefix still matches).

- [ ] **Step 4: Add response caching to `/trend` and `/drilldown`**

Replace `get_trend`:

```python
@router.get("/trend/{hospital_id}")
def get_trend(hospital_id: int, db: Session = Depends(get_db)):
    cache_key = f"smart_trend_{hospital_id}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from app.models import Hospital
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        from app.models import QualityScore
        months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]
        trend_data = []
        for m in months:
            data = _get_smart_data(db, m)["data"]
            hospital_anomaly = next(
                (a for a in data["anomalies"] if a["hospital_id"] == hospital_id), None
            )
            if hospital_anomaly:
                trend_data.append({
                    "month": m,
                    "anomaly_score": hospital_anomaly["anomaly_score"],
                    "severity": hospital_anomaly["severity"],
                    "method_scores": hospital_anomaly["method_scores"],
                })
        response = _sanitize({
            "hospital_id": hospital_id,
            "hospital_name": hospital.name,
            "trend": trend_data,
        })
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_trend_{hospital_id}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الاتجاه: {str(e)}")
```

Replace `get_drilldown` (keep the `_get_drilldown_all_months` helper unchanged):

```python
@router.get("/drilldown/{hospital_id}/{month}")
def get_drilldown(hospital_id: int, month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_drilldown_{hospital_id}_{month}_{SMART_CACHE_VERSION}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from app.models import Hospital
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        if month == "all":
            response = _get_drilldown_all_months(db, hospital_id, hospital)
            cache.set(cache_key, response, ttl=300)
            return response
        data = _get_smart_data(db, month)["data"]
        anomaly = next((a for a in data["anomalies"] if a["hospital_id"] == hospital_id), None)
        explanation = next((e for e in data["explanations"] if e["hospital_id"] == hospital_id), None)
        residuals = [r for r in data["residuals"] if r["hospital_id"] == hospital_id]
        stratified = [s for s in data["stratified"] if s["hospital_id"] == hospital_id]
        from app.engine.smart.lag_analysis import run_hospital_forecast
        forecast = run_hospital_forecast(db, hospital_id, month, data.get("lag_analysis"))
        response = _sanitize({
            "hospital_id": hospital_id,
            "hospital_name": hospital.name,
            "month": month,
            "anomaly": anomaly,
            "explanation": explanation,
            "residuals": residuals,
            "stratified": stratified,
            "forecast": _sanitize(forecast) if forecast else {},
        })
        cache.set(cache_key, response, ttl=300)
        return response
    except HTTPException:
        raise
    except Exception as e:
        cache.invalidate(f"smart_drilldown_{hospital_id}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل المستشفى: {str(e)}")
```

- [ ] **Step 5: Update the two cache-key literals in existing tests**

In `tests/test_smart_analytics.py`:

`test_cache_returns_cached_result`:
```python
    cache_key = "smart_overview_2026-06_v3"
```

`test_anomaly_timeline_cache_used`:
```python
    assert cache.get("smart_timeline_v3") is not None
```

- [ ] **Step 6: Run the full smart test file**

Run: `python -m pytest tests/test_smart_analytics.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/api/smart_analytics.py tests/test_smart_analytics.py
git commit -m "feat: versioned smart cache keys and response caching for trend/drilldown"
```

---

### Task 2: New endpoint `/smart/decision-board/{month}`

**Files:**
- Modify: `app/api/smart_analytics.py`
- Test: `tests/test_smart_decision_board.py` (new)

**Interfaces:**
- Consumes: `_get_smart_data(db, month)` envelope (`data.kpi`, `data.anomalies`, `data.early_warnings`, `data.healthy_hospitals`, `hospitals_count`, `generated_at`).
- Produces: `GET /smart/decision-board/{month}` → `{month, generated_at, hospitals_count, kpi, anomalies (all, sorted critical-first), early_warnings, healthy_hospitals}` or `{empty: true, message: "لا توجد بيانات لهذا الشهر"}` when `hospitals_count == 0`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_decision_board.py`:

```python
"""Tests for the smart decision-board endpoint."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_decision_board_returns_subset(client):
    resp = client.get("/smart/decision-board/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert "kpi" in data
    assert "anomalies" in data
    assert "early_warnings" in data
    assert "healthy_hospitals" in data
    assert "generated_at" in data
    assert data["hospitals_count"] >= 0
    # لا يحمل الحمولة الكاملة الثقيلة
    assert "correlations" not in data
    assert "clustering" not in data


def test_decision_board_empty_month(client):
    """شهر بلا مستشفيات يُرجع empty بدل خطأ خام."""
    resp = client.get("/smart/decision-board/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True
    assert "لا توجد بيانات" in data.get("message", "")


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_decision_board_error_arabic_and_invalidates(mock_run, client):
    from app.cache import cache
    cache.set("smart_overview_2026-06_v3", {"stale": True}, ttl=300)
    resp = client.get("/smart/decision-board/2026-06")
    assert resp.status_code == 500
    assert "خطأ في لوحة القرار" in resp.json()["detail"]
    assert cache.get("smart_overview_2026-06_v3") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_decision_board.py -q`
Expected: FAIL with 404 (endpoint not defined).

- [ ] **Step 3: Add the endpoint**

In `app/api/smart_analytics.py`, after `get_overview`:

```python
@router.get("/decision-board/{month}")
def get_decision_board(month: str, db: Session = Depends(get_db)):
    """لوحة القرار: حمولة خفيفة سريعة (KPI + أولويات + إنذار مبكر) أعلى الصفحة.

    تُشتق من مذكّرة الشهر المشتركة (_get_smart_data) بلا إعادة حساب؛ يعرض فقط
    ما يحتاجه القرار الفوري. الشهر الخالي يُرجع empty مع رسالة عربية.
    """
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        data = envelope["data"]
        order = {"critical": 0, "warning": 1, "normal": 2}
        anomalies = sorted(data["anomalies"], key=lambda a: (order.get(a["severity"], 2), -a["anomaly_score"]))
        return _sanitize({
            "month": month,
            "generated_at": envelope["generated_at"],
            "hospitals_count": envelope["hospitals_count"],
            "kpi": data["kpi"],
            "anomalies": anomalies,
            "early_warnings": data.get("early_warnings", []),
            "healthy_hospitals": data.get("healthy_hospitals", []),
        })
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في لوحة القرار: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_decision_board.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/smart_analytics.py tests/test_smart_decision_board.py
git commit -m "feat: add smart decision-board endpoint"
```

---

### Task 3: New per-section endpoints `/patterns`, `/lag-analysis`, `/xgboost`

**Files:**
- Modify: `app/api/smart_analytics.py`
- Test: `tests/test_smart_section_endpoints.py` (new)

**Interfaces:**
- Consumes: envelope keys `data.patterns`, `data.lag_analysis`, `data.xgboost`.
- Produces:
  - `GET /smart/patterns/{month}` → `{month, patterns: [...]}`
  - `GET /smart/lag-analysis/{month}` → `{month, lag_analysis: {...}}` (empty month → `{empty: true, message: "لا توجد بيانات لهذا الشهر", lag_analysis: {}}`)
  - `GET /smart/xgboost/{month}` → `{month, xgboost: {...} | None}` (no predictions → `{month, empty: true, message: "لا توجد تنبؤات كافية لهذا الشهر", xgboost: None}`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_section_endpoints.py`:

```python
"""Tests for the new per-section smart analytics endpoints."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_patterns_endpoint_returns_list(client):
    resp = client.get("/smart/patterns/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert isinstance(data["patterns"], list)


def test_lag_analysis_endpoint_returns_dict(client):
    resp = client.get("/smart/lag-analysis/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "lag_analysis" in data


def test_lag_analysis_empty_month(client):
    resp = client.get("/smart/lag-analysis/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True


def test_xgboost_endpoint(client):
    resp = client.get("/smart/xgboost/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "xgboost" in data


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_section_endpoints_error_arabic(mock_run, client):
    for path, msg in [
        ("/smart/patterns/2026-06", "خطأ في تحليل الأنماط"),
        ("/smart/lag-analysis/2026-06", "خطأ في تحليل العلاقات المتأخرة"),
        ("/smart/xgboost/2026-06", "خطأ في تحليل التنبؤات"),
    ]:
        resp = client.get(path)
        assert resp.status_code == 500, path
        assert msg in resp.json()["detail"], path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_section_endpoints.py -q`
Expected: FAIL with 404.

- [ ] **Step 3: Add the three endpoints**

In `app/api/smart_analytics.py`, after `get_geo`:

```python
@router.get("/patterns/{month}")
def get_patterns(month: str, db: Session = Depends(get_db)):
    try:
        data = _get_smart_data(db, month)["data"]
        return {"month": month, "patterns": data.get("patterns", [])}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الأنماط: {str(e)}")


@router.get("/lag-analysis/{month}")
def get_lag_analysis(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر",
                    "month": month, "lag_analysis": {}}
        return {"month": month, "lag_analysis": envelope["data"].get("lag_analysis", {})}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل العلاقات المتأخرة: {str(e)}")


@router.get("/xgboost/{month}")
def get_xgboost(month: str, db: Session = Depends(get_db)):
    try:
        data = _get_smart_data(db, month)["data"]
        xgb = data.get("xgboost")
        if not xgb or not xgb.get("predictions"):
            return {"month": month, "empty": True,
                    "message": "لا توجد تنبؤات كافية لهذا الشهر", "xgboost": None}
        return {"month": month, "xgboost": xgb}
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل التنبؤات: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_section_endpoints.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/smart_analytics.py tests/test_smart_section_endpoints.py
git commit -m "feat: add per-section smart endpoints for patterns, lag-analysis, xgboost"
```

---

### Task 4: New endpoint `/smart/time-overview`

**Files:**
- Modify: `app/api/smart_analytics.py`
- Test: `tests/test_smart_time_overview.py` (new)

**Interfaces:**
- Consumes: `_get_smart_data(db, m)` per distinct month + `QualityScore.month` distinct list (same pattern as `get_anomaly_timeline`).
- Produces: `GET /smart/time-overview` → `{months: [...], series: {avg_score: [{month, value}], critical_count: [...], warning_count: [...], affected_governorates: [...]}}`. Cached under `smart_time_overview_{v3}` TTL 300. Empty data → `{empty: true, message: "لا توجد بيانات بعد", months: []}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_time_overview.py`:

```python
"""Tests for the smart time-overview endpoint."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_time_overview_structure(client):
    resp = client.get("/smart/time-overview")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("months"), list)
    assert "series" in data
    assert "avg_score" in data["series"]
    assert "critical_count" in data["series"]
    assert "warning_count" in data["series"]
    assert "affected_governorates" in data["series"]


def test_time_overview_cached(client):
    from app.cache import cache
    cache.invalidate("smart_time_overview_")
    client.get("/smart/time-overview")
    assert any(k.startswith("smart_time_overview_") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_time_overview_error_arabic(mock_run, client):
    from app.cache import cache
    cache.invalidate("smart_time_overview_")
    resp = client.get("/smart/time-overview")
    assert resp.status_code == 500
    assert "خطأ في التحليل الزمني" in resp.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_time_overview.py -q`
Expected: FAIL with 404.

- [ ] **Step 3: Add the endpoint**

In `app/api/smart_analytics.py`, after `get_anomaly_timeline`:

```python
@router.get("/time-overview")
def get_time_overview(db: Session = Depends(get_db)):
    """نظرة زمنية عبر الأشهر: تطور متوسط الدرجة وتوزيع الشدة والمحافظات المتأثرة.

    يُبني من مذكّرات الشهور المخزّنة (نفس مصدر anomaly-timeline) وتُخزَّن
    النتيجة مؤقتاً كاملة تحت مفتاح معنوَّن بالإصدار.
    """
    try:
        cache_key = f"smart_time_overview_{SMART_CACHE_VERSION}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        from app.models import QualityScore
        months = [r[0] for r in db.query(QualityScore.month).distinct().order_by(QualityScore.month).all()]
        if not months:
            response = {"empty": True, "message": "لا توجد بيانات بعد", "months": []}
            cache.set(cache_key, response, ttl=300)
            return response

        series = {
            "avg_score": [], "critical_count": [], "warning_count": [],
            "affected_governorates": [],
        }
        for m in months:
            envelope = _get_smart_data(db, m)
            data = envelope["data"]
            anomalies = data["anomalies"]
            avg = round(sum(a["anomaly_score"] for a in anomalies) / len(anomalies), 3) if anomalies else 0.0
            series["avg_score"].append({"month": m, "value": avg})
            series["critical_count"].append({"month": m, "value": data["kpi"]["critical_count"]})
            series["warning_count"].append({"month": m, "value": data["kpi"]["warning_count"]})
            series["affected_governorates"].append({"month": m, "value": data["kpi"]["affected_governorates"]})

        response = _sanitize({"months": months, "series": series})
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate("smart_time_overview_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الزمني: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_time_overview.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/smart_analytics.py tests/test_smart_time_overview.py
git commit -m "feat: add smart time-overview endpoint"
```

---

### Task 5: Backend robustness — empty states + error isolation for existing slice endpoints

**Files:**
- Modify: `app/api/smart_analytics.py`
- Modify: `tests/test_smart_section_endpoints.py`

**Interfaces:**
- Produces: consistent `{empty: true, message: "لا توجد بيانات لهذا الشهر"}` on `hospitals_count == 0` for `/anomalies`, `/clusters`, `/correlations`, `/residuals`, `/stratified`, `/geo`, `/patterns`, `/decision-board`, `/lag-analysis`.
- Consumes: `_get_smart_data` envelope.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smart_section_endpoints.py`:

```python
def test_slice_endpoints_empty_month(client):
    for path in [
        "/smart/anomalies/2030-01",
        "/smart/clusters/2030-01",
        "/smart/correlations/2030-01",
        "/smart/residuals/2030-01",
        "/smart/stratified/2030-01",
        "/smart/geo/2030-01",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        data = resp.json()
        assert data.get("empty") is True, path
        assert "لا توجد بيانات" in data.get("message", ""), path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_section_endpoints.py::test_slice_endpoints_empty_month -q`
Expected: FAIL — endpoints return 200 with empty lists, not the `empty` contract.

- [ ] **Step 3: Add empty detection to the six slice endpoints**

For each of `get_anomalies`, `get_clusters`, `get_correlations`, `get_residuals`, `get_stratified`, `get_geo`, change the body from:

```python
        data = _get_smart_data(db, month)["data"]
        response = {"month": month, "...": data["..."]}
```

to:

```python
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        data = envelope["data"]
        response = {"month": month, "...": data["..."]}
```

Concretely, the resulting handlers:

```python
@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        data = envelope["data"]
        response = {"month": month, "anomalies": data["anomalies"], "explanations": data["explanations"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الشذوذ: {str(e)}")


@router.get("/clusters/{month}")
def get_clusters(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        response = {"month": month, "clustering": envelope["data"]["clustering"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل التجمعات: {str(e)}")


@router.get("/correlations/{month}")
def get_correlations(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        response = {"month": month, "correlations": envelope["data"]["correlations"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الارتباطات: {str(e)}")


@router.get("/residuals/{month}")
def get_residuals(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        response = {"month": month, "residuals": envelope["data"]["residuals"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل البواقي: {str(e)}")


@router.get("/stratified/{month}")
def get_stratified(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        response = {"month": month, "stratified": envelope["data"]["stratified"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الطبقى: {str(e)}")


@router.get("/geo/{month}")
def get_geo(month: str, db: Session = Depends(get_db)):
    try:
        envelope = _get_smart_data(db, month)
        if envelope["hospitals_count"] == 0:
            return {"empty": True, "message": "لا توجد بيانات لهذا الشهر", "month": month}
        response = {"month": month, "geo": envelope["data"]["geo"]}
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}_")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الجغرافي: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_section_endpoints.py tests/test_smart_analytics.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/smart_analytics.py tests/test_smart_section_endpoints.py
git commit -m "feat: clean empty states for smart section endpoints"
```

---

### Task 6: Extract smart-analytics CSS into `styles.css`

**Files:**
- Modify: `static/css/styles.css`
- Test: `tests/test_smart_styles.py` (new)

**Interfaces:**
- Produces CSS classes used by the new HTML/JS (Task 7+): `.smart-mode-bar`, `.smart-mode-btn`, `.smart-mode-btn.active`, `.smart-context-bar`, `.smart-section-card`, `.smart-section-header`, `.smart-section-body`, `.smart-kpi-grid`, `.smart-kpi-card`, `.smart-kpi-value`, `.smart-kpi-label`, `.smart-priority-list`, `.smart-priority-item`, `.smart-priority-critical`, `.smart-priority-warning`, `.smart-priority-normal`, `.smart-badge`, `.smart-badge-critical`, `.smart-badge-warning`, `.smart-badge-normal`, `.smart-loader`, `.smart-error-banner`, `.smart-empty-state`, `.smart-methodology-modal`, `.smart-table-wrap`, `.smart-tabs`, `.smart-tab-btn`, `.smart-tab-btn.active`, `.smart-donut-flex`.
- Consumes: existing `@media` breakpoints in `styles.css`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_styles.py`:

```python
"""Static tests for the smart-analytics CSS extraction."""
import os


def _read_styles():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_smart_mode_bar_css_present():
    css = _read_styles()
    assert ".smart-mode-bar" in css
    assert ".smart-mode-btn" in css
    assert ".smart-mode-btn.active" in css


def test_smart_section_and_kpi_css_present():
    css = _read_styles()
    assert ".smart-section-card" in css
    assert ".smart-kpi-grid" in css
    assert ".smart-priority-item" in css
    assert ".smart-badge-critical" in css


def test_smart_loader_and_error_css_present():
    css = _read_styles()
    assert ".smart-loader" in css
    assert ".smart-error-banner" in css
    assert ".smart-empty-state" in css


def test_smart_responsive_grid_uses_autofit():
    css = _read_styles()
    assert "repeat(auto-fit,minmax(" in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_styles.py -q`
Expected: FAIL — classes missing.

- [ ] **Step 3: Add the CSS block**

Append to `static/css/styles.css`:

```css
/* ══════════════════════════════════════════════════════════════════
   Smart Analytics (التحليل الذكي) — production redesign
   ══════════════════════════════════════════════════════════════════ */
.smart-mode-bar { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 1rem; }
.smart-mode-btn { padding: 0.5rem 1.1rem; border-radius: 8px; border: 1px solid #c7d2fe; background: #fff; color: #4338ca; font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: all 0.18s; }
.smart-mode-btn:hover { background: #eef2ff; }
.smart-mode-btn.active { background: linear-gradient(135deg, #1a237e, #312e81); color: #fff; border-color: #1a237e; }

.smart-context-bar { display: flex; gap: 0.8rem; align-items: flex-end; flex-wrap: wrap; margin-bottom: 1rem; padding: 0.8rem 1rem; background: linear-gradient(135deg, #f8fafc, #eef2ff); border-radius: 10px; border: 1px solid #c7d2fe; }

.smart-section-card { background: #fff; border: 1px solid #e0e0e0; border-radius: 10px; margin-bottom: 0.9rem; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.smart-section-header { background: #f8f9fb; padding: 0.75rem 1rem; cursor: pointer; display: flex; align-items: center; justify-content: space-between; font-weight: 700; color: #1a237e; font-size: 0.92rem; user-select: none; border-bottom: 1px solid #eef0f8; }
.smart-section-header .smart-toggle-icon { transition: transform 0.2s; }
.smart-section-card.open .smart-toggle-icon { transform: rotate(180deg); }
.smart-section-body { padding: 1rem; display: none; }
.smart-section-card.open .smart-section-body { display: block; }

.smart-kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
.smart-kpi-card { text-align: center; padding: 1rem; border-radius: 8px; cursor: pointer; background: #fff; border-top: 3px solid #e0e0e0; box-shadow: 0 1px 4px rgba(0,0,0,0.06); transition: transform 0.15s, box-shadow 0.15s; }
.smart-kpi-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
.smart-kpi-value { font-size: 1.9rem; font-weight: 700; }
.smart-kpi-label { font-size: 0.8rem; color: #444; font-weight: 600; margin: 0.3rem 0; }
.smart-kpi-sub { font-size: 0.7rem; color: #888; line-height: 1.4; }

.smart-priority-list { display: flex; flex-direction: column; gap: 0.5rem; }
.smart-priority-item { border-radius: 10px; padding: 0.7rem 0.85rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.smart-priority-critical { border: 1px solid #fecaca; background: #fef2f2; }
.smart-priority-warning { border: 1px solid #fde68a; background: #fffbeb; }
.smart-priority-normal { border: 1px solid #bbf7d0; background: #f0fdf4; }
.smart-priority-name { font-size: 0.85rem; font-weight: 700; }
.smart-priority-meta { font-size: 0.7rem; color: #6b7280; }

.smart-badge { display: inline-block; padding: 0.12rem 0.5rem; border-radius: 10px; font-size: 0.72rem; font-weight: 700; }
.smart-badge-critical { background: #dc2626; color: #fff; }
.smart-badge-warning { background: #f59e0b; color: #fff; }
.smart-badge-normal { background: #22c55e; color: #fff; }

.smart-loader { display: none; text-align: center; padding: 1.2rem; color: #4338ca; font-size: 0.85rem; font-weight: 600; }
.smart-loader.active { display: block; }
.smart-error-banner { display: none; background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c; padding: 0.7rem 1rem; border-radius: 8px; font-size: 0.82rem; margin: 0.6rem 0; }
.smart-error-banner.active { display: block; }
.smart-empty-state { background: #f0f9ff; border: 1px solid #bae6fd; color: #0c4a6e; padding: 0.9rem 1rem; border-radius: 8px; font-size: 0.85rem; margin: 0.6rem 0; }

.smart-table-wrap { overflow-x: auto; font-size: 0.8rem; }
.smart-table-wrap table { width: 100%; border-collapse: collapse; }
.smart-table-wrap th { background: #f1f5f9; border-bottom: 2px solid #e2e8f0; padding: 0.45rem 0.6rem; }
.smart-table-wrap td { border-bottom: 1px solid #f0f0f0; padding: 0.4rem 0.6rem; }

.smart-tabs { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-bottom: 0.8rem; }
.smart-tab-btn { padding: 0.4rem 0.9rem; border-radius: 6px; border: 1px solid #c7d2fe; background: #fff; color: #4338ca; font-size: 0.78rem; font-weight: 600; cursor: pointer; }
.smart-tab-btn.active { background: #4338ca; color: #fff; }

.smart-methodology-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center; backdrop-filter: blur(3px); }
.smart-methodology-modal.active { display: flex; }
.smart-modal-box { background: #fff; border-radius: 14px; max-width: 860px; width: 94%; max-height: 86vh; overflow-y: auto; box-shadow: 0 25px 80px rgba(0,0,0,0.3); position: relative; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_styles.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/css/styles.css tests/test_smart_styles.py
git commit -m "style: extract smart-analytics CSS into styles.css"
```

---

### Task 7: Rewrite `static/tabs/smart-analytics.html`

**Files:**
- Rewrite: `static/tabs/smart-analytics.html`
- Modify: `tests/test_export.py` (only if an ID is intentionally dropped — see Step 4 note)
- Modify: `tests/test_comparative.py`
- Modify: `tests/test_lag_analysis.py`
- Test: static structure tests

**Interfaces:**
- Consumes: new module script files (loaded in index.html, Task 14), new endpoints.
- Produces: the screen chrome with `data-i18n` attributes, three-mode bar, decision board, collapsible sections, methodology modal (`role="dialog"` + `aria-modal`), a11y labels.

**IMPORTANT — preserved IDs (existing static tests depend on them; DO NOT remove):**
`smart-export-btn`, `smart-export-scope`, `smart-report-generate`, `smart-report-lang-toggle`, `smart-comparison-type`, `smart-report-kpi-dashboard`, `smart-comparison-chart`, `smart-peer-comparison-table`, `smart-decision-board`, `smart-decision-verdict`, `smart-decision-hotspots`, `smart-decision-watchlist`, `smart-decision-priorities`, `smart-timeline-chart`, `smart-timeline-badge`, `smart-timeline-text`, `smart-cluster-profiles`, `smart-composite-patterns`, `smart-drilldown-factors`, `smart-drilldown-text`, `smart-drilldown-name`, `smart-hospital-forecast`, `smart-month-select`, `smart-hospital-select`, `smart-loading-overlay`, `smart-status`, `smart-kpi-container`, `smart-critical-list`, `smart-critical-count`, `smart-disclaimer`, `smart-drilldown-modal`, `smart-kpi-modal`.

- [ ] **Step 1: Write the failing static structure test**

Append to `tests/test_export.py`:

```python
def test_smart_redesign_structure():
    """الشاشة الجديدة: شريط أوضاع + لوحة قرار + أقسام قابلة للطي + مودال منهجية."""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    # شريط الأوضاع الثلاثة
    assert soup.find(id="smart-mode-monthly") is not None
    assert soup.find(id="smart-mode-time") is not None
    assert soup.find(id="smart-mode-hospital") is not None
    # لوحة القرار أعلى الصفحة
    assert soup.find(id="smart-decision-board") is not None
    assert soup.find(id="smart-kpi-container") is not None
    assert soup.find(id="smart-critical-list") is not None
    # أقسام قابلة للطي
    assert len(soup.find_all(class_="smart-section-card")) >= 4
    # مودال المنهجية الموصول
    assert soup.find(id="smart-methodology-modal") is not None
    assert soup.find(id="smart-methodology-btn") is not None
    # أقسام الأوضاع الثلاثة
    assert soup.find(id="smart-monthly-panel") is not None
    assert soup.find(id="smart-time-panel") is not None
    assert soup.find(id="smart-hospital-panel") is not None
    # إمكانية الوصول للمودالات
    drill = soup.find(id="smart-drilldown-modal")
    assert drill is not None
    assert drill.get("role") == "dialog"
    assert drill.get("aria-modal") == "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export.py::test_smart_redesign_structure -q`
Expected: FAIL — new IDs missing.

- [ ] **Step 3: Rewrite the HTML file**

Replace the full content of `static/tabs/smart-analytics.html` with the complete new markup below (preserve every ID listed above):

```html
<div class="smart-analytics-tab" dir="rtl" style="padding:0.5rem 0.25rem;max-width:1200px;margin:0 auto;position:relative;">

  <!-- Loading overlay -->
  <div id="smart-loading-overlay" style="display:none;position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(255,255,255,0.85);z-index:500;border-radius:12px;backdrop-filter:blur(3px);flex-direction:column;align-items:center;justify-content:center;gap:1rem;">
    <div style="width:48px;height:48px;border:4px solid #c7d2fe;border-top-color:#1a237e;border-radius:50%;animation:smartSpin 0.8s linear infinite;"></div>
    <span style="font-size:0.95rem;font-weight:600;color:#1a237e;" data-i18n="Analyzing data...">جاري تحليل البيانات…</span>
  </div>
  <style>@keyframes smartSpin{to{transform:rotate(360deg)}}</style>

  <!-- ═══ Top bar: title + mode bar + methodology ⓘ ═══ -->
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.8rem;margin-bottom:1rem;">
    <div>
      <h2 style="margin:0;color:#1a237e;font-size:1.15rem;">🛡️ <span data-i18n="Smart Analytics">التحليل الذكي</span></h2>
      <div style="font-size:0.72rem;color:#6b7280;margin-top:0.2rem;" data-i18n="Decision first, analysis second">قرار أولاً، تحليل ثانياً</div>
    </div>
    <div class="smart-mode-bar" role="tablist" aria-label="Analysis mode">
      <button id="smart-mode-monthly" class="smart-mode-btn active" role="tab" aria-selected="true" data-smart-mode="monthly" data-i18n="Monthly">شهري</button>
      <button id="smart-mode-time" class="smart-mode-btn" role="tab" aria-selected="false" data-smart-mode="time" data-i18n="Time">زمني</button>
      <button id="smart-mode-hospital" class="smart-mode-btn" role="tab" aria-selected="false" data-smart-mode="hospital" data-i18n="Hospital">مستشفى</button>
    </div>
    <button id="smart-methodology-btn" class="btn btn-sm btn-outline" aria-label="Methodology" data-i18n="Methodology">ⓘ المنهجية</button>
  </div>

  <!-- ═══ Context bar (per-mode filters + actions) ═══ -->
  <div class="smart-context-bar">
    <div id="smart-monthly-context" style="display:flex;gap:0.8rem;align-items:flex-end;flex-wrap:wrap;width:100%;">
      <div>
        <label style="font-weight:600;font-size:0.82rem;display:block;margin-bottom:0.25rem;color:#4338ca;" data-i18n="Month:">الشهر:</label>
        <select id="smart-month-select" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;min-width:130px;font-size:0.85rem;background:white;"></select>
      </div>
      <div>
        <label style="font-weight:600;font-size:0.82rem;display:block;margin-bottom:0.25rem;color:#4338ca;" data-i18n="Hospital:">المستشفى:</label>
        <select id="smart-hospital-select" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;min-width:220px;font-size:0.85rem;background:white;">
          <option value="">-- <span data-i18n="All Hospitals">جميع المستشفيات</span> --</option>
        </select>
      </div>
      <button id="smart-refresh" class="btn btn-sm" data-i18n="Refresh">تحديث</button>
      <div style="margin-inline-start:auto;display:flex;gap:0.5rem;align-items:flex-end;flex-wrap:wrap;">
        <select id="smart-export-scope" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;font-size:0.82rem;background:white;">
          <option value="current" data-i18n="Selected month">الشهر المحدد</option>
          <option value="all" data-i18n="All months">كل الأشهر</option>
        </select>
        <button id="smart-export-btn" class="btn btn-sm" onclick="smartExportData()" data-i18n="Export Data">تصدير البيانات</button>
        <button id="smart-report-generate" class="btn btn-sm" onclick="smartGenerateComprehensiveReport()" data-i18n="Generate Report">🤖 توليد التقرير الشامل</button>
        <button id="smart-report-lang-toggle" class="btn btn-sm btn-outline" onclick="smartToggleReportLang()">🇬🇧 English</button>
      </div>
    </div>
    <div id="smart-time-context" style="display:none;font-size:0.8rem;color:#6b7280;width:100%;" data-i18n="All hospitals across all months">كل المستشفيات عبر كل الأشهر</div>
    <div id="smart-hospital-context" style="display:none;gap:0.8rem;align-items:flex-end;flex-wrap:wrap;width:100%;">
      <select id="smart-hospital-context-select" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;min-width:220px;font-size:0.85rem;background:white;">
        <option value="">-- <span data-i18n="Select Hospital">اختر مستشفى</span> --</option>
      </select>
      <button id="smart-hospital-context-all" class="btn btn-sm btn-outline" data-i18n="All months">كل الأشهر</button>
    </div>
    <span id="smart-status" style="font-size:0.8rem;color:#6b7280;"></span>
  </div>

  <!-- ═══ Panel: Monthly ═══ -->
  <div id="smart-monthly-panel">

    <!-- Decision board (above the fold) -->
    <div id="smart-decision-board" style="margin-bottom:1.2rem;">
      <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.8rem;">
        <h3 style="margin:0;color:#1a237e;font-size:1rem;">🛡️ <span data-i18n="Decision Board">لوحة القرار</span></h3>
        <span id="smart-decision-month" style="font-size:0.8rem;font-weight:700;color:#4338ca;background:#eef2ff;border:1px solid #c7d2fe;padding:0.2rem 0.7rem;border-radius:12px;"></span>
      </div>
      <div id="smart-kpi-container" class="smart-kpi-grid"></div>
      <div class="smart-section-card">
        <div class="smart-section-header" data-smart-collapsible="smart-critical-block">
          <span>🚨 <span data-i18n="Hospitals needing urgent action">مستشفيات تحتاج تدخلاً عاجلاً</span></span>
          <span id="smart-critical-count" style="font-size:0.72rem;padding:0.2rem 0.7rem;border-radius:12px;background:#fef2f2;color:#dc2626;font-weight:600;"></span>
          <span class="smart-toggle-icon">▾</span>
        </div>
        <div id="smart-critical-block" class="smart-section-body">
          <div id="smart-critical-list" class="smart-priority-list"></div>
          <div id="smart-critical-text" style="font-size:0.72rem;color:#6b7280;margin-top:0.5rem;"></div>
        </div>
      </div>
      <div id="smart-early-warnings" style="margin-bottom:0.8rem;"></div>
      <div id="smart-healthy-hospitals" style="margin-bottom:0.8rem;"></div>
    </div>

    <!-- Analytics sections (collapsible, heavy ones folded) -->
    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-hospitals-section">
        <span>🏥 <span data-i18n="Hospitals">المستشفيات</span> — <span data-i18n="Anomaly table and healthy models">جدول الشذوذ ونماذج القدوة</span></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div id="smart-hospitals-section" class="smart-section-body">
        <div class="smart-loader" data-smart-loader="anomalies"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="anomalies" role="alert"></div>
        <div class="smart-empty-state" data-smart-empty="anomalies"></div>
        <div class="smart-table-wrap">
          <table>
            <thead><tr><th data-i18n="Hospital">المستشفى</th><th data-i18n="Governorate">المحافظة</th><th data-i18n="Score">الدرجة</th><th data-i18n="Status">الحالة</th><th data-i18n="Explanation">التفسير</th><th></th></tr></thead>
            <tbody id="smart-anomaly-table"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-geo-section">
        <span>🗺️ <span data-i18n="Geography">الجغرافيا</span> — <span data-i18n="Map, governorates, regional">الخريطة والمحافظات والإقليمي</span></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div id="smart-geo-section" class="smart-section-body">
        <div class="smart-loader" data-smart-loader="geo"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="geo" role="alert"></div>
        <div class="smart-empty-state" data-smart-empty="geo"></div>
        <div id="smart-geo-map" style="height:260px;"></div>
        <div id="smart-regional-content"></div>
        <div id="smart-governorate-content"></div>
      </div>
    </div>

    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-advanced-section">
        <span>🧠 <span data-i18n="Advanced Models">النماذج المتقدمة</span> — <span data-i18n="clusters, correlations, patterns, lead-lag">عنقودات، ارتباطات، أنماط، قيادة متأخرة</span></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div id="smart-advanced-section" class="smart-section-body">
        <div class="smart-tabs">
          <button class="smart-tab-btn active" data-smart-tab="clusters-tab" data-i18n="Clusters">عنقودات</button>
          <button class="smart-tab-btn" data-smart-tab="corr-tab" data-i18n="Correlations & Residuals">ارتباط وبواقي</button>
          <button class="smart-tab-btn" data-smart-tab="patterns-tab" data-i18n="Patterns & Lead-lag">أنماط وقيادة</button>
          <button class="smart-tab-btn" data-smart-tab="fi-tab" data-i18n="Feature Importance">أهمية العوامل</button>
        </div>
        <div class="smart-loader" data-smart-loader="advanced"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="advanced" role="alert"></div>
        <div class="smart-empty-state" data-smart-empty="advanced"></div>
        <div id="clusters-tab" style="display:block;">
          <div id="smart-cluster-scatter" style="height:260px;"></div>
          <div id="smart-cluster-profiles"></div>
        </div>
        <div id="corr-tab" style="display:none;">
          <div id="smart-correlation-heatmap" style="height:260px;"></div>
          <div id="smart-residual-plot" style="height:260px;"></div>
        </div>
        <div id="patterns-tab" style="display:none;">
          <div id="smart-composite-patterns"></div>
          <div id="smart-lag-analysis"></div>
        </div>
        <div id="fi-tab" style="display:none;">
          <div id="smart-feature-importance"></div>
        </div>
      </div>
    </div>

    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-forecast-section">
        <span>🔮 <span data-i18n="Forecasts">التنبؤات</span> — <span data-i18n="XGBoost and walk-forward">XGBoost والتحقق الزمني</span></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div id="smart-forecast-section" class="smart-section-body">
        <div class="smart-loader" data-smart-loader="xgboost"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="xgboost" role="alert"></div>
        <div class="smart-empty-state" data-smart-empty="xgboost"></div>
        <div id="smart-xgboost-predictions"></div>
        <div id="smart-walk-forward"></div>
        <div id="smart-predicted-scatter" style="height:260px;"></div>
      </div>
    </div>

    <!-- Report output (kept for backward compatibility) -->
    <div id="smart-report-section" style="display:none;margin-top:1.2rem;">
      <h3 style="color:#1a237e;font-size:1rem;">📋 <span data-i18n="Comprehensive Report">التقرير الشامل</span></h3>
      <div id="smart-report-kpi-dashboard" class="smart-kpi-grid"></div>
      <div class="smart-section-card">
        <div class="smart-section-header" data-smart-collapsible="smart-decision-board">
          <span>🎯 <span data-i18n="Executive Decisions">قرارات تنفيذية</span></span>
          <span class="smart-toggle-icon">▾</span>
        </div>
        <div class="smart-section-body">
          <div id="smart-decision-verdict" style="font-size:1rem;font-weight:700;margin-bottom:0.6rem;"></div>
          <div id="smart-decision-risk" style="font-size:0.8rem;color:#6b7280;margin-bottom:0.6rem;"></div>
          <h4 style="font-size:0.85rem;color:#1a237e;margin:0.6rem 0 0.3rem;"><span data-i18n="Hotspots">البؤر الساخنة</span></h4>
          <div id="smart-decision-hotspots"></div>
          <h4 style="font-size:0.85rem;color:#1a237e;margin:0.6rem 0 0.3rem;"><span data-i18n="Watchlist">قائمة المراقبة</span></h4>
          <div id="smart-decision-watchlist"></div>
          <h4 style="font-size:0.85rem;color:#1a237e;margin:0.6rem 0 0.3rem;"><span data-i18n="Priorities">الأولويات</span></h4>
          <div id="smart-decision-priorities"></div>
        </div>
      </div>
      <div id="smart-report-output"></div>
      <div class="smart-section-card">
        <div class="smart-section-header" data-smart-collapsible="smart-comparison-block">
          <span>⚖️ <span data-i18n="Peer Comparison">مقارنة النظير</span></span>
          <span class="smart-toggle-icon">▾</span>
        </div>
        <div class="smart-section-body" id="smart-comparison-block">
          <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;margin-bottom:0.6rem;">
            <label style="font-size:0.8rem;color:#4338ca;font-weight:600;" data-i18n="Comparison scope:">نطاق المقارنة:</label>
            <select id="smart-comparison-type" style="padding:0.4rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;font-size:0.8rem;">
              <option value="all" data-i18n="All hospitals">كل المستشفيات</option>
              <option value="governorate" data-i18n="Same governorate">نفس المحافظة</option>
              <option value="type" data-i18n="Same type">نفس النوع</option>
            </select>
          </div>
          <div id="smart-comparison-chart" style="height:260px;"></div>
          <div id="smart-peer-comparison-table" class="smart-table-wrap"></div>
        </div>
      </div>
    </div>

    <!-- Disclaimer -->
    <div style="background:linear-gradient(135deg,#fffbeb,#fef3c7);border:1px solid #fbbf24;border-radius:8px;padding:0.8rem 1rem;margin-top:0.5rem;display:flex;align-items:center;gap:0.6rem;">
      <span style="font-size:1.1rem;">&#9888;&#65039;</span>
      <span id="smart-disclaimer" style="color:#92400e;font-size:0.82rem;" data-i18n="Results are based on registered hospital data only. Treat them as preliminary information, not final decisions.">النتائج مبنية على بيانات المستشفيات المسجلة فقط. يجب تفسيرها كمعلومات أولية وليست قرارات نهائية.</span>
    </div>
  </div>

  <!-- ═══ Panel: Time (زمني) ═══ -->
  <div id="smart-time-panel" style="display:none;">
    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-timeline-block">
        <span>📈 <span data-i18n="Anomaly Timeline">تطور درجات الشذوذ</span></span>
        <span id="smart-timeline-badge" style="font-size:0.7rem;color:#6b7280;"></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div class="smart-section-body" id="smart-timeline-block">
        <div class="smart-loader" data-smart-loader="timeline"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="timeline" role="alert"></div>
        <div id="smart-timeline-chart" style="height:420px;"></div>
        <div id="smart-timeline-text" style="font-size:0.75rem;color:#6b7280;margin-top:0.4rem;"></div>
      </div>
    </div>
    <div class="smart-section-card">
      <div class="smart-section-header" data-smart-collapsible="smart-time-overview-block">
        <span>🌐 <span data-i18n="Time Overview">النظرة الزمنية</span></span>
        <span class="smart-toggle-icon">▾</span>
      </div>
      <div class="smart-section-body" id="smart-time-overview-block">
        <div class="smart-loader" data-smart-loader="time-overview"><span data-i18n="Loading...">جاري التحميل...</span></div>
        <div class="smart-error-banner" data-smart-error="time-overview" role="alert"></div>
        <div class="smart-empty-state" data-smart-empty="time-overview"></div>
        <div id="smart-time-avg" style="height:260px;"></div>
        <div id="smart-time-severity" style="height:260px;"></div>
        <div id="smart-time-governorates" style="height:260px;"></div>
      </div>
    </div>
  </div>

  <!-- ═══ Panel: Hospital (مستشفى) ═══ -->
  <div id="smart-hospital-panel" style="display:none;margin-top:1rem;">
    <div class="smart-loader" data-smart-loader="hospital"><span data-i18n="Loading...">جاري التحميل...</span></div>
    <div class="smart-error-banner" data-smart-error="hospital" role="alert"></div>
    <div class="smart-empty-state" data-smart-empty="hospital"></div>
    <div id="smart-hospital-name" style="font-size:1rem;font-weight:700;color:#1a237e;margin-bottom:0.8rem;"></div>
    <div id="smart-hospital-forecast"></div>
    <div id="smart-hospital-trend" style="height:260px;"></div>
    <div id="smart-hospital-factors" class="smart-table-wrap"></div>
  </div>

  <!-- ═══ Methodology modal (single unified source) ═══ -->
  <div id="smart-methodology-modal" class="smart-methodology-modal" role="dialog" aria-modal="true" aria-labelledby="smart-methodology-title">
    <div class="smart-modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:1rem 1.5rem;border-bottom:1px solid #e5e7eb;background:linear-gradient(135deg,#f8fafc,#eef2ff);border-radius:14px 14px 0 0;position:sticky;top:0;z-index:1;">
        <h3 id="smart-methodology-title" style="margin:0;color:#1a237e;font-size:1.05rem;">📘 <span data-i18n="How is the anomaly score calculated?">كيف تُحسب درجة الشذوذ؟</span></h3>
        <button id="smart-methodology-close" aria-label="Close" style="background:none;border:none;font-size:1.4rem;cursor:pointer;color:#666;padding:0 0.5rem;">&#10006;</button>
      </div>
      <div style="padding:1.5rem;font-size:0.85rem;color:#374151;line-height:1.8;">
        <p><strong><span data-i18n="Four engines">4 محركات</span>:</strong> <span data-i18n="Isolation Forest (35%), LOF (30%), Mahalanobis (20%), residuals (15%).">Isolation Forest (35%)، LOF (30%)، Mahalanobis (20%)، والبواقي (15%).</span></p>
        <p><strong><span data-i18n="Unified score (0-1)">النتيجة الموحّدة (0–1)</span>:</strong> <span data-i18n="below 0.3 normal, 0.3-0.6 warning, above 0.6 critical.">أقل من 0.3 طبيعي، 0.3–0.6 تنبيه، أعلى 0.6 حرج.</span></p>
        <p><strong><span data-i18n="Inputs">الإدخالات</span>:</strong> <span data-i18n="10 clinical indicators + hospital type + governorate.">10 مؤشرات سريرية + نوع المستشفى + المحافظة.</span></p>
        <p><strong><span data-i18n="Interpretation">التفسير</span>:</strong> <span data-i18n="SHAP factors and peer-group comparison explain each anomaly. Results are preliminary indicators, not final decisions.">عوامل SHAP والمقارنة الطبقية تفسران كل شذوذ. النتائج مؤشرات أولية وليست قرارات نهائية.</span></p>
      </div>
    </div>
  </div>

  <!-- ═══ Drill-down modal (kept IDs + a11y) ═══ -->
  <div id="smart-drilldown-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;justify-content:center;align-items:center;backdrop-filter:blur(3px);" role="dialog" aria-modal="true" aria-labelledby="smart-drilldown-name">
    <div style="background:white;border-radius:14px;max-width:800px;width:94%;max-height:88vh;overflow-y:auto;box-shadow:0 25px 80px rgba(0,0,0,0.3);position:relative;">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:1rem 1.5rem;border-bottom:1px solid #e5e7eb;background:linear-gradient(135deg,#f8fafc,#eef2ff);border-radius:14px 14px 0 0;position:sticky;top:0;z-index:1;">
        <h3 style="margin:0;color:#1a237e;font-size:1.05rem;">&#128269; <span data-i18n="Hospital details">تفاصيل المستشفى</span>: <span id="smart-drilldown-name" style="font-weight:700;"></span></h3>
        <button onclick="document.getElementById('smart-drilldown-modal').style.display='none'" aria-label="Close" style="background:none;border:none;font-size:1.4rem;cursor:pointer;color:#666;padding:0 0.5rem;">&#10006;</button>
      </div>
      <div style="padding:1.5rem;">
        <div id="smart-shap-waterfall" style="height:250px;"></div>
        <div id="smart-trend-line" style="height:250px;"></div>
        <p id="smart-drilldown-text" style="font-size:0.82rem;color:#444;background:#f9fafb;padding:0.7rem;border-radius:6px;border:1px solid #e5e7eb;line-height:1.6;"></p>
        <h4 style="color:#333;font-size:0.88rem;margin-bottom:0.5rem;">&#128202; <span data-i18n="Actual factor values vs peer average">قيم العوامل الفعلية مقابل متوسط النظير</span></h4>
        <div id="smart-drilldown-factors" style="font-size:0.8rem;overflow-x:auto;"></div>
      </div>
    </div>
  </div>

  <!-- ═══ KPI detail modal (kept IDs + a11y) ═══ -->
  <div id="smart-kpi-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;justify-content:center;align-items:center;backdrop-filter:blur(2px);" role="dialog" aria-modal="true">
    <div style="background:white;border-radius:14px;max-width:720px;width:92%;max-height:82vh;overflow-y:auto;box-shadow:0 25px 80px rgba(0,0,0,0.25);position:relative;">
      <div id="smart-kpi-modal-header" style="display:flex;justify-content:space-between;align-items:center;padding:1rem 1.5rem;border-bottom:1px solid #e5e7eb;background:linear-gradient(135deg,#f8fafc,#eef2ff);border-radius:14px 14px 0 0;position:sticky;top:0;z-index:1;">
        <h3 id="smart-kpi-modal-title" style="margin:0;color:#1a237e;font-size:1.05rem;"></h3>
        <button aria-label="Close" style="background:none;border:none;font-size:1.4rem;cursor:pointer;color:#666;padding:0 0.5rem;">&#10006;</button>
      </div>
      <div id="smart-kpi-modal-body" style="padding:1.5rem;"></div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Run the affected static tests**

Run: `python -m pytest tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py -q`
Expected: PASS. If any assertion fails because of an ID mismatch, fix the HTML/JS to preserve the exact ID (never delete a listed preserved ID).

- [ ] **Step 5: Commit**

```bash
git add static/tabs/smart-analytics.html tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py
git commit -m "feat: rewrite smart-analytics HTML with three modes and decision-first layout"
```

---

### Task 8: Create `static/js/smart/core.js` (state, fetch, loaders, modes)

**Files:**
- Create: `static/js/smart/core.js`
- Test: `tests/test_smart_core_js.py` (new)

**Interfaces:**
- Produces (ES module exports): `smartState` object `{ month, data, monthChartsRendered, reportGenerating }`, `apiSmartGet(path)`, `smartShowLoading()`, `smartHideLoading()`, `setSmartLoader(key, active)`, `showSmartSectionError(key, message)`, `showSmartSectionEmpty(key, message)`, `clearSmartSectionState(key)`, `_smartEscapeHtml(s)`, `smartTranslateFeature(name)`, `_fmtNum(v, digits)`, `_riskBadge(label, level)`, `toggleSmartSection(header)`, `setSmartMode(mode)`, `registerSectionLoaders(registry)`.
- Consumes: `window.currentLang` / `__` from i18n via `window.__` (set by app.js) — fall back to Arabic text if missing.

- [ ] **Step 1: Write the failing static test**

Create `tests/test_smart_core_js.py`:

```python
"""Static tests for smart/core.js module."""
import os


def _read_core():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "core.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_core_exports_expected_api():
    js = _read_core()
    for name in ["smartState", "apiSmartGet", "smartShowLoading", "smartHideLoading",
                 "setSmartLoader", "showSmartSectionError", "showSmartSectionEmpty",
                 "_smartEscapeHtml", "smartTranslateFeature", "toggleSmartSection",
                 "setSmartMode", "registerSectionLoaders"]:
        assert f"export function {name}" in js or f"export const {name}" in js or f"export let {name}" in js, name


def test_core_has_single_escape_helper():
    js = _read_core()
    assert js.count("function _smartEscapeHtml") == 1


def test_core_has_mode_names():
    js = _read_core()
    assert "monthly" in js
    assert "time" in js
    assert "hospital" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/core.js`:

```javascript
// core.js — shared state, fetch, loaders, mode switching, small utilities.
// Singletons used by the whole smart-analytics screen.

export const SMART_COLORS = {
  normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444',
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],
  noise: '#6b7280', shap_positive: '#ef4444', shap_negative: '#3b82f6',
  corr_negative: '#3b82f6', corr_zero: '#ffffff', corr_positive: '#ef4444',
};

export const smartState = {
  month: null,
  data: null,
  monthChartsRendered: false,
  reportGenerating: false,
  mode: 'monthly',
  lang: 'ar',
};

// i18n helper: use the global __ from app.js when available, else passthrough.
export function _t(text) {
  if (typeof window.__ === 'function') {
    const translated = window.__(text);
    if (translated && translated !== text) return translated;
  }
  const smartArabic = window.SMART_ARABIC || {};
  return smartArabic[text] || text;
}

export async function apiSmartGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch (e) { /* ignore */ }
    throw new Error(detail || ('HTTP ' + res.status));
  }
  return res.json();
}

export function smartShowLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) el.style.display = 'flex';
}
export function smartHideLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) el.style.display = 'none';
}

export function setSmartLoader(key, active) {
  const el = document.querySelector(`[data-smart-loader="${key}"]`);
  if (el) el.classList.toggle('active', !!active);
}

export function showSmartSectionError(key, message) {
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) { err.textContent = message || _t('Failed to load'); err.classList.add('active'); }
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) empty.textContent = '';
}

export function showSmartSectionEmpty(key, message) {
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) { empty.textContent = message || _t('No data'); empty.style.display = 'block'; }
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) err.classList.remove('active');
}

export function clearSmartSectionState(key) {
  const loader = document.querySelector(`[data-smart-loader="${key}"]`);
  if (loader) loader.classList.remove('active');
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) { err.textContent = ''; err.classList.remove('active'); }
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) { empty.textContent = ''; empty.style.display = 'none'; }
}

export function _smartEscapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function _fmtNum(v, digits) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(digits == null ? 2 : digits);
}

export function _riskBadge(label, level) {
  const cls = level === 'critical' ? 'smart-badge-critical'
    : level === 'warning' ? 'smart-badge-warning' : 'smart-badge-normal';
  return `<span class="${cls}">${_smartEscapeHtml(label)}</span>`;
}

// Translate feature keys (reuses the global SMART_ARABIC dict registered by charts.js)
export function smartTranslateFeature(name) {
  const ar = window.SMART_ARABIC || {};
  if (!name) return '-';
  if (ar[name]) return ar[name];
  if (name.startsWith('governorate_')) {
    const val = name.substring('governorate_'.length);
    return val.startsWith('محافظة') ? val : 'محافظة ' + val;
  }
  if (name.startsWith('hospital_type_')) {
    const val = name.substring('hospital_type_'.length);
    return val.startsWith('نوع') ? val : 'نوع: ' + val;
  }
  return name;
}

export function toggleSmartSection(header) {
  const card = header.closest('.smart-section-card');
  if (!card) return;
  const isOpen = card.classList.contains('open');
  card.classList.toggle('open', !isOpen);
  const targetId = header.getAttribute('data-smart-collapsible');
  const target = targetId ? document.getElementById(targetId) : null;
  if (isOpen && target && window.Plotly) {
    // collapsing: purge Plotly charts inside to free memory (spec 3.4)
    target.querySelectorAll('[id]').forEach(el => {
      if (el.__plotly) Plotly.purge(el.id);
    });
  }
  if (target && !isOpen) {
    // opening: notify section loader registry (IntersectionObserver re-run)
    const evt = new CustomEvent('smart-section-opened', { detail: { id: targetId } });
    document.dispatchEvent(evt);
  }
}

export function setSmartMode(mode) {
  smartState.mode = mode;
  document.querySelectorAll('.smart-mode-btn').forEach(btn => {
    const active = btn.dataset.smartMode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.getElementById('smart-monthly-panel').style.display = mode === 'monthly' ? 'block' : 'none';
  document.getElementById('smart-time-panel').style.display = mode === 'time' ? 'block' : 'none';
  document.getElementById('smart-hospital-panel').style.display = mode === 'hospital' ? 'block' : 'none';
  document.getElementById('smart-monthly-context').style.display = mode === 'monthly' ? 'flex' : 'none';
  document.getElementById('smart-time-context').style.display = mode === 'time' ? 'block' : 'none';
  document.getElementById('smart-hospital-context').style.display = mode === 'hospital' ? 'flex' : 'none';
  const evt = new CustomEvent('smart-mode-changed', { detail: { mode } });
  document.dispatchEvent(evt);
}

// Registry: key -> { load: () => Promise, containerId }
const _sectionRegistry = {};
export function registerSectionLoaders(registry) {
  Object.assign(_sectionRegistry, registry);
}

// IntersectionObserver: lazily load each registered section when visible.
export function initSectionObserver() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const key = el.getAttribute('data-smart-loader');
      if (!key) return;
      observer.unobserve(el);
      const entryItem = _sectionRegistry[key];
      if (entryItem && typeof entryItem.load === 'function') {
        setSmartLoader(key, true);
        entryItem.load().catch(() => {}).finally(() => setSmartLoader(key, false));
      }
    });
  }, { rootMargin: '200px' });
  document.querySelectorAll('[data-smart-loader]').forEach(el => observer.observe(el));
  return observer;
}

// Focus trap + Escape for modals.
export function trapFocus(modalEl, openFocusEl) {
  const focusables = modalEl.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  function onKey(e) {
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === first || !modalEl.contains(document.activeElement)) {
          e.preventDefault(); last.focus();
        }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    if (e.key === 'Escape') { close(); }
  }
  function close() {
    modalEl.style.display = 'none';
    document.removeEventListener('keydown', onKey);
    if (openFocusEl) openFocusEl.focus();
  }
  document.addEventListener('keydown', onKey);
  (openFocusEl || first)?.focus();
  return { close };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/core.js tests/test_smart_core_js.py
git commit -m "feat: add smart-analytics core module (state, fetch, loaders, modes)"
```

---

### Task 9: Create `static/js/smart/decision-board.js`

**Files:**
- Create: `static/js/smart/decision-board.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `smartState`, `apiSmartGet`, `_smartEscapeHtml`, `_t`, `_fmtNum`, `_riskBadge`, `smartTranslateFeature` from `core.js`.
- Produces (exports): `loadDecisionBoard(month)` (fetches `/smart/decision-board/{month}`, renders KPI grid + critical list + early warnings + healthy hospitals), `renderKPIs(kpi, hospitalsCount)`, `renderCriticalList(anomalies)`, `renderEarlyWarnings(ew)`, `renderHealthyHospitals(healthy)`, and `window._smartKPIAnomalies`, `window._smartKPIGovernorates`, `window._smartKPIFactors`, `window._smartKPIStatus` (modal openers, kept for inline onclick).
- Produces: `window.SMART_ARABIC` (feature-name dict, moved from old file) so `smartTranslateFeature` works.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_decision_board_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["loadDecisionBoard", "renderKPIs", "renderCriticalList",
                 "renderEarlyWarnings", "renderHealthyHospitals"]:
        assert f"export function {name}" in js, name
    assert "smart-decision-board" in js
    assert "smart-critical-list" in js


def test_decision_board_uses_decision_endpoint():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "/smart/decision-board/" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_decision_board_module_exists tests/test_smart_core_js.py::test_decision_board_uses_decision_endpoint -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/decision-board.js`:

```javascript
// decision-board.js — the above-the-fold decision board for monthly mode.
import { smartState, apiSmartGet, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature, SMART_COLORS } from './core.js';

// Arabic labels for feature keys (moved from the monolithic file).
window.SMART_ARABIC = window.SMART_ARABIC || {};
Object.assign(window.SMART_ARABIC, {
  cs_rate: 'معدل القيصارية', smm_total: 'المضاعفات الخطيرة', mat_deaths: 'الوفيات الأمومية',
  nd: 'وفيات المولودين', sb: 'الولادات الميتة', preterm: 'الولادات السابقة لأوانها',
  lbw: 'نقص وزن الولادة', total_births: 'إجمالي المواليد', high_risk: 'حالات الخطر العالي',
  adolescent: 'الحالات المراهقة', governorate: 'المحافظة', hospital_type: 'نوع المستشفى',
  cs_per_birth: 'نسبة القيصارية لكل ولادة', smm_per_1000: 'المضاعفات لكل 1000 ولادة',
  mat_mortality_rate: 'معدل الوفيات الأمومية', stillbirth_rate: 'معدل الولادات الميتة',
  preterm_rate: 'معدل الولادات المبكرة', lbw_rate: 'معدل نقص الوزن',
  high_risk_rate: 'نسبة الخطر العالي', adolescent_rate: 'نسبة الحالات المراهقة',
  cs_x_highrisk: 'قيصارية × خطر عالي', preterm_x_lbw: 'ولادة مبكرة × نقص وزن',
  smm_x_matdeaths: 'مضاعفات × وفيات أمومية', nd_x_sb: 'وفيات جديدة × ولادات ميتة',
  cs_rate_delta: 'تغير معدل القيصارية', smm_delta: 'تغير المضاعفات',
  mat_deaths_delta: 'تغير الوفيات الأمومية', total_births_delta: 'تغير المواليد',
});
['cs_rate', 'smm_total', 'mat_deaths', 'total_births', 'nd', 'sb'].forEach(k => {
  window.SMART_ARABIC['lag1_' + k] = (window.SMART_ARABIC[k] || k) + ' (قيمة الشهر السابق)';
  window.SMART_ARABIC['lag2_' + k] = (window.SMART_ARABIC[k] || k) + ' (قيمة شهرين سابقين)';
});
['cs_rate', 'smm_total', 'mat_deaths', 'nd', 'sb', 'preterm', 'lbw', 'total_births', 'high_risk', 'adolescent'].forEach(k => {
  window.SMART_ARABIC['delta_' + k] = 'التغيّر الشهري في ' + (window.SMART_ARABIC[k] || k);
});

function openSmartModal(title, bodyHtml) {
  const modal = document.getElementById('smart-kpi-modal');
  document.getElementById('smart-kpi-modal-title').textContent = title;
  document.getElementById('smart-kpi-modal-body').innerHTML = bodyHtml;
  modal.style.display = 'flex';
  modal.onclick = function(e) { if (e.target === modal) modal.style.display = 'none'; };
}

export async function loadDecisionBoard(month) {
  const data = await apiSmartGet(`/smart/decision-board/${month}`);
  smartState.month = month;
  if (data.empty) {
    const status = document.getElementById('smart-status');
    if (status) status.textContent = data.message || _t('No data for this month');
    const c = document.getElementById('smart-kpi-container');
    if (c) c.innerHTML = `<div class="smart-empty-state">${_smartEscapeHtml(data.message || '')}</div>`;
    return;
  }
  document.getElementById('smart-decision-month').textContent = month;
  renderKPIs(data.kpi, data.hospitals_count);
  renderCriticalList(data.anomalies);
  renderEarlyWarnings(data.early_warnings);
  renderHealthyHospitals(data.healthy_hospitals);
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Updated') + ' — ' + data.hospitals_count + ' ' + _t('hospitals');
}

export function renderKPIs(kpi, hospitalsCount) {
  const c = document.getElementById('smart-kpi-container');
  if (!c) return;
  const statusColor = kpi.month_status === 'critical' ? SMART_COLORS.critical
    : kpi.month_status === 'attention_needed' ? SMART_COLORS.warning : SMART_COLORS.normal;
  const statusText = kpi.month_status === 'critical' ? _t('Needs urgent action')
    : kpi.month_status === 'attention_needed' ? _t('Needs ongoing monitoring') : _t('Within normal range');
  const statusIcon = kpi.month_status === 'critical' ? '❌' : kpi.month_status === 'attention_needed' ? '⚠️' : '✅';
  const criticalPct = hospitalsCount > 0 ? Math.round(kpi.critical_count / hospitalsCount * 100) : 0;
  const warningPct = hospitalsCount > 0 ? Math.round(kpi.warning_count / hospitalsCount * 100) : 0;
  const normalCount = hospitalsCount - kpi.critical_count - kpi.warning_count;

  c.innerHTML = `
    <div class="smart-kpi-card" style="border-top-color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};" onclick="window._smartKPIAnomalies()">
      <div class="smart-kpi-value" style="color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};">${kpi.total_anomalies}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount}</span></div>
      <div class="smart-kpi-label">${_t('Hospitals with anomalies')}</div>
      <div class="smart-kpi-sub">${kpi.critical_count} ${_t('critical')} (${criticalPct}%) + ${kpi.warning_count} ${_t('warning')} (${warningPct}%)</div>
    </div>
    <div class="smart-kpi-card" style="border-top-color:#3b82f6;" onclick="window._smartKPIGovernorates()">
      <div class="smart-kpi-value" style="color:#3b82f6;">${kpi.affected_governorates}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount > 0 ? Math.min(hospitalsCount, 5) : 5}</span></div>
      <div class="smart-kpi-label">${_t('Governorates with deviations')}</div>
      <div class="smart-kpi-sub">${_t('Contain warning or critical hospitals')}</div>
    </div>
    <div class="smart-kpi-card" style="border-top-color:#8b5cf6;" onclick="window._smartKPIFactors()">
      <div class="smart-kpi-value" style="font-size:1rem;color:#8b5cf6;word-break:break-word;line-height:1.4;">${_smartEscapeHtml(smartTranslateFeature(kpi.top_contributing_factor) || _t('Undefined'))}</div>
      <div class="smart-kpi-label">${_t('Top contributing factor')}</div>
      <div class="smart-kpi-sub">${_t('SHAP analysis of drivers')}</div>
    </div>
    <div class="smart-kpi-card" style="border-left:4px solid ${statusColor};" onclick="window._smartKPIStatus()">
      <div class="smart-kpi-value" style="font-size:1.2rem;">${statusIcon} ${_smartEscapeHtml(statusText)}</div>
      <div class="smart-kpi-label">${_t('Month status')}</div>
      <div class="smart-kpi-sub">${hospitalsCount} ${_t('hospitals')} — ${normalCount} ${_t('normal')}, ${kpi.warning_count} ${_t('warning')}, ${kpi.critical_count} ${_t('critical')}</div>
    </div>
  `;
}

export function renderCriticalList(anomalies) {
  const container = document.getElementById('smart-critical-list');
  const countEl = document.getElementById('smart-critical-count');
  const textEl = document.getElementById('smart-critical-text');
  if (!container) return;
  const critical = (anomalies || []).filter(a => a.severity === 'critical');
  const warnings = (anomalies || []).filter(a => a.severity === 'warning');
  if (countEl) countEl.textContent = `${critical.length} ${_t('critical')} · ${warnings.length} ${_t('warning')}`;
  if (critical.length === 0) {
    container.innerHTML = `<div class="smart-priority-item smart-priority-normal">
      <div>✅ ${_t('No critical hospitals this month')}</div>
    </div>`;
    if (textEl) textEl.textContent = _t('Warning hospitals (0.3-0.6) — open the anomaly table to follow up.');
    return;
  }
  container.innerHTML = critical.map(h => {
    const hid = parseInt(h.hospital_id, 10);
    const month = smartState.month || '';
    return `<div class="smart-priority-item smart-priority-critical">
      <div>
        <div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
        <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')}${h.hospital_type ? ' · ' + _smartEscapeHtml(h.hospital_type) : ''}</div>
      </div>
      <div style="display:flex;gap:0.4rem;align-items:center;">
        ${_riskBadge(h.anomaly_score.toFixed(3), 'critical')}
        <button class="btn btn-sm btn-outline" onclick="window.smartDrilldown(${hid})">📊 ${_t('Details')}</button>
        <button class="btn btn-sm" style="background:#dc2626;color:#fff;border:none;" onclick="window.smartGoRootCause(${hid}, '${month}')">🔍 ${_t('Root cause')}</button>
      </div>
    </div>`;
  }).join('');
  if (textEl) textEl.textContent = _t('Critical hospitals (>0.6) need urgent intervention.');
}

export function renderEarlyWarnings(ew) {
  const container = document.getElementById('smart-early-warnings');
  if (!container) return;
  const warnings = ew?.warnings || [];
  if (!warnings.length) { container.innerHTML = ''; return; }
  const rows = warnings.slice(0, 6).map(w => {
    const badge = w.severity === 'critical' ? '<span class="smart-badge smart-badge-critical">' + _t('critical') + '</span>'
      : w.severity === 'warning' ? '<span class="smart-badge smart-badge-warning">' + _t('warning') + '</span>'
      : '<span class="smart-badge smart-badge-normal">' + _t('info') + '</span>';
    return `<div class="smart-priority-item smart-priority-${w.severity === 'critical' ? 'critical' : 'warning'}">
      <div>
        <div class="smart-priority-name">${_smartEscapeHtml(w.hospital_name || '')}</div>
        <div class="smart-priority-meta">${_smartEscapeHtml(w.hospital_governorate || '')} — ${_smartEscapeHtml((w.leading_rising || []).map(l => l.metric_ar || l.metric).join(', '))}</div>
      </div>
      <div>${badge} <span style="font-size:0.72rem;color:#6b7280;">${_fmtNum(w.probability, 2)}</span></div>
    </div>`;
  }).join('');
  container.innerHTML = `<div class="smart-section-card">
    <div class="smart-section-header" data-smart-collapsible="smart-early-warnings-body">
      <span>⚠️ ${_t('Early Warning System')}</span><span class="smart-toggle-icon">▾</span>
    </div>
    <div id="smart-early-warnings-body" class="smart-section-body"><div class="smart-priority-list">${rows}</div></div>
  </div>`;
}

export function renderHealthyHospitals(healthy) {
  const container = document.getElementById('smart-healthy-hospitals');
  if (!container) return;
  const list = healthy || [];
  if (!list.length) { container.innerHTML = ''; return; }
  const rows = list.map(h => `<div class="smart-priority-item smart-priority-normal">
    <div>
      <div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
      <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')} · ${_t('composite')}: ${_fmtNum(h.composite_score, 1)}</div>
    </div>
  </div>`).join('');
  container.innerHTML = `<div class="smart-section-card">
    <div class="smart-section-header" data-smart-collapsible="smart-healthy-body">
      <span>🏆 ${_t('Healthy hospitals (models to follow)')}</span><span class="smart-toggle-icon">▾</span>
    </div>
    <div id="smart-healthy-body" class="smart-section-body"><div class="smart-priority-list">${rows}</div></div>
  </div>`;
}

// KPI modal openers (kept on window for inline onclick compatibility).
window._smartKPIAnomalies = function() {
  if (!smartState.data || !smartState.data.anomalies) return;
  const anomalies = smartState.data.anomalies || [];
  const total = smartState.data.hospitals_count || anomalies.length;
  const sorted = [...anomalies].sort((a, b) => b.anomaly_score - a.anomaly_score);
  const rows = sorted.map((a, i) => `<tr>
    <td style="padding:0.4rem 0.6rem;text-align:center;color:#999;font-size:0.8rem;">${i + 1}</td>
    <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:600;font-size:0.82rem;">${_smartEscapeHtml(a.hospital_name)}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;font-size:0.75rem;">${_smartEscapeHtml(a.governorate || '-')}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;">${_riskBadge(a.anomaly_score.toFixed(3), a.severity)}</td>
  </tr>`).join('');
  openSmartModal('🔍 ' + _t('Anomaly details'), `<div class="smart-table-wrap"><table><thead><tr><th>#</th><th>${_t('Hospital')}</th><th>${_t('Governorate')}</th><th>${_t('Score')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIGovernorates = function() {
  if (!smartState.data) return;
  const geo = smartState.data.geo || {};
  const govs = (geo.governorates || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  const rows = govs.map(g => `<tr>
    <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:600;font-size:0.82rem;">${_smartEscapeHtml(g.governorate)}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;font-size:0.78rem;">${g.hospital_count}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;">${_riskBadge(_fmtNum(g.avg_anomaly_score, 3), g.avg_anomaly_score >= 0.6 ? 'critical' : g.avg_anomaly_score >= 0.3 ? 'warning' : 'normal')}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;font-size:0.78rem;">${g.outlier_count}</td>
  </tr>`).join('');
  openSmartModal('🗺️ ' + _t('Governorates'), `<div class="smart-table-wrap"><table><thead><tr><th>${_t('Governorate')}</th><th>${_t('Hospitals')}</th><th>${_t('Avg score')}</th><th>${_t('Outliers')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIFactors = function() {
  if (!smartState.data) return;
  const exps = smartState.data.explanations || [];
  const factors = {};
  exps.forEach(e => (e.top_factors || []).forEach(f => {
    factors[f.arabic_label || f.feature] = (factors[f.arabic_label || f.feature] || 0) + Math.abs(f.shap_value || 0);
  }));
  const sorted = Object.entries(factors).sort((a, b) => b[1] - a[1]);
  const rows = sorted.map(([name, value], i) => `<tr>
    <td style="padding:0.4rem 0.6rem;text-align:center;color:#999;font-size:0.8rem;">${i + 1}</td>
    <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:600;font-size:0.82rem;">${_smartEscapeHtml(name)}</td>
    <td style="padding:0.4rem 0.6rem;text-align:center;font-size:0.78rem;">${_fmtNum(value, 3)}</td>
  </tr>`).join('');
  openSmartModal('🧠 ' + _t('Top contributing factors'), `<div class="smart-table-wrap"><table><thead><tr><th>#</th><th>${_t('Factor')}</th><th>${_t('Impact')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIStatus = function() {
  if (!smartState.data) return;
  const kpi = smartState.data.kpi || {};
  const level = kpi.month_status === 'critical' ? 'critical' : kpi.month_status === 'attention_needed' ? 'warning' : 'normal';
  openSmartModal('📊 ' + _t('Month status'), `<div class="smart-priority-list">
    <div class="smart-priority-item smart-priority-${level}">
      <div>
        <div class="smart-priority-name">${_t('Month status')}: ${_smartEscapeHtml(kpi.month_status_ar || kpi.month_status || '')}</div>
        <div class="smart-priority-meta">${_t('Hospitals with anomalies')}: ${kpi.total_anomalies} / ${smartState.data.hospitals_count || 0}</div>
      </div>
    </div>
  </div>`);
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/decision-board.js tests/test_smart_core_js.py
git commit -m "feat: add smart decision-board module with KPI modals and SMART_ARABIC dict"
```

---

### Task 10: Create `static/js/smart/charts.js` (Plotly helpers)

**Files:**
- Create: `static/js/smart/charts.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `SMART_COLORS` from `core.js`; global `Plotly` (still loaded from `static/index.html`).
- Produces (exports): `smartChartTheme` (shared Plotly layout presets incl. RTL-aware margins + Arabic digit formatting), `renderPlot(divId, data, layout, options)` (wrapper with error handling), `makeLineChart(divId, trace, opts)`, `makeBarChart(divId, labels, values, opts)`, `makeScatter(divId, traces, opts)`, `makeHeatmap(divId, z, x, y, opts)`, `makeDonut(divId, labels, values, opts)`, `renderWaterfall(divId, factors, opts)`.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_charts_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "charts.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["smartChartTheme", "renderPlot", "makeLineChart", "makeBarChart",
                 "makeScatter", "makeHeatmap", "makeDonut", "renderWaterfall"]:
        assert f"export function {name}" in js or f"export const {name}" in js, name
    assert "Plotly" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_charts_module_exists -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/charts.js`:

```javascript
// charts.js — Plotly wrappers shared by all smart-analytics renderers.
import { SMART_COLORS } from './core.js';

const ARABIC_DIGITS = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];
export function formatArabicDigits(value) {
  return String(value).replace(/[0-9]/g, d => ARABIC_DIGITS[+d]);
}

export const smartChartTheme = {
  font: { family: 'Segoe UI, Tahoma, Arial, sans-serif', size: 12 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  margin: { l: 46, r: 16, t: 36, b: 44 },
  hoverlabel: { align: 'left' },
  legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center' },
};

export function renderPlot(divId, data, layout, options) {
  const el = document.getElementById(divId);
  if (!el) return;
  Plotly.react(el, data, Object.assign({}, smartChartTheme, layout || {}), Object.assign({ responsive: true, displaylogo: false }, options || {}));
}

export function makeLineChart(divId, x, y, name, opts = {}) {
  renderPlot(divId, [{
    x, y, name, type: 'scatter', mode: 'lines+markers',
    line: { color: opts.color || SMART_COLORS.warning, width: 2.5, shape: opts.shape || 'linear' },
    marker: { size: opts.size || 5 },
  }], { title: opts.title || '', yaxis: { title: opts.yTitle || '' }, xaxis: { title: opts.xTitle || '' } });
}

export function makeBarChart(divId, labels, values, opts = {}) {
  const color = opts.colors || Array(labels.length).fill(SMART_COLORS.warning);
  renderPlot(divId, [{ x: labels, y: values, type: 'bar', marker: { color } }],
    { title: opts.title || '', yaxis: { title: opts.yTitle || '' } });
}

export function makeScatter(divId, traces, opts = {}) {
  renderPlot(divId, traces.map(t => Object.assign({ type: 'scatter', mode: 'markers' }, t)),
    { title: opts.title || '', xaxis: { title: opts.xTitle || '' }, yaxis: { title: opts.yTitle || '' } });
}

export function makeHeatmap(divId, z, x, y, opts = {}) {
  renderPlot(divId, [{ z, x, y, type: 'heatmap', colorscale: opts.colorscale || 'RdBu', zmid: opts.zmid ?? 0 }],
    { title: opts.title || '', xaxis: { tickangle: -45 } });
}

export function makeDonut(divId, labels, values, opts = {}) {
  renderPlot(divId, [{
    labels, values, type: 'pie', hole: 0.55,
    marker: { colors: opts.colors || Object.values(SMART_COLORS.clusters) },
    textinfo: 'label+percent',
  }], { title: opts.title || '', showlegend: opts.showlegend !== false });
}

export function renderWaterfall(divId, factors, opts = {}) {
  // SHAP waterfall: horizontal bars from negative to positive around 0.
  const names = factors.map(f => f.arabic_label || f.feature);
  const values = factors.map(f => f.shap_value || 0);
  renderPlot(divId, [{
    x: values, y: names, type: 'bar', orientation: 'h',
    marker: { color: values.map(v => v >= 0 ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative) },
    text: values.map(v => v.toFixed(3)),
  }], { title: opts.title || 'SHAP', xaxis: { title: 'SHAP value' }, margin: { l: 140, r: 16, t: 36, b: 40 } });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py::test_charts_module_exists -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/charts.js tests/test_smart_core_js.py
git commit -m "feat: add smart charts module with shared Plotly helpers"
```

---

### Task 11: Create `static/js/smart/advanced.js` (clusters, correlations, residuals, patterns, lag-analysis, xgboost, feature importance)

**Files:**
- Create: `static/js/smart/advanced.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `core.js` (`smartState`, `apiSmartGet`, `setSmartLoader`, `showSmartSectionError`, `showSmartSectionEmpty`, `clearSmartSectionState`, `_smartEscapeHtml`, `_t`, `_fmtNum`, `smartTranslateFeature`), `charts.js` renderers.
- Produces (exports): `initAdvancedTabs()`, `loadAdvancedSection(month)` (lazy per-tab loader entry), `loadClustersTab(month)`, `loadCorrelationsTab(month)`, `loadPatternsTab(month)`, `loadXGBoostTab(month)`, `loadFeatureImportanceTab(month)`, `renderClusterScatter(data)`, `renderClusterProfiles(data)`, `renderCorrelationHeatmap(data)`, `renderResidualPlot(data)`, `renderCompositePatterns(data)`, `renderLagAnalysis(data)`, `renderXGBoost(data)`, `renderFeatureImportance(data)`. Section loaders fetch `/smart/clusters/{month}`, `/smart/correlations/{month}`, `/smart/residuals/{month}`, `/smart/patterns/{month}`, `/smart/lag-analysis/{month}`, `/smart/xgboost/{month}` — never a full `/overview` payload.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_advanced_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["initAdvancedTabs", "loadAdvancedSection", "loadClustersTab",
                 "loadCorrelationsTab", "loadPatternsTab", "loadXGBoostTab"]:
        assert f"export function {name}" in js, name


def test_advanced_uses_section_endpoints():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for path_part in ["/smart/clusters/", "/smart/correlations/", "/smart/patterns/",
                      "/smart/lag-analysis/", "/smart/xgboost/"]:
        assert path_part in js, path_part
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_advanced_module_exists tests/test_smart_core_js.py::test_advanced_uses_section_endpoints -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/advanced.js`:

```javascript
// advanced.js — heavy analytical sections (clusters, correlations, patterns, forecasts).
import { smartState, apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, _smartEscapeHtml, _t, _fmtNum, smartTranslateFeature } from './core.js';
import { renderPlot, makeScatter, makeHeatmap, makeBarChart, makeLineChart } from './charts.js';

export function initAdvancedTabs() {
  const loaders = {
    'clusters-tab': loadClustersTab,
    'corr-tab': loadCorrelationsTab,
    'patterns-tab': loadPatternsTab,
    'fi-tab': loadFeatureImportanceTab,
  };
  document.querySelectorAll('.smart-tab-btn[data-smart-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.smart-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('[id$="-tab"]').forEach(t => t.style.display = 'none');
      const tab = document.getElementById(btn.dataset.smartTab);
      if (tab) tab.style.display = 'block';
      // load the newly selected tab's data on demand
      const loader = loaders[btn.dataset.smartTab];
      if (loader && smartState.month) loader(smartState.month);
    });
  });
}

async function fetchSection(path, key) {
  const res = await apiSmartGet(path);
  if (res && res.empty) {
    showSmartSectionEmpty(key, res.message || _t('No data'));
  }
  return res;
}

export function loadClustersTab(month) {
  return fetchSection(`/smart/clusters/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const clustering = d.clustering || {};
    const points = clustering.points || [];
    renderClusterScatter(points, clustering.labels || [], clustering.features || []);
    renderClusterProfiles(clustering.profiles || []);
  });
}

export function loadCorrelationsTab(month) {
  return fetchSection(`/smart/correlations/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const corr = d.correlations || {};
    renderCorrelationHeatmap(corr.matrix || [], corr.features || []);
    return fetchSection(`/smart/residuals/${month}`, 'advanced').then(rd => {
      if (!rd || rd.empty) return;
      renderResidualPlot(rd.residuals || []);
    });
  });
}

export function loadPatternsTab(month) {
  return fetchSection(`/smart/patterns/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    renderCompositePatterns(d.patterns || []);
    return fetchSection(`/smart/lag-analysis/${month}`, 'advanced').then(ld => {
      if (!ld || ld.empty) return;
      renderLagAnalysis(ld.lag_analysis || {});
    });
  });
}

export function loadXGBoostTab(month) {
  return fetchSection(`/smart/xgboost/${month}`, 'xgboost').then(d => {
    if (!d || d.empty) return;
    renderXGBoost(d.xgboost || {});
  });
}

export function loadFeatureImportanceTab(month) {
  // Derived from the anomaly explanations already fetched by the decision board.
  const data = smartState.data;
  if (!data) return Promise.resolve();
  renderFeatureImportance((data.explanations || []));
}

export function loadAdvancedSection(month) {
  // Entry used by the IntersectionObserver: load only the active tab's data.
  const active = document.querySelector('.smart-tab-btn.active');
  const tab = active ? active.dataset.smartTab : 'clusters-tab';
  if (tab === 'clusters-tab') return loadClustersTab(month);
  if (tab === 'corr-tab') return loadCorrelationsTab(month);
  if (tab === 'patterns-tab') return loadPatternsTab(month);
  if (tab === 'fi-tab') return loadFeatureImportanceTab(month);
  return loadXGBoostTab(month);
}

export function renderClusterScatter(points, labels, features) {
  const colors = ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'];
  const clusters = [...new Set(labels)];
  const traces = clusters.map((c, i) => {
    const pts = points.filter((_, idx) => labels[idx] === c);
    return {
      x: pts.map(p => p[0]), y: pts.map(p => p[1]),
      name: `${_t('Cluster')} ${c}`,
      type: 'scatter', mode: 'markers',
      marker: { color: colors[i % colors.length] },
    };
  });
  renderPlot('smart-cluster-scatter', traces, {
    xaxis: { title: features[0] || 'PC1' }, yaxis: { title: features[1] || 'PC2' },
  });
}

export function renderClusterProfiles(profiles) {
  const c = document.getElementById('smart-cluster-profiles');
  if (!c) return;
  c.innerHTML = profiles.map(p => `<div class="smart-priority-item smart-priority-normal">
    <div><div class="smart-priority-name">${_t('Cluster')} ${_smartEscapeHtml(p.cluster)} — ${_fmtNum(p.size)} ${_t('hospitals')}</div>
    <div class="smart-priority-meta">${_smartEscapeHtml(p.description || '')}</div></div>
  </div>`).join('');
}

export function renderCorrelationHeatmap(matrix, features) {
  makeHeatmap('smart-correlation-heatmap', matrix, features, features, { title: _t('Feature correlations') });
}

export function renderResidualPlot(residuals) {
  const c = document.getElementById('smart-residual-plot');
  if (!c) return;
  renderPlot('smart-residual-plot', [{
    x: residuals.map(r => r.hospital_id), y: residuals.map(r => r.residual),
    type: 'bar', marker: { color: residuals.map(r => r.residual > 0 ? '#ef4444' : '#3b82f6') },
  }], { title: _t('Residuals by hospital'), xaxis: { title: _t('Hospital ID') } });
  const _ = c; // container kept for no-op guards
}

export function renderCompositePatterns(patterns) {
  const c = document.getElementById('smart-composite-patterns');
  if (!c) return;
  if (!patterns.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No composite patterns')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Pattern')}</th><th>${_t('Hospitals')}</th><th>${_t('Description')}</th>
  </tr></thead><tbody>` + patterns.map(p => `<tr>
    <td style="font-weight:600;">${_smartEscapeHtml(p.name)}</td>
    <td>${_smartEscapeHtml((p.hospitals || []).join('، '))}</td>
    <td style="font-size:0.78rem;">${_smartEscapeHtml(p.description_ar || p.description || '')}</td>
  </tr>`).join('') + `</tbody></table></div>`;
}

export function renderLagAnalysis(lag) {
  const c = document.getElementById('smart-lag-analysis');
  if (!c) return;
  const matrix = lag.matrix || [];
  const html = `<div class="smart-table-wrap"><table><thead><tr><th></th>${
    matrix.map(m => `<th>${_smartEscapeHtml(smartTranslateFeature(m.feature))}</th>`).join('')}
  </tr></thead><tbody>` + matrix.map(row => `<tr>
    <td style="font-weight:600;">${_smartEscapeHtml(smartTranslateFeature(row.feature))}</td>
    ${matrix.map(m => `<td style="text-align:center;">${m.feature === row.feature ? '—' : _fmtNum(row.values[m.feature], 2)}</td>`).join('')}
  </tr>`).join('') + `</tbody></table></div>`;
  const note = lag.note_ar || lag.note_en || '';
  c.innerHTML = (note ? `<div class="smart-empty-state">${_smartEscapeHtml(note)}</div>` : '') + html;
}

export function renderXGBoost(xgb) {
  const pred = xgb.predictions || [];
  const c = document.getElementById('smart-xgboost-predictions');
  if (!c) return;
  if (!pred.length) { c.innerHTML = `<div class="smart-empty-state">${_t('Not enough predictions for this month')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Hospital')}</th><th>${_t('Predicted score')}</th><th>${_t('Risk')}</th></tr></thead><tbody>` +
    pred.map(p => `<tr><td>${_smartEscapeHtml(p.hospital_name)}</td>
      <td>${_fmtNum(p.prediction, 3)}</td>
      <td>${_riskLevel(p.prediction)}</td></tr>`).join('') + `</tbody></table></div>`;
}

export function renderFeatureImportance(explanations) {
  const c = document.getElementById('smart-feature-importance');
  if (!c) return;
  const factors = {};
  (explanations || []).forEach(e => (e.top_factors || []).forEach(f => {
    const key = f.arabic_label || f.feature;
    factors[key] = (factors[key] || 0) + Math.abs(f.shap_value || 0);
  }));
  const sorted = Object.entries(factors).sort((a, b) => b[1] - a[1]).slice(0, 15);
  makeBarChart('smart-feature-importance', sorted.map(x => x[0]), sorted.map(x => x[1]), {
    title: _t('Feature importance (SHAP)'), colors: '#8b5cf6',
  });
  const _ = c;
}

function _riskLevel(score) {
  const label = score >= 0.6 ? _t('critical') : score >= 0.3 ? _t('warning') : _t('normal');
  const cls = score >= 0.6 ? 'smart-badge-critical' : score >= 0.3 ? 'smart-badge-warning' : 'smart-badge-normal';
  return `<span class="${cls}">${_smartEscapeHtml(label)}</span>`;
}
```

> Note: `_riskLevel` is module-private; the public risk badge lives in `core.js` (`_riskBadge`). Do not re-export.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py::test_advanced_module_exists tests/test_smart_core_js.py::test_advanced_uses_section_endpoints -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/advanced.js tests/test_smart_core_js.py
git commit -m "feat: add smart advanced module with lazy per-tab section loading"
```

---

### Task 12: Create `static/js/smart/geo-regional.js` (map, governorates, regional)

**Files:**
- Create: `static/js/smart/geo-regional.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `core.js`, `charts.js`.
- Produces (exports): `loadGeoSection(month)` (fetch `/smart/geo/{month}`; on `empty` → `showSmartSectionEmpty`), `renderGeoMap(geo)`, `renderGovernorates(geo)`, `renderRegionalAnalysis(geo)`.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_geo_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "geo-regional.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["loadGeoSection", "renderGeoMap", "renderGovernorates", "renderRegionalAnalysis"]:
        assert f"export function {name}" in js, name
    assert "/smart/geo/" in js
    assert "smart-geo-map" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_geo_module_exists -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/geo-regional.js`:

```javascript
// geo-regional.js — map, governorate, and regional analysis for monthly mode.
import { apiSmartGet, showSmartSectionError, showSmartSectionEmpty,
         _smartEscapeHtml, _t, _fmtNum, _riskBadge } from './core.js';
import { renderPlot, makeBarChart } from './charts.js';

export async function loadGeoSection(month) {
  try {
    const d = await apiSmartGet(`/smart/geo/${month}`);
    if (d.empty) { showSmartSectionEmpty('geo', d.message || _t('No data')); return; }
    renderGeoMap(d.geo || {});
    renderGovernorates(d.geo || {});
    renderRegionalAnalysis(d.geo || {});
  } catch (e) {
    showSmartSectionError('geo', e.message);
  }
}

export function renderGeoMap(geo) {
  const mapDiv = document.getElementById('smart-geo-map');
  if (!mapDiv) return;
  const regions = geo.regions || [];
  renderPlot('smart-geo-map', [{
    type: 'choropleth', locationmode: 'ISO-3',
    locations: regions.map(r => r.iso3), z: regions.map(r => r.avg_anomaly_score),
    text: regions.map(r => r.governorate),
    colorscale: [[0, '#22c55e'], [0.5, '#f59e0b'], [1, '#ef4444']],
    zmin: 0, zmax: 1,
    marker: { line: { color: '#fff', width: 1 } },
  }], { title: _t('Geographic distribution'), geo: { showframe: false, showcoastlines: false } });
}

export function renderGovernorates(geo) {
  const c = document.getElementById('smart-governorate-content');
  if (!c) return;
  const govs = (geo.governorates || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Governorate')}</th><th>${_t('Hospitals')}</th><th>${_t('Avg score')}</th>
    <th>${_t('Outliers')}</th></tr></thead><tbody>` +
    govs.map(g => `<tr>
      <td style="font-weight:600;">${_smartEscapeHtml(g.governorate)}</td>
      <td style="text-align:center;">${g.hospital_count}</td>
      <td style="text-align:center;">${_riskBadge(_fmtNum(g.avg_anomaly_score, 3), g.avg_anomaly_score >= 0.6 ? 'critical' : g.avg_anomaly_score >= 0.3 ? 'warning' : 'normal')}</td>
      <td style="text-align:center;">${g.outlier_count}</td>
    </tr>`).join('') + `</tbody></table></div>`;
}

export function renderRegionalAnalysis(geo) {
  const c = document.getElementById('smart-regional-content');
  if (!c) return;
  const regions = geo.regions || [];
  if (!regions.length) { c.innerHTML = ''; return; }
  makeBarChart('smart-regional-content-chart', regions.map(r => r.governorate),
    regions.map(r => r.avg_anomaly_score),
    { title: _t('Regional average anomaly score') });
  // makeBarChart renders into a div id; reuse a hidden chart host injected here.
  c.innerHTML = '<div id="smart-regional-content-chart" style="height:240px;"></div>';
  makeBarChart('smart-regional-content-chart', regions.map(r => r.governorate),
    regions.map(r => r.avg_anomaly_score), { title: _t('Regional average anomaly score') });
}
```

> Note: the second `makeBarChart` call after injecting the container is intentional (chart host must exist in the DOM before Plotly.react). Do not "clean up" into a single call.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py::test_geo_module_exists -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/geo-regional.js tests/test_smart_core_js.py
git commit -m "feat: add smart geo-regional module"
```

---

### Task 13: Create `static/js/smart/hospital.js` (hospital mode, drilldown, root cause)

**Files:**
- Create: `static/js/smart/hospital.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `core.js`, `charts.js`.
- Produces (exports): `initHospitalSelect()`, `loadHospitalMode(hospitalId, months)` (fetch `/smart/trend/{id}` and `/smart/drilldown/{id}/all`; renders name, trend chart, forecast, factor table), `renderTrend(hospitalId)`, `renderHospitalForecast(forecast)`, `renderHospitalFactors(factors)`.
- Produces (window globals for inline onclick): `window.smartDrilldown(hospitalId)`, `window.smartGoRootCause(hospitalId, month)`.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_hospital_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "hospital.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["initHospitalSelect", "loadHospitalMode", "renderTrend", "renderHospitalForecast"]:
        assert f"export function {name}" in js, name
    assert "window.smartDrilldown" in js
    assert "window.smartGoRootCause" in js
    assert "/smart/drilldown/" in js
    assert "/smart/trend/" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_hospital_module_exists -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/hospital.js`:

```javascript
// hospital.js — hospital-scope mode: trend, forecast, drilldown, root cause.
import { smartState, apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature } from './core.js';
import { renderPlot, makeLineChart, renderWaterfall } from './charts.js';

export function initHospitalSelect(hospitals) {
  const select = document.getElementById('smart-hospital-context-select');
  const monthlySelect = document.getElementById('smart-hospital-select');
  if (select) {
    select.innerHTML = '<option value="">-- ' + _t('Select Hospital') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
  if (monthlySelect && monthlySelect.options.length === 1) {
    monthlySelect.innerHTML = '<option value="">-- ' + _t('All Hospitals') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
}

export async function loadHospitalMode(hospitalId, months) {
  const panel = document.getElementById('smart-hospital-panel');
  if (!panel) return;
  setSmartLoader('hospital', true);
  try {
    const trend = await apiSmartGet(`/smart/trend/${hospitalId}`);
    if (!trend.hospital_name) { showSmartSectionEmpty('hospital', _t('No data for this hospital')); return; }
    document.getElementById('smart-hospital-name').textContent = trend.hospital_name;
    renderTrend(trend);

    const drill = await apiSmartGet(`/smart/drilldown/${hospitalId}/all`);
    if (!drill.empty) {
      const forecast = drill.forecast || {};
      renderHospitalForecast(forecast);
      renderHospitalFactors(drill.anomaly, drill.explanation);
    } else {
      showSmartSectionEmpty('hospital', drill.message || _t('No data'));
    }
  } catch (e) {
    showSmartSectionError('hospital', e.message);
  } finally {
    setSmartLoader('hospital', false);
  }
}

export function renderTrend(trend) {
  const months = trend.trend.map(t => t.month);
  const scores = trend.trend.map(t => t.anomaly_score);
  const colors = trend.trend.map(t => t.severity === 'critical' ? '#ef4444' : t.severity === 'warning' ? '#f59e0b' : '#22c55e');
  renderPlot('smart-hospital-trend', [{
    x: months, y: scores, type: 'scatter', mode: 'lines+markers',
    line: { color: '#4338ca', width: 2.5 }, marker: { color, size: 8 },
    text: trend.trend.map(t => _t(t.severity)),
  }], { title: _t('Anomaly score over time'), yaxis: { range: [0, 1] } });
}

export function renderHospitalForecast(forecast) {
  const c = document.getElementById('smart-hospital-forecast');
  if (!c) return;
  const forecasts = forecast.forecasts || forecast.forecast || [];
  if (!forecasts.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No forecast available')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Month')}</th><th>${_t('Predicted score')}</th><th>${_t('Range')}</th></tr></thead><tbody>` +
    forecasts.map(f => `<tr><td>${_smartEscapeHtml(f.month)}</td>
      <td>${_fmtNum(f.prediction, 3)}</td>
      <td style="font-size:0.75rem;">${_fmtNum(f.lower, 3)} – ${_fmtNum(f.upper, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
}

export function renderHospitalFactors(anomaly, explanation) {
  const c = document.getElementById('smart-hospital-factors');
  if (!c) return;
  const factors = explanation?.top_factors || [];
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Factor')}</th><th>${_t('Value')}</th><th>${_t('SHAP')}</th></tr></thead><tbody>` +
    factors.map(f => `<tr><td>${_smartEscapeHtml(smartTranslateFeature(f.feature))}</td>
      <td>${_fmtNum(f.value, 3)}</td><td>${_fmtNum(f.shap_value, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
  if (factors.length) renderWaterfall('smart-shap-waterfall', factors);
}

export function openDrilldown(hospitalId) {
  const month = smartState.month || '';
  const modal = document.getElementById('smart-drilldown-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  apiSmartGet(`/smart/drilldown/${hospitalId}/${month}`).then(d => {
    if (d.empty || !d.anomaly) {
      document.getElementById('smart-drilldown-name').textContent = d.hospital_name || hospitalId;
      document.getElementById('smart-drilldown-text').textContent = d.message || _t('No data');
      return;
    }
    document.getElementById('smart-drilldown-name').textContent = d.hospital_name;
    document.getElementById('smart-drilldown-text').textContent = d.explanation?.text_ar || d.explanation?.text || '';
    const residuals = d.residuals || [];
    if (residuals.length) renderPlot('smart-trend-line', [{
      x: residuals.map(r => r.month), y: residuals.map(r => r.residual),
      type: 'bar', marker: { color: residuals.map(r => r.residual > 0 ? '#ef4444' : '#3b82f6') },
    }], { title: _t('Monthly residuals') });
    renderHospitalFactors(d.anomaly, d.explanation);
  }).catch(e => {
    document.getElementById('smart-drilldown-text').textContent = e.message;
  });
}

export function goRootCause(hospitalId, month) {
  // Root-cause navigation: switch to hospital mode and load the hospital.
  const btn = document.querySelector('.smart-mode-btn[data-smart-mode="hospital"]');
  if (btn) btn.click();
  const select = document.getElementById('smart-hospital-context-select');
  if (select && select.querySelector(`option[value="${hospitalId}"]`)) {
    select.value = String(hospitalId);
    select.dispatchEvent(new Event('change'));
  }
}

// Exposed for inline onclick attributes (kept for backward compatibility).
window.smartDrilldown = openDrilldown;
window.smartGoRootCause = goRootCause;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py::test_hospital_module_exists -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/hospital.js tests/test_smart_core_js.py
git commit -m "feat: add smart hospital module (mode, trend, drilldown, root cause)"
```

---

### Task 14: Create `static/js/smart/report.js` (report generation, export, comparison)

**Files:**
- Create: `static/js/smart/report.js`
- Modify: `tests/test_smart_core_js.py`
- Test: static assertions

**Interfaces:**
- Consumes: `core.js`, `charts.js`, `decision-board.js` (`loadDecisionBoard` not needed here; renders into `smart-report-section`).
- Produces (exports): `generateComprehensiveReport()` (window `smartGenerateComprehensiveReport`), `toggleReportLang()` (window `smartToggleReportLang`), `exportSmartData()` (window `smartExportData`), `initComparisonSelect()`, `renderComparison(scope)`, `renderReportSection(data)`.
- Report render targets (preserved IDs): `smart-report-kpi-dashboard`, `smart-decision-verdict`, `smart-decision-risk`, `smart-decision-hotspots`, `smart-decision-watchlist`, `smart-decision-priorities`, `smart-report-output`, `smart-comparison-chart`, `smart-peer-comparison-table`, `smart-comparison-type`.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_smart_core_js.py`:

```python
def test_report_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "report.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["generateComprehensiveReport", "toggleReportLang", "exportSmartData", "renderComparison"]:
        assert f"export function {name}" in js, name
    assert "window.smartGenerateComprehensiveReport" in js
    assert "window.smartExportData" in js
    assert "smart-comparison-type" in js
    assert "smart-export-scope" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_report_module_exists -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the module**

Create `static/js/smart/report.js`:

```javascript
// report.js — comprehensive report, data export, and peer comparison.
import { smartState, apiSmartGet, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature } from './core.js';
import { renderPlot } from './charts.js';

function reportLang() {
  return smartState.lang || 'ar';
}

export function toggleReportLang() {
  smartState.lang = smartState.lang === 'ar' ? 'en' : 'ar';
  const btn = document.getElementById('smart-report-lang-toggle');
  if (btn) btn.textContent = smartState.lang === 'ar' ? '🇬🇧 English' : '🇸🇦 العربية';
  const section = document.getElementById('smart-report-section');
  if (section && section.style.display !== 'none') generateComprehensiveReport();
}

export async function exportSmartData() {
  const scope = document.getElementById('smart-export-scope')?.value || 'current';
  const month = smartState.month || '';
  const url = scope === 'all' ? '/smart/overview/all' : `/smart/overview/${month}`;
  try {
    const data = await apiSmartGet(url);
    const rows = [];
    const anomalies = data.data ? data.data.anomalies : (data.anomalies || []);
    (anomalies || []).forEach(a => rows.push({
      month: month, hospital: a.hospital_name, governorate: a.governorate,
      score: a.anomaly_score, severity: a.severity,
    }));
    const csv = ['month,hospital,governorate,score,severity',
      ...rows.map(r => [r.month, r.hospital, r.governorate, r.score, r.severity].join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `smart_export_${month}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert(e.message || _t('Export failed'));
  }
}

export async function generateComprehensiveReport() {
  if (smartState.reportGenerating) return;
  const section = document.getElementById('smart-report-section');
  if (!section) return;
  const month = smartState.month || '';
  const overlay = document.getElementById('smart-loading-overlay');
  smartState.reportGenerating = true;
  if (overlay) overlay.style.display = 'flex';
  try {
    const data = await apiSmartGet(`/smart/overview/${month}`);
    smartState.data = data.data || data;
    renderReportSection(data.data || data, month);
    section.style.display = 'block';
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    alert(e.message || _t('Report generation failed'));
  } finally {
    smartState.reportGenerating = false;
    if (overlay) overlay.style.display = 'none';
  }
}

export function renderReportSection(data, month) {
  const kpi = data.kpi || {};
  const isEn = reportLang() === 'en';
  const k = key => _t(key);
  const kpiDashboard = document.getElementById('smart-report-kpi-dashboard');
  if (kpiDashboard) {
    kpiDashboard.innerHTML = `
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.total_anomalies ?? '-'}</div><div class="smart-kpi-label">${k('Hospitals with anomalies')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.critical_count ?? '-'}</div><div class="smart-kpi-label">${k('Critical')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.warning_count ?? '-'}</div><div class="smart-kpi-label">${k('Warning')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.affected_governorates ?? '-'}</div><div class="smart-kpi-label">${k('Governorates affected')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value" style="font-size:1.1rem;">${_smartEscapeHtml(smartTranslateFeature(kpi.top_contributing_factor))}</div><div class="smart-kpi-label">${k('Top factor')}</div></div>`;
  }
  const verdict = document.getElementById('smart-decision-verdict');
  if (verdict) {
    const st = kpi.month_status || 'normal';
    const colors = { critical: '#dc2626', attention_needed: '#f59e0b', normal: '#22c55e' };
    verdict.style.color = colors[st] || '#22c55e';
    verdict.textContent = st === 'critical' ? k('Needs urgent action')
      : st === 'attention_needed' ? k('Needs ongoing monitoring') : k('Within normal range');
  }
  const risk = document.getElementById('smart-decision-risk');
  if (risk) risk.textContent = k('Risk level') + ': ' + (stLabel(kpi.month_status, isEn));
  const hotspots = document.getElementById('smart-decision-hotspots');
  if (hotspots) hotspots.innerHTML = renderHospitalRows(data.anomalies.filter(a => a.severity === 'critical'), k);
  const watchlist = document.getElementById('smart-decision-watchlist');
  if (watchlist) watchlist.innerHTML = renderHospitalRows(data.anomalies.filter(a => a.severity === 'warning'), k);
  const priorities = document.getElementById('smart-decision-priorities');
  if (priorities) priorities.innerHTML = renderPriorityRows(data.anomalies, k);
  const output = document.getElementById('smart-report-output');
  if (output) output.innerHTML = '';
}

function stLabel(status, isEn) {
  const map = { critical: isEn ? 'Critical' : 'حرج', attention_needed: isEn ? 'Attention needed' : 'يحتاج متابعة', normal: isEn ? 'Normal' : 'طبيعي' };
  return map[status] || map.normal;
}

function renderHospitalRows(list, k) {
  if (!list.length) return `<div class="smart-priority-item smart-priority-normal"><div>✅ ${k('None')}</div></div>`;
  return list.map(h => `<div class="smart-priority-item smart-priority-${h.severity}">
    <div><div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
    <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')}</div></div>
    <div>${_riskBadge(_fmtNum(h.anomaly_score, 3), h.severity)}</div>
  </div>`).join('');
}

function renderPriorityRows(list, k) {
  const sorted = list.slice().sort((a, b) => b.anomaly_score - a.anomaly_score);
  return renderHospitalRows(sorted.slice(0, 10), k);
}

export function initComparisonSelect() {
  const select = document.getElementById('smart-comparison-type');
  if (!select) return;
  select.addEventListener('change', () => renderComparison(select.value));
}

export async function renderComparison(scope) {
  const month = smartState.month || '';
  try {
    const data = await apiSmartGet(`/smart/overview/${month}`);
    const anomalies = data.data ? data.data.anomalies : data.anomalies || [];
    const peer = document.getElementById('smart-peer-comparison-table');
    if (peer) peer.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
      <th>${_t('Hospital')}</th><th>${_t('Governorate')}</th><th>${_t('Score')}</th><th>${_t('Severity')}</th></tr></thead><tbody>` +
      anomalies.map(a => `<tr><td>${_smartEscapeHtml(a.hospital_name)}</td>
        <td>${_smartEscapeHtml(a.governorate)}</td>
        <td>${_fmtNum(a.anomaly_score, 3)}</td>
        <td>${_riskBadge(a.severity, a.severity)}</td></tr>`).join('') + `</tbody></table></div>`;
  } catch (e) { /* ignored */ }
}

// Exposed for inline onclick attributes.
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py::test_report_module_exists -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/report.js tests/test_smart_core_js.py
git commit -m "feat: add smart report module (report, export, comparison)"
```

---

### Task 15: Module entry `smart-analytics.js` + `index.html` wiring

**Files:**
- Rewrite: `static/js/smart-analytics.js` (becomes the ES-module entry)
- Modify: `static/index.html` (module script tag)
- Test: existing frontend static tests (must stay green — the file must still exist and expose the same window functions)

**Interfaces:**
- Consumes: all `static/js/smart/*.js` modules.
- Produces: screen initialization — mode buttons, collapsible headers, modal open/close, focus trap + Escape, IntersectionObserver section loaders, month/hospital select handlers, legacy window globals.
- Entry file stays at `static/js/smart-analytics.js` so existing `<script src="js/smart-analytics.js">` references and static-test path assertions keep working.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smart_core_js.py`:

```python
def test_entry_is_module_and_wires_modules():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "import" in js and "from './smart/" in js
    for mod in ["core.js", "decision-board.js", "charts.js", "advanced.js",
                "geo-regional.js", "hospital.js", "report.js"]:
        assert f"from './smart/{mod}'" in js, mod
    assert "initSectionObserver" in js
    assert "trapFocus" in js
    assert "registerSectionLoaders" in js


def test_index_html_loads_module_entry():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert 'type="module"' in html and "js/smart-analytics.js" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_entry_is_module_and_wires_modules tests/test_smart_core_js.py::test_index_html_loads_module_entry -q`
Expected: FAIL — old file is not a module; index.html uses a classic script tag.

- [ ] **Step 3: Rewrite `static/js/smart-analytics.js` as the entry**

Replace the full content of `static/js/smart-analytics.js`:

```javascript
// smart-analytics.js — ES-module entry: wires the smart-analytics screen.
import { smartState, apiSmartGet, smartShowLoading, smartHideLoading,
         setSmartLoader, showSmartSectionError, showSmartSectionEmpty,
         clearSmartSectionState, _smartEscapeHtml, _t, _fmtNum, _riskBadge,
         smartTranslateFeature, toggleSmartSection, setSmartMode,
         registerSectionLoaders, initSectionObserver, trapFocus } from './smart/core.js';
import { loadDecisionBoard, renderKPIs, renderCriticalList, renderEarlyWarnings, renderHealthyHospitals } from './smart/decision-board.js';
import { initAdvancedTabs, loadAdvancedSection, loadClustersTab, loadCorrelationsTab,
         loadPatternsTab, loadXGBoostTab, loadFeatureImportanceTab } from './smart/advanced.js';
import { renderPlot } from './smart/charts.js';
import { loadGeoSection } from './smart/geo-regional.js';
import { initHospitalSelect, loadHospitalMode, openDrilldown, goRootCause } from './smart/hospital.js';
import { generateComprehensiveReport, toggleReportLang, exportSmartData, initComparisonSelect, renderComparison } from './smart/report.js';

// Legacy window globals kept for inline onclick compatibility (some live in modules).
window.smartDrilldown = openDrilldown;
window.smartGoRootCause = goRootCause;
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;
// _smartKPI* modal openers are registered by decision-board.js as module side effects —
// do NOT redefine them here (that would overwrite the working implementations).

// ---- month + hospital selects ----
async function loadMonths() {
  const select = document.getElementById('smart-month-select');
  if (!select) return;
  try {
    const months = await apiSmartGet('/smart/months');
    if (!months || !months.length) return;
    select.innerHTML = months.map(m => `<option value="${_smartEscapeHtml(m)}">${_smartEscapeHtml(m)}</option>`).join('');
    const last = months[months.length - 1];
    select.value = last;
    smartState.month = last;
    onMonthChange(last);
  } catch (e) {
    showSmartSectionError('anomalies', e.message);
  }
}

async function loadHospitals() {
  try {
    const hospitals = await apiSmartGet('/smart/hospitals');
    initHospitalSelect(hospitals);
  } catch (e) { /* non-fatal */ }
}

async function onMonthChange(month) {
  smartState.month = month;
  smartState.monthChartsRendered = false;
  document.getElementById('smart-critical-list').innerHTML = '';
  document.getElementById('smart-kpi-container').innerHTML = '';
  document.getElementById('smart-anomaly-table').innerHTML = '';
  await loadDecisionBoard(month);
}

// ---- section loaders registry ----
registerSectionLoaders({
  anomalies: { load: () => loadAnomaliesTable(smartState.month) },
  geo: { load: () => loadGeoSection(smartState.month) },
  advanced: { load: () => loadAdvancedSection(smartState.month) },
  xgboost: { load: () => loadXGBoostTab(smartState.month) },
  timeline: { load: () => loadTimeline() },
  'time-overview': { load: () => loadTimeOverview() },
  hospital: { load: () => loadHospitalMode(getSelectedHospital(), null) },
});

async function loadAnomaliesTable(month) {
  try {
    const d = await apiSmartGet(`/smart/anomalies/${month}`);
    if (d.empty) { showSmartSectionEmpty('anomalies', d.message); return; }
    const rows = d.anomalies.map(a => `<tr>
      <td>${_smartEscapeHtml(a.hospital_name)}</td>
      <td>${_smartEscapeHtml(a.governorate)}</td>
      <td>${_fmtNum(a.anomaly_score, 3)}</td>
      <td>${_riskBadge(a.severity, a.severity)}</td>
      <td style="font-size:0.75rem;">${_smartEscapeHtml(a.reason || '')}</td>
      <td><button class="btn btn-sm btn-outline" onclick="window.smartDrilldown(${a.hospital_id})">📊</button></td>
    </tr>`).join('');
    document.getElementById('smart-anomaly-table').innerHTML = rows;
  } catch (e) {
    showSmartSectionError('anomalies', e.message);
  }
}

async function loadTimeline() {
  try {
    const d = await apiSmartGet('/smart/anomaly-timeline');
    const t = d.timeline || [];
    const months = t.map(x => x.month);
    const avg = t.map(x => x.avg_anomaly_score);
    const critical = t.map(x => x.critical_count);
    renderPlot('smart-timeline-chart', [
      { x: months, y: avg, name: _t('Avg score'), type: 'scatter', mode: 'lines+markers' },
      { x: months, y: critical, name: _t('Critical count'), type: 'bar', yaxis: 'y2' },
    ], { yaxis: { range: [0, 1] }, yaxis2: { overlaying: 'y', side: 'right' } });
    const last = t[t.length - 1];
    if (last && last.status) {
      const badge = document.getElementById('smart-timeline-badge');
      if (badge) badge.textContent = last.status;
      const text = document.getElementById('smart-timeline-text');
      if (text) text.textContent = d.summary_ar || d.summary || '';
    }
  } catch (e) {
    showSmartSectionError('timeline', e.message);
  }
}

async function loadTimeOverview() {
  try {
    const d = await apiSmartGet('/smart/time-overview');
    if (d.empty) { showSmartSectionEmpty('time-overview', d.message); return; }
    const s = d.series;
    renderPlot('smart-time-avg', [{ x: s.avg_score.map(p => p.month), y: s.avg_score.map(p => p.value), type: 'scatter', mode: 'lines+markers' }], { title: _t('Average anomaly score') });
    renderPlot('smart-time-severity', [
      { x: s.critical_count.map(p => p.month), y: s.critical_count.map(p => p.value), name: _t('Critical'), type: 'bar' },
      { x: s.warning_count.map(p => p.month), y: s.warning_count.map(p => p.value), name: _t('Warning'), type: 'bar' },
    ], { barmode: 'group', title: _t('Severity counts') });
    renderPlot('smart-time-governorates', [{ x: s.affected_governorates.map(p => p.month), y: s.affected_governorates.map(p => p.value), type: 'scatter', mode: 'lines+markers' }], { title: _t('Affected governorates') });
  } catch (e) {
    showSmartSectionError('time-overview', e.message);
  }
}

function getSelectedHospital() {
  const s = document.getElementById('smart-hospital-context-select');
  return s ? s.value : '';
}

// ---- mode buttons ----
document.querySelectorAll('.smart-mode-btn').forEach(btn => {
  btn.addEventListener('click', () => setSmartMode(btn.dataset.smartMode));
});

// ---- collapsible headers ----
document.querySelectorAll('[data-smart-collapsible]').forEach(header => {
  header.addEventListener('click', () => toggleSmartSection(header));
});

// ---- methodology modal ----
function openMethodology() {
  const modal = document.getElementById('smart-methodology-modal');
  if (modal) { modal.classList.add('active'); trapFocus(modal, document.getElementById('smart-methodology-btn')); }
}
function closeMethodology() {
  const modal = document.getElementById('smart-methodology-modal');
  if (modal) modal.classList.remove('active');
}
const methodologyBtn = document.getElementById('smart-methodology-btn');
if (methodologyBtn) methodologyBtn.addEventListener('click', openMethodology);
const methodologyClose = document.getElementById('smart-methodology-close');
if (methodologyClose) methodologyClose.addEventListener('click', closeMethodology);

// ---- KPI / drilldown modals: click-outside + close buttons ----
['smart-kpi-modal', 'smart-drilldown-modal'].forEach(id => {
  const modal = document.getElementById(id);
  if (modal) {
    modal.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });
    const closeBtn = modal.querySelector('button[aria-label="Close"]');
    if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
  }
});

// ---- event wiring ----
document.getElementById('smart-month-select')?.addEventListener('change', e => onMonthChange(e.target.value));
document.getElementById('smart-hospital-select')?.addEventListener('change', e => {
  const v = e.target.value;
  if (v) loadHospitalMode(v, null);
});
document.getElementById('smart-hospital-context-select')?.addEventListener('change', e => loadHospitalMode(e.target.value, null));
document.getElementById('smart-hospital-context-all')?.addEventListener('click', () => {
  loadHospitalMode(getSelectedHospital(), 'all');
});
document.getElementById('smart-refresh')?.addEventListener('click', () => {
  cacheBust();
  onMonthChange(smartState.month);
});
initComparisonSelect();
initAdvancedTabs();

// ---- error banner retry (spec 5): clicking an active error banner reloads its section ----
const _retryLoaders = {
  anomalies: () => loadAnomaliesTable(smartState.month),
  geo: () => loadGeoSection(smartState.month),
  advanced: () => loadAdvancedSection(smartState.month),
  xgboost: () => loadXGBoostTab(smartState.month),
  timeline: () => loadTimeline(),
  'time-overview': () => loadTimeOverview(),
  hospital: () => loadHospitalMode(getSelectedHospital(), null),
};
document.addEventListener('click', e => {
  const banner = e.target.closest('.smart-error-banner.active');
  if (!banner) return;
  const key = banner.getAttribute('data-smart-error');
  const fn = key && _retryLoaders[key];
  if (!fn) return;
  setSmartLoader(key, true);
  fn().catch(() => {}).finally(() => setSmartLoader(key, false));
});

function cacheBust() {
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Refreshed');
}

// ---- startup ----
(function init() {
  initSectionObserver();
  loadHospitals();
  loadMonths();
})();
```

- [ ] **Step 4: Update `static/index.html` script tag**

In `static/index.html`, change the smart-analytics script tag from:

```html
<script src="js/smart-analytics.js"></script>
```

to:

```html
<script type="module" src="js/smart-analytics.js"></script>
```

Keep the tag in the same position (after `js/i18n.js` and `js/app.js`). Do NOT remove the Plotly `<script>` tag.

- [ ] **Step 5: Run the static tests**

Run: `python -m pytest tests/test_smart_core_js.py tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py -q`
Expected: PASS (any ID assertions must still pass — see Task 7 preserved-ID list).

- [ ] **Step 6: Commit**

```bash
git add static/js/smart-analytics.js static/index.html tests/test_smart_core_js.py
git commit -m "feat: wire smart-analytics ES-module entry and index.html module tag"
```

---

### Task 16: Add i18n translations for the new screen chrome

**Files:**
- Modify: `static/js/i18n.js`
- Test: existing i18n tests + the new static structure test (`tests/test_export.py::test_smart_redesign_structure` is structure-only; translation coverage is asserted here)

**Interfaces:**
- Consumes: the `data-i18n` keys used in the new HTML (Task 7).
- Produces: AR + EN dictionary entries for every new `data-i18n` key so `translateDOM()` / `__()` resolve them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smart_core_js.py`:

```python
def test_i18n_covers_smart_keys():
    import os
    import re
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    i18n_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    with open(i18n_path, encoding="utf-8") as f:
        i18n = f.read()
    keys = re.findall(r'data-i18n="([^"]+)"', html)
    assert keys, "no data-i18n keys found"
    for key in keys:
        assert key in i18n, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_i18n_covers_smart_keys -q`
Expected: FAIL — several new keys missing from `i18n.js`.

- [ ] **Step 3: Add the missing keys**

In `static/js/i18n.js`, add to the AR translation dict (key → Arabic) and the EN dict (key → English) all keys found by the test, including at least:

- "Smart Analytics" → "التحليل الذكي" / "Smart Analytics"
- "Decision first, analysis second" → "قرار أولاً، تحليل ثانياً" / "Decision first, analysis second"
- "Monthly" → "شهري" / "Monthly"
- "Time" → "زمني" / "Time"
- "Hospital" → "مستشفى" / "Hospital"
- "Methodology" → "المنهجية" / "Methodology"
- "Decision Board" → "لوحة القرار" / "Decision Board"
- "Hospitals needing urgent action" → "مستشفيات تحتاج تدخلاً عاجلاً" / "Hospitals needing urgent action"
- "Hospitals" → "المستشفيات" / "Hospitals"
- "Geography" → "الجغرافيا" / "Geography"
- "Advanced Models" → "النماذج المتقدمة" / "Advanced Models"
- "Forecasts" → "التنبؤات" / "Forecasts"
- "Comprehensive Report" → "التقرير الشامل" / "Comprehensive Report"
- "Executive Decisions" → "قرارات تنفيذية" / "Executive Decisions"
- "Peer Comparison" → "مقارنة النظير" / "Peer Comparison"
- "Time Overview" → "النظرة الزمنية" / "Time Overview"
- "Anomaly Timeline" → "تطور درجات الشذوذ" / "Anomaly Timeline"
- "How is the anomaly score calculated?" → "كيف تُحسب درجة الشذوذ؟" / "How is the anomaly score calculated?"
- "Four engines" → "4 محركات" / "Four engines"
- "No data for this month" → "لا توجد بيانات لهذا الشهر" / "No data for this month"
- "No data" → "لا توجد بيانات" / "No data"
- "Loading..." → "جاري التحميل..." / "Loading..."
- "Failed to load" → "تعذر التحميل" / "Failed to load"
- "Updated" → "تم التحديث" / "Updated"
- "Refresh" → "تحديث" / "Refresh"
- "Export Data" → "تصدير البيانات" / "Export Data"
- "Generate Report" → "توليد التقرير الشامل" / "Generate Report"
- "Hospitals with anomalies" → "مستشفيات بها شذوذ" / "Hospitals with anomalies"
- "Governorates with deviations" → "محافظات بها انحرافات" / "Governorates with deviations"
- "Top contributing factor" → "العامل الأكثر إسهاماً" / "Top contributing factor"
- "Month status" → "حالة الشهر" / "Month status"
- "Needs urgent action" → "يحتاج تدخلاً عاجلاً" / "Needs urgent action"
- "Needs ongoing monitoring" → "يحتاج متابعة مستمرة" / "Needs ongoing monitoring"
- "Within normal range" → "ضمن النطاق الطبيعي" / "Within normal range"
- "Critical" / "Warning" / "Normal" → "حرج" / "تنبيه" / "طبيعي"
- "No critical hospitals this month" → "لا توجد مستشفيات حرجة هذا الشهر" / "No critical hospitals this month"
- "Details" → "التفاصيل" / "Details"
- "Root cause" → "تحليل السبب الجذري" / "Root cause"
- "Early Warning System" → "نظام الإنذار المبكر" / "Early Warning System"
- "Healthy hospitals (models to follow)" → "مستشفيات سليمة (نماذج للاقتداء)" / "Healthy hospitals (models to follow)"
- "Cluster" → "عنقود" / "Cluster"
- "Feature correlations" → "ارتباطات العوامل" / "Feature correlations"
- "Residuals by hospital" → "البواقي حسب المستشفى" / "Residuals by hospital"
- "No composite patterns" → "لا توجد أنماط مركبة" / "No composite patterns"
- "Predicted score" → "الدرجة المتوقعة" / "Predicted score"
- "Not enough predictions for this month" → "لا توجد تنبؤات كافية لهذا الشهر" / "Not enough predictions for this month"
- "Geographic distribution" → "التوزيع الجغرافي" / "Geographic distribution"
- "Average anomaly score" → "متوسط درجة الشذوذ" / "Average anomaly score"
- "Avg score" → "متوسط الدرجة" / "Avg score"
- "Outliers" → "القيم الشاذة" / "Outliers"
- "Select Hospital" → "اختر مستشفى" / "Select Hospital"
- "All Hospitals" → "جميع المستشفيات" / "All Hospitals"
- "All months" → "كل الأشهر" / "All months"
- "Selected month" → "الشهر المحدد" / "Selected month"
- "Month:" / "Hospital:" → "الشهر:" / "المستشفى:" / "Month:" / "Hospital:"
- "No forecast available" → "لا يوجد تنبؤ متاح" / "No forecast available"
- "Factor" → "العامل" / "Factor"
- "Impact" → "التأثير" / "Impact"
- "Export failed" → "فشل التصدير" / "Export failed"
- "Report generation failed" → "فشل توليد التقرير" / "Report generation failed"
- "Risk level" → "مستوى الخطورة" / "Risk level"
- "None" → "لا شيء" / "None"
- "Governorates affected" → "المحافظات المتأثرة" / "Governorates affected"
- "Top factor" → "العامل الأعلى" / "Top factor"
- "Refreshed" → "تم التحديث" / "Refreshed"
- "Composite" → "المركب" / "Composite"
- "Description" → "الوصف" / "Description"
- "Anomaly score over time" → "تطور درجة الشذوذ" / "Anomaly score over time"
- "Predicted score" → "الدرجة المتوقعة" / "Predicted score"
- "Monthly residuals" → "البواقي الشهرية" / "Monthly residuals"
- "Severity counts" → "عدد الحالات حسب الشدة" / "Severity counts"
- "Affected governorates" → "المحافظات المتأثرة" / "Affected governorates"
- "Feature importance (SHAP)" → "أهمية العوامل (SHAP)" / "Feature importance (SHAP)"
- "Regional average anomaly score" → "متوسط درجة الشذوذ الإقليمي" / "Regional average anomaly score"
- "Comparison scope:" → "نطاق المقارنة:" / "Comparison scope:"
- "Same governorate" → "نفس المحافظة" / "Same governorate"
- "Same type" → "نفس النوع" / "Same type"
- "Close" → "إغلاق" / "Close"

Use the existing dictionary structure of `i18n.js` (exact object shape varies — add to both `ar` and `en` sections).

- [ ] **Step 4: Run the i18n test**

Run: `python -m pytest tests/test_smart_core_js.py::test_i18n_covers_smart_keys -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/i18n.js tests/test_smart_core_js.py
git commit -m "feat: add smart-analytics i18n keys for new screen chrome"
```

---

### Task 17: Frontend hygiene — single escape helper, single methodology source, spelling fixes

**Files:**
- Modify: `static/js/smart/*.js` (as needed)
- Test: `tests/test_smart_core_js.py`

**Interfaces:**
- Produces: exactly one `_smartEscapeHtml` definition in the codebase (in `core.js`); no inline methodology markup in JS modules (the single source is the HTML `smart-methodology-modal`); no known Arabic/English misspellings in visible labels.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smart_core_js.py`:

```python
def test_single_escape_helper_across_modules():
    import os
    root = os.path.join(os.path.dirname(__file__), "..", "static", "js")
    total = 0
    for fname in os.listdir(os.path.join(root, "smart")):
        if fname.endswith(".js"):
            with open(os.path.join(root, "smart", fname), encoding="utf-8") as f:
                total += f.read().count("function _smartEscapeHtml")
    assert total == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_core_js.py::test_single_escape_helper_across_modules -q`
Expected: FAIL — the old monolithic file or a module duplicates the helper.

- [ ] **Step 3: Deduplicate and clean up**

- Remove any duplicated `_smartEscapeHtml`/`escapeHtml` definitions in `static/js/smart/*.js` and in `static/js/smart-analytics.js`; keep the single exported copy in `core.js` and import it everywhere it is used.
- Remove inline methodology/`smart-methodology-*` markup strings from `report.js`/`advanced.js` if any remain — the only methodology source is the HTML modal (Task 7).
- Fix known misspellings in visible labels and API error details:
  - «المتأضعة» → «المتأثرة» (spec 3.6)
  - «المتوسطقة» → «المتوسطة» (spec 3.6)
  - «التحليل الطبقى» → «التحليل الطبقي» (introduced in Task 5)
  - Remove any duplicate English labels.
- Remove dead code: any function in the old file that has no caller in the new modules (check with grep across `static/js/`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smart_core_js.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/ static/js/smart-analytics.js app/api/smart_analytics.py tests/test_smart_core_js.py
git commit -m "refactor: single escape helper, single methodology source, spelling fixes"
```

---

### Task 18: Update frontend static tests for the new module files

**Files:**
- Modify: `tests/test_export.py`
- Modify: `tests/test_comparative.py`
- Modify: `tests/test_lag_analysis.py`
- Test: those three files

**Interfaces:**
- Consumes: the new module files under `static/js/smart/`.
- Produces: static assertions that read the new module files instead of the monolithic `smart-analytics.js` (whose content is now the small entry).

- [ ] **Step 1: Write the failing tests**

For each of the three files, locate the assertions that read `static/js/smart-analytics.js` and assert function names (e.g. `smartExportData`, `smartToggleReportLang`, `smartGoRootCause`, `smartTimeline`/lag-analysis helpers) or inline methodology HTML. Update them to read the module that owns the function:

- `tests/test_export.py` export-related assertions → read `static/js/smart/report.js` (assert `window.smartExportData`, `exportSmartData`, `smart-export-scope`).
- `tests/test_comparative.py` report/comparison assertions → read `static/js/smart/report.js` (assert `smart-comparison-type`, `renderComparison`, `smartGenerateComprehensiveReport`).
- `tests/test_lag_analysis.py` timeline/lag assertions → read `static/js/smart/advanced.js` (assert `renderLagAnalysis`, `smart-lag-analysis`) and the entry for `smart-timeline-*` wiring.

Concretely, change each helper like:

```python
def _read_smart_js():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
```

to read the module file, and replace any content assertions on removed monolithic functions with the module-owning equivalents listed above.

- [ ] **Step 2: Run the three test files**

Run: `python -m pytest tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py -q`
Expected: PASS.

- [ ] **Step 3: Run the full frontend static suite**

Run: `python -m pytest tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py tests/test_chart_migration.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_export.py tests/test_comparative.py tests/test_lag_analysis.py
git commit -m "test: point frontend static tests at the new smart modules"
```

---

### Task 19: Full verification and review

**Files:**
- Run: entire test suite; manual checklist below.
- Test: `python -m pytest tests/ -q`

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: ALL PASS (previously 793 passing; ~30+ new tests added by this plan).

- [ ] **Step 2: Run the smart-focused suite**

Run: `python -m pytest tests/test_smart_analytics.py tests/test_smart_decision_board.py tests/test_smart_section_endpoints.py tests/test_smart_time_overview.py tests/test_smart_styles.py tests/test_smart_core_js.py -q`
Expected: PASS.

- [ ] **Step 3: Manual smoke checklist (in the running app)**

- [ ] Open the smart tab: loading overlay shows, then decision board renders above the fold with 4 KPI cards.
- [ ] Switch modes شهري/زمني/مستشفى — panels and context bars swap correctly, `aria-selected` updates.
- [ ] Month change re-fetches decision board only (Network tab: one `/smart/decision-board/...` request, no full `/overview`).
- [ ] Scroll down: each heavy section loads lazily via its own endpoint (`/smart/clusters/...`, `/smart/patterns/...`, `/smart/xgboost/...`, `/smart/geo/...`).
- [ ] Open methodology modal: focus trap works, Escape closes, focus returns to the ⓘ button.
- [ ] Empty month (e.g. 2030-01): sections show the Arabic empty-state banner, no console 500s.
- [ ] AR ⇄ EN toggle: new chrome text translates via `data-i18n`.
- [ ] Report generation shows the comprehensive report section with KPI dashboard and decision lists.
- [ ] Export CSV downloads a UTF-8 (BOM) file.
- [ ] Drilldown modal opens from a critical hospital; close button and click-outside work.

- [ ] **Step 4: Request code review**

Run the whole-branch review (requesting-code-review) and fix any findings. Confirm: no Plotly removal, no `/smart/overview/{month}` removal, all preserved IDs intact, all 127 original smart tests still pass.

- [ ] **Step 5: Update the progress ledger**

Record each completed task in `.superpowers/sdd/progress.md` (do NOT commit this file).

- [ ] **Step 6: Final commit if any review fixes**

If review produced fixes, commit them with a descriptive message, then re-run the full suite.

---

## Verification Plan

- `python -m pytest tests/ -q` — full suite green at the end (Tasks 6, 9, 19).
- Per-task test-first steps (write failing test → implement → pass) throughout Tasks 1–18.
- Static tests cover: cache keys, endpoint shapes/empty/error contracts, CSS classes, HTML structure + preserved IDs, module APIs, single-escape-helper rule, i18n key coverage, index.html module wiring.

## Risks / Mitigations

- **Preserved IDs / old function names in static tests** — Tasks 7/15/18 keep every listed ID and window global; tests are updated only where they assert removed internals.
- **IntersectionObserver double-loading** — `observer.unobserve(el)` after first fire + `smartState.monthChartsRendered` flag guard duplicate renders on month change.
- **Module load order** — the entry runs after DOM parse (module scripts are deferred); `window.__` from `i18n.js`/`app.js` is available because those classic scripts run earlier in document order.
- **Plotly still required** — kept in `index.html`; only the screen JS is modularized.
- **Cache key collisions** — version suffix `_v3` isolates new schemas; prefix-based `invalidate()` calls keep working for all keys.