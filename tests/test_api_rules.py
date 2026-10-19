"""Tests for rules API endpoints (api.rules)."""
import json

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import func

from app.database import get_db
from app.main import app
from app.models import AppConfig, Hospital, Indicator, IndicatorValue, QualityScore, Rule, ValidationResult


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

    def test_create_benchmark_rule_is_rejected(self, client):
        payload = {
            "code": "R998",
            "name": "Benchmark Rule",
            "rule_type": "BENCHMARK",
            "severity": "MEDIUM",
            "category": "STATISTICAL_BENCHMARK",
            "expression_type": "benchmark_rate",
            "params": '{"num_code": "5", "den_code": "2"}',
            "description": "Benchmark rules are no longer managed here",
        }
        resp = client.post("/rules/", json=payload)
        assert resp.status_code == 422


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

    def test_benchmark_rule_is_removed_from_storage_and_api(self, client, db_session):
        from scripts.seed_rules import remove_benchmark_validation_data
        from app.engine.quality import ValidationContext, dispatch_rule, run_rules_from_db

        hospital = db_session.query(Hospital).first()
        benchmark = Rule(
            code="R041", name="Legacy benchmark", rule_type="BENCHMARK",
            severity="HIGH", category="STATISTICAL_BENCHMARK",
            expression_type="benchmark_rate", params="{}",
            description="Legacy benchmark rule",
        )
        db_session.add(benchmark)
        db_session.flush()
        benchmark_id = benchmark.id
        db_session.add(ValidationResult(
            hospital_id=hospital.id, month="2026-01", rule_code="R041",
            rule_description="Legacy benchmark", status="FAIL",
            severity="HIGH", rule_type="BENCHMARK", details="Legacy result",
        ))
        db_session.commit()

        ctx = ValidationContext(
            values={"2": 100, "5": 90},
            hospital_name=hospital.name,
            month="2026-01",
        )
        assert dispatch_rule(benchmark, ctx) is None
        assert all(result.rule_code != "R041" for result in run_rules_from_db(db_session, ctx))

        db_session.add(ValidationResult(
            hospital_id=hospital.id, month="2026-02", rule_code="R041",
            rule_description="Legacy benchmark pass", status="PASS",
            severity="HIGH", rule_type="BENCHMARK", details="Historical pass",
        ))
        db_session.add(ValidationResult(
            hospital_id=hospital.id, month="2026-01", rule_code="R001",
            rule_description="Logic rule", status="PASS",
            severity="HIGH", rule_type="LOGIC", details="Passed",
        ))
        score = QualityScore(
            hospital_id=hospital.id, month="2026-01", score=70,
            rule_compliance=50, completeness=80, consistency=50,
            outlier_penalty=0,
            issues=json.dumps(["R041: Legacy benchmark", "Anomaly: test"]),
        )
        db_session.add(score)
        db_session.add_all([
            AppConfig(key="cs_rate_threshold", value=80, category="rules"),
            AppConfig(key="nvd_rate_threshold", value=10, category="rules"),
        ])
        db_session.commit()

        removed_rules, removed_results, removed_settings = remove_benchmark_validation_data(db_session)
        db_session.commit()
        assert removed_rules == 1
        assert removed_results == 2
        assert removed_settings == 2
        assert db_session.query(Rule).filter_by(code="R041").first() is None
        assert db_session.query(ValidationResult).filter_by(rule_code="R041").count() == 0
        db_session.refresh(score)
        assert score.rule_compliance == 100
        assert score.consistency == 100
        assert score.score == 95.0
        assert json.loads(score.issues) == ["Anomaly: test"]
        assert db_session.query(AppConfig).filter(
            AppConfig.key.in_(("cs_rate_threshold", "nvd_rate_threshold"))
        ).count() == 0
        listed = client.get("/rules/").json()
        assert all(rule["rule_type"] != "BENCHMARK" for rule in listed)
        assert client.get(f"/rules/{benchmark_id}").status_code == 404

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
    def test_benchmark_failures_are_not_exposed(self, client, db_session):
        db_session.add(Rule(
            code="R041", name="Legacy benchmark", rule_type="BENCHMARK",
            severity="HIGH", category="STATISTICAL_BENCHMARK",
            expression_type="benchmark_rate", params="{}", description="Legacy",
        ))
        db_session.commit()
        resp = client.get("/rules/failures?rule_code=R041")
        assert resp.status_code == 404

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


class TestRuleFailureSearchAndSort:
    """Alerts screen: one search box over the whole row, and sorting that
    actually orders the result set (the old DOM sort only touched the loaded
    page, and months compared as numbers)."""

    @pytest.fixture(autouse=True)
    def _rows(self, db_session, client):
        from app.cache import cache as _cache
        _cache._cache.clear()
        self.hospitals = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).limit(3).all()
        assert len(self.hospitals) >= 3, "fixture needs at least three active hospitals"
        # Deterministic, deliberately unsorted: hospital order != month order.
        for i, h in enumerate(self.hospitals):
            h.name = f"Hosp-{3 - i}"
            db_session.commit()
            for month, code, sev in (
                ("2026-01", "R_BBB", "HIGH"),
                ("2026-03", "R_AAA", "CRITICAL"),
                ("2026-08", "R_CCC", "LOW"),
            ):
                db_session.add(ValidationResult(
                    hospital_id=h.id, month=month, rule_code=code,
                    rule_description=f"{code} alpha failure",
                    status="FAIL", severity=sev, rule_type="LOGIC",
                    details=f"{code} details needle-{i}",
                ))
        db_session.add(ValidationResult(
            hospital_id=self.hospitals[0].id,
            month="2026-08",
            rule_code="R_BENCHMARK",
            rule_description="Benchmark-only failure",
            status="FAIL",
            severity="CRITICAL",
            rule_type="BENCHMARK",
            details="Must not appear in Validation Alerts",
        ))
        db_session.commit()
        _cache._cache.clear()
        yield
        _cache._cache.clear()

    def _codes(self, client, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        resp = client.get("/analysis/rule-failures?" + q)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        return body, [d["rule_code"] for d in body["data"]]

    def test_search_matches_rule_code(self, client):
        body, codes = self._codes(client, q="R_AAA", limit=100)
        assert body["total"] == 3
        assert set(codes) == {"R_AAA"}

    def test_search_matches_details_text(self, client):
        # needle-2 is unique to one hospital → its three months, and only those.
        body, codes = self._codes(client, q="needle-2", limit=100)
        assert body["total"] == 3
        assert set(codes) == {"R_AAA", "R_BBB", "R_CCC"}
        assert {d["hospital"] for d in body["data"]} == {"Hosp-1"}

    def test_search_matches_hospital_name(self, client):
        body, _ = self._codes(client, q="Hosp-1", limit=100)
        assert body["total"] == 3

    def test_search_matches_month(self, client):
        body, _ = self._codes(client, q="2026-03", limit=100)
        assert body["total"] == 3

    def test_search_is_case_insensitive_and_ignores_blanks(self, client):
        body, _ = self._codes(client, q="r_aaa", limit=100)
        assert body["total"] == 3
        assert self._codes(client, q="   ", limit=100)[0]["total"] == 9

    def test_search_without_match_is_empty_not_error(self, client):
        body, codes = self._codes(client, q="zzz-no-such-thing", limit=100)
        assert body["total"] == 0
        assert codes == []

    def test_benchmark_failures_are_hidden_from_validation_alerts(self, client):
        body, codes = self._codes(client, limit=100)
        assert body["total"] == 9
        assert "R_BENCHMARK" not in codes

        overview = client.get("/alerts/overview")
        assert overview.status_code == 200, overview.text
        assert overview.json()["total_alerts"] == 9
        assert "outlier_count" not in overview.json()
        assert all(
            alert["rule_code"] != "R_BENCHMARK"
            for alert in overview.json()["recent_critical"]
        )

        listing = client.get("/alerts/list?limit=100")
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 9
        assert all(
            alert["rule_code"] != "R_BENCHMARK"
            for alert in listing.json()["items"]
        )

    def test_search_combines_with_existing_filters(self, client):
        body, codes = self._codes(client, q="R_", month="2026-01", limit=100)
        assert body["total"] == 3
        assert set(codes) == {"R_BBB"}

    def test_sort_by_hospital_name(self, client):
        body, _ = self._codes(client, sort_by="hospital", order="asc", limit=100)
        names = [d["hospital"] for d in body["data"]]
        assert names == sorted(names)

    def test_sort_by_hospital_name_desc(self, client):
        body, _ = self._codes(client, sort_by="hospital", order="desc", limit=100)
        names = [d["hospital"] for d in body["data"]]
        assert names == sorted(names, reverse=True)

    def test_sort_by_month_is_chronological_not_numeric(self, client):
        """The bug this pins: parseFloat('2026-08') = 2026, so every month of a
        year tied and 'newest first' came back in arbitrary order."""
        body, _ = self._codes(client, sort_by="month", order="desc", limit=100)
        months = [d["month"] for d in body["data"]]
        assert months == sorted(months, reverse=True)
        assert months[0] == "2026-08"

        body, _ = self._codes(client, sort_by="month", order="asc", limit=100)
        months = [d["month"] for d in body["data"]]
        assert months == sorted(months)
        assert months[0] == "2026-01"

    def test_sort_by_severity_uses_rank_not_alphabet(self, client):
        body, _ = self._codes(client, sort_by="severity", order="asc", limit=100)
        order = [d["severity"] for d in body["data"]]
        assert order == ["CRITICAL"] * 3 + ["HIGH"] * 3 + ["LOW"] * 3
        body, _ = self._codes(client, sort_by="severity", order="desc", limit=100)
        assert [d["severity"] for d in body["data"]][:3] == ["LOW"] * 3

    def test_default_sort_is_worst_severity_first(self, client):
        body, _ = self._codes(client, limit=100)
        assert [d["severity"] for d in body["data"]][:3] == ["CRITICAL"] * 3

    def test_unknown_sort_by_falls_back_instead_of_500(self, client):
        """An unrecognised column used to leave the SQLAlchemy sort expression
        unbound and raise UnboundLocalError on the first row fetch."""
        body, _ = self._codes(client, sort_by="nonsense", limit=100)
        assert body["total"] == 9
        assert [d["severity"] for d in body["data"]][:3] == ["CRITICAL"] * 3

    def test_sort_by_aliases(self, client):
        body, codes = self._codes(client, sort_by="rule_code", order="asc", limit=100)
        assert codes == sorted(codes)
        resp = client.get("/analysis/rule-failures?sort_by=rule_type&order=asc&limit=100")
        assert resp.status_code == 200, resp.text
        types = [d["rule_type"] for d in resp.json()["data"]]
        assert types == sorted(types)

    def test_search_and_sort_hit_different_cache_entries(self, client):
        _, plain = self._codes(client, limit=100)
        _, searched = self._codes(client, q="R_AAA", limit=100)
        assert len(plain) == 9 and len(searched) == 3


_PROBE_PARENT = "2"
_PROBE_CHILD = "2.a"   # seeded high -> ge FAILs while the rule points at it
_PROBE_OTHER = "2.b"   # seeded low  -> ge PASSes when the rule points here


def _seed_impact_data(db_session, parent_value=42.0, child_value=50.0,
                      other_value=0.0, month="2026-08"):
    """Give /rules/impact something to evaluate.

    The endpoint live-evaluates every rule against the single LATEST month that
    has indicator data, and returns an all-zero map when no data exists at all.
    Tests that assert on failure counts must therefore seed that month for every
    active hospital. Returns the month that became the latest one.
    """
    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    if not hosp:
        hosp = [Hospital(name="General Hospital", region="Region A", is_active=True)]
        db_session.add_all(hosp)
        db_session.flush()
    values = {_PROBE_PARENT: parent_value,
              _PROBE_CHILD: child_value,
              _PROBE_OTHER: other_value}
    for code, val in values.items():
        ind = db_session.query(Indicator).filter(Indicator.code == code).first()
        assert ind is not None, f"seeded indicator {code} missing"
        for h in hosp:
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind.id, month=month, value=val))
    db_session.commit()
    return month


class TestRuleImpact:
    def test_benchmark_rules_are_not_returned(self, client):
        result = client.get("/rules/impact?refresh=true").json()
        assert all(rule["rule_type"] != "BENCHMARK" for rule in result)
        assert all(rule["category"] != "STATISTICAL_BENCHMARK" for rule in result)

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

    def test_impact_includes_params_for_drawer(self, client, db_session):
        """The rules drawer renders Parameters straight from the impact map —
        every entry must carry the rule's parsed params dict."""
        resp = client.get("/rules/impact")
        assert resp.status_code == 200
        for r in resp.json():
            assert "params" in r, "impact entry missing params — drawer falls back to stale local JSON"
            assert isinstance(r["params"], dict)
        # Cross-check against the DB: parsed params must match the stored blob
        by_code = {r["code"]: r["params"] for r in resp.json()}
        for rule in db_session.query(Rule).all():
            expected = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
            assert by_code.get(rule.code) == expected

    def test_impact_nonempty(self, client):
        resp = client.get("/rules/impact")
        assert resp.status_code == 200
        assert resp.json() != []

    def test_impact_carries_historical_alert_counts(self, client):
        """failure_count only reflects the latest month, so a rule that failed in
        earlier months (e.g. R060) looked permanently clean. Every entry must
        carry its all-months alert totals."""
        resp = client.get("/rules/impact")
        assert resp.status_code == 200
        for r in resp.json():
            assert "alert_count" in r
            assert "alert_hospitals" in r
            assert "last_alert_month" in r
            assert isinstance(r["alert_count"], int)
            assert isinstance(r["alert_hospitals"], int)

    def test_impact_alert_counts_match_stored_failures(self, client, db_session):
        resp = client.get("/rules/impact")
        by_code = {r["code"]: r for r in resp.json()}
        expected = dict(
            db_session.query(ValidationResult.rule_code, func.count())
            .filter(ValidationResult.status == "FAIL")
            .group_by(ValidationResult.rule_code)
            .all()
        )
        for code, entry in by_code.items():
            assert entry["alert_count"] == expected.get(code, 0), f"{code} alert_count mismatch"

    def test_impact_alert_hospitals_are_distinct(self, client, db_session):
        """alert_hospitals counts distinct facilities, not FAIL rows — one
        hospital failing six months must report 1, not 6."""
        resp = client.get("/rules/impact")
        by_code = {r["code"]: r for r in resp.json()}
        expected = dict(
            db_session.query(
                ValidationResult.rule_code,
                func.count(func.distinct(ValidationResult.hospital_id)),
            )
            .filter(ValidationResult.status == "FAIL")
            .group_by(ValidationResult.rule_code)
            .all()
        )
        for code, entry in by_code.items():
            assert entry["alert_hospitals"] == expected.get(code, 0), f"{code} alert_hospitals mismatch"

    def test_impact_last_alert_month_is_max(self, client, db_session):
        resp = client.get("/rules/impact")
        by_code = {r["code"]: r for r in resp.json()}
        expected = dict(
            db_session.query(ValidationResult.rule_code, func.max(ValidationResult.month))
            .filter(ValidationResult.status == "FAIL")
            .group_by(ValidationResult.rule_code)
            .all()
        )
        for code, entry in by_code.items():
            assert entry["last_alert_month"] == expected.get(code), f"{code} last_alert_month mismatch"

    def test_impact_evaluates_disabled_rules(self, client, db_session):
        """A disabled rule is still live-evaluated so the Rules Manager reflects
        the saved definition while it is being tuned.

        Regression: disabled rules were skipped, so the impact column reported a
        hard 0 and the UI rendered it as "no hospitals affected" — identical to a
        clean pass, which made editing a disabled rule look like it had no effect.
        """
        month = _seed_impact_data(db_session)
        rule = db_session.query(Rule).filter(Rule.code == "R061").first()
        rule.enabled = False
        rule.expression_type = "ge"
        rule.params = json.dumps({"parent": _PROBE_PARENT, "children": [_PROBE_CHILD]})
        db_session.commit()

        entry = {r["code"]: r for r in client.get("/rules/impact?refresh=true").json()}[rule.code]
        assert entry["month"] == month
        assert entry["enabled"] is False
        assert entry["failure_count"] >= 1, "disabled rule must still be evaluated"
        assert entry["hospitals_affected"], "disabled rule must still report affected hospitals"

    def test_impact_enabled_flag_present(self, client):
        """Every entry carries `enabled` so the UI can label the impact number
        instead of implying a disabled rule is passing."""
        for r in client.get("/rules/impact").json():
            assert "enabled" in r
            assert isinstance(r["enabled"], bool)

    def test_impact_update_then_reflects_new_params(self, client, db_session):
        """The full loop the user hit: change the definition, refetch with
        ?refresh=true, and the affected-hospitals figure must follow."""
        _seed_impact_data(db_session)
        rule = db_session.query(Rule).filter(Rule.code == "R061").first()
        rule.enabled = True
        rule.expression_type = "ge"
        rule.params = json.dumps({"parent": _PROBE_PARENT, "children": [_PROBE_CHILD]})
        db_session.commit()

        before = {r["code"]: r for r in client.get("/rules/impact?refresh=true").json()}[rule.code]
        assert before["failure_count"] >= 1, "children sum above the parent must fail"

        # Repoint the rule at the low-valued indicator: the figure must follow.
        res = client.put(f"/rules/{rule.id}", json={"params": json.dumps(
            {"parent": _PROBE_PARENT, "children": [_PROBE_OTHER]})})
        assert res.status_code == 200

        after = {r["code"]: r for r in client.get("/rules/impact?refresh=true").json()}[rule.code]
        assert after["failure_count"] == 0, "repointed rule must pass immediately"
        assert after["hospitals_affected"] == []

    def test_impact_passed_rule_still_reports_old_alerts(self, client, db_session):
        """The exact confusion this fixes: a rule passing in the latest month
        while carrying FAIL rows from earlier months."""
        rule = db_session.query(Rule).filter(Rule.code == "R051").first()
        hosp = db_session.query(Hospital).first()
        db_session.add(ValidationResult(
            hospital_id=hosp.id, month="2020-01", rule_code=rule.code,
            rule_description=rule.name, status="FAIL",
            severity=rule.severity, rule_type=rule.rule_type,
            details="historical failure",
        ))
        db_session.commit()

        entry = {r["code"]: r for r in client.get("/rules/impact?refresh=true").json()}[rule.code]
        assert entry["alert_count"] >= 1
        assert entry["last_alert_month"] == "2020-01"


class TestStoredScoreRefresh:
    """ValidationResult / QualityScore are persisted snapshots. A rule edit must
    refresh them, otherwise the hospital card keeps showing a pre-edit score
    while the Rules Manager shows the rule failing."""

    def test_recompute_updates_stored_quality_score(self, client, db_session):
        from app.api.rules import _run_latest_month_recompute
        from app.models import QualityScore

        month = _seed_impact_data(db_session)
        hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()

        # A rule that fails: children sum above the parent.
        rule = db_session.query(Rule).filter(Rule.code == "R061").first()
        rule.enabled = True
        rule.expression_type = "ge"
        rule.params = json.dumps({"parent": _PROBE_PARENT, "children": [_PROBE_CHILD]})
        db_session.commit()

        _run_latest_month_recompute("test-task", month, [hosp.id])

        qs = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == hosp.id, QualityScore.month == month).first()
        assert qs is not None, "recompute must write a QualityScore row"
        assert qs.rule_compliance < 100.0, (
            "a failing rule must pull the stored compliance below 100")
        fails = db_session.query(ValidationResult).filter(
            ValidationResult.hospital_id == hosp.id,
            ValidationResult.month == month,
            ValidationResult.status == "FAIL").all()
        # Other rules legitimately fail on this sparse fixture (only 3 indicators
        # are seeded); what matters is that R061's FAIL was persisted.
        assert rule.code in [v.rule_code for v in fails]

    def test_recompute_status_is_quiet_when_idle(self, client):
        resp = client.get("/rules/recompute-status")
        assert resp.status_code == 200
        assert resp.json() == {"running": False}

    def test_second_rule_edit_during_a_running_pass_is_re_applied(
            self, client, db_session, monkeypatch):
        """Two edits in quick succession must BOTH reach the stored scores.

        The scheduler never runs two engine passes at once, so the second edit
        is coalesced into the pass already running — but that pass may have read
        the rules before the second edit landed, and it reports "done" to the
        UI either way. The change would then be silently lost: the manager sees
        a finished refresh and a score that ignores their edit. A coalesced
        edit must therefore queue exactly one follow-up pass.
        """
        import types
        import threading as real_threading
        import app.api.rules as rules_mod
        import app.engine.pipeline as pipeline_mod

        month = _seed_impact_data(db_session)
        hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()

        # isolate the module-level scheduler state for this test
        monkeypatch.setattr(
            rules_mod, "_latest_recompute",
            {"running": False, "task_id": None, "pending": False},
        )
        threads = []

        class _FakeThread:
            def __init__(self, target=None, args=(), **kwargs):
                threads.append((target, args))

            def start(self):
                pass

        monkeypatch.setattr(
            rules_mod, "threading",
            types.SimpleNamespace(Thread=_FakeThread, Lock=real_threading.Lock),
        )
        ran = []
        monkeypatch.setattr(
            pipeline_mod, "recompute_hospital_months",
            lambda db, hid, months, force=False: ran.append((hid, list(months), force)),
        )

        # A pass is already running when the user's second edit is saved.
        rules_mod._latest_recompute["running"] = True
        rules_mod._latest_recompute["task_id"] = "first-pass"

        task_id = rules_mod._schedule_latest_month_recompute()
        # the in-flight pass is reused, not duplicated …
        assert task_id == "first-pass"
        assert threads == [], "a second pass must not run in parallel"
        # … and the edit is remembered for a follow-up.
        assert rules_mod._latest_recompute["pending"] is True

        # When the running pass finishes it must schedule that follow-up.
        result = rules_mod._run_latest_month_recompute(
            "first-pass", month, [hosp.id])
        assert result["month"] == month
        assert ran == [(hosp.id, [month], True)]
        assert len(threads) == 1, "the coalesced edit must queue a follow-up pass"
        assert rules_mod._latest_recompute["pending"] is False, (
            "the follow-up is consumed exactly once")
        assert rules_mod._latest_recompute["running"] is False

    def test_recompute_latest_rejects_when_no_data(self, client, db_session):
        db_session.query(IndicatorValue).delete()
        db_session.commit()
        resp = client.post("/rules/recompute-latest")
        assert resp.status_code == 400

    @pytest.mark.parametrize("method,path,body", [
        ("put", "/rules/{rid}", {"description": "changed"}),
        ("put", "/rules/{rid}/toggle", None),
        ("delete", "/rules/{rid}", None),
    ])
    def test_mutations_schedule_a_recompute(self, client, db_session, monkeypatch,
                                            method, path, body):
        """Every rule mutation must refresh the stored scores, not just the
        in-memory impact cache."""
        import app.api.rules as rules_mod
        calls = []
        monkeypatch.setattr(rules_mod, "_schedule_latest_month_recompute",
                            lambda *a, **k: calls.append(1))
        rule = db_session.query(Rule).filter(Rule.code == "R061").first()
        url = path.format(rid=rule.id)
        fn = getattr(client, method)
        if body is None:
            fn(url)
        else:
            fn(url, json=body)
        assert calls, f"{method.upper()} {url} did not schedule a recompute"

    def test_toggle_invalidates_impact_cache(self, client, db_session):
        """toggle_rule never dropped the impact memo, so enabling a rule left
        the Rules Manager showing the old figure for up to 5 minutes."""
        import app.api.rules as rules_mod
        calls = []
        original = rules_mod._invalidate_impact_cache

        def spy():
            calls.append(1)
            return original()

        rules_mod._invalidate_impact_cache = spy
        try:
            rule = db_session.query(Rule).filter(Rule.code == "R061").first()
            before = rule.enabled
            client.put(f"/rules/{rule.id}/toggle")
            assert calls, "toggle must invalidate the impact cache"
            db_session.refresh(rule)
            assert rule.enabled != before
        finally:
            rules_mod._invalidate_impact_cache = original


class TestRuleValidate:
    def test_validate_benchmark_rule_is_rejected(self, client):
        resp = client.post("/rules/validate", json={
            "code": "RBENCH",
            "rule_type": "BENCHMARK",
            "category": "STATISTICAL_BENCHMARK",
            "expression_type": "cross_hospital_rate",
            "params": {"num_code": "5", "den_code": "2", "z_threshold": 2.5},
        })
        assert resp.status_code == 422

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
    def test_test_benchmark_rule_is_rejected(self, client):
        resp = client.post("/rules/test", json={
            "rule_type": "BENCHMARK",
            "expression_type": "benchmark_rate",
            "params": {"num_code": "5", "den_code": "2", "threshold": 80},
        })
        assert resp.status_code == 422

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
            assert r["rule_type"] != "BENCHMARK"
            assert r["category"] != "STATISTICAL_BENCHMARK"
            assert r["expression_type"] not in {"benchmark_rate", "benchmark_low_rate", "cross_hospital_rate"}

    def test_import_skips_benchmark_rule(self, client, db_session):
        resp = client.post("/rules/import", json={"rules": [{
            "code": "TESTIMP_BENCH",
            "name": "Benchmark Rule",
            "rule_type": "BENCHMARK",
            "severity": "HIGH",
            "category": "STATISTICAL_BENCHMARK",
            "expression_type": "benchmark_rate",
            "params": {"num_code": "5", "den_code": "2", "threshold": 80},
        }]})
        assert resp.status_code == 200
        assert resp.json()["created"] == 0
        assert resp.json()["skipped"][0]["code"] == "TESTIMP_BENCH"
        assert db_session.query(Rule).filter_by(code="TESTIMP_BENCH").first() is None

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


class TestImpactCacheInvalidation:
    """Editing a rule must immediately refresh /rules/impact — the drawer's
    'Referenced indicators' and 'Affected hospitals' read from that map, and
    it used to stay stale for up to 5 minutes after a save."""

    def _seed_impact_data(self, db_session):
        """/rules/impact only memoizes when a latest data month exists — seed
        one hospital-month of indicator values so the cache is exercised."""
        from app.models import IndicatorValue, Hospital
        hosp = db_session.query(Hospital).first()
        ind = db_session.query(Rule).first()  # noqa: F841 (rules seeded too)
        from app.models import Indicator
        indicator = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01",
                                      indicator_id=indicator.id, value=10))
        db_session.commit()
        from app.cache import cache
        cache.invalidate("analysis:months")

    def test_update_rule_refreshes_impact(self, client, db_session):
        from app.api import rules as rules_api

        self._seed_impact_data(db_session)
        rule = db_session.query(Rule).first()
        # Warm the cache by calling impact directly through the endpoint
        first = client.get("/rules/impact").json()
        assert rules_api._impact_cache["data"] is not None
        before = next(x for x in first if x["code"] == rule.code)

        # Change the rule's params (children) — a real edit
        import json as _json
        params = _json.loads(rule.params or "{}")
        params["children"] = (params.get("children") or [])[:1] or ["3"]
        resp = client.put(f"/rules/{rule.id}", json={"params": _json.dumps(params)})
        assert resp.status_code == 200

        # The memo must have been dropped, and the new impact reflects the edit
        assert rules_api._impact_cache["data"] is None
        second = client.get("/rules/impact").json()
        after = next(x for x in second if x["code"] == rule.code)
        assert after["ref_codes"] != before["ref_codes"], (
            "impact ref_codes unchanged after rule edit — impact cache was not invalidated"
        )

    def test_delete_rule_invalidates_impact_cache(self, client, db_session):
        from app.api import rules as rules_api

        self._seed_impact_data(db_session)
        client.get("/rules/impact")
        assert rules_api._impact_cache["data"] is not None
        rule = db_session.query(Rule).first()
        resp = client.delete(f"/rules/{rule.id}")
        assert resp.status_code == 200
        assert rules_api._impact_cache["data"] is None
