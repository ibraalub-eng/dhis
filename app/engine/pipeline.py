import json
import logging
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.engine.anomaly import detect_anomalies, detect_monthly_trend
from app.engine.confidence import build_indicator_rule_map, calculate_confidence
from app.engine.config_resolver import (
    PolicySnapshot,
    PolicyUnavailable,
    load_policy_snapshot,
)
from app.engine.ml import run_ml_analysis
from app.engine.policy_view import (
    ConfidencePolicyInvalid,
    analysis_config_from_snapshot,
    confidence_policy_from_snapshot,
    snapshot_provenance,
)
from app.engine.quality import (
    RuleResult,
    ValidationContext,
    calculate_quality_score,
    get_covered_child_codes,
    run_all_rules,
    run_rules_from_db,
    # A3.5: rule settings travel as a resolved RulesPolicy, not a global.
)
from app.engine.quality.outlier_eligibility import eligible_outlier_units
from app.indicators import INDICATOR_CODE_TO_NAME, PARENT_CHILD_MAP, SYNTHETIC_INDICATOR_CODES
from app.models import (
    AnomalyResult,
    ClinicalInsight,
    ConfidenceScore,
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# P3.3.3b: stable, machine-readable analysis outcome. ``failure_kind`` is only
# populated on a failed result; the human-readable ``issues`` list remains for
# backwards compatibility and is never the machine contract.
ANALYSIS_STATUS_OK = "ok"
ANALYSIS_STATUS_FAILED = "failed"
FAILURE_POLICY_UNAVAILABLE = "policy_unavailable"
FAILURE_CONFIDENCE_POLICY_INVALID = "confidence_policy_invalid"
FAILURE_ANALYSIS_ERROR = "analysis_error"
# D4: the Confidence result was CALCULATED but could not be PERSISTED. Kept
# distinct from an analysis error (the calculation itself failed) so callers
# and operators can tell "computed, not stored" apart from "could not compute".
FAILURE_CONFIDENCE_PERSISTENCE = "confidence_persistence_failed"
# D4: a batch month raised while purging or persisting. Distinct from the
# analysis-level kinds, which say why a completed run ended as a fallback.
FAILURE_RECOMPUTE_ERROR = "recompute_error"
POLICY_PROVENANCE_AVAILABLE = "available"
POLICY_PROVENANCE_CACHED = "cached_unavailable"
POLICY_PROVENANCE_UNAVAILABLE = "unavailable"
# D5: identity of the policy behind a returned result. A cached row can now
# carry the digest of the policy its run used (``recorded``); rows written
# before that was stored, and fallback rows no policy produced, are
# ``unknown``; a run with no policy at all is ``unavailable``. Only the digest
# is ever exposed — never raw policy values, config row ids or read errors.
POLICY_IDENTITY_RECORDED = "recorded"
POLICY_IDENTITY_UNKNOWN = "unknown"
POLICY_IDENTITY_UNAVAILABLE = "unavailable"
# P3.3.3b-Fix: a failed analysis still persists a score-0 QualityScore row (the
# existing rollback/persistence contract), so the row itself must carry a
# durable sign that it is a FAILURE and not a completed zero-score analysis.
# This single constant is the one source of that sign: written only by
# ``_analysis_failure_result`` and read only by ``is_fallback_quality_row``.
FALLBACK_ANALYSIS_ISSUE = "Analysis failed during report generation"
# ``failure_kind`` reported when a STORED fallback is served: the row records
# the original cause nowhere, so the honest answer is "this is a stored
# fallback", never an invented cause and never a success.
FAILURE_STORED_FALLBACK = "stored_fallback"

USE_DB_RULES = True

KEY_INDICATOR_CODES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "17", "18", "26"]


def _layered_analysis_code(result) -> str:
    """Analysis-unit key for a live LayerResult (spec) or a stored row."""
    spec = getattr(result, "spec", None)
    return (getattr(spec, "analysis_code", None)
            or getattr(result, "analysis_code", None))


def _build_code_resolver(code_to_name: Dict[str, str]):
    """Build a function that prettifies rule details by replacing indicator
    codes with their names.

    A code only matches as a standalone token: not preceded by a digit or a
    dot (so the fraction of "12.0" can never match code "0", and "2" inside
    "12" cannot match code "2"), and not followed by a dot or digit.
    Returns None when there are no codes to resolve.
    """
    codes_sorted = sorted(code_to_name.keys(), key=len, reverse=True)
    if not codes_sorted:
        return None
    code_pattern = r'(?<![\d.])(' + '|'.join(re.escape(c) for c in codes_sorted) + r')(?![.\d])'
    def _resolve_codes(text):
        return re.sub(code_pattern, lambda m: code_to_name[m.group(1)], text)
    return _resolve_codes


def _build_ml_config(flat: dict) -> dict:
    return {
        "enabled": bool(flat.get("ml_enabled", 0)),
        "clustering": {
            "enabled": bool(flat.get("ml_clustering_enabled", 1)),
            "min_k": int(flat.get("ml_clustering_min_k", 2)),
            "max_k": int(flat.get("ml_clustering_max_k", 6)),
        },
        "anomaly": {
            "enabled": bool(flat.get("ml_anomaly_enabled", 1)),
            "contamination": float(flat.get("ml_anomaly_contamination", 0.05)),
        },
        "pca": {
            "enabled": bool(flat.get("ml_pca_enabled", 1)),
            "variance_threshold": flat.get("ml_pca_variance_threshold", 0.95),
        },
    }


def get_values_for_hospital_month(session: Session, hospital_id: int, month: str) -> Dict[str, float]:
    rows = (
        session.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(IndicatorValue.hospital_id == hospital_id, IndicatorValue.month == month)
        .all()
    )
    return {row[1].code: row[0].value for row in rows if row[0].value is not None}


def get_default_disabled_indicator_ids(session, month):
    """Return indicator IDs disabled by the default (All Hospitals) config for a month.
    Month '__all__' disables an indicator if it is disabled in ANY month."""
    if month == "__all__":
        return [
            indicator_id
            for (indicator_id, enabled) in session.query(
                IndicatorDefaultConfig.indicator_id, IndicatorDefaultConfig.is_enabled
            ).all()
            if not enabled
        ]
    return [
        c.indicator_id
        for c in session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.month == month,
            IndicatorDefaultConfig.is_enabled.is_(False),
        ).all()
    ]


def get_hospital_override_indicator_ids(session, hospital_id):
    """Return indicator IDs that have an explicit per-hospital config (override) — any state."""
    return [
        c.indicator_id
        for c in session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id,
        ).all()
    ]


def get_effective_manual_disabled_ids(session, hospital_id, month):
    """Return the effective manually-disabled indicator IDs for a hospital/month.
    A hospital's own config (whether enabled or disabled) always overrides the
    default (All Hospitals) config for that month."""
    hospital_disabled = {
        c.indicator_id
        for c in session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id,
            HospitalIndicatorConfig.is_enabled.is_(False),
        ).all()
    }
    override_ids = set(get_hospital_override_indicator_ids(session, hospital_id))
    default_disabled = set(get_default_disabled_indicator_ids(session, month))
    return list(hospital_disabled | (default_disabled - override_ids))


def get_enabled_values_for_hospital_month(session: Session, hospital_id: int, month: str) -> Dict[str, float]:
    disabled_ids = set(get_effective_manual_disabled_ids(session, hospital_id, month))
    rows = (
        session.query(IndicatorValue, Indicator)
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.month == month,
        )
        .all()
    )
    result = {}
    for val, ind in rows:
        if ind.id in disabled_ids:
            continue
        if val.value is not None:
            result[ind.code] = val.value
    return result


def get_outlier_eligible_codes(session, hospital_id, month,
                                evaluated_codes=None) -> set:
    """The approved denominator for the layered outlier penalty.

    Required elements count whether reported or missing; Optional elements and
    derived rates count only when assessed. Manual disable and covered-by-total
    exclusion apply; auto-disable-on-null deliberately does not. See
    ``app.engine.quality.outlier_eligibility`` for the full policy.
    """
    return eligible_outlier_units(
        session, hospital_id, month, evaluated_codes=evaluated_codes)


def get_optional_source_indicator_ids(session) -> set:
    """Indicator IDs whose whole data-element subtree is Optional.

    Doctrine (COVERAGE-DISABLE-DOCTRINE §1.4): a parent total is only as
    required as the elements it is built from. When EVERY child of a node is
    Optional — or is itself optional by inheritance — the node's absence is a
    legitimate non-event even though its own requirement_type still says
    'Required': the form never asks the hospital to fill it, so counting it in
    the completeness denominator (and naming it in every "has no value for this
    month" list) penalized a value nobody can supply. Live example: 17
    (Neonatal deaths) is Required while all eight of its children are Optional
    or optional-by-inheritance (17.c inherits from its two Optional children).

    A Required LEAF (no children at all, e.g. 14) keeps its own flag — it has
    no source elements to inherit optionality from. Cycles in parent_id are
    treated as NOT optional, so the gate always fails closed.

    This is the single source of truth for the rule: completeness
    (get_required_indicator_ids), the Why popup's data problems, the Audit
    screen and the dashboard diagnostics all read it instead of re-deriving it.
    """
    rows = session.query(
        Indicator.id, Indicator.parent_id, Indicator.requirement_type
    ).all()
    children: Dict[int, List[int]] = {}
    own_optional: Dict[int, bool] = {}
    for iid, parent_id, requirement in rows:
        own_optional[iid] = (requirement or "Required") == "Optional"
        if parent_id is not None:
            children.setdefault(parent_id, []).append(iid)

    resolved: Dict[int, bool] = {}

    def _all_sources_optional(iid: int, seen: frozenset) -> bool:
        if iid in resolved:
            return resolved[iid]
        if iid in seen:                      # cycle: never claim "optional"
            return False
        kids = children.get(iid) or []
        result = (own_optional.get(iid, False) if not kids
                  else all(_all_sources_optional(kid, seen | {iid}) for kid in kids))
        resolved[iid] = result
        return result

    return {iid for iid in own_optional
            if _all_sources_optional(iid, frozenset())}


def get_optional_by_inheritance_ids(session) -> set:
    """Indicator IDs that ARE marked Required yet are optional by inheritance.

    The display counterpart of get_optional_source_indicator_ids: that set
    also contains elements whose own flag is already 'Optional' (nothing to
    explain), while this one keeps only the confusing case — a node the Data
    Tree shows as Required that the completeness denominator silently skips
    because every source element under it is Optional. The tree and the
    indicator catalog mark these distinctly so the exclusion is visible.

    Same rule, same query: it filters the single source of truth rather than
    re-deriving optionality, so the badge can never disagree with the score.
    """
    optional_ids = get_optional_source_indicator_ids(session)
    if not optional_ids:
        return set()
    own_flag = dict(
        session.query(Indicator.id, Indicator.requirement_type)
        .filter(Indicator.id.in_(optional_ids))
        .all()
    )
    return {
        iid for iid in optional_ids
        # Defensive (None) like get_required_indicator_ids: None means Required.
        if (own_flag.get(iid) or "Required") == "Required"
    }


def get_required_indicator_ids(session, hospital_id, month, *,
                               auto_disable_null: bool):
    """Completeness denominator (indicator-groups design rev 2).

    An indicator counts toward the denominator iff:
      enabled   — NOT effectively disabled (hospital override > monthly default
                  > global True), and not auto-disabled (null value / missing
                  row) when the auto_disable_null_indicators setting is on;
      required  — Indicator.requirement_type == 'Required' ('Optional' is
                  excluded from the denominator entirely — doctrine: an
                  Optional indicator is a third legitimate reason for absence,
                  alongside covered-by-total and disabled);
      sourced   — at least one of its source data elements is Required. A node
                  whose whole subtree is Optional is optional by inheritance
                  (get_optional_source_indicator_ids) even when its own flag
                  still says 'Required'.

    Synthetic form-header labels (SYNTHETIC_INDICATOR_CODES, e.g. code "0")
    are excluded, as in every completeness path today. The three completeness
    call sites (pipeline._compute_full_analysis, dashboard._recalc_completeness,
    indicator_config._recalc_hospital_scores) must all compose through this
    helper so they cannot drift apart.

    Returns a sorted list of indicator IDs.
    """
    from app.indicators import SYNTHETIC_INDICATOR_CODES
    disabled_ids = set(get_disabled_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null))
    # Optional by inheritance is resolved once for the whole catalog: every
    # consumer (completeness, diagnostics, Why popups, audit screen) must agree.
    optional_ids = get_optional_source_indicator_ids(session)
    required_ids = [
        iid for (iid, req) in session.query(Indicator.id, Indicator.requirement_type).all()
        if iid not in disabled_ids
        and iid not in optional_ids
        # Defensive (req is None) for rows created before the column had a
        # value — None behaves as 'Required', preserving pre-feature behavior.
        and (req or "Required") == "Required"
    ]
    # Synthetic codes never have a value row, so they are usually already
    # disabled/absent — but exclude them explicitly so they can never slip
    # into the denominator via a stray config row.
    if SYNTHETIC_INDICATOR_CODES:
        syn_ids = {
            r[0] for r in session.query(Indicator.id).filter(
                Indicator.code.in_(SYNTHETIC_INDICATOR_CODES)
            ).all()
        }
        required_ids = [iid for iid in required_ids if iid not in syn_ids]
    return sorted(required_ids)


def get_required_indicator_codes(session, hospital_id, month, *,
                                 auto_disable_null: bool):
    """Required indicators as CODES, for the DB-free compute_completeness core."""
    required_ids = get_required_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
    if not required_ids:
        return set()
    return {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(required_ids)).all()
    }


def compute_hospital_completeness(session, hospital_id, month, *,
                                  auto_disable_null: bool, rules=None):
    """Rev-2 completeness for one hospital/month (0-100), via the single
    DB-free compute_completeness core — so the stored QualityScore rows, the
    dashboard KPI-card recalc and the indicator-config recalc cannot drift:

      numerator   = enabled non-null values (Optional fills included; capped)
      denominator = required indicators minus covered-by-total (required only)
    """
    from app.engine.quality import compute_completeness, compute_covered_codes
    values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
    disabled_codes = {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(disabled_ids)).all()
    } if disabled_ids else set()
    covered_codes = compute_covered_codes(values, disabled_codes, session,
                                          rules=rules)
    required_codes = get_required_indicator_codes(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
    return compute_completeness(values, required_codes, covered_codes) * 100.0


def get_disabled_indicator_ids(session, hospital_id, month, *,
                               auto_disable_null: bool):
    """Indicator IDs that are disabled — manual plus, when the gate is ON, auto.

    ``auto_disable_null`` is required and keyword-only: it comes from the run's
    ``PolicySnapshot``. A missing argument raises ``TypeError`` instead of
    silently re-reading System Control (A3.3).
    """
    manually_disabled = get_effective_manual_disabled_ids(session, hospital_id, month)
    if auto_disable_null:
        null_rows = (
            session.query(IndicatorValue.indicator_id)
            .filter(
                IndicatorValue.hospital_id == hospital_id,
                IndicatorValue.month == month,
                IndicatorValue.value.is_(None),
            )
            .all()
        )
        null_ids = [r[0] for r in null_rows if r[0] not in manually_disabled]

        # Also disable indicators that have NO row at all for this hospital/month
        existing_ids = [
            r[0] for r in session.query(IndicatorValue.indicator_id).filter(
                IndicatorValue.hospital_id == hospital_id,
                IndicatorValue.month == month,
            ).distinct().all()
        ]
        all_indicator_ids = [r[0] for r in session.query(Indicator.id).all()]
        missing_ids = [
            iid for iid in all_indicator_ids
            if iid not in manually_disabled and iid not in existing_ids
        ]

        return manually_disabled + null_ids + missing_ids
    return manually_disabled


def get_all_hospital_data_for_month(session: Session, month: str) -> Dict[str, Dict[str, float]]:
    hospitals = session.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    result = {}
    for hosp in hospitals:
        vals = get_enabled_values_for_hospital_month(session, hosp.id, month)
        if vals:
            result[hosp.name] = vals
    return result


def get_historical_months(session: Session, hospital_id: int, current_month: str) -> Dict[str, Dict[str, float]]:
    rows = (
        session.query(IndicatorValue.month)
        .filter(IndicatorValue.hospital_id == hospital_id)
        .distinct()
        .all()
    )
    months = [r[0] for r in rows if r[0] != current_month]
    result = {}
    for m in months:
        vals = get_enabled_values_for_hospital_month(session, hospital_id, m)
        if vals:
            result[m] = vals
    return result


def check_analysis_exists(session: Session, hospital_id: int, month: str) -> bool:
    """Check if analysis results already exist for a hospital/month."""
    return session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first() is not None


def _stored_issues(row) -> list:
    """The issues list stored on a QualityScore row, defensively parsed."""
    raw = getattr(row, "issues", None)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def is_fallback_quality_row(row) -> bool:
    """True when a stored QualityScore row is a failed-analysis placeholder.

    Why this representation is safe (P3.3.3b-Fix):

    * **Stable** — the marker is ``FALLBACK_ANALYSIS_ISSUE``, a single module
      constant written by exactly one code path (``_analysis_failure_result``).
      No other writer can introduce it without changing this file.
    * **Unambiguous** — a real analysis fills ``issues`` from rule results and
      anomalies (``"<CODE>: <description>"`` / ``"Anomaly: ..."``); it never
      emits that sentence, and the match is exact list membership, so a
      longer message that merely quotes it is not a fallback.
    * **Score-independent** — the score is deliberately NOT part of identity.
      The scoring repair path (``recompute_quality_scores(apply=True)``) can
      rewrite the numeric score from stored evidence while leaving ``issues``
      untouched; gating on ``score == 0`` made such a repaired fallback stop
      being recognised and be served as a successful cached result.
    * **Backward-compatible** — historical fallback rows were written with this
      exact literal by the same path, so rows created before this fix are
      recognised without touching them (no rewrite, no migration).

    A genuine analysis keeps its own issues (real rule/anomaly text), so a
    legitimate zero-score result — or any successful score — is NOT a fallback
    and stays cacheable.
    """
    if row is None:
        return False
    return FALLBACK_ANALYSIS_ISSUE in _stored_issues(row)


def _policy_validation_status(policy: Optional[PolicySnapshot]) -> Optional[str]:
    """Safe validation state of the policy actually carried by a run."""
    if policy is None:
        return None
    if policy.read_error is not None:
        return "unavailable"
    if getattr(policy, "confidence_policy", None) is None:
        return "invalid"
    entries = [entry for entry in policy.entries.values()
               if entry.component == "confidence"]
    if not entries:
        return "unavailable"
    sources = {entry.source for entry in entries}
    if sources == {"default"}:
        return "default"
    if any(entry.validation == "conflict" for entry in entries):
        return "conflict"
    if "invalid" in sources:
        return "fallback"
    return "valid"


def _policy_provenance(policy: Optional[PolicySnapshot]) -> Optional[Dict]:
    """Provenance for the exact snapshot used by this run.

    ``snapshot_provenance`` already omits raw values and row ids. The raw
    ``read_error`` is omitted here as well: it can contain database details and
    is not needed to identify the policy; the stable validation state and
    error keys carry the machine-readable meaning.
    """
    if policy is None:
        return None
    provenance = dict(snapshot_provenance(policy))
    provenance.pop("read_error", None)
    versions = dict(provenance.get("component_versions") or {})
    provenance["confidence_policy_version"] = versions.get("confidence")
    provenance["validation_status"] = _policy_validation_status(policy)
    confidence = dict(provenance.get("confidence") or {})
    entries = [entry for entry in policy.entries.values()
               if entry.component == "confidence"]
    confidence["sources"] = sorted({entry.source for entry in entries})
    confidence["defaults_applied"] = bool(entries) and all(
        entry.source == "default" for entry in entries)
    provenance["confidence"] = confidence
    return provenance


def _with_analysis_metadata(result: Dict, *, policy: Optional[PolicySnapshot],
                            analysis_status: str,
                            provenance_status: str,
                            failure_kind: Optional[str] = None,
                            policy_digest: Optional[str] = None,
                            policy_identity_status: Optional[str] = None) -> Dict:
    """Attach the outcome and the snapshot actually used to a result copy.

    ``policy_digest``/``policy_identity_status`` describe the identity of the
    returned numbers. A fresh run derives them from its snapshot; a cached
    read passes the stored row's values (``recorded`` or ``unknown``).
    """
    enriched = dict(result)
    enriched["analysis_status"] = analysis_status
    enriched["failure_kind"] = failure_kind
    enriched["policy_provenance"] = _policy_provenance(policy)
    enriched["policy_provenance_status"] = provenance_status
    if policy_identity_status is None:
        policy_identity_status = (
            POLICY_IDENTITY_RECORDED
            if policy is not None and policy.digest
            else POLICY_IDENTITY_UNAVAILABLE)
    if policy_digest is None and policy is not None:
        policy_digest = policy.digest
    enriched["policy_digest"] = policy_digest
    enriched["policy_identity_status"] = policy_identity_status
    return enriched


def _analysis_failure_result(session: Session, hospital_id: int, month: str,
                             *, failure_kind: str,
                             policy: Optional[PolicySnapshot]) -> Dict:
    """Preserve the existing rollback/persistence contract, then label it.

    The persisted row carries the fallback marker and NO scoring provenance:
    no scoring configuration produced those zeroes, so the row must look like
    a fallback however it was written (first insert or overwrite).
    """
    # Reset the session after the failed step (PostgreSQL aborts the transaction
    # until ROLLBACK; SQLAlchemy raises PendingRollbackError otherwise).
    try:
        session.rollback()
    except Exception:
        logger.exception("Rollback after analysis failure failed for %s/%s",
                         hospital_id, month)
    try:
        _save_quality_score(session, hospital_id, month, {
            "score": 0,
            "rule_compliance": 0,
            "completeness": 0,
            "consistency": 0,
            "outlier_penalty": 0,
            "issues": [FALLBACK_ANALYSIS_ISSUE],
        }, policy_digest=None, set_policy_identity=True)
    except Exception:
        logger.exception("Could not save fallback quality report for %s/%s",
                         hospital_id, month)
        session.rollback()
    hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    result = {
        "hospital": hospital.name if hospital else None,
        "month": month,
        "data_quality_score": 0,
        "rule_compliance": 0,
        "completeness": 0,
        "consistency": 0,
        "outlier_penalty": 0,
        "issues": [FALLBACK_ANALYSIS_ISSUE],
        "outliers": [],
        "cached": False,
    }
    provenance_status = (POLICY_PROVENANCE_AVAILABLE if policy is not None
                         else POLICY_PROVENANCE_UNAVAILABLE)
    return _with_analysis_metadata(
        result, policy=policy, analysis_status=ANALYSIS_STATUS_FAILED,
        provenance_status=provenance_status, failure_kind=failure_kind)


def _compute_full_analysis(session: Session, hospital_id: int, month: str,
                           force: bool = False,
                           policy: Optional[PolicySnapshot] = None) -> Dict:
    """Analyse one hospital/month from the run's single PolicySnapshot."""
    hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise ValueError(f"Hospital id {hospital_id} not found")

    # Skip analysis if results already exist and not forced
    if not force and check_analysis_exists(session, hospital_id, month):
        existing_qs = session.query(QualityScore).filter(
            QualityScore.hospital_id == hospital_id,
            QualityScore.month == month,
        ).first()
        return {
            "hospital": hospital.name,
            "month": month,
            "data_quality_score": existing_qs.score,
            "rule_compliance": existing_qs.rule_compliance,
            "completeness": existing_qs.completeness,
            "consistency": existing_qs.consistency,
            "outlier_penalty": existing_qs.outlier_penalty,
            "issues": json.loads(existing_qs.issues) if existing_qs.issues else [],
            "outliers": [],
            "cached": True,
            # D5: a cached row is attributed to the policy its run recorded,
            # never to the policy resolved for this read.
            "policy_digest": existing_qs.policy_digest,
            "policy_identity_status": (
                POLICY_IDENTITY_RECORDED if existing_qs.policy_digest
                else POLICY_IDENTITY_UNKNOWN),
            **({
                # P3.3.3b-Fix: a failure placeholder is not a completed
                # analysis. Serving it back must stay a FAILURE — the stored
                # row records no original kind, so report the honest "stored
                # fallback" kind instead of inventing a cause.
                "analysis_status": ANALYSIS_STATUS_FAILED,
                "failure_kind": FAILURE_STORED_FALLBACK,
            } if is_fallback_quality_row(existing_qs) else {}),
        }

    values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    if not values:
        # On a forced recompute (e.g. tree config save) purge stale stored
        # results so screens don't show data for a hospital/month that now
        # has no enabled data. Adhoc loads (force=False) keep existing rows.
        if force:
            session.query(ValidationResult).filter(
                ValidationResult.hospital_id == hospital_id,
                ValidationResult.month == month,
            ).delete(synchronize_session=False)
            session.query(AnomalyResult).filter(
                AnomalyResult.hospital_id == hospital_id,
                AnomalyResult.month == month,
            ).delete(synchronize_session=False)
            session.query(ConfidenceScore).filter(
                ConfidenceScore.hospital_id == hospital_id,
                ConfidenceScore.month == month,
            ).delete(synchronize_session=False)
            session.query(LayeredOutlierResult).filter(
                LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month,
            ).delete(synchronize_session=False)
            session.commit()
        return {
            "hospital": hospital.name,
            "month": month,
            "data_quality_score": 0,
            "issues": ["No data found for this hospital/month"],
            "outliers": [],
        }

    # A3.3: the gate is resolved once, here, from this run's snapshot — before
    # the first eligibility read — and every call below receives it explicitly.
    if policy is None:
        policy = load_policy_snapshot(session)
    auto_disable_null = policy.require_auto_disable_null()

    # A3.5: the rules plane travels with the same snapshot. Every rule and
    # coverage consumer below receives this policy explicitly; the pipeline
    # never writes a process-global rules table again.
    from app.engine.policy_view import rules_policy_from_snapshot
    rules_policy = rules_policy_from_snapshot(policy)
    # P3.3.3a: resolve the Confidence policy once from this run's snapshot.
    confidence_policy = confidence_policy_from_snapshot(policy)

    all_hospital_data = get_all_hospital_data_for_month(session, month)
    historical = get_historical_months(session, hospital_id, month)

    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
    disabled_codes = set()
    if disabled_ids:
        ind_rows = session.query(Indicator).filter(Indicator.id.in_(disabled_ids)).all()
        disabled_codes = {ind.code for ind in ind_rows}

    ctx = ValidationContext(
        values=values,
        hospital_name=hospital.name,
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data=historical if historical else {},
        disabled_codes=disabled_codes,
        rules=rules_policy,
    )

    from app.config_utils import get_config_dict

    # A3.3/A3.4: `policy` was resolved above (or supplied by the caller)
    # before the first eligibility read; nothing below re-resolves it.
    if policy.invalid_keys:
        logger.warning(
            "Analysis %s/%s is using %d fallback value(s) from invalid "
            "stored settings: %s", hospital.name, month,
            len(policy.invalid_keys), ", ".join(policy.invalid_keys))

    analysis_config = analysis_config_from_snapshot(policy)
    # A3.5 P2: trend consumers receive the snapshot-derived policy explicitly;
    # this run no longer rewrites the process-global trend table.
    anomaly_config = {"zscore_threshold": analysis_config.zscore_threshold}

    ml_config = get_config_dict(session, "ml")
    ml_config_nested = _build_ml_config(ml_config)
    ml_results = {}
    if ml_config_nested.get("enabled", False):
        try:
            ml_results = run_ml_analysis(all_hospital_data, ml_config_nested) or {}
        except Exception:
            logger.exception("ML analysis failed for %s/%s; continuing without ML results", hospital.name, month)

    if USE_DB_RULES:
        rule_results = run_rules_from_db(session, ctx)
        if not rule_results:
            import logging
            logging.getLogger(__name__).warning("No rules returned from DB, falling back to compiled rules")
            rule_results = run_all_rules(ctx)
    else:
        rule_results = run_all_rules(ctx)

    # Build indicator code-to-name mapping from DB — synthetic tree labels
    # (e.g. "0" = "Main elements complete ratio") are excluded: they are not
    # data indicators, and letting the resolver see them corrupts plain
    # numbers in rule details ("=12.0" became "=12.Main elements complete ratio").
    all_indicators = session.query(Indicator.code, Indicator.name).all()
    code_to_name = {
        ind.code: ind.name for ind in all_indicators
        if ind.code not in SYNTHETIC_INDICATOR_CODES
    }
    _resolve_codes = _build_code_resolver(code_to_name)
    if _resolve_codes:
        for r in rule_results:
            if r.details:
                r.details = _resolve_codes(r.details)

    from app.engine import indicator_service
    from app.engine.anomaly.layered import is_detection_outlier
    from app.engine.anomaly.projection import (
        project_rate_rows,
        resolved_indicator_map,
        row_z_score,
    )

    # ── ONE detection engine ─────────────────────────────────────────────────
    # The layered engine analyses every data-tree element and every active rate
    # spec, then classifies the finding. The legacy AnomalyResult rows are a
    # PROJECTION of those results — never a second computation — so the
    # dashboard, the audit benchmark, root cause and the outlier drill-down
    # quote the same numbers as Outlier Diagnostics and the Quality Score.
    layered_ok = False
    layered_results = []
    try:
        layered_results = _build_layered_results(
            session, hospital_id, month, values,
            historical if historical else {},
            all_hospital_data,
            anomaly_config["zscore_threshold"],
        )
        layered_ok = True
    except Exception:
        session.rollback()
        logger.exception(
            "Layered analysis failed for %s/%s; falling back to the classic detector",
            hospital.name, month,
        )

    if layered_ok:
        # Provenance for the projected rows: the live registry definition when
        # one exists (indicator_id "derived:<id>", the Quality report's
        # stale-formula check), otherwise the builtin rate spec.
        # Provenance for the projected rows — the ONE builder the Outliers
        # reader also uses to map a stored analysis_code back to the code the
        # projection writes, so that join never depends on a display name.
        resolved_by_code = resolved_indicator_map(
            session, context=f"{hospital.name}/{month}")
        hospital_names = {
            hid: name for hid, name in
            session.query(Hospital.id, Hospital.name)
            .filter(Hospital.is_active.is_(True)).all()
        }
        anomaly_results = project_rate_rows(
            layered_results, resolved_by_code, hospital_names)
    else:
        # Detector down (never a second opinion): keep the month analysable with
        # the classic rows, logged above as a degradation.
        managed_indicators = indicator_service.resolve_outlier_candidates(session)
        classic_rows = detect_anomalies(
            all_hospital_data, hospital.name, month, anomaly_config,
            additional_indicators=managed_indicators)
        classic_rows += detect_monthly_trend(
            historical, month, values, anomaly_config,
            additional_indicators=managed_indicators)
        seen_codes: set = set()
        anomaly_results = []
        for a in classic_rows:
            code = getattr(a, "indicator_code", None)
            if code and code not in seen_codes:
                seen_codes.add(code)
                anomaly_results.append(a)

    # Rev 2 denominator: enabled ∧ requirement_type=='Required' as codes, via
    # the shared helper. Falls back to all non-synthetic, non-disabled codes if
    # the helper fails (e.g. requirement_type column not yet migrated).
    try:
        required_codes = get_required_indicator_codes(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
    except Exception:
        disabled_ids = get_disabled_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
        required_codes = {
            code for (iid, code) in session.query(Indicator.id, Indicator.code).all()
            if iid not in disabled_ids and code not in SYNTHETIC_INDICATOR_CODES
        }
    from app.config_utils import get_config_dict
    quality_config = get_config_dict(session, "quality")
    covered_codes = get_covered_child_codes(ctx, session)

    # The outlier penalty answers "what share of the REQUIRED assessment units
    # were flagged?", not "what share of the rows we happened to evaluate?"
    # Missing required observations therefore stay in the denominator instead
    # of shrinking it; completeness already measures the missingness.
    outlier_eligible_codes = None
    if layered_ok:
        outlier_eligible_codes = get_outlier_eligible_codes(
            session, hospital_id, month,
            evaluated_codes=[_layered_analysis_code(r) for r in layered_results])

    quality = calculate_quality_score(
        rule_results, values, anomaly_results, required_codes, quality_config,
        covered_codes=covered_codes,
        layered_results=layered_results if layered_ok else None,
        outlier_eligible_codes=outlier_eligible_codes,
    )

    indicator_rule_map = build_indicator_rule_map(session)
    all_indicators_db = session.query(Indicator.code, Indicator.name).all()
    indicator_map = {ind.code: ind.name for ind in all_indicators_db}
    indicator_map.update(INDICATOR_CODE_TO_NAME)

    confidence_data = {}
    confidence_persistence_failed = False
    try:
        confidence_result = calculate_confidence(
            hospital_name=hospital.name,
            month=month,
            values=values,
            rule_results=rule_results,
            historical_data=historical if historical else {},
            all_hospital_data=all_hospital_data,
            indicator_map=indicator_map,
            indicator_children=PARENT_CHILD_MAP,
            indicator_rule_map=indicator_rule_map,
            key_indicator_codes=KEY_INDICATOR_CODES,
            disabled_codes=disabled_codes,
            confidence_policy=confidence_policy,
            auto_disable_null=auto_disable_null,
        )
        confidence_data = confidence_result.to_dict()
    except PolicyUnavailable:
        # A configuration failure must not be converted into an ordinary
        # Confidence result; let the run-level fallback expose the failure.
        raise
    except Exception:
        logger.exception("Confidence analysis failed for %s/%s; continuing with core results", hospital.name, month)

    _save_validation_results(session, hospital_id, month, rule_results)
    _save_anomaly_results(session, hospital_id, month, anomaly_results)
    _save_quality_score(session, hospital_id, month, quality,
                        policy_digest=policy.digest,
                        set_policy_identity=True)
    if confidence_data:
        try:
            _save_confidence_score(session, hospital_id, month, confidence_data)
        except Exception:
            # D4: the calculation succeeded but its result was NOT stored. This
            # run is not a success: mark it failed with its own kind and drop
            # the payload so no consumer can read a confidence that the
            # database never accepted. The QualityScore written above stays a
            # genuine result (it is not rewritten as a fallback placeholder).
            confidence_persistence_failed = True
            try:
                session.rollback()
            except Exception:
                pass
            logger.exception(
                "Confidence persistence failed for %s/%s; the run is marked failed",
                hospital.name, month)

    if layered_ok:
        try:
            # Rows were computed before scoring; persist them now. An empty
            # list still clears stale rows for the month.
            _save_layered_results(session, hospital_id, month, layered_results,
                                  zscore_threshold=anomaly_config["zscore_threshold"])
        except Exception:
            # Layered rows are additive (spec §7): never discard the quality/
            # validation/anomaly results already committed above, and never trip
            # run_full_analysis's zero-score fallback report.
            session.rollback()
            logger.exception(
                "Saving layered results failed for %s/%s; continuing without them",
                hospital.name, month,
            )

    outliers = []
    if layered_ok:
        # Same verdict the Outlier Diagnostics screen and the report show.
        for r in layered_results:
            if not is_detection_outlier(r.classification.outlier_level):
                continue
            value = r.rate.rate if r.spec.is_rate else r.raw.value
            # The z of the comparison that produced the benchmark — and no
            # substitute when that comparison was not graded (too few peers to
            # measure a spread produces no z; see projection.row_z_score).
            row_z = row_z_score(r.peer, r.historical)
            outliers.append({
                "indicator": r.spec.name,
                "value": float(value) if value is not None else None,
                "benchmark": (float(r.peer.peer_mean)
                              if r.peer.peer_mean is not None
                              else (float(r.historical.mean)
                                    if r.historical.mean is not None else None)),
                "z_score": float(row_z) if row_z is not None else None,
                "level": r.classification.outlier_level,
                "kind": "rate" if r.spec.is_rate else "element",
            })
    else:
        for a in anomaly_results:
            if a.is_outlier:
                outliers.append({
                    "indicator": a.rate_name,
                    "value": float(a.value) if a.value is not None else None,
                    "benchmark": float(a.benchmark) if a.benchmark is not None else None,
                    "z_score": float(a.z_score) if a.z_score is not None else None,
                })

    result = {
        "hospital": hospital.name,
        "month": month,
        "data_quality_score": quality["score"],
        "rule_compliance": quality["rule_compliance"],
        "completeness": quality["completeness"],
        "consistency": quality["consistency"],
        "outlier_penalty": quality["outlier_penalty"],
        "issues": quality["issues"],
        "outliers": outliers,
        "cached": False,
        # D4: no confidence payload when persistence failed — the run must not
        # expose a "confidence computed" success for data that was not stored.
        "confidence": None if confidence_persistence_failed else {
            "overall_confidence": confidence_data.get("overall_confidence", 0),
            "level": confidence_data.get("level", "UNKNOWN"),
            "by_level": confidence_data.get("by_level", {}),
            "by_group": confidence_data.get("by_group", {}),
            "priority_verify": [
                {
                    "indicator_code": i.get("indicator_code"),
                    "indicator_name": i.get("indicator_name"),
                    "value": i.get("value"),
                    "confidence": i.get("confidence"),
                    "level": i.get("level"),
                    "recommendations": i.get("recommendations", []),
                }
                for i in (confidence_data.get("priority_verify") or [])
            ],
            "summary": confidence_data.get("summary", ""),
        },
        **ml_results,
    }
    if confidence_persistence_failed:
        result["analysis_status"] = ANALYSIS_STATUS_FAILED
        result["failure_kind"] = FAILURE_CONFIDENCE_PERSISTENCE
    return result


def _maybe_auto_scan_quality_alerts(session: Session, month: str, *,
                                   auto_scan: bool,
                                   policy: Optional[PolicySnapshot] = None) -> None:
    """Run the Quality Alerts scan for ``month`` after a fresh analysis.

    ``auto_scan`` is the run's RESOLVED gate (``alerts.auto_scan``, default ON
    when System Control has no row). It is passed in by the caller instead of
    being read here, so the analysis, the scan decision and the scan itself
    cannot disagree about the configuration version (A3.4).

    The scan is month-scoped and covers ALL hospitals, so it is memoized per
    session+month — a bulk upload of N hospitals triggers one scan per month,
    not N. Any failure is rolled back and logged: alerting must never lose or
    block the analysis already persisted above. A configuration read failure
    never reaches this helper: the run entry point fails first.
    """
    if not auto_scan:
        return
    scanned = session.info.setdefault("qa_auto_scanned_months", set())
    if month in scanned:
        return
    try:
        # Lazy import: quality_alerts imports this module for its data helpers.
        from app.engine import quality_alerts
        # The scan that follows an analysis reuses THIS run's snapshot: the
        # alerts and the analysis that triggered them cannot see two
        # versions of the same setting.
        stats = quality_alerts.scan(session, month, policy=policy)
        scanned.add(month)
        if stats.get("created") or stats.get("updated") or stats.get("deactivated"):
            logger.info("Quality Alerts auto-scan %s: %s", month, stats)
    except Exception:
        logger.exception("Quality Alerts auto-scan failed for %s", month)
        try:
            session.rollback()
        except Exception:
            pass


def run_full_analysis(session: Session, hospital_id: int, month: str,
                      force: bool = False,
                      policy: Optional[PolicySnapshot] = None) -> Dict:
    """Run full analysis for a hospital/month, guaranteeing a QualityScore row is
    persisted so the report always appears in /reports/ and /analysis/months.

    ``month`` must be a concrete YYYY-MM. The synthetic '__all__' selector
    (Indicator Tree → All Months) must never reach the persistence layer —
    saving a config with All Months previously persisted a score row with
    month='__all__', which then leaked into reports, trends and dropdowns.

    If analysis reports that no data was found, a score-0 QualityScore is still
    saved (so detected-but-empty months stay visible). If any analysis step
    raises, a minimal quality report is persisted with the error recorded in the
    issues list, instead of the month silently disappearing.
    """
    if month == "__all__" or not re.match(r"^\d{4}-\d{2}$", str(month)):
        raise ValueError(
            f"Invalid month for analysis: {month!r} — expected YYYY-MM (the '__all__' selector must be expanded to concrete months by the caller)"
        )
    try:
        # One snapshot for the whole run — the analysis AND the alerts
        # auto-scan that follows it. The snapshot is resolved BEFORE the
        # cached-report check. That ordering is deliberately unchanged: the
        # current cache row stores no policy identity, so a cached result is
        # labelled ``cached_unavailable`` rather than pretending a newly
        # resolved policy produced it. A read failure here propagates to the
        # established fallback contract below; it is never retried and never
        # becomes a successful analysis result.
        if policy is None:
            policy = load_policy_snapshot(session)
        result = _compute_full_analysis(session, hospital_id, month,
                                        force=force, policy=policy)
        # Empty/missing-data path returns early without persisting — persist it
        # so the detected month still shows a report row.
        if not result.get("cached") and not check_analysis_exists(session, hospital_id, month):
            _save_quality_score(session, hospital_id, month, {
                "score": result.get("data_quality_score", 0),
                "rule_compliance": result.get("rule_compliance", 0),
                "completeness": result.get("completeness", 0),
                "consistency": result.get("consistency", 0),
                "outlier_penalty": result.get("outlier_penalty", 0),
                "issues": result.get("issues") or [],
            }, policy_digest=policy.digest, set_policy_identity=True)
        # Fresh analysis -> refresh this month's Quality Alerts for all
        # hospitals (default on; see _maybe_auto_scan_quality_alerts).
        if not result.get("cached"):
            if policy is None:  # pragma: no cover - _compute_full_analysis resolved it
                raise PolicyUnavailable(
                    "alerts auto-scan reached without the run's policy snapshot")
            _maybe_auto_scan_quality_alerts(
                session, month, auto_scan=policy.alerts_auto_scan,
                policy=policy)
        if result.get("cached"):
            # The row was computed earlier; no snapshot can be attributed to
            # it. Keep the cached result usable, but make the missing identity
            # explicit instead of attaching the policy just resolved here.
            if result.get("analysis_status") == ANALYSIS_STATUS_FAILED:
                # P3.3.3b-Fix: cache recovery must never convert a previous
                # failure into a success. The failure kind found on the stored
                # row is carried through verbatim.
                return _with_analysis_metadata(
                    result, policy=None,
                    analysis_status=ANALYSIS_STATUS_FAILED,
                    provenance_status=POLICY_PROVENANCE_CACHED,
                    failure_kind=(result.get("failure_kind")
                                  or FAILURE_STORED_FALLBACK),
                    policy_digest=result.get("policy_digest"),
                    policy_identity_status=result.get("policy_identity_status"))
            return _with_analysis_metadata(
                result, policy=None, analysis_status=ANALYSIS_STATUS_OK,
                provenance_status=POLICY_PROVENANCE_CACHED,
                policy_digest=result.get("policy_digest"),
                policy_identity_status=result.get("policy_identity_status"))
        # D4: a run that computed its scores but failed to persist a derived
        # artifact (Confidence) is NOT successful. Its failure kind travels
        # with the result; the stored QualityScore stays a genuine row.
        _failed = result.get("analysis_status") == ANALYSIS_STATUS_FAILED
        return _with_analysis_metadata(
            result, policy=policy,
            analysis_status=(ANALYSIS_STATUS_FAILED if _failed
                             else ANALYSIS_STATUS_OK),
            provenance_status=POLICY_PROVENANCE_AVAILABLE,
            failure_kind=(result.get("failure_kind") if _failed else None))
    except ValueError:
        raise
    except PolicyUnavailable as exc:
        logger.exception(
            "Policy configuration failure for %s/%s; saving fallback quality report",
            hospital_id, month)
        failure_kind = (FAILURE_CONFIDENCE_POLICY_INVALID
                        if isinstance(exc, ConfidencePolicyInvalid)
                        else FAILURE_POLICY_UNAVAILABLE)
        return _analysis_failure_result(
            session, hospital_id, month, failure_kind=failure_kind, policy=policy)
    except Exception:
        logger.exception("Full analysis failed for %s/%s; saving fallback quality report", hospital_id, month)
        return _analysis_failure_result(
            session, hospital_id, month, failure_kind=FAILURE_ANALYSIS_ERROR,
            policy=policy)


def purge_derived_results(session: Session, hospital_id: int, month: str = None) -> Dict[str, int]:
    """Delete derived analysis rows for one (hospital, month).

    month=None clears the hospital across every month. Raw IndicatorValue rows
    are left untouched — callers decide whether those go too (Remove Data
    deletes them; re-analysis keeps them).
    """
    counts = {}
    for key, model in (
        ("quality_scores", QualityScore),
        ("validation_results", ValidationResult),
        ("anomaly_results", AnomalyResult),
        ("confidence_scores", ConfidenceScore),
        ("clinical_insights", ClinicalInsight),
        ("layered_outlier_results", LayeredOutlierResult),
    ):
        query = session.query(model).filter(model.hospital_id == hospital_id)
        if month is not None:
            query = query.filter(model.month == month)
        counts[key] = query.delete(synchronize_session=False)
    return counts


class RecomputeResult(int):
    """Successful recompute count plus the batch's structured failure report.

    ``recompute_hospital_months`` has always returned an int, and its callers
    rely on that: Remove Data asserts ``done == 1``, the deep-repair worker
    does ``recomputed += n`` / ``len(months) - n``, the restore scripts print
    ``f"{done}/{len(months)}"``. Subclassing ``int`` keeps every one of those
    unchanged while letting a caller that cares read ``requested``,
    ``succeeded``, ``failed`` and ``failures``. Arithmetic yields a plain int.
    """

    def __new__(cls, succeeded: int, *, requested: int, failures: list):
        obj = super().__new__(cls, succeeded)
        obj.requested = int(requested)
        obj.succeeded = int(succeeded)
        obj.failures = list(failures)
        obj.failed = len(obj.failures)
        return obj

    def as_dict(self) -> Dict:
        return {
            "requested": self.requested,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "failures": [dict(record) for record in self.failures],
        }

    # Rendering is deliberately NOT overridden: an int subclass prints and
    # formats as its plain value (scripts do f"{done}/{len(months)}"). The
    # structured report is read through the attributes or as_dict().


def _recompute_failure(hospital_id: int, month: str, *, failure_kind: str,
                       reason: str, error_type: Optional[str] = None) -> Dict:
    """One failed hospital/month, safe to log or return.

    The reason is flattened and truncated: it identifies the failure without
    carrying multi-line tracebacks or unbounded driver text, and the
    machine-readable kind is never derived from the message.
    """
    return {
        "hospital_id": hospital_id,
        "month": month,
        "failure_kind": failure_kind,
        "error_type": error_type,
        "reason": " ".join(str(reason).split())[:300],
    }


def recompute_hospital_months(
    session: Session,
    hospital_id: int,
    months=None,
    force: bool = True,
    progress_cb=None,
    policy: Optional[PolicySnapshot] = None,
) -> int:
    """Purge derived rows and re-run analysis for a hospital's months.

    months=None means every month that still has indicator values for the
    hospital.

    Returns a :class:`RecomputeResult`: an ``int`` equal to the number of
    months whose analysis SUCCEEDED (the long-standing contract), carrying
    ``requested``, ``succeeded``, ``failed`` and ``failures`` so a partial
    batch can never look like a clean one. A run that ends as a failed-analysis
    placeholder counts as failed, not recomputed. One failing month never
    stops the remaining months.
    """
    if months is None:
        months = sorted({
            r[0] for r in session.query(IndicatorValue.month).filter(
                IndicatorValue.hospital_id == hospital_id,
            ).distinct().all()
        })
    months = list(months)
    # One snapshot for every month of this batch (A3.3).
    if policy is None:
        policy = load_policy_snapshot(session)

    done = 0
    failures: list = []
    for month in months:
        try:
            # Purge and analysis are one unit: a purge/commit failure belongs
            # to this month and must not abort the rest of the batch.
            purge_derived_results(session, hospital_id, month)
            session.commit()
            result = run_full_analysis(session, hospital_id, month,
                                       force=force, policy=policy)
            if (isinstance(result, dict)
                    and result.get("analysis_status") == ANALYSIS_STATUS_FAILED):
                # A fallback row is a failed analysis, not a recompute: never
                # count it as success (the P3.3.3b identity, applied to batches).
                failures.append(_recompute_failure(
                    hospital_id, month,
                    failure_kind=(result.get("failure_kind")
                                  or FAILURE_STORED_FALLBACK),
                    reason="analysis returned a failed-analysis status"))
            else:
                done += 1
        except Exception as exc:
            try:
                session.rollback()
            except Exception:
                pass
            logger.exception("Recompute failed for hospital %s / %s", hospital_id, month)
            failures.append(_recompute_failure(
                hospital_id, month, failure_kind=FAILURE_RECOMPUTE_ERROR,
                error_type=type(exc).__name__, reason=str(exc)))
        if progress_cb:
            try:
                progress_cb(done)
            except Exception:
                pass
    return RecomputeResult(done, requested=len(months), failures=failures)


def revalidate_hospital_months(session: Session, hospital_id: int, months=None,
                               progress_cb=None,
                               policy: Optional[PolicySnapshot] = None) -> int:
    """Re-run the validation rules and refresh the rule-dependent scores.

    A rule edit changes ONLY the rule outcomes. A full analysis would also
    recompute anomalies, ML, the layered diagnostics and confidence (~13 s per
    hospital-month on this dataset); this pass reuses the STORED outlier rows
    for the score and recomputes just:

      * ValidationResult rows — what the Validation Alerts screen lists — and
      * QualityScore's rule_compliance / consistency / combined score.

    ~150 ms per hospital-month, which makes "re-apply the rules to every
    recorded month" affordable instead of only the latest one.

    ``months=None`` means every month with indicator values for the hospital.
    Returns the number of months refreshed.
    """
    from app.config_utils import get_config_dict

    # One snapshot for this batch: every month below shares the same gate.
    if policy is None:
        policy = load_policy_snapshot(session)
    auto_disable_null = policy.require_auto_disable_null()

    hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if hospital is None:
        return 0
    if months is None:
        months = sorted({
            r[0] for r in session.query(IndicatorValue.month).filter(
                IndicatorValue.hospital_id == hospital_id).distinct().all() if r[0]
        })

    quality_config = get_config_dict(session, "quality")
    from app.engine.policy_view import rules_policy_from_snapshot
    rules_policy = rules_policy_from_snapshot(policy)
    code_to_name = {
        code: name for code, name in session.query(Indicator.code, Indicator.name).all()
        if code not in SYNTHETIC_INDICATOR_CODES
    }
    _resolve_codes = _build_code_resolver(code_to_name)

    done = 0
    for month in months:
        values = get_enabled_values_for_hospital_month(session, hospital_id, month)
        if not values:
            continue
        all_hospital_data = get_all_hospital_data_for_month(session, month)
        historical = get_historical_months(session, hospital_id, month)
        disabled_ids = get_disabled_indicator_ids(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
        disabled_codes = set()
        if disabled_ids:
            disabled_codes = {
                ind.code for ind in session.query(Indicator)
                .filter(Indicator.id.in_(disabled_ids)).all()
            }

        ctx = ValidationContext(
            values=values,
            hospital_name=hospital.name,
            month=month,
            all_hospital_data=all_hospital_data,
            historical_data=historical or {},
            disabled_codes=disabled_codes,
        rules=rules_policy,
        )
        rule_results = run_rules_from_db(session, ctx)
        if not rule_results:
            rule_results = run_all_rules(ctx)
        if _resolve_codes:
            for r in rule_results:
                if r.details:
                    r.details = _resolve_codes(r.details)

        try:
            required_codes = get_required_indicator_codes(session, hospital_id, month,
                                                             auto_disable_null=auto_disable_null)
        except Exception:
            required_codes = {
                code for (iid, code) in session.query(Indicator.id, Indicator.code).all()
                if iid not in (disabled_ids or set())
                and code not in SYNTHETIC_INDICATOR_CODES
            }
        covered_codes = get_covered_child_codes(ctx, session)

        # The outlier component keeps whatever the last full analysis stored:
        # layered rows when they exist, classic anomaly rows otherwise (the
        # same precedence the pipeline's scoring uses).
        layered_rows = session.query(LayeredOutlierResult).filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.month == month,
        ).all()
        anomaly_rows = [] if layered_rows else session.query(AnomalyResult).filter(
            AnomalyResult.hospital_id == hospital_id,
            AnomalyResult.month == month,
        ).all()

        outlier_eligible_codes = None
        if layered_rows:
            outlier_eligible_codes = get_outlier_eligible_codes(
                session, hospital_id, month,
                evaluated_codes=[r.analysis_code for r in layered_rows])

        quality = calculate_quality_score(
            rule_results, values, anomaly_rows, required_codes, quality_config,
            covered_codes=covered_codes,
            layered_results=layered_rows if layered_rows else None,
            outlier_eligible_codes=outlier_eligible_codes,
        )
        # The rule outcomes and the score they produce are ONE snapshot: both
        # rows are committed together, so a failure here can never leave new
        # FAIL rows beside the old (often 100%) rule_compliance that the
        # dashboard KPI reads while the Validation Alerts screen lists them.
        try:
            _save_validation_results(session, hospital_id, month, rule_results,
                                     commit=False)
            _save_quality_score(session, hospital_id, month, quality,
                                action="revalidate", commit=False)
            session.commit()
        except Exception:
            session.rollback()
            raise
        done += 1
        if progress_cb:
            try:
                progress_cb(done)
            except Exception:
                pass
    return done


def _save_validation_results(session: Session, hospital_id: int, month: str,
                             results: List[RuleResult], commit: bool = True):
    """Replace the month's stored rule outcomes.

    ``commit=False`` leaves the rows pending so a caller can commit them
    together with the QualityScore they produced. Writing the two snapshots in
    separate transactions let a failure in between leave NEW alert rows beside
    an OLD (often 100%) rule_compliance — the dashboard then reported perfect
    validation while the Validation Alerts screen listed real failures.
    """
    session.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
    ).delete()
    for r in results:
        rule_type = r.rule_type.value if hasattr(r.rule_type, 'value') else str(r.rule_type)
        vr = ValidationResult(
            hospital_id=hospital_id,
            month=month,
            rule_code=r.rule_code,
            rule_description=r.description,
            status=r.status.value,
            severity=r.severity.value,
            rule_type=rule_type,
            details=r.details,
        )
        session.add(vr)
    if commit:
        session.commit()


def _save_anomaly_results(session: Session, hospital_id: int, month: str, results: list):
    session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
    ).delete()
    for a in results:
        ar = AnomalyResult(
            hospital_id=hospital_id,
            month=month,
            indicator_code=a.indicator_code,
            indicator_id=getattr(a, "indicator_id", None),
            formula=getattr(a, "formula", None),
            formula_version=getattr(a, "formula_version", None),
            rate_name=a.rate_name,
            value=float(a.value) if a.value is not None else None,
            benchmark=float(a.benchmark) if a.benchmark is not None else None,
            z_score=float(a.z_score) if a.z_score is not None else None,
            is_outlier=bool(a.is_outlier),
            peer_count=int(a.peer_count) if getattr(a, "peer_count", None) is not None else None,
            peer_std=float(a.peer_std) if getattr(a, "peer_std", None) is not None else None,
            peer_min=float(a.peer_min) if getattr(a, "peer_min", None) is not None else None,
            peer_max=float(a.peer_max) if getattr(a, "peer_max", None) is not None else None,
            peer_median=float(a.peer_median) if getattr(a, "peer_median", None) is not None else None,
            peers_detail=getattr(a, "peers_detail", None),
        )
        session.add(ar)
    session.commit()


def _build_layered_results(session: Session, hospital_id: int, month: str,
                           values: Dict, historical: Dict,
                           all_hospital_data: Dict,
                           zscore_threshold: float) -> list:
    """Run the layered outlier pipeline (spec §7) for the analyzed hospital
    and return the rows that should be persisted — WITHOUT writing anything.

    get_historical_months() excludes the current month (pipeline.py:262), so
    the current month's enabled values are merged in — analyze_layered_entry
    splits history itself. peer inputs arrive name-keyed from
    get_all_hospital_data_for_month() and are re-keyed by hospital id here;
    tier attributes come straight from the Hospital columns.
    """
    from app.engine.anomaly.layered import (
        Thresholds,
        build_analysis_specs,
        run_layered_analysis,
        should_persist,
    )

    specs = build_analysis_specs(session)
    hospitals = (
        session.query(
            Hospital.id, Hospital.name, Hospital.hospital_type_id,
            Hospital.facility_ownership_id, Hospital.governorate_id,
        )
        .filter(Hospital.is_active.is_(True))
        .all()
    )
    peer_values_by_hospital = {
        h.id: {month: all_hospital_data.get(h.name, {})}
        for h in hospitals
    }
    peer_attributes = {
        h.id: {
            "type": h.hospital_type_id,
            "ownership": h.facility_ownership_id,
            "governorate": h.governorate_id,
        }
        for h in hospitals
    }
    history = dict(historical)
    history[month] = values

    from app.engine.comparison_policy import load_comparison_policy

    comparison_policy = load_comparison_policy(session)
    results = run_layered_analysis(
        specs, history, month, hospital_id,
        peer_values_by_hospital, peer_attributes,
        Thresholds(peer_z_threshold=float(zscore_threshold),
                   min_peers=comparison_policy.peer.min_peers),
        history_policy=comparison_policy.history,
        peer_policy=comparison_policy.peer,
    )
    return [r for r in results if should_persist(r)]


def _save_layered_results(session: Session, hospital_id: int, month: str, results: list,
                          zscore_threshold: Optional[float] = None):
    from app.engine.anomaly.layered import (
        MIN_PEERS_FOR_TOP_BAND,
        THIN_PEER_LEVEL_CAP,
        ZERO_SPREAD_LEVEL_CAP,
    )
    from app.engine.comparison_policy import (
        COMPARISON_POLICY_VERSION,
        DETECTION_PEER_GROUP,
    )

    session.query(LayeredOutlierResult).filter(
        LayeredOutlierResult.hospital_id == hospital_id,
        LayeredOutlierResult.month == month,
    ).delete()
    for r in results:
        c = r.classification
        session.add(LayeredOutlierResult(
            hospital_id=hospital_id,
            indicator_id=r.spec.indicator_id,
            analysis_code=r.spec.analysis_code,
            month=month,
            raw_value=float(r.raw.value) if r.raw.value is not None else None,
            previous_value=float(r.raw.previous) if r.raw.previous is not None else None,
            numerator=float(r.raw.value) if (r.spec.is_rate and r.raw.value is not None) else None,
            denominator=(float(r.volume.denominator)
                         if r.volume and r.volume.denominator is not None else None),
            rate=float(r.rate.rate) if r.rate.rate is not None else None,
            previous_denominator=(float(r.volume.previous)
                                  if r.volume and r.volume.previous is not None else None),
            denominator_change_percent=(float(r.volume.change_percent)
                                        if r.volume and r.volume.change_percent is not None else None),
            historical_mean=(float(r.historical.mean)
                             if r.historical.mean is not None else None),
            historical_median=(float(r.historical.median)
                               if r.historical.median is not None else None),
            historical_std=(float(r.historical.std)
                            if r.historical.std is not None else None),
            historical_z_score=(float(r.historical.z_score)
                                if r.historical.z_score is not None else None),
            historical_change_percent=(float(r.historical.change_percent)
                                       if r.historical.change_percent is not None else None),
            raw_value_outlier_score=(float(r.raw.score)
                                     if r.raw.score is not None else None),
            rate_outlier_score=(float(r.rate.score)
                                if r.rate.score is not None else None),
            historical_outlier_score=(float(r.historical.score)
                                      if r.historical.score is not None else None),
            volume_anomaly_score=(float(r.volume.score)
                                  if r.volume and r.volume.score is not None else None),
            peer_outlier_score=(float(r.peer.score)
                                if r.peer.score is not None else None),
            peer_mean=float(r.peer.peer_mean) if r.peer.peer_mean is not None else None,
            peer_count=r.peer.peer_count,
            outlier_level=c.outlier_level,
            outlier_type=c.outlier_type,
            outlier_method=c.method,
            interpretation=c.interpretation,
            investigation_required=c.investigation_required,
            investigation_route=c.investigation_route,
            history_provenance={
                "policy_version": COMPARISON_POLICY_VERSION,
                "window": r.historical.window,
                "min_observations": r.historical.min_observations,
                "months": list(r.historical.window_months),
                "values": [float(v) for v in r.historical.series],
                "skipped_months": list(r.historical.skipped_months),
            },
            peer_provenance={
                "policy_version": COMPARISON_POLICY_VERSION,
                # The engine's canonical tier is named "all"; persist the
                # policy's stable group id so readers do not depend on that
                # internal label.
                "group": (DETECTION_PEER_GROUP
                          if r.peer.group in (None, "all")
                          else r.peer.group),
                "month": month,
                "min_peers": r.peer.min_peers,
                "scored_peer_count": r.peer.peer_count,
                "eligible_count": r.peer.eligible_count,
                "peer_ids": list(r.peer.eligible_ids),
                "values": dict(r.peer.peer_values or {}),
            },
            # Which layers could not grade a magnitude — no spread at all, or a
            # peer group too small to measure one — and the band their raw
            # scores alone implied. Readers use this to explain the level, and
            # the Why popup re-applies the same caps when it recomputes the
            # classification.
            classification_provenance={
                "policy_version": COMPARISON_POLICY_VERSION,
                # The z threshold this row was CLASSIFIED with. The top-band
                # eligibility gate is applied at read time and must ask the
                # same question the scan answered; without this the gate falls
                # back to today's setting and a row classified under a
                # different threshold is graded with the wrong scale.
                "zscore_threshold": (float(zscore_threshold)
                                     if zscore_threshold is not None else None),
                "zero_spread_layers": list(c.zero_spread_layers),
                "thin_peer_layers": list(c.thin_peer_layers),
                "min_peers_for_top_band": MIN_PEERS_FOR_TOP_BAND,
                "level_from_layers": (c.level_capped_from
                                      or c.outlier_level),
                "level": c.outlier_level,
                "cap": (ZERO_SPREAD_LEVEL_CAP
                        if c.zero_spread_layers else
                        (THIN_PEER_LEVEL_CAP if c.thin_peer_layers else None)),
            },
        ))
    session.commit()


def _save_quality_score(session: Session, hospital_id: int, month: str, quality: Dict,
                        action: str = "analysis", actor: str = "system", commit: bool = True,
                        policy_digest: Optional[str] = None,
                        set_policy_identity: bool = False):
    """Persist the computed score WITH its scoring configuration provenance.

    An overwrite is recorded in quality_score_revisions first, so the values
    that were replaced (and the configuration that produced them) stay
    explainable.

    D5: an analysis run also stamps the policy identity it used. Writers that
    have no policy (dashboard recalculation, indicator toggles, repair) leave
    the recorded identity untouched instead of erasing it.
    """
    from app.engine.quality.scoring_audit import apply_score_update

    existing = session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    changes = dict(
        score=quality["score"],
        rule_compliance=quality["rule_compliance"],
        completeness=quality["completeness"],
        consistency=quality["consistency"],
        outlier_penalty=quality["outlier_penalty"],
        issues=json.dumps(quality["issues"]),
    )
    if existing:
        # ``scoring_config`` is absent for config-less writes (the failed-
        # analysis fallback): passing None keeps the row provenance-free
        # instead of raising and losing the fallback entirely.
        apply_score_update(session, existing, quality.get("scoring_config"),
                           action, actor,
                           policy_digest=policy_digest,
                           set_policy_identity=set_policy_identity, **changes)
    else:
        qs = QualityScore(
            hospital_id=hospital_id,
            month=month,
            scoring_fingerprint=quality.get("scoring_fingerprint"),
            scoring_config=quality.get("scoring_config"),
            policy_digest=(policy_digest if set_policy_identity else None),
            **changes,
        )
        session.add(qs)
    if commit:
        session.commit()


def _save_confidence_score(session: Session, hospital_id: int, month: str, confidence_data: Dict):
    existing = session.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if existing:
        existing.overall_confidence = confidence_data["overall_confidence"]
        existing.level = confidence_data["level"]
        existing.indicator_count = confidence_data["indicator_count"]
        existing.high_count = confidence_data["by_level"].get("HIGH", 0)
        existing.medium_count = confidence_data["by_level"].get("MEDIUM", 0)
        existing.low_count = confidence_data["by_level"].get("LOW", 0)
        existing.critical_count = confidence_data["by_level"].get("CRITICAL", 0)
        existing.indicators_data = json.dumps(confidence_data["indicators"])
        existing.summary = confidence_data["summary"]
    else:
        cs = ConfidenceScore(
            hospital_id=hospital_id,
            month=month,
            overall_confidence=confidence_data["overall_confidence"],
            level=confidence_data["level"],
            indicator_count=confidence_data["indicator_count"],
            high_count=confidence_data["by_level"].get("HIGH", 0),
            medium_count=confidence_data["by_level"].get("MEDIUM", 0),
            low_count=confidence_data["by_level"].get("LOW", 0),
            critical_count=confidence_data["by_level"].get("CRITICAL", 0),
            indicators_data=json.dumps(confidence_data["indicators"]),
            summary=confidence_data["summary"],
        )
        session.add(cs)
    session.commit()
