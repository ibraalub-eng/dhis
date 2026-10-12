"""dedup + unique constraint on indicator_values (hospital, indicator, month)

Revision ID: e5f6a7b8c9d0
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12

US-02 — Prevent Duplicate Indicator Values (Critical):

Before US-02, re-uploading the same Excel twice (with /upload?override=true
against a flush boundary, or two overlapping imports racing) could leave two
IndicatorValue rows for the same hospital x indicator x month, silently
corrupting quality scores, completeness, averages and anomaly math.

This migration:
  1. Deletes duplicate rows — for every (hospital_id, indicator_id, month)
     group it keeps the row with the HIGHEST id (the most recently written
     value wins; the parser's upsert path already treats a re-upload as an
     overwrite, so newest-wins matches the app's semantics). No information
     that was not already-shadowed older data is lost.
  2. Adds the unique constraint uq_indicator_value_hosp_ind_month, matching
     the ORM's UniqueConstraint on app.models.IndicatorValue.

Idempotent, same defensive style as b1c2d3e4f5a6: works on SQLite (dev) and
PostgreSQL (Render prod). A fresh DB bootstraps via Base.metadata.create_all
+ stamp head, where the constraint already exists from ORM metadata, so the
constraint step must be guarded by an index/constraint probe rather than
blindly re-issued.
"""
import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

_TABLE = "indicator_values"
_CONSTRAINT = "uq_indicator_value_hosp_ind_month"


def _existing_constraint_names(bind):
    from sqlalchemy import inspect
    insp = inspect(bind)
    names = set()
    try:
        names |= {c["name"] for c in insp.get_unique_constraints(_TABLE) if c.get("name")}
    except Exception:
        pass
    try:
        names |= {i["name"] for i in insp.get_indexes(_TABLE) if i.get("name")}
    except Exception:
        pass
    return names


def _upgrade_sqlite(bind):
    """SQLite path: DELETE dupes, then rewrite the table via batch mode to
    embed the unique constraint in the table DDL (no ALTER CONSTRAINT here)."""
    op.execute(
        "DELETE FROM indicator_values WHERE id NOT IN ("
        "  SELECT MAX(id) FROM indicator_values"
        "  GROUP BY hospital_id, indicator_id, month)"
    )
    if _CONSTRAINT in _existing_constraint_names(bind):
        return
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.create_unique_constraint(
            _CONSTRAINT, ["hospital_id", "indicator_id", "month"]
        )


def _upgrade_postgres(bind):
    op.execute(
        "DELETE FROM indicator_values WHERE id NOT IN ("
        "  SELECT MAX(id) FROM indicator_values"
        "  GROUP BY hospital_id, indicator_id, month)"
    )
    if _CONSTRAINT in _existing_constraint_names(bind):
        return
    op.create_unique_constraint(
        _CONSTRAINT, _TABLE, ["hospital_id", "indicator_id", "month"]
    )


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _upgrade_sqlite(bind)
    else:
        _upgrade_postgres(bind)


def downgrade():
    bind = op.get_bind()
    if _CONSTRAINT not in _existing_constraint_names(bind):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            batch.drop_constraint(_CONSTRAINT, type_="unique")
    else:
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
