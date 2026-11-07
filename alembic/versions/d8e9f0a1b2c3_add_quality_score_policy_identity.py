"""add quality score policy identity

D5 — a stored Quality Score records the policy identity (PolicySnapshot
digest) of the run that produced it, so a cached result can be attributed
without re-resolving a policy. Revisions record the identity moved between.

Additive and nullable only: legacy rows stay NULL, meaning "not recorded",
which is never treated as a different policy. No backfill is performed and no
existing value is rewritten. The upgrade is idempotent (safe when a database
was bootstrapped with ``create_all`` and stamped) and reversible.

Revision ID: d8e9f0a1b2c3
Revises: a1c2e3f4b5d6
"""
import sqlalchemy as sa

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None

_QUALITY = "quality_scores"
_REVISIONS = "quality_score_revisions"
_INDEX = "ix_quality_scores_policy_digest"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Hand-built/partial-schema databases (migration tests, reduced bootstrap)
    # may legitimately not have these tables yet. Guard on existence: when a
    # table IS present every required column/index change is still applied.
    tables = _tables()
    if _QUALITY in tables:
        quality_columns = _columns(_QUALITY)
        if "policy_digest" not in quality_columns:
            op.add_column(_QUALITY, sa.Column("policy_digest", sa.String(64),
                                              nullable=True))
        if _INDEX not in _indexes(_QUALITY):
            op.create_index(_INDEX, _QUALITY, ["policy_digest"])

    if _REVISIONS in tables:
        revision_columns = _columns(_REVISIONS)
        if "previous_policy_digest" not in revision_columns:
            op.add_column(_REVISIONS, sa.Column("previous_policy_digest",
                                                sa.String(64), nullable=True))
        if "new_policy_digest" not in revision_columns:
            op.add_column(_REVISIONS, sa.Column("new_policy_digest",
                                                sa.String(64), nullable=True))


def downgrade() -> None:
    tables = _tables()
    if _QUALITY in tables:
        if _INDEX in _indexes(_QUALITY):
            op.drop_index(_INDEX, table_name=_QUALITY)
        if "policy_digest" in _columns(_QUALITY):
            op.drop_column(_QUALITY, "policy_digest")

    if _REVISIONS in tables:
        revision_columns = _columns(_REVISIONS)
        if "new_policy_digest" in revision_columns:
            op.drop_column(_REVISIONS, "new_policy_digest")
        if "previous_policy_digest" in revision_columns:
            op.drop_column(_REVISIONS, "previous_policy_digest")
