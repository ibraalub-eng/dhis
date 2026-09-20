"""AI agents API — kill-switch, permissions, hospital scope, daily caps."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.runtime import run_agent
from app.config_utils import get_ai_config, validate_agents_config
from app.core.deps import get_current_user, get_user_hospital_ids, require_permission
from app.database import get_db
from app.models import AgentRun, Conversation, Hospital, IndicatorValue, Message

router = APIRouter(prefix="/ai/agents", tags=["agents"])

AGENT_DAILY_CAP = 20
_AGENT_SETTING_KEYS = ("agents_enabled", "agents_provider", "agent_provider_roles",
                       "local_runtime", "local_model", "local_url")
_AGENT_ADMIN_KEYS = ("agent_cap", "agent_retention_days")


def _agent_enabled(db) -> bool:
    return str(get_ai_config(db).get("agents_enabled", "false")).lower() == "true"


def require_ai_write(
    user=Depends(require_permission("ai.write")),
    _read_ok=Depends(require_permission("ai.read")),
):
    """Report/digest gates: BOTH ai.write AND ai.read (spec §9). Each
    sub-dependency raises 403 independently; the user the caller sees is the
    ai.write one (same user object)."""
    return user


def _check_daily_cap(db, user):
    from app.models import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == "agent_cap").first()
    try:
        cap = int(row.value)
    except (AttributeError, TypeError, ValueError):
        cap = AGENT_DAILY_CAP
    if cap < 1:
        cap = AGENT_DAILY_CAP
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.query(AgentRun).filter(
        AgentRun.user_id == user.id,
        AgentRun.created_at >= today_start,
    ).count()
    if count >= cap:
        raise HTTPException(status_code=429, detail="Daily agent run limit reached")


def save_agent_run(db, user, result, conversation_id=None):
    row = AgentRun(user_id=user.id, agent=result.agent, conversation_id=conversation_id,
                   status=result.status, duration_ms=result.duration_ms,
                   steps=result.steps, tool_calls=result.tool_calls, tokens=result.tokens,
                   data_version=result.data_version, model=result.model,
                   provider=result.provider, language=result.language,
                   cache_hit=result.cache_hit, fallback_used=result.fallback_used,
                   hospital_scope_hash=result.hospital_scope_hash,
                   permission_scope_hash=result.permission_scope_hash,
                   prompt_hash=result.prompt_hash, error=result.error)
    db.add(row)
    db.commit()
    return row.id


def _run_and_persist(db, user, profile, month, lang, entity, question, history=None):
    result = run_agent(profile=profile, user=user, db=db, month=month, lang=lang,
                       entity=entity, question=question, history=history)
    run_id = save_agent_run(db, user, result)
    return result, run_id


def _month_for_user(db, user) -> str:
    """Most recent month with data across the user's hospitals, else current."""
    hids = get_user_hospital_ids(user, db)
    if hids is None:
        hids = [r.id for r in db.query(Hospital).filter(Hospital.is_active).all()]
    if hids:
        latest = db.query(func.max(IndicatorValue.month)).filter(
            IndicatorValue.hospital_id.in_(hids)).scalar()
        if latest:
            return latest
    return datetime.utcnow().strftime("%Y-%m")


def _conversation(db, user, conversation_id):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("/chat")
def chat(body: dict, user=Depends(require_permission("ai.read")), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    _check_daily_cap(db, user)
    conv = None
    if body.get("conversation_id"):
        conv = _conversation(db, user, body["conversation_id"])
    else:
        conv = Conversation(user_id=user.id, title=message[:80], lang=body.get("lang", "en"))
        db.add(conv)
        db.commit()
    db.add(Message(conversation_id=conv.id, message_type="user", role="user", content=message))
    db.commit()
    prior = [{"role": m.role, "content": m.content}
             for m in db.query(Message).filter(Message.conversation_id == conv.id,
                                               Message.message_type.in_(("user", "assistant")))
             .order_by(Message.id).all()[:-1]]  # exclude the message just stored
    result, _ = _run_and_persist(db, user, "qa", _month_for_user(db, user),
                                 body.get("lang") or conv.lang or "en", "", message,
                                 history=prior or None)
    db.add(Message(conversation_id=conv.id, message_type="assistant", role="assistant",
                   content=result.answer, token_usage=result.tokens))
    db.commit()
    return {"enabled": True, "conversation_id": conv.id, "answer": result.answer,
            "steps": result.steps, "provider": result.provider, "model": result.model,
            "fallback_used": result.fallback_used, "sources": result.sources}


@router.get("/chat/{conversation_id}/messages")
def chat_messages(conversation_id: int, user=Depends(require_permission("ai.read")),
                  db: Session = Depends(get_db)):
    _conversation(db, user, conversation_id)
    msgs = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [{"message_type": m.message_type, "role": m.role, "content": m.content,
             "tool_steps": m.tool_steps, "created_at": m.created_at.isoformat()} for m in msgs]


@router.post("/explain")
def explain(body: dict, user=Depends(require_permission("ai.read")), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    month = body.get("month")
    if not month:
        raise HTTPException(status_code=422, detail="month is required")
    hospital_id = body.get("hospital_id")
    if hospital_id is None:
        raise HTTPException(status_code=422, detail="hospital_id is required")
    result, _ = _run_and_persist(db, user, "explainer", month, body.get("lang", "en"),
                                 str(body.get("entity", "")),
                                 f"Explain {body.get('entity', '')} at hospital {hospital_id} for {month}")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.post("/report")
def report(body: dict, user=Depends(require_ai_write), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    month = body.get("month")
    if not month:
        raise HTTPException(status_code=422, detail="month is required")
    hospital_id = body.get("hospital_id")
    if hospital_id is None:
        raise HTTPException(status_code=422, detail="hospital_id is required")
    result, _ = _run_and_persist(db, user, "report_writer", month, body.get("lang", "en"),
                                 str(hospital_id), f"Write the {month} report")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.post("/digest")
def digest(body: dict, user=Depends(require_ai_write), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    month = body.get("month")
    if not month:
        raise HTTPException(status_code=422, detail="month is required")
    result, _ = _run_and_persist(db, user, "triage", month, body.get("lang", "en"), "",
                                 f"Generate the triage digest for {month}")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.get("/status")
def status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    perms = {p.codename for p in user.permissions} | {p.codename for r in user.roles for p in r.permissions}
    if user.is_superuser:
        perms |= {"ai.read", "ai.write", "system.manage_users"}
    provider = get_ai_config(db).get("agents_provider", "auto")
    return {"enabled": _agent_enabled(db), "permissions": sorted(perms), "provider": provider}


@router.get("/runs")
def runs(page: int = 1, per_page: int = 20,
         user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    q = db.query(AgentRun).order_by(AgentRun.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total = db.query(AgentRun).count()
    return {"total": total, "page": page, "per_page": per_page,
            "runs": [{"id": r.id, "user_id": r.user_id, "agent": r.agent, "status": r.status,
                      "duration_ms": r.duration_ms, "steps": r.steps, "tool_calls": r.tool_calls,
                      "tokens": r.tokens, "data_version": r.data_version, "model": r.model,
                      "provider": r.provider, "language": r.language, "cache_hit": r.cache_hit,
                      "fallback_used": r.fallback_used, "created_at": r.created_at.isoformat()}
                     for r in q]}


@router.get("/admin")
def admin_get(user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    from app.models import SystemSetting
    cfg = get_ai_config(db)
    row = {s.key: s.value for s in db.query(SystemSetting).filter(
        SystemSetting.key.in_(("agent_cap", "agent_retention_days"))).all()}
    out = {k: cfg.get(k) for k in _AGENT_SETTING_KEYS}
    cap_raw = row.get("agent_cap") or cfg.get("agent_cap")
    ret_raw = row.get("agent_retention_days") or cfg.get("agent_retention_days")
    try:
        out["agent_cap"] = int(cap_raw)
    except (TypeError, ValueError):
        out["agent_cap"] = AGENT_DAILY_CAP
    try:
        out["agent_retention_days"] = int(ret_raw)
    except (TypeError, ValueError):
        out["agent_retention_days"] = 90
    return out


@router.put("/admin")
def admin_put(body: dict, user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.items() if k in _AGENT_SETTING_KEYS}
    # admin-only numeric settings (persisted as SystemSetting, read by admin_get)
    for k in _AGENT_ADMIN_KEYS:
        if k in body and body[k] is not None:
            try:
                v = int(body[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{k} must be an integer") from None
            if k == "agent_cap" and not 1 <= v <= 1000:
                raise HTTPException(status_code=422, detail="agent_cap must be 1..1000")
            if k == "agent_retention_days" and not 1 <= v <= 3650:
                raise HTTPException(status_code=422, detail="agent_retention_days must be 1..3650")
            updates[k] = str(v)
    try:
        validate_agents_config(updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    from app.models import SystemSetting
    for k, v in updates.items():
        row = db.query(SystemSetting).filter(SystemSetting.key == k).first()
        if row:
            row.value = str(v)
        else:
            db.add(SystemSetting(key=k, value=str(v)))
    db.commit()
    return {"status": "ok"}
