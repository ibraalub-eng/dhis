"""add layered outlier comparison provenance

Revision ID: e1f2a3b4c5d6
Revises: d6f7a8b9c0d1
Create Date: 2026-10-24

Anomaly Diagnostics must be reproducible: each stored row now records the
exact hospital-history window/observations behind its historical score and the
exact peer group (ids + values) behind its peer score. Existing rows keep NULL
(unknown provenance, not wrong). Idempotent and reversible.
"""
import sqlalchemy as sa

from alembic import op

revision = 'e1f2a3b4c5d6'
down_revision = 'd6f7a8b9c0d1'
branch_labels = None
depends_on = None

_TABLE = "layered_outlier_results"
_COLUMNS = ("history_provenance", "peer_provenance")


def _has_table(bind, table):
    from sqlalchemy import inspect
    return table in set(inspect(bind).get_table_names())


def _has_column(bind, table, column):
    from sqlalchemy import inspect
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    for column in _COLUMNS:
        if not _has_column(bind, _TABLE, column):
            op.add_column(_TABLE, sa.Column(column, sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    for column in reversed(_COLUMNS):
        if _has_column(bind, _TABLE, column):
            op.drop_column(_TABLE, column)
