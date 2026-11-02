"""Central configuration resolver — D16-A1.

One explicit, immutable snapshot of every *consumed* analysis policy value per
analysis run, resolved from the existing System Control storage
(``app_config`` + ``system_settings``).

Why this module exists
----------------------
System Control is authoritative, but today each consumer re-reads and re-derives
policy on its own: ``severity.load_analysis_config`` merges two tables,
``_alerts_config`` reads ``thresholds`` again with different clamping,
``load_comparison_policy`` re-resolves the window, ``resolve_scoring_config``
resolves the weights, and ``trends.set_trends_config`` mutates a process
global. Values that *look* identical can therefore differ per plane, and no
result can name the exact configuration behind it.

This module resolves all of them once, records where each value came from, and
digests the result. It is deliberately **additive**:

* it does not replace, wrap, or alter any existing loader;
* it switches no production consumer (A1 — migration is A2, separately
  approved);
* it does not normalise, unify, clamp, or reinterpret values across planes.

Behaviour parity, per plane
---------------------------
The resolver reproduces each existing reader exactly, including the
inconsistencies that a later phase may unify:

* ``severity`` — ``zscore_threshold`` clamped to [1.0, 5.0], rounded to 2dp,
  ``database`` / ``default`` / ``invalid`` sources (``load_analysis_config``).
* ``alerts`` — ``z_threshold`` only rejects a non-positive or unreadable value
  and is **not** upper-clamped (``_alerts_config``), so a stored ``0.5`` stays
  ``0.5`` here while severity reports ``1.0``.
* ``alerts.history_window`` — resolved **without** the trend window, exactly as
  ``_alerts_config`` does before the scan overrides it.
* ``comparison`` — ``min(alerts_history_window, trend_analysis_window)`` plus
  the clamped ``alerts_min_history`` / ``alerts_min_peers`` floors
  (``resolve_comparison_policy``).
* ``scoring`` — weights, outlier multiplier and severity weights through
  ``resolve_scoring_config``.
* ``confidence`` — the raw ``thresholds`` values as ``confidence.py`` reads
  them (no clamping, no rounding).
* ``frozen`` — the approved algorithm constants, recorded as metadata with
  ``configurable=False`` so a result can name the frozen policy that judged it.
  They are **not** returned in ``values`` and must never become operator
  settings.

Two documented deviations, both on paths where the current code would raise
rather than return a value: an unreadable ``confidence`` cutoff or a
non-numeric ``confidence`` Z is recorded as ``invalid`` with the documented
default instead of propagating an exception. Nothing else deviates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from app.engine import severity as severity_policy
from app.engine.comparison_policy import (
    COMPARISON_POLICY_VERSION,
    resolve_comparison_policy,
)
from app.engine.quality.scoring import (
    OUTLIER_MULTIPLIER_KEY,
    QUALITY_WEIGHT_KEYS,
    SEVERITY_WEIGHT_KEYS,
    resolve_scoring_config,
)

RESOLVER_VERSION = "1.0.0"

#: Planes that carry a policy but no version constant yet. Recorded explicitly
#: as ``unversioned`` rather than invented: D15 §5 identified exactly one
#: component version in the codebase (the comparison policy).
UNVERSIONED = "unversioned"

#: Storage plane of each resolved key, for the UI and for provenance readers.
STORAGE_APP_CONFIG = "app_config"
STORAGE_SYSTEM_SETTING = "system_settings"
STORAGE_CODE = "code"

#: Confidence cutoffs are read by ``confidence._compute_level`` with these
#: literals; they are the seeded ``thresholds`` defaults.
_CONFIDENCE_DEFAULTS = (("confidence_high", 80.0),
                        ("confidence_medium", 50.0),
                        ("confidence_low", 25.0))

_ALERTS_KEYS = ("alerts_min_score", "alerts_min_peers", "alerts_min_history",
                "alerts_history_window", "alerts_ml_enabled",
                "alerts_ml_min_samples")
_COMPARISON_KEYS = ("alerts_history_window", "alerts_min_history",
                    "alerts_min_peers")


class PolicyUnavailable(RuntimeError):
    """The saved configuration could not be read and the caller required it."""


@dataclass(frozen=True)
class PolicyEntry:
    """One resolved value with its provenance."""

    key: str
    value: Any
    source: str                 # database | default | invalid | unavailable
    component: str              # severity | alerts | comparison | scoring | ...
    configurable: bool = True
    fallback_applied: bool = False
    validation: str = "ok"      # ok | clamped | monotonic_floor | fallback
    storage: str = STORAGE_APP_CONFIG

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "component": self.component,
            "configurable": self.configurable,
            "fallback_applied": self.fallback_applied,
            "validation": self.validation,
            "storage": self.storage,
        }


@dataclass(frozen=True)
class PolicyError:
    """A value that could not be used, and what replaced it."""

    key: str
    raw: Any
    reason: str
    fallback: Any

    def as_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "raw": self.raw, "reason": self.reason,
                "fallback": self.fallback}


def _normalise(value: Any) -> Any:
    """Canonical JSON-safe form: numbers as floats, no tuples."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _normalise(value[k]) for k in sorted(value)}
    return value


@dataclass(frozen=True)
class PolicySnapshot:
    """Immutable resolved configuration for one analysis run.

    ``entries`` is a read-only mapping; ``values`` returns a plain dict copy so
    a caller cannot mutate the snapshot through it.
    """

    entries: Mapping[str, PolicyEntry]
    frozen_constants: Mapping[str, PolicyEntry]
    component_versions: Mapping[str, str]
    resolver_version: str
    digest: str
    errors: Tuple[PolicyError, ...] = ()
    read_error: Optional[str] = None

    # -- read-only views -------------------------------------------------
    @property
    def values(self) -> Dict[str, Any]:
        return {key: entry.value for key, entry in self.entries.items()}

    @property
    def sources(self) -> Dict[str, str]:
        return {key: entry.source for key, entry in self.entries.items()}

    @property
    def unavailable_keys(self) -> Tuple[str, ...]:
        return tuple(sorted(key for key, entry in self.entries.items()
                            if entry.source == "unavailable"))

    @property
    def invalid_keys(self) -> Tuple[str, ...]:
        return tuple(sorted(key for key, entry in self.entries.items()
                            if entry.source == "invalid"))

    @property
    def components(self) -> Dict[str, Any]:
        """The per-plane shaped view A2 will hand to each consumer."""
        planes: Dict[str, Dict[str, Any]] = {}
        for key, entry in self.entries.items():
            planes.setdefault(entry.component, {})[key] = entry.value
        return planes

    def get(self, key: str, default: Any = None) -> Any:
        entry = self.entries.get(key)
        return default if entry is None else entry.value

    def canonical_json(self) -> str:
        payload = {
            "resolver": self.resolver_version,
            "components": dict(self.component_versions),
            "values": _normalise(self.values),
            "frozen": _normalise({key: entry.value
                                  for key, entry in self.frozen_constants.items()}),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "resolver_version": self.resolver_version,
            "digest": self.digest,
            "component_versions": dict(self.component_versions),
            "values": self.values,
            "entries": {key: entry.as_dict()
                        for key, entry in self.entries.items()},
            "frozen_constants": {key: entry.as_dict()
                                 for key, entry in self.frozen_constants.items()},
            "errors": [error.as_dict() for error in self.errors],
            "unavailable_keys": list(self.unavailable_keys),
            "read_error": self.read_error,
        }


class _Collector:
    """Accumulates entries + errors while resolving, then freezes them."""

    def __init__(self) -> None:
        self.entries: Dict[str, PolicyEntry] = {}
        self.errors: list = []

    def add(self, key: str, value: Any, source: str, component: str, *,
            storage: str = STORAGE_APP_CONFIG, raw: Any = None,
            reason: str = "", validation: str = "ok") -> None:
        fallback = source in ("default", "invalid", "unavailable")
        self.entries[key] = PolicyEntry(
            key=key, value=value, source=source, component=component,
            configurable=True, fallback_applied=fallback,
            validation=validation, storage=storage,
        )
        if source == "invalid":
            self.errors.append(PolicyError(key=key, raw=raw,
                                           reason=reason or "invalid value",
                                           fallback=value))

    def missing(self, key: str, value: Any, component: str, *,
                storage: str = STORAGE_APP_CONFIG) -> None:
        self.add(key, value, "default", component, storage=storage,
                 validation="fallback")


def _float_or(raw: Any, default: float) -> Tuple[float, str]:
    """``(value, 'database'|'invalid'|'default')`` for an optional number."""
    if raw is None:
        return default, "default"
    try:
        return float(raw), "database"
    except (TypeError, ValueError):
        return default, "invalid"


def _resolve_severity(app_config: Mapping[str, Any],
                      collector: _Collector) -> Dict[str, Any]:
    """Reproduce ``severity.load_analysis_config``'s Z-score block exactly."""
    raw = app_config.get(severity_policy.ZSCORE_KEY)
    if raw is None:
        z_value = severity_policy.DEFAULT_ZSCORE_THRESHOLD
        collector.missing("severity.zscore_threshold", z_value, "severity",
                          storage=STORAGE_APP_CONFIG)
    else:
        try:
            stored = float(raw)
        except (TypeError, ValueError):
            z_value = severity_policy.DEFAULT_ZSCORE_THRESHOLD
            collector.add("severity.zscore_threshold", z_value, "invalid",
                          "severity", raw=raw,
                          reason=f"expected a number; using default "
                                 f"{severity_policy.DEFAULT_ZSCORE_THRESHOLD}")
        else:
            clamped = max(severity_policy.ZSCORE_MIN,
                          min(severity_policy.ZSCORE_MAX, stored))
            z_value = round(clamped, 2)
            collector.add("severity.zscore_threshold", z_value, "database",
                          "severity", raw=raw,
                          validation=("clamped" if clamped != stored else "ok"))
    return {"zscore_threshold": z_value}


def _trend_raw(app_config: Mapping[str, Any],
               system_settings: Mapping[str, str]) -> Dict[str, Any]:
    """Exactly ``load_analysis_config``'s merge of the two storage tables.

    ``trends`` AppConfig rows first, then every genuinely new control from
    ``system_settings`` (an empty value never overrides), so
    ``trend_analysis_window`` and its enum siblings resolve from the text table
    while ``trend_finding_consecutive`` stays in ``app_config``.
    """
    raw: Dict[str, Any] = {}
    for key in severity_policy.TREND_SETTING_SPECS:
        if key in app_config and app_config[key] is not None:
            raw[key] = app_config[key]
    for key in severity_policy.NEW_TREND_KEYS:
        value = system_settings.get(key)
        if value not in (None, ""):
            raw[key] = value
    return raw


def _resolve_trend(app_config: Mapping[str, Any],
                   system_settings: Mapping[str, str],
                   collector: _Collector) -> Dict[str, Any]:
    """Trend controls + slope bands, in the shape the consumers already use."""
    raw = _trend_raw(app_config, system_settings)
    trend = severity_policy.resolve_trend_settings(raw)

    for spec in severity_policy.TREND_SETTING_SPECS.values():
        source = trend.sources.get(spec.key, "default")
        mapped = {"configured": "database", "default": "default",
                  "invalid": "invalid"}.get(source, source)
        if mapped == "database":
            storage = (STORAGE_SYSTEM_SETTING
                       if spec.key in severity_policy.NEW_TREND_KEYS
                       else STORAGE_APP_CONFIG)
            collector.add(spec.key, getattr(trend, spec.key), "database",
                          "trend", storage=storage, raw=raw.get(spec.key))
        elif mapped == "invalid":
            storage = (STORAGE_SYSTEM_SETTING
                       if spec.key in severity_policy.NEW_TREND_KEYS
                       else STORAGE_APP_CONFIG)
            collector.add(spec.key, getattr(trend, spec.key), "invalid",
                          "trend", storage=storage, raw=raw.get(spec.key),
                          reason="stored value rejected by its validation spec")
        else:
            storage = (STORAGE_SYSTEM_SETTING
                       if spec.key in severity_policy.NEW_TREND_KEYS
                       else STORAGE_APP_CONFIG)
            collector.missing(spec.key, getattr(trend, spec.key), "trend",
                              storage=storage)

    # Slope bands: same read, same monotonic ladder as load_analysis_config.
    bands = dict(severity_policy.default_trend_bands())
    band_validation: Dict[str, str] = {}
    for name, key, default in severity_policy.BAND_KEYS:
        band_raw = app_config.get(key)
        if band_raw is None:
            collector.missing(key, bands[name], "trend")
            band_validation[name] = "ok"
            continue
        try:
            bands[name] = max(0.0, float(band_raw))
        except (TypeError, ValueError):
            collector.add(key, bands[name], "invalid", "trend", raw=band_raw,
                          reason=f"expected a number; using default {default}")
            band_validation[name] = "ok"
            continue
        collector.add(key, bands[name], "database", "trend", raw=band_raw)
        band_validation[name] = "ok"

    order = ("stable", "low", "moderate", "high")
    for previous, current in zip(order, order[1:], strict=False):
        if bands[current] < bands[previous]:
            bands[current] = bands[previous]
            band_validation[current] = "monotonic_floor"
            key = dict((name, key) for name, key, _default
                       in severity_policy.BAND_KEYS)[current]
            collector.add(key, bands[current], "database", "trend",
                          raw=app_config.get(key),
                          validation="monotonic_floor")

    resolved = {spec.key: getattr(trend, spec.key)
                for spec in severity_policy.TREND_SETTING_SPECS.values()}
    resolved.update({key: bands[name] for name, key, _default
                     in severity_policy.BAND_KEYS})
    return resolved


def _alerts_slice(app_config: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: app_config[key] for key in _ALERTS_KEYS if key in app_config}


def _resolve_alerts(app_config: Mapping[str, Any],
                    collector: _Collector) -> Dict[str, Any]:
    """Reproduce ``quality_alerts._alerts_config``, including its Z handling."""
    cfg = _alerts_slice(app_config)

    def _f(key: str, default: float, name: Optional[str] = None) -> float:
        name = name or key
        raw = cfg.get(key)
        if raw is None:
            collector.missing(name, default, "alerts")
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            collector.add(name, default, "invalid", "alerts", raw=raw,
                          reason=f"expected a number; using default {default}")
            return default
        collector.add(name, value, "database", "alerts", raw=raw)
        return value

    min_score = _f("alerts_min_score", 0.5, "alerts.min_score")
    # The scan's own pre-policy resolve: alert window only, no trend window.
    pre_policy = resolve_comparison_policy(cfg)
    min_peers = pre_policy.peer.min_peers
    min_history = pre_policy.history.min_observations
    history_window = pre_policy.history.window
    collector.add("alerts.min_peers", min_peers,
                  "database" if cfg.get("alerts_min_peers") is not None else "default",
                  "alerts", raw=cfg.get("alerts_min_peers"))
    collector.add("alerts.min_history", min_history,
                  "database" if cfg.get("alerts_min_history") is not None else "default",
                  "alerts", raw=cfg.get("alerts_min_history"))
    collector.add("alerts.history_window", history_window,
                  "database" if cfg.get("alerts_history_window") is not None else "default",
                  "alerts", raw=cfg.get("alerts_history_window"))

    ml_raw = cfg.get("alerts_ml_enabled")
    if ml_raw is None:
        ml_enabled = True
        collector.missing("alerts.ml_enabled", ml_enabled, "alerts")
    else:
        try:
            ml_enabled = int(float(ml_raw)) == 1
        except (TypeError, ValueError):
            ml_enabled = True
            collector.add("alerts.ml_enabled", ml_enabled, "invalid", "alerts",
                          raw=ml_raw, reason="expected 0/1; using default 1")
        else:
            collector.add("alerts.ml_enabled", ml_enabled, "database",
                          "alerts", raw=ml_raw)

    ml_min_raw = cfg.get("alerts_ml_min_samples")
    if ml_min_raw is None:
        ml_min_samples = max(4, 12)
        collector.missing("alerts.ml_min_samples", ml_min_samples, "alerts")
    else:
        try:
            ml_min_samples = max(4, int(float(ml_min_raw)))
        except (TypeError, ValueError):
            ml_min_samples = max(4, 12)
            collector.add("alerts.ml_min_samples", ml_min_samples, "invalid",
                          "alerts", raw=ml_min_raw,
                          reason="expected a number; using default 12")
        else:
            collector.add("alerts.ml_min_samples", ml_min_samples, "database",
                          "alerts", raw=ml_min_raw)

    # The alerts plane deliberately does NOT upper-clamp the threshold: a stored
    # 0.5 stays 0.5 here while severity reports 1.0. Only unreadable or
    # non-positive values fall back, exactly as _alerts_config does.
    z_raw = app_config.get(severity_policy.ZSCORE_KEY)
    default_z = severity_policy.DEFAULT_ZSCORE_THRESHOLD
    if z_raw is None:
        z_value, z_source = default_z, "default"
        collector.missing("alerts.z_threshold", z_value, "alerts")
    else:
        try:
            z_value = float(z_raw)
        except (TypeError, ValueError):
            z_value, z_source = default_z, "invalid"
            collector.add("alerts.z_threshold", z_value, "invalid", "alerts",
                          raw=z_raw,
                          reason=f"expected a number; using default {default_z}")
        else:
            z_source = "database"
            if z_value <= 0:
                z_value = default_z
                z_source = "invalid"
                collector.add("alerts.z_threshold", z_value, "invalid",
                              "alerts", raw=z_raw,
                              reason="non-positive threshold; using default "
                                     f"{default_z}")
            else:
                collector.add("alerts.z_threshold", z_value, "database",
                              "alerts", raw=z_raw)

    return {"min_score": min_score, "min_peers": min_peers,
            "min_history": min_history, "history_window": history_window,
            "ml_enabled": ml_enabled, "ml_min_samples": ml_min_samples,
            "z_threshold": z_value}


def _resolve_comparison(app_config: Mapping[str, Any],
                        trend_values: Mapping[str, Any],
                        collector: _Collector) -> Dict[str, Any]:
    """The shared policy both engines use, with the trend window applied."""
    cfg = {key: app_config[key] for key in _COMPARISON_KEYS if key in app_config}
    policy = resolve_comparison_policy(cfg, trend_values.get("trend_analysis_window"))
    collector.add("comparison.history_window", policy.history.window,
                  "database" if app_config else "default", "comparison",
                  raw=cfg.get("alerts_history_window"))
    collector.add("comparison.min_observations", policy.history.min_observations,
                  "database" if cfg.get("alerts_min_history") is not None
                  else "default", "comparison", raw=cfg.get("alerts_min_history"))
    collector.add("comparison.min_peers", policy.peer.min_peers,
                  "database" if cfg.get("alerts_min_peers") is not None
                  else "default", "comparison", raw=cfg.get("alerts_min_peers"))
    return {"history_window": policy.history.window,
            "min_observations": policy.history.min_observations,
            "min_peers": policy.peer.min_peers}


def _resolve_scoring(app_config: Mapping[str, Any],
                     collector: _Collector) -> Dict[str, Any]:
    """``resolve_scoring_config`` — the shared weight/multiplier resolver."""
    keys = (*QUALITY_WEIGHT_KEYS.values(), OUTLIER_MULTIPLIER_KEY,
            *SEVERITY_WEIGHT_KEYS.values())
    cfg = {key: app_config[key] for key in keys if key in app_config}
    resolved = resolve_scoring_config(cfg)
    for key in keys:
        raw = app_config.get(key)
        if raw is None:
            collector.missing(key, resolved[key], "scoring")
        else:
            try:
                float(raw)
            except (TypeError, ValueError):
                collector.add(key, resolved[key], "invalid", "scoring",
                              raw=raw,
                              reason="expected a number; using documented default")
            else:
                collector.add(key, resolved[key], "database", "scoring", raw=raw)
    return resolved


def _resolve_confidence(app_config: Mapping[str, Any],
                        collector: _Collector) -> Dict[str, Any]:
    """The raw ``thresholds`` values ``confidence.py`` reads, unclamped."""
    resolved: Dict[str, Any] = {}
    for key, default in _CONFIDENCE_DEFAULTS:
        raw = app_config.get(key)
        if raw is None:
            resolved[key] = default
            collector.missing(f"confidence.{key.replace('confidence_', '')}",
                              default, "confidence")
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
            collector.add(f"confidence.{key.replace('confidence_', '')}", value,
                          "invalid", "confidence", raw=raw,
                          reason=f"expected a number; using default {default}")
        else:
            collector.add(f"confidence.{key.replace('confidence_', '')}", value,
                          "database", "confidence", raw=raw)
        resolved[key] = value

    z_raw = app_config.get(severity_policy.ZSCORE_KEY)
    default_z = severity_policy.DEFAULT_ZSCORE_THRESHOLD
    if z_raw is None:
        resolved["zscore_threshold"] = default_z
        collector.missing("confidence.zscore_threshold", default_z, "confidence")
    else:
        try:
            resolved["zscore_threshold"] = float(z_raw)
        except (TypeError, ValueError):
            resolved["zscore_threshold"] = default_z
            collector.add("confidence.zscore_threshold", default_z, "invalid",
                          "confidence", raw=z_raw,
                          reason=f"expected a number; using default {default_z}")
        else:
            collector.add("confidence.zscore_threshold",
                          resolved["zscore_threshold"], "database",
                          "confidence", raw=z_raw)
    return resolved


def frozen_constants() -> Dict[str, PolicyEntry]:
    """Approved algorithm constants — metadata only, never operator settings.

    Read from the modules that own them (no restated literals), and marked
    ``configurable=False`` so a result can record which frozen policy judged it
    without offering an operator a control.
    """
    from app.engine.anomaly import layered

    constants = (
        ("MIN_PEERS_FOR_TOP_BAND", layered.MIN_PEERS_FOR_TOP_BAND, "layered",
         "Top-band peer floor; raising/lowering it changes an approved policy"),
        ("ZERO_SPREAD_LEVEL_CAP", layered.ZERO_SPREAD_LEVEL_CAP, "layered",
         "Approved cap: no dispersion cannot support a top band"),
        ("THIN_PEER_LEVEL_CAP", layered.THIN_PEER_LEVEL_CAP, "layered",
         "Approved cap: too few peers cannot support a top band"),
        ("PCT_CHANGE_CAP_POLICY", layered.PCT_CHANGE_CAP_POLICY, "layered",
         "Approved %-change cap policy text"),
        ("CV_MAX", layered.CV_MAX, "method_selection",
         "Method selection: auto -> pct_change below this CV"),
        ("MIN_IQR_POINTS", layered.MIN_IQR_POINTS, "method_selection",
         "Method selection: minimum points for IQR"),
        ("MIN_TREND_POINTS", layered.MIN_TREND_POINTS, "method_selection",
         "Method selection: minimum points for Theil-Sen"),
        ("RARE_EVENT_MEAN_MAX", layered.RARE_EVENT_MEAN_MAX, "method_selection",
         "Method selection: rare-event series never use plain z"),
        ("MAD_SCALE", layered.MAD_SCALE, "method_selection",
         "Normal-consistent MAD -> sigma scale (1.4826)"),
        ("DEFAULT_MINIMUM_HISTORY", layered.DEFAULT_MINIMUM_HISTORY,
         "method_selection",
         "Indicator.minimum_history_period default when no per-indicator value"),
        ("PEER_Z_THRESHOLD_DEFAULT", layered.PEER_Z_THRESHOLD_DEFAULT,
         "layered",
         "Last-resort z fallback for a row with no stored threshold"),
    )
    return {
        name: PolicyEntry(key=name, value=value, source="code",
                          component=component, configurable=False,
                          fallback_applied=False, validation="frozen",
                          storage=STORAGE_CODE)
        for name, value, component, _reason in constants
    }


def component_versions() -> Dict[str, str]:
    """Version metadata for every plane in the snapshot.

    Only the comparison policy has a version constant today; the rest are
    recorded as ``unversioned`` rather than given invented semver (D15 §5).
    """
    return {
        "comparison": COMPARISON_POLICY_VERSION,
        "severity": UNVERSIONED,
        "alerts": UNVERSIONED,
        "trend": UNVERSIONED,
        "scoring": UNVERSIONED,
        "confidence": UNVERSIONED,
        "layered": UNVERSIONED,
        "config": RESOLVER_VERSION,
    }


def _digest(snapshot: PolicySnapshot) -> str:
    return hashlib.sha256(snapshot.canonical_json().encode("utf-8")).hexdigest()


def _build(app_config: Mapping[str, Any],
           system_settings: Mapping[str, str]) -> PolicySnapshot:
    collector = _Collector()
    _resolve_severity(app_config, collector)
    trend_values = _resolve_trend(app_config, system_settings, collector)
    _resolve_alerts(app_config, collector)
    _resolve_comparison(app_config, trend_values, collector)
    _resolve_scoring(app_config, collector)
    _resolve_confidence(app_config, collector)

    entries = MappingProxyType(dict(collector.entries))
    frozen = MappingProxyType(frozen_constants())
    snapshot = PolicySnapshot(
        entries=entries,
        frozen_constants=frozen,
        component_versions=MappingProxyType(component_versions()),
        resolver_version=RESOLVER_VERSION,
        digest="",
        errors=tuple(collector.errors),
    )
    # Digest is computed over the canonical form (values + versions + frozen),
    # then attached via replace so the dataclass stays frozen.
    return replace(snapshot, digest=_digest(snapshot))


def resolve_policy(app_config: Optional[Mapping[str, Any]] = None,
                   system_settings: Optional[Mapping[str, str]] = None,
                   *, strict: bool = True,
                   read_error: Optional[str] = None) -> PolicySnapshot:
    """Resolve one immutable snapshot from raw System Control rows.

    Pure: no database, no I/O, no module state. ``app_config`` is the flat
    ``{key: value}`` mapping of ``app_config`` rows (keys are globally unique,
    so a flat map is equivalent to the per-category reads the old loaders do);
    ``system_settings`` is ``{key: text}``.

    ``strict`` only governs an unreadable store: with ``strict=True`` a
    ``read_error`` raises :class:`PolicyUnavailable` (run paths); with
    ``strict=False`` the snapshot is returned with every key marked
    ``unavailable`` and its documented default, so a display path can render
    and *say* the configuration was unavailable instead of inventing values.
    Invalid individual values never raise — they are reported per key, exactly
    like the loaders they mirror.
    """
    if read_error is not None and strict:
        raise PolicyUnavailable(read_error)

    snapshot = _build(app_config or {}, system_settings or {})
    if read_error is None:
        return snapshot

    unavailable = {
        key: replace(entry, source="unavailable", fallback_applied=True,
                     validation="fallback")
        for key, entry in snapshot.entries.items()
    }
    downgraded = replace(
        snapshot,
        entries=MappingProxyType(unavailable),
        read_error=read_error,
        errors=snapshot.errors,
    )
    return replace(downgraded, digest=_digest(downgraded))


def load_policy_snapshot(db, *, strict: bool = True) -> PolicySnapshot:
    """Database-backed snapshot: one read of each System Control store.

    This is the only function in the module that touches the session. It reads
    the two stores once and delegates all resolution to :func:`resolve_policy`,
    so the values a caller sees are identical to the pure path over the same
    rows. No consumer is switched to it in A1.
    """
    from app.models import AppConfig, SystemSetting

    try:
        app_rows = db.query(AppConfig).all()
        app_config = {row.key: row.value for row in app_rows}
        setting_rows = db.query(SystemSetting).all()
        system_settings = {row.key: row.value for row in setting_rows}
    except Exception as exc:  # noqa: BLE001 - re-raised or recorded as required
        message = ("Analysis configuration could not be read from the "
                   f"database: {exc}")
        if strict:
            raise PolicyUnavailable(message) from exc
        return resolve_policy({}, {}, strict=False, read_error=message)

    return resolve_policy(app_config, system_settings, strict=strict)
