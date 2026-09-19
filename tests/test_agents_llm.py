"""Provider shim tests — no real network. httpx and genai are monkeypatched."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SystemSetting
from app.agents.llm import resolve_agent_provider, llm_chat
from app.agents.llm import ResolvedProvider


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _set(db, **kv):
    for k, v in kv.items():
        db.add(SystemSetting(key=k, value=str(v)))
    db.commit()


def test_resolve_role_map_wins(db_session, monkeypatch):
    monkeypatch.setattr("app.agents.llm._local_reachable", lambda url, timeout=1.0: True)
    _set(db_session, agent_provider_roles='{"report_writer": "gemini"}', agents_provider="auto",
         ai_api_key="k1", local_model="qwen3:8b", local_url="http://localhost:11434")
    rp = resolve_agent_provider("report_writer", db_session)
    assert rp.provider == "gemini"
    rp2 = resolve_agent_provider("qa", db_session)
    assert rp2.provider == "local"   # auto -> local reachable -> local


def test_resolve_global_provider(db_session):
    _set(db_session, agents_provider="openai_compatible", ai_api_url="http://x/v1/chat/completions", ai_api_key="k")
    rp = resolve_agent_provider("triage", db_session)
    assert rp.provider == "openai_compatible"
    assert rp.model == "gemini-3.5-flash-lite" or rp.model


def test_resolve_rejects_unknown_role(db_session):
    _set(db_session, agent_provider_roles='{"nope": "local"}')
    with pytest.raises(ValueError):
        resolve_agent_provider("qa", db_session)


def test_resolve_mapped_but_down_degrades_to_global(db_session, monkeypatch):
    # report_writer is mapped to local, but local is unreachable and
    # no local_model/openai-compatible config -> degrade to global gemini
    monkeypatch.setattr("app.agents.llm._local_reachable", lambda url, timeout=1.0: False)
    _set(db_session, agent_provider_roles='{"report_writer": "local"}',
         agents_provider="gemini", ai_api_key="k1")
    rp = resolve_agent_provider("report_writer", db_session)
    assert rp.provider == "gemini"
    # mapped local IS configured+reachable -> mapped wins
    monkeypatch.setattr("app.agents.llm._local_reachable", lambda url, timeout=1.0: True)
    _set(db_session, local_model="qwen3:8b")   # other keys already set (key is PK)
    rp2 = resolve_agent_provider("report_writer", db_session)
    assert rp2.provider == "local"


def test_llm_chat_openai_compatible(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        headers = {}
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"tools": []}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4}}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, url, json, headers=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    rp = ResolvedProvider(provider="openai_compatible", model="m1",
                          base_url="http://x/v1/chat/completions", needs_key=True)
    out = llm_chat(rp, system="sys", user="hi", max_output_tokens=100)
    assert out.text == '{"tools": []}'
    assert out.prompt_tokens == 12 and out.completion_tokens == 4
    assert captured["url"] == "http://x/v1/chat/completions"
    assert captured["payload"]["messages"][0]["content"] == "sys"