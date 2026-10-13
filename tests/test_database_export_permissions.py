"""US-03: DB export/preview require high-level authorization.

A user holding only settings.read (or any subset without system.export_data)
must get 403. Only system.export_data (or a superuser) may reach the
endpoints. Sensitive columns (password hashes, tokens, credentials, ...)
are never serialized in preview or export output.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.models import Permission, Role, User


@pytest.fixture(autouse=True)
def _clear_bypass(app, _bypass_auth):
    """Remove conftest's FakeSuperAdmin so real JWT auth is tested."""
    app.dependency_overrides.pop(get_current_user, None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app, db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _make_user(db_session, username, perms=None, is_superuser=False):
    role = Role(
        name=f"role-{username}",
        permissions=[Permission(codename=p) for p in (perms or [])],
    )
    user = User(
        username=username,
        email=f"{username}@test.com",
        full_name=username,
        password_hash=hash_password("pass123"),
        roles=[role],
        is_superuser=is_superuser,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, username):
    resp = client.post("/auth/login", json={"username": username, "password": "pass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": "Bearer " + resp.json()["access_token"]}


class TestDatabaseExportAuthorization:
    def test_settings_read_alone_forbidden_on_export(self, client, db_session):
        _make_user(db_session, "settings_only", ["settings.read"])
        headers = _login(client, "settings_only")
        assert client.get("/config/database/export", headers=headers).status_code == 403

    def test_settings_read_alone_forbidden_on_preview(self, client, db_session):
        _make_user(db_session, "settings_only2", ["settings.read"])
        headers = _login(client, "settings_only2")
        assert client.get("/config/database/preview", headers=headers).status_code == 403

    def test_normal_user_forbidden(self, client, db_session):
        _make_user(db_session, "viewer_user", ["dashboard.read", "analysis.read"])
        headers = _login(client, "viewer_user")
        assert client.get("/config/database/export", headers=headers).status_code == 403
        assert client.get("/config/database/preview", headers=headers).status_code == 403

    def test_export_data_permission_allowed_on_export(self, client, db_session):
        _make_user(db_session, "exporter", ["system.export_data"])
        headers = _login(client, "exporter")
        assert client.get("/config/database/export", headers=headers).status_code == 200

    def test_export_data_permission_allowed_on_preview(self, client, db_session):
        _make_user(db_session, "previewer", ["system.export_data"])
        headers = _login(client, "previewer")
        assert client.get("/config/database/preview", headers=headers).status_code == 200

    def test_superadmin_allowed(self, client, db_session):
        _make_user(db_session, "root", is_superuser=True)
        headers = _login(client, "root")
        assert client.get("/config/database/export", headers=headers).status_code == 200
        assert client.get("/config/database/preview", headers=headers).status_code == 200


class TestSensitiveDataMasking:
    def test_password_hash_not_exported(self, client, db_session):
        user = _make_user(db_session, "hashed_user", ["system.export_data"])
        headers = _login(client, "hashed_user")
        resp = client.get("/config/database/export", headers=headers)
        assert resp.status_code == 200
        assert "password_hash" not in resp.text
        assert user.password_hash not in resp.text

    def test_password_hash_not_previewed(self, client, db_session):
        user = _make_user(db_session, "hashed_user2", ["system.export_data"])
        headers = _login(client, "hashed_user2")
        resp = client.get("/config/database/preview", headers=headers)
        assert resp.status_code == 200
        assert "password_hash" not in resp.text
        assert user.password_hash not in resp.text

    def test_substring_sensitive_columns_masked(self, client, db_session):
        db_session.execute(text(
            "CREATE TABLE audit_secrets ("
            "id INTEGER PRIMARY KEY, "
            "user_credentials TEXT, "
            "session_token TEXT, "
            "password_hash TEXT, "
            "public_name TEXT)"
        ))
        db_session.execute(text(
            "INSERT INTO audit_secrets "
            "(id, user_credentials, session_token, password_hash, public_name) "
            "VALUES (1, 'cred-value', 'tok-value', 'hash-value', 'ok-value')"
        ))
        db_session.commit()
        _make_user(db_session, "masker", ["system.export_data"])
        headers = _login(client, "masker")
        resp = client.get("/config/database/export", headers=headers)
        assert resp.status_code == 200
        for leaked in (
            "user_credentials", "cred-value",
            "session_token", "tok-value",
            "password_hash", "hash-value",
        ):
            assert leaked not in resp.text
        assert "public_name" in resp.text
