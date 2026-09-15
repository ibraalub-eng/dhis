"""Verify startup self-heals partially-migrated DBs missing permission rows.

The deployed PostgreSQL can be stamped at alembic head while row inserts from
migrations were never applied (see 6128ff7). Grants only link existing rows,
so a missing `dashboard.write` row silently yields "Missing permission:
dashboard.write" 403s for every non-superuser. _ensure_admin_user must create
missing rows AND grant them to the admin role.
"""
from app.main import _ensure_admin_user, CANONICAL_PERMISSION_CODENAMES
from app.models import User, Role, Permission


def _recreate_admin_state(session, include_dashboard_write=True):
    """Rebuild users/roles/permissions to the token state of a prod DB."""
    # Clear auth-touching rows (fixtures create tables, not rows for auth)
    session.query(User).delete()
    session.execute(Role.__table__.delete())
    session.execute(Permission.__table__.delete())

    # Seeded permission rows (simulate what migrations actually inserted)
    base_codes = ['analysis.read', 'settings.read', 'settings.write',
                  'system.manage_users', 'data.read']
    for code in base_codes:
        session.add(Permission(codename=code))
    # Optionally omit dashboard.write entirely (the reported prod symptom)
    if include_dashboard_write:
        session.add(Permission(codename='dashboard.write'))

    sa_role = Role(name='superadmin', description='Super administrator', is_system=True)
    admin_role = Role(name='admin', description='Administrator', is_system=True)
    session.add_all([sa_role, admin_role])
    session.flush()

    # Link whatever permission rows currently exist to the roles, mimicking a
    # DB that pre-dates the dashboard.write migration.
    perms = session.query(Permission).all()
    sa_role.permissions = perms
    admin_role.permissions = [p for p in perms]

    session.commit()
    session.flush()


class TestStartupPermissionHeal:
    def test_heals_missing_dashboard_write_row_for_admin_role(self, db_session):
        _recreate_admin_state(db_session, include_dashboard_write=False)

        # Sanity: admin role must NOT have dashboard.write before the heal.
        admin_role = db_session.query(Role).filter_by(name='admin').first()
        admin_codes = {p.codename for p in admin_role.permissions}
        assert 'dashboard.write' not in admin_codes

        _ensure_admin_user(db_session)

        # Permission row now exists.
        perm = db_session.query(Permission).filter_by(codename='dashboard.write').first()
        assert perm is not None

        # ...and the admin role has been granted it.
        admin_role = db_session.query(Role).filter_by(name='admin').first()
        admin_codes = {p.codename for p in admin_role.permissions}
        assert 'dashboard.write' in admin_codes

    def test_no_op_when_rows_already_present(self, db_session):
        _recreate_admin_state(db_session, include_dashboard_write=True)

        admin_role = db_session.query(Role).filter_by(name='admin').first()
        assert 'dashboard.write' in {p.codename for p in admin_role.permissions}

        _ensure_admin_user(db_session)

        admin_role = db_session.query(Role).filter_by(name='admin').first()
        assert 'dashboard.write' in {p.codename for p in admin_role.permissions}

    def test_all_canonical_rows_exist_after_heal(self, db_session):
        _recreate_admin_state(db_session, include_dashboard_write=False)
        _ensure_admin_user(db_session)

        existing = {row[0] for row in db_session.query(Permission.codename).all()}
        for code in CANONICAL_PERMISSION_CODENAMES:
            assert code in existing, f'missing canonical permission row: {code}'