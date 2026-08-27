"""FastAPI dependencies for authentication and authorization."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Decode JWT and return the User record. Raises 401 on failure."""
    from app.models import User  # avoid circular import

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_permission(codename: str):
    """Return a dependency that checks the current user has a specific permission."""

    def checker(
        user=Depends(get_current_user),
    ):
        if user.is_superuser:
            return user
        user_perms = {p.codename for r in user.roles for p in r.permissions}
        if codename not in user_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {codename}",
            )
        return user

    return checker


def get_user_hospital_ids(user, db: Session) -> list[int] | None:
    """Return the list of hospital IDs a user is restricted to.

    Returns:
        None — user is superadmin or has no restriction (see all hospitals)
        [] — user explicitly assigned zero hospitals (should see nothing, treat as all)
        [1, 2, 3] — user restricted to these hospital IDs
    """
    if getattr(user, 'is_superuser', False):
        return None
    from app.models import user_hospitals as _uh
    from sqlalchemy import select as _sel
    assigned = [row[0] for row in db.execute(
        _sel(_uh.c.hospital_id).where(_uh.c.user_id == user.id)
    ).fetchall()]
    return assigned if assigned else None  # empty list means no restriction
