"""Identify and controlledly recompute stored Quality Scores.

A stored QualityScore records the configuration that produced it
(``scoring_fingerprint`` + ``scoring_config``). Rows written before that
provenance existed have no fingerprint: they are *unknown*, never assumed
wrong. Two independent pieces of evidence decide whether a row's numbers were
produced by a different configuration:

1. the stored fingerprint, compared with the current one and with the
   fingerprint of the approved configuration under the old hidden fallback
   (``PREVIOUS_OUTLIER_MULTIPLIER``); and
2. the stored outlier rows (LayeredOutlierResult / AnomalyResult), which let
   the penalty be recomputed exactly under any multiplier and compared with
   the stored penalty within ``SCORE_TOLERANCE``.

Recomputation here is deterministic and read-only with respect to detection:
it reuses the persisted outlier rows and the persisted rule/completeness/
consistency components, so the same stored inputs and config always produce
the same result. It never overwrites a row without writing a
QualityScoreRevision first.
"""
import json
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.config_utils import get_config_dict
from app.models import (
    AnomalyResult,
    LayeredOutlierResult,
    QualityScore,
    QualityScoreRevision,
)

from .scoring import (
    FLAGGED_LEVELS,
    OUTLIER_MULTIPLIER_DEFAULT,
    OUTLIER_MULTIPLIER_KEY,
    PREVIOUS_OUTLIER_MULTIPLIER,
    anomaly_outlier_penalty,
    combine_quality_score,
    layered_outlier_penalty,
    layered_severity,
    resolve_scoring_config,
    scoring_config_fingerprint,
    scoring_config_with_multiplier,
)

# Stored components are rounded to one decimal; a difference smaller than this
# is rounding noise, not a different result.
SCORE_TOLERANCE = 0.1

# States reported by identify_scores / recompute_quality_scores.
STATE_CURRENT = "current"
STATE_PREVIOUS_CONFIG = "previous_configuration"
STATE_OTHER_CONFIG = "other_configuration"
STATE_UNKNOWN = "unknown"

ACTOR_SYSTEM = "system"


def current_scoring_config(db: Session) -> Dict[str, float]:
    """The approved scoring configuration from AppConfig (category quality)."""
    return resolve_scoring_config(get_config_dict(db, "quality"))


def previous_scoring_config(db: Session) -> Dict[str, float]:
    """Approved configuration with the old hidden fallback multiplier.

    Only used to RECOGNISE rows; it is never written back.
    """
    return scoring_config_with_multiplier(
        PREVIOUS_OUTLIER_MULTIPLIER, get_config_dict(db, "quality"))


def score_snapshot(row: QualityScore) -> Dict:
    """Every stored value a recompute can overwrite."""
    return {
        "score": row.score,
        "rule_compliance": row.rule_compliance,
        "completeness": row.completeness,
        "consistency": row.consistency,
        "outlier_penalty": row.outlier_penalty,
        "issues": row.issues,
        "scoring_fingerprint": row.scoring_fingerprint,
        "scoring_config": row.scoring_config,
        "policy_digest": row.policy_digest,
    }


def _numeric(values: Dict) -> Dict[str, Optional[float]]:
    return {
        key: values.get(key)
        for key in ("score", "rule_compliance", "completeness",
                    "consistency", "outlier_penalty")
    }


def _is_fallback(issues) -> bool:
    """True when a stored ``issues`` value carries the failed-analysis marker.

    The same single marker and exact list membership the pipeline uses; the
    import is local because ``app.engine.pipeline`` imports this module lazily
    (avoiding a module-level cycle). A stored value may be the JSON string the
    database holds or an already-parsed list.
    """
    from app.engine.pipeline import FALLBACK_ANALYSIS_ISSUE

    if not issues:
        return False
    if isinstance(issues, str):
        try:
            issues = json.loads(issues)
        except (TypeError, ValueError):
            return False
    return isinstance(issues, list) and FALLBACK_ANALYSIS_ISSUE in issues


def _differs(previous: Dict, current: Dict) -> bool:
    for key, before in _numeric(previous).items():
        after = current.get(key)
        if before is None and after is None:
            continue
        if before is None or after is None:
            return True
        if abs(float(before) - float(after)) > SCORE_TOLERANCE:
            return True
    return False


def _recomputed_differs(row: QualityScore, recomputed: Dict) -> bool:
    """A recomputed result carries only the two values it derives."""
    for key in ("score", "outlier_penalty"):
        stored = getattr(row, key)
        expected = recomputed.get(key)
        if stored is None or expected is None:
            return True
        if abs(float(stored) - float(expected)) > SCORE_TOLERANCE:
            return True
    return False


def score_config_state(row: QualityScore, current_fp: str,
                       previous_fp: str) -> str:
    """Classify a row by the configuration it says produced it."""
    stored = row.scoring_fingerprint
    if not stored:
        return STATE_UNKNOWN
    if stored == current_fp:
        return STATE_CURRENT
    if stored == previous_fp:
        return STATE_PREVIOUS_CONFIG
    return STATE_OTHER_CONFIG


def _stored_outlier_rows(db: Session, hospital_id: int, month: str):
    layered = (
        db.query(LayeredOutlierResult)
        .filter(LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month)
        .all()
    )
    # Both sources are read: a row computed before the layered engine existed
    # has classic rows only, and a row computed later has both. The source is
    # chosen by which stored penalty the rows reproduce, never by preference.
    anomalies = (
        db.query(AnomalyResult)
        .filter(AnomalyResult.hospital_id == hospital_id,
                AnomalyResult.month == month)
        .all()
    )
    return layered, anomalies


def _eligible_codes_for(db: Session, row: QualityScore, layered_rows) -> Optional[set]:
    """The approved eligible denominator for a stored layered month."""
    if not layered_rows:
        return None
    from app.engine.pipeline import get_outlier_eligible_codes

    return get_outlier_eligible_codes(
        db, row.hospital_id, row.month,
        evaluated_codes=[r.analysis_code for r in layered_rows])


def recompute_from_stored_rows(row: QualityScore, layered_rows, anomaly_rows,
                               config: Dict[str, float],
                               eligible_codes: Optional[set] = None) -> Optional[Dict]:
    """Deterministic recomputation of a stored score from its stored inputs.

    Returns ``{"outlier_penalty", "score", "source"}`` or None when the month
    has no persisted outlier rows (a deep recompute from raw data is needed).
    The source (layered vs classic) is chosen by which stored penalty the
    persisted rows reproduce, so recomputing never silently switches the
    component to a different detection source.
    """
    previous_config = scoring_config_with_multiplier(
        PREVIOUS_OUTLIER_MULTIPLIER, config)
    candidates = []
    if layered_rows:
        candidates.append((
            "layered",
            round(layered_outlier_penalty(
                layered_rows, config, eligible_codes=eligible_codes) * 100, 1),
            round(layered_outlier_penalty(
                layered_rows, previous_config,
                eligible_codes=eligible_codes) * 100, 1),
        ))
    if anomaly_rows:
        candidates.append((
            "anomaly",
            round(anomaly_outlier_penalty(anomaly_rows, config) * 100, 1),
            round(anomaly_outlier_penalty(anomaly_rows, previous_config) * 100, 1),
        ))
    if not candidates:
        return None

    stored_penalty = row.outlier_penalty
    if stored_penalty is None:
        return None

    # Which source was used at calculation time? The one whose penalty matches
    # the stored value — under the approved multiplier or under the old hidden
    # fallback. If neither matches, the stored score cannot be reconciled from
    # available data and must not be rewritten.
    matched = [
        (source, approved_penalty) for source, approved_penalty, old_penalty
        in candidates
        if (abs(approved_penalty - float(stored_penalty)) <= SCORE_TOLERANCE
            or abs(old_penalty - float(stored_penalty)) <= SCORE_TOLERANCE)
    ]
    if not matched:
        return None
    source, penalty = matched[0]
    score = combine_quality_score(
        row.rule_compliance, row.completeness, row.consistency, penalty, config)
    return {"outlier_penalty": penalty, "score": score, "source": source}


def apply_score_update(db: Session, row: QualityScore,
                       config: Optional[Dict[str, float]],
                       action: str, actor: str = ACTOR_SYSTEM,
                       policy_digest: Optional[str] = None,
                       set_policy_identity: bool = False, **changes) -> bool:
    """Apply a score change, recording the previous values when they move.

    ``config`` must be a resolved configuration (``resolve_scoring_config``),
    or ``None`` for a config-less write that no scoring configuration produced
    (the failed-analysis fallback): such a row carries no provenance, exactly
    like a fallback row written for the first time.

    D5 identity rules:

    * ``set_policy_identity=True`` records ``policy_digest`` on the row (an
      analysis run's digest, or ``None`` to clear it for a fallback that no
      policy produced). ``False`` leaves a row's recorded identity untouched —
      repair/recalculation writers do not know a policy and must not erase it.
    * A revision is written when numeric values move (as before), when the row
      flips between the failed-analysis placeholder and a genuine result (even
      at the same numbers — a failed 0 is not a genuine 0), or when a recorded
      policy identity actually changes. A legacy ``NULL`` identity becoming
      recorded is provenance being added, not a changed result, and does not
      by itself append a revision.

    Returns True when a revision was recorded. The row is not committed.
    """
    previous = score_snapshot(row)
    if set_policy_identity:
        row.policy_digest = policy_digest
    for key, value in changes.items():
        if key not in ("score", "rule_compliance", "completeness",
                       "consistency", "outlier_penalty", "issues"):
            raise ValueError(f"Unsupported QualityScore field: {key}")
        setattr(row, key, value)

    resolved = None
    if config is not None:
        resolved = resolve_scoring_config(config)
        row.scoring_fingerprint = scoring_config_fingerprint(resolved)
    else:
        row.scoring_fingerprint = None
    row.scoring_config = resolved
    current = score_snapshot(row)

    identity_changed = _is_fallback(previous["issues"]) != _is_fallback(
        current["issues"])
    policy_changed = (previous["policy_digest"] is not None
                      and current["policy_digest"] is not None
                      and previous["policy_digest"] != current["policy_digest"])
    if not (_differs(previous, current) or identity_changed or policy_changed):
        return False
    db.add(QualityScoreRevision(
        hospital_id=row.hospital_id,
        month=row.month,
        action=action,
        actor=actor,
        previous_score=previous["score"],
        new_score=current["score"],
        previous_fingerprint=previous["scoring_fingerprint"],
        new_fingerprint=current["scoring_fingerprint"],
        previous_policy_digest=previous["policy_digest"],
        new_policy_digest=current["policy_digest"],
        previous_values=previous,
        new_values=current,
        config=resolved,
    ))
    return True


def _penalty_diagnostics(db: Session, row: QualityScore, layered_rows,
                         anomaly_rows, approved: Dict[str, float]) -> Dict:
    """Evidence for one stored row's outlier component.

    Reports the approved eligible denominator, the number of rows actually
    evaluated, whether the stored penalty reproduces it, and whether the
    stored value instead matches the old evaluated-rows denominator.
    """
    multiplier = approved[OUTLIER_MULTIPLIER_KEY]
    stored = row.outlier_penalty

    def _close(value) -> bool:
        return (stored is not None and value is not None
                and abs(float(stored) - float(value)) <= SCORE_TOLERANCE)

    if layered_rows:
        eligible = _eligible_codes_for(db, row, layered_rows)
        eligible_count = len(eligible or ())
        evaluated_count = len(layered_rows)
        # The canonical band, exactly as the scoring path counts it: a row the
        # approved caps/gate lowered is not reported as a top-band finding.
        grades = [layered_severity(r) for r in layered_rows]
        flagged = sum(1 for g in grades if g["level"] in FLAGGED_LEVELS)
        capped = sum(1 for g in grades if g["stored_level"] != g["level"])
        eligible_penalty = round(min(
            1.0, flagged / eligible_count * multiplier) * 100, 1) \
            if eligible_count else 0.0
        evaluated_penalty = round(min(
            1.0, flagged / evaluated_count * multiplier) * 100, 1) \
            if evaluated_count else 0.0
        matches = _close(eligible_penalty)
        return {
            "available": True,
            "source": "layered",
            "eligible": eligible_count,
            "evaluated": evaluated_count,
            "flagged": flagged,
            # Rows whose stored band the approved policy lowered (cap/gate), so
            # a reader can tell a stored VERY_HIGH from the HIGH that was used.
            "capped": capped,
            "penalty": eligible_penalty,
            "stored": stored,
            "matches": matches,
            "scored_under_evaluated_rows_denominator": bool(
                _close(evaluated_penalty)
                and abs(evaluated_penalty - eligible_penalty) > SCORE_TOLERANCE),
        }
    if anomaly_rows:
        penalty = round(anomaly_outlier_penalty(anomaly_rows, approved) * 100, 1)
        return {
            "available": True,
            "source": "anomaly",
            "eligible": len(anomaly_rows),
            "evaluated": len(anomaly_rows),
            "flagged": sum(1 for r in anomaly_rows if getattr(r, "is_outlier", False)),
            "penalty": penalty,
            "stored": stored,
            "matches": _close(penalty),
            "scored_under_evaluated_rows_denominator": False,
        }
    return {"available": False, "stored": stored, "matches": False}


def identify_scores(db: Session, config: Optional[Dict] = None,
                    limit_examples: int = 50) -> Dict:
    """Read-only report: which stored rows used which configuration.

    ``affected`` counts rows whose recomputation under the approved
    configuration differs from the stored values beyond tolerance. A row with
    no fingerprint is reported as ``unknown``; it becomes ``affected`` only
    when the stored numbers themselves show a different configuration.
    """
    approved = resolve_scoring_config(config or get_config_dict(db, "quality"))
    current_fp = scoring_config_fingerprint(approved)
    previous_fp = scoring_config_fingerprint(
        scoring_config_with_multiplier(PREVIOUS_OUTLIER_MULTIPLIER, approved))

    rows = db.query(QualityScore).order_by(QualityScore.hospital_id,
                                           QualityScore.month).all()
    summary = {
        "current_fingerprint": current_fp,
        "previous_fingerprint": previous_fp,
        "approved_multiplier": approved[OUTLIER_MULTIPLIER_KEY],
        "previous_multiplier": PREVIOUS_OUTLIER_MULTIPLIER,
        "default_multiplier": OUTLIER_MULTIPLIER_DEFAULT,
        "total_rows": len(rows),
        "by_state": {STATE_CURRENT: 0, STATE_PREVIOUS_CONFIG: 0,
                     STATE_OTHER_CONFIG: 0, STATE_UNKNOWN: 0},
        "affected_count": 0,
        "recomputable_count": 0,
        "needs_deep_recompute": 0,
        "unreconciled_count": 0,
        "affected": [],
        "items": [],
        "needs_deep_examples": [],
        "truncated": False,
    }

    for row in rows:
        state = score_config_state(row, current_fp, previous_fp)
        summary["by_state"][state] += 1
        layered_rows, anomaly_rows = _stored_outlier_rows(
            db, row.hospital_id, row.month)
        if len(summary["items"]) < limit_examples:
            summary["items"].append({
                "hospital_id": row.hospital_id,
                "month": row.month,
                "state": state,
                "score": row.score,
                "outlier_penalty": row.outlier_penalty,
                "penalty": _penalty_diagnostics(
                    db, row, layered_rows, anomaly_rows, approved),
            })
        if not layered_rows and not anomaly_rows:
            summary["needs_deep_recompute"] += 1
            if len(summary["needs_deep_examples"]) < limit_examples:
                summary["needs_deep_examples"].append(
                    {"hospital_id": row.hospital_id, "month": row.month,
                     "state": state, "reason": "no persisted outlier rows"})
            continue
        recomputed = recompute_from_stored_rows(
            row, layered_rows, anomaly_rows, approved,
            eligible_codes=_eligible_codes_for(db, row, layered_rows))
        if recomputed is None:
            summary["unreconciled_count"] += 1
            continue
        summary["recomputable_count"] += 1
        if _recomputed_differs(row, recomputed):
            summary["affected_count"] += 1
            if len(summary["affected"]) < limit_examples:
                summary["affected"].append({
                    "hospital_id": row.hospital_id,
                    "month": row.month,
                    "state": state,
                    "stored_score": row.score,
                    "stored_outlier_penalty": row.outlier_penalty,
                    "expected_score": recomputed["score"],
                    "expected_outlier_penalty": recomputed["outlier_penalty"],
                    "source": recomputed["source"],
                })
            else:
                summary["truncated"] = True
    return summary


def recompute_quality_scores(db: Session, config: Optional[Dict] = None,
                             apply: bool = False, actor: str = ACTOR_SYSTEM,
                             hospital_id: Optional[int] = None,
                             month_from: Optional[str] = None,
                             month_to: Optional[str] = None,
                             limit_examples: int = 50) -> Dict:
    """Recompute affected scores from stored evidence under the approved config.

    ``apply=False`` (the default) is a dry run: nothing is written. ``apply``
    rewrites only rows whose values actually change, and every rewrite first
    records a QualityScoreRevision containing the previous values and the
    configuration that produced them. Rows with no persisted outlier rows are
    reported for a deep recompute from raw data instead of being guessed at.
    """
    approved = resolve_scoring_config(config or get_config_dict(db, "quality"))
    current_fp = scoring_config_fingerprint(approved)
    previous_fp = scoring_config_fingerprint(
        scoring_config_with_multiplier(PREVIOUS_OUTLIER_MULTIPLIER, approved))

    query = db.query(QualityScore)
    if hospital_id is not None:
        query = query.filter(QualityScore.hospital_id == hospital_id)
    if month_from:
        query = query.filter(QualityScore.month >= month_from)
    if month_to:
        query = query.filter(QualityScore.month <= month_to)
    rows = query.order_by(QualityScore.hospital_id, QualityScore.month).all()

    result = {
        "apply": bool(apply),
        "current_fingerprint": current_fp,
        "previous_fingerprint": previous_fp,
        "approved_multiplier": approved[OUTLIER_MULTIPLIER_KEY],
        "total_rows": len(rows),
        "changed_count": 0,
        "recomputed_count": 0,
        "revisions_recorded": 0,
        "needs_deep_recompute": 0,
        "unreconciled_count": 0,
        "changes": [],
        "needs_deep_examples": [],
        "truncated": False,
    }

    for row in rows:
        state = score_config_state(row, current_fp, previous_fp)
        layered_rows, anomaly_rows = _stored_outlier_rows(
            db, row.hospital_id, row.month)
        recomputed = recompute_from_stored_rows(
            row, layered_rows, anomaly_rows, approved,
            eligible_codes=_eligible_codes_for(db, row, layered_rows))
        if recomputed is None:
            if not layered_rows and not anomaly_rows:
                result["needs_deep_recompute"] += 1
                if len(result["needs_deep_examples"]) < limit_examples:
                    result["needs_deep_examples"].append(
                        {"hospital_id": row.hospital_id, "month": row.month,
                         "state": state, "reason": "no persisted outlier rows"})
            else:
                result["unreconciled_count"] += 1
            continue

        result["recomputed_count"] += 1
        change = {
            "hospital_id": row.hospital_id,
            "month": row.month,
            "state": state,
            "stored_score": row.score,
            "expected_score": recomputed["score"],
            "stored_outlier_penalty": row.outlier_penalty,
            "expected_outlier_penalty": recomputed["outlier_penalty"],
            "source": recomputed["source"],
        }
        if not _recomputed_differs(row, recomputed):
            continue
        result["changed_count"] += 1
        if len(result["changes"]) < limit_examples:
            result["changes"].append(change)
        else:
            result["truncated"] = True

        if apply:
            recorded = apply_score_update(
                db, row, approved, "recompute_scoring_config", actor,
                score=recomputed["score"],
                outlier_penalty=recomputed["outlier_penalty"],
            )
            result["revisions_recorded"] += int(recorded)

    if apply and result["changed_count"]:
        db.commit()
    return result
