"""Path-traversal guards for upload/file endpoints (Critical security fix).

Client-supplied filenames are joined with UPLOAD_DIR; a name containing
directory components (``../`` or ``..\\``) must never escape it.
"""
import io
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import UPLOAD_DIR
from app.database import get_db
from app.main import app
from app.utils.files import safe_upload_name


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _excel_bytes():
    import pandas as pd

    df = pd.DataFrame({
        "organisationunitname": ["General Hospital"],
        "month": ["2026-05"],
        "Total Deliveries": [100],
        "Normal Vaginal Deliveries": [70],
        "Caesarean Sections": [30],
        "Live Births": [95],
        "Maternal Deaths": [0],
        "Neonatal deaths": [1],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return buf


class TestSafeUploadName:
    def test_strips_posix_directory(self):
        assert safe_upload_name("../../etc/passwd") == "passwd"

    def test_strips_windows_directory(self):
        assert safe_upload_name("..\\..\\win.ini") == "win.ini"

    def test_keeps_plain_name(self):
        assert safe_upload_name("report.xlsx") == "report.xlsx"

    @pytest.mark.parametrize("bad", ["", None, ".", "..", "/", "a/"])
    def test_rejects_empty_and_dot(self, bad):
        with pytest.raises(HTTPException):
            safe_upload_name(bad)


def test_preview_traversal_does_not_write_outside_upload_dir(client):
    """A crafted filename posted to /upload/preview must not create a file in
    the parent of UPLOAD_DIR."""
    outside = os.path.join(os.path.dirname(UPLOAD_DIR), "escape_traversal.xlsx")
    if os.path.exists(outside):
        os.remove(outside)
    resp = client.post(
        "/upload/preview",
        files={"file": (
            "../../escape_traversal.xlsx",
            _excel_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert resp.status_code in (200, 400, 422)
    assert not os.path.exists(outside), "traversal write escaped UPLOAD_DIR"


def test_analyze_saved_traversal_does_not_read_outside(client):
    """A traversal filename passed to /analysis/analyze-saved must not read a
    file from outside UPLOAD_DIR."""
    outside = os.path.join(os.path.dirname(UPLOAD_DIR), "secret_outside.xlsx")
    with open(outside, "wb") as f:
        f.write(b"not an excel file")
    try:
        resp = client.post(
            "/analysis/analyze-saved",
            params={"filenames": "../secret_outside.xlsx"},
        )
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            assert resp.json().get("files_processed", 0) == 0
    finally:
        if os.path.exists(outside):
            os.remove(outside)
