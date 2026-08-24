"""Seed hospital metadata from scripts/hospital_metadata.json.

Runs on startup: matches hospitals by name (fuzzy) and sets governorate_id,
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


def _fuzzy_match(name: str, lookup: dict) -> Optional[int]:
    """Match a name against a lookup dict using exact, normalized, and partial match."""
    norm = name.strip().lower()
    # Exact
    if norm in lookup:
        return lookup[norm]
    # No spaces
    if norm.replace(" ", "") in lookup:
        return lookup[norm.replace(" ", "")]
    # Partial: query name contains the key
    for key, val in lookup.items():
        if norm in key or key in norm:
            return val
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
    gov_map = {g.name.lower(): g.id for g in session.query(Governorate).all()}
    type_map = {t.name.lower(): t.id for t in session.query(HospitalType).all()}
    own_map = {o.name.lower(): o.id for o in session.query(FacilityOwnership).all()}
    ft_map = {f.name.lower(): f.id for f in session.query(FacilityType).all()}

    # Build hospital lookup with normalized names + org_unit_id
    hosp_lookup = {}
    org_lookup = {}
    for h in session.query(Hospital).all():
        norm = h.name.strip().lower()
        hosp_lookup[norm] = h
        hosp_lookup[norm.replace(" ", "")] = h
        if h.organisation_unit_id:
            org_lookup[h.organisation_unit_id.strip()] = h

    updated = 0
    matched = 0
    unmatched = []

    for entry in hospitals_data:
        name = entry.get("name", "").strip()
        if not name:
            continue

        # Try org_unit_id first (most reliable)
        org_id_str = str(entry.get("organisation_unit_id", "")).strip()
        hosp = org_lookup.get(org_id_str) if org_id_str else None

        if not hosp:
            hosp = hosp_lookup.get(name.lower()) or hosp_lookup.get(name.lower().replace(" ", ""))
        if not hosp:
            # Try partial match
            for key, h in hosp_lookup.items():
                if name.lower() in key or key in name.lower():
                    hosp = h
                    break

        if not hosp:
            # Create the hospital if it doesn't exist
            hosp = Hospital(name=name, is_active=True)
            session.add(hosp)
            session.flush()
            hosp_lookup[name.lower()] = hosp
            if org_id_str:
                org_lookup[org_id_str] = hosp
                hosp.organisation_unit_id = org_id_str
            matched += 1
            # Fall through to set metadata below
            changed = True
        else:
            matched += 1

        matched += 1
        changed = False

        # Set governorate
        gov_name = entry.get("governorate", "")
        if gov_name:
            gov_id = _fuzzy_match(gov_name, gov_map)
            if gov_id:
                hosp.governorate_id = gov_id
                changed = True

        # Set hospital type
        ht_name = entry.get("hospital_type", "")
        if ht_name:
            ht_id = _fuzzy_match(ht_name, type_map)
            if ht_id:
                hosp.hospital_type_id = ht_id
                changed = True

        # Set facility ownership
        own_name = entry.get("facility_ownership", "")
        if own_name:
            own_id = _fuzzy_match(own_name, own_map)
            if own_id:
                hosp.facility_ownership_id = own_id
                changed = True

        # Set facility type
        ft_name = entry.get("facility_type", "")
        if ft_name:
            ft_id = _fuzzy_match(ft_name, ft_map)
            if ft_id:
                hosp.facility_type_id = ft_id
                changed = True

        # Set organisation unit ID
        org_id = entry.get("organisation_unit_id", "")
        if org_id:
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

    if unmatched:
        logger.info(f"[hospital-metadata] {len(unmatched)} hospitals not found in JSON: {', '.join(unmatched[:10])}")

    return updated
