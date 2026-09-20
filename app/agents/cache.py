"""Entity-keyed, versioned, scope-safe agent cache with single-flight."""
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from app.models import AgentCache as _Row, AgentDataVersion

AGENT_CACHE_TTL_HOURS = 24
_IN_FLIGHT = {}
_IN_FLIGHT_LOCK = threading.Lock()


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def build_agent_cache_key(*, profile, hospital_scope_hash, permission_scope_hash,
                          month, entity, data_version, language, prompt_hash):
    return "agents:%s:%s:%s:%s:%s:%s:%s:%s" % (
        profile, hospital_scope_hash[:16], permission_scope_hash[:16], month,
        _h(entity or ""), data_version, language, prompt_hash[:16])


def current_data_version(db, hospital_ids, months) -> str:
    if isinstance(months, str):
        months = [months]
    if not hospital_ids:
        return "0"
    per_hospital = []
    for hid in hospital_ids:
        v = 0
        for month in months:
            rows = db.query(AgentDataVersion).filter(
                AgentDataVersion.hospital_id == hid,
                AgentDataVersion.month == month).all()
            if rows:
                v = max(v, max(r.version for r in rows))
        per_hospital.append(v)
    if all(v == 0 for v in per_hospital):
        return "0"
    return "-".join(str(v) for v in sorted(per_hospital))


def bump_data_version(db, hospital_ids, months) -> None:
    if isinstance(months, str):
        months = [months]
    if not hospital_ids or not months:
        return
    for hid in hospital_ids:
        for month in months:
            row = db.query(AgentDataVersion).filter(
                AgentDataVersion.hospital_id == hid,
                AgentDataVersion.month == month).first()
            if row:
                row.version += 1
            else:
                db.add(AgentDataVersion(hospital_id=hid, month=month, version=1))
    db.commit()


def get_agent_cache(db, key) -> str | None:
    row = db.query(_Row).filter(_Row.cache_key == key).first()
    if row is None:
        return None
    if row.expires_at is not None and datetime.utcnow() > row.expires_at:
        db.delete(row)
        db.commit()
        return None
    try:
        return json.loads(row.result_json)
    except (TypeError, ValueError):
        return None


def set_agent_cache(db, key, result_json, data_version=None,
                    hospital_scope_hash=None, ttl_hours=AGENT_CACHE_TTL_HOURS) -> None:
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    row = db.query(_Row).filter(_Row.cache_key == key).first()
    payload = json.dumps(result_json, ensure_ascii=False)
    if row:
        row.result_json = payload
        row.data_version = data_version
        row.hospital_scope_hash = hospital_scope_hash
        row.expires_at = expires
    else:
        db.add(_Row(cache_key=key, result_json=payload,
                    data_version=data_version, hospital_scope_hash=hospital_scope_hash,
                    expires_at=expires))
    db.commit()


@contextmanager
def single_flight_key(key: str):
    """Shared by identical in-flight runs; returns the result via a wait-flag."""
    with _IN_FLIGHT_LOCK:
        if key in _IN_FLIGHT:
            evt = _IN_FLIGHT[key]
            yield evt           # caller waits below
            return
        evt = threading.Event()
        _IN_FLIGHT[key] = evt
    try:
        yield evt
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.pop(key, None)