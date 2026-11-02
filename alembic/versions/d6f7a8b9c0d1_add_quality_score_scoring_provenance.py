"""add QualityScore scoring provenance + revision history

Revision ID: d6f7a8b9c0d1
Revises: c9d0e1f2a3b4
Create Date: 2026-10-24

A stored Quality Score must be reproducible: each row now records the
configuration fingerprint that produced it (and the resolved configuration
itself, so an old digest stays explainable after AppConfig changes), and every
overwrite of an existing row appends to ``quality_score_revisions`` before the
values are replaced.

Existing rows keep NULL provenance. That is deliberate: they were computed
before the configuration was recorded, and the audit reports them as unknown
rather than assuming they are wrong.

Idempotent like the other migrations: fresh databases bootstrap via
``Base.metadata.create_all`` + stamp head, so ``upgrade head`` must not crash
when the columns/table already exist.
"""
import sqlalchemy as sa

from alembic import op

revision = 'd6f7a8b9c0d1'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None

_SCORE_TABLE = "quality_scores"
_REVISION_TABLE = "quality_score_revisions"
_SCORE_INDEX = "ix_quality_scores_scoring_fingerprint"


def _has_table(bind, table):
    from sqlalchemy import inspect
    return table in set(inspect(bind).get_table_names())


def _has_column(bind, table, column):
    from sqlalchemy import inspect
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def _has_index(bind, table, name):
    from sqlalchemy import inspect
    return name in {i["name"] for i in inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    if _has_table(bind, _SCORE_TABLE):
        if not _has_column(bind, _SCORE_TABLE, "scoring_fingerprint"):
            op.add_column(_SCORE_TABLE,
                          sa.Column("scoring_fingerprint", sa.String(length=32),
                                    nullable=True))
        if not _has_column(bind, _SCORE_TABLE, "scoring_config"):
            op.add_column(_SCORE_TABLE,
                          sa.Column("scoring_config", sa.JSON(), nullable=True))
        if not _has_index(bind, _SCORE_TABLE, _SCORE_INDEX):
            op.create_index(_SCORE_INDEX, _SCORE_TABLE,
                            ["scoring_fingerprint"], unique=False)

    if not _has_table(bind, _REVISION_TABLE):
        op.create_table(
            _REVISION_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('hospital_id', sa.Integer(),
                      sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('month', sa.String(length=7), nullable=False),
            sa.Column('action', sa.String(length=40), nullable=False),
            sa.Column('actor', sa.String(length=120), nullable=False),
            sa.Column('previous_score', sa.Float(), nullable=True),
            sa.Column('new_score', sa.Float(), nullable=True),
            sa.Column('previous_fingerprint', sa.String(length=32), nullable=True),
            sa.Column('new_fingerprint', sa.String(length=32), nullable=True),
            sa.Column('previous_values', sa.JSON(), nullable=True),
            sa.Column('new_values', sa.JSON(), nullable=True),
            sa.Column('config', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index("ix_quality_score_revisions_id",
                        _REVISION_TABLE, ['id'], unique=False)
        op.create_index("ix_quality_score_revisions_hospital_id",
                        _REVISION_TABLE, ['hospital_id'], unique=False)
        op.create_index("ix_quality_score_revisions_month",
                        _REVISION_TABLE, ['month'], unique=False)
        op.create_index("ix_quality_score_revisions_action",
                        _REVISION_TABLE, ['action'], unique=False)
        op.create_index("ix_quality_score_revisions_created_at",
                        _REVISION_TABLE, ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    if _has_table(bind, _REVISION_TABLE):
        existing = {idx["name"] for idx in
                    sa.inspect(bind).get_indexes(_REVISION_TABLE)}
        for name in ("ix_quality_score_revisions_id",
                     "ix_quality_score_revisions_hospital_id",
                     "ix_quality_score_revisions_month",
                     "ix_quality_score_revisions_action",
                     "ix_quality_score_revisions_created_at"):
            if name in existing:
                op.drop_index(name, table_name=_REVISION_TABLE)
        op.drop_table(_REVISION_TABLE)
    if _has_table(bind, _SCORE_TABLE):
        if _has_index(bind, _SCORE_TABLE, _SCORE_INDEX):
            op.drop_index(_SCORE_INDEX, table_name=_SCORE_TABLE)
        for column in ("scoring_config", "scoring_fingerprint"):
            if _has_column(bind, _SCORE_TABLE, column):
                op.drop_column(_SCORE_TABLE, column)
