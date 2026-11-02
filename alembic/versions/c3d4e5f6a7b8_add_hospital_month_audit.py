"""add hospital_month_audit (who enabled/disabled a hospital month, when)

Revision ID: c3d4e5f6a7b8
Revises: e1f2a3b4c5d6
Create Date: 2026-10-24

A month switched off for one hospital changes what every analysis screen
shows, but the ``month_enabled_<hospital>_<YYYY-MM>`` SystemSetting only kept
the latest value. This append-only table records one row per real change: the
hospital and month, the resulting state, the previous state (``unset`` when no
setting existed, i.e. enabled by default), the acting user and the timestamp.

The hospital/user names are snapshotted and ``hospital_id`` is SET NULL on
delete, so the trail outlives its subjects. Rows are never updated or deleted
by the application.

Idempotent like the other migrations: fresh databases bootstrap via
``Base.metadata.create_all`` + stamp head, so ``upgrade head`` must not crash
when the table (and its indexes) already exist.
"""
import sqlalchemy as sa

from alembic import op

revision = 'c3d4e5f6a7b8'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None

_TABLE = "hospital_month_audit"
_FKS = ("fk_hospital_month_audit_hospital_id",)
_INDEXES = (
    "ix_hospital_month_audit_id",
    "ix_hospital_month_audit_hospital_id",
    "ix_hospital_month_audit_month",
    "ix_hospital_month_audit_created_at",
)


def _has_table(bind, table):
    from sqlalchemy import inspect
    return table in set(inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    if _has_table(bind, _TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('hospital_id', sa.Integer(), nullable=True),
        sa.Column('hospital_name', sa.String(length=500), nullable=True),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('previous_state', sa.String(length=10), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                                name=_FKS[0], ondelete='SET NULL'),
    )
    op.create_index(_INDEXES[0], _TABLE, ['id'], unique=False)
    op.create_index(_INDEXES[1], _TABLE, ['hospital_id'], unique=False)
    op.create_index(_INDEXES[2], _TABLE, ['month'], unique=False)
    op.create_index(_INDEXES[3], _TABLE, ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(_TABLE)}
    for name in _INDEXES:
        if name in existing:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
