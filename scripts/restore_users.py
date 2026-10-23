#!/usr/bin/env python3
"""Restore users, roles and their grants from a plain pg_dump.

A database reset that re-runs the seeds leaves only the four demo accounts
(admin / superadmin / doctor / viewer). Staff accounts created in the real
system disappear, so their owners cannot log in — the login endpoint answers
"Invalid credentials" for a username that no longer exists.

This script copies the account layer back from a dump:

* ``permissions``      — missing codenames,
* ``roles``            — missing role names,
* ``role_permissions`` — role grants,
* ``users``            — missing usernames (password hash included, so the
                          original password keeps working),
* ``user_roles``       — role assignments,
* ``user_hospitals``   — hospital assignments (mapped by organisation unit),
* ``user_permissions`` — direct grants.

Existing usernames are never modified, so the current admin password and
flags stay untouched. Everything is insert-only and safe to re-run.

Usage::

    python scripts/restore_users.py --source C:/path/dhis_prod_snapshot.sql
    python scripts/restore_users.py --source C:/path/dhis_prod_snapshot.sql --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine
from app.models import Hospital, Permission, Role, User, user_hospitals

NULL = "\\N"


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore users/roles/grants from a pg_dump")
    parser.add_argument("--source", required=True, help="plain pg_dump (.sql) file")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL (default is a dry run)")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"Backup not found: {source}")
        return 1

    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    users = block(lines, "users")
    roles = block(lines, "roles")
    permissions = block(lines, "permissions")
    role_permissions = block(lines, "role_permissions")
    user_roles = block(lines, "user_roles")
    user_hospitals_rows = block(lines, "user_hospitals")
    user_permissions_rows = block(lines, "user_permissions")
    hospitals = block(lines, "hospitals")

    session = SessionLocal()
    try:
        existing_users = {u.username for u in session.query(User).all()}
        existing_roles = {r.name: r for r in session.query(Role).all()}
        existing_permissions = {p.codename: p for p in session.query(Permission).all()}

        missing_users = [u for u in users if u["username"] not in existing_users]
        missing_roles = [r for r in roles if r["name"] not in existing_roles]
        missing_permissions = [p for p in permissions if p["codename"] not in existing_permissions]

        print(f"Users to restore: {len(missing_users)}")
        for user in missing_users:
            print(f"  {user['username']:20} super={user['is_superuser']} active={user['is_active']}")
        print(f"Roles to restore: {len(missing_roles)} -> {[r['name'] for r in missing_roles]}")
        print(f"Permissions missing: {len(missing_permissions)}")
        print(f"Grants: role_permissions={len(role_permissions)}, user_roles={len(user_roles)}, "
              f"user_hospitals={len(user_hospitals_rows)}, user_permissions={len(user_permissions_rows)}")

        if not args.apply:
            print("\nDry run — re-run with --apply to write.")
            return 0

        # Permissions and roles first: grants reference them.
        for row in missing_permissions:
            permission = Permission(
                codename=row["codename"],
                description=None if row.get("description") == NULL else row.get("description"),
            )
            session.add(permission)
            existing_permissions[row["codename"]] = permission
        for row in missing_roles:
            role = Role(
                name=row["name"],
                description=None if row.get("description") == NULL else row.get("description"),
                is_system=row.get("is_system") == "t",
            )
            session.add(role)
            existing_roles[row["name"]] = role
        session.flush()

        snapshot_roles = {row["id"]: row["name"] for row in roles}
        snapshot_permissions = {row["id"]: row["codename"] for row in permissions}

        for row in role_permissions:
            role = existing_roles.get(snapshot_roles.get(row["role_id"]))
            permission = existing_permissions.get(snapshot_permissions.get(row["permission_id"]))
            if role is not None and permission is not None and permission not in role.permissions:
                role.permissions.append(permission)

        snapshot_users = {row["id"]: row["username"] for row in users}
        user_objects = {u.username: u for u in session.query(User).all()}

        for row in missing_users:
            user = User(
                username=row["username"],
                email=None if row.get("email") == NULL else row.get("email"),
                full_name=None if row.get("full_name") == NULL else row.get("full_name"),
                password_hash=row["password_hash"],
                is_active=row["is_active"] == "t",
                is_superuser=row["is_superuser"] == "t",
            )
            session.add(user)
            session.flush()
            user_objects[user.username] = user

        for row in user_roles:
            user = user_objects.get(snapshot_users.get(row["user_id"]))
            role = existing_roles.get(snapshot_roles.get(row["role_id"]))
            if user is not None and role is not None and role not in user.roles:
                user.roles.append(role)

        for row in user_permissions_rows:
            user = user_objects.get(snapshot_users.get(row["user_id"]))
            permission = existing_permissions.get(snapshot_permissions.get(row["permission_id"]))
            if user is not None and permission is not None and permission not in user.permissions:
                user.permissions.append(permission)

        # Hospital assignments are keyed by snapshot hospital id; map by org unit.
        by_org = {h.organisation_unit_id: h.id for h in session.query(Hospital).all() if h.organisation_unit_id}
        snapshot_orgs = {row["id"]: row.get("organisation_unit_id", NULL) for row in hospitals}
        existing_assignments = {
            (row[0], row[1]) for row in session.execute(
                user_hospitals.select().with_only_columns(
                    user_hospitals.c.user_id, user_hospitals.c.hospital_id
                )
            ).all()
        }
        added = 0
        for row in user_hospitals_rows:
            user = user_objects.get(snapshot_users.get(row["user_id"]))
            org = snapshot_orgs.get(row["hospital_id"])
            hospital_id = by_org.get(org) if org and org != NULL else None
            if user is None or hospital_id is None:
                continue
            key = (user.id, hospital_id)
            if key in existing_assignments:
                continue
            existing_assignments.add(key)
            session.execute(user_hospitals.insert().values(user_id=user.id, hospital_id=hospital_id))
            added += 1

        session.commit()
        print(f"Committed: {len(missing_users)} users, {len(missing_roles)} roles, "
              f"{len(missing_permissions)} permissions, {added} hospital assignments.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
