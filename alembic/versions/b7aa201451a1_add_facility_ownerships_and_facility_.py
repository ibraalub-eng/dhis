"""add facility ownerships and facility types

Revision ID: b7aa201451a1
Revises: de7d2edd89dd
Create Date: 2026-07-20 13:08:48.098789

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7aa201451a1'
down_revision: Union[str, Sequence[str], None] = 'de7d2edd89dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('facility_ownerships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table('facility_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organisation_unit_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('facility_ownership_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('facility_type_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_hospitals_facility_ownership', 'facility_ownerships', ['facility_ownership_id'], ['id'])
        batch_op.create_foreign_key('fk_hospitals_facility_type', 'facility_types', ['facility_type_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('hospitals', schema=None) as batch_op:
        batch_op.drop_constraint('fk_hospitals_facility_type', type_='foreignkey')
        batch_op.drop_constraint('fk_hospitals_facility_ownership', type_='foreignkey')
        batch_op.drop_column('facility_type_id')
        batch_op.drop_column('facility_ownership_id')
        batch_op.drop_column('organisation_unit_id')

    op.drop_table('facility_types')
    op.drop_table('facility_ownerships')
