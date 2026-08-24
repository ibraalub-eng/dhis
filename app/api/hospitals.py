from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.cache import cache
from app.models import Hospital, Indicator
from app.schemas import HospitalOut, IndicatorOut, HospitalCreate
from app.engine.pipeline import run_full_analysis
from app.core.deps import require_permission

router = APIRouter(prefix="/hospitals", tags=["hospitals"], dependencies=[Depends(require_permission("hospitals.read"))])


@router.get("/", response_model=List[HospitalOut])
def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    include_inactive: bool = Query(False, description="Include inactive hospitals"),
    db: Session = Depends(get_db),
    user=Depends(require_permission("hospitals.read")),
):
    cache_key = cache.make_key("hospitals:list", skip=skip, limit=limit, include_inactive=include_inactive)
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
    if user and not user.is_superuser:
        from app.models import user_hospitals
        user_hospital_ids = db.query(user_hospitals.c.hospital_id).filter(
            user_hospitals.c.user_id == user.id
        ).subquery()
        # If user has specific hospitals assigned, filter to only those
        assigned_count = db.query(user_hospitals).filter(user_hospitals.c.user_id == user.id).count()
        if assigned_count > 0:
            q = q.filter(Hospital.id.in_(db.query(user_hospital_ids)))

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
    Also clears quality scores, validation results, and clinical results."""
    from app.models import IndicatorValue, QualityScore, ValidationResult, ClinicalInsight
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    q_iv = db.query(IndicatorValue).filter(IndicatorValue.hospital_id == hospital_id)
    q_qs = db.query(QualityScore).filter(QualityScore.hospital_id == hospital_id)
    q_vr = db.query(ValidationResult).filter(ValidationResult.hospital_id == hospital_id)
    q_cr = db.query(ClinicalInsight).filter(ClinicalInsight.hospital_id == hospital_id)

    if month:
        q_iv = q_iv.filter(IndicatorValue.month == month)
        q_qs = q_qs.filter(QualityScore.month == month)
        q_vr = q_vr.filter(ValidationResult.month == month)
        q_cr = q_cr.filter(ClinicalInsight.month == month)

    iv_count = q_iv.delete(synchronize_session=False)
    qs_count = q_qs.delete(synchronize_session=False)
    vr_count = q_vr.delete(synchronize_session=False)
    cr_count = q_cr.delete(synchronize_session=False)

    db.commit()
    cache.invalidate()
    msg = f"Cleared {iv_count} indicator values, {qs_count} quality scores, {vr_count} validation results, {cr_count} clinical results"
    if month:
        msg += f" for {month}"
    return {"hospital_id": hospital_id, "hospital_name": hospital.name, "message": msg}


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
        gov_name = entry.get("governorate", "")
        if gov_name and not hosp.governorate_id and gov_name.lower() in gov_map:
            hosp.governorate_id = gov_map[gov_name.lower()]
            changed = True

        ht_name = entry.get("hospital_type", "")
        if ht_name and not hosp.hospital_type_id and ht_name.lower() in type_map:
            hosp.hospital_type_id = type_map[ht_name.lower()]
            changed = True

        own_name = entry.get("facility_ownership", "")
        if own_name and not hosp.facility_ownership_id and own_name.lower() in own_map:
            hosp.facility_ownership_id = own_map[own_name.lower()]
            changed = True

        ft_name = entry.get("facility_type", "")
        if ft_name and not hosp.facility_type_id and ft_name.lower() in ft_map:
            hosp.facility_type_id = ft_map[ft_name.lower()]
            changed = True

        org_id = entry.get("organisation_unit_id", "")
        if org_id and not hosp.organisation_unit_id:
            hosp.organisation_unit_id = org_id
            changed = True

        address = entry.get("address", "")
        if address and not hosp.address:
            hosp.address = address
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
