"""ReAct loop mechanics with a scripted fake LLM."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Hospital
from app.agents.runtime import run_agent, AgentResult


class FakeSuperUser:
    is_superuser = True
    id = 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Hospital(name="Alpha", region="R"))
    s.add(Hospital(name="Beta", region="R"))
    s.commit()
    yield s
    s.close()


def _fake_llm(script):
    """Return a callable that yields scripted tool-JSON then a final answer."""
    calls = []
    def caller(resolved, system, user, max_output_tokens=3000, timeout=30.0):
        calls.append(user)
        from app.agents.llm import ChatResult
        if len(calls) == 1 and script[0]:
            step = script.pop(0)
            return ChatResult(text=step, provider="local", model="qwen3:8b",
                              prompt_tokens=100, completion_tokens=20)
        return ChatResult(text=script.pop(0), provider="local", model="qwen3:8b",
                          prompt_tokens=100, completion_tokens=20)
    return caller


def test_run_agent_tool_then_answer(db_session, monkeypatch):
    script = ['{"tools": [{"name": "list_accessible_hospitals", "args": {}}], "done": false}',
              '{"done": true, "answer": "Alpha and Beta"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="list hospitals", llm_caller=_fake_llm(script))
    assert res.status == "completed"
    assert res.answer == "Alpha and Beta"
    assert res.steps == 1
    assert res.tool_calls and res.tool_calls[0]["name"] == "list_accessible_hospitals"
    assert res.provider in ("local", "gemini", "openai_compatible")


def test_run_agent_early_finish_no_tools(db_session, monkeypatch):
    script = ['{"done": true, "answer": "Direct"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="hi", llm_caller=_fake_llm(script))
    assert res.steps == 0
    assert res.status == "completed"


def test_run_agent_malformed_json_then_fallback(db_session, monkeypatch):
    script = ["not json at all", "also not json"]
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="explainer", user=FakeSuperUser(), db=db_session,
                    month="2026-08", entity="cs_rate", question="why",
                    llm_caller=_fake_llm(script))
    assert res.status == "fallback"
    assert res.fallback_used is True
    assert res.answer.strip() != ""
    assert "Insufficient data" in res.answer or "finding" in res.answer.lower()


def test_run_agent_step_budget_exceeded(db_session, monkeypatch):
    script = ['{"tools": [{"name": "list_accessible_hospitals", "args": {}}], "done": false}'] * 20
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="q", llm_caller=_fake_llm(script))
    assert res.status == "budget_exceeded"


def test_run_agent_rejects_disallowed_tool(db_session, monkeypatch):
    # triage may NOT call get_clinical_profile -> validation observation
    script = ['{"tools": [{"name": "get_clinical_profile", "args": {"hospital_ids": [1], "month": "2026-08"}}], "done": false}',
              '{"done": true, "answer": "done"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="triage", user=FakeSuperUser(), db=db_session,
                    month="2026-08", entity="", question="digest",
                    llm_caller=_fake_llm(script))
    assert res.status == "completed"
    # the rejected tool must never have been executed for real
    assert all(tc["name"] != "get_clinical_profile" for tc in res.tool_calls)


def test_run_agent_history_compression(db_session, monkeypatch):
    # 12 prior turns -> last ~6 kept verbatim, older folded into a summary line
    captured = {}
    def caller(resolved, system, user, max_output_tokens=3000, timeout=30.0):
        captured["user"] = user
        from app.agents.llm import ChatResult
        return ChatResult(text='{"done": true, "answer": "ok"}', provider="local",
                          model="m", prompt_tokens=10, completion_tokens=5)
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
               for i in range(12)]
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="q", llm_caller=caller, history=history)
    assert res.status == "completed"
    assert "summary" in captured["user"].lower()
    assert "turn 5" not in captured["user"]        # older turn folded, not verbatim
    assert "turn 11" in captured["user"]           # most recent turn kept verbatim