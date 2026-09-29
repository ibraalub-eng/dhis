from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig
from app.schemas import (
    HospitalIndicatorConfigOut, ConfigToggleOut,
    IndicatorUpdate, IndicatorOut, IndicatorBase, RequirementTypeIn,
)
from app.core.deps import require_permission

router = APIRouter(prefix="/hospitals", tags=["hospitals"], dependencies=[Depends(require_permission("settings.read"))])


def _get_or_create_config(db: Session, hospital_id: int, indicator_id: int) -> HospitalIndicatorConfig:
    config = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id == hospital_id,
        HospitalIndicatorConfig.indicator_id == indicator_id,
    ).first()
    if not config:
        config = HospitalIndicatorConfig(
            hospital_id=hospital_id,
            indicator_id=indicator_id,
            is_enabled=True,
        )
        db.add(config)
        db.flush()
    return config


def _get_default_state(db: Session, indicator_id: int, month: str | None):
    """Return the default (All Hospitals) config state for an indicator/month, or None.
    With month='__all__' the indicator counts as disabled when disabled in ANY month."""
    if not month:
        return None
    from app.models import IndicatorDefaultConfig
    if month == "__all__":
        rows = db.query(IndicatorDefaultConfig.is_enabled).filter(
            IndicatorDefaultConfig.indicator_id == indicator_id,
        ).all()
        if not rows:
            return None
        enabled = [e for (e,) in rows]
        if not all(enabled):
            return False
        return True
    cfg = db.query(IndicatorDefaultConfig).filter(
        IndicatorDefaultConfig.indicator_id == indicator_id,
        IndicatorDefaultConfig.month == month,
    ).first()
    return cfg.is_enabled if cfg else None


def _get_effective_state(db: Session, hospital_id: int, indicator_id: int, month: str | None):
    """Effective enabled state = per-hospital override if present, else the monthly default, else True."""
    config = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id == hospital_id,
        HospitalIndicatorConfig.indicator_id == indicator_id,
    ).first()
    if config is not None:
        return config.is_enabled
    default_state = _get_default_state(db, indicator_id, month)
    if default_state is not None:
        return default_state
    return True


def _get_all_descendant_ids(db: Session, indicator_id: int) -> List[int]:
    """Recursively find all descendant indicator DB ids."""
    children = (
        db.query(Indicator.id)
        .filter(Indicator.parent_id == indicator_id)
        .all()
    )
    result = []
    for (child_id,) in children:
        result.append(child_id)
        result.extend(_get_all_descendant_ids(db, child_id))
    return result



def _recalc_hospital_scores(db: Session, hospital_id: int):
    """Recalculate completeness and overall score for a specific hospital's quality scores.

    Completeness comes from the single shared rev-2 formula
    (pipeline.compute_hospital_completeness) — identical to what
    run_full_analysis writes, so toggles can never drift the stored rows
    away from a fresh analysis.
    """
    from app.engine.pipeline import compute_hospital_completeness as _chc
    from app.models import QualityScore, AppConfig
    scores = db.query(QualityScore).filter(QualityScore.hospital_id == hospital_id).all()
    if not scores:
        return
    # Get weights
    try:
        cfg_rows = db.query(AppConfig).all()
        cfg_map = {c.key: c.value for c in cfg_rows}
        w_rc = float(cfg_map.get("quality_rule_compliance", "0.35"))
        w_cp = float(cfg_map.get("quality_completeness", "0.25"))
        w_co = float(cfg_map.get("quality_consistency", "0.25"))
        w_op = float(cfg_map.get("quality_outlier_penalty", "0.15"))
    except Exception:
        w_rc, w_cp, w_co, w_op = 0.35, 0.25, 0.25, 0.15
    for s in scores:
        try:
            new_cp = round(_chc(db, s.hospital_id, s.month), 1)
            s.completeness = new_cp
            rc = float(s.rule_compliance or 0) / 100
            cp = new_cp / 100
            co = float(s.consistency or 0) / 100
            op = float(s.outlier_penalty or 0) / 100
            s.score = max(0, min(100, round((rc * w_rc + cp * w_cp + co * w_co + (1.0 - op) * w_op) * 100, 1)))
        except Exception:
            pass
    db.commit()


def _recalc_all_hospital_scores(db: Session):
    """Recalculate completeness and overall score for ALL hospitals."""
    from sqlalchemy import func
    hospital_ids = [h.id for h in db.query(Hospital.id).filter(Hospital.is_active.is_(True)).all()]
    for hid in hospital_ids:
        _recalc_hospital_scores(db, hid)


@router.get("/{hospital_id}/indicator-config", response_model=List[HospitalIndicatorConfigOut])
def get_hospital_indicator_config(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    indicators = db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    configs = {
        c.indicator_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == hospital_id
        ).all()
    }

    results = []
    for ind in indicators:
        config = configs.get(ind.id)
        results.append(HospitalIndicatorConfigOut(
            id=config.id if config else 0,
            hospital_id=hospital_id,
            indicator_id=ind.id,
            indicator_code=ind.code,
            indicator_name=ind.name,
            is_enabled=config.is_enabled if config else True,
            weight_override=config.weight_override if config else None,
            default_weight=ind.default_weight or 1.0,
        ))
    return results


@router.put("/{hospital_id}/indicators/{indicator_id}/toggle", response_model=ConfigToggleOut)
def toggle_indicator(
    hospital_id: int,
    indicator_id: int,
    month: Optional[str] = Query(None, description="Month YYYY-MM used to resolve the inherited default state"),
    cascade: bool = Query(False, description="Also toggle all descendant indicators"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    # Toggle the EFFECTIVE state (per-hospital override else monthly default), then
    # record the result as a per-hospital override so it wins over the default.
    current_effective = _get_effective_state(db, hospital_id, indicator_id, month)
    new_state = not current_effective
    config = _get_or_create_config(db, hospital_id, indicator_id)

    if cascade:
        descendant_ids = _get_all_descendant_ids(db, indicator_id)
        for desc_id in descendant_ids:
            desc_effective = _get_effective_state(db, hospital_id, desc_id, month)
            desc_new = not desc_effective
            desc_config = _get_or_create_config(db, hospital_id, desc_id)
            desc_config.is_enabled = desc_new
        config.is_enabled = new_state
        msg = f"Branch '{indicator.name}' and all {len(descendant_ids)} sub-indicators {'enabled' if new_state else 'disabled'} for {hospital.name}"
    else:
        config.is_enabled = new_state
        msg = f"Indicator '{indicator.name}' {'enabled' if new_state else 'disabled'} for {hospital.name}"

    db.commit()
    db.refresh(config)
    try:
        _recalc_hospital_scores(db, hospital_id)
    except Exception:
        pass
    return ConfigToggleOut(
        hospital_id=hospital_id,
        indicator_id=indicator_id,
        is_enabled=new_state,
        message=msg,
    )


@router.get("/indicators/never-reported")
def get_never_reported_indicators(db: Session = Depends(get_db)):
    """List enabled indicators that have NO value rows in the entire history.

    These are the recurring "ghost gaps" that resurface after every new import:
    indicators the SRMNH form still contains but that no hospital ever reports
    (e.g. 16 NICU admissions, 2.k/2.l, 11.a/11.b, 12, 21, 26). They drag
    completeness down every month and reappear in missing-indicator lists.

    The synthetic form-header labels (SYNTHETIC_INDICATOR_CODES, e.g. code "0"
    "Main elements complete ratio") are excluded — they are already hidden
    from every engine and are never counted as missing.
    """
    from app.indicators import SYNTHETIC_INDICATOR_CODES

    reported_ids = {
        iid for (iid,) in db.query(IndicatorValue.indicator_id).distinct().all()
    }
    never = []
    for ind in db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all():
        if ind.id in reported_ids or ind.code in SYNTHETIC_INDICATOR_CODES:
            continue
        never.append({
            "indicator_id": ind.id,
            "code": ind.code,
            "name": ind.name,
            "disabled": False,   # recomputed below from live configs
        })
    if never:
        never_ids = [i["indicator_id"] for i in never]
        disabled_ids = {
            iid for (iid,) in db.query(HospitalIndicatorConfig.indicator_id).filter(
                HospitalIndicatorConfig.indicator_id.in_(never_ids),
                HospitalIndicatorConfig.is_enabled.is_(False),
            ).distinct().all()
        }
        for i in never:
            i["disabled"] = i["indicator_id"] in disabled_ids
    return {
        "indicators": never,
        "count": len(never),
        "disabled_count": sum(1 for i in never if i["disabled"]),
    }


@router.post("/indicators/disable-never-reported")
def disable_never_reported_indicators(
    dry_run: bool = Query(False, description="Preview the affected indicators without changing anything"),
    db: Session = Depends(get_db),
):
    """Disable every enabled indicator that has no value rows in the entire
    history, for all hospitals at once (default scope, month-agnostic).

    This is the doctrine-sanctioned way to silence indicators the SRMNH form
    carries but no hospital ever reports — the completeness engines already
    treat hospital_indicator_configs.is_enabled=false as "not required"
    (docs/COVERAGE-DISABLE-DOCTRINE.md §3). New imports cannot resurrect the
    gap: the config rows survive re-uploads, and if a hospital ever DOES
    report one of these indicators, the admin simply re-enables it from the
    tree.

    Returns the affected codes; with dry_run=true nothing is written.
    """
    from app.indicators import SYNTHETIC_INDICATOR_CODES

    reported_ids = {
        iid for (iid,) in db.query(IndicatorValue.indicator_id).distinct().all()
    }
    targets = [
        ind for ind in db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
        if ind.id not in reported_ids and ind.code not in SYNTHETIC_INDICATOR_CODES
    ]
    hospital_ids = [h.id for h in db.query(Hospital.id).filter(Hospital.is_active.is_(True)).all()]
    if dry_run or not targets or not hospital_ids:
        return {
            "dry_run": dry_run,
            "disabled": [{"code": t.code, "name": t.name} for t in targets],
            "count": len(targets),
            "hospital_count": len(hospital_ids),
            "message": (
                f"{len(targets)} never-reported indicator(s) would be disabled for "
                f"{len(hospital_ids)} hospital(s)"
                if targets else "No never-reported indicators found — nothing to disable"
            ),
        }

    target_ids = [t.id for t in targets]
    existing = {
        (c.hospital_id, c.indicator_id): c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
            HospitalIndicatorConfig.indicator_id.in_(target_ids),
        ).all()
    }
    for hid in hospital_ids:
        for iid in target_ids:
            config = existing.get((hid, iid))
            if not config:
                db.add(HospitalIndicatorConfig(
                    hospital_id=hid, indicator_id=iid, is_enabled=False,
                ))
            else:
                config.is_enabled = False
    db.commit()

    try:
        from app.cache import cache as _smart_cache
        _smart_cache.invalidate("smart_drilldown_")
        _smart_cache.invalidate("smart_trend_")
        _smart_cache.invalidate("smart_overview_")
    except Exception:
        pass
    try:
        _recalc_all_hospital_scores(db)
    except Exception:
        pass
    return {
        "dry_run": False,
        "disabled": [{"code": t.code, "name": t.name} for t in targets],
        "count": len(targets),
        "hospital_count": len(hospital_ids),
        "message": (
            f"Disabled {len(targets)} never-reported indicator(s) "
            f"for {len(hospital_ids)} hospital(s) and recalculated scores"
        ),
    }


def _all_known_months(db: Session):
    """Return every month that appears in indicator values or default configs."""
    from app.models import IndicatorDefaultConfig
    months = set()
    for (m,) in db.query(IndicatorValue.month).distinct().all():
        months.add(m)
    for (m,) in db.query(IndicatorDefaultConfig.month).distinct().all():
        months.add(m)
    return sorted(months)


@router.put("/indicators/{indicator_id}/toggle-default")
def toggle_default_indicator(
    indicator_id: int,
    month: str = Query(..., description="Month YYYY-MM, or '__all__' to apply to every known month"),
    cascade: bool = Query(False, description="Also toggle all descendant indicators"),
    db: Session = Depends(get_db),
):
    """Toggle the default (All Hospitals) config for an indicator.

    With month='__all__' the new state is applied to every known month.

    This config is inherited by every hospital that lacks a per-hospital override."""
    from app.models import IndicatorDefaultConfig

    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    months = [month]
    if month == "__all__":
        months = _all_known_months(db)

    target_ids = [indicator_id]
    if cascade:
        target_ids += _get_all_descendant_ids(db, indicator_id)

    existing = {
        (c.month, c.indicator_id): c
        for c in db.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.month.in_(months),
        ).all()
    }
    # The effective state across the targets/months: enabled only if currently enabled everywhere.
    all_current_enabled = all(
        existing.get((m, iid), IndicatorDefaultConfig(is_enabled=True)).is_enabled
        for m in months
        for iid in target_ids
    )
    new_state = not all_current_enabled

    for m in months:
        for iid in target_ids:
            cfg = existing.get((m, iid))
            if not cfg:
                db.add(IndicatorDefaultConfig(
                    indicator_id=iid, month=m, is_enabled=new_state,
                ))
            else:
                cfg.is_enabled = new_state
    db.commit()

    try:
        from app.api.indicator_config import _recalc_all_hospital_scores
        _recalc_all_hospital_scores(db)
    except Exception:
        pass
    return {
        "indicator_id": indicator_id,
        "month": month,
        "cascade": cascade,
        "is_enabled": new_state,
        "message": f"{'Enabled' if new_state else 'Disabled'} default for {len(target_ids)} indicator(s) in {month}",
    }


@router.put("/{hospital_id}/indicators/{indicator_id}/weight", response_model=ConfigToggleOut)
def update_indicator_weight(
    hospital_id: int,
    indicator_id: int,
    weight: Optional[float] = Query(None),
    reset: bool = Query(False),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    config = _get_or_create_config(db, hospital_id, indicator_id)
    if reset:
        config.weight_override = None
    else:
        config.weight_override = weight
    db.commit()
    db.refresh(config)
    return ConfigToggleOut(
        hospital_id=hospital_id,
        indicator_id=indicator_id,
        is_enabled=config.is_enabled,
        message="Weight updated" if not reset else "Weight reset to default",
    )


@router.put("/indicators/reorder")
def bulk_reorder_indicators(
    body: dict,
    db: Session = Depends(get_db),
):
    """Bulk reorder: pass {"items": [{"id": 1, "sort_order": 0}, {"id": 2, "sort_order": 1}, ...]}"""
    items = body.get("items", [])
    for item in items:
        ind = db.query(Indicator).filter(Indicator.id == item["id"]).first()
        if ind:
            ind.sort_order = item["sort_order"]
    db.commit()
    return {"message": f"{len(items)} indicators reordered"}


@router.put("/indicators/{indicator_id}", response_model=IndicatorOut)
def update_global_indicator(
    indicator_id: int,
    update: IndicatorUpdate,
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    if update.name is not None:
        ind.name = update.name
    if update.formula is not None:
        ind.formula = update.formula
    if update.default_weight is not None:
        ind.default_weight = update.default_weight
    db.commit()
    db.refresh(ind)
    return ind


@router.post("/indicators", response_model=IndicatorOut)
def create_global_indicator(
    indicator: IndicatorBase,
    db: Session = Depends(get_db),
):
    existing = db.query(Indicator).filter(Indicator.code == indicator.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Indicator code '{indicator.code}' already exists")
    db_ind = Indicator(
        code=indicator.code,
        name=indicator.name,
        parent_id=indicator.parent_id,
        level=indicator.level,
        sort_order=indicator.sort_order,
        group_name=indicator.group_name,
    )
    db.add(db_ind)
    db.commit()
    db.refresh(db_ind)
    return db_ind


@router.delete("/indicators/{indicator_id}")
def delete_global_indicator(
    indicator_id: int,
    cascade: bool = Query(False, description="Also delete all descendant indicators"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")

    children = db.query(Indicator).filter(Indicator.parent_id == indicator_id).count()
    if children > 0 and not cascade:
        raise HTTPException(
            status_code=400,
            detail=f"Indicator '{ind.code}' has {children} child indicators. Use cascade=true to delete them all.",
        )

    if cascade:
        descendant_ids = _get_all_descendant_ids(db, indicator_id)
        for desc_id in descendant_ids + [indicator_id]:
            db.query(HospitalIndicatorConfig).filter(
                HospitalIndicatorConfig.indicator_id == desc_id
            ).delete()
            db.query(IndicatorValue).filter(
                IndicatorValue.indicator_id == desc_id
            ).delete()
        db.query(Indicator).filter(Indicator.id.in_(descendant_ids + [indicator_id])).delete(synchronize_session=False)
    else:
        db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == indicator_id
        ).delete()
        db.query(IndicatorValue).filter(
            IndicatorValue.indicator_id == indicator_id
        ).delete()
        db.query(Indicator).filter(Indicator.id == indicator_id).delete()

    db.commit()
    return {"message": f"Indicator '{ind.code}' deleted", "indicator_id": indicator_id, "cascade": cascade}


@router.put("/indicators/{indicator_id}/reparent")
def reparent_indicator(
    indicator_id: int,
    new_parent_id: Optional[int] = Query(None, description="New parent indicator id, or null for root"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")

    if new_parent_id is not None:
        parent = db.query(Indicator).filter(Indicator.id == new_parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent indicator not found")
        if new_parent_id == indicator_id:
            raise HTTPException(status_code=400, detail="Cannot set self as parent")
        descendants = _get_all_descendant_ids(db, indicator_id)
        if new_parent_id in descendants:
            raise HTTPException(status_code=400, detail="Cannot set a descendant as parent (circular reference)")

    ind.parent_id = new_parent_id
    db.commit()
    db.refresh(ind)
    return {"message": f"Indicator '{ind.code}' reparented", "indicator_id": indicator_id, "new_parent_id": new_parent_id}


@router.put("/indicators/{indicator_id}/global-toggle")
def global_toggle_indicator(
    indicator_id: int,
    cascade: bool = Query(False, description="Also toggle all descendant indicators"),
    db: Session = Depends(get_db),
):
    """Enable or disable an indicator for ALL hospitals."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    if not hospitals:
        raise HTTPException(status_code=400, detail="No hospitals exist")

    hospital_ids = [h.id for h in hospitals]

    configs = {
        c.hospital_id: c
        for c in db.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == indicator_id
        ).all()
    }
    all_enabled = all(
        configs.get(h.id, HospitalIndicatorConfig(is_enabled=True)).is_enabled
        for h in hospitals
    )
    new_state = not all_enabled

    target_ids = [indicator_id]
    if cascade:
        target_ids += _get_all_descendant_ids(db, indicator_id)

    existing = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.indicator_id.in_(target_ids),
    ).all()
    existing_set = {(c.hospital_id, c.indicator_id) for c in existing}

    new_configs = []
    for tid in target_ids:
        for h in hospitals:
            if (h.id, tid) not in existing_set:
                new_configs.append(HospitalIndicatorConfig(
                    hospital_id=h.id, indicator_id=tid, is_enabled=new_state,
                ))
    if new_configs:
        db.add_all(new_configs)
        db.flush()

    db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id.in_(hospital_ids),
        HospitalIndicatorConfig.indicator_id.in_(target_ids),
    ).update({"is_enabled": new_state}, synchronize_session=False)

    db.commit()
    try:
        _recalc_all_hospital_scores(db)
    except Exception:
        pass
    count = len(target_ids) * len(hospitals)
    return {
        "indicator_id": indicator_id,
        "cascade": cascade,
        "is_enabled": new_state,
        "message": f"{'Enabled' if new_state else 'Disabled'} indicator for all {len(hospitals)} hospitals ({count} configs updated)",
    }


@router.put("/indicators/{indicator_id}/sort-order")
def set_indicator_sort_order(
    indicator_id: int,
    order: int = Query(..., description="New sort order"),
    db: Session = Depends(get_db),
):
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    ind.sort_order = order
    db.commit()
    return {"message": f"Sort order updated to {order}", "indicator_id": indicator_id, "sort_order": order}


@router.put(
    "/indicators/{indicator_id}/requirement-type",
    dependencies=[Depends(require_permission("settings.write"))],
)
def set_requirement_type(
    indicator_id: int,
    body: RequirementTypeIn,
    db: Session = Depends(get_db),
):
    """Set an indicator's completeness requirement type (rev 2).

    'Required' → counts in the completeness denominator (today's behavior).
    'Optional' → excluded from the denominator entirely — a third legitimate
    absence reason alongside covered-by-total and disabled, per the
    Coverage-Disable Doctrine. All three completeness call sites apply the
    same filter, so the flag takes effect after the standard recalculation.
    """
    if body.requirement_type not in ("Required", "Optional"):
        raise HTTPException(status_code=422, detail="requirement_type must be 'Required' or 'Optional'")
    ind = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    ind.requirement_type = body.requirement_type
    db.commit()
    try:
        _recalc_all_hospital_scores(db)
    except Exception:
        pass
    return {
        "indicator_id": indicator_id,
        "requirement_type": body.requirement_type,
        "message": f"Indicator '{ind.code}' set to {body.requirement_type}",
    }
