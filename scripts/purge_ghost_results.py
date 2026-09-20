#!/usr/bin/env python3
"""Delete ghost derived-result rows from the database.

A "ghost" is a row in QualityScore / ConfidenceScore / ValidationResult /
AnomalyResult for a (hospital, month) that has NO IndicatorValue rows —
i.e. a month that was never actually analyzed. The engine persists zero-score
sentinel rows for such months on purpose (so detected-but-empty months stay
visible as reports), but once a month is stale, those sentinels are pure
noise: they made fake months show up in the month/year dropdowns and dragged
down every average until the dashboard learned to gate them out.

Months with REAL indicator data are never touched — including analyzed months
whose score legitimately equals 0 (all rules failing is real data, not a ghost).

Usage:
    python scripts/purge_ghost_results.py            # dry run: print what would go
    python scripts/purge_ghost_results.py --execute  # actually delete + invalidate caches

After --execute the shared file cache (data/cache) is fully invalidated so the
month dropdowns and dashboards pick up the change immediately.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AnomalyResult,
    ConfidenceScore,
    IndicatorValue,
    QualityScore,
    ValidationResult,
)

# All derived-result tables that carry a (hospital_id, month) stamp.
RESULT_TABLES = (
    ("quality_scores", QualityScore),
    ("confidence_scores", ConfidenceScore),
    ("validation_results", ValidationResult),
    ("anomaly_results", AnomalyResult),
)


def analyzed_pairs(db) -> set:
    """(hospital_id, month) pairs that have real indicator data."""
    return {
        (h, m)
        for h, m in db.query(IndicatorValue.hospital_id, IndicatorValue.month).distinct().all()
    }


def find_ghosts(db):
    """Return [(table_name, [rows])] for every derived row whose
    (hospital, month) has no indicator data."""
    pairs = analyzed_pairs(db)
    report = []
    for name, model in RESULT_TABLES:
        rows = db.query(model).all()
        ghosts = [r for r in rows if (r.hospital_id, r.month) not in pairs]
        report.append((name, ghosts))
    return report


def main():
    parser = argparse.ArgumentParser(description="Delete ghost zero-score result rows.")
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete. Without this flag, only a preview is printed.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = find_ghosts(db)
        total = sum(len(rows) for _, rows in report)

        pairs = analyzed_pairs(db)
        print(f"Analyzed (hospital, month) pairs with real data: {len(pairs)}")
        if pairs:
            months = sorted({m for _, m in pairs})
            print(f"  months: {', '.join(months)}")
        print()

        if total == 0:
            print("No ghost rows found — nothing to do.")
            return

        for name, ghosts in report:
            if not ghosts:
                continue
            months = sorted({r.month for r in ghosts})
            hosp_ids = sorted({r.hospital_id for r in ghosts})
            print(f"{name}: {len(ghosts)} ghost row(s)")
            print(f"  hospital_ids: {hosp_ids}")
            print(f"  months:       {months}")

        if not args.execute:
            print("\nDRY RUN — no rows deleted. Re-run with --execute to apply.")
            return

        for _, ghosts in report:
            for row in ghosts:
                db.delete(row)
        db.commit()
        print(f"\nDeleted {total} ghost row(s).")

        # Invalidate the shared file cache so month dropdowns, dashboards and
        # rankings reflect the purge without a restart.
        from app.cache import cache
        cache.invalidate()
        print("Cache invalidated (data/cache cleared).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
