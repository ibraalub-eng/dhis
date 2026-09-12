from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import List
import logging
import re
import threading
from app.database import get_db
from app.cache import cache
from app.models import (
    Hospital, Indicator, IndicatorValue,
    QualityScore, ValidationResult, ConfidenceScore, AnomalyResult,
)
from app.schemas import HospitalOut, IndicatorOut, HospitalCreate
from app.engine.pipeline import (
    run_full_analysis,
    purge_derived_results,
    recompute_hospital_months,
)
from app.tasks import create_task, run_task
from app.core.deps import require_permission
from app import undo_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hospitals", tags=["hospitals"], dependencies=[Depends(require_permission("hospitals.read"))])


@router.get("/", response_model=List[HospitalOut])
def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    include_inactive: bool = Query(False, description="Include inactive hospitals"),
    db: Session = Depends(get_db),
    user=Depends(require_permission("hospitals.read")),
):
    cache_key = cache.make_key("hospitals:list", uid=getattr(user, "id", 0), skip=skip, limit=limit, include_inactive=include_inactive)
    cached = cache.get(cache_key)
    if cached:
        result = []
        for item in cached:
            if isinstance(item, dict):
                result.append(item)
            else:
                d = {
                    "id": item.id,
                    "name": item.name,
                    "region": item.region,
                    "governorate_id": item.governorate_id,
                    "hospital_type_id": item.hospital_type_id,
                    "organisation_unit_id": item.organisation_unit_id,
                    "facility_ownership_id": item.facility_ownership_id,
                    "facility_type_id": item.facility_type_id,
                    "address": item.address,
                    "is_active": item.is_active,
                    "created_at": item.created_at,
                    "governorate_name": item.governorate.name if item.governorate else None,
                    "hospital_type_name": item.hospital_type.name if item.hospital_type else None,
                    "facility_ownership_name": item.facility_ownership.name if item.facility_ownership else None,
                    "facility_type_name": item.facility_type.name if item.facility_type else None,
                }
                result.append(d)
        return result
    q = db.query(Hospital)

    # Filter by user's assigned hospitals (if any)
    if user and not getattr(user, 'is_superuser', False):
        from app.models import user_hospitals as _uh
        from sqlalchemy import select as _sel
        _assigned = [row[0] for row in db.execute(_sel(_uh.c.hospital_id).where(_uh.c.user_id == user.id)).fetchall()]
        if _assigned:
            q = q.filter(Hospital.id.in_(_assigned))

    if not include_inactive:
        q = q.filter(Hospital.is_active.is_(True))
    hospitals = q.offset(skip).limit(limit).all()
    result = []
    for h in hospitals:
        result.append({
            "id": h.id,
            "name": h.name,
            "region": h.region,
            "governorate_id": h.governorate_id,
            "hospital_type_id": h.hospital_type_id,
            "organisation_unit_id": h.organisation_unit_id,
            "facility_ownership_id": h.facility_ownership_id,
            "facility_type_id": h.facility_type_id,
            "address": h.address,
            "is_active": h.is_active,
            "created_at": h.created_at,
            "governorate_name": h.governorate.name if h.governorate else None,
            "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
            "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
            "facility_type_name": h.facility_type.name if h.facility_type else None,
        })
    cache.set(cache_key, result)
    return result


@router.post("/", response_model=HospitalOut)
def create_hospital(data: HospitalCreate, db: Session = Depends(get_db)):
    existing = db.query(Hospital).filter(Hospital.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Hospital already exists")
    hosp = Hospital(
        name=data.name,
        region=data.region,
        governorate_id=data.governorate_id,
        hospital_type_id=data.hospital_type_id,
        organisation_unit_id=data.organisation_unit_id,
        facility_ownership_id=data.facility_ownership_id,
        facility_type_id=data.facility_type_id,
        address=data.address,
    )
    db.add(hosp)
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp


@router.put("/{hospital_id}/toggle-active")
def toggle_hospital_active(hospital_id: int, db: Session = Depends(get_db)):
    """Toggle a hospital's active status. Inactive hospitals are excluded from analysis and reports."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    hospital.is_active = not hospital.is_active
    db.commit()
    cache.invalidate()
    return {"id": hospital.id, "name": hospital.name, "is_active": hospital.is_active}


@router.put("/{hospital_id}/clear-data")
def clear_hospital_data(
    hospital_id: int,
    month: str = Query(None, description="If set, only clear this month. Otherwise clear ALL data."),
    db: Session = Depends(get_db),
):
    """Clear indicator values for a hospital (optionally filtered by month).

    Also clears every derived analysis row: quality scores, validation results,
    anomalies, confidence scores and clinical results.
    """
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    iv_query = db.query(IndicatorValue).filter(IndicatorValue.hospital_id == hospital_id)
    if month:
        iv_query = iv_query.filter(IndicatorValue.month == month)
    iv_count = iv_query.delete(synchronize_session=False)
    derived = purge_derived_results(db, hospital_id, month or None)
    db.commit()

    _invalidate_analysis_caches(db)
    msg = (
        f"Cleared {iv_count} indicator values, {derived['quality_scores']} quality scores, "
        f"{derived['validation_results']} validation results, {derived['anomaly_results']} anomaly results, "
        f"{derived['confidence_scores']} confidence scores, {derived['clinical_insights']} clinical results"
    )
    if month:
        msg += f" for {month}"
    return {"hospital_id": hospital_id, "hospital_name": hospital.name, "message": msg}


@router.post("/remove-data", dependencies=[Depends(require_permission("data.manage"))])
def remove_data(body: dict = Body(...), db: Session = Depends(get_db)):
    """Remove all indicator data for one month — one hospital or all active hospitals.

    Deletes the (hospital, month) data slice plus every derived analysis row,
    then re-runs analysis for the surviving months so scores reflect the
    reduced history. The deleted month itself is never re-analysed, so it
    disappears cleanly instead of leaving a score-0 ghost row.
    """
    month = (body or {}).get("month")
    hospital_id = (body or {}).get("hospital_id")
    if not month or month == "__all__" or not re.match(r"^\d{4}-\d{2}$", str(month)):
        raise HTTPException(status_code=400, detail="A specific month (YYYY-MM) is required")

    if hospital_id:
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        targets = [hospital]
    else:
        targets = db.query(Hospital).filter(Hospital.is_active.is_(True)).all()

    totals = {
        "indicator_values": 0, "quality_scores": 0, "validation_results": 0,
        "anomaly_results": 0, "confidence_scores": 0, "clinical_insights": 0,
    }
    # Copy the raw rows aside before deleting them so the client can undo the
    # removal for a short window instead of having to re-upload the file.
    snapshot_rows: List[dict] = []
    for h in targets:
        rows = db.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == h.id,
            IndicatorValue.month == month,
        ).all()
        totals["indicator_values"] += len(rows)
        for r in rows:
            snapshot_rows.append({
                "hospital_id": r.hospital_id,
                "indicator_id": r.indicator_id,
                "month": r.month,
                "value": r.value,
                "source_file": r.source_file,
                "created_at": r.created_at,
            })
        db.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == h.id,
            IndicatorValue.month == month,
        ).delete(synchronize_session=False)
        for key, value in purge_derived_results(db, h.id, month).items():
            totals[key] += value
    db.commit()

    undo = undo_store.create(snapshot_rows, {
        "month": month,
        "scope": "hospital" if hospital_id else "all_hospitals",
        "hospital_ids": [h.id for h in targets],
    }) if snapshot_rows else None

    _invalidate_analysis_caches(db)

    # Does the deleted month still exist anywhere? Drives the frontend month selector.
    month_still_available = any(
        db.query(tbl.id).filter(tbl.month == month).first()
        for tbl in (QualityScore, ValidationResult, ConfidenceScore, AnomalyResult)
    )

    scope = "hospital" if hospital_id else "all_hospitals"
    if totals["indicator_values"] == 0:
        return {
            "month": month, "scope": scope, "hospitals": [h.name for h in targets],
            "removed": totals, "month_still_available": month_still_available,
            "recompute_task_id": None, "undo": None,
            "message": f"No data found for {month} in the selected scope — nothing removed.",
        }

    recompute = bool((body or {}).get("recompute", True))
    pairs = _plan_recompute_pairs(db, targets, month, single_hospital=bool(hospital_id)) if recompute else []
    task_id = create_task(f"remove-data:{month}") if pairs else None
    if task_id:
        threading.Thread(
            target=run_task, args=(task_id, _run_remove_recompute, pairs, task_id), daemon=True
        ).start()

    message = (
        f"Removed {totals['indicator_values']} values for {month} across "
        f"{len(targets)} hospital(s). Re-analysis started."
    )
    if undo:
        message += f" Undo is available for {undo['expires_in'] // 60} minutes."

    return {
        "month": month, "scope": scope, "hospitals": [h.name for h in targets],
        "removed": totals, "month_still_available": month_still_available,
        "recompute_task_id": task_id, "undo": undo,
        "message": message,
    }


@router.post("/remove-data/undo", dependencies=[Depends(require_permission("data.manage"))])
def undo_remove_data(body: dict = Body(...), db: Session = Depends(get_db)):
    """Restore a Remove Data deletion from its snapshot.

    Puts the raw indicator values back (skipping any that have reappeared in the
    meantime, e.g. via a re-upload), then re-runs analysis for the affected
    months so scores, validations, anomalies and confidence are rebuilt from the
    restored history.
    """
    token = (body or {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="An undo token is required")
    snapshot = undo_store.get(token)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail="Undo is no longer available for this removal (the snapshot expired).",
        )

    month = snapshot["meta"].get("month")
    scope = snapshot["meta"].get("scope", "hospital")
    rows = snapshot["rows"]

    requested = len(rows)
    # A hospital or indicator deleted while the snapshot was alive can no longer
    # take its values back — drop those rows instead of failing on the FK.
    live_hospital_ids = {
        r[0] for r in db.query(Hospital.id).filter(
            Hospital.id.in_({r["hospital_id"] for r in rows})
        ).all()
    }
    live_indicator_ids = {
        r[0] for r in db.query(Indicator.id).filter(
            Indicator.id.in_({r["indicator_id"] for r in rows})
        ).all()
    }
    rows = [
        r for r in rows
        if r["hospital_id"] in live_hospital_ids and r["indicator_id"] in live_indicator_ids
    ]

    existing = {
        (h, i) for h, i in db.query(
            IndicatorValue.hospital_id, IndicatorValue.indicator_id
        ).filter(
            IndicatorValue.hospital_id.in_({r["hospital_id"] for r in rows} or {0}),
            IndicatorValue.month == month,
        ).all()
    }
    to_insert = [r for r in rows if (r["hospital_id"], r["indicator_id"]) not in existing]
    skipped = requested - len(to_insert)
    if to_insert:
        db.bulk_insert_mappings(IndicatorValue, to_insert)
    db.commit()

    undo_store.drop(token)
    _invalidate_analysis_caches(db)

    targets = db.query(Hospital).filter(Hospital.id.in_(live_hospital_ids)).all()
    pairs = _plan_recompute_pairs(
        db, targets, month, single_hospital=(scope == "hospital"), include_month=True
    ) if to_insert else []
    task_id = create_task(f"undo-remove-data:{month}") if pairs else None
    if task_id:
        threading.Thread(
            target=run_task, args=(task_id, _run_remove_recompute, pairs, task_id), daemon=True
        ).start()

    return {
        "month": month, "scope": scope, "hospitals": [h.name for h in targets],
        "restored": {"indicator_values": len(to_insert), "skipped_existing": skipped},
        "recompute_task_id": task_id,
        "message": (
            f"Restored {len(to_insert)} values for {month} across {len(targets)} hospital(s). "
            "Re-analysis started."
        ),
    }


def _invalidate_analysis_caches(db: Session) -> None:
    """Drop memory + file caches (incl. analysis:months) and smart/report caches."""
    cache.invalidate()
    try:
        from app.engine.comparative.report_cache import invalidate_report_cache
        invalidate_report_cache(db)
    except Exception as e:
        logger.warning("Report cache invalidation failed: %s", e)
    for prefix in (
        "smart_overview_", "smart_anomalies_", "smart_clusters_",
        "smart_correlations_", "smart_residuals_",
    ):
        cache.invalidate(prefix)


def _plan_recompute_pairs(
    db: Session,
    targets: list,
    month: str,
    single_hospital: bool,
    include_month: bool = False,
) -> list:
    """(hospital_id, month) pairs whose analysis depends on ``month`` for ``targets``.

    Historical values changed for every target hospital, so all of its remaining
    months are recomputed. For a single-hospital delete the peer set for that
    month changed too, so ``month`` is recomputed for the other active
    hospitals. ``include_month=True`` adds ``month`` back for the targets — used
    by Undo, where the month's data has just been restored and must be
    re-analysed rather than skipped.
    """
    pairs = []
    target_ids = {h.id for h in targets}
    for h in targets:
        months = [
            r[0] for r in db.query(IndicatorValue.month).filter(
                IndicatorValue.hospital_id == h.id,
                IndicatorValue.month != month,
            ).distinct().all()
        ]
        if include_month:
            has_month = db.query(IndicatorValue.id).filter(
                IndicatorValue.hospital_id == h.id,
                IndicatorValue.month == month,
            ).first()
            if has_month:
                months.append(month)
        pairs += [(h.id, m) for m in sorted(months)]
    if single_hospital:
        others = db.query(Hospital).filter(
            Hospital.is_active.is_(True),
            Hospital.id.notin_(target_ids),
        ).all()
        for h in others:
            has_month = db.query(IndicatorValue.id).filter(
                IndicatorValue.hospital_id == h.id,
                IndicatorValue.month == month,
            ).first()
            if has_month:
                pairs.append((h.id, month))
    return pairs


def _run_remove_recompute(pairs: list, task_id: str) -> None:
    """Background worker: force-refresh every affected (hospital, month)."""
    from app.database import SessionLocal
    from app.tasks import set_progress

    db = SessionLocal()
    try:
        total = max(len(pairs), 1)
        for i, (hospital_id, month) in enumerate(pairs):
            try:
                recompute_hospital_months(db, hospital_id, [month], force=True)
            except Exception:
                db.rollback()
                logger.exception("Recompute failed for hospital %s / %s", hospital_id, month)
            set_progress(task_id, int((i + 1) / total * 100))
    finally:
        db.close()


@router.delete("/clear-all-data")
def clear_all_data(db: Session = Depends(get_db)):
    """Nuclear option: clear ALL indicator data, quality scores, validation results.
    Hospitals remain but become inactive."""
    from app.models import IndicatorValue, QualityScore, ValidationResult, ClinicalInsight
    from sqlalchemy import func as sa_func

    iv_count = db.query(IndicatorValue).delete(synchronize_session=False)
    qs_count = db.query(QualityScore).delete(synchronize_session=False)
    vr_count = db.query(ValidationResult).delete(synchronize_session=False)
    cr_count = db.query(ClinicalInsight).delete(synchronize_session=False)

    # Mark all hospitals as inactive since they have no data
    db.query(Hospital).update({Hospital.is_active: False}, synchronize_session=False)

    db.commit()
    cache.invalidate()
    return {"message": f"Cleared ALL data: {iv_count} indicator values, {qs_count} quality scores, {vr_count} validation results, {cr_count} clinical results. All hospitals marked inactive."}


@router.get("/data-status")
def hospital_data_status(db: Session = Depends(get_db)):
    """Show data status for every hospital — helps diagnose missing results.

    Returns each hospital with indicator_values_count, quality_score_count,
    months with data, and whether it's active.
    """
    from sqlalchemy import func
    from app.models import IndicatorValue, QualityScore

    rows = (
        db.query(
            Hospital.id,
            Hospital.name,
            Hospital.is_active,
            func.coalesce(func.count(func.distinct(IndicatorValue.id)), 0).label("iv_count"),
            func.coalesce(func.count(func.distinct(QualityScore.id)), 0).label("qs_count"),
        )
        .outerjoin(IndicatorValue, IndicatorValue.hospital_id == Hospital.id)
        .outerjoin(QualityScore, QualityScore.hospital_id == Hospital.id)
        .group_by(Hospital.id, Hospital.name, Hospital.is_active)
        .order_by(Hospital.name)
        .all()
    )

    result = []
    for r in rows:
        # Get months with data
        months = (
            db.query(IndicatorValue.month)
            .filter(IndicatorValue.hospital_id == r.id)
            .distinct()
            .order_by(IndicatorValue.month)
            .all()
        )
        result.append({
            "id": r.id,
            "name": r.name,
            "is_active": r.is_active,
            "indicator_values": r.iv_count,
            "quality_scores": r.qs_count,
            "months": [m[0] for m in months],
        })
    return result


@router.post("/bulk-metadata")
def bulk_update_metadata(
    updates: list = Body(...),
    db: Session = Depends(get_db),
):
    """Bulk-update hospital metadata by name (fuzzy match).

    Each item: {name, governorate, hospital_type, facility_ownership,
                facility_type, organisation_unit_id, address}
    """
    from sqlalchemy import func as sqlfunc

    gov_map = {g.name.lower(): g.id for g in db.query(Governorate).all()}
    type_map = {t.name.lower(): t.id for t in db.query(HospitalType).all()}
    own_map = {o.name.lower(): o.id for o in db.query(FacilityOwnership).all()}
    ft_map = {f.name.lower(): f.id for f in db.query(FacilityType).all()}

    # Build fuzzy hospital lookup: normalized name → hospital
    hosp_lookup = {}
    for h in db.query(Hospital).all():
        normalized = h.name.strip().lower()
        hosp_lookup[normalized] = h
        # Also try without spaces
        hosp_lookup[normalized.replace(" ", "")] = h

    updated = 0
    for entry in updates:
        name = entry.get("name", "").strip()
        if not name:
            continue

        # Try exact match, then normalized match
        hosp = hosp_lookup.get(name.lower()) or hosp_lookup.get(name.lower().replace(" ", ""))
        if not hosp:
            # Try partial match
            for key, h in hosp_lookup.items():
                if name.lower() in key or key in name.lower():
                    hosp = h
                    break
        if not hosp:
            continue

        changed = False
        def _lookup_type(name):
            """Fuzzy match hospital type: try exact, then strip 'مستشفى' prefix."""
            low = name.lower().strip()
            if low in type_map:
                return type_map[low]
            # Strip prefix like 'مستشفى' from 'مستشفى عام' -> 'عام'
            stripped = low.replace('مستشفى ', '').replace('مستشفية ', '').strip()
            if stripped in type_map:
                return type_map[stripped]
            return None

        gov_name = entry.get("governorate", "")
        if gov_name and gov_name.lower().strip() in gov_map:
            new_gov = gov_map[gov_name.lower().strip()]
            if hosp.governorate_id != new_gov:
                hosp.governorate_id = new_gov
                changed = True

        ht_name = entry.get("hospital_type", "")
        if ht_name:
            ht_id = _lookup_type(ht_name)
            if ht_id and hosp.hospital_type_id != ht_id:
                hosp.hospital_type_id = ht_id
                changed = True

        own_name = entry.get("facility_ownership", "")
        if own_name and own_name.lower().strip() in own_map:
            new_own = own_map[own_name.lower().strip()]
            if hosp.facility_ownership_id != new_own:
                hosp.facility_ownership_id = new_own
                changed = True

        ft_name = entry.get("facility_type", "")
        if ft_name and ft_name.lower().strip() in ft_map:
            new_ft = ft_map[ft_name.lower().strip()]
            if hosp.facility_type_id != new_ft:
                hosp.facility_type_id = new_ft
                changed = True

        org_id = entry.get("organisation_unit_id", "")
        if org_id and str(org_id).strip() and hosp.organisation_unit_id != str(org_id).strip():
            hosp.organisation_unit_id = str(org_id).strip()
            changed = True

        address = entry.get("address", "")
        if address and address.strip() and hosp.address != address.strip():
            hosp.address = address.strip()
            changed = True

        if changed:
            updated += 1

    db.commit()
    cache.invalidate()
    return {"updated": updated, "total": len(updates)}


@router.get("/indicators", response_model=List[IndicatorOut])
def list_all_indicators(db: Session = Depends(get_db)):
    cache_key = "hospitals:indicators"
    cached = cache.get(cache_key)
    if cached:
        return cached
    result = db.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    cache.set(cache_key, result)
    return result


@router.get("/{hospital_id}", response_model=HospitalOut)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return {
        "id": h.id,
        "name": h.name,
        "region": h.region,
        "governorate_id": h.governorate_id,
        "hospital_type_id": h.hospital_type_id,
        "organisation_unit_id": h.organisation_unit_id,
        "facility_ownership_id": h.facility_ownership_id,
        "facility_type_id": h.facility_type_id,
        "address": h.address,
        "is_active": h.is_active,
        "created_at": h.created_at,
        "governorate_name": h.governorate.name if h.governorate else None,
        "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
        "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
        "facility_type_name": h.facility_type.name if h.facility_type else None,
    }


@router.put("/{hospital_id}", response_model=HospitalOut)
def update_hospital(hospital_id: int, data: HospitalCreate, db: Session = Depends(get_db)):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    dup = db.query(Hospital).filter(Hospital.name == data.name, Hospital.id != hospital_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="Hospital name already taken")
    hosp.name = data.name
    hosp.region = data.region
    hosp.governorate_id = data.governorate_id
    hosp.hospital_type_id = data.hospital_type_id
    hosp.organisation_unit_id = data.organisation_unit_id
    hosp.facility_ownership_id = data.facility_ownership_id
    hosp.facility_type_id = data.facility_type_id
    hosp.address = data.address
    db.commit()
    db.refresh(hosp)
    cache.invalidate()
    return hosp


@router.delete("/{hospital_id}")
def delete_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    db.delete(hosp)
    db.commit()
    cache.invalidate()
    return {"ok": True}


@router.post("/{hospital_id}/re-analyze")
def reanalyze_hospital(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    force: bool = Query(False, description="Force re-analysis even if cached results exist"),
    db: Session = Depends(get_db),
):
    """Re-run full analysis for a specific hospital/month (after config changes)."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    try:
        report = run_full_analysis(db, hospital_id, month, force=force)
        # Clear cache so fresh data is served
        cache.invalidate()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
