"""Align the zscore mortality rates with the clinical display scale.

The same rate key was registered twice with two different formulas:
zscore stored MMR/NMR/stillbirth as "x100 / per 100" while clinical and
forecast report per-100,000 / per-1,000. Quality Alerts (zscore engine)
therefore showed ``{17} / {6} * 100`` for Neonatal mortality rate while the
Indicators registry showed ``{17} / {6} * 1000`` — same indicator, two
formulas. rate_config's builtin zscore slice now carries the unit's real
multiplier; this migration applies the same values to the rows already
stored in the registry.

Revision ID: f7a8b9c0d1e2
Revises: e3f4a5b6c7d8
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

# (legacy_code, aligned multiplier, aligned unit, legacy multiplier, legacy unit)
_ALIGNED = (
    ("rate_mmr", 100000.0, "per 100,000", 100.0, "per 100"),
    ("rate_nmr", 1000.0, "per 1,000", 100.0, "per 100"),
    ("rate_stillbirth", 1000.0, "per 1,000", 100.0, "per 100"),
)

_UPDATE = sa.text(
    "UPDATE indicator_definitions "
    "SET multiplier = :multiplier, unit = :unit "
    "WHERE source_site = 'zscore' AND legacy_code = :code AND is_system = true"
)


def _definition_columns(bind) -> set:
    inspector = inspect(bind)
    if "indicator_definitions" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in
            inspector.get_columns("indicator_definitions")}


def _apply(bind, aligned: bool) -> None:
    # Guarded like the earlier registry migrations: a database whose
    # indicator_definitions predates the multiplier/unit columns (the startup
    # create_all path can leave a minimal table behind) only gets those
    # columns from the revision that adds them, so the UPDATE must be a no-op
    # here instead of failing the whole upgrade.
    required = {"multiplier", "unit", "source_site", "legacy_code", "is_system"}
    if not required <= _definition_columns(bind):
        return
    for legacy_code, mult, unit, old_mult, old_unit in _ALIGNED:
        bind.execute(_UPDATE, {
            "multiplier": mult if aligned else old_mult,
            "unit": unit if aligned else old_unit,
            "code": legacy_code,
        })


def upgrade():
    _apply(op.get_bind(), aligned=True)


def downgrade():
    _apply(op.get_bind(), aligned=False)
