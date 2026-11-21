"""Add an audit trail for raw Data Element clinical directions.

``indicators.global_direction`` is edited from the Data Element drawer; this
table records who changed it, when, and the value it replaced. Additive and
idempotent for databases bootstrapped with ``create_all`` and stamped.

Revision ID: f3a4b5c6d7e8
Revises: e7f8a9b0c1d2
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None

TABLE = "indicator_direction_history"


def _tables() -> set:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade():
    if TABLE in _tables():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indicator_id", sa.Integer(), nullable=True),
        sa.Column("indicator_code", sa.String(50), nullable=False),
        sa.Column("previous_value", sa.String(20), nullable=True),
        sa.Column("new_value", sa.String(20), nullable=True),
        sa.Column("changed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["indicator_id"], ["indicators.id"], ondelete="SET NULL"),
    )
    op.create_index(f"ix_{TABLE}_id", TABLE, ["id"])
    op.create_index(f"ix_{TABLE}_indicator_id", TABLE, ["indicator_id"])
    op.create_index(f"ix_{TABLE}_indicator_code", TABLE, ["indicator_code"])


def downgrade():
    if TABLE in _tables():
        op.drop_table(TABLE)
