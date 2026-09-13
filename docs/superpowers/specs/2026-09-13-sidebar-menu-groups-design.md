# Design: Sidebar Navigation with DB-Driven Menu Groups

Date: 2026-09-13

## Goal

Replace the horizontal tab bar with a collapsible vertical sidebar that
organizes the existing 14 tabs under admin-managed root groups. Admins can
create/reorder groups, assign tabs into groups via a dropdown, and reorder
groups or tabs. Group structure and ordering live in the database so all
users see the same menu.

## Scope

- New: `MenuGroup` + `MenuItem` models, `menu` API router, admin "Menu
  Layout" panel in System Control.
- Change: `static/index.html` tab bar becomes a sidebar built from
  `GET /menu` (not static HTML); `main.js` reuses `switchTab`/`_tabInited`
  unchanged; permission gating via existing `data-requires` mechanism
  preserved.
- Removed: `localStorage.tab_order` ordering is retired in favor of DB order.
- Out of scope (YAGNI): full DB-driven tab registry with custom content
  URLs/permissions, drag-and-drop, multi-tenant menus.

## 1. Data Model (`app/models.py`)

```python
class MenuGroup(Base):
    __tablename__ = "menu_groups"
    id: int (pk)
    name: str
    icon: str (default "")
    sort_order: int
    is_active: bool = True

class MenuItem(Base):
    __tablename__ = "menu_items"
    id: int (pk)
    group_id: int (FK -> menu_groups.id, ondelete CASCADE)
    tab_key: str            # one of the 14 known tab keys
    sort_order: int
    # unique constraint on (group_id, tab_key)
```

`tab_key` references the fixed tab registry (dashboard, upload, quality,
analysis, clinical, outliers, alerts, indicator-tree, rules-manager,
root-cause, audit, admin, settings, smart-analytics). Tabs themselves, their
content files, and their permission keys stay in code. Tab keys not present
in any active group are hidden from the sidebar.

## 2. Tab Registry (static, kept in code)

The canonical list of tabs remains in `static/js/main.js`
(`_tabLabels`, `_tabIcons`) plus `auth.js _TAB_PERMISSIONS` and the tab
content divs in `index.html`. Both the sidebar builder and the seed use this
registry.

## 3. API Router (`app/api/menu.py`)

Permission: `menu.manage` (new Permission codename; auto-seeded to admin
role and superuser).

- `GET /menu` -> `{ groups: [ { id, name, icon, sort_order, items: [ { id, tab_key, label, icon, sort_order } ] } ] }`
  - Groups returned ordered by `sort_order`; only `is_active=true` groups.
  - Items ordered by `sort_order`.
  - Server-side filtering NOT applied here; client already hides tabs the
    user lacks permission for via `data-requires`.
- `POST /menu/groups` `{name, icon, sort_order?, is_active?}` -> created group
  (sort_order default = max+1).
- `PUT /menu/groups/{id}` `{name?, icon?, sort_order?, is_active?}`.
- `DELETE /menu/groups/{id}` -> deletes group + its items (CASCADE), reorders
  remaining groups to close the gap.
- `POST /menu/items` `{group_id, tab_key, sort_order?}` -> 400 if tab_key
  unknown or already in that group.
- `PUT /menu/items/{id}` `{group_id?, sort_order?}` (move/reorder).
- `DELETE /menu/items/{id}`.
- `GET /menu/tabs` -> `{ tabs: [ { tab_key, label, icon } ] }` (the registry,
  used to populate the admin dropdown; optionally excluded keys already added).

On any create/delete/reorder the menu is cached/invalidated the same way the
existing `cache` utility is used elsewhere.

## 4. Seeding

In `scripts/seed_rules.py` or a new `scripts/seed_menu.py` (called from the
same startup block in `app/main.py:445` guard):

- If `menu_groups` table is empty, create default groups with the 14 tabs:
  - **الرئيسية / Home**: dashboard
  - **البيانات / Data**: upload, indicator-tree, rules-manager
  - **التحليل / Analysis**: analysis, root-cause, smart-analytics
  - **التقارير / Reports**: quality, clinical, outliers, alerts
  - **الإدارة / Admin**: audit, admin, settings
- Idempotent: skip if groups already exist (add-only). Preserve existing
  DB rows on future runs.

## 5. Frontend

### 5.1 Sidebar layout (`index.html` + CSS)

- Replace `<div class="tab-bar">...</div>` static tabs with
  `<aside id="sidebar" class="sidebar">` rendered by JS from `GET /menu`.
- Each group = a `<div class="sidebar-group">` with a collapsible header
  (`name` + chevron + icon) and child `<div class="tab" data-tab="...">`.
- Expanded/collapsed group state per user persisted to
  `localStorage.sidebar_groups` (UI state only, NOT ordering).
- Sidebar is fixed-width (~240px) on desktop; collapsed to icon rail
  (~56px) via a toggle button; on small screens a hamburger opens it as an
  overlay drawer.
- RTL support: sidebar sits on the right in RTL, left in LTR (follow
  existing `html[dir=rtl]` handling).

### 5.2 Tab rendering + switching (`main.js`)

- New `renderSidebar(groups)` builds the sidebar; uses
  `_tabLabels`/`_tabIcons` for label/icon display, falls back to
  `tab_key`/generic icon when registry entry is missing.
- Group headers are NOT `.tab` elements (no `data-tab`, no switching).
- Child items keep `class="tab"` + `data-tab` so `switchTab()`,
  `_tabInited`, lazy loading, and keyboard arrow navigation
  (`document.querySelectorAll('.tab')`) keep working unchanged.
- Apply saved `tab_order` (localStorage) is removed; DB order governs.
- After `applyPermissions()` hides unauthorized `.tab` elements, empty
  groups (no visible tabs remaining) are collapsed/kept but their inactive
  items stay hidden. (Simplest: keep group visible; show only allowed tabs.)
- On initial load, `switchTab('dashboard')` runs after sidebar render.

### 5.3 Admin panel (System Control)

- New section "Menu Layout" in `admin.js` (adjacent to Analysis Control).
- UI:
  - List of groups (name, icon, up/down arrows to reorder, rename, delete).
  - Each group shows its items with up/down arrows and a remove button.
  - "Add Tab" per group: `<select>` dropdown populated from
    `GET /menu/tabs` (excluding keys already in that group) + Add button.
  - "New Group" button with name + icon fields.
- Actions call the menu API directly and re-render both the admin panel and
  the sidebar live.

## 6. Error Handling

- API returns 400 with detail for: duplicate `(group_id, tab_key)`, unknown
  `tab_key`, moving an item to a deleted/nonexistent group.
- Frontend shows toast on failure and does not mutate local state.
- If `GET /menu` fails (network/DB), sidebar falls back to a static default
  order using the registry (tabs render anyway) so the app never loses
  navigation.

## 7. Testing

- Backend tests (`tests/test_menu_api.py`):
  - Seed creates 6 groups with 14 tabs, idempotent on second call.
  - CRUD groups; ordering reindex; reordering doesn't collide.
  - Add item: success, duplicate -> 400, unknown tab_key -> 400.
  - Move item between groups; delete item; delete group cascades.
  - Permission: `menu.manage` required to mutate; GET /menu open to any
    authenticated user.
  - Caching: after mutation, subsequent GET returns fresh menu.
- Frontend: JS syntax check (`node --check`); no JS test framework exists
  (consistent with repo).
- Manual smoke: render sidebar, permission hides unauthorized tabs, empty
  groups don't break, RTL layout, mobile drawer.

## 8. Migration / Compatibility

- New tables created by `Base.metadata.create_all` on startup; no manual
  migration needed (repo uses create_all).
- `localStorage.tab_order` becomes dead code (removed). No server data is
  migrated — DB seed establishes the initial menu.
- Old horizontal tab bar markup removed from `index.html`.

## 9. Files Touched

- `app/models.py` — MenuGroup, MenuItem (+ relationship)
- `app/api/menu.py` — new router (registered in `app/main.py`)
- `scripts/seed_menu.py` or extend `scripts/seed_rules.py` — default groups
- `app/main.py` — include router + call seed on startup
- `static/index.html` — sidebar markup + collapse toggle markup; remove
  static tab bar + `tab_order` script block
- `static/js/main.js` — `renderSidebar`, group collapse state, remove
  `tab_order` handling, keep `switchTab`
- `static/js/admin.js` — "Menu Layout" panel
- `static/css/styles.css` — sidebar styles (+ RTL, collapsed rail, mobile
  drawer)
- `tests/test_menu_api.py` — new