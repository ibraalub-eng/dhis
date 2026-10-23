"""Single severity vocabulary, temporal-trend policy and severity resolution.

Why this module exists
----------------------
The platform already classifies issues with four engines, each with its own
vocabulary:

* clinical rules / thresholds  -> ``CRITICAL / HIGH / MEDIUM / LOW``
* statistical outlier detection (layered + z-score) -> ``NONE / LOW / MODERATE
  / HIGH / VERY_HIGH``
* data-validation / quality rules -> ``CRITICAL / HIGH / MEDIUM / LOW``
* peer-comparison analysis -> the layered bands above

This module is the ONE place those vocabularies are normalized, and the ONE
place the configured temporal-trend policy is interpreted. It never replaces an
engine's classification: the original engine level is carried in every result
(``engine_level``) together with the source and a plain-language reason, so a
finding stays auditable after normalization.

Three distinct, persisted outputs are produced by :func:`resolve_severity`:

``base_severity``
    The classification of the existing issue-specific engine (rules, outlier
    detection, validation, peer comparison), normalized but never altered.
``trend_assessment``
    What the temporal-trend engine found, with its supporting numbers.
``final_severity``
    ``base_severity`` after the configured severity policy. With the default
    policy (``none``) it always equals ``base_severity``: a trend is recorded
    but cannot raise severity on its own.

Configuration
-------------
Trend controls live in the EXISTING ``AppConfig`` category ``trends`` that
``app.engine.pipeline`` already loads into ``app.engine.anomaly.trends``. The
only new keys are listed in :data:`TREND_SETTING_SPECS`; the persistence
control reuses the existing ``trend_finding_consecutive`` key. The Z-score
threshold is NOT duplicated here: ``thresholds.zscore_threshold`` is the single
authoritative value (saved default 2.5), read through
:func:`load_analysis_config`.

Missing keys fall back to the documented defaults in the specs BELOW and are
reported with ``source == "default"`` so System Control can show what is
effectively running. A database read failure is never papered over: the loader
raises :class:`AnalysisConfigError` and callers surface it.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# ── Canonical severity scale ───────────────────────────────────────────────
# The layered detection bands are the canonical scale because they are the
# scale already shared by Outlier Diagnostics, Quality Alerts and the Quality
# Score. Other engines map into it without losing their original value.
LEVEL_NONE = "NONE"
LEVEL_LOW = "LOW"
LEVEL_MODERATE = "MODERATE"
LEVEL_HIGH = "HIGH"
LEVEL_VERY_HIGH = "VERY_HIGH"
LEVELS: Tuple[str, ...] = (LEVEL_NONE, LEVEL_LOW, LEVEL_MODERATE, LEVEL_HIGH,
                           LEVEL_VERY_HIGH)
LEVEL_RANK: Dict[str, int] = {name: i for i, name in enumerate(LEVELS)}

# Engine vocabularies -> canonical levels. Aliases are intentional and
# documented: the rule engine's CRITICAL is the top band (VERY_HIGH), its
# MEDIUM is the middle band (MODERATE). Normalization NEVER invents a higher or
# lower level for an existing engine result.
_SEVERITY_ALIASES: Dict[str, str] = {
    "NONE": LEVEL_NONE,
    "NORMAL": LEVEL_NONE,
    "NEGLIGIBLE": LEVEL_NONE,
    "INFO": LEVEL_NONE,
    "LOW": LEVEL_LOW,
    "MINOR": LEVEL_LOW,
    "MODERATE": LEVEL_MODERATE,
    "MEDIUM": LEVEL_MODERATE,
    "MED": LEVEL_MODERATE,
    "HIGH": LEVEL_HIGH,
    "MAJOR": LEVEL_HIGH,
    "VERY_HIGH": LEVEL_VERY_HIGH,
    "VERY HIGH": LEVEL_VERY_HIGH,
    "VERYHIGH": LEVEL_VERY_HIGH,
    "CRITICAL": LEVEL_VERY_HIGH,
    "SEVERE": LEVEL_VERY_HIGH,
}

# Classification sources (recorded next to every severity so a finding can be
# traced back to the engine that produced it).
SOURCE_CLINICAL_RULE = "clinical_rule"
SOURCE_STATISTICAL_OUTLIER = "statistical_outlier"
SOURCE_DATA_QUALITY = "data_quality"
SOURCE_PEER_COMPARISON = "peer_comparison"
SOURCE_TEMPORAL_TREND = "temporal_trend"
SOURCE_SEVERITY_POLICY = "severity_policy"
SOURCE_LEGACY = "legacy"
SOURCES: Tuple[str, ...] = (
    SOURCE_CLINICAL_RULE,
    SOURCE_STATISTICAL_OUTLIER,
    SOURCE_DATA_QUALITY,
    SOURCE_PEER_COMPARISON,
    SOURCE_TEMPORAL_TREND,
)


class UnknownSeverityError(ValueError):
    """Raised when a value cannot be mapped onto the canonical scale."""


def normalize_severity(raw: Any, *, source: str,
                       reason: str = "") -> "SeverityClassification":
    """Map any engine severity onto the canonical scale, preserving the input."""
    engine_level = str(raw or "").strip()
    canonical = _SEVERITY_ALIASES.get(engine_level.upper())
    if canonical is None:
        raise UnknownSeverityError(f"unknown severity {raw!r} (source {source!r})")
    note = reason or (
        f"Engine level {engine_level or 'NONE'} from {source} normalized to "
        f"{canonical} by the shared severity policy."
    )
    return SeverityClassification(
        level=canonical,
        engine_level=engine_level or LEVEL_NONE,
        source=source,
        reason=note,
    )


def try_normalize_severity(raw: Any, *, source: str) -> Optional["SeverityClassification"]:
    try:
        return normalize_severity(raw, source=source)
    except UnknownSeverityError:
        return None


def max_level(*levels: Optional[str]) -> str:
    """Highest canonical level among ``levels`` (unknown values ignored)."""
    best = LEVEL_NONE
    for level in levels:
        rank = LEVEL_RANK.get(str(level or "").upper())
        if rank is not None and rank > LEVEL_RANK[best]:
            best = LEVELS[rank]
    return best


def raise_level(level: str, steps: int) -> str:
    """Move ``level`` up ``steps`` bands, capped at VERY_HIGH."""
    rank = LEVEL_RANK.get(str(level or "").upper(), 0) + max(0, int(steps or 0))
    return LEVELS[min(rank, len(LEVELS) - 1)]


@dataclass(frozen=True)
class SeverityClassification:
    """One normalized classification with its provenance."""

    level: str
    engine_level: str
    source: str
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "engine_level": self.engine_level,
            "source": self.source,
            "reason": self.reason,
        }


# ── Settings specs (the single source of defaults + validation) ────────────
TREND_CATEGORY = "trends"
THRESHOLDS_CATEGORY = "thresholds"
ZSCORE_KEY = "zscore_threshold"
DEFAULT_ZSCORE_THRESHOLD = 2.5
ZSCORE_MIN, ZSCORE_MAX = 1.0, 5.0
ZSCORE_STEP = 0.1


def zscore_bounds() -> Dict[str, Any]:
    """The allowed Z-score range, shared by every editor.

    System Control and Settings both render this range from the API instead of
    hardcoding their own, so the two screens cannot drift apart (they used to
    disagree: 1-4 with 0.5 steps vs 1-5 with 0.1 steps).
    """
    return {
        "min": ZSCORE_MIN,
        "max": ZSCORE_MAX,
        "step": ZSCORE_STEP,
        "default": DEFAULT_ZSCORE_THRESHOLD,
    }

#: Existing slope bands used to label how strong a trend is. Read from the same
#: ``trends`` AppConfig category the trend engine already consumes.
BAND_KEYS = (
    ("stable", "trend_slope_stable", 2.0),
    ("low", "trend_slope_low", 5.0),
    ("moderate", "trend_slope_moderate", 15.0),
    ("high", "trend_slope_high", 30.0),
)


@dataclass(frozen=True)
class SettingSpec:
    """Validation metadata for one System Control trend setting."""

    key: str
    default: Any
    kind: str                     # bool | int | float | enum
    label: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    options: Tuple[str, ...] = ()
    description: str = ""

    def describe(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "default": self.default,
            "kind": self.kind,
            "label": self.label,
            "min": self.minimum,
            "max": self.maximum,
            "options": list(self.options),
            "description": self.description,
        }


#: Genuinely new controls (plus the existing persistence knob, reused instead of
#: introducing a duplicate). Every one is validated here, persisted in AppConfig
#: category ``trends`` and consumed by the trend engine / severity resolution.
TREND_SETTING_SPECS: Dict[str, SettingSpec] = {
    spec.key: spec for spec in (
        SettingSpec(
            "trend_assessment_enabled", True, "bool",
            "Enable temporal trend assessment",
            description="When off, the trend engine returns no trend results and "
                        "no trend-based severity policy can apply.",
        ),
        SettingSpec(
            "trend_analysis_window", 12, "int",
            "Analysis window (months)",
            minimum=1, maximum=36,
            description="How many of the most recent months the trend engine "
                        "analyses.",
        ),
        SettingSpec(
            "trend_min_history_months", 2, "int",
            "Minimum historical months",
            minimum=2, maximum=24,
            description="Prior periods required before a trend may be assessed.",
        ),
        SettingSpec(
            "trend_direction", "any", "enum",
            "Trend direction that counts",
            options=("any", "increasing", "decreasing", "indicator_specific"),
            description="'indicator_specific' uses each indicator's configured "
                        "clinical direction (lower_is_better -> rising is adverse).",
        ),
        SettingSpec(
            # Existing AppConfig key, reused instead of adding a duplicate.
            "trend_finding_consecutive", 3, "int",
            "Minimum persistence (consecutive months)",
            minimum=1, maximum=12,
            description="Existing persistence setting, reused: consecutive "
                        "same-direction months required for a trend to qualify.",
        ),
        SettingSpec(
            "trend_min_cumulative_change_pct", 5.0, "float",
            "Minimum cumulative change (%)",
            minimum=0.0, maximum=100.0,
            description="Absolute first-to-last change across the window required "
                        "for a trend to qualify.",
        ),
        SettingSpec(
            "trend_severity_policy", "none", "enum",
            "Trend handling policy",
            options=("none", "escalate", "override"),
            description="'none' records the trend only; 'escalate' raises final "
                        "severity by the escalation factor; 'override' sets it to "
                        "the configured target.",
        ),
        SettingSpec(
            "trend_severity_escalation", 1, "int",
            "Severity escalation factor (bands)",
            minimum=1, maximum=4,
            description="Bands added to base severity when the policy is "
                        "'escalate' (capped at VERY_HIGH).",
        ),
        SettingSpec(
            "trend_severity_target", "HIGH", "enum",
            "Target severity for override",
            options=("LOW", "MODERATE", "HIGH", "VERY_HIGH"),
            description="Final severity used when the policy is 'override'.",
        ),
        SettingSpec(
            "trend_min_completeness", 0.0, "float",
            "Minimum data completeness (%) before trend escalation",
            minimum=0.0, maximum=100.0,
            description="0 disables the gate. When set, a trend may only change "
                        "severity if the hospital/month completeness meets it.",
        ),
    )
}


class AnalysisConfigError(RuntimeError):
    """The saved analysis configuration could not be loaded from the database."""


#: ``trend_finding_consecutive`` is an EXISTING AppConfig key and stays there.
#: Every other spec above is a genuinely new control, stored as a
#: ``SystemSetting`` (the same key/value storage the rest of System Control
#: uses) so textual enums are persisted losslessly.
EXISTING_TREND_KEYS = ("trend_finding_consecutive",)
NEW_TREND_KEYS: Tuple[str, ...] = tuple(
    key for key in TREND_SETTING_SPECS if key not in EXISTING_TREND_KEYS)


def coerce_setting(spec: SettingSpec, raw: Any) -> Any:
    """Validate/normalize one raw setting value. Raises ``ValueError``."""
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if float(raw) in (0.0, 1.0):
                return float(raw) == 1.0
            raise ValueError("expected a boolean (0/1)")
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off", ""):
            return False
        raise ValueError("expected a boolean (true/false)")
    if spec.kind in ("int", "float"):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError("expected a number") from None
        if not math.isfinite(value):
            raise ValueError("expected a finite number")
        value = max(float(spec.minimum), min(float(spec.maximum), value)) \
            if spec.minimum is not None and spec.maximum is not None else value
        return int(round(value)) if spec.kind == "int" else round(value, 4)
    if spec.kind == "enum":
        text = str(raw).strip().lower()
        for option in spec.options:
            if option.lower() == text:
                return option
        raise ValueError(f"expected one of {', '.join(spec.options)}")
    raise ValueError(f"unsupported setting kind {spec.kind!r}")


@dataclass(frozen=True)
class TrendSettings:
    """Resolved trend controls (field names == AppConfig keys)."""

    trend_assessment_enabled: bool = True
    trend_analysis_window: int = 12
    trend_min_history_months: int = 2
    trend_direction: str = "any"
    trend_finding_consecutive: int = 3
    trend_min_cumulative_change_pct: float = 5.0
    trend_severity_policy: str = "none"
    trend_severity_escalation: int = 1
    trend_severity_target: str = "HIGH"
    trend_min_completeness: float = 0.0
    sources: Mapping[str, str] = field(default_factory=dict)
    errors: Tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.trend_assessment_enabled)

    @property
    def window(self) -> int:
        return max(1, int(self.trend_analysis_window))

    @property
    def min_history(self) -> int:
        return max(2, int(self.trend_min_history_months))

    @property
    def min_persistence(self) -> int:
        return max(1, int(self.trend_finding_consecutive))

    @property
    def min_cumulative_change(self) -> float:
        return max(0.0, float(self.trend_min_cumulative_change_pct))

    @property
    def policy(self) -> str:
        return str(self.trend_severity_policy or "none").lower()

    @property
    def escalation(self) -> int:
        return max(1, int(self.trend_severity_escalation))

    @property
    def target(self) -> str:
        return str(self.trend_severity_target or LEVEL_HIGH).upper()

    @property
    def min_completeness(self) -> float:
        return max(0.0, float(self.trend_min_completeness))

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            spec.key: getattr(self, spec.key) for spec in TREND_SETTING_SPECS.values()
        }
        data.update({"sources": dict(self.sources), "errors": list(self.errors)})
        return data


def default_trend_bands() -> Dict[str, float]:
    return {name: default for name, _key, default in BAND_KEYS}


def resolve_trend_settings(config: Optional[Mapping[str, Any]] = None) -> TrendSettings:
    """Resolve + validate the trend controls from a raw config mapping.

    Missing keys use the documented spec defaults and are reported as
    ``source == "default"``. An unparseable stored value is reported as
    ``source == "invalid"`` plus an error string and falls back to its default —
    the failure is visible, never silent.
    """
    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    errors = []
    for spec in TREND_SETTING_SPECS.values():
        present = (config is not None and spec.key in config
                   and config[spec.key] not in (None, ""))
        if not present:
            values[spec.key] = spec.default
            sources[spec.key] = "default"
            continue
        try:
            values[spec.key] = coerce_setting(spec, config[spec.key])
            sources[spec.key] = "configured"
        except ValueError as exc:
            values[spec.key] = spec.default
            sources[spec.key] = "invalid"
            errors.append(
                f"{spec.key}: {exc}; using default {spec.default!r}")
    return TrendSettings(**values, sources=sources, errors=tuple(errors))


@dataclass(frozen=True)
class AnalysisConfig:
    """Effective analysis configuration loaded from the database."""

    zscore_threshold: float
    zscore_threshold_source: str
    trend: TrendSettings
    trend_bands: Mapping[str, float]
    raw_trends: Mapping[str, Any]
    settings: Mapping[str, Mapping[str, Any]]
    errors: Tuple[str, ...] = ()

    @property
    def source(self) -> str:
        sources = {meta.get("source") for meta in self.settings.values()}
        if not sources:
            return "defaults"
        if sources == {"database"}:
            return "database"
        if "database" in sources:
            return "mixed"
        return "defaults"

    def trend_engine_config(self) -> Dict[str, Any]:
        """Config dict for ``app.engine.anomaly.trends`` callers.

        Carries the saved trend slice plus the authoritative Z-score threshold
        and slope bands, so an out-of-pipeline caller (analysis API, file ops,
        audit explain) applies exactly the same saved configuration.
        """
        merged: Dict[str, Any] = dict(self.raw_trends)
        merged[ZSCORE_KEY] = self.zscore_threshold
        for name, key, _default in BAND_KEYS:
            merged[key] = self.trend_bands[name]
        return merged


def load_analysis_config(db) -> AnalysisConfig:
    """Load the saved severity/trend configuration from the database.

    Raises :class:`AnalysisConfigError` when the configuration cannot be read —
    callers must surface that instead of silently running on hardcoded rules.
    """
    from app.config_utils import get_config_dict
    from app.models import SystemSetting

    try:
        trends_cfg = get_config_dict(db, TREND_CATEGORY) or {}
        thresholds_cfg = get_config_dict(db, THRESHOLDS_CATEGORY) or {}
        stored_settings = {row.key: row.value
                           for row in db.query(SystemSetting).all()}
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed error
        raise AnalysisConfigError(
            "Analysis configuration could not be read from the database: "
            f"{exc}") from exc

    raw_trends: Dict[str, Any] = dict(trends_cfg)
    for key in NEW_TREND_KEYS:
        value = stored_settings.get(key)
        if value not in (None, ""):
            raw_trends[key] = value
    trend = resolve_trend_settings(raw_trends)

    errors = list(trend.errors)
    settings: Dict[str, Dict[str, Any]] = {}
    for spec in TREND_SETTING_SPECS.values():
        source = trend.sources.get(spec.key, "default")
        settings[spec.key] = {
            **spec.describe(),
            "value": getattr(trend, spec.key),
            "source": "database" if source == "configured" else source,
        }

    # Authoritative Z-score threshold: thresholds.zscore_threshold only. The
    # saved value is 2.5; it is clamped for safety exactly like System Control.
    raw_z = thresholds_cfg.get(ZSCORE_KEY)
    if raw_z is None:
        z_value, z_source = DEFAULT_ZSCORE_THRESHOLD, "default"
    else:
        try:
            z_value = max(ZSCORE_MIN, min(ZSCORE_MAX, float(raw_z)))
            z_source = "database"
        except (TypeError, ValueError):
            z_value, z_source = DEFAULT_ZSCORE_THRESHOLD, "invalid"
            errors.append(
                f"{ZSCORE_KEY}: expected a number; using default "
                f"{DEFAULT_ZSCORE_THRESHOLD}")

    bands = dict(default_trend_bands())
    for name, key, default in BAND_KEYS:
        raw = trends_cfg.get(key)
        if raw is None:
            continue
        try:
            bands[name] = max(0.0, float(raw))
        except (TypeError, ValueError):
            errors.append(f"{key}: expected a number; using default {default}")
    # Keep the band ladder monotonic so a misordered config cannot invert
    # severity labels.
    order = ("stable", "low", "moderate", "high")
    for previous, current in zip(order, order[1:], strict=False):
        bands[current] = max(bands[current], bands[previous])

    return AnalysisConfig(
        zscore_threshold=round(z_value, 2),
        zscore_threshold_source=z_source,
        trend=trend,
        trend_bands=bands,
        raw_trends=raw_trends,
        settings=settings,
        errors=tuple(errors),
    )


def policy_fingerprint(config: AnalysisConfig) -> str:
    """Stable digest of every setting that can change a classified severity.

    Stored next to each persisted alert so a later reader can tell whether the
    row was resolved under the policy that is in effect NOW, without guessing
    from the policy name alone (changing window, persistence, direction,
    escalation factor or the Z-score threshold alters outcomes while the policy
    label stays ``escalate``).
    """
    payload = {
        "zscore_threshold": round(float(config.zscore_threshold), 4),
        **{key: getattr(config.trend, key) for key in TREND_SETTING_SPECS},
        "trend_bands": {name: round(float(value), 4)
                        for name, value in config.trend_bands.items()},
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def stored_policy_state(stored: dict, current_fingerprint: Optional[str]) -> str:
    """``current`` / ``stale`` / ``unknown`` for one persisted policy snapshot.

    One definition shared by the Quality Alerts list/detail and the dashboard
    drift count, so a row can never be "stale" on one screen and "current" on
    another. ``unknown`` means the comparison cannot be made: no fingerprint on
    the stored row (predates fingerprints) or no readable current policy.
    """
    fingerprint = stored.get("fingerprint") if isinstance(stored, dict) else None
    if not current_fingerprint or not fingerprint:
        return "unknown"
    return "current" if fingerprint == current_fingerprint else "stale"


def seed_severity_trend_settings(session) -> int:
    """Persist defaults for genuinely new controls that have no row yet.

    Idempotent and insert-only: an operator's saved value is never overwritten.
    Returns the number of rows created.
    """
    from app.models import SystemSetting

    existing = {row.key for row in session.query(SystemSetting).all()}
    created = 0
    for key in NEW_TREND_KEYS:
        if key in existing:
            continue
        spec = TREND_SETTING_SPECS[key]
        value = spec.default
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        session.add(SystemSetting(key=key, value=text))
        created += 1
    if created:
        session.commit()
    return created


# ── Trend assessment ───────────────────────────────────────────────────────
def _ols(values: Sequence[float]) -> Tuple[float, float]:
    """(slope per month, r²) of ``values`` against month index 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0, 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    sxx = sum((x - mean_x) ** 2 for x in range(n))
    if sxx == 0:
        return 0.0, 0.0
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot <= 0:
        return slope, 0.0
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in enumerate(values))
    return slope, max(0.0, 1.0 - ss_res / ss_tot)


def persistence_run(values: Sequence[float]) -> Tuple[str, int]:
    """Longest run of same-direction month-over-month moves (count = moves)."""
    best_direction, best = "stable", 0
    current_direction, current = "stable", 0
    for previous, value in zip(values, list(values)[1:], strict=False):
        diff = value - previous
        if abs(diff) <= 1e-9:
            current_direction, current = "stable", 0
            continue
        direction = "increasing" if diff > 0 else "decreasing"
        current = current + 1 if direction == current_direction else 1
        current_direction = direction
        if current > best:
            best, best_direction = current, direction
    return best_direction, best


def _direction_relevant(configured: str, trend_direction: str,
                        indicator_direction: Optional[str]) -> bool:
    if trend_direction == "stable":
        return False
    configured = (configured or "any").lower()
    if configured == "increasing":
        return trend_direction == "increasing"
    if configured == "decreasing":
        return trend_direction == "decreasing"
    if configured == "indicator_specific":
        clinical = (indicator_direction or "").lower()
        if clinical == "lower_is_better":
            return trend_direction == "increasing"
        if clinical == "higher_is_better":
            return trend_direction == "decreasing"
        return True
    return True


def _trend_severity_label(abs_slope_pct: float,
                          bands: Mapping[str, float]) -> str:
    if abs_slope_pct < float(bands.get("stable", 2.0)):
        return "NEGLIGIBLE"
    if abs_slope_pct < float(bands.get("low", 5.0)):
        return "LOW"
    if abs_slope_pct < float(bands.get("moderate", 15.0)):
        return "MODERATE"
    if abs_slope_pct < float(bands.get("high", 30.0)):
        return "HIGH"
    return "CRITICAL"


@dataclass(frozen=True)
class TrendAssessment:
    """Temporal trend result + the evidence that qualified (or did not)."""

    enabled: bool = True
    evaluated: bool = False
    direction: str = "stable"
    direction_relevant: bool = False
    points: int = 0
    months: Tuple[str, ...] = ()
    slope_pct: float = 0.0
    cumulative_change_pct: float = 0.0
    persistence_months: int = 0
    min_persistence: int = 3
    min_cumulative_change_pct: float = 5.0
    r_squared: float = 0.0
    severity: str = LEVEL_NONE
    qualifies: bool = False
    indicator_direction: Optional[str] = None
    skipped_reason: Optional[str] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "evaluated": self.evaluated,
            "direction": self.direction,
            "direction_relevant": self.direction_relevant,
            "points": self.points,
            "months": list(self.months),
            "slope_pct": self.slope_pct,
            "cumulative_change_pct": self.cumulative_change_pct,
            "persistence_months": self.persistence_months,
            "min_persistence": self.min_persistence,
            "min_cumulative_change_pct": self.min_cumulative_change_pct,
            "r_squared": self.r_squared,
            "severity": self.severity,
            "qualifies": self.qualifies,
            "indicator_direction": self.indicator_direction,
            "skipped_reason": self.skipped_reason,
            "reason": self.reason,
        }


def trend_from_dict(data: Optional[Mapping[str, Any]],
                    config: Optional[TrendSettings] = None) -> Optional[TrendAssessment]:
    """Rebuild a stored assessment so a changed policy can be re-evaluated."""
    if not isinstance(data, Mapping) or not data:
        return None
    months = data.get("months") or ()
    assessment = TrendAssessment(
        enabled=bool(data.get("enabled", True)),
        evaluated=bool(data.get("evaluated", False)),
        direction=str(data.get("direction") or "stable"),
        direction_relevant=bool(data.get("direction_relevant", False)),
        points=int(data.get("points") or 0),
        months=tuple(str(m) for m in months),
        slope_pct=float(data.get("slope_pct") or 0.0),
        cumulative_change_pct=float(data.get("cumulative_change_pct") or 0.0),
        persistence_months=int(data.get("persistence_months") or 0),
        min_persistence=int(data.get("min_persistence") or 3),
        min_cumulative_change_pct=float(data.get("min_cumulative_change_pct") or 0.0),
        r_squared=float(data.get("r_squared") or 0.0),
        severity=str(data.get("severity") or LEVEL_NONE),
        qualifies=bool(data.get("qualifies", False)),
        indicator_direction=data.get("indicator_direction"),
        skipped_reason=data.get("skipped_reason"),
        reason=str(data.get("reason") or ""),
    )
    if config is None:
        return assessment
    return evaluate_qualification(assessment, config)


def evaluate_qualification(assessment: TrendAssessment,
                           config: TrendSettings) -> TrendAssessment:
    """Recompute relevance + ``qualifies`` from the stored numbers + settings.

    The direction gate is re-derived (not trusted from storage) so changing
    ``trend_direction`` takes effect for both new scans and the impact preview.
    """
    from dataclasses import replace

    relevant = _direction_relevant(config.trend_direction, assessment.direction,
                                   assessment.indicator_direction)
    qualifies = bool(
        config.enabled
        and assessment.evaluated
        and relevant
        and assessment.persistence_months >= config.min_persistence
        and abs(assessment.cumulative_change_pct) >= config.min_cumulative_change
    )
    reason = assessment.reason
    if not qualifies and assessment.evaluated:
        blockers = []
        if not relevant:
            blockers.append(
                f"direction {assessment.direction!r} does not match the configured "
                f"{config.trend_direction!r} trend direction")
        if assessment.persistence_months < config.min_persistence:
            blockers.append(
                f"persistence {assessment.persistence_months} < required "
                f"{config.min_persistence} months")
        if abs(assessment.cumulative_change_pct) < config.min_cumulative_change:
            blockers.append(
                f"cumulative change {assessment.cumulative_change_pct:+.2f}% < "
                f"required {config.min_cumulative_change:g}%")
        if blockers:
            reason = "Trend does not qualify: " + "; ".join(blockers) + "."
    return replace(assessment, direction_relevant=relevant,
                   qualifies=qualifies, reason=reason)


def assess_trend(values: Sequence[float], months: Optional[Sequence[str]] = None,
                 *, config: Optional[TrendSettings] = None,
                 bands: Optional[Mapping[str, float]] = None,
                 indicator_direction: Optional[str] = None) -> TrendAssessment:
    """Assess one indicator's monthly series under the configured policy.

    Pure function: no database access. The same function is used by the trend
    engine, by Quality Alerts and by the System Control impact preview, so a
    trend can never be judged by two different rule sets.
    """
    cfg = config or resolve_trend_settings({})
    bands = bands or default_trend_bands()
    month_list = tuple(str(m) for m in (months or ()))
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]

    if not cfg.enabled:
        return TrendAssessment(
            enabled=False, min_persistence=cfg.min_persistence,
            min_cumulative_change_pct=cfg.min_cumulative_change,
            months=month_list[:len(clean)],
            skipped_reason="temporal trend assessment is disabled in System Control",
            reason="Temporal trend assessment is disabled; no trend was assessed.",
        )
    if len(clean) < cfg.min_history:
        return TrendAssessment(
            enabled=True, points=len(clean),
            min_persistence=cfg.min_persistence,
            min_cumulative_change_pct=cfg.min_cumulative_change,
            months=month_list[:len(clean)],
            skipped_reason=(
                f"only {len(clean)} usable periods; at least {cfg.min_history} "
                "are required"),
            reason=(
                f"Trend not assessed: {len(clean)} usable period(s) < required "
                f"{cfg.min_history}."),
        )

    mean_value = sum(clean) / len(clean)
    slope, r_squared = _ols(clean)
    slope_pct = (slope / abs(mean_value) * 100.0) if mean_value else 0.0
    stable = float(bands.get("stable", 2.0))
    if abs(slope_pct) < stable:
        direction = "stable"
    else:
        direction = "increasing" if slope > 0 else "decreasing"

    persistence_direction, persistence = persistence_run(clean)
    if persistence_direction != "stable" and persistence_direction != direction:
        persistence = 0
    cumulative = ((clean[-1] - clean[0]) / abs(clean[0]) * 100.0) \
        if clean[0] else 0.0

    relevant = _direction_relevant(cfg.trend_direction, direction,
                                   indicator_direction)
    label = _trend_severity_label(abs(slope_pct), bands)
    severity = normalize_severity(label, source=SOURCE_TEMPORAL_TREND).level

    assessment = TrendAssessment(
        enabled=True,
        evaluated=True,
        direction=direction,
        direction_relevant=relevant,
        indicator_direction=indicator_direction,
        points=len(clean),
        months=month_list[:len(clean)],
        slope_pct=round(slope_pct, 4),
        cumulative_change_pct=round(cumulative, 4),
        persistence_months=persistence,
        min_persistence=cfg.min_persistence,
        min_cumulative_change_pct=cfg.min_cumulative_change,
        r_squared=round(r_squared, 4),
        severity=severity,
        reason=(
            f"{direction.title()} trend over {len(clean)} periods "
            f"({slope_pct:+.2f}%/period, cumulative {cumulative:+.2f}%, "
            f"{persistence} consecutive move(s))."),
    )
    return evaluate_qualification(assessment, cfg)


# ── Severity resolution ────────────────────────────────────────────────────
@dataclass(frozen=True)
class SeverityResolution:
    """base_severity + trend_assessment + final_severity, all auditable."""

    base: SeverityClassification
    trend: Optional[TrendAssessment]
    final: SeverityClassification
    policy: str
    applied: bool
    reason: str
    data_quality: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "base_severity": self.base.as_dict(),
            "trend_assessment": self.trend.as_dict() if self.trend else None,
            "final_severity": self.final.as_dict(),
            "policy": self.policy,
            "applied": self.applied,
            "reason": self.reason,
            "data_quality": ({"completeness": self.data_quality}
                             if self.data_quality is not None else None),
        }


def resolve_severity(base_level: Any, source: str, *,
                     trend: Optional[TrendAssessment] = None,
                     config: Optional[TrendSettings] = None,
                     data_quality: Optional[float] = None) -> SeverityResolution:
    """Apply the configured severity policy to a base classification.

    The base classification is preserved verbatim (plus normalization). The
    final level only differs when ALL of the following hold:

    * a trend was assessed and qualifies under the CURRENT settings,
    * the configured policy is ``escalate`` or ``override``,
    * the base level is at least LOW (a NONE finding is not an issue),
    * the optional data-quality gate is met (when configured).
    """
    cfg = config or resolve_trend_settings({})
    base = normalize_severity(base_level, source=source)
    policy = cfg.policy
    final = base
    applied = False
    reason = (
        f"Final severity equals base severity ({base.level}); trend policy "
        f"{policy!r} did not change it."
    )

    # Re-evaluate the stored assessment against the CURRENT settings so a
    # policy change cannot act on stale qualification flags.
    if trend is not None and trend.evaluated:
        trend = evaluate_qualification(trend, cfg)
    qualified = bool(trend is not None and trend.qualifies)

    if (policy in ("escalate", "override") and qualified
            and LEVEL_RANK[base.level] >= LEVEL_RANK[LEVEL_LOW]):
        gate = cfg.min_completeness
        quality_ok = True
        if gate > 0:
            quality_ok = (data_quality is not None
                          and float(data_quality) >= gate)
            if not quality_ok:
                reason = (
                    f"Trend qualified but data completeness "
                    f"{'unknown' if data_quality is None else f'{float(data_quality):.1f}%'}"
                    f" is below the configured minimum {gate:g}%; severity kept "
                    f"at base {base.level}.")
        if quality_ok:
            if policy == "override":
                target = normalize_severity(cfg.target,
                                            source=SOURCE_SEVERITY_POLICY)
                final = SeverityClassification(
                    level=target.level,
                    engine_level=base.engine_level,
                    source=SOURCE_SEVERITY_POLICY,
                    reason=(f"Configured trend override set final severity to "
                            f"{target.level} (base {base.level})."),
                )
                applied = target.level != base.level
                reason = (
                    f"Trend policy 'override' applied: {base.level} -> "
                    f"{target.level} because a qualifying trend was detected."
                    if applied else
                    f"Trend policy 'override' set {target.level}, which equals "
                    f"the base severity.")
            else:
                raised = raise_level(base.level, cfg.escalation)
                final = SeverityClassification(
                    level=raised,
                    engine_level=base.engine_level,
                    source=SOURCE_SEVERITY_POLICY,
                    reason=(f"Temporal trend escalated severity by "
                            f"{cfg.escalation} band(s): {base.level} -> {raised}."),
                )
                applied = raised != base.level
                reason = (
                    f"Trend policy 'escalate' applied {cfg.escalation} band(s): "
                    f"{base.level} -> {raised}."
                    if applied else
                    f"Trend qualified but base severity {base.level} is already "
                    "at the top band; final severity unchanged.")

    return SeverityResolution(base=base, trend=trend, final=final,
                              policy=policy, applied=applied, reason=reason,
                              data_quality=data_quality)


def legacy_resolution(level: Any, *, source: str = SOURCE_LEGACY) -> SeverityResolution:
    """Resolution for rows persisted before severity provenance was stored."""
    base = try_normalize_severity(level, source=source)
    if base is None:
        base = SeverityClassification(
            level=LEVEL_NONE, engine_level=str(level or ""), source=source,
            reason=f"Stored severity {level!r} is not on the canonical scale.")
    return SeverityResolution(
        base=base, trend=None,
        final=SeverityClassification(
            level=base.level, engine_level=base.engine_level, source=source,
            reason="Stored before base/final severity was persisted; "
                   "final equals stored severity."),
        policy="legacy", applied=False,
        reason="Legacy row: no stored trend assessment or severity policy.",
    )
