"""Add a clinical direction to raw Data Elements.

Raw catalog elements are scanned as stored values and have no derived
definition, so a direction recorded on ``indicator_definitions`` can never
reach them. This column records that direction on the element itself.

Nullable and additive: an unset element stays NULL and the scan keeps falling
back to the clinical threshold table, so no stored alert changes on upgrade.
Idempotent for databases bootstrapped with ``create_all`` and stamped.

Revision ID: e7f8a9b0c1d2
Revises: b2c3d4e5f6a7
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

TABLE = "indicators"
COLUMN = "global_direction"


def _columns() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade():
    columns = _columns()
    if not columns or COLUMN in columns:
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(20), nullable=True))


def downgrade():
    if COLUMN in _columns():
        op.drop_column(TABLE, COLUMN)
