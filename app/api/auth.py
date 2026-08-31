"""Authentication endpoints: login, refresh, logout, me."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.core.deps import get_current_user
from app.models import User, RefreshToken, SessionLog

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent", ""))[:500]
    if user is None or not verify_password(req.password, user.password_hash):
        try:
            db.add(SessionLog(user_id=user.id if user else None, username=req.username,
                              event="failed_login", ip_address=ip, user_agent=ua))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        try:
            db.add(SessionLog(user_id=user.id, username=req.username,
                              event="inactive_account", ip_address=ip, user_agent=ua))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive")

    roles = [r.name for r in user.roles]
    permissions = list({p.codename for r in user.roles for p in r.permissions})
    if user.is_superuser:
        permissions = ["*.*"]

    access = create_access_token(user.id, roles, permissions)
    refresh_token_str, jti, expires_at = create_refresh_token(user.id, remember_me=req.remember_me)

    rt = RefreshToken(user_id=user.id, token_jti=jti, expires_at=expires_at)
    db.add(rt)
    db.commit()
    try:
        db.add(SessionLog(user_id=user.id, username=user.username, event="login",
                          ip_address=ip, user_agent=ua))
        db.commit()
    except Exception:
        db.rollback()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_token_str,
        user={"id": user.id, "username": user.username, "full_name": user.full_name,
              "roles": roles, "permissions": permissions},
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    jti = payload.get("jti")
    rt = db.query(RefreshToken).filter(RefreshToken.token_jti == jti).first()
    if rt is None or rt.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
    if datetime.now(timezone.utc) > rt.expires_at.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    # Rotate: revoke old, issue new
    rt.revoked = True
    db.commit()

    user = db.query(User).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    roles = [r.name for r in user.roles]
    permissions = list({p.codename for r in user.roles for p in r.permissions})
    if user.is_superuser:
        permissions = ["*.*"]

    new_access = create_access_token(user.id, roles, permissions)
    new_refresh_str, new_jti, new_exp = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_jti=new_jti, expires_at=new_exp))
    db.commit()

    return {"access_token": new_access, "refresh_token": new_refresh_str, "token_type": "bearer"}


class LogoutRequest(BaseModel):
    refresh_token: str


@router.post("/logout")
def logout(req: LogoutRequest, request: Request, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent", ""))[:500]
    if payload and payload.get("jti"):
        rt = db.query(RefreshToken).filter(RefreshToken.token_jti == payload["jti"]).first()
        if rt:
            rt.revoked = True
            uid = rt.user_id
            uname = None
            u = db.query(User).filter(User.id == uid).first() if uid else None
            if u:
                uname = u.username
            try:
                db.add(SessionLog(user_id=uid, username=uname or "unknown", event="logout",
                                  ip_address=ip, user_agent=ua))
                db.commit()
            except Exception:
                db.rollback()
    return {"success": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    roles = [r.name for r in user.roles]
    permissions = list({p.codename for r in user.roles for p in r.permissions})
    if user.is_superuser:
        permissions = ["*.*"]
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_superuser": user.is_superuser,
        "roles": roles,
        "permissions": permissions,
    }


class ProfileUpdateRequest(BaseModel):
    full_name: str = ""
    email: str = ""


@router.put("/me")
def update_own_profile(req: ProfileUpdateRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Logged-in user updates their own profile (full name, email)."""
    if req.full_name:
        user.full_name = req.full_name.strip()
    if req.email:
        email = req.email.strip().lower()
        # Check uniqueness
        existing = db.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use by another user")
        user.email = email
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "message": "Profile updated successfully"
    }


class SelfPasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str = ""


@router.post("/change-password")
def change_own_password(req: SelfPasswordChangeRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Logged-in user changes their own password."""
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from current")
    if req.confirm_password and req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"success": True, "message": "Password changed successfully"}


@router.get("/sessions")
def get_sessions(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Return recent session events. Superadmin only."""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superadmin only")
    from sqlalchemy import func
    limit = int(request.query_params.get("limit", 100))
    limit = min(limit, 500)
    logs = db.query(SessionLog).order_by(SessionLog.created_at.desc()).limit(limit).all()
    # Active sessions: logins without a subsequent logout
    # Get last event per user
    last_events = (
        db.query(
            SessionLog.user_id,
            SessionLog.username,
            func.max(SessionLog.created_at).label("last_at")
        )
        .group_by(SessionLog.user_id, SessionLog.username)
        .subquery()
    )
    # Check which users last event was a login (still online)
    online_rows = (
        db.query(SessionLog)
        .join(last_events, (SessionLog.user_id == last_events.c.user_id) & (SessionLog.created_at == last_events.c.last_at))
        .filter(SessionLog.event.in_("login", "refresh"))
        .all()
    )
    online_user_ids = {r.user_id for r in online_rows if r.user_id}
    return {
        "events": [{
            "id": l.id,
            "user_id": l.user_id,
            "username": l.username,
            "event": l.event,
            "ip_address": l.ip_address,
            "user_agent": l.user_agent,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
        "online": list(online_user_ids),
    }


@router.post("/sessions/kick")
def kick_user(req: LogoutRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Force-revoke a refresh token (kick a user offline). Superadmin only."""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superadmin only")
    payload = decode_token(req.refresh_token)
    if payload and payload.get("jti"):
        rt = db.query(RefreshToken).filter(RefreshToken.token_jti == payload["jti"]).first()
        if rt and not rt.revoked:
            rt.revoked = True
            db.commit()
            return {"success": True, "message": "User kicked"}
    return {"success": False, "message": "Token already revoked or not found"}
