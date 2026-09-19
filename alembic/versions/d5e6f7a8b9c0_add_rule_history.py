"""add rule_history table

Revision ID: d5e6f7a8b9c0
Revises: c4d8e9f0a1b2
Create Date: 2026-09-18
"""
import sqlalchemy as sa

from alembic import op

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d8e9f0a1b2'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'rule_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rule_code', sa.String(length=50), nullable=False, index=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('snapshot', sa.Text(), nullable=True),
        sa.Column('changed_fields', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_rule_history_rule_id', 'rule_history', ['rule_id'])
    op.create_index('ix_rule_history_created_at', 'rule_history', ['created_at'])

def downgrade():
    op.drop_table('rule_history')
