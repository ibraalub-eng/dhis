"""Seed the indicator definitions into the database."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.indicators import INDICATOR_FLAT_LIST
from app.models import Indicator


def seed_indicators(session):
    """Seed indicators into the database using the given session."""
    existing = {ind.code for ind in session.query(Indicator).all()}
    if not existing:
        code_to_id = {}
        for ind in INDICATOR_FLAT_LIST:
            parent_id = None
            if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                parent_id = code_to_id[ind["parent_id"]]
            db_ind = Indicator(
                code=ind["code"],
                name=ind["name"],
                parent_id=parent_id,
                level=ind["level"],
                group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
            )
            session.add(db_ind)
            session.flush()
            code_to_id[ind["code"]] = db_ind.id
    else:
        code_to_id = {}
        for db_ind in session.query(Indicator).all():
            code_to_id[db_ind.code] = db_ind.id
        for ind in INDICATOR_FLAT_LIST:
            if ind["code"] in code_to_id:
                continue
            parent_id = None
            if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                parent_id = code_to_id[ind["parent_id"]]
            db_ind = Indicator(
                code=ind["code"],
                name=ind["name"],
                parent_id=parent_id,
                level=ind["level"],
                group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
            )
            session.add(db_ind)
            session.flush()
            code_to_id[ind["code"]] = db_ind.id
    if session.new:
        session.commit()


def seed_rate_config(session):
    """Insert-if-missing the registry's zscore slice into rate_config.

    Spec 2026-10-08 §4.2: DB rows are seeded from the builtin zscore slice
    (rate_multiplier 100 for all 7 rates, minimum_denominator NULL = guard
    dormant); the engine merges DB tunables over builtin defaults. Returns
    the number of rows added; invalidates the in-process spec cache.
    """
    from app.engine.rate_config import invalidate_rate_specs_cache, zscore_specs
    from app.models import RateConfig

    existing = {code for (code,) in session.query(RateConfig.rate_code).all()}
    added = 0
    for spec in zscore_specs():
        if spec.rate_code in existing:
            continue
        session.add(RateConfig(
            rate_code=spec.rate_code,
            rate_name=spec.rate_name,
            indicator_type=spec.indicator_type,
            numerator_codes=list(spec.numerator_codes),
            denominator_codes=list(spec.denominator_codes),
            rate_multiplier=int(spec.rate_multiplier),
            minimum_denominator=None,
            minimum_history_period=spec.minimum_history_period,
            outlier_method=spec.outlier_method,
            historical_enabled=spec.historical_enabled,
            peer_comparison_enabled=spec.peer_comparison_enabled,
            is_active=spec.is_active,
        ))
        added += 1
    if added:
        session.commit()
    invalidate_rate_specs_cache()
    return added


def seed_system_indicator_definitions(session):
    """Migrate built-in rate definitions into the versioned Indicators registry.

    The original source-specific formulas are intentionally kept as distinct
    rows. Existing module behavior selects the matching ``source_site`` while
    new user-managed definitions remain shared across modules.
    """
    from app.engine.rate_config import (
        SITE_CLINICAL,
        SITE_FORECAST,
        SITE_ZSCORE,
        iter_site,
        load_rate_specs,
    )
    from app.models import IndicatorDefinition, IndicatorDefinitionVersion

    specs = list(load_rate_specs(session).values())
    specs.extend(iter_site(SITE_CLINICAL))
    specs.extend(iter_site(SITE_FORECAST))
    existing = {
        (definition.source_site, definition.legacy_code)
        for definition in session.query(IndicatorDefinition)
        .filter(IndicatorDefinition.is_system.is_(True))
        .all()
    }
    added = 0
    for spec in specs:
        site = spec.site or SITE_ZSCORE
        legacy_code = spec.rate_code
        if (
            spec.indicator_type == "count"
            and not spec.denominator_codes
            and len(spec.numerator_codes) == 1
            and spec.rate_multiplier == 1
        ):
            continue
        key = (site, legacy_code)
        if key in existing:
            continue
        readable = "".join(
            char.lower() if char.isalnum() else "_"
            for char in legacy_code
        ).strip("_")
        code = f"sys_{site}_{readable}"
        if len(code) > 50:
            suffix = hashlib.sha1(code.encode("utf-8")).hexdigest()[:8]
            code = f"{code[:41]}_{suffix}"
        definition = IndicatorDefinition(
            code=code,
            name=spec.rate_name,
            description=f"Migrated system definition ({site}); legacy key {legacy_code}.",
            group_name=f"System indicators / {site}",
            source_site=site,
            legacy_code=legacy_code,
            is_system=True,
            formula_type="ratio",
            numerator_codes=list(spec.numerator_codes or ()),
            denominator_codes=list(spec.denominator_codes or ()),
            operator="/" if spec.denominator_codes else "*",
            multiplier=float(spec.rate_multiplier),
            aggregation="sum",
            result_type=spec.indicator_type,
            unit=spec.unit or None,
            is_active=bool(spec.is_active),
            version=1,
        )
        session.add(definition)
        session.flush()
        snapshot = {
            "code": definition.code,
            "legacy_code": definition.legacy_code,
            "name": definition.name,
            "source_site": definition.source_site,
            "is_system": True,
            "formula_type": definition.formula_type,
            "numerator_codes": definition.numerator_codes,
            "denominator_codes": definition.denominator_codes,
            "operator": definition.operator,
            "multiplier": definition.multiplier,
            "aggregation": definition.aggregation,
            "result_type": definition.result_type,
            "unit": definition.unit,
            "is_active": definition.is_active,
            "version": definition.version,
        }
        session.add(IndicatorDefinitionVersion(
            definition_id=definition.id,
            definition_code=definition.code,
            version=1,
            action="migrated",
            snapshot=json.dumps(snapshot, ensure_ascii=False),
            changed_fields=json.dumps(["*"]),
            changed_by="system-migration",
        ))
        existing.add(key)
        added += 1

    # Sync EXISTING system rows with their spec — the spec stays the single
    # source of truth for migrated definitions. A drift (e.g. the clinical
    # slice's per-1,000/per-100,000 multipliers being corrected from x1 to
    # the real display scaling) is applied as a VERSIONED content change with
    # a full history snapshot, never silently: previously stored results keep
    # their own formula_version and are flagged stale until recomputed.
    updated = 0
    spec_by_key = {(spec.site or SITE_ZSCORE, spec.rate_code): spec
                   for spec in specs}
    for definition in session.query(IndicatorDefinition).filter(
            IndicatorDefinition.is_system.is_(True)).all():
        spec = spec_by_key.get((definition.source_site, definition.legacy_code))
        if spec is None:
            continue
        desired = {
            "name": spec.rate_name,
            "numerator_codes": list(spec.numerator_codes or ()),
            "denominator_codes": list(spec.denominator_codes or ()),
            "operator": "/" if spec.denominator_codes else "*",
            "multiplier": float(spec.rate_multiplier),
            "result_type": spec.indicator_type,
            "unit": spec.unit or None,
            "is_active": bool(spec.is_active),
        }
        changed = [field for field, value in desired.items()
                   if getattr(definition, field, None) != value]
        if not changed:
            continue
        for field, value in desired.items():
            setattr(definition, field, value)
        definition.version = int(definition.version or 1) + 1
        session.add(IndicatorDefinitionVersion(
            definition_id=definition.id,
            definition_code=definition.code,
            version=definition.version,
            action="migrated",
            snapshot=json.dumps({
                "code": definition.code,
                "legacy_code": definition.legacy_code,
                "name": definition.name,
                "source_site": definition.source_site,
                "is_system": True,
                "formula_type": definition.formula_type,
                "numerator_codes": definition.numerator_codes,
                "denominator_codes": definition.denominator_codes,
                "operator": definition.operator,
                "multiplier": definition.multiplier,
                "aggregation": definition.aggregation,
                "result_type": definition.result_type,
                "unit": definition.unit,
                "is_active": definition.is_active,
                "version": definition.version,
            }, ensure_ascii=False),
            changed_fields=json.dumps(sorted(changed)),
            changed_by="system-migration",
        ))
        updated += 1

    if added or updated:
        session.commit()
    return added + updated


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_indicators(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
