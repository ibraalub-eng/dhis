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
from app.engine.confidence_policy import ConfidencePolicy
from app.engine.config_resolver import PolicySnapshot, PolicyUnavailable
from app.engine.quality.definitions import DEFAULT_RULES_POLICY, RulesPolicy

#: Keys whose local ``trend`` setting names are the resolver's own key names.
_TREND_KEYS = tuple(severity_policy.TREND_SETTING_SPECS)
_BAND_KEYS = tuple(key for _name, key, _default in severity_policy.BAND_KEYS)

#: Every value the Confidence adapter needs. A snapshot that lacks one of
#: these, or marks one unavailable, cannot produce a policy.
_CONFIDENCE_REQUIRED_KEYS = (
    "confidence.weight.rule_compliance",
    "confidence.weight.historical",
    "confidence.weight.cross_hospital",
    "confidence.weight.trend",
    "confidence.weight.completeness",
    "confidence.high",
    "confidence.medium",
    "confidence.low",
    "confidence.zscore_threshold",
)


class ConfidencePolicyInvalid(PolicyUnavailable):
    """Confidence values were present but could not form a valid policy.

    This is deliberately a :class:`PolicyUnavailable` subclass so callers that
    already fail closed on an unavailable policy also fail closed here. The
    snapshot's entries remain unchanged and retain their original source and
    invalid value; this exception never carries a substituted default.
    """


def _entry(snapshot: PolicySnapshot, key: str):
    try:
        return snapshot.entries[key]
    except KeyError as exc:  # a consumer asked for a plane A1 does not resolve
        raise KeyError(
            f"policy snapshot has no entry for {key!r} — the resolver does not "
            "resolve that key yet") from exc


def _value(snapshot: PolicySnapshot, key: str) -> Any:
    return _entry(snapshot, key).value


def rules_policy_from_snapshot(snapshot: PolicySnapshot) -> RulesPolicy:
    """The five Rules settings as the immutable value A3.5 consumers receive.

    Every field is read from the snapshot's ``rules.*`` plane, which the
    resolver populated from System Control (or its documented default). Nothing
    here reads a database or a process-global table, and a missing entry raises
    rather than silently substituting a default.
    """
    return RulesPolicy.from_mapping({
        key: float(_value(snapshot, f"rules.{key}"))
        for key in DEFAULT_RULES_POLICY.as_dict()
    })


def trends_policy_from_snapshot(snapshot: PolicySnapshot):
    """The trend policy as the immutable value A3.5 P2 consumers receive.

    Every field is taken from the snapshot: the validated trend controls and
    bands from the severity plane, the five raw engine gates from their own
    ``trend`` entries, and the clamped Z threshold from ``severity``. Nothing
    is re-read from the database or from the trend module's global table, and a
    missing entry raises rather than substituting a default here.
    """
    from app.engine.anomaly.trends import TREND_GATE_KEYS, TrendsPolicy

    analysis = analysis_config_from_snapshot(snapshot)
    gates = {key: float(_value(snapshot, key)) for key in TREND_GATE_KEYS}
    return TrendsPolicy(
        settings=analysis.trend,
        bands=dict(analysis.trend_bands),
        finding_slope=gates["trend_finding_slope"],
        finding_deviation=gates["trend_finding_deviation"],
        finding_cv=gates["trend_finding_cv"],
        finding_r_squared=gates["trend_finding_r_squared"],
        trend_r_squared=gates["trend_r_squared"],
        zscore_threshold=analysis.zscore_threshold,
    )


def confidence_policy_from_snapshot(snapshot: PolicySnapshot) -> ConfidencePolicy:
    """The immutable Confidence policy carried by this snapshot.

    The resolver attaches the policy it actually validated. That object is the
    only place the original ``submitted_weights`` and
    ``normalization_applied`` survive; the five snapshot entries intentionally
    contain only the effective weights that analytical consumers use.

    A hand-built/legacy snapshot without the attached object falls back to the
    five effective entries and the four cutoff/Z entries. In that fallback the
    original submission is unavailable, so normalization is necessarily
    reported as not applied; resolver-produced snapshots always take the
    faithful path above.

    A snapshot that could not read its configuration, omitted a required
    Confidence entry, or marked one unavailable is refused. It is not a legacy
    snapshot with usable entries: returning defaults for it would turn an
    outage into a normal-looking policy. Invalid cutoff/Z values are likewise
    refused, with :class:`ConfidencePolicyInvalid`, after preserving the
    snapshot's original entry and source.
    """
    if snapshot.read_error is not None:
        raise PolicyUnavailable(
            "Confidence policy unavailable: the configuration snapshot records "
            f"a read error: {snapshot.read_error}")

    missing = [key for key in _CONFIDENCE_REQUIRED_KEYS
               if key not in snapshot.entries]
    if missing:
        raise PolicyUnavailable(
            "Confidence policy unavailable: snapshot is missing required "
            f"entries: {', '.join(missing)}")

    unavailable = [key for key in _CONFIDENCE_REQUIRED_KEYS
                   if snapshot.entries[key].source == "unavailable"]
    if unavailable:
        raise PolicyUnavailable(
            "Confidence policy unavailable: snapshot entries are unavailable: "
            f"{', '.join(unavailable)}")

    policy = getattr(snapshot, "confidence_policy", None)
    if policy is not None:
        return policy
    try:
        return ConfidencePolicy(
            rule_compliance=float(_value(
                snapshot, "confidence.weight.rule_compliance")),
            historical=float(_value(snapshot, "confidence.weight.historical")),
            cross_hospital=float(_value(
                snapshot, "confidence.weight.cross_hospital")),
            trend=float(_value(snapshot, "confidence.weight.trend")),
            completeness=float(_value(
                snapshot, "confidence.weight.completeness")),
            high=float(_value(snapshot, "confidence.high")),
            medium=float(_value(snapshot, "confidence.medium")),
            low=float(_value(snapshot, "confidence.low")),
            zscore_threshold=float(_value(
                snapshot, "confidence.zscore_threshold")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfidencePolicyInvalid(
            "Confidence policy invalid: "
            f"{exc}; resolved entries were preserved") from exc


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
    """What a run should record about the configuration it used.

    ``errors`` is the stable, serializable error summary: key and reason only,
    never the raw value (which can contain database row ids or submitted-only
    weights). ``confidence`` carries the validation state a future analysis
    consumer needs to see an invalid-weight fallback or a duplicate-row
    conflict without depending on the analytical digest, which intentionally
    identifies effective behavior only.
    """
    confidence_errors = [
        {"key": error.key, "reason": error.reason}
        for error in snapshot.errors
        if error.key.startswith("confidence.")
    ]
    confidence_entries = {
        key: entry for key, entry in snapshot.entries.items()
        if entry.component == "confidence"
    }
    return {
        "digest": snapshot.digest,
        "resolver_version": snapshot.resolver_version,
        "component_versions": dict(snapshot.component_versions),
        "unavailable_keys": list(snapshot.unavailable_keys),
        "invalid_keys": list(snapshot.invalid_keys),
        "read_error": snapshot.read_error,
        "errors": [
            {"key": error.key, "reason": error.reason}
            for error in snapshot.errors
        ],
        "confidence": {
            "errors": confidence_errors,
            "invalid_keys": sorted(
                key for key, entry in confidence_entries.items()
                if entry.source == "invalid"),
            "fallback_keys": sorted(
                key for key, entry in confidence_entries.items()
                if entry.source == "invalid" and entry.fallback_applied),
            "conflict_keys": sorted(
                key for key, entry in confidence_entries.items()
                if entry.validation == "conflict"),
            "validation": {
                key: entry.validation
                for key, entry in sorted(confidence_entries.items())
                if entry.validation != "ok" and entry.source != "default"
            },
        },
    }
