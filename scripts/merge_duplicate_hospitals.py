#!/usr/bin/env python3
"""Merge upload-created duplicate hospitals into their canonical records.

DHIS exports carry the full organisation-unit path
(``وزارة الصحة/مستشفيات/عبدالعزيز الرنتيسي``) while the registry keeps the
short facility name (``مستشفى عبدالعزيز الرنتيسي``). When the importer
failed to resolve the two spellings to one facility it created a *second*
hospital and wrote the values there, leaving duplicates with identical data
in the Settings → Hospitals screen and double-counting them in every
cross-hospital average.

For each (duplicate → canonical) pair this script copies the duplicate's
values onto the canonical hospital (the duplicate's value wins where it is
non-null; the canonical keeps its value only where the duplicate carries an
empty cell), clears the derived rows of both sides (rebuilt by the analysis
pipeline), deletes the duplicate and can recompute the affected
hospital/months.

The duplicate id → (canonical id, optional canonical rename) mapping lives in
``MERGES`` below. Run with no flags for a dry run.

Usage::

    python scripts/merge_duplicate_hospitals.py
    python scripts/merge_duplicate_hospitals.py --apply --recompute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, inspect, text

from app.database import SessionLocal, engine
from app.models import Hospital, IndicatorValue

# duplicate hospital id -> (canonical hospital id, canonical rename or None)
MERGES = {
    # Full DHIS path vs short registry name (مستشفيات ≠ مستشفى spelling).
    47: (11, None),   # وزارة الصحة/مستشفيات/عبدالعزيز الرنتيسي -> مستشفى عبدالعزيز الرنتيسي (org 1027)
    44: (28, None),   # الهيئة الطبية الدولية الميداني غزة الكتيبة/IMC -> الهيئة الطبية الدولية الميداني غزة IMC (org 132799)
    45: (30, None),   # مستشفيات/ مستشفي القدس/PRCS -> مستشفى القدس PRCS (org 44641)
    # Same reporting line, facility renamed in the source export:
    # "مستشفى القدس الميداني" now ships as "مستشفى الشمال الميداني"
    # (760/760 identical rows). Canonical keeps its id and org unit (4877)
    # but adopts the current name so the next upload matches it.
    46: (37, "مستشفى الشمال الميداني PRCS"),
}

# Raw data and user assignments are never cleared on the canonical side.
_KEEP_FOR_CANONICAL = ("indicator_values", "user_hospitals")
# Hospital-scoped configuration is a deliberate admin choice — only the
# duplicate's copy goes away, the canonical keeps its overrides and groups.
_CONFIG_TABLES = ("hospital_indicator_config", "indicator_groups")


def _tables_referencing_hospitals(bind):
    """(table, column) pairs with a foreign key to hospitals.id.

    Discovered from the live schema so a model added later can never be
    missed and leave a dangling reference behind the deleted duplicate.
    """
    insp = inspect(bind)
    refs = []
    for table in insp.get_table_names():
        for fk in insp.get_foreign_keys(table):
            if fk.get("referred_table") == "hospitals" and fk.get("constrained_columns"):
                refs.append((table, fk["constrained_columns"][0]))
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge duplicate hospitals into canonical records")
    parser.add_argument("--apply", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--recompute", action="store_true", help="Rebuild derived results afterwards")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        ref_cols = _tables_referencing_hospitals(session.get_bind())
        print("Tables referencing hospitals: "
              + ", ".join(f"{t}.{c}" for t, c in ref_cols))

        for duplicate_id, (canonical_id, new_name) in MERGES.items():
            duplicate = session.get(Hospital, duplicate_id)
            canonical = session.get(Hospital, canonical_id)
            if duplicate is None or canonical is None:
                print(f"skip {duplicate_id}->{canonical_id}: hospital missing (already merged?)")
                continue
            dup_values = session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == duplicate_id).count()
            dup_real = session.query(func.count(IndicatorValue.id)).filter(
                IndicatorValue.hospital_id == duplicate_id,
                IndicatorValue.value.isnot(None)).scalar()
            can_real = session.query(func.count(IndicatorValue.id)).filter(
                IndicatorValue.hospital_id == canonical_id,
                IndicatorValue.value.isnot(None)).scalar()
            rename_note = f" and rename to {new_name!r}" if new_name else ""
            print(f"{duplicate_id} {duplicate.name[:46]:46} ({dup_values} rows, {dup_real} real) "
                  f"-> {canonical_id} {canonical.name[:34]} (existing {can_real} real){rename_note}")

            if not args.apply:
                continue

            taken = {
                (v.indicator_id, v.month): v
                for v in session.query(IndicatorValue).filter(
                    IndicatorValue.hospital_id == canonical_id).all()
            }
            copied = kept = 0
            for value in session.query(IndicatorValue).filter(
                    IndicatorValue.hospital_id == duplicate_id).all():
                key = (value.indicator_id, value.month)
                existing = taken.get(key)
                if existing is None:
                    session.add(IndicatorValue(
                        hospital_id=canonical_id,
                        indicator_id=value.indicator_id,
                        month=value.month,
                        value=value.value,
                        source_file=value.source_file,
                    ))
                    copied += 1
                elif value.value is not None and existing.value is None:
                    # Duplicate carries a real value the canonical is missing.
                    existing.value = value.value
                    existing.source_file = value.source_file
                    copied += 1
                else:
                    # Canonical value (or both empty / duplicate empty) wins.
                    kept += 1
            session.flush()

            # Drop the duplicate's rows everywhere; clear the canonical's
            # derived result rows so the recompute rebuilds them from the
            # merged values (config tables and raw values stay untouched).
            for table, column in ref_cols:
                session.execute(text(f'DELETE FROM "{table}" WHERE "{column}" = :id'),
                                {"id": duplicate_id})
                if table not in _KEEP_FOR_CANONICAL and table not in _CONFIG_TABLES:
                    session.execute(text(f'DELETE FROM "{table}" WHERE "{column}" = :id'),
                                    {"id": canonical_id})
            if new_name:
                canonical.name = new_name
            session.execute(text('DELETE FROM hospitals WHERE id = :id'), {"id": duplicate_id})
            canonical.is_active = True
            session.flush()
            print(f"  copied {copied} values (kept {kept} canonical), deleted duplicate {duplicate_id}"
                  + (f", renamed {canonical_id}" if new_name else ""))

        session.commit()

        if args.apply and args.recompute:
            from app.engine.pipeline import recompute_hospital_months

            print("\nRecomputing…")
            for canonical_id in sorted({c for _, (c, _) in MERGES.items()}):
                months = sorted({
                    month for (month,) in session.query(IndicatorValue.month)
                    .filter(IndicatorValue.hospital_id == canonical_id).distinct().all()
                })
                done = recompute_hospital_months(session, canonical_id, months, force=True)
                print(f"  hospital {canonical_id}: {done}/{len(months)} months", flush=True)
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
