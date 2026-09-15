"""Verify that /analysis/reanalyze-all requires dashboard.write.

Matching /dashboard/recalculate-completeness which also requires dashboard.write.
Viewer and doctor roles (no dashboard.write) must get 403.
Admin role and superadmin (both have dashboard.write) must get 200.
"""
import pytest
from unittest.mock import patch
from app.main import app
from app.database import get_db
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.models import User, Role, Permission
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_bypass(app, _bypass_auth):
    """Remove conftest's FakeSuperAdmin so real JWT auth is tested."""
    app.dependency_overrides.pop(get_current_user, None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app, db_session):
    sess = db_session

    def override_get_db():
        try:
            yield sess
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Seed permissions
    for code in ['analysis.read', 'dashboard.write', 'settings.read']:
        if not sess.query(Permission).filter_by(codename=code).first():
            sess.add(Permission(codename=code))
            sess.flush()

    read_perm = sess.query(Permission).filter_by(codename='analysis.read').first()
    write_perm = sess.query(Permission).filter_by(codename='dashboard.write').first()

    # Viewer role: analysis.read only
    viewer_role = Role(name='test_viewer')
    viewer_role.permissions.append(read_perm)
    sess.add(viewer_role)
    sess.flush()

    # Admin role: analysis.read + dashboard.write
    admin_role = Role(name='test_admin')
    admin_role.permissions.extend([read_perm, write_perm])
    sess.add(admin_role)
    sess.flush()

    # Users
    viewer = User(username='viewer', email='viewer@test.com', full_name='Viewer',
                  password_hash=hash_password('test123'), roles=[viewer_role])
    admin = User(username='admin_user', email='admin@test.com', full_name='Admin',
                 password_hash=hash_password('test123'), roles=[admin_role])
    superadmin = User(username='superadmin', email='sa@test.com', full_name='SA',
                      password_hash=hash_password('test123'), is_superuser=True)
    sess.add_all([viewer, admin, superadmin])
    sess.commit()

    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


def _login(client, username, password='test123'):
    r = client.post('/auth/login', json={'username': username, 'password': password})
    assert r.status_code == 200, f'Login {username} failed: {r.status_code}'
    return r.json()['access_token']


def _post_reanalyze(client, token):
    return client.post(
        '/analysis/reanalyze-all',
        params={'force': 'true'},
        headers={'Authorization': f'Bearer {token}'},
    )


class TestReanalyzePermissions:
    def test_viewer_gets_403(self, client):
        token = _login(client, 'viewer')
        resp = _post_reanalyze(client, token)
        assert resp.status_code == 403

    def test_admin_with_dashboard_write_gets_200(self, client):
        token = _login(client, 'admin_user')
        with patch('app.api.analysis._run_reanalyze_all', return_value={'analyzed': 0, 'skipped': 0}):
            resp = _post_reanalyze(client, token)
        assert resp.status_code == 200
        data = resp.json()
        assert 'task_id' in data

    def test_superadmin_gets_200(self, client):
        token = _login(client, 'superadmin')
        with patch('app.api.analysis._run_reanalyze_all', return_value={'analyzed': 0, 'skipped': 0}):
            resp = _post_reanalyze(client, token)
        assert resp.status_code == 200
        data = resp.json()
        assert 'task_id' in data
