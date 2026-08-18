### Task 1: Export Engine — Master Data, Months, Indicator Values, Sanitize

**Files:**
- Create: `app/engine/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Produces (consumed by Task 2, Task 3):
  - `_sanitize(obj) -> Any` — recursive: dict/list/tuple recursion; numpy scalar `.item()`; numpy array `.tolist()`; float NaN/Inf → 0.0.
  - `_get_available_months(session) -> List[str]` — sorted distinct `IndicatorValue.month` values.
  - `_get_master_data(session) -> dict` — keys `governorates`, `hospitals`, `indicators`, `hospital_indicator_configs`.
  - `_get_indicator_values(session, months) -> Dict[str, list]` — month → list of value dicts.
  - Constant `NoDataError` (subclass of `ValueError`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export.py` with a `client` fixture (same pattern as `tests/test_comparative.py:72-87`):

```python
"""Tests for the full data export feature."""
import json
import pytest
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
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# --- Engine helpers ---

def test_sanitize_converts_numpy_scalars(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"score": np.float64(0.45), "count": np.int64(7), "nan": float("nan"), "inf": float("inf")})
    assert out["score"] == 0.45
    assert isinstance(out["score"], float)
    assert out["count"] == 7
    assert isinstance(out["count"], int)
    assert out["nan"] == 0.0
    assert out["inf"] == 0.0


def test_sanitize_converts_numpy_array(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"arr": np.array([1.0, 2.5, 3.0])})
    assert out["arr"] == [1.0, 2.5, 3.0]
    assert isinstance(out["arr"], list)
    assert all(isinstance(v, float) for v in out["arr"])


def test_get_available_months_empty(db_session):
    from app.engine.export import _get_available_months
    assert _get_available_months(db_session) == []


def test_get_available_months_distinct_sorted(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_available_months
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=90),
    ])
    db_session.commit()
    assert _get_available_months(db_session) == ["2026-05", "2026-06"]


def test_get_master_data_returns_all_sections(db_session):
    from app.engine.export import _get_master_data
    md = _get_master_data(db_session)
    assert "governorates" in md
    assert "hospitals" in md
    assert "indicators" in md
    assert "hospital_indicator_configs" in md
    assert len(md["hospitals"]) == 3
    assert len(md["indicators"]) > 0
    h = md["hospitals"][0]
    for key in ("id", "name", "region", "address", "governorate_name",
                "hospital_type_name", "facility_ownership_name", "facility_type_name", "is_active"):
        assert key in h


def test_get_indicator_values_grouped_by_month(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_indicator_values
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=300, source_file="x.xlsx"))
    db_session.commit()
    result = _get_indicator_values(db_session, ["2026-06"])
    assert "2026-06" in result
    row = result["2026-06"][0]
    assert row["hospital_id"] == hosp.id
    assert row["hospital_name"] == hosp.name
    assert row["indicator_code"] == "2"
    assert row["indicator_name"] == ind.name
    assert row["value"] == 300
    assert row["source_file"] == "x.xlsx"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -q`
Expected: ERROR at collection — `ModuleNotFoundError: No module named 'app.engine.export'`

- [ ] **Step 3: Create the module**

Create `app/engine/export.py`:

```python
"""Build the full data export package for external analysis tools."""
import math
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models import (
    Hospital, Governorate, Indicator, HospitalIndicatorConfig, IndicatorValue,
)


class NoDataError(ValueError):
    """Raised when there is nothing to export."""


def _sanitize(obj: Any) -> Any:
    """Recursively convert numpy/NaN/Inf values to native JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "tolist") and not isinstance(obj, (int, float, str, bool)):
        try:
            return _sanitize(obj.tolist())
        except (ValueError, AttributeError, TypeError):
            pass
    if hasattr(obj, "item") and not isinstance(obj, (int, float, str, bool)):
        try:
            return obj.item()
        except (ValueError, AttributeError, TypeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    return obj


def _get_available_months(session: Session) -> List[str]:
    """Distinct months that have indicator values, sorted ascending."""
    months = [m for (m,) in session.query(IndicatorValue.month).distinct().all()]
    return sorted(months)


def _get_master_data(session: Session) -> Dict[str, Any]:
    """Governorates, hospitals, indicators, and hospital indicator configs."""
    governorates = [
        {"id": g.id, "name": g.name}
        for g in session.query(Governorate).order_by(Governorate.name).all()
    ]

    hospitals = []
    for h in session.query(Hospital).order_by(Hospital.name).all():
        hospitals.append({
            "id": h.id,
            "name": h.name,
            "region": h.region,
            "address": h.address,
            "governorate_name": h.governorate.name if h.governorate else None,
            "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
            "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
            "facility_type_name": h.facility_type.name if h.facility_type else None,
            "is_active": h.is_active,
        })

    indicators = [
        {
            "code": i.code,
            "name": i.name,
            "level": i.level,
            "group_name": i.group_name,
            "parent_code": i.parent.code if i.parent else None,
        }
        for i in session.query(Indicator).order_by(Indicator.sort_order, Indicator.id).all()
    ]

    configs = [
        {
            "hospital_id": c.hospital_id,
            "indicator_code": c.indicator.code if c.indicator else None,
            "is_enabled": c.is_enabled,
            "weight_override": c.weight_override,
        }
        for c in session.query(HospitalIndicatorConfig).all()
    ]

    return {
        "governorates": governorates,
        "hospitals": hospitals,
        "indicators": indicators,
        "hospital_indicator_configs": configs,
    }


def _get_indicator_values(session: Session, months: List[str]) -> Dict[str, list]:
    """Indicator values grouped by month."""
    by_month: Dict[str, list] = {}
    if not months:
        return by_month

    hospitals = {h.id: h for h in session.query(Hospital).all()}
    indicators = {i.id: i for i in session.query(Indicator).all()}

    rows = session.query(IndicatorValue).filter(IndicatorValue.month.in_(months)).all()
    for iv in rows:
        hosp = hospitals.get(iv.hospital_id)
        ind = indicators.get(iv.indicator_id)
        by_month.setdefault(iv.month, []).append({
            "hospital_id": iv.hospital_id,
            "hospital_name": hosp.name if hosp else "",
            "indicator_code": ind.code if ind else "",
            "indicator_name": ind.name if ind else "",
            "value": iv.value,
            "source_file": iv.source_file,
        })
    return by_month
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -k "sanitize or available_months or master_data or indicator_values" -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/export.py tests/test_export.py
git commit -m "feat: add export engine helpers for master data and indicator values"
```


