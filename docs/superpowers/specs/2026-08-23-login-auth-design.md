# Login Flow & System Permissions — Design Spec

**Date:** 2026-08-23
**Status:** Approved — ready for implementation planning
**Scope:** Full authentication + RBAC + admin panel + bilingual login page

---

## 1. Overview

The application currently has **zero authentication**. Every API endpoint and the
entire dashboard are publicly accessible. This spec adds:

- JWT-based login with refresh tokens
- Custom roles + granular permissions (~15 codenames)
- Admin-only user creation (no public signup)
- Bilingual (Arabic/English) login page
- Admin panel for user/role management
- API protection via FastAPI dependency injection

## 2. Authentication Flow

### 2.1 JWT Tokens

| Token | Lifetime | Storage | Contains |
|-------|----------|---------|----------|
| Access | 15 min | `localStorage` | `user_id`, `username`, `roles[]`, `permissions[]` |
| Refresh | 7 days | DB (`refresh_tokens`) + `httpOnly` cookie | `user_id`, `jti` (revocable) |

### 2.2 Login Flow

```
POST /auth/login  { username, password }
  → validate credentials (bcrypt)
  → generate access + refresh tokens
  → return { access_token, refresh_token, user: { id, username, roles, permissions } }
```

### 2.3 Token Refresh

```
POST /auth/refresh  { refresh_token }
  → validate refresh token (not expired, not revoked)
  → rotate: revoke old, issue new access + refresh pair
  → return { access_token, refresh_token }
```

### 2.4 Logout

```
POST /auth/logout  { refresh_token }
  → revoke refresh token in DB
  → return { success: true }
```

### 2.5 Current User

```
GET /auth/me  (Authorization: Bearer <access_token>)
  → return { id, username, email, full_name, roles, permissions }
```

### 2.6 Password Hashing

- Algorithm: bcrypt via `passlib`
- Rounds: 12
- Password reset: admin-only (no self-service reset in v1)

## 3. Data Models

### 3.1 Tables (Alembic migration)

```sql
users (
  id            SERIAL PRIMARY KEY,
  username      VARCHAR(50) UNIQUE NOT NULL,
  email         VARCHAR(120) UNIQUE NOT NULL,
  full_name     VARCHAR(120) NOT NULL,
  password_hash VARCHAR(200) NOT NULL,
  is_active     BOOLEAN DEFAULT TRUE,
  is_superuser  BOOLEAN DEFAULT FALSE,
  created_at    TIMESTAMP DEFAULT NOW(),
  updated_at    TIMESTAMP DEFAULT NOW()
);

roles (
  id          SERIAL PRIMARY KEY,
  name        VARCHAR(50) UNIQUE NOT NULL,
  description VARCHAR(200),
  is_system   BOOLEAN DEFAULT FALSE  -- protected from deletion
);

permissions (
  id          SERIAL PRIMARY KEY,
  codename    VARCHAR(80) UNIQUE NOT NULL,  -- e.g. "dashboard.read"
  description VARCHAR(200)
);

user_roles (
  user_id  INT REFERENCES users(id) ON DELETE CASCADE,
  role_id  INT REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

role_permissions (
  role_id       INT REFERENCES roles(id) ON DELETE CASCADE,
  permission_id INT REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

refresh_tokens (
  id         SERIAL PRIMARY KEY,
  user_id    INT REFERENCES users(id) ON DELETE CASCADE,
  token_jti  VARCHAR(64) UNIQUE NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  revoked    BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 3.2 SQLAlchemy Models

Add to `app/models.py`:
- `User(Base)` with `password_hash`, `is_active`, `is_superuser`
- `Role(Base)` with `is_system` flag
- `Permission(Base)` with `codename`
- Association tables: `user_roles`, `role_permissions`
- `RefreshToken(Base)` with `token_jti`, `revoked`

## 4. Permissions

### 4.1 Codenames (~15)

**Tab-level (read access):**
- `dashboard.read`
- `analysis.read`
- `quality.read`
- `outliers.read`
- `clinical.read`
- `alerts.read`
- `hospitals.read`
- `smart_analytics.read`
- `rules.read`
- `root_cause.read`
- `audit.read`
- `settings.read`

**Action-level:**
- `data.upload`
- `data.export`
- `smart_analytics.generate_report`
- `system.manage_users`

### 4.2 Default Roles

| Role | Permissions |
|------|------------|
| `superadmin` | All (bypasses checks via `is_superuser`) |
| `admin` | All except `system.manage_users` |
| `doctor` | `dashboard.read`, `analysis.read`, `quality.read`, `smart_analytics.read`, `smart_analytics.generate_report`, `hospitals.read`, `clinical.read`, `alerts.read` |
| `viewer` | All `*.read` permissions (no actions) |

### 4.3 Permission Check Logic

```python
# Dependency injection
def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
    payload = decode_jwt(token)
    user = db.query(User).get(payload["user_id"])
    if not user or not user.is_active:
        raise HTTPException(401)
    return user

def require_permission(codename: str):
    def checker(user = Depends(get_current_user)):
        if user.is_superuser:
            return user
        user_perms = {p.codename for r in user.roles for p in r.permissions}
        if codename not in user_perms:
            raise HTTPException(403, f"Missing permission: {codename}")
        return user
    return checker
```

## 5. Backend Structure

### 5.1 New Files

```
app/
  api/
    auth.py              # /auth/login, /auth/refresh, /auth/logout, /auth/me
    admin_users.py       # /admin/users CRUD, /admin/roles CRUD
  core/
    security.py          # JWT encode/decode, password hashing, token generation
    deps.py              # get_current_user, require_permission dependencies
```

### 5.2 Modified Files

- `app/models.py` — add User, Role, Permission, RefreshToken models
- `app/main.py` — add auth + admin_users routers, protect existing routers
- `app/config.py` — add JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE, REFRESH_TOKEN_EXPIRE
- `.env.example` — add JWT_SECRET, JWT_ALGORITHM=HS256, ACCESS_TOKEN_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=7
- `alembic/versions/` — new migration for auth tables + seed data

### 5.3 Router Protection

Every existing router gets a dependency:

```python
# Before:
router = APIRouter(prefix="/smart", tags=["Smart Analytics"])

# After:
router = APIRouter(
    prefix="/smart",
    tags=["Smart Analytics"],
    dependencies=[Depends(require_permission("smart_analytics.read"))]
)
```

Action-specific endpoints get per-route protection:

```python
@router.post("/upload")
def upload_data(user = Depends(require_permission("data.upload"))):
    ...
```

### 5.4 Unprotected Routes

- `GET /health` — no auth
- `POST /auth/login` — no auth
- `POST /auth/refresh` — no auth
- `GET /metrics` — no auth (Prometheus)

## 6. Frontend

### 6.1 Login Page

- Centered card: logo, username, password, language toggle, submit button
- Bilingual: Arabic (RTL) default, English (LTR) on toggle
- Error messages displayed bilingually
- Stores tokens in `localStorage` after successful login
- Redirects to dashboard on success

### 6.2 Auth Guard (`static/js/auth.js`)

```javascript
// On page load:
const token = localStorage.getItem('access_token');
if (!token) { showLoginPage(); return; }
// Try refresh if expired
// Attach Authorization header to all fetch calls
// Logout button in header
```

### 6.3 API Calls

All `apiSmartGet` / `apiSmartPost` calls get the auth header:

```javascript
headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
```

### 6.4 Admin Panel (new tab)

- **User list**: table with username, email, roles, status, actions
- **Create user**: form with username, email, full_name, password, role assignment
- **Edit user**: toggle active, change roles, reset password
- **Role viewer**: shows permissions per role
- Only visible to users with `system.manage_users` permission

### 6.5 Conditional UI

Tabs/actions hidden based on user permissions:

```javascript
if (!user.permissions.includes('data.upload')) {
  document.getElementById('upload-section')?.remove();
}
```

## 7. Testing Strategy

### 7.1 Test Fixtures (`tests/conftest.py`)

- `test_user` — user with `viewer` role
- `test_doctor` — user with `doctor` role
- `test_admin` — user with `admin` role
- `test_superadmin` — user with `superadmin` role
- `auth_headers(user)` — returns `{"Authorization": "Bearer <token>"}` for test requests

### 7.2 Test Cases

| Category | Tests |
|----------|-------|
| Auth flow | login success, login wrong password, login inactive user, refresh token, refresh revoked token, logout, /auth/me |
| Permissions | viewer cannot upload, doctor can generate report, admin cannot manage users, superadmin bypasses all |
| Role management | create role, assign role, remove role, delete protected role fails |
| User management | create user, deactivate user, delete user, password hashing |
| API protection | unauthenticated returns 401, wrong permission returns 403 |

## 8. Migration & Seeding

On first Alembic migration:
1. Create tables
2. Seed 4 default roles (superadmin, admin, doctor, viewer)
3. Seed all 16 permissions
4. Assign permissions to each role
5. Create default superadmin user (username: `admin`, password: from env var `ADMIN_PASSWORD` or default `admin123`)

## 9. Configuration

New environment variables:

```
JWT_SECRET=<random-64-char-hex>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
ADMIN_PASSWORD=admin123  # changed on first login
```

## 10. Security Considerations

- Passwords hashed with bcrypt (12 rounds)
- Refresh tokens stored with `httpOnly` cookie + DB for revocation
- Token rotation on refresh (old token revoked)
- `is_superuser` bypasses permission checks but NOT authentication
- Rate limiting on `/auth/login` (5 attempts per minute per IP)
- No password reset in v1 (admin-only)
- CORS already has `allow_credentials=True` — works with JWT cookies
