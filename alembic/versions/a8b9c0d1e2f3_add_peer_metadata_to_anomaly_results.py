"""add peer metadata columns to anomaly_results

Revision ID: a8b9c0d1e2f3
Revises: c7d8e9f0a2b3
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'a8b9c0d1e2f3'
down_revision = 'c7d8e9f0a2b3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("anomaly_results")}
    # Guarded adds so the migration is idempotent for DBs already healed by
    # create_all (new columns are nullable, so existing rows read as NULL =
    # "computed before peer metadata existed").
    for name, col in [
        ("peer_count", sa.Column("peer_count", sa.Integer(), nullable=True)),
        ("peer_std", sa.Column("peer_std", sa.Float(), nullable=True)),
        ("peer_min", sa.Column("peer_min", sa.Float(), nullable=True)),
        ("peer_max", sa.Column("peer_max", sa.Float(), nullable=True)),
        ("peer_median", sa.Column("peer_median", sa.Float(), nullable=True)),
    ]:
        if name not in cols:
            op.add_column("anomaly_results", col)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("anomaly_results")}
    for name in ("peer_median", "peer_max", "peer_min", "peer_std", "peer_count"):
        if name in cols:
            op.drop_column("anomaly_results", name)
