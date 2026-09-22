"""Agents API: kill-switch, permissions, caps, persistence."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Hospital, Permission, Role, User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h = Hospital(name="Alpha", region="R")
    s.add(h)
    s.commit()
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
    app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user(db_session, username, codenames, is_superuser=False):
    perms = [Permission(codename=c) for c in codenames]
    role = Role(name=username + "_role", permissions=perms)
    db_session.add(role)
    db_session.add_all(perms)
    db_session.commit()
    u = User(username=username, email=username + "@t.com", full_name=username,
             password_hash=hash_password("pw"), is_superuser=is_superuser, roles=[role])
    db_session.add(u)
    db_session.commit()
    token = create_access_token(user_id=u.id, roles=[role.name], permissions=list(codenames))
    return {"Authorization": f"Bearer {token}"}


def test_status_off_by_default(client, db_session):
    hdr = _user(db_session, "viewer", [])
    r = client.get("/ai/agents/status", headers=hdr)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_disabled_returns_no_run(client, db_session, monkeypatch):
    hdr = _user(db_session, "reader", ["ai.read"])
    called = []

    def fake_run(**kw):
        called.append(kw)
        from app.agents.runtime import AgentResult
        return AgentResult(agent="qa", answer="x", language="en")
    monkeypatch.setattr("app.api.agents.run_agent", fake_run)
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "false"})
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert called == []


def test_chat_requires_ai_read(client, db_session, monkeypatch):
    hdr = _user(db_session, "nolibs", [])
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 403


def test_chat_runs_and_persists(client, db_session, monkeypatch):
    hdr = _user(db_session, "reader", ["ai.read"])
    from app.agents.runtime import AgentResult
    monkeypatch.setattr("app.api.agents.get_ai_config",
                        lambda db: {"agents_enabled": "true", "agents_provider": "auto",
                                    "agent_provider_roles": "{}", "local_runtime": "ollama",
                                    "local_model": "qwen3:8b", "local_url": "http://127.0.0.1:9"})
    monkeypatch.setattr("app.api.agents.run_agent",
                        lambda **kw: AgentResult(agent="qa", answer="hi there", language="en",
                                                 steps=1, tool_calls=[], tokens={"in": 1, "out": 1},
                                                 provider="local", model="m", status="completed"))
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "hi there" and data["enabled"] is True
    conv = data["conversation_id"]
    msgs = client.get(f"/ai/agents/chat/{conv}/messages", headers=hdr)
    assert msgs.status_code == 200 and len(msgs.json()) == 2  # user + assistant


def test_report_requires_ai_write(client, db_session, monkeypatch):
    # ai.read only -> 403 (spec §9: report needs BOTH)
    hdr = _user(db_session, "reader", ["ai.read"])
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "true"})
    r = client.post("/ai/agents/report", headers=hdr,
                    json={"hospital_id": 1, "month": "2026-08", "lang": "en"})
    assert r.status_code == 403


def test_report_and_digest_blocked_without_ai_read(client, db_session, monkeypatch):
    # ai.write only (has ai.write but NOT ai.read) -> still 403 on both
    hdr = _user(db_session, "writer_no_read", ["ai.write"])
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "true"})
    r = client.post("/ai/agents/report", headers=hdr,
                    json={"hospital_id": 1, "month": "2026-08", "lang": "en"})
    assert r.status_code == 403
    r2 = client.post("/ai/agents/digest", headers=hdr, json={"month": "2026-08"})
    assert r2.status_code == 403


def test_admin_runs_gated(client, db_session):
    hdr = _user(db_session, "ops", ["ai.read"])
    r = client.get("/ai/agents/runs", headers=hdr)
    assert r.status_code == 403
    admin_hdr = _user(db_session, "boss", ["system.manage_users"])
    r2 = client.get("/ai/agents/runs", headers=admin_hdr)
    assert r2.status_code == 200


def test_daily_cap(client, db_session, monkeypatch):
    from datetime import datetime

    from app.models import AgentRun
    hdr = _user(db_session, "reader", ["ai.read"])
    monkeypatch.setattr("app.api.agents.get_ai_config",
                        lambda db: {"agents_enabled": "true", "agents_provider": "auto",
                                    "agent_provider_roles": "{}", "local_runtime": "ollama",
                                    "local_model": "qwen3:8b", "local_url": "http://127.0.0.1:9"})
    from app.api.agents import AGENT_DAILY_CAP
    for _i in range(AGENT_DAILY_CAP):
        u = db_session.query(User).filter(User.username == "reader").first()
        db_session.add(AgentRun(user_id=u.id, agent="qa", status="completed",
                                created_at=datetime.utcnow()))
    db_session.commit()
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 429


def test_admin_put_settings_validation(client, db_session, monkeypatch):
    hdr = _user(db_session, "boss", ["system.manage_users"])
    r = client.put("/ai/agents/admin", headers=hdr, json={"agent_provider_roles": '{"qa": "bad"}'})
    assert r.status_code == 422


def test_prune_removes_old_runs(db_session):
    from datetime import datetime, timedelta
    from app.models import AgentRun
    from app.api.agents import prune_agent_runs
    db_session.add(AgentRun(user_id=1, agent="qa", status="completed",
                            created_at=datetime.utcnow() - timedelta(days=200)))
    db_session.add(AgentRun(user_id=1, agent="qa", status="completed",
                            created_at=datetime.utcnow()))
    db_session.commit()
    deleted = prune_agent_runs(db_session, retention_days=90)
    assert deleted == 1
    assert db_session.query(AgentRun).count() == 1
