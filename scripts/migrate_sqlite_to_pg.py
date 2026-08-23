#!/usr/bin/env python3
"""Migrate data from local SQLite to Render PostgreSQL.

Usage:
    # Set your PostgreSQL connection string (from Render dashboard → Settings → DATABASE_URL):
    export DATABASE_URL="postgresql://user:pass@host:5432/health_ai"

    # Make sure Alembic migrations have run on PostgreSQL (happens automatically on Render deploy).
    # For local testing, run first:
    #   alembic upgrade head

    # Then run:
    python scripts/migrate_sqlite_to_pg.py

    # Or point to a specific SQLite file:
    python scripts/migrate_sqlite_to_pg.py --sqlite data/health_ai.db
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.orm import sessionmaker

# ── Tables in foreign-key insertion order ──
TABLES_IN_ORDER = [
    "governorates",
    "hospital_types",
    "facility_ownerships",
    "facility_types",
    "hospitals",
    "indicators",
    "hospital_indicator_config",
    "indicator_values",
    "rules",
    "validation_results",
    "anomaly_results",
    "quality_scores",
    "clinical_insights",
    "confidence_scores",
    "confidence_weights",
    "app_config",
    "analysis_cache",
    "system_settings",
]

# Tables with auto-increment PKs that need ID remapping for FK references
# Maps: table_name -> list of (column_name, referencing_table, referencing_column)
FK_MAP = [
    ("hospitals", "governorate_id", "governorates", "id"),
    ("hospitals", "hospital_type_id", "hospital_types", "id"),
    ("hospitals", "facility_ownership_id", "facility_ownerships", "id"),
    ("hospitals", "facility_type_id", "facility_types", "id"),
    ("indicators", "parent_id", "indicators", "id"),
    ("hospital_indicator_config", "hospital_id", "hospitals", "id"),
    ("hospital_indicator_config", "indicator_id", "indicators", "id"),
    ("indicator_values", "hospital_id", "hospitals", "id"),
    ("indicator_values", "indicator_id", "indicators", "id"),
    ("validation_results", "hospital_id", "hospitals", "id"),
    ("anomaly_results", "hospital_id", "hospitals", "id"),
    ("quality_scores", "hospital_id", "hospitals", "id"),
    ("clinical_insights", "hospital_id", "hospitals", "id"),
    ("confidence_scores", "hospital_id", "hospitals", "id"),
]


def get_engine(url):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def read_sqlite_data(sqlite_path):
    """Read all tables from SQLite, return {table_name: [row_dicts]}."""
    url = f"sqlite:///{sqlite_path}"
    engine = get_engine(url)
    inspector = inspect(engine)

    data = {}
    for table in TABLES_IN_ORDER:
        if table not in inspector.get_table_names():
            print(f"  ⚠  SQLite table '{table}' not found — skipping")
            continue
        with engine.connect() as conn:
            rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
            cols = [c["name"] for c in inspector.get_columns(table)]
            data[table] = [dict(zip(cols, row)) for row in rows]
            print(f"  ✓  {table}: {len(data[table])} rows")
    return data


def clear_pg_tables(pg_engine):
    """Truncate all tables in PG (respecting FK order)."""
    with pg_engine.connect() as conn:
        for table in reversed(TABLES_IN_ORDER):
            try:
                conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
            except Exception:
                pass
        conn.commit()
    print("  ✓  Cleared PostgreSQL tables")


def insert_data(pg_engine, data):
    """Insert data into PostgreSQL with ID remapping for FKs."""
    inspector = inspect(pg_engine)
    existing_tables = set(inspector.get_table_names())

    # id_map[table_name] = {old_id: new_id}
    id_map = {}

    for table in TABLES_IN_ORDER:
        if table not in data or not data[table]:
            continue
        if table not in existing_tables:
            print(f"  ⚠  PG table '{table}' not found — skipping")
            continue

        rows = data[table]
        cols_info = {c["name"]: c for c in inspector.get_columns(table)}
        pk_col = "id" if "id" in cols_info else None

        # Remap FK IDs
        for row in rows:
            for src_table, fk_col, ref_table, ref_col in FK_MAP:
                if src_table == table and fk_col in row and row[fk_col] is not None:
                    old_fk = row[fk_col]
                    if ref_table in id_map and old_fk in id_map[ref_table]:
                        row[fk_col] = id_map[ref_table][old_fk]

        # Insert in batches
        cols = [c for c in cols_info.keys() if any(c in row for row in rows)]
        new_id_map = {}
        batch_size = 500

        with pg_engine.connect() as conn:
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                for row in batch:
                    filtered = {k: v for k, v in row.items() if k in cols and k in cols_info}
                    # Convert dict/list values to JSON strings for Text columns
                    for k, v in filtered.items():
                        if isinstance(v, (dict, list)):
                            import json
                            filtered[k] = json.dumps(v, ensure_ascii=False)

                    if pk_col and pk_col in filtered:
                        old_id = filtered.pop(pk_col)
                        try:
                            result = conn.execute(
                                text(f'INSERT INTO "{table}" ({", ".join(f"{c}" for c in filtered.keys())}) '
                                     f'VALUES ({", ".join(f":{c}" for c in filtered.keys())}) '
                                     f'RETURNING "{pk_col}"'),
                                filtered,
                            )
                            new_id = result.scalar()
                            new_id_map[old_id] = new_id
                        except Exception as e:
                            # Try without RETURNING (some columns like system_settings use non-int PKs)
                            try:
                                conn.execute(
                                    text(f'INSERT INTO "{table}" ({", ".join(f"{c}" for c in filtered.keys())}) '
                                         f'VALUES ({", ".join(f":{c}" for c in filtered.keys())})'),
                                    filtered,
                                )
                                if pk_col == "key":
                                    # system_settings uses string PK
                                    new_id_map[old_id] = old_id
                            except Exception as e2:
                                print(f"  ⚠  Failed to insert into {table}: {e2}")
                                continue
                    else:
                        try:
                            conn.execute(
                                text(f'INSERT INTO "{table}" ({", ".join(f"{c}" for c in filtered.keys())}) '
                                     f'VALUES ({", ".join(f":{c}" for c in filtered.keys())})'),
                                filtered,
                            )
                        except Exception as e:
                            print(f"  ⚠  Failed to insert into {table}: {e}")
                            continue
                conn.commit()

        if pk_col:
            id_map[table] = new_id_map
        print(f"  ✓  {table}: {len(rows)} rows inserted")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "health_ai.db"),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--pg-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL connection URL (or set DATABASE_URL env var)",
    )
    parser.add_argument(
        "--skip-clear",
        action="store_true",
        help="Skip clearing PG tables before insert (append mode)",
    )
    args = parser.parse_args()

    if not args.pg_url:
        print("❌ No PostgreSQL URL provided.\n"
              "   Set DATABASE_URL or pass --pg-url\n"
              "   Example: export DATABASE_URL='postgresql://user:pass@host:5432/health_ai'")
        sys.exit(1)

    if not os.path.exists(args.sqlite):
        print(f"❌ SQLite file not found: {args.sqlite}")
        sys.exit(1)

    print("=" * 60)
    print("  SQLite → PostgreSQL Migration")
    print("=" * 60)

    # Read SQLite
    print(f"\n📖 Reading SQLite: {args.sqlite}")
    data = read_sqlite_data(args.sqlite)
    total_rows = sum(len(v) for v in data.values())
    print(f"   Total: {total_rows} rows across {len(data)} tables")

    # Connect to PG
    print(f"\n🔌 Connecting to PostgreSQL...")
    pg_engine = get_engine(args.pg_url)
    with pg_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("   ✓  Connected")

    # Clear PG (optional)
    if not args.skip_clear:
        print(f"\n🗑  Clearing PostgreSQL tables...")
        clear_pg_tables(pg_engine)

    # Insert
    print(f"\n📥 Inserting data into PostgreSQL...")
    insert_data(pg_engine, data)

    print(f"\n{'=' * 60}")
    print(f"  ✅ Migration complete!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
