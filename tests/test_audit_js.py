"""Static checks for the Audit screen frontend (static/js/audit.js + styles.css)."""
import os


def _read(name="audit.js"):
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_css():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_audit_exports_expected_api():
    js = _read()
    for name in ["initAudit", "loadAudit", "downloadAuditJSON", "downloadAuditCSV"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name


def test_executive_summary_strip_renderer_present():
    """The KPI strip lives behind a dedicated render function that reuses the
    existing .kpi-card classes."""
    js = _read()
    assert "function renderSummaryStrip(steps, da)" in js
    assert "class=\"kpi-card" in js
    for label in ["Risk Level", "Quality Score", "Completeness", "Rule Failures", "Outliers", "Data Confidence"]:
        assert f"__('{label}')" in js


def test_benchmark_range_bar_present():
    """Benchmark now shows the hospital as a dot on the peer min→max range with
    median/average ticks instead of the old deviation-only bar."""
    js = _read()
    for marker in ["range-track", "range-tick-med", "range-tick-avg", "range-dot", "range-scale"]:
        assert marker in js


def test_benchmark_keeps_zscore_breakdown():
    """The z calculation line must survive the visual rework."""
    js = _read()
    assert "z = (hospital value - peer average) / peer standard deviation" in js
    assert "zcalc" in js


def test_confidence_explanation_present():
    """The 'how confidence is calculated' box lists all five weighted signals."""
    js = _read()
    assert "How confidence is calculated" in js
    for signal in ["rule_compliance", "historical", "cross_hospital", "trend", "completeness"]:
        assert f"w('{signal}'" in js
    assert "Levels:" in js


def test_quality_score_breakdown_present():
    """Quality score renders a stacked contribution bar plus per-component
    formula explanation."""
    js = _read()
    assert "function renderQualityScore" in js
    assert "function stackBar" in js
    assert "How the quality score is calculated" in js
    assert "_QS_COLORS" in js


def test_consistent_card_helpers_present():
    js = _read()
    for helper in ["function sectTitle", "function subLabel", "function emptyState", "function explainBox", "function sevClass"]:
        assert helper in js


def test_css_classes_defined():
    css = _read_css()
    for cls in [".audit-kpis", ".audit-summary", ".audit-label", ".range-track", ".range-dot", ".range-legend"]:
        assert cls in css