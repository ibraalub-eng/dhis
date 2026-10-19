"""Add formula provenance to stored anomaly results.

Revision ID: f1a2b3c4d5e6
Revises: d7e8f9a0b1c2
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "anomaly_results" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("anomaly_results")}
    for name, column_type in (
        ("indicator_id", sa.String(length=100)),
        ("formula", sa.Text()),
        ("formula_version", sa.String(length=100)),
    ):
        if name not in columns:
            op.add_column("anomaly_results", sa.Column(name, column_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "anomaly_results" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("anomaly_results")}
    for name in ("formula_version", "formula", "indicator_id"):
        if name in columns:
            op.drop_column("anomaly_results", name)
