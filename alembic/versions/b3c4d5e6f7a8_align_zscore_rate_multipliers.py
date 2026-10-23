"""Align the stored zscore multipliers with their reported units.

The zscore slice used to register MMR / NMR / stillbirth as "x100 / per 100"
while every other slice reports per-100,000 / per-1,000. The builtin slice now
carries the real unit multiplier, but two tables still hold the legacy 100 and
take precedence at calculation time:

* ``rate_config`` — the rows the layered engine / Outlier Scan reads (seeded
  once, insert-if-missing, so they froze the old default);
* ``indicator_definitions`` — the registry rows the Indicators screen shows.

f7a8b9c0d1e2 fixed the registry units; this revision fixes the numbers in both
stores so Neonatal mortality rate reads ``{17} / {6} * 1000`` on the Indicators
screen AND in the Quality / Outlier explanation. A value someone already
changed deliberately keeps itself — only the legacy 100 default is rewritten.

Revision ID: b3c4d5e6f7a8
Revises: f7a8b9c0d1e2
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

# (legacy_code, aligned multiplier, legacy multiplier)
_ALIGNED = (
    ("rate_mmr", 100000.0, 100.0),
    ("rate_nmr", 1000.0, 100.0),
    ("rate_stillbirth", 1000.0, 100.0),
)

_RATE_CONFIG_UPDATE = sa.text(
    "UPDATE rate_config "
    "SET rate_multiplier = :multiplier "
    "WHERE rate_code = :code AND rate_multiplier = :old_multiplier"
)

_DEFINITION_UPDATE = sa.text(
    "UPDATE indicator_definitions "
    "SET multiplier = :multiplier "
    "WHERE source_site = 'zscore' AND legacy_code = :code "
    "AND multiplier = :old_multiplier"
)


def _columns(bind, table: str) -> set:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _apply(bind, aligned: bool) -> None:
    # Guarded like the earlier registry migrations: each UPDATE only runs when
    # its table carries every column it writes/filters on. A minimal or legacy
    # table (e.g. one created by the startup create_all before this revision
    # existed) must not turn the upgrade into a "no such column" failure.
    rate_config_ready = {"rate_multiplier", "rate_code"} <= _columns(
        bind, "rate_config")
    definitions_ready = {"multiplier", "source_site", "legacy_code"} <= _columns(
        bind, "indicator_definitions")

    for legacy_code, mult, old_mult in _ALIGNED:
        params = {
            "code": legacy_code,
            "multiplier": mult if aligned else old_mult,
            "old_multiplier": old_mult if aligned else mult,
        }
        if rate_config_ready:
            bind.execute(_RATE_CONFIG_UPDATE, params)
        if definitions_ready:
            bind.execute(_DEFINITION_UPDATE, params)


def upgrade():
    _apply(op.get_bind(), aligned=True)


def downgrade():
    _apply(op.get_bind(), aligned=False)
