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


# A stamped revision with no migration file behind it: the database gets stuck
# and 'alembic upgrade head' aborts before running anything.
_PHANTOM_REVISION = "a7b8c9d0e1f2"


def test_sync_guard_flags_a_recorded_revision_with_no_migration_file(monkeypatch, capsys):
    """A DB stamped at a revision the code chain does not contain must say so.

    This is not the same failure as being behind head: alembic cannot resolve
    the applied revision, so the operator has to restamp before upgrading. The
    real October 2026 restart hit exactly this (the hospital-month-audit
    migration had been renumbered, leaving 'a7b8c9d0e1f2' on the DB).
    """
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "engine", _FakeEngine(_PHANTOM_REVISION))

    _check_migration_sync()

    out = capsys.readouterr().out
    assert main_mod.schema_in_sync is False
    assert _PHANTOM_REVISION in out
    assert "no migration file" in out
    # The generic "just upgrade" advice would be wrong for this state.
    assert "Run 'alembic upgrade head' on this database." not in out


def test_sync_guard_keeps_upgrade_advice_for_a_known_older_revision(monkeypatch, capsys):
    """A revision that exists but is behind head still gets the upgrade advice."""
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "engine", _FakeEngine("f25afbb94bc7"))

    _check_migration_sync()

    out = capsys.readouterr().out
    assert main_mod.schema_in_sync is False
    assert "Run 'alembic upgrade head' on this database." in out
    assert "no migration file" not in out


def test_migration_chain_references_only_revisions_it_contains():
    """Every down_revision must name a migration file that exists.

    A renamed or deleted revision file leaves stamped databases with a revision
    id nothing can resolve. Catching it here fails the suite instead of the
    next app restart.
    """
    import os

    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    from app.config import BASE_DIR

    script = ScriptDirectory.from_config(
        AlembicConfig(os.path.join(BASE_DIR, "alembic.ini")))
    revisions = {rev.revision: rev for rev in script.walk_revisions()}

    heads = script.get_heads()
    assert len(heads) == 1, f"the chain must have exactly one head, got {heads}"

    for revision, rev in revisions.items():
        parents = rev.down_revision
        if parents is None:
            continue
        if isinstance(parents, str):
            parents = (parents,)
        for parent in parents:
            assert parent in revisions, (
                f"revision {revision} revises {parent}, which has no migration file "
                "- a renamed or removed revision makes stamped databases un-upgradable"
            )
