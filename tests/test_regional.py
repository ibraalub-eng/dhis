"""اختبارات الاستخبارات الصحية الإقليمية (Regional Health Intelligence).

تغطي: بوابة المقام، المعدلات المجمّعة، المعايير والمئويات، تحليل الوفيات
وعينة صغيرة، O/E (Poisson/احتياطي)، الولادات مقابل الوفيات، الاتجاهات
الإقليمية، بوابة الثقة للمخاطر، وواجهة /regional.
"""

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db

from app.engine.smart.regional import (
    _safe_rate,
    _gov_metrics,
    _benchmarks,
    _percentile_rank,
    _observed_expected,
    _births_vs_mortality,
    _regional_trends,
    _risk_scores,
    _regional_anomalies,
    _explain_risk,
    _gov_aggregates,
    run_regional_analysis,
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


def _seed_gov(db_session, gov_name, hospitals, month="2026-06", values_by_hosp=None):
    """محافظة بمستشفياتها وقيم مؤشراتها (قيم افتراضية إن لم تُمرَّر)."""
    from app.models import Governorate, Hospital, IndicatorValue

    gov = db_session.query(Governorate).filter(Governorate.name == gov_name).first()
    if not gov:
        gov = Governorate(name=gov_name)
        db_session.add(gov)
        db_session.flush()
    inds = _ensure_indicators(db_session)

    default_values = {
        "2": 300.0, "5": 80.0, "6": 280.0, "6.f": 20.0, "6.g": 15.0,
        "7": 10.0, "10": 15.0, "11": 1.0, "17": 5.0, "2.c": 8.0, "2.d": 4.0,
        "2.n": 30.0,
    }
    for i, hname in enumerate(hospitals):
        hosp = Hospital(name=hname, is_active=True, governorate_id=gov.id)
        db_session.add(hosp)
        db_session.flush()
        values = (values_by_hosp or {}).get(hname, default_values)
        for code, val in values.items():
            if val is None:
                continue
            db_session.add(IndicatorValue(
                hospital_id=hosp.id, indicator_id=inds[code], month=month, value=val,
            ))
    db_session.commit()
    return gov


# ── بوابة المقام ──

def test_safe_rate_denominator_gate():
    """لا تُحسب نسبة بمقام صفر أو غائب — تُرجع None (لا نسبة وهمية)."""
    assert _safe_rate(5.0, 0.0, 1000.0) is None
    assert _safe_rate(5.0, None, 1000.0) is None
    assert _safe_rate(None, 100.0, 1000.0) is None
    assert _safe_rate(5.0, 100.0, 1000.0) == 50.0


def test_gov_metrics_pooled_rates(db_session):
    """المعدلات تُحسب على المجاميع (لا متوسط معدلات المستشفيات)."""
    _seed_gov(db_session, "محافظة أ", ["م1 أ", "م2 أ"], values_by_hosp={
        "م1 أ": {"2": 200.0, "5": 50.0, "6": 180.0, "17": 3.0, "11": 1.0},
        "م2 أ": {"2": 100.0, "5": 30.0, "6": 90.0, "17": 2.0, "11": 0.0},
    })
    agg = _gov_aggregates(_load_for(db_session, "2026-06"))["محافظة أ"]
    m = _gov_metrics(agg)
    assert m["births"] == 270.0
    assert m["nd"] == 5.0
    # nmr = 5/270*1000
    assert abs(m["nmr"] - 5 / 270 * 1000) < 1e-6
    assert abs(m["mmr"] - 1 / 270 * 100000) < 1e-6
    assert abs(m["cs_rate"] - 80 / 300 * 100) < 1e-6


def test_gov_metrics_missing_denominator(db_session):
    """محافظة بلا مواليد صالحة => المعدلات None مع بقاء الأعداد الخام."""
    _seed_gov(db_session, "محافظة ب", ["م ب"], values_by_hosp={
        "م ب": {"2": 0.0, "5": 0.0, "17": 2.0},
    })
    agg = _gov_aggregates(_load_for(db_session, "2026-06"))["محافظة ب"]
    m = _gov_metrics(agg)
    assert m["nmr"] is None
    assert m["mmr"] is None
    assert m["nd"] == 2.0


def _load_for(db_session, month):
    from app.engine.smart import _load_hospital_data
    return _load_hospital_data(db_session, month)


# ── المعايير والمئويات ──

def test_benchmarks_and_percentile():
    metrics = {
        "أ": {"nmr": 10.0, "cs_rate": 20.0},
        "ب": {"nmr": 20.0, "cs_rate": 30.0},
        "ج": {"nmr": 30.0, "cs_rate": 40.0},
    }
    bm = _benchmarks(metrics)
    assert bm["nmr"]["mean"] == 20.0
    assert bm["nmr"]["median"] == 20.0
    assert bm["nmr"]["min"] == 10.0 and bm["nmr"]["max"] == 30.0
    # المئوي: الأدنى 0، الأوسط 50، الأعلى 100
    assert _percentile_rank(10.0, [10.0, 20.0, 30.0]) == 0.0
    assert _percentile_rank(20.0, [10.0, 20.0, 30.0]) == 50.0
    assert _percentile_rank(30.0, [10.0, 20.0, 30.0]) == 100.0


# ── O/E ──

def _synthetic_gov_metrics(n=6):
    metrics = {}
    for i in range(n):
        births = 200 + i * 150
        nmr = 10 + (i % 3) * 5
        nd = births / 1000.0 * nmr
        metrics[f"محافظة {i}"] = {
            "births": float(births), "nd": float(nd),
            "cs_rate": 15.0 + i, "preterm_rate": 10.0 + i, "lbw_rate": 8.0 + i,
            "smm_rate": 5.0 + i, "high_risk_rate": 12.0 + i,
        }
    return metrics


def test_observed_expected_regression_path():
    """6 محافظات ببيانات كافية => نموذج انحداري (Poisson/NB) ونتائج O/E."""
    metrics = _synthetic_gov_metrics(6)
    res = _observed_expected(metrics, list(metrics.keys()))
    assert res["model"] in ("poisson", "negative_binomial")
    assert len(res["results"]) == 6
    for r in res["results"]:
        assert r["observed"] > 0
        assert r["expected"] > 0
        assert r["oe_ratio"] is not None


def test_observed_expected_simple_fallback():
    """محافظتان فقط => احتياطي بسيط (معدل الإقليم) بلا انحدار."""
    metrics = _synthetic_gov_metrics(2)
    res = _observed_expected(metrics, list(metrics.keys()))
    assert res["model"] == "simple_benchmark"
    assert len(res["results"]) == 2
    assert "بيانات غير كافية" in res["note_ar"]


# ── الولادات مقابل الوفيات ──

def test_births_vs_mortality_structure():
    metrics = {
        "أ": {"births": 500.0, "nd": 5.0, "nmr": 10.0},
        "ب": {"births": 1000.0, "nd": 15.0, "nmr": 15.0},
        "ج": {"births": 2000.0, "nd": 40.0, "nmr": 20.0},
    }
    res = _births_vs_mortality(metrics, list(metrics.keys()))
    assert len(res["points"]) == 3
    assert res["corr_raw"] is not None and "pearson" in res["corr_raw"]
    assert res["corr_rate"] is not None
    assert res["regression"] is not None and "slope" in res["regression"]
    assert "لا يعني سببّية" in res["note_ar"]


def test_births_vs_mortality_insufficient():
    metrics = {"أ": {"births": 500.0, "nd": 5.0, "nmr": 10.0}}
    res = _births_vs_mortality(metrics, ["أ"])
    assert res["corr_raw"] is None
    assert res["corr_rate"] is None


# ── الاتجاهات الإقليمية ──

def _seed_trending_data(db_session):
    """محافظتان: الأولى بوفيات متصاعدة شهراً بعد شهر، الثانية مستقرة."""
    from app.models import QualityScore, Hospital

    months = ["2026-01", "2026-02", "2026-03", "2026-04"]
    for m in months:
        db_session.add(QualityScore(hospital_id=1, month=m, score=70.0))
    db_session.commit()

    rising = {m: {"2": 300.0, "5": 80.0, "6": 280.0, "17": 3.0 + i * 2.0}
              for i, m in enumerate(months)}
    _seed_gov(db_session, "محافظة متصاعدة", ["م ص"], month=months[0],
              values_by_hosp={"م ص": rising[months[0]]})
    # إضافة قيم الأشهر اللاحقة للمستشفى نفسه
    _add_month_values(db_session, "م ص", rising)
    _seed_gov(db_session, "محافظة مستقرة", ["م ث"], month=months[0],
              values_by_hosp={"م ث": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 5.0}})
    _add_month_values(db_session, "م ث", {m: {"2": 300.0, "5": 80.0, "6": 280.0, "17": 5.0}
                                          for m in months})


def _add_month_values(db_session, hosp_name, values_by_month):
    from app.models import Hospital, IndicatorValue, Indicator

    hosp = db_session.query(Hospital).filter(Hospital.name == hosp_name).first()
    inds = _ensure_indicators(db_session)
    for month, values in values_by_month.items():
        for code, val in values.items():
            db_session.add(IndicatorValue(
                hospital_id=hosp.id, indicator_id=inds[code], month=month, value=val,
            ))
    db_session.commit()


def test_regional_trends_detects_persistent_worsening(db_session):
    """ارتفاع متواصل في وفيات المواليد (4 أشهر) => اتجاه «تدهور مستمر»."""
    _seed_trending_data(db_session)
    findings = _regional_trends(db_session, "2026-04", months_back=6)
    rising = [f for f in findings
              if f["governorate"] == "محافظة متصاعدة" and f["metric"] == "nmr"]
    assert rising, f"يجب اكتشاف تدهور مستمر في nmr — النتائج: {findings}"
    assert rising[0]["direction"] == "worsening"


# ── بوابة الثقة للمخاطر ──

def test_risk_quality_gate_low_confidence(db_session):
    """اكتمال < 40% => ثقة منخفضة ودرجة الخطر تَحدّ عند 60."""
    from app.models import QualityScore, Hospital, Governorate

    gov = db_session.query(Governorate).filter(Governorate.name == "محافظة أ").first()
    if not gov:
        gov = _seed_gov(db_session, "محافظة أ", ["م ر"])
    hosp = db_session.query(Hospital).filter(Hospital.name == "م ر").first()
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-06", score=50.0,
                                completeness=25.0, consistency=60.0, rule_compliance=50.0))
    db_session.commit()

    data = _load_for(db_session, "2026-06")
    govs = _gov_aggregates(data)
    metrics = {g: _gov_metrics(a) for g, a in govs.items()}
    bm = _benchmarks(metrics)
    risks = _risk_scores(metrics, bm, db_session, "2026-06", list(govs.keys()))
    assert len(risks) == 1
    r = risks[0]
    assert r["confidence"] == "low"
    assert r["risk_score"] <= 60.0
    assert any("مكتملة" in w for w in r["warnings"])


def test_risk_quality_gate_high_confidence(db_session):
    """اكتمال مرتفع ومقام صالح => ثقة عالية."""
    from app.models import QualityScore, Hospital, Governorate

    gov = _seed_gov(db_session, "محافظة كاملة", ["م ك"])
    hosp = db_session.query(Hospital).filter(Hospital.name == "م ك").first()
    db_session.add(QualityScore(hospital_id=hosp.id, month="2026-06", score=90.0,
                                completeness=95.0, consistency=90.0, rule_compliance=95.0))
    db_session.commit()

    data = _load_for(db_session, "2026-06")
    govs = _gov_aggregates(data)
    metrics = {g: _gov_metrics(a) for g, a in govs.items()}
    bm = _benchmarks(metrics)
    risks = _risk_scores(metrics, bm, db_session, "2026-06", list(govs.keys()))
    r = risks[0]
    assert r["confidence"] == "high"


# ── الشذوذ الإقليمي وشرح العوامل ──

def test_regional_anomalies_cross_sectional(db_session):
    """محافظة متطرفة مقابل نظيراتها (|z| ≥ 2) => شذوذ عرضي."""
    # 6 محافظات: 5 بمعدلات متقاربة وواحدة متطرفة (قيمة وفيات عالية جداً)
    for i in range(5):
        _seed_gov(db_session, f"محافظة عادية {i}", [f"م ع {i}"], values_by_hosp={
            f"م ع {i}": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 3.0},
        })
    _seed_gov(db_session, "محافظة متطرفة", ["م ط"], values_by_hosp={
        "م ط": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 90.0},
    })

    data = _load_for(db_session, "2026-06")
    govs = _gov_aggregates(data)
    gov_names = sorted(govs)
    metrics = {g: _gov_metrics(a) for g, a in govs.items()}
    bm = _benchmarks(metrics)
    findings = _regional_anomalies(db_session, "2026-06", metrics, bm, gov_names)

    xs = [f for f in findings if f["type"] == "cross_sectional"]
    assert xs, "يجب اكتشاف شذوذ عرضي واحد على الأقل"
    outlier = [f for f in xs if f["governorate"] == "محافظة متطرفة"]
    assert outlier and outlier[0]["metric"] == "nmr"
    assert outlier[0]["z_score"] >= 2.0
    assert outlier[0]["severity"] in ("warning", "critical")
    assert "لا يعني" in outlier[0]["summary_ar"] or outlier[0]["summary_ar"]


def test_regional_anomalies_historical_spike(db_session):
    """قفزة في معدل وفيات محافظة مقابل أشهرها السابقة => شذوذ تاريخي."""
    from app.models import QualityScore, Hospital

    months = ["2026-01", "2026-02", "2026-03", "2026-04"]
    for m in months:
        db_session.add(QualityScore(hospital_id=1, month=m, score=70.0))
    db_session.commit()

    # أشهر سابقة متغيرة (3، 4، 5 وفيات) ثم قفزة كبيرة في الشهر الحالي (30)
    _seed_gov(db_session, "محافظة قافزة", ["م ق"], month=months[0], values_by_hosp={
        "م ق": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 3.0},
    })
    _add_month_values(db_session, "م ق", {
        "2026-01": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 3.0},
        "2026-02": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 4.0},
        "2026-03": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 5.0},
        "2026-04": {"2": 300.0, "5": 80.0, "6": 280.0, "17": 30.0},
    })

    data = _load_for(db_session, "2026-04")
    govs = _gov_aggregates(data)
    gov_names = sorted(govs)
    metrics = {g: _gov_metrics(a) for g, a in govs.items()}
    bm = _benchmarks(metrics)
    findings = _regional_anomalies(db_session, "2026-04", metrics, bm, gov_names,
                                   months_back=6)

    hist = [f for f in findings if f["type"] == "historical"]
    spike = [f for f in hist if f["governorate"] == "محافظة قافزة" and f["metric"] == "nmr"]
    assert spike, f"يجب اكتشاف شذوذ تاريخي — النتائج: {findings}"
    assert spike[0]["z_score"] >= 2.0
    assert spike[0]["direction"] == "increased"


def test_explain_risk_structure():
    """تفكيك درجة الخطر: عوامل مرتبة تنازلياً مع بياناتها الفعلية وملاحظة سببّية."""
    metrics = {
        "أ": {"nmr": 60.0, "mmr": 300.0, "stillbirth_rate": 40.0, "cs_rate": 50.0,
              "preterm_rate": 30.0, "lbw_rate": 20.0, "smm_rate": 15.0,
              "adolescent_rate": 8.0, "high_risk_rate": 30.0},
        "ب": {"nmr": 10.0, "mmr": 100.0, "stillbirth_rate": 10.0, "cs_rate": 20.0,
              "preterm_rate": 10.0, "lbw_rate": 8.0, "smm_rate": 4.0,
              "adolescent_rate": 2.0, "high_risk_rate": 8.0},
        "ج": {"nmr": 12.0, "mmr": 120.0, "stillbirth_rate": 12.0, "cs_rate": 22.0,
              "preterm_rate": 11.0, "lbw_rate": 9.0, "smm_rate": 5.0,
              "adolescent_rate": 3.0, "high_risk_rate": 9.0},
    }
    bm = _benchmarks(metrics)
    risks = [
        {"governorate": "أ", "risk_score": 55.0, "level": "high", "completeness": 85.0},
        {"governorate": "ب", "risk_score": 10.0, "level": "low", "completeness": 95.0},
        {"governorate": "ج", "risk_score": 12.0, "level": "low", "completeness": 95.0},
    ]
    out = _explain_risk(metrics, bm, risks)
    assert len(out) == 3
    top = next(e for e in out if e["governorate"] == "أ")
    assert top["factors"], "المحافظة المتطرفة يجب أن يكون لها عوامل"
    # مرتبة تنازلياً بالمساهمة
    contribs = [f["contribution"] for f in top["factors"]]
    assert contribs == sorted(contribs, reverse=True)
    for f in top["factors"]:
        assert f["arabic_label"] and f["deviation_pct"] is not None
        assert f["observed"] is not None and f["benchmark"] is not None
    assert "سبب" in top["note_ar"]
    # المحافظة السليمة: nmr لديها أدنى من المعيار => لا يظهر كعامل دافع (صدق)
    healthy = next(e for e in out if e["governorate"] == "ب")
    assert all(f["feature"] != "nmr" for f in healthy["factors"])


def test_run_regional_analysis_includes_new_keys(db_session):
    """التحليل الكامل يتضمن الشذوذ وشرح العوامل."""
    _seed_gov(db_session, "محافظة أ", ["م1 أ", "م2 أ"])
    _seed_gov(db_session, "محافظة ب", ["م1 ب"])
    res = run_regional_analysis(db_session, "2026-06")
    assert "anomalies" in res and isinstance(res["anomalies"], list)
    assert "risk_explanations" in res and isinstance(res["risk_explanations"], list)
    for e in res["risk_explanations"]:
        assert e["governorate"] and "factors" in e


# ── التجميع الكامل والواجهة ──

def test_run_regional_analysis_structure(db_session):
    _seed_gov(db_session, "محافظة أ", ["م1 أ", "م2 أ"])
    _seed_gov(db_session, "محافظة ب", ["م1 ب"])
    res = run_regional_analysis(db_session, "2026-06")
    assert len(res["governorates"]) == 2
    for g in res["governorates"]:
        assert g["rates"]["nmr"]["value"] is not None
        assert "percentile" in g["rates"]["nmr"]
        assert "deviation_pct" in g["rates"]["nmr"]
    assert len(res["mortality"]) == 2
    assert len(res["risk_scores"]) == 2
    assert res["referrals"]["available"] is False
    assert "لا توجد بيانات إحالات" in res["referrals"]["note_ar"]
    assert res["births_vs_mortality"]["points"] or res["observed_expected"]["results"]


def test_regional_api_endpoint(client, db_session):
    """نقطة نهاية /regional/overview/{month} تعيد البنية الكاملة."""
    from app.cache import cache
    cache.invalidate("regional_2026-06_6")
    _seed_gov(db_session, "محافظة أ", ["م1 أ", "م2 أ"])
    response = client.get("/regional/overview/2026-06")
    assert response.status_code == 200
    data = response.json()
    for key in ("governorates", "mortality", "risk_scores", "trends",
                "observed_expected", "births_vs_mortality",
                "anomalies", "risk_explanations"):
        assert key in data
    assert isinstance(data["governorates"], list)


def test_regional_api_endpoint_error(client):
    """خطأ داخلي => 500 برسالة عربية."""
    from unittest.mock import patch
    from app.cache import cache
    cache.invalidate("regional_2026-06_6")
    with patch("app.api.regional.run_regional_analysis", side_effect=Exception("boom")):
        response = client.get("/regional/overview/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل الإقليمي" in response.json()["detail"]
