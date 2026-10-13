"""Static /setup page must follow the user's language.

Priority: app_lang cookie (written by the UI language toggle) →
Accept-Language header → default Arabic (historical behavior).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import main as app_main  # noqa: E402


def _client():
    return TestClient(app_main.app)


def _force_db_not_ready(monkeypatch):
    """Language tests must hit the setup-page branch, not the /dashboard redirect.

    Everything this suite does lives on app.database._db_ready, which
    setup_page imports at call time.
    """
    from app import database as database_module

    monkeypatch.setattr(database_module, "_db_ready", False, raising=False)


@pytest.fixture(autouse=True)
def _db_not_ready(request, monkeypatch):
    """Apply automatically to every test except the explicit db-ready one."""
    if request.node.get_closest_marker("keep_db_ready"):
        return
    _force_db_not_ready(monkeypatch)


def test_setup_default_arabic_when_no_language_info(monkeypatch):
    client = _client()
    d = client.get("/setup")
    assert d.status_code == 200
    body = d.text
    assert 'dir="rtl"' in body
    assert "إعداد قاعدة البيانات" in body


def test_setup_arabic_cookie(monkeypatch):
    client = _client()
    r = client.get("/setup", headers={"Cookie": "app_lang=ar"})
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    assert "إعداد قاعدة البيانات" in r.text


def test_setup_english_cookie(monkeypatch):
    client = _client()
    r = client.get("/setup", headers={"Cookie": "app_lang=en"})
    assert r.status_code == 200
    assert 'dir="ltr"' in r.text
    assert "Database Setup" in r.text
    assert "إعداد قاعدة البيانات" not in r.text


def test_setup_accept_language_english_fallback(monkeypatch):
    client = _client()
    r = client.get("/setup", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.status_code == 200
    assert 'dir="ltr"' in r.text
    assert "Database Setup" in r.text


def test_setup_accept_language_arabic(monkeypatch):
    client = _client()
    r = client.get("/setup", headers={"Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8"})
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    assert "إعداد قاعدة البيانات" in r.text


@pytest.mark.keep_db_ready
def test_setup_redirects_when_db_ready(monkeypatch):
    # The redirect contract (db ready → /dashboard) must stay intact.
    from app import database as database_module

    monkeypatch.setattr(database_module, "_db_ready", True, raising=False)
    try:
        client = _client()
        r = client.get("/setup", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"] == "/dashboard"
    finally:
        monkeypatch.setattr(database_module, "_db_ready", False, raising=False)
