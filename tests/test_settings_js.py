"""Static checks for the Settings screen frontend (settings.html + settings.js + styles.css)."""
import os, re

def _read(name="settings.js"):
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", name)
    with open(path, encoding="utf-8") as f:
        return f.read()

def _read_html(name="settings.html"):
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", name)
    with open(path, encoding="utf-8") as f:
        return f.read()

def _read_css():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        return f.read()

def _read_i18n():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(path, encoding="utf-8") as f:
        return f.read()

def test_settings_exports():
    js = _read()
    for name in ["loadAllSettings", "saveAllSettings", "showSettingsTab", "settingsLiveSearch"]:
        assert name in js, f"Missing {name}"

def test_settings_ux_helpers_present():
    js = _read()
    for fn in [
        "_settingsSnapshot", "_settingsChangedKeys", "_settingsRefreshDirtyUI",
        "_settingsInitUX", "_settingsWatchInputs",
        "_settingsTabOf", "_settingsSectionOf", "_settingsTabLabel",
        "_settingsFindCollapsible", "_settingsInjectPreviews",
        "_renderQualityPreview", "_renderConfPreview", "_refreshClinicalPreviews",
        "_settingsInjectClinicalPreviews",
        "_settingsGuardSwitch",
    ]:
        assert fn in js, f"Missing helper {fn}"

def test_settings_html_toolbar():
    html = _read_html()
    assert 'id="settingsToolbar"' in html, "Missing #settingsToolbar"
    assert 'id="settingsSearch"' in html, "Missing #settingsSearch"
    assert 'id="settingsSaveChip"' in html, "Missing #settingsSaveChip"
    assert 'id="settingsSearchInfo"' in html, "Missing #settingsSearchInfo"
    assert 'id="settingsSearchResults"' in html, "Missing #settingsSearchResults"

def test_settings_html_clinical_threshold_table():
    html = _read_html()
    assert 'cfg_clinical_' in html, "Clinical threshold cfg_ ids missing"
    assert 'settings-clinical' in html, "Clinical settings section missing"

def test_settings_js_imports_confirm_modal():
    js = _read()
    assert "from './confirm-modal.js'" in js

def test_settings_js_imports_esc():
    js = _read()
    assert "import { esc" in js or "import {esc" in js

def test_settings_save_totals_guard():
    """saveAllSettings must reject weight_total != 1.0."""
    js = _read()
    assert "weight_total" in js
    assert "cfgtotal_quality" in js
    assert "settings-section-invalid" in js

def test_settings_dirty_tracking():
    js = _read()
    assert "_settingsBaseline" in js
    assert "_settingsChangedKeys" in js
    assert "_settingsRefreshDirtyUI" in js

def test_settings_beforeunload():
    js = _read()
    assert "beforeunload" in js

def test_settings_leave_guard():
    js = _read()
    assert "_settingsGuardSwitch" in js
    assert "window._settingsGuardSwitch" in js

def test_settings_live_preview_quality():
    js = _read()
    assert "rule_compliance" in js
    assert "completeness" in js
    assert "consistency" in js
    assert "outlier" in js

def test_settings_live_preview_confidence():
    js = _read()
    assert "confidence_high" in js
    assert "confidence_medium" in js
    assert "confidence_low" in js

def test_settings_main_js_guard_hook():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    with open(path, encoding="utf-8") as f:
        main = f.read()
    assert "async function switchTab" in main or "async function switchTab" in main
    assert "_settingsGuardSwitch" in main

def test_settings_css_classes():
    css = _read_css()
    for cls in [
        ".settings-preview", ".settings-preview-title",
        ".settings-dirty-dot", ".settings-section-invalid",
        ".stbtn-dirty", ".settings-search-miss", ".clinical-preview",
    ]:
        assert cls in css, f"Missing CSS class {cls}"

def test_settings_i18n_coverage():
    """Every __() key in settings.js must appear in i18n.js translations."""
    i18n = _read_i18n()
    js = _read()
    keys = re.findall(r"__\('([^']+)'\)", js)
    for key in keys:
        assert f"'{key}': " in i18n, f"i18n missing settings key: {key}"
