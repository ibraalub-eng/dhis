"""Deterministic profile fallbacks: no LLM, bilingual, grounded in tool reads."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Hospital, QualityScore, ValidationResult
from app.agents.tools import ToolContext
from app.agents.profiles.fallbacks import fallback_answer


class FakeUser:
    is_superuser = True
    id = 1


@pytest.fixture(autouse=True)
def _bypass_auth():
    """Shadow conftest's autouse auth-bypass so these unit tests do not import app.main."""
    yield


@pytest.fixture
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h = Hospital(name="Alpha", region="R")
    s.add(h)
    s.commit()
    s.add(QualityScore(hospital_id=h.id, month="2026-08", score=54.0, rule_compliance=40.0))
    s.add(ValidationResult(hospital_id=h.id, month="2026-08", rule_code="1.a.1",
                           rule_description="CS rate within threshold", status="FAIL",
                           severity="high"))
    s.commit()
    s.expunge(h)
    c = ToolContext(s, FakeUser(), "2026-08")
    yield c
    s.close()


def test_fallback_uses_facts_only(ctx):
    out = fallback_answer("explainer", ctx, "", "en")
    assert out["facts"]
    assert any("quality" in str(t).lower() for t in out["facts"])
    assert out["answer"]


def test_fallback_empty_data_safe(ctx):
    empty = type("Ctx", (), {})()
    empty.quality_row = lambda hid: None
    empty.rule_rows = lambda hid: []
    empty.anomaly_rows = lambda hid: []
    empty.hospital_data = lambda: {}
    out = fallback_answer("explainer", empty, "", "en")
    assert "Insufficient data" in out["answer"]


def test_fallback_arabic_present(ctx):
    out = fallback_answer("explainer", ctx, "", "ar")
    assert out["answer"].strip() != ""