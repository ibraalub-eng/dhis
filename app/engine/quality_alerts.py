"""Quality Alerts detection engine (design 2026-10-21).

Centralized risk monitoring over the Indicators Registry. This module never
defines a clinical formula of its own: every indicator value comes from
``indicator_service.calculate_from_values`` over the *enabled* raw values the
rest of the app uses (pipeline.get_* helpers), and every rate's numerator /
denominator / multiplier lives in the registry (IndicatorDefinition /
rate_config). What this module adds is COMPARISON and INTERPRETATION:

* perspectives — hospital history, hospital type, ownership, facility type,
  governorate (region) and all-hospital, each evaluated independently so a
  single hospital+indicator can carry several distinct pieces of evidence;
* scoring — reuses the layered engine's band cutoffs and score builders
  (``score_from_z``, ``select_method``/``_score_window``) so alert severity
  agrees with the Outlier Diagnostics screen;
* clinical interpretation — statistical outlier status is NEVER relabelled
  harmful: direction metadata (``IndicatorDefinition.direction`` / clinical
  threshold ``higher_is_worse``) decides whether a HIGH value is favourable,
  concerning, outside a target range, or purely statistical.

Safeguards (spec §9): non-ok calculations are excluded from baselines, peer
groups need >= ``alerts_min_peers`` other hospitals, history needs >=
``alerts_min_history`` valid months, small peer groups are flagged
low-confidence, and an optional Isolation-Forest cross-check (existing
sklearn method, only when enough samples) can downgrade confidence.

Persistence: one QualityAlert row per (hospital, indicator, month,
perspective). Rescans upsert; reviewed findings that disappear are deactivated
(kept for audit), never silently deleted. The API groups rows into one risk
issue per (hospital, indicator, month) showing every perspective that fired.

Coverage: ALL catalog kinds get the same search — registered rate specs AND
derivative definitions (both resolve from IndicatorDefinition, so a
non-system derived formula receives the same peer/history evidence) plus raw
DATA ELEMENTS, whose stored value is read as-is: a data element has no
formula and none is invented for it (spec §10). The per-element
``historical_enabled`` / ``peer_comparison_enabled`` toggles are honored for
data elements exactly as the layered engine honors them.
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config_utils import get_config_dict
from app.engine import (
    canonical_identity,
    comparison_policy,
    indicator_service,
)
from app.engine.config_resolver import (
    PolicySnapshot,
    PolicyUnavailable,
    load_policy_snapshot,
)
from app.engine.policy_view import (
    alerts_config_from_snapshot,
    analysis_config_from_snapshot,
    comparison_policy_from_snapshot,
)
from app.engine import (
    severity as severity_policy,
)
from app.engine.anomaly import layered
from app.engine.pipeline import (
    get_all_hospital_data_for_month,
    get_enabled_values_for_hospital_month,
    get_historical_months,
)
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.models import (
    QUALITY_ALERT_STATUSES,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
    QualityAlertEvent,
)

logger = logging.getLogger(__name__)

# ── Perspective registry ────────────────────────────────────────────────────
# Only perspectives backed by REAL hospital metadata exist here — no invented
# categories. "governance" (managing authority) is deliberately absent: the
# schema has no such column and ownership must never be assumed interchangeable
# with it. The API reports it as unavailable with that reason.
PERSPECTIVE_HISTORY = "history"
PERSPECTIVE_TYPE = "type"
PERSPECTIVE_OWNERSHIP = "ownership"
PERSPECTIVE_FACILITY_TYPE = "facility_type"
PERSPECTIVE_GOVERNORATE = "governorate"
PERSPECTIVE_ALL = "all"

PEER_PERSPECTIVES: Tuple[Tuple[str, str, str], ...] = (
    # (perspective key, Hospital attribute, English label)
    (PERSPECTIVE_TYPE, "hospital_type_id", "Same hospital type"),
    (PERSPECTIVE_OWNERSHIP, "facility_ownership_id", "Same ownership"),
    (PERSPECTIVE_FACILITY_TYPE, "facility_type_id", "Same facility type"),
    (PERSPECTIVE_GOVERNORATE, "governorate_id", "Same governorate (region)"),
    (PERSPECTIVE_ALL, None, "All hospitals"),
)

PERSPECTIVE_LABELS = {
    PERSPECTIVE_HISTORY: "Hospital history",
    PERSPECTIVE_TYPE: "Similar hospitals (type)",
    PERSPECTIVE_OWNERSHIP: "Ownership peers",
    PERSPECTIVE_FACILITY_TYPE: "Facility-type peers",
    PERSPECTIVE_GOVERNORATE: "Regional peers (governorate)",
    PERSPECTIVE_ALL: "All hospitals",
}

# Interpretation labels — the clinical-direction vocabulary the UI shows.
INTERP_HIGH_CONCERN = "high_is_concern"
INTERP_HIGH_FAVORABLE = "high_is_favorable"
INTERP_LOW_CONCERN = "low_is_concern"
INTERP_LOW_FAVORABLE = "low_is_favorable"
INTERP_OUTSIDE_TARGET = "outside_target_range"
INTERP_WITHIN_TARGET = "within_target_range"
INTERP_STATISTICAL_ONLY = "statistical_only"

STATUS_NEW = "New"
STATUS_UNDER_REVIEW = "Under Review"
STATUS_CONFIRMED = "Confirmed Issue"
STATUS_FALSE_POSITIVE = "False Positive"
STATUS_RESOLVED = "Resolved"

# Issue-level status rollup priority (first present wins).
_STATUS_ROLLUP = (STATUS_CONFIRMED, STATUS_UNDER_REVIEW, STATUS_NEW,
                  STATUS_FALSE_POSITIVE, STATUS_RESOLVED)
_STATUS_PRIORITY = {status: rank for rank, status in enumerate(_STATUS_ROLLUP)}

# ── Open vs closed investigation state ────────────────────────────────────
# A reviewer CLOSES an alert by marking it Resolved (the finding was dealt with)
# or False Positive (it was skipped: the deviation is not a real issue).
# Closing is a decision about ALERTING, not about storage: the row keeps its
# statistics, its ``active`` flag (which only says "the scan still detects this
# finding") and its whole event trail. What changes is presentation — every open
# view (the Quality Alerts list and KPIs, the dashboard cards, the stale
# recompute) stops raising it, and it reappears only when someone asks for that
# status explicitly. Otherwise a closed alert would keep alerting forever, with
# nothing but a coloured badge to tell the reader it was already dealt with.
CLOSED_STATUSES = (STATUS_RESOLVED, STATUS_FALSE_POSITIVE)


def is_open_status(status: Optional[str]) -> bool:
    """True while an alert still needs attention (not Resolved / skipped)."""
    return status not in CLOSED_STATUSES


def _alerts_config(db: Session) -> dict:
    """Configurable knobs (AppConfig category ``alerts`` + shared z threshold).

    All meanings are documented in the seeded config labels:
    * alerts_min_score    — smallest 0-1 score that raises an alert
                            (default 0.5 = the MODERATE band boundary).
    * alerts_min_peers    — other hospitals required for a peer baseline.
    * alerts_min_history  — valid prior months required for the history baseline.
    * alerts_history_window — how many prior months the baseline may span.
    * alerts_ml_enabled   — 1 to run the Isolation-Forest cross-check.
    * alerts_ml_min_samples — hospitals required before ML is meaningful.
    * zscore_threshold (thresholds category, shared) — z anchor for scoring.
    """
    alerts_cfg = get_config_dict(db, "alerts")
    thresholds_cfg = get_config_dict(db, "thresholds")

    def _f(key: str, default: float) -> float:
        try:
            return float(alerts_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _i(key: str, default: int) -> int:
        return int(_f(key, float(default)))

    try:
        z_threshold = float(thresholds_cfg.get("zscore_threshold", 2.5))
    except (TypeError, ValueError):
        z_threshold = 2.5
    if z_threshold <= 0:
        z_threshold = 2.5
    # Window/minimums come from the shared comparison policy, not from a
    # second copy of the clamping rules. The scan later replaces them with a
    # policy that also honours the System Control trend window.
    policy = comparison_policy.resolve_comparison_policy(alerts_cfg)
    return {
        "min_score": _f("alerts_min_score", 0.5),
        "min_peers": policy.peer.min_peers,
        "min_history": policy.history.min_observations,
        "history_window": policy.history.window,
        "ml_enabled": _i("alerts_ml_enabled", 1) == 1,
        "ml_min_samples": max(4, _i("alerts_ml_min_samples", 12)),
        "z_threshold": z_threshold,
    }


# ── Registry resolution ─────────────────────────────────────────────────────

@dataclass
class AlertCandidate:
    """One authoritative indicator value for one hospital/month."""
    resolved: object
    value: Optional[float]
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    status: str = "no_data"


def resolve_registry(db: Session) -> List[object]:
    """Every active definition in the Indicators Registry (shared + sites).

    This is the same resolution the pipeline and outlier screens use — the
    Alerts module analyses ONLY registered indicators, never raw ad-hoc math.
    Readers that resolve a STORED code (detail, trend, peer groups) use this so
    a historical row on an alias code stays renderable.
    """
    return indicator_service.resolve_active_definitions(db)


def resolve_canonical_registry(db: Session) -> List[object]:
    """Every active LOGICAL formula once — the scan's candidate set.

    The registry holds one row per analysis site, and those rows can carry an
    identical formula (the per-site C-section copies). They compute the same
    number, so scanning both would raise the same clinical finding twice and
    inflate every dashboard total. Each canonical identity is scanned once; the
    equivalent codes travel with the finding in ``evidence["canonical"]`` so it
    stays traceable to every registration.
    """
    return indicator_service.canonical_formulas(db)


def canonical_code_index(db: Session) -> Dict[str, dict]:
    """code -> canonical identity, for every registry code (active or not).

    Read side only: stored alerts may predate canonical scanning and still
    carry an alias code. They must be grouped under the canonical identity (a
    single unique issue) rather than counted again — and an inactive alias must
    keep resolving, because its historical findings are still on record.
    """
    return indicator_service.canonical_code_index(db)


def canonical_formula_index(db: Session) -> Dict[str, dict]:
    """identity key -> canonical registration, for naming stored findings.

    Readers group rows by the formula each row carries; this index only names
    the representative code and every equivalent registration. A key the
    registry no longer holds (formula edited since the scan) misses on purpose:
    the row keeps the code it was written with.
    """
    return indicator_service.canonical_formula_index(db)


def _calculate(resolved, values: Dict[str, float], hospital_id: int,
               month: str) -> AlertCandidate:
    result = indicator_service.calculate_from_values(
        resolved, values, hospital_id=hospital_id, month=month)
    return AlertCandidate(
        resolved=resolved,
        value=result.value if result.status == "ok" else None,
        numerator=getattr(result, "numerator", None),
        denominator=getattr(result, "denominator", None),
        status=result.status,
    )


# ── Data Elements (raw catalog) ─────────────────────────────────────────────

@dataclass
class RawElementRef:
    """A catalog Data Element evaluated as-is (no formula exists for it).

    Its authoritative value for a (hospital, month) IS the stored enabled
    value — read, never recomputed. The per-element toggles mirror the
    layered engine's ``historical_enabled`` / ``peer_comparison_enabled``
    semantics so both screens agree on which comparisons an element may
    take part in.
    """
    code: str
    name: str
    indicator_type: Optional[str] = "count"
    unit: Optional[str] = None          # the raw catalog has no unit column
    formula: Optional[str] = None
    definition: Optional[object] = None  # no registry definition row
    is_raw: bool = True
    historical_enabled: bool = True
    peer_comparison_enabled: bool = True
    minimum_history_period: int = comparison_policy.MIN_HISTORY_OBSERVATIONS_DEFAULT
    outlier_method: str = "auto"


def resolve_data_elements(db: Session) -> List[RawElementRef]:
    """Every catalog Data Element (raw, uploaded indicators).

    Only the synthetic form-header code is excluded (it is a label, not a
    value). An element with no stored values simply produces no candidates —
    the scan's existing safeguards handle the rest.
    """
    rows = (db.query(Indicator)
            .filter(~Indicator.code.in_(SYNTHETIC_INDICATOR_CODES))
            .order_by(Indicator.sort_order, Indicator.code)
            .all())
    return [
        RawElementRef(
            code=row.code, name=row.name,
            indicator_type=row.indicator_type or "count",
            historical_enabled=row.historical_enabled is not False,
            peer_comparison_enabled=row.peer_comparison_enabled is not False,
            minimum_history_period=(row.minimum_history_period
                                    or comparison_policy.MIN_HISTORY_OBSERVATIONS_DEFAULT),
            outlier_method=(row.outlier_method or "auto"),
        )
        for row in rows
    ]


def _candidate(resolved, values: Dict[str, float], hospital_id: int,
               month: str) -> AlertCandidate:
    """Authoritative value for one (registered indicator | data element).

    Registered indicators go through the shared calculation engine; raw data
    elements are stored values and are read as-is (they have no formula and
    none may be invented for them — spec §10).
    """
    if getattr(resolved, "is_raw", False):
        raw = values.get(resolved.code)
        if raw is None:
            return AlertCandidate(resolved=resolved, value=None, status="no_data")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return AlertCandidate(resolved=resolved, value=None, status="invalid")
        if not math.isfinite(value):
            return AlertCandidate(resolved=resolved, value=None, status="invalid")
        return AlertCandidate(resolved=resolved, value=value, status="ok")
    return _calculate(resolved, values, hospital_id, month)


# ── Direction / clinical interpretation ─────────────────────────────────────

def resolve_direction(db: Session, resolved) -> Tuple[str, Optional[float], Optional[float]]:
    """(direction, target_min, target_max) for an indicator — metadata only.

    Order: the definition's own configured direction (user-set in the
    Indicators screen) wins; else the clinical threshold table's
    ``higher_is_worse`` for the matching registry code (existing configured
    clinical interpretation rules); else "none" (statistical only).
    """
    definition = getattr(resolved, "definition", None)
    if definition is not None:
        direction = (getattr(definition, "direction", None) or "").strip()
        if direction and direction != "none":
            return direction, getattr(definition, "target_min", None), getattr(definition, "target_max", None)
    code = getattr(resolved, "code", None)
    if code:
        try:
            from app.engine.clinical.thresholds import get_threshold
            threshold = get_threshold(code)
            if threshold is not None and threshold.higher_is_worse is not None:
                direction = "lower_is_better" if threshold.higher_is_worse else "higher_is_better"
                return direction, None, None
        except Exception:  # pragma: no cover - threshold table optional
            pass
    return "none", None, None


def interpret_deviation(direction: str, value: Optional[float],
                        baseline: Optional[float],
                        target_min: Optional[float] = None,
                        target_max: Optional[float] = None) -> str:
    """Map (direction, deviation sign) to the interpretation label.

    Statistical outlier status is preserved either way — this only decides
    whether HIGH is good news or a review trigger. Never claims harm from
    magnitude alone.
    """
    if value is None or baseline is None:
        return INTERP_STATISTICAL_ONLY
    high = value >= baseline
    if direction == "target_range":
        if target_max is not None and value > target_max:
            return INTERP_OUTSIDE_TARGET
        if target_min is not None and value < target_min:
            return INTERP_OUTSIDE_TARGET
        return INTERP_WITHIN_TARGET
    if direction == "higher_is_better":
        return INTERP_HIGH_FAVORABLE if high else INTERP_LOW_CONCERN
    if direction == "lower_is_better":
        return INTERP_HIGH_CONCERN if high else INTERP_LOW_FAVORABLE
    return INTERP_STATISTICAL_ONLY


# ── Peer helpers ────────────────────────────────────────────────────────────

def _hospital_directory(db: Session) -> Dict[int, Hospital]:
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    return {h.id: h for h in hospitals}


def _rate_analysis_settings(db: Session) -> Dict[str, dict]:
    """Per-formula analysis settings from the rate configuration.

    Diagnostics builds its spec from ``rate_config`` (method, minimum history,
    history/peer toggles); the registry definition of the same formula is what
    Alerts scans. Keying the settings by the shared canonical identity lets
    both engines apply the same per-formula choices without either inventing
    its own.
    """
    from app.engine.rate_config import load_rate_specs

    index: Dict[str, dict] = {}
    for spec in load_rate_specs(db).values():
        key = canonical_identity.identity_key(
            canonical_identity.ratio_identity(
                spec.numerator_codes, spec.denominator_codes, "/",
                spec.rate_multiplier, spec.unit))
        index.setdefault(key, {
            "minimum_history_period": spec.minimum_history_period,
            "outlier_method": spec.outlier_method or "auto",
            "historical_enabled": spec.historical_enabled is not False,
            "peer_comparison_enabled": spec.peer_comparison_enabled is not False,
            "source": "rate_config",
        })
    return index


def _item_comparison_settings(resolved, rate_index: Dict[str, dict],
                              policy: comparison_policy.ComparisonPolicy) -> dict:
    """Effective window/method/toggles for one scanned indicator.

    Raw elements and resolved rate specs carry their own columns; a registry
    definition without those columns inherits the settings of the rate_config
    row with the same canonical formula. Anything unmatched uses the approved
    system defaults — never a hidden per-engine override.
    """
    defaults = {
        "minimum_history_period": policy.history.min_observations,
        "outlier_method": "auto",
        "historical_enabled": True,
        "peer_comparison_enabled": True,
        "source": "comparison_policy",
    }
    spec = getattr(resolved, "spec", None)
    if spec is not None:
        return {
            "minimum_history_period": spec.minimum_history_period,
            "outlier_method": spec.outlier_method or "auto",
            "historical_enabled": spec.historical_enabled is not False,
            "peer_comparison_enabled": spec.peer_comparison_enabled is not False,
            "source": "rate_config",
        }
    if getattr(resolved, "is_raw", False):
        return {
            "minimum_history_period": (resolved.minimum_history_period
                                       or policy.history.min_observations),
            "outlier_method": resolved.outlier_method or "auto",
            "historical_enabled": resolved.historical_enabled is not False,
            "peer_comparison_enabled": resolved.peer_comparison_enabled is not False,
            "source": "indicator",
        }
    key = canonical_identity.identity_key(
        canonical_identity.resolved_identity(resolved))
    return dict(rate_index.get(key, defaults))


def _peer_members(directory: Dict[int, Hospital], self_id: int,
                  attribute: Optional[str],
                  values: Dict[int, Optional[float]]) -> List[Tuple[int, float]]:
    """Other hospitals in the perspective with a valid value, (id, value)."""
    members = []
    self_hosp = directory.get(self_id)
    for hid, value in values.items():
        if hid == self_id or value is None or not math.isfinite(float(value)):
            continue
        if attribute is not None:
            if self_hosp is None:
                continue
            if getattr(directory.get(hid), attribute, None) != getattr(self_hosp, attribute, None):
                continue
            if getattr(self_hosp, attribute, None) is None:
                continue  # hospital lacks the metadata: perspective not applicable
        members.append((hid, float(value)))
    return members


# ── Scoring (reuses layered engine building blocks) ─────────────────────────

def _peer_score(current: float, member_values: Sequence[float],
                z_threshold: float) -> Tuple[Optional[float], Optional[float], dict]:
    """z-score against peer mean (self excluded) + layered score + stats.

    A group too small to measure a spread is still SCORED — the deviation is
    real evidence — but produces no z-score (``layered.PEER_Z_POLICY``): the z
    divides by the group's own spread, and 2-3 hospitals cannot measure one.
    ``stats["z_provenance"]`` records that, so the screen explains the dash
    instead of leaving it to guesswork. Identical to the Diagnostics peer
    layer, which stores the same NULL z for the same group.
    """
    import statistics

    stats = {
        "mean": None, "std": None, "median": None,
        "min": None, "max": None,
    }
    if len(member_values) < 2:
        return None, None, stats
    mean = statistics.fmean(member_values)
    std = statistics.stdev(member_values)  # ddof=1, same as layered peer layer
    stats.update(mean=mean, std=std, median=statistics.median(member_values),
                 min=min(member_values), max=max(member_values))
    if std == 0:
        z = 0.0 if current == mean else None
        score = 0.0 if current == mean else 1.0
    else:
        graded_z = (current - mean) / std
        score = layered.score_from_z(graded_z, z_threshold)
        z = (graded_z if layered.peer_z_measurable(len(member_values))
             else None)
    stats["z_provenance"] = layered.peer_z_provenance(len(member_values))
    return z, score, stats


# ── Degenerate comparisons (no dispersion) ─────────────────────────────────
# A comparison whose values are all identical has no scale: the z-score is
# undefined (0/0) and the relative deviation is undefined (baseline 0 or a
# flat baseline). The shared score builders answer such a comparison with
# 1.0 — "maximal deviation" — which is the right RAW evidence signal (the
# hospital really is the only one off the level) but not a measurable
# magnitude. Every hospital that is the only one reporting a rare event
# therefore used to land in the top band: in the live database 889 stored
# alerts (24% of all VERY_HIGH) had a baseline of exactly 0, score 1.0 and no
# z-score. Such findings are KEPT — "only this hospital reports it" is
# evidence — but their level is capped at HIGH, and the row records the cap
# (``evidence["dispersion"]``) so the screens explain it instead of quoting a
# graded maximum. Measured deviations (spread > 0) are untouched, so the
# existing thresholds still decide every non-degenerate comparison.
# The policy itself lives in the shared engine module (layered.cap_zero_spread)
# because Outlier Diagnostics applies the same cap to its own bands; these are
# thin adapters over a stats dict so the alert and diagnostic rows carry the
# identical provenance shape.
ZERO_SPREAD_LEVEL_CAP = layered.ZERO_SPREAD_LEVEL_CAP
ZERO_SPREAD_POLICY = layered.ZERO_SPREAD_POLICY


def stored_threshold(evidence: Optional[dict]) -> Optional[float]:
    """The z threshold the scan STORED on this row, if it recorded one.

    ``evidence["z_threshold"]`` is the value the scan actually scored with, so
    a row is judged with its own threshold rather than today's setting; a row
    written before it was recorded returns ``None`` and the caller falls back
    to the configured value (``layered.gate_threshold``).
    """
    raw = (evidence or {}).get("z_threshold")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def stored_series(evidence: Optional[dict]) -> List[float]:
    """The comparison window a stored alert was scored against.

    ``evidence["history"]`` is the exact series handed to the scorer at scan
    time, so a robust method's divisor (MAD / IQR) can be recomputed from it
    for rows written before those divisors were stored.
    """
    out: List[float] = []
    for item in (evidence or {}).get("history") or ():
        if isinstance(item, (list, tuple)) and len(item) == 2:
            value = item[1]
            if value is None:
                continue
            try:
                out.append(float(value))
            except (TypeError, ValueError):
                continue
    return out


def peer_definition_codes(db: Session) -> set:
    """The analysis codes the PEER definition gate can resolve from the catalog.

    Deliberately ``layered.build_analysis_specs``: the catalog the SCAN itself
    covers — registered indicators plus active derived rates. A synthetic
    forecast indicator is absent from it, so a comparison resting on one stays
    ``not_establishable`` instead of being "resolved" by a lookup the scan never
    graded. (A formula identity is NOT a definition: the canonical evidence
    block is written on every alert, so keying on it would silently define rows
    the catalog does not analyse.)
    """
    from app.engine.anomaly.layered import build_analysis_specs

    return {spec.analysis_code for spec in build_analysis_specs(db)}


def stored_peer_group(evidence: Optional[dict]) -> dict:
    """The peer group a STORED alert recorded: hospital id -> value.

    The scan writes the exact members that produced the row's peer score to
    ``evidence["comparison_policy"]["peer"]["values"]`` (the focal hospital is
    not one of them), so the peer policy is judged on the group the finding was
    created from rather than on a recomputed one. A row written before that
    block existed returns an empty dict; nothing is inferred.

    The stored values carry 4 decimals (the scan rounds them), which is the
    documented tolerance of this read path — the group membership and the
    original z-score are never re-derived from them.
    """
    block = ((evidence or {}).get("comparison_policy") or {}).get("peer")
    values = block.get("values") if isinstance(block, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def alert_peer_definition(alert, catalog_codes=None) -> dict:
    """One stored alert's own definition evidence.

    Shape expected by ``layered.peer_definition_status``. The formula and the
    ratio come from the ROW (the definition the finding was computed with); the
    catalog only supplements it, through ``catalog_codes`` — and a row that
    leans on the catalog is marked ``catalog_only``, never reported as verified
    group-wide comparability.
    """
    evidence = getattr(alert, "evidence", None) or {}
    canonical = evidence.get("canonical") or {}
    codes = [canonical.get("code"), getattr(alert, "indicator_code", None)]
    codes += list(canonical.get("registered_codes") or ())
    resolved = {str(code) for code in (catalog_codes or ()) if code}
    return {
        "formula": (getattr(alert, "formula", None)
                    or canonical.get("formula")),
        "numerator": evidence.get("numerator"),
        "denominator": evidence.get("denominator"),
        "catalog_resolved": any(str(code) in resolved for code in codes if code),
    }


def peer_gate_inputs(alert, catalog_codes=None) -> dict:
    """``top_band_gate`` keyword arguments for one stored alert's peer evidence.

    Empty for any route that is not ``peer``: a history, volume or raw-count
    claim must never be judged by the peer policy, even when the row happens to
    carry a peer block beside it.
    """
    route = alert_route(getattr(alert, "perspective", None),
                        getattr(alert, "method", None))
    if route != layered.ROUTE_PEER:
        return {}
    values = stored_peer_group(getattr(alert, "evidence", None))
    if not values:
        # No stored group: a row written before the peer evidence existed keeps
        # exactly the answer it had (``undecided`` / ``PEER_POLICY``). Supplying
        # an empty group instead would restate it as ``NO_STORED_PEER_VALUES``,
        # which is a different claim about the SAME missing evidence.
        return {}
    return {
        "peer_values": values,
        "peer_definition": alert_peer_definition(alert, catalog_codes),
    }


def _stored_spread(stats: Optional[dict], method: Optional[str],
                   series: Optional[Sequence[float]] = None
                   ) -> Tuple[Optional[float], str]:
    """``(divisor, kind)`` for one STORED comparison, or ``(None, "std")``.

    The no-dispersion cap must test the spread the score divided by: a
    ``rolling_median_mad`` row divides by MAD and an ``iqr`` row by the IQR,
    either of which can be 0 while the window's std is not. Rows written
    before those divisors were recorded recompute them from the stored history
    series; when neither is available the std-only test still applies.
    """
    stats = stats or {}
    values = [float(v) for v in (series or ()) if v is not None]
    if method == layered.METHOD_ROLLING_MEDIAN_MAD:
        if stats.get("mad") is not None:
            return float(stats["mad"]), "mad"
        return (layered.mad(values), "mad") if values else (None, "std")
    if method == layered.METHOD_IQR:
        if stats.get("iqr") is not None:
            return float(stats["iqr"]), "iqr"
        if len(values) >= 2:
            q1, _q2, q3 = layered.quartiles(values)
            return q3 - q1, "iqr"
        return None, "std"
    if method == layered.METHOD_TREND_DEVIATION:
        if stats.get("residual_std") is not None:
            return float(stats["residual_std"]), "residual_std"
        return None, "std"
    if stats.get("std") is not None:
        return float(stats["std"]), "std"
    return None, "std"


def zero_spread(stats: Optional[dict], method: Optional[str] = None,
                series: Optional[Sequence[float]] = None) -> bool:
    """True when a dispersion-based comparison had no dispersion.

    ``method`` narrows the check to the methods whose score divides by the
    spread; ``series`` lets a robust method's divisor be recomputed from the
    window it was scored against. Without either only the stored statistics
    are inspected (used where the method is not available).
    """
    spread, kind = _stored_spread(stats, method, series)
    return layered.zero_dispersion((stats or {}).get("std"), method,
                                   spread=spread, spread_kind=kind)


def cap_zero_spread(severity: str, stats: Optional[dict],
                    method: Optional[str] = None,
                    series: Optional[Sequence[float]] = None
                    ) -> Tuple[str, Optional[dict]]:
    """Apply the documented no-dispersion cap to a resolved severity band.

    Returns ``(level, provenance)``; provenance is ``None`` when the
    comparison had real spread (nothing was capped). The cap never lowers a
    level below the configured thresholds for a degenerate comparison — it
    only stops an unmeasurable comparison from claiming the top band.
    """
    spread, kind = _stored_spread(stats, method, series)
    return layered.cap_zero_spread(severity, (stats or {}).get("std"), method,
                                   spread=spread, spread_kind=kind)


# A comparison group below this size is reported as low confidence. For a PEER
# perspective the same boundary also caps the BAND at HIGH: a z-score divides
# by the group's own spread, and 2-3 other hospitals cannot measure one (stored
# rows carried |z| = 224 from a 2-peer group). The finding, its score, its z
# and its peer list are untouched — only the top band is refused.
SMALL_COMPARISON_GROUP = layered.MIN_PEERS_FOR_TOP_BAND
THIN_PEER_LEVEL_CAP = layered.THIN_PEER_LEVEL_CAP


def cap_thin_peer(severity: str, peer_count: Optional[int],
                  method: Optional[str] = None
                  ) -> Tuple[str, Optional[dict]]:
    """Apply the documented thin-peer-group cap to a resolved severity band.

    Returns ``(level, provenance)``; provenance is ``None`` when the group is
    large enough (nothing was capped). Only peer comparisons are affected:
    the history perspective stores the number of baseline MONTHS in
    ``peer_count``, which is governed by the history-observation minimum.
    """
    return layered.cap_thin_peer(severity, peer_count, method)


PERSPECTIVE_HISTORY = "history"


def _peer_definition_tier(peer_definition) -> str:
    """The definition tier for one peer alert.

    Accepts the evidence itself (``formula`` / ``numerator`` / ``denominator`` /
    ``catalog_resolved``), an already-resolved tier, or nothing — and nothing
    means NOT establishable, because the approved policy requires a definition
    to be shown before a comparison can be graded.
    """
    if isinstance(peer_definition, str) and peer_definition.strip():
        return peer_definition.strip()
    if isinstance(peer_definition, Mapping):
        return layered.peer_definition_status(**peer_definition)
    return layered.PEER_DEFINITION_NOT_ESTABLISHABLE


def alert_route(perspective: Optional[str], method: Optional[str]) -> str:
    """Which rule judges a STORED alert's top band.

    An alert row scores ONE labelled perspective: ``history`` is the hospital's
    own months, every other label (``all``, ``type``, ``ownership``,
    ``facility_type``, ``governorate``) is a comparison against other
    hospitals. Only the history perspective is judged by the top-band gate; a
    peer perspective keeps the two approved peer policies that already decide
    it.

    Rows written before the perspective was read alongside the band are routed
    by their method instead — a ``peer_zscore`` row is a peer comparison, every
    other method scores the hospital's own window — which is the same narrowing
    ``cap_thin_peer`` already applies.
    """
    if perspective:
        return (layered.ROUTE_HISTORY if perspective == PERSPECTIVE_HISTORY
                else layered.ROUTE_PEER)
    if method == layered.METHOD_PEER_ZSCORE:
        return layered.ROUTE_PEER
    return layered.ROUTE_HISTORY


def top_band_gate(level: Optional[str], *, method: Optional[str] = None,
                  perspective: Optional[str] = None,
                  series: Optional[Sequence[float]] = None,
                  current: Optional[float] = None,
                  threshold: Optional[float] = None,
                  peer_values: Optional[Mapping] = None,
                  peer_definition=None,
                  denominator_review: bool = False
                  ) -> Tuple[Optional[str], Optional[dict], dict]:
    """The top-band eligibility gate for one STORED alert row.

    Returns ``(level, provenance, assessment)``: ``provenance`` is ``None`` when
    nothing was refused, and ``assessment`` always states the routed verdict
    (``decision`` is one of ``eligible`` / ``ineligible`` / ``undecided`` /
    ``not_applicable``, plus the peer-only ``insufficient_robust_scale``) so a
    reader can name WHY a top band was or was not judged instead of guessing.

    A HISTORY row with no window or no current value is ``undecided`` — an
    absent measurement is not a refusal.

    A PEER perspective is judged by the approved peer policy (Rule B) once the
    caller supplies the stored peer group in ``peer_values``. ``peer_definition``
    is that row's definition evidence (a mapping for
    :func:`layered.peer_definition_status`, or an already-resolved tier) and is
    applied BEFORE any scale: a comparison whose indicator definition cannot be
    established is ``undecided``, never eligible. With no definition evidence a
    row is treated as not establishable, because an unproven definition must not
    read as a verified one.

    Rule B NEVER changes the band: ``level`` is returned exactly as passed in
    whichever way a peer row is judged, and ``provenance`` is ``None`` (nothing
    was capped), so no reader starts showing a different severity. Callers that
    pass no peer evidence keep the previous answer verbatim — ``undecided`` with
    the peer-policy reason.
    """
    route = alert_route(perspective, method)
    assessment = {
        "route": route,
        "decision": layered.DECISION_NOT_APPLICABLE,
        "applicable": False,
        "eligible": None,
        "reason": layered.NOT_APPLICABLE,
        "original_band": level,
        "final_band": level,
        "history_window": len(list(series or ())),
        "current": current,
        "policy": layered.TOP_BAND_ROUTE_POLICY.get(route, ""),
    }
    if (level is None
            or layered.LEVEL_RANK.get(level, 0)
            < layered.LEVEL_RANK[layered.LEVEL_VERY_HIGH]):
        return level, None, assessment
    if route == layered.ROUTE_PEER and peer_values is not None:
        # The definition gate runs first, then Rule B on the peer group's own
        # robust scales. Both are read-only: the stored band, score and
        # evidence are untouched, and the band cannot move.
        definition_status = _peer_definition_tier(peer_definition)
        verdict = layered.peer_very_high_eligibility(
            level, peer_values, current,
            definition_status=definition_status,
            threshold=threshold,
            denominator_review=denominator_review)
        assessment.update({
            "decision": verdict["decision"],
            "reason": verdict["reason"],
            "applicable": verdict["applicable"],
            "eligible": verdict["eligible"],
            "policy": verdict["policy"],
            "threshold": verdict["threshold"],
            "final_band": level,          # Rule B never moves the band
            "definition_status": verdict["definition_status"],
            "group_comparability_status": verdict["group_comparability_status"],
            "zero_share": verdict["zero_share"],
            "zero_share_warning": verdict["zero_share_warning"],
            "denominator_review": verdict["denominator_review"],
            "peer_eligibility": verdict,
        })
        return level, None, assessment
    if route != layered.ROUTE_HISTORY:
        assessment["decision"] = layered.DECISION_UNDECIDED
        assessment["reason"] = layered.ROUTE_PEER.upper() + "_POLICY"
        return level, None, assessment
    used = layered.gate_threshold(threshold)
    assessment["threshold"] = used
    # ONE assessment, measured once: the band and its provenance are both read
    # from it, so the dispersion is no longer computed twice for one row.
    eligible = layered.very_high_eligibility(
        level, list(series or ()), current, used)
    provenance = layered.eligibility_provenance(eligible)
    gated = eligible["final_band"]
    assessment.update({
        "applicable": eligible["applicable"],
        "eligible": eligible["eligible"],
        "reason": eligible["reason"],
        "assessment": eligible,
        "final_band": gated,
        "policy": eligible["policy"],
        "decision": (layered.DECISION_ELIGIBLE if eligible["eligible"]
                     else layered.DECISION_INELIGIBLE
                     if eligible["eligible"] is False
                     else layered.DECISION_UNDECIDED),
    })
    if eligible["applicable"] and eligible["eligible"] is None:
        # Say whether the window or the value was the missing input.
        assessment["reason"] = (layered.REASON_NO_WINDOW
                                if not list(series or ())
                                else layered.REASON_NO_CURRENT)
    return gated, provenance, assessment


def effective_severity(severity: Optional[str], *, stats: Optional[dict] = None,
                       method: Optional[str] = None,
                       peer_count: Optional[int] = None,
                       series: Optional[Sequence[float]] = None,
                       current: Optional[float] = None,
                       perspective: Optional[str] = None,
                       threshold: Optional[float] = None) -> Optional[str]:
    """The band the APPROVED policy assigns to a stored comparison result.

    The scan applies both caps when it WRITES a row (a comparison with no
    dispersion, and a peer group too small to measure a spread). Rows written
    before a cap was approved still carry the uncapped band, but both caps are
    derivable from the row's own stored evidence — counting the stored band
    instead kept reporting findings the policy refuses to grade: on the live
    store 231 of 1448 open Very High issues were Very High only through such a
    comparison, and the dashboard's Very High Issues KPI and this screen's KPI
    cards both kept calling them Very High.

    The TOP-BAND ELIGIBILITY GATE is composed after those caps, for the history
    perspective only (see :func:`top_band_gate`): a robust scale can sit at its
    floor and grade any change as maximal, so the same window's
    dispersion-aware score decides whether ``VERY_HIGH`` may be claimed. It is
    never applied to a peer, volume or stratified claim, and it never lowers a
    band below HIGH.

    Every reader that counts or filters alerts uses this band, so the dashboard
    KPI, the screen's KPI cards and its table agree about the same row. Applying
    it to a row the scan already capped is idempotent: a cap never raises a
    band, and the cap it applied is the same one this function recomputes.
    """
    level, _ = cap_zero_spread(severity, stats or {}, method, series)
    level, thin = cap_thin_peer(level, peer_count, method)
    level, _gate, _assessment = top_band_gate(
        level, method=method, perspective=perspective, series=series,
        current=current, threshold=threshold)
    return level


def severity_cap(severity: Optional[str], *, stats: Optional[dict] = None,
                 method: Optional[str] = None,
                 peer_count: Optional[int] = None,
                 series: Optional[Sequence[float]] = None,
                 current: Optional[float] = None,
                 perspective: Optional[str] = None,
                 threshold: Optional[float] = None) -> Optional[dict]:
    """Provenance for :func:`effective_severity`; ``None`` when nothing capped.

    Carries the stored band, the band the policy allows and which cap applied,
    so a reader reports "stored VERY_HIGH, capped to HIGH: too few peers to
    measure a spread" instead of silently showing a different severity. A band
    refused by the top-band gate is reported under ``very_high_eligibility``
    with the window, value and threshold it was judged with.
    """
    level, dispersion = cap_zero_spread(severity, stats or {}, method, series)
    level, thin = cap_thin_peer(level, peer_count, method)
    level, gate, assessment = top_band_gate(
        level, method=method, perspective=perspective, series=series,
        current=current, threshold=threshold)
    if not dispersion and not thin and not gate:
        return None
    return {
        "stored_severity": severity,
        "severity": level,
        "dispersion": dispersion,
        "thin_peer_group": thin,
        "very_high_eligibility": gate,
        "route": assessment["route"],
    }


def eligibility_assessment(severity: Optional[str], *,
                           stats: Optional[dict] = None,
                           method: Optional[str] = None,
                           peer_count: Optional[int] = None,
                           series: Optional[Sequence[float]] = None,
                           current: Optional[float] = None,
                           perspective: Optional[str] = None,
                           threshold: Optional[float] = None,
                           peer_values: Optional[Mapping] = None,
                           peer_definition=None,
                           denominator_review: bool = False) -> dict:
    """The routed top-band verdict for one stored alert, caps included.

    The caps run FIRST (a comparison they already refuse is not the gate's
    business), so ``decision`` always describes the band the reader actually
    sees. Readers use this to explain a band instead of recomputing the policy.

    ``peer_values`` is the peer group the scan STORED on the row (see
    :func:`stored_peer_group`); with it a PEER row is judged by the approved
    peer policy (Rule B) after the definition gate (``peer_definition``). The
    returned ``decision`` is the only thing that changes — this function
    returns no band, so nothing here can alter a severity.
    """
    level, _ = cap_zero_spread(severity, stats or {}, method, series)
    level, _thin = cap_thin_peer(level, peer_count, method)
    _gated, _gate, assessment = top_band_gate(
        level, method=method, perspective=perspective, series=series,
        current=current, threshold=threshold, peer_values=peer_values,
        peer_definition=peer_definition,
        denominator_review=denominator_review)
    return assessment


def effective_z_score(z: Optional[float], *, method: Optional[str] = None,
                      peer_count: Optional[int] = None) -> Optional[float]:
    """The z-score a stored comparison can actually support, at read time.

    The scan withholds a peer z for a group below MIN_PEERS_FOR_TOP_BAND
    (``layered.PEER_Z_POLICY``): a z divides by the group's own spread, and
    2-3 hospitals cannot measure one. Rows written before that policy still
    carry the uncapped z, so every reader presents the z the policy in effect
    NOW allows — exactly as :func:`effective_severity` presents the current
    band — instead of the detail screen quoting ``z = 224.30`` beside a band
    the same policy caps at HIGH.

    Only PEER comparisons are affected: a history baseline's ``peer_count``
    counts prior MONTHS, not hospitals, and is governed by the
    history-observation minimum instead. The stored value is never rewritten;
    the caller reports it as ``stored_z_score``.
    """
    if method != layered.METHOD_PEER_ZSCORE:
        return z
    return z if layered.peer_z_measurable(peer_count) else None


def z_score_provenance(z: Optional[float], *, method: Optional[str] = None,
                       peer_count: Optional[int] = None
                       ) -> Optional[dict]:
    """Why a stored peer z is or is not presented (:func:`effective_z_score`).

    ``None`` for a non-peer comparison: those z-scores are not governed by this
    policy and must not borrow its explanation. A peer row — including one
    written before the policy, whose ``stats`` carry no provenance block — gets
    the block here, so a withheld z is explained instead of read as a missing
    measurement.
    """
    if method != layered.METHOD_PEER_ZSCORE:
        return None
    provenance = layered.peer_z_provenance(peer_count)
    provenance["scope"] = "peer"
    return provenance


def _history_score(spec_type: str, series: Sequence[float], current: float,
                   z_threshold: float, outlier_method: Optional[str] = None
                   ) -> Tuple[Optional[float], str, Optional[float], dict]:
    """Score current against the hospital's own baseline window.

    Uses the layered engine's method selection (an explicitly configured
    method, else rare-event counts -> rolling median+MAD, stable series ->
    %change, enough points -> IQR, else z-score) and the SAME prepared window
    as Diagnostics, so the two screens cannot disagree for one formula.
    """
    import statistics

    stats = {
        "mean": None, "median": None, "std": None,
        "min": None, "max": None, "points": len(series),
    }
    if not series:
        return None, "insufficient_history", None, stats
    values = [float(v) for v in series]
    stats.update(mean=statistics.fmean(values), median=statistics.median(values),
                 min=min(values), max=max(values))
    stats["std"] = statistics.stdev(values) if len(values) >= 2 else None
    # The divisor a robust method actually divides by. Recorded so a reader
    # can tell a MAD=0 (no measurable spread for that method) from a flat
    # window without recomputing it, and so the cap tests the right scale
    # (layered.spread_used).
    stats["mad"] = layered.mad(values) if values else None
    stats["iqr"] = (lambda q: q[2] - q[0])(layered.quartiles(values)) \
        if len(values) >= 2 else None
    z = None
    if stats["std"] not in (None, 0):
        z = (float(current) - stats["mean"]) / stats["std"]
    method = layered.select_method(outlier_method, values, spec_type)
    # One scoring implementation for both engines. A percentage-change score
    # comes back clamped to the score this window's z supports
    # (layered.PCT_CHANGE_CAP_POLICY); the change before the clamp is recorded
    # so the alert keeps the evidence that was actually observed.
    score, pct_before_cap = layered.score_window_detail(
        method, values, float(current), values[-1], z_threshold)
    if pct_before_cap is not None:
        stats["pct_change_capped"] = {
            "pct_change_score": round(float(pct_before_cap), 4),
            "score": round(float(score), 4) if score is not None else None,
            "z_score": round(float(z), 4) if z is not None else None,
            "z_threshold": z_threshold,
            "policy": layered.PCT_CHANGE_CAP_POLICY,
        }
    return score, method, z, stats


# ── ML cross-check (existing method, opt-in by sample size) ────────────────

def _ml_flags(values_by_hospital: Dict[int, float], min_samples: int) -> Optional[set]:
    """Isolation-Forest outlier hospital ids for one indicator's cross-section.

    Returns None when the sample is too small or sklearn is unavailable —
    the statistical finding never depends on this cross-check.
    """
    if len(values_by_hospital) < min_samples:
        return None
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
        ids = list(values_by_hospital.keys())
        matrix = np.array([[values_by_hospital[hid]] for hid in ids], dtype=float)
        model = IsolationForest(contamination=0.1, random_state=42)
        model.fit(matrix)
        flags = model.predict(matrix)
        return {hid for hid, flag in zip(ids, flags) if flag == -1}
    except Exception as exc:  # pragma: no cover - sklearn optional at runtime
        logger.warning("Quality Alerts ML cross-check skipped: %s", exc)
        return None


# ── Detail: the hospitals behind one comparison ──────────────────────

def _peer_group(db: Session, alert: QualityAlert, peer_ids: Sequence[int],
                resolved, month_data: dict) -> List[dict]:
    """Hospitals in one comparison group, with their value for the alert month.

    Values are recomputed exactly like the scan (same registry definition,
    same enabled raw values), so the group can never tell a different story
    than the alert it explains. A peer whose calculation is not ``ok`` keeps
    its name with ``value = None`` (a gap, never a fabricated 0).
    """
    ids: List[int] = []
    for pid in peer_ids or ():
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid not in ids:
            ids.append(pid)
    if not ids:
        return []

    hospitals = {h.id: h.name for h in db.query(Hospital)
                 .filter(Hospital.id.in_(ids)).all()}

    out: List[dict] = []
    for pid in ids:
        name = hospitals.get(pid)
        value = None
        if resolved is not None and name is not None:
            candidate = _candidate(resolved, month_data.get(name) or {}, pid,
                                   alert.month)
            if candidate.value is not None and math.isfinite(float(candidate.value)):
                value = round(float(candidate.value), 4)
        out.append({"id": pid, "name": name or f"#{pid}", "value": value})
    return out


def peer_groups(db: Session, alert: QualityAlert,
                siblings: Sequence[QualityAlert]) -> List[dict]:
    """Every peer comparison group stored for one alert issue, with values.

    The detail screen has to show WHO was compared and at what value — "n = 7"
    explains neither. A history alert has no peers of its own, yet the same
    issue may also have been compared with peer hospitals; listing every group
    keeps the detail from implying "no peers" when the indicator really was
    compared. ``siblings`` should already be ordered worst-first.
    """
    resolved = _alert_source(db, alert.indicator_code)
    month_data = (get_all_hospital_data_for_month(db, alert.month)
                  if resolved is not None else {})
    groups: List[dict] = []
    seen = set()
    for sibling in siblings:
        raw_ids = (sibling.evidence or {}).get("peer_ids") or []
        ids = tuple(int(pid) for pid in raw_ids if pid is not None)
        if not ids or (sibling.perspective, ids) in seen:
            continue
        seen.add((sibling.perspective, ids))
        groups.append({
            "perspective": sibling.perspective,
            "label": PERSPECTIVE_LABELS.get(sibling.perspective,
                                            sibling.perspective),
            "peers": _peer_group(db, alert, ids, resolved, month_data),
        })
    return groups


# ── Detail trend: the months behind one alert ──────────────────────────────

def _alert_source(db: Session, code: str):
    """The registry definition or data element an alert row was computed from."""
    for resolved in resolve_registry(db):
        if resolved.code == code:
            return resolved
    for element in resolve_data_elements(db):
        if element.code == code:
            return element
    return None


# Months drawn after the alert month, so the reader can see whether the
# finding persisted, moved, or returned to the normal range.
FORWARD_MONTHS = 3


def alert_trend(db: Session, alert: QualityAlert,
                max_months: int = 12) -> Optional[dict]:
    """Month-by-month values behind ONE alert, for the detail screen's chart.

    Every point is recomputed exactly like the scan: same registry definition,
    same enabled raw values (``get_enabled_values_for_hospital_month``), same
    peer membership. That is the point of this function — the line has to
    explain the finding it is displayed next to, never tell a second story.

    Returns ``None`` when there is nothing to draw (unknown indicator, no
    stored months). A month whose calculation is not ``ok`` is a ``None``
    point: the chart shows a gap rather than a fabricated value.
    """
    resolved = _alert_source(db, alert.indicator_code)
    hospital = db.query(Hospital).filter(Hospital.id == alert.hospital_id).first()
    if resolved is None or hospital is None:
        return None

    stored_months = [m for (m,) in db.query(IndicatorValue.month)
                     .filter(IndicatorValue.hospital_id == alert.hospital_id)
                     .distinct().all() if m]
    months = sorted(set(stored_months))
    if not months:
        return None
    # Window = up to ``max_months`` reporting periods around the alert: the
    # history that produced it plus the months that followed ("did it stay?").
    # The alert month itself is always inside the window.
    if alert.month in months:
        end = min(len(months), months.index(alert.month) + 1 + FORWARD_MONTHS)
    else:
        end = len(months)
    window = months[max(0, end - max_months):end]
    if alert.month and alert.month not in window:
        window = sorted(set(window) | {alert.month})

    directory = _hospital_directory(db)
    if alert.hospital_id not in directory:
        directory[alert.hospital_id] = hospital
    by_name = {h.name: hid for hid, h in directory.items() if h.name}

    is_peer = False
    peer_attribute: Optional[str] = None
    for key, attribute, _label in PEER_PERSPECTIVES:
        if key == alert.perspective:
            is_peer, peer_attribute = True, attribute
            break

    values: List[Optional[float]] = []
    baseline: List[Optional[float]] = []
    peer_counts: List[int] = []
    for month in window:
        valid: Dict[int, float] = {}
        if is_peer:
            # A peer comparison needs every hospital's value for that month.
            for name, raw_values in get_all_hospital_data_for_month(db, month).items():
                hid = by_name.get(name)
                if hid is None:
                    continue
                candidate = _candidate(resolved, raw_values, hid, month)
                if candidate.value is not None and math.isfinite(float(candidate.value)):
                    valid[hid] = float(candidate.value)
        else:
            # History only needs this hospital: skip the cross-section.
            raw_values = get_enabled_values_for_hospital_month(
                db, alert.hospital_id, month)
            if raw_values:
                candidate = _candidate(resolved, raw_values, alert.hospital_id, month)
                if candidate.value is not None and math.isfinite(float(candidate.value)):
                    valid[alert.hospital_id] = float(candidate.value)
        own = valid.get(alert.hospital_id)
        values.append(round(own, 4) if own is not None else None)
        if is_peer:
            members = _peer_members(directory, alert.hospital_id,
                                    peer_attribute, valid)
            peer_counts.append(len(members))
            baseline.append(
                round(sum(v for _mid, v in members) / len(members), 4)
                if members else None)
        else:
            peer_counts.append(0)
            baseline.append(None)

    if is_peer:
        baseline_label = (PERSPECTIVE_LABELS.get(alert.perspective, alert.perspective)
                          + " — mean")
        baseline_kind = "peer"
    else:
        # History (and any perspective without a per-month group): the stored
        # baseline is a single number, drawn as one flat reference line.
        baseline_label = "Prior-months baseline"
        baseline_kind = "history"

    return {
        "months": window,
        "values": values,
        "baseline": baseline,
        "baseline_kind": baseline_kind,
        "baseline_label": baseline_label,
        "peer_counts": peer_counts,
        "reference_value": alert.baseline_value,
        "reference_label": PERSPECTIVE_LABELS.get(alert.perspective, alert.perspective),
        "alert_month": alert.month,
        "alert_value": alert.current_value,
        "unit": alert.unit or "",
    }


def sparkline_series(db: Session, alerts: Sequence[QualityAlert],
                     max_months: int = 8) -> Dict[Tuple[int, str, str], Optional[dict]]:
    """Compact monthly series for LIST rows (the table's inline trend line).

    Same authoritative calculation as ``alert_trend``, but without the peer
    cross-section: a page of 25 issues cannot afford 25 peer scans, and the
    row only needs the hospital's own shape — a one-month spike versus a
    sustained problem — to be triaged at a glance. Opening the row shows the
    full peer comparison.

    Keyed by ``(hospital_id, indicator_code, month)`` — the issue key.
    """
    if not alerts:
        return {}

    resolved_by_code = {r.code: r for r in resolve_registry(db)}
    for element in resolve_data_elements(db):
        resolved_by_code.setdefault(element.code, element)

    hospital_ids = {a.hospital_id for a in alerts}
    months_by_hospital: Dict[int, List[str]] = {}
    for hid, month in (db.query(IndicatorValue.hospital_id, IndicatorValue.month)
                       .filter(IndicatorValue.hospital_id.in_(hospital_ids))
                       .distinct().all()):
        if month:
            months_by_hospital.setdefault(hid, []).append(month)
    for hid in months_by_hospital:
        months_by_hospital[hid] = sorted(set(months_by_hospital[hid]))

    # One enabled-value read per (hospital, month), shared by every indicator
    # of that hospital on the page.
    raw_cache: Dict[Tuple[int, str], Dict[str, float]] = {}

    def _raw(hid: int, month: str) -> Dict[str, float]:
        key = (hid, month)
        if key not in raw_cache:
            raw_cache[key] = get_enabled_values_for_hospital_month(db, hid, month)
        return raw_cache[key]

    out: Dict[Tuple[int, str, str], Optional[dict]] = {}
    for alert in alerts:
        key = (alert.hospital_id, alert.indicator_code, alert.month)
        resolved = resolved_by_code.get(alert.indicator_code)
        if resolved is None:
            out[key] = None
            continue
        months = months_by_hospital.get(alert.hospital_id) or []
        if alert.month in months:
            end = min(len(months), months.index(alert.month) + 1 + FORWARD_MONTHS)
        else:
            end = len(months)
        window = months[max(0, end - max_months):end]

        values: List[Optional[float]] = []
        seen: List[float] = []
        for month in window:
            candidate = _candidate(resolved, _raw(alert.hospital_id, month),
                                   alert.hospital_id, month)
            if candidate.value is None:
                values.append(None)
                continue
            value = round(float(candidate.value), 4)
            values.append(value)
            seen.append(value)

        out[key] = {
            "months": window,
            "values": values,
            "alert_month": alert.month,
            "baseline": alert.baseline_value,
            "min": min(seen) if seen else None,
            "max": max(seen) if seen else None,
        }
    return out


# ── Scan orchestration ──────────────────────────────────────────────────────

@dataclass
class ScanStats:
    hospitals_scanned: int = 0
    indicators: int = 0
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    deduplicated: int = 0
    perspectives_evaluated: int = 0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "hospitals_scanned": self.hospitals_scanned,
            "indicators": self.indicators,
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
            # Rows retired because they duplicated a canonical formula that
            # this run re-detected under its canonical code.
            "deduplicated": self.deduplicated,
            "perspectives_evaluated": self.perspectives_evaluated,
            "errors": self.errors[:10],
        }


def _severity_for_score(score: Optional[float], min_score: float) -> Optional[str]:
    """Layered band for the score; None when below the alert floor."""
    if score is None or score < min_score:
        return None
    return layered.level_for_score(score)


def _severity_source(perspective: str) -> str:
    """Which existing engine produced this perspective's base classification.

    The history perspective is the hospital's own statistical baseline; every
    peer perspective is a peer comparison. The classification itself still
    comes from the layered band engine (``_severity_for_score``) — this only
    records provenance for the audit trail.
    """
    if perspective == PERSPECTIVE_HISTORY:
        return severity_policy.SOURCE_STATISTICAL_OUTLIER
    return severity_policy.SOURCE_PEER_COMPARISON


def _canonical_evidence(resolved, canonical_by_code: Dict[str, object],
                        identity_index: Dict[str, dict]) -> dict:
    """Traceability block stored with every finding.

    ``key`` is the canonical formula identity shared with Anomaly Diagnostics,
    ``code`` the representative registration, and ``registered_codes`` every
    equivalent code (so a stored finding can always be traced back to the
    formula AND to any diagnostic result computed for it). A raw data element
    has no formula, so it is its own identity.
    """
    formula = canonical_by_code.get(getattr(resolved, "code", None))
    if formula is not None:
        return {
            "key": formula.key,
            "code": formula.code,
            "formula": getattr(resolved, "formula", None),
            "registered_codes": list(formula.registered_codes),
        }
    info = identity_index.get(getattr(resolved, "code", None))
    if info:
        return {
            "key": info["key"],
            "code": info["code"],
            "formula": getattr(resolved, "formula", None),
            "registered_codes": list(info["registered_codes"]),
        }
    identity = canonical_identity.resolved_identity(resolved)
    return {
        "key": canonical_identity.identity_key(identity),
        "code": getattr(resolved, "code", None),
        "formula": getattr(resolved, "formula", None),
        "registered_codes": [getattr(resolved, "code", None)],
    }


# ── Canonical layered evidence (Phase 3) ───────────────────────────────────
# Quality Alerts and Outlier Diagnostics grade the same comparison. Where the
# two questions are analytically equivalent — the detection baseline (every
# active hospital reporting the formula) and the hospital's own history window
# — Diagnostics has already computed and STORED the score on its
# ``LayeredOutlierResult`` row. The scan CONSUMES that stored score instead of
# computing the same statistic a second time, so one comparison has one number.
#
# Reuse is proved per row, never assumed: the stored window's months and values
# must equal the window this scan selected, and the stored peer group must be
# exactly the hospitals this scan compared against. A stratified perspective
# (type / ownership / facility type / governorate) is a DIFFERENT population
# and therefore never consumes the detection baseline; it keeps its own
# approved calculation and says so in its evidence.
EVIDENCE_CANONICAL = "canonical_layered"
EVIDENCE_SCAN = "alert_scan"
CANONICAL_EQUIVALENT = "equivalent"
CANONICAL_MISSING = "missing_layered_result"
CANONICAL_NOT_EQUIVALENT = "not_equivalent"
CANONICAL_INDEPENDENT = "independent_perspective"
LAYER_HISTORY = "historical"
LAYER_PEER = "peer"


def canonical_analysis_codes(db: Session) -> Dict[str, str]:
    """``indicator code -> the layered analysis unit that analyses it``.

    The one join the pipeline already uses for its projection
    (``projection.projection_codes``), inverted. A data element is its own
    analysis unit and carries no projection row, so it maps to itself.
    """
    from app.engine.anomaly.projection import projection_codes

    codes = {code: analysis for analysis, code in projection_codes(db).items()}
    for (code,) in db.query(Indicator.code).all():
        if code:
            codes.setdefault(code, code)
    return codes


def canonical_layered_index(db: Session, month: str,
                            hospital_id: Optional[int] = None
                            ) -> Dict[Tuple[int, str], object]:
    """Stored layered rows for one month, keyed by (hospital, analysis_code)."""
    query = db.query(LayeredOutlierResult).filter(
        LayeredOutlierResult.month == month)
    if hospital_id is not None:
        query = query.filter(LayeredOutlierResult.hospital_id == hospital_id)
    return {(row.hospital_id, row.analysis_code): row for row in query.all()}


def _canonical_stats(layer: str, values: Sequence[float], row) -> dict:
    """Descriptive statistics of the STORED comparison window/group.

    The layered row stores its score, mean and std; the read-time caps also ask
    for the divisor the method divided by (MAD / IQR). Those are computed from
    the stored values themselves — the same list the canonical calculation used
    — so the cap test sees exactly what that calculation saw. No score is
    recomputed here.
    """
    import statistics

    numbers = [float(v) for v in values]
    stored_mean = (getattr(row, "peer_mean", None) if layer == LAYER_PEER
                   else getattr(row, "historical_mean", None))
    stats = {
        "mean": (float(stored_mean) if stored_mean is not None
                 else statistics.fmean(numbers)),
        "median": statistics.median(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "points": len(numbers),
        "std": statistics.stdev(numbers) if len(numbers) >= 2 else None,
        "mad": layered.mad(numbers) if numbers else None,
        "iqr": ((lambda q: q[2] - q[0])(layered.quartiles(numbers))
                if len(numbers) >= 2 else None),
    }
    if layer == LAYER_PEER:
        stats["z_provenance"] = layered.peer_z_provenance(len(numbers))
    return stats


def _canonical_caps(row, layer: str) -> dict:
    """The caps the canonical row recorded for this layer, if it recorded any."""
    provenance = getattr(row, "classification_provenance", None) or {}
    return {
        "policy_version": provenance.get("policy_version"),
        "zero_spread": layer in set(provenance.get("zero_spread_layers") or ()),
        "thin_peer": layer in set(provenance.get("thin_peer_layers") or ()),
        "level": provenance.get("level"),
        "cap": provenance.get("cap"),
    }


def _canonical_z(stats: dict, current: Optional[float], *,
                 measurable: bool) -> Optional[float]:
    """The z the stored comparison's own mean/std support (None if unmeasurable)."""
    std = stats.get("std")
    mean = stats.get("mean")
    if current is None or std in (None, 0) or mean is None or not measurable:
        return None
    return (float(current) - float(mean)) / float(std)


def canonical_comparison_evidence(
        row, perspective: str, *,
        months: Optional[Sequence[str]] = None,
        series: Optional[Sequence[float]] = None,
        peer_ids: Optional[Sequence[int]] = None,
        current: Optional[float] = None) -> Tuple[Optional[dict], str]:
    """The stored layered layer that answers this perspective, when equivalent.

    Returns ``(evidence, status)``. ``evidence`` is populated only when the
    stored comparison IS the comparison this scan would run:

    * the detection baseline (``all``) needs the stored group to be the
      canonical detection group AND its members to be exactly the hospitals
      this scan compared against;
    * the history perspective needs the stored window's months and values to
      equal the window this scan selected.

    Status is ``equivalent`` (evidence returned), ``missing_layered_result``
    (nothing stored to reuse), ``not_equivalent`` (stored evidence exists but
    describes a different comparison) or ``independent_perspective`` (a
    stratified population, which is deliberately its own calculation).
    """
    if perspective not in (PERSPECTIVE_HISTORY, PERSPECTIVE_ALL):
        # A stratified population is not the detection baseline: keeping its
        # own calculation is the approved behaviour, not a fallback — and it
        # stays that way whether or not a layered row happens to exist.
        return None, CANONICAL_INDEPENDENT
    if row is None:
        return None, CANONICAL_MISSING
    if perspective == PERSPECTIVE_HISTORY:
        provenance = getattr(row, "history_provenance", None) or {}
        try:
            stored_months = [str(m) for m in provenance.get("months") or ()]
            stored_values = [float(v) for v in provenance.get("values") or ()]
        except (TypeError, ValueError):
            return None, CANONICAL_NOT_EQUIVALENT
        if not stored_values:
            return None, CANONICAL_MISSING
        if (list(months or ()) != stored_months
                or [float(v) for v in (series or ())] != stored_values):
            return None, CANONICAL_NOT_EQUIVALENT
        score = getattr(row, "historical_outlier_score", None)
        if score is None:
            return None, CANONICAL_MISSING
        stats = _canonical_stats(LAYER_HISTORY, stored_values, row)
        z = getattr(row, "historical_z_score", None)
        return {
            "source": EVIDENCE_CANONICAL,
            "status": CANONICAL_EQUIVALENT,
            "layer": LAYER_HISTORY,
            "perspective": perspective,
            "perspective_scope": "detection_baseline",
            "layered_result_id": getattr(row, "id", None),
            "analysis_code": getattr(row, "analysis_code", None),
            "month": getattr(row, "month", None),
            "stored_level": getattr(row, "outlier_level", None),
            "score": float(score),
            "baseline": stats["mean"],
            "z": float(z) if z is not None else None,
            "peer_count": stats["points"],
            "stats": stats,
            "window": [[m, v] for m, v in zip(stored_months, stored_values)],
            "caps": _canonical_caps(row, LAYER_HISTORY),
        }, CANONICAL_EQUIVALENT
    provenance = getattr(row, "peer_provenance", None) or {}
    if provenance.get("group") != comparison_policy.DETECTION_PEER_GROUP:
        return None, CANONICAL_NOT_EQUIVALENT
    by_id: Dict[int, float] = {}
    for key, value in (provenance.get("values") or {}).items():
        try:
            by_id[int(key)] = float(value)
        except (TypeError, ValueError):
            continue
    stored_ids = sorted(by_id)
    try:
        compared = sorted(int(hid) for hid in (peer_ids or ()))
    except (TypeError, ValueError):
        return None, CANONICAL_NOT_EQUIVALENT
    if not stored_ids or stored_ids != compared:
        return None, CANONICAL_NOT_EQUIVALENT
    score = getattr(row, "peer_outlier_score", None)
    if score is None:
        return None, CANONICAL_MISSING
    numbers = [by_id[mid] for mid in stored_ids]
    stats = _canonical_stats(LAYER_PEER, numbers, row)
    return {
        "source": EVIDENCE_CANONICAL,
        "status": CANONICAL_EQUIVALENT,
        "layer": LAYER_PEER,
        "perspective": perspective,
        "perspective_scope": "detection_baseline",
        "layered_result_id": getattr(row, "id", None),
        "analysis_code": getattr(row, "analysis_code", None),
        "month": getattr(row, "month", None),
        "stored_level": getattr(row, "outlier_level", None),
        "score": float(score),
        "baseline": stats["mean"],
        "z": _canonical_z(stats, current,
                          measurable=layered.peer_z_measurable(len(numbers))),
        "peer_count": len(numbers),
        "stats": stats,
        "peer_ids": stored_ids,
        "caps": _canonical_caps(row, LAYER_PEER),
    }, CANONICAL_EQUIVALENT


def _merge_investigation_state(db: Session, target: QualityAlert,
                               source: QualityAlert, now: datetime) -> bool:
    """Carry investigation state from a retired duplicate to its canonical row.

    Only the more advanced status wins (``_STATUS_ROLLUP`` order) and an
    existing assignee is never overwritten. Returns True when anything moved;
    a status/note event records the merge on the surviving row so the
    provenance of a Confirmed Issue stays readable.
    """
    moved: List[str] = []
    old_status = target.status
    if (_STATUS_PRIORITY.get(source.status, 99)
            < _STATUS_PRIORITY.get(target.status, 99)):
        target.status = source.status
        moved.append(f"status {source.status}")
    if source.assignee and not target.assignee:
        target.assignee = source.assignee
        moved.append(f"assignee {source.assignee}")
    if not moved:
        return False
    target.updated_at = now
    db.add(QualityAlertEvent(
        alert_id=target.id, from_status=old_status, to_status=target.status,
        note=("Merged investigation state from duplicate registration "
              f"{source.indicator_code} ({', '.join(moved)})."),
        actor="system", created_at=now))
    return True


def _reason_text(resolved, perspective: str, severity: str,
                 current: float, baseline: float, z: Optional[float],
                 peer_count: Optional[int], interpretation: str) -> str:
    unit = getattr(resolved, "unit", "") or ""
    label = PERSPECTIVE_LABELS.get(perspective, perspective)
    direction = {
        INTERP_HIGH_CONCERN: "Higher values are undesirable for this indicator.",
        INTERP_HIGH_FAVORABLE: "Higher values are desirable — verify data accuracy before concluding performance.",
        INTERP_LOW_CONCERN: "Lower values are undesirable for this indicator.",
        INTERP_LOW_FAVORABLE: "Lower values are desirable for this indicator.",
        INTERP_OUTSIDE_TARGET: "The value is outside the configured target range.",
        INTERP_WITHIN_TARGET: "The value is outside its baseline but still within the configured target range.",
        INTERP_STATISTICAL_ONLY: "No clinical direction is configured — treat as a statistical deviation only.",
    }.get(interpretation, "")
    parts = [f"{resolved.name} = {current:g}{unit} deviates from the {label.lower()} baseline {baseline:g}"]
    if z is not None:
        parts.append(f"z = {z:.2f}")
    if peer_count is not None:
        parts.append(f"n = {peer_count}")
    parts.append(f"severity {severity}")
    text = " — ".join(parts) + "."
    if direction:
        text += " " + direction
    return text


def scan(db: Session, month: str, hospital_id: Optional[int] = None,
         indicator_codes: Optional[Sequence[str]] = None,
         policy: Optional[PolicySnapshot] = None) -> dict:
    """Run the multi-perspective scan for one reporting month and persist.

    Upserts one row per (hospital, indicator, month, perspective); reviewed
    rows that are no longer detected are deactivated, never deleted.

    ``indicator_codes`` narrows BOTH the regeneration and the deactivation
    sweep to those indicators. That is what makes a targeted recompute safe:
    re-checking the rows already known to be stale must never deactivate (or
    rewrite) a sibling indicator's untouched rows for the same hospital/month.
    """
    stats = ScanStats()
    # D16-A2: the scan resolves policy ONCE for the whole month (or receives
    # the snapshot of the analysis run that triggered it). A read failure
    # still aborts with a visible error — never hidden hardcoded rules.
    if policy is None:
        try:
            policy = load_policy_snapshot(db)
        except PolicyUnavailable as exc:
            logger.error("Quality Alerts scan aborted: %s", exc)
            return {"error": str(exc), "configuration_error": True,
                    **stats.as_dict()}
    if policy.invalid_keys:
        logger.warning(
            "Quality Alerts scan %s is using %d fallback value(s) from "
            "invalid stored settings: %s", month, len(policy.invalid_keys),
            ", ".join(policy.invalid_keys))
    # Stage 1 — the alerts plane's OWN pre-policy view (alert window only,
    # unclamped Z), exactly as _alerts_config built it.
    cfg = alerts_config_from_snapshot(policy)
    sev_cfg = analysis_config_from_snapshot(policy)
    # One Z-score threshold: the value the shared surface already validated
    # and clamped (thresholds.zscore_threshold) replaces this scan's own.
    cfg["z_threshold"] = sev_cfg.zscore_threshold
    # Stage 2 — the shared temporal/peer policy, trend window applied. The
    # same window and minimum peer count apply to Diagnostics and to the
    # equivalent Alerts perspectives; narrower perspectives stay narrower
    # and are labelled as such. Both stages stay distinct: the pre-policy
    # window is never overwritten in the snapshot, only in this scan-local
    # dict.
    comparison = comparison_policy_from_snapshot(policy)
    cfg["history_window"] = comparison.history.window
    cfg["min_history"] = comparison.history.min_observations
    cfg["min_peers"] = comparison.peer.min_peers
    rate_settings = _rate_analysis_settings(db)
    # Identifies this exact saved configuration; stored with every row.
    policy_fingerprint = severity_policy.policy_fingerprint(sev_cfg)
    registry = resolve_registry(db)
    # One row per LOGICAL formula, not per registered code: the registry keeps
    # a per-site copy of most rates, and analysing every copy would raise the
    # same deviation (and count it) once per code.
    formulas = resolve_canonical_registry(db)
    # ALL catalog kinds are searched: canonical rate/derivative definitions
    # AND raw data elements. Codes are unique across kinds in practice; a raw
    # element shadowing a registry code is skipped (the managed definition
    # wins) so one code can never overwrite the other's persisted rows.
    def_codes = {d.code for d in registry}
    elements = [e for e in resolve_data_elements(db) if e.code not in def_codes]
    if not formulas and not elements:
        return {"error": "Indicators Registry has no active definitions",
                **stats.as_dict()}
    scanned = [formula.resolved for formula in formulas] + list(elements)
    identity_index = canonical_code_index(db)
    canonical_by_code = {formula.resolved.code: formula for formula in formulas}
    # Duplicate registrations of formulas being analysed this run. Their stored
    # rows are retired once the canonical row exists (see the stale sweep).
    alias_to_canonical = {
        code: formula.code
        for formula in formulas
        for code in formula.registered_codes
        if code != formula.code
    }
    code_filter: Optional[set] = None
    if indicator_codes is not None:
        requested = {str(code) for code in indicator_codes}
        # A caller may name a duplicate registration (e.g. the stale-policy
        # rescan walks stored rows). Its canonical representative is what is
        # actually scanned, so widen the filter to the whole canonical group.
        canonical_requested = {
            (identity_index.get(code) or {}).get("code", code)
            for code in requested
        }
        code_filter = requested | {
            code for code, info in identity_index.items()
            if info["code"] in canonical_requested
        }
        scanned = [item for item in scanned if item.code in code_filter]
        if not scanned:
            return {"error": "No matching indicators to scan",
                    **stats.as_dict()}
    stats.indicators = len(scanned)

    # Phase 3: this month's canonical layered evidence, read ONCE per scan. A
    # finding whose comparison is analytically equivalent to a stored layer
    # consumes that stored score (canonical_comparison_evidence); a scan that
    # cannot read the canonical plane keeps its own calculation and records
    # that in every row's evidence — alerting is never blocked or silently
    # re-graded because the layered plane is unavailable.
    try:
        canonical_codes = canonical_analysis_codes(db)
        canonical_index = canonical_layered_index(db, month)
    except Exception:
        logger.exception(
            "Canonical layered evidence unreadable for %s; the scan keeps its "
            "own calculation and records the missing source", month)
        canonical_codes, canonical_index = {}, {}

    directory = _hospital_directory(db)
    if not directory:
        return {"error": "No eligible hospitals", **stats.as_dict()}
    # A hospital-scoped run still needs the OTHER hospitals to compare against.
    # Filtering the directory itself left one value per indicator, so every
    # peer comparison was skipped and the target's existing alerts were then
    # deactivated as "no longer detected". Compare on the full directory and
    # restrict only what gets persisted.
    target_hospitals: Optional[set] = None
    if hospital_id is not None:
        target_hospitals = {hospital_id} if hospital_id in directory else set()
        if not target_hospitals:
            return {"error": "No eligible hospitals", **stats.as_dict()}

    # Authoritative current-month values through the shared calculation engine.
    all_month_data = get_all_hospital_data_for_month(db, month)  # name -> raw values
    name_to_id = {h.name: hid for hid, h in directory.items()}
    raw_by_hospital: Dict[int, Dict[str, float]] = {}
    for name, values in all_month_data.items():
        hid = name_to_id.get(name)
        if hid is not None:
            raw_by_hospital[hid] = values

    # Cross-section per indicator (peer + ML input).
    cross_section: Dict[str, Dict[int, AlertCandidate]] = {}
    for hid, values in raw_by_hospital.items():
        for resolved in scanned:
            candidate = _candidate(resolved, values, hid, month)
            cross_section.setdefault(resolved.code, {})[hid] = candidate

    # Data-quality gate for trend escalation: one read per scan, only when a
    # minimum is actually configured. Completeness is the same component the
    # Quality Score stores for the hospital/month.
    completeness_by_hospital: Dict[int, Optional[float]] = {}
    if sev_cfg.trend.min_completeness > 0:
        from app.models import QualityScore
        for hid, completeness in (db.query(QualityScore.hospital_id,
                                           QualityScore.completeness)
                                  .filter(QualityScore.month == month).all()):
            completeness_by_hospital[hid] = (
                float(completeness) if completeness is not None else None)

    now = datetime.utcnow()
    seen_keys: List[Tuple[int, str, str, str]] = []

    # History months are fetched ONCE per hospital and shared by every
    # element/indicator of that hospital (100+ data elements would otherwise
    # re-query the same months once per element).
    history_cache: Dict[int, Dict[str, Dict[str, float]]] = {}
    for resolved in scanned:
        canonical_evidence = _canonical_evidence(
            resolved, canonical_by_code, identity_index)
        item_settings = _item_comparison_settings(
            resolved, rate_settings, comparison)
        peers_allowed = item_settings["peer_comparison_enabled"]
        history_allowed = item_settings["historical_enabled"]
        item_history_policy = comparison.history.with_item_minimum(
            item_settings["minimum_history_period"])
        by_hospital = cross_section.get(resolved.code, {})
        valid_values = {
            hid: c.value for hid, c in by_hospital.items()
            if c.value is not None and math.isfinite(float(c.value))
        }
        if len(valid_values) < 2:
            continue  # nothing comparable — safeguards, never a forced alert

        direction, target_min, target_max = resolve_direction(db, resolved)
        ml_out = (_ml_flags(valid_values, cfg["ml_min_samples"])
                  if cfg["ml_enabled"] else None)

        for hid, candidate in by_hospital.items():
            if target_hospitals is not None and hid not in target_hospitals:
                continue  # comparison universe complete; persist target only
            if candidate.value is None:
                continue  # missing / zero-denominator / non-ok: never alerted
            current = float(candidate.value)
            findings: List[dict] = []
            analysis_code = canonical_codes.get(
                getattr(resolved, "code", None))
            canonical_row = (canonical_index.get((hid, analysis_code))
                             if analysis_code else None)

            # ── Peer perspectives (current month) ──
            for perspective, attribute, _label in (
                    PEER_PERSPECTIVES if peers_allowed else ()):
                members = _peer_members(directory, hid, attribute, valid_values)
                if len(members) < comparison.peer.min_peers:
                    continue  # peer group too small — avoid misleading comparisons
                canonical, canonical_status = canonical_comparison_evidence(
                    canonical_row, perspective,
                    peer_ids=[mid for mid, _v in members], current=current)
                if canonical is not None:
                    # The stored detection-baseline comparison IS this one:
                    # consume its score instead of computing it again.
                    score = canonical["score"]
                    z = canonical["z"]
                    pstats = canonical["stats"]
                    baseline = canonical["baseline"]
                    peer_count = canonical["peer_count"]
                else:
                    z, score, pstats = _peer_score(
                        current, [v for _mid, v in members],
                        cfg["z_threshold"])
                    baseline = pstats["mean"]
                    peer_count = len(members)
                if score is None:
                    continue
                peer_group = (
                    comparison_policy.DETECTION_PEER_GROUP
                    if perspective == PERSPECTIVE_ALL
                    else comparison_policy.stratified_peer_group(perspective)
                )
                findings.append({
                    "perspective": perspective,
                    "score": score, "z": z, "method": "peer_zscore",
                    "baseline": baseline,
                    "peer_count": peer_count,
                    "stats": pstats,
                    "canonical": canonical,
                    "canonical_status": canonical_status,
                    "peer_ids": [mid for mid, _v in members],
                    "comparison": {
                        "perspective_scope": (
                            "detection_baseline"
                            if perspective == PERSPECTIVE_ALL else "stratified"),
                        "peer": {
                            "policy_version": comparison.version,
                            "group": peer_group,
                            "group_label": PERSPECTIVE_LABELS.get(
                                perspective, perspective),
                            "month": month,
                            "min_peers": comparison.peer.min_peers,
                            "eligible_count": len(members),
                            "peer_ids": [mid for mid, _v in members],
                            "values": {str(mid): round(float(value), 4)
                                       for mid, value in members},
                        },
                    },
                })

            # ── History perspective (own prior periods) ──
            trend_assessment = None
            if history_allowed:
                if hid not in history_cache:
                    history_cache[hid] = get_historical_months(db, hid, month)
                history = history_cache[hid]
                # The same shared window as Diagnostics: the last N reporting
                # months, missing observations skipped, minimum valid points
                # from the system policy with the per-indicator floor.
                history_window = comparison_policy.history_window(
                    history, month, item_history_policy,
                    lambda m, _h=history, _hid=hid, _r=resolved: (
                        _candidate(_r, _h[m], _hid, m).value),
                )
                series = history_window.values
                series_months = [m for m, _v in history_window.observations]
                # ONE trend assessment per hospital/indicator, shared by every
                # perspective row persisted below (no second trend rule set).
                trend_assessment = severity_policy.assess_trend(
                    series, series_months, config=sev_cfg.trend,
                    bands=sev_cfg.trend_bands,
                    indicator_direction=direction)
                if len(series) >= item_history_policy.min_observations:
                    spec_type = getattr(resolved, "indicator_type", None) or "rate"
                    canonical, canonical_status = canonical_comparison_evidence(
                        canonical_row, PERSPECTIVE_HISTORY,
                        months=series_months, series=series, current=current)
                    if canonical is not None:
                        # Same window, same values, same threshold: reuse the
                        # stored layered score and keep the scan's own method
                        # name (selection is deterministic for this window).
                        hscore = canonical["score"]
                        method = layered.select_method(
                            item_settings["outlier_method"], series, spec_type)
                        z, hstats = canonical["z"], canonical["stats"]
                    else:
                        hscore, method, z, hstats = _history_score(
                            spec_type, series, current, cfg["z_threshold"],
                            outlier_method=item_settings["outlier_method"])
                    if hscore is not None:
                        findings.append({
                            "perspective": PERSPECTIVE_HISTORY,
                            "score": hscore, "z": z, "method": method,
                            "baseline": hstats["mean"],
                            "peer_count": len(series),
                            "stats": hstats,
                            "canonical": canonical,
                            "canonical_status": canonical_status,
                            "history": list(zip(series_months, series,
                                                strict=False)),
                            "comparison": {
                                "perspective_scope": "detection_baseline",
                                "history": {
                                    "policy_version": comparison.version,
                                    "window": item_history_policy.window,
                                    "min_observations": (
                                        item_history_policy.min_observations),
                                    "months": history_window.months,
                                    "valid_count": history_window.valid_count,
                                    "skipped_months": (
                                        history_window.skipped_months),
                                    "method": method,
                                    "observation_config_source": (
                                        item_settings["source"]),
                                },
                            },
                        })

            # ── Persist each perspective that clears the floor ──
            for finding in findings:
                base_level = _severity_for_score(finding["score"], cfg["min_score"])
                if base_level is None:
                    continue
                # base severity (existing engine) + trend assessment + final
                # severity (configured policy) stay three distinct outputs.
                resolution = severity_policy.resolve_severity(
                    base_level, _severity_source(finding["perspective"]),
                    trend=trend_assessment, config=sev_cfg.trend,
                    data_quality=(completeness_by_hospital.get(hid)
                                  if sev_cfg.trend.min_completeness > 0 else None),
                )
                severity, dispersion = cap_zero_spread(
                    resolution.final.level, finding.get("stats"),
                    finding.get("method"))
                # A peer comparison with too few peers cannot measure a spread,
                # so it may not claim the top band (THIN_PEER_POLICY). Applied
                # after the severity policy, exactly like the no-dispersion
                # cap, and only ever downward.
                severity, thin_peer = cap_thin_peer(
                    severity, finding.get("peer_count"),
                    finding.get("method"))
                stats.perspectives_evaluated += 1
                interpretation = interpret_deviation(
                    direction, current, finding["baseline"],
                    target_min, target_max)
                ml_agrees: Optional[bool] = None
                confidence = "high"
                if (finding["perspective"] == PERSPECTIVE_ALL
                        and ml_out is not None):
                    ml_agrees = hid in ml_out
                    if not ml_agrees:
                        confidence = "low"
                if finding["peer_count"] < SMALL_COMPARISON_GROUP:
                    confidence = "low"  # small comparison group
                finding_evidence = {
                    "baseline_label": PERSPECTIVE_LABELS.get(
                        finding["perspective"], finding["perspective"]),
                    "stats": finding["stats"],
                    "z_threshold": cfg["z_threshold"],
                    "min_score": cfg["min_score"],
                    "direction": direction,
                    "target_min": target_min,
                    "target_max": target_max,
                    "ml_confirms": ml_agrees,
                }
                if "peer_ids" in finding:
                    finding_evidence["peer_ids"] = finding["peer_ids"][:50]
                if "history" in finding:
                    finding_evidence["history"] = finding["history"]
                # Effective window / peer group / eligible peers behind THIS
                # row, so the exact comparison can be audited after the
                # configuration or data changes.
                if "comparison" in finding:
                    # The comparison perspective travels WITH its evidence
                    # source, so a reader never confuses the canonical
                    # detection baseline with a stratified population.
                    comparison_block = dict(finding["comparison"])
                    comparison_block["evidence_source"] = (
                        EVIDENCE_CANONICAL if finding.get("canonical")
                        else EVIDENCE_SCAN)
                    comparison_block["perspective"] = finding["perspective"]
                    finding_evidence["comparison_policy"] = comparison_block
                evidence = dict(finding_evidence)
                if candidate.denominator is not None:
                    evidence["denominator"] = candidate.denominator
                if candidate.numerator is not None:
                    evidence["numerator"] = candidate.numerator
                # Canonical formula traceability: the identity every engine
                # (Anomaly Diagnostics included) keys this formula by, and
                # every registered code that carries it — an auditor can walk
                # from this alert to any result computed for the same formula.
                evidence["canonical"] = canonical_evidence
                # Which evidence answered this perspective (Phase 3): the
                # stored canonical layered result when the comparison is the
                # same one, otherwise this scan's own calculation — and an
                # explicit status saying why it is not canonical.
                canonical_block = finding.get("canonical")
                if canonical_block is not None:
                    evidence["evidence_source"] = EVIDENCE_CANONICAL
                else:
                    evidence["evidence_source"] = EVIDENCE_SCAN
                    canonical_block = {
                        "source": EVIDENCE_SCAN,
                        "status": finding.get(
                            "canonical_status", CANONICAL_MISSING),
                        "perspective": finding["perspective"],
                        "perspective_scope": (
                            "stratified"
                            if finding["perspective"] not in (
                                PERSPECTIVE_HISTORY, PERSPECTIVE_ALL)
                            else "detection_baseline"),
                    }
                evidence["canonical_evidence"] = canonical_block
                # Three auditable outputs. The base classification is stored
                # verbatim; the final level is what the alert row carries.
                evidence["base_severity"] = resolution.base.as_dict()
                evidence["trend_assessment"] = (
                    resolution.trend.as_dict() if resolution.trend else None)
                evidence["final_severity"] = resolution.final.as_dict()
                evidence["severity_policy"] = {
                    "policy": resolution.policy,
                    "applied": resolution.applied,
                    "reason": resolution.reason,
                    # Identifies the exact saved configuration used, so a later
                    # reader can flag this row as computed under an older
                    # policy instead of silently trusting its severity.
                    "fingerprint": policy_fingerprint,
                }
                if dispersion is not None:
                    # The comparison had no spread: record the cap next to the
                    # evidence that produced it, so a reader sees WHY the level
                    # is not the top band and what the score alone would say.
                    evidence["dispersion"] = dispersion
                if thin_peer is not None:
                    # The peer group is too small to measure a spread: record
                    # the cap beside the evidence, so "differs from 2 peers but
                    # only HIGH" can be explained from the row itself.
                    evidence["thin_peer_group"] = thin_peer
                reason = _reason_text(
                    resolved, finding["perspective"], severity, current,
                    float(finding["baseline"]), finding["z"],
                    finding["peer_count"], interpretation)
                if resolution.applied:
                    reason += (f" Base severity {resolution.base.level} was "
                               f"changed to {severity} by the configured "
                               f"temporal-trend policy.")
                if dispersion is not None:
                    reason += " " + ZERO_SPREAD_POLICY + "."
                if thin_peer is not None and thin_peer.get("capped"):
                    reason += " " + thin_peer["policy"] + "."
                pct_cap = (finding.get("stats") or {}).get("pct_change_capped")
                if pct_cap:
                    # The change was real but the window's spread does not
                    # support the band it alone implies: state it, so the row
                    # never reads as "large change, no reason given".
                    evidence["pct_change_cap"] = pct_cap
                    reason += (" Percentage change "
                               f"({pct_cap['pct_change_score']:.2f}) is "
                               "clamped to the level the window's z-score "
                               f"supports ({pct_cap['score']:.2f}); the change "
                               "itself is still reported.")

                _upsert_alert(
                    db, stats, seen_keys,
                    hospital_id=hid, month=month,
                    perspective=finding["perspective"],
                    resolved=resolved,
                    severity=severity, score=float(finding["score"]),
                    method=finding["method"], current=current,
                    baseline=finding["baseline"], z=finding["z"],
                    peer_count=finding["peer_count"],
                    deviation_pct=((current - float(finding["baseline"]))
                                   / float(finding["baseline"]) * 100.0)
                    if finding["baseline"] else None,
                    direction=direction, interpretation=interpretation,
                    reason=reason, confidence=confidence, evidence=evidence,
                    now=now)

    # ── Deactivate previously-detected rows for this scope that vanished ──
    stale_query = db.query(QualityAlert).filter(
        QualityAlert.month == month, QualityAlert.active.is_(True))
    if hospital_id is not None:
        stale_query = stale_query.filter(QualityAlert.hospital_id == hospital_id)
    if code_filter is not None:
        # Only the indicators this run regenerated may be deactivated; the rest
        # of the hospital/month keeps its stored result exactly as it was.
        stale_query = stale_query.filter(
            QualityAlert.indicator_code.in_(code_filter))
    seen_set = set(seen_keys)
    for alert in stale_query.all():
        key = (alert.hospital_id, alert.indicator_code, alert.month, alert.perspective)
        if key in seen_set:
            continue
        canonical_code = alias_to_canonical.get(alert.indicator_code)
        if canonical_code is not None:
            # Only a row computed with the SAME formula may be folded: a code
            # whose definition was edited since the row was written represents
            # a different finding and keeps its own record.
            group = identity_index.get(alert.indicator_code) or {}
            stored_key = canonical_identity.identity_key(
                canonical_identity.alert_identity(alert))
            if group.get("key") != stored_key:
                canonical_code = None
        if canonical_code is not None:
            # A duplicate registration of a formula that IS still analysed.
            # Retire the row (never delete it: the row and its event trail stay
            # on record) after moving the investigation state to the canonical
            # row, so a reviewer's work is not lost in the deduplication.
            counterpart = db.query(QualityAlert).filter_by(
                hospital_id=alert.hospital_id, indicator_code=canonical_code,
                month=alert.month, perspective=alert.perspective).first()
            if counterpart is not None and counterpart.id != alert.id:
                _merge_investigation_state(db, counterpart, alert, now)
                stats.deduplicated += 1
        alert.active = False
        alert.updated_at = now
        stats.deactivated += 1

    stats.hospitals_scanned = (len(target_hospitals)
                               if target_hospitals is not None
                               else len(raw_by_hospital))
    db.commit()
    return stats.as_dict()


def scan_all_months(db: Session,
                    policy: Optional[PolicySnapshot] = None) -> dict:
    """Scan every reporting month that has data (catch-up / backfill).

    Used by the "Run Scan" button when no period is selected and by anyone
    wanting the full history covered without walking the dropdown. Returns
    per-month results plus aggregate counters.
    """
    months = sorted({
        row[0] for row in db.query(IndicatorValue.month).distinct().all()
        if row[0] and len(str(row[0])) == 7
    })
    per_month: List[dict] = []
    totals = {
        "months_scanned": len(months),
        "created": 0, "updated": 0, "deactivated": 0, "deduplicated": 0,
        "hospitals_scanned": 0, "perspectives_evaluated": 0,
        "errors": [],
    }
    if policy is None:
        try:
            # One snapshot for the whole backfill: every month is scanned
            # under the same configuration, not one read per month.
            policy = load_policy_snapshot(db)
        except PolicyUnavailable as exc:
            logger.error("Quality Alerts backfill aborted: %s", exc)
            policy = None  # each scan reports the failure per month
    for m in months:
        result = scan(db, m, policy=policy)
        per_month.append({"month": m, **{k: result.get(k) for k in
                         ("created", "updated", "deactivated",
                          "deduplicated", "error")}})
        for key in ("created", "updated", "deactivated", "deduplicated",
                    "perspectives_evaluated"):
            totals[key] += result.get(key) or 0
        totals["hospitals_scanned"] = max(
            totals["hospitals_scanned"], result.get("hospitals_scanned") or 0)
        if result.get("error"):
            totals["errors"].append(f"{m}: {result['error']}")
    totals["per_month"] = per_month
    return totals


def _upsert_alert(db: Session, stats: ScanStats,
                  seen_keys: List[Tuple[int, str, str, str]], *,
                  hospital_id: int, month: str, perspective: str,
                  resolved, severity: str, score: float, method: str,
                  current: float, baseline: Optional[float],
                  z: Optional[float], peer_count: Optional[int],
                  deviation_pct: Optional[float], direction: str,
                  interpretation: str, reason: str, confidence: str,
                  evidence: dict, now: datetime) -> None:
    key = (hospital_id, resolved.code, month, perspective)
    seen_keys.append(key)
    existing = db.query(QualityAlert).filter_by(
        hospital_id=hospital_id, indicator_code=resolved.code,
        month=month, perspective=perspective).first()
    definition = getattr(resolved, "definition", None)
    if existing is None:
        alert = QualityAlert(
            hospital_id=hospital_id, month=month, perspective=perspective,
            indicator_id=getattr(definition, "id", None),
            indicator_code=resolved.code, indicator_name=resolved.name,
            unit=getattr(resolved, "unit", None),
            formula=getattr(resolved, "formula", None),
            formula_version=getattr(resolved, "formula_version", None),
            severity=severity, score=score, method=method,
            current_value=current, baseline_value=baseline,
            deviation_pct=deviation_pct, z_score=z, peer_count=peer_count,
            direction=direction, interpretation=interpretation,
            reason=reason, confidence=confidence, evidence=evidence,
            status=STATUS_NEW, active=True, detected_at=now, updated_at=now,
        )
        db.add(alert)
        db.flush()
        db.add(QualityAlertEvent(
            alert_id=alert.id, from_status=None, to_status=STATUS_NEW,
            note="Alert detected by scan", actor="system", created_at=now))
        stats.created += 1
        return
    # Refresh statistics; investigation state (status/assignee/notes) is kept.
    existing.indicator_name = resolved.name
    existing.unit = getattr(resolved, "unit", None)
    existing.formula = getattr(resolved, "formula", None)
    existing.formula_version = getattr(resolved, "formula_version", None)
    existing.severity = severity
    existing.score = score
    existing.method = method
    existing.current_value = current
    existing.baseline_value = baseline
    existing.deviation_pct = deviation_pct
    existing.z_score = z
    existing.peer_count = peer_count
    existing.direction = direction
    existing.interpretation = interpretation
    existing.reason = reason
    existing.confidence = confidence
    existing.evidence = evidence
    existing.active = True
    existing.updated_at = now
    stats.updated += 1


# ── Investigation workflow (spec §10) ───────────────────────────────────────

def record_status_change(db: Session, alert: QualityAlert, new_status: str,
                         note: Optional[str] = None,
                         assignee: Optional[str] = None,
                         actor: str = "user") -> QualityAlertEvent:
    """Status/note/assignment transition + audit event. Never touches source data."""
    if new_status not in QUALITY_ALERT_STATUSES:
        raise ValueError(f"Unknown alert status: {new_status}")
    old_status = alert.status
    alert.status = new_status
    if assignee is not None:
        alert.assignee = assignee or None
    event = QualityAlertEvent(
        alert_id=alert.id, from_status=old_status, to_status=new_status,
        note=note, actor=actor)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def record_note(db: Session, alert: QualityAlert, note: str,
                actor: str = "user") -> QualityAlertEvent:
    """Append a note-only event (no status change)."""
    event = QualityAlertEvent(
        alert_id=alert.id, from_status=alert.status, to_status=None,
        note=note, actor=actor)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
