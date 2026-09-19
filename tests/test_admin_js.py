"""Static checks for the System Control frontend (admin.js + styles.css)."""
import os, re

def _read_css():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        return f.read()

def _read_i18n():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(path, encoding="utf-8") as f:
        return f.read()

def _read(name):
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", name)
    with open(path, encoding="utf-8") as f:
        return f.read()

def test_admin_exports_window_functions():
    js = _read("admin.js")
    for fn in [
        "loadAdminPanel", "loadAdminLogs", "loadSessions", "clearAdminLogs",
        "exportLogsCSV", "deleteRole", "deactivateUser", "switchAdminTab",
        "adminForceLogoff", "adminLogsSearch", "adminLogsClearSearch",
        "confirmDestructive", "confirmWarning", "confirmAction",
    ]:
        assert f"window.{fn} =" in js or fn in js, f"Missing {fn}"

def test_admin_global_confirm_aliases():
    """Classic scripts call bare confirmDestructive/confirmWarning; the aliases
    must be exposed on window from within the admin IIFE."""
    js = _read("admin.js")
    assert "window.confirmDestructive = function(opts)" in js
    assert "window.confirmWarning = function(opts)" in js
    assert "window.confirmAction = function(opts)" in js

def test_admin_dangerous_actions_use_styled_confirm():
    js = _read("admin.js")
    assert "window.confirmDestructive(" in js
    assert "window.confirm(" not in js or "confirm(" not in js.replace("window.confirm", "")

def test_admin_kpi_strip():
    js = _read("admin.js")
    for kpi in ["adminKpiOnline", "adminKpiLogs", "adminKpiDb"]:
        assert f"id=\"{kpi}\"" in js or f"'{kpi}'" in js, f"Missing KPI {kpi}"

def test_admin_logs_search():
    js = _read("admin.js")
    assert "logsSearchFilter" in js
    assert "_logsEntries" in js
    assert "_adminRenderLogs" in js

def test_admin_logs_badge_rows():
    js = _read("admin.js")
    assert "admin-log-row" in js
    assert "log-badge-" in js

def test_admin_force_logoff_fetch():
    js = _read("admin.js")
    assert "'/auth/sessions/kick-user'" in js

def test_admin_sessions_chip_css():
    css = _read_css()
    assert ".session-chip" in css
    assert ".admin-chip" in css

def test_admin_css_classes():
    css = _read_css()
    for cls in [".admin-kpis", ".admin-log-row", ".log-badge", ".log-badge-ERROR"]:
        assert cls in css, f"Missing CSS class {cls}"

def test_admin_i18n_coverage():
    """Every __() key in admin.js must appear in i18n.js translations."""
    i18n = _read_i18n()
    js = _read("admin.js")
    keys = re.findall(r"__\('([^']+)'\)", js)
    for key in keys:
        assert f"'{key}': " in i18n, f"i18n missing admin key: {key}"


def test_admin_users_table_permissions_column():
    """Users table must render direct per-user permissions separately from roles."""
    js = _read("admin.js")
    assert "admin-user-perm" in js
    assert "direct_permissions" in js


def test_admin_user_modal_direct_permission_checkboxes():
    """Edit User modal must have a Direct Permissions checkbox list distinct from Roles."""
    js = _read("admin.js")
    assert "adminUserPermCheckboxes" in js
    assert "admin-user-perm-cb" in js


def test_admin_save_user_sends_permission_ids():
    """saveAdminUser must send the checked direct permission ids."""
    js = _read("admin.js")
    assert "permission_ids" in js


def test_admin_user_edit_fills_direct_permissions():
    """editUser must check the user's assigned direct permissions."""
    js = _read("admin.js")
    assert "data.direct_permissions" in js


def test_admin_users_roles_permissions_are_separate_tabs():
    """Users, Roles, and Permissions must be separate admin tab buttons
    backed by distinct sub-panels (no longer one combined Users & Roles tab)."""
    js = _read("admin.js")
    assert "switchAdminTab('roles')" in js
    assert "switchAdminTab('permissions')" in js
    for panel in ["adminUsersSubPanel", "adminRolesSubPanel", "adminPermsSubPanel"]:
        assert f'id="{panel}"' in js, f"Missing sub-panel {panel}"
    # switchAdminTab must toggle the three sub-panels
    assert 'document.getElementById("adminUsersSubPanel")' in js
    assert 'document.getElementById("adminRolesSubPanel")' in js
    assert 'document.getElementById("adminPermsSubPanel")' in js


def test_admin_roles_tab_expandable_permission_codenames():
    """Roles tab rows must be expandable to reveal the role's permission
    codenames, resolved from /admin/roles permission_ids + the permission list,
    with state kept across re-renders."""
    js = _read("admin.js")
    assert "toggleRolePerms(" in js
    assert "window.toggleRolePerms" in js
    assert "rolePermsRow-" in js
    assert "roleCaret-" in js
    assert "_expandedRoleIds" in js
    assert "admin-role-perm-chip" in js


def test_admin_role_permission_matrix():
    """Permissions tab must render a role x permission checkbox matrix that
    saves changed roles straight to PUT /admin/roles/{id}."""
    js = _read("admin.js")
    assert "perm-matrix-cb" in js
    assert "permMatrixMarkDirty" in js
    assert "permMatrixSaveAll" in js
    assert "permMatrixDirty" in js
    # Saves per role via the existing role update endpoint
    assert "'/admin/roles/' + roleId" in js
    assert "permission_ids: permIds" in js


def test_admin_permissions_tab_has_no_duplicate_permissions_list():
    """The Permissions tab must NOT render a second standalone list of all
    permission codenames — the matrix rows already show each codename once."""
    js = _read("admin.js")
    assert "Available Permissions (${perms.length})" not in js
    # Matrix rows must still show codename + description
    assert "perm-matrix-cb" in js


def test_admin_roles_tab_links_to_permission_matrix():
    """Roles tab rows must offer a jump into the matrix for editing that
    role's permissions (single edit surface)."""
    js = _read("admin.js")
    assert "editRolePermsInMatrix" in js
    assert "permCol-" in js


# ── Task 3: KPI strip hydrated on panel load ──────────────────────

def test_admin_kpi_hydration_on_panel_load():
    """The KPI strip (Online / Logs / Database) must hydrate as soon as the
    admin panel loads — not lazily on first visit to each sub-tab. The
    hydration must be a named function that loadAdminPanel calls, and it
    must fetch all three KPI sources."""
    js = _read("admin.js")
    assert "window._hydrateAdminKpis = " in js, "missing _hydrateAdminKpis"
    # loadAdminPanel must invoke it after the panel fetches succeed
    panel_idx = js.index("window.loadAdminPanel = async function")
    hydrate_idx = js.index("window._hydrateAdminKpis = ")
    assert re.search(r"_hydrateAdminKpis\(\)", js[panel_idx:panel_idx + 6000]) or \
           js.find("_hydrateAdminKpis()", panel_idx) != -1, (
        "loadAdminPanel must call _hydrateAdminKpis()"
    )
    # Hydration must cover all three KPI sources
    fn = js[hydrate_idx:hydrate_idx + 2500]
    assert "'/auth/sessions?limit=100'" in fn or '"/auth/sessions?limit=100"' in fn
    assert "'/logs?level=WARNING&limit=200'" in fn or '"/logs?level=WARNING&limit=200"' in fn
    assert 'api("/config/database-status")' in fn or "api('/config/database-status')" in fn


def test_admin_kpi_hydration_does_not_disturb_subtab_loaders():
    """Visiting Logs/Sessions/Database tabs must still refresh their panels
    (idempotent), and the hydration path must set the KPIs via _adminKpi."""
    js = _read("admin.js")
    assert 'if(tab==="logs"){loadAdminLogs();_startLogsAutoRefresh();}' in js
    assert 'if(tab==="sessions"){loadSessions();}' in js
    assert 'if(tab==="database"){loadAdminDbStatus();' in js
    hydrate_idx = js.index("window._hydrateAdminKpis = ")
    fn = js[hydrate_idx:hydrate_idx + 2500]
    assert fn.count("_adminKpi(") >= 3, "hydration must set all three KPI cards"


# ── Task 4: logs CSV export reads the data, not the DOM ────────────

def test_admin_logs_csv_export_is_data_driven():
    """exportLogsCSV must serialize window._logsEntries directly — DOM
    scraping silently breaks whenever the row layout changes."""
    js = _read("admin.js")
    start = js.index("window.exportLogsCSV = function")
    fn = js[start:js.index("};", start) + 2]
    assert "window._logsEntries" in fn, "export must read _logsEntries"
    assert "querySelectorAll" not in fn, "export must not scrape the DOM"
    # filename pattern preserved
    assert "server-logs-" in fn
    # empty case handled with a user-visible warning, not a silent no-op
    assert "toastWarning" in fn or "toast" in fn.lower()


def test_admin_logs_csv_escapes_csv_specials():
    """CSV fields must be quoted so commas/quotes/newlines in log messages
    cannot corrupt the file."""
    js = _read("admin.js")
    start = js.index("window.exportLogsCSV = function")
    fn = js[start:js.index("};", start) + 2]
    # every field goes through a quoting helper that doubles embedded quotes
    assert 'replace(/"/g' in fn or 'csvEscape' in fn
    assert 'Time,Level,Logger,Message' in fn