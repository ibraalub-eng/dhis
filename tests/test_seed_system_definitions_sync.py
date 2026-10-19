"""Re-seeding heals spec drift on system definitions — versioned, never silent.

2026-10-19: the clinical slice's per-1,000 / per-100,000 multipliers were
corrected from a legacy x1 to the real display scaling (x1,000 / x100,000).
Databases seeded before that fix must converge through the seed's sync
phase: a versioned content change with a full history snapshot, so stored
results keep their own formula_version and are flagged stale until
recomputed — never silently rewritten.
"""

import json

from app.models import IndicatorDefinition, IndicatorDefinitionVersion
from scripts.seed_indicators import seed_system_indicator_definitions


def _clinical_nmr(session):
    return session.query(IndicatorDefinition).filter(
        IndicatorDefinition.is_system.is_(True),
        IndicatorDefinition.source_site == "clinical",
        IndicatorDefinition.legacy_code == "rate_nmr",
    ).one()


def test_seed_sync_heals_multiplier_drift_with_history(db_session):
    seeded = _clinical_nmr(db_session)
    seeded_version = seeded.version
    # Simulate a database seeded before the multiplier fix.
    seeded.multiplier = 1.0
    db_session.commit()

    updated = seed_system_indicator_definitions(db_session)

    assert updated == 1  # only the drifted row, nothing else touched
    healed = _clinical_nmr(db_session)
    assert healed.multiplier == 1000.0
    assert healed.version == seeded_version + 1

    history = db_session.query(IndicatorDefinitionVersion).filter(
        IndicatorDefinitionVersion.definition_id == healed.id,
        IndicatorDefinitionVersion.version == healed.version,
    ).one()
    assert history.action == "migrated"
    assert history.changed_by == "system-migration"
    assert "multiplier" in json.loads(history.changed_fields)
    snapshot = json.loads(history.snapshot)
    assert snapshot["multiplier"] == 1000.0
    assert snapshot["unit"] == "per 1,000"


def test_seed_sync_is_idempotent(db_session):
    definition = _clinical_nmr(db_session)
    definition.multiplier = 1.0
    db_session.commit()

    first = seed_system_indicator_definitions(db_session)
    version_after_first = _clinical_nmr(db_session).version
    second = seed_system_indicator_definitions(db_session)

    assert first == 1
    assert second == 0  # no drift left — no extra version bump
    assert _clinical_nmr(db_session).version == version_after_first
