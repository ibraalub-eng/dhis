"""D16-A1 — parity tests for the central configuration resolver.

These tests prove the resolver is *additive*: for the same stored rows it
returns exactly what the existing loaders return, including the two distinct
Z-score clamp policies, the peer floors, the trend settings split across
``app_config`` and ``system_settings``, and the documented legacy defaults.

Nothing here migrates a consumer; one test asserts that too.
"""
import dataclasses
import inspect

import pytest

from app.config_utils import get_config_dict
from app.engine import config_resolver as cr
from app.engine import severity as sev
from app.engine.anomaly import trends
from app.engine.comparison_policy import load_comparison_policy
from app.engine.config_resolver import (
    PolicyUnavailable,
    PolicySnapshot,
    load_policy_snapshot,
    resolve_policy,
)
from app.engine.quality.scoring import resolve_scoring_config
from app.engine.quality_alerts import _alerts_config
from app.models import AppConfig, SystemSetting


# ── helpers ─────────────────────────────────────────────────────────────


def _app(db, key, value, category="thresholds"):
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        db.add(AppConfig(key=key, value=float(value), category=category,
                         label=key))
    else:
        row.value = float(value)
    db.commit()


def _ss(db, key, value):
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def _populated(db):
    _app(db, "zscore_threshold", 3.0, "thresholds")
    _app(db, "alerts_history_window", 9, "alerts")
    _app(db, "alerts_min_history", 4, "alerts")
    _app(db, "alerts_min_peers", 3, "alerts")
    _app(db, "alerts_min_score", 0.6, "alerts")
    _app(db, "quality_rule_compliance", 0.3, "quality")
    _app(db, "outlier_multiplier", 2.5, "quality")
    _app(db, "severity_critical", 4.0, "quality")
    _app(db, "trend_slope_stable", 1.5, "trends")
    _app(db, "confidence_high", 85.0, "thresholds")
    _ss(db, "trend_direction", "increasing")
    _ss(db, "trend_analysis_window", "6")
    _ss(db, "trend_severity_policy", "escalate")


# ── 1. Parity with every existing loader ────────────────────────────────


def test_resolver_values_match_existing_loader_outputs(db_session):
    _populated(db_session)
    snap = load_policy_snapshot(db_session)

    severity_config = sev.load_analysis_config(db_session)
    assert snap.values["severity.zscore_threshold"] == \
        severity_config.zscore_threshold

    for spec in sev.TREND_SETTING_SPECS.values():
        assert snap.values[spec.key] == getattr(severity_config.trend,
                                                spec.key), spec.key
    for name, key, _default in sev.BAND_KEYS:
        assert snap.values[key] == pytest.approx(
            severity_config.trend_bands[name]), key

    alerts = _alerts_config(db_session)
    assert snap.values["alerts.min_score"] == alerts["min_score"]
    assert snap.values["alerts.min_peers"] == alerts["min_peers"]
    assert snap.values["alerts.min_history"] == alerts["min_history"]
    assert snap.values["alerts.history_window"] == alerts["history_window"]
    assert snap.values["alerts.ml_enabled"] == alerts["ml_enabled"]
    assert snap.values["alerts.ml_min_samples"] == alerts["ml_min_samples"]
    assert snap.values["alerts.z_threshold"] == alerts["z_threshold"]

    policy = load_comparison_policy(db_session)
    assert snap.values["comparison.history_window"] == policy.history.window
    assert snap.values["comparison.min_observations"] == \
        policy.history.min_observations
    assert snap.values["comparison.min_peers"] == policy.peer.min_peers

    scoring = resolve_scoring_config(get_config_dict(db_session, "quality"))
    for key, value in scoring.items():
        assert snap.values[key] == value, key


def test_missing_configuration_reproduces_documented_defaults(db_session):
    """No rows at all: every plane must equal the loader's defaults."""
    snap = load_policy_snapshot(db_session)
    severity_config = sev.load_analysis_config(db_session)

    assert snap.values["severity.zscore_threshold"] == 2.5
    assert snap.values["severity.zscore_threshold"] == \
        severity_config.zscore_threshold
    assert snap.sources["severity.zscore_threshold"] == "default"

    assert snap.values["alerts.min_peers"] == 2
    assert snap.values["alerts.history_window"] == 12
    assert snap.values["comparison.history_window"] == 12
    assert snap.values["outlier_multiplier"] == 2.0
    assert snap.values["trend_analysis_window"] == 12
    assert snap.sources["outlier_multiplier"] == "default"

    alerts = _alerts_config(db_session)
    assert snap.values["alerts.z_threshold"] == alerts["z_threshold"]


# ── 2. The Z-score value and its two clamp policies ────────────────────


def test_configured_zscore_threshold_is_unchanged(db_session):
    snap = load_policy_snapshot(db_session)
    assert snap.values["severity.zscore_threshold"] == 2.5
    assert snap.values["alerts.z_threshold"] == 2.5
    assert snap.values["confidence.zscore_threshold"] == 2.5

    _app(db_session, "zscore_threshold", 3.0)
    snap = load_policy_snapshot(db_session)
    assert snap.values["severity.zscore_threshold"] == 3.0
    assert snap.values["alerts.z_threshold"] == 3.0
    assert snap.sources["severity.zscore_threshold"] == "database"


def test_both_zscore_clamp_policies_remain_distinct(db_session):
    """Severity clamps to [1, 5]; alerts only rejects a non-positive value."""
    _app(db_session, "zscore_threshold", 99)
    snap = load_policy_snapshot(db_session)
    assert snap.values["severity.zscore_threshold"] == 5.0
    assert snap.values["alerts.z_threshold"] == 99.0
    assert snap.entries["severity.zscore_threshold"].validation == "clamped"

    _app(db_session, "zscore_threshold", 0.5)
    snap = load_policy_snapshot(db_session)
    assert snap.values["severity.zscore_threshold"] == 1.0
    assert snap.values["alerts.z_threshold"] == 0.5

    _app(db_session, "zscore_threshold", 0)
    snap = load_policy_snapshot(db_session)
    assert snap.values["severity.zscore_threshold"] == 1.0
    assert snap.values["alerts.z_threshold"] == 2.5
    assert snap.entries["alerts.z_threshold"].source == "invalid"


# ── 3. Peer floors stay unchanged, frozen constant stays frozen ────────


def test_peer_minimums_are_unchanged(db_session):
    _app(db_session, "alerts_min_peers", 0, "alerts")
    snap = load_policy_snapshot(db_session)
    # The configurable floor is clamped to its documented minimum of 2.
    assert snap.values["alerts.min_peers"] == 2
    assert snap.values["comparison.min_peers"] == 2

    _app(db_session, "alerts_min_peers", 7, "alerts")
    snap = load_policy_snapshot(db_session)
    assert snap.values["comparison.min_peers"] == 7

    # The top-band floor is a frozen policy constant, not a knob.
    frozen = snap.frozen_constants["MIN_PEERS_FOR_TOP_BAND"]
    assert frozen.value == 4
    assert frozen.configurable is False
    assert "MIN_PEERS_FOR_TOP_BAND" not in snap.values


# ── 4. Trend settings resolve across both storage tables ───────────────


def test_trend_settings_resolve_across_both_storage_tables(db_session):
    _ss(db_session, "trend_analysis_window", "6")
    _ss(db_session, "trend_direction", "decreasing")
    _app(db_session, "trend_finding_consecutive", 5, "trends")
    _app(db_session, "trend_slope_stable", 1.5, "trends")
    _app(db_session, "alerts_history_window", 9, "alerts")

    snap = load_policy_snapshot(db_session)
    assert snap.values["trend_analysis_window"] == 6
    assert snap.values["trend_direction"] == "decreasing"
    assert snap.values["trend_finding_consecutive"] == 5
    assert snap.values["trend_slope_stable"] == 1.5

    # Storage plane is recorded per key, so the split never has to be guessed.
    assert snap.entries["trend_analysis_window"].storage == "system_settings"
    assert snap.entries["trend_finding_consecutive"].storage == "app_config"

    # The shorter of the two windows governs the shared comparison policy.
    assert snap.values["comparison.history_window"] == 6
    assert snap.values["alerts.history_window"] == 9


# ── 5. Invalid values are reported, never silently replaced ────────────


def test_invalid_values_are_explicitly_reported(db_session):
    _ss(db_session, "trend_direction", "banana")
    snap = load_policy_snapshot(db_session)

    entry = snap.entries["trend_direction"]
    assert entry.source == "invalid"
    assert entry.value == "any"
    assert entry.fallback_applied is True
    assert "trend_direction" in snap.invalid_keys
    assert any(error.key == "trend_direction" for error in snap.errors)

    # The existing loader reports the same fallback, so parity still holds.
    severity_config = sev.load_analysis_config(db_session)
    assert severity_config.trend.trend_direction == "any"
    assert severity_config.trend.sources["trend_direction"] == "invalid"


# ── 6. Snapshot immutability and independence ──────────────────────────


def test_snapshot_is_immutable(db_session):
    snap = load_policy_snapshot(db_session)
    assert isinstance(snap, PolicySnapshot)

    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.digest = "tampered"          # type: ignore[misc]
    with pytest.raises(TypeError):
        snap.entries["severity.zscore_threshold"] = None  # type: ignore[index]

    values = snap.values
    values["severity.zscore_threshold"] = 999
    assert snap.values["severity.zscore_threshold"] == 2.5


def test_two_snapshots_from_different_configs_do_not_overwrite_each_other(
        db_session):
    _app(db_session, "zscore_threshold", 2.5)
    first = load_policy_snapshot(db_session)

    _app(db_session, "zscore_threshold", 4.0)
    second = load_policy_snapshot(db_session)

    assert first.values["severity.zscore_threshold"] == 2.5
    assert second.values["severity.zscore_threshold"] == 4.0
    assert first.digest != second.digest
    assert first.entries is not second.entries


# ── 7. Deterministic fingerprints ──────────────────────────────────────


def test_fingerprint_is_deterministic(db_session):
    _populated(db_session)
    first = load_policy_snapshot(db_session)
    second = load_policy_snapshot(db_session)
    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert first.canonical_json() == second.canonical_json()


def test_different_configuration_produces_a_different_fingerprint(db_session):
    _app(db_session, "zscore_threshold", 2.5)
    baseline = load_policy_snapshot(db_session)
    _app(db_session, "zscore_threshold", 2.6)
    changed = load_policy_snapshot(db_session)
    assert baseline.digest != changed.digest


def test_fingerprint_ignores_input_key_ordering():
    app_config = {"zscore_threshold": 3.0, "alerts_min_peers": 3,
                  "outlier_multiplier": 2.5, "confidence_high": 85.0}
    system_settings = {"trend_direction": "increasing",
                       "trend_analysis_window": "6"}
    forward = resolve_policy(app_config, system_settings)
    reverse = resolve_policy(dict(reversed(list(app_config.items()))),
                             dict(reversed(list(system_settings.items()))))
    assert forward.digest == reverse.digest
    assert forward.values == reverse.values


# ── 8. Strictness and unavailable tracking ─────────────────────────────


def test_unreadable_configuration_raises_when_strict_and_is_labelled_otherwise(
        db_session):
    with pytest.raises(PolicyUnavailable):
        resolve_policy({}, {}, read_error="database unreachable")

    tolerant = resolve_policy({}, {}, strict=False,
                              read_error="database unreachable")
    assert tolerant.read_error == "database unreachable"
    assert tolerant.entries and all(
        entry.source == "unavailable" for entry in tolerant.entries.values())
    assert tolerant.unavailable_keys == tuple(sorted(tolerant.entries))
    # Documented defaults are still present, but marked as assumed.
    assert tolerant.values == resolve_policy({}, {}).values


# ── 9. Scope: exactly the approved consumers, nothing else ─────────────
#
# A1 asserted that NO consumer was migrated. D16-A2 approves exactly two — the
# analysis run and the Quality Alerts scan — so the guard now pins that exact
# set instead of asserting an empty one. It is not weaker: an unapproved module
# picking the resolver up still fails it, and every un-migrated display path
# must still reach the legacy loaders.


def test_migration_is_limited_to_the_two_run_entry_points():
    import app.engine.pipeline as pipeline
    import app.engine.quality_alerts as quality_alerts
    import app.engine.audit.explain as explain
    import app.api.analysis as analysis_api

    assert "config_resolver" in inspect.getsource(pipeline)
    assert "config_resolver" in inspect.getsource(quality_alerts)
    # Display / explain paths are NOT migrated in A2.
    assert "config_resolver" not in inspect.getsource(analysis_api)
    assert "config_resolver" not in inspect.getsource(explain)
    # The legacy loaders and the compatibility setter are still present.
    assert callable(trends.set_trends_config)
    assert hasattr(trends, "_TRENDS_CONFIG")
    assert callable(sev.load_analysis_config)
    assert callable(load_comparison_policy)
    assert cr.RESOLVER_VERSION == "1.0.0"
