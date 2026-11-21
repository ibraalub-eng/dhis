"""Add the per-family indicator target ranges.

The single target range becomes one range per benchmark family, so each of
Target min and Target max exists twice: the global figure and the local one.
All four columns are nullable and independent — a family whose pair is not
recorded stays NULL and contributes no comparison.

The legacy target_min/target_max pair is kept (older rows and clients still
read it) and copied into the global family once, so a configured target does
not have to be re-entered after the upgrade.

Additive and nullable: no stored result is rewritten, and the upgrade is
idempotent for databases bootstrapped with ``create_all`` and stamped.

Revision ID: a2b3c4d5e6f7
Revises: d0e1f2a3b4c5
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None

TABLE = "indicator_definitions"
COLUMNS = (
    "global_target_min", "global_target_max",
    "local_target_min", "local_target_max",
)


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
    if {"target_min", "target_max"} <= columns:
        # The old single range was the global benchmark in all but name.
        op.execute(sa.text(
            f"UPDATE {TABLE} "
            "SET global_target_min = target_min, global_target_max = target_max "
            "WHERE global_target_min IS NULL AND global_target_max IS NULL "
            "AND target_min IS NOT NULL AND target_max IS NOT NULL"
        ))


def downgrade():
    columns = _columns()
    for name in COLUMNS:
        if name in columns:
            op.drop_column(TABLE, name)
