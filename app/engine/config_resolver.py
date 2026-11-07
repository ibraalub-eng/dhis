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
  them (no clamping, no rounding), plus the five **effective** Confidence
  signal weights resolved from the single ``confidence_weights`` row through
  ``confidence_policy.ConfidencePolicy`` (P3.3.2).
* ``frozen`` — the approved algorithm constants, recorded as metadata with
  ``configurable=False`` so a result can name the frozen policy that judged it.
  They are **not** returned in ``values`` and must never become operator
  settings.

Policy identity vs provenance
-----------------------------
``digest`` is a *policy identity* digest: it answers "would this run resolve a
different analytical policy?". Two consequences follow, and both are enforced
in code:

* only analytically relevant content participates — ``rules`` contributes a
  content hash of the rule set plus its size and field list, never each rule's
  body and never a write timestamp;
* entries that record provenance (``PROVENANCE_METADATA_KEYS``, currently the
  newest ``rules.updated_at``) stay on the snapshot for display but are
  excluded from ``canonical_json()``, so touching a row without changing a
  value leaves the digest intact.

``rules.hash`` is byte-stable across processes and repeated resolutions: rows
are ordered by the UNIQUE ``code``, values are normalised, ``params`` JSON is
canonicalised, and the storage primary key and ``*_at`` columns are excluded.

The Confidence weights follow the same split. The five
``confidence.weight.*`` entries hold the **effective** (normalized) values the
engine would consume, so they participate in ``digest``: a weight change moves
policy identity. Everything that describes *how* the values were stored stays
out of it — the row ids, the duplicate/conflict marker, the row's
``updated_at`` column, the submitted-only view and the two-decimal display
format. Two configurations with identical effective weights therefore share a
digest whether those weights came from a row or from the defaults, and whether
the submitted numbers were scaled or not.

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
from app.engine.confidence_policy import (
    CONFIDENCE_POLICY_VERSION,
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MEDIUM,
    DEFAULT_WEIGHTS,
    DEFAULT_ZSCORE_THRESHOLD,
    WEIGHT_KEYS,
    ConfidencePolicy,
)
from app.engine.quality.scoring import (
    OUTLIER_MULTIPLIER_KEY,
    QUALITY_WEIGHT_KEYS,
    SEVERITY_WEIGHT_KEYS,
    resolve_scoring_config,
)

RESOLVER_VERSION = "1.4.0"   # P3.3.2: effective Confidence weights join identity

#: Planes that carry a policy but no version constant yet. Recorded explicitly
#: as ``unversioned`` rather than invented: D15 §5 identified exactly one
#: component version in the codebase (the comparison policy).
UNVERSIONED = "unversioned"

#: Storage plane of each resolved key, for the UI and for provenance readers.
STORAGE_APP_CONFIG = "app_config"
STORAGE_SYSTEM_SETTING = "system_settings"
STORAGE_CONFIDENCE_WEIGHTS = "confidence_weights"
STORAGE_CODE = "code"

#: Confidence cutoffs are read by ``confidence._compute_level`` with these
#: literals; they are the seeded ``thresholds`` defaults.
_CONFIDENCE_DEFAULTS = (("confidence_high", DEFAULT_HIGH),
                        ("confidence_medium", DEFAULT_MEDIUM),
                        ("confidence_low", DEFAULT_LOW))

#: The row-level error key used for both an unusable weights row and duplicate
#: rows. The five individual ``confidence.weight.*`` entries carry the fallback
#: or conflict validation metadata; this key explains why.
CONFIDENCE_WEIGHTS_ERROR_KEY = "confidence.weights"

#: Entry-key prefix of the five effective Confidence signal weights.
CONFIDENCE_WEIGHT_PREFIX = "confidence.weight."

#: Row-level error key used when a stored cutoff or Z cannot be represented by
#: ``ConfidencePolicy`` at all. The cutoffs keep their own resolved entries;
#: this key explains why no policy object accompanies them.
CONFIDENCE_POLICY_ERROR_KEY = "confidence.policy"

_AUTO_SCAN_OFF = frozenset({"0", "0.0", "false", "False", "off"})

#: Snapshot metadata that records *provenance* rather than analytical identity.
#:
#: Such an entry says when something was written, not what policy was resolved,
#: so it stays visible on ``metadata`` / ``as_dict()`` but is excluded from
#: ``canonical_json()`` and therefore from ``digest``. Without this split a
#: timestamp-only rule touch would rewrite the digest of an unchanged policy.
PROVENANCE_METADATA_KEYS = frozenset({"rules.updated_at"})

_ALERTS_KEYS = ("alerts_min_score", "alerts_min_peers", "alerts_min_history",
                "alerts_history_window", "alerts_ml_enabled",
                "alerts_ml_min_samples", "alerts_auto_scan")
_COMPARISON_KEYS = ("alerts_history_window", "alerts_min_history",
                    "alerts_min_peers")

#: Analysis gates (A3.3). A gate is not a policy scalar: it decides *whether* a
#: Step runs, so it belongs in the same immutable snapshot as the thresholds it
#: guards. ``auto_disable_null_indicators`` is the first one migrated.
FLAG_AUTO_DISABLE_KEY = "auto_disable_null_indicators"
FLAG_AUTO_DISABLE_NULL = "flags.auto_disable_null"


def parse_auto_disable_null(raw: Any) -> bool:
    """The single parser for ``auto_disable_null_indicators`` (approved).

    Only the literal text ``"true"`` enables it. ``"TRUE"``, ``"True"``,
    ``"yes"``, ``"1"``, ``""`` and ``None`` all mean OFF — no case folding and
    no truthiness, exactly as the pre-A3.3 reader behaved.
    """
    return raw == "true"


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
    validation: str = "ok"      # ok | normalized | conflict | clamped |
                                # monotonic_floor | fallback
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
    #: Non-configurable provenance resolved with the policy (D16-A3.1): the
    #: content digest/size of the rules table. Kept OUT of ``values`` so it
    #: can never be mistaken for a setting an operator may edit.
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}))
    #: The immutable Confidence policy resolved for this snapshot. It retains
    #: the submitted/effective split and ``normalization_applied``, which the
    #: five effective ``confidence.weight.*`` entries intentionally do not
    #: duplicate. It is not serialised into ``canonical_json`` or the digest:
    #: the digest identifies effective analytical behavior, while submitted
    #: values and row provenance remain available without claiming identity.
    confidence_policy: Optional[ConfidencePolicy] = field(
        default=None, compare=False, repr=False)

    # -- read-only views -------------------------------------------------
    @property
    def values(self) -> Dict[str, Any]:
        return {key: entry.value for key, entry in self.entries.items()}

    @property
    def sources(self) -> Dict[str, str]:
        return {key: entry.source for key, entry in self.entries.items()}

    @property
    def flags(self) -> Dict[str, Any]:
        """The analysis gates this run resolved (A3.3)."""
        return {key: entry.value for key, entry in self.entries.items()
                if entry.component == "flags"}

    @property
    def auto_disable_null(self) -> Optional[bool]:
        """The auto-disable gate, or ``None`` when it could not be resolved.

        Display paths use this tri-state so they can distinguish "configuration
        unavailable" from a legitimate ``False``. Analysis paths must call
        :meth:`require_auto_disable_null` instead.
        """
        entry = self.entries.get(FLAG_AUTO_DISABLE_NULL)
        if entry is None or entry.source == "unavailable":
            return None
        return bool(entry.value)

    def require_auto_disable_null(self) -> bool:
        """The gate for an analysis run — never substitutes a value."""
        value = self.auto_disable_null
        if value is None:
            raise PolicyUnavailable(
                "auto_disable_null_indicators could not be resolved; refusing "
                "to analyse with an assumed value")
        return value

    @property
    def alerts_auto_scan(self) -> bool:
        """Whether a fresh analysis triggers the Quality Alerts scan.

        Resolved once per snapshot from ``alerts.auto_scan`` (default ON when
        System Control has no row). A snapshot that does not carry the entry is
        an error, never a silent default (A3.4).
        """
        try:
            return bool(self.entries["alerts.auto_scan"].value)
        except KeyError as exc:
            raise PolicyUnavailable(
                "policy snapshot has no 'alerts.auto_scan' entry") from exc

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

    @property
    def identity_metadata(self) -> Dict[str, Any]:
        """Metadata that defines policy identity.

        Provenance-only entries (``PROVENANCE_METADATA_KEYS``) are excluded: a
        write timestamp records *when*, not *what*, so it must not move the
        digest. The full record stays available on ``metadata``.
        """
        return {key: value for key, value in self.metadata.items()
                if key not in PROVENANCE_METADATA_KEYS}

    def canonical_json(self, *, include_provenance: bool = False) -> str:
        """Canonical JSON of the snapshot — the exact bytes ``digest`` hashes.

        Sorted keys and compact separators make the form independent of input
        and insertion order. The five Confidence entries are the **effective**
        weights, so this identity describes analytical behavior, not the
        submitted row or its normalization history. Provenance metadata is
        excluded by default (see :attr:`identity_metadata`); pass
        ``include_provenance=True`` to render the complete record for display
        or audit. Only policy scalars, a hash/count/field-list and approved
        algorithm constants appear here — never credentials, keys, or session
        material.
        """
        metadata = (dict(self.metadata) if include_provenance
                    else self.identity_metadata)
        payload = {
            "resolver": self.resolver_version,
            "components": dict(self.component_versions),
            "values": _normalise(self.values),
            "metadata": _normalise(metadata),
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
            "metadata": dict(self.metadata),
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
            reason: str = "", validation: str = "ok",
            record_error: bool = True) -> None:
        fallback = source in ("default", "invalid", "unavailable")
        self.entries[key] = PolicyEntry(
            key=key, value=value, source=source, component=component,
            configurable=True, fallback_applied=fallback,
            validation=validation, storage=storage,
        )
        if source == "invalid" and record_error:
            self.errors.append(PolicyError(key=key, raw=raw,
                                           reason=reason or "invalid value",
                                           fallback=value))

    def missing(self, key: str, value: Any, component: str, *,
                storage: str = STORAGE_APP_CONFIG) -> None:
        self.add(key, value, "default", component, storage=storage,
                 validation="fallback")

    def add_error(self, key: str, *, raw: Any, reason: str,
                  fallback: Any) -> None:
        """Record a row/state error without pretending a value was replaced."""
        self.errors.append(PolicyError(key=key, raw=raw, reason=reason,
                                       fallback=fallback))


def _float_or(raw: Any, default: float) -> Tuple[float, str]:
    """``(value, 'database'|'invalid'|'default')`` for an optional number."""
    if raw is None:
        return default, "default"
    try:
        return float(raw), "database"
    except (TypeError, ValueError):
        return default, "invalid"


def _resolve_flags(system_settings: Mapping[str, Any],
                   collector: _Collector) -> Dict[str, Any]:
    """Analysis gates, resolved as explicit Booleans from the text store.

    A missing row is the documented fallback ``False`` (source ``default``).
    A present row is ``database`` even when its text is not ``"true"``: the
    value then really is OFF, which is different from never having configured
    it.
    """
    if FLAG_AUTO_DISABLE_KEY in system_settings:
        raw = system_settings[FLAG_AUTO_DISABLE_KEY]
        value = parse_auto_disable_null(raw)
        collector.add(FLAG_AUTO_DISABLE_NULL, value, "database", "flags",
                      storage=STORAGE_SYSTEM_SETTING, raw=raw)
    else:
        value = False
        collector.missing(FLAG_AUTO_DISABLE_NULL, value, "flags",
                          storage=STORAGE_SYSTEM_SETTING)
    return {FLAG_AUTO_DISABLE_NULL: value}


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
        z_value = default_z
        collector.missing("alerts.z_threshold", z_value, "alerts")
    else:
        try:
            z_value = float(z_raw)
        except (TypeError, ValueError):
            z_value = default_z
            collector.add("alerts.z_threshold", z_value, "invalid", "alerts",
                          raw=z_raw,
                          reason=f"expected a number; using default {default_z}")
        else:
            if z_value <= 0:
                z_value = default_z
                collector.add("alerts.z_threshold", z_value, "invalid",
                              "alerts", raw=z_raw,
                              reason="non-positive threshold; using default "
                                     f"{default_z}")
            else:
                collector.add("alerts.z_threshold", z_value, "database",
                              "alerts", raw=z_raw)

    # Auto-scan flag: ``pipeline._maybe_auto_scan_quality_alerts`` treats the
    # stored text form of 0/false/off as OFF and anything else as ON.
    auto_raw = cfg.get("alerts_auto_scan")
    if auto_raw is None:
        auto_scan = True
        collector.missing("alerts.auto_scan", auto_scan, "alerts")
    elif str(auto_raw).strip() in _AUTO_SCAN_OFF:
        auto_scan = False
        collector.add("alerts.auto_scan", False, "database", "alerts",
                      raw=auto_raw)
    else:
        auto_scan = True
        collector.add("alerts.auto_scan", True, "database", "alerts",
                      raw=auto_raw)

    return {"min_score": min_score, "min_peers": min_peers,
            "min_history": min_history, "history_window": history_window,
            "ml_enabled": ml_enabled, "ml_min_samples": ml_min_samples,
            "auto_scan": auto_scan,
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


def _confidence_policy(
    weights: Mapping[str, Any],
    high: Any,
    medium: Any,
    low: Any,
    zscore_threshold: Any,
) -> ConfidencePolicy:
    """Build one policy without adding another defaulting layer here."""
    return ConfidencePolicy(
        **{key: weights[key] for key in WEIGHT_KEYS},
        high=high,
        medium=medium,
        low=low,
        zscore_threshold=zscore_threshold,
    )


def _add_confidence_weight_entries(
    collector: _Collector,
    values: Mapping[str, Any],
    *,
    source: str,
    validation: str,
    raw: Any,
    reason: str = "",
    record_error: bool = True,
) -> None:
    for key in WEIGHT_KEYS:
        name = f"{CONFIDENCE_WEIGHT_PREFIX}{key}"
        value = values[key]
        if source == "default":
            collector.missing(name, value, "confidence",
                              storage=STORAGE_CONFIDENCE_WEIGHTS)
        else:
            collector.add(name, value, source, "confidence",
                          storage=STORAGE_CONFIDENCE_WEIGHTS, raw=raw,
                          reason=reason, validation=validation,
                          record_error=record_error)


def _resolve_confidence(
    app_config: Mapping[str, Any],
    collector: _Collector,
    *,
    confidence_weights: Optional[Mapping[str, Any]] = None,
    confidence_weights_row_id: Optional[int] = None,
    confidence_weights_row_ids: Optional[tuple[int, ...]] = None,
    confidence_weights_conflict: bool = False,
) -> Optional[ConfidencePolicy]:
    """Resolve cutoffs, raw Z, and the five effective Confidence weights.

    The weights row is an input to this pure resolver. A missing row means the
    documented defaults; a present row is validated and normalized by the one
    owner, :class:`ConfidencePolicy`. An unusable row falls back to the complete
    default weight set and records a row-level error. Duplicate rows retain the
    selected (lowest-id) values and are marked ``conflict`` on every weight
    entry; their observed ids live only in the error, never in the digest.
    """
    resolved: Dict[str, Any] = {}
    for key, default in _CONFIDENCE_DEFAULTS:
        raw = app_config.get(key)
        name = f"confidence.{key.replace('confidence_', '')}"
        if raw is None:
            resolved[key] = default
            collector.missing(name, default, "confidence")
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
            collector.add(name, value, "invalid", "confidence", raw=raw,
                          reason=f"expected a number; using default {default}")
        else:
            collector.add(name, value, "database", "confidence", raw=raw)
        resolved[key] = value

    z_raw = app_config.get(severity_policy.ZSCORE_KEY)
    default_z = DEFAULT_ZSCORE_THRESHOLD
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

    cutoffs = (resolved["confidence_high"], resolved["confidence_medium"],
               resolved["confidence_low"], resolved["zscore_threshold"])

    # Weights are judged and normalized by the policy itself, and that division
    # does not involve the cutoffs. A weights-only policy therefore resolves the
    # entries below, and the snapshot's policy is rebuilt from the same
    # submitted values plus the resolved cutoffs and Z.
    weights_only = (DEFAULT_HIGH, DEFAULT_MEDIUM, DEFAULT_LOW,
                    DEFAULT_ZSCORE_THRESHOLD)
    if confidence_weights is None:
        weights_policy = _confidence_policy(DEFAULT_WEIGHTS, *weights_only)
        _add_confidence_weight_entries(
            collector, weights_policy.effective_weights, source="default",
            validation="fallback", raw=None)
    else:
        raw_weights = (dict(confidence_weights)
                       if isinstance(confidence_weights, Mapping)
                       else None)
        try:
            if raw_weights is None:
                raise ValueError("weights row must be a mapping")
            weights_policy = _confidence_policy(raw_weights, *weights_only)
        except (KeyError, TypeError, ValueError) as exc:
            raw = raw_weights if raw_weights is not None else repr(
                confidence_weights)
            reason = f"invalid confidence weights: {exc}"
            weights_policy = _confidence_policy(DEFAULT_WEIGHTS, *weights_only)
            _add_confidence_weight_entries(
                collector, weights_policy.effective_weights, source="invalid",
                validation=("conflict" if confidence_weights_conflict
                             else "fallback"),
                raw=raw, reason=reason, record_error=False)
            collector.add_error(
                CONFIDENCE_WEIGHTS_ERROR_KEY, raw=raw, reason=reason,
                fallback=dict(weights_policy.effective_weights))
        else:
            validation = ("conflict" if confidence_weights_conflict else "ok")
            _add_confidence_weight_entries(
                collector, weights_policy.effective_weights, source="database",
                validation=validation, raw=raw_weights)

    try:
        policy: Optional[ConfidencePolicy] = _confidence_policy(
            dict(weights_policy.submitted_weights), *cutoffs)
    except (KeyError, TypeError, ValueError) as exc:
        # Only a stored cutoff or Z can fail here. They keep their own resolved
        # entries, unclamped, exactly as before; what is refused is inventing a
        # policy object whose scalars would disagree with those entries.
        collector.add_error(
            CONFIDENCE_POLICY_ERROR_KEY,
            raw=dict(zip(("high", "medium", "low", "zscore_threshold"),
                         cutoffs, strict=False)),
            reason=f"resolved Confidence cutoffs are not a usable policy: {exc}",
            fallback=None,
        )
        policy = None

    if confidence_weights_conflict:
        row_ids = list(confidence_weights_row_ids or ())
        if not row_ids and confidence_weights_row_id is not None:
            row_ids = [confidence_weights_row_id]
        collector.add_error(
            CONFIDENCE_WEIGHTS_ERROR_KEY,
            raw={"row_ids": row_ids, "count": len(row_ids)},
            reason="multiple confidence_weights rows; using lowest id",
            fallback=dict(weights_policy.effective_weights),
        )
    return policy


def _resolve_rules_config(app_config: Mapping[str, Any],
                          collector: _Collector) -> Dict[str, Any]:
    """Category ``rules`` — the compiled-rule factors.

    Defaults come from ``quality.definitions.RULE_DEFAULTS``, the immutable
    baseline captured at import. They must **not** come from the legacy
    ``_RULES_CONFIG`` table: reading it would make a stored value look like the
    documented default (wrong ``source``). A3.5 passes the resolved
    ``RulesPolicy`` to the rule engine, so this plane is the only authority.
    """
    from app.engine.quality.definitions import RULE_DEFAULTS

    resolved: Dict[str, Any] = {}
    for key, default in RULE_DEFAULTS.items():
        name = f"rules.{key}"
        raw = app_config.get(key)
        if raw is None:
            resolved[key] = default
            collector.missing(name, default, "rules")
            continue
        try:
            resolved[key] = float(raw)
        except (TypeError, ValueError):
            resolved[key] = default
            collector.add(name, default, "invalid", "rules", raw=raw,
                          reason=f"expected a number; using default {default}")
        else:
            collector.add(name, resolved[key], "database", "rules", raw=raw)
    return resolved


#: ``ml`` keys and coercions, mirroring ``pipeline._build_ml_config``. The
#: parity test compares this plane against that function, so a change there
#: cannot leave the resolver silently behind.
_ML_SPECS = (
    ("ml.enabled", "ml_enabled", "bool", 0),
    ("ml.clustering_enabled", "ml_clustering_enabled", "bool", 1),
    ("ml.clustering_min_k", "ml_clustering_min_k", "int", 2),
    ("ml.clustering_max_k", "ml_clustering_max_k", "int", 6),
    ("ml.anomaly_enabled", "ml_anomaly_enabled", "bool", 1),
    ("ml.anomaly_contamination", "ml_anomaly_contamination", "float", 0.05),
    ("ml.pca_enabled", "ml_pca_enabled", "bool", 1),
    ("ml.pca_variance_threshold", "ml_pca_variance_threshold", "float", 0.95),
)


def _resolve_ml(app_config: Mapping[str, Any],
                collector: _Collector) -> Dict[str, Any]:
    """Category ``ml`` — the Isolation-Forest / clustering switches."""
    resolved: Dict[str, Any] = {}
    for name, key, kind, default in _ML_SPECS:
        raw = app_config.get(key)
        if raw is None:
            value = bool(default) if kind == "bool" else default
            collector.missing(name, value, "ml")
            resolved[name] = value
            continue
        try:
            # ``_build_ml_config`` uses plain truthiness for booleans.
            value = (bool(raw) if kind == "bool"
                     else int(raw) if kind == "int" else float(raw))
        except (TypeError, ValueError):
            value = bool(default) if kind == "bool" else default
            collector.add(name, value, "invalid", "ml", raw=raw,
                          reason=f"expected {kind}; using default {default}")
        else:
            collector.add(name, value, "database", "ml", raw=raw)
        resolved[name] = value
    return resolved


def _resolve_trend_engine_gates(app_config: Mapping[str, Any],
                                collector: _Collector) -> Dict[str, Any]:
    """The leftover ``trends`` gates the trend engine reads directly.

    ``trend_r_squared`` and the four ``trend_finding_*`` gates are read by
    ``analyze_historical_trends`` as raw config, not through the setting
    specs. Defaults come from ``trends.TREND_ENGINE_DEFAULTS`` (the module's
    own documented table), so nothing is restated here.
    """
    from app.engine.anomaly.trends import TREND_ENGINE_DEFAULTS

    band_keys = {key for _name, key, _default in severity_policy.BAND_KEYS}
    resolved: Dict[str, Any] = {}
    for key, default in TREND_ENGINE_DEFAULTS.items():
        if (key == severity_policy.ZSCORE_KEY
                or key in severity_policy.TREND_SETTING_SPECS
                or key in band_keys):
            continue  # already resolved by the severity / trend planes
        raw = app_config.get(key)
        if raw is None:
            resolved[key] = float(default)
            collector.missing(key, resolved[key], "trend")
            continue
        try:
            resolved[key] = float(raw)
        except (TypeError, ValueError):
            resolved[key] = float(default)
            collector.add(key, float(default), "invalid", "trend", raw=raw,
                          reason=f"expected a number; using default {default}")
        else:
            collector.add(key, resolved[key], "database", "trend", raw=raw)
    return resolved


#: Rule columns that never participate in the identity hash.
#:
#: ``*_at`` are bookkeeping timestamps; ``id`` is a storage-assigned surrogate
#: key, so re-seeding or restoring byte-identical rule content under a new
#: primary key must not look like a policy change. Every other column is
#: derived from the mapper and therefore participates by default, so a future
#: analytical column cannot silently escape the hash.
_RULES_HASH_EXCLUDED_FIELDS = frozenset({"id"})


def rules_hash_fields() -> Tuple[str, ...]:
    """Rule columns hashed by :func:`rules_version`, in declaration order."""
    from app.models import Rule

    return tuple(attr.key for attr in Rule.__mapper__.column_attrs
                 if not attr.key.endswith("_at")
                 and attr.key not in _RULES_HASH_EXCLUDED_FIELDS)


def _rule_payload_value(name: str, value: Any) -> Any:
    """Canonical form of one rule field for the identity hash.

    ``params`` is stored as text. Parsing and re-serialising it through
    ``_normalise`` makes the hash sensitive to the *meaning* of the parameters
    and insensitive to JSON formatting (whitespace, key order). Text that is
    not valid JSON is tagged, so malformed text can never collide with the
    parsed value that happens to render the same string.
    """
    if name == "params" and isinstance(value, str):
        try:
            return {"json": _normalise(json.loads(value))}
        except (TypeError, ValueError):
            return {"text": value}
    return _normalise(value)


def rules_version(db) -> Dict[str, Any]:
    """Content digest + size of the ``rules`` table (D5: hash + stamp).

    Contract — what ``rules.hash`` identifies
    -----------------------------------------
    The hash identifies the **analytical rule set**: which validations run, at
    what severity, against what parameters. It is built from

    * every column returned by :func:`rules_hash_fields` — ``code``, ``name``,
      ``rule_type``, ``severity``, ``category``, ``expression_type``,
      ``params``, ``description``, ``enabled`` and ``sort_order``;
    * never a ``*_at`` timestamp, and never ``id`` (a surrogate key, see
      ``_RULES_HASH_EXCLUDED_FIELDS``);
    * rows ordered by ``code``, which is UNIQUE, so the order is total —
      independent of insertion order, of the query plan, and of process
      history;
    * canonical JSON (sorted keys, compact separators) of normalised values,
      with ``params`` parsed and re-serialised so formatting is inert.

    Therefore a timestamp-only touch, a ``params`` reformat, a primary-key
    reassignment and a re-seed of identical content all keep the hash, while
    any change to a field above moves it. No credential or secret can enter:
    ``Rule`` holds none, and ``RuleHistory`` — which stores old/new payloads —
    is never read.

    ``rules.updated_at`` is returned alongside the hash for display. It is
    provenance, not identity: it is excluded from the snapshot digest via
    ``PROVENANCE_METADATA_KEYS``.
    """
    from app.models import Rule

    rows = db.query(Rule).order_by(Rule.code).all()
    fields = rules_hash_fields()
    payload = [[_rule_payload_value(key, getattr(row, key)) for key in fields]
               for row in rows]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         default=str).encode("utf-8")
    stamps = [getattr(row, "updated_at", None) for row in rows]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return {
        "rules.hash": hashlib.sha256(encoded).hexdigest(),
        "rules.count": len(rows),
        "rules.fields": len(fields),
        "rules.hash_fields": list(fields),
        "rules.updated_at": max(stamps).isoformat() if stamps else None,
    }


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

    Only the comparison and Confidence policies have version constants today;
    the rest are recorded as ``unversioned`` rather than given invented semver
    (D15 §5). ``confidence`` is the policy version that owns weight validation
    and normalization, so a digest can name the rules that produced it.
    """
    return {
        "comparison": COMPARISON_POLICY_VERSION,
        "flags": UNVERSIONED,
        "severity": UNVERSIONED,
        "alerts": UNVERSIONED,
        "trend": UNVERSIONED,
        "scoring": UNVERSIONED,
        "confidence": CONFIDENCE_POLICY_VERSION,
        "rules": UNVERSIONED,
        "ml": UNVERSIONED,
        "layered": UNVERSIONED,
        "config": RESOLVER_VERSION,
    }


def _digest(snapshot: PolicySnapshot) -> str:
    return hashlib.sha256(snapshot.canonical_json().encode("utf-8")).hexdigest()


def _build(app_config: Mapping[str, Any],
           system_settings: Mapping[str, str],
           metadata: Optional[Mapping[str, Any]] = None,
           *,
           confidence_weights: Optional[Mapping[str, Any]] = None,
           confidence_weights_row_id: Optional[int] = None,
           confidence_weights_row_ids: Optional[tuple[int, ...]] = None,
           confidence_weights_conflict: bool = False) -> PolicySnapshot:
    collector = _Collector()
    _resolve_flags(system_settings, collector)
    _resolve_severity(app_config, collector)
    trend_values = _resolve_trend(app_config, system_settings, collector)
    _resolve_alerts(app_config, collector)
    _resolve_comparison(app_config, trend_values, collector)
    _resolve_scoring(app_config, collector)
    confidence_policy = _resolve_confidence(
        app_config, collector,
        confidence_weights=confidence_weights,
        confidence_weights_row_id=confidence_weights_row_id,
        confidence_weights_row_ids=confidence_weights_row_ids,
        confidence_weights_conflict=confidence_weights_conflict,
    )
    _resolve_rules_config(app_config, collector)
    _resolve_ml(app_config, collector)
    _resolve_trend_engine_gates(app_config, collector)

    entries = MappingProxyType(dict(collector.entries))
    frozen = MappingProxyType(frozen_constants())
    snapshot = PolicySnapshot(
        entries=entries,
        metadata=MappingProxyType(dict(metadata or {})),
        frozen_constants=frozen,
        component_versions=MappingProxyType(component_versions()),
        resolver_version=RESOLVER_VERSION,
        digest="",
        errors=tuple(collector.errors),
        confidence_policy=confidence_policy,
    )
    # Digest is computed over the canonical form (values + versions + frozen),
    # then attached via replace so the dataclass stays frozen.
    return replace(snapshot, digest=_digest(snapshot))


def resolve_policy(app_config: Optional[Mapping[str, Any]] = None,
                   system_settings: Optional[Mapping[str, str]] = None,
                   *, strict: bool = True,
                   read_error: Optional[str] = None,
                   metadata: Optional[Mapping[str, Any]] = None,
                   confidence_weights: Optional[Mapping[str, Any]] = None,
                   confidence_weights_row_id: Optional[int] = None,
                   confidence_weights_row_ids: Optional[tuple[int, ...]] = None,
                   confidence_weights_conflict: bool = False,
                   ) -> PolicySnapshot:
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

    snapshot = _build(
        app_config or {}, system_settings or {}, metadata,
        confidence_weights=confidence_weights,
        confidence_weights_row_id=confidence_weights_row_id,
        confidence_weights_row_ids=confidence_weights_row_ids,
        confidence_weights_conflict=confidence_weights_conflict,
    )
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
        confidence_policy=None,
    )
    return replace(downgraded, digest=_digest(downgraded))


def load_policy_snapshot(db, *, strict: bool = True) -> PolicySnapshot:
    """Database-backed snapshot: one read of each policy store.

    This is the only function in the module that touches the session. It reads
    the two stores once and delegates all resolution to :func:`resolve_policy`,
    so the values a caller sees are identical to the pure path over the same
    rows. No consumer is switched to it in A1.
    """
    from app.models import AppConfig, ConfidenceWeights, SystemSetting

    try:
        app_rows = db.query(AppConfig).all()
        app_config = {row.key: row.value for row in app_rows}
        setting_rows = db.query(SystemSetting).all()
        system_settings = {row.key: row.value for row in setting_rows}
        # ConfidenceWeights is a singleton in intent, but the table has no
        # uniqueness constraint. Read every row, use the lowest id as the
        # deterministic policy, and report all observed ids as a conflict.
        weight_rows = (db.query(ConfidenceWeights)
                       .order_by(ConfidenceWeights.id.asc())
                       .all())
        selected_weights = weight_rows[0] if weight_rows else None
        weight_values = ({
            key: getattr(selected_weights, key) for key in WEIGHT_KEYS
        } if selected_weights is not None else None)
        weight_row_ids = tuple(row.id for row in weight_rows)
        # The rules table is policy too, but as rows rather than settings:
        # it is recorded as immutable metadata (hash + size), never as a
        # configurable value (D16-A3.1 / D5).
        rules_metadata = rules_version(db)
    except Exception as exc:  # noqa: BLE001 - re-raised or recorded as required
        message = ("Analysis configuration could not be read from the "
                   f"database: {exc}")
        if strict:
            raise PolicyUnavailable(message) from exc
        return resolve_policy({}, {}, strict=False, read_error=message)

    return resolve_policy(
        app_config, system_settings, strict=strict, metadata=rules_metadata,
        confidence_weights=weight_values,
        confidence_weights_row_id=(selected_weights.id
                                   if selected_weights is not None else None),
        confidence_weights_row_ids=weight_row_ids,
        confidence_weights_conflict=len(weight_rows) > 1,
    )


def load_display_policy(db) -> PolicySnapshot:
    """Display-path snapshot: never raises, memoized per session.

    Dashboard, tree and preview paths call this instead of resolving once per
    widget. A gate whose entry is ``unavailable`` reads as ``None`` through
    :attr:`PolicySnapshot.auto_disable_null`, and the caller must surface that
    as "configuration unavailable" rather than render a confident ``False``.
    """
    info = getattr(db, "info", None)
    if info is not None:
        cached = info.get("display_policy_snapshot")
        if cached is not None:
            return cached
    snapshot = load_policy_snapshot(db, strict=False)
    if info is not None:
        try:
            info["display_policy_snapshot"] = snapshot
        except Exception:
            pass
    return snapshot
