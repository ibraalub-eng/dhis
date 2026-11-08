"""A3.5 P1 — Rules settings are immutable snapshot content (``RulesPolicy``).

Every assertion here is about *explicit* policy:

* the resolver's five ``rules.*`` entries become a frozen ``RulesPolicy``;
* rule evaluation, coverage and the Rules preview read that value;
* the legacy ``_RULES_CONFIG`` table is inert (the shim records the call and
  moves nothing), so two concurrent operations cannot leak settings;
* the pipeline no longer writes the global per hospital-month.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import threading

import pytest
from fastapi.testclient import TestClient

from app.engine import config_resolver as cr
from app.engine import pipeline
from app.engine.policy_view import rules_policy_from_snapshot
from app.engine.quality import (
    ValidationContext,
    compute_covered_codes,
    run_all_rules,
)
from app.engine.quality import definitions as quality_definitions
from app.engine.quality import rules as rules_mod
from app.engine.quality.definitions import (
    DEFAULT_RULES_POLICY,
    RULE_DEFAULTS,
    RULE_POLICY_KEYS,
    RulesPolicy,
)
from app.models import AppConfig, Hospital, Indicator, IndicatorValue, ValidationResult

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONTH = "2033-01"


def _set_rules(db, **values):
    db.query(AppConfig).filter(AppConfig.category == "rules").delete(
        synchronize_session=False)
    for key, value in values.items():
        db.add(AppConfig(key=key, value=str(value), category="rules", label=key))
    db.commit()
    # Each HTTP request in production gets its own session; the shared test
    # session memoizes the display snapshot, so drop it to model a new request.
    try:
        db.info.pop("display_policy_snapshot", None)
    except Exception:
        pass


def _ctx(values, rules=None):
    return ValidationContext(values=values, hospital_name="H", month=MONTH,
                             rules=rules or DEFAULT_RULES_POLICY)


def _status(results, code):
    for result in results:
        if result.rule_code == code:
            return result.status
    raise AssertionError(f"{code} not evaluated")


def _seed_off_by_five(db):
    """One analysable hospital/month whose R002 total is off by exactly 5."""
    hospital = db.query(Hospital).filter(Hospital.name == "Central Medical").first()
    for code, value in (("2", 105.0), ("2.a", 60.0), ("2.b", 40.0),
                        ("3", 74.0), ("4", 11.0), ("5", 20.0), ("6", 99.0)):
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital.id,
                              indicator_id=indicator.id,
                              month=MONTH, value=value))
    db.commit()
    return hospital


# ── the immutable carrier ─────────────────────────────────────────────────


def test_snapshot_rules_entries_become_a_policy(db_session):
    _set_rules(db_session, eq_tolerance=0.5)
    policy = rules_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    assert isinstance(policy, RulesPolicy)
    assert policy.eq_tolerance == pytest.approx(0.5)
    # Stored in the snapshot as a documented default, not a second guess.
    assert policy.month_over_factor == pytest.approx(RULE_DEFAULTS["month_over_factor"])
    assert set(policy.as_dict()) == set(RULE_POLICY_KEYS)


def test_missing_settings_resolve_to_the_documented_defaults(db_session):
    policy = rules_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    assert policy.as_dict() == dict(RULE_DEFAULTS)
    assert policy == DEFAULT_RULES_POLICY


@pytest.mark.parametrize("stored", [
    {},
    {"eq_tolerance": "0.5"},
    {"eq_tolerance": "10.0", "month_under_factor": "0.4"},
])
def test_snapshot_policy_equals_the_legacy_category_read(db_session, stored):
    """Parity: the new carrier reproduces exactly what the old global held.

    P0/P1 are behaviour-preserving: whatever ``get_config_dict(db, "rules")``
    returned to the pre-A3.5 setter must equal the snapshot-derived policy for
    the same rows (stored values win, missing keys use the documented default).
    """
    from app.config_utils import get_config_dict

    _set_rules(db_session)
    for key, value in stored.items():
        db_session.add(AppConfig(key=key, value=value, category="rules", label=key))
    db_session.commit()

    legacy = RulesPolicy.from_mapping(get_config_dict(db_session, "rules"))
    from_snapshot = rules_policy_from_snapshot(
        cr.load_policy_snapshot(db_session))
    assert from_snapshot == legacy


def test_policy_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_RULES_POLICY.eq_tolerance = 1.0  # type: ignore[misc]


def test_from_mapping_rejects_non_numeric_instead_of_coercing():
    with pytest.raises(ValueError):
        RulesPolicy.from_mapping({"eq_tolerance": "not-a-number"})


# ── evaluation reads the policy, never the legacy table ──────────────────


def test_rule_evaluation_uses_the_context_policy():
    ctx = _ctx({"2": 100, "2.a": 105, "2.b": 0})
    assert _status(run_all_rules(ctx), "R002").value == "FAIL"

    ctx.rules = RulesPolicy(eq_tolerance=10.0)
    assert _status(run_all_rules(ctx), "R002").value == "PASS"


def test_legacy_table_cannot_change_an_evaluation(monkeypatch):
    monkeypatch.setitem(quality_definitions._RULES_CONFIG, "eq_tolerance", 99.0)
    ctx = _ctx({"2": 100, "2.a": 105, "2.b": 0})
    assert _status(run_all_rules(ctx), "R002").value == "FAIL"


def test_month_factors_come_from_the_policy():
    def run(factor):
        ctx = _ctx({"2": 350}, RulesPolicy(month_over_factor=factor))
        ctx.historical_data = {"2": 100.0}
        return _status(run_all_rules(ctx), "R051").value

    assert run(3.0) == "PASS"
    assert run(2.0) == "FAIL"


def test_coverage_uses_explicit_policy(db_session):
    values = {"2": 100.0, "2.a": 95.0}
    strict = compute_covered_codes(values, set(), db_session)
    loose = compute_covered_codes(values, set(), db_session,
                                  rules=RulesPolicy(eq_tolerance=10.0))
    assert "2.b" not in strict
    assert "2.b" in loose


def test_set_rules_config_is_inert(monkeypatch):
    baseline = dict(quality_definitions._RULES_CONFIG)
    rules_mod.set_rules_config({"eq_tolerance": 0.5})
    assert dict(quality_definitions._RULES_CONFIG) == baseline


# ── concurrency / isolation ───────────────────────────────────────────────


def _two_policies():
    strict = rules_policy_from_snapshot(
        cr.resolve_policy({"eq_tolerance": "0.01"}, {}))
    loose = rules_policy_from_snapshot(
        cr.resolve_policy({"eq_tolerance": "10.0"}, {}))
    return strict, loose


def test_two_concurrent_evaluations_keep_their_own_policy():
    strict, loose = _two_policies()
    barrier = threading.Barrier(2)
    seen = {}
    errors = []

    def worker(name, policy):
        try:
            ctx = _ctx({"2": 100, "2.a": 105, "2.b": 0}, policy)
            barrier.wait(timeout=5)
            seen[name] = _status(run_all_rules(ctx), "R002").value
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=("strict", strict)),
               threading.Thread(target=worker, args=("loose", loose))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert seen == {"strict": "FAIL", "loose": "PASS"}


def test_two_concurrent_coverage_calls_keep_their_own_policy():
    strict, loose = _two_policies()
    barrier = threading.Barrier(2)
    seen = {}

    def worker(name, policy):
        barrier.wait(timeout=5)
        seen[name] = "2.b" in compute_covered_codes(
            {"2": 100.0, "2.a": 95.0}, set(), None, rules=policy)

    threads = [threading.Thread(target=worker, args=("strict", strict)),
               threading.Thread(target=worker, args=("loose", loose))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert seen == {"strict": False, "loose": True}


# ── pipeline integration and zero-caller audit ────────────────────────────


def test_pipeline_no_longer_writes_the_rules_global():
    source = (ROOT / "app" / "engine" / "pipeline.py").read_text(encoding="utf-8")
    assert "set_rules_config(" not in source
    assert "_RULES_CONFIG" not in source

    rules_source = (ROOT / "app" / "engine" / "quality" / "rules.py").read_text(
        encoding="utf-8")
    assert "_RULES_CONFIG[" not in rules_source

    callers = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "set_rules_config":
                callers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert callers == []


def test_pipeline_consumes_the_stored_tolerance(db_session):
    hospital = _seed_off_by_five(db_session)

    _set_rules(db_session, eq_tolerance=10.0)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    stored = db_session.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital.id,
        ValidationResult.month == MONTH,
        ValidationResult.rule_code == "R002").first()
    assert stored is not None and stored.status == "PASS"

    _set_rules(db_session, eq_tolerance=0.01)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    stored = db_session.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital.id,
        ValidationResult.month == MONTH,
        ValidationResult.rule_code == "R002").first()
    assert stored is not None and stored.status == "FAIL"


def test_rules_preview_uses_the_stored_policy(app, db_session, monkeypatch):
    hospital = _seed_off_by_five(db_session)
    body = {
        "code": "R002",
        "name": "Primigravida + Multigravida ≈ Total Deliveries",
        "rule_type": "LOGIC",
        "severity": "MEDIUM",
        "expression_type": "eq",
        "params": {"parent": "2", "children": ["2.a", "2.b"]},
        "hospital_id": hospital.id,
        "month": MONTH,
    }
    client = TestClient(app)

    _set_rules(db_session, eq_tolerance=0.01)
    assert client.post("/rules/test", json=body).json()["status"] == "FAIL"

    # The stored value is what matters — not whatever a previous analysis left
    # in the process-global table.
    _set_rules(db_session, eq_tolerance=10.0)
    monkeypatch.setitem(quality_definitions._RULES_CONFIG, "eq_tolerance", 0.01)
    assert client.post("/rules/test", json=body).json()["status"] == "PASS"
