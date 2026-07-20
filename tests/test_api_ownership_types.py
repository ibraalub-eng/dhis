"""Tests for facility-ownerships and facility-types API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Hospital


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


class TestFacilityOwnerships:
    def test_list_empty(self, client):
        resp = client.get("/facility-ownerships/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create(self, client):
        resp = client.post("/facility-ownerships/", json={"name": "\u062d\u0643\u0648\u0645\u064a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "\u062d\u0643\u0648\u0645\u064a"
        assert "id" in data

    def test_create_duplicate(self, client):
        client.post("/facility-ownerships/", json={"name": "NGOs"})
        resp = client.post("/facility-ownerships/", json={"name": "NGOs"})
        assert resp.status_code == 400

    def test_update(self, client):
        client.post("/facility-ownerships/", json={"name": "OLD"})
        resp = client.put("/facility-ownerships/1", json={"name": "NEW"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "NEW"

    def test_delete(self, client):
        client.post("/facility-ownerships/", json={"name": "DELETE_ME"})
        resp = client.delete("/facility-ownerships/1")
        assert resp.status_code == 200

    def test_delete_linked_hospital_fails(self, client, db_session):
        client.post("/facility-ownerships/", json={"name": "GOV"})
        h = db_session.query(Hospital).first()
        h.facility_ownership_id = 1
        db_session.commit()
        resp = client.delete("/facility-ownerships/1")
        assert resp.status_code == 400

    def test_get_nonexistent(self, client):
        resp = client.get("/facility-ownerships/999")
        assert resp.status_code == 404


class TestFacilityTypes:
    def test_list_empty(self, client):
        resp = client.get("/facility-types/")
        assert resp.status_code == 200

    def test_create(self, client):
        resp = client.post("/facility-types/", json={"name": "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "\u0645\u0633\u062a\u0634\u0641\u064a\u0627\u062a"

    def test_create_duplicate(self, client):
        client.post("/facility-types/", json={"name": "X"})
        resp = client.post("/facility-types/", json={"name": "X"})
        assert resp.status_code == 400

    def test_update(self, client):
        client.post("/facility-types/", json={"name": "A"})
        resp = client.put("/facility-types/1", json={"name": "B"})
        assert resp.status_code == 200

    def test_delete(self, client):
        client.post("/facility-types/", json={"name": "DEL"})
        resp = client.delete("/facility-types/1")
        assert resp.status_code == 200

    def test_delete_linked_hospital_fails(self, client, db_session):
        client.post("/facility-types/", json={"name": "FT"})
        h = db_session.query(Hospital).first()
        h.facility_type_id = 1
        db_session.commit()
        resp = client.delete("/facility-types/1")
        assert resp.status_code == 400


class TestHospitalExtended:
    def test_hospital_has_new_fields(self, client):
        resp = client.get("/hospitals/")
        assert resp.status_code == 200
        data = resp.json()
        if data:
            h = data[0]
            assert "organisation_unit_id" in h
            assert "facility_ownership_id" in h
            assert "facility_type_id" in h
            assert "facility_ownership_name" in h
            assert "facility_type_name" in h
