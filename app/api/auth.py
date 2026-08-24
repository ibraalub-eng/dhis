"""Authentication endpoints: login, refresh, logout, me."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.core.deps import get_current_user
from app.models import User, RefreshToken

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
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
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
def logout(req: LogoutRequest, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload and payload.get("jti"):
        rt = db.query(RefreshToken).filter(RefreshToken.token_jti == payload["jti"]).first()
        if rt:
            rt.revoked = True
            db.commit()
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
        "roles": roles,
        "permissions": permissions,
    }
