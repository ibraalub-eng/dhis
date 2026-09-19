"""Admin endpoints: user CRUD, role CRUD, permission list, score repair."""
import threading
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.core.deps import get_current_user, require_permission
from app.core.security import hash_password
from app.models import User, Role, Permission, Hospital
from app.tasks import create_task, run_task

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_permission("system.manage_users"))])


class _AppState:
    """Process-wide flags (module singleton; survives per-request deps)."""
    deep_repair_running = False


app_state = _AppState()


# --- Schemas ---

class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role_ids: list[int] = []
    permission_ids: list[int] = []
    is_superuser: bool = False


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    role_ids: Optional[list[int]] = None
    permission_ids: Optional[list[int]] = None


class AdminPasswordChangeRequest(BaseModel):
    new_password: str
    confirm_password: str = ""


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
        "direct_permissions": [{"id": p.id, "codename": p.codename} for p in u.permissions],
        "permissions": sorted({p.codename for p in u.permissions} | {p.codename for r in u.roles for p in r.permissions}),
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
    if req.permission_ids:
        user.permissions = db.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_dict(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
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
    if req.permission_ids is not None:
        user.permissions = db.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    return {"success": True, "detail": "User deactivated"}


@router.post("/users/{user_id}/change-password")
def admin_change_user_password(user_id: int, req: AdminPasswordChangeRequest, db: Session = Depends(get_db)):
    """Admin sets a new password for a user (used by the Users page)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if req.confirm_password and req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"success": True, "message": "Password changed successfully"}


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
    role = db.get(Role, role_id)
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
    role = db.get(Role, role_id)
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


# --- Role Visibility Matrix ---

# Tab definitions: tab_id -> (label, required_permission)
_TAB_DEFS = {
    "dashboard": ("📊 Dashboard", "dashboard.read"),
    "upload": ("📤 Upload", "data.upload"),
    "analysis": ("📈 Analysis", "analysis.read"),
    "quality": ("✅ Quality", "quality.read"),
    "outliers": ("⚠️ Outliers", "outliers.read"),
    "clinical": ("🏥 Clinical", "clinical.read"),
    "alerts": ("🔔 Alerts", "alerts.read"),
    "hospitals": ("🏢 Hospitals", "hospitals.read"),
    "smart_analytics": ("🛡️ Smart Analytics", "smart_analytics.read"),
    "rules": ("📋 Rules", "rules.read"),
    "root_cause": ("🔍 Root Cause", "root_cause.read"),
    "audit": ("📝 Audit", "audit.read"),
    "settings": ("⚙️ Settings", "settings.read"),
    "admin": ("👤 Admin", "system.manage_users"),
}


# --- Quality Score Repair ---

def _quality_weights(db: Session) -> dict:
    from app.config_utils import get_config_dict
    cfg = get_config_dict(db, "quality")
    return {
        "rule_compliance": float(cfg.get("quality_rule_compliance", 0.35)),
        "completeness": float(cfg.get("quality_completeness", 0.25)),
        "consistency": float(cfg.get("quality_consistency", 0.25)),
        "outlier_inverted": float(cfg.get("quality_outlier_penalty", 0.15)),
    }


def _expected_score(w: dict, rc, cp, co, op) -> float:
    op_inv = 100.0 - float(op or 0)
    expected = round(float(rc or 0) * w["rule_compliance"] + float(cp or 0) * w["completeness"]
                     + float(co or 0) * w["consistency"] + op_inv * w["outlier_inverted"], 1)
    return max(0, min(100, expected))


# The engine stores components rounded to 0.1 and rounds the final score from
# the UNROUNDED components, so the formula applied to stored components can
# legitimately differ from the stored score by up to 0.1 (0.05 per component
# weighting + 0.05 final rounding). Anything beyond that is a real mismatch.
SHALLOW_TOLERANCE = 0.15


def _is_no_data_sentinel(s) -> bool:
    """True for placeholder rows the engine writes for hospital/months with
    no analyzable data (pipeline.py: everything zeroed + sentinel issue text).
    Such rows have no meaningful formula result and must be left alone."""
    comps = (s.rule_compliance, s.completeness, s.consistency, s.outlier_penalty)
    if any(float(c or 0) != 0.0 for c in comps):
        return False
    if float(s.score or 0) != 0.0:
        return False
    return "no data" in (s.issues or "").lower()


def _shallow_check(w: dict, rows):
    """Shared shallow-mode logic: return (mismatches, sentinel_count) where
    mismatches is a list of (row, expected_score) tuples. Used by both the
    preview and the repair so they can never disagree."""
    mismatches, sentinels = [], 0
    for s in rows:
        if _is_no_data_sentinel(s):
            sentinels += 1
            continue
        expected = _expected_score(w, s.rule_compliance, s.completeness, s.consistency, s.outlier_penalty)
        if abs(expected - float(s.score or 0)) > SHALLOW_TOLERANCE:
            mismatches.append((s, expected))
    return mismatches, sentinels


def _deep_targets(db: Session) -> list:
    """(hospital_id, month) pairs from QualityScore that still have *enabled*
    raw indicator values — the pairs deep mode will recompute from source
    data. Uses the engine's own enabled-values logic so a pair the pipeline
    would treat as "no data" (all values disabled/null) is not targeted; deep
    repair never deletes the sentinel rows written for those."""
    from app.models import QualityScore
    from app.engine.pipeline import get_enabled_values_for_hospital_month
    pairs = db.query(QualityScore.hospital_id, QualityScore.month).distinct().all()
    return [(h, m) for (h, m) in pairs if get_enabled_values_for_hospital_month(db, h, m)]


def _run_deep_recompute(task_id: str, targets: list):
    """Background worker: recompute every target (hospital, month) through the
    canonical engine pipeline (same as upload/reanalyze-all). Uses its own DB
    session; writes nothing for months that were skipped."""
    from app.engine.pipeline import recompute_hospital_months
    from app.tasks import set_progress, set_status
    bg_db = SessionLocal()
    recomputed, failed, skipped = 0, 0, 0
    try:
        total = max(len(targets), 1)
        # Group by hospital so each hospital recompute covers all its months
        by_hospital = {}
        for h, m in targets:
            by_hospital.setdefault(h, []).append(m)
        done = 0
        for h_id, months in sorted(by_hospital.items()):
            try:
                n = recompute_hospital_months(bg_db, h_id, sorted(months), force=True)
                if n is None:
                    n = 0
                recomputed += n
                failed += len(months) - n
            except Exception:
                bg_db.rollback()
                failed += len(months)
            done += len(months)
            set_progress(task_id, int(done / total * 100))
        set_status(task_id, "done")
    except Exception as e:  # run_task also guards, but keep the session safe
        try:
            bg_db.rollback()
        except Exception:
            pass
        raise
    finally:
        bg_db.close()
    return {"recomputed": recomputed, "failed": failed, "skipped": skipped}


@router.get("/quality-scores/repair-preview")
def repair_quality_scores_preview(
    deep: bool = False,  # query param: list deep-mode recompute targets instead of formula mismatches
    db: Session = Depends(get_db),
    _user=Depends(require_permission("system.manage_data")),
):
    """Dry-run. shallow (default): find stored QualityScore rows whose
    components do not sum to the stored final score under the engine formula
    (weights from the quality config). deep: list the (hospital, month) pairs
    that deep repair would recompute from raw indicator values — read-only,
    nothing is written either way."""
    from app.models import QualityScore

    rows = db.query(QualityScore).all()
    if deep:
        targets = _deep_targets(db)
        return {
            "mode": "deep",
            "total_rows": len(rows),
            "target_count": len(targets),
            "targets": [
                {"hospital_id": h, "month": m,
                 "stored_score": next((float(s.score or 0) for s in rows if s.hospital_id == h and s.month == m), None)}
                for h, m in targets[:200]
            ],
            "truncated": len(targets) > 200,
            "note": "Deep repair reruns the full engine pipeline per hospital/month; exact post-values are only known after it runs.",
        }

    w = _quality_weights(db)
    mismatches, sentinels = _shallow_check(w, rows)
    return {
        "mode": "shallow",
        "total_rows": len(rows),
        "sentinel_rows_skipped": sentinels,
        "mismatch_count": len(mismatches),
        "weights": w,
        "mismatches": [
            {"id": s.id, "hospital_id": s.hospital_id, "month": s.month,
             "stored_score": s.score, "expected_score": expected}
            for (s, expected) in mismatches[:200]
        ],
        "truncated": len(mismatches) > 200,
    }

    rows = db.query(QualityScore).all()
    mismatches = []
    for s in rows:
        rc = float(s.rule_compliance or 0)
        cp = float(s.completeness or 0)
        co = float(s.consistency or 0)
        op_inv = 100.0 - float(s.outlier_penalty or 0)
        expected = round(rc * w_rc + cp * w_cp + co * w_co + op_inv * w_op, 1)
        expected = max(0, min(100, expected))
        if abs(expected - float(s.score or 0)) > 0.05:
            mismatches.append({
                "id": s.id, "hospital_id": s.hospital_id, "month": s.month,
                "stored_score": s.score, "expected_score": expected,
            })
    return {
        "total_rows": len(rows),
        "mismatch_count": len(mismatches),
        "weights": {"rule_compliance": w_rc, "completeness": w_cp,
                     "consistency": w_co, "outlier_inverted": w_op},
        "mismatches": mismatches[:200],
        "truncated": len(mismatches) > 200,
    }


@router.post("/quality-scores/repair")
def repair_quality_scores(
    background_tasks: BackgroundTasks = None,
    deep: bool = False,  # query param: recompute all components from raw indicator values via the engine pipeline (background task)
    db: Session = Depends(get_db),
    _user=Depends(require_permission("system.manage_data")),
):
    """Repair QualityScore rows.

    shallow (default): recompute the final score from the STORED components
    using the engine formula and overwrite divergent scores. Component values
    are kept.

    deep: rerun the full engine pipeline (recompute_hospital_months, the same
    path as upload/reanalyze-all) for every hospital/month that still has raw
    indicator values — recomputing rule compliance, completeness, consistency,
    and outliers from source data. Runs as a background task; poll
    /tasks/{task_id}. Pairs without raw values are skipped (never deleted)."""
    from app.models import QualityScore

    rows = db.query(QualityScore).all()

    if deep:
        if getattr(app_state, "deep_repair_running", False):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="A deep repair is already running")
        targets = _deep_targets(db)
        app_state.deep_repair_running = True
        task_id = create_task("Deep Quality Score Repair", lambda: None)

        def _run(tid):
            try:
                return _run_deep_recompute(tid, targets)
            finally:
                app_state.deep_repair_running = False

        if background_tasks is not None:
            background_tasks.add_task(run_task, task_id, _run, task_id)
        else:
            threading.Thread(target=run_task, args=(task_id, _run, task_id), daemon=True).start()
        return {
            "mode": "deep",
            "task_id": task_id,
            "target_count": len(targets),
            "message": f"Deep repair started for {len(targets)} hospital/month pairs. Use /tasks/{task_id} to check status.",
        }

    w = _quality_weights(db)
    mismatches, _sentinels = _shallow_check(w, rows)
    repaired = 0
    for s, expected in mismatches:
        s.score = expected
        repaired += 1
    if repaired:
        db.commit()
    return {
        "mode": "shallow",
        "total_rows": len(rows),
        "repaired": repaired,
        "already_consistent": len(rows) - repaired,
    }


@router.get("/visibility-matrix")
def get_visibility_matrix(db: Session = Depends(get_db)):
    """Return a matrix of roles × tabs showing which tabs each role can see."""
    roles = db.query(Role).order_by(Role.id).all()
    result = {"tabs": {}, "roles": []}
    for tab_id, (label, perm) in _TAB_DEFS.items():
        result["tabs"][tab_id] = {"label": label, "permission": perm}
    for role in roles:
        perm_codes = {p.codename for p in role.permissions}
        is_super = role.is_system and role.name == "superadmin"
        tab_access = {}
        for tab_id, (_, perm) in _TAB_DEFS.items():
            tab_access[tab_id] = is_super or ("*.*" in perm_codes) or (perm in perm_codes)
        result["roles"].append({
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "is_superuser": is_super,
            "permission_count": len(perm_codes),
            "tab_access": tab_access,
        })
    return result
