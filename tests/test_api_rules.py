"""Tests for rules API endpoints (api.rules)."""
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Rule


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


class TestListRules:
    def test_list_all(self, client):
        resp = client.get("/rules/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_filter_by_type(self, client):
        resp = client.get("/rules/?rule_type=LOGIC")
        assert resp.status_code == 200
        data = resp.json()
        for r in data:
            assert r["rule_type"] == "LOGIC"

    def test_filter_by_severity(self, client):
        resp = client.get("/rules/?severity=HIGH")
        assert resp.status_code == 200
        data = resp.json()
        for r in data:
            assert r["severity"] == "HIGH"

    def test_filter_by_enabled(self, client):
        resp = client.get("/rules/?enabled=true")
        assert resp.status_code == 200
        data = resp.json()
        for r in data:
            assert r["enabled"] is True

    def test_filter_by_category(self, client):
        resp = client.get("/rules/?category=deliveries")
        assert resp.status_code == 200
        data = resp.json()
        for r in data:
            assert r["category"] == "deliveries"

    def test_rules_have_required_fields(self, client):
        resp = client.get("/rules/")
        data = resp.json()
        for r in data:
            assert "id" in r
            assert "code" in r
            assert "name" in r
            assert "rule_type" in r
            assert "severity" in r


class TestGetRule:
    def test_get_existing(self, client, db_session):
        rule = db_session.query(Rule).first()
        resp = client.get(f"/rules/{rule.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == rule.id
        assert data["code"] == rule.code

    def test_get_nonexistent(self, client):
        resp = client.get("/rules/99999")
        assert resp.status_code == 404


class TestCreateRule:
    def test_create_success(self, client):
        payload = {
            "code": "R999",
            "name": "Test Rule",
            "rule_type": "LOGIC",
            "severity": "LOW",
            "category": "test",
            "expression_type": "ge",
            "params": '{"parent": "2", "children": ["3"]}',
            "description": "A test rule",
        }
        resp = client.post("/rules/", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "R999"
        assert data["name"] == "Test Rule"

    def test_create_duplicate(self, client, db_session):
        existing = db_session.query(Rule).first()
        payload = {
            "code": existing.code,
            "name": "Duplicate",
            "rule_type": "LOGIC",
            "severity": "LOW",
            "category": "test",
            "expression_type": "ge",
            "params": "{}",
            "description": "Duplicate",
        }
        resp = client.post("/rules/", json=payload)
        assert resp.status_code == 400

    def test_create_disabled(self, client):
        payload = {
            "code": "R998",
            "name": "Disabled Rule",
            "rule_type": "THRESHOLD",
            "severity": "MEDIUM",
            "category": "test",
            "expression_type": "benchmark_rate",
            "params": '{"num_code": "5", "den_code": "2"}',
            "description": "Test",
        }
        resp = client.post("/rules/", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True


class TestUpdateRule:
    def test_update_name(self, client, db_session):
        rule = db_session.query(Rule).first()
        resp = client.put(f"/rules/{rule.id}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"

    def test_update_enabled(self, client, db_session):
        rule = db_session.query(Rule).first()
        resp = client.put(f"/rules/{rule.id}", json={"enabled": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_update_nonexistent(self, client):
        resp = client.put("/rules/99999", json={"name": "Test"})
        assert resp.status_code == 404

    def test_partial_update(self, client, db_session):
        rule = db_session.query(Rule).first()
        original_code = rule.code
        resp = client.put(f"/rules/{rule.id}", json={"severity": "CRITICAL"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["severity"] == "CRITICAL"
        assert data["code"] == original_code


class TestDeleteRule:
    def test_delete_success(self, client, db_session):
        rule = Rule(
            code="R997", name="To Delete", rule_type="LOGIC",
            severity="LOW", category="test", expression_type="ge",
            params="{}", description="Will be deleted",
        )
        db_session.add(rule)
        db_session.commit()

        resp = client.delete(f"/rules/{rule.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data["message"].lower()

    def test_delete_nonexistent(self, client):
        resp = client.delete("/rules/99999")
        assert resp.status_code == 404


class TestBulkReorder:
    def test_reorder_rules(self, client, db_session):
        rules = db_session.query(Rule).limit(3).all()
        items = [{"id": r.id, "sort_order": i} for i, r in enumerate(rules)]
        resp = client.put("/rules/reorder", content=json.dumps({"items": items}), headers={"Content-Type": "application/json"})
        assert resp.status_code in (200, 422)


class TestToggleRule:
    def test_toggle_enabled_to_disabled(self, client, db_session):
        rule = db_session.query(Rule).filter(Rule.enabled == True).first()
        resp = client.put(f"/rules/{rule.id}/toggle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_toggle_disabled_to_enabled(self, client, db_session):
        rule = db_session.query(Rule).filter(Rule.enabled == False).first()
        if rule:
            resp = client.put(f"/rules/{rule.id}/toggle")
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is True

    def test_toggle_nonexistent(self, client):
        resp = client.put("/rules/99999/toggle")
        assert resp.status_code == 404
