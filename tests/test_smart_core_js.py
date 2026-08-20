"""Static tests for smart/core.js module."""
import os


def _read_core():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "core.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_core_exports_expected_api():
    js = _read_core()
    for name in ["smartState", "apiSmartGet", "smartShowLoading", "smartHideLoading",
                 "setSmartLoader", "showSmartSectionError", "showSmartSectionEmpty",
                 "_smartEscapeHtml", "smartTranslateFeature", "toggleSmartSection",
                 "setSmartMode", "registerSectionLoaders"]:
        assert f"export function {name}" in js or f"export async function {name}" in js or f"export const {name}" in js or f"export let {name}" in js, name


def test_core_has_single_escape_helper():
    js = _read_core()
    assert js.count("function _smartEscapeHtml") == 1


def test_core_has_mode_names():
    js = _read_core()
    assert "monthly" in js
    assert "time" in js
    assert "hospital" in js


def test_decision_board_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["loadDecisionBoard", "renderKPIs", "renderCriticalList",
                 "renderEarlyWarnings", "renderHealthyHospitals"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name
    assert "smart-decision-month" in js
    assert "smart-critical-list" in js


def test_decision_board_uses_decision_endpoint():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "/smart/decision-board/" in js