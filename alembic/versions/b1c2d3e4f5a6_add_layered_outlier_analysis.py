"""add layered outlier analysis schema

Revision ID: b1c2d3e4f5a6
Revises: a9c8e7d6f5b4
Create Date: 2026-10-08

Layered Outlier Analysis (design spec 2026-10-08):
  * layered_outlier_results — one row per hospital x analysis unit x month,
    unique (hospital_id, analysis_code, month).
  * rate_config — rate definitions & layered-engine tuning rows; seeded from
    the registry zscore slice (seed_indicators.py::seed_rate_config).
  * indicators.{indicator_type,minimum_history_period,outlier_method,
    historical_enabled,peer_comparison_enabled} — count/raw-layer config.

Idempotent, same style as a9c8e7d6f5b4: fresh DBs bootstrap via
Base.metadata.create_all + stamp head, so a bare `upgrade head` on an
empty/partial DB must not crash or double-create. Boolean server defaults
use sa.text('true'/'false') — a QUOTED string default ('false') is stored
as text by SQLite and reads back as True through SQLAlchemy's Boolean
converter.
"""
import sqlalchemy as sa

from alembic import op

revision = 'b1c2d3e4f5a6'
down_revision = 'a9c8e7d6f5b4'
branch_labels = None
depends_on = None


def _table_state(bind, table):
    from sqlalchemy import inspect
    insp = inspect(bind)
    if table not in set(insp.get_table_names()):
        return False, set()
    return True, {c["name"] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()

    have_lor, _ = _table_state(bind, "layered_outlier_results")
    if not have_lor:
        op.create_table(
            'layered_outlier_results',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('indicator_id', sa.Integer(), sa.ForeignKey('indicators.id'), nullable=True),
            sa.Column('analysis_code', sa.String(length=50), nullable=False),
            sa.Column('month', sa.String(length=7), nullable=False),
            sa.Column('raw_value', sa.Float(), nullable=True),
            sa.Column('previous_value', sa.Float(), nullable=True),
            sa.Column('numerator', sa.Float(), nullable=True),
            sa.Column('denominator', sa.Float(), nullable=True),
            sa.Column('rate', sa.Float(), nullable=True),
            sa.Column('previous_denominator', sa.Float(), nullable=True),
            sa.Column('denominator_change_percent', sa.Float(), nullable=True),
            sa.Column('historical_mean', sa.Float(), nullable=True),
            sa.Column('historical_median', sa.Float(), nullable=True),
            sa.Column('historical_std', sa.Float(), nullable=True),
            sa.Column('historical_z_score', sa.Float(), nullable=True),
            sa.Column('historical_change_percent', sa.Float(), nullable=True),
            sa.Column('raw_value_outlier_score', sa.Float(), nullable=True),
            sa.Column('rate_outlier_score', sa.Float(), nullable=True),
            sa.Column('historical_outlier_score', sa.Float(), nullable=True),
            sa.Column('volume_anomaly_score', sa.Float(), nullable=True),
            sa.Column('peer_outlier_score', sa.Float(), nullable=True),
            sa.Column('peer_mean', sa.Float(), nullable=True),
            sa.Column('peer_count', sa.Integer(), nullable=True),
            sa.Column('outlier_level', sa.String(length=20), nullable=True),
            sa.Column('outlier_type', sa.String(length=40), nullable=True),
            sa.Column('outlier_method', sa.String(length=30), nullable=True),
            sa.Column('interpretation', sa.Text(), nullable=True),
            sa.Column('investigation_required', sa.Boolean(), nullable=True,
                      server_default=sa.text('false')),
            sa.Column('investigation_route', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('hospital_id', 'analysis_code', 'month',
                                name='uq_layered_hosp_code_month'),
        )
        op.create_index('ix_layered_outlier_results_id', 'layered_outlier_results', ['id'])
        op.create_index('ix_layered_outlier_results_hospital_id', 'layered_outlier_results', ['hospital_id'])
        op.create_index('ix_layered_outlier_results_analysis_code', 'layered_outlier_results', ['analysis_code'])
        op.create_index('ix_layered_outlier_results_month', 'layered_outlier_results', ['month'])
        op.create_index('ix_lr_hosp_month', 'layered_outlier_results', ['hospital_id', 'month'])
        op.create_index('ix_lr_month_type', 'layered_outlier_results', ['month', 'outlier_type'])

    have_rc, _ = _table_state(bind, "rate_config")
    if not have_rc:
        op.create_table(
            'rate_config',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('rate_code', sa.String(length=50), nullable=False),
            sa.Column('rate_name', sa.String(length=200), nullable=True),
            sa.Column('indicator_type', sa.String(length=20), nullable=True),
            sa.Column('numerator_codes', sa.JSON(), nullable=True),
            sa.Column('denominator_codes', sa.JSON(), nullable=True),
            sa.Column('rate_multiplier', sa.Integer(), nullable=True),
            sa.Column('minimum_denominator', sa.Integer(), nullable=True),
            sa.Column('minimum_history_period', sa.Integer(), nullable=True,
                      server_default='3'),
            sa.Column('outlier_method', sa.String(length=30), nullable=True,
                      server_default='auto'),
            sa.Column('historical_enabled', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.Column('peer_comparison_enabled', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.Column('is_active', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.UniqueConstraint('rate_code', name='uq_rate_config_code'),
        )
        op.create_index('ix_rate_config_id', 'rate_config', ['id'])
        op.create_index('ix_rate_config_rate_code', 'rate_config', ['rate_code'])

    have_ind, ind_cols = _table_state(bind, "indicators")
    if have_ind:
        new_cols = {
            "indicator_type": sa.Column('indicator_type', sa.String(length=20),
                                        nullable=True, server_default='count'),
            "minimum_history_period": sa.Column('minimum_history_period', sa.Integer(),
                                                nullable=True, server_default='3'),
            "outlier_method": sa.Column('outlier_method', sa.String(length=30),
                                        nullable=True, server_default='auto'),
            "historical_enabled": sa.Column('historical_enabled', sa.Boolean(),
                                            nullable=True, server_default=sa.text('true')),
            "peer_comparison_enabled": sa.Column('peer_comparison_enabled', sa.Boolean(),
                                                 nullable=True, server_default=sa.text('true')),
        }
        for name, col in new_cols.items():
            if name not in ind_cols:
                op.add_column('indicators', col)


def downgrade():
    bind = op.get_bind()
    have_ind, ind_cols = _table_state(bind, "indicators")
    if have_ind:
        for name in ("peer_comparison_enabled", "historical_enabled", "outlier_method",
                     "minimum_history_period", "indicator_type"):
            if name in ind_cols:
                op.drop_column('indicators', name)
    have_rc, _ = _table_state(bind, "rate_config")
    if have_rc:
        op.drop_table('rate_config')
    have_lor, _ = _table_state(bind, "layered_outlier_results")
    if have_lor:
        op.drop_table('layered_outlier_results')
