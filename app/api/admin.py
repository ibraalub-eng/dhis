"""Admin endpoints: user CRUD, role CRUD, permission list."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.security import hash_password
from app.models import User, Role, Permission

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_permission("system.manage_users"))])


# --- Schemas ---

class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role_ids: list[int] = []
    is_superuser: bool = False


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    role_ids: Optional[list[int]] = None


class RoleCreate(BaseModel):
    name: str
    description: str = ""
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[list[int]] = None


def _user_dict(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "email": u.email,
        "full_name": u.full_name, "is_active": u.is_active,
        "is_superuser": u.is_superuser,
        "roles": [{"id": r.id, "name": r.name} for r in u.roles],
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# --- Users ---

@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return {"users": [_user_dict(u) for u in users]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(req: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        username=req.username, email=req.email, full_name=req.full_name,
        password_hash=hash_password(req.password),
        is_superuser=req.is_superuser,
    )
    if req.role_ids:
        user.roles = db.query(Role).filter(Role.id.in_(req.role_ids)).all()
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_dict(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.email is not None:
        existing = db.query(User).filter(User.email == req.email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = req.email
    if req.full_name is not None:
        user.full_name = req.full_name
    if req.password is not None:
        user.password_hash = hash_password(req.password)
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.is_superuser is not None:
        user.is_superuser = req.is_superuser
    if req.role_ids is not None:
        user.roles = db.query(Role).filter(Role.id.in_(req.role_ids)).all()
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    return {"success": True, "detail": "User deactivated"}


# --- Roles ---

@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.id).all()
    return {"roles": [{"id": r.id, "name": r.name, "description": r.description,
                         "is_system": r.is_system,
                         "permission_ids": [p.id for p in r.permissions],
                         "user_count": len(r.users)} for r in roles]}


@router.get("/roles/{role_id}")
def get_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return {
        "id": role.id, "name": role.name, "description": role.description,
        "is_system": role.is_system,
        "permission_ids": [p.id for p in role.permissions],
        "user_count": len(role.users),
    }


@router.post("/roles", status_code=status.HTTP_201_CREATED)
def create_role(req: RoleCreate, db: Session = Depends(get_db)):
    if db.query(Role).filter(Role.name == req.name).first():
        raise HTTPException(status_code=400, detail="Role name already exists")
    role = Role(name=req.name, description=req.description)
    if req.permission_ids:
        role.permissions = db.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
    db.add(role)
    db.commit()
    db.refresh(role)
    return {"id": role.id, "name": role.name, "description": role.description}


@router.put("/roles/{role_id}")
def update_role(role_id: int, req: RoleUpdate, db: Session = Depends(get_db)):
    role = db.query(Role).get(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system and role.name == "superadmin":
        raise HTTPException(status_code=400, detail="Cannot modify the superadmin role")
    if req.name is not None:
        existing = db.query(Role).filter(Role.name == req.name, Role.id != role_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Role name already exists")
        role.name = req.name
    if req.description is not None:
        role.description = req.description
    if req.permission_ids is not None:
        role.permissions = db.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
    db.commit()
    db.refresh(role)
    return {"id": role.id, "name": role.name, "description": role.description}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).get(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system role")
    if role.users:
        raise HTTPException(status_code=400, detail="Cannot delete role with assigned users")
    db.delete(role)
    db.commit()
    return {"success": True}


# --- User Hospital Assignments ---

@router.get("/users/{user_id}/hospitals")
def get_user_hospitals(user_id: int, db: Session = Depends(get_db)):
    """Get hospitals assigned to a user. Empty list = all hospitals (no restriction)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    hospitals = [{"id": h.id, "name": h.name} for h in user.hospitals]
    return {"user_id": user_id, "username": user.username, "hospitals": hospitals, "is_restricted": len(hospitals) > 0}


@router.put("/users/{user_id}/hospitals")
def update_user_hospitals(user_id: int, req: dict, db: Session = Depends(get_db)):
    """Update hospitals assigned to a user.
    Pass {"hospital_ids": [1,2,3]} to restrict, or {"hospital_ids": []} to allow all.
    Superusers always see all hospitals regardless of assignment."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser:
        return {"message": "Superusers always see all hospitals.", "hospital_ids": []}

    hospital_ids = req.get("hospital_ids", [])
    if hospital_ids:
        hospitals = db.query(Hospital).filter(Hospital.id.in_(hospital_ids)).all()
        user.hospitals = hospitals
    else:
        user.hospitals = []
    db.commit()
    return {"user_id": user_id, "username": user.username, "hospital_count": len(user.hospitals), "message": f"Assigned {len(user.hospitals)} hospitals to {user.username}"}


# --- Permissions ---

@router.get("/permissions")
def list_permissions(db: Session = Depends(get_db)):
    perms = db.query(Permission).order_by(Permission.codename).all()
    return {"permissions": [{"id": p.id, "codename": p.codename, "description": p.description} for p in perms]}
