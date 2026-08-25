"""Test hospital filtering by user role/assignment.
Overrides conftest's _bypass_auth to test real JWT-based auth."""
import pytest
from app.main import app
from app.database import get_db, Base
from app.models import User, Role, Permission, Hospital, user_hospitals
from app.core.security import hash_password
from app.core.deps import get_current_user
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from scripts.seed_indicators import seed_indicators
from scripts.seed_rules import seed_rules


@pytest.fixture(autouse=True)
def _reapply_overrides(app, _bypass_auth):
    """After conftest's _bypass_auth runs, clear its overrides so real auth is used."""
    app.dependency_overrides.pop(get_current_user, None)
    # Also invalidate the in-memory cache so each test starts fresh
    from app.cache import cache
    cache.invalidate()
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app, db_session):
    """Uses conftest's db_session but with real JWT auth (no bypass)."""
    # db_session from conftest already has the schema
    # Seed test users into conftest's db_session
    sess = db_session
    seed_indicators(sess)
    seed_rules(sess)

    all_perms = ['hospitals.read','hospitals.write','dashboard.read','analysis.read',
                 'quality.read','outliers.read','clinical.read','alerts.read',
                 'smart_analytics.read','rules.read','root_cause.read','audit.read',
                 'settings.read','settings.write','system.manage_users',
                 'system.read_audit','system.manage_data','system.export_data']
    super_role = Role(name='superadmin', is_system=True)
    for code in all_perms:
        p = sess.query(Permission).filter(Permission.codename==code).first()
        if not p:
            p = Permission(codename=code, description=code)
            sess.add(p)
            sess.flush()
        super_role.permissions.append(p)
    sess.add(super_role)
    sess.flush()

    doc_role = Role(name='doctor')
    for code in ['hospitals.read','dashboard.read','analysis.read','quality.read','clinical.read','alerts.read']:
        p = sess.query(Permission).filter(Permission.codename==code).first()
        if not p:
            p = Permission(codename=code, description=code)
            sess.add(p)
            sess.flush()
        doc_role.permissions.append(p)
    sess.add(doc_role)
    sess.flush()

    vw_role = Role(name='viewer')
    vw_code = sess.query(Permission).filter(Permission.codename=='hospitals.read').first()
    vw_role.permissions.append(vw_code)
    sess.add(vw_role)
    sess.flush()

    for uname, role, is_sup in [('superadmin', super_role, True), ('doctor', doc_role, False), ('viewer', vw_role, False)]:
        if not sess.query(User).filter(User.username==uname).first():
            sess.add(User(username=uname, email=uname+'@test.com', full_name=uname.title(),
                          password_hash=hash_password('admin123'), is_superuser=is_sup, roles=[role]))
    for nm in ['Hospital Alpha','Hospital Beta','Hospital Gamma']:
        if not sess.query(Hospital).filter(Hospital.name==nm).first():
            sess.add(Hospital(name=nm, is_active=True))
    sess.commit()

    c = TestClient(app, raise_server_exceptions=False)
    yield c


def login(c, u, pw='admin123'):
    r = c.post('/auth/login', json={'username': u, 'password': pw, 'remember_me': True})
    assert r.status_code == 200, 'Login ' + u + ' failed: ' + str(r.status_code) + ' ' + r.text[:200]
    return r.json()['access_token']

def ag(c, t, p):
    return c.get(p, headers={'Authorization': 'Bearer ' + t})


class TestHospitalFiltering:
    def test_all_roles_login(self, client):
        for u in ['superadmin', 'doctor', 'viewer']:
            assert login(client, u)

    def test_superadmin_sees_all(self, client):
        t = login(client, 'superadmin')
        r = ag(client, t, '/hospitals/')
        assert r.status_code == 200 and len(r.json()) >= 3

    def test_doctor_unrestricted(self, client):
        t = login(client, 'doctor')
        r = ag(client, t, '/hospitals/')
        assert r.status_code == 200 and len(r.json()) >= 3

    def test_doctor_restricted(self, client):
        sa = login(client, 'superadmin')
        r = ag(client, sa, '/hospitals/')
        all_h = r.json()
        r2 = ag(client, sa, '/admin/users')
        doc = next(u for u in r2.json()['users'] if u['username'] == 'doctor')
        ids = [all_h[0]['id'], all_h[1]['id']]
        r3 = client.put('/admin/users/' + str(doc['id']) + '/hospitals',
                        json={'hospital_ids': ids},
                        headers={'Authorization': 'Bearer ' + sa})
        assert r3.status_code == 200, r3.text[:200]
        r4 = ag(client, login(client, 'doctor'), '/hospitals/')
        assert len(r4.json()) == 2, 'Expected 2, got ' + str(len(r4.json()))

    def test_remove_restriction(self, client):
        sa = login(client, 'superadmin')
        r = ag(client, sa, '/hospitals/')
        n = len(r.json())
        r2 = ag(client, sa, '/admin/users')
        doc = next(u for u in r2.json()['users'] if u['username'] == 'doctor')
        client.put('/admin/users/' + str(doc['id']) + '/hospitals',
                   json={'hospital_ids': []},
                   headers={'Authorization': 'Bearer ' + sa})
        r3 = ag(client, login(client, 'doctor'), '/hospitals/')
        assert len(r3.json()) == n

    def test_viewer_restricted(self, client):
        sa = login(client, 'superadmin')
        r = ag(client, sa, '/hospitals/')
        fid = r.json()[0]['id']
        r2 = ag(client, sa, '/admin/users')
        vw = next(u for u in r2.json()['users'] if u['username'] == 'viewer')
        client.put('/admin/users/' + str(vw['id']) + '/hospitals',
                   json={'hospital_ids': [fid]},
                   headers={'Authorization': 'Bearer ' + sa})
        r3 = ag(client, login(client, 'viewer'), '/hospitals/')
        assert len(r3.json()) == 1, 'Expected 1, got ' + str(len(r3.json()))

    def test_viewer_no_admin(self, client):
        assert ag(client, login(client, 'viewer'), '/admin/users').status_code == 403

    def test_auth_me(self, client):
        for u in ['superadmin', 'doctor', 'viewer']:
            r = ag(client, login(client, u), '/auth/me')
            assert r.status_code == 200 and 'roles' in r.json()

    def test_password_change(self, client):
        sa = login(client, 'superadmin')
        r = ag(client, sa, '/admin/users')
        doc = next(u for u in r.json()['users'] if u['username'] == 'doctor')
        r2 = client.post('/admin/users/' + str(doc['id']) + '/change-password',
                         json={'new_password': 'newpw123', 'confirm_password': 'newpw123'},
                         headers={'Authorization': 'Bearer ' + sa})
        assert r2.status_code == 200 and r2.json()['success'] == True
        assert login(client, 'doctor', 'newpw123')
        assert client.post('/auth/login', json={'username': 'doctor', 'password': 'admin123'}).status_code != 200

    def test_visibility_matrix(self, client):
        sa = login(client, 'superadmin')
        r = ag(client, sa, '/admin/visibility-matrix')
        assert r.status_code == 200 and len(r.json()['roles']) >= 2
