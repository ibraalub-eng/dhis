"""اختبارات اكتشاف العلاقات المتأخرة زمنياً والإنذار المبكر.

تغطي: بنية النتائج، كشف علاقة رائدة حقيقية (t → t+1)، عدم كفاية الأشهر،
اكتشاف الإنذار المبكر من مؤشرات قيادية صاعدة، غياب الإشارة، وواجهة /smart،
وتكامل /smart/drilldown مع توقعات الشهر القادم.
"""

import os
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db

from app.engine.smart.lag_analysis import (
    run_lag_analysis,
    run_early_warnings,
    _hospital_rates,
    _discovered_leading_indicators,
)

_CODES = ["2", "5", "6", "6.f", "6.g", "7", "10", "11", "17", "2.c", "2.d", "2.n"]


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ensure_indicators(db_session):
    from app.models import Indicator

    inds = {}
    for code in _CODES:
        existing = db_session.query(Indicator).filter(Indicator.code == code).first()
        if existing:
            inds[code] = existing.id
            continue
        ind = Indicator(code=code, name=f"Ind {code}")
        db_session.add(ind)
        db_session.flush()
        inds[code] = ind.id
    return inds


def _seed_hospital(db_session, name, months_values, governorate="محافظة أ"):
    """مستشفى بقيمه لكل شهر: months_values = {شهر: {كود: قيمة}}."""
    from app.models import Governorate, Hospital, IndicatorValue

    gov = db_session.query(Governorate).filter(Governorate.name == governorate).first()
    if not gov:
        gov = Governorate(name=governorate)
        db_session.add(gov)
        db_session.flush()
    hosp = Hospital(name=name, is_active=True, governorate_id=gov.id)
    db_session.add(hosp)
    db_session.flush()
    inds = _ensure_indicators(db_session)
    for month, values in months_values.items():
        for code, val in values.items():
            if val is None:
                continue
            db_session.add(IndicatorValue(
                hospital_id=hosp.id, indicator_id=inds[code], month=month, value=val,
            ))
    db_session.commit()
    return hosp


def _full_values(births=300, deliveries=320, cs=80, preterm=10, lbw=5, smm=8,
                 mat=0, nd=2, sb=3, hr=15, adol=4):
    return {"2": deliveries, "5": cs, "6": births, "6.f": preterm, "6.g": lbw,
            "10": smm, "11": mat, "17": nd, "7": sb, "2.n": hr, "2.c": adol, "2.d": 0}


# ── معدلات المستشفى ──

def test_hospital_rates_denominator_gate():
    """بلا مقام صالح => None لا نسبة وهمية."""
    rates = _hospital_rates({"total_births": 0, "nd": 5, "2": 0, "smm_total": 8})
    assert rates["nmr"] is None
    assert rates["smm_rate"] is None
    rates2 = _hospital_rates({"total_births": 100, "nd": 5, "2": 120, "smm_total": 8})
    assert abs(rates2["nmr"] - 5 / 100 * 1000) < 1e-6
    assert abs(rates2["smm_rate"] - 8 / 120 * 1000) < 1e-6


# ── العلاقات المتأخرة ──

def test_lag_detects_true_lead(db_session):
    """بيانات مصممة بحيث يسبق preterm عند t ارتفاع nmr عند t+1 => علاقة رائدة."""
    months = ["2026-01", "2026-02", "2026-03", "2026-04"]
    for h in range(6):
        vals_by_month = {}
        for i, m in enumerate(months):
            preterm = 15 + h + i * 5
            # nmr عند الشهر m يعتمد على preterm الشهر السابق (علاقة حتمية متأخرة)
            prev_preterm = 15 + h + (i - 1) * 5 if i > 0 else 5
            nd = 1 + prev_preterm * 0.25
            vals_by_month[m] = _full_values(preterm=preterm, nd=nd, smm=8 + h)
        _seed_hospital(db_session, f"H{h}", vals_by_month)

    res = run_lag_analysis(db_session, "2026-04")
    assert res["lags"], "يجب اكتشاف علاقات متأخرة"
    pair = next((l for l in res["lags"]
                 if l["indicator_a"] == "preterm_rate" and l["indicator_b"] == "nmr"), None)
    assert pair, "يجب أن تظهر العلاقة preterm→nmr المتأخرة"
    assert pair["direction"] == "positive"
    assert pair["lag_pearson"] > 0.5
    assert pair["p_value"] < 0.05
    assert pair["n"] >= 10
    assert pair["is_lead"] is True
    for key in ("strength", "confidence", "summary_ar", "summary_en"):
        assert key in pair


def test_lag_insufficient_months(db_session):
    """شهر واحد => لا علاقات مع ملاحظة توضيحية."""
    _seed_hospital(db_session, "H", {"2026-01": _full_values()})
    res = run_lag_analysis(db_session, "2026-01")
    assert res["lags"] == []
    assert "شهران" in res["note_ar"]


# ── الإنذار المبكر ──

def test_early_warning_detects_rising(db_session):
    """مستشفى تضاعفت مؤشراته القيادية => إنذار حرج باحتمال وثقة."""
    m1 = _full_values(preterm=10, lbw=5, smm=8, nd=2)
    m2 = _full_values(preterm=25, lbw=15, smm=20, nd=5)
    _seed_hospital(db_session, "H صاعد", {"2026-02": m1, "2026-03": m2})

    res = run_early_warnings(db_session, "2026-03")
    w = next((w for w in res["warnings"] if w["hospital_name"] == "H صاعد"), None)
    assert w, "يجب اكتشاف إنذار مبكر"
    assert w["severity"] in ("critical", "warning")
    assert w["rising_count"] >= 3
    assert w["probability"] >= 0.5
    assert w["contributing"], "يجب سرد المؤشرات الصاعدة"
    metrics = {c["metric"] for c in w["contributing"]}
    assert {"preterm_rate", "lbw_rate"} <= metrics
    assert w["confidence"] in ("high", "medium", "low")
    assert w["hospital_id"] is not None


def test_early_warning_no_signal(db_session):
    """مستشفى ثابت المؤشرات => لا إنذار."""
    v = _full_values()
    _seed_hospital(db_session, "H ثابت", {"2026-02": v, "2026-03": v})
    res = run_early_warnings(db_session, "2026-03")
    assert not any(w["hospital_name"] == "H ثابت" for w in res["warnings"])


def test_early_warning_insufficient_months(db_session):
    """شهر واحد => لا إنذارات مع ملاحظة."""
    _seed_hospital(db_session, "H", {"2026-01": _full_values()})
    res = run_early_warnings(db_session, "2026-01")
    assert res["warnings"] == []
    assert "شهران" in res["summary_ar"]


def test_early_warning_uses_discovered_leads(db_session):
    """القائمة القيادية تُبنى من العلاقات المكتشفة وتُوزن، والمؤشرات غير المكتشفة لا تُحتسب."""
    lag_results = {"lags": [
        {"indicator_a": "preterm_rate", "indicator_b": "nmr",
         "granger_pearson": 0.8, "lag_pearson": 0.9, "consistency": 1.0,
         "is_lead": True, "indicator_b_ar": "معدل وفيات المواليد"},
        {"indicator_a": "cs_rate", "indicator_b": "nmr",
         "granger_pearson": 0.4, "lag_pearson": 0.5, "consistency": 0.3,
         "is_lead": False, "indicator_b_ar": "معدل وفيات المواليد"},
    ]}
    leaders = _discovered_leading_indicators(lag_results)
    # الأقوى يُطبَّع إلى 1.0 والآخر أقل، مع تسمية النتيجة التي يقودها
    assert leaders["preterm_rate"]["weight"] == 1.0
    assert leaders["cs_rate"]["weight"] < 1.0
    assert leaders["preterm_rate"]["outcome_ar"] == "معدل وفيات المواليد"

    # مستشفى ارتفع فيه preterm (قائد مكتشف) وlbw (غير مكتشف): لا يُحتسب lbw
    m1 = _full_values(preterm=10, lbw=5, nd=2)
    m2 = _full_values(preterm=25, lbw=15, nd=2)
    _seed_hospital(db_session, "H1", {"2026-02": m1, "2026-03": m2})
    _seed_hospital(db_session, "H2", {"2026-02": m1, "2026-03": m2})
    res = run_early_warnings(db_session, "2026-03", lag_results)
    w = next((x for x in res["warnings"] if x["hospital_name"] == "H1"), None)
    assert w, "يجب إصدار إنذار من القائد المكتشف"
    assert w["discovered_leads"] is True
    assert w["rising_count"] == 1
    assert w["contributing"][0]["metric"] == "preterm_rate"
    assert w["contributing"][0]["weight"] == 1.0
    assert w["contributing"][0]["leads"] == "معدل وفيات المواليد"
    assert w["score"] == 1.0
    assert w["severity"] == "info"


# ── الواجهة ──

def test_smart_overview_includes_new_keys(client, db_session):
    """/smart/overview/{month} يتضمن lag_analysis و early_warnings."""
    from app.cache import cache
    cache.invalidate("smart_overview_2026-03")
    _seed_hospital(db_session, "H1", {"2026-02": _full_values(), "2026-03": _full_values()})
    _seed_hospital(db_session, "H2", {"2026-02": _full_values(), "2026-03": _full_values()})
    response = client.get("/smart/overview/2026-03")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "lag_analysis" in data
    assert "early_warnings" in data
    assert isinstance(data["lag_analysis"].get("lags"), list)
    assert isinstance(data["early_warnings"].get("warnings"), list)


# ── توقعات الشهر القادم لمستشفى محدد ──

def test_hospital_forecast_rising_leads_with_weights(db_session):
    """لوحة المستشفى: المؤشرات القيادية الصاعدة بأوزانها + النتائج المتوقعة + الاحتمال."""
    lag_results = {"lags": [
        {"indicator_a": "preterm_rate", "indicator_b": "nmr",
         "indicator_b_ar": "معدل وفيات المواليد", "lag": 1,
         "granger_pearson": 0.8, "lag_pearson": 0.9,
         "granger_pass": True, "is_lead": True,
         "prediction_ar": "إذا ارتفعت الولادات المبكرة 10% يُتوقع ارتفاع وفيات المواليد"},
    ]}
    m1 = _full_values(preterm=10, lbw=5, nd=2)
    m2 = _full_values(preterm=25, lbw=15, nd=2)
    hosp = _seed_hospital(db_session, "H متوقع", {"2026-02": m1, "2026-03": m2})

    from app.engine.smart.lag_analysis import run_hospital_forecast
    f = run_hospital_forecast(db_session, hosp.id, "2026-03", lag_results)
    assert f, "يجب أن تعيد توقعات للمستشفى"
    assert f["hospital_id"] == hosp.id
    assert f["month"] == "2026-03"
    assert f["discovered_leads"] is True
    assert f["leading_rising"], "يجب رصد المؤشرات الصاعدة"
    top = next(r for r in f["leading_rising"] if r["metric"] == "preterm_rate")
    assert top["weight"] == 1.0
    assert top["delta_pct"] > 100
    assert top["leads_to"], "يجب ربط المؤشر بالنتيجة المتوقعة"
    assert top["leads_to"][0]["outcome_ar"] == "معدل وفيات المواليد"
    assert top["leads_to"][0]["lag"] == 1
    assert f["score"] >= 1.0
    assert f["severity"] in ("critical", "warning", "info", "none")
    assert 0 <= f["probability"] <= 0.95
    assert f["confidence"] in ("high", "medium", "low")
    assert "مكتشفة" in f["note_ar"]


def test_hospital_forecast_missing_hospital_returns_empty(db_session):
    """مستشفى بلا بيانات في النافذة => {} (لا قائمة مفاجئة)."""
    from app.engine.smart.lag_analysis import run_hospital_forecast
    assert run_hospital_forecast(db_session, 99999, "2026-03") == {}


# ── تكامل: نقطة نهاية /smart/drilldown + وجود حاوية العرض في HTML ──

def test_drilldown_returns_complete_forecast(client, db_session):
    """تكامل: /smart/drilldown/{id}/{month} يُرجع forecast كاملة بكل الحقول."""
    m1 = _full_values(preterm=10, lbw=5, nd=2)
    m2 = _full_values(preterm=25, lbw=15, nd=2)
    hosp = _seed_hospital(db_session, "H تكامل", {"2026-02": m1, "2026-03": m2})

    response = client.get(f"/smart/drilldown/{hosp.id}/2026-03")
    assert response.status_code == 200
    data = response.json()
    assert "forecast" in data, "الاستجابة يجب أن تتضمن forecast"

    f = data["forecast"]
    assert f["hospital_id"] == hosp.id
    assert f["month"] == "2026-03"
    # كل الحقول الأساسية للتوقعات حاضرة
    for key in ("hospital_name", "discovered_leads", "leading_rising",
                "outcome_rising", "score", "severity", "probability",
                "confidence", "confidence_label_ar", "note_ar"):
        assert key in f, f"حقل مفقود في forecast: {key}"
    # المؤشرات القيادية الصاعدة بأوزانها والنتائج المتوقعة
    assert f["leading_rising"], "يجب رصد مؤشرات قيادية صاعدة عبر النقطة النهائية"
    top = f["leading_rising"][0]
    for key in ("metric", "metric_ar", "weight", "delta_pct", "leads_to"):
        assert key in top, f"حقل مفقود في المؤشر الصاعد: {key}"
    assert top["weight"] > 0
    assert f["severity"] in ("critical", "warning", "info", "none")
    assert 0 <= f["probability"] <= 0.95
    assert f["confidence"] in ("high", "medium", "low")


def test_drilldown_forecast_container_in_html():
    """واجهة لوحة المستشفى تتضمن حاوية عرض توقعات الشهر القادم."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs",
                        "smart-analytics.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert "smart-hospital-forecast" in html


def test_hospital_forecast_no_rise_returns_none_severity(db_session):
    """مستشفى ثابت => leading_rising فارغ وseverity = none."""
    v = _full_values()
    hosp = _seed_hospital(db_session, "H ثابت", {"2026-02": v, "2026-03": v})
    from app.engine.smart.lag_analysis import run_hospital_forecast
    f = run_hospital_forecast(db_session, hosp.id, "2026-03")
    assert f["leading_rising"] == []
    assert f["severity"] == "none"
    assert f["score"] == 0
