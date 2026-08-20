"""Tests for the full data export feature."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# --- Engine helpers ---

def test_sanitize_converts_numpy_scalars(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"score": np.float64(0.45), "count": np.int64(7), "nan": float("nan"), "inf": float("inf")})
    assert out["score"] == 0.45
    assert isinstance(out["score"], float)
    assert out["count"] == 7
    assert isinstance(out["count"], int)
    assert out["nan"] == 0.0
    assert out["inf"] == 0.0


def test_sanitize_converts_numpy_array(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"arr": np.array([1.0, 2.5, 3.0])})
    assert out["arr"] == [1.0, 2.5, 3.0]
    assert isinstance(out["arr"], list)
    assert all(isinstance(v, float) for v in out["arr"])


def test_get_available_months_empty(db_session):
    from app.engine.export import _get_available_months
    assert _get_available_months(db_session) == []


def test_get_available_months_distinct_sorted(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_available_months
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=90),
    ])
    db_session.commit()
    assert _get_available_months(db_session) == ["2026-05", "2026-06"]


def test_get_master_data_returns_all_sections(db_session):
    from app.engine.export import _get_master_data
    md = _get_master_data(db_session)
    assert "governorates" in md
    assert "hospitals" in md
    assert "indicators" in md
    assert "hospital_indicator_configs" in md
    assert len(md["hospitals"]) == 3
    assert len(md["indicators"]) > 0
    h = md["hospitals"][0]
    for key in ("id", "name", "region", "address", "governorate_name",
                "hospital_type_name", "facility_ownership_name", "facility_type_name", "is_active"):
        assert key in h


def test_get_indicator_values_grouped_by_month(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_indicator_values
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=300, source_file="x.xlsx"))
    db_session.commit()
    result = _get_indicator_values(db_session, ["2026-06"])
    assert "2026-06" in result
    row = result["2026-06"][0]
    assert row["hospital_id"] == hosp.id
    assert row["hospital_name"] == hosp.name
    assert row["indicator_code"] == "2"
    assert row["indicator_name"] == ind.name
    assert row["value"] == 300
    assert row["source_file"] == "x.xlsx"


# --- build_full_export ---

def test_build_full_export_structure(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["meta"]["scope"] == "2026-06"
    assert pkg["meta"]["lang"] == "ar"
    assert pkg["meta"]["schema_version"] == 1
    assert "master_data" in pkg
    assert "indicator_values" in pkg
    assert "analysis" in pkg
    assert "2026-06" in pkg["analysis"]
    assert isinstance(json.loads(json.dumps(pkg, ensure_ascii=False)), dict)


def test_build_full_export_smart_sections(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    smart = pkg["analysis"]["2026-06"]["smart"]
    for key in ("kpi", "anomalies", "clustering", "correlations", "residuals",
                "stratified", "explanations", "geo", "patterns"):
        assert key in smart


@patch("app.engine.export.run_smart_analytics")
def test_build_full_export_month_error_embedded(mock_analytics, db_session):
    mock_analytics.side_effect = RuntimeError("boom")
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert "error" in pkg["analysis"]["2026-06"]
    assert "boom" in pkg["analysis"]["2026-06"]["error"]


def test_build_full_export_all_months(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import build_full_export
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    pkg = build_full_export(db_session, "all", "ar")
    assert pkg["meta"]["scope"] == "all"
    assert set(pkg["indicator_values"].keys()) == {"2026-05", "2026-06"}
    assert set(pkg["analysis"].keys()) == {"2026-05", "2026-06"}


def test_build_full_export_comprehensive_report_null_when_uncached(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["analysis"]["2026-06"]["comprehensive_report"] is None


@patch("app.engine.comparative.report_generator._call_api")
def test_export_never_calls_ai(mock_api, db_session):
    from app.engine.export import build_full_export
    build_full_export(db_session, "all", "ar")
    assert mock_api.call_count == 0


def test_build_full_export_report_from_cache(db_session):
    from app.engine.comparative.report_cache import store_report
    from app.engine.export import build_full_export
    store_report(db_session, "2026-06", "ar", {"report": "نص مخزن", "report_source": "ai", "month": "2026-06"})
    pkg = build_full_export(db_session, "2026-06", "ar")
    rep = pkg["analysis"]["2026-06"]["comprehensive_report"]
    assert rep == {"report": "نص مخزن", "report_source": "ai"}


def test_build_full_export_no_data_raises(db_session):
    from app.models import Hospital
    from app.engine.export import build_full_export, NoDataError
    db_session.query(Hospital).delete()
    db_session.commit()
    try:
        build_full_export(db_session, "all", "ar")
        assert False, "expected NoDataError"
    except NoDataError:
        pass


# --- API endpoint ---

def test_export_endpoint_returns_json_download(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["meta"]["scope"] == "2026-06"


def test_export_endpoint_all_months(client, db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "en"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["scope"] == "all"
    assert data["meta"]["lang"] == "en"
    assert set(data["indicator_values"].keys()) == {"2026-05", "2026-06"}


def test_export_endpoint_invalid_lang_422(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "xx"})
    assert resp.status_code == 422


def test_export_endpoint_no_data_404(client, db_session):
    from app.models import Hospital
    db_session.query(Hospital).delete()
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "ar"})
    assert resp.status_code == 404
    assert "لا توجد بيانات" in resp.json()["detail"]


def test_export_endpoint_serializes_without_error(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@patch("app.api.export.build_full_export")
def test_export_endpoint_500_on_engine_failure(mock_build, client):
    mock_build.side_effect = RuntimeError("boom")
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 500


# --- Frontend structure ---

def test_smart_page_has_export_button():
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-export-btn") is not None
    assert soup.find(id="smart-export-scope") is not None


def test_merged_page_has_report_controls():
    """التحليل الذكي المدمج يحتوي على توليد التقرير الشامل ومقارنته"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-report-generate") is not None
    assert soup.find(id="smart-report-lang-toggle") is not None
    assert soup.find(id="smart-comparison-type") is not None
    assert soup.find(id="smart-report-kpi-dashboard") is not None
    assert soup.find(id="smart-comparison-chart") is not None
    assert soup.find(id="smart-peer-comparison-table") is not None


def test_smart_js_has_export_handler():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function smartExportData" in content
    assert "/export/full-data?month=" in content
    assert "lang=" in content


def test_merged_js_has_report_handlers():
    """smart-analytics.js يحتوي على منطق التقرير الشامل المدمج"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function smartGenerateComprehensiveReport" in content
    assert "function smartToggleReportLang" in content
    assert "function smartGenerateAdvancedComparison" in content
    assert "/comparative/comprehensive-report/" in content
    assert "/comparative/advanced-comparison/" in content
    assert "renderSeverityDonut" in content
    assert "renderScoreHistogram" in content
    assert "renderPredictedScatter" in content


def test_decision_board_rendered_in_frontend():
    """لوحة القرارات التنفيذية موجودة في HTML وJS وتُستدعى بعد التقرير."""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    assert 'id="smart-decision-board"' in html
    assert 'id="smart-decision-verdict"' in html
    assert 'id="smart-decision-hotspots"' in html
    assert 'id="smart-decision-watchlist"' in html
    assert 'id="smart-decision-priorities"' in html

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(js_path, encoding="utf-8") as f:
        js = f.read()
    assert "function smartRenderDecisionBoard" in js
    assert "smartRenderDecisionBoard(result.data.decision)" in js
    assert "قرارات تنفيذية" in js
    assert "قرارات تنفيذية" in html


def test_merged_page_has_animated_timeline():
    """الصفحة المدمجة تحتوي على الرسم المتحرك لتطور درجات الشذوذ"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-timeline-chart") is not None
    assert soup.find(id="smart-timeline-badge") is not None
    assert soup.find(id="smart-timeline-text") is not None


def test_merged_js_has_animated_timeline_handler():
    """smart-analytics.js يحتوي على منطق الرسم المتحرك"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function loadAnomalyTimeline" in content
    assert "function renderAnomalyTimeline" in content
    assert "/smart/anomaly-timeline" in content
    assert "Plotly.addFrames" in content


# --- Merged tabs (AI Reports -> Clinical Intelligence, Rule Failures -> Alerts) ---

def test_clinical_page_has_unified_analysis_bar():
    """clinical.html يحتوي على شريط الفلاتر الموحّد: زر واحد + حاوية نتائج واحدة"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "clinical.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="clinicalRunBtn") is not None
    assert soup.find(id="clinicalHospitalSelect") is not None
    assert soup.find(id="clinicalMonthSelect") is not None
    assert soup.find(id="clinicalResults") is not None
    assert soup.find(id="reportProgressWrap") is not None


def test_clinical_js_has_unified_analysis_handler():
    """clinical.js يحتوي على runAnalysis الموحّد والبيانات الدفعية"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "clinical.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function runAnalysis" in content
    assert "function applyReportFilter" in content
    assert "function openBatchDetail" in content
    assert "/analysis/generate-report" in content


def test_alerts_page_has_rule_failures_table():
    """alerts.html يحتوي على جدول فشل القواعد المدمج من Rule Failures"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "alerts.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="ruleFailTable") is not None
    assert soup.find(id="ruleFailTbody") is not None
    assert soup.find(id="ruleFailSummary") is not None
    assert soup.find(id="ruleFailHospitalFilter") is not None
    assert soup.find(id="alertSummaryBar") is not None


def test_alerts_js_still_has_overview_handlers():
    """alerts.js يحتفظ بمعالجات النظرة العامة بعد الدمج"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "alerts.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function loadAlerts" in content
    assert "function updateAlertBadge" in content
    assert "renderAlertOverview" in content
    assert "renderAlertTable" not in content


def test_index_has_no_removed_tabs():
    """index.html لم يعد يحتوي على تبويبي AI Reports وRule Failures المنفصلين"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "data-tab=\"ai-reports\"" not in content
    assert "data-tab=\"rulefailures\"" not in content
    assert "tab-ai-reports" not in content
    assert "tab-rulefailures" not in content


# --- Merged comparative-analysis tab (Trends + Hospital Comparison) ---

def test_analysis_page_has_both_modes():
    """analysis.html يحتوي على قسمي الاتجاهات والمقارنة مع مبدّل داخلي"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "analysis.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    # Mode switcher
    assert soup.find(id="analysisModeTrend") is not None
    assert soup.find(id="analysisModeCompare") is not None
    # Trend mode elements
    assert soup.find(id="analysisTrendSection") is not None
    assert soup.find(id="trendHospitalSelect") is not None
    assert soup.find(id="qualityTrendContent") is not None
    assert soup.find(id="trendTbody") is not None
    # Compare mode elements
    assert soup.find(id="analysisCompareSection") is not None
    assert soup.find(id="compareMonthSelect") is not None
    assert soup.find(id="compareIndicatorFilter") is not None
    assert soup.find(id="compareTbody") is not None
    assert soup.find(id="mlClusters") is not None


def test_analysis_js_has_mode_handlers():
    """validation.js يحتوي على دوال المبدّل والتهيئة للتبويب المدمج"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "validation.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function switchAnalysisMode" in content
    assert "function initAnalysis" in content
    assert "function initTrends" in content
    assert "function initCompare" in content


def test_app_js_exports_analysis_handlers():
    """app.js يصدّر دوال التبويب المدمج"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "app.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "window.switchAnalysisMode = switchAnalysisMode" in content
    assert "window.initAnalysis = initAnalysis" in content


def test_index_has_analysis_tab_no_old_tabs():
    """index.html يستبدل تبويبي trends/compare بتبويب analysis واحد"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "data-tab=\"analysis\"" in content
    assert "/static/tabs/analysis.html" in content
    assert "data-tab=\"trends\"" not in content
    assert "data-tab=\"compare\"" not in content
    assert "tab-trends" not in content
    assert "tab-compare" not in content


# --- Root Cause navigation from Smart Analytics ---

def test_smart_js_has_root_cause_button_handler():
    """smart-analytics.js يعرّف معالج الانتقال إلى السبب الجذري"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "window.smartGoRootCause = function" in content
    assert "window.goRootCause(" in content
    # الزر في جدول الشذوذ يمرر معرّف المستشفى والشهر الحالي
    assert "smartGoRootCause(${hid}" in content
    assert "smartCurrentMonth" in content


def test_settings_js_has_root_cause_context_helpers():
    """settings.js ينقل سياق المستشفى والشهر إلى تبويب السبب الجذري"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "export function goRootCause" in content
    assert "export function applyRootCauseContext" in content
    assert "_rootCauseContext" in content
    assert "SwitchTab('root-cause')" in content
    assert "loadRootCause()" in content
    # initRootCause يطبّق السياق المعلّق بعد اكتمال ملء القوائم
    assert "applyRootCauseContext()" in content


def test_app_js_exports_root_cause_navigation():
    """app.js يصدّر goRootCause على window"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "app.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "goRootCause" in content
    assert "window.goRootCause = goRootCause" in content


def test_smart_table_has_generated_arabic_sentence():
    """جدول الشذوذ يعرض جملة التفسير العربية المولّدة ويربطها بزر السبب الجذري"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # عمود التفسير في الجدول
    assert "التفسير" in content
    # الجملة المولّدة من text_explanation معروضة وقابلة للنقر نحو السبب الجذري
    assert "text_explanation" in content
    assert "smartGoRootCause(" in content
    assert "const sentence = expMap[a.hospital_name]?.text_explanation" in content


def test_smart_sentence_has_ai_badge_and_tooltip():
    """الجملة المولّدة تحمل شارة AI مع tooltip يشرح منهجية SHAP + المقارنة الطبقية"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "AI</span>" in content
    assert "SHAP" in content
    assert "متوسط مجموعة النظير" in content
    assert "cursor:help" in content


def test_smart_sentence_has_factor_data_link_and_table():
    """رابط سريع لعرض بيانات العوامل الفعلية، ودالة تُرسم جدول القيم مقابل النظير"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "بيانات العوامل الفعلية" in content
    assert "window.smartDrilldown(${hid})" in content
    assert "function renderDrilldownFactorTable" in content
    assert "smart-drilldown-factors" in content
    assert "متوسط النظير" in content


def test_smart_correlation_text_guards_pearson_r():
    """مخطط الارتباطات يحمي pearson_r من أن يكون undefined/null قبل toFixed."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "typeof r === 'number' && isFinite(r)" in content
    assert "r.toFixed(2)" in content


def test_smart_cluster_profiles_rendered():
    """التحليل الذكي يعرض ملفات تعريف المجموعات (دالة + حاوية HTML + استدعاء)."""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()
    assert "function renderClusterProfiles" in js
    assert "renderClusterProfiles(d.clustering?.profiles)" in js
    assert "ملفات تعريف المجموعات" in js

    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "smart-cluster-profiles" in html


def test_smart_composite_patterns_rendered():
    """التحليل الذكي يعرض الأنماط المركبة (دالة + حاوية HTML + استدعاء + شرح منهجية)."""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()
    assert "function renderCompositePatterns" in js
    assert "renderCompositePatterns(d.patterns)" in js
    assert "Lift" in js
    assert "الدعم" in js
    assert "_smartEscapeHtml" in js

    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "smart-composite-patterns" in html
    assert "أنماط وقيادة" in html
    assert "smart-lag-analysis" in html


def test_smart_drilldown_modal_has_factor_container():
    """نافذة التفاصيل تحتوي على حاوية جدول قيم العوامل الفعلية"""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-drilldown-factors") is not None
    assert soup.find(id="smart-drilldown-text") is not None
    assert soup.find(id="smart-drilldown-name") is not None


# --- Interactive Plotly quality trend chart (replaces static SVG) ---

def test_analysis_js_has_plotly_quality_trend():
    """validation.js يستبدل مخطط SVG الثابت بمخطط Plotly تفاعلي لدرجة الجودة"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "validation.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # دالة الرسم التفاعلي ومبدّل المقياس
    assert "function renderQualityTrendPlot" in content
    assert "window.switchQualityTrendMetric = function" in content
    assert "Plotly.newPlot" in content
    assert "qualityTrendPlot" in content
    # حاوية الرسم حاضرة في HTML المُصيّر
    assert '<div id="qualityTrendPlot"' in content
    # ملء المنطقة تحت الخط (areas)
    assert "fill: 'tozeroy'" in content
    assert "fillcolor: cfg.color" in content
    # تلميحات hover تعرض مكونات الدرجة
    assert "hovermode: 'x unified'" in content
    assert "خصم الشذوذ" in content
    # SVG الثابت القديم لم يعد موجوداً (رسم Sparkline يحتفظ بـ svg بلا viewBox)
    assert "Build SVG chart" not in content


def test_analysis_js_has_metric_toggle_labels():
    """أزرار التبديل تعرض أسماء المكونات بالعربية وتربط كل مقياس ببياناته"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "validation.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "درجة الجودة" in content
    assert "الاكتمال" in content
    assert "الالتزام" in content
    assert "الاتساق" in content
    assert "data-metric=\"score\"" in content
    assert "data-metric=\"completeness\"" in content
    assert "data-metric=\"rule_compliance\"" in content
    assert "data-metric=\"consistency\"" in content
    # بيانات المكونات تُقرأ من الرد الخلفي quality-trend
    assert "_qtValue(s, 'completeness')" in content
    assert "_qtValue(s, 'rule_compliance')" in content
    assert "_qtValue(s, 'consistency')" in content
    assert "s[metric]" in content
    # عند اختيار مكوّن تظهر درجة الجودة كخط مرجعي متقطع
    assert "درجة الجودة (مرجع)" in content


def test_styles_have_quality_trend_toggle_css():
    """styles.css يعرّف أنماط أزرار التبديل لمخطط الجودة"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert ".qt-metric-btn" in content
    assert ".qt-metric-btn:hover" in content


def test_smart_redesign_structure():
    """الشاشة الجديدة: شريط أوضاع + لوحة قرار + أقسام قابلة للطي + مودال منهجية."""
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    # شريط الأوضاع الثلاثة
    assert soup.find(id="smart-mode-monthly") is not None
    assert soup.find(id="smart-mode-time") is not None
    assert soup.find(id="smart-mode-hospital") is not None
    # لوحة القرار أعلى الصفحة
    assert soup.find(id="smart-decision-board") is not None
    assert soup.find(id="smart-kpi-container") is not None
    assert soup.find(id="smart-critical-list") is not None
    # أقسام قابلة للطي
    assert len(soup.find_all(class_="smart-section-card")) >= 4
    # مودال المنهجية الموصول
    assert soup.find(id="smart-methodology-modal") is not None
    assert soup.find(id="smart-methodology-btn") is not None
    # أقسام الأوضاع الثلاثة
    assert soup.find(id="smart-monthly-panel") is not None
    assert soup.find(id="smart-time-panel") is not None
    assert soup.find(id="smart-hospital-panel") is not None
    # إمكانية الوصول للمودالات
    drill = soup.find(id="smart-drilldown-modal")
    assert drill is not None
    assert drill.get("role") == "dialog"
    assert drill.get("aria-modal") == "true"
