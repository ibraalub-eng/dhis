"""Add the indicator rounding setting for databases already at the prior head.

Revision ID: c2d3e4f5a6b7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "indicator_definitions" not in inspector.get_table_names():
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("indicator_definitions")
    }
    if "rounding" not in columns:
        op.add_column(
            "indicator_definitions",
            sa.Column(
                "rounding",
                sa.String(length=10),
                nullable=False,
                server_default="half_up",
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "indicator_definitions" not in inspector.get_table_names():
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("indicator_definitions")
    }
    if "rounding" in columns:
        op.drop_column("indicator_definitions", "rounding")
