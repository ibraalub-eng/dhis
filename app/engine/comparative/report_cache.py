"""Persistent storage for AI-generated comprehensive reports."""
import json
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.models import AnalysisCache

logger = logging.getLogger(__name__)

REPORT_CACHE_PREFIX = "comparative_report:"


def _cache_key(month: str, lang: str) -> str:
    return f"{REPORT_CACHE_PREFIX}{month}:{lang}"


def _sanitize(obj: Any) -> Any:
    """Convert numpy types and dataclasses to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (int, float, str, bool)):
        try:
            return obj.item()
        except (ValueError, AttributeError):
            return str(obj)
    if hasattr(obj, "tolist") and not isinstance(obj, (list, tuple)):
        return _sanitize(obj.tolist())
    if hasattr(obj, "__dict__") and not isinstance(obj, (int, float, str, bool)):
        return _sanitize(vars(obj))
    return obj


def get_stored_report(session: Session, month: str, lang: str) -> Optional[Dict[str, Any]]:
    """Return the stored report for a month/lang, or None if absent."""
    row = session.query(AnalysisCache).filter(
        AnalysisCache.cache_key == _cache_key(month, lang)
    ).first()
    if not row:
        return None
    try:
        return json.loads(row.result_json)
    except Exception as e:
        logger.warning(f"Error reading report cache: {e}")
        return None


def store_report(session: Session, month: str, lang: str, result: Dict[str, Any]) -> None:
    """Persist a report for a month/lang. No expiry (deleted on data change)."""
    key = _cache_key(month, lang)
    payload = json.dumps(_sanitize(result), default=str)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if row:
        row.result_json = payload
        row.expires_at = None
    else:
        row = AnalysisCache(cache_key=key, result_json=payload, expires_at=None)
        session.add(row)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to store report: {e}")


def invalidate_report_cache(session: Session, month: Optional[str] = None) -> int:
    """Delete cached reports for a month (or all months if month is None)."""
    if month is None:
        rows = session.query(AnalysisCache).filter(
            AnalysisCache.cache_key.like(f"{REPORT_CACHE_PREFIX}%")
        ).all()
    else:
        rows = session.query(AnalysisCache).filter(
            AnalysisCache.cache_key.like(f"{REPORT_CACHE_PREFIX}{month}:%")
        ).all()
    count = len(rows)
    for row in rows:
        session.delete(row)
    if count:
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to invalidate report cache: {e}")
    return count
