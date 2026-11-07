"""A3.5 P2 — trend settings are immutable snapshot content (``TrendsPolicy``).

Every assertion is about *explicit* policy:

* the snapshot's trend plane, slope bands, five engine gates and Z threshold
  become one frozen ``TrendsPolicy``;
* the engine reads that policy and nothing else, so a poisoned global or a
  stale request cannot change a finding;
* the pipeline performs no trend configuration read and no global write;
* the Explain display uses the same policy (the historical 25% default is
  gone: it was never the engine's default);
* two concurrent evaluations keep their own policies.
"""
from __future__ import annotations

import ast
import dataclasses
import math
import pathlib
import threading

import pytest
from fastapi.testclient import TestClient

from app.engine import config_resolver as cr
from app.engine import pipeline as pipeline_mod
from app.engine import severity as severity_policy
from app.engine.anomaly import trends
from app.engine.anomaly.trends import (
    TREND_ENGINE_DEFAULTS,
    TREND_GATE_KEYS,
    analyze_historical_trends,
    detect_trend_anomalies,
    trends_policy_from_config,
)
from app.engine.policy_view import (
    analysis_config_from_snapshot,
    trends_policy_from_snapshot,
)
from app.engine.audit.explain import explain_anomaly
from app.models import (
    AnomalyResult, AppConfig, Hospital, Indicator, IndicatorValue, SystemSetting)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONTHS = ("2033-02", "2033-03", "2033-04", "2033-05")


@pytest.fixture
def client(app):
    return TestClient(app)


def _app(db, key, value, category="trends"):
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        db.add(AppConfig(key=key, value=float(value), category=category, label=key))
    else:
        row.value = float(value)
    db.commit()


def _setting(db, key, value):
    db.add(SystemSetting(key=key, value=str(value)))
    db.commit()


def _series(values):
    """Four months of C-section inputs: ``5`` over the ``2`` denominator."""
    return {month: {"5": value, "2": 200.0}
            for month, value in zip(MONTHS, values)}


def _c_section(rows):
    return next(row for row in rows if "C-section" in row.rate_name)


# ── resolution ─────────────────────────────────────────────────────────────
def test_defaults_match_the_engine_table(db_session):
    policy = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    resolved = policy.as_dict()

    assert policy.settings.window == 12
    assert dict(policy.bands) == severity_policy.default_trend_bands()
    for gate in TREND_GATE_KEYS:
        assert resolved[gate] == pytest.approx(TREND_ENGINE_DEFAULTS[gate]), gate
    assert policy.zscore_threshold == 2.5

    analysis = analysis_config_from_snapshot(cr.load_policy_snapshot(db_session))
    assert policy.settings == analysis.trend
    assert policy.zscore_threshold == analysis.zscore_threshold


def test_all_five_gates_and_the_window_are_read_from_the_snapshot(db_session):
    for key, value in {
        "trend_finding_slope": 8.5,
        "trend_finding_deviation": 33.0,
        "trend_finding_cv": 44.0,
        "trend_finding_r_squared": 0.9,
        "trend_r_squared": 0.6,
    }.items():
        _app(db_session, key, value)
    _setting(db_session, "trend_analysis_window", 6)
    _app(db_session, "trend_slope_stable", 1.5)

    policy = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))

    assert policy.finding_slope == pytest.approx(8.5)
    assert policy.finding_deviation == pytest.approx(33.0)
    assert policy.finding_cv == pytest.approx(44.0)
    assert policy.finding_r_squared == pytest.approx(0.9)
    assert policy.trend_r_squared == pytest.approx(0.6)
    assert policy.settings.window == 6
    assert policy.bands["stable"] == pytest.approx(1.5)


def test_partial_configuration_matches_the_legacy_flow(db_session):
    _app(db_session, "trend_finding_deviation", 33.0)

    policy = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    analysis = severity_policy.load_analysis_config(db_session)
    legacy = trends_policy_from_config(analysis.trend_engine_config())

    assert policy.settings == analysis.trend
    assert dict(policy.bands) == dict(analysis.trend_bands)
    assert policy.finding_deviation == legacy.finding_deviation == 33.0
    assert policy.finding_slope == legacy.finding_slope
    assert policy.zscore_threshold == legacy.zscore_threshold


def test_legacy_absent_gates_keep_the_engine_defaults():
    policy = trends_policy_from_config(None)
    for key in TREND_GATE_KEYS:
        assert float(policy.as_dict()[key]) == TREND_ENGINE_DEFAULTS[key]


def test_legacy_malformed_gates_are_rejected_not_silently_defaulted():
    # The pre-P2 engine compared these raw values with numbers, so a string or
    # None raised TypeError; the adapter keeps that contract instead of
    # substituting the default (which would silently change findings).
    for key in ("trend_finding_slope", "trend_finding_deviation",
                "trend_finding_cv", "trend_finding_r_squared",
                "trend_r_squared"):
        with pytest.raises(TypeError):
            trends_policy_from_config({key: "oops"})
        with pytest.raises(TypeError):
            trends_policy_from_config({key: None})
        with pytest.raises(TypeError):
            trends_policy_from_config({key: "10"})
    with pytest.raises(TypeError):
        trends_policy_from_config({"trend_finding_consecutive": "3"})
    with pytest.raises(TypeError):
        trends_policy_from_config({"trend_finding_consecutive": None})
    with pytest.raises(ValueError):
        trends_policy_from_config({"trend_finding_consecutive": float("inf")})


def test_legacy_z_threshold_keeps_its_float_contract():
    assert trends_policy_from_config({"zscore_threshold": "3.5"}) \
        .zscore_threshold == 3.5
    with pytest.raises(ValueError):
        trends_policy_from_config({"zscore_threshold": "oops"})
    with pytest.raises(TypeError):
        trends_policy_from_config({"zscore_threshold": None})


def test_legacy_non_finite_gates_are_not_rejected():
    # The old comparisons accepted nan/inf; they simply never fired. Keep that
    # pass-through rather than inventing a new rejection on the legacy path.
    policy = trends_policy_from_config({"trend_finding_cv": float("nan")})
    assert math.isnan(policy.finding_cv)


def test_legacy_valid_values_keep_their_meaning():
    policy = trends_policy_from_config({
        "trend_finding_slope": 8,
        "trend_finding_deviation": 33.0,
        "trend_finding_cv": 44.0,
        "trend_finding_r_squared": 0.9,
        "trend_r_squared": 0.6,
        "trend_finding_consecutive": 4,
    })
    assert policy.finding_slope == 8.0
    assert policy.finding_deviation == 33.0
    assert policy.finding_cv == 44.0
    assert policy.finding_r_squared == 0.9
    assert policy.trend_r_squared == 0.6
    assert policy.settings.trend_finding_consecutive == 4


def test_invalid_gate_falls_back_and_is_reported():
    snapshot = cr.resolve_policy({"trend_finding_cv": "not-a-number"}, {})
    policy = trends_policy_from_snapshot(snapshot)

    assert policy.finding_cv == pytest.approx(TREND_ENGINE_DEFAULTS["trend_finding_cv"])
    assert snapshot.entries["trend_finding_cv"].source == "invalid"
    assert "trend_finding_cv" in snapshot.invalid_keys


def test_trends_policy_is_frozen():
    policy = trends_policy_from_snapshot(cr.resolve_policy({}, {}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.finding_slope = 1.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        policy.bands["stable"] = 99.0  # type: ignore[index]


# ── engine behaviour ───────────────────────────────────────────────────────
def test_engine_findings_follow_the_supplied_deviation_gate():
    monthly = _series((25.0, 28.0, 30.0, 35.0))
    loose = trends_policy_from_snapshot(cr.resolve_policy(
        {"trend_finding_deviation": 1000.0}, {}))
    strict = trends_policy_from_snapshot(cr.resolve_policy(
        {"trend_finding_deviation": 10.0}, {}))

    loose_row = _c_section(analyze_historical_trends("H", monthly, policy=loose))
    strict_row = _c_section(analyze_historical_trends("H", monthly, policy=strict))

    assert not any("deviates" in finding for finding in loose_row.findings)
    assert any("deviates" in finding for finding in strict_row.findings)


def test_engine_ignores_a_poisoned_process_global():
    monthly = _series((25.0, 28.0, 30.0, 35.0))
    policy = trends_policy_from_snapshot(cr.resolve_policy(
        {"trend_finding_deviation": 10.0}, {}))

    saved = dict(trends._TRENDS_CONFIG)
    try:
        # Simulates a leftover writer from the pre-A3.5 architecture.
        trends._TRENDS_CONFIG.update({"trend_finding_deviation": 1000.0,
                                      "trend_finding_slope": 1000.0})
        row = _c_section(analyze_historical_trends("H", monthly, policy=policy))
    finally:
        trends._TRENDS_CONFIG.clear()
        trends._TRENDS_CONFIG.update(saved)

    assert any("deviates" in finding for finding in row.findings)


def test_persistence_gate_comes_from_the_settings_plane(db_session):
    monthly = _series((25.0, 28.0, 30.0, 35.0))
    _app(db_session, "trend_finding_consecutive", 2)
    short = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    _app(db_session, "trend_finding_consecutive", 4)
    long = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))

    assert short.settings.trend_finding_consecutive == 2
    assert long.settings.trend_finding_consecutive == 4

    assert any("consecutive" in finding
               for finding in _c_section(analyze_historical_trends(
                   "H", monthly, policy=short)).findings)
    assert not any("consecutive" in finding
                   for finding in _c_section(analyze_historical_trends(
                       "H", monthly, policy=long)).findings)


def test_trend_anomalies_use_the_policy_z_threshold():
    monthly = _series((25.0, 27.0, 29.0, 30.0))
    strict = trends_policy_from_snapshot(cr.resolve_policy(
        {"zscore_threshold": 1.0}, {}))
    loose = trends_policy_from_snapshot(cr.resolve_policy(
        {"zscore_threshold": 5.0}, {}))

    def flagged(policy):
        rows = detect_trend_anomalies("H", monthly, policy=policy)
        return next(row for row in rows if row.indicator_code == "5").is_outlier

    assert flagged(strict) is True
    assert flagged(loose) is False


def test_trends_policy_shares_the_authoritative_z_threshold(db_session):
    _app(db_session, "zscore_threshold", 3.0, "thresholds")
    policy = trends_policy_from_snapshot(cr.load_policy_snapshot(db_session))
    assert policy.zscore_threshold == 3.0
    assert severity_policy.load_analysis_config(db_session).zscore_threshold == 3.0


# ── legacy compatibility ───────────────────────────────────────────────────
def _equivalence_config():
    return {
        "trend_analysis_window": 4,
        "trend_min_history_months": 2,
        "trend_finding_slope": 8.0,
        "trend_finding_deviation": 10.0,
        "trend_finding_cv": 50.0,
        "trend_finding_r_squared": 0.9,
        "trend_r_squared": 0.9,
        "trend_finding_consecutive": 2,
    }


def test_legacy_config_and_policy_produce_identical_trend_output():
    monthly = _series((25.0, 28.0, 30.0, 35.0))
    for config in (None, _equivalence_config()):
        supplied = dict(config) if config is not None else None
        expected = analyze_historical_trends("H", monthly, config=supplied)
        actual = analyze_historical_trends(
            "H", monthly, policy=trends_policy_from_config(supplied))
        assert expected and actual == expected


def test_legacy_config_and_policy_produce_identical_anomaly_output():
    monthly = _series((25.0, 27.0, 29.0, 30.0))
    for config in (None, _equivalence_config()):
        supplied = dict(config) if config is not None else None
        expected = detect_trend_anomalies("H", monthly, config=supplied)
        actual = detect_trend_anomalies(
            "H", monthly, policy=trends_policy_from_config(supplied))
        assert expected and actual == expected


# ── concurrency ────────────────────────────────────────────────────────────
def test_concurrent_evaluations_keep_their_own_policy():
    strict = trends_policy_from_snapshot(cr.resolve_policy(
        {"trend_finding_deviation": 5.0}, {}))
    loose = trends_policy_from_snapshot(cr.resolve_policy(
        {"trend_finding_deviation": 1000.0}, {}))
    monthly = _series((25.0, 28.0, 30.0, 35.0))
    barrier = threading.Barrier(2)
    findings = {}

    def run(name, policy):
        barrier.wait(timeout=5)
        findings[name] = _c_section(
            analyze_historical_trends("H", monthly, policy=policy)).findings

    threads = [threading.Thread(target=run, args=("strict", strict)),
               threading.Thread(target=run, args=("loose", loose))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert any("deviates" in finding for finding in findings["strict"])
    assert not any("deviates" in finding for finding in findings["loose"])
    # Neither thread wrote the process-global table.
    assert "trend_finding_deviation" in trends._TRENDS_CONFIG
    assert trends._TRENDS_CONFIG["trend_finding_deviation"] == 20.0


# ── pipeline and batch consumers ───────────────────────────────────────────
def test_pipeline_reads_no_trend_configuration_and_writes_no_global(
        db_session, monkeypatch):
    import app.config_utils as config_utils

    hospital = db_session.query(Hospital).first()
    calls = []
    real_get = config_utils.get_config_dict

    def spy(db, category):
        calls.append(category)
        assert category not in ("trends", "rates"), category
        return real_get(db, category)

    monkeypatch.setattr(config_utils, "get_config_dict", spy)
    assert not hasattr(pipeline_mod, "set_trends_config")

    report = pipeline_mod.run_full_analysis(
        db_session, hospital.id, "2033-09", force=True)

    assert report is not None
    assert "trends" not in calls
    assert "rates" not in calls


def test_file_ops_batch_uses_one_policy_for_every_hospital(db_session, monkeypatch):
    from app.api import file_ops

    hospitals = db_session.query(Hospital).limit(2).all()
    assert len(hospitals) == 2
    month_map = {hospital.id: list(MONTHS[:2]) for hospital in hospitals}

    monkeypatch.setattr(file_ops, "get_enabled_values_for_hospital_month",
                        lambda db, hid, month: {"5": 25.0, "2": 200.0})
    seen = []

    def capture(name, monthly, additional_indicators=None, config=None,
                policy=None):
        seen.append(policy)
        return []

    monkeypatch.setattr(file_ops, "analyze_historical_trends", capture)

    file_ops._run_trend_analyses(db_session, hospitals, month_map)

    assert len(seen) == len(hospitals)
    assert seen[0] is not None
    assert all(policy is seen[0] for policy in seen)


# ── Explain parity ─────────────────────────────────────────────────────────
def _seed_explain_months(db):
    hospital = db.query(Hospital).filter(Hospital.name == "General Hospital").first()
    ids = {code: iid for iid, code in db.query(Indicator.id, Indicator.code).all()}
    for month, c_section in (("2026-03", 25.0), ("2026-04", 35.0)):
        for code, value in (("5", c_section), ("2", 200.0)):
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=ids[code],
                                  month=month, value=value))
    db.commit()
    return hospital


def _explain(client, hospital):
    response = client.get(
        f"/audit/explain?kind=trend_row&hospital_id={hospital.id}"
        "&month=2026-04&rate_name=C-section%20rate")
    assert response.status_code == 200, response.text
    return response.json()


def test_explain_uses_the_engine_default_not_the_old_25_percent(db_session, client):
    hospital = _seed_explain_months(db_session)
    payload = _explain(client, hospital)

    thresholds = payload["how"]["thresholds"]
    assert thresholds["trend_finding_deviation"] == 20.0
    assert thresholds["trend_finding_slope"] == TREND_ENGINE_DEFAULTS[
        "trend_finding_slope"]


def test_explain_uses_a_stored_gate_over_the_default(db_session, client):
    hospital = _seed_explain_months(db_session)
    _app(db_session, "trend_finding_deviation", 33.0)

    payload = _explain(client, hospital)

    assert payload["how"]["thresholds"]["trend_finding_deviation"] == 33.0


def _seed_anomaly(db):
    hospital = db.query(Hospital).filter(Hospital.name == "General Hospital").first()
    ids = {code: iid for iid, code in db.query(Indicator.id, Indicator.code).all()}
    for month, c_section in (("2026-03", 25.0), ("2026-04", 35.0)):
        for code, value in (("5", c_section), ("2", 200.0)):
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=ids[code],
                                  month=month, value=value))
    db.add(AnomalyResult(
        hospital_id=hospital.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=35.0, benchmark=25.0,
        z_score=4.0, is_outlier=True, peer_count=3, peer_std=2.0,
        peer_min=24.0, peer_max=26.0, peer_median=25.0, peers_detail=[]))
    db.commit()
    return hospital


def test_explain_anomaly_z_display_uses_the_snapshot(db_session, monkeypatch):
    hospital = _seed_anomaly(db_session)

    def _live_loader_must_not_run(_db):
        raise AssertionError("Explain read the live loader instead of the snapshot")

    monkeypatch.setattr(severity_policy, "load_analysis_config",
                        _live_loader_must_not_run)
    payload = explain_anomaly(db_session, hospital.id, "2026-04",
                              rate_name="C-section rate")

    assert payload["how"]["thresholds"]["zscore_threshold"] == 2.5


def test_explain_anomaly_z_display_prefers_a_stored_value(db_session):
    hospital = _seed_anomaly(db_session)
    _app(db_session, "zscore_threshold", 3.0, "thresholds")

    payload = explain_anomaly(db_session, hospital.id, "2026-04",
                              rate_name="C-section rate")

    assert payload["how"]["thresholds"]["zscore_threshold"] == 3.0


# ── architecture guard ─────────────────────────────────────────────────────
_LEGACY_MODULE = "app/engine/anomaly/trends.py"
_ANALYTICAL_FILES = {
    "app/engine/pipeline.py",
    "app/api/analysis.py",
    "app/api/file_ops.py",
    "app/engine/audit/explain.py",
}
_TREND_CATEGORIES = {"trends", "rates"}


def _trend_aliases(tree):
    """Local names that resolve to the legacy global or the setter."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in (
                "app.engine.anomaly.trends", "app.engine.anomaly"):
            for alias in node.names:
                if alias.name in ("_TRENDS_CONFIG", "set_trends_config"):
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("app.engine.anomaly.trends",
                                  "app.engine.anomaly"):
                    aliases[alias.asname or alias.name.split(".")[-1]] = "trends"
    return aliases


def _trend_guard_offenders(source: str, path: str):
    """Every prohibited reference to the legacy trend global/configuration.

    The only approved boundary is ``app/engine/anomaly/trends.py`` itself: its
    legacy helpers may read the table, and nobody outside may read, write or
    rebind it. Calls are checked by name, attribute and import alias; the DB
    category read is checked only for the four analytical consumers, because
    the documented legacy loaders elsewhere still read ``trends``/``rates``.
    """
    tree = ast.parse(source)
    aliases = _trend_aliases(tree)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            original = aliases.get(node.id, node.id)
            if original == "_TRENDS_CONFIG" and path != _LEGACY_MODULE:
                offenders.append(
                    (node.lineno, f"{original} reference (local {node.id})"))
        elif isinstance(node, ast.Attribute) and node.attr == "_TRENDS_CONFIG":
            if path != _LEGACY_MODULE:
                offenders.append((node.lineno, "attribute _TRENDS_CONFIG"))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called = aliases.get(func.id, func.id)
            elif isinstance(func, ast.Attribute):
                called = func.attr
            else:
                called = None
            if called == "set_trends_config" and path != _LEGACY_MODULE:
                offenders.append((node.lineno, "set_trends_config() call"))
            if (isinstance(func, ast.Name) and func.id == "getattr"
                    and len(node.args) >= 2):
                attr = node.args[1]
                if (isinstance(attr, ast.Constant)
                        and attr.value in ("_TRENDS_CONFIG", "set_trends_config")):
                    offenders.append((node.lineno, f"getattr(..., {attr.value!r})"))
            if path in _ANALYTICAL_FILES and called == "get_config_dict":
                for arg in node.args[1:]:
                    if (isinstance(arg, ast.Constant)
                            and arg.value in _TREND_CATEGORIES):
                        offenders.append((node.lineno,
                                          f"get_config_dict(..., {arg.value!r})"))
                    elif isinstance(arg, ast.Name) and arg.id == "TREND_CATEGORY":
                        offenders.append((node.lineno,
                                          "get_config_dict(..., TREND_CATEGORY)"))
    return sorted(offenders)


def test_no_analytical_trend_global_or_config_read_remains():
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        offenders += [f"{relative}:{line}:{why}" for line, why
                      in _trend_guard_offenders(path.read_text(encoding="utf-8"),
                                                relative)]
    assert offenders == []


@pytest.mark.parametrize("source, why", [
    ("x = trends._TRENDS_CONFIG", "attribute _TRENDS_CONFIG"),
    ("_TRENDS_CONFIG['a'] = 1", "_TRENDS_CONFIG reference"),
    ("trends._TRENDS_CONFIG['a'] = 1", "attribute _TRENDS_CONFIG"),
    ("set_trends_config({})", "set_trends_config() call"),
    ("trends.set_trends_config({})", "set_trends_config() call"),
    ("from app.engine.anomaly.trends import set_trends_config as stc\n"
     "stc({})", "set_trends_config() call"),
    ("from app.engine.anomaly.trends import _TRENDS_CONFIG as C\n"
     "C['a'] = 1", "_TRENDS_CONFIG reference"),
    ("getattr(trends, '_TRENDS_CONFIG')", "getattr"),
])
def test_trend_guard_detects_each_prohibited_pattern(source, why):
    offenders = _trend_guard_offenders(source, "app/engine/example.py")
    assert any(why in reason for _, reason in offenders), offenders


def test_trend_guard_allows_the_documented_legacy_boundary():
    source = "x = _TRENDS_CONFIG['a']\nset_trends_config({})"
    assert _trend_guard_offenders(source, _LEGACY_MODULE) == []


def test_trend_guard_detects_a_direct_trends_category_read():
    source = "get_config_dict(db, 'trends')"
    offenders = _trend_guard_offenders(source, "app/engine/pipeline.py")
    assert any("get_config_dict" in reason for _, reason in offenders), offenders
