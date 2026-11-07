import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.database import get_db
from app.engine.confidence import (
    HospitalConfidenceResult,
    build_indicator_rule_map,
    calculate_confidence,
)
from app.engine.confidence_policy import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MEDIUM,
    DEFAULT_WEIGHTS,
    DEFAULT_ZSCORE_THRESHOLD,
    WEIGHT_KEYS,
    ConfidencePolicy,
    validate_weight_update,
    validate_weight_values,
)
from app.engine.config_resolver import (
    PolicySnapshot,
    PolicyUnavailable,
    load_display_policy,
)
from app.engine.pipeline import (
    get_all_hospital_data_for_month,
    get_enabled_values_for_hospital_month,
    get_historical_months,
)
from app.engine.policy_view import (
    ConfidencePolicyInvalid,
    confidence_policy_from_snapshot,
    rules_policy_from_snapshot,
)
from app.engine.quality import ValidationContext, run_all_rules, run_rules_from_db
from app.indicators import INDICATOR_CODE_TO_NAME, PARENT_CHILD_MAP
from app.models import ConfidenceScore, ConfidenceWeights, Hospital, Indicator
from app.schemas import ConfidenceComparisonOut, HospitalConfidenceOut

logger = logging.getLogger(__name__)

_POLICY_UNAVAILABLE_DETAIL = (
    "Confidence policy unavailable; configuration could not be resolved."
)

router = APIRouter(prefix="/confidence", tags=["confidence"], dependencies=[Depends(require_permission("analysis.read"))])

KEY_INDICATOR_CODES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "17", "18", "26"]


def _run_confidence_for_hospital(
    db: Session,
    hospital_id: int,
    month: str,
    *,
    display_policy: Optional[PolicySnapshot] = None,
    confidence_policy: Optional[ConfidencePolicy] = None,
) -> HospitalConfidenceResult:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise ValueError(f"Hospital id {hospital_id} not found")

    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not values:
        raise ValueError(f"No data found for hospital {hospital.name} / {month}")

    all_hospital_data = get_all_hospital_data_for_month(db, month)
    historical = get_historical_months(db, hospital_id, month)

    if display_policy is None:
        display_policy = load_display_policy(db)
    if confidence_policy is None:
        confidence_policy = confidence_policy_from_snapshot(display_policy)
    ctx = ValidationContext(
        values=values,
        hospital_name=hospital.name,
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data=historical if historical else None,
        rules=rules_policy_from_snapshot(display_policy),
    )

    rule_results = run_rules_from_db(db, ctx)
    if not rule_results:
        rule_results = run_all_rules(ctx)

    indicator_rule_map = build_indicator_rule_map(db)

    all_indicators = db.query(Indicator.code, Indicator.name).all()
    indicator_map = {ind.code: ind.name for ind in all_indicators}
    indicator_map.update(INDICATOR_CODE_TO_NAME)

    # Build disabled-indicator set so calculate_confidence excludes them from
    # assessed list. A3.3: the auto-disable gate is resolved once here and
    # passed explicitly — neither helper reads System Control itself.
    from app.engine.pipeline import get_disabled_indicator_ids
    _auto_disable_null = display_policy.require_auto_disable_null()
    _disabled_ids = set(get_disabled_indicator_ids(
        db, hospital_id, month, auto_disable_null=_auto_disable_null))
    _ind_rows = db.query(Indicator.id, Indicator.code).all()
    _id_to_code = {i: c for i, c in _ind_rows}
    _disabled_codes = {_id_to_code[d] for d in _disabled_ids if d in _id_to_code}

    result = calculate_confidence(
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
        disabled_codes=_disabled_codes,
        confidence_policy=confidence_policy,
        auto_disable_null=_auto_disable_null,
    )
    return result


@router.get("/{hospital_id:int}", response_model=HospitalConfidenceOut)
def get_confidence_scores(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    try:
        result = _run_confidence_for_hospital(db, hospital_id, month)
    except (PolicyUnavailable, ConfidencePolicyInvalid) as e:
        logger.warning(
            "Confidence policy unavailable for hospital %s/%s: %s",
            hospital_id, month, e)
        raise HTTPException(
            status_code=503, detail=_POLICY_UNAVAILABLE_DETAIL) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error computing confidence for hospital {hospital_id}/{month}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}") from e
    return result.to_dict()


@router.get("/{hospital_id}/summary")
def get_confidence_summary(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    try:
        result = _run_confidence_for_hospital(db, hospital_id, month)
    except (PolicyUnavailable, ConfidencePolicyInvalid) as e:
        logger.warning(
            "Confidence policy unavailable for hospital %s/%s: %s",
            hospital_id, month, e)
        raise HTTPException(
            status_code=503, detail=_POLICY_UNAVAILABLE_DETAIL) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    d = result.to_dict()
    return {
        "hospital": d["hospital"],
        "month": d["month"],
        "overall_confidence": d["overall_confidence"],
        "level": d["level"],
        "by_level": d["by_level"],
        "by_group": d["by_group"],
        "priority_verify_count": len(d["priority_verify"]),
        "priority_indicators": [
            {"code": i["indicator_code"], "name": i["indicator_name"], "confidence": i["confidence"], "level": i["level"]}
            for i in d["priority_verify"]
        ],
        "summary": d["summary"],
    }


@router.get("/compare/all", response_model=List[ConfidenceComparisonOut])
def compare_hospital_confidence(
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    try:
        display_policy = load_display_policy(db)
        confidence_policy = confidence_policy_from_snapshot(display_policy)
    except (PolicyUnavailable, ConfidencePolicyInvalid) as e:
        logger.warning(
            "Confidence policy unavailable for the %s comparison batch: %s",
            month, e)
        raise HTTPException(
            status_code=503, detail=_POLICY_UNAVAILABLE_DETAIL) from e
    results: List[dict] = []
    for hosp in hospitals:
        vals = get_enabled_values_for_hospital_month(db, hosp.id, month)
        if not vals:
            continue
        try:
            result = _run_confidence_for_hospital(
                db, hosp.id, month,
                display_policy=display_policy,
                confidence_policy=confidence_policy,
            )
            d = result.to_dict()
            results.append(ConfidenceComparisonOut(
                hospital=d["hospital"],
                hospital_id=hosp.id,
                overall_confidence=d["overall_confidence"],
                level=d["level"],
                critical_count=d["by_level"].get("CRITICAL", 0),
                low_count=d["by_level"].get("LOW", 0),
                medium_count=d["by_level"].get("MEDIUM", 0),
                high_count=d["by_level"].get("HIGH", 0),
            ))
        except (PolicyUnavailable, ConfidencePolicyInvalid) as e:
            logger.warning(
                "Confidence policy unavailable for hospital %s/%s: %s",
                hosp.id, month, e)
            raise HTTPException(
                status_code=503, detail=_POLICY_UNAVAILABLE_DETAIL) from e
        except Exception as e:
            logger.warning(f"Could not compute confidence for {hosp.name}/{month}: {e}")
            continue
    results.sort(key=lambda r: r.overall_confidence, reverse=True)
    return results


@router.get("/{hospital_id}/stored")
def get_stored_confidence(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    db: Session = Depends(get_db),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    cs = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if not cs:
        raise HTTPException(status_code=404, detail="No stored confidence score. Run analysis first.")
    import json
    indicators = json.loads(cs.indicators_data) if cs.indicators_data else []
    return {
        "hospital": hosp.name,
        "hospital_id": hospital_id,
        "month": cs.month,
        "overall_confidence": cs.overall_confidence,
        "level": cs.level,
        "indicator_count": cs.indicator_count,
        "by_level": {
            "HIGH": cs.high_count,
            "MEDIUM": cs.medium_count,
            "LOW": cs.low_count,
            "CRITICAL": cs.critical_count,
        },
        "indicators": indicators,
        "summary": cs.summary,
        "created_at": cs.created_at.isoformat() if cs.created_at else None,
    }


_WEIGHTS_READ_DETAIL = (
    "Confidence weights unavailable; configuration could not be read."
)

_WEIGHTS_CORRUPT_DETAIL = (
    "Stored confidence weights are invalid; submit the complete weight set."
)


def _confidence_weight_rows(db: Session):
    """Every stored weights row, lowest id first — the resolver's own order.

    ``confidence_weights`` is a singleton in intent but has no uniqueness
    constraint, so duplicates are possible. The resolver selects the lowest id
    and reports the rest as a conflict; this endpoint reads the same way and
    never deletes, merges or rewrites the other rows.
    """
    return (db.query(ConfidenceWeights)
            .order_by(ConfidenceWeights.id.asc())
            .all())


def _stored_weight_values(row) -> dict:
    return {key: getattr(row, key) for key in WEIGHT_KEYS}


def _weights_policy(weights: dict) -> ConfidencePolicy:
    """Validate/normalize the five weights through the single policy owner.

    Cutoffs and the raw Z threshold are not part of this endpoint, so the
    policy defaults fill those scalars; only the weights influence validation
    and normalization here.
    """
    return ConfidencePolicy(
        rule_compliance=weights["rule_compliance"],
        historical=weights["historical"],
        cross_hospital=weights["cross_hospital"],
        trend=weights["trend"],
        completeness=weights["completeness"],
        high=DEFAULT_HIGH,
        medium=DEFAULT_MEDIUM,
        low=DEFAULT_LOW,
        zscore_threshold=DEFAULT_ZSCORE_THRESHOLD,
    )


def _weights_response(*, submitted: dict, policy: ConfidencePolicy,
                      source: str, validation: str, row_ids, error=None) -> dict:
    """Response with the legacy five keys plus explicit submitted/effective.

    The five top-level keys keep their previous meaning — the values the
    Settings form displays and edits (the submitted/stored set) — so the
    existing UI contract is unchanged. ``effective`` carries the normalized
    values actually used for calculation, and the validation fields make a
    conflicted or invalid stored configuration explicit instead of silent.
    """
    submitted_values = {key: float(submitted[key]) for key in WEIGHT_KEYS}
    effective = {key: policy.weight_for(key) for key in WEIGHT_KEYS}
    return {
        **submitted_values,
        "submitted": submitted_values,
        "effective": effective,
        "normalized": bool(policy.normalization_applied),
        "source": source,
        "validation": validation,
        "valid": validation != "invalid",
        "conflict": len(row_ids) > 1,
        "row_id": row_ids[0] if row_ids else None,
        "row_ids": list(row_ids),
        "error": error,
    }


@router.get("/weights")
def get_confidence_weights(db: Session = Depends(get_db)):
    """Read the Confidence weights without ever writing.

    A missing row returns the documented defaults and creates nothing. A valid
    row returns its submitted values plus the normalized effective values. A
    duplicate set selects the lowest id and reports every observed id as a
    conflict without modifying any row. A row that ``ConfidencePolicy`` cannot
    validate is reported as ``validation: invalid`` with the documented
    defaults and the reason — never presented as if those were the stored
    values. Only an unreadable store is a 503.
    """
    try:
        rows = _confidence_weight_rows(db)
    except SQLAlchemyError as exc:
        logger.warning("Confidence weights could not be read: %s", exc)
        raise HTTPException(
            status_code=503, detail=_WEIGHTS_READ_DETAIL) from exc

    row_ids = [row.id for row in rows]
    if not rows:
        return _weights_response(
            submitted=dict(DEFAULT_WEIGHTS),
            policy=ConfidencePolicy.defaults(),
            source="default", validation="default", row_ids=(),
        )

    try:
        submitted = validate_weight_values(
            _stored_weight_values(rows[0]))
        policy = _weights_policy(submitted)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Stored confidence weights row %s is invalid: %s", row_ids[0], exc)
        return _weights_response(
            submitted=dict(DEFAULT_WEIGHTS),
            policy=ConfidencePolicy.defaults(),
            source="default", validation="invalid", row_ids=row_ids,
            error=f"stored confidence weights are invalid: {exc}",
        )

    return _weights_response(
        submitted=submitted, policy=policy, source="database",
        validation=("conflict" if len(row_ids) > 1 else "ok"),
        row_ids=row_ids,
    )


@router.put("/weights", dependencies=[Depends(require_permission("settings.write"))])
def update_confidence_weights(weights: dict, db: Session = Depends(get_db)):
    """Validate the complete resulting policy, then persist the submitted set.

    A partial payload is merged onto the current **valid** stored weights (or
    the documented defaults when no row exists) and the complete result is
    validated through ``ConfidencePolicy`` before anything is written. The
    submitted values are stored as submitted; normalization is for calculation
    only. Invalid input is a 422, an unusable stored base or unreadable store
    a 503, and a persistence failure rolls back and returns 500. Duplicate
    rows are never merged or deleted: only the lowest-id row is updated.
    """
    try:
        rows = _confidence_weight_rows(db)
    except SQLAlchemyError as exc:
        logger.warning("Confidence weights could not be read: %s", exc)
        raise HTTPException(
            status_code=503, detail=_WEIGHTS_READ_DETAIL) from exc

    row_ids = [row.id for row in rows]
    selected = rows[0] if rows else None
    complete = isinstance(weights, dict) and set(weights) == set(WEIGHT_KEYS)

    current = None
    if selected is not None:
        try:
            current = validate_weight_values(_stored_weight_values(selected))
        except (TypeError, ValueError) as exc:
            if not complete:
                # A partial update needs a valid base; merging onto defaults
                # would silently repair a corrupt stored policy.
                logger.warning(
                    "Partial confidence weight update refused; row %s is "
                    "invalid: %s", selected.id, exc)
                raise HTTPException(
                    status_code=503, detail=_WEIGHTS_CORRUPT_DETAIL) from exc

    try:
        merged = validate_weight_update(weights, current)
        policy = _weights_policy(merged)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        if selected is None:
            selected = ConfidenceWeights(**merged)
            db.add(selected)
        else:
            for key in WEIGHT_KEYS:
                setattr(selected, key, merged[key])
        db.commit()
        db.refresh(selected)
    except Exception as exc:  # noqa: BLE001 - rolled back and reported
        db.rollback()
        logger.error("Could not persist confidence weights: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Confidence weights could not be saved.") from exc

    persisted_ids = row_ids or [selected.id]
    response = _weights_response(
        submitted=merged, policy=policy, source="database",
        validation=("conflict" if len(persisted_ids) > 1 else "ok"),
        row_ids=persisted_ids,
    )
    response["updated_at"] = (
        selected.updated_at.isoformat() if selected.updated_at else None)
    return response
