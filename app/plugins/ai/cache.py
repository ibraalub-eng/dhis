import json
import hashlib
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import AnalysisCache
from app.plugins.ai.providers import ai_config_signature

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def _make_cache_key(prompt: str) -> str:
    # The provider/model/prompt-schema signature is part of the key so a config
    # change (reload_ai_config) cannot serve a response produced by another model.
    payload = f"{ai_config_signature()}\n{prompt}"
    return "ai:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def get_ai_cache(session: Session, prompt: str) -> str | None:
    key = _make_cache_key(prompt)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if not row:
        return None
    if row.expires_at and datetime.utcnow() > row.expires_at:
        session.delete(row)
        session.commit()
        return None
    try:
        data = json.loads(row.result_json)
        return data.get("response")
    except Exception as e:
        logger.warning(f"Error reading AI cache: {e}")
        return None


def set_ai_cache(session: Session, prompt: str, response: str):
    key = _make_cache_key(prompt)
    expires_at = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    row = session.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
    if row:
        row.result_json = json.dumps({"response": response})
        row.expires_at = expires_at
    else:
        row = AnalysisCache(
            cache_key=key,
            result_json=json.dumps({"response": response}),
            expires_at=expires_at,
        )
        session.add(row)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to cache AI response: {e}")
