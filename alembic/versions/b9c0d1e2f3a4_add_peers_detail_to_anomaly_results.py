"""add peers_detail json column to anomaly_results

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("anomaly_results")}
    # Guarded add (idempotent if create_all already healed the column).
    # Nullable JSON: existing rows read as NULL = "computed before the
    # drill-down data was recorded".
    if "peers_detail" not in cols:
        op.add_column("anomaly_results", sa.Column("peers_detail", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("anomaly_results")}
    if "peers_detail" in cols:
        op.drop_column("anomaly_results", "peers_detail")
