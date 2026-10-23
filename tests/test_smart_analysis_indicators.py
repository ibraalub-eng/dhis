"""لوحة «المؤشرات التي يعمل بها التحليل» — التغطية الفعلية لما يمكن تحليله.

تجيب عن سؤال المستخدم «على أي مؤشرات يعمل التحليل؟»: المحرك مثبّت على
FEATURE_KEYS المشتقة من رموز قاعدة البيانات، ف تعرض اللوحة لكل منها عدد
المستشفيات التي يمكن اشتقاق قيمتها هذا الشهر والمعطّلة والناقصة — بلا صفر
صامت وبلا وعود بمؤشرات لا يقرأها المحرك فعلاً.
"""
import os

import pytest


# ── Engine: analysis_indicator_coverage ──────────────────────────────


def _full_values():
    """قيم مصدرية مكتملة تُشتق منها كل FEATURE_KEYS العشرة."""
    return {
        "2": 100.0, "5": 30.0, "6": 90.0, "10": 5.0, "11": 1.0,
        "17": 2.0, "7": 1.0, "6.f": 8.0, "6.g": 6.0, "2.n": 12.0,
        "2.c": 3.0, "2.d": 2.0,
    }


def _seed_coverage_month(db_session, month="2026-06"):
    """ثلاثة مستشفيات نشطة: واحد بقيم مكتملة، وواحد بلا أي بيانات،
    وواحد معطّل المصدر («10» معطّل يدوياً لعدم وجود قيم أصلاً)."""
    from app.models import (Hospital, Indicator, IndicatorValue,
                            HospitalIndicatorConfig, SystemSetting)

    # إلغاء التعطيل التلقائي صراحةً: الاختبارات تقيس التغطية كما هي افتراضياً
    # (البيئات السابقة قد تترك النظام مفعّلاً لنفس القاعدة)
    setting = db_session.query(SystemSetting).filter(
        SystemSetting.key == "auto_disable_null_indicators").first()
    if setting:
        setting.value = "false"
    else:
        db_session.add(SystemSetting(key="auto_disable_null_indicators", value="false"))
    db_session.commit()

    def _ind(code):
        row = db_session.query(Indicator).filter(Indicator.code == code).first()
        if row:
            return row.id
        ind = Indicator(code=code, name=f"Ind {code}")
        db_session.add(ind)
        db_session.flush()
        return ind.id

    # مستشفى 1: قيم مكتملة
    full = Hospital(name="Coverage Full", is_active=True)
    # مستشفى 2: بلا أي قيم
    empty = Hospital(name="Coverage Empty", is_active=True)
    # مستشفى 3: قيم جزئية (بلا 10 وبلا 17)
    partial = Hospital(name="Coverage Partial", is_active=True)
    db_session.add_all([full, empty, partial])
    db_session.flush()

    for code, val in _full_values().items():
        db_session.add(IndicatorValue(
            hospital_id=full.id, indicator_id=_ind(code), month=month, value=val))

    # مستشفى جزئي: كل شيء ما عدا المضاعفات (10) والوفيات الجديدة (17)
    partial_values = {k: v for k, v in _full_values().items() if k not in ("10", "17")}
    for code, val in partial_values.items():
        db_session.add(IndicatorValue(
            hospital_id=partial.id, indicator_id=_ind(code), month=month, value=val))
    # صفّ بقيمة null للمضاعفات (تُعامل كمعطّل تلقائي عند تفعيل القاعدة)
    db_session.add(IndicatorValue(
        hospital_id=partial.id, indicator_id=_ind("10"), month=month, value=None))

    # مستشفى فارغ: معطّل يدوياً للمصدر «2» ليرجع تصنيف «معطّل» لا «ناقص»
    db_session.add(HospitalIndicatorConfig(
        hospital_id=empty.id, indicator_id=_ind("2"), is_enabled=False))
    db_session.commit()
    return {"full": full.id, "empty": empty.id, "partial": partial.id}


def test_coverage_covers_every_feature_key(db_session):
    """كل ميزة في FEATURE_KEYS لها صف تغطية بمصدر ونوع وحالة."""
    from app.engine.smart import analysis_indicator_coverage
    from app.engine.smart.anomaly import FEATURE_KEYS
    from app.engine.smart import FEATURE_SOURCE_CODES

    _seed_coverage_month(db_session)
    result = analysis_indicator_coverage(db_session, "2026-06")

    assert result["month"] == "2026-06"
    # 3 مستشفيات البذرة في conftest + 3 المستشفيات المزروعة هنا
    assert result["hospitals_total"] == 6
    keys = [r["key"] for r in result["indicators"]]
    assert keys == FEATURE_KEYS
    for row in result["indicators"]:
        assert row["sources"] == list(FEATURE_SOURCE_CODES[row["key"]])
        assert row["kind"] == ("rate" if row["key"] == "cs_rate" else "count")
        assert row["label_ar"]
        # التوزيع يغطي كل المستشفيات النشطة بالكامل — بلا صفر مُختلق
        assert (row["hospitals_with_value"] + row["hospitals_disabled"]
                + row["hospitals_missing"]) == result["hospitals_total"]


def test_coverage_counts_partial_and_missing(db_session):
    """المستشفى بلا بيانات يُحسب «ناقصاً»، والجزئي يُحسب حسب توفّر مصدره."""
    from app.engine.smart import analysis_indicator_coverage

    _seed_coverage_month(db_session)
    result = analysis_indicator_coverage(db_session, "2026-06")
    by_key = {r["key"]: r for r in result["indicators"]}

    # المضاعفات (10): الكامل فقط له قيمة؛ والجزئي (null) والفارغ ومستشفيات
    # البذرة بلا قيمة => ناقص. لا صفر صامت ولا معطّل مُختلق (التعطيل التلقائي مُلغى)
    smm = by_key["smm_total"]
    assert smm["hospitals_with_value"] == 1
    assert smm["hospitals_disabled"] == 0
    assert smm["hospitals_missing"] == 5
    assert smm["status"] == "partial"

    # القيصارية (5/2): الكامل والجزئي يملكان 2 و5 => قابلتان للاشتقاق؛
    # والفارغ مصدره «2» معطّل يدوياً => «معطّل» لا «ناقص»
    cs = by_key["cs_rate"]
    assert cs["hospitals_with_value"] == 2
    assert cs["hospitals_disabled"] == 1
    assert cs["hospitals_missing"] == 3  # مستشفيات البذرة بلا قيم
    assert cs["status"] == "partial"


def test_coverage_available_and_unavailable_statuses(db_session):
    """حالة «متاح» تعني كل المستشفيات تملك القيمة؛ «غير متاح» تعني لا واحدة."""
    from app.engine.smart import analysis_indicator_coverage

    _seed_coverage_month(db_session)
    result = analysis_indicator_coverage(db_session, "2026-06")
    by_key = {r["key"]: r for r in result["indicators"]}

    # لميزة كل مصادرها مكتملة لدى الكامل وجزئي (عدا 10/17): ليست متاحة بالكامل
    assert by_key["total_births"]["status"] == "partial"
    # ميزة بلا بيانات إطلاقاً لدى أي مستشفى: غير متاح (لا صف ذي تغطية كاذبة)
    assert all(r["status"] != "unavailable" for r in result["indicators"]
               if r["hospitals_with_value"] > 0)


def test_coverage_note_explains_derived_only_scope(db_session):
    """اللوحة تصرّح بأن التحليل يعمل على المشتقة فقط (لا كل المؤشرات)."""
    from app.engine.smart import analysis_indicator_coverage

    _seed_coverage_month(db_session)
    note = analysis_indicator_coverage(db_session, "2026-06")["note"]
    assert "المشتقة" in note
    assert "لا يدخل نماذج" in note


def test_coverage_empty_month_no_hospitals(db_session):
    """شهر بلا أي قيم: كل الميزات «غير متاح» بلا انهيار وبلا تغطية مصطنعة."""
    from app.engine.smart import analysis_indicator_coverage

    result = analysis_indicator_coverage(db_session, "2099-01")
    assert len(result["indicators"]) == 10
    assert all(r["hospitals_total"] == result["hospitals_total"]
               for r in result["indicators"])
    assert all(r["hospitals_with_value"] == 0 for r in result["indicators"])
    assert all(r["status"] == "unavailable" for r in result["indicators"])
    assert all(r["coverage_pct"] == 0.0 for r in result["indicators"])


def test_disabled_maps_shared_helper_matches_loader(db_session):
    """الدالة المشتركة _disabled_maps تعيد نفس خرائط ما قبل الاستخراج."""
    from app.engine.smart import _disabled_maps, _load_hospital_data
    from app.models import Hospital, Indicator, IndicatorValue

    ids = _seed_coverage_month(db_session)
    hospitals = db_session.query(Hospital).filter(Hospital.is_active).all()
    indicators = db_session.query(Indicator).all()
    all_values = db_session.query(IndicatorValue).filter(
        IndicatorValue.month == "2026-06").all()

    combined, auto = _disabled_maps(db_session, "2026-06", hospitals, indicators, all_values)
    ind_map = {i.id: i.code for i in indicators}

    # مستشفى الفارغ: «2» معطّل يدوياً
    empty_disabled = {ind_map[i] for i in combined.get(ids["empty"], set())}
    assert "2" in empty_disabled

    # حمولة التحليل نفسها تستبعد «2» لهذا المستشفى => بلا cs_rate
    data = _load_hospital_data(db_session, "2026-06")
    assert "Coverage Full" in data
    assert data["Coverage Full"]["values"]["cs_rate"] == 30.0
    assert "cs_rate" not in data.get("Coverage Empty", {}).get("values", {})


# ── API: /smart/analysis-indicators/{month} ──────────────────────────


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_endpoint_returns_coverage_shape(client, db_session):
    from app.cache import cache

    _seed_coverage_month(db_session)
    cache.invalidate("smart_analysis_indicators_")
    resp = client.get("/smart/analysis-indicators/2026-06")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["month"] == "2026-06"
    assert payload["hospitals_total"] >= 3  # البذرة + المزروع هنا
    assert len(payload["indicators"]) == 10
    row = payload["indicators"][0]
    assert {"key", "label_ar", "kind", "sources", "hospitals_with_value",
            "hospitals_disabled", "hospitals_missing", "hospitals_total",
            "coverage_pct", "status"} <= set(row.keys())
    # الكاش المؤقت يُخزَّن تحت مفتاح الشهر
    assert cache.get("smart_analysis_indicators_2026-06_v3") is not None
    cache.invalidate("smart_analysis_indicators_")


def test_endpoint_invalidated_on_upload_prefix(client, db_session):
    """مفتاح الكاش يبدأ بالبادئة نفسها التي تُبطلها عملية الرفع."""
    from app.cache import cache

    _seed_coverage_month(db_session)
    cache.invalidate("smart_analysis_indicators_")
    assert client.get("/smart/analysis-indicators/2026-06").status_code == 200
    # نفس منطق upload.py: البادئة تمحو المفتاح
    cache.invalidate("smart_analysis_indicators_")
    assert cache.get("smart_analysis_indicators_2026-06_v3") is None


# ── UI contract: القسم مسجّل في HTML والمحمل في JS ───────────────────


def _read(rel):
    path = os.path.join(os.path.dirname(__file__), "..", rel)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_html_has_indicators_scope_section():
    """حاوية القسم موجودة في شاشة التحليل الذكي بمحمّلها وجدولها."""
    html = _read(os.path.join("static", "tabs", "smart-analytics.html"))
    assert 'id="smart-indicators-scope"' in html
    assert 'data-smart-loader="indicators-scope"' in html
    assert 'id="smart-indicators-scope-table"' in html
    assert "المؤشرات التي يعمل بها التحليل" in html


def test_js_registers_scope_loader():
    """المحمل مسجّل في section registry وفي قائمة إعادة المحاولة."""
    js = _read(os.path.join("static", "js", "smart-analytics.js"))
    assert "'indicators-scope': { load: () => loadIndicatorsScope" in js
    assert "loadIndicatorsScope(smartState.month)" in js
    assert "renderIndicatorsScope" in js


def test_endpoint_returns_coverage_history(client, db_session):
    """خط تغطية بسيط لآخر ستة أشهر مرفق بالاستجابة بترتيب تصاعدي."""
    from app.cache import cache
    from app.engine.smart.anomaly import FEATURE_KEYS
    from app.models import Indicator, IndicatorValue

    ids = _seed_coverage_month(db_session)
    # شهور سابقة بقيم للمستشفى الكامل حتى يتحرك الخط لا أن يكون خطاً مسطحاً
    ind_map = {i.code: i.id for i in db_session.query(Indicator).all()}
    for m in ("2026-04", "2026-05"):
        for code in ("2", "5", "6"):
            db_session.add(IndicatorValue(
                hospital_id=ids["full"], indicator_id=ind_map[code],
                month=m, value=90.0))
    db_session.commit()

    cache.invalidate("smart_analysis_indicators_")
    resp = client.get("/smart/analysis-indicators/2026-06")
    assert resp.status_code == 200
    history = resp.json()["coverage_history"]
    assert 3 <= len(history) <= 6
    months = [h["month"] for h in history]
    assert months == sorted(months)
    assert months[-1] == "2026-06"
    for entry in history:
        assert set(entry["coverage"].keys()) == set(FEATURE_KEYS)
        assert all(0.0 <= v <= 100.0 for v in entry["coverage"].values())
    # آخر نقطة في الخط مطابقة تماماً لجدول الشهر المعروض
    current = dict(history[-1]["coverage"])
    for row in resp.json()["indicators"]:
        assert current[row["key"]] == row["coverage_pct"]
    # الشهر بلا قيم يبقى آخر نقطة ولا يُسقط الخط
    cache.invalidate("smart_analysis_indicators_")
    resp = client.get("/smart/analysis-indicators/2099-01")
    future = resp.json()["coverage_history"]
    assert future[-1]["month"] == "2099-01"
    assert len(future) <= 6
    cache.invalidate("smart_analysis_indicators_")


def test_html_and_js_render_coverage_trend():
    """العمود الجديد موجود في HTML ويتولاه راسم SVG في الواجهة."""
    html = _read(os.path.join("static", "tabs", "smart-analytics.html"))
    js = _read(os.path.join("static", "js", "smart-analytics.js"))
    assert 'data-i18n="Coverage trend (6 months)"' in html
    assert "_coverageSparkline" in js
    assert "coverage_history" in js


def test_core_starts_visible_section_loaders():
    """المحمّل مخفي حتى التفعيل، فالأقسام المفتوحة عند الإقلاع تشغّل نفسها:
    إقلاع + تبديل الوضع يُشغّلان محمّلات الأقسام الظاهرة فقط."""
    core = _read(os.path.join("static", "js", "smart", "core.js"))
    assert "runVisibleSectionLoaders" in core
    assert "_sectionIsLaidOut" in core
    assert "'smart-mode-changed'" in core
    # الأقسام داخل الألواح المخفية (زمني/مستشفى/تقرير) لا تُشغَّل مبكراً
    assert "if (key && !_loadedKeys.has(key) && _sectionIsLaidOut(el)) runSectionLoader(key);" in core
    # ولا قسم يُحمَّل قبل معرفة الشهر (وإلا طلب /smart/analysis-indicators/null)
    assert "if (!smartState.month) return;" in core
    # المحمّل نفسه display:none، ففحص العرض يبدأ من الأب لا من الشريحة
    assert "let node = el.parentElement;" in core
    # بعد تحديد الشهر تُشغَّل الأقسام المفتوحة التي لم تُحمَّل
    assert "runVisibleSectionLoaders();" in core.split("export function reloadSmartSections")[1]


def test_i18n_has_scope_keys():
    """مفاتيح الترجمة الجديدة معرّفة بالعربية."""
    i18n = _read(os.path.join("static", "js", "i18n.js"))
    for key in ("Indicators the analysis works with", "Source codes",
                "Coverage", "Partially covered", "Not covered",
                "Coverage trend (6 months)", "Action board"):
        assert f"'{key}':" in i18n, key
