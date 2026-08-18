import pytest
from app.engine.smart.schemas import SmartAnomalyResult
from app.engine.smart.explainability import explain_anomalies


@pytest.fixture
def sample_anomalies():
    return [
        SmartAnomalyResult(
            hospital_name="Hospital 0", hospital_id=0,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.8, severity="critical", is_outlier=True,
            method_scores={"isolation_forest": 0.9, "lof": 0.7, "mahalanobis": 0.6, "residual": 0.5},
        ),
        SmartAnomalyResult(
            hospital_name="Hospital 1", hospital_id=1,
            governorate="Gaza", hospital_type="general",
            anomaly_score=0.2, severity="normal", is_outlier=False,
            method_scores={"isolation_forest": 0.1, "lof": 0.2, "mahalanobis": 0.3, "residual": 0.1},
        ),
    ]


@pytest.fixture
def sample_data():
    import numpy as np
    np.random.seed(42)
    data = {}
    for i in range(8):
        data[f"Hospital {i}"] = {
            "hospital_id": i, "governorate": "Gaza", "hospital_type": "general",
            "values": {
                "cs_rate": 25.0 + i * 2 + np.random.normal(0, 1),
                "smm_total": 5.0 + np.random.normal(0, 0.5),
                "mat_deaths": 1.0 + np.random.normal(0, 0.2),
                "nd": 2.0 + np.random.normal(0, 0.3),
                "sb": 1.0, "preterm": 10.0, "lbw": 8.0,
                "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0,
            },
        }
    return data


def test_explanations_for_outliers_only(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results) == 1
    assert results[0].hospital_name == "Hospital 0"


def test_top_factors_present(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].top_factors) > 0
    assert len(results[0].top_factors) <= 3


def test_text_explanation_in_arabic(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results[0].text_explanation) > 0


def test_disabled_returns_empty(sample_anomalies, sample_data):
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": False})
    assert results == []


def test_no_outliers_returns_empty(sample_data):
    anomalies = [
        SmartAnomalyResult(
            hospital_name="H", hospital_id=1, governorate="G", hospital_type="t",
            anomaly_score=0.1, severity="normal", is_outlier=False, method_scores={},
        )
    ]
    results = explain_anomalies(anomalies, sample_data, {"shap_enabled": True})
    assert results == []


def test_rich_text_builder_with_peer_values():
    """باني الجملة ينتج جملة عربية بقيمة المستشفى مقابل متوسط النظير مع % للقيصارية"""
    from app.engine.smart.schemas import FactorExplanation, StratifiedComparison
    from app.engine.smart.explainability import _build_rich_text_explanation

    factors = [
        FactorExplanation(
            feature="cs_rate", shap_value=0.8, direction="increases_anomaly",
            magnitude="high", arabic_label="معدل العمليات القيصارية",
        ),
        FactorExplanation(
            feature="mat_deaths", shap_value=0.4, direction="increases_anomaly",
            magnitude="medium", arabic_label="الوفيات الأمومية",
        ),
    ]
    strat_map = {
        ("Hospital A", "cs_rate"): StratifiedComparison(
            hospital_name="Hospital A", hospital_id=1, indicator="cs_rate",
            hospital_value=60.0, peer_group_mean=28.0, peer_group_std=5.0,
            deviation_pct=114.3, rank_in_peer_group=1, peer_group_size=8,
            label="significantly_above", governorate="Gaza", hospital_type="general",
        ),
        ("Hospital A", "mat_deaths"): StratifiedComparison(
            hospital_name="Hospital A", hospital_id=1, indicator="mat_deaths",
            hospital_value=3.0, peer_group_mean=1.0, peer_group_std=0.5,
            deviation_pct=200.0, rank_in_peer_group=1, peer_group_size=8,
            label="significantly_above", governorate="Gaza", hospital_type="general",
        ),
    }

    text = _build_rich_text_explanation(factors, strat_map, "Hospital A")
    assert "ارتفاع درجة الشذوذ يعود أساساً إلى معدل العمليات القيصارية" in text
    assert "60.0%" in text
    assert "28.0%" in text
    assert "مقابل متوسط النظير" in text
    assert "الوفيات الأمومية" in text  # العامل الثاني يُذكر أيضاً


def test_rich_text_builder_falls_back_empty_without_peer_data():
    """بلا بيانات طبقية يعود النص الفارغ فيستخدم البديل العام"""
    from app.engine.smart.schemas import FactorExplanation
    from app.engine.smart.explainability import _build_rich_text_explanation

    factors = [
        FactorExplanation(
            feature="cs_rate", shap_value=0.8, direction="increases_anomaly",
            magnitude="high", arabic_label="معدل العمليات القيصارية",
        ),
    ]
    assert _build_rich_text_explanation(factors, {}, "Hospital A") == ""


def test_text_explanation_uses_rich_sentence_when_stratified_passed(sample_anomalies, sample_data):
    """عند تمرير التحليل الطبقي تُدمج قيم النظير في جملة التفسير النهائية"""
    from app.engine.smart.anomaly import FEATURE_KEYS
    from app.engine.smart.schemas import StratifiedComparison
    # وفّر بيانات طبقية لكل المؤشرات حتى يجد المحرّك (أيًّا كان) مطابقته
    strat = [
        StratifiedComparison(
            hospital_name="Hospital 0", hospital_id=0, indicator=ind,
            hospital_value=45.0 + i, peer_group_mean=30.0, peer_group_std=4.0,
            deviation_pct=50.0, rank_in_peer_group=1, peer_group_size=8,
            label="significantly_above", governorate="Gaza", hospital_type="general",
        )
        for i, ind in enumerate(FEATURE_KEYS)
    ]
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True}, stratified=strat)
    assert len(results) == 1
    text = results[0].text_explanation
    assert "مقابل متوسط النظير" in text
    assert "30.0%" in text or "30.0" in text  # قيمة النظير (بعلامة % للمؤشرات المئوية)
    assert "يظهر هذا المستشفى كشاذ بسبب" not in text  # استُخدمت الجملة الغنية لا العامة


def test_text_explanation_falls_back_without_stratified(sample_anomalies, sample_data):
    """بدون التحليل الطبقي تبقى الجملة العامة الحالية سليمة"""
    results = explain_anomalies(sample_anomalies, sample_data, {"shap_enabled": True})
    assert len(results) == 1
    assert "يظهر هذا المستشفى كشاذ بسبب" in results[0].text_explanation


def test_shap_direction_semantics_negative_is_driver():
    """SHAP يفسّر decision_function حيث الأقل = أكثر شذوذاً: الإسهام السالب
    يزيد الشذوذ (increases_anomaly)، والموجب يخفضه. هذا عكس التفسير الخاطئ السابق."""
    import numpy as np
    from app.engine.smart.schemas import SmartAnomalyResult
    from app.engine.smart.explainability import explain_anomalies

    # مستشفى بقيمة smm_total مرتفعة شاذة جداً مقابل نظراء طبيعيين
    data = {}
    for i in range(7):
        data[f"Normal {i}"] = {
            "hospital_id": 100 + i, "governorate": "Gaza", "hospital_type": "general",
            "values": {
                "cs_rate": 28.0, "smm_total": 4.0, "mat_deaths": 1.0, "nd": 2.0,
                "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0,
                "high_risk": 15.0, "adolescent": 3.0,
            },
        }
    data["Anomalous"] = {
        "hospital_id": 999, "governorate": "Gaza", "hospital_type": "general",
        "values": {
            "cs_rate": 80.0, "smm_total": 60.0, "mat_deaths": 5.0, "nd": 8.0,
            "sb": 6.0, "preterm": 40.0, "lbw": 25.0, "total_births": 400.0,
            "high_risk": 60.0, "adolescent": 20.0,
        },
    }
    anomalies = [SmartAnomalyResult(
        hospital_name="Anomalous", hospital_id=999,
        governorate="Gaza", hospital_type="general",
        anomaly_score=0.9, severity="critical", is_outlier=True,
        method_scores={"isolation_forest": 0.9, "lof": 0.8, "mahalanobis": 0.7, "residual": 0.6},
    )]
    results = explain_anomalies(anomalies, data, {"shap_enabled": True})
    assert len(results) == 1
    factors = results[0].top_factors
    assert factors
    # العوامل ذات المساهمة السالبة هي المسؤولة (تزيد الشذوذ)
    driver = [f for f in factors if f.direction == "increases_anomaly"]
    non_driver = [f for f in factors if f.direction == "decreases_anomaly"]
    assert driver, "يجب وجود عامل موجب للشذوذ (إسهام سالب) لمستشفى شاذ فعلاً"
    # التحقق من الاتساق: كل عامل سالب في SHAP مصنّف كمسؤول، وكل موجب كغير مسؤول
    for f in factors:
        if f.shap_value < 0:
            assert f.direction == "increases_anomaly", f"{f.feature}: سالب يجب أن يزيد الشذوذ"
        elif f.shap_value > 0:
            assert f.direction == "decreases_anomaly", f"{f.feature}: موجب يجب أن يخفض الشذوذ"


def test_fallback_phrase_uses_actual_value_direction():
    """الجملة الاحتياطية تصف اتجاه القيمة الفعلية (ارتفاع/انخفاض حقيقي مقابل النظير)
    لا اتجاه إشارة SHAP — فالمستشفى الذي قيمته منخفضة جداً يظهر كـ«انخفاض» حتى لو
    كان عاملاً مسؤولاً عن الشذوذ."""
    from app.engine.smart.schemas import StratifiedComparison
    from app.engine.smart.explainability import explain_anomalies

    # مستشفى شاذ لأن قيمه كلها صفر (انخفاض حاد) مقابل نظراء بقيم طبيعية
    data = {}
    for i in range(7):
        data[f"Normal {i}"] = {
            "hospital_id": 100 + i, "governorate": "Gaza", "hospital_type": "general",
            "values": {
                "cs_rate": 28.0, "smm_total": 4.0, "mat_deaths": 1.0, "nd": 2.0,
                "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0,
                "high_risk": 15.0, "adolescent": 3.0,
            },
        }
    data["AllZeros"] = {
        "hospital_id": 888, "governorate": "Gaza", "hospital_type": "general",
        "values": {k: 0.0 for k in ["cs_rate", "smm_total", "mat_deaths", "nd", "sb", "preterm", "lbw", "total_births", "high_risk", "adolescent"]},
    }
    anomalies = [SmartAnomalyResult(
        hospital_name="AllZeros", hospital_id=888,
        governorate="Gaza", hospital_type="general",
        anomaly_score=0.85, severity="critical", is_outlier=True,
        method_scores={"isolation_forest": 0.9, "lof": 0.8, "mahalanobis": 0.7, "residual": 0.6},
    )]
    # بيانات طبقية تُظهر أن قيم المستشفى أقل من النظير (انخفاض فعلي)
    from app.engine.smart.anomaly import FEATURE_KEYS
    strat = [StratifiedComparison(
        hospital_name="AllZeros", hospital_id=888, indicator=ind,
        hospital_value=0.0, peer_group_mean=20.0, peer_group_std=5.0,
        deviation_pct=-100.0, rank_in_peer_group=8, peer_group_size=8,
        label="significantly_below", governorate="Gaza", hospital_type="general",
    ) for ind in FEATURE_KEYS]
    results = explain_anomalies(anomalies, data, {"shap_enabled": True}, stratified=strat)
    assert len(results) == 1
    text = results[0].text_explanation
    # القيم الفعلية كلها صفر مقابل نظير 20: يجب أن تصف الجملة انخفاضاً فعلياً لا ارتفاعاً
    # (ضمان أن حارس «القيمة المرتفعة فقط» في الجملة الغنية لم يُنتج جملة ارتفاع خاطئة)
    assert "انخفاض" in text
    assert "ارتفاع درجة الشذوذ يعود أساساً إلى" not in text
