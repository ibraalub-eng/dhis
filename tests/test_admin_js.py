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