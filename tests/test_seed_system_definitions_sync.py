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


def test_system_definitions_carry_suitable_clinical_groups(db_session):
    """System definitions are grouped by clinical domain — reusable work
    units other screens select — never by the technical site key."""
    from app.engine.indicator_groups import (
        GROUP_DELIVERY,
        GROUP_MATERNAL,
        GROUP_NEWBORN,
        GROUP_ORDER,
    )

    rows = db_session.query(IndicatorDefinition).filter(
        IndicatorDefinition.is_system.is_(True)).all()
    assert rows, "seed must create system definitions"
    groups = {r.group_name for r in rows}
    assert not any(g and g.startswith("System indicators /") for g in groups)
    assert all(g in GROUP_ORDER for g in groups if g)

    by_key = {(r.source_site, r.legacy_code): r for r in rows}
    assert by_key[("clinical", "rate_mmr")].group_name == GROUP_MATERNAL
    assert by_key[("clinical", "rate_nmr")].group_name == GROUP_NEWBORN
    assert by_key[("clinical", "rate_cs")].group_name == GROUP_DELIVERY
    assert by_key[("zscore", "rate_cs")].group_name == GROUP_DELIVERY
    # one domain spans the sites where it applies — that cross-site span is
    # what makes the group reusable as a unit (outlier sets, report sections)
    maternal = {r.source_site for r in rows if r.group_name == GROUP_MATERNAL}
    assert maternal >= {"clinical", "zscore"}


def test_seed_sync_heals_group_name_drift_with_history(db_session):
    """A legacy site-key group label heals through the sync phase as a
    versioned content change with history — never silently."""
    from app.engine.indicator_groups import GROUP_NEWBORN

    definition = _clinical_nmr(db_session)
    definition.group_name = "System indicators / clinical"  # pre-fix label
    db_session.commit()

    updated = seed_system_indicator_definitions(db_session)

    assert updated == 1
    healed = _clinical_nmr(db_session)
    assert healed.group_name == GROUP_NEWBORN
    assert healed.version >= 2

    history = db_session.query(IndicatorDefinitionVersion).filter(
        IndicatorDefinitionVersion.definition_id == healed.id,
        IndicatorDefinitionVersion.version == healed.version,
    ).one()
    assert history.action == "migrated"
    assert "group_name" in json.loads(history.changed_fields)
    snapshot = json.loads(history.snapshot)
    assert snapshot["group_name"] == GROUP_NEWBORN
