"""FastAPI dependencies for authentication and authorization."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Permission that authorizes a non-superuser (role or direct grant) to see every
# hospital regardless of assignment. WITHOUT it, a user who has no hospitals
# assigned is scoped to NO hospitals — never to all hospitals.
UNRESTRICTED_HOSPITALS_PERMISSION = "hospitals.unrestricted"


def effective_permission_codenames(user) -> set:
    """Union of a user's direct and role-derived permission codenames."""
    return (
        {p.codename for p in user.permissions}
        | {p.codename for r in user.roles for p in r.permissions}
    )


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
        if codename not in effective_permission_codenames(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {codename}",
            )
        return user

    return checker


def user_has_unrestricted_hospitals(user) -> bool:
    """True when the user may see every hospital.

    Superadmins always qualify. A non-superuser qualifies only when a role
    (or a direct grant) carries ``hospitals.unrestricted`` — hospital
    assignment must never be the thing that grants unrestricted access.
    """
    if getattr(user, "is_superuser", False):
        return True
    try:
        return UNRESTRICTED_HOSPITALS_PERMISSION in effective_permission_codenames(user)
    except Exception:
        return False


def get_user_hospital_ids(user, db: Session) -> list[int] | None:
    """Return the hospital IDs a user may access, or ``None`` when unrestricted.

    Returns:
        None — superadmin, or a user/role explicitly authorized for
               unrestricted access (``hospitals.unrestricted`` permission).
        [1, 2, 3] — restricted to exactly these assigned hospital IDs.
        [] — no hospitals assigned and no unrestricted authorization, i.e.
             NO access. An empty assignment never means "all hospitals".
    """
    if user_has_unrestricted_hospitals(user):
        return None
    from app.models import user_hospitals as _uh
    from sqlalchemy import select as _sel
    assigned = [row[0] for row in db.execute(
        _sel(_uh.c.hospital_id).where(_uh.c.user_id == user.id)
    ).fetchall()]
    return assigned
