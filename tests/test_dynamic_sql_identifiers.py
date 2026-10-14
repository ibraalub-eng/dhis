"""US-08: dynamic SQL in config_api.py must use safe identifier handling.

Table names are interpolated into SQL (identifiers cannot be bound params), so
they are treated as untrusted: names come ONLY from DB introspection, must match
a strict identifier allowlist pattern, and are quoted via the dialect preparer.
A malicious or malformed name is skipped, never executed.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.config_api import _is_safe_identifier, iter_safe_tables
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.models import Permission, Role, User

INJECTION_PAYLOADS = [
    'users" ; DROP TABLE users; --',
    "users'; DROP TABLE users; --",
    "users) UNION SELECT password_hash FROM users --",
    "users WHERE 1=1",
    "users\nDROP TABLE x",
    "users`",
    'users"',
    "",
    "1users",
    "users-name",
    "users name",
    "schema.users",
]


class TestSafeIdentifierPredicate:
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_injection_payloads_rejected(self, payload):
        assert _is_safe_identifier(payload) is False

    @pytest.mark.parametrize(
        "name", ["users", "indicator_values", "_private", "Table_1", "a", "T9"]
    )
    def test_plain_identifiers_accepted(self, name):
        assert _is_safe_identifier(name) is True

    def test_non_string_rejected(self):
        assert _is_safe_identifier(None) is False
        assert _is_safe_identifier(123) is False


class TestIterSafeTables:
    def test_only_introspected_safe_tables_yielded(self, db_session):
        yield_names = {name for name, _ in iter_safe_tables(db_session)}
        assert yield_names, "expected at least one introspected table"
        for name, quoted in iter_safe_tables(db_session):
            assert _is_safe_identifier(name) is True
            # Dialect preparer must have produced a usable quoted identifier.
            assert quoted

    def test_unsafe_table_name_is_skipped(self, db_session):
        db_session.execute(text('CREATE TABLE "evil; DROP TABLE users; --" (id INTEGER)'))
        db_session.commit()
        served = {name for name, _ in iter_safe_tables(db_session)}
        assert "evil; DROP TABLE users; --" not in served

    def test_malicious_name_cannot_be_requested(self, db_session):
        # There is no request parameter for table names; the only names ever
        # used come from introspection. Confirm an arbitrary attacker-supplied
        # name is NOT among the served allowlist.
        served = {name for name, _ in iter_safe_tables(db_session)}
        assert "non_existent_table" not in served


@pytest.fixture(autouse=True)
def _clear_bypass(app, _bypass_auth):
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


def _make_exporter(db_session, username):
    role = Role(name=f"role-{username}", permissions=[Permission(codename="system.export_data")])
    user = User(
        username=username,
        email=f"{username}@test.com",
        full_name=username,
        password_hash=hash_password("pass123"),
        roles=[role],
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, username):
    resp = client.post("/auth/login", json={"username": username, "password": "pass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": "Bearer " + resp.json()["access_token"]}


class TestEndpointsNeverExecuteUnsafeNames:
    def test_export_skips_unsafe_table(self, client, db_session):
        db_session.execute(text('CREATE TABLE "x); DROP TABLE users; --" (id INTEGER)'))
        db_session.commit()
        _make_exporter(db_session, "exporter1")
        headers = _login(client, "exporter1")
        resp = client.get("/config/database/export", headers=headers)
        assert resp.status_code == 200
        assert "DROP TABLE users" not in resp.text

    def test_preview_skips_unsafe_table(self, client, db_session):
        db_session.execute(text('CREATE TABLE "y; DROP TABLE users; --" (id INTEGER)'))
        db_session.commit()
        _make_exporter(db_session, "previewer1")
        headers = _login(client, "previewer1")
        resp = client.get("/config/database/preview", headers=headers)
        assert resp.status_code == 200
        assert "DROP TABLE users" not in resp.text
