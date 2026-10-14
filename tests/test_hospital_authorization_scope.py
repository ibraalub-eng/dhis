"""US-09 — Hospital authorization scope.

Desired behaviour (the contract these tests lock in):

* Superadmin                       -> unrestricted (every hospital).
* Assigned hospitals              -> exactly those hospitals.
* No assigned hospitals           -> NO hospitals, unless a role (or a direct
                                     grant) carries ``hospitals.unrestricted``.

The regression under test: a user with an empty hospital assignment must never
be treated as unrestricted ("sees all"), which is what the old
``get_user_hospital_ids`` docstring ("treat as all") and the old
``list_hospitals`` ``if _assigned:`` filter //accidentally// allowed.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import (
    UNRESTRICTED_HOSPITALS_PERMISSION,
    get_current_user,
    get_user_hospital_ids,
    user_has_unrestricted_hospitals,
)
from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models import Hospital, Permission, Role, User

PW = "scope-pw-123"


def _perm(db, code: str) -> Permission:
    p = db.query(Permission).filter(Permission.codename == code).first()
    if p is None:
        p = Permission(codename=code, description=code)
        db.add(p)
        db.flush()
    return p


def _user(db, username, *, roles=(), perms=(), hospitals=(), is_superuser=False) -> User:
    u = User(
        username=username,
        email=f"{username}@scope.test",
        full_name=username,
        password_hash=hash_password(PW),
        is_superuser=is_superuser,
        roles=list(roles),
        permissions=list(perms),
        hospitals=list(hospitals),
    )
    db.add(u)
    db.commit()
    return u


# ---------------------------------------------------------------------------
# Unit tests for the scope helper itself
# ---------------------------------------------------------------------------

class TestScopeHelperSemantics:
    def test_superuser_is_unrestricted(self, db_session):
        u = _user(db_session, "unit_su", is_superuser=True)
        assert get_user_hospital_ids(u, db_session) is None
        assert user_has_unrestricted_hospitals(u) is True

    def test_no_assignment_returns_empty_not_none(self, db_session):
        u = _user(db_session, "unit_none")
        result = get_user_hospital_ids(u, db_session)
        assert result == []
        assert result is not None, "empty assignment must not mean 'all hospitals'"
        assert user_has_unrestricted_hospitals(u) is False

    def test_assignment_returns_exact_ids(self, db_session):
        h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
        u = _user(db_session, "unit_scoped", hospitals=[h1])
        assert sorted(get_user_hospital_ids(u, db_session)) == [h1.id]

    def test_direct_unrestricted_permission(self, db_session):
        u = _user(
            db_session,
            "unit_direct",
            perms=[_perm(db_session, UNRESTRICTED_HOSPITALS_PERMISSION)],
        )
        assert get_user_hospital_ids(u, db_session) is None

    def test_role_unrestricted_permission(self, db_session):
        role = Role(
            name="unit_global",
            permissions=[_perm(db_session, UNRESTRICTED_HOSPITALS_PERMISSION)],
        )
        u = _user(db_session, "unit_role", roles=[role])
        assert get_user_hospital_ids(u, db_session) is None

    def test_other_permissions_do_not_grant_unrestricted(self, db_session):
        u = _user(db_session, "unit_readonly", perms=[_perm(db_session, "hospitals.read")])
        assert user_has_unrestricted_hospitals(u) is False
        assert get_user_hospital_ids(u, db_session) == []


# ---------------------------------------------------------------------------
# Endpoint tests (real JWT auth, scoped queries)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reapply_overrides(app, _bypass_auth):
    app.dependency_overrides.pop(get_current_user, None)
    from app.cache import cache
    cache.invalidate()
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app, db_session):
    db = db_session
    read = _perm(db, "hospitals.read")
    manage = _perm(db, "system.manage_users")

    super_role = Role(name="superadmin", is_system=True, permissions=[read, manage])
    doctor_role = Role(name="doctor", permissions=[read])
    global_role = Role(
        name="global_reader",
        permissions=[read, _perm(db, UNRESTRICTED_HOSPITALS_PERMISSION)],
    )
    db.add_all([super_role, doctor_role, global_role])
    db.flush()

    hospitals = db.query(Hospital).order_by(Hospital.id).all()
    _user(db, "scope_sa", roles=[super_role], is_superuser=True)
    _user(db, "scope_none", roles=[doctor_role])            # no assignment
    _user(db, "scope_one", roles=[doctor_role], hospitals=[hospitals[0]])
    _user(db, "scope_global", roles=[global_role])          # role-authorized all

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


def _login(c, username):
    r = c.post("/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _hospitals(c, headers):
    r = c.get("/hospitals/", headers=headers)
    assert r.status_code == 200, r.text[:200]
    return r.json()


class TestHospitalListScope:
    def test_superadmin_sees_everything(self, client, db_session):
        bodies = _hospitals(client, _login(client, "scope_sa"))
        assert len(bodies) == db_session.query(Hospital).count()

    def test_no_assignment_sees_nothing(self, client):
        assert _hospitals(client, _login(client, "scope_none")) == []

    def test_assignment_sees_only_assigned(self, client, db_session):
        first = db_session.query(Hospital).order_by(Hospital.id).first()
        bodies = _hospitals(client, _login(client, "scope_one"))
        assert [h["id"] for h in bodies] == [first.id]

    def test_role_authorized_unrestricted_sees_everything(self, client, db_session):
        bodies = _hospitals(client, _login(client, "scope_global"))
        assert len(bodies) == db_session.query(Hospital).count()


class TestAdminAssignmentContract:
    def test_empty_assignment_does_not_grant_all(self, client, db_session):
        sa = _login(client, "scope_sa")
        users = client.get("/admin/users", headers=sa).json()["users"]
        none_user = next(u for u in users if u["username"] == "scope_none")
        resp = client.put(
            f"/admin/users/{none_user['id']}/hospitals",
            json={"hospital_ids": []},
            headers=sa,
        )
        assert resp.status_code == 200
        assert _hospitals(client, _login(client, "scope_none")) == []

    def test_explicit_unrestricted_grant(self, client, db_session):
        sa = _login(client, "scope_sa")
        users = client.get("/admin/users", headers=sa).json()["users"]
        none_user = next(u for u in users if u["username"] == "scope_none")
        resp = client.put(
            f"/admin/users/{none_user['id']}/hospitals",
            json={"unrestricted": True},
            headers=sa,
        )
        assert resp.status_code == 200 and resp.json()["unrestricted"] is True
        assert len(_hospitals(client, _login(client, "scope_none"))) == db_session.query(Hospital).count()

    def test_unrestricted_revoke_removes_access(self, client, db_session):
        sa = _login(client, "scope_sa")
        users = client.get("/admin/users", headers=sa).json()["users"]
        uid = next(u["id"] for u in users if u["username"] == "scope_none")
        client.put(f"/admin/users/{uid}/hospitals", json={"unrestricted": True}, headers=sa)
        assert len(_hospitals(client, _login(client, "scope_none"))) == db_session.query(Hospital).count()
        resp = client.put(
            f"/admin/users/{uid}/hospitals",
            json={"unrestricted": False},
            headers=sa,
        )
        assert resp.status_code == 200 and resp.json()["unrestricted"] is False
        assert _hospitals(client, _login(client, "scope_none")) == []

    def test_get_reports_unrestricted_flag(self, client, db_session):
        sa = _login(client, "scope_sa")
        users = client.get("/admin/users", headers=sa).json()["users"]
        uid = next(u["id"] for u in users if u["username"] == "scope_none")
        body = client.get(f"/admin/users/{uid}/hospitals", headers=sa).json()
        assert body["unrestricted"] is False
        assert body["is_restricted"] is True
        assert body["hospitals"] == []
