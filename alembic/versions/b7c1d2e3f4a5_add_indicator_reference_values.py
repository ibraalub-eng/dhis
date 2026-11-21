"""Add the per-family indicator direction values.

Two nullable columns record the direction value for each benchmark family,
so one indicator can carry both its global and its local value. Both are
independent and optional: a left-empty field is stored as NULL.

Additive and nullable: existing definitions keep no value, no stored result
is rewritten, and the upgrade is idempotent for databases bootstrapped with
``create_all`` and stamped.

Revision ID: b7c1d2e3f4a5
Revises: d8e9f0a1b2c3
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "b7c1d2e3f4a5"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None

TABLE = "indicator_definitions"
COLUMNS = ("global_reference_value", "local_reference_value")


def _columns() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade():
    columns = _columns()
    if not columns:
        return
    for name in COLUMNS:
        if name not in columns:
            op.add_column(TABLE, sa.Column(name, sa.Float(), nullable=True))


def downgrade():
    columns = _columns()
    for name in COLUMNS:
        if name in columns:
            op.drop_column(TABLE, name)
