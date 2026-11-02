"""D16-A2 — explicit ``PolicySnapshot`` integration proofs.

A1 proves the resolver reproduces every loader. These tests prove the
*integration* instead:

* one snapshot is resolved per analysis run and the alerts auto-scan receives
  that same object;
* no participating component re-reads System Control afterwards;
* the alerts scan keeps its two-stage history window (alerts plane, then the
  comparison policy that applies the trend window);
* the trend process-global stays a compatibility shim and can no longer
  contaminate a run it was not asked to configure;
* every value handed to the engines is identical to what the legacy loaders
  would have produced — same Z, same bands, same severity fingerprint.
"""
import inspect
import pathlib

import pytest

from app.engine import pipeline, quality_alerts
from app.engine import severity as severity_policy
from app.engine.anomaly import trends
from app.engine.comparison_policy import load_comparison_policy
from app.engine.config_resolver import (
    PolicyUnavailable,
    load_policy_snapshot,
    resolve_policy,
)
from app.engine.policy_view import (
    alerts_config_from_snapshot,
    analysis_config_from_snapshot,
    comparison_policy_from_snapshot,
)
from app.models import AppConfig, Hospital, Indicator, IndicatorValue, SystemSetting

MONTH = "2026-04"


# ── fixtures ────────────────────────────────────────────────────────────────
def _app(db, key: str, value: float, category: str) -> None:
    db.add(AppConfig(key=key, value=float(value), category=category, label=key))


def _setting(db, key: str, value) -> None:
    db.add(SystemSetting(key=key, value=str(value)))


def _seed_configured(db) -> None:
    """A configuration in which no value equals its documented default."""
    _app(db, "zscore_threshold", 3.0, "thresholds")
    _app(db, "alerts_history_window", 12, "alerts")
    _app(db, "alerts_min_history", 4, "alerts")
    _app(db, "alerts_min_peers", 3, "alerts")
    _app(db, "alerts_min_score", 0.6, "alerts")
    _app(db, "alerts_ml_enabled", 0, "alerts")
    _app(db, "alerts_ml_min_samples", 8, "alerts")
    _app(db, "trend_slope_stable", 1.0, "trends")
    _app(db, "trend_finding_consecutive", 4, "trends")
    _setting(db, "trend_analysis_window", 6)
    _setting(db, "trend_min_history_months", 3)
    db.commit()


def _seed_month(db, month: str = MONTH) -> Hospital:
    """One analysable hospital/month, so the run reaches the config block."""
    hospital = db.query(Hospital).first()
    for code, value in (("2", 320.0), ("3", 210.0)):
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital.id,
                              indicator_id=indicator.id,
                              month=month, value=value))
    db.commit()
    return hospital


# ── 1 + 2: one snapshot per run, no downstream reload ───────────────────────
def test_full_analysis_resolves_exactly_one_snapshot(db_session, monkeypatch):
    hospital = _seed_month(db_session)
    resolved = []
    real_load = pipeline.load_policy_snapshot

    def counting(db, **kwargs):
        snapshot = real_load(db, **kwargs)
        resolved.append(snapshot)
        return snapshot

    monkeypatch.setattr(pipeline, "load_policy_snapshot", counting)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)

    assert len(resolved) == 1, "the run resolved more than one configuration"


def test_run_does_not_reload_configuration_downstream(db_session, monkeypatch):
    hospital = _seed_month(db_session)

    def boom(*_args, **_kwargs):
        raise AssertionError(
            "a participating component re-read System Control configuration")

    monkeypatch.setattr(severity_policy, "load_analysis_config", boom)
    monkeypatch.setattr(quality_alerts, "_alerts_config", boom)
    monkeypatch.setattr(quality_alerts, "load_policy_snapshot", boom)

    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)

    assert result.get("hospital") == hospital.name


def test_alerts_auto_scan_receives_the_same_snapshot(db_session, monkeypatch):
    hospital = _seed_month(db_session)
    resolved = []
    seen = []
    real_load = pipeline.load_policy_snapshot
    real_scan = quality_alerts.scan

    def counting(db, **kwargs):
        snapshot = real_load(db, **kwargs)
        resolved.append(snapshot)
        return snapshot

    def capturing_scan(db, month, hospital_id=None, indicator_codes=None,
                       policy=None):
        seen.append(policy)
        return real_scan(db, month, hospital_id=hospital_id,
                         indicator_codes=indicator_codes, policy=policy)

    monkeypatch.setattr(pipeline, "load_policy_snapshot", counting)
    monkeypatch.setattr(quality_alerts, "scan", capturing_scan)

    pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)

    assert len(resolved) == 1
    if seen:  # the auto-scan is gated by config; when it runs it must share
        assert seen[0] is resolved[0]


# ── 3: interleaved runs cannot contaminate each other's trend settings ──────
def test_interleaved_runs_cannot_contaminate_trend_settings():
    wide = resolve_policy({}, {"trend_analysis_window": 12,
                               "trend_min_history_months": 2})
    narrow = resolve_policy({}, {"trend_analysis_window": 4,
                                 "trend_min_history_months": 2})
    save_settings = dict(trends._TRENDS_CONFIG)
    try:
        # A stale run's configuration left in the process global.
        trends.set_trends_config({"trend_analysis_window": 3,
                                  "trend_slope_stable": 99.0})
        for snapshot, expected_window in ((wide, 12), (narrow, 4), (wide, 12)):
            config = analysis_config_from_snapshot(snapshot).trend_engine_config()
            settings = trends._resolved_settings(config)
            bands = trends._resolved_bands(config)
            assert settings.window == expected_window
            assert bands["stable"] == 2.0, "the global leak reached the bands"
        # The global itself is untouched by any of those reads.
        assert trends._TRENDS_CONFIG["trend_analysis_window"] == 3
    finally:
        trends._TRENDS_CONFIG.clear()
        trends._TRENDS_CONFIG.update(save_settings)


# ── 4: the alerts two-stage window survives integration ─────────────────────
def test_alerts_keeps_its_two_stage_history_window():
    snapshot = resolve_policy({"alerts_history_window": 12},
                              {"trend_analysis_window": 6})

    # The snapshot keeps BOTH planes: they are never flattened into one value.
    assert snapshot.get("alerts.history_window") == 12
    assert snapshot.get("comparison.history_window") == 6
    # Stage 1 is the alerts plane; stage 2 applies the trend window.
    assert alerts_config_from_snapshot(snapshot)["history_window"] == 12
    assert comparison_policy_from_snapshot(snapshot).history.window == 6


def test_scan_consumes_the_supplied_snapshot_without_reloading(db_session,
                                                               monkeypatch):
    snapshot = load_policy_snapshot(db_session)

    def boom(*_args, **_kwargs):
        raise AssertionError("the scan re-read the configuration")

    monkeypatch.setattr(quality_alerts, "load_policy_snapshot", boom)
    monkeypatch.setattr(quality_alerts, "_alerts_config", boom)

    result = quality_alerts.scan(db_session, "2099-01", policy=snapshot)

    assert result.get("configuration_error") is not True
    assert "error" not in result or isinstance(result["error"], str)


# ── 5–7: parity with the loaders, and default behaviour ─────────────────────
def test_snapshot_views_match_the_existing_loaders(db_session):
    _seed_configured(db_session)
    snapshot = load_policy_snapshot(db_session)

    view = analysis_config_from_snapshot(snapshot)
    legacy = severity_policy.load_analysis_config(db_session)
    assert view.zscore_threshold == legacy.zscore_threshold == 3.0
    assert view.trend.window == legacy.trend.window == 6
    assert view.trend.min_history == legacy.trend.min_history == 3
    assert view.trend.trend_finding_consecutive == legacy.trend.trend_finding_consecutive
    assert dict(view.trend_bands) == dict(legacy.trend_bands)
    assert (view.trend_engine_config()["zscore_threshold"]
            == legacy.trend_engine_config()["zscore_threshold"])
    # Every severity-affecting value identical => identical stored fingerprint,
    # so persisted alerts are not re-labelled "stale" by the migration.
    assert (severity_policy.policy_fingerprint(view)
            == severity_policy.policy_fingerprint(legacy))

    cfg = alerts_config_from_snapshot(snapshot)
    legacy_cfg = quality_alerts._alerts_config(db_session)
    for key in ("min_score", "min_peers", "min_history", "history_window",
                "ml_enabled", "ml_min_samples", "z_threshold"):
        assert cfg[key] == legacy_cfg[key], key

    assert (comparison_policy_from_snapshot(snapshot).as_dict()
            == load_comparison_policy(db_session).as_dict())


def test_defaults_are_unchanged_when_nothing_is_configured(db_session):
    snapshot = load_policy_snapshot(db_session)
    view = analysis_config_from_snapshot(snapshot)

    assert view.zscore_threshold == 2.5
    assert view.trend.window == severity_policy.TREND_SETTING_SPECS[
        "trend_analysis_window"].default
    assert dict(view.trend_bands) == severity_policy.default_trend_bands()

    cfg = alerts_config_from_snapshot(snapshot)
    assert cfg["min_score"] == 0.5
    assert cfg["history_window"] == 12
    assert cfg["ml_enabled"] is True
    assert cfg["ml_min_samples"] == 12


# ── strictness per entry point ──────────────────────────────────────────────
def test_scan_reports_an_unreadable_configuration(db_session, monkeypatch):
    def boom(_db, **_kwargs):
        raise PolicyUnavailable("configuration store unavailable")

    monkeypatch.setattr(quality_alerts, "load_policy_snapshot", boom)

    result = quality_alerts.scan(db_session, MONTH)

    assert result["configuration_error"] is True
    assert "configuration store unavailable" in result["error"]


def test_analysis_reports_an_unreadable_configuration(db_session, monkeypatch):
    hospital = _seed_month(db_session)

    def boom(_db, **_kwargs):
        raise PolicyUnavailable("configuration store unavailable")

    monkeypatch.setattr(pipeline, "load_policy_snapshot", boom)

    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)

    assert result["data_quality_score"] == 0
    assert any("Analysis failed" in issue for issue in result["issues"])


# ── 4: the trend global is a labelled shim, not a silent second source ──────
def test_trend_global_setter_warns_but_still_works(caplog):
    save_settings = dict(trends._TRENDS_CONFIG)
    save_calls = trends._SET_TRENDS_CONFIG_CALLS
    try:
        trends._SET_TRENDS_CONFIG_CALLS = 0
        with caplog.at_level("WARNING", logger=trends.__name__):
            trends.set_trends_config({"trend_analysis_window": 9})
        assert "deprecated" in caplog.text
        assert trends._SET_TRENDS_CONFIG_CALLS == 1
        assert trends._TRENDS_CONFIG["trend_analysis_window"] == 9
    finally:
        trends._TRENDS_CONFIG.clear()
        trends._TRENDS_CONFIG.update(save_settings)
        trends._SET_TRENDS_CONFIG_CALLS = save_calls


# ── 11: nobody else was migrated, and the public API still fits ─────────────
def test_only_the_two_run_entry_points_consume_the_snapshot():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    consumers = {path.name for path in root.rglob("*.py")
                 if "policy_view" in path.read_text(encoding="utf-8")}
    assert consumers == {"pipeline.py", "quality_alerts.py"}

    # Display/explain paths stay on the legacy loaders in A2.
    analysis_api = (root / "api" / "analysis.py").read_text(encoding="utf-8")
    assert "load_analysis_config" in analysis_api
    assert callable(severity_policy.load_analysis_config)
    assert callable(quality_alerts._alerts_config)


def test_public_entry_points_stay_backwards_compatible():
    assert list(inspect.signature(pipeline.run_full_analysis).parameters)[:4] == [
        "session", "hospital_id", "month", "force"]
    assert inspect.signature(quality_alerts.scan).parameters["policy"].default is None
    assert inspect.signature(
        quality_alerts.scan_all_months).parameters["policy"].default is None
