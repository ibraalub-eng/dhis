"""Tool registry: scope enforcement, validation, and response limits."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Hospital, Indicator, IndicatorValue


class FakeUser:
    is_superuser = False
    id = 1


class SuperUser:
    is_superuser = True
    id = 2


@pytest.fixture(autouse=True)
def _bypass_auth():
    """Shadow conftest's autouse auth-bypass so these unit tests do not import app.main."""
    yield


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h1 = Hospital(name="Alpha", region="R")
    h2 = Hospital(name="Beta", region="R")
    h3 = Hospital(name="Gamma", region="R")
    s.add_all([h1, h2, h3])
    s.flush()
    ind = Indicator(code="1", name="Test deliveries")
    s.add(ind)
    s.flush()
    s.add(IndicatorValue(hospital_id=h1.id, indicator_id=ind.id, month="2026-08", value=10.0))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def ctx(db_session):
    from app.agents.tools import ToolContext

    u = FakeUser()
    u.id = 1
    # restrict to hospitals 1 and 2 in the association table
    from app.models import user_hospitals
    db_session.execute(user_hospitals.insert().values(user_id=1, hospital_id=1))
    db_session.execute(user_hospitals.insert().values(user_id=1, hospital_id=2))
    db_session.commit()
    return ToolContext(db_session, u, "2026-08")


def test_list_accessible_hospitals_only_authorized(ctx):
    from app.agents.tools import execute_tool

    res = execute_tool("list_accessible_hospitals", {}, ctx)
    assert res["ok"] is True
    names = {r["id"] for r in res["data"]}
    assert names == {1, 2}


def test_unauthorized_hospital_denied(ctx):
    from app.agents.tools import execute_tool

    res = execute_tool("get_indicator_values",
                       {"hospital_ids": [3], "month": "2026-08", "indicators": ["cs_rate"]}, ctx)
    assert res["ok"] is False
    assert res["error"] == "ACCESS_DENIED"


def test_partial_scope_intersection(ctx):
    from app.agents.tools import execute_tool

    res = execute_tool("get_indicator_values",
                       {"hospital_ids": [1, 3], "month": "2026-08"}, ctx)
    assert res["ok"] is True
    hids = {r["hospital_id"] for r in res["data"]}
    assert 1 in hids and 3 not in hids


def test_invalid_month_rejected(ctx):
    from app.agents.tools import execute_tool

    res = execute_tool("get_indicator_values", {"hospital_ids": [1], "month": "2026-13"}, ctx)
    assert res["ok"] is False
    assert res["error"].startswith("validation")


def test_unknown_tool_rejected(ctx):
    from app.agents.tools import execute_tool

    res = execute_tool("get_nonexistent", {}, ctx)
    assert res["ok"] is False


def test_superadmin_sees_all(db_session):
    from app.agents.tools import ToolContext, execute_tool

    su = SuperUser()
    su.id = 2
    ctx = ToolContext(db_session, su, "2026-08")
    res = execute_tool("list_accessible_hospitals", {}, ctx)
    assert res["ok"] is True and len(res["data"]) == 3