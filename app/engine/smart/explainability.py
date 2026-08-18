import numpy as np
from typing import Dict, Any, List
import shap
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer

from app.engine.smart.schemas import SmartAnomalyResult, AnomalyExplanation, FactorExplanation
from app.engine.smart.anomaly import FEATURE_KEYS

ARABIC_NAMES = {
    "cs_rate": "معدل العمليات القيصارية",
    "smm_total": "المضاعفات الخطيرة",
    "mat_deaths": "الوفيات الأمومية",
    "nd": "الوفيات الجديدة",
    "sb": "الولادات الميتة",
    "preterm": "الولادات السابقة لأوانها",
    "lbw": "نقص وزن الولادة",
    "total_births": "إجمالي المواليد",
    "high_risk": "حالات الخطر العالي",
    "adolescent": "الحالات المراهقة",
    "governorate": "المحافظة",
    "hospital_type": "نوع المستشفى",
}

# المؤشرات المعبَّر عنها كنسب مئوية (تظهر بعلامة %)، والباقي أعداد أولية
_PERCENT_INDICATORS = {"cs_rate"}


def _format_indicator_value(indicator: str, value: float) -> str:
    if indicator in _PERCENT_INDICATORS:
        return f"{value:.1f}%"
    return f"{value:.1f}"


def _build_rich_text_explanation(
    top_factors: List[FactorExplanation],
    strat_map: Dict,
    hospital_name: str,
) -> str:
    """جملة تفسير عربية مولّدة تربط العامل الأبرز بقيمة المستشفى مقابل متوسط النظير.

    مثال: «ارتفاع درجة الشذوذ يعود أساساً إلى معدل العمليات القيصارية: 60.0%
    مقابل متوسط النظير 28.0%». يُفضَّل العامل ذو المساهمة السالبة في
    decision_function (الذي يزيد الشذوذ في IsolationForest).
    """
    if not top_factors:
        return ""

    # اختر أول عامل مسؤول (يزيد الشذوذ) قيمته الفعلية فعلاً فوق متوسط النظير، حتى
    # تبقى صيغة «ارتفاع درجة الشذوذ يعود أساساً إلى...» صادقة. أما المستشفى الذي
    # شذوذه ناتج عن نقص إبلاغ (قيم صفرية) فتُترك الجملة للبديل الاحتياطي الذي
    # يصف الاتجاه الفعلي للقيمة (انخفاض).
    driver = None
    for f in top_factors:
        if f.direction != "increases_anomaly":
            continue
        entry = strat_map.get((hospital_name, f.feature))
        if entry is None or entry.hospital_value is None or entry.peer_group_mean is None:
            continue
        if entry.hospital_value > entry.peer_group_mean:
            driver = f
            break
    if driver is None:
        return ""

    entry = strat_map[(hospital_name, driver.feature)]
    value = _format_indicator_value(driver.feature, entry.hospital_value)
    peer = _format_indicator_value(driver.feature, entry.peer_group_mean)

    sentence = (
        f"ارتفاع درجة الشذوذ يعود أساساً إلى {driver.arabic_label}: "
        f"{value} مقابل متوسط النظير {peer}."
    )

    # أضف عاملاً ثانياً مرتفعاً فعلاً إن وُجد له سياق نظيري واضح
    for f in top_factors[1:]:
        if f.feature == driver.feature or f.direction != "increases_anomaly":
            continue
        entry2 = strat_map.get((hospital_name, f.feature))
        if entry2 is None or entry2.hospital_value is None or entry2.peer_group_mean is None:
            continue
        if entry2.hospital_value <= entry2.peer_group_mean:
            continue
        v2 = _format_indicator_value(f.feature, entry2.hospital_value)
        p2 = _format_indicator_value(f.feature, entry2.peer_group_mean)
        sentence += f" كما يبرز {f.arabic_label}: {v2} مقابل {p2}."
        break

    return sentence


def explain_anomalies(
    anomalies: List[SmartAnomalyResult],
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    stratified: List = None,
) -> List[AnomalyExplanation]:
    if not config.get("shap_enabled", True):
        return []

    outliers = [a for a in anomalies if a.is_outlier]
    if not outliers or len(all_hospital_data) < 3:
        return []

    # فهرس (مستشفى، مؤشر) -> مقارنة طبقية، لتغذية جملة التفسير بقيم حقيقية
    strat_map = {}
    if stratified:
        for s in stratified:
            strat_map[(s.hospital_name, s.indicator)] = s

    hospital_names = list(all_hospital_data.keys())

    numeric_features = []
    categorical_data = []
    for name in hospital_names:
        entry = all_hospital_data[name]
        values = entry.get("values", {})
        row = [values.get(k, np.nan) for k in FEATURE_KEYS]
        numeric_features.append(row)
        categorical_data.append([
            entry.get("governorate", "unknown"),
            entry.get("hospital_type", "unknown"),
        ])

    numeric_array = np.array(numeric_features, dtype=float)
    # Columns where EVERY hospital is NaN would make SimpleImputer skip them AND
    # leave NaN that poisons StandardScaler + SHAP. Zero-fill up-front.
    numeric_array[:, np.isnan(numeric_array).all(axis=0)] = 0.0
    imputer = SimpleImputer(strategy="median")
    numeric_imputed = imputer.fit_transform(numeric_array)
    scaler = StandardScaler()
    numeric_scaled = scaler.fit_transform(numeric_imputed)

    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    categorical_encoded = encoder.fit_transform(categorical_data)

    combined = np.hstack([numeric_scaled, categorical_encoded])

    feature_names = list(FEATURE_KEYS)
    feature_names += list(encoder.get_feature_names_out(["governorate", "hospital_type"]))

    contamination = config.get("contamination", 0.1)
    iforest = IsolationForest(contamination=contamination, random_state=42)
    iforest.fit(combined)

    explainer = shap.TreeExplainer(iforest)
    shap_values = explainer.shap_values(combined)

    explanations = []
    for outlier in outliers:
        idx = hospital_names.index(outlier.hospital_name) if outlier.hospital_name in hospital_names else -1
        if idx < 0:
            continue

        sv = shap_values[idx]
        feature_shap = dict(zip(feature_names, sv.tolist()))

        sorted_features = sorted(feature_shap.items(), key=lambda x: abs(x[1]), reverse=True)

        numeric_factors = [(f, v) for f, v in sorted_features if not f.startswith("governorate_") and not f.startswith("hospital_type_")]
        context_factors = [(f, v) for f, v in sorted_features if f.startswith("governorate_") or f.startswith("hospital_type_")]

        top_factors = []
        for feat, val in numeric_factors[:3]:
            # SHAP يفسّر مخرَج IsolationForest.raw (decision_function) حيث القيمة
            # الأقل = أكثر شذوذاً. إذن الإسهام السالب في decision_function يدفع
            # المستشفى نحو الشذوذ (زيادة)، والموجب يدفعه نحو الطبيعي (نقصان).
            direction = "increases_anomaly" if val < 0 else "decreases_anomaly"
            magnitude = "high" if abs(val) > 0.5 else "medium" if abs(val) > 0.2 else "low"
            arabic = ARABIC_NAMES.get(feat, feat)
            top_factors.append(FactorExplanation(
                feature=feat, shap_value=float(val),
                direction=direction, magnitude=magnitude, arabic_label=arabic,
            ))

        # اتجاه الجملة يُشتق من القيمة الفعلية مقابل النظير (ارتفاع/انخفاض حقيقي)،
        # لا من إشارة SHAP التي تعبّر عن المساهمة في مخرَج النموذج لا عن اتجاه القيمة
        factors_text = []
        for f in top_factors:
            entry = strat_map.get((outlier.hospital_name, f.feature))
            if entry is not None and entry.hospital_value is not None and entry.peer_group_mean is not None:
                if entry.hospital_value > entry.peer_group_mean:
                    direction_ar = "ارتفاع غير متوقع في"
                elif entry.hospital_value < entry.peer_group_mean:
                    direction_ar = "انخفاض غير متوقع في"
                else:
                    direction_ar = "انحراف غير متوقع في"
            else:
                direction_ar = "انحراف غير متوقع في"
            factors_text.append(f"{direction_ar} {f.arabic_label}")

        # جملة مولّدة ببيانات حقيقية (قيمة المستشفى مقابل متوسط النظير) عند توفرها،
        # مع الاحتفاظ بالجملة العامة كبديل احتياطي
        rich = _build_rich_text_explanation(top_factors, strat_map, outlier.hospital_name)
        text = rich or f"يظهر هذا المستشفى كشاذ بسبب: {'، '.join(factors_text)}."

        explanations.append(AnomalyExplanation(
            hospital_name=outlier.hospital_name,
            hospital_id=outlier.hospital_id,
            anomaly_score=outlier.anomaly_score,
            severity=outlier.severity,
            shap_values=feature_shap,
            top_factors=top_factors,
            text_explanation=text,
        ))

    return explanations
