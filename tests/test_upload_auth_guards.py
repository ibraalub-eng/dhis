"""Auth guards on upload.py endpoints that were previously unauthenticated.

/template, /check-duplicate and /data-entry/options used to be reachable
without any token. They must now require the data.upload permission.
"""
import io

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models import Permission, Role, User


@pytest.fixture
def real_client(db_session):
    """Client with the autouse auth bypass removed -> real auth is enforced."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _xlsx():
    import pandas as pd

    buf = io.BytesIO()
    pd.DataFrame({"organisationunitname": ["General Hospital"], "month": ["2026-05"]}).to_excel(
        buf, index=False, engine="openpyxl"
    )
    buf.seek(0)
    return buf


def _login_header(client, db_session, perms):
    role = Role(name="viewer-" + "-".join(perms or ["none"]), permissions=[Permission(codename=p) for p in perms])
    user = User(
        username="u-" + (perms[0] if perms else "none"),
        email="u@test.com",
        full_name="U",
        password_hash=hash_password("pass123"),
        roles=[role],
    )
    db_session.add(user)
    db_session.commit()
    login = client.post("/auth/login", json={"username": user.username, "password": "pass123"})
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def test_template_requires_auth(real_client):
    assert real_client.get("/upload/template").status_code == 401


def test_data_entry_options_requires_auth(real_client):
    assert real_client.get("/upload/data-entry/options").status_code == 401


def test_check_duplicate_requires_auth(real_client):
    resp = real_client.post(
        "/upload/check-duplicate",
        files={"file": ("x.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 401


def test_template_forbidden_without_upload_permission(real_client, db_session):
    headers = _login_header(real_client, db_session, ["dashboard.read"])
    assert real_client.get("/upload/template", headers=headers).status_code == 403


def test_data_entry_options_forbidden_without_upload_permission(real_client, db_session):
    headers = _login_header(real_client, db_session, ["dashboard.read"])
    assert real_client.get("/upload/data-entry/options", headers=headers).status_code == 403


def test_check_duplicate_forbidden_without_upload_permission(real_client, db_session):
    headers = _login_header(real_client, db_session, ["dashboard.read"])
    resp = real_client.post(
        "/upload/check-duplicate",
        headers=headers,
        files={"file": ("x.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 403
