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


def explain_anomalies(
    anomalies: List[SmartAnomalyResult],
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> List[AnomalyExplanation]:
    if not config.get("shap_enabled", True):
        return []

    outliers = [a for a in anomalies if a.is_outlier]
    if not outliers or len(all_hospital_data) < 3:
        return []

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

        sorted_features = sorted(feature_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        top_factors = []
        for feat, val in sorted_features:
            direction = "increases_anomaly" if val > 0 else "decreases_anomaly"
            magnitude = "high" if abs(val) > 0.5 else "medium" if abs(val) > 0.2 else "low"
            arabic = ARABIC_NAMES.get(feat, feat)
            top_factors.append(FactorExplanation(
                feature=feat, shap_value=float(val),
                direction=direction, magnitude=magnitude, arabic_label=arabic,
            ))

        factors_text = []
        for f in top_factors:
            direction_ar = "ارتفاع غير متوقع في" if f.direction == "increases_anomaly" else "انخفاض غير متوقع في"
            factors_text.append(f"{direction_ar} {f.arabic_label}")
        text = f"يظهر هذا المستشفى كشاذ بسبب: {'، '.join(factors_text)}."

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
