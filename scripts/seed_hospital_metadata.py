"""Seed hospital metadata from scripts/hospital_metadata.json.

Runs on startup: matches hospitals by name and sets governorate_id,
hospital_type_id, facility_ownership_id, facility_type_id, and
organisation_unit_id for any hospitals that are missing this data.

Safe to run repeatedly — only updates NULL fields.
"""
import json
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Hospital,
    Governorate,
    HospitalType,
    FacilityOwnership,
    FacilityType,
)

logger = logging.getLogger(__name__)

METADATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "hospital_metadata.json",
)


def _load_metadata() -> Optional[dict]:
    if not os.path.exists(METADATA_PATH):
        return None
    try:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load hospital metadata: {e}")
        return None


def seed_hospital_metadata(session: Session) -> int:
    """Apply hospital metadata from JSON seed file.

    Returns the number of hospitals updated.
    """
    metadata = _load_metadata()
    if not metadata:
        return 0

    hospitals_data = metadata.get("hospitals", [])
    if not hospitals_data:
        return 0

    # Build name→id lookup for reference tables
    gov_map = {g.name: g.id for g in session.query(Governorate).all()}
    type_map = {t.name: t.id for t in session.query(HospitalType).all()}
    own_map = {o.name: o.id for o in session.query(FacilityOwnership).all()}
    ft_map = {f.name: f.id for f in session.query(FacilityType).all()}

    # Build name→hospital lookup (case-insensitive)
    hosp_map = {}
    for h in session.query(Hospital).all():
        hosp_map[h.name.strip().lower()] = h

    updated = 0
    for entry in hospitals_data:
        name = entry.get("name", "").strip()
        if not name:
            continue
        hosp = hosp_map.get(name.lower())
        if not hosp:
            continue

        changed = False

        # Set governorate
        gov_name = entry.get("governorate", "")
        if gov_name and not hosp.governorate_id and gov_name in gov_map:
            hosp.governorate_id = gov_map[gov_name]
            changed = True

        # Set hospital type
        ht_name = entry.get("hospital_type", "")
        if ht_name and not hosp.hospital_type_id and ht_name in type_map:
            hosp.hospital_type_id = type_map[ht_name]
            changed = True

        # Set facility ownership
        own_name = entry.get("facility_ownership", "")
        if own_name and not hosp.facility_ownership_id and own_name in own_map:
            hosp.facility_ownership_id = own_map[own_name]
            changed = True

        # Set facility type
        ft_name = entry.get("facility_type", "")
        if ft_name and not hosp.facility_type_id and ft_name in ft_map:
            hosp.facility_type_id = ft_map[ft_name]
            changed = True

        # Set organisation unit ID
        org_id = entry.get("organisation_unit_id", "")
        if org_id and not hosp.organisation_unit_id:
            hosp.organisation_unit_id = org_id
            changed = True

        # Set address
        address = entry.get("address", "")
        if address and not hosp.address:
            hosp.address = address
            changed = True

        if changed:
            updated += 1

    if updated:
        session.commit()
        logger.info(f"[hospital-metadata] Updated {updated} hospitals with metadata")

    return updated
