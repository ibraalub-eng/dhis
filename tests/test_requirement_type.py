# -*- coding: utf-8 -*-
"""requirement_type surface tests (indicator-groups design rev 2).

The completeness-denominator behavior itself is covered in
test_indicator_groups.py; these tests cover the MANAGEMENT surface:
  * PUT /hospitals/indicators/{id}/requirement-type validation + persistence
  * the tree endpoints expose requirement_type on every node
  * the endpoint requires settings.write (read-only users get 403)
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.database import get_db
from app.main import app
from app.models import Hospital, Indicator, Permission, Role


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


def _iid(db, code):
    ind = db.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    return ind.id


def _walk_collect(node, out):
    if node.get("indicator_id") is not None:
        out[node["indicator_id"]] = node.get("requirement_type")
    for c in node.get("children", []) or []:
        _walk_collect(c, out)


class TestRequirementTypeEndpoint:
    def test_set_and_persist(self, client, db_session):
        iid = _iid(db_session, "2")
        resp = client.put(f"/hospitals/indicators/{iid}/requirement-type",
                          json={"requirement_type": "Optional"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["requirement_type"] == "Optional"
        db_session.expire_all()
        assert db_session.get(Indicator, iid).requirement_type == "Optional"

    def test_switch_back_to_required(self, client, db_session):
        iid = _iid(db_session, "3")
        client.put(f"/hospitals/indicators/{iid}/requirement-type", json={"requirement_type": "Optional"})
        resp = client.put(f"/hospitals/indicators/{iid}/requirement-type", json={"requirement_type": "Required"})
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Indicator, iid).requirement_type == "Required"

    def test_invalid_value_422(self, client, db_session):
        iid = _iid(db_session, "2")
        resp = client.put(f"/hospitals/indicators/{iid}/requirement-type",
                          json={"requirement_type": "Sometimes"})
        assert resp.status_code == 422

    def test_unknown_indicator_404(self, client):
        resp = client.put("/hospitals/indicators/999999/requirement-type",
                          json={"requirement_type": "Optional"})
        assert resp.status_code == 404

    def test_requires_settings_write(self, client, db_session):
        """Read-only users get 403 — the endpoint mutates global config."""
        class _ReadOnlyUser:
            id = 99998
            username = "readonly"
            email = "ro@test.local"
            full_name = "Read Only"
            is_active = True
            is_superuser = False
            roles = []
            permissions = []

        role = Role(name="ro_reqtype", description="", permissions=[Permission(codename="settings.read")])
        _ReadOnlyUser.roles = [role]

        app.dependency_overrides[get_current_user] = lambda: _ReadOnlyUser
        try:
            iid = _iid(db_session, "2")
            resp = client.put(f"/hospitals/indicators/{iid}/requirement-type",
                              json={"requirement_type": "Optional"})
            assert resp.status_code == 403, resp.text
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestTreeExposesRequirementType:
    def test_default_tree_nodes_carry_requirement_type(self, client, db_session):
        iid = _iid(db_session, "2")
        ind = db_session.get(Indicator, iid)
        ind.requirement_type = "Optional"
        db_session.commit()

        resp = client.get("/hospitals/indicator-tree/default?month=2026-01")
        assert resp.status_code == 200, resp.text

        found = {}
        for root in resp.json()["children"]:
            _walk_collect(root, found)
        assert found, "tree returned no indicator nodes"
        assert found.get(iid) == "Optional"
        assert all(v == "Required" for k, v in found.items() if k != iid)

    def test_hospital_tree_nodes_carry_requirement_type(self, client, db_session):
        hid = db_session.query(Hospital).first().id
        iid = _iid(db_session, "5")
        ind = db_session.get(Indicator, iid)
        ind.requirement_type = "Optional"
        db_session.commit()

        resp = client.get(f"/hospitals/{hid}/indicator-tree?month=2026-01")
        assert resp.status_code == 200, resp.text

        found = {}
        for root in resp.json()["children"]:
            _walk_collect(root, found)
        assert found.get(iid) == "Optional"
