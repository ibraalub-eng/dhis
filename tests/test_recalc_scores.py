"""Regression tests for score recalculation paths.

Guards against stale model-name imports (SystemConfig was renamed to
AppConfig but two API modules still referenced the old name), which made
POST /dashboard/recalculate-completeness return 500 and made indicator
toggles silently skip score recalculation.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import QualityScore


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


def test_recalculate_completeness_empty_db(client):
    """Empty DB must return 200 with zero counts — a stale model import would 500 here."""
    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    assert resp.json() == {"updated": 0, "total": 0}


def test_recalculate_completeness_updates_scores(client, db_session):
    """With an existing quality score, completeness is recomputed and reported as updated."""
    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["updated"] == 1


def test_recalc_hospital_scores_no_crash(db_session):
    """Indicator score recalculation must not raise (regression: SystemConfig ImportError)."""
    from app.api.indicator_config import _recalc_hospital_scores

    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    # The imports inside the function run before any try/except, so the old
    # stale model name raised an ImportError here — assert it completes.
    _recalc_hospital_scores(db_session, 1)

    refreshed = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == "2027-01"
    ).first()
    assert refreshed is not None
    assert refreshed.completeness is not None


def test_toggle_indicator_endpoint(client, db_session):
    """Toggling an indicator returns the expected shape and doesn't crash recalculation."""
    from app.models import Indicator

    indicator = db_session.query(Indicator).first()
    assert indicator is not None

    resp = client.put(f"/hospitals/1/indicators/{indicator.id}/toggle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hospital_id"] == 1
    assert data["indicator_id"] == indicator.id
    assert data["is_enabled"] is False
    assert "message" in data