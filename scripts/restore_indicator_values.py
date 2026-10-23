#!/usr/bin/env python3
"""Restore indicator values from a backup into PostgreSQL.

Context: ``DELETE /hospitals/clear-all-data`` wipes ``indicator_values`` and
marks every hospital inactive. When that runs against the deployed Postgres
database, every screen (Dashboard, Quality, Alerts, Outliers, Audit) goes empty
for every user, including superusers, because there is nothing to read.

This script copies the raw monthly values back **without touching** hospitals,
indicators, definitions, users or derived results. It understands two backup
formats:

* ``*.db``  — the local SQLite snapshot (``data/health_ai.db``),
* ``*.sql`` — a plain ``pg_dump`` dump (the production snapshot).

Hospitals are matched by DHIS ``organisation_unit_id`` first, then by exact
name, then by any ``--map "old=new"`` alias. Indicators are matched by code.
Values are inserted with ``ON CONFLICT DO NOTHING`` so the script is safe to
re-run; hospitals that receive values are re-activated.

Derived rows (quality scores, anomalies, validation) are rebuilt separately by
the analysis pipeline; pass ``--recompute`` to run it for every restored
hospital/month.

Usage::

    # preview only (default)
    python scripts/restore_indicator_values.py --source data/health_ai.db

    # write, then rebuild derived results
    python scripts/restore_indicator_values.py --source data/health_ai.db --apply --recompute

    # production pg_dump snapshot
    python scripts/restore_indicator_values.py --source C:/path/dhis_prod_snapshot.sql --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import Hospital, Indicator, IndicatorValue

NULL = "\\N"


def read_sqlite(path: Path) -> list[dict]:
    """One dict per value, with the keys shared by both backup formats."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT h.name AS hospital_name,
                   h.id AS hospital_legacy_id,
                   i.code AS indicator_code,
                   v.month AS month,
                   v.value AS value,
                   v.source_file AS source_file,
                   v.created_at AS created_at
            FROM indicator_values v
            JOIN hospitals h ON h.id = v.hospital_id
            JOIN indicators i ON i.id = v.indicator_id
            ORDER BY h.name, v.month, i.code
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row, hospital_org=None) for row in rows]


def _copy_block(lines: list[str], table: str) -> list[list[str]]:
    prefix = f"COPY public.{table} "
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        raise SystemExit(f"Table '{table}' not found in the dump")
    rows = []
    for line in lines[start + 1:]:
        if line == "\\.":
            break
        rows.append(line.split("\t"))
    return rows


def read_pg_dump(path: Path) -> list[dict]:
    """Read hospitals/indicators/indicator_values out of a plain pg_dump file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hospitals = {}
    for row in _copy_block(lines, "hospitals"):
        # id, name, region, created_at, is_active, governorate_id,
        # hospital_type_id, address, organisation_unit_id, ...
        org = row[8] if len(row) > 8 and row[8] != NULL else None
        hospitals[row[0]] = {"name": row[1], "org": org}
    codes = {row[0]: row[1] for row in _copy_block(lines, "indicators")}

    rows = []
    for row in _copy_block(lines, "indicator_values"):
        # id, hospital_id, indicator_id, month, value, source_file, created_at
        hospital = hospitals.get(row[1])
        if hospital is None:
            continue
        rows.append({
            "hospital_name": hospital["name"],
            "hospital_org": hospital["org"],
            "hospital_legacy_id": row[1],
            "indicator_code": codes.get(row[2]),
            "month": row[3],
            "value": None if row[4] == NULL else float(row[4]),
            "source_file": None if row[5] == NULL else row[5],
            "created_at": None if row[6] == NULL else row[6],
        })
    return rows


def read_source(path: Path) -> list[dict]:
    if path.suffix.lower() == ".db":
        return read_sqlite(path)
    if path.suffix.lower() == ".sql":
        return read_pg_dump(path)
    raise SystemExit(f"Unsupported backup format: {path.name} (expected .db or .sql)")


def parse_maps(pairs: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--map expects 'old=new', got: {pair!r}")
        old, new = pair.split("=", 1)
        mapping[old.strip()] = new.strip()
    return mapping


def resolve_hospitals(
    session: Session,
    rows: list[dict],
    aliases: dict[str, str],
) -> tuple[dict[str, int], list[str], list[str]]:
    """Map backup hospital rows to Postgres ids (by org unit, name, or alias).

    Returns ``(resolved, unresolved, ambiguous)`` keyed by the backup hospital
    label (org unit id when present, otherwise the name).
    """
    by_org: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    for hospital in session.query(Hospital.id, Hospital.name, Hospital.organisation_unit_id).all():
        by_name[hospital.name].append(hospital.id)
        if hospital.organisation_unit_id:
            by_org[str(hospital.organisation_unit_id)].append(hospital.id)

    labels: dict[str, dict] = {}
    for row in rows:
        label = row["hospital_org"] or row["hospital_name"]
        labels[label] = row

    resolved: dict[str, int] = {}
    unresolved: list[str] = []
    ambiguous: list[str] = []
    for label, row in labels.items():
        target_name = aliases.get(row["hospital_name"], row["hospital_name"])
        matches = by_org.get(str(row["hospital_org"]), []) if row["hospital_org"] else []
        if len(matches) != 1:
            matches = by_name.get(target_name, [])
        if len(matches) == 1:
            resolved[label] = matches[0]
        elif len(matches) > 1:
            ambiguous.append(label)
        else:
            unresolved.append(label)
    return resolved, unresolved, ambiguous


def insert_values(
    session: Session,
    rows: list[dict],
    hospital_ids: dict[str, int],
    overwrite: bool = False,
) -> tuple[int, int, int, int]:
    """Insert missing values (optionally update differing ones).

    Returns ``(inserted, updated, already_present, unknown_indicator)``.
    """
    indicator_ids = {code: pk for pk, code in session.query(Indicator.id, Indicator.code).all()}
    existing = {
        (hospital_id, indicator_id, month): value
        for hospital_id, indicator_id, month, value in session.query(
            IndicatorValue.hospital_id,
            IndicatorValue.indicator_id,
            IndicatorValue.month,
            IndicatorValue.value,
        ).all()
    }

    payload = []
    updates = []
    already = 0
    unknown = 0
    for row in rows:
        label = row["hospital_org"] or row["hospital_name"]
        hospital_id = hospital_ids.get(label)
        indicator_id = indicator_ids.get(row["indicator_code"])
        if hospital_id is None or indicator_id is None:
            unknown += 1
            continue
        key = (hospital_id, indicator_id, row["month"])
        if key in existing:
            stored = existing[key]
            if overwrite and stored != row["value"]:
                updates.append({
                    "b_hospital": hospital_id,
                    "b_indicator": indicator_id,
                    "b_month": row["month"],
                    "b_value": row["value"],
                })
            else:
                already += 1
            continue
        existing[key] = row["value"]
        payload.append({
            "hospital_id": hospital_id,
            "indicator_id": indicator_id,
            "month": row["month"],
            "value": row["value"],
            "source_file": row["source_file"],
            "created_at": row["created_at"],
        })

    inserted = 0
    batch_size = 1000
    for start in range(0, len(payload), batch_size):
        statement = insert(IndicatorValue).values(payload[start:start + batch_size])
        statement = statement.on_conflict_do_nothing(
            index_elements=["hospital_id", "indicator_id", "month"]
        )
        result = session.execute(statement)
        inserted += result.rowcount or 0

    updated = 0
    if updates:
        from sqlalchemy import bindparam, text

        statement = text(
            "UPDATE indicator_values SET value = :b_value "
            "WHERE hospital_id = :b_hospital AND indicator_id = :b_indicator AND month = :b_month"
        ).bindparams(bindparam("b_value"), bindparam("b_hospital"), bindparam("b_indicator"), bindparam("b_month"))
        session.execute(statement, updates)
        updated = len(updates)
    return inserted, updated, already, unknown


def reactivate(session: Session, hospital_ids: list[int]) -> int:
    if not hospital_ids:
        return 0
    updated = (
        session.query(Hospital)
        .filter(Hospital.id.in_(hospital_ids), Hospital.is_active.isnot(True))
        .update({Hospital.is_active: True}, synchronize_session=False)
    )
    return int(updated or 0)


def recompute(session: Session, hospital_ids: list[int]) -> None:
    from app.engine.pipeline import recompute_hospital_months

    for hospital_id in hospital_ids:
        months = [
            row[0]
            for row in session.query(IndicatorValue.month)
            .filter(IndicatorValue.hospital_id == hospital_id)
            .distinct()
            .order_by(IndicatorValue.month)
            .all()
        ]
        done = recompute_hospital_months(session, hospital_id, months, force=True)
        print(f"  recomputed hospital {hospital_id}: {done}/{len(months)} months", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore indicator values from a backup into PostgreSQL")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parent.parent / "data" / "health_ai.db"),
                        help="SQLite backup (.db) or plain pg_dump (.sql)")
    parser.add_argument("--map", action="append", default=[], metavar="OLD=NEW",
                        help="Alias for a legacy hospital name (repeatable)")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL (default is a dry run)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace stored values that differ from the backup")
    parser.add_argument("--recompute", action="store_true",
                        help="Rebuild quality/anomaly/validation results after inserting")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"Backup not found: {source}")
        return 1

    rows = read_source(source)
    print(f"Backup values: {len(rows)}  ({source})")
    if not rows:
        print("Nothing to restore.")
        return 0

    session = SessionLocal()
    try:
        resolved, unresolved, ambiguous = resolve_hospitals(session, rows, parse_maps(args.map))
        print(f"Hospitals matched: {len(resolved)}")
        for label in unresolved:
            count = sum(1 for row in rows if (row["hospital_org"] or row["hospital_name"]) == label)
            print(f"  UNMATCHED ({count} values): {label}")
        for label in ambiguous:
            print(f"  AMBIGUOUS (skipped): {label}")

        matched_rows = [
            row for row in rows if (row["hospital_org"] or row["hospital_name"]) in resolved
        ]
        print(f"Values eligible: {len(matched_rows)}")

        if not args.apply:
            stats = defaultdict(int)
            for row in matched_rows:
                stats[row["hospital_org"] or row["hospital_name"]] += 1
            for label in sorted(stats):
                print(f"  would restore {stats[label]:5}  {label}")
            print("\nDry run — re-run with --apply to write.")
            return 0

        inserted, updated, already, unknown = insert_values(
            session, matched_rows, resolved, overwrite=args.overwrite
        )
        active = reactivate(session, sorted(set(resolved.values())))
        session.commit()
        print(f"\nInserted {inserted}, updated {updated}, already present {already}, "
              f"unknown indicator {unknown}")
        print(f"Hospitals re-activated: {active}")

        if args.recompute:
            print("\nRecomputing derived results…")
            recompute(session, sorted(set(resolved.values())))
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
