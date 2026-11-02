"""add layered classification provenance (zero-dispersion cap)

Revision ID: f5a6b7c8d9e0
Revises: c3d4e5f6a7b8
Create Date: 2026-10-25

A layer whose score was built by dividing by the spread cannot grade a
magnitude when that spread is 0 (every hospital reported the same value, or
the hospital's history is flat): the builders fall back to 1.0, so the layer
used to claim the top band. Outlier Diagnostics now caps such a layer's band at
HIGH — the same policy Quality Alerts already applies — and records which
layers were degenerate plus the band the raw scores alone implied.

Existing rows keep NULL (unknown, not wrong): that is what marks them for
recalculation, exactly like the other provenance columns. Idempotent and
reversible.
"""
import sqlalchemy as sa

from alembic import op

revision = 'f5a6b7c8d9e0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None

_TABLE = "layered_outlier_results"
_COLUMN = "classification_provenance"


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
    if not _has_column(bind, _TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
