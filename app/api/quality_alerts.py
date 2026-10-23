"""Quality Alerts API — centralized risk-outlier monitoring (2026-10-21).

Read endpoints require ``quality_alerts.read``; scan + investigation workflow
require ``quality_alerts.write``. All indicator values rendered here were
computed by the shared engine at scan time (see app/engine/quality_alerts.py)
— this router never recalculates a clinical indicator.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_permission
from app.database import get_db
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


def _apply_issue_filters(query, db: Session, month: Optional[str],
                         hospital_id: Optional[int], indicator: Optional[str],
                         severity: Optional[str], perspective: Optional[str],
                         status: Optional[str], ownership_id: Optional[int],
                         governorate_id: Optional[int],
                         hospital_type_id: Optional[int],
                         confidence: Optional[str],
                         indicator_type: Optional[str],
                         active: bool, q: Optional[str]):
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
    if severity:
        query = query.filter(QualityAlert.severity == severity)
    if perspective:
        query = query.filter(QualityAlert.perspective == perspective)
    if status:
        query = query.filter(QualityAlert.status == status)
    if confidence:
        query = query.filter(QualityAlert.confidence == confidence)
    if indicator_type:
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
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Hospital.name.ilike(like),
            QualityAlert.indicator_name.ilike(like),
            QualityAlert.indicator_code.ilike(like),
        ))
    return query


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
    # Only the four columns the comparison needs: no ORM entities, no full rows.
    rows = (db.query(QualityAlert.month, QualityAlert.hospital_id,
                     QualityAlert.indicator_code, QualityAlert.evidence)
            .filter(QualityAlert.active.is_(True)).all())
    stale: List[dict] = []
    for month, hospital_id, code, evidence in rows:
        stored = (evidence or {}).get("severity_policy") or {}
        if _policy_state(stored, policy) != "stale":
            continue
        stale.append({"month": month, "hospital_id": hospital_id,
                      "indicator_code": code})
    return stale


def _summarize_stale(rows: List[dict]) -> List[dict]:
    """Per-month stale counts for the preview (alert rows + distinct issues)."""
    buckets: dict = {}
    for row in rows:
        bucket = buckets.setdefault(
            row["month"], {"month": row["month"], "alerts": 0, "issues": set()})
        bucket["alerts"] += 1
        bucket["issues"].add((row["hospital_id"], row["indicator_code"]))
    return [{"month": month, "alerts": data["alerts"],
             "issues": len(data["issues"])}
            for month, data in sorted(buckets.items())]


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


def _alert_dict(alert: QualityAlert, policy: Optional[dict] = None) -> dict:
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
        "severity": alert.severity,
        **_severity_outputs(alert, policy),
        "score": alert.score,
        "method": alert.method,
        "current_value": alert.current_value,
        "baseline_value": alert.baseline_value,
        "deviation_pct": alert.deviation_pct,
        "z_score": alert.z_score,
        "peer_count": alert.peer_count,
        "direction": alert.direction or "none",
        "interpretation": alert.interpretation or "statistical_only",
        "reason": alert.reason,
        "confidence": alert.confidence or "high",
        "status": alert.status,
        "assignee": alert.assignee,
        "detected_at": alert.detected_at.isoformat() if alert.detected_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }


def _group_alerts(alerts: List[QualityAlert], names: dict,
                  policy: Optional[dict] = None) -> List[dict]:
    """Group per-perspective rows into one risk issue per (hospital, indicator, month).

    Spec §8: distinct perspectives are preserved as evidence; the dashboard
    shows a single issue with a primary severity and every perspective listed.
    """
    groups: dict = {}
    for alert in alerts:
        key = (alert.hospital_id, alert.indicator_code, alert.month)
        groups.setdefault(key, []).append(alert)

    issues = []
    for (hid, code, month), rows in groups.items():
        primary = max(rows, key=lambda a: SEVERITY_ORDER.get(a.severity, 0))
        statuses = {r.status for r in rows}
        rollup = next((s for s in _STATUS_ROLLUP if s in statuses), engine.STATUS_NEW)
        perspectives = sorted(
            (_alert_dict(r, policy) for r in rows),
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
        issues.append({
            "hospital_id": hid,
            "hospital": names.get(hid, f"Hospital #{hid}"),
            "indicator_code": code,
            "indicator_name": primary.indicator_name,
            "unit": primary.unit or "",
            "month": month,
            "primary_severity": primary.severity,
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
    month: Optional[str] = Query(None),
    hospital_id: Optional[int] = Query(None),
    indicator: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    perspective: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    ownership_id: Optional[int] = Query(None),
    governorate_id: Optional[int] = Query(None),
    hospital_type_id: Optional[int] = Query(None),
    confidence: Optional[str] = Query(None),
    indicator_type: Optional[str] = Query(None, description="element | derivative"),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Dashboard KPIs over active alerts, respecting every active filter.

    Two units exist on this screen and the response keeps them apart:

    * **perspective rows** — one row per comparison group (history, all,
      governorate…), the evidence unit. ``total_active`` / ``red_alerts`` /
      ``new_alerts`` / ``unresolved`` count these, and so does the
      per-perspective chip tally.
    * **risk issues** — one per hospital+indicator+month, whatever number of
      perspectives fired. The issue table, its pager and the KPI cards use
      these: ``total_issues`` / ``red_issues`` / ``new_issues`` /
      ``unresolved_issues``.

    Both are derived from the same filtered rows and grouped exactly like
    ``/issues``, so ``total_issues`` always equals that endpoint's ``total``.

    ``red_only_issues`` / ``mixed_severity_issues`` split the selected issues
    by their whole evidence: red-only means every perspective that fired on the
    issue is Very High, mixed means it also carries a lower band. Filters that
    narrow which rows matched (severity, perspective, status, confidence) say
    nothing about what the issue contains, so they are dropped when that split
    is computed. On the pinned Red screen the two add up to ``total_issues``.
    """
    query = db.query(QualityAlert)
    query = _apply_issue_filters(
        query, db, month, hospital_id, indicator, severity, perspective,
        status, ownership_id, governorate_id, hospital_type_id, confidence,
        indicator_type, active=True, q=q)
    rows = query.all()
    by_perspective: dict = {}
    for alert in rows:
        by_perspective[alert.perspective] = by_perspective.get(alert.perspective, 0) + 1

    # Group with the same key and the same status rollup as _group_alerts so
    # the summary can never disagree with the table it sits above.
    grouped: dict = {}
    for alert in rows:
        grouped.setdefault(
            (alert.hospital_id, alert.indicator_code, alert.month), []).append(alert)
    rolled = []
    for issue_rows in grouped.values():
        statuses = {a.status for a in issue_rows}
        rolled.append((issue_rows, next(
            (s for s in _STATUS_ROLLUP if s in statuses), engine.STATUS_NEW)))

    # Is a red issue red on its own, or red because one perspective escalated
    # while the others stayed lower? That is a property of the ISSUE, so read
    # every perspective that fired — not only the rows the filters let
    # through. Without a narrowing filter the rows already are the full set.
    if any((severity, perspective, status, confidence)):
        sibling_query = _apply_issue_filters(
            db.query(QualityAlert), db, month, hospital_id, indicator,
            None, None, None, ownership_id, governorate_id, hospital_type_id,
            None, indicator_type, active=True, q=q)
        sibling_rows = sibling_query.all()
    else:
        sibling_rows = rows
    issue_keys = set(grouped)
    severities_by_issue: dict = {}
    for alert in sibling_rows:
        key = (alert.hospital_id, alert.indicator_code, alert.month)
        if key in issue_keys:
            severities_by_issue.setdefault(key, set()).add(alert.severity)
    red_only = sum(1 for sevs in severities_by_issue.values()
                   if sevs == {"VERY_HIGH"})
    mixed = sum(1 for sevs in severities_by_issue.values()
                if "VERY_HIGH" in sevs and len(sevs) > 1)

    return {
        # Perspective-row units (evidence).
        "total_active": len(rows),
        "red_alerts": sum(1 for a in rows if a.severity == "VERY_HIGH"),
        "new_alerts": sum(1 for a in rows if a.status == engine.STATUS_NEW),
        "unresolved": sum(
            1 for a in rows
            if a.status not in (engine.STATUS_RESOLVED, engine.STATUS_FALSE_POSITIVE)),
        "by_perspective": by_perspective,
        "by_severity": {
            sev: sum(1 for a in rows if a.severity == sev)
            for sev in QUALITY_ALERT_SEVERITIES
        },
        # Issue units (what the screen lists, pages and counts).
        "total_issues": len(grouped),
        "red_issues": sum(
            1 for issue_rows, _ in rolled
            if any(a.severity == "VERY_HIGH" for a in issue_rows)),
        "red_only_issues": red_only,
        "mixed_severity_issues": mixed,
        "new_issues": sum(1 for _, status in rolled if status == engine.STATUS_NEW),
        "unresolved_issues": sum(
            1 for _, status in rolled
            if status not in (engine.STATUS_RESOLVED, engine.STATUS_FALSE_POSITIVE)),
        "hospitals_affected": len({a.hospital_id for a in rows}),
        "indicators_affected": len({a.indicator_code for a in rows}),
    }


# ── GET /quality-alerts/issues ──────────────────────────────────────────────

@router.get("/issues")
def list_issues(
    month: Optional[str] = Query(None),
    hospital_id: Optional[int] = Query(None),
    indicator: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    perspective: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    ownership_id: Optional[int] = Query(None),
    governorate_id: Optional[int] = Query(None),
    hospital_type_id: Optional[int] = Query(None),
    confidence: Optional[str] = Query(None),
    indicator_type: Optional[str] = Query(None, description="element | derivative"),
    q: Optional[str] = Query(None),
    sort: str = Query("severity"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Grouped risk issues (one per hospital+indicator+month), paged."""
    query = db.query(QualityAlert).options(selectinload(QualityAlert.hospital))
    query = _apply_issue_filters(
        query, db, month, hospital_id, indicator, severity, perspective,
        status, ownership_id, governorate_id, hospital_type_id, confidence,
        indicator_type, active=True, q=q)
    alerts = query.all()
    names = _name_by_id(db, Hospital)
    issues = _group_alerts(alerts, names, _current_policy(db))

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
    start = (page - 1) * page_size
    page_items = issues[start:start + page_size]

    # Inline trend per row (one small series each) so the list itself shows
    # whether a finding is a one-month spike or a sustained problem. Only the
    # visible page is computed; a failure here degrades to "no trend" rather
    # than hiding the issues. The full peer comparison lives in the detail.
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
        "total_issues": len({(row["month"], row["hospital_id"],
                              row["indicator_code"]) for row in rows}),
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

    counters = {"created": 0, "updated": 0, "deactivated": 0}
    rescanned: List[dict] = []
    errors: List[str] = []
    for (month, hospital_id), codes in sorted(scopes.items()):
        result = engine.scan(db, month, hospital_id=hospital_id,
                             indicator_codes=sorted(codes))
        rescanned.append({"month": month, "hospital_id": hospital_id,
                          "indicators": len(codes),
                          **{key: result.get(key) for key in
                             ("created", "updated", "deactivated", "error")}})
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
    return {
        "alert": _alert_dict(alert, policy),
        "evidence": alert.evidence or {},
        "trend": trend,
        "peers": peers,
        "peer_groups": groups,
        "issue": {
            "perspectives": [_alert_dict(s, policy) for s in siblings],
            "primary_severity": max(
                (s.severity for s in siblings),
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
        "previous_alerts": [_alert_dict(p, policy) for p in previous],
        "events": [{
            "id": e.id,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "note": e.note,
            "actor": e.actor,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
        "audit_link": {
            "kind": "quality_score",
            "hospital_id": alert.hospital_id,
            "month": alert.month,
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
    return {"alert": _alert_dict(alert), "event": {
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
