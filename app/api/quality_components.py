"""Quality component screens — one page per Quality Score component.

The Quality Reports screen shows the composite score one hospital-month at a
time. These endpoints feed the per-component screens (Completeness, Rule
Compliance, Consistency and Confidence) that list EVERY hospital-month in the
user's scope, so a component can be reviewed across the network instead of one
report at a time.

Values are read from the same stored rows the Quality Reports screen and the
dashboard read (``QualityScore`` components and ``ConfidenceScore``). Nothing
is recomputed here except completeness, which the dashboard also recalculates
at read time — so a stored value that predates an indicator setting change
cannot make this screen disagree with the KPI cards.
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config_utils import get_config_dict
from app.core.deps import get_current_user, get_user_hospital_ids, require_permission
from app.database import get_db
from app.eligibility import exclude_disabled
from app.engine.pipeline import is_fallback_quality_row
from app.engine.quality.scoring import quality_weights
from app.models import ConfidenceScore, Hospital, QualityScore

router = APIRouter(
    prefix="/quality-components",
    tags=["quality-components"],
    dependencies=[Depends(require_permission("quality.read"))],
)

#: One entry per screen. ``field`` is the QualityScore column the page reads
#: (None when the page's own table is the source); ``target`` matches the
#: dashboard's component targets so both screens grade a value identically.
COMPONENTS: Dict[str, dict] = {
    "completeness": {
        "label": "Completeness",
        "field": "completeness",
        "weight_key": "completeness",
        "target": 90.0,
        "description": "Share of the required indicator values a hospital reported for the month.",
    },
    "compliance": {
        "label": "Rule Compliance",
        "field": "rule_compliance",
        "weight_key": "rule_compliance",
        "target": 85.0,
        "description": "Share of the validation rules that passed for the month.",
    },
    "consistency": {
        "label": "Consistency",
        "field": "consistency",
        "weight_key": "consistency",
        "target": 85.0,
        "description": "Agreement between related indicators reported in the same month.",
    },
    "confidence": {
        "label": "Confidence",
        "field": None,
        "weight_key": None,
        "target": None,
        "description": (
            "How far the month's reported values can be trusted. Confidence is a "
            "separate reliability score — it is not a weighted part of the Quality Score."
        ),
    },
}

_CONFIDENCE_LEVELS = ("high", "medium", "low", "critical")


def _meta(component: str) -> dict:
    meta = COMPONENTS.get(component)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown quality component: {component}")
    return meta


def _round(value) -> Optional[float]:
    return round(float(value), 1) if value is not None else None


def _band(value, target) -> Optional[str]:
    """The dashboard's component targets, expressed as three states."""
    if value is None or target is None:
        return None
    if value >= target:
        return "on_target"
    if value >= target - 10:
        return "watch"
    return "below"


def _confidence_level(conf: Optional[ConfidenceScore]) -> Optional[str]:
    if conf is None or not conf.level:
        return None
    level = conf.level.strip().lower()
    return level if level in _CONFIDENCE_LEVELS else None


def _row(hospital_id, hospital, month, value, meta, score, conf) -> dict:
    return {
        "hospital_id": hospital_id,
        "hospital": hospital,
        "month": month,
        "value": _round(value),
        "level": (_confidence_level(conf) if meta["target"] is None
                  else _band(value, meta["target"])),
        "target": meta["target"],
        "gap": (round(float(value) - meta["target"], 1)
                if value is not None and meta["target"] is not None else None),
        "overall_score": _round(score.score) if score is not None else None,
        "rule_compliance": _round(score.rule_compliance) if score is not None else None,
        "completeness": _round(score.completeness) if score is not None else None,
        "consistency": _round(score.consistency) if score is not None else None,
        "outlier_penalty": _round(score.outlier_penalty) if score is not None else None,
        "confidence": _round(conf.overall_confidence) if conf is not None else None,
        "confidence_level": _confidence_level(conf),
        "indicator_count": conf.indicator_count if conf is not None else None,
        "high_count": conf.high_count if conf is not None else None,
        "medium_count": conf.medium_count if conf is not None else None,
        "low_count": conf.low_count if conf is not None else None,
        "critical_count": conf.critical_count if conf is not None else None,
    }


def _weight(db: Session, weight_key: Optional[str]) -> Optional[float]:
    if weight_key is None:
        return None
    try:
        weights = quality_weights(get_config_dict(db, "quality"))
        return round(float(weights[weight_key]), 4)
    except Exception:
        return None


def _quality_scores(db: Session, hospitals) -> list:
    q = db.query(QualityScore).filter(QualityScore.hospital_id.in_(list(hospitals)))
    q = exclude_disabled(db, q, QualityScore)
    return q.order_by(QualityScore.hospital_id, QualityScore.month).all()


def _confidence_scores(db: Session, hospitals) -> list:
    q = (db.query(ConfidenceScore)
         .filter(ConfidenceScore.hospital_id.in_(list(hospitals)))
         .filter(ConfidenceScore.overall_confidence.isnot(None)))
    q = exclude_disabled(db, q, ConfidenceScore)
    return q.order_by(ConfidenceScore.hospital_id, ConfidenceScore.month).all()


def _quality_rows(db, hospitals, component) -> tuple:
    meta = COMPONENTS[component]
    stored = _quality_scores(db, hospitals)
    rows = [s for s in stored if not is_fallback_quality_row(s)]
    excluded_failed = len(stored) - len(rows)
    completeness_values = None
    if component == "completeness":
        # Same read-time recalculation the dashboard uses, so the two screens
        # report one completeness number (stored rows go stale when the
        # completeness denominator changes).
        from app.api.dashboard import _recalc_completeness
        completeness_values = _recalc_completeness(db, rows)
    conf_map = {(c.hospital_id, c.month): c for c in _confidence_scores(db, hospitals)}
    out = []
    for i, s in enumerate(rows):
        value = (completeness_values[i] if completeness_values is not None
                 else getattr(s, meta["field"], None))
        if value is None:
            continue
        out.append(_row(s.hospital_id, hospitals.get(s.hospital_id, "Unknown"),
                        s.month, value, meta, s, conf_map.get((s.hospital_id, s.month))))
    return out, excluded_failed


def _confidence_rows(db, hospitals) -> list:
    meta = COMPONENTS["confidence"]
    quality = {(s.hospital_id, s.month): s for s in _quality_scores(db, hospitals)
               if not is_fallback_quality_row(s)}
    out = []
    for c in _confidence_scores(db, hospitals):
        out.append(_row(c.hospital_id, hospitals.get(c.hospital_id, "Unknown"),
                        c.month, c.overall_confidence, meta,
                        quality.get((c.hospital_id, c.month)), c))
    return out


@router.get("/{component}")
def quality_component(
    component: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Every hospital-month's result for one Quality Score component."""
    meta = _meta(component)
    user_hosp_ids = get_user_hospital_ids(user, db)
    hosp_q = db.query(Hospital).filter(Hospital.is_active.is_(True))
    if user_hosp_ids is not None:
        hosp_q = hosp_q.filter(Hospital.id.in_(user_hosp_ids))
    hospitals = {h.id: h.name for h in hosp_q.all()}

    rows: list = []
    excluded_failed = 0
    if hospitals:
        if component == "confidence":
            rows = _confidence_rows(db, hospitals)
        else:
            rows, excluded_failed = _quality_rows(db, hospitals, component)

    return {
        "component": component,
        "label": meta["label"],
        "description": meta["description"],
        "unit": "%",
        "target": meta["target"],
        "weight": _weight(db, meta["weight_key"]),
        "months": sorted({r["month"] for r in rows}),
        "rows": rows,
        "excluded_failed": excluded_failed,
    }
