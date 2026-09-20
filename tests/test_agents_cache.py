"""Versioned agent cache + single-flight + data_version bump."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AgentCache, AgentDataVersion
from app.agents import cache as acache


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_build_key_includes_scope_and_version():
    k1 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                      permission_scope_hash="P", month="2026-08",
                                      entity="", data_version="7", language="en", prompt_hash="X")
    k2 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="B",
                                      permission_scope_hash="P", month="2026-08",
                                      entity="", data_version="7", language="en", prompt_hash="X")
    assert k1 != k2
    assert "agents:qa" in k1


def test_bump_and_current_version(db_session):
    acache.bump_data_version(db_session, [1, 2], ["2026-08"])
    acache.bump_data_version(db_session, [1], ["2026-08"])
    assert acache.current_data_version(db_session, [1], "2026-08") == "2"
    rows = db_session.query(AgentDataVersion).all()
    assert {(r.hospital_id, r.month) for r in rows} == {(1, "2026-08"), (2, "2026-08")}


def test_cache_set_get_and_expiry(db_session):
    key = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                       permission_scope_hash="P", month="2026-08",
                                       entity="", data_version="1", language="en", prompt_hash="X")
    acache.set_agent_cache(db_session, key, '{"answer": "hi"}', data_version="1",
                           hospital_scope_hash="A")
    assert acache.get_agent_cache(db_session, key) == '{"answer": "hi"}'
    # a different scope must NOT match
    key2 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="B",
                                        permission_scope_hash="P", month="2026-08",
                                        entity="", data_version="1", language="en", prompt_hash="X")
    assert acache.get_agent_cache(db_session, key2) is None


def test_data_version_mismatch_is_miss(db_session):
    key = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                       permission_scope_hash="P", month="2026-08",
                                       entity="", data_version="1", language="en", prompt_hash="X")
    acache.set_agent_cache(db_session, key, "x", data_version="1", hospital_scope_hash="A")
    key_stale = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                             permission_scope_hash="P", month="2026-08",
                                             entity="", data_version="99", language="en", prompt_hash="X")
    assert acache.get_agent_cache(db_session, key_stale) is None