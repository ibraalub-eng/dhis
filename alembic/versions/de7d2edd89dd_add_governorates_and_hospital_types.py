"""add governorates and hospital types

Revision ID: de7d2edd89dd
Revises: e43bebf7f9e0
Create Date: 2026-07-19 13:37:41.223208

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'de7d2edd89dd'
down_revision: Union[str, Sequence[str], None] = 'e43bebf7f9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('governorates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_governorates_name'), 'governorates', ['name'], unique=True)

    op.create_table('hospital_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_hospital_types_name'), 'hospital_types', ['name'], unique=True)

    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('governorate_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('hospital_type_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('address', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_hospitals_governorate', 'governorates', ['governorate_id'], ['id'])
        batch_op.create_foreign_key('fk_hospitals_type', 'hospital_types', ['hospital_type_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.drop_constraint('fk_hospitals_type', type_='foreignkey')
        batch_op.drop_constraint('fk_hospitals_governorate', type_='foreignkey')
        batch_op.drop_column('address')
        batch_op.drop_column('hospital_type_id')
        batch_op.drop_column('governorate_id')

    op.drop_index(op.f('ix_hospital_types_name'), table_name='hospital_types')
    op.drop_table('hospital_types')
    op.drop_index(op.f('ix_governorates_name'), table_name='governorates')
    op.drop_table('governorates')
