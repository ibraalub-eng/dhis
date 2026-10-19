"""Add scope and legacy identity to central indicator definitions.

Revision ID: e3f4a5b6c7d8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "c2d3e4f5a6b7"
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
    additions = (
        ("source_site", sa.String(length=20), True, None),
        ("legacy_code", sa.String(length=100), True, None),
        ("is_system", sa.Boolean(), False, sa.text("false")),
    )
    for name, column_type, nullable, server_default in additions:
        if name not in columns:
            op.add_column(
                "indicator_definitions",
                sa.Column(
                    name,
                    column_type,
                    nullable=nullable,
                    server_default=server_default,
                ),
            )
    indexes = {index["name"] for index in inspector.get_indexes("indicator_definitions")}
    for name, column in (
        ("ix_indicator_definitions_source_site", "source_site"),
        ("ix_indicator_definitions_legacy_code", "legacy_code"),
    ):
        if name not in indexes:
            op.create_index(name, "indicator_definitions", [column])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "indicator_definitions" not in inspector.get_table_names():
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("indicator_definitions")
    }
    indexes = {index["name"] for index in inspector.get_indexes("indicator_definitions")}
    for name in (
        "ix_indicator_definitions_legacy_code",
        "ix_indicator_definitions_source_site",
    ):
        if name in indexes:
            op.drop_index(name, table_name="indicator_definitions")
    for name in ("is_system", "legacy_code", "source_site"):
        if name in columns:
            op.drop_column("indicator_definitions", name)
