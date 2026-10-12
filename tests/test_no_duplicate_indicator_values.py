"""US-02 — Prevent Duplicate Indicator Values (Critical).

Each (hospital_id, indicator_id, month) combination must be unique at the DB
level. Covers:
  * ORM metadata carries the named UniqueConstraint;
  * actual inserts raise IntegrityError (no two rows can coexist);
  * the e5f6a7b8c9d0 migration dedups existing rows before adding the
    constraint, keeping the newest row per key;
  * the Excel-parser upsert path overwrites instead of inserting a second row.
"""
import contextlib
import os

import pytest
import sqlalchemy as _sa
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from app.config import BASE_DIR
from app.models import Hospital, Indicator, IndicatorValue
from app.utils.excel_parser import import_data_to_db


def _constraint_names(ddl_table):
    return {c.name for c in ddl_table.constraints if c.__class__.__name__ == "UniqueConstraint"}


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _alembic_cfg(db_url):
    """Alembic config pinned to a scratch DB.

    alembic/env.py runs load_dotenv(override=False) and, when DATABASE_URL is
    set, overrides the config's url with it. .env points at the shared dev
    database, which these tests must never touch — so they export DATABASE_URL
    for the duration of the alembic call (see _with_db_url), which env.py
    faithfully reads.
    """
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


@pytest.fixture()
def alembic_upgrader():
    """Stamp a scratch file DB as the previous head, then upgrade to head."""
    def _up(db_url, *, stamp_first):
        if stamp_first:
            with_db = lambda: alembic_command.stamp(_alembic_cfg(db_url), "b1c2d3e4f5a6")  # noqa: E731
            _with_db_url(db_url, with_db)
        _with_db_url(db_url, lambda: alembic_command.upgrade(_alembic_cfg(db_url), "head"))
    return _up


# ── ORM metadata ─────────────────────────────────────────────────────────────

def test_model_declares_unique_hosp_ind_month():
    cons = _constraint_names(IndicatorValue.__table__)
    assert "uq_indicator_value_hosp_ind_month" in cons


def test_create_all_enforces_unique_hosp_ind_month():
    """End-to-end at the DB level: a second INSERT for the same
    (hospital, indicator, month) raises at flush, and a different month or
    different indicator still inserts fine."""
    engine = _engine()
    from app.database import Base
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        h = Hospital(name="Unique Test Hospital")
        i1 = Indicator(code="uq.ind1", name="Ind 1")
        i2 = Indicator(code="uq.ind2", name="Ind 2")
        db.add_all([h, i1, i2])
        db.flush()
        db.add(IndicatorValue(hospital_id=h.id, indicator_id=i1.id, month="2026-05", value=10.0))
        db.flush()  # first row ok
        with pytest.raises(IntegrityError):
            db.add(IndicatorValue(hospital_id=h.id, indicator_id=i1.id, month="2026-05", value=99.0))
            db.flush()
        db.rollback()
        # same indicator+hospital, different month: fine
        db.add(IndicatorValue(hospital_id=h.id, indicator_id=i1.id, month="2026-06", value=5.0))
        # same indicator+month, different indicator: fine
        db.add(IndicatorValue(hospital_id=h.id, indicator_id=i2.id, month="2026-05", value=7.0))
        db.flush()
        assert db.query(IndicatorValue).count() == 2
    finally:
        db.close()
        engine.dispose()


# ── Migration e5f6a7b8c9d0: dedup then constraint ────────────────────────────

def test_migration_dedups_existing_rows_and_adds_constraint(tmp_path, alembic_upgrader):
    """A pre-US-02 database with duplicate rows is healed: exactly one row per
    key survives (the newest), and the unique constraint is live afterwards."""
    db_url = f"sqlite:///{(tmp_path / 'us02_dedup.db').as_posix()}"
    engine = create_engine(db_url)
    # Hand-build the PRE-US-02 shape: full current schema EXCEPT this values
    # table, created old-style without the unique constraint, pre-seeded with
    # duplicates. Bare columns (no FK specs) so DDL compiles without needing
    # hospitals/indicators in this scratch metadata.
    old_shape = _sa.Table(
        "indicator_values", _sa.MetaData(),
        _sa.Column("id", _sa.Integer, primary_key=True),
        _sa.Column("hospital_id", _sa.Integer, nullable=False),
        _sa.Column("indicator_id", _sa.Integer, nullable=False),
        _sa.Column("month", _sa.String(7), nullable=False),
        _sa.Column("value", _sa.Float, nullable=True),
        _sa.Column("source_file", _sa.String(500), nullable=True),
        _sa.Column("created_at", _sa.DateTime),
    )
    try:
        hospital_table = Hospital.__table__
        indicator_table = Indicator.__table__
        hospital_table.create(bind=engine, checkfirst=True)
        indicator_table.create(bind=engine, checkfirst=True)
        old_shape.create(bind=engine, checkfirst=True)
        with engine.begin() as c:
            hosp_id = c.execute(hospital_table.insert().values(name="Mig Dup Test Hospital")).inserted_primary_key[0]
            i1 = c.execute(indicator_table.insert().values(code="mig.ind1", name="Mig Ind 1")).inserted_primary_key[0]
            # three duplicates for the same key + one distinct key that must survive too
            c.execute(_sa.text(
                "INSERT INTO indicator_values (hospital_id, indicator_id, month, value) "
                f"VALUES ({hosp_id}, {i1}, '2026-01', 1.0), ({hosp_id}, {i1}, '2026-01', 2.0), "
                f"({hosp_id}, {i1}, '2026-01', 3.0), ({hosp_id}, {i1}, '2026-02', 9.0)"
            ))

        # The DB is pre-head (old shape); stamp it at the previous revision so
        # only our migration (and nothing newer) runs, then upgrade to head.
        alembic_upgrader(db_url, stamp_first=True)

        with engine.connect() as c:
            rows = c.execute(_sa.text(
                "SELECT month, value FROM indicator_values ORDER BY month, value"
            )).fetchall()
            assert rows == [("2026-01", 3.0), ("2026-02", 9.0)], rows
            uqs = {u["name"] for u in inspect(engine).get_unique_constraints("indicator_values") if u["name"]}
            assert "uq_indicator_value_hosp_ind_month" in uqs
            # constraint actually blocks a new duplicate
            with pytest.raises(IntegrityError):
                c.execute(_sa.text(
                    f"INSERT INTO indicator_values (hospital_id, indicator_id, month, value) "
                    f"VALUES ({hosp_id}, {i1}, '2026-01', 42.0)"
                ))
                c.commit()
    finally:
        engine.dispose()


def test_migration_is_noop_on_fresh_head_db(tmp_path, alembic_upgrader):
    """A DB bootstrapped by create_all+stamp (constraint already present) must
    survive a plain stamp at previous head + upgrade to head without crashing
    or touching data."""
    db_url = f"sqlite:///{(tmp_path / 'us02_idem.db').as_posix()}"
    engine = create_engine(db_url)
    from app.database import Base
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        h = Hospital(name="Idempotent Migr Test Hospital")
        i = Indicator(code="idem.ind", name="Idem Ind")
        db.add_all([h, i])
        db.flush()
        db.add(IndicatorValue(hospital_id=h.id, indicator_id=i.id, month="2026-03", value=4.0))
        db.commit()
        hid, iid = h.id, i.id
        db.close()

        # act like the deployed bootstrap: stamped at the OLD head, then a
        # plain upgrade head — the dedup DELETE must not lose the sole row.
        alembic_upgrader(db_url, stamp_first=True)

        db2 = sessionmaker(bind=engine)()
        try:
            rows = db2.query(IndicatorValue).filter_by(
                hospital_id=hid, indicator_id=iid, month="2026-03"
            ).all()
            assert len(rows) == 1 and rows[0].value == 4.0
        finally:
            db2.close()
    finally:
        with contextlib.suppress(Exception):
            db.close()
        engine.dispose()


# ── Input path still behaves with the constraint in place ────────────────────

def test_excel_import_upsert_does_not_create_duplicates(db_session):
    h = Hospital(name="Parser Upsert Hospital")
    db_session.add(h)
    db_session.flush()
    records = [
        {"hospital_name": "Parser Upsert Hospital", "indicator_code": "2", "month": "2026-04", "value": 100.0},
        {"hospital_name": "Parser Upsert Hospital", "indicator_code": "2", "month": "2026-04", "value": 120.0},
    ]
    import_data_to_db(records, db_session, source_file="test_us02.xlsx")
    rows = db_session.query(IndicatorValue).filter_by(hospital_id=h.id, month="2026-04").all()
    assert len(rows) == 1
    assert rows[0].value == 120.0  # newest wins
    assert rows[0].source_file == "test_us02.xlsx"


def test_reupload_second_file_overwrites_not_duplicates(db_session):
    h = Hospital(name="Reupload Hospital")
    db_session.add(h)
    db_session.flush()
    rec = {"hospital_name": "Reupload Hospital", "indicator_code": "2", "month": "2026-05", "value": 50.0}
    import_data_to_db([rec], db_session, source_file="a.xlsx")
    rec2 = dict(rec, value=75.0)
    import_data_to_db([rec2], db_session, source_file="b.xlsx")
    rows = db_session.query(IndicatorValue).filter_by(hospital_id=h.id).all()
    assert len(rows) == 1
    assert rows[0].value == 75.0
    assert rows[0].source_file == "b.xlsx"
