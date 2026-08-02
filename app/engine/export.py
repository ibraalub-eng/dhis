"""Build the full data export package for external analysis tools."""
import math
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models import (
    Hospital, Governorate, Indicator, HospitalIndicatorConfig, IndicatorValue,
)


class NoDataError(ValueError):
    """Raised when there is nothing to export."""


def _sanitize(obj: Any) -> Any:
    """Recursively convert numpy/NaN/Inf values to native JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "tolist") and not isinstance(obj, (int, float, str, bool)):
        try:
            return _sanitize(obj.tolist())
        except (ValueError, AttributeError, TypeError):
            pass
    if hasattr(obj, "item") and not isinstance(obj, (int, float, str, bool)):
        try:
            return obj.item()
        except (ValueError, AttributeError, TypeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    return obj


def _get_available_months(session: Session) -> List[str]:
    """Distinct months that have indicator values, sorted ascending."""
    months = [m for (m,) in session.query(IndicatorValue.month).distinct().all()]
    return sorted(months)


def _get_master_data(session: Session) -> Dict[str, Any]:
    """Governorates, hospitals, indicators, and hospital indicator configs."""
    governorates = [
        {"id": g.id, "name": g.name}
        for g in session.query(Governorate).order_by(Governorate.name).all()
    ]

    hospitals = []
    for h in session.query(Hospital).order_by(Hospital.name).all():
        hospitals.append({
            "id": h.id,
            "name": h.name,
            "region": h.region,
            "address": h.address,
            "governorate_name": h.governorate.name if h.governorate else None,
            "hospital_type_name": h.hospital_type.name if h.hospital_type else None,
            "facility_ownership_name": h.facility_ownership.name if h.facility_ownership else None,
            "facility_type_name": h.facility_type.name if h.facility_type else None,
            "is_active": h.is_active,
        })

    indicators = [
        {
            "code": i.code,
            "name": i.name,
            "level": i.level,
            "group_name": i.group_name,
            "parent_code": i.parent.code if i.parent else None,
        }
        for i in session.query(Indicator).order_by(Indicator.sort_order, Indicator.id).all()
    ]

    configs = [
        {
            "hospital_id": c.hospital_id,
            "indicator_code": c.indicator.code if c.indicator else None,
            "is_enabled": c.is_enabled,
            "weight_override": c.weight_override,
        }
        for c in session.query(HospitalIndicatorConfig).all()
    ]

    return {
        "governorates": governorates,
        "hospitals": hospitals,
        "indicators": indicators,
        "hospital_indicator_configs": configs,
    }


def _get_indicator_values(session: Session, months: List[str]) -> Dict[str, list]:
    """Indicator values grouped by month."""
    by_month: Dict[str, list] = {}
    if not months:
        return by_month

    hospitals = {h.id: h for h in session.query(Hospital).all()}
    indicators = {i.id: i for i in session.query(Indicator).all()}

    rows = session.query(IndicatorValue).filter(IndicatorValue.month.in_(months)).all()
    for iv in rows:
        hosp = hospitals.get(iv.hospital_id)
        ind = indicators.get(iv.indicator_id)
        by_month.setdefault(iv.month, []).append({
            "hospital_id": iv.hospital_id,
            "hospital_name": hosp.name if hosp else "",
            "indicator_code": ind.code if ind else "",
            "indicator_name": ind.name if ind else "",
            "value": iv.value,
            "source_file": iv.source_file,
        })
    return by_month
