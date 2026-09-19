# System Control Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicated/overlapping UI in the System Control area and fix two correctness bugs found in the 2026-09-19 audit: the Role UI Visibility Matrix reads a stale hard-coded tab list that diverges from the real sidebar registry, and the Server Logs API is guarded by a permission codename (`admin.manage`) that does not exist in the seeded permission set, making it ungrantable to any role.

**Architecture:** Make `app/menu_registry.py`'s `TAB_REGISTRY` the single source of truth for tab ids/labels/permissions (the Visibility Matrix derives from it; the drift-prone `_TAB_DEFS` dict is deleted). Fix the `/logs` guard to use the canonical `system.read_audit` codename. Hydrate the admin KPI strip once on panel load instead of lazily per sub-tab. Export logs CSV from the in-memory entries array instead of DOM scraping. Finally, split the 1,815-line `static/js/admin.js` IIFE into focused modules under `static/js/admin/` (mirroring the existing `static/js/smart/` split) and add regression tests that would have caught the bugs: a permission-codename drift test, a tab-registry drift test, and a template `<div>`-balance test.

**Tech Stack:** FastAPI, SQLAlchemy, vanilla JS (classic IIFE modules loaded via `index.html`), CSS custom properties, Pytest, Node `--check` for JS syntax.

**Audit:** Performed 2026-09-19 against commit `cfdd112`; findings verified against the running app. Related context: recent admin-tab split (Users / Roles / Permissions sub-tabs), expandable role codenames, and the Role × Permission matrix.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `app/api/admin.py` | Delete `_TAB_DEFS`; `get_visibility_matrix` reads `TAB_REGISTRY` from `app.menu_registry` |
| Modify | `app/api/server_logs.py` | Change both `require_permission("admin.manage")` guards to `require_permission("system.read_audit")` |
| Modify | `static/js/admin.js` | KPI hydration on panel load; data-driven CSV export; de-dup follow-ups; later becomes a thin loader |
| Create | `static/js/admin/core.js` | Shared helpers (`esc`, `api`, toasts, `_adminKpi`, modal/confirm plumbing) |
| Create | `static/js/admin/users.js` | Users sub-tab + user modals (create/edit, password, hospitals) |
| Create | `static/js/admin/roles.js` | Roles sub-tab (table, expandable codenames, role editor modal) |
| Create | `static/js/admin/permissions.js` | Permissions sub-tab (Role × Permission matrix, save, dirty state) |
| Create | `static/js/admin/logs.js` | Logs sub-tab (load, search, render, CSV, auto-refresh) |
| Create | `static/js/admin/sessions.js` | Sessions sub-tab (online chips, events table, force-logoff, auto-refresh) |
| Create | `static/js/admin/database.js` | Database sub-tab (status, preview, export) |
| Create | `static/js/admin/menu.js` | Menu Layout sub-tab (groups/items CRUD, reorder) |
| Modify | `static/index.html` | Load `static/js/admin.js` (kept as loader) — no new script tags needed if admin.js imports stay classic-script based; verify order |
| Create | `tests/test_admin_drift_guards.py` | Drift guards: permission codenames exist; visibility-matrix tabs ⊆ `TAB_REGISTRY`; admin.js `<div>` balance |
| Modify | `tests/test_admin_js.py` | Adjust any string assertions affected by the split; keep behavioral assertions green |
| Optional | `static/css/styles.css` | Lower sidebar mobile breakpoint 768px → 600px (Task 7) |

---

## Global Constraints

- Windows/PowerShell for all commands. Venv: `.venv\Scripts\python.exe`. No `rg`.
- Tests: `$env:DATABASE_URL="sqlite://"; $env:PYTHONPATH="..."; & .\.venv\Scripts\python.exe -m pytest <target> -q`. Full suite: `& .\.venv\Scripts\python.exe -m pytest tests\ -q` — must be green after each task (record baseline before Task 1).
- JS syntax check: `Get-Content <file> -Raw | node --input-type=module --check` (admin.js is loaded as a classic script but parses as module — keep it that way).
- `admin.js` communicates with the backend only via its `api()` wrapper (see `tests/test_smart_core_js.py` raw-fetch rule). Keep that invariant through the split.
- Permission gating: backend routers use `require_permission(<codename>)`; codenames must exist in `CANONICAL_PERMISSION_CODENAMES` (`app/main.py`) so they are seedable and grantable via the Role × Permission matrix.
- The SPA default language is Arabic (RTL). Sidebar is right-side in RTL; do not break `[dir="rtl"]` rules when touching the breakpoint.
- No API response-shape changes. The Visibility Matrix response keeps its current JSON shape (`tabs`, `roles[].tab_access`) — only the source of `tabs` changes.
- Push only after user approval.

---

## Task 1: Visibility Matrix reads `TAB_REGISTRY` (P1 bug)

**Files:**
- Modify: `app/api/admin.py`
- Create: `tests/test_admin_drift_guards.py`

**Interfaces:**
- Consumes: `TAB_REGISTRY` from `app/menu_registry.py` (OrderedDict of `tab_id -> {label, icon, permission}`)
- Produces: `GET /admin/visibility-matrix` with identical JSON shape, now covering the real sidebar tabs

### Steps

- [ ] **Step 1: Write the drift guard test first** (`tests/test_admin_drift_guards.py`): import `app.api.admin` and assert the module has no `_TAB_DEFS` attribute and that `get_visibility_matrix`'s tab set equals `TAB_REGISTRY.keys()` (via `monkeypatch` a fake db or by refactoring the tab-enumeration into a small helper `_visibility_tabs()` that returns `{tab_id: {label, permission}}` sourced from `TAB_REGISTRY`).
- [ ] **Step 2: Delete `_TAB_DEFS`** from `app/api/admin.py` and rewrite `get_visibility_matrix` to enumerate `TAB_REGISTRY` (label = `icon + ' ' + label`; permission = registry `permission`; keep the `superadmin`/`*.*` special-casing).
- [ ] **Step 3: Verify** the response in the running app: Roles tab → Visibility Matrix shows exactly the 14 sidebar tabs (including `indicator-tree`, no phantom `hospitals` tab) with registry ids.
- [ ] **Step 4:** `& .\.venv\Scripts\python.exe -m pytest tests\test_admin_drift_guards.py tests\test_admin_js.py -q`
- [ ] **Step 5:** `git add app/api/admin.py tests/test_admin_drift_guards.py && git commit -m "fix(admin): derive visibility matrix from TAB_REGISTRY (drop drifted _TAB_DEFS)"`

## Task 2: Fix `/logs` permission codename (P1 bug)

**Files:**
- Modify: `app/api/server_logs.py`

**Interfaces:**
- Changes: `require_permission("admin.manage")` → `require_permission("system.read_audit")` on `GET /logs` and `DELETE /logs`

### Steps

- [ ] **Step 1: Add the drift test** to `tests/test_admin_drift_guards.py`: scan `app/api/**/*.py` for `require_permission("...")` literals and assert every codename is in `CANONICAL_PERMISSION_CODENAMES`. Confirm it fails on `admin.manage`.
- [ ] **Step 2: Replace both guards** in `app/api/server_logs.py` with `system.read_audit`.
- [ ] **Step 3: Verify grantability:** create a test role with only `system.read_audit`, hit `GET /logs` as that user → 200; a role without it → 403.
- [ ] **Step 4:** Run the drift test + full auth/admin test files green.
- [ ] **Step 5:** `git add app/api/server_logs.py tests/test_admin_drift_guards.py && git commit -m "fix(logs): guard /logs with grantable system.read_audit permission (admin.manage never existed)"`

## Task 3: Hydrate KPI strip on panel load (P2)

**Files:**
- Modify: `static/js/admin.js` (later: `static/js/admin/core.js`)

**Interfaces:**
- Produces: `window._hydrateAdminKpis()` — fires `/auth/sessions?limit=100`, `/logs?level=WARNING&limit=200`, `/config/database-status` in parallel on `loadAdminPanel()`; sub-tab loaders keep their existing behavior (idempotent refresh)

### Steps

- [ ] **Step 1: Extract the KPI-setting lines** (`_adminKpi('adminKpiOnline'…)`, `adminKpiLogs`, `adminKpiDb`) into `_hydrateAdminKpis()` and call it from `loadAdminPanel()` after the three panel fetches succeed.
- [ ] **Step 2: Keep sub-tab loaders unchanged** — visiting Logs/Sessions/Database still refreshes (and starts auto-refresh) as today.
- [ ] **Step 3: Verify** in the running app: after opening System Control, all six KPI cards show values without visiting any sub-tab; no duplicate network calls when switching tabs afterward.
- [ ] **Step 4:** `node --check` + `pytest tests\test_admin_js.py -q` green.
- [ ] **Step 5:** `git add static/js/admin.js && git commit -m "feat(admin): hydrate KPI strip on panel load instead of lazy per-tab"`

## Task 4: Data-driven logs CSV export (P2)

**Files:**
- Modify: `static/js/admin.js` (later: `static/js/admin/logs.js`)

**Interfaces:**
- Consumes: `window._logsEntries` (array of `{time, level, logger, message}` already fetched by `loadAdminLogs`)

### Steps

- [ ] **Step 1: Rewrite `exportLogsCSV`** to serialize `_logsEntries` directly (drop the DOM `querySelectorAll('div[style]')` scraping). Keep filename pattern `server-logs-YYYY-MM-DD.csv`.
- [ ] **Step 2: Handle the empty case:** toast a warning when there are no entries instead of silently no-op.
- [ ] **Step 3: Verify** in the app: load logs → Export CSV → file opens with Time/Level/Logger/Message columns matching the rendered rows, including messages containing quotes/commas.
- [ ] **Step 4:** `node --check` green; add/adjust a static assertion in `tests/test_admin_js.py` that `exportLogsCSV` references `_logsEntries` and not `querySelectorAll`.
- [ ] **Step 5:** `git add static/js/admin.js tests/test_admin_js.py && git commit -m "refactor(admin): export logs CSV from entries array, not DOM scraping"`

## Task 5: De-dup surface polish (P2, small)

**Files:**
- Modify: `static/js/admin.js` (headings only)

### Steps

- [ ] **Step 1: De-collide emoji headings:** Logs panel `📋 Server Logs` → `🧾 Server Logs` (Menu Layout keeps `📋`… actually Menu Layout uses `🧭` in the tab bar; align both H2s so no two admin sub-panels share an icon).
- [ ] **Step 2: Database tab note:** the status box and the Database KPI card read the same endpoint; add a one-line "Mirrored in the KPI strip above" hint instead of removing either (both have distinct value: summary vs detail).
- [ ] **Step 3:** `node --check` + `pytest tests\test_admin_js.py -q` green (i18n keys unchanged — headings are not `__()`-wrapped; if you i18n them, add keys to `static/js/i18n.js` first).
- [ ] **Step 4:** `git add static/js/admin.js && git commit -m "chore(admin): de-collide sub-panel icons; note KPI/db-status mirroring"`

## Task 6: Split `admin.js` into modules (P3)

**Files:**
- Create: `static/js/admin/core.js`, `users.js`, `roles.js`, `permissions.js`, `logs.js`, `sessions.js`, `database.js`, `menu.js`
- Modify: `static/js/admin.js` (becomes the loader/concatenation point), `static/index.html`, `tests/test_admin_js.py`, `tests/test_smart_core_js.py` (raw-fetch allowlist entries if file names change)

**Interfaces:**
- Preserve: every `window.*` export that exists today (`loadAdminPanel`, `switchAdminTab`, `editUser`, `saveAdminUser`, `editRole`, `saveRole`, `deleteRole`, `toggleRolePerms`, `editRolePermsInMatrix`, `permMatrixMarkDirty`, `permMatrixSaveAll`, `loadAdminLogs`, `adminLogsSearch`, `exportLogsCSV`, `loadSessions`, `adminForceLogoff`, `confirmDestructive` aliases, …). `tests/test_admin_js.py` pins many of these.

### Steps

- [ ] **Step 1: Add the div-balance regression test** (belongs in this task even though the bug it guards came from Task 5 of the earlier feature work): for each `#admin<Panel>` template literal in admin.js, assert `${`-free tag counts of `<div` and `</div>` balance within the Users-panel block. This test must pass before you start moving code.
- [ ] **Step 2: Move code bottom-up in dependency order:** `core.js` (esc/api/toasts/_adminKpi/confirm aliases) → `users.js` → `roles.js` → `permissions.js` → `logs.js` → `sessions.js` → `database.js` → `menu.js`. Keep everything classic-script global-scope based (same pattern as today) — no ES module imports inside admin.js, because `index.html` loads it as a plain script and other classic scripts call `window.confirmDestructive` etc.
- [ ] **Step 3:** `admin.js` ends up as a small loader that ensures load order, or is replaced by eight `<script>` tags in `index.html` in the same order — choose one, document it in the File Map, and update `tests/test_smart_core_js.py`'s file allowlist accordingly.
- [ ] **Step 4: Full behavioral pass in the running app:** every sub-tab renders; user/role modals save; matrix saves; logs CSV; force-logoff; menu layout CRUD; role simulator; visibility matrix.
- [ ] **Step 5:** Full suite: `& .\.venv\Scripts\python.exe -m pytest tests\ -q` green (pay attention to `test_admin_js.py`, `test_smart_core_js.py`, `test_menu_api.py`).
- [ ] **Step 6:** `git add static/js/admin* static/index.html tests/ && git commit -m "refactor(admin): split admin.js into focused modules under static/js/admin/ with div-balance guard"`

## Task 7 (optional, UX): Narrow-viewport sidebar

**Files:**
- Modify: `static/css/styles.css` (breakpoint `max-width:768px` block around line 1414)
- Modify: `static/js/renderSidebar.js` (`_showToggleOnMobile` width check)

**Context:** In windows narrower than 768px (e.g. docked preview panes) the sidebar becomes a hidden drawer and users report "menu not shown". Lowering the breakpoint restores the always-visible inline sidebar in those cases.

### Steps

- [ ] **Step 1: Change the sidebar media query** from `max-width:768px` to `max-width:600px` in both `styles.css` and the `_showToggleOnMobile` JS check.
- [ ] **Step 2: Verify at three widths** (≈583px, ≈700px, ≈900px): inline sidebar at ≥601px with collapse button; drawer + ☰ + overlay below; RTL correctness at each (`dir="rtl"` default).
- [ ] **Step 3:** `pytest tests\ -q` green (CSS-only, but confirms nothing else broke).
- [ ] **Step 4:** `git add static/css/styles.css static/js/renderSidebar.js && git commit -m "fix(ui): show inline sidebar down to 600px (drawer only below)"`

---

## Verification (whole plan)

- [ ] `& .\.venv\Scripts\python.exe -m pytest tests\ -q` — full suite green.
- [ ] `Get-Content static\js\admin.js -Raw | node --input-type=module --check` (or each split module) — syntax clean.
- [ ] Manual pass in the running app: System Control opens, all 8 sub-tabs work, KPI strip hydrated on load, visibility matrix matches the real sidebar, a non-superadmin role granted only `system.read_audit` can read `/logs`.
- [ ] Drift guards (`tests/test_admin_drift_guards.py`) fail if someone re-adds an unknown permission codename or a hard-coded tab list.

## Out of scope

- Merging `/admin/users/{id}/change-password` and `/auth/change-password` (different actors: admin-vs-self; document, don't unify).
- Changing any API response shapes.
- The AI-agents design (`docs/superpowers/specs/2026-09-18-ai-agents-design.md`) admin UI, which will add an Agents sub-tab — implement after Task 6 so it lands in the new module structure.
