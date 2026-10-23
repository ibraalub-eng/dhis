"""Migration d7e8f9a0b1c2 — indicator_definitions / versions / results.

The startup lifespan runs ``_ensure_all_tables()`` (create_all checkfirst)
BEFORE ``alembic upgrade head``, so this migration must be a guarded no-op
when the tables already exist, and must create the exact DDL shape the
models declare when they do not. Both paths are covered here, plus the
downgrade path.
"""
import os

from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command as alembic_command
from app.config import BASE_DIR
from app.engine import indicator_calc as calc
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorDefinitionVersion,
    IndicatorResult,
    IndicatorValue,
)

DOWN_REV = "e5f6a7b8c9d0"
NEW_TABLES = ("indicator_definitions", "indicator_definition_versions",
              "indicator_results")
PRE_ROUNDING_HEAD = "f1a2b3c4d5e6"


def _head_revision():
    """The real chain head, so adding a migration after this one does not
    leave this test asserting a stale revision id."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_alembic_cfg("sqlite://")).get_current_head()


def _alembic_cfg(db_url):
    cfg = AlembicConfig(os.path.join(BASE_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _with_db_url(db_url, fn):
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        fn()
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


def _upgrade(db_url, revision="head"):
    _with_db_url(db_url, lambda: alembic_command.upgrade(_alembic_cfg(db_url),
                                                         revision))


def _downgrade(db_url, revision=DOWN_REV):
    _with_db_url(db_url, lambda: alembic_command.downgrade(_alembic_cfg(db_url),
                                                           revision))


# ── fresh DB: the full chain creates the three tables ───────────────────────

def test_upgrade_head_creates_all_three_tables(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'ind_upgrade.db').as_posix()}"
    engine = create_engine(db_url)
    try:
        _upgrade(db_url)
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        for table in NEW_TABLES:
            assert table in tables, table

        cols = {c["name"] for c in insp.get_columns("indicator_definitions")}
        assert {"code", "name", "formula_type", "expression",
                "numerator_codes", "denominator_codes", "operator",
                "multiplier", "aggregation", "result_type", "unit",
                "direction", "threshold_low", "threshold_high",
                "target_min", "target_max", "is_active", "version"} <= cols
        anomaly_cols = {
            c["name"] for c in insp.get_columns("anomaly_results")
        }
        assert {"indicator_id", "formula", "formula_version"} <= anomaly_cols

        uqs = {u["name"] for u in
               insp.get_unique_constraints("indicator_definitions") if u["name"]}
        assert "uq_indicator_definition_code" in uqs

        result_uqs = {u["name"] for u in
                      insp.get_unique_constraints("indicator_results") if u["name"]}
        assert "uq_indicator_result_def_hosp_month" in result_uqs

        indexes = {i["name"] for i in insp.get_indexes("indicator_results")
                   if i["name"]}
        assert "ix_ir_hosp_month" in indexes

        # audit trail outlives the definition; results vanish with it
        v_fk = {f["options"].get("ondelete")
                for f in insp.get_foreign_keys("indicator_definition_versions")}
        assert "SET NULL" in v_fk
        r_fk = {f["options"].get("ondelete")
                for f in insp.get_foreign_keys("indicator_results")}
        assert "CASCADE" in r_fk
    finally:
        engine.dispose()


def test_downgrade_removes_the_three_tables(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'ind_down.db').as_posix()}"
    engine = create_engine(db_url)
    try:
        _upgrade(db_url)
        assert set(NEW_TABLES) <= set(inspect(engine).get_table_names())
        _downgrade(db_url)
        remaining = set(inspect(engine).get_table_names())
        assert not (set(NEW_TABLES) & remaining), remaining
    finally:
        engine.dispose()


# ── deployed path: create_all ran first, migration must be a no-op ──────────

def test_migration_noop_when_create_all_already_created_tables(tmp_path):
    """Lifespan order: _ensure_all_tables() (create_all) THEN upgrade head.
    The guarded migration must skip creation and keep existing data."""
    db_url = f"sqlite:///{(tmp_path / 'ind_noop.db').as_posix()}"
    engine = create_engine(db_url)
    try:
        from app.database import Base
        Base.metadata.create_all(engine)

        # seed through the ORM exactly like the app would
        db = sessionmaker(bind=engine)()
        try:
            h = Hospital(name="Mig Idem Hospital")
            ind5 = Indicator(code="5", name="Caesarean Sections")
            ind2 = Indicator(code="2", name="Total Deliveries")
            db.add_all([h, ind5, ind2])
            db.flush()
            defn = IndicatorDefinition(
                code="cs_rate", name="C-Section Rate", formula_type="ratio",
                numerator_codes=["5"], denominator_codes=["2"], operator="/",
                multiplier=100.0, aggregation="sum", result_type="percentage",
                is_active=True, version=1)
            db.add(defn)
            db.flush()
            db.add(IndicatorDefinitionVersion(
                definition_id=defn.id, definition_code=defn.code, version=1,
                action="created", snapshot="{}"))
            db.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind5.id, month="2026-03",
                value=30.0))
            calc.compute_and_store(db, defn, h.id, "2026-03")
            db.commit()
            defn_id, defn_code = defn.id, defn.code
        finally:
            db.close()

        # deployed bootstrap: stamped at the OLD head, then upgrade head —
        # the guarded creates must skip and the seeded rows must survive.
        _with_db_url(db_url, lambda: alembic_command.stamp(
            _alembic_cfg(db_url), DOWN_REV))
        _upgrade(db_url)

        db2 = sessionmaker(bind=engine)()
        try:
            kept = db2.get(IndicatorDefinition, defn_id)
            assert kept is not None and kept.code == defn_code
            assert db2.query(IndicatorDefinitionVersion).count() >= 1
            assert db2.query(IndicatorResult).count() == 1
        finally:
            db2.close()
    finally:
        engine.dispose()


# ── model/migration DDL parity ──────────────────────────────────────────────

def test_models_declare_expected_constraints():
    def _uqs(table):
        return {c.name for c in table.constraints
                if c.__class__.__name__ == "UniqueConstraint"}

    assert "uq_indicator_definition_code" in _uqs(IndicatorDefinition.__table__)
    assert "uq_indicator_result_def_hosp_month" in _uqs(IndicatorResult.__table__)


def test_version_rows_are_nullable_on_definition_id():
    """definition_id must be nullable — the audit trail outlives deletions."""
    col = IndicatorDefinitionVersion.__table__.c.definition_id
    assert col.nullable is True


def test_upgrade_adds_rounding_to_database_already_at_previous_head(tmp_path):
    """Older databases at the previous Alembic head may lack rounding."""
    db_url = f"sqlite:///{(tmp_path / 'ind_rounding.db').as_posix()}"
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            conn.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES (?)",
                (PRE_ROUNDING_HEAD,),
            )
            conn.exec_driver_sql(
                "CREATE TABLE indicator_definitions "
                "(id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)"
            )
            conn.exec_driver_sql(
                "INSERT INTO indicator_definitions (id, code) "
                "VALUES (1, 'existing_rate')"
            )

        _upgrade(db_url)

        with engine.connect() as conn:
            revision = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            row = conn.exec_driver_sql(
                "SELECT code, rounding FROM indicator_definitions WHERE id = 1"
            ).one()
        assert revision == _head_revision()
        assert row == ("existing_rate", "half_up")
    finally:
        engine.dispose()
