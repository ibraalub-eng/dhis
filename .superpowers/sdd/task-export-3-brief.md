### Task 3: Export API Endpoint

**Files:**
- Create: `app/api/export.py`
- Modify: `app/main.py` (import + `include_router`)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `build_full_export`, `NoDataError` from Task 2.
- Produces: `GET /export/full-data?month=YYYY-MM|all&lang=ar|en` → `StreamingResponse` JSON attachment, or 404/422.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# --- API endpoint ---

def test_export_endpoint_returns_json_download(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["meta"]["scope"] == "2026-06"


def test_export_endpoint_all_months(client, db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "en"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["scope"] == "all"
    assert data["meta"]["lang"] == "en"
    assert set(data["indicator_values"].keys()) == {"2026-05", "2026-06"}


def test_export_endpoint_invalid_lang_422(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "xx"})
    assert resp.status_code == 422


def test_export_endpoint_no_data_404(client, db_session):
    from app.models import Hospital
    db_session.query(Hospital).delete()
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "ar"})
    assert resp.status_code == 404
    assert "لا توجد بيانات" in resp.json()["detail"]


def test_export_endpoint_serializes_without_error(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "endpoint" -q`
Expected: FAIL — `404 Not Found` (router not registered yet).

- [ ] **Step 3: Create the router**

Create `app/api/export.py`:

```python
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.export import build_full_export, NoDataError

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/full-data")
def export_full_data(
    month: str = Query(..., description="الشهر (YYYY-MM) أو all"),
    lang: str = Query("ar", description="لغة التقرير (ar/en)", pattern="^(ar|en)$"),
    db: Session = Depends(get_db),
):
    """تصدير البيانات الكاملة كملف JSON"""
    try:
        payload = build_full_export(db, month, lang)
    except NoDataError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في التصدير: {str(e)}")

    filename = f"health_export_{datetime.now().strftime('%Y-%m-%d')}.json"
    content = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

Add the import of `StreamingResponse` to the top of `app/api/export.py`:

```python
from fastapi.responses import StreamingResponse
```

- [ ] **Step 4: Register the router in `app/main.py`**

Modify the import at `app/main.py:15` — append `, export as export_router` to the `app.api` import list (after `comparative`):

```python
from app.api import upload, hospitals, reports, analysis, rules as rules_api, clinical, alerts, confidence, config_api, root_cause, dashboard, file_ops, indicator_config, tree_config, audit as audit_api, governorates as governorates_api, hospital_types as hospital_types_api, facility_ownerships as facility_ownerships_api, facility_types as facility_types_api, smart_analytics as smart_analytics_router, comparative as comparative_router, export as export_router  # noqa: E402
```

Add after the existing `app.include_router(comparative_router.router)` at `app/main.py:245`:

```python
app.include_router(export_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -k "endpoint" -q`
Expected: 5 passed

- [ ] **Step 6: Run the full export suite**

Run: `python -m pytest tests/test_export.py -q`
Expected: all pass (19 total)

- [ ] **Step 7: Commit**

```bash
git add app/api/export.py app/main.py tests/test_export.py
git commit -m "feat: add full data export API endpoint"
```


