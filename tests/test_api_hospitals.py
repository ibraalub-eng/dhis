"""Tests for hospital API endpoints (api.hospitals)."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Hospital, Indicator, IndicatorValue


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


class TestListHospitals:
    def test_list_all(self, client):
        resp = client.get("/hospitals/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    def test_pagination_skip(self, client):
        resp = client.get("/hospitals/?skip=1&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1

    def test_pagination_limit(self, client):
        resp = client.get("/hospitals/?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 2

    def test_hospital_has_required_fields(self, client):
        resp = client.get("/hospitals/")
        data = resp.json()
        for h in data:
            assert "id" in h
            assert "name" in h


class TestGetHospital:
    def test_get_existing(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        resp = client.get(f"/hospitals/{hospital.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == hospital.id
        assert data["name"] == hospital.name

    def test_get_nonexistent(self, client):
        resp = client.get("/hospitals/99999")
        assert resp.status_code == 404


class TestListIndicators:
    def test_returns_indicators(self, client):
        resp = client.get("/hospitals/indicators")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_indicator_has_fields(self, client):
        resp = client.get("/hospitals/indicators")
        data = resp.json()
        for ind in data:
            assert "code" in ind
            assert "name" in ind


class TestReanalyzeHospital:
    def test_reanalyze_missing_month(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        resp = client.post(f"/hospitals/{hospital.id}/re-analyze")
        assert resp.status_code in (400, 422)

    def test_reanalyze_nonexistent_hospital(self, client):
        resp = client.post("/hospitals/99999/re-analyze", params={"month": "2026-04"})
        assert resp.status_code == 404

    def test_reanalyze_no_data(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        resp = client.post(
            f"/hospitals/{hospital.id}/re-analyze",
            params={"month": "2099-01"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_quality_score"] == 0

    def test_reanalyze_with_data(self, client, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, indicator_id=ind.id,
                    month="2026-04", value=value,
                ))
        db_session.commit()

        resp = client.post(
            f"/hospitals/{hospital.id}/re-analyze",
            params={"month": "2026-04"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data_quality_score" in data
        assert data["cached"] is False

    def test_reanalyze_force(self, client, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, indicator_id=ind.id,
                    month="2026-05", value=value,
                ))
        db_session.commit()

        client.post(f"/hospitals/{hospital.id}/re-analyze", params={"month": "2026-05"})
        resp = client.post(
            f"/hospitals/{hospital.id}/re-analyze",
            params={"month": "2026-05", "force": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is False
