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
    assert "reloadSmartSections" in js


def test_entry_reloads_sections_on_month_change():
    """CRIT-1: month change re-runs registered section loaders."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "await loadDecisionBoard(month);" in js
    assert "reloadSmartSections()" in js


def test_entry_init_is_idempotent():
    """IMP-3: initSmartAnalytics must guard against duplicate observer/fetch on lang toggle."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "_smartInitDone" in js
    assert "if (_smartInitDone) return;" in js


def test_core_reloads_sections_and_reruns_reopened():
    """CRIT-1/IMP-1: core exposes reloadSmartSections and re-runs loaders on reopen."""
    js = _read_core()
    assert "export function reloadSmartSections" in js
    assert "_loadedKeys" in js
    assert "smart-section-opened" in js
    assert "runSectionLoader" in js


def test_timeline_consumes_months_hospitals_shape():
    """CRIT-3: loadTimeline reads {months, hospitals} from the backend, not d.timeline."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "const months = d.months || [];" in js
    assert "const hospitals = d.hospitals || [];" in js
    assert "h.scores" in js
    assert "h.severities" in js


def test_decision_board_sets_smart_state_data():
    """CRIT-2: loadDecisionBoard populates smartState.data so KPI modals work."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "smartState.data = data;" in js
    assert "smartState.data = data" in js


def test_kpi_modals_lazy_fetch_missing_data():
    """CRIT-2: governorates/factors modals fetch geo/anomalies lazily from section endpoints."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "decision-board.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "apiSmartGet(`/smart/geo/${month}`)" in js
    assert "apiSmartGet(`/smart/anomalies/${month}`)" in js


def test_drilldown_renders_factors_into_modal():
    """IMP-4: openDrilldown renders the factor table into the modal container."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "hospital.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "renderHospitalFactors(d.anomaly, d.explanation, 'smart-drilldown-factors');" in js
    assert "containerId || 'smart-hospital-factors'" in js


def test_xgboost_renders_walk_forward_and_scatter():
    """IMP-4: dead elements smart-walk-forward / smart-predicted-scatter are now rendered."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "export function renderWalkForward" in js
    assert "export function renderPredictedScatter" in js
    assert "renderWalkForward(xgb);" in js
    assert "renderPredictedScatter(xgb);" in js
    assert "smart-walk-forward" in js
    assert "smart-predicted-scatter" in js


def test_feature_importance_fetches_explanations_lazily():
    """CRIT-2: feature importance tab fetches /smart/anomalies since the
    decision-board payload (smartState.data) no longer carries explanations."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "apiSmartGet(`/smart/anomalies/${month}`)" in js or "fetchSection(`/smart/anomalies/${month}`" in js
    assert "renderFeatureImportance(d.explanations || [])" in js


def test_composite_patterns_uses_correct_schema_fields():
    """renderCompositePatterns must use summary_ar and arabic_names/indicators
    — NOT name/description which do not exist on CompositePattern."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "summary_ar" in js
    assert "arabic_names" in js
    assert "p.name" not in js, "p.name is not a CompositePattern field"


def test_patterns_tab_loads_stratified_analysis():
    """Stratified analysis must be loaded alongside patterns and lag analysis."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "advanced.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "/smart/stratified/${month}" in js
    assert "renderStratifiedAnalysis" in js


def test_stratified_chart_container_exists():
    """HTML must contain the stratified chart container."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert 'id="smart-stratified-chart"' in html
    assert 'id="smart-strat-indicator"' in html


def test_report_uses_server_endpoints():
    """IMP-2: report/export/comparison flow through server-side endpoints."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart", "report.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "/comparative/comprehensive-report/" in js
    assert "/export/full-data" in js
    assert "/comparative/advanced-comparison/" in js


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