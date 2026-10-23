"""Schema layer: models, migration revision, rate_config seeding, DB-over-builtin specs."""
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.engine.rate_config import (
    get_spec,
    invalidate_rate_specs_cache,
    load_rate_specs,
    zscore_specs,
)
from app.main import _ensure_required_columns
from app.models import Indicator, LayeredOutlierResult, RateConfig
from scripts.seed_indicators import seed_rate_config

OLD_SHAPE_INDICATORS = """
CREATE TABLE indicators (
    id INTEGER NOT NULL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(500) NOT NULL,
    parent_id INTEGER,
    level INTEGER,
    sort_order INTEGER,
    group_name VARCHAR(100),
    formula TEXT,
    default_weight FLOAT,
    requirement_type VARCHAR(10) NOT NULL DEFAULT 'Required'
)
"""


def test_indicator_layer_config_columns_exist_with_defaults():
    cols = Indicator.__table__.columns
    for name in ("indicator_type", "minimum_history_period", "outlier_method",
                 "historical_enabled", "peer_comparison_enabled"):
        assert name in cols, name
        # nullable so the startup self-heal path (skips NOT NULL) can add it
        assert cols[name].nullable is True, name
    assert cols["indicator_type"].default.arg == "count"
    assert cols["minimum_history_period"].default.arg == 3
    assert cols["outlier_method"].default.arg == "auto"
    assert cols["historical_enabled"].default.arg is True
    assert cols["peer_comparison_enabled"].default.arg is True


def test_new_indicator_row_gets_layer_config_defaults(db_session):
    ind = Indicator(code="test.layered.cfg", name="Layered Config Test")
    db_session.add(ind)
    db_session.flush()
    assert ind.indicator_type == "count"
    assert ind.minimum_history_period == 3
    assert ind.outlier_method == "auto"
    assert ind.historical_enabled is True
    assert ind.peer_comparison_enabled is True
    db_session.rollback()


def test_ensure_required_columns_heals_old_shape_indicators():
    """Old-shape indicators table stamped at head must gain the 5 new columns;
    the pre-existing row reads the server defaults (never NULL)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(OLD_SHAPE_INDICATORS)
            conn.exec_driver_sql(
                "INSERT INTO indicators (id, code, name, requirement_type) "
                "VALUES (1, '5', 'C-sections', 'Required')"
            )
        with pytest.raises(Exception, match="no such column"):
            with engine.connect() as conn:
                conn.execute(select(Indicator.indicator_type)).all()

        _ensure_required_columns(engine)

        from sqlalchemy import inspect as sa_inspect
        got = {c["name"] for c in sa_inspect(engine).get_columns("indicators")}
        for name in ("indicator_type", "minimum_history_period", "outlier_method",
                     "historical_enabled", "peer_comparison_enabled"):
            assert name in got, name
        with engine.connect() as conn:
            row = conn.execute(select(
                Indicator.indicator_type, Indicator.minimum_history_period,
                Indicator.outlier_method, Indicator.historical_enabled,
            )).first()
        assert row == ("count", 3, "auto", True)
        # idempotent: a second run must not raise
        _ensure_required_columns(engine)
    finally:
        engine.dispose()


def test_layered_outlier_results_columns_match_spec():
    cols = LayeredOutlierResult.__table__.columns
    expected = {
        "id", "hospital_id", "indicator_id", "analysis_code", "month",
        "raw_value", "previous_value", "numerator", "denominator", "rate",
        "previous_denominator", "denominator_change_percent",
        "historical_mean", "historical_median", "historical_std",
        "historical_z_score", "historical_change_percent",
        "raw_value_outlier_score", "rate_outlier_score", "historical_outlier_score",
        "volume_anomaly_score", "peer_outlier_score", "peer_mean", "peer_count",
        "outlier_level", "outlier_type", "outlier_method", "interpretation",
        "investigation_required", "investigation_route", "created_at",
    }
    assert set(cols.keys()) == expected
    assert cols["hospital_id"].nullable is False
    assert cols["analysis_code"].nullable is False
    assert cols["month"].nullable is False
    assert cols["indicator_id"].nullable is True
    names = {c.name for c in LayeredOutlierResult.__table_args__
             if c.__class__.__name__ == "UniqueConstraint"}
    assert names == {"uq_layered_hosp_code_month"}
    idx = {i.name for i in LayeredOutlierResult.__table__.indexes}
    assert {"ix_lr_hosp_month", "ix_lr_month_type"} <= idx


def test_layered_outlier_results_unique_key(db_session):
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-01", outlier_level="NONE",
                                        outlier_type="NORMAL"))
    db_session.flush()
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-01"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    # same analysis_code, different month/hospital is fine
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-02"))
    db_session.add(LayeredOutlierResult(hospital_id=2, analysis_code="5",
                                        month="2026-01"))
    db_session.flush()
    db_session.rollback()


def test_rate_config_columns_match_spec():
    cols = RateConfig.__table__.columns
    expected = {
        "id", "rate_code", "rate_name", "indicator_type", "numerator_codes",
        "denominator_codes", "rate_multiplier", "minimum_denominator",
        "minimum_history_period", "outlier_method", "historical_enabled",
        "peer_comparison_enabled", "is_active",
    }
    assert set(cols.keys()) == expected
    assert cols["rate_code"].nullable is False
    assert cols["minimum_denominator"].nullable is True  # NULL = guard dormant (§12)
    names = {c.name for c in RateConfig.__table_args__
             if c.__class__.__name__ == "UniqueConstraint"}
    assert names == {"uq_rate_config_code"}


def test_seed_rate_config_parity_with_zscore_slice(db_session):
    rows = {r.rate_code: r for r in db_session.query(RateConfig).all()}
    specs = zscore_specs()
    assert set(rows) == {s.rate_code for s in specs}   # seeded by conftest
    for spec in specs:
        row = rows[spec.rate_code]
        assert row.rate_name == spec.rate_name
        assert row.indicator_type == spec.indicator_type
        assert row.numerator_codes == list(spec.numerator_codes)
        assert row.denominator_codes == list(spec.denominator_codes)
        # Per-unit scaling (x100 %, x1,000 per-1,000, x100,000 per-100,000),
        # not the legacy flat 100.
        assert row.rate_multiplier == spec.rate_multiplier
        assert row.minimum_denominator is None      # dormant guard (§12)
        assert row.minimum_history_period == 3
        assert row.outlier_method == "auto"
        assert row.historical_enabled is True
        assert row.peer_comparison_enabled is True
        assert row.is_active is True


def test_seed_rate_config_is_idempotent(db_session):
    db_session.query(RateConfig).delete()
    db_session.commit()
    assert seed_rate_config(db_session) == 7
    assert seed_rate_config(db_session) == 0
    assert db_session.query(RateConfig).count() == 7


def test_load_rate_specs_falls_back_to_builtin_when_table_empty(db_session):
    db_session.query(RateConfig).delete()
    db_session.commit()
    invalidate_rate_specs_cache()
    specs = load_rate_specs(db_session)
    assert set(specs) == {s.rate_code for s in zscore_specs()}
    assert specs["rate_mmr"].denominator_codes == ("2",)  # zscore-slice value


def test_load_rate_specs_db_rows_override_builtin(db_session):
    invalidate_rate_specs_cache()
    row = db_session.query(RateConfig).filter_by(rate_code="rate_mmr").one()
    row.rate_multiplier = 100000
    row.minimum_denominator = 6
    db_session.commit()
    specs = load_rate_specs(db_session)
    assert specs["rate_mmr"].rate_multiplier == 100000.0
    assert specs["rate_mmr"].minimum_denominator == 6
    assert specs["rate_mmr"].unit == "per 100,000"      # inherited from builtin base
    assert specs["rate_mmr"].typical_pct == 1.0
    assert specs["rate_cs"].rate_multiplier == 100.0     # untouched row unchanged
    db_session.rollback()


def test_load_rate_specs_inactive_row_is_dropped(db_session):
    invalidate_rate_specs_cache()
    db_session.query(RateConfig).filter_by(rate_code="rate_nicu").one().is_active = False
    db_session.commit()
    specs = load_rate_specs(db_session)
    # An explicitly switched-off rate disappears from the current set — the
    # builtin base must not resurface as a silent default.
    assert "rate_nicu" not in specs
    assert "rate_cs" in specs
    db_session.rollback()
    invalidate_rate_specs_cache()


def test_load_rate_specs_caches_until_invalidated(db_session):
    invalidate_rate_specs_cache()
    first = load_rate_specs(db_session)
    db_session.query(RateConfig).filter_by(rate_code="rate_cs").one().rate_multiplier = 1
    db_session.commit()
    assert load_rate_specs(db_session) is first
    assert first["rate_cs"].rate_multiplier == 100.0
    invalidate_rate_specs_cache()
    assert load_rate_specs(db_session)["rate_cs"].rate_multiplier == 1.0
    db_session.rollback()


def test_get_spec_lookup_and_miss(db_session):
    invalidate_rate_specs_cache()
    spec = get_spec(db_session, "rate_cs")
    assert spec is not None and spec.rate_code == "rate_cs"
    assert get_spec(db_session, "no_such_rate") is None


def test_migration_revision_is_new_head():
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    from app.config import BASE_DIR
    script = ScriptDirectory.from_config(AlembicConfig(os.path.join(BASE_DIR, "alembic.ini")))
    assert script.get_current_head() == "b3c4d5e6f7a8"
    assert script.get_revision("b3c4d5e6f7a8").down_revision == "f7a8b9c0d1e2"
