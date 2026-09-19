"""add agent tables

Revision ID: e9f0a1b2c3d4
Revises: d5e6f7a8b9c0
Create Date: 2026-09-19
"""
import sqlalchemy as sa

from alembic import op

revision = 'e9f0a1b2c3d4'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('lang', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_id', 'conversations', ['id'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])

    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('message_type', sa.String(length=10), nullable=False),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_steps', sa.JSON(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_messages_id', 'messages', ['id'])
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_msg_conv_created', 'messages', ['conversation_id', 'created_at'])

    op.create_table(
        'agent_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent', sa.String(length=30), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('steps', sa.Integer(), nullable=False),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('tokens', sa.JSON(), nullable=True),
        sa.Column('data_version', sa.String(length=40), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('cache_hit', sa.Boolean(), nullable=False),
        sa.Column('fallback_used', sa.Boolean(), nullable=False),
        sa.Column('hospital_scope_hash', sa.String(length=64), nullable=True),
        sa.Column('permission_scope_hash', sa.String(length=64), nullable=True),
        sa.Column('prompt_hash', sa.String(length=64), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_runs_id', 'agent_runs', ['id'])
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'])
    op.create_index('ix_agent_runs_created', 'agent_runs', ['created_at'])
    op.create_index('ix_agent_runs_user_created', 'agent_runs', ['user_id', 'created_at'])

    op.create_table(
        'agent_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(length=200), nullable=False),
        sa.Column('result_json', sa.Text(), nullable=False),
        sa.Column('data_version', sa.String(length=40), nullable=True),
        sa.Column('hospital_scope_hash', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cache_key', name='uq_agent_cache_cache_key'),
    )
    op.create_index('ix_agent_cache_id', 'agent_cache', ['id'])
    op.create_index('ix_agent_cache_cache_key', 'agent_cache', ['cache_key'])

    op.create_table(
        'agent_data_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospital_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hospital_id', 'month', name='uq_agent_dv_hosp_month'),
    )
    op.create_index('ix_agent_data_versions_id', 'agent_data_versions', ['id'])
    op.create_index('ix_agent_data_versions_hospital_id', 'agent_data_versions', ['hospital_id'])

def downgrade():
    op.drop_index('ix_agent_data_versions_hospital_id', table_name='agent_data_versions')
    op.drop_index('ix_agent_data_versions_id', table_name='agent_data_versions')
    op.drop_table('agent_data_versions')
    op.drop_index('ix_agent_cache_cache_key', table_name='agent_cache')
    op.drop_index('ix_agent_cache_id', table_name='agent_cache')
    op.drop_table('agent_cache')
    op.drop_index('ix_agent_runs_user_created', table_name='agent_runs')
    op.drop_index('ix_agent_runs_created', table_name='agent_runs')
    op.drop_index('ix_agent_runs_user_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_id', table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index('ix_msg_conv_created', table_name='messages')
    op.drop_index('ix_messages_conversation_id', table_name='messages')
    op.drop_index('ix_messages_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_index('ix_conversations_id', table_name='conversations')
    op.drop_table('conversations')