"""Endpoint contract for /analysis/layered/heatmap.

The Layered tab's hospital × month grid: every cell carries the WORST
classification present under the current filters (severity order documented
in the endpoint), inactive hospitals are never rows, and the same filters
the table honors narrow the grid.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import Hospital, LayeredOutlierResult


class _NoCache:
    """Test-local cache stub: never reads, never writes.

    The real TTLCache persists to data/cache/ files scoped to a data epoch;
    letting tests write there is the poison-file doctrine conftest.py warns
    about. Endpoint logic does not depend on the cache being real.
    """

    def make_key(self, *args, **kwargs):
        return "test"

    def get(self, key):
        return None

    def set(self, key, value):
        pass


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr("app.api.analysis.cache", _NoCache())

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_hospital(db, name, active=True):
    h = Hospital(name=name, is_active=active)
    db.add(h)
    db.flush()
    return h


def _seed_layered(db, h, month, code, otype, level="HIGH"):
    db.add(LayeredOutlierResult(
        hospital_id=h.id,
        indicator_id=3,  # arbitrary; endpoint never joins on it
        analysis_code=code,
        month=month,
        outlier_type=otype,
        outlier_level=level,
        investigation_route="none",
    ))


def test_worst_classification_wins_the_cell(db_session, client):
    Al = _seed_hospital(db_session, "Heatmap Al-Shifa")
    Bashir = _seed_hospital(db_session, "Heatmap Bashir")
    # One cell mixed: POSSIBLE_DATA_ENTRY_ERROR must beat HISTORICAL_ANOMALY.
    # Distinct analysis codes: the schema keeps one row per hospital/code/month.
    _seed_layered(db_session, Al, "2026-01", "CBB", "HISTORICAL_ANOMALY")
    _seed_layered(db_session, Al, "2026-01", "rate_cs", "POSSIBLE_DATA_ENTRY_ERROR")
    _seed_layered(db_session, Al, "2026-01", "CS", "HISTORICAL_ANOMALY")
    # Bashir alone in another month: RATE_ANOMALY.
    _seed_layered(db_session, Bashir, "2026-02", "rate_cs", "RATE_ANOMALY")
    db_session.commit()

    resp = client.get("/analysis/layered/heatmap")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"] == ["2026-01", "2026-02"]

    rows = {d["hospital"]: d for d in body["data"]}
    cell_janvier = rows["Heatmap Al-Shifa"]["2026-01"]
    assert cell_janvier["type"] == "POSSIBLE_DATA_ENTRY_ERROR"
    assert cell_janvier["count"] == 3
    assert cell_janvier["breakdown"] == {
        "HISTORICAL_ANOMALY": 2,
        "POSSIBLE_DATA_ENTRY_ERROR": 1,
    }
    cell_janvier = rows["Heatmap Bashir"]["2026-02"]
    assert cell_janvier["type"] == "RATE_ANOMALY"


def test_cells_without_rows_are_absent_not_zero(db_session, client):
    alone = _seed_hospital(db_session, "Heatmap Only")
    _seed_layered(db_session, alone, "2026-01", "CBB", "PEER_ANOMALY")
    db_session.commit()

    body = client.get("/analysis/layered/heatmap").json()
    row = next(d for d in body["data"] if d["hospital"] == "Heatmap Only")
    assert body["months"] == ["2026-01"]
    assert "2026-02" not in row  # a month the hospital never had data for


def test_classification_filter_narrows_cells(db_session, client):
    h = _seed_hospital(db_session, "Heatmap Filter")
    _seed_layered(db_session, h, "2026-01", "CBB", "PEER_ANOMALY")
    _seed_layered(db_session, h, "2026-01", "rate_cs", "RATE_ANOMALY")
    db_session.commit()

    body = client.get(
        "/analysis/layered/heatmap?classification=RATE_ANOMALY"
    ).json()
    row = next(d for d in body["data"] if d["hospital"] == "Heatmap Filter")
    assert row["2026-01"]["type"] == "RATE_ANOMALY"
    assert row["2026-01"]["count"] == 1  # only rows matching the filter


def test_inactive_hospitals_never_become_rows(db_session, client):
    h = _seed_hospital(db_session, "Heatmap Dormant", active=False)
    _seed_layered(db_session, h, "2026-01", "CBB", "PEER_ANOMALY")
    db_session.commit()

    body = client.get("/analysis/layered/heatmap").json()
    assert all(d["hospital"] != "Heatmap Dormant" for d in body["data"])
