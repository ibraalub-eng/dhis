# Login Flow & System Permissions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add JWT authentication, RBAC permissions, bilingual login page, and admin panel to the health analytics dashboard.

**Architecture:** JWT access+refresh tokens with bcrypt password hashing. SQLAlchemy models for User, Role, Permission with many-to-many associations. FastAPI dependency injection for route protection. Vanilla JS login page embedded in the existing SPA.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, bcrypt (passlib), python-jose (JWT), vanilla JS/CSS

## Global Constraints

- Database: PostgreSQL (prod), SQLite (tests) — use `app/database.py` patterns
- Frontend: vanilla JS/CSS, Arabic RTL, no frameworks
- Auth library: `passlib[bcrypt]` for hashing, `python-jose[cryptography]` for JWT
- New env vars: `JWT_SECRET`, `JWT_ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_DAYS=7`, `ADMIN_PASSWORD=admin123`
- Never commit `.env` — update `.env.example` only
- Default superadmin: username `admin`, password from `ADMIN_PASSWORD` env var
- Alembic migration must be reversible
- All new API tests go in `tests/test_auth.py`
- Follow existing patterns: `app/api/` router pattern, `app/models.py` model pattern, `tests/conftest.py` fixture pattern

---

### Task 1: Add Auth Dependencies & Config

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `app/core/__init__.py` (empty)
- Create: `app/core/security.py`
- Create: `app/core/deps.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces: `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`, `create_access_token(user_id, roles, permissions) -> str`, `create_refresh_token(user_id) -> str`, `decode_token(token) -> dict`
- Produces: `get_current_user(token, db) -> User`, `require_permission(codename) -> Dependency`

- [ ] **Step 1: Add JWT config to app/config.py**

```python
# Add to app/config.py (after existing config vars):
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
```

- [ ] **Step 2: Update .env.example**

Add these lines to `.env.example`:
```
JWT_SECRET=change-me-to-a-random-64-char-hex
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
ADMIN_PASSWORD=admin123
```

- [ ] **Step 3: Create app/core/__init__.py**

```python
# empty file
```

- [ ] **Step 4: Create app/core/security.py**

```python
"""JWT token creation/verification and password hashing."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, roles: list[str], permissions: list[str]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "roles": roles,
        "permissions": permissions,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Returns (token_string, jti, expires_at)."""
    jti = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "exp": expires_at,
        "type": "refresh",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT. Returns payload dict or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
```

- [ ] **Step 5: Create app/core/deps.py**

```python
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
```

- [ ] **Step 6: Write failing tests in tests/test_auth.py**

```python
"""Tests for auth security utilities and dependencies."""
import pytest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)


def test_hash_and_verify_password():
    hashed = hash_password("testpass123")
    assert hashed != "testpass123"
    assert verify_password("testpass123", hashed)
    assert not verify_password("wrongpass", hashed)


def test_create_and_decode_access_token():
    token = create_access_token(user_id=1, roles=["admin"], permissions=["dashboard.read"])
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "1"
    assert payload["roles"] == ["admin"]
    assert payload["permissions"] == ["dashboard.read"]
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token, jti, expires_at = create_refresh_token(user_id=42)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["jti"] == jti
    assert payload["type"] == "refresh"


def test_decode_invalid_token_returns_none():
    assert decode_token("garbage.token.value") is None


def test_decode_expired_token():
    """Manually create an expired token."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import JWT_SECRET, JWT_ALGORITHM

    payload = {
        "sub": "1",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "type": "access",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert decode_token(token) is None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add app/config.py .env.example app/core/__init__.py app/core/security.py app/core/deps.py tests/test_auth.py
git commit -m "feat(auth): add JWT security utilities and auth dependencies"
```

---

### Task 2: Add Auth Models

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Produces: `User`, `Role`, `Permission`, `RefreshToken` models
- Produces: `user_roles`, `role_permissions` association tables

- [ ] **Step 1: Add models to app/models.py**

Add these models at the end of `app/models.py` (before the last line):

```python
from sqlalchemy import Table, Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

# Association tables
user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, index=True)
    codename = Column(String(80), unique=True, nullable=False)
    description = Column(String(200))


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200))
    is_system = Column(Boolean, default=False)
    permissions = relationship("Permission", secondary=role_permissions, backref="roles")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    password_hash = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"), onupdate=text("now()"))
    roles = relationship("Role", secondary=user_roles, backref="users")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    token_jti = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("now()"))
```

Make sure the `text` import is at the top of models.py (it should already be there).

- [ ] **Step 2: Write model tests in tests/test_auth.py**

Append to `tests/test_auth.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import User, Role, Permission, RefreshToken, user_roles, role_permissions


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_permission(db_session):
    p = Permission(codename="dashboard.read", description="Read dashboard")
    db_session.add(p)
    db_session.commit()
    assert db_session.query(Permission).filter_by(codename="dashboard.read").count() == 1


def test_create_role_with_permissions(db_session):
    p1 = Permission(codename="dashboard.read")
    p2 = Permission(codename="data.upload")
    role = Role(name="doctor", description="Doctor role", permissions=[p1, p2])
    db_session.add(role)
    db_session.commit()
    fetched = db_session.query(Role).filter_by(name="doctor").first()
    assert len(fetched.permissions) == 2
    assert {p.codename for p in fetched.permissions} == {"dashboard.read", "data.upload"}


def test_create_user_with_role(db_session):
    p = Permission(codename="dashboard.read")
    role = Role(name="viewer", permissions=[p])
    user = User(
        username="testuser", email="test@test.com", full_name="Test User",
        password_hash=hash_password("pass123"), roles=[role],
    )
    db_session.add(user)
    db_session.commit()
    fetched = db_session.query(User).filter_by(username="testuser").first()
    assert fetched is not None
    assert len(fetched.roles) == 1
    assert fetched.roles[0].name == "viewer"


def test_refresh_token_model(db_session):
    user = User(username="u1", email="u1@test.com", full_name="U1", password_hash=hash_password("p"))
    db_session.add(user)
    db_session.commit()
    rt = RefreshToken(user_id=user.id, token_jti="abc123", expires_at="2026-12-31")
    db_session.add(rt)
    db_session.commit()
    assert db_session.query(RefreshToken).filter_by(token_jti="abc123").count() == 1
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_auth.py -v`
Expected: 9 passed (5 security + 4 model)

- [ ] **Step 4: Commit**

```bash
git add app/models.py tests/test_auth.py
git commit -m "feat(auth): add User, Role, Permission, RefreshToken models"
```

---

### Task 3: Create Alembic Migration

**Files:**
- Create: `alembic/versions/2026_08_23_add_auth_tables.py`

**Interfaces:**
- Produces: migration that creates users, roles, permissions, user_roles, role_permissions, refresh_tokens tables and seeds default data

- [ ] **Step 1: Generate migration**

Run: `alembic revision --autogenerate -m "add auth tables"`
This creates a new file in `alembic/versions/`.

- [ ] **Step 2: Edit the migration to add seed data**

In the `upgrade()` function, after the `op.create_table` calls, add:

```python
from sqlalchemy import insert
from app.models import Permission, Role, User, role_permissions
from app.core.security import hash_password

# Seed permissions
permissions_data = [
    ("dashboard.read", "Read dashboard"),
    ("analysis.read", "Read analysis"),
    ("quality.read", "Read quality"),
    ("outliers.read", "Read outliers"),
    ("clinical.read", "Read clinical"),
    ("alerts.read", "Read alerts"),
    ("hospitals.read", "Read hospitals"),
    ("smart_analytics.read", "Read smart analytics"),
    ("rules.read", "Read rules"),
    ("root_cause.read", "Read root cause"),
    ("audit.read", "Read audit"),
    ("settings.read", "Read settings"),
    ("data.upload", "Upload data"),
    ("data.export", "Export data"),
    ("smart_analytics.generate_report", "Generate smart analytics report"),
    ("system.manage_users", "Manage users and roles"),
]
for codename, desc in permissions_data:
    op.execute(insert(Permission).values(codename=codename, description=desc))

# Seed roles
roles_data = [
    ("superadmin", "Super administrator", True),
    ("admin", "Administrator", True),
    ("doctor", "Doctor", True),
    ("viewer", "Viewer (read-only)", True),
]
for name, desc, is_sys in roles_data:
    op.execute(insert(Role).values(name=name, description=desc, is_system=is_sys))

# Assign permissions to roles (via raw SQL for simplicity)
# superadmin: all permissions (handled by is_superuser flag)
# admin: all except system.manage_users
op.execute("""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM roles r, permissions p
    WHERE r.name = 'admin' AND p.codename != 'system.manage_users'
""")
# doctor: specific read + generate_report
op.execute("""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM roles r, permissions p
    WHERE r.name = 'doctor' AND p.codename IN (
        'dashboard.read', 'analysis.read', 'quality.read', 'smart_analytics.read',
        'smart_analytics.generate_report', 'hospitals.read', 'clinical.read', 'alerts.read'
    )
""")
# viewer: all *.read
op.execute("""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM roles r, permissions p
    WHERE r.name = 'viewer' AND p.codename LIKE '%.read'
""")

# Create default superadmin user
import os
admin_pw = os.getenv("ADMIN_PASSWORD", "admin123")
op.execute("""
    INSERT INTO users (username, email, full_name, password_hash, is_active, is_superuser)
    VALUES ('admin', 'admin@health.local', 'System Administrator', '{}', 1, 1)
""".format(hash_password(admin_pw)))
```

In the `downgrade()` function:
```python
op.execute("DELETE FROM users WHERE username = 'admin'")
op.execute("DELETE FROM role_permissions")
op.execute("DELETE FROM user_roles")
op.execute("DELETE FROM permissions")
op.execute("DELETE FROM roles")
op.execute("DELETE FROM refresh_tokens")
op.drop_table("refresh_tokens")
op.drop_table("role_permissions")
op.drop_table("user_roles")
op.drop_table("users")
op.drop_table("roles")
op.drop_table("permissions")
```

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`
Expected: Tables created, seed data inserted.

- [ ] **Step 4: Verify seed data**

```python
# Quick check in python shell or test:
from app.database import SessionLocal
db = SessionLocal()
from app.models import User, Role, Permission
assert db.query(User).filter_by(username="admin").count() == 1
assert db.query(Role).count() == 4
assert db.query(Permission).count() == 16
db.close()
```

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat(auth): add alembic migration for auth tables with seed data"
```

---

### Task 4: Auth API — Login, Refresh, Logout, Me

**Files:**
- Create: `app/api/auth.py`
- Modify: `app/main.py` (add router)
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `create_access_token`, `create_refresh_token`, `decode_token` from `app.core.security`
- Consumes: `User`, `RefreshToken` from `app.models`
- Produces: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_auth.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _seed_user(db_session, username="testuser", password="test123", role_name="viewer"):
    """Seed a test user into the DB. Returns user object."""
    p = Permission(codename="dashboard.read")
    role = Role(name=role_name, permissions=[p])
    user = User(
        username=username, email=f"{username}@test.com",
        full_name=username.title(),
        password_hash=hash_password(password),
        roles=[role],
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_success(db_session):
    _seed_user(db_session)
    resp = client.post("/auth/login", json={"username": "testuser", "password": "test123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "testuser"


def test_login_wrong_password(db_session):
    _seed_user(db_session)
    resp = client.post("/auth/login", json={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 401


def test_login_nonexistent_user():
    resp = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_login_inactive_user(db_session):
    user = _seed_user(db_session)
    user.is_active = False
    db_session.commit()
    resp = client.post("/auth/login", json={"username": "testuser", "password": "test123"})
    assert resp.status_code == 401


def test_refresh_token(db_session):
    _seed_user(db_session)
    login_resp = client.post("/auth/login", json={"username": "testuser", "password": "test123"})
    refresh = login_resp.json()["refresh_token"]
    resp = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_refresh_revoked_token(db_session):
    _seed_user(db_session)
    login_resp = client.post("/auth/login", json={"username": "testuser", "password": "test123"})
    refresh = login_resp.json()["refresh_token"]
    client.post("/auth/logout", json={"refresh_token": refresh})
    resp = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


def test_me_endpoint(db_session):
    _seed_user(db_session)
    login_resp = client.post("/auth/login", json={"username": "testuser", "password": "test123"})
    token = login_resp.json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


def test_me_unauthenticated():
    resp = client.get("/auth/me")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -k "login_success or wrong_password or nonexistent or inactive or refresh or me" -v`
Expected: FAIL (routes don't exist yet)

- [ ] **Step 3: Create app/api/auth.py**

```python
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
    refresh_token_str, jti, expires_at = create_refresh_token(user.id)

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
```

- [ ] **Step 4: Register router in app/main.py**

Add `from app.api import auth` near the other imports, and `app.include_router(auth.router)` in the router list.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_auth.py -v`
Expected: 17 passed

- [ ] **Step 6: Commit**

```bash
git add app/api/auth.py app/main.py tests/test_auth.py
git commit -m "feat(auth): add login, refresh, logout, me endpoints"
```

---

### Task 5: Protect Existing API Routers

**Files:**
- Modify: All `app/api/*.py` router files (add dependency)
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `require_permission` from `app.core.deps`
- Produces: All existing routers require auth by default

- [ ] **Step 1: Write a test that unauthenticated access returns 401**

Append to `tests/test_auth.py`:

```python
def test_unauthenticated_api_returns_401():
    """Any existing API endpoint should return 401 without a token."""
    resp = client.get("/smart/months")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_unauthenticated_api_returns_401 -v`
Expected: FAIL (endpoint currently returns 200)

- [ ] **Step 3: Add auth dependency to all routers**

In each `app/api/*.py` file, add the dependency to the router:

```python
# At the top, add import:
from app.core.deps import require_permission

# Change router definition to include default dependency:
router = APIRouter(
    prefix="/...",
    tags=["..."],
    dependencies=[Depends(require_permission("dashboard.read"))],  # adjust per router
)
```

Permission mapping per router:
| Router file | Permission |
|-------------|-----------|
| `dashboard.py` | `dashboard.read` |
| `analysis.py` | `analysis.read` |
| `hospitals.py` | `hospitals.read` |
| `upload.py` | (no default — individual routes get `data.upload`) |
| `smart_analytics.py` | `smart_analytics.read` |
| `comparative.py` | `smart_analytics.read` |
| `export.py` | `data.export` |
| `rules.py` | `rules.read` |
| `clinical.py` | `clinical.read` |
| `alerts.py` | `alerts.read` |
| `root_cause.py` | `root_cause.read` |
| `audit.py` | `audit.read` |
| `config_api.py` | `settings.read` |
| `confidence.py` | `analysis.read` |
| `regional.py` | `smart_analytics.read` |
| `indicator_config.py` | `settings.read` |
| `tree_config.py` | `settings.read` |
| `file_ops.py` | `data.upload` |
| `governorates.py` | `analysis.read` |
| `hospital_types.py` | `analysis.read` |
| `facility_ownerships.py` | `analysis.read` |
| `facility_types.py` | `analysis.read` |

For `upload.py`, remove the default dependency and add per-route:
```python
@router.post("/upload")
def upload_data(..., user=Depends(require_permission("data.upload"))):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py::test_unauthenticated_api_returns_401 -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: All existing tests pass (they use in-memory SQLite which bypasses JWT).

- [ ] **Step 6: Commit**

```bash
git add app/api/
git commit -m "feat(auth): protect all API routers with auth dependency"
```

---

### Task 6: Frontend — Login Page

**Files:**
- Create: `static/js/auth.js`
- Modify: `static/index.html`
- Modify: `static/css/styles.css`

**Interfaces:**
- Consumes: `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
- Produces: Bilingual login page, token storage in localStorage

- [ ] **Step 1: Add login page HTML to static/index.html**

Before the main dashboard div, add:

```html
<!-- Login Page (hidden by default) -->
<div id="login-page" style="display:none; min-height:100vh; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#f8fafc,#eef2ff);">
  <div id="login-card" style="background:white;border-radius:14px;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.12);width:380px;max-width:94%;">
    <div style="text-align:center;margin-bottom:1.5rem;">
      <h1 style="color:#1a237e;font-size:1.3rem;margin:0;">🛡️ <span data-i18n="Smart Analytics">التحليل الذكي</span></h1>
      <p style="color:#6b7280;font-size:0.82rem;margin:0.4rem 0 0;" data-i18n="Login to access the dashboard">سجّل الدخول للوصول إلى لوحة التحكم</p>
    </div>
    <form id="login-form" onsubmit="return handleLogin(event)">
      <div style="margin-bottom:1rem;">
        <label style="font-weight:600;font-size:0.82rem;display:block;margin-bottom:0.25rem;color:#4338ca;" data-i18n="Username">اسم المستخدم</label>
        <input id="login-username" type="text" required style="width:100%;padding:0.5rem;border:1px solid #c7d2fe;border-radius:8px;font-size:0.9rem;box-sizing:border-box;" autocomplete="username">
      </div>
      <div style="margin-bottom:1rem;">
        <label style="font-weight:600;font-size:0.82rem;display:block;margin-bottom:0.25rem;color:#4338ca;" data-i18n="Password">كلمة المرور</label>
        <input id="login-password" type="password" required style="width:100%;padding:0.5rem;border:1px solid #c7d2fe;border-radius:8px;font-size:0.9rem;box-sizing:border-box;" autocomplete="current-password">
      </div>
      <div id="login-error" style="display:none;color:#dc2626;font-size:0.82rem;margin-bottom:0.8rem;"></div>
      <button type="submit" id="login-submit" style="width:100%;padding:0.6rem;background:linear-gradient(135deg,#1a237e,#312e81);color:white;border:none;border-radius:8px;font-size:0.95rem;font-weight:600;cursor:pointer;" data-i18n="Login">تسجيل الدخول</button>
    </form>
    <div style="text-align:center;margin-top:1rem;">
      <button id="login-lang-toggle" onclick="toggleLoginLang()" style="background:none;border:1px solid #c7d2fe;border-radius:6px;padding:0.3rem 0.8rem;font-size:0.78rem;color:#4338ca;cursor:pointer;">🇬🇧 English</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Create static/js/auth.js**

```javascript
// auth.js — login page, token management, auth guard.
(function() {
  const API_BASE = document.getElementById('apiBase')?.value || '';

  // ---- Token management ----
  window.getAccessToken = () => localStorage.getItem('access_token');
  window.getRefreshToken = () => localStorage.getItem('refresh_token');

  window.setTokens = (access, refresh) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
  };

  window.clearTokens = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_info');
  };

  window.getUserInfo = () => {
    try { return JSON.parse(localStorage.getItem('user_info')); } catch { return null; }
  };

  window.setUserInfo = (info) => {
    localStorage.setItem('user_info', JSON.stringify(info));
  };

  window.hasPermission = (perm) => {
    const user = getUserInfo();
    if (!user) return false;
    if (user.permissions && user.permissions.includes('*.*')) return true;
    return user.permissions && user.permissions.includes(perm);
  };

  // ---- Auth fetch wrapper ----
  window.authFetch = async function(url, options = {}) {
    options.headers = options.headers || {};
    const token = getAccessToken();
    if (token) options.headers['Authorization'] = `Bearer ${token}`;
    let resp = await fetch(url, options);
    if (resp.status === 401) {
      // Try refresh
      const refreshed = await tryRefresh();
      if (refreshed) {
        options.headers['Authorization'] = `Bearer ${getAccessToken()}`;
        resp = await fetch(url, options);
      } else {
        showLoginPage();
        throw new Error('Session expired');
      }
    }
    return resp;
  };

  async function tryRefresh() {
    const refresh = getRefreshToken();
    if (!refresh) return false;
    try {
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setTokens(data.access_token, data.refresh_token);
        return true;
      }
    } catch {}
    clearTokens();
    return false;
  }

  // ---- Login page ----
  window.showLoginPage = function() {
    document.getElementById('login-page').style.display = 'flex';
    const dashboard = document.querySelector('.dashboard-container') || document.querySelector('[class*="dashboard"]');
    if (dashboard) dashboard.style.display = 'none';
  };

  window.hideLoginPage = function() {
    document.getElementById('login-page').style.display = 'none';
    const dashboard = document.querySelector('.dashboard-container') || document.querySelector('[class*="dashboard"]');
    if (dashboard) dashboard.style.display = '';
  };

  window.handleLogin = async function(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');
    const submitBtn = document.getElementById('login-submit');
    errorEl.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = '...';
    try {
      const resp = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        errorEl.textContent = data.detail || 'Login failed';
        errorEl.style.display = 'block';
        return false;
      }
      setTokens(data.access_token, data.refresh_token);
      setUserInfo(data.user);
      hideLoginPage();
      // Reload dashboard data
      if (typeof window.initDashboard === 'function') window.initDashboard();
    } catch (err) {
      errorEl.textContent = 'Network error';
      errorEl.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = document.documentElement.dir === 'rtl' ? 'تسجيل الدخول' : 'Login';
    }
    return false;
  };

  window.handleLogout = async function() {
    const refresh = getRefreshToken();
    if (refresh) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {}
    }
    clearTokens();
    showLoginPage();
  };

  window.toggleLoginLang = function() {
    const html = document.documentElement;
    const btn = document.getElementById('login-lang-toggle');
    if (html.dir === 'rtl') {
      html.dir = 'ltr'; html.lang = 'en';
      btn.textContent = '🇸🇦 العربية';
    } else {
      html.dir = 'rtl'; html.lang = 'ar';
      btn.textContent = '🇬🇧 English';
    }
  };

  // ---- Auth guard (run on page load) ----
  window.checkAuth = async function() {
    const token = getAccessToken();
    if (!token) { showLoginPage(); return false; }
    try {
      const resp = await fetch(`${API_BASE}/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (resp.ok) {
        const user = await resp.json();
        setUserInfo(user);
        hideLoginPage();
        return true;
      }
    } catch {}
    // Token invalid — try refresh
    const refreshed = await tryRefresh();
    if (refreshed) {
      const meResp = await fetch(`${API_BASE}/auth/me`, {
        headers: { 'Authorization': `Bearer ${getAccessToken()}` },
      });
      if (meResp.ok) {
        setUserInfo(await meResp.json());
        hideLoginPage();
        return true;
      }
    }
    showLoginPage();
    return false;
  };
})();
```

- [ ] **Step 3: Add login page CSS to static/css/styles.css**

```css
/* Auth / Login Page */
#login-page { background: linear-gradient(135deg, #f8fafc, #eef2ff); }
#login-card { transition: box-shadow 0.2s; }
#login-card:focus-within { box-shadow: 0 12px 40px rgba(0,0,0,0.18); }
#login-form input:focus { outline: none; border-color: #4338ca; box-shadow: 0 0 0 2px rgba(67,56,202,0.15); }
#login-submit:disabled { opacity: 0.6; cursor: not-allowed; }
```

- [ ] **Step 4: Add auth.js script to static/index.html**

Add before the closing `</body>` tag:
```html
<script src="/static/js/auth.js"></script>
```

- [ ] **Step 5: Verify login page renders**

Open the app in browser. If no token in localStorage, the login page should appear.

- [ ] **Step 6: Commit**

```bash
git add static/js/auth.js static/index.html static/css/styles.css
git commit -m "feat(auth): add bilingual login page and token management"
```

---

### Task 7: Frontend — Auth Guard Integration

**Files:**
- Modify: `static/index.html` (add auth check on load)
- Modify: `static/js/main.js` (wrap init in auth check)

**Interfaces:**
- Consumes: `checkAuth()` from auth.js
- Produces: Dashboard only loads after authentication

- [ ] **Step 1: Add auth guard call to static/index.html**

In the main script section, before `initDashboard()` or equivalent:

```javascript
// Auth guard — check login before loading dashboard
(async function() {
  const authed = await checkAuth();
  if (authed) {
    // Proceed with normal dashboard initialization
    initDashboard();
  }
  // If not authed, showLoginPage() was already called by checkAuth()
})();
```

- [ ] **Step 2: Add logout button to header**

In the header/nav area of `static/index.html`, add:

```html
<button id="logout-btn" onclick="handleLogout()" style="display:none;background:none;border:1px solid #dc2626;color:#dc2626;border-radius:6px;padding:0.3rem 0.7rem;font-size:0.78rem;cursor:pointer;" data-i18n="Logout">تسجيل الخروج</button>
```

Show it after successful login:
```javascript
document.getElementById('logout-btn').style.display = '';
```

- [ ] **Step 3: Verify auth guard works**

1. Open app without token → login page shown
2. Login → dashboard loads
3. Refresh page → stays logged in
4. Click logout → login page shown

- [ ] **Step 4: Commit**

```bash
git add static/index.html
git commit -m "feat(auth): integrate auth guard into dashboard load flow"
```

---

### Task 8: Frontend — Conditional UI Based on Permissions

**Files:**
- Modify: `static/js/main.js` or `static/js/auth.js`
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `hasPermission(codename)` from auth.js
- Produces: Tabs/actions hidden based on user permissions

- [ ] **Step 1: Add permission-based UI hiding function**

Add to `static/js/auth.js`:

```javascript
window.applyPermissions = function() {
  const user = getUserInfo();
  if (!user) return;
  // Hide tabs user can't access
  const tabMap = {
    'tab-dashboard': 'dashboard.read',
    'tab-analysis': 'analysis.read',
    'tab-quality': 'quality.read',
    'tab-outliers': 'outliers.read',
    'tab-clinical': 'clinical.read',
    'tab-alerts': 'alerts.read',
    'tab-hospitals': 'hospitals.read',
    'tab-smart-analytics': 'smart_analytics.read',
    'tab-rules': 'rules.read',
    'tab-root-cause': 'root_cause.read',
    'tab-audit': 'audit.read',
    'tab-settings': 'settings.read',
  };
  Object.entries(tabMap).forEach(([tabId, perm]) => {
    const el = document.getElementById(tabId);
    if (el && !hasPermission(perm)) el.style.display = 'none';
  });
  // Hide action buttons
  document.querySelectorAll('[data-requires]').forEach(el => {
    if (!hasPermission(el.dataset.requires)) el.style.display = 'none';
  });
  // Show logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.style.display = '';
};
```

- [ ] **Step 2: Call applyPermissions after login**

In the `handleLogin` success block and in `checkAuth` success block:
```javascript
applyPermissions();
```

- [ ] **Step 3: Add data-requires attributes to action buttons in HTML**

Example:
```html
<button data-requires="data.upload" id="upload-btn">Upload</button>
<button data-requires="data.export" id="export-btn">Export</button>
<button data-requires="smart_analytics.generate_report" id="report-btn">Generate Report</button>
```

- [ ] **Step 4: Commit**

```bash
git add static/js/auth.js static/index.html
git commit -m "feat(auth): hide tabs/actions based on user permissions"
```

---

### Task 9: Admin Panel — User Management API

**Files:**
- Create: `app/api/admin_users.py`
- Modify: `app/main.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `require_permission("system.manage_users")`, User/Role models
- Produces: `GET/POST /admin/users`, `GET/PUT/DELETE /admin/users/{id}`, `GET/POST /admin/roles`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_auth.py`:

```python
def _get_admin_token():
    """Login as superadmin and return token."""
    # Seed superadmin directly
    from app.database import SessionLocal
    db = SessionLocal()
    from app.models import User
    admin = db.query(User).filter_by(username="admin").first()
    if admin:
        token = create_access_token(admin.id, ["superadmin"], ["*.*"])
        db.close()
        return token
    db.close()
    return None


def test_admin_list_users():
    token = _get_admin_token()
    if not token:
        pytest.skip("No admin user seeded")
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_admin_create_user():
    token = _get_admin_token()
    if not token:
        pytest.skip("No admin user seeded")
    resp = client.post("/admin/users", headers={"Authorization": f"Bearer {token}"}, json={
        "username": "newdoc", "email": "doc@test.com", "full_name": "New Doctor",
        "password": "doc123", "role_ids": [],
    })
    assert resp.status_code == 200


def test_admin_unauthorized():
    """Viewer cannot access admin endpoints."""
    resp = client.get("/admin/users")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py::test_admin_list_users -v`
Expected: FAIL (route doesn't exist)

- [ ] **Step 3: Create app/api/admin_users.py**

```python
"""Admin endpoints for user and role management."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import require_permission
from app.core.security import hash_password
from app.models import User, Role, Permission

router = APIRouter(prefix="/admin", tags=["Admin"])

admin_dep = Depends(require_permission("system.manage_users"))


class CreateUserRequest(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role_ids: list[int] = []


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[list[int]] = None
    password: Optional[str] = None


@router.get("/users")
def list_users(db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    users = db.query(User).all()
    return [
        {
            "id": u.id, "username": u.username, "email": u.email,
            "full_name": u.full_name, "is_active": u.is_active,
            "is_superuser": u.is_superuser,
            "roles": [{"id": r.id, "name": r.name} for r in u.roles],
        }
        for u in users
    ]


@router.post("/users")
def create_user(req: CreateUserRequest, db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    roles = db.query(Role).filter(Role.id.in_(req.role_ids)).all() if req.role_ids else []
    user = User(
        username=req.username, email=req.email, full_name=req.full_name,
        password_hash=hash_password(req.password), roles=roles,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username}


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.email is not None: user.email = req.email
    if req.full_name is not None: user.full_name = req.full_name
    if req.is_active is not None: user.is_active = req.is_active
    if req.password is not None: user.password_hash = hash_password(req.password)
    if req.role_ids is not None: user.roles = db.query(Role).filter(Role.id.in_(req.role_ids)).all()
    db.commit()
    return {"success": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser:
        raise HTTPException(status_code=400, detail="Cannot delete superuser")
    db.delete(user)
    db.commit()
    return {"success": True}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    roles = db.query(Role).all()
    return [
        {
            "id": r.id, "name": r.name, "description": r.description,
            "is_system": r.is_system,
            "permissions": [{"id": p.id, "codename": p.codename} for p in r.permissions],
        }
        for r in roles
    ]


@router.get("/permissions")
def list_permissions(db: Session = Depends(get_db), _user=Depends(require_permission("system.manage_users"))):
    return [{"id": p.id, "codename": p.codename, "description": p.description} for p in db.query(Permission).all()]
```

- [ ] **Step 4: Register router in app/main.py**

```python
from app.api import admin_users
app.include_router(admin_users.router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_auth.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/api/admin_users.py app/main.py tests/test_auth.py
git commit -m "feat(auth): add admin user/role management API"
```

---

### Task 10: Admin Panel — Frontend UI

**Files:**
- Create: `static/tabs/admin-users.html`
- Modify: `static/index.html` (add tab)
- Modify: `static/js/main.js` (wire tab)

**Interfaces:**
- Consumes: `GET/POST/PUT/DELETE /admin/users`, `GET /admin/roles`, `hasPermission("system.manage_users")`
- Produces: User management tab visible only to admins

- [ ] **Step 1: Create static/tabs/admin-users.html**

```html
<div style="padding:1rem;">
  <h3 style="color:#1a237e;margin:0 0 1rem;">👤 <span data-i18n="User Management">إدارة المستخدمين</span></h3>
  <button id="admin-create-user-btn" class="btn btn-sm" style="margin-bottom:1rem;" data-i18n="Create User">+ إنشاء مستخدم</button>
  <div id="admin-user-table" class="smart-table-wrap"></div>

  <!-- Create/Edit User Modal -->
  <div id="admin-user-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;justify-content:center;align-items:center;">
    <div style="background:white;border-radius:14px;max-width:500px;width:94%;padding:1.5rem;">
      <h3 id="admin-modal-title" style="margin:0 0 1rem;color:#1a237e;">Create User</h3>
      <input id="admin-uid" type="hidden">
      <div style="margin-bottom:0.8rem;">
        <label style="font-weight:600;font-size:0.82rem;">Username</label>
        <input id="admin-uusername" type="text" style="width:100%;padding:0.4rem;border:1px solid #c7d2fe;border-radius:6px;">
      </div>
      <div style="margin-bottom:0.8rem;">
        <label style="font-weight:600;font-size:0.82rem;">Email</label>
        <input id="admin-uemail" type="email" style="width:100%;padding:0.4rem;border:1px solid #c7d2fe;border-radius:6px;">
      </div>
      <div style="margin-bottom:0.8rem;">
        <label style="font-weight:600;font-size:0.82rem;">Full Name</label>
        <input id="admin-ufullname" type="text" style="width:100%;padding:0.4rem;border:1px solid #c7d2fe;border-radius:6px;">
      </div>
      <div style="margin-bottom:0.8rem;">
        <label style="font-weight:600;font-size:0.82rem;">Password</label>
        <input id="admin-upassword" type="password" style="width:100%;padding:0.4rem;border:1px solid #c7d2fe;border-radius:6px;">
      </div>
      <div style="margin-bottom:1rem;">
        <label style="font-weight:600;font-size:0.82rem;">Roles</label>
        <div id="admin-uroles" style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.3rem;"></div>
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button onclick="document.getElementById('admin-user-modal').style.display='none'" class="btn btn-sm btn-outline">Cancel</button>
        <button onclick="saveAdminUser()" class="btn btn-sm">Save</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Create static/js/admin-users.js**

```javascript
// admin-users.js — admin panel for user management.
(function() {
  let _roles = [];

  window.loadAdminUsers = async function() {
    const resp = await authFetch('/admin/users');
    if (!resp.ok) return;
    const users = await resp.json();
    const rolesResp = await authFetch('/admin/roles');
    if (rolesResp.ok) _roles = await rolesResp.json();

    const container = document.getElementById('admin-user-table');
    if (!container) return;
    container.innerHTML = `<table><thead><tr>
      <th>#</th><th>Username</th><th>Full Name</th><th>Email</th><th>Roles</th><th>Status</th><th></th>
    </tr></thead><tbody>` + users.map((u, i) => `<tr>
      <td>${i + 1}</td>
      <td style="font-weight:600;">${u.username}</td>
      <td>${u.full_name}</td>
      <td>${u.email}</td>
      <td>${u.roles.map(r => `<span class="smart-badge smart-badge-normal">${r.name}</span>`).join(' ')}</td>
      <td>${u.is_active ? '<span class="smart-badge smart-badge-normal">Active</span>' : '<span class="smart-badge smart-badge-critical">Inactive</span>'}</td>
      <td><button class="btn btn-sm btn-outline" onclick="editAdminUser(${u.id})">Edit</button>
          ${u.is_superuser ? '' : ` <button class="btn btn-sm" style="color:#dc2626;" onclick="deleteAdminUser(${u.id})">Delete</button>`}</td>
    </tr>`).join('') + `</tbody></table>`;

    document.getElementById('admin-create-user-btn').onclick = () => openAdminUserModal();
  };

  window.openAdminUserModal = function(user) {
    document.getElementById('admin-uid').value = user ? user.id : '';
    document.getElementById('admin-uusername').value = user ? user.username : '';
    document.getElementById('admin-uemail').value = user ? user.email : '';
    document.getElementById('admin-ufullname').value = user ? user.full_name : '';
    document.getElementById('admin-upassword').value = '';
    document.getElementById('admin-uusername').disabled = !!user;
    document.getElementById('admin-modal-title').textContent = user ? 'Edit User' : 'Create User';
    const rolesDiv = document.getElementById('admin-uroles');
    rolesDiv.innerHTML = _roles.map(r => `<label style="display:flex;align-items:center;gap:0.3rem;font-size:0.82rem;">
      <input type="checkbox" value="${r.id}" ${user && user.roles.some(ur => ur.id === r.id) ? 'checked' : ''}> ${r.name}
    </label>`).join('');
    document.getElementById('admin-user-modal').style.display = 'flex';
  };

  window.editAdminUser = async function(userId) {
    const resp = await authFetch('/admin/users');
    const users = await resp.json();
    const user = users.find(u => u.id === userId);
    if (user) openAdminUserModal(user);
  };

  window.saveAdminUser = async function() {
    const id = document.getElementById('admin-uid').value;
    const roleIds = [...document.getElementById('admin-uroles').querySelectorAll('input:checked')].map(cb => parseInt(cb.value));
    const body = {
      username: document.getElementById('admin-uusername').value,
      email: document.getElementById('admin-uemail').value,
      full_name: document.getElementById('admin-ufullname').value,
      role_ids: roleIds,
    };
    const pw = document.getElementById('admin-upassword').value;
    if (pw) body.password = pw;

    if (id) {
      await authFetch(`/admin/users/${id}`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    } else {
      body.password = pw || 'changeme123';
      await authFetch('/admin/users', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    }
    document.getElementById('admin-user-modal').style.display = 'none';
    loadAdminUsers();
  };

  window.deleteAdminUser = async function(userId) {
    if (!confirm('Delete this user?')) return;
    await authFetch(`/admin/users/${userId}`, { method: 'DELETE' });
    loadAdminUsers();
  };
})();
```

- [ ] **Step 3: Add admin tab to static/index.html**

```html
<li id="tab-admin-users" class="nav-item" style="display:none;">
  <a class="nav-link" data-tab="admin-users" href="#">👤 <span data-i18n="Users">المستخدمين</span></a>
</li>
```

Add `<script src="/static/js/admin-users.js"></script>` before `</body>`.

- [ ] **Step 4: Wire tab switching in main.js**

When the admin-users tab is shown, call `loadAdminUsers()`.

- [ ] **Step 5: Show admin tab only for users with system.manage_users**

In `applyPermissions()`:
```javascript
if (hasPermission('system.manage_users')) {
  const adminTab = document.getElementById('tab-admin-users');
  if (adminTab) adminTab.style.display = '';
}
```

- [ ] **Step 6: Commit**

```bash
git add static/tabs/admin-users.html static/js/admin-users.js static/index.html
git commit -m "feat(auth): add admin panel UI for user management"
```

---

### Task 11: Test Auth Integration End-to-End

**Files:**
- Modify: `tests/test_auth.py`

**Interfaces:**
- Tests the full flow: seed users → login → access protected endpoint → logout

- [ ] **Step 1: Add integration tests**

```python
def test_full_auth_flow(db_session):
    """End-to-end: login → access protected endpoint → logout."""
    # Seed a doctor user
    p1 = Permission(codename="dashboard.read")
    p2 = Permission(codename="smart_analytics.read")
    role = Role(name="doctor", permissions=[p1, p2])
    user = User(
        username="drtest", email="dr@test.com", full_name="Dr Test",
        password_hash=hash_password("docpass"), roles=[role],
    )
    db_session.add(user)
    db_session.commit()

    # Login
    login_resp = client.post("/auth/login", json={"username": "drtest", "password": "docpass"})
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Access protected endpoint
    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "drtest"

    # Logout
    logout_resp = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_resp.status_code == 200

    # Refresh should fail after logout
    refresh_resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_resp.status_code == 401


def test_permission_enforcement(db_session):
    """Viewer cannot access upload endpoint."""
    p = Permission(codename="dashboard.read")
    role = Role(name="viewer", permissions=[p])
    user = User(
        username="viewer1", email="v@test.com", full_name="Viewer",
        password_hash=hash_password("vpass"), roles=[role],
    )
    db_session.add(user)
    db_session.commit()

    login_resp = client.post("/auth/login", json={"username": "viewer1", "password": "vpass"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Should fail — viewer doesn't have data.upload
    resp = client.post("/upload/upload", headers=headers)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run all auth tests**

Run: `pytest tests/test_auth.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "test(auth): add end-to-end auth flow and permission enforcement tests"
```

---

### Task 12: Final Verification & Documentation

**Files:**
- Modify: `docs/PROJECT_DOCUMENTATION.md` (update auth section)
- Modify: `.env.example` (verify complete)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -q`
Expected: All tests pass

- [ ] **Step 2: Verify all JS files syntax-check**

Run: `node --check static/js/auth.js && node --check static/js/admin-users.js`

- [ ] **Step 3: Update PROJECT_DOCUMENTATION.md**

Update section 12.5 (Future Recommendations) to reflect that auth is now implemented.

- [ ] **Step 4: Commit**

```bash
git add docs/PROJECT_DOCUMENTATION.md
git commit -m "docs: update project documentation with auth implementation"
```

---

## Summary

| Task | Description | Est. Time |
|------|------------|-----------|
| 1 | Auth dependencies & config | 20 min |
| 2 | Auth models | 15 min |
| 3 | Alembic migration + seeding | 15 min |
| 4 | Auth API (login/refresh/logout/me) | 30 min |
| 5 | Protect existing routers | 20 min |
| 6 | Frontend login page | 25 min |
| 7 | Auth guard integration | 15 min |
| 8 | Permission-based UI | 15 min |
| 9 | Admin user management API | 20 min |
| 10 | Admin panel frontend | 25 min |
| 11 | Integration tests | 15 min |
| 12 | Final verification & docs | 10 min |
| **Total** | | **~4 hours** |
