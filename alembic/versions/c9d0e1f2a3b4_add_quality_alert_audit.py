"""add quality_alert_audit (durable record of batch alert recomputes)

Revision ID: c9d0e1f2a3b4
Revises: b3c4d5e6f7a8
Create Date: 2026-10-23

A stale-policy recompute rewrites many stored Quality Alerts at once. The
per-alert ``quality_alert_events`` trail cannot express "who rescanned which
months", so this append-only table records the actor, the affected months and
the per-scope counters produced by the run.

Idempotent like the other migrations: fresh databases bootstrap via
``Base.metadata.create_all`` + stamp head, so ``upgrade head`` must not crash
when the table (and its indexes) already exist.
"""
import sqlalchemy as sa

from alembic import op

revision = 'c9d0e1f2a3b4'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None

_TABLE = "quality_alert_audit"
_INDEXES = (
    "ix_quality_alert_audit_id",
    "ix_quality_alert_audit_action",
    "ix_quality_alert_audit_created_at",
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
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('actor', sa.String(length=120), nullable=False),
        sa.Column('months', sa.JSON(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(_INDEXES[0], _TABLE, ['id'], unique=False)
    op.create_index(_INDEXES[1], _TABLE, ['action'], unique=False)
    op.create_index(_INDEXES[2], _TABLE, ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(_TABLE)}
    for name in _INDEXES:
        if name in existing:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
