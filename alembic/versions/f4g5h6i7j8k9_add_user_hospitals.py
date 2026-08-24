"""add user_hospitals

Revision ID: f4g5h6i7j8k9
Revises: e2f3a4b5c6d7
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4g5h6i7j8k9'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'user_hospitals',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_index('ix_user_hospitals_user', 'user_hospitals', ['user_id'])
    op.create_index('ix_user_hospitals_hospital', 'user_hospitals', ['hospital_id'])

def downgrade():
    op.drop_table('user_hospitals')
