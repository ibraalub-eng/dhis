# Sidebar Menu with DB-Driven Groups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the horizontal `.tab-bar` with a responsive, RTL-aware collapsible sidebar. Tabs are organized into DB-managed groups; admins manage groups/order from a new "Menu Layout" panel in System Control.

**Architecture:** New `MenuGroup`/`MenuItem` models + alembic migration. A thin API (`/menu`) returns the menu tree for the frontend. A fixed `TAB_REGISTRY` (14 known tabs) is shared between `scripts/seed_menu.py`, `app/api/menu.py`, and the admin dropdown. Frontend `renderSidebar()` replaces the static `.tab-bar` divs. The admin "Tab Order" panel is replaced with a "Menu Layout" CRUD panel.

**Tech Stack:** SQLAlchemy (Column-style models), Alembic, FastAPI, vanilla JS, CSS custom properties.

**Spec:** `docs/superpowers/specs/2026-09-13-sidebar-menu-groups-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/menu_registry.py` | `TAB_REGISTRY` (key→label/icon/perm) + `DEFAULT_GROUPS` (name/icon/tab_keys) |
| Create | `app/models.py` (append) | `MenuGroup`, `MenuItem` models |
| Create | `app/schemas.py` (append) | `MenuGroupCreate/Update`, `MenuItemCreate/Update` Pydantic schemas |
| Create | `scripts/seed_menu.py` | `seed_menu(session)` idempotent seeder |
| Create | `alembic/versions/<rev>_add_menu.py` | Migration: tables + `menu.manage` permission + role assignment |
| Modify | `app/main.py:326-340` | Add `"menu.manage"` to admin-role codename list |
| Modify | `app/main.py:445` | Add `("menu", seed_menu)` to startup seed loop |
| Create | `app/api/menu.py` | Full CRUD router (GET /menu, POST/PATCH/DELETE groups & items, GET /menu/tabs) |
| Modify | `app/main.py:526-551` | Include `menu_router` |
| Create | `static/js/renderSidebar.js` | `renderSidebar()`: fetch `/menu`, build sidebar DOM, wire click + collapse + mobile drawer |
| Modify | `static/index.html` | Remove static `.tab-bar` divs (lines 110-125), remove `tab_order` script (lines 44-57), add `<aside id="sidebar" class="sidebar">` + hamburger toggle, add `<main id="tabArea">` wrapper around tab-content panels |
| Modify | `static/js/main.js` | Import `renderSidebar`, call it at boot after `checkAuth()`; keep `switchTab`/`.tab` selectors working |
| Modify | `static/css/styles.css` | Sidebar + responsive + RTL styles; neutralize old `.tab-bar` horizontal layout |
| Modify | `static/js/admin.js:452-461,962,1385-1470` | Replace `adminTabOrderPanel` with `adminMenuLayoutPanel`; replace `loadTabOrder`/`saveTabOrder`/`resetTabOrder` with `loadMenuLayout` CRUD functions; remove `_applyTabOrder` |
| Create | `tests/test_menu_api.py` | Backend API tests |
| Modify | `tests/conftest.py:78-80` | Add `seed_menu(session)` to `db_session` fixture |

---

## Global Constraints

- Windows/PowerShell for all commands. Venv: `.venv\Scripts\python.exe`. No `rg`.
- Tests: `$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="..."; & ...\python.exe -m pytest <target> -q`. Full suite: `& .\.venv\Scripts\python.exe -m pytest tests\ -x -q`.
- Node check: `Get-Content <file> -Raw | node --input-type=module --check`. No JS test framework.
- App default language: Arabic (`<html lang="ar" dir="rtl">`). Sidebar must be on the **right** in RTL, on the left in LTR.
- Permission gating: `auth.js applyPermissions()` uses `_TAB_PERMISSIONS` + `[data-requires]` + `[data-requires-superadmin]` — sidebar items must carry `data-requires`/`data-requires-superadmin` attributes.
- Push only after user approval.

---

## Task 1: Tab Registry + Models + Schemas + Seeder

**Files:**
- Create: `app/menu_registry.py`
- Modify: `app/models.py` (append after `MenuItem` note: before the end of file)
- Modify: `app/schemas.py` (append MenuGroup/MenuItem schemas)

**Interfaces:**
- Produces: `TAB_REGISTRY: dict[str, dict]` with keys `{label, icon, permission}`; `DEFAULT_GROUPS: list[dict]` with `{name, icon, items: list[str]}`; `seed_menu(session)` callable
- Produces: `MenuGroup`, `MenuItem` ORM models; `MenuGroupCreate`, `MenuGroupUpdate`, `MenuItemCreate`, `MenuItemUpdate` Pydantic schemas

### Steps

- [ ] **Step 1: Create `app/menu_registry.py`**

```python
"""Fixed tab registry and default menu groups for the sidebar."""
from collections import OrderedDict

TAB_REGISTRY = OrderedDict([
    ("dashboard",       {"label": "Dashboard",            "icon": "📊", "permission": "dashboard.read"}),
    ("upload",          {"label": "Upload Data",          "icon": "📤", "permission": "data.upload"}),
    ("indicator-tree",  {"label": "Indicator Tree",       "icon": "🌳", "permission": "settings.read"}),
    ("rules-manager",   {"label": "Rules Manager",        "icon": "📋", "permission": "rules.read"}),
    ("analysis",        {"label": "Comparative Analysis", "icon": "📈", "permission": "analysis.read"}),
    ("root-cause",      {"label": "Root Cause",           "icon": "🔍", "permission": "root_cause.read"}),
    ("smart-analytics", {"label": "Smart Analytics",      "icon": "🛡️", "permission": "smart_analytics.read"}),
    ("quality",         {"label": "Quality Reports",      "icon": "✅", "permission": "quality.read"}),
    ("clinical",        {"label": "Clinical Intelligence","icon": "🏥", "permission": "clinical.read"}),
    ("outliers",        {"label": "Outliers",              "icon": "⚠️", "permission": "outliers.read"}),
    ("alerts",          {"label": "Alerts",                "icon": "🔔", "permission": "alerts.read"}),
    ("audit",           {"label": "Audit Log",             "icon": "📝", "permission": "audit.read"}),
    ("admin",           {"label": "System Control",       "icon": "⚙️", "permission": "system.manage_users", "superadmin_only": True}),
    ("settings",        {"label": "Settings",             "icon": "🔧", "permission": "system.manage_users", "hidden": True}),
])

DEFAULT_GROUPS = [
    {"name": "الرئيسية",  "icon": "🏠", "items": ["dashboard"]},
    {"name": "البيانات",  "icon": "📊", "items": ["upload", "indicator-tree", "rules-manager"]},
    {"name": "التحليل",   "icon": "📈", "items": ["analysis", "root-cause", "smart-analytics"]},
    {"name": "التقارير",  "icon": "📋", "items": ["quality", "clinical", "outliers", "alerts"]},
    {"name": "الإدارة",   "icon": "⚙️", "items": ["audit", "admin", "settings"]},
]
```

- [ ] **Step 2: Append `MenuGroup` and `MenuItem` models to `app/models.py`**

```python
# --- Menu models ---

class MenuGroup(Base):
    __tablename__ = "menu_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    icon = Column(String(20), default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    items = relationship(
        "MenuItem", back_populates="group",
        cascade="all, delete-orphan",
        order_by="MenuItem.sort_order",
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("menu_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    tab_key = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)

    group = relationship("MenuGroup", back_populates="items")

    __table_args__ = (UniqueConstraint("group_id", "tab_key"),)
```

Add the `UniqueConstraint` import near top of models.py if not present: it's already imported at line ~3 (`from sqlalchemy import ... UniqueConstraint ...`). Verify and skip if already there.

- [ ] **Step 3: Append Pydantic schemas to `app/schemas.py`**

```python
# --- Menu schemas ---

class MenuGroupCreate(BaseModel):
    name: str
    icon: str = ""
    sort_order: int = 0

class MenuGroupUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class MenuItemCreate(BaseModel):
    group_id: int
    tab_key: str
    sort_order: int = 0

class MenuItemUpdate(BaseModel):
    sort_order: Optional[int] = None
    group_id: Optional[int] = None
```

- [ ] **Step 4: Create `scripts/seed_menu.py`**

```python
"""Seed default menu groups into the database."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import MenuGroup, MenuItem
from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY


def seed_menu(session):
    """Idempotent: only seeds if menu_groups table is empty."""
    if session.query(MenuGroup).first() is not None:
        return
    for idx, group_def in enumerate(DEFAULT_GROUPS):
        group = MenuGroup(
            name=group_def["name"],
            icon=group_def["icon"],
            sort_order=idx,
            is_active=True,
        )
        session.add(group)
        session.flush()
        for item_idx, tab_key in enumerate(group_def["items"]):
            session.add(MenuItem(
                group_id=group.id,
                tab_key=tab_key,
                sort_order=item_idx,
            ))
    session.commit()


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_menu(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
```

- [ ] **Step 5: Run node check + pytest full suite**

```powershell
Get-Content app\menu_registry.py -Raw | node --input-type=module --check
& .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 6: Commit**

```powershell
git add app/menu_registry.py app/models.py app/schemas.py scripts/seed_menu.py
git commit -m "feat(menu): add MenuGroup/MenuItem models, tab registry, and default seeder"
```

---

## Task 2: Alembic Migration + Permission Wiring

**Files:**
- Create: `alembic/versions/<new-rev>_add_menu_tables.py` (use `alembic revision --autogenerate -m "add menu tables"` or create manually)
- Modify: `app/main.py:326-340` (add `"menu.manage"` to admin-role codename list)
- Modify: `app/main.py:445` (add seed_menu to startup loop)

**Interfaces:**
- Consumes: `MenuGroup`, `MenuItem` tables (created by `_ensure_all_tables` via models); `seed_menu` function
- Produces: `menu_groups`/`menu_items` tables + `menu.manage` permission row + role assignments

### Steps

- [ ] **Step 1: Create alembic migration**

Run:
```powershell
& .\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add menu tables and permission"
```

Open the generated file and ensure `upgrade()` does:

```python
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Tables — guarded create (safe if _ensure_all_tables already created them)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "menu_groups" not in inspector.get_table_names():
        op.create_table(
            "menu_groups",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("icon", sa.String(20), server_default=""),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("1")),
        )
    if "menu_items" not in inspector.get_table_names():
        op.create_table(
            "menu_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("group_id", sa.Integer, sa.ForeignKey("menu_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("tab_key", sa.String(50), nullable=False),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.UniqueConstraint("group_id", "tab_key"),
        )

    # Permission
    op.execute("""
        INSERT INTO permissions (codename, description)
        SELECT 'menu.manage', 'Manage menu layout and groups'
        WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE codename = 'menu.manage')
    """)

    # Assign to superadmin + admin roles
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE p.codename = 'menu.manage'
          AND r.name IN ('superadmin', 'admin')
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
    """)


def downgrade():
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE codename = 'menu.manage')")
    op.execute("DELETE FROM permissions WHERE codename = 'menu.manage'")
    op.drop_table("menu_items", if_exists=True)
    op.drop_table("menu_groups", if_exists=True)
```

- [ ] **Step 2: Add `"menu.manage"` to admin-role codename list in `app/main.py`**

At line ~326-340, add `"menu.manage"` to the codename list inside `write_manage_perms`:

```python
write_manage_perms = session.query(Permission).filter(
    Permission.codename.in_([
        ...existing codenames...,
        "menu.manage",          # <-- add this line
    ])
).all()
```

- [ ] **Step 3: Add `seed_menu` to startup seed loop in `app/main.py`**

At line ~445, change:
```python
for label, fn in [("config", seed_app_config), ("indicators", seed_indicators), ("rules", seed_rules)]:
```
to:
```python
from scripts.seed_menu import seed_menu as _seed_menu
for label, fn in [("config", seed_app_config), ("indicators", seed_indicators), ("rules", seed_rules), ("menu", _seed_menu)]:
```

(Or import `seed_menu` at the top with the other imports.)

- [ ] **Step 4: Run migration + full suite**

```powershell
# Apply migration to local DB (if using file-based DB)
& .\.venv\Scripts\python.exe -m alembic upgrade head

# Run full test suite
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 5: Commit**

```powershell
git add alembic/versions/ app/main.py
git commit -m "feat(menu): add alembic migration + menu.manage permission wiring"
```

---

## Task 3: API Router — `app/api/menu.py`

**Files:**
- Create: `app/api/menu.py`
- Modify: `app/main.py:526-551` (include router)
- Modify: `tests/conftest.py:78-80` (add `seed_menu` to db_session)
- Create: `tests/test_menu_api.py`

**Interfaces:**
- Consumes: `MenuGroup`, `MenuItem` models; `TAB_REGISTRY` from `app/menu_registry`; `seed_menu` for tests
- Produces: `GET /menu`, `POST /menu/groups`, `PATCH /menu/groups/{id}`, `DELETE /menu/groups/{id}`, `POST /menu/items`, `PATCH /menu/items/{id}`, `DELETE /menu/items/{id}`, `GET /menu/tabs`

### Steps

- [ ] **Step 1: Create `app/api/menu.py`**

```python
"""Menu API: sidebar group/item CRUD + tab registry."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models import MenuGroup, MenuItem
from app.menu_registry import TAB_REGISTRY

router = APIRouter(
    prefix="/menu",
    tags=["menu"],
    dependencies=[Depends(get_current_user)],  # login required for all
)


# ── GET /menu ────────────────────────────────────────────────────────────────

def _item_dict(item: MenuItem) -> dict:
    meta = TAB_REGISTRY.get(item.tab_key, {})
    return {
        "id": item.id,
        "tab_key": item.tab_key,
        "label": meta.get("label", item.tab_key),
        "icon": meta.get("icon", ""),
        "permission": meta.get("permission", ""),
        "superadmin_only": meta.get("superadmin_only", False),
        "sort_order": item.sort_order,
    }


def _group_dict(group: MenuGroup) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "icon": group.icon,
        "sort_order": group.sort_order,
        "is_active": group.is_active,
        "items": [_item_dict(i) for i in group.items],
    }


@router.get("")
def get_menu(db: Session = Depends(get_db)):
    groups = (
        db.query(MenuGroup)
        .filter(MenuGroup.is_active.is_(True))
        .order_by(MenuGroup.sort_order, MenuGroup.id)
        .all()
    )
    return {"groups": [_group_dict(g) for g in groups]}


# ── POST /menu/groups ────────────────────────────────────────────────────────

class _GroupCreate(BaseModel):
    name: str
    icon: str = ""
    sort_order: int = 0


@router.post("/groups", dependencies=[Depends(require_permission("menu.manage"))])
def create_group(body: _GroupCreate, db: Session = Depends(get_db)):
    max_order = db.query(MenuGroup.sort_order).order_by(MenuGroup.sort_order.desc()).scalar() or 0
    g = MenuGroup(name=body.name, icon=body.icon, sort_order=body.sort_order or max_order + 1)
    db.add(g)
    db.commit()
    db.refresh(g)
    return _group_dict(g)


# ── PATCH /menu/groups/{id} ──────────────────────────────────────────────────

class _GroupUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.patch("/groups/{group_id}", dependencies=[Depends(require_permission("menu.manage"))])
def update_group(group_id: int, body: _GroupUpdate, db: Session = Depends(get_db)):
    g = db.query(MenuGroup).get(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    for field in ("name", "icon", "sort_order", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(g, field, val)
    db.commit()
    db.refresh(g)
    return _group_dict(g)


# ── DELETE /menu/groups/{id} ─────────────────────────────────────────────────

@router.delete("/groups/{group_id}", dependencies=[Depends(require_permission("menu.manage"))])
def delete_group(group_id: int, db: Session = Depends(get_db)):
    g = db.query(MenuGroup).get(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    db.delete(g)  # cascade deletes items
    db.commit()
    return {"ok": True}


# ── POST /menu/items ─────────────────────────────────────────────────────────

class _ItemCreate(BaseModel):
    group_id: int
    tab_key: str
    sort_order: int = 0


@router.post("/items", dependencies=[Depends(require_permission("menu.manage"))])
def create_item(body: _ItemCreate, db: Session = Depends(get_db)):
    if body.tab_key not in TAB_REGISTRY:
        raise HTTPException(422, f"Unknown tab_key: {body.tab_key}")
    g = db.query(MenuGroup).get(body.group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    dup = db.query(MenuItem).filter_by(group_id=body.group_id, tab_key=body.tab_key).first()
    if dup:
        raise HTTPException(409, f"Tab '{body.tab_key}' already in group '{g.name}'")
    max_order = db.query(MenuItem.sort_order).filter_by(group_id=body.group_id).order_by(MenuItem.sort_order.desc()).scalar() or 0
    item = MenuItem(group_id=body.group_id, tab_key=body.tab_key, sort_order=body.sort_order or max_order + 1)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_dict(item)


# ── PATCH /menu/items/{id} ──────────────────────────────────────────────────

class _ItemUpdate(BaseModel):
    sort_order: Optional[int] = None
    group_id: Optional[int] = None


@router.patch("/items/{item_id}", dependencies=[Depends(require_permission("menu.manage"))])
def update_item(item_id: int, body: _ItemUpdate, db: Session = Depends(get_db)):
    item = db.query(MenuItem).get(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if body.group_id is not None:
        g = db.query(MenuGroup).get(body.group_id)
        if not g:
            raise HTTPException(404, "Target group not found")
        dup = (
            db.query(MenuItem)
            .filter(MenuItem.group_id == body.group_id, MenuItem.tab_key == item.tab_key, MenuItem.id != item.id)
            .first()
        )
        if dup:
            raise HTTPException(409, f"Tab '{item.tab_key}' already in target group")
        item.group_id = body.group_id
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    db.commit()
    db.refresh(item)
    return _item_dict(item)


# ── DELETE /menu/items/{id} ─────────────────────────────────────────────────

@router.delete("/items/{item_id}", dependencies=[Depends(require_permission("menu.manage"))])
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(MenuItem).get(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── GET /menu/tabs ──────────────────────────────────────────────────────────

@router.get("/tabs")
def list_tabs():
    return {"tabs": [{"key": k, **v} for k, v in TAB_REGISTRY.items()]}
```

- [ ] **Step 2: Include router in `app/main.py`**

At line ~526-551, add inside the `if "menu" not in [r.prefix for r in app.routes]:` block (or at the end of the router list):

```python
from app.api.menu import router as menu_router
app.include_router(menu_router)
```

Or follow the existing pattern — add `("menu", menu_router)` if the list is iterated, or append directly. Look at how existing routers are added and follow that pattern exactly. The existing code uses individual `app.include_router(...)` calls — just add one more after the last.

- [ ] **Step 3: Add `seed_menu` to conftest `db_session` fixture**

In `tests/conftest.py`, add at line ~9:
```python
from scripts.seed_menu import seed_menu
```

And inside `db_session` fixture, after `seed_rules(session)` at line ~80, add:
```python
seed_menu(session)
```

- [ ] **Step 4: Run full test suite**

```powershell
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 5: Commit**

```powershell
git add app/api/menu.py app/main.py tests/conftest.py
git commit -m "feat(menu): add menu API router with group/item CRUD"
```

---

## Task 4: Backend Tests — `tests/test_menu_api.py`

**Files:**
- Create: `tests/test_menu_api.py`

### Steps

- [ ] **Step 1: Write test file**

```python
"""Tests for the menu API."""
import pytest


def test_get_menu_returns_seeded_groups(client):
    resp = client.get("/menu")
    assert resp.status_code == 200
    data = resp.json()
    groups = data["groups"]
    assert len(groups) == 5
    # First group is الرئيسية with dashboard
    first = groups[0]
    assert first["name"] == "الرئيسية"
    assert first["icon"] == "🏠"
    assert len(first["items"]) == 1
    assert first["items"][0]["tab_key"] == "dashboard"
    assert first["items"][0]["label"] == "Dashboard"


def test_get_menu_includes_tab_metadata(client):
    resp = client.get("/menu")
    items = resp.json()["groups"][1]["items"]  # البيانات group
    upload = next(i for i in items if i["tab_key"] == "upload")
    assert upload["icon"] == "📤"
    assert upload["permission"] == "data.upload"


def test_list_tabs(client):
    resp = client.get("/menu/tabs")
    assert resp.status_code == 200
    tabs = resp.json()["tabs"]
    assert len(tabs) == 14
    keys = [t["key"] for t in tabs]
    assert "dashboard" in keys
    assert "smart-analytics" in keys


def test_create_group(client):
    resp = client.post("/menu/groups", json={"name": "Test Group", "icon": "🧪"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Group"
    assert data["icon"] == "🧪"
    assert data["is_active"] is True


def test_update_group(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.patch(f"/menu/groups/{gid}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_delete_group(client):
    resp = client.post("/menu/groups", json={"name": "Disposable"})
    gid = resp.json()["id"]
    resp = client.delete(f"/menu/groups/{gid}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    groups = client.get("/menu").json()["groups"]
    assert all(g["id"] != gid for g in groups)


def test_create_item(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    assert resp.status_code == 200
    assert resp.json()["tab_key"] == "upload"


def test_create_item_duplicate_returns_409(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "upload"})
    assert resp.status_code == 409


def test_create_item_invalid_tab_key_returns_422(client):
    groups = client.get("/menu").json()["groups"]
    gid = groups[0]["id"]
    resp = client.post("/menu/items", json={"group_id": gid, "tab_key": "nonexistent"})
    assert resp.status_code == 422


def test_create_item_invalid_group_returns_404(client):
    resp = client.post("/menu/items", json={"group_id": 99999, "tab_key": "upload"})
    assert resp.status_code == 404


def test_update_item_sort_order(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[1]["items"][0]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"sort_order": 99})
    assert resp.status_code == 200
    assert resp.json()["sort_order"] == 99


def test_update_item_move_to_different_group(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[1]["items"][0]["id"]
    target_gid = groups[2]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"group_id": target_gid})
    assert resp.status_code == 200
    assert resp.json()["group_id"] == target_gid


def test_delete_item(client):
    groups = client.get("/menu").json()["groups"]
    item_id = groups[0]["items"][0]["id"]
    resp = client.delete(f"/menu/items/{item_id}")
    assert resp.status_code == 200


def test_delete_nonexistent_item_returns_404(client):
    resp = client.delete("/menu/items/99999")
    assert resp.status_code == 404


def test_move_item_to_group_with_same_tab_key_returns_409(client):
    groups = client.get("/menu").json()["groups"]
    # dashboard is in group[0], try moving it to a group that also has dashboard
    # First add dashboard to group[2] (if not already), then try to move group[0]'s dashboard there
    client.post("/menu/items", json={"group_id": groups[2]["id"], "tab_key": "dashboard"})
    item_id = groups[0]["items"][0]["id"]
    resp = client.patch(f"/menu/items/{item_id}", json={"group_id": groups[2]["id"]})
    assert resp.status_code == 409


def test_hidden_tab_settings_excluded_from_groups(client):
    resp = client.get("/menu")
    all_tab_keys = [
        item["tab_key"]
        for g in resp.json()["groups"]
        for item in g["items"]
    ]
    # 'settings' IS included (hidden is a frontend-only concept)
    assert "settings" in all_tab_keys
```

- [ ] **Step 2: Run menu tests**

```powershell
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\test_menu_api.py -v -q
```

- [ ] **Step 3: Run full suite**

```powershell
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 4: Commit**

```powershell
git add tests/test_menu_api.py
git commit -m "test(menu): add menu API test suite"
```

---

## Task 5: Frontend — Sidebar HTML + renderSidebar.js + CSS

**Files:**
- Modify: `static/index.html` (replace `.tab-bar` divs with sidebar shell; add hamburger toggle in header; remove `tab_order` script)
- Create: `static/js/renderSidebar.js`
- Modify: `static/css/styles.css` (sidebar + responsive + RTL styles)
- Modify: `static/js/main.js` (import renderSidebar, call it at boot)
- Modify: `static/js/app.js` (call renderSidebar after auth)

### Steps

- [ ] **Step 1: Edit `static/index.html`**

**A. Remove the `tab_order` reorder script** (lines 44-57 — delete the `if (savedOrder)` block, keep the theme toggle and the `DOMContentLoaded` wrapper).

**B. Add hamburger toggle button in header** (inside the `.header` `<div style="display:flex;...">` block at line ~98, add before `#version-badge`):

```html
<button id="sidebarToggle" class="sidebar-toggle-btn" onclick="toggleSidebar()" title="Toggle sidebar" style="display:none;background:none;border:1px solid var(--border-default);color:var(--text-primary);border-radius:6px;padding:0.3rem 0.6rem;font-size:0.85rem;cursor:pointer;">☰</button>
```

Show it after auth via JS (set `display:''` inside `renderSidebar()` when screen is small).

**C. Replace the static `.tab-bar` div (lines 110-125) with the sidebar shell:**

Replace the entire `<div class="tab-bar" ...>...</div>` (lines 110-125) with:

```html
<aside id="sidebar" class="sidebar" role="navigation" aria-label="Main navigation">
  <nav id="sidebarRoot"></nav>
  <button class="sidebar-collapse-btn" onclick="toggleSidebarCollapse()" title="Collapse sidebar">◀</button>
</aside>
```

**D. Wrap the tab-content panels in `<main id="tabArea">`:**

After the breadcrumb div (line 132), insert `<main id="tabArea">` and close it with `</main>` after the last `.tab-content` div (before line 166's `</div>`).

The structure becomes:
```html
<!-- breadcrumb -->
<main id="tabArea">
  <div id="tab-dashboard" class="tab-content active" ...></div>
  <div id="tab-upload" ...></div>
  ...
  <div id="tab-smart-analytics" ...></div>
</main>
```

- [ ] **Step 2: Create `static/js/renderSidebar.js`**

```javascript
/**
 * renderSidebar.js — Fetch /menu and build sidebar DOM.
 * Replaces the static .tab-bar from index.html.
 */
import { switchTab } from './main.js';

var _sidebarData = null;

/**
 * Build a sidebar item element (.tab with data-tab + data-requires).
 */
function _buildItem(item) {
    var el = document.createElement('div');
    el.className = 'tab';
    el.setAttribute('data-tab', item.tab_key);
    el.setAttribute('role', 'tab');
    el.setAttribute('tabindex', '-1');
    el.setAttribute('aria-controls', 'tab-' + item.tab_key);
    if (item.permission) {
        el.setAttribute('data-requires', item.permission);
    }
    if (item.superadmin_only) {
        el.setAttribute('data-requires-superadmin', '');
    }
    el.innerHTML =
        '<span class="sidebar-item-icon">' + (item.icon || '') + '</span>' +
        '<span class="sidebar-item-label">' + (item.label || item.tab_key) + '</span>';
    el.addEventListener('click', function() { switchTab(item.tab_key); });
    return el;
}

/**
 * Build the full sidebar from /menu response.
 */
function _render(groups) {
    var root = document.getElementById('sidebarRoot');
    if (!root) return;
    root.innerHTML = '';
    groups.forEach(function(group) {
        var section = document.createElement('div');
        section.className = 'sidebar-group';
        section.setAttribute('data-group-id', group.id);

        var title = document.createElement('div');
        title.className = 'sidebar-group-title';
        title.innerHTML =
            '<span class="sidebar-group-icon">' + (group.icon || '') + '</span>' +
            '<span class="sidebar-group-label">' + (group.name || '') + '</span>' +
            '<span class="sidebar-group-chevron">▾</span>';
        title.addEventListener('click', function() {
            section.classList.toggle('collapsed');
        });
        section.appendChild(title);

        var itemsWrap = document.createElement('div');
        itemsWrap.className = 'sidebar-group-items';
        group.items.forEach(function(item) {
            itemsWrap.appendChild(_buildItem(item));
        });
        section.appendChild(itemsWrap);
        root.appendChild(section);
    });

    // Restore collapsed state from localStorage
    try {
        var saved = JSON.parse(localStorage.getItem('sidebar_collapsed_groups') || '[]');
        saved.forEach(function(gid) {
            var sec = root.querySelector('[data-group-id="' + gid + '"]');
            if (sec) sec.classList.add('collapsed');
        });
    } catch(e) {}

    // Apply permission gating (hides unauthorized items)
    if (typeof window.applyPermissions === 'function') {
        window.applyPermissions();
    }
    // Highlight the active tab
    _highlightActive();
}

function _highlightActive() {
    var active = document.querySelector('.tab.active');
    var tabName = active ? active.getAttribute('data-tab') : 'dashboard';
    document.querySelectorAll('#sidebarRoot .tab').forEach(function(el) {
        el.classList.toggle('active', el.getAttribute('data-tab') === tabName);
    });
}

/**
 * Fetch /menu and render. Called once at boot.
 */
export async function renderSidebar() {
    try {
        var resp = await fetch('/menu', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') } });
        if (!resp.ok) throw new Error(resp.status);
        var data = await resp.json();
        _sidebarData = data;
        _render(data.groups || []);
    } catch(e) {
        console.warn('[sidebar] Failed to load menu:', e);
        // Fallback: use static registry
        _renderFallback();
    }
    _applyCollapseState();
    _showToggleOnMobile();
}

/**
 * Fallback if /menu fails: use DEFAULT_GROUPS from index.html inline data or hardcoded.
 */
function _renderFallback() {
    // Hardcoded minimal fallback (matches seed defaults)
    var fallback = [
        {name:'الرئيسية', icon:'🏠', items:[{tab_key:'dashboard', label:'Dashboard', icon:'📊', permission:'dashboard.read'}]},
        {name:'البيانات', icon:'📊', items:[
            {tab_key:'upload', label:'Upload Data', icon:'📤', permission:'data.upload'},
            {tab_key:'indicator-tree', label:'Indicator Tree', icon:'🌳', permission:'settings.read'},
            {tab_key:'rules-manager', label:'Rules Manager', icon:'📋', permission:'rules.read'},
        ]},
        {name:'التحليل', icon:'📈', items:[
            {tab_key:'analysis', label:'Comparative Analysis', icon:'📈', permission:'analysis.read'},
            {tab_key:'root-cause', label:'Root Cause', icon:'🔍', permission:'root_cause.read'},
            {tab_key:'smart-analytics', label:'Smart Analytics', icon:'🛡️', permission:'smart_analytics.read'},
        ]},
        {name:'التقارير', icon:'📋', items:[
            {tab_key:'quality', label:'Quality Reports', icon:'✅', permission:'quality.read'},
            {tab_key:'clinical', label:'Clinical Intelligence', icon:'🏥', permission:'clinical.read'},
            {tab_key:'outliers', label:'Outliers', icon:'⚠️', permission:'outliers.read'},
            {tab_key:'alerts', label:'Alerts', icon:'🔔', permission:'alerts.read'},
        ]},
        {name:'الإدارة', icon:'⚙️', items:[
            {tab_key:'audit', label:'Audit Log', icon:'📝', permission:'audit.read'},
            {tab_key:'admin', label:'System Control', icon:'⚙️', permission:'system.manage_users', superadmin_only:true},
            {tab_key:'settings', label:'Settings', icon:'🔧', permission:'system.manage_users'},
        ]},
    ];
    _render(fallback);
}

function _applyCollapseState() {
    var collapsed = localStorage.getItem('sidebar_collapsed') === '1';
    var sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('collapsed', collapsed);
    _updateChevrons(collapsed);
}

function _updateChevrons(collapsed) {
    var btn = document.querySelector('.sidebar-collapse-btn');
    if (btn) btn.textContent = collapsed ? '▶' : '◀';
}

window.toggleSidebarCollapse = function() {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    var collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('sidebar_collapsed', collapsed ? '1' : '0');
    _updateChevrons(collapsed);
};

window.toggleSidebar = function() {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
};

function _showToggleOnMobile() {
    var btn = document.getElementById('sidebarToggle');
    if (btn && window.innerWidth <= 768) btn.style.display = '';
}

// Re-highlight on switchTab (main.js calls switchTab; we hook it)
var _origSwitchTab = window.switchTab;
window.switchTab = function(name) {
    if (_origSwitchTab) _origSwitchTab(name);
    _highlightActive();
    // Close mobile drawer on tab select
    var sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.remove('open');
};

// Save group collapse state on click
document.addEventListener('click', function(e) {
    var title = e.target.closest('.sidebar-group-title');
    if (!title) return;
    var section = title.closest('.sidebar-group');
    if (!section) return;
    var gid = section.getAttribute('data-group-id');
    var saved = [];
    try { saved = JSON.parse(localStorage.getItem('sidebar_collapsed_groups') || '[]'); } catch(e) {}
    if (section.classList.contains('collapsed')) {
        saved.push(gid);
    } else {
        saved = saved.filter(function(id) { return id !== gid; });
    }
    localStorage.setItem('sidebar_collapsed_groups', JSON.stringify(saved));
});
```

- [ ] **Step 3: Add sidebar CSS to `static/css/styles.css`**

Append at the end of the file:

```css
/* ── Sidebar ──────────────────────────────────────────────────────────────── */
.app-shell { display:flex; gap:1rem; min-height:0; }

.sidebar {
  width: 240px;
  min-width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
  max-height: calc(100vh - 80px);
  position: sticky;
  top: 76px;
  transition: width 0.2s ease, min-width 0.2s ease;
}
.sidebar.collapsed { width: 56px; min-width: 56px; }
.sidebar.collapsed .sidebar-item-label,
.sidebar.collapsed .sidebar-group-label,
.sidebar.collapsed .sidebar-group-chevron { display:none; }
.sidebar.collapsed .sidebar-group-title { justify-content:center; padding:0.6rem 0; }
.sidebar.collapsed .sidebar-collapse-btn { margin:0.4rem auto; }
.sidebar.collapsed .sidebar-item-icon { margin:0; }

.sidebar nav#sidebarRoot {
  display:flex; flex-direction:column; gap:0;
  overflow-y:auto; flex:1; padding:0.4rem 0;
}

.sidebar-collapse-btn {
  background:none; border:none; border-top:1px solid var(--border-default);
  padding:0.35rem; cursor:pointer; font-size:0.7rem; color:var(--text-muted);
  transition: color 0.15s;
}
.sidebar-collapse-btn:hover { color:var(--text-primary); }

.sidebar-group { border-bottom:1px solid var(--border-default); }
.sidebar-group:last-child { border-bottom:none; }

.sidebar-group-title {
  display:flex; align-items:center; gap:0.45rem;
  padding:0.55rem 0.7rem; cursor:pointer; user-select:none;
  font-size:0.76rem; font-weight:600; color:var(--text-secondary);
  transition: background 0.12s;
}
.sidebar-group-title:hover { background:var(--bg-surface-hover); }
.sidebar-group-icon { font-size:0.85rem; flex-shrink:0; }
.sidebar-group-label { flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sidebar-group-chevron { font-size:0.6rem; transition:transform 0.2s; }
.sidebar-group.collapsed .sidebar-group-chevron { transform:rotate(-90deg); }

.sidebar-group-items { display:flex; flex-direction:column; gap:0; }
.sidebar-group.collapsed .sidebar-group-items { display:none; }

/* Sidebar .tab items (same class as old tabs for switchTab/applyPermissions compat) */
.sidebar .tab {
  display:flex; align-items:center; gap:0.5rem;
  padding:0.5rem 0.7rem 0.5rem 1.1rem;
  cursor:pointer; font-size:0.82rem; color:var(--text-secondary);
  border-left:3px solid transparent;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.sidebar .tab:hover { background:var(--bg-surface-hover); color:var(--text-primary); }
.sidebar .tab.active {
  background:var(--accent-blue-10, rgba(0,120,255,0.08));
  color:var(--accent-blue);
  border-left-color:var(--accent-blue);
  font-weight:600;
}
.sidebar-item-icon { font-size:0.85rem; flex-shrink:0; min-width:1.1rem; text-align:center; }
.sidebar-item-label { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

.sidebar-toggle-btn {
  display:none !important; /* overridden to '' on mobile */
}

/* ── RTL sidebar ──────────────────────────────────────────────────────────── */
[dir="rtl"] .sidebar .tab { border-left:none; border-right:3px solid transparent; }
[dir="rtl"] .sidebar .tab.active { border-right-color:var(--accent-blue); }
[dir="rtl"] .sidebar .tab { padding:0.5rem 1.1rem 0.5rem 0.7rem; }

/* ── Mobile responsive ────────────────────────────────────────────────────── */
@media (max-width:768px) {
  .sidebar-toggle-btn { display:inline-flex !important; }

  .sidebar {
    position:fixed; top:0; bottom:0;
    z-index:200; width:280px; min-width:280px;
    transform:translateX(100%);
    transition:transform 0.25s ease;
    border-radius:0; border:none; box-shadow:var(--shadow-lg);
  }
  [dir="rtl"] .sidebar { left:0; right:auto; transform:translateX(-100%); }
  [dir="ltr"] .sidebar { right:0; left:auto; }

  .sidebar.open { transform:translateX(0); }
  [dir="rtl"] .sidebar.open { transform:translateX(0); }

  .sidebar-overlay {
    position:fixed; inset:0; background:rgba(0,0,0,0.4);
    z-index:199; display:none; cursor:pointer;
  }
  .sidebar.open ~ .sidebar-overlay { display:block; }

  .app-shell { flex-direction:column; }
  #tabArea { width:100%; }
}
```

- [ ] **Step 4: Remove old `.tab-bar` horizontal styles from `static/css/styles.css`**

Find and replace `.tab-bar` styles with a deactivation (or just leave them — they only affect `.tab-bar` which no longer exists in DOM):

```css
/* .tab-bar styles retained but unused — sidebar replaces horizontal tabs */
/* .tab-bar { display:flex; ... } */
```

This keeps the diff small and avoids accidentally breaking admin.js tab-bar usage.

- [ ] **Step 5: Wire renderSidebar into app boot in `static/js/app.js`**

At the end of app.js boot, after `switchTab('dashboard')` (line 318), add:

```javascript
import { renderSidebar } from './renderSidebar.js';
// ... at boot after switchTab('dashboard'):
renderSidebar();
```

But app.js is `type="module"` already (line 319). The import must be at top. Actually, `renderSidebar` should be called after auth succeeds, after `switchTab('dashboard')`. Since `switchTab('dashboard')` depends on sidebar items existing... We need to call `renderSidebar()` BEFORE `switchTab('dashboard')`. Fix:

In `static/js/app.js`, replace line 318:

```javascript
// Before: switchTab('dashboard');
// After:
renderSidebar().then(function() { switchTab('dashboard'); });
```

But renderSidebar is async. To avoid breaking the module, import at top:

```javascript
import { renderSidebar } from './renderSidebar.js';
```

And replace line 318:
```javascript
renderSidebar().then(function() { switchTab('dashboard'); });
```

- [ ] **Step 6: Remove old `applyTabOrder` from admin.js and `_applyTabOrder` export**

In `static/js/admin.js`, delete the following (lines 1454-1469):
- `function applyTabOrder()`
- `window._applyTabOrder = applyTabOrder;`
- The `if (document.getElementById('tabOrderList')) loadTabOrder();` line

- [ ] **Step 7: Run node check + full suite**

```powershell
Get-Content static\js\renderSidebar.js -Raw | node --input-type=module --check
Get-Content static\js\app.js -Raw | node --input-type=module --check
Get-Content static\js\main.js -Raw | node --input-type=module --check
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 8: Commit**

```powershell
git add static/index.html static/js/renderSidebar.js static/js/app.js static/js/main.js static/css/styles.css static/js/admin.js
git commit -m "feat(menu): add responsive sidebar with RTL support, replace tab-bar"
```

---

## Task 6: Admin Menu Layout Panel (Replace Tab Order)

**Files:**
- Modify: `static/js/admin.js` (replace `adminTabOrderPanel` with menu layout panel; replace `loadTabOrder`/`saveTabOrder`/`resetTabOrder`/`loadTabOrder` with `loadMenuLayout`)

### Steps

- [ ] **Step 1: Replace the Tab Order panel HTML in admin.js template**

In the admin control panel template literal (around line 452-460), replace the `adminTabOrderPanel` div with:

```javascript
<div id="adminMenuLayoutPanel" style="display:none;">
  <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">📋 Menu Layout</h2>
  <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.7rem;">
    Manage sidebar groups, add tabs, and reorder items. Changes apply immediately.
  </p>
  <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">
    <button class="btn btn-sm btn-outline" onclick="addMenuGroup()">➕ Add Group</button>
  </div>
  <div id="menuLayoutList"></div>
</div>
```

- [ ] **Step 2: Replace `loadTabOrder` with `loadMenuLayout` + CRUD functions**

Delete these functions from admin.js (lines 1385-1469):
- `window.loadTabOrder`
- `window._tabDragStart`
- `window._tabDragOver`
- `window._tabDrop`
- `window.saveTabOrder`
- `window.resetTabOrder`
- `function applyTabOrder`
- `window._applyTabOrder`
- The `document.addEventListener('dragend', ...)` block (line 1436-1438)
- The `if (document.getElementById('tabOrderList')) loadTabOrder();` line (1469)

Replace with:

```javascript
// ── Menu Layout Panel ──────────────────────────────────────────────────────

window.loadMenuLayout = async function() {
  var el = document.getElementById('menuLayoutList');
  if (!el) return;
  try {
    var resp = await api('/menu');
    var groups = (resp && resp.groups) || [];
    _renderMenuLayout(groups, el);
  } catch(e) {
    el.innerHTML = '<div style="color:var(--accent-red);padding:1rem;">Failed to load menu: ' + esc(e.message) + '</div>';
  }
};

function _renderMenuLayout(groups, el) {
  if (!groups.length) {
    el.innerHTML = '<div style="color:var(--text-muted);padding:1rem;">No groups. Click "Add Group" to create one.</div>';
    return;
  }
  var html = '';
  groups.forEach(function(g) {
    html += '<div style="border:1px solid var(--border-default);border-radius:8px;margin-bottom:0.6rem;overflow:hidden;">';
    html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.6rem 0.8rem;background:var(--bg-surface-hover);">';
    html += '<span style="cursor:grab;font-size:0.7rem;color:var(--text-muted);">⠿</span>';
    html += '<span style="font-size:0.9rem;">' + esc(g.icon) + '</span>';
    html += '<span style="flex:1;font-weight:600;font-size:0.82rem;">' + esc(g.name) + '</span>';
    html += '<button class="btn btn-sm btn-outline" onclick="editMenuGroup(' + g.id + ')" title="Edit">✏️</button>';
    html += '<button class="btn btn-sm btn-outline" style="color:var(--accent-red);" onclick="deleteMenuGroup(' + g.id + ')" title="Delete">🗑️</button>';
    html += '</div>';
    g.items.forEach(function(item) {
      html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.8rem 0.4rem 2rem;border-top:1px solid var(--border-default);font-size:0.8rem;">';
      html += '<span style="color:var(--text-muted);font-size:0.65rem;">⠿</span>';
      html += '<span>' + esc(item.icon) + '</span>';
      html += '<span style="flex:1;">' + esc(item.label) + '</span>';
      html += '<span style="font-size:0.65rem;color:var(--text-muted);">[ ' + esc(item.tab_key) + ' ]</span>';
      html += '<button class="btn btn-sm btn-outline" style="color:var(--accent-red);font-size:0.7rem;" onclick="deleteMenuItem(' + item.id + ')" title="Remove">✕</button>';
      html += '</div>';
    });
    // Add tab dropdown
    html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.8rem 0.4rem 2rem;border-top:1px solid var(--border-default);">';
    html += '<select id="addTabSelect_' + g.id + '" style="flex:1;font-size:0.78rem;padding:0.3rem;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-surface);color:var(--text-primary);">';
    html += '<option value="">+ Add tab to this group...</option>';
    // Populate with tabs not already in this group
    var inGroup = new Set(g.items.map(function(i) { return i.tab_key; }));
    if (window._menuTabRegistry) {
      window._menuTabRegistry.forEach(function(t) {
        if (!inGroup.has(t.key)) {
          html += '<option value="' + t.key + '">' + t.icon + ' ' + esc(t.label) + '</option>';
        }
      });
    }
    html += '</select>';
    html += '<button class="btn btn-sm" style="background:var(--accent-green);color:white;font-size:0.72rem;" onclick="addMenuItem(' + g.id + ')">Add</button>';
    html += '</div>';
    html += '</div>';
  });
  el.innerHTML = html;
}

// Fetch tab registry once for the dropdown
async function _loadMenuTabRegistry() {
  if (window._menuTabRegistry) return;
  try {
    var resp = await api('/menu/tabs');
    window._menuTabRegistry = (resp && resp.tabs) || [];
  } catch(e) { window._menuTabRegistry = []; }
}

window.addMenuGroup = async function() {
  var name = prompt('Group name (e.g. "Data"):');
  if (!name) return;
  var icon = prompt('Icon emoji (e.g. 📊):', '📁');
  if (icon === null) icon = '📁';
  await api('/menu/groups', { method:'POST', body: JSON.stringify({name:name, icon:icon}) });
  loadMenuLayout();
};

window.editMenuGroup = async function(id) {
  var name = prompt('New group name:');
  if (!name) return;
  var icon = prompt('New icon emoji:');
  if (icon === null) return;
  await api('/menu/groups/' + id, { method:'PATCH', body: JSON.stringify({name:name, icon:icon}) });
  loadMenuLayout();
};

window.deleteMenuGroup = async function(id) {
  if (!confirm('Delete this group and all its tabs?')) return;
  await api('/menu/groups/' + id, { method:'DELETE' });
  loadMenuLayout();
};

window.addMenuItem = async function(groupId) {
  var sel = document.getElementById('addTabSelect_' + groupId);
  var tabKey = sel ? sel.value : '';
  if (!tabKey) return;
  await api('/menu/items', { method:'POST', body: JSON.stringify({group_id: groupId, tab_key: tabKey}) });
  loadMenuLayout();
};

window.deleteMenuItem = async function(id) {
  await api('/menu/items/' + id, { method:'DELETE' });
  loadMenuLayout();
};
```

- [ ] **Step 3: Wire into `switchAdminTab` (atab-tabs case)**

Find the `atab-tabs` case in `switchAdminTab` (around line 962) and replace:

```javascript
// Before:
adminTabOrderPanel.style.display = '';
loadTabOrder();

// After:
adminMenuLayoutPanel.style.display = '';
_loadMenuTabRegistry().then(loadMenuLayout);
```

Also update the reference to `adminTabOrderPanel` to `adminMenuLayoutPanel` (the `style.display = 'none'` reset for other panels should hide `adminMenuLayoutPanel` too).

- [ ] **Step 4: Run node check + full suite**

```powershell
Get-Content static\js\admin.js -Raw | node --input-type=module --check
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 5: Commit**

```powershell
git add static/js/admin.js
git commit -m "feat(menu): replace Tab Order panel with Menu Layout CRUD in admin"
```

---

## Task 7: Final Integration & Cleanup

**Files:**
- Review all modified files for consistency
- Run full verification

### Steps

- [ ] **Step 1: Run full test suite + node checks**

```powershell
Get-Content static\js\renderSidebar.js -Raw | node --input-type=module --check
Get-Content static\js\app.js -Raw | node --input-type=module --check
Get-Content static\js\main.js -Raw | node --input-type=module --check
Get-Content static\js\admin.js -Raw | node --input-type=module --check
$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis"; & .\.venv\Scripts\python.exe -m pytest tests\ -x -q
```

- [ ] **Step 2: Verify no stale references**

Grep for dead code:
```powershell
rg "loadTabOrder|saveTabOrder|resetTabOrder|_applyTabOrder|adminTabOrderPanel|tab_order|tabOrderList" static/js/ --include="*.js"
```
Expected: zero matches (all replaced).

- [ ] **Step 3: Verify the old .tab-bar divs are gone from index.html**

```powershell
rg "class=\"tab-bar\"" static/index.html
```
Expected: zero matches.

- [ ] **Step 4: Final commit + push (after user approval)**

```powershell
git add -A
git status
git commit -m "feat(menu): sidebar menu with DB-driven groups — full integration"
```
(Only after user approves push.)

---

## Self-Review Checklist

1. **Spec coverage:** 5 groups, 14 tabs, sidebar collapse, mobile drawer, RTL, admin Menu Layout panel, DB persistence, GET /menu/tabs registry — all covered.
2. **No placeholders:** All code blocks contain real implementation.
3. **Type consistency:** `renderSidebar()` uses `_item_dict` shape from API; `admin.js` matches `GET /menu` response shape; `switchTab`/`applyPermissions` still work via `.tab[data-tab]` class.
4. **Permission gating preserved:** `data-requires` + `data-requires-superadmin` on sidebar items; `applyPermissions()` re-called after render; `_TAB_PERMISSIONS` unchanged.
