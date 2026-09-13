"""Tests for the menu API."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


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


def test_get_menu_returns_seeded_groups(client):
    resp = client.get("/menu")
    assert resp.status_code == 200
    data = resp.json()
    groups = data["groups"]
    assert len(groups) == 5
    # First group is الرئيسية with dashboard
    first = groups[0]
    assert first["name"] == "الرئيسية"
    assert first["icon"] == "🏠"
    assert len(first["items"]) == 1
    assert first["items"][0]["tab_key"] == "dashboard"
    assert first["items"][0]["label"] == "Dashboard"


def test_get_menu_includes_tab_metadata(client):
    resp = client.get("/menu")
    items = resp.json()["groups"][1]["items"]  # البيانات group
    upload = next(i for i in items if i["tab_key"] == "upload")
    assert upload["icon"] == "📤"
    assert upload["permission"] == "data.upload"


def test_list_tabs(client):
    resp = client.get("/menu/tabs")
    assert resp.status_code == 200
    tabs = resp.json()["tabs"]
    assert len(tabs) == 14
    keys = [t["key"] for t in tabs]
    assert "dashboard" in keys
    assert "smart-analytics" in keys


def test_create_group(client):
    resp = client.post("/menu/groups", json={"name": "Test Group", "icon": "🧪"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Group"
    assert data["icon"] == "🧪"
    assert data["is_active"] is True


def test_update_group(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.patch(f"/menu/groups/{gid}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_delete_group(client):
    resp = client.post("/menu/groups", json={"name": "Disposable"})
    gid = resp.json()["id"]
    resp = client.delete(f"/menu/groups/{gid}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    groups = client.get("/menu").json()["groups"]
    assert all(g["id"] != gid for g in groups)


def test_create_item(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    assert resp.status_code == 200
    assert resp.json()["tab_key"] == "upload"


def test_create_item_duplicate_returns_409(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    assert resp.status_code == 409


def test_create_item_invalid_tab_key_returns_422(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "nonexistent"})
    assert resp.status_code == 422


def test_create_item_invalid_group_returns_404(client):
    resp = client.post("/menu/items", json={"group_id": 99999, "tab_key": "upload"})
    assert resp.status_code == 404


def test_update_item_sort_order(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[1]["items"][0]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"sort_order": 99})
    assert resp.status_code == 200
    assert resp.json()["sort_order"] == 99


def test_update_item_move_to_different_group(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[1]["items"][0]["id"]
    target_gid = groups[2]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"group_id": target_gid})
    assert resp.status_code == 200
    assert resp.json()["group_id"] == target_gid


def test_delete_item(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[0]["items"][0]["id"]
    resp = client.delete(f"/menu/items/{item_id}")
    assert resp.status_code == 200


def test_delete_nonexistent_item_returns_404(client):
    resp = client.delete("/menu/items/99999")
    assert resp.status_code == 404


def test_move_item_to_group_with_same_tab_key_returns_409(client):
    groups = client.get("/menu").json()["groups"]
    # dashboard is in group[0], try moving it to a group that also has dashboard
    # First add dashboard to group[2] (if not already), then try to move group[0]'s dashboard there
    client.post("/menu/items", json={"group_id": groups[2]["id"], "tab_key": "dashboard"})
    item_id = groups[0]["items"][0]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"group_id": groups[2]["id"]})
    assert resp.status_code == 409


def test_settings_tab_included_in_groups(client):
    resp = client.get("/menu")
    all_tab_keys = [
        item["tab_key"]
        for g in resp.json()["groups"]
        for item in g["items"]
    ]
    # 'settings' IS included (hidden is a frontend-only concept)
    assert "settings" in all_tab_keys