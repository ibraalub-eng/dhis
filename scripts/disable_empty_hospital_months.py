#!/usr/bin/env python3
"""Disable months a hospital has no data for.

The per-hospital month toggles live in ``system_settings`` as
``month_enabled_<hospital_id>_<YYYY-MM>``. A database reset wipes them, and
there is no audit trail to rebuild the operator's original choices. What the
toggles were doing, though, can be re-derived from the data itself: a month in
which a facility reported **nothing at all** is not "0 % complete", it is a
month that facility did not report.

This script writes ``= false`` for every (active hospital, month) pair that has
no non-null indicator value behind it, and nothing else:

* pairs that already carry a setting are never touched (the operator's explicit
  choice wins, in either direction);
* hospitals with at least one value in the month are left enabled, so genuinely
  sparse months keep counting as low completeness instead of being hidden;
* inactive hospitals are skipped — they are out of every aggregate already.

Dry run by default; pass ``--apply`` to write.

Usage::

    python scripts/disable_empty_hospital_months.py
    python scripts/disable_empty_hospital_months.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.analysis import _list_months_with_data
from app.api.config_api import MONTH_SETTINGS_PREFIX
from app.database import SessionLocal
from app.models import Hospital, IndicatorValue, SystemSetting


def main() -> int:
    parser = argparse.ArgumentParser(description="Disable months without any reported value")
    parser.add_argument("--apply", action="store_true", help="Write the settings (default is a dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        months = _list_months_with_data(session, None)
        hospitals = [h for h in session.query(Hospital).all() if h.is_active]
        existing = {s.key for s in session.query(SystemSetting).all()}

        reported = set()
        for hid, month in session.query(
            IndicatorValue.hospital_id, IndicatorValue.month
        ).filter(IndicatorValue.value.isnot(None)).distinct():
            reported.add((hid, month))

        planned = []
        for hospital in hospitals:
            for month in months:
                if (hospital.id, month) in reported:
                    continue
                key = f"{MONTH_SETTINGS_PREFIX}{hospital.id}_{month}"
                if key in existing:
                    continue
                planned.append((hospital, month, key))

        print(f"months with data: {len(months)} ({months[0]} … {months[-1]})" if months else "no months with data")
        print(f"active hospitals: {len(hospitals)} | hospital-months reported: {len(reported)}")
        print(f"empty hospital-months to disable: {len(planned)}")
        by_hospital: dict[int, list[str]] = {}
        for hospital, month, _ in planned:
            by_hospital.setdefault(hospital.id, []).append(month)
        for hid, mms in sorted(by_hospital.items()):
            name = next(h.name for h, _, _ in planned if h.id == hid)
            print(f"  {hid} {name[:38]} — {len(mms)} month(s): {', '.join(sorted(mms))}")

        if not planned:
            print("Nothing to do.")
            return 0

        if args.apply:
            for _, _, key in planned:
                session.add(SystemSetting(key=key, value="false"))
            session.commit()
            print(f"\nApplied: {len(planned)} month settings disabled.")
            try:
                from app.cache import cache as _cache

                _cache.invalidate("v2|reports:")
                _cache.invalidate("v2|analysis:")
                print("Invalidated reports/analysis caches.")
            except Exception as exc:  # cache is optional at script level
                print(f"Cache invalidation skipped: {exc}")
        else:
            session.rollback()
            print(f"\nDry run: {len(planned)} settings would be written. Re-run with --apply.")
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
