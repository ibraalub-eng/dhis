"""Add a clinical direction per benchmark family.

The single ``direction`` column could not say that being high is bad globally
but acceptable locally (or the reverse). Each family now carries its own
direction: the global one governs every comparison, the local one governs the
local reference family only.

The old single direction is copied into both families once, so every existing
configuration keeps interpreting exactly as it did. Both columns are nullable
and the upgrade is idempotent for databases bootstrapped with ``create_all``
and stamped.

Revision ID: b2c3d4e5f6a7
Revises: a2b3c4d5e6f7
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

TABLE = "indicator_definitions"
COLUMNS = ("global_direction", "local_direction")


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
            op.add_column(TABLE, sa.Column(name, sa.String(20), nullable=True))
    if "direction" in columns:
        # The former single direction was the direction of both families.
        op.execute(sa.text(
            f"UPDATE {TABLE} "
            "SET global_direction = direction, local_direction = direction "
            "WHERE direction IS NOT NULL "
            "AND global_direction IS NULL AND local_direction IS NULL"
        ))


def downgrade():
    columns = _columns()
    for name in COLUMNS:
        if name in columns:
            op.drop_column(TABLE, name)
