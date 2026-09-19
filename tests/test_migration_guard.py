"""Tests for the startup migration-sync guard (app.main._check_migration_sync)."""
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.main import _check_migration_sync, app


@pytest.fixture
def client(db_session):
    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_exposes_schema_sync_state(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "schema_in_sync" in data
    # None (unknown) or True/False are all valid states
    assert data["schema_in_sync"] in (None, True, False)


class _FakeConn:
    def __init__(self, version):
        self._version = version

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q):
        version = self._version

        class R:
            def fetchone(self):
                return (version,)
        return R()


class _FakeEngine:
    def __init__(self, version):
        self._version = version

    def connect(self):
        return _FakeConn(self._version)


class _FakeScript:
    def __init__(self, head):
        self._head = head

    def get_current_head(self):
        return self._head


def test_sync_guard_sets_true_when_revision_matches(monkeypatch):
    """A DB whose alembic_version equals the script head is in sync
    (hermetic: uses a fake engine, never touches a real database)."""
    import app.main as main_mod
    monkeypatch.setattr(main_mod.ScriptDirectory, "from_config", staticmethod(lambda cfg: _FakeScript("d5e6f7a8b9c0")))
    monkeypatch.setattr(main_mod, "engine", _FakeEngine("d5e6f7a8b9c0"))
    _check_migration_sync()
    assert main_mod.schema_in_sync is True


def test_sync_guard_detects_drift(monkeypatch):
    """A DB stamped at a bogus old revision must be reported as out of sync."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    # Stand up a scratch SQLite DB with an alembic_version table stamped wrong
    eng = create_engine("sqlite://")
    ctx = MigrationContext.configure(eng.connect())
    op = Operations(ctx)
    op.create_table("alembic_version", sa.Column("version_num", sa.String(32), nullable=False))
    op.execute("INSERT INTO alembic_version (version_num) VALUES ('0000old_revision')")
    eng.dispose()

    # Point the guard at that DB by stubbing Config/engine paths
    import app.main as main_mod
    calls = {}

    class FakeScript:
        def get_current_head(self):
            return "d5e6f7a8b9c0"

    def fake_from_config(cfg):
        return FakeScript()

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, q):
            calls["q"] = str(q)
            class R:
                def fetchone(self):
                    return ("0000old_revision",)
            return R()

    class FakeEngine:
        def connect(self):
            return FakeConn()

    monkeypatch.setattr(main_mod.ScriptDirectory, "from_config", staticmethod(fake_from_config))
    monkeypatch.setattr(main_mod, "engine", FakeEngine())

    _check_migration_sync()
    assert main_mod.schema_in_sync is False
