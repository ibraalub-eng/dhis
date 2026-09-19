"""Agent-layer data model round-trip tests (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    User, Conversation, Message, AgentRun, AgentCache, AgentDataVersion,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_conversation_message_roundtrip(db_session):
    u = User(username="a", email="a@t.com", full_name="A", password_hash="x")
    db_session.add(u)
    db_session.commit()
    conv = Conversation(user_id=u.id, title="Q", lang="en")
    db_session.add(conv)
    db_session.commit()
    db_session.add(Message(conversation_id=conv.id, message_type="user", role="user", content="hi"))
    db_session.add(Message(conversation_id=conv.id, message_type="assistant", role="assistant",
                           content='{"done": true, "answer": "ok"}', token_usage={"in": 10, "out": 5}))
    db_session.commit()
    msgs = db_session.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.id).all()
    assert len(msgs) == 2
    assert msgs[0].message_type == "user"
    assert msgs[1].token_usage == {"in": 10, "out": 5}


def test_agent_run_roundtrip(db_session):
    u = User(username="b", email="b@t.com", full_name="B", password_hash="x")
    db_session.add(u)
    db_session.commit()
    run = AgentRun(user_id=u.id, agent="qa", status="completed", duration_ms=120,
                   steps=2, tool_calls=[{"name": "get_quality_score"}],
                   tokens={"in": 100, "out": 50}, provider="local", model="qwen3:8b",
                   language="en", cache_hit=False, fallback_used=False,
                   hospital_scope_hash="h", permission_scope_hash="p")
    db_session.add(run)
    db_session.commit()
    row = db_session.query(AgentRun).filter(AgentRun.agent == "qa").first()
    assert row.status == "completed"
    assert row.tool_calls == [{"name": "get_quality_score"}]


def test_agent_cache_roundtrip(db_session):
    db_session.add(AgentCache(cache_key="agents:qa:xyz:1", result_json='{"answer": "x"}',
                              data_version="42", hospital_scope_hash="abc"))
    db_session.commit()
    row = db_session.query(AgentCache).filter_by(cache_key="agents:qa:xyz:1").first()
    assert row is not None and row.data_version == "42"


def test_agent_data_version_unique(db_session):
    from sqlalchemy.exc import IntegrityError
    db_session.add(AgentDataVersion(hospital_id=1, month="2026-08", version=1))
    db_session.commit()
    db_session.add(AgentDataVersion(hospital_id=1, month="2026-08", version=2))
    with pytest.raises(IntegrityError):
        db_session.commit()