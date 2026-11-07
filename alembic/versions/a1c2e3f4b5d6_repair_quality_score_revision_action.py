"""repair legacy quality_score_revisions shape

Revision ID: a1c2e3f4b5d6
Revises: f5a6b7c8d9e0
Create Date: 2026-10-27

``d6f7a8b9c0d1`` creates ``quality_score_revisions`` only when the table is
absent, and some databases already had it from an older shape whose column was
``reason`` (not ``action``, and NOT NULL with no default). On those databases
``upgrade head`` reported the revision as applied while the table still did not
match the model, so every analysis that overwrote a stored Quality Score raised
``UndefinedColumn: action`` — and the whole analysis fell back, leaving the
Outlier Diagnostics rows stale.

This revision closes that gap the same idempotent way the other migrations do:
add the missing ``action`` column (backfilling it from ``reason`` on any legacy
rows, so old history still says what it did), drop the NOT NULL that would
reject the model's inserts, and add the missing index. A database already at the
correct shape is left untouched.
"""
import sqlalchemy as sa

from alembic import op

revision = 'a1c2e3f4b5d6'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None

_TABLE = "quality_score_revisions"
_ACTION_INDEX = "ix_quality_score_revisions_action"
_LEGACY_ACTION_COLUMN = "reason"


def _has_table(bind, table):
    from sqlalchemy import inspect
    return table in set(inspect(bind).get_table_names())


def _columns(bind, table):
    from sqlalchemy import inspect
    return {c["name"]: c for c in inspect(bind).get_columns(table)}


def _has_index(bind, table, name):
    from sqlalchemy import inspect
    return name in {i["name"] for i in inspect(bind).get_indexes(table)}


def _fk_targets_present(bind, table):
    """False when a referenced table is absent (a partial/synthetic database).

    ``batch_alter_table`` reflects the table together with its foreign keys,
    and reflection resolves the referenced tables *transitively*: rebuilding
    ``quality_score_revisions`` reflects ``hospitals``, whose own foreign key
    points at ``governorates``. Checking only the direct targets therefore
    still raised ``NoSuchTableError: governorates`` on a partial schema. Walk
    the whole reachable FK closure (cycle-safe) so any missing table in it
    skips the repair, exactly as intended, instead of failing the upgrade.

    A real database has the full closure, so the repair runs unchanged there;
    a partial one cannot be rebuilt safely and is skipped rather than guessed
    at.
    """
    from sqlalchemy import inspect
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    seen = set()
    pending = [table]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for fk in inspector.get_foreign_keys(current):
            target = fk.get("referred_table")
            if not target:
                continue
            if target not in tables:
                return False
            pending.append(target)
    return True


def upgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    columns = _columns(bind, _TABLE)

    if "action" not in columns:
        op.add_column(_TABLE,
                      sa.Column("action", sa.String(length=40), nullable=True))
        if _LEGACY_ACTION_COLUMN in columns:
            # The old column held the same thing: what produced the revision.
            op.execute(
                f"UPDATE {_TABLE} SET action = {_LEGACY_ACTION_COLUMN} "
                f"WHERE action IS NULL"
            )

    # NOT NULL only once nothing is missing it, so a legacy table with rows
    # whose action cannot be recovered stays insertable rather than half-migrated.
    remaining = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE action IS NULL")
    ).scalar()
    # SQLite cannot ALTER COLUMN in place, so these shape repairs go through
    # ``batch_alter_table``: PostgreSQL issues the same plain ALTER TABLE, while
    # SQLite recreates the table and copies its rows. The schema result is
    # identical on both dialects; only the mechanism differs.
    alterations = []
    if not remaining:
        alterations.append(("action", sa.String(length=40), False))
    if "actor" in columns and not columns["actor"]["nullable"]:
        alterations.append(("actor", sa.String(length=120), True))
    # The model no longer writes `reason`, but a legacy NOT NULL there would
    # reject every insert; relax it instead of dropping the old column, so the
    # text it holds stays readable.
    if (_LEGACY_ACTION_COLUMN in columns
            and not columns[_LEGACY_ACTION_COLUMN]["nullable"]):
        alterations.append((_LEGACY_ACTION_COLUMN, sa.String(length=60), True))
    if alterations and _fk_targets_present(bind, _TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            for name, existing_type, nullable in alterations:
                batch.alter_column(name, existing_type=existing_type,
                                   nullable=nullable)

    if not _has_index(bind, _TABLE, _ACTION_INDEX):
        op.create_index(_ACTION_INDEX, _TABLE, ["action"], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if _has_index(bind, _TABLE, _ACTION_INDEX):
        op.drop_index(_ACTION_INDEX, table_name=_TABLE)
    if "action" in _columns(bind, _TABLE):
        op.drop_column(_TABLE, "action")
