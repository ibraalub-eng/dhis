"""Agent config keys + validation tests."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config_utils import AI_CONFIG_KEYS, get_ai_config, validate_agents_config
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop("get_current_user", None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_keys_have_defaults():
    assert AI_CONFIG_KEYS["agents_enabled"] == "false"
    assert AI_CONFIG_KEYS["agents_provider"] == "auto"
    assert AI_CONFIG_KEYS["agent_provider_roles"] == "{}"
    assert AI_CONFIG_KEYS["local_runtime"] == "ollama"
    assert AI_CONFIG_KEYS["local_model"] == "qwen3:8b"
    assert AI_CONFIG_KEYS["local_url"] == "http://localhost:11434"


def test_validate_agents_provider_rejects_unknown():
    with pytest.raises(ValueError):
        validate_agents_config({"agents_provider": "claude"})
    # known values pass
    for val in ("local", "gemini", "openai_compatible", "auto"):
        validate_agents_config({"agents_provider": val})


def test_validate_agent_provider_roles_shape():
    validate_agents_config({"agent_provider_roles": '{"qa": "local", "report_writer": "gemini"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": '{"qa": "claude"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": '{"unknown_role": "local"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": "not-json"})
    # empty map + non-object values are invalid
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": "[]"})


def test_update_ai_settings_persists_agent_keys(client, db_session):
    resp = client.put("/config/ai/settings", json={"agents_enabled": "true", "agents_provider": "local"})
    assert resp.status_code == 200
    stored = get_ai_config(db_session)
    assert stored["agents_enabled"] == "true"
    assert stored["agents_provider"] == "local"


def test_update_ai_settings_rejects_bad_agent_provider(client):
    resp = client.put("/config/ai/settings", json={"agents_provider": "claude"})
    assert resp.status_code == 422


def test_get_ai_settings_contains_keys(client):
    resp = client.get("/config/ai/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents_enabled"] == "false"
    assert data["agents_provider"] == "auto"