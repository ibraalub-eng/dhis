import json
import logging
import re
from typing import Dict, List

from sqlalchemy.orm import Session

from app.engine.anomaly import detect_anomalies, detect_monthly_trend, set_trends_config
from app.engine.confidence import build_indicator_rule_map, calculate_confidence
from app.engine.ml import run_ml_analysis
from app.engine.quality import (
    RuleResult,
    ValidationContext,
    calculate_quality_score,
    get_covered_child_codes,
    run_all_rules,
    run_rules_from_db,
    set_rules_config,
)
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

USE_DB_RULES = True

KEY_INDICATOR_CODES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "17", "18", "26"]


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


def _is_auto_disable_null(session):
    from app.models import SystemSetting
    row = session.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
    return bool(row and row.value == "true")


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


def get_required_indicator_ids(session, hospital_id, month):
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
    disabled_ids = set(get_disabled_indicator_ids(session, hospital_id, month))
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


def get_required_indicator_codes(session, hospital_id, month):
    """Required indicators as CODES, for the DB-free compute_completeness core."""
    required_ids = get_required_indicator_ids(session, hospital_id, month)
    if not required_ids:
        return set()
    return {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(required_ids)).all()
    }


def compute_hospital_completeness(session, hospital_id, month):
    """Rev-2 completeness for one hospital/month (0-100), via the single
    DB-free compute_completeness core — so the stored QualityScore rows, the
    dashboard KPI-card recalc and the indicator-config recalc cannot drift:

      numerator   = enabled non-null values (Optional fills included; capped)
      denominator = required indicators minus covered-by-total (required only)
    """
    from app.engine.quality import compute_completeness, compute_covered_codes
    values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
    disabled_codes = {
        code for (code,) in session.query(Indicator.code)
        .filter(Indicator.id.in_(disabled_ids)).all()
    } if disabled_ids else set()
    covered_codes = compute_covered_codes(values, disabled_codes, session)
    required_codes = get_required_indicator_codes(session, hospital_id, month)
    return compute_completeness(values, required_codes, covered_codes) * 100.0


def get_disabled_indicator_ids(session, hospital_id, month):
    """Return all indicator IDs that should be considered disabled — manual + auto (null values + missing rows)."""
    manually_disabled = get_effective_manual_disabled_ids(session, hospital_id, month)
    if _is_auto_disable_null(session):
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


def _compute_full_analysis(session: Session, hospital_id: int, month: str, force: bool = False) -> Dict:
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

    all_hospital_data = get_all_hospital_data_for_month(session, month)
    historical = get_historical_months(session, hospital_id, month)

    disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
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
    )

    from app.config_utils import get_config_dict
    from app.engine.severity import load_analysis_config

    rules_config = get_config_dict(session, "rules")
    set_rules_config(rules_config)

    # Saved severity/trend configuration (System Control) is authoritative —
    # including the trend controls stored as SystemSetting rows and the single
    # zscore_threshold. A configuration read failure raises and is reported by
    # the caller; it never silently falls back to hardcoded rules.
    analysis_config = load_analysis_config(session)
    trends_config = get_config_dict(session, "trends")
    rates_config = get_config_dict(session, "rates")
    trends_config.update(rates_config)
    trends_config.update(analysis_config.trend_engine_config())
    set_trends_config(trends_config)

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
    from app.engine.anomaly.projection import project_rate_rows

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
        candidates = indicator_service.resolve_outlier_candidates(session)
        resolved_by_code = {resolved.code: resolved for resolved in candidates}
        # A rate_config code ("rate_cs") has no registry record of its own; the
        # same rate lives in the registry under its definition code. Match them
        # by formula + scale so the projected row keeps the definition's id
        # (the Quality report's stale-formula check reads it).
        by_formula = {}
        for resolved in candidates:
            definition = getattr(resolved, "definition", None)
            if definition is None or not definition.denominator_codes:
                continue
            by_formula.setdefault(
                (tuple(definition.numerator_codes or ()),
                 tuple(definition.denominator_codes or ()),
                 round(float(definition.multiplier or 1.0), 6)),
                resolved)
        try:
            from app.engine.rate_config import load_rate_specs
            for code, rate_spec in load_rate_specs(session).items():
                key = (tuple(rate_spec.numerator_codes),
                       tuple(rate_spec.denominator_codes),
                       round(float(rate_spec.rate_multiplier or 1.0), 6))
                resolved_by_code.setdefault(
                    code, by_formula.get(key)
                    or indicator_service.resolve_spec(rate_spec))
        except Exception:
            logger.exception(
                "Rate specs unreadable for %s/%s; projecting without their provenance",
                hospital.name, month,
            )
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
        required_codes = get_required_indicator_codes(session, hospital_id, month)
    except Exception:
        disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
        required_codes = {
            code for (iid, code) in session.query(Indicator.id, Indicator.code).all()
            if iid not in disabled_ids and code not in SYNTHETIC_INDICATOR_CODES
        }
    from app.config_utils import get_config_dict
    quality_config = get_config_dict(session, "quality")
    covered_codes = get_covered_child_codes(ctx, session)

    quality = calculate_quality_score(
        rule_results, values, anomaly_results, required_codes, quality_config,
        covered_codes=covered_codes,
        layered_results=layered_results if layered_ok else None,
    )

    indicator_rule_map = build_indicator_rule_map(session)
    all_indicators_db = session.query(Indicator.code, Indicator.name).all()
    indicator_map = {ind.code: ind.name for ind in all_indicators_db}
    indicator_map.update(INDICATOR_CODE_TO_NAME)

    confidence_data = {}
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
            session=session,
        )
        confidence_data = confidence_result.to_dict()
    except Exception:
        logger.exception("Confidence analysis failed for %s/%s; continuing with core results", hospital.name, month)

    _save_validation_results(session, hospital_id, month, rule_results)
    _save_anomaly_results(session, hospital_id, month, anomaly_results)
    _save_quality_score(session, hospital_id, month, quality)
    if confidence_data:
        try:
            _save_confidence_score(session, hospital_id, month, confidence_data)
        except Exception:
            logger.exception("Saving confidence score failed for %s/%s", hospital.name, month)

    if layered_ok:
        try:
            # Rows were computed before scoring; persist them now. An empty
            # list still clears stale rows for the month.
            _save_layered_results(session, hospital_id, month, layered_results)
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
            outliers.append({
                "indicator": r.spec.name,
                "value": float(value) if value is not None else None,
                "benchmark": (float(r.peer.peer_mean)
                              if r.peer.peer_mean is not None
                              else (float(r.historical.mean)
                                    if r.historical.mean is not None else None)),
                "z_score": (float(r.peer.z) if r.peer.z is not None
                            else (float(r.historical.z_score)
                                  if r.historical.z_score is not None else None)),
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

    return {
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
        "confidence": {
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


def _maybe_auto_scan_quality_alerts(session: Session, month: str) -> None:
    """Run the Quality Alerts scan for ``month`` after a fresh analysis.

    Default ON (AppConfig ``alerts_auto_scan`` = 1, category ``alerts``):
    uploaded / re-analysed data raises its alerts without anyone pressing
    Run Scan. The scan is month-scoped and covers ALL hospitals, so it is
    memoized per session+month — a bulk upload of N hospitals triggers one
    scan per month, not N. Any failure is rolled back and logged: alerting
    must never lose or block the analysis already persisted above.
    """
    try:
        from app.config_utils import get_config_dict
        flag = str(get_config_dict(session, "alerts").get("alerts_auto_scan", 1)).strip()
        if flag in ("0", "0.0", "false", "False", "off"):
            return
    except Exception:
        logger.exception("Quality Alerts auto-scan config check failed; scanning anyway")
    scanned = session.info.setdefault("qa_auto_scanned_months", set())
    if month in scanned:
        return
    try:
        # Lazy import: quality_alerts imports this module for its data helpers.
        from app.engine import quality_alerts
        stats = quality_alerts.scan(session, month)
        scanned.add(month)
        if stats.get("created") or stats.get("updated") or stats.get("deactivated"):
            logger.info("Quality Alerts auto-scan %s: %s", month, stats)
    except Exception:
        logger.exception("Quality Alerts auto-scan failed for %s", month)
        try:
            session.rollback()
        except Exception:
            pass


def run_full_analysis(session: Session, hospital_id: int, month: str, force: bool = False) -> Dict:
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
        result = _compute_full_analysis(session, hospital_id, month, force=force)
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
            })
        # Fresh analysis -> refresh this month's Quality Alerts for all
        # hospitals (default on; see _maybe_auto_scan_quality_alerts).
        if not result.get("cached"):
            _maybe_auto_scan_quality_alerts(session, month)
        return result
    except ValueError:
        raise
    except Exception:
        logger.exception("Full analysis failed for %s/%s; saving fallback quality report", hospital_id, month)
        # The failed step (e.g. _save_anomaly_results) aborts the DB transaction
        # (PostgreSQL: "current transaction is aborted"). Any further use of the
        # session without rollback raises InFailedSqlTransaction — "This
        # Session's transaction has been rolled back due to a previous
        # exception" — which then cascades to every later hospital/month of a
        # bulk re-analysis. Reset the session before the fallback save.
        try:
            session.rollback()
        except Exception:
            logger.exception("Rollback after analysis failure failed for %s/%s", hospital_id, month)
        try:
            _save_quality_score(session, hospital_id, month, {
                "score": 0,
                "rule_compliance": 0,
                "completeness": 0,
                "consistency": 0,
                "outlier_penalty": 0,
                "issues": ["Analysis failed during report generation"],
            })
        except Exception:
            logger.exception("Could not save fallback quality report for %s/%s", hospital_id, month)
            session.rollback()
        hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
        return {
            "hospital": hospital.name if hospital else None,
            "month": month,
            "data_quality_score": 0,
            "rule_compliance": 0,
            "completeness": 0,
            "consistency": 0,
            "outlier_penalty": 0,
            "issues": ["Analysis failed during report generation"],
            "outliers": [],
            "cached": False,
        }


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


def recompute_hospital_months(
    session: Session,
    hospital_id: int,
    months=None,
    force: bool = True,
    progress_cb=None,
) -> int:
    """Purge derived rows and re-run analysis for a hospital's months.

    months=None means every month that still has indicator values for the
    hospital. Returns the number of months successfully recomputed.
    """
    if months is None:
        months = sorted({
            r[0] for r in session.query(IndicatorValue.month).filter(
                IndicatorValue.hospital_id == hospital_id,
            ).distinct().all()
        })
    done = 0
    for month in months:
        purge_derived_results(session, hospital_id, month)
        session.commit()
        try:
            run_full_analysis(session, hospital_id, month, force=force)
            done += 1
        except Exception:
            session.rollback()
            logger.exception("Recompute failed for hospital %s / %s", hospital_id, month)
        if progress_cb:
            try:
                progress_cb(done)
            except Exception:
                pass
    return done


def revalidate_hospital_months(session: Session, hospital_id: int, months=None,
                               progress_cb=None) -> int:
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

    hospital = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if hospital is None:
        return 0
    if months is None:
        months = sorted({
            r[0] for r in session.query(IndicatorValue.month).filter(
                IndicatorValue.hospital_id == hospital_id).distinct().all() if r[0]
        })

    quality_config = get_config_dict(session, "quality")
    set_rules_config(get_config_dict(session, "rules"))
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
        disabled_ids = get_disabled_indicator_ids(session, hospital_id, month)
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
        )
        rule_results = run_rules_from_db(session, ctx)
        if not rule_results:
            rule_results = run_all_rules(ctx)
        if _resolve_codes:
            for r in rule_results:
                if r.details:
                    r.details = _resolve_codes(r.details)

        try:
            required_codes = get_required_indicator_codes(session, hospital_id, month)
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

        quality = calculate_quality_score(
            rule_results, values, anomaly_rows, required_codes, quality_config,
            covered_codes=covered_codes,
            layered_results=layered_rows if layered_rows else None,
        )
        _save_validation_results(session, hospital_id, month, rule_results)
        _save_quality_score(session, hospital_id, month, quality)
        done += 1
        if progress_cb:
            try:
                progress_cb(done)
            except Exception:
                pass
    return done


def _save_validation_results(session: Session, hospital_id: int, month: str, results: List[RuleResult]):
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

    results = run_layered_analysis(
        specs, history, month, hospital_id,
        peer_values_by_hospital, peer_attributes,
        Thresholds(peer_z_threshold=float(zscore_threshold)),
    )
    return [r for r in results if should_persist(r)]


def _save_layered_results(session: Session, hospital_id: int, month: str, results: list):
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
        ))
    session.commit()


def _save_quality_score(session: Session, hospital_id: int, month: str, quality: Dict):
    existing = session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    if existing:
        existing.score = quality["score"]
        existing.rule_compliance = quality["rule_compliance"]
        existing.completeness = quality["completeness"]
        existing.consistency = quality["consistency"]
        existing.outlier_penalty = quality["outlier_penalty"]
        existing.issues = json.dumps(quality["issues"])
    else:
        qs = QualityScore(
            hospital_id=hospital_id,
            month=month,
            score=quality["score"],
            rule_compliance=quality["rule_compliance"],
            completeness=quality["completeness"],
            consistency=quality["consistency"],
            outlier_penalty=quality["outlier_penalty"],
            issues=json.dumps(quality["issues"]),
        )
        session.add(qs)
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
