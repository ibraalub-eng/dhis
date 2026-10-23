#!/usr/bin/env python3
"""Rebuild stored results with the single outlier engine.

Analyses run before the unification wrote two independent sets of numbers:
the layered engine stored rates and data elements in ``layered_outlier_results``
while the classic detector stored derived rates in ``anomaly_results``, with a
different peer group. Since then ``anomaly_results`` is a projection of the
layered result, so both tables agree — but only for months analysed after the
change.

This script re-runs the analysis for the months that still carry layered rows,
which rewrites the projected rows with the engine's own peer statistics (peer
names, spread, min/max/median). Re-analysis is the only faithful way to do it:
the stored layered rows keep the score and the level, not the peer set the
score was computed against.

Usage:
    python scripts/backfill_anomaly_projection.py            # dry run: list months
    python scripts/backfill_anomaly_projection.py --execute  # re-analyse them

``--month YYYY-MM`` narrows the run. Failures are reported per hospital/month
and do not stop the run; the pipeline persists a fallback score row for them.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.engine.pipeline import run_full_analysis  # noqa: E402
from app.models import LayeredOutlierResult  # noqa: E402


def stored_pairs(db, month=None):
    """(hospital_id, month) pairs that already have layered results."""
    query = (db.query(LayeredOutlierResult.hospital_id,
                      LayeredOutlierResult.month)
             .distinct())
    if month:
        query = query.filter(LayeredOutlierResult.month == month)
    return sorted(query.all())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="actually re-analyse (default: dry run)")
    parser.add_argument("--month", default=None,
                        help="only this month (YYYY-MM)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        pairs = stored_pairs(db, args.month)
        if not pairs:
            print("No stored layered results found — nothing to rebuild.")
            return 0

        print(f"{len(pairs)} hospital/month pair(s) with layered results")
        if not args.execute:
            for hospital_id, month in pairs:
                print(f"  would re-analyse hospital {hospital_id} / {month}")
            print("\nDry run — pass --execute to rebuild.")
            return 0

        done = 0
        failed = []
        for hospital_id, month in pairs:
            try:
                run_full_analysis(db, hospital_id, month, force=True)
                done += 1
            except Exception as exc:                      # noqa: BLE001 - report and continue
                db.rollback()
                failed.append((hospital_id, month, str(exc)))
                print(f"  FAILED hospital {hospital_id} / {month}: {exc}")
            if done and done % 25 == 0:
                print(f"  ... {done}/{len(pairs)}")

        print(f"\nRebuilt {done}/{len(pairs)} hospital/month pair(s).")
        if failed:
            print(f"{len(failed)} failure(s):")
            for hospital_id, month, reason in failed:
                print(f"  {hospital_id} / {month}: {reason}")
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
