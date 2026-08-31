"""add session_logs table

Revision ID: a1b2c3d4e5f6
Revises: f4g5h6i7j8k9
Create Date: 2026-08-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f4g5h6i7j8k9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('session_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('event', sa.String(length=20), nullable=False),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_session_logs_id', 'session_logs', ['id'])
    op.create_index('ix_session_logs_created_at', 'session_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_session_logs_created_at', table_name='session_logs')
    op.drop_index('ix_session_logs_id', table_name='session_logs')
    op.drop_table('session_logs')
