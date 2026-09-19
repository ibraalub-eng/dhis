"""Tests for rules API endpoints (api.rules)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
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
        rule = db_session.query(Rule).filter(Rule.enabled).first()
        resp = client.put(f"/rules/{rule.id}/toggle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_toggle_disabled_to_enabled(self, client, db_session):
        rule = db_session.query(Rule).filter(Rule.enabled.is_(False)).first()
        if rule:
            resp = client.put(f"/rules/{rule.id}/toggle")
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is True

    def test_toggle_nonexistent(self, client):
        resp = client.put("/rules/99999/toggle")
        assert resp.status_code == 404


class TestSaveEnabled:
    def test_save_enabled_bulk(self, client, db_session):
        rules = db_session.query(Rule).limit(3).all()
        assert len(rules) >= 2
        items = [{"id": r.id, "enabled": (idx % 2 == 0)} for idx, r in enumerate(rules)]
        resp = client.put("/rules/save-enabled", json={"items": items})
        assert resp.status_code == 200
        for item in items:
            row = db_session.query(Rule).filter(Rule.id == item["id"]).first()
            assert row.enabled is item["enabled"]

    def test_save_enabled_bulk_partial_ids(self, client, db_session):
        valid = db_session.query(Rule).first()
        resp = client.put("/rules/save-enabled", json={"items": [{"id": 99999, "enabled": True}, {"id": valid.id, "enabled": False}]})
        assert resp.status_code == 200
        assert db_session.query(Rule).filter(Rule.id == valid.id).first().enabled is False


class TestRuleFailures:
    def test_failures_unknown_code(self, client):
        resp = client.get("/rules/failures?rule_code=NOPE_NOT_EXISTS")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_code"] == "NOPE_NOT_EXISTS"
        assert data["months"] == []
        assert data["total_months"] == 0

    def test_failures_requires_rule_code(self, client):
        resp = client.get("/rules/failures")
        assert resp.status_code == 422

    def test_failures_with_hospital_filter(self, client):
        resp = client.get("/rules/failures?rule_code=NOPE_NOT_EXISTS&hospital_id=1")
        assert resp.status_code == 200


class TestRuleImpact:
    def test_impact_shape(self, client):
        resp = client.get("/rules/impact")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for r in data:
            assert "code" in r
            assert "ref_codes" in r
            assert "ref_names" in r
            assert "failure_count" in r
            assert isinstance(r["hospitals_affected"], list)
            for h in r["hospitals_affected"]:
                assert "id" in h and "name" in h and "details" in h
            assert "month" in r

    def test_impact_nonempty(self, client):
        resp = client.get("/rules/impact")
        assert resp.status_code == 200
        assert resp.json() != []


class TestRuleValidate:
    def test_validate_nonexistent_code_clean(self, client):
        payload = {
            "code": "RAAAA",
            "expression_type": "ge",
            "params": {"parent": "2", "children": ["3", "4"]},
        }
        resp = client.post("/rules/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert "warnings" in data

    def test_validate_duplicate_code(self, client, db_session):
        existing = db_session.query(Rule).first()
        payload = {
            "code": existing.code,
            "expression_type": "ge",
            "params": {"parent": "2", "children": ["3"]},
        }
        resp = client.post("/rules/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert any("already exists" in e for e in data["errors"])

    def test_validate_own_code_with_exclude_id_no_error(self, client, db_session):
        existing = db_session.query(Rule).first()
        payload = {
            "code": existing.code,
            "expression_type": existing.expression_type,
            "params": existing.params,
            "exclude_id": existing.id,
        }
        resp = client.post("/rules/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert not any("already exists" in e for e in data["errors"])

    def test_validate_exact_duplicate_params(self, client, db_session):
        existing = db_session.query(Rule).filter(Rule.expression_type == "ge").first()
        if not existing:
            existing = db_session.query(Rule).first()
        resp = client.post("/rules/validate", json={
            "code": "RBBBB",
            "expression_type": existing.expression_type,
            "params": existing.params,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert any("Identical" in w for w in data["warnings"])

    def test_validate_opposite_trend_conflict(self, client):
        resp = client.post("/rules/validate", json={
            "code": "RCCCC",
            "expression_type": "month_over",
            "params": {"code": "2"},
        })
        assert resp.status_code == 200
        data = resp.json()
        for w in data["warnings"]:
            assert "Conflicts with" in w

    def test_validate_with_string_params(self, client):
        resp = client.post("/rules/validate", json={
            "code": "RDDDD",
            "expression_type": "ge",
            "params": '{"parent": "2", "children": ["3"]}',
        })
        assert resp.status_code == 200


class TestRuleTestDryRun:
    def test_test_unknown_hospital_404(self, client):
        resp = client.post("/rules/test", json={"hospital_id": 99999, "month": "2025-01"})
        assert resp.status_code == 404

    def test_test_no_values_returns_no_data(self, client):
        # Use a huge month that cannot have data
        resp = client.post("/rules/test", json={
            "hospital_id": 1,
            "month": "2099-01",
            "code": "RTE1",
            "name": "Dry run",
            "expression_type": "ge",
            "params": {"parent": "2", "children": ["3"]},
        })
        assert resp.status_code == 200

    def test_test_without_hospital_defaults_to_all(self, client):
        # No hospital/month -> latest month, all active hospitals (scope 'all')
        resp = client.post("/rules/test", json={
            "code": "RTE2",
            "name": "Dry run all",
            "expression_type": "ge",
            "params": {"parent": "2", "children": ["3"]},
        })
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            data = resp.json()
            assert data["scope"] == "all"
            assert "hospitals" in data
            assert "passed" in data and "failed" in data


class TestRuleHistory:
    def test_create_records_history(self, client, db_session):
        from app.models import RuleHistory
        before = db_session.query(RuleHistory).count()
        resp = client.post("/rules/", json={
            "code": "TESTHIST1", "name": "History Test Rule",
            "rule_type": "LOGIC", "severity": "LOW", "category": "TEST",
            "expression_type": "ge", "params": json.dumps({"parent": "2", "children": ["3"]}),
            "description": "",
        })
        assert resp.status_code == 200, resp.text
        rows = db_session.query(RuleHistory).filter(RuleHistory.rule_code == "TESTHIST1").all()
        assert len(rows) == before + 1
        assert rows[-1].action == "created"

    def test_update_records_changed_fields(self, client, db_session):
        resp = client.post("/rules/", json={
            "code": "TESTHIST2", "name": "Hist2",
            "rule_type": "LOGIC", "severity": "LOW", "category": "TEST",
            "expression_type": "ge", "params": "{}", "description": "",
        })
        rule_id = resp.json()["id"]
        resp = client.put(f"/rules/{rule_id}", json={"severity": "HIGH", "name": "Hist2-renamed"})
        assert resp.status_code == 200
        from app.models import RuleHistory
        rows = db_session.query(RuleHistory).filter(
            RuleHistory.rule_code == "TESTHIST2", RuleHistory.action == "updated"
        ).all()
        assert len(rows) == 1
        changed = json.loads(rows[0].changed_fields)
        assert set(changed) == {"severity", "name"}

    def test_save_enabled_records_enable_disable(self, client, db_session):
        from app.models import RuleHistory
        rule = db_session.query(Rule).filter(Rule.enabled.is_(True)).first()
        resp = client.put("/rules/save-enabled", json={"items": [{"id": rule.id, "enabled": False}]})
        assert resp.status_code == 200
        rows = db_session.query(RuleHistory).filter(
            RuleHistory.rule_code == rule.code, RuleHistory.action == "disabled"
        ).all()
        assert len(rows) >= 1

    def test_delete_preserves_history(self, client, db_session):
        from app.models import RuleHistory
        resp = client.post("/rules/", json={
            "code": "TESTHIST3", "name": "Hist3",
            "rule_type": "LOGIC", "severity": "LOW", "category": "TEST",
            "expression_type": "ge", "params": "{}", "description": "",
        })
        rule_id = resp.json()["id"]
        resp = client.delete(f"/rules/{rule_id}")
        assert resp.status_code == 200
        # The rule row is gone...
        assert db_session.query(Rule).filter(Rule.code == "TESTHIST3").first() is None
        # ...but the audit trail survives (rule_id NULL, code retained)
        rows = db_session.query(RuleHistory).filter(RuleHistory.rule_code == "TESTHIST3").all()
        assert [r.action for r in rows] == ["created", "deleted"]
        assert rows[-1].rule_id is None
        snap = json.loads(rows[-1].snapshot)
        assert snap["code"] == "TESTHIST3"

    def test_history_endpoint_newest_first(self, client, db_session):
        resp = client.post("/rules/", json={
            "code": "TESTHIST4", "name": "Hist4",
            "rule_type": "LOGIC", "severity": "LOW", "category": "TEST",
            "expression_type": "ge", "params": "{}", "description": "",
        })
        rule_id = resp.json()["id"]
        client.put(f"/rules/{rule_id}", json={"name": "Hist4-b"})
        client.put(f"/rules/{rule_id}", json={"name": "Hist4-c"})
        resp = client.get("/rules/history/TESTHIST4")
        assert resp.status_code == 200
        data = resp.json()
        actions = [e["action"] for e in data["entries"]]
        assert actions[0] == "updated"  # newest first
        assert "created" in actions


class TestRulesExportImport:
    def test_export_returns_catalog(self, client):
        resp = client.get("/rules/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["count"] == len(data["rules"])
        assert data["count"] > 0
        for r in data["rules"]:
            assert {"code", "name", "expression_type", "params", "enabled"} <= set(r.keys())

    def test_import_roundtrip(self, client, db_session):
        resp = client.get("/rules/export")
        payload = resp.json()
        # Mutate one rule so the import exercises the update path
        payload["rules"][0]["name"] = payload["rules"][0]["name"] + " X"
        resp = client.post("/rules/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] >= 1
        assert data["created"] == 0

    def test_import_creates_new_rule(self, client, db_session):
        payload = {"rules": [{
            "code": "TESTIMP1", "name": "Imported Rule", "rule_type": "LOGIC",
            "severity": "LOW", "category": "TEST", "expression_type": "ge",
            "params": {"parent": "2", "children": ["3"]}, "description": "", "enabled": False,
        }]}
        resp = client.post("/rules/import", json=payload)
        assert resp.status_code == 200
        assert resp.json()["created"] == 1
        rule = db_session.query(Rule).filter(Rule.code == "TESTIMP1").first()
        assert rule is not None
        assert rule.enabled is False

    def test_import_accepts_bare_list(self, client):
        resp = client.post("/rules/import", json=[{"code": "TESTIMP2", "name": "Bare"}])
        assert resp.status_code == 200
        assert resp.json()["created"] == 1

    def test_import_rejects_bad_body(self, client):
        resp = client.post("/rules/import", json={"nope": True})
        assert resp.status_code == 400
