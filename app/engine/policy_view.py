"""Typed views over one ``PolicySnapshot`` — D16-A2.

The resolver (``app.engine.config_resolver``) owns *resolution*: one immutable
snapshot per analysis run. This module owns the *shape* each consumer already
expects, and it is deliberately the only place in A2 that knows how a snapshot
maps onto those shapes.

Why a separate module
---------------------
The pipeline and the Quality Alerts scan already consume three different shapes
for the same policy: an :class:`~app.engine.severity.AnalysisConfig`, a plain
alerts config dict, and a
:class:`~app.engine.comparison_policy.ComparisonPolicy`. Keeping the adapters
here lets A2 hand the identical snapshot to both engines without editing either
engine's vocabulary — and lets a reviewer see, in one file, that no value is
re-derived, re-clamped or defaulted a second time.

Nothing here reads the database, and nothing here resolves a default: every
value is taken from the snapshot entry, which already recorded whether it came
from ``app_config``, ``system_settings``, a documented default, or an invalid
stored value that fell back. That is what makes "the run used one set of
settings" checkable after the fact.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from app.engine import severity as severity_policy
from app.engine.comparison_policy import (
    ComparisonPolicy,
    HistoryPolicy,
    PeerPolicy,
)
from app.engine.config_resolver import PolicySnapshot

#: Keys whose local ``trend`` setting names are the resolver's own key names.
_TREND_KEYS = tuple(severity_policy.TREND_SETTING_SPECS)
_BAND_KEYS = tuple(key for _name, key, _default in severity_policy.BAND_KEYS)


def _entry(snapshot: PolicySnapshot, key: str):
    try:
        return snapshot.entries[key]
    except KeyError as exc:  # a consumer asked for a plane A1 does not resolve
        raise KeyError(
            f"policy snapshot has no entry for {key!r} — the resolver does not "
            "resolve that key yet") from exc


def _value(snapshot: PolicySnapshot, key: str) -> Any:
    return _entry(snapshot, key).value


def _trend_source(snapshot: PolicySnapshot, key: str) -> str:
    """Snapshot provenance in the vocabulary ``TrendSettings`` already uses."""
    source = _entry(snapshot, key).source
    return {"database": "configured",
            "default": "default",
            "invalid": "invalid",
            "unavailable": "unavailable"}.get(source, source)


def analysis_config_from_snapshot(snapshot: PolicySnapshot):
    """Rebuild the ``AnalysisConfig`` the severity engine consumes.

    Every field is taken from the snapshot: the trend settings (with their
    provenance), the slope-band ladder (already made monotonic by the resolver),
    and the clamped ``zscore_threshold``. The result is value-identical to
    ``severity.load_analysis_config(db)`` over the same rows — the parity test
    asserts that — but it costs no second database read, so a run cannot see two
    versions of the same setting.
    """
    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    settings: Dict[str, Dict[str, Any]] = {}
    for spec in severity_policy.TREND_SETTING_SPECS.values():
        value = _value(snapshot, spec.key)
        source = _trend_source(snapshot, spec.key)
        values[spec.key] = value
        sources[spec.key] = source
        settings[spec.key] = {**spec.describe(), "value": value,
                              "source": source}

    errors = tuple(f"{error.key}: {error.reason}" for error in snapshot.errors
                   if error.key in _TREND_KEYS or error.key in _BAND_KEYS)
    trend = severity_policy.TrendSettings(**values, sources=sources,
                                          errors=errors)
    bands = {name: _value(snapshot, key)
             for name, key, _default in severity_policy.BAND_KEYS}
    raw_trends: Dict[str, Any] = dict(values)
    raw_trends.update({key: bands[name] for name, key, _default
                       in severity_policy.BAND_KEYS})

    z_entry = _entry(snapshot, "severity.zscore_threshold")
    return severity_policy.AnalysisConfig(
        zscore_threshold=z_entry.value,
        zscore_threshold_source=z_entry.source,
        trend=trend,
        trend_bands=bands,
        raw_trends=raw_trends,
        settings=settings,
        errors=errors,
    )


def alerts_config_from_snapshot(snapshot: PolicySnapshot) -> Dict[str, Any]:
    """The alerts plane exactly as ``_alerts_config`` shapes it.

    Deliberately the **pre-policy** view: ``history_window`` here is the alert
    window alone, without the trend window applied. The scan replaces it with
    the comparison policy below, so the two-stage behaviour is preserved rather
    than flattened, and the alerts plane keeps its own unclamped Z handling.
    """
    return {
        "min_score": _value(snapshot, "alerts.min_score"),
        "min_peers": _value(snapshot, "alerts.min_peers"),
        "min_history": _value(snapshot, "alerts.min_history"),
        "history_window": _value(snapshot, "alerts.history_window"),
        "ml_enabled": bool(_value(snapshot, "alerts.ml_enabled")),
        "ml_min_samples": int(_value(snapshot, "alerts.ml_min_samples")),
        "z_threshold": _value(snapshot, "alerts.z_threshold"),
    }


def comparison_policy_from_snapshot(snapshot: PolicySnapshot) -> ComparisonPolicy:
    """The shared temporal/peer policy, with the trend window already applied.

    Built from the comparison plane rather than re-resolved from the raw rows,
    so the scan cannot apply a different clamp than the one Diagnostics uses.
    The version string stays the module constant, so persisted evidence keeps
    naming the same policy version.
    """
    return ComparisonPolicy(
        history=HistoryPolicy(
            window=int(_value(snapshot, "comparison.history_window")),
            min_observations=int(_value(snapshot, "comparison.min_observations")),
        ),
        peer=PeerPolicy(min_peers=int(_value(snapshot, "comparison.min_peers"))),
    )


def snapshot_provenance(snapshot: PolicySnapshot) -> Mapping[str, Any]:
    """What a run should record about the configuration it used."""
    return {
        "digest": snapshot.digest,
        "resolver_version": snapshot.resolver_version,
        "component_versions": dict(snapshot.component_versions),
        "unavailable_keys": list(snapshot.unavailable_keys),
        "invalid_keys": list(snapshot.invalid_keys),
        "read_error": snapshot.read_error,
    }
