"""Smart Forecast screen — the prediction section split out of Smart Analytics.

The XGBoost/forecast block (predictions table, trajectory, accuracy, tracking,
signals, per-indicator forecast, walk-forward, scatter) used to live inside
``static/tabs/smart-analytics.html``. These tests pin the separation: the
moved markup lives on its own screen, and every registration touchpoint a new
tab needs (menu registry, index.html, init hook, permissions, sidebar
fallback, i18n, upload reset) is wired for ``smart-forecast``.
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "..")

FORECAST_IDS = [
    "smart-forecast-section",
    "smart-xgboost-predictions",
    "smart-forecast-timeline",
    "smart-forecast-accuracy",
    "smart-forecast-tracking",
    "smart-forecast-signals",
    "smart-indicator-forecast",
    "smart-indicator-select",
    "smart-indicator-hospitals",
    "smart-indicator-forecast-output",
    "smart-walk-forward",
    "smart-predicted-scatter",
    "smart-horizon-select",
    # single-hospital forecast (moved from the analytics hospital mode)
    "smart-hospital-forecast",
    "smart-forecast-hospital-select",
]


def _read(*parts):
    with open(os.path.join(BASE, *parts), encoding="utf-8") as f:
        return f.read()


def test_forecast_markup_moved_to_its_own_screen():
    """كل حاويات التنبؤ انتقلت، ولم يبقَ منها شيء في شاشة التحليل الذكي."""
    forecast = _read("static", "tabs", "smart-forecast.html")
    analytics = _read("static", "tabs", "smart-analytics.html")
    for el_id in FORECAST_IDS:
        assert el_id in forecast, f"{el_id} must live on the Smart Forecast screen"
        assert el_id not in analytics, f"{el_id} must be gone from Smart Analytics"
    # the per-hospital forecast left the hospital mode as well (this task)
    assert "smart-hospital-forecast" not in analytics
    # the forecast screen owns its month control + the xgboost section state
    assert 'id="smart-forecast-month-select"' in forecast
    assert 'data-smart-loader="hospital-forecast"' in forecast
    assert 'data-smart-loader="hospital-forecast"' not in analytics
    assert 'data-smart-loader="xgboost"' in forecast
    assert 'data-smart-loader="xgboost"' not in analytics
    # removing one card must not collapse the analytics layout guard
    assert analytics.count('class="smart-section-card"') >= 5


def test_forecast_entry_is_a_registered_module():
    js = _read("static", "js", "smart-forecast.js")
    assert "window.initSmartForecast = initSmartForecast;" in js
    assert "from './smart/advanced.js'" in js
    for name in ["loadXGBoostTab", "initHorizonSelect", "getForecastMonth"]:
        assert name in js, name
    # idempotent init (the language toggle re-runs the tab init hook)
    assert "_initDone" in js and "if (_initDone) return;" in js
    # the screen must not read/write the analytics month state
    assert "smartState.month" not in js


def test_analytics_entry_dropped_forecast_wiring():
    js = _read("static", "js", "smart-analytics.js")
    assert "loadXGBoostTab" not in js, "analytics no longer loads forecasts"
    assert "initHorizonSelect" not in js, "horizon select moved with the screen"
    assert "xgboost" not in js, "no loader key / registry / retry entry left behind"


def test_forecast_month_is_tracked_in_advanced_module():
    adv = _read("static", "js", "smart", "advanced.js")
    assert "export function getForecastMonth" in adv
    assert "if (month) _forecastMonth = month;" in adv
    # horizon change is broadcast as an event; the screen decides what to reload
    assert "smart-forecast:horizon-change" in adv
    # the indicator forecast reuses the screen's own month
    assert "const month = _forecastMonth || smartState.month;" in adv
    # the analytics-side section entry can no longer route into the forecast screen
    assert "return loadXGBoostTab(month);" not in adv


def test_single_hospital_forecast_moved_with_its_renderer():
    """تنبؤ المستشفى المنفرد يُعرض من شاشة التنبؤ باختيار المستشفى نفسه."""
    js = _read("static", "js", "smart-forecast.js")
    assert "renderHospitalForecast" in js          # renderer reused from hospital.js
    assert "import { renderHospitalForecast } from './smart/hospital.js'" in js
    assert "/smart/drilldown/" in js               # same endpoint hospital mode used
    assert "loadHospitalForecast(_selectedHospital())" in js   # panel loader

    hosp = _read("static", "js", "smart", "hospital.js")
    assert "export function renderHospitalForecast" in hosp
    # the moved block renders what run_hospital_forecast actually returns
    # (severity/score/probability + leading_rising), not a dead month table
    assert "leading_rising" in hosp
    assert "Probability" in hosp
    body = hosp[hosp.index("export async function loadHospitalMode"):hosp.index("function computeTrendDirection")]
    assert "renderHospitalForecast(" not in body, (
        "hospital mode must stop rendering a container that moved away")


def test_indicator_selector_groups_rates_and_raw_counts():
    """مُحدد المؤشر يجمّع المعدلات والعدّادات الخام ويتبع لغة الشاشة (طلب المستخدم:
    التنبؤ بحركة المؤشر الخام أيضاً في شاشة التنبؤ)."""
    adv = _read("static", "js", "smart", "advanced.js")
    assert "optgroup" in adv
    assert "_t('Rates')" in adv and "_t('Raw counts')" in adv
    assert "unit === 'count'" in adv            # معيار فصل العدّادات الخام
    assert "_renderIndicatorSelectOptions" in adv
    assert "dataset.lang" in adv                # إعادة البناء عند تغيير اللغة

    js = _read("static", "js", "smart-forecast.js")
    # كل تهيئة للشاشة تُعيد بناء التسميات من الكاش (زر اللغة يعيد تشغيل التهيئة)
    assert "initIndicatorForecast" in js

    i18n = _read("static", "js", "i18n.js")
    assert "'Rates': 'المعدلات'" in i18n
    assert "'Raw counts': 'عدّادات خام'" in i18n


def test_tab_registered_in_menu_registry():
    from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY

    spec = TAB_REGISTRY["smart-forecast"]
    assert spec["label"] == "Smart Forecast"
    assert spec["icon"] == "🔮"
    # reuses the analytics permission — no new permission to seed
    assert spec["permission"] == "smart_analytics.read"
    analysis = next(g for g in DEFAULT_GROUPS if g["name"] == "Analysis")
    assert "smart-forecast" in analysis["items"]
    assert analysis["items"].index("smart-forecast") == (
        analysis["items"].index("smart-analytics") + 1
    )


def test_index_html_loads_tab_and_module():
    html = _read("static", "index.html")
    assert 'id="tab-smart-forecast"' in html
    assert "/static/tabs/smart-forecast.html" in html
    assert '<script type="module" src="/static/js/smart-forecast.js"></script>' in html


def test_main_js_routes_labels_and_searches_the_tab():
    js = _read("static", "js", "main.js")
    assert "_tryInit('initSmartForecast', 10)" in js
    assert "'smart-forecast': 'Smart Forecast'" in js   # breadcrumb label
    assert "'smart-forecast': '🔮'" in js               # breadcrumb icon
    assert "tab:'smart-forecast'" in js                 # Ctrl+K search


def test_auth_permission_map_covers_the_tab():
    js = _read("static", "js", "auth.js")
    assert "'tab-smart-forecast': 'smart_analytics.read'" in js


def test_sidebar_fallback_lists_the_tab_in_analysis():
    js = _read("static", "js", "renderSidebar.js")
    idx = js.index("tab_key:'smart-forecast'")
    assert js.index("fb-3") < idx < js.index("fb-4"), "must sit in the Analysis fallback group"
    assert js[idx:idx + 120].count("🔮") == 1


def test_i18n_translates_label_and_subtitle():
    i18n = _read("static", "js", "i18n.js")
    assert "'Smart Forecast': 'التنبؤ الذكي'" in i18n
    assert "'Forecast first, act early':" in i18n


def test_upload_reanalysis_resets_the_forecast_tab():
    """بعد رفع ملف جديد يجب أن تُعاد قراءة بيانات التنبؤ عند فتح الشاشة."""
    js = _read("static", "js", "upload.js")
    assert "'smart-forecast'" in js


# ── Phase 1: sub-tabs with on-demand loading + reactive horizon ──

SUBTAB_PANELS = ["models", "quality", "signals", "indicator", "hospital"]


def test_forecast_subtabs_and_panels_exist():
    """الشاشة مقسّمة إلى تبويبات فرعية؛ كل تبويب لوح مستقل بمعرّف ثابت."""
    html = _read("static", "tabs", "smart-forecast.html")
    for name in SUBTAB_PANELS:
        assert f'data-forecast-tab="{name}"' in html, name
        assert f'id="forecast-panel-{name}"' in html, name
        assert f'data-forecast-panel="{name}"' in html, name
    # the sub-tab bar uses its own namespace, never the analytics `.smart-tab-btn`
    assert "smart-forecast-tab-btn" in html
    assert "smart-forecast-subtabs" in html
    # markup stays RTL + converted from the old two stacked cards
    assert 'dir="rtl"' in html


def test_forecast_screen_loads_panels_on_demand():
    """التحميل عند الطلب: init يجهّز الأشهر والمستشفيات فقط، وكل لوح يُحمّل عند تفعيله."""
    js = _read("static", "js", "smart-forecast.js")
    assert "_loadForecastPanel" in js
    assert "data-forecast-tab" in js                 # tab clicks drive the loader
    assert "data-forecast-panel" in js               # per-panel containers
    # each panel has a loader, and the heavy fetchers are reached only through it
    for token in ["loadXGBoostTab", "loadForecastQuality", "loadForecastSignalsPanel",
                  "initIndicatorForecast", "loadHospitalForecast"]:
        assert token in js, token
    # init bootstrap loads only months + hospitals (no forecast on open)
    assert "loadMonths()" in js and "loadHospitals()" in js
    # the xgboost loader is invoked from the panel dispatcher, not the tab init body
    assert "case 'models':" in js or "models:" in js


def test_horizon_change_broadcasts_event_and_reloads_active_panel():
    """تغيير الأفق يُبَثّ كحدث والمتتبّع في شاشة التنبؤ يعيد تحميل اللوح النشط."""
    adv = _read("static", "js", "smart", "advanced.js")
    assert "smart-forecast:horizon-change" in adv
    assert "CustomEvent" in adv

    js = _read("static", "js", "smart-forecast.js")
    assert "addEventListener('smart-forecast:horizon-change'" in js
    # horizon-dependent panels are marked stale; only the active one reloads
    assert "HORIZON_PANELS" in js or "horizon" in js.lower()


def test_advanced_exposes_granular_forecast_renderers():
    """advanced.js يفصل الرسّامات ليتمكن كل لوح من رسم قسمه فقط."""
    adv = _read("static", "js", "smart", "advanced.js")
    for name in ["renderXGBoostPredictions", "renderForecastSignals",
                 "renderForecastTracking", "loadForecastQuality",
                 "loadForecastSignalsPanel"]:
        assert (f"export function {name}" in adv
                or f"export async function {name}" in adv), name


def test_forecast_context_bar_is_sticky():
    """شريط السياق (شهر + أفق) يبقى مرئياً أثناء التمرير."""
    html = _read("static", "tabs", "smart-forecast.html")
    assert "smart-forecast-context" in html
    css = _read("static", "css", "styles.css")
    assert ".smart-forecast-context" in css
    assert "position: sticky" in css or "position:sticky" in css


def test_forecast_subtab_i18n_keys_present():
    i18n = _read("static", "js", "i18n.js")
    for key in ("Forecasts", "Accuracy and validation", "Signals"):
        assert f"'{key}':" in i18n, key
