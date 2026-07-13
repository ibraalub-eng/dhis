"""Tests for config API endpoints (api.config_api)."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import AppConfig, SystemSetting


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


class TestControlSettings:
    def test_get_default(self, client):
        resp = client.get("/config/control/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "auto_disable_null_indicators" in data
        assert data["auto_disable_null_indicators"] is False

    def test_update_setting(self, client):
        resp = client.put("/config/control/settings", json={"auto_disable_null_indicators": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_disable_null_indicators"] is True

    def test_update_to_false(self, client):
        client.put("/config/control/settings", json={"auto_disable_null_indicators": True})
        resp = client.put("/config/control/settings", json={"auto_disable_null_indicators": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_disable_null_indicators"] is False

    def test_get_after_update(self, client):
        client.put("/config/control/settings", json={"auto_disable_null_indicators": True})
        resp = client.get("/config/control/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_disable_null_indicators"] is True


class TestGetAllConfig:
    def test_returns_categories(self, client):
        resp = client.get("/config/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_config_structure(self, client, db_session):
        db_session.add(AppConfig(
            key="test_key", value=42.0, category="test", label="Test Key",
        ))
        db_session.commit()

        resp = client.get("/config/")
        data = resp.json()
        assert "test" in data
        assert "test_key" in data["test"]
        assert data["test"]["test_key"]["value"] == 42.0


class TestGetConfigByCategory:
    def test_existing_category(self, client, db_session):
        db_session.add(AppConfig(
            key="cat_key", value=10.0, category="testcat", label="Cat Key",
        ))
        db_session.commit()

        resp = client.get("/config/testcat")
        assert resp.status_code == 200
        data = resp.json()
        assert "cat_key" in data
        assert data["cat_key"]["value"] == 10.0

    def test_nonexistent_category(self, client):
        resp = client.get("/config/nonexistent_category_xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {}


class TestUpdateConfig:
    def test_update_existing(self, client, db_session):
        db_session.add(AppConfig(
            key="update_key", value=1.0, category="test", label="Update Key",
        ))
        db_session.commit()

        resp = client.put("/config/", json={"update_key": 99.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["updated"] == 1

    def test_update_multiple(self, client, db_session):
        db_session.add_all([
            AppConfig(key="mk1", value=1.0, category="t", label="K1"),
            AppConfig(key="mk2", value=2.0, category="t", label="K2"),
        ])
        db_session.commit()

        resp = client.put("/config/", json={"mk1": 10.0, "mk2": 20.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 2

    def test_update_nonexistent_key(self, client):
        resp = client.put("/config/", json={"nonexistent_key_xyz": 5.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 0

    def test_update_invalid_value(self, client, db_session):
        db_session.add(AppConfig(
            key="inv_key", value=1.0, category="t", label="Inv",
        ))
        db_session.commit()

        resp = client.put("/config/", json={"inv_key": "not_a_number"})
        assert resp.status_code == 422


class TestAiSettings:
    def test_get_ai_settings(self, client):
        resp = client.get("/config/ai/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
