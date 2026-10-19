"""add indicator_definitions / indicator_definition_versions / indicator_results

Revision ID: d7e8f9a0b1c2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-18

Indicators-management feature: managed DERIVED indicators computed from
existing raw IndicatorValue rows.

Design invariants enforced by this schema (2026-10-18 design):

* Nothing here touches ``indicators`` or ``indicator_values`` — raw-data
  import, completeness, Data Tree and every existing dashboard stay
  byte-identical. Derived results live in their own ``indicator_results``
  table.
* ``indicator_definition_versions`` stores a full JSON snapshot per change
  (RuleHistory pattern): definition_id is SET NULL on deletion so the
  audit trail outlives the definition, definition_code keeps it queryable.
* ``indicator_results.definition_version`` stamps which formula version
  produced each row, so an edit never silently rewrites historical
  results — stale rows are flagged until an explicit recompute.

Idempotent in the house style: _ensure_all_tables() (create_all checkfirst)
runs BEFORE migrations at startup, so every CREATE is guarded by an
inspector check — a table already created from the models is left alone
and alembic simply records the revision.
"""
import sqlalchemy as sa

from alembic import op

revision = 'd7e8f9a0b1c2'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    from sqlalchemy import inspect as _inspect
    existing = _inspect(bind).get_table_names()

    if "indicator_definitions" not in existing:
        op.create_table(
            'indicator_definitions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('code', sa.String(50), nullable=False, index=True),
            sa.Column('name', sa.String(500), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('group_name', sa.String(100), nullable=True),
            sa.Column('formula_type', sa.String(20), nullable=False,
                      server_default='ratio'),
            sa.Column('expression', sa.Text(), nullable=True),
            sa.Column('numerator_codes', sa.JSON(), nullable=True),
            sa.Column('denominator_codes', sa.JSON(), nullable=True),
            sa.Column('operator', sa.String(3), nullable=False,
                      server_default='/'),
            sa.Column('multiplier', sa.Float(), nullable=False,
                      server_default='1.0'),
            sa.Column('aggregation', sa.String(10), nullable=False,
                      server_default='sum'),
            sa.Column('result_type', sa.String(20), nullable=False,
                      server_default='percentage'),
            sa.Column('unit', sa.String(30), nullable=True),
            sa.Column('precision', sa.Integer(), nullable=True),
            sa.Column('rounding', sa.String(10), nullable=False,
                      server_default='half_up'),
            sa.Column('direction', sa.String(20), nullable=True),
            sa.Column('threshold_low', sa.Float(), nullable=True),
            sa.Column('threshold_high', sa.Float(), nullable=True),
            sa.Column('target_min', sa.Float(), nullable=True),
            sa.Column('target_max', sa.Float(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False,
                      server_default=sa.text("true")),
            sa.Column('version', sa.Integer(), nullable=False,
                      server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('code', name='uq_indicator_definition_code'),
        )

    if "indicator_definition_versions" not in existing:
        op.create_table(
            'indicator_definition_versions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('definition_id', sa.Integer(),
                      sa.ForeignKey('indicator_definitions.id',
                                    ondelete='SET NULL'),
                      nullable=True, index=True),
            sa.Column('definition_code', sa.String(50), nullable=False,
                      index=True),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(20), nullable=False),
            sa.Column('snapshot', sa.Text(), nullable=False),
            sa.Column('changed_fields', sa.Text(), nullable=True),
            sa.Column('changed_by', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

    if "indicator_results" not in existing:
        op.create_table(
            'indicator_results',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('definition_id', sa.Integer(),
                      sa.ForeignKey('indicator_definitions.id',
                                    ondelete='CASCADE'),
                      nullable=True, index=True),
            sa.Column('definition_code', sa.String(50), nullable=False,
                      index=True),
            sa.Column('hospital_id', sa.Integer(),
                      sa.ForeignKey('hospitals.id'), nullable=False,
                      index=True),
            sa.Column('month', sa.String(7), nullable=False, index=True),
            sa.Column('value', sa.Float(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False,
                      server_default='ok'),
            sa.Column('numerator', sa.Float(), nullable=True),
            sa.Column('denominator', sa.Float(), nullable=True),
            sa.Column('inputs', sa.Text(), nullable=True),
            sa.Column('definition_version', sa.Integer(), nullable=False,
                      server_default='1'),
            sa.Column('computed_at', sa.DateTime(), nullable=True),
            sa.Index('ix_ir_hosp_month', 'hospital_id', 'month'),
            sa.UniqueConstraint('definition_id', 'hospital_id', 'month',
                                name='uq_indicator_result_def_hosp_month'),
        )

    # Column-level guard: create_all may have created indicator_definitions
    # from an EARLIER version of the models (before precision/rounding
    # existed) — the table-level check above would then skip it forever.
    # Add any missing precision/rounding columns idempotently.
    if "indicator_definitions" in existing:
        cols = {c["name"] for c in _inspect(bind).get_columns("indicator_definitions")}
        if "precision" not in cols:
            op.add_column("indicator_definitions",
                          sa.Column("precision", sa.Integer(), nullable=True))
        if "rounding" not in cols:
            op.add_column("indicator_definitions",
                          sa.Column("rounding", sa.String(10), nullable=False,
                                    server_default="half_up"))


def downgrade():
    bind = op.get_bind()
    from sqlalchemy import inspect as _inspect
    existing = _inspect(bind).get_table_names()
    for table in ("indicator_results",
                  "indicator_definition_versions",
                  "indicator_definitions"):
        if table in existing:
            op.drop_table(table)
