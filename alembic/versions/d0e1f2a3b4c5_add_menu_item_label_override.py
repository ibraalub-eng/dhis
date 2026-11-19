"""Add a per-menu-item display name override.

Lets an admin rename a sidebar entry (the name shown for the screen) without
touching the fixed tab registry. NULL keeps the registry default, so the
column is nullable and existing rows are unaffected.

Revision ID: d0e1f2a3b4c5
Revises: b7c1d2e3f4a5
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None

TABLE = "menu_items"
COLUMN = "label_override"


def _columns() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade():
    columns = _columns()
    if not columns:
        return
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=100), nullable=True))


def downgrade():
    if COLUMN in _columns():
        op.drop_column(TABLE, COLUMN)
