"""add indicator_default_config

Revision ID: b6c7d8e9f0a1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade():
    # NOTE: indicator_id/month columns use index=True, which already creates
    # ix_indicator_default_config_indicator_id / _month. A previous version of
    # this migration duplicated those names with op.create_index and always
    # failed ("index already exists"), leaving indicator_default_config missing
    # -- or, on non-transactional SQLite, an orphan empty table behind. Handle
    # both states so the table reliably ends up present.
    bind = op.get_bind()
    from sqlalchemy import inspect as _inspect
    if "indicator_default_config" in _inspect(bind).get_table_names():
        return
    op.create_table(
        'indicator_default_config',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('indicator_id', sa.Integer(), sa.ForeignKey('indicators.id'), nullable=False, index=True),
        sa.Column('month', sa.String(7), nullable=False, index=True),
        sa.Column('is_enabled', sa.Boolean(), default=True),
        sa.Column('weight_override', sa.Float(), nullable=True),
        sa.UniqueConstraint('indicator_id', 'month', name='uq_indicator_default_month'),
    )

def downgrade():
    op.drop_table('indicator_default_config')