"""add indicator groups + requirement_type

Revision ID: a9c8e7d6f5b4
Revises: d5e6f7a8b9c0
Create Date: 2026-09-28

Indicator Groups feature (design rev 2):
  * indicator_groups / indicator_group_members tables (bulk toggle macros;
    no stored is_enabled — state is derived from member config rows).
  * indicators.requirement_type with server_default='Required' so existing
    rows read as Required (behavior-preserving backfill) and the startup
    _ensure_required_columns() self-heal path can also add it safely.
"""
import sqlalchemy as sa
from alembic import op

revision = 'a9c8e7d6f5b4'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def _tables_exist(bind):
    from sqlalchemy import inspect
    names = set(inspect(bind).get_table_names())
    return "indicator_groups" in names, "indicator_group_members" in names


def upgrade():
    bind = op.get_bind()
    have_groups, have_members = _tables_exist(bind)
    # NOTE: on a FRESH database this chain does not create `indicators` — the
    # app bootstraps new DBs via Base.metadata.create_all + stamp head
    # (app/main.py run_alembic_upgrade). Alembic upgrades only run on
    # pre-existing DBs, where the table exists. Guard the column step anyway
    # (same idempotent style as b6c7d8e9f0a1) so a bare `upgrade head` on an
    # empty DB cannot crash.

    # Idempotent (mirrors b6c7d8e9f0a1): a partially-failed run must not
    # leave the feature half-created on retry.
    if not have_groups:
        op.create_table(
            'indicator_groups',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('scope_type', sa.String(length=20), nullable=False, server_default='all'),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True),
            sa.Column('month_from', sa.String(length=7), nullable=True),
            sa.Column('month_to', sa.String(length=7), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('name', name='uq_indicator_group_name'),
        )
        op.create_index('ix_indicator_groups_id', 'indicator_groups', ['id'])
        op.create_index('ix_indicator_groups_name', 'indicator_groups', ['name'])
        op.create_index('ix_indicator_groups_hospital_id', 'indicator_groups', ['hospital_id'])

    if not have_members:
        op.create_table(
            'indicator_group_members',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('indicator_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('indicator_id', sa.Integer(), sa.ForeignKey('indicators.id', ondelete='CASCADE'), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=True),
            sa.UniqueConstraint('group_id', 'indicator_id', name='uq_group_indicator'),
        )
        op.create_index('ix_indicator_group_members_id', 'indicator_group_members', ['id'])
        op.create_index('ix_indicator_group_members_group_id', 'indicator_group_members', ['group_id'])
        op.create_index('ix_indicator_group_members_indicator_id', 'indicator_group_members', ['indicator_id'])

    # requirement_type: server_default backfills existing rows at the SQL
    # level on PostgreSQL; SQLite needs the explicit UPDATE below.
    if "indicators" in sa.inspect(bind).get_table_names():
        existing_cols = {c["name"] for c in sa.inspect(bind).get_columns("indicators")}
        if "requirement_type" not in existing_cols:
            op.add_column(
                'indicators',
                sa.Column('requirement_type', sa.String(length=10), nullable=False,
                          server_default='Required'),
            )
            op.execute("UPDATE indicators SET requirement_type = 'Required' "
                       "WHERE requirement_type IS NULL OR requirement_type = ''")


def downgrade():
    bind = op.get_bind()
    if "indicators" in sa.inspect(bind).get_table_names():
        existing_cols = {c["name"] for c in sa.inspect(bind).get_columns("indicators")}
        if "requirement_type" in existing_cols:
            op.drop_column('indicators', 'requirement_type')
    have_groups, have_members = _tables_exist(bind)
    if have_members:
        op.drop_table('indicator_group_members')
    if have_groups:
        op.drop_table('indicator_groups')
