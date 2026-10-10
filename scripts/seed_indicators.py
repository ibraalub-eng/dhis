"""Seed the indicator definitions into the database."""
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


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_indicators(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
