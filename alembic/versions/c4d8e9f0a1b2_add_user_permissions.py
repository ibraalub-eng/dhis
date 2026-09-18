"""add user_permissions

Revision ID: c4d8e9f0a1b2
Revises: b9c0d1e2f3a4
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d8e9f0a1b2'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'user_permissions',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission_id', sa.Integer(), sa.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_index('ix_user_permissions_user', 'user_permissions', ['user_id'])
    op.create_index('ix_user_permissions_permission', 'user_permissions', ['permission_id'])

def downgrade():
    op.drop_table('user_permissions')