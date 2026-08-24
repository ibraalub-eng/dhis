"""add indicator_value created_at

Revision ID: d1a2b3c4e5f6
Revises: c3a1d5e7f920
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a2b3c4e5f6'
down_revision = 'c3a1d5e7f920'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('indicator_values', sa.Column('created_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('indicator_values', 'created_at')
