"""Regression tests for startup migration/revision detection.

Guards the sticky-startup bug where a DB stamped at a stale alembic
revision (e.g. after a failed migration) was treated as fully initialized,
so pending migrations were never retried and API endpoints that reference
the new tables 500'd (see /dashboard/overview missing
indicator_default_config).
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import _db_already_initialized


CREATE_APP_CONFIG = """
CREATE TABLE app_config (
    id INTEGER NOT NULL PRIMARY KEY,
    key VARCHAR(100) NOT NULL,
    value FLOAT NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT 'general',
    label VARCHAR(200),
    updated_at DATETIME
)
"""


def _make_session(with_version_table, with_app_config_row):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    with engine.begin() as conn:
        conn.exec_driver_sql(CREATE_APP_CONFIG)
        conn.exec_driver_sql("CREATE UNIQUE INDEX uq_app_config_key ON app_config (key)")
        if with_app_config_row:
            conn.exec_driver_sql(
                "INSERT INTO app_config (id, key, value, category) VALUES (1, 'k', 1.0, 'general')"
            )
        if with_version_table:
            conn.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
            conn.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES ('00000000_old_rev')"
            )
    return session, engine


@pytest.fixture
def stale_db():
    session, engine = _make_session(with_version_table=True, with_app_config_row=True)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def head_db():
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory
    from app.config import BASE_DIR

    session, engine = _make_session(with_version_table=True, with_app_config_row=True)
    script = ScriptDirectory.from_config(
        AlembicConfig(os.path.join(BASE_DIR, "alembic.ini"))
    )
    session.execute(
        text("UPDATE alembic_version SET version_num = :h"),
        {"h": script.get_current_head()},
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_missing_version_table_is_not_initialized():
    session, engine = _make_session(with_version_table=False, with_app_config_row=True)
    try:
        assert _db_already_initialized(session) is False
    finally:
        session.close()
        engine.dispose()


def test_empty_app_config_is_not_initialized():
    session, engine = _make_session(with_version_table=True, with_app_config_row=False)
    try:
        assert _db_already_initialized(session) is False
    finally:
        session.close()
        engine.dispose()


def test_stale_revision_is_not_initialized(stale_db):
    assert _db_already_initialized(stale_db) is False


def test_head_revision_is_initialized(head_db):
    assert _db_already_initialized(head_db) is True