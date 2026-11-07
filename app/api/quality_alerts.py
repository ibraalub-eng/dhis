"""Quality Alerts API — centralized risk-outlier monitoring (2026-10-21).

Read endpoints require ``quality_alerts.read``; scan + investigation workflow
require ``quality_alerts.write``. All indicator values rendered here were
computed by the shared engine at scan time (see app/engine/quality_alerts.py)
— this router never recalculates a clinical indicator.
"""
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_permission
from app.database import get_db
from app.eligibility import exclude_disabled
from app.engine import comparison_identity as identity_logic
from app.engine import quality_alerts as engine
from app.models import (
    QUALITY_ALERT_SEVERITIES,
    QUALITY_ALERT_STATUSES,
    FacilityOwnership,
    FacilityType,
    Governorate,
    Hospital,
    HospitalType,
    QualityAlert,
    QualityAlertAudit,
    QualityAlertEvent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quality-alerts", tags=["quality-alerts"],
                   dependencies=[Depends(require_permission("quality_alerts.read"))])

SEVERITY_ORDER = {name: i for i, name in enumerate(QUALITY_ALERT_SEVERITIES)}
# Issue rollup: the most "advanced" investigation state wins the display.
_STATUS_ROLLUP = (engine.STATUS_CONFIRMED, engine.STATUS_UNDER_REVIEW,
                  engine.STATUS_NEW, engine.STATUS_FALSE_POSITIVE,
                  engine.STATUS_RESOLVED)

INTERPRETATION_LEGEND = {
    "high_is_concern": {"en": "High values are undesirable — review indicated",
                        "ar": "القيم المرتفعة غير مرغوبة — يُوصى بالمراجعة"},
    "high_is_favorable": {"en": "High values are desirable — verify data accuracy",
                          "ar": "القيم المرتفعة مرغوبة — تحقق من دقة البيانات"},
    "low_is_concern": {"en": "Low values are undesirable — possible under-reporting",
                       "ar": "القيم المنخفضة غير مرغوبة — احتمال نقص في الإبلاغ"},
    "low_is_favorable": {"en": "Low values are desirable",
                         "ar": "القيم المنخفضة مرغوبة"},
    "outside_target_range": {"en": "Outside the configured target range",
                             "ar": "خارج نطاق الهدف المُعد"},
    "within_target_range": {"en": "Within the configured target range",
                            "ar": "ضمن نطاق الهدف المُعد"},
    "statistical_only": {"en": "No clinical direction configured — statistical only",
                         "ar": "لا توجد اتجاهات سريرية مُعدة — إحصائي فقط"},
}


# ── Shared helpers ──────────────────────────────────────────────────────────

def _name_by_id(db: Session, model) -> dict:
    return {row.id: row.name for row in db.query(model).all()}


# ── Query-parameter contract (D7) ─────────────────────────────────────────
# ONE rule for every optional filter, applied identically by both endpoints:
# an ABSENT parameter and an EMPTY value both mean "not set". A non-empty value
# must be one of the accepted forms below, otherwise the request is a 422 that
# names the parameter and the accepted forms. Before this, several filters
# compared the raw string against the column, so a typo or a malformed id came
# back as an empty list — indistinguishable from "no such data".
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CONFIDENCE_VALUES = ("high", "low")
VERY_HIGH_SCOPES = ("only", "mixed", "corroborated")
SORT_VALUES = ("severity", "hospital", "indicator", "detected")
ORDER_VALUES = ("asc", "desc")


def _is_unset(value) -> bool:
    """True for None and for a FastAPI ``Query`` default object.

    Direct callers (tests, internal previews) bypass dependency injection, so an
    omitted parameter still holds its ``Query(...)`` default instead of None.
    That means "not set" — never a value to validate.
    """
    return value is None or not isinstance(value, (str, int, float))


def _text(value) -> Optional[str]:
    """Strip an optional query value; None and blank both mean "not set"."""
    if _is_unset(value):
        return None
    text = str(value).strip()
    return text or None


def _choice_filter(name: str, value, allowed, noun: str = "values"):
    """Validate an enumerated query value; empty means "not set"."""
    text = _text(value)
    if text is None:
        return None
    if text not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Unknown " + name + ": " + repr(text)
                   + ". Valid " + noun + ": " + ", ".join(allowed) + ".")
    return text


def _month_filter(value):
    """``?month=`` as YYYY-MM; any other non-empty value is a 422."""
    text = _text(value)
    if text is None:
        return None
    if not MONTH_PATTERN.match(text):
        raise HTTPException(
            status_code=422,
            detail="Invalid month: " + repr(text)
                   + ". Expected YYYY-MM, for example 2026-08.")
    return text


def _positive_id_filter(name: str, value):
    """A stored primary key: ids are autoincrement, so only >= 1 exists.

    ``0`` used to fall through the ``if hospital_id:`` guard and silently
    disable the filter, while a negative id matched nothing and looked like
    "no data". Both are invalid input, not an empty result.
    """
    if _is_unset(value):
        return None
    if value <= 0:
        raise HTTPException(
            status_code=422,
            detail="Invalid " + name + ": " + str(value)
                   + ". Expected a positive integer id (stored ids start at 1).")
    return value


def _severity_filter(value):
    return _choice_filter("severity", value, QUALITY_ALERT_SEVERITIES)


def _confidence_filter(value):
    return _choice_filter("confidence", value, CONFIDENCE_VALUES)


def _very_high_scope_filter(value):
    return _choice_filter("very_high_scope", value, VERY_HIGH_SCOPES,
                          noun="scopes")


#: The ``?indicator_type=`` tokens the screen offers. They name HOW the alert's
#: indicator is registered — NOT the registry's own numeric ``indicator_type``
#: (count / rate / ...) — because the alert row itself distinguishes only these
#: two: a Data Element row is scanned from the raw catalog and has no
#: IndicatorDefinition FK, while a Derivative Indicator row always carries one.
INDICATOR_TYPE_VALUES = ("element", "derivative")


#: The stored review states ``?status=`` accepts. The list is the model's own
#: ``QUALITY_ALERT_STATUSES`` — the screen's Status options are rendered from
#: the same tuple via ``/quality-alerts/meta`` — so the two cannot drift.
STATUS_VALUES = QUALITY_ALERT_STATUSES


def _status_filter(value) -> Optional[str]:
    """Validate ``?status=`` into exactly one stored review state.

    Absent or empty means the OPEN view, the screen's default: every status
    except ``engine.CLOSED_STATUSES`` (Resolved and False Positive), which are
    still stored and are returned when asked for explicitly or when
    ``include_closed`` is set. Surrounding whitespace is trimmed; the names are
    case-sensitive because they are stored workflow labels ("Under Review",
    "Confirmed Issue"), and a lowercased copy must not be silently accepted as
    a different state.

    An unknown value is a 422 that names it and the supported statuses. Before
    this, any string was compared against the column, so a typo produced an
    empty list that looked exactly like "no alerts in that state".
    """
    if _is_unset(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text not in STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail="Unknown status: "
                   + repr(text)
                   + ". Valid statuses: "
                   + ", ".join(STATUS_VALUES) + ".")
    return text


def _indicator_type_filter(indicator_type) -> Optional[str]:
    """Validate ``?indicator_type=`` into one of ``INDICATOR_TYPE_VALUES``.

    Absent — including the empty string, which is how both the screen's "All
    types" option and an unset query parameter arrive — means "no type
    filter", the same optional-filter contract the other filters follow.
    Surrounding whitespace is trimmed, so ``?indicator_type=%20element`` is
    accepted; the tokens themselves are case-sensitive, so ``ELEMENT`` is
    rejected instead of being silently accepted as something else. Both
    endpoints call this, so they cannot disagree about what a value means.

    An unknown value is a 422 that names the offending token and the supported
    values: the filter used to fall through and return the UNFILTERED
    population, which made a typo look like "no such alerts".
    """
    if _is_unset(indicator_type):
        return None
    value = str(indicator_type).strip()
    if not value:
        return None
    if value not in INDICATOR_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail="Unknown indicator_type: "
                   + repr(value)
                   + ". Valid values: "
                   + ", ".join(INDICATOR_TYPE_VALUES) + ".")
    return value


def _perspective_filter(perspective) -> Optional[List[str]]:
    """Validate ``?perspective=`` into the comparison keys to OR together.

    One value is what a single-chip selection has always sent, so it keeps its
    exact meaning: the issue is in scope when that comparison fired on it.
    Several chips arrive as a repeated parameter
    (``?perspective=history&perspective=all``) and mean OR — an issue is in
    scope when AT LEAST ONE selected comparison fired on it. That is the union
    of the populations each chip lists on its own, so selecting a second chip
    can only widen the result and the per-chip counts stay additive. A
    comma-separated list is read the same way for scripts pasting keys.
    """
    if perspective is None:
        return None
    raw = [perspective] if isinstance(perspective, str) else list(perspective)
    keys: List[str] = []
    unknown: List[str] = []
    for item in raw:
        for key in str(item).split(","):
            key = key.strip()
            if not key or key in keys:
                continue
            if key not in engine.PERSPECTIVE_LABELS:
                unknown.append(key)
            else:
                keys.append(key)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail="Unknown perspective(s): "
                   + ", ".join(sorted(set(unknown)))
                   + ". Valid keys: "
                   + ", ".join(sorted(engine.PERSPECTIVE_LABELS)) + ".")
    return keys or None


def _apply_issue_filters(query, db: Session, month: Optional[str],
                         hospital_id: Optional[int], indicator: Optional[str],
                         severity: Optional[str],
                         perspective: Optional[list],
                         status: Optional[str], ownership_id: Optional[int],
                         governorate_id: Optional[int],
                         hospital_type_id: Optional[int],
                         confidence: Optional[str],
                         indicator_type: Optional[str],
                         active: bool, q: Optional[str],
                         include_closed: bool = False):
    query = query.join(Hospital, QualityAlert.hospital_id == Hospital.id)
    query = query.filter(Hospital.is_active.is_(True))
    if active:
        query = query.filter(QualityAlert.active.is_(True))
    if month:
        query = query.filter(QualityAlert.month == month)
    if hospital_id:
        query = query.filter(QualityAlert.hospital_id == hospital_id)
    if indicator:
        query = query.filter(QualityAlert.indicator_code == indicator)
    # NOTE: ``severity`` is NOT a SQL filter. The severity a screen shows and
    # counts is the band under the approved cap policy (``_effective_severity``),
    # which is derived per row — filtering the stored column here would list
    # rows the KPI cards no longer count. Callers narrow by severity with
    # ``_matches_severity`` after loading, exactly like the issue grouping.
    if perspective:
        # OR over the selected comparisons (see _perspective_filter): an issue
        # is in scope when at least one chosen comparison fired on it. This
        # narrows WHICH ROWS matched, so the whole-evidence map and the Very
        # High classification keep reading every row of the issue.
        keys = [perspective] if isinstance(perspective, str) else list(perspective)
        query = query.filter(QualityAlert.perspective.in_(keys))
    if status:
        # An explicit status is authoritative: it selects exactly those rows and
        # ``include_closed`` cannot widen it, so the pair is deterministic
        # instead of contradictory (the status wins). Callers validate the value
        # (_status_filter), so an unknown status can no longer come back as a
        # silent, empty list.
        query = query.filter(QualityAlert.status == status)
    elif not include_closed:
        # Open view: an alert a reviewer closed (Resolved / False Positive)
        # stops being raised here. The row is NOT deleted and its `active` flag
        # is untouched — only the open views stop presenting it, and asking for
        # that status explicitly (or include_closed) brings it back.
        query = query.filter(QualityAlert.status.notin_(engine.CLOSED_STATUSES))
    if confidence:
        # Rows written before confidence provenance existed are NULL, and the
        # screen presents those as "high" (_alert_dict). Choosing "high" must
        # include them, otherwise the filter would hide findings the same
        # screen labels high confidence.
        if confidence == "high":
            query = query.filter(or_(QualityAlert.confidence == "high",
                                     QualityAlert.confidence.is_(None)))
        else:
            query = query.filter(QualityAlert.confidence == confidence)
    if indicator_type:
        # Validated at the endpoint (_indicator_type_filter): only "element" or
        # "derivative" reach this point, so an unknown token can no longer fall
        # through and quietly return the unfiltered population.
        # Data Element rows are scanned from the raw catalog (no registry
        # definition), so indicator_id stays NULL on them; Derivative
        # Indicator rows always carry their IndicatorDefinition FK.
        if indicator_type == "element":
            query = query.filter(QualityAlert.indicator_id.is_(None))
        elif indicator_type == "derivative":
            query = query.filter(QualityAlert.indicator_id.isnot(None))
    if ownership_id:
        query = query.filter(Hospital.facility_ownership_id == ownership_id)
    if governorate_id:
        query = query.filter(Hospital.governorate_id == governorate_id)
    if hospital_type_id:
        query = query.filter(Hospital.hospital_type_id == hospital_type_id)
    if q and q.strip():
        # A blank search is "not set": it must not turn into LIKE '%%', which
        # is a filter on the name columns rather than no filter at all.
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Hospital.name.ilike(like),
            QualityAlert.indicator_name.ilike(like),
            QualityAlert.indicator_code.ilike(like),
        ))
    # The one shared disabled hospital/month rule: a month switched off for a
    # hospital is outside its reporting scope, so its stored alerts must not
    # be counted or listed here either. The row itself is kept (detail and
    # audit stay readable) — only active views stop presenting it.
    return exclude_disabled(db, query, QualityAlert)


def _current_policy(db: Session) -> dict:
    """Fingerprint of the severity/trend policy in effect right now.

    Loaded once per request. An unreadable configuration yields
    ``state="unavailable"`` so rows are never reported as current OR stale on a
    guess — the caller shows the configuration error instead.
    """
    from app.engine import severity as severity_policy

    try:
        cfg = severity_policy.load_analysis_config(db)
    except severity_policy.AnalysisConfigError as exc:
        logger.warning("Severity policy unavailable for staleness check: %s", exc)
        return {"state": "unavailable", "error": str(exc)}
    return {"state": "current",
            "fingerprint": severity_policy.policy_fingerprint(cfg)}


def _policy_state(stored: dict, policy: Optional[dict]) -> str:
    """``current`` / ``stale`` / ``unknown`` for one persisted snapshot.

    ``unknown`` means the comparison cannot be made: the stored row predates
    policy fingerprints, or the saved configuration itself cannot be read. Such
    rows are left unmarked rather than being accused of being out of date.
    """
    from app.engine import severity as severity_policy

    if not policy or policy.get("state") != "current":
        return "unknown"
    return severity_policy.stored_policy_state(stored, policy.get("fingerprint"))


def _stale_policy_rows(db: Session, policy: dict) -> List[dict]:
    """Active alert rows computed under an older policy.

    One entry per stale perspective row (an indicator can hold several), each
    carrying the (month, hospital, indicator) scope that produced it. Uses the
    same comparison as the list badges, so a recompute can only ever target
    rows the operator is actually shown as stale. Rows without a fingerprint
    (legacy) are ``unknown`` and never collected here: their severity was not
    produced by a policy that can be identified.
    """
    # Only the columns the comparison needs: no ORM entities, no full rows.
    # Closed findings are skipped: the recompute batch must target the rows the
    # operator is shown as stale, and a Resolved / skipped row is not shown.
    rows = (db.query(QualityAlert.month, QualityAlert.hospital_id,
                     QualityAlert.indicator_code, QualityAlert.formula,
                     QualityAlert.unit, QualityAlert.evidence)
            .filter(QualityAlert.active.is_(True),
                    QualityAlert.status.notin_(engine.CLOSED_STATUSES)).all())
    stale: List[dict] = []
    for month, hospital_id, code, formula, unit, evidence in rows:
        stored = (evidence or {}).get("severity_policy") or {}
        if _policy_state(stored, policy) != "stale":
            continue
        stale.append({"month": month, "hospital_id": hospital_id,
                      "indicator_code": code, "formula": formula,
                      "unit": unit})
    return stale


def _summarize_stale(rows: List[dict]) -> List[dict]:
    """Per-month stale counts for the preview (alert rows + canonical issues)."""
    buckets: dict = {}
    for row in rows:
        bucket = buckets.setdefault(
            row["month"], {"month": row["month"], "alerts": 0, "issues": set()})
        bucket["alerts"] += 1
        bucket["issues"].add((
            row["hospital_id"],
            _identity_key(row.get("formula"), row.get("unit"),
                          row["indicator_code"])))
    return [{"month": month, "alerts": data["alerts"],
             "issues": len(data["issues"])}
            for month, data in sorted(buckets.items())]


def _effective_severity(alert: QualityAlert) -> str:
    """The band the approved policy assigns to this stored row.

    The two caps (a comparison with no dispersion; a peer group too small to
    measure a spread) are recomputed from the row's own evidence, exactly as
    the scan applies them when it writes one — so a row written before a cap was
    approved is presented and counted under the policy in effect now, instead
    of keeping the dashboard's Very High Issues KPI and this screen's Very High
    KPIs at issues the policy refuses to grade. The stored band stays on the
    row and travels in ``severity_cap``.

    The TOP-BAND ELIGIBILITY GATE then runs for the history perspective only,
    with the inputs this row stored for itself: the comparison window, the
    value that was compared (``current_value``), the z threshold the scan
    scored with, and the perspective that produced the band. A peer, volume or
    stratified row is left to the approved peer policies and keeps its band;
    a history row whose window cannot decide keeps its band too.
    """
    evidence = alert.evidence or {}
    return engine.effective_severity(
        alert.severity, stats=evidence.get("stats"), method=alert.method,
        peer_count=alert.peer_count,
        series=engine.stored_series(evidence),
        current=alert.current_value, perspective=alert.perspective,
        threshold=engine.stored_threshold(evidence)) or alert.severity


def _severity_outputs(alert: QualityAlert, policy: Optional[dict] = None) -> dict:
    """(base, trend, final) severity for a stored alert, with legacy fallback.

    Rows written before severity provenance existed carry only ``severity``;
    they are reported honestly as a legacy row rather than being backfilled
    with an invented trend assessment.

    ``policy_state`` answers "was this row resolved under the settings in effect
    now?" WITHOUT rewriting it: a stale row keeps its stored severity and is
    only marked, so nothing historical changes silently.
    """
    from app.engine import severity as severity_policy

    evidence = alert.evidence or {}
    base = evidence.get("base_severity")
    final = evidence.get("final_severity")
    trend = evidence.get("trend_assessment")
    if not isinstance(base, dict) or not isinstance(final, dict):
        legacy = severity_policy.legacy_resolution(alert.severity)
        dumped = legacy.as_dict()
        return {
            "base_severity": dumped["base_severity"],
            "trend_assessment": None,
            "final_severity": dumped["final_severity"],
            "policy_state": "legacy",
            "severity_provenance": {
                "legacy": True,
                "policy": legacy.policy,
                "reason": legacy.reason,
            },
        }
    stored = evidence.get("severity_policy") or {}
    state = _policy_state(stored, policy)
    return {
        "base_severity": base,
        "trend_assessment": trend,
        "final_severity": final,
        "policy_state": state,
        "severity_provenance": {
            "legacy": False,
            "policy_state": state,
            **stored,
        },
    }


def _evidence_output(alert: QualityAlert) -> dict:
    """The stored evidence, with the read-time z provenance stated.

    A peer row written before the thin-peer no-z policy has no
    ``stats.z_provenance`` block, while its row still carries the stored z.
    The response adds the block (never to the database row, whose stored
    evidence stays exactly as written) so every consumer of ``evidence`` reads
    the same provenance the alert payload reports.
    """
    evidence = dict(alert.evidence or {})
    provenance = engine.z_score_provenance(
        alert.z_score, method=alert.method, peer_count=alert.peer_count)
    if provenance is not None:
        stats = dict(evidence.get("stats") or {})
        stored = stats.get("z_provenance")
        # A row written AFTER the policy already records its own provenance;
        # that block is the original record and is kept as-is.
        if not isinstance(stored, dict):
            stats["z_provenance"] = provenance
        evidence["stats"] = stats
    return evidence


def _alert_dict(alert: QualityAlert, policy: Optional[dict] = None,
                *, catalog_codes=None) -> dict:
    """One stored alert as the API publishes it.

    ``catalog_codes`` are the codes the definition gate may resolve from the
    live catalog (``engine.peer_definition_codes``). It only feeds the PEER
    eligibility verdict below: the band itself is decided by
    ``_effective_severity``, which is deliberately called WITHOUT peer evidence
    so a peer row can never change severity here.
    """
    effective = _effective_severity(alert)
    cap = engine.severity_cap(
        alert.severity, stats=(alert.evidence or {}).get("stats"),
        method=alert.method, peer_count=alert.peer_count,
        series=engine.stored_series(alert.evidence),
        current=alert.current_value, perspective=alert.perspective,
        threshold=engine.stored_threshold(alert.evidence))
    # The routed top-band verdict, stated even when nothing was capped: a
    # ``undecided`` history row must be readable as "the window could not judge"
    # beside its band, never as "no deviation".
    #
    # A PEER row is judged by the approved peer policy (Rule B) on the peer
    # group the scan stored on the row, after the definition gate; the gate
    # never moves the band, so ``severity`` above is unaffected.
    eligibility = engine.eligibility_assessment(
        alert.severity, stats=(alert.evidence or {}).get("stats"),
        method=alert.method, peer_count=alert.peer_count,
        series=engine.stored_series(alert.evidence),
        current=alert.current_value, perspective=alert.perspective,
        threshold=engine.stored_threshold(alert.evidence),
        **engine.peer_gate_inputs(alert, catalog_codes))
    # The z the approved thin-peer policy allows (see engine.effective_z_score):
    # a stored z from a group too small to measure a spread is presented as
    # WITHHELD, never as a measured magnitude.
    z_score = engine.effective_z_score(
        alert.z_score, method=alert.method, peer_count=alert.peer_count)
    return {
        "id": alert.id,
        "hospital_id": alert.hospital_id,
        "month": alert.month,
        "perspective": alert.perspective,
        "perspective_label": engine.PERSPECTIVE_LABELS.get(
            alert.perspective, alert.perspective),
        "indicator_id": alert.indicator_id,
        "indicator_code": alert.indicator_code,
        "indicator_name": alert.indicator_name,
        "unit": alert.unit or "",
        "formula": alert.formula,
        "formula_version": alert.formula_version,
        # The band under the policy in effect now (see _effective_severity);
        # ``stored_severity`` is what the row was written with, and
        # ``severity_cap`` explains a difference between the two.
        "severity": effective,
        # Alias of ``severity`` under the name the severity contract uses, so a
        # consumer reads the authoritative band by name instead of inferring it
        # from a docstring. ``stored_severity`` stays available to explain a cap.
        "effective_severity": effective,
        "stored_severity": alert.severity,
        # Which evidence answered this row's comparison (Phase 3): the stored
        # canonical layered result for an equivalent comparison, or this scan's
        # own calculation. ``canonical_evidence`` states why when it is not.
        "evidence_source": (alert.evidence or {}).get("evidence_source"),
        "canonical_evidence": (alert.evidence or {}).get("canonical_evidence"),
        "severity_cap": cap,
        "top_band_eligibility": eligibility,
        **_severity_outputs(alert, policy),
        "score": alert.score,
        "method": alert.method,
        "current_value": alert.current_value,
        "baseline_value": alert.baseline_value,
        "deviation_pct": alert.deviation_pct,
        "z_score": z_score,
        # What the row was written with — the same pairing as
        # severity/stored_severity, so a withheld z is reported as withheld
        # rather than as a comparison that never had one.
        "stored_z_score": alert.z_score,
        "z_provenance": engine.z_score_provenance(
            alert.z_score, method=alert.method, peer_count=alert.peer_count),
        "peer_count": alert.peer_count,
        "direction": alert.direction or "none",
        "interpretation": alert.interpretation or "statistical_only",
        "reason": alert.reason,
        "confidence": alert.confidence or "high",
        # Degenerate comparison (every value in the group identical => no
        # measurable scale). The level is capped at HIGH and this flag lets the
        # list say so instead of printing a bare 0 baseline as if the deviation
        # had been measured. Derived from the stored stats, so rows written
        # before the cap existed are labelled too.
        "zero_spread": engine.zero_spread((alert.evidence or {}).get("stats"),
                                          alert.method,
                                          engine.stored_series(alert.evidence)),
        # True for a peer comparison too small to measure a spread (the same
        # boundary that caps its band and withholds its z-score).
        "thin_peer_group": engine.cap_thin_peer(
            alert.severity, alert.peer_count, alert.method)[1] is not None,
        "dispersion": (alert.evidence or {}).get("dispersion"),
        # Effective comparison window / peer group behind this row (None on
        # rows written before provenance was recorded).
        "comparison_policy": (alert.evidence or {}).get("comparison_policy"),
        "status": alert.status,
        "assignee": alert.assignee,
        "detected_at": alert.detected_at.isoformat() if alert.detected_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }


def _matches_severity(alert: QualityAlert, severity: Optional[str]) -> bool:
    """Policy band test for the ``severity`` filter (see _effective_severity)."""
    if not severity:
        return True
    return _effective_severity(alert) == severity


def _identity_key(formula, unit, code) -> str:
    """Counting identity of one STORED finding.

    Equivalent registrations of one formula share this key, so a historical
    row on a duplicate code folds into the canonical issue instead of being
    counted again. The formula stored on the row is used — not the definition's
    current state — so editing a definition never re-files old findings under a
    formula they were not computed with. A row without a formula (raw data
    element) keeps its own code as its identity.
    """
    from app.engine import canonical_identity

    return canonical_identity.identity_key(
        canonical_identity.stored_identity(formula, unit, code))


def _issue_key(alert: QualityAlert) -> tuple:
    """Counting identity of one risk issue: hospital + canonical formula + month."""
    return (alert.hospital_id,
            _identity_key(alert.formula, alert.unit, alert.indicator_code),
            alert.month)


def _very_high_scope(rows: List[QualityAlert]) -> Optional[str]:
    """``only`` / ``mixed`` / ``None`` for ONE issue's whole evidence.

    ``only``  every perspective that fired is Very High;
    ``mixed`` a Very High perspective beside a lower band;
    ``None``  no perspective is Very High at all.

    Read from every stored row of the issue, never from the rows a filter let
    through: the Very High cards split one population, so a band filter must
    not turn an every-perspective issue into a mixed one.
    """
    bands = {_effective_severity(a) for a in rows}
    if "VERY_HIGH" not in bands:
        return None
    return "only" if bands == {"VERY_HIGH"} else "mixed"


def _very_high_corroborated(rows: List[QualityAlert]) -> bool:
    """``True`` when 2+ perspectives agreed the issue is Very High.

    ``_very_high_scope``'s ``only`` is satisfied vacuously by a single fired
    perspective: nothing else was compared, so nothing could come out lower.
    Only a second independent comparison grading the same value Very High
    corroborates the band, which is what the screen's third card lists.
    """
    return (len({a.perspective for a in rows}) > 1
            and _very_high_scope(rows) == "only")


def _very_high_only_categories(fits: dict, evidence: dict,
                               grouped: dict) -> dict:
    """``comparison_category`` of every Very-High-only issue, by issue key.

    ``fits``, ``evidence`` and ``grouped`` are the maps ``get_summary`` already
    builds, so this adds no classification of its own: it is the same lookup
    ``_comparison_shadow`` counts with, kept per issue because the breakdown
    cells are filters and must list exactly the issues they counted.
    """
    return {
        key: _issue_comparison_evidence(evidence.get(key) or grouped[key])[
            "comparison_category"]
        for key, band in fits.items() if band == "only"
    }


def _very_high_only_breakdown(*, total: int, corroborated: int,
                              single: int) -> dict:
    """The Very-High-only card's own split into its two subgroups.

    An issue is Very High only when every perspective that fired came out Very
    High, which leaves exactly two shapes: only ONE comparison fired (nothing
    was there to disagree, so ``single_perspective``), or two or more fired and
    all of them agreed (``corroborated``). Both are read off the same fitted
    bands and the same fired sets as the bucket itself, so they partition it:
    ``single + corroborated == total``. The card states that arithmetic rather
    than leaving a reader to add two independently counted numbers.

    The shares are published from here for the same reason: percentages of
    ``total`` rounded to one decimal, the corroborated one rounded and the
    single-perspective one its complement, so the pair always adds up to 100.
    ``total == 0`` yields zeros, never a division by zero and never a 0.0% that
    would read as "none of a measured population".
    """
    if total <= 0:
        return {"total": 0, "corroborated": 0, "single_perspective": 0,
                "corroborated_pct": 0.0, "single_perspective_pct": 0.0}
    corroborated_pct = round(100.0 * corroborated / total, 1)
    return {
        "total": total,
        "corroborated": corroborated,
        "single_perspective": single,
        "corroborated_pct": corroborated_pct,
        "single_perspective_pct": round(100.0 - corroborated_pct, 1),
    }


# ── Comparison identity (Step 10D-4 — SHADOW) ───────────────────────────────
# The published Very High corroboration KPI counts perspective LABELS. The
# helpers below measure the same population by the peer GROUP each row actually
# compared, using the pure module app/engine/comparison_identity.py.
#
# They are additive by design: every field they add is new, no published number
# changes, no identity is persisted and nothing is written. A nested or
# overlapping peer group is reported as such and never described as independent
# evidence; a temporal (history) row is a separate evidence class and is never
# counted as a peer comparison.
COMPARISON_CATEGORIES = ("multiple_peer", "single_peer", "temporal_only",
                         "unknown_identity", "invalid_evidence")
COMPARISON_RELATIONSHIPS = ("all_disjoint", "nested_only",
                            "overlapping_only", "mixed_relationships")


def _comparison_category_filter(value):
    """``?comparison_category=``: one evidence-breakdown category.

    The tokens are the five identity categories the breakdown cells publish,
    from the same module constant the summary counts with, so a cell and the
    filter it sends cannot drift. An unknown value is a 422 rather than an
    empty list that would read as "this category has no issues".
    """
    return _choice_filter("comparison_category", value, COMPARISON_CATEGORIES,
                          noun="categories")


def _comparison_policy_version(alert: QualityAlert) -> Optional[str]:
    """The policy version stored on this row's peer block, if it recorded one.

    Provenance only: the version never participates in the identity, so two
    rows that compared the same hospitals stay ONE identity across versions.
    """
    policy = (alert.evidence or {}).get("comparison_policy")
    if not isinstance(policy, dict):
        return None
    for block in (policy.get("peer"), policy):
        if isinstance(block, dict) and block.get("policy_version"):
            return str(block["policy_version"])
    return None


def _comparison_statistics(alert: QualityAlert, band: str) -> dict:
    """The stored outcomes two rows on ONE peer identity must agree on.

    Identity is the peer set alone, so a disagreement here is not a second
    comparison — it is a conflict on the same comparison, reported as such.
    """
    return {
        "severity": band,
        "stored_severity": alert.severity,
        "z_score": alert.z_score,
        "current_value": alert.current_value,
        "baseline_value": alert.baseline_value,
        "method": alert.method,
        "peer_count": alert.peer_count,
        "direction": alert.direction,
    }


def _issue_comparison_evidence(rows: List[QualityAlert]) -> dict:
    """Classify ONE issue's comparison evidence by peer identity (SHADOW).

    ``rows`` is the issue's WHOLE stored evidence — every perspective that
    fired, whatever band, filter or status scope — because a category describes
    the issue and not the rows a request let through.

    Categories are exclusive, in this precedence: ``multiple_peer`` (2+
    distinct valid peer identities), ``single_peer`` (exactly one),
    ``temporal_only`` (no peer, at least one usable history comparison),
    ``unknown_identity`` (no peer, no usable history, evidence that cannot say
    what was compared), ``invalid_evidence`` (nothing on the issue validates).

    Everything else is an orthogonal FLAG (``temporal_present``,
    ``unknown_evidence_present``, ``invalid_evidence_present``,
    ``evidence_conflict``, ``policy_mixed``): a peer comparison beside a broken
    or unreadable row keeps its count and the other evidence stays visible
    instead of being dropped or counted twice.

    Identity comes only from ``comparison_identity``, so identical peer ids
    collapse to one entry and a history row never becomes a peer identity.
    """
    identities: dict = {}
    temporal: List[dict] = []
    unknown: List[dict] = []
    invalid: List[dict] = []
    versions: set = set()
    for alert in rows:
        version = _comparison_policy_version(alert)
        if version:
            versions.add(version)
        identity = identity_logic.comparison_identity(alert)
        band = _effective_severity(alert)
        if identity.type == identity_logic.COMPARISON_TEMPORAL:
            # A trend comparison is its own evidence class: usable only when
            # the stored window can be read back, never a peer comparison.
            temporal.append({
                "perspective": alert.perspective,
                "state": ("valid" if engine.stored_series(alert.evidence)
                          else "unknown"),
                "band": band,
            })
            continue
        if identity.type == identity_logic.COMPARISON_PEER:
            entry = identities.get(identity.hash)
            if entry is None:
                entry = identities[identity.hash] = {
                    "identity": identity,
                    "perspectives": set(),
                    "versions": set(),
                    "statistics": [],
                    "bands": set(),
                    "row_ids": [],
                }
            entry["perspectives"].add(alert.perspective)
            if version:
                entry["versions"].add(version)
            statistics = _comparison_statistics(alert, band)
            if statistics not in entry["statistics"]:
                entry["statistics"].append(statistics)
            entry["bands"].add(band)
            if alert.id is not None:
                entry["row_ids"].append(alert.id)
            continue
        # Neither a peer group nor a trend: keep the row and say why it named
        # no comparison. ``invalid`` is contradictory evidence, ``unknown`` is
        # absent or truncated evidence — never silently dropped.
        bucket = (invalid if identity.state == identity_logic.EVIDENCE_INVALID
                  else unknown)
        bucket.append({"perspective": alert.perspective,
                       "reason": identity.reason,
                       "state": identity.state})

    order = {name: index for index, name in
             enumerate(engine.PERSPECTIVE_LABELS)}
    relations: dict = {key: [] for key in identities}
    kinds: set = set()
    keys = list(identities)
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            first = identities[left]["identity"]
            second = identities[right]["identity"]
            kind = identity_logic.pairwise_relationship(first, second)
            shared = len(set(first.peer_ids) & set(second.peer_ids))
            kinds.add(kind)
            relations[left].append({"identity": second.hash[:12],
                                    "relationship": kind,
                                    "shared_peers": shared})
            relations[right].append({"identity": first.hash[:12],
                                     "relationship": kind,
                                     "shared_peers": shared})

    views: List[dict] = []
    for hash_key, entry in sorted(
            identities.items(),
            key=lambda kv: (min(order.get(p, len(order))
                                for p in kv[1]["perspectives"]),
                            sorted(kv[1]["perspectives"]))):
        identity = entry["identity"]
        statistics = entry["statistics"]
        # Fields the rows on this ONE identity disagree about. Values only:
        # nothing is averaged, chosen or repaired here.
        conflicting: List[str] = []
        if len(statistics) > 1:
            conflicting = sorted(
                name for name in statistics[0]
                if len({row[name] for row in statistics}) > 1)
        perspectives = sorted(entry["perspectives"],
                              key=lambda p: (order.get(p, len(order)), p))
        views.append({
            "identity_hash": hash_key,
            "identity": hash_key[:12],
            "source": identity.source,
            "peer_count": len(identity.peer_ids),
            # Complete by construction: a group the helper cannot prove
            # complete is ``unknown`` and never reaches this list, so this list
            # is either absent (no identity) or the whole group.
            "peer_ids": list(identity.peer_ids),
            "perspectives": perspectives,
            "perspective_labels": [engine.PERSPECTIVE_LABELS.get(p, p)
                                   for p in perspectives],
            "policy_versions": sorted(entry["versions"]),
            "bands": sorted(entry["bands"]),
            "evidence_state": identity.state,
            "row_ids": sorted(entry["row_ids"]),
            "relationships": relations.get(hash_key, []),
            "evidence_conflict": bool(conflicting),
            "conflict_fields": conflicting,
        })

    peer_count = len(identities)
    temporal_valid = any(item["state"] == "valid" for item in temporal)
    if peer_count >= 2:
        category = "multiple_peer"
    elif peer_count == 1:
        category = "single_peer"
    elif temporal_valid:
        category = "temporal_only"
    elif unknown:
        category = "unknown_identity"
    elif invalid:
        category = "invalid_evidence"
    else:
        # No row at all cannot be classified; still one explicit category.
        category = "unknown_identity"

    if peer_count < 2:
        relationship_class = "not_applicable"
    elif kinds == {identity_logic.RELATIONSHIP_DISJOINT}:
        relationship_class = "all_disjoint"
    elif kinds == {identity_logic.RELATIONSHIP_NESTED}:
        relationship_class = "nested_only"
    elif kinds == {identity_logic.RELATIONSHIP_OVERLAPPING}:
        relationship_class = "overlapping_only"
    else:
        # More than one membership relationship (or an unreadable pair).
        relationship_class = "mixed_relationships"

    # The two-way view the Step 10D-2 audit reported (any shared-but-not-
    # contained pair counts as overlapping, otherwise nested), published
    # BESIDE the finer class so the two figures stay reconcilable instead of
    # one silently replacing the other.
    if peer_count < 2:
        relationship_summary = None
    elif identity_logic.RELATIONSHIP_OVERLAPPING in kinds:
        relationship_summary = "overlapping"
    elif identity_logic.RELATIONSHIP_NESTED in kinds:
        relationship_summary = "nested"
    elif kinds == {identity_logic.RELATIONSHIP_DISJOINT}:
        relationship_summary = "disjoint"
    else:
        relationship_summary = "unknown"

    return {
        "comparison_category": category,
        "distinct_peer_comparisons": peer_count,
        "temporal_present": bool(temporal),
        "temporal_state": (("valid" if temporal_valid else "unknown")
                           if temporal else None),
        "temporal_bands": sorted({item["band"] for item in temporal}),
        "unknown_evidence_present": bool(unknown),
        "unknown_perspectives": sorted({item["perspective"]
                                        for item in unknown}),
        "invalid_evidence_present": bool(invalid),
        "invalid_perspectives": sorted({item["perspective"]
                                        for item in invalid}),
        "evidence_conflict": any(view["evidence_conflict"]
                                 for view in views),
        "policy_mixed": len(versions) > 1,
        "policy_versions": sorted(versions),
        "relationship_class": relationship_class,
        "relationship_summary": relationship_summary,
        "comparison_identities": views,
        "perspective_count": len(rows),
        "distinct_perspective_count": len({a.perspective for a in rows}),
    }


def _comparison_shadow(fits: dict, grouped: dict, evidence: dict, *,
                       legacy_corroborated: int) -> dict:
    """Aggregate the SHADOW classification over the Very-High-only issues.

    ``fits`` is the same whole-evidence band map ``get_summary`` already uses,
    so the shadow population IS ``very_high_only_issues`` — never a re-filtered
    or re-counted one. ``balances`` states the arithmetic the payload publishes
    (each issue lands in exactly one category) instead of leaving a reader to
    add the parts.
    """
    by_category = {name: 0 for name in COMPARISON_CATEGORIES}
    by_relationship = {name: 0 for name in COMPARISON_RELATIONSHIPS}
    by_relationship_summary = {"nested": 0, "overlapping": 0,
                               "disjoint": 0, "unknown": 0}
    flags = {"with_temporal_evidence": 0, "with_unknown_evidence": 0,
             "with_invalid_evidence": 0, "with_evidence_conflict": 0,
             "with_mixed_policy_versions": 0}
    total = 0
    for key, band in fits.items():
        if band != "only":
            continue
        total += 1
        detail = _issue_comparison_evidence(
            evidence.get(key) or grouped.get(key) or [])
        by_category[detail["comparison_category"]] += 1
        if detail["comparison_category"] == "multiple_peer":
            by_relationship[detail["relationship_class"]] = (
                by_relationship.get(detail["relationship_class"], 0) + 1)
            summary_name = detail["relationship_summary"] or "unknown"
            by_relationship_summary[summary_name] = (
                by_relationship_summary.get(summary_name, 0) + 1)
        if detail["temporal_present"]:
            flags["with_temporal_evidence"] += 1
        if detail["unknown_evidence_present"]:
            flags["with_unknown_evidence"] += 1
        if detail["invalid_evidence_present"]:
            flags["with_invalid_evidence"] += 1
        if detail["evidence_conflict"]:
            flags["with_evidence_conflict"] += 1
        if detail["policy_mixed"]:
            flags["with_mixed_policy_versions"] += 1
    return {
        "basis": "distinct_peer_identities",
        "total": total,
        **by_category,
        "multiple_peer_by_relationship": by_relationship,
        "multiple_peer_by_relationship_summary": by_relationship_summary,
        **flags,
        "legacy_corroborated_perspective_labels": legacy_corroborated,
        "balances": sum(by_category.values()) == total,
    }


def _evidence_by_issue(db: Session, *, month: Optional[str],
                       hospital_id: Optional[int], indicator: Optional[str],
                       status: Optional[str],
                       ownership_id: Optional[int],
                       governorate_id: Optional[int],
                       hospital_type_id: Optional[int],
                       indicator_type: Optional[str], q: Optional[str],
                       include_closed: bool) -> dict:
    """Every perspective that fired on each issue in scope, by issue key.

    Same conjunctive filters as the list (month, hospital, indicator, geography,
    status scope, search) with the filters that narrow WHICH ROWS matched
    dropped: band, perspective and confidence say nothing about the rest of the
    issue's evidence. ``_very_high_scope`` and the perspective chips read this,
    so both screens grade an issue from the same rows.

    The review state is one of the CONJUNCTIVE filters, not one of the dropped
    ones: a request that lists ``status=Resolved`` must be graded from the rows
    that request lists, or none of its issues have an entry here at all. It is
    also what keeps a closed-status view from asking the cards about rows the
    open view deliberately hides.
    """
    query = _apply_issue_filters(
        db.query(QualityAlert), db, month, hospital_id, indicator,
        None, None, status, ownership_id, governorate_id, hospital_type_id,
        None, indicator_type, active=True, q=q, include_closed=include_closed)
    evidence: dict = {}
    for alert in query.all():
        evidence.setdefault(_issue_key(alert), []).append(alert)
    return evidence


def _canonical_info(db: Session, alert: QualityAlert) -> dict:
    """Canonical registration for one stored alert (identity from its row)."""
    info = engine.canonical_formula_index(db).get(
        _identity_key(alert.formula, alert.unit, alert.indicator_code))
    if info:
        return info
    return {"key": _identity_key(alert.formula, alert.unit,
                                 alert.indicator_code),
            "code": alert.indicator_code,
            "registered_codes": [alert.indicator_code]}


def _group_alerts(alerts: List[QualityAlert], names: dict,
                  policy: Optional[dict] = None,
                  formula_index: Optional[dict] = None,
                  evidence: Optional[dict] = None,
                  catalog_codes=None) -> List[dict]:
    """Group per-perspective rows into one risk issue per canonical formula.

    Spec §8: distinct perspectives are preserved as evidence; the dashboard
    shows a single issue with a primary severity and every perspective listed.

    The issue key is (hospital, CANONICAL FORMULA, month), not the registered
    code: a formula stored under several codes is one clinical finding, so it
    must produce one row, one issue and one KPI unit. ``formula_index`` is
    ``engine.canonical_formula_index``; without it each stored formula is still
    its own identity, only the representative code is unknown.
    """
    groups: dict = {}
    for alert in alerts:
        groups.setdefault(_issue_key(alert), []).append(alert)

    issues = []
    for key, rows in groups.items():
        hid, identity, month = key
        primary = max(rows, key=lambda a: SEVERITY_ORDER.get(
            _effective_severity(a), 0))
        code = primary.indicator_code
        statuses = {r.status for r in rows}
        rollup = next((s for s in _STATUS_ROLLUP if s in statuses), engine.STATUS_NEW)
        # Every perspective the issue fired, not only the rows matching the
        # active band filter: a Very High row beside a High one must show both,
        # or a mixed issue would look identical to an every-perspective one.
        perspectives = sorted(
            (_alert_dict(r, policy, catalog_codes=catalog_codes)
             for r in ((evidence or {}).get(key) or rows)),
            key=lambda d: -SEVERITY_ORDER.get(d["severity"], 0))
        stale_count = sum(1 for d in perspectives
                          if d.get("policy_state") == "stale")
        states = {d.get("policy_state") for d in perspectives}
        if stale_count:
            issue_state = "stale"
        elif "unknown" in states:
            issue_state = "unknown"
        elif "legacy" in states:
            issue_state = "legacy"
        else:
            issue_state = "current"
        row_codes = sorted({r.indicator_code for r in rows})
        info = (formula_index or {}).get(identity) or {
            "key": identity,
            "code": primary.indicator_code,
            "registered_codes": row_codes,
        }
        issues.append({
            "hospital_id": hid,
            "hospital": names.get(hid, f"Hospital #{hid}"),
            "indicator_code": code,
            "indicator_name": primary.indicator_name,
            # Canonical formula traceability: the representative registration,
            # the identity shared with Anomaly Diagnostics, and every code that
            # carries this formula.
            "canonical_code": info["code"],
            "canonical_key": info["key"],
            "registered_codes": sorted(set(info["registered_codes"])
                                      | set(row_codes)),
            "unit": primary.unit or "",
            "month": month,
            "primary_severity": _effective_severity(primary),
            # Which band to REPORT on. `primary_severity` and
            # `effective_severity` are the same value: the band after the
            # VERY-HIGH eligibility caps, i.e. what the screen shows and
            # what every KPI counts. `stored_severity` is the pre-cap value
            # on the row (quality_alerts.severity), kept so the difference
            # stays traceable instead of being silently overwritten.
            "effective_severity": _effective_severity(primary),
            "stored_severity": primary.severity,
            # A pre-cap row keeps its stored band on the row; the list marks the
            # difference instead of silently showing a different severity.
            "primary_severity_cap": engine.severity_cap(
                primary.severity,
                stats=(primary.evidence or {}).get("stats"),
                method=primary.method, peer_count=primary.peer_count,
                series=engine.stored_series(primary.evidence),
                current=primary.current_value,
                perspective=primary.perspective,
                threshold=engine.stored_threshold(primary.evidence)),
            "primary_perspective": primary.perspective,
            "interpretation": primary.interpretation or "statistical_only",
            "confidence": primary.confidence or "high",
            "status": rollup,
            "perspective_count": len(rows),
            # Computed under a different saved policy than the one in effect
            # now. Surfaced so the operator can re-run the scan deliberately;
            # nothing is recalculated or overwritten from here.
            "policy_state": issue_state,
            "policy_stale": stale_count > 0,
            "policy_stale_count": stale_count,
            "perspectives": perspectives,
            "alert_ids": [r.id for r in rows],
            "detected_at": max(
                (r.detected_at for r in rows if r.detected_at), default=None,
            ).isoformat() if any(r.detected_at for r in rows) else None,
        })
    return issues


# ── GET /quality-alerts/meta ────────────────────────────────────────────────

@router.get("/meta")
def get_meta(db: Session = Depends(get_db)):
    """Filter vocabulary + the governance-perspective availability note.

    Governance (managing authority) is reported UNAVAILABLE because the
    hospital metadata schema has no such column and ownership must never be
    assumed interchangeable with it (spec §3.D).
    """
    return {
        "perspectives": [
            {"key": engine.PERSPECTIVE_HISTORY,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_HISTORY],
             "available": True},
            {"key": engine.PERSPECTIVE_TYPE,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_TYPE],
             "available": True},
            {"key": engine.PERSPECTIVE_OWNERSHIP,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_OWNERSHIP],
             "available": True},
            {"key": engine.PERSPECTIVE_FACILITY_TYPE,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_FACILITY_TYPE],
             "available": True},
            {"key": engine.PERSPECTIVE_GOVERNORATE,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_GOVERNORATE],
             "available": True},
            {"key": engine.PERSPECTIVE_ALL,
             "label": engine.PERSPECTIVE_LABELS[engine.PERSPECTIVE_ALL],
             "available": True},
            {"key": "governance", "label": "Governance / managing authority",
             "available": False,
             "unavailable_reason": "No managing-authority metadata exists in the "
                                   "system; ownership is not assumed interchangeable."},
        ],
        "severities": list(QUALITY_ALERT_SEVERITIES),
        "statuses": list(QUALITY_ALERT_STATUSES),
        "interpretation_legend": INTERPRETATION_LEGEND,
        "methods": ["peer_zscore", "zscore", "robust_z", "iqr", "pct_change"],
    }


# ── GET /quality-alerts/summary ─────────────────────────────────────────────

@router.get("/summary")
def get_summary(
    month: Optional[str] = Query(
        None, description="YYYY-MM; any other non-empty value is a 422"),
    hospital_id: Optional[int] = Query(None),
    indicator: Optional[str] = Query(None),
    severity: Optional[str] = Query(
        None,
        description="LOW | MODERATE | HIGH | VERY_HIGH; empty = every "
                    "band. Any other value is a 422"),
    perspective: Optional[List[str]] = Query(
        None,
        description="comparison perspective key; repeat the parameter to "
                    "select several, OR-combined (any selected comparison "
                    "fired on the issue)"),
    status: Optional[str] = Query(
        None,
        description="exactly one stored review state; empty = the open view "
                    "(Resolved and False Positive excluded). An unknown value "
                    "is a 422"),
    ownership_id: Optional[int] = Query(None),
    governorate_id: Optional[int] = Query(None),
    hospital_type_id: Optional[int] = Query(None),
    confidence: Optional[str] = Query(
        None, description="high | low; empty = either. Any other value is a 422"),
    indicator_type: Optional[str] = Query(
        None,
        description="element (raw data element) | derivative (registered "
                    "indicator); any other non-empty value is a 422"),
    very_high_scope: Optional[str] = Query(
        None,
        description="only = every fired perspective is Very High; "
                    "mixed = a Very High perspective beside a lower band; "
                    "corroborated = only, with 2+ perspectives agreeing; "
                    "empty = no scope. Any other value is a 422"),
    comparison_category: Optional[str] = Query(
        None,
        description="multiple_peer | single_peer | temporal_only | "
                    "unknown_identity | invalid_evidence; lists the Very "
                    "High only issues whose comparison evidence is in that "
                    "category. Empty = no category filter. Any other value "
                    "is a 422"),
    q: Optional[str] = Query(None),
    include_closed: bool = Query(
        False,
        description="with no status selected, also count Resolved / False "
                    "Positive; ignored when status is set"),
    db: Session = Depends(get_db),
):
    """Dashboard KPIs over OPEN alerts, respecting every active filter.

    Closed findings (``engine.CLOSED_STATUSES``) are not counted here unless
    ``include_closed`` is set: an alert a reviewer resolved or skipped is no
    longer an open one, so it must not keep inflating the KPIs. The rows stay
    stored and are counted again when their status is requested explicitly.

    Two units exist on this screen and the response keeps them apart:

    * **perspective rows** — one row per comparison group (history, all,
      governorate…), the evidence unit. ``total_active`` / ``new_alerts`` /
      ``unresolved`` count these, as do ``very_high_rows`` (the rows whose
      band is VERY_HIGH) and the per-perspective chip tally.
    * **risk issues** — one per (hospital, CANONICAL FORMULA, month), whatever
      number of perspectives fired and however many registry codes carry that
      formula. The issue table, its pager and the KPI cards use these:
      ``total_issues`` / ``very_high_issues`` / ``new_issues`` /
      ``unresolved_issues``.

    This screen has no "red" concept: VERY_HIGH is one band, named for itself
    everywhere. ``very_high_issues`` counts ISSUES in that band, and the row
    count lives under its own explicit name, ``very_high_rows``, because one
    issue can carry several Very High evidence rows. It used to be published as
    ``red_alerts`` beside ``red_issues``, which read 1686 beside 1217 and made
    one band look like two severities; those aliases are gone.

    Counting policy, shared by every issue total here and by the dashboard's
    Very High Issues KPI: an issue is one (hospital, canonical formula, month);
    a Very High issue is one such issue with at least one VERY_HIGH perspective
    row. Duplicate registrations of a formula never add an issue.

    Both are derived from the same filtered rows and grouped exactly like
    ``/issues``, so ``total_issues`` always equals that endpoint's ``total``.

    ``very_high_only_issues`` / ``mixed_severity_issues`` split the selected
    issues by their whole evidence: Very-High-only means every perspective that
    fired on the issue is Very High, mixed means it also carries a lower band.
    Read literally, Very-High-only is also true of an issue where only ONE
    perspective fired — nothing else was compared, so nothing came out lower.
    ``very_high_single_perspective_issues`` counts those apart (by perspective)
    so the bucket can never be read as agreement between comparisons.
    ``very_high_only_by_perspectives`` keeps that same bucket by the SET of
    comparisons that fired — one comparison alone, history + all hospitals,
    three peers at once — and ``very_high_only_corroborated_issues`` is the
    part of it where two or more independent comparisons all graded Very High.
    ``very_high_only_breakdown`` is that split as the card states it: the
    corroborated and single-perspective counts with their shares of
    ``very_high_only_issues``, so the two subgroups visibly add up to it.
    KPI SCOPE (D2) — two populations, stated once here so nothing downstream
    has to guess:
      * ``total_issues`` and every row-unit field describe the FILTERED ISSUE
        population: the general scope filters plus the selected band, the
        selected perspectives and the active card scope.
      * ``very_high_issues``, ``very_high_only_issues``,
        ``mixed_severity_issues``, ``very_high_only_corroborated_issues`` and
        the breakdowns below describe the VERY HIGH KPI POPULATION: the same
        general scope filters, but neither the selected band nor the selected
        perspectives narrow it, and an active card scope does not narrow it
        either — the card the operator just clicked must keep its number.
        Choosing HIGH or MODERATE therefore moves ``total_issues`` and the
        table, never the Very High cards.
    Filters that narrow which ROWS matched (severity, perspective, status,
    confidence) say nothing about what the issue contains, so they are dropped
    when that split is computed. Under the default Very High filter with no
    perspective selected the two populations coincide and the split is a
    partition of ``total_issues``; otherwise the split describes the Very High
    part of the scope and need not add up to it.

    ``very_high_scope`` is the same split used as a FILTER (the clickable
    cards): it narrows the list, the pager and ``total_issues`` to one bucket,
    while the two bucket counts keep describing the whole Very High population
    so the card that was clicked still shows its number. It is read from each
    issue's whole evidence, exactly like the split. ``corroborated`` selects the
    part of Very-High-only that two or more perspectives agreed on, which is the
    only reading of that bucket that is not vacuous.
    ``comparison_category`` uses the evidence breakdown as a FILTER: it lists
    the Very High only issues whose comparison evidence falls in that one
    category, while the five cell counts keep describing the whole Very High
    population so the cell that was clicked still shows its number.
    """
    perspective = _perspective_filter(perspective)
    indicator_type = _indicator_type_filter(indicator_type)
    status = _status_filter(status)
    month = _month_filter(month)
    severity = _severity_filter(severity)
    confidence = _confidence_filter(confidence)
    very_high_scope = _very_high_scope_filter(very_high_scope)
    comparison_category = _comparison_category_filter(comparison_category)
    hospital_id = _positive_id_filter("hospital_id", hospital_id)
    ownership_id = _positive_id_filter("ownership_id", ownership_id)
    governorate_id = _positive_id_filter("governorate_id", governorate_id)
    hospital_type_id = _positive_id_filter("hospital_type_id",
                                            hospital_type_id)
    # ONE query, TWO populations (see KPI SCOPE above): the rows are fetched
    # under the general scope filters only, then split in Python. The band and
    # perspective selections narrow the filtered issue population; the Very
    # High KPI population keeps every perspective and every band, so choosing
    # HIGH cannot make a Very High card read zero.
    query = db.query(QualityAlert)
    query = _apply_issue_filters(
        query, db, month, hospital_id, indicator, None, None,
        status, ownership_id, governorate_id, hospital_type_id, confidence,
        indicator_type, active=True, q=q, include_closed=include_closed)
    scope_rows = query.all()
    rows = [a for a in scope_rows
            if (not perspective or a.perspective in perspective)
            and _matches_severity(a, severity)]
    vh_rows = scope_rows
    # Direct calls (tests, internal previews) bypass FastAPI, which injects the
    # Query defaults: an unresolved default is "no scope", never a filter value.
    if not isinstance(very_high_scope, str):
        very_high_scope = None

    # Group with the same key and the same status rollup as _group_alerts so
    # the summary can never disagree with the table it sits above. The key is
    # the canonical formula: duplicate registrations are one unique issue.
    grouped: dict = {}
    for alert in rows:
        grouped.setdefault(_issue_key(alert), []).append(alert)

    # The Very High population the cards count: the same scope, no band and no
    # perspective filter. It is a superset of ``grouped``, so a card's number
    # can never be smaller than the part of it the table is currently showing.
    vh_grouped: dict = {}
    for alert in vh_rows:
        vh_grouped.setdefault(_issue_key(alert), []).append(alert)

    # Is a Very High issue Very High on its own, or because one perspective
    # escalated while the others stayed lower? That is a property of the ISSUE,
    # so it is read from every perspective that fired — never from the rows a
    # band filter let through.
    evidence = _evidence_by_issue(
        db, month=month, hospital_id=hospital_id, indicator=indicator,
        status=status,
        ownership_id=ownership_id, governorate_id=governorate_id,
        hospital_type_id=hospital_type_id, indicator_type=indicator_type,
        q=q, include_closed=include_closed)
    fits = {key: _very_high_scope(evidence.get(key) or issue_rows)
            for key, issue_rows in vh_grouped.items()}
    very_high_only = sum(1 for band in fits.values() if band == "only")
    mixed = sum(1 for band in fits.values() if band == "mixed")
    very_high_issues = very_high_only + mixed

    # "Every perspective is Very High" is vacuous when only one perspective
    # fired, and that is the common case on the live store: a hospital-history
    # outlier has no peers to be checked against, so it is not corroborated by
    # them either. Counted by label so the screen can name what the bucket is
    # mostly made of instead of implying cross-perspective agreement.
    #
    # The same bucket kept by the SET of perspectives that fired, not one label:
    # "Hospital history" alone is a single comparison nothing could disagree
    # with, "Hospital history + All hospitals" is two comparisons that both
    # graded Very High, which is the only reading of "every perspective" that
    # says anything. Ordered by the registry (never by row order), so issues
    # that fired on the same comparisons group into one line.
    perspective_order = {p: i for i, p in
                         enumerate(engine.PERSPECTIVE_LABELS)}
    single_perspective: dict = {}
    by_fired: dict = {}
    for key, band in fits.items():
        if band != "only":
            continue
        fired = sorted({a.perspective
                        for a in evidence.get(key) or vh_grouped[key]},
                       key=lambda p: (perspective_order.get(
                           p, len(perspective_order)), p))
        labels = tuple(engine.PERSPECTIVE_LABELS.get(p, p) for p in fired)
        if len(fired) == 1:
            single_perspective[labels[0]] = single_perspective.get(labels[0], 0) + 1
        by_fired[labels] = by_fired.get(labels, 0) + 1
    only_by_fired = [
        {"perspectives": list(labels), "issues": count,
         "corroborated": len(labels) > 1}
        for labels, count in sorted(by_fired.items(),
                                    key=lambda kv: (-kv[1], kv[0]))
    ]
    # The card's split, from the SAME fitted bands and fired sets as the bucket
    # itself: corroborated is the multi-perspective part of the fired sets, and
    # single-perspective is what that leaves — never a second pass that could
    # count a different population.
    corroborated = sum(entry["issues"] for entry in only_by_fired
                       if entry["corroborated"])
    single_total = sum(single_perspective.values())
    only_breakdown = _very_high_only_breakdown(
        total=very_high_only, corroborated=corroborated, single=single_total)
    # SHADOW (Step 10D-4): the same Very-High-only population, counted by the
    # peer group each row actually compared instead of by perspective label.
    # Additive only - ``corroborated`` above is still the published number,
    # and ``very_high_only_corroborated_issues`` still returns it unchanged.
    comparison_shadow = _comparison_shadow(
        fits, vh_grouped, evidence, legacy_corroborated=corroborated)

    # The evidence-breakdown cells are filters too: each one lists exactly the
    # Very-High-only issues its category counted, read from the same identity
    # classification the shadow publishes (never a second pass). The cell
    # counts keep describing the whole Very High population, like the cards,
    # so the clicked cell still shows its number.
    if comparison_category:
        categories = _very_high_only_categories(fits, evidence, vh_grouped)
        grouped = {key: value for key, value in grouped.items()
                   if categories.get(key) == comparison_category}
        rows = [a for a in rows if grouped.get(_issue_key(a)) is not None]

    # The clickable cards narrow the LIST, not each other: with "Mixed" active
    # the split above still describes the whole Very High population, so the
    # other card keeps the number the operator just clicked beside.
    if very_high_scope == "corroborated":
        grouped = {key: value for key, value in grouped.items()
                   if _very_high_corroborated(evidence.get(key) or value)}
    elif very_high_scope:
        grouped = {key: value for key, value in grouped.items()
                   if fits.get(key) == very_high_scope}
    if very_high_scope:
        rows = [a for a in rows if grouped.get(_issue_key(a)) is not None]

    rolled = []
    for issue_rows in grouped.values():
        statuses = {a.status for a in issue_rows}
        rolled.append((issue_rows, next(
            (s for s in _STATUS_ROLLUP if s in statuses), engine.STATUS_NEW)))

    by_perspective: dict = {}
    for alert in rows:
        by_perspective[alert.perspective] = by_perspective.get(alert.perspective, 0) + 1

    very_high_rows = sum(1 for a in rows
                         if _effective_severity(a) == "VERY_HIGH")

    return {
        # Perspective-row units (evidence).
        "total_active": len(rows),
        # Very High evidence rows. Named for the band and the unit: one issue
        # can carry several Very High rows, so this must not be compared with,
        # or shown as, the Very High issue count below.
        "very_high_rows": very_high_rows,
        "new_alerts": sum(1 for a in rows if a.status == engine.STATUS_NEW),
        "unresolved": sum(
            1 for a in rows
            if a.status not in (engine.STATUS_RESOLVED, engine.STATUS_FALSE_POSITIVE)),
        "by_perspective": by_perspective,
        # Under the policy band, like every other count on this screen.
        "by_severity": {
            sev: sum(1 for a in rows if _effective_severity(a) == sev)
            for sev in QUALITY_ALERT_SEVERITIES
        },
        # Issue units (what the screen lists, pages and counts).
        "total_issues": len(grouped),
        "very_high_issues": very_high_issues,
        "very_high_only_issues": very_high_only,
        "very_high_single_perspective_issues": single_total,
        "very_high_single_perspective_by_perspective": single_perspective,
        # The Very-High-only card's split, counts and shares together: the card
        # shows a total, so it must also show the parts it is made of and that
        # neither part is described as agreement when only one comparison fired.
        "very_high_only_breakdown": only_breakdown,
        # Which comparisons fired together on each Very-High-only issue. Sums to
        # very_high_only_issues; the entries with more than one perspective are
        # the ones actually corroborated by an independent comparison.
        "very_high_only_by_perspectives": only_by_fired,
        "very_high_only_corroborated_issues": corroborated,
        # SHADOW (Step 10D-4): identity-based classification of the SAME
        # Very-High-only issues. New fields beside the published KPI above,
        # which keeps its perspective-label meaning and value.
        "very_high_multiple_peer_issues": comparison_shadow["multiple_peer"],
        "very_high_single_peer_issues": comparison_shadow["single_peer"],
        "very_high_temporal_only_issues":
            comparison_shadow["temporal_only"],
        "very_high_unknown_identity_issues":
            comparison_shadow["unknown_identity"],
        "very_high_invalid_evidence_issues":
            comparison_shadow["invalid_evidence"],
        "very_high_comparison_shadow": comparison_shadow,
        "mixed_severity_issues": mixed,
        "new_issues": sum(1 for _, status in rolled if status == engine.STATUS_NEW),
        "unresolved_issues": sum(
            1 for _, status in rolled
            if status not in (engine.STATUS_RESOLVED, engine.STATUS_FALSE_POSITIVE)),
        "hospitals_affected": len({a.hospital_id for a in rows}),
        # Indicators are counted by canonical formula, not by registered code:
        # one formula reported under three codes is still one indicator.
        "indicators_affected": len({
            _identity_key(a.formula, a.unit, a.indicator_code) for a in rows
        }),
    }


# ── GET /quality-alerts/issues ──────────────────────────────────────────────

@router.get("/issues")
def list_issues(
    month: Optional[str] = Query(
        None, description="YYYY-MM; any other non-empty value is a 422"),
    hospital_id: Optional[int] = Query(None),
    indicator: Optional[str] = Query(None),
    severity: Optional[str] = Query(
        None,
        description="LOW | MODERATE | HIGH | VERY_HIGH; empty = every "
                    "band. Any other value is a 422"),
    perspective: Optional[List[str]] = Query(
        None,
        description="comparison perspective key; repeat the parameter to "
                    "select several, OR-combined (any selected comparison "
                    "fired on the issue)"),
    status: Optional[str] = Query(
        None,
        description="exactly one stored review state; empty = the open view "
                    "(Resolved and False Positive excluded). An unknown value "
                    "is a 422"),
    ownership_id: Optional[int] = Query(None),
    governorate_id: Optional[int] = Query(None),
    hospital_type_id: Optional[int] = Query(None),
    confidence: Optional[str] = Query(
        None, description="high | low; empty = either. Any other value is a 422"),
    indicator_type: Optional[str] = Query(
        None,
        description="element (raw data element) | derivative (registered "
                    "indicator); any other non-empty value is a 422"),
    very_high_scope: Optional[str] = Query(
        None,
        description="only = every fired perspective is Very High; "
                    "mixed = a Very High perspective beside a lower band; "
                    "corroborated = only, with 2+ perspectives agreeing; "
                    "empty = no scope. Any other value is a 422"),
    comparison_category: Optional[str] = Query(
        None,
        description="multiple_peer | single_peer | temporal_only | "
                    "unknown_identity | invalid_evidence; lists the Very "
                    "High only issues whose comparison evidence is in that "
                    "category. Empty = no category filter. Any other value "
                    "is a 422"),
    q: Optional[str] = Query(None),
    include_closed: bool = Query(
        False,
        description="with no status selected, also list Resolved / False "
                    "Positive; ignored when status is set"),
    sort: str = Query(
        "severity", description="severity | hospital | indicator | detected"),
    order: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(
        50, ge=0, le=200,
        description="rows per page; 0 = every matching issue (the screen's "
                    "\"All\" page size)",
    ),
    db: Session = Depends(get_db),
):
    """Grouped OPEN risk issues (one per hospital+indicator+month), paged.

    A finding closed by a reviewer (Resolved / False Positive) leaves this list;
    ``status=Resolved`` or ``include_closed=true`` brings closed rows back.

    ``page_size=0`` is the screen's "All" page size: every matching issue in one
    response. Grouping above already loads and sorts the whole filtered set, so
    this skips the slice — it never widens the query.
    """
    perspective = _perspective_filter(perspective)
    indicator_type = _indicator_type_filter(indicator_type)
    status = _status_filter(status)
    month = _month_filter(month)
    severity = _severity_filter(severity)
    confidence = _confidence_filter(confidence)
    very_high_scope = _very_high_scope_filter(very_high_scope)
    comparison_category = _comparison_category_filter(comparison_category)
    hospital_id = _positive_id_filter("hospital_id", hospital_id)
    ownership_id = _positive_id_filter("ownership_id", ownership_id)
    governorate_id = _positive_id_filter("governorate_id", governorate_id)
    hospital_type_id = _positive_id_filter("hospital_type_id",
                                            hospital_type_id)
    sort = _choice_filter("sort", sort, SORT_VALUES) or "severity"
    order = _choice_filter("order", order, ORDER_VALUES) or "desc"
    query = db.query(QualityAlert).options(selectinload(QualityAlert.hospital))
    query = _apply_issue_filters(
        query, db, month, hospital_id, indicator, severity, perspective,
        status, ownership_id, governorate_id, hospital_type_id, confidence,
        indicator_type, active=True, q=q, include_closed=include_closed)
    # ``severity`` is not a SQL filter (see _apply_issue_filters), so these rows
    # are every band; the whole-evidence map is built from them, and the band is
    # only applied to WHICH ROWS matched — the issue's other perspectives stay
    # visible on its chips and in the detail modal.
    rows = query.all()
    # Direct calls (tests, internal previews) bypass FastAPI, which injects the
    # Query defaults: an unresolved default is "no scope", never a filter value.
    if not isinstance(very_high_scope, str):
        very_high_scope = None
    # Same whole-evidence map the summary grades from (band, perspective and
    # confidence dropped), so a card's number and this table's rows are always
    # the same population.
    evidence = _evidence_by_issue(
        db, month=month, hospital_id=hospital_id, indicator=indicator,
        status=status,
        ownership_id=ownership_id, governorate_id=governorate_id,
        hospital_type_id=hospital_type_id, indicator_type=indicator_type,
        q=q, include_closed=include_closed)
    alerts = [a for a in rows if _matches_severity(a, severity)]
    if comparison_category:
        # A category is only defined inside Very High only (the five cells
        # partition that bucket), so an issue carrying a lower band is never
        # listed under a cell that did not count it. Read from the issue's
        # whole evidence, exactly like the summary's cells.
        by_key: dict = {}
        for alert in alerts:
            by_key.setdefault(_issue_key(alert), []).append(alert)
        matched = {
            key for key, issue_rows in by_key.items()
            if _very_high_scope(evidence.get(key) or issue_rows) == "only"
            and _issue_comparison_evidence(
                evidence.get(key) or issue_rows)["comparison_category"]
            == comparison_category
        }
        alerts = [a for a in alerts if _issue_key(a) in matched]
    # Every issue in ``alerts`` has an entry in ``evidence`` — it is built from
    # a superset of the same conjunctive filters. Reading through ``.get``
    # keeps that a guarantee instead of an assumption: a scope lookup must
    # never turn one absent row into a 500 for the whole table.
    if very_high_scope == "corroborated":
        alerts = [a for a in alerts
                  if _very_high_corroborated(
                      evidence.get(_issue_key(a)) or [])]
    elif very_high_scope:
        alerts = [a for a in alerts
                  if _very_high_scope(
                      evidence.get(_issue_key(a)) or []) == very_high_scope]
    names = _name_by_id(db, Hospital)
    issues = _group_alerts(alerts, names, _current_policy(db),
                           engine.canonical_formula_index(db),
                           evidence=evidence,
                           catalog_codes=engine.peer_definition_codes(db))

    reverse = order != "asc"
    if sort == "hospital":
        issues.sort(key=lambda i: i["hospital"], reverse=reverse)
    elif sort == "indicator":
        issues.sort(key=lambda i: (i["indicator_name"] or "").lower(), reverse=reverse)
    elif sort == "detected":
        issues.sort(key=lambda i: i["detected_at"] or "", reverse=reverse)
    else:  # severity (default)
        issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["primary_severity"], 0),
                                   i["detected_at"] or ""), reverse=reverse)

    total = len(issues)
    if page_size:
        start = (page - 1) * page_size
        page_items = issues[start:start + page_size]
    else:
        # "All": one page holding every matching issue.
        page_items = issues

    # SHADOW (Step 10D-4): comparison identity per returned issue, read from
    # the issue's WHOLE stored evidence map (``evidence``) and never from the
    # rows this request's band/perspective filter let through. Additive: no
    # existing key changes and no finding is added, removed or re-paged.
    owner = {alert.id: key for key, issue_rows in evidence.items()
             for alert in issue_rows}
    for item in page_items:
        key = owner.get((item.get("alert_ids") or [None])[0])
        item["comparison_evidence"] = _issue_comparison_evidence(
            evidence.get(key) or [])

    # Inline trend per row (one small series each) so the list itself shows
    # whether a finding is a one-month spike or a sustained problem. Only the
    # rows actually returned are computed — one page, or the whole set under
    # "All"; a failure here degrades to "no trend" rather than hiding the
    # issues. The full peer comparison lives in the detail.
    by_id = {a.id: a for a in alerts}
    page_alerts = [by_id[item["alert_ids"][0]] for item in page_items
                   if item.get("alert_ids")]
    try:
        sparklines = engine.sparkline_series(db, page_alerts)
    except Exception:  # pragma: no cover - supplementary data
        logger.exception("Quality alert sparklines failed")
        sparklines = {}
    for item in page_items:
        item["sparkline"] = sparklines.get(
            (item["hospital_id"], item["indicator_code"], item["month"]))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": page_items,
    }


# ── POST /quality-alerts/scan ───────────────────────────────────────────────

class _ScanBody(BaseModel):
    month: Optional[str] = None  # None = every month that has data
    hospital_id: Optional[int] = None


@router.post("/scan", dependencies=[Depends(require_permission("quality_alerts.write"))])
def scan_month(body: _ScanBody, db: Session = Depends(get_db)):
    """Run the multi-perspective detection for one month — or all periods.

    With no ``month`` in the body every reporting month with data is scanned
    (catch-up after enabling the screen). Scans also happen automatically
    after each analysis (pipeline auto-scan, config ``alerts_auto_scan``).
    """
    if not body.month:
        return engine.scan_all_months(db)
    if len(body.month) != 7:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    result = engine.scan(db, body.month, hospital_id=body.hospital_id)
    if "error" in result and result.get("hospitals_scanned", 0) == 0:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── POST /quality-alerts/rescan-stale ─────────────────────────────────────

class _RescanStaleBody(BaseModel):
    confirm: bool = False  # False = preview only; nothing is written
    months: Optional[List[str]] = None  # the months the operator confirmed


@router.post("/rescan-stale",
             dependencies=[Depends(require_permission("quality_alerts.write"))])
def rescan_stale_months(body: _RescanStaleBody, db: Session = Depends(get_db),
                        user=Depends(get_current_user)):
    """Recompute only the rows whose stored results predate the saved policy.

    Preview-first: ``confirm=false`` (the default) writes nothing and reports
    the affected months with their alert/issue counts. ``confirm=true``
    re-runs the scan for each affected (month, hospital) scope and only for
    the indicators that actually hold stale rows — never a whole month and
    never a sibling indicator that already matches the current policy.
    """
    policy = _current_policy(db)
    if policy.get("state") != "current":
        # Without a readable policy "stale" cannot be computed; refuse rather
        # than recompute rows on a guess.
        raise HTTPException(
            status_code=409,
            detail=policy.get("error") or
            "The saved severity policy cannot be read; nothing was recomputed.")

    rows = _stale_policy_rows(db, policy)
    if body.months is not None:
        # Re-checked, never trusted: a month that is no longer stale is dropped.
        wanted = set(body.months)
        rows = [row for row in rows if row["month"] in wanted]
    totals = {
        "months": _summarize_stale(rows),
        "total_alerts": len(rows),
        "total_issues": len({
            (row["month"], row["hospital_id"],
             _identity_key(row.get("formula"), row.get("unit"),
                           row["indicator_code"]))
            for row in rows}),
        "total_hospitals": len({(row["month"], row["hospital_id"])
                                for row in rows}),
    }
    if not body.confirm:
        return {"confirm_required": True, **totals}

    # One scan call per (month, hospital), carrying only the stale indicators.
    scopes: dict = {}
    for row in rows:
        scopes.setdefault((row["month"], row["hospital_id"]), set()).add(
            row["indicator_code"])

    counters = {"created": 0, "updated": 0, "deactivated": 0,
                "deduplicated": 0}
    rescanned: List[dict] = []
    errors: List[str] = []
    for (month, hospital_id), codes in sorted(scopes.items()):
        result = engine.scan(db, month, hospital_id=hospital_id,
                             indicator_codes=sorted(codes))
        rescanned.append({"month": month, "hospital_id": hospital_id,
                          "indicators": len(codes),
                          **{key: result.get(key) for key in
                             ("created", "updated", "deactivated",
                              "deduplicated", "error")}})
        for key in counters:
            counters[key] += result.get(key) or 0
        if result.get("error"):
            errors.append(f"{month}: {result['error']}")

    # Durable audit entry: who recomputed which months, and what each scope
    # produced. A preview or a no-op confirm writes nothing.
    audit = None
    if rows:
        record = QualityAlertAudit(
            action="rescan_stale",
            actor=getattr(user, "username", None) or "user",
            months=[entry["month"] for entry in totals["months"]],
            details={
                "hospitals": totals["total_hospitals"],
                "indicators": totals["total_issues"],
                "alerts_rewritten": totals["total_alerts"],
                **counters,
                "scopes": rescanned,
                "errors": errors,
            },
        )
        db.add(record)
        db.commit()
        audit = {
            "id": record.id,
            "action": record.action,
            "actor": record.actor,
            "months": record.months,
            "created_at": (record.created_at.isoformat()
                           if record.created_at else None),
        }
    return {"confirm_required": False, **totals, **counters,
            "rescanned": rescanned, "errors": errors, "audit": audit}


# ── GET /quality-alerts/{alert_id} ──────────────────────────────────────────

@router.get("/{alert_id}")
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    """Full evidence for one alert + its sibling perspectives + audit trail."""
    alert = db.query(QualityAlert).filter(QualityAlert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    hospital = db.query(Hospital).filter(Hospital.id == alert.hospital_id).first()
    siblings = db.query(QualityAlert).filter(
        QualityAlert.hospital_id == alert.hospital_id,
        QualityAlert.indicator_code == alert.indicator_code,
        QualityAlert.month == alert.month,
    ).all()
    previous = db.query(QualityAlert).filter(
        QualityAlert.hospital_id == alert.hospital_id,
        QualityAlert.indicator_code == alert.indicator_code,
        QualityAlert.month != alert.month,
    ).order_by(QualityAlert.month.desc()).limit(20).all()
    events = (db.query(QualityAlertEvent)
              .filter(QualityAlertEvent.alert_id == alert.id)
              .order_by(QualityAlertEvent.created_at.asc()).all())

    # Registry metadata straight from the definition row (formula, version…).
    definition_info = None
    from app.models import IndicatorDefinition
    if alert.indicator_id is not None:
        row = db.query(IndicatorDefinition).filter(
            IndicatorDefinition.id == alert.indicator_id).first()
        if row is not None:
            definition_info = {
                "id": row.id, "code": row.code, "name": row.name,
                "description": row.description, "unit": row.unit,
                "direction": row.direction or "none",
                "target_min": row.target_min, "target_max": row.target_max,
                "threshold_low": row.threshold_low, "threshold_high": row.threshold_high,
                "version": row.version, "is_active": row.is_active,
                "formula": alert.formula or row.expression,
                "numerator_codes": row.numerator_codes,
                "denominator_codes": row.denominator_codes,
                "operator": row.operator, "multiplier": row.multiplier,
            }

    # The comparison group(s) the engine used, resolved to names AND values.
    # A history-perspective alert has no peers of its own, but the same issue
    # may carry peer perspectives — listing those groups keeps the detail from
    # claiming "no peers" when the indicator was in fact compared with other
    # hospitals. Groups are ordered worst-first, like the sibling list.
    groups = engine.peer_groups(
        db, alert,
        sorted(siblings, key=lambda s: -SEVERITY_ORDER.get(s.severity, 0)),
    )
    own = next((g for g in groups if g["perspective"] == alert.perspective), None)
    # Keep the flat list populated for callers/older clients: the opened
    # alert's own group when it has one, else the strongest group of the issue.
    peers = (own or groups[0])["peers"] if groups else []

    # Month-by-month evidence for the detail chart. Supplementary: a failure
    # here must never hide the finding itself from the investigator.
    try:
        trend = engine.alert_trend(db, alert)
    except Exception:  # pragma: no cover - defensive, logged for diagnosis
        logger.exception("Quality alert trend failed for alert %s", alert.id)
        trend = None

    policy = _current_policy(db)
    canonical = _canonical_info(db, alert)
    # Resolved once for the whole detail payload: the definition gate needs the
    # live catalog, and the same set grades the opened alert and its siblings.
    catalog_codes = engine.peer_definition_codes(db)
    return {
        "alert": _alert_dict(alert, policy, catalog_codes=catalog_codes),
        "evidence": _evidence_output(alert),
        # Canonical formula this alert belongs to. The identity comes from the
        # formula stored on the row; the registry only names the representative
        # registration and lists the equivalent codes.
        "canonical": canonical,
        "trend": trend,
        "peers": peers,
        "peer_groups": groups,
        "issue": {
            "perspectives": [_alert_dict(s, policy, catalog_codes=catalog_codes)
                             for s in siblings],
            "primary_severity": max(
                (_effective_severity(s) for s in siblings),
                key=lambda sev: SEVERITY_ORDER.get(sev, 0)),
        },
        "hospital": {
            "id": hospital.id if hospital else alert.hospital_id,
            "name": hospital.name if hospital else None,
            "type": _name_by_id(db, HospitalType).get(hospital.hospital_type_id) if hospital else None,
            "ownership": _name_by_id(db, FacilityOwnership).get(hospital.facility_ownership_id) if hospital else None,
            "facility_type": _name_by_id(db, FacilityType).get(hospital.facility_type_id) if hospital else None,
            "governorate": _name_by_id(db, Governorate).get(hospital.governorate_id) if hospital else None,
        } if hospital else None,
        "definition": definition_info,
        "previous_alerts": [_alert_dict(p, policy, catalog_codes=catalog_codes)
                            for p in previous],
        "events": [{
            "id": e.id,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "note": e.note,
            "actor": e.actor,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
        # The audit screen resolves an indicator by its CODE — the existing
        # contract of /audit/explain and of audit.js's `_trailQuery` — so a link
        # without it opened the hospital's whole month instead of this finding.
        # `indicator_id` is carried for callers that can use it; it is None on a
        # data-element row, which has no registry definition.
        "audit_link": {
            "kind": "quality_score",
            "hospital_id": alert.hospital_id,
            "month": alert.month,
            "indicator_code": alert.indicator_code,
            "indicator_id": alert.indicator_id,
        },
    }


# ── POST /quality-alerts/{alert_id}/status | /note ─────────────────────────

class _StatusBody(BaseModel):
    status: str
    note: Optional[str] = None
    assignee: Optional[str] = None


class _NoteBody(BaseModel):
    note: str


@router.post("/{alert_id}/status",
             dependencies=[Depends(require_permission("quality_alerts.write"))])
def set_status(alert_id: int, body: _StatusBody, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    alert = db.query(QualityAlert).filter(QualityAlert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if body.status not in QUALITY_ALERT_STATUSES:
        raise HTTPException(status_code=422,
                            detail=f"status must be one of {list(QUALITY_ALERT_STATUSES)}")
    actor = getattr(user, "username", None) or "user"
    event = engine.record_status_change(
        db, alert, body.status, note=body.note, assignee=body.assignee,
        actor=actor)
    return {"alert": _alert_dict(alert, catalog_codes=engine.peer_definition_codes(db)),
            "event": {
        "id": event.id, "from_status": event.from_status,
        "to_status": event.to_status, "note": event.note,
        "actor": event.actor,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }}


@router.post("/{alert_id}/note",
             dependencies=[Depends(require_permission("quality_alerts.write"))])
def add_note(alert_id: int, body: _NoteBody, db: Session = Depends(get_db),
             user=Depends(get_current_user)):
    alert = db.query(QualityAlert).filter(QualityAlert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not body.note or not body.note.strip():
        raise HTTPException(status_code=422, detail="note must not be empty")
    actor = getattr(user, "username", None) or "user"
    event = engine.record_note(db, alert, body.note.strip(), actor=actor)
    return {"event": {
        "id": event.id, "from_status": event.from_status,
        "to_status": event.to_status, "note": event.note,
        "actor": event.actor,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }}
