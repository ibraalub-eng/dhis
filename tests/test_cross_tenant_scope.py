"""Cross-tenant scoping regression tests (Batch 4 hardening).

A restricted (hospital-scoped) user must NOT be able to read report or
dashboard data belonging to a hospital outside their assignment. The
endpoints under test return 403 before touching per-hospital data.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.core.security import hash_password
from app.models import Hospital, Permission, Role, User


@pytest.fixture(autouse=True)
def _reapply_overrides(app, _bypass_auth):
    """Clear conftest's FakeSuperAdmin so real JWT auth + scoping run."""
    app.dependency_overrides.pop(get_current_user, None)
    from app.cache import cache
    cache.invalidate()
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app, db_session):
    sess = db_session

    perms = ['dashboard.read', 'analysis.read', 'hospitals.read', 'reports.read']
    perm_objs = {}
    for code in perms:
        p = sess.query(Permission).filter(Permission.codename == code).first()
        if not p:
            p = Permission(codename=code, description=code)
            sess.add(p)
            sess.flush()
        perm_objs[code] = p

    super_role = Role(name='scope_super', is_system=True)
    super_role.permissions.extend(perm_objs.values())
    doc_role = Role(name='scope_doctor')
    doc_role.permissions.extend([perm_objs['dashboard.read'], perm_objs['analysis.read'], perm_objs['hospitals.read']])
    sess.add_all([super_role, doc_role])
    sess.flush()

    sess.add_all([
        User(username='scope_sa', email='sa@scope.test', full_name='SA',
             password_hash=hash_password('pw12345'), is_superuser=True, roles=[super_role]),
        User(username='scope_doc', email='doc@scope.test', full_name='Doc',
             password_hash=hash_password('pw12345'), roles=[doc_role]),
    ])
    sess.add_all([Hospital(name='Scope A', is_active=True), Hospital(name='Scope B', is_active=True)])
    sess.commit()

    c = TestClient(app, raise_server_exceptions=False)
    yield c


def _login(c, u):
    r = c.post('/auth/login', json={'username': u, 'password': 'pw12345'})
    assert r.status_code == 200, f'login {u}: {r.status_code} {r.text[:200]}'
    return r.json()['access_token']


def _hdr(t):
    return {'Authorization': f'Bearer {t}'}


def _hospital_ids(c, sa_token):
    r = c.get('/hospitals/', headers=_hdr(sa_token))
    assert r.status_code == 200, r.text[:200]
    by_name = {h['name']: h['id'] for h in r.json()}
    return by_name['Scope A'], by_name['Scope B']


def _scope_doctor_to(c, sa_token, hid):
    users = c.get('/admin/users', headers=_hdr(sa_token)).json()['users']
    doc = next(u for u in users if u['username'] == 'scope_doc')
    r = c.put(f"/admin/users/{doc['id']}/hospitals", json={'hospital_ids': [hid]}, headers=_hdr(sa_token))
    assert r.status_code == 200, r.text[:200]


class TestCrossTenantScope:
    def test_reports_generate_out_of_scope_403(self, client):
        sa = _login(client, 'scope_sa')
        a, b = _hospital_ids(client, sa)
        _scope_doctor_to(client, sa, a)
        doc = _login(client, 'scope_doc')
        r = client.get(f'/reports/generate/{b}', params={'month': '2025-01'}, headers=_hdr(doc))
        assert r.status_code == 403

    def test_reports_detail_out_of_scope_403(self, client):
        sa = _login(client, 'scope_sa')
        a, b = _hospital_ids(client, sa)
        _scope_doctor_to(client, sa, a)
        doc = _login(client, 'scope_doc')
        r = client.get(f'/reports/detail/{b}', params={'month': '2025-01'}, headers=_hdr(doc))
        assert r.status_code == 403

    def test_dashboard_performance_out_of_scope_403(self, client):
        sa = _login(client, 'scope_sa')
        a, b = _hospital_ids(client, sa)
        _scope_doctor_to(client, sa, a)
        doc = _login(client, 'scope_doc')
        r = client.get(f'/dashboard/hospital-performance/{b}', headers=_hdr(doc))
        assert r.status_code == 403

    def test_in_scope_is_not_forbidden(self, client):
        sa = _login(client, 'scope_sa')
        a, b = _hospital_ids(client, sa)
        _scope_doctor_to(client, sa, a)
        doc = _login(client, 'scope_doc')
        r = client.get(f'/reports/generate/{a}', params={'month': '2025-01'}, headers=_hdr(doc))
        assert r.status_code != 403

    def test_superadmin_out_of_scope_not_forbidden(self, client):
        sa = _login(client, 'scope_sa')
        a, b = _hospital_ids(client, sa)
        r = client.get(f'/reports/generate/{b}', params={'month': '2025-01'}, headers=_hdr(sa))
        assert r.status_code != 403
