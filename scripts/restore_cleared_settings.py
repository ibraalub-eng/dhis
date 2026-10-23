#!/usr/bin/env python3
"""Restore hospital metadata and system settings cleared by a database reset.

A reset that re-runs the seeds rebuilds ``hospitals`` and ``system_settings``
from scratch, so two things the operator had configured disappear:

* **hospital metadata** — ``facility_ownership_id`` (and sometimes governorate /
  type) ends up NULL, which drops facilities out of ownership/region filters
  and makes regional dashboards group them as "unknown";
* **system settings** — ``hide_explanatory_text``, the logging switches,
  ``upload_incremental_months`` and the AI configuration are gone, so the UI
  silently falls back to defaults.

This script copies both layers back from a plain ``pg_dump``:

* hospitals are matched by ``organisation_unit_id`` (names in the live DB are
  often shortened, and ids are reassigned by a re-seed); records without an
  organisation unit fall back to an exact name match. Only fields that are
  currently NULL/empty are filled — anything already set is left alone, so the
  script is insert/fill-only and safe to re-run;
* system settings are inserted only when the key is absent. ``ai_api_key`` is
  skipped unless ``--include-secrets`` is passed, and its value is never
  printed.

Per-hospital month toggles (``month_enabled_<hid>_<YYYY-MM>``) live in
``system_settings`` too; when the dump does not contain them there is nothing
to restore and the script says so instead of inventing a state.

Usage::

    python scripts/restore_cleared_settings.py --source C:/path/dump.sql
    python scripts/restore_cleared_settings.py --source C:/path/dump.sql --apply
    python scripts/restore_cleared_settings.py --source C:/path/dump.sql --apply --include-secrets
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import Hospital, SystemSetting

NULL = "\\N"

HOSPITAL_FIELDS = (
    "governorate_id",
    "hospital_type_id",
    "facility_type_id",
    "facility_ownership_id",
    "address",
)

SECRET_SETTING_KEYS = {"ai_api_key"}


def block(lines: list[str], table: str) -> list[dict]:
    prefix = f"COPY public.{table} "
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        return []
    header = lines[start]
    columns = header[header.index("(") + 1: header.rindex(")")].split(", ")
    rows = []
    for line in lines[start + 1:]:
        if line == "\\.":
            break
        rows.append(dict(zip(columns, line.split("\t"), strict=False)))
    return rows


def _int(value):
    return None if value in (NULL, "") else int(value)


def _str(value):
    return None if value in (NULL, "") else value


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore hospital metadata and system settings")
    parser.add_argument("--source", required=True, help="plain pg_dump (.sql) file")
    parser.add_argument("--apply", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--include-secrets", action="store_true", help="Also restore ai_api_key")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"Backup not found: {source}")
        return 1

    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    dump_hospitals = block(lines, "hospitals")
    dump_settings = block(lines, "system_settings")
    if not dump_hospitals:
        print("No hospitals COPY block found in the dump.")
        return 1

    by_org = {}
    by_name = {}
    for row in dump_hospitals:
        org = _str(row.get("organisation_unit_id"))
        meta = {
            "governorate_id": _int(row.get("governorate_id")),
            "hospital_type_id": _int(row.get("hospital_type_id")),
            "facility_type_id": _int(row.get("facility_type_id")),
            "facility_ownership_id": _int(row.get("facility_ownership_id")),
            "address": _str(row.get("address")),
            "name": row.get("name", ""),
        }
        if org:
            by_org[org] = meta
        by_name[meta["name"]] = meta

    session = SessionLocal()
    filled = 0
    try:
        hospitals = session.query(Hospital).all()
        print(f"hospitals in dump: {len(dump_hospitals)} | in database: {len(hospitals)}")
        for hospital in hospitals:
            org = str(hospital.organisation_unit_id) if hospital.organisation_unit_id else None
            meta = by_org.get(org) if org else None
            if meta is None:
                meta = by_name.get(hospital.name)
            if meta is None:
                print(f"  skip  {hospital.id} {hospital.name[:40]} — no counterpart in the dump")
                continue
            changes = {}
            for field in HOSPITAL_FIELDS:
                current = getattr(hospital, field)
                wanted = meta[field]
                if wanted in (None, "") or current not in (None, ""):
                    continue
                changes[field] = wanted
            if changes:
                filled += 1
                rendered = ", ".join(f"{k}={v}" for k, v in changes.items())
                print(f"  fill  {hospital.id} {hospital.name[:40]} — {rendered}")
                for field, value in changes.items():
                    setattr(hospital, field, value)

        existing_keys = {s.key for s in session.query(SystemSetting).all()}
        month_keys = [r for r in dump_settings if r["key"].startswith("month_enabled_")]
        restorable = [r for r in dump_settings if r["key"] not in existing_keys]
        secrets = [r for r in restorable if r["key"] in SECRET_SETTING_KEYS]
        plain = [r for r in restorable if r["key"] not in SECRET_SETTING_KEYS]
        print(f"\nsystem settings in dump: {len(dump_settings)} | already present: "
              f"{len(dump_settings) - len(restorable)} | missing: {len(restorable)}")
        for row in plain:
            print(f"  set   {row['key']} = {row['value'][:60]}")
            session.add(SystemSetting(key=row["key"], value=row["value"]))
        for row in secrets:
            if args.include_secrets:
                print(f"  set   {row['key']} = <value from backup, not shown>")
                session.add(SystemSetting(key=row["key"], value=row["value"]))
            else:
                print(f"  skip  {row['key']} — secret, re-run with --include-secrets to restore")
        if month_keys:
            print(f"  month toggles in dump: {len(month_keys)}")
        else:
            print("  month toggles (month_enabled_<hid>_<month>) are NOT in this dump — "
                  "nothing to restore; re-toggle them in Settings → Data Tree")

        if args.apply:
            session.commit()
            print(f"\nApplied: {filled} hospital records filled, "
                  f"{len(plain) + (len(secrets) if args.include_secrets else 0)} settings written.")
        else:
            session.rollback()
            print(f"\nDry run: {filled} hospital records and "
                  f"{len(plain) + (len(secrets) if args.include_secrets else 0)} settings "
                  "would be written. Re-run with --apply to commit.")
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
