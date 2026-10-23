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
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config_utils import get_config_dict
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.engine import indicator_service, severity as severity_policy
from app.engine.anomaly import layered
from app.engine.pipeline import (
    get_all_hospital_data_for_month,
    get_enabled_values_for_hospital_month,
    get_historical_months,
)
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    QualityAlert,
    QualityAlertEvent,
    QUALITY_ALERT_STATUSES,
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
    return {
        "min_score": _f("alerts_min_score", 0.5),
        "min_peers": max(1, _i("alerts_min_peers", 2)),
        "min_history": max(2, _i("alerts_min_history", 3)),
        "history_window": max(3, _i("alerts_history_window", 12)),
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
    """
    return indicator_service.resolve_active_definitions(db)


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
    """z-score against peer mean (self excluded) + layered score + stats."""
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
        z = (current - mean) / std
        score = layered.score_from_z(z, z_threshold)
    return z, score, stats


def _history_score(spec_type: str, series: Sequence[float], current: float,
                   z_threshold: float) -> Tuple[Optional[float], str, Optional[float], dict]:
    """Score current against the hospital's own baseline window.

    Uses the layered engine's method auto-selection (rare-event counts ->
    rolling median+MAD, stable series -> %change, enough points -> IQR, else
    z-score) so the alert screen and Diagnostics agree.
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
    z = None
    if stats["std"] not in (None, 0):
        z = (float(current) - stats["mean"]) / stats["std"]
    method = layered.select_method(None, values, spec_type)
    score = layered._score_window(  # same-package reuse: one scoring implementation
        method, values, float(current), values[-1], z_threshold)
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
    perspectives_evaluated: int = 0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "hospitals_scanned": self.hospitals_scanned,
            "indicators": self.indicators,
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
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
         indicator_codes: Optional[Sequence[str]] = None) -> dict:
    """Run the multi-perspective scan for one reporting month and persist.

    Upserts one row per (hospital, indicator, month, perspective); reviewed
    rows that are no longer detected are deactivated, never deleted.

    ``indicator_codes`` narrows BOTH the regeneration and the deactivation
    sweep to those indicators. That is what makes a targeted recompute safe:
    re-checking the rows already known to be stale must never deactivate (or
    rewrite) a sibling indicator's untouched rows for the same hospital/month.
    """
    cfg = _alerts_config(db)
    stats = ScanStats()
    # Saved severity/trend configuration (System Control). A configuration
    # read failure aborts the scan with a visible error — the scan never falls
    # back to hidden hardcoded rules.
    try:
        sev_cfg = severity_policy.load_analysis_config(db)
    except severity_policy.AnalysisConfigError as exc:
        logger.error("Quality Alerts scan aborted: %s", exc)
        return {"error": str(exc), "configuration_error": True,
                **stats.as_dict()}
    # One Z-score threshold: the value the shared loader already validated and
    # clamped (thresholds.zscore_threshold) replaces this scan's own read.
    cfg["z_threshold"] = sev_cfg.zscore_threshold
    # Identifies this exact saved configuration; stored with every row.
    policy_fingerprint = severity_policy.policy_fingerprint(sev_cfg)
    registry = resolve_registry(db)
    # ALL catalog kinds are searched: rate specs + derivative definitions
    # (same table) AND raw data elements. Codes are unique across kinds in
    # practice; a raw element shadowing a registry code is skipped (the
    # managed definition wins) so one code can never overwrite the other's
    # persisted rows.
    def_codes = {d.code for d in registry}
    elements = [e for e in resolve_data_elements(db) if e.code not in def_codes]
    if not registry and not elements:
        return {"error": "Indicators Registry has no active definitions",
                **stats.as_dict()}
    scanned = list(registry) + list(elements)
    code_filter: Optional[set] = None
    if indicator_codes is not None:
        code_filter = {str(code) for code in indicator_codes}
        scanned = [item for item in scanned if item.code in code_filter]
        if not scanned:
            return {"error": "No matching indicators to scan",
                    **stats.as_dict()}
    stats.indicators = len(scanned)

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
        is_raw = getattr(resolved, "is_raw", False)
        peers_allowed = not (is_raw and not resolved.peer_comparison_enabled)
        history_allowed = not (is_raw and not resolved.historical_enabled)
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

            # ── Peer perspectives (current month) ──
            for perspective, attribute, _label in (
                    PEER_PERSPECTIVES if peers_allowed else ()):
                members = _peer_members(directory, hid, attribute, valid_values)
                if len(members) < cfg["min_peers"]:
                    continue  # peer group too small — avoid misleading comparisons
                z, score, pstats = _peer_score(
                    current, [v for _mid, v in members], cfg["z_threshold"])
                if score is None:
                    continue
                findings.append({
                    "perspective": perspective,
                    "score": score, "z": z, "method": "peer_zscore",
                    "baseline": pstats["mean"],
                    "peer_count": len(members),
                    "stats": pstats,
                    "peer_ids": [mid for mid, _v in members],
                })

            # ── History perspective (own prior periods) ──
            trend_assessment = None
            if history_allowed:
                if hid not in history_cache:
                    history_cache[hid] = get_historical_months(db, hid, month)
                history = history_cache[hid]
                # Both the alert history window and the System Control trend
                # window apply; the shorter one wins.
                window = min(int(cfg["history_window"]),
                             int(sev_cfg.trend.window))
                months_sorted = sorted(history.keys())[-window:]
                series: List[float] = []
                series_months: List[str] = []
                for m in months_sorted:
                    prior = _candidate(resolved, history[m], hid, m)
                    if prior.value is not None:
                        series.append(float(prior.value))
                        series_months.append(m)
                # ONE trend assessment per hospital/indicator, shared by every
                # perspective row persisted below (no second trend rule set).
                trend_assessment = severity_policy.assess_trend(
                    series, series_months, config=sev_cfg.trend,
                    bands=sev_cfg.trend_bands,
                    indicator_direction=direction)
                if len(series) >= cfg["min_history"]:
                    spec_type = getattr(resolved, "indicator_type", None) or "rate"
                    hscore, method, z, hstats = _history_score(
                        spec_type, series, current, cfg["z_threshold"])
                    if hscore is not None:
                        findings.append({
                            "perspective": PERSPECTIVE_HISTORY,
                            "score": hscore, "z": z, "method": method,
                            "baseline": hstats["mean"],
                            "peer_count": len(series),
                            "stats": hstats,
                            "history": list(zip(series_months, series)),
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
                severity = resolution.final.level
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
                if finding["peer_count"] < 4:
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
                evidence = dict(finding_evidence)
                if candidate.denominator is not None:
                    evidence["denominator"] = candidate.denominator
                if candidate.numerator is not None:
                    evidence["numerator"] = candidate.numerator
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
                reason = _reason_text(
                    resolved, finding["perspective"], severity, current,
                    float(finding["baseline"]), finding["z"],
                    finding["peer_count"], interpretation)
                if resolution.applied:
                    reason += (f" Base severity {resolution.base.level} was "
                               f"changed to {severity} by the configured "
                               f"temporal-trend policy.")

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
        if key not in seen_set:
            alert.active = False
            alert.updated_at = now
            stats.deactivated += 1

    stats.hospitals_scanned = (len(target_hospitals)
                               if target_hospitals is not None
                               else len(raw_by_hospital))
    db.commit()
    return stats.as_dict()


def scan_all_months(db: Session) -> dict:
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
        "created": 0, "updated": 0, "deactivated": 0,
        "hospitals_scanned": 0, "perspectives_evaluated": 0,
        "errors": [],
    }
    for m in months:
        result = scan(db, m)
        per_month.append({"month": m, **{k: result.get(k) for k in
                         ("created", "updated", "deactivated", "error")}})
        for key in ("created", "updated", "deactivated",
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
