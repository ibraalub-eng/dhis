import pytest
from unittest.mock import MagicMock
from app.engine.smart.schemas import SmartAnalyticsResult


def test_composite_patterns_adaptive_threshold():
    """الأنماط المركبة تظهر افتراضياً حتى مع بيانات صغيرة (17 مستشفى).

    كانت العتبة الثابتة 25% تُخفي كل التوليفات: 4/17 = 23.5% < 25%.
    العتبة التكيفية تتطلب ≥ 3 مستشفيات فعلياً دون تجاوز 25%.
    """
    from app.engine.smart.patterns import detect_composite_patterns

    high = {"cs_rate": 35.0, "smm_total": 0.0, "mat_deaths": 0.0, "nd": 3.0, "sb": 2.0,
            "preterm": 12.0, "lbw": 14.0, "high_risk": 1.0, "adolescent": 0.0}
    low = {"cs_rate": 18.0, "smm_total": 0.0, "mat_deaths": 0.0, "nd": 0.0, "sb": 0.0,
           "preterm": 4.0, "lbw": 5.0, "high_risk": 1.0, "adolescent": 0.0}
    data = {}
    for i in range(4):
        data[f"h{i}"] = {"values": dict(high)}
    for i in range(4, 17):
        data[f"h{i}"] = {"values": dict(low)}

    patterns = detect_composite_patterns(data, {}, enabled=True)
    assert patterns, "يجب اكتشاف أنماط بعتبة تكيفية على 17 مستشفى"
    # نمط الولادات المبكرة + انخفاض الوزن ظاهر بين النتائج بقوة رفع عالية
    assert any("preterm" in p.indicators and "lbw" in p.indicators for p in patterns)
    assert patterns[0].lift > 5
    # أسماء المستشفيات الحاملة للنمط تُمرَّر للواجهة
    assert patterns[0].hospitals_count == 4
    assert set(patterns[0].hospitals) <= {f"h{i}" for i in range(4)}

    # إعادة إنتاج الخطأ القديم: عتبة صريحة 0.25 تُخفي كل الأنماط (4/17 = 23.5% < 25%)
    strict = detect_composite_patterns(data, {"pattern_min_support": 0.25}, enabled=True)
    assert not strict


def test_orchestrator_returns_result():
    from app.engine.smart import run_smart_analytics

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    result = run_smart_analytics(mock_session, "2026-06")
    assert isinstance(result, SmartAnalyticsResult)
    assert result.month == "2026-06"


def test_residuals_wired_into_anomaly_ensemble(monkeypatch):
    """run_smart_analytics must pass per-hospital residual scores into
    detect_smart_anomalies so the residual weight actually counts (bug fix)."""
    from app.engine.smart import run_smart_analytics
    from app.engine.smart.schemas import ResidualResult

    captured = {}

    def fake_residuals(all_data, config):
        return [
            ResidualResult(
                hospital_name="General Hospital", hospital_id=1, indicator="cs_rate",
                actual_value=60.0, predicted_value=25.0, residual=35.0,
                residual_z_score=3.0, is_anomaly=True, severity="critical",
            ),
        ]

    def fake_detect(all_data, config, enabled=True, residual_scores=None):
        captured["residual_scores"] = residual_scores
        return []

    monkeypatch.setattr("app.engine.smart.analyze_residuals", fake_residuals)
    monkeypatch.setattr("app.engine.smart.detect_smart_anomalies", fake_detect)

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    run_smart_analytics(mock_session, "2026-06")
    # z=3.0 normalized as 3.0/4.0 = 0.75, passed for the cs_rate residual
    assert captured["residual_scores"] == {"General Hospital": 0.75}


def _seed_smart_data(db_session):
    """مستشفى واحد بقيم مصدرية كاملة + مؤشر بلا بيانات + مؤشر معطّل يدوياً.

    يُستخدم مفتاح «نظري» يستخدم نفس أرقام مصادر المشتقات (2,5,6,10...) لأن المحرك
    يقرأها بالكود تحديداً، مع مؤشر إضافي معطّل يدوياً ("52").
    """
    from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig

    hosp = Hospital(name="Smart Test Hospital", is_active=True)
    db_session.add(hosp)
    db_session.flush()

    codes = ["2", "5", "6", "10", "11", "17", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "52"]
    inds = {}
    for code in codes:
        existing = db_session.query(Indicator).filter(Indicator.code == code).first()
        if existing:
            inds[code] = existing.id
            continue
        ind = Indicator(code=code, name=f"Ind {code}")
        db_session.add(ind)
        db_session.flush()
        inds[code] = ind.id

    # قيم صالحة لكل المصادر
    values = {"2": 100.0, "5": 30.0, "6": 90.0, "10": 5.0, "11": 1.0, "17": 2.0,
              "7": 1.0, "6.f": 8.0, "6.g": 6.0, "2.n": 12.0, "2.c": 3.0, "2.d": 2.0, "52": 9.0}
    for code, val in values.items():
        db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=inds[code], month="2026-06", value=val))

    # مؤشر 52 معطّل يدوياً رغم وجود قيمة
    db_session.add(HospitalIndicatorConfig(hospital_id=hosp.id, indicator_id=inds["52"], is_enabled=False))
    db_session.commit()
    return hosp, inds


def test_load_hospital_data_excludes_disabled_indicators(db_session):
    """المؤشرات المعطّلة (يدوياً أو تلقائياً لغياب البيانات) لا تدخل في متجه التحليل الذكي."""
    from app.engine.smart import _load_hospital_data

    hosp, inds = _seed_smart_data(db_session)
    data = _load_hospital_data(db_session, "2026-06")
    assert hosp.name in data
    vals = data[hosp.name]["values"]
    # المؤشر المعطّل يدوياً (52) مستبعد رغم وجود قيمته
    assert "52" not in vals
    # المشتقات الصحيحة موجودة من المصادر الصالحة
    assert "cs_rate" in vals and vals["cs_rate"] == 30.0
    assert "smm_total" in vals and vals["smm_total"] == 5.0
    assert "total_births" in vals and vals["total_births"] == 90.0
    assert "adolescent" in vals and vals["adolescent"] == 5.0


def test_load_hospital_data_null_derived_stays_none(db_session):
    """عند غياب بيانات المؤشر المصدر تُترك المشتقات None بدل 0 المصطنع."""
    from app.models import SystemSetting
    from app.engine.smart import _load_hospital_data

    # فعّل القاعدة التلقائية (أو قد تكون مفعّلة من بيئة سابقة — أعد ضبطها بوضوح)
    existing = db_session.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
    if existing:
        existing.value = "true"
    else:
        db_session.add(SystemSetting(key="auto_disable_null_indicators", value="true"))
    db_session.commit()

    hosp, inds = _seed_smart_data(db_session)
    # أزل قيمة المؤشر 10 (المضاعفات) لتصبح بلا بيانات
    from app.models import IndicatorValue
    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hosp.id, IndicatorValue.indicator_id == inds["10"]
    ).delete()
    db_session.commit()

    data = _load_hospital_data(db_session, "2026-06")
    vals = data[hosp.name]["values"]
    # smm_total بلا بيانات => لا تُضاف (أو None) بدل 0
    assert "smm_total" not in vals or vals.get("smm_total") is None
    # cs_rate ما زال يُحسب لأن مصدريه (2,5) موجودان
    assert vals.get("cs_rate") == 30.0


def test_load_hospital_data_excludes_hospital_without_any_data(db_session):
    """مستشفى بلا أي قيم صالحة (كلها فارغة) يُستبعد من التحليل الذكي."""
    from app.models import SystemSetting
    from app.engine.smart import _load_hospital_data

    existing = db_session.query(SystemSetting).filter(SystemSetting.key == "auto_disable_null_indicators").first()
    if existing:
        existing.value = "true"
    else:
        db_session.add(SystemSetting(key="auto_disable_null_indicators", value="true"))
    db_session.commit()

    from app.models import Hospital, Indicator, IndicatorValue
    empty_hosp = Hospital(name="Empty Hospital", is_active=True)
    db_session.add(empty_hosp)
    db_session.flush()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    assert ind is not None, "conftest يجب أن يزرع مؤشر 2"
    db_session.add(IndicatorValue(hospital_id=empty_hosp.id, indicator_id=ind.id, month="2026-06", value=None))
    db_session.commit()

    data = _load_hospital_data(db_session, "2026-06")
    assert "Empty Hospital" not in data
