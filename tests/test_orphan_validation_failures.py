"""Failures whose rule no longer exists must never reach the Alerts screens.

ValidationResult is a stored snapshot: rows written when a rule existed stay
behind after the rule is deleted (or after a restore brings rows back without
their Rule). The Alerts screens used to list those rows by code alone, so a
deleted rule kept showing failures that the Rules Manager could not explain —
"R0xx failed, but R0xx does not exist".

Three guards are pinned here:
  * the Alerts overview/list and /analysis/rule-failures join the Rule table, so
    an orphan code is unlistable even before cleanup runs;
  * deleting a rule removes its stored results in the same transaction;
  * the cache epoch fingerprints the FAIL rows, so rewritten/deleted failures
    invalidate cached alert payloads instead of being served for a day.
"""
import pytest
from fastapi.testclient import TestClient

from app import cache as cache_mod
from app.models import Hospital, Rule, ValidationResult

# Captured at import time, before the conftest cache fixture replaces
# cache.compute_data_epoch with a constant: these tests exercise the real
# fingerprint against the test database.
_REAL_COMPUTE_EPOCH = cache_mod.compute_data_epoch

ORPHAN_CODE = "R999_DELETED"


@pytest.fixture
def client(app):
    return TestClient(app)


def _real_rule(db_session):
    rule = (
        db_session.query(Rule)
        .filter(Rule.rule_type != "BENCHMARK",
                Rule.category != "STATISTICAL_BENCHMARK")
        .order_by(Rule.code)
        .first()
    )
    assert rule is not None, "conftest seeds validation rules"
    return rule


def _add_failure(db_session, code, status="FAIL", severity="CRITICAL"):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    assert hospital is not None
    row = ValidationResult(
        hospital_id=hospital.id,
        month="2026-08",
        rule_code=code,
        rule_description=f"stored result for {code}",
        status=status,
        severity=severity,
        rule_type="LOGIC",
        details="seeded by test",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _codes(payload):
    # /alerts/list returns "items"; /analysis/rule-failures returns "data".
    rows = payload.get("items", payload.get("data", []))
    return [item["rule_code"] for item in rows]


def test_orphan_failure_is_hidden_from_every_alert_screen(client, db_session):
    _add_failure(db_session, ORPHAN_CODE)

    listing = client.get("/alerts/list?limit=100").json()
    assert listing["total"] == 0
    assert ORPHAN_CODE not in _codes(listing)

    overview = client.get("/alerts/overview").json()
    assert overview["total_alerts"] == 0
    assert ORPHAN_CODE not in [r["rule_code"] for r in overview["recent_critical"]]

    failures = client.get("/analysis/rule-failures?limit=100").json()
    assert failures["total"] == 0
    assert ORPHAN_CODE not in _codes(failures)


def test_failure_of_an_existing_rule_is_still_listed(client, db_session):
    rule = _real_rule(db_session)
    _add_failure(db_session, rule.code)

    listing = client.get("/alerts/list?limit=100").json()
    assert listing["total"] == 1
    assert rule.code in _codes(listing)

    overview = client.get("/alerts/overview").json()
    assert overview["total_alerts"] == 1
    assert rule.code in [r["rule_code"] for r in overview["recent_critical"]]

    failures = client.get("/analysis/rule-failures?limit=100").json()
    assert failures["total"] == 1
    assert rule.code in _codes(failures)


def test_deleting_a_rule_removes_its_failures_immediately(
        client, db_session, monkeypatch):
    import app.api.rules as rules_api

    # The cleanup must not depend on the background re-scoring pass.
    monkeypatch.setattr(rules_api, "_schedule_latest_month_recompute",
                        lambda *args, **kwargs: None)

    rule = _real_rule(db_session)
    _add_failure(db_session, rule.code)
    assert client.get("/alerts/list?limit=100").json()["total"] == 1

    resp = client.delete(f"/rules/{rule.id}")
    assert resp.status_code == 200, resp.text

    remaining = (db_session.query(ValidationResult)
                 .filter(ValidationResult.rule_code == rule.code).count())
    assert remaining == 0
    assert client.get("/alerts/list?limit=100").json()["total"] == 0
    assert client.get("/alerts/overview").json()["total_alerts"] == 0


def test_cache_epoch_tracks_the_failure_set(db_session):
    rule = _real_rule(db_session)
    before = _REAL_COMPUTE_EPOCH()

    row = _add_failure(db_session, rule.code)
    appeared = _REAL_COMPUTE_EPOCH()
    assert appeared != before, (
        "a new failure must invalidate cached alert payloads")

    row.status = "PASS"
    db_session.commit()
    cleared = _REAL_COMPUTE_EPOCH()
    assert cleared != appeared, (
        "a cleared failure must invalidate cached alert payloads")
