#!/usr/bin/env python3
"""Restore indicator configuration and catalog rows from a plain pg_dump.

The completeness denominator is built from the indicator catalog plus the
enable/disable configuration:

* ``indicators``               — the catalog (a dropped data element is a
                                 permanently missing value),
* ``hospital_indicator_config`` — per-hospital enable/disable overrides,
* ``indicator_default_config``  — All-Hospitals defaults per month,
* ``rules``                     — coverage/validation rules.

A database reset silently empties those tables while the monthly values are
restored later, which makes completeness drop: every indicator is suddenly
required again. This script copies the rows back, matching hospitals by DHIS
``organisation_unit_id`` and indicators/rules by their stable code. It only
inserts missing rows and never deletes or overwrites anything, so it is safe
to re-run.

Usage::

    python scripts/restore_indicator_config.py --source C:/path/dhis_prod_snapshot.sql
    python scripts/restore_indicator_config.py --source C:/path/dhis_prod_snapshot.sql --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal, engine
from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    Rule,
)

NULL = "\\N"


def block(lines: list[str], table: str) -> tuple[list[str], list[list[str]]]:
    prefix = f"COPY public.{table} "
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        return [], []
    columns = lines[start][lines[start].index("(") + 1: lines[start].rindex(")")].split(", ")
    rows = []
    for line in lines[start + 1:]:
        if line == "\\.":
            break
        rows.append(line.split("\t"))
    return columns, rows



def main() -> int:
    parser = argparse.ArgumentParser(description="Restore indicator catalog + config from a pg_dump")
    parser.add_argument("--source", required=True, help="plain pg_dump (.sql) file")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL (default is a dry run)")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"Backup not found: {source}")
        return 1

    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    _, hospital_rows = block(lines, "hospitals")
    _, indicator_rows = block(lines, "indicators")
    _, config_rows = block(lines, "hospital_indicator_config")
    _, default_rows = block(lines, "indicator_default_config")
    _, rule_rows = block(lines, "rules")

    snapshot_hospitals = {}
    for row in hospital_rows:
        org = row[8] if len(row) > 8 and row[8] != NULL else None
        snapshot_hospitals[row[0]] = {"name": row[1], "org": org}
    snapshot_indicators = {row[0]: {"code": row[1], "name": row[2], "parent_id": row[3],
                                    "level": row[4], "sort_order": row[5], "group_name": row[6],
                                    "formula": row[7], "default_weight": row[8]}
                           for row in indicator_rows}

    session = SessionLocal()
    try:
        by_org = {h.organisation_unit_id: h for h in session.query(Hospital).all() if h.organisation_unit_id}
        by_code = {i.code: i for i in session.query(Indicator).all()}
        existing_rules = {code for (code,) in session.query(Rule.code).all()}

        # 1. Catalog rows the current database no longer has (e.g. 11.c).
        missing_indicators = [row for row in indicator_rows if row[1] not in by_code]
        print(f"Catalog rows missing: {len(missing_indicators)}")
        for row in missing_indicators:
            print(f"  {row[1]}  {row[2]}")

        # 2. Per-hospital enable/disable rows that can be mapped.
        # Keyed by SNAPSHOT hospital id (the config row's hospital_id column),
        # never by the config row's own primary key.
        hopital_map = {}
        for row in config_rows:
            snap_hospital = snapshot_hospitals.get(row[1])
            org = snap_hospital["org"] if snap_hospital else None
            current = by_org.get(org)
            if current is not None:
                hopital_map[row[1]] = current.id
        mapped_config = [
            row for row in config_rows
            if row[1] in hopital_map and snapshot_indicators.get(row[2], {}).get("code") in by_code
        ]
        disabled = sum(1 for row in mapped_config if row[3] == "f")
        unmapped_config = len(config_rows) - len(mapped_config)
        print(f"Per-hospital config rows: {len(config_rows)} "
              f"(mappable {len(mapped_config)}, {disabled} disabling, skipped {unmapped_config})")

        mapped_defaults = [
            row for row in default_rows
            if snapshot_indicators.get(row[1], {}).get("code") in by_code
        ]
        print(f"Monthly default rows: {len(default_rows)} (mappable {len(mapped_defaults)})")

        missing_rules = [row for row in rule_rows if row[1] not in existing_rules]
        print(f"Rules missing: {len(missing_rules)}")
        for row in missing_rules:
            print(f"  {row[1]}  {row[2]}")

        if not args.apply:
            print("\nDry run — re-run with --apply to write.")
            return 0

        # Insert catalog rows first, resolving parent_id through the code map.
        inserted_indicators = 0
        for row in missing_indicators:
            code = row[1]
            if code in by_code:
                continue
            parent_code = snapshot_indicators.get(row[3], {}).get("code") if row[3] != NULL else None
            parent = by_code.get(parent_code) if parent_code else None
            indicator = Indicator(
                code=code,
                name=row[2],
                parent_id=parent.id if parent else None,
                level=int(row[4]) if row[4] != NULL else 0,
                sort_order=int(row[5]) if row[5] != NULL else 0,
                group_name=None if row[6] == NULL else row[6],
                formula=None if row[7] == NULL else row[7],
                default_weight=float(row[8]) if row[8] != NULL else 1.0,
            )
            session.add(indicator)
            session.flush()
            by_code[code] = indicator
            inserted_indicators += 1
        print(f"Inserted catalog rows: {inserted_indicators}")

        # Existing config pairs, so re-runs are no-ops.
        existing_config = {
            (row.hospital_id, row.indicator_id)
            for row in session.query(HospitalIndicatorConfig).all()
        }
        config_payload = []
        for row in mapped_config:
            code = snapshot_indicators[row[2]]["code"]
            hospital_id = hopital_map[row[1]]
            indicator_id = by_code[code].id
            if (hospital_id, indicator_id) in existing_config:
                continue
            existing_config.add((hospital_id, indicator_id))
            config_payload.append({
                "hospital_id": hospital_id,
                "indicator_id": indicator_id,
                "is_enabled": row[3] == "t",
                "weight_override": None if row[4] == NULL else float(row[4]),
            })
        if config_payload:
            statement = insert(HospitalIndicatorConfig).values(config_payload)
            statement = statement.on_conflict_do_nothing(index_elements=["hospital_id", "indicator_id"])
            session.execute(statement)
        print(f"Inserted per-hospital config rows: {len(config_payload)}")

        existing_defaults = {
            (row.indicator_id, row.month) for row in session.query(IndicatorDefaultConfig).all()
        }
        default_payload = []
        for row in mapped_defaults:
            code = snapshot_indicators[row[1]]["code"]
            indicator_id = by_code[code].id
            if (indicator_id, row[2]) in existing_defaults:
                continue
            existing_defaults.add((indicator_id, row[2]))
            default_payload.append({
                "indicator_id": indicator_id,
                "month": row[2],
                "is_enabled": row[3] == "t",
                "weight_override": None if row[4] == NULL else float(row[4]),
            })
        if default_payload:
            statement = insert(IndicatorDefaultConfig).values(default_payload)
            statement = statement.on_conflict_do_nothing(index_elements=["indicator_id", "month"])
            session.execute(statement)
        print(f"Inserted monthly default rows: {len(default_payload)}")

        inserted_rules = 0
        for row in missing_rules:
            session.add(Rule(
                code=row[1],
                name=row[2],
                rule_type=row[3],
                severity=row[4],
                category=row[5],
                expression_type=row[6],
                params=None if row[7] == NULL else row[7],
                description="" if len(row) < 9 or row[8] == NULL else row[8],
                enabled=(len(row) < 10 or row[9] == "t"),
                sort_order=int(row[10]) if len(row) > 10 and row[10] != NULL else 0,
            ))
            inserted_rules += 1
        print(f"Inserted rules: {inserted_rules}")

        session.commit()
        print("Committed.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
