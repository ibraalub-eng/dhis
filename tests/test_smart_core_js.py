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


def test_charts_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "charts.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["smartChartTheme", "renderPlot", "makeLineChart", "makeBarChart",
                 "makeScatter", "makeHeatmap", "makeDonut", "renderWaterfall"]:
        assert f"export function {name}" in js or f"export const {name}" in js, name
    assert "Plotly" in js


def test_advanced_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["initAdvancedTabs", "loadAdvancedSection", "loadClustersTab",
                 "loadCorrelationsTab", "loadPatternsTab", "loadXGBoostTab"]:
        assert f"export function {name}" in js, name


def test_advanced_uses_section_endpoints():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for path_part in ["/smart/clusters/", "/smart/correlations/", "/smart/patterns/",
                      "/smart/lag-analysis/", "/smart/xgboost/"]:
        assert path_part in js, path_part


def test_geo_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "geo-regional.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["loadGeoSection", "renderGeoMap", "renderGovernorates", "renderRegionalAnalysis"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name
    assert "/smart/geo/" in js
    assert "smart-geo-map" in js


def test_hospital_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "hospital.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["initHospitalSelect", "loadHospitalMode", "renderTrend", "renderHospitalForecast"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name
    assert "window.smartDrilldown" in js
    assert "window.smartGoRootCause" in js
    assert "/smart/drilldown/" in js
    assert "/smart/trend/" in js


def test_report_module_exists():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "report.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    for name in ["generateComprehensiveReport", "toggleReportLang", "exportSmartData", "renderComparison"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name
    assert "window.smartGenerateComprehensiveReport" in js
    assert "window.smartExportData" in js
    assert "smart-comparison-type" in js
    assert "smart-export-scope" in js


def test_entry_is_module_and_wires_modules():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "import" in js and "from './smart/" in js
    for mod in ["core.js", "decision-board.js", "charts.js", "advanced.js",
                "geo-regional.js", "hospital.js", "report.js"]:
        assert f"from './smart/{mod}'" in js, mod
    assert "initSectionObserver" in js
    assert "trapFocus" in js
    assert "registerSectionLoaders" in js


def test_index_html_loads_module_entry():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert 'type="module"' in html and "js/smart-analytics.js" in html


def test_i18n_covers_smart_keys():
    import os
    import re
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    i18n_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    with open(i18n_path, encoding="utf-8") as f:
        i18n = f.read()
    keys = re.findall(r'data-i18n="([^"]+)"', html)
    assert keys, "no data-i18n keys found"
    for key in keys:
        assert key in i18n, key


def test_single_escape_helper_across_modules():
    import os
    root = os.path.join(os.path.dirname(__file__), "..", "static", "js")
    total = 0
    for fname in os.listdir(os.path.join(root, "smart")):
        if fname.endswith(".js"):
            with open(os.path.join(root, "smart", fname), encoding="utf-8") as f:
                total += f.read().count("function _smartEscapeHtml")
    assert total == 1