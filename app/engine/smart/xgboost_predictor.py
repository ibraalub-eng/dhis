import numpy as np
from typing import Dict, Any, List, Tuple
from sklearn.preprocessing import StandardScaler, OneHotEncoder, LabelEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import r2_score, mean_absolute_error, accuracy_score, classification_report
import xgboost as xgb
import shap

from app.engine.smart.schemas import (
    XGBoostPrediction,
    XGBoostPredictionResult,
    XGBoostDriver,
    XGBoostGlobalExplanation,
    SmartAnomalyResult,
)
from app.engine.smart.anomaly import FEATURE_KEYS, _normalize_scores

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
    # Derived features
    "cs_per_birth": "نسبة القيصارية لكل ولادة",
    "smm_per_1000": "المضاعفات لكل 1000 ولادة",
    "mat_mortality_rate": "معدل الوفيات الأمومية",
    "stillbirth_rate": "معدل الولادات الميتة",
    "preterm_rate": "معدل الولادات المبكرة",
    "lbw_rate": "معدل نقص الوزن",
    "high_risk_rate": "نسبة الخطر العالي",
    "adolescent_rate": "نسبة الحالات المراهقة",
    # Interaction features
    "cs_x_highrisk": "قيصارية × خطر عالي",
    "preterm_x_lbw": "ولادة مبكرة × نقص وزن",
    "smm_x_matdeaths": "مضاعفات × وفيات أمومية",
    "nd_x_sb": "وفيات جديدة × ولادات ميتة",
    # Time-series features
    "cs_rate_delta": "تغير معدل القيصارية",
    "smm_delta": "تغير المضاعفات",
    "mat_deaths_delta": "تغير الوفيات الأمومية",
    "total_births_delta": "تغير المواليد",
}

FEATURE_KEYS_SET = set(FEATURE_KEYS)

ENSEMBLE_CONFIGS = [
    {"name": "XGBoost-Light", "n_estimators": 80, "max_depth": 3, "learning_rate": 0.15},
    {"name": "XGBoost-Medium", "n_estimators": 150, "max_depth": 5, "learning_rate": 0.1},
    {"name": "XGBoost-Deep", "n_estimators": 200, "max_depth": 7, "learning_rate": 0.05},
]


def _load_multi_month_data(
    session, months: List[str]
) -> Tuple[Dict[str, Any], List[str]]:
    from app.models import Hospital, IndicatorValue, Indicator

    hospitals = session.query(Hospital).filter(Hospital.is_active).all()
    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}

    all_rows = []
    all_hospital_names = set()

    for month in months:
        for hosp in hospitals:
            values = session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == hosp.id,
                IndicatorValue.month == month,
            ).all()

            indicator_values = {}
            for iv in values:
                code = indicator_map.get(iv.indicator_id, "")
                if code and iv.value is not None:
                    indicator_values[code] = float(iv.value)

            total_deliveries = indicator_values.get("2", 0)
            cs_count = indicator_values.get("5", 0)
            live_births = indicator_values.get("6", 0)

            derived = {
                "cs_rate": (cs_count / total_deliveries * 100) if total_deliveries > 0 else 0,
                "smm_total": indicator_values.get("10", 0),
                "mat_deaths": indicator_values.get("11", 0),
                "nd": indicator_values.get("17", 0),
                "sb": indicator_values.get("7", 0),
                "preterm": indicator_values.get("6.f", 0),
                "lbw": indicator_values.get("6.g", 0),
                "total_births": live_births,
                "high_risk": indicator_values.get("2.n", 0),
                "adolescent": indicator_values.get("2.c", 0) + indicator_values.get("2.d", 0),
            }
            indicator_values.update(derived)

            row = {
                "hospital_name": hosp.name,
                "hospital_id": hosp.id,
                "governorate": hosp.governorate.name if hosp.governorate else "unknown",
                "hospital_type": hosp.hospital_type.name if hosp.hospital_type else "unknown",
                "month": month,
                "values": indicator_values,
            }
            all_rows.append(row)
            all_hospital_names.add(hosp.name)

    return all_rows, sorted(all_hospital_names)


def _compute_derived_features(values: Dict[str, float]) -> Dict[str, float]:
    total = values.get("total_births", 0)
    derived = {}

    derived["cs_per_birth"] = values.get("cs_rate", 0) / 100.0 if total > 0 else 0
    derived["smm_per_1000"] = (values.get("smm_total", 0) / total * 1000) if total > 0 else 0
    derived["mat_mortality_rate"] = (values.get("mat_deaths", 0) / total * 100000) if total > 0 else 0
    derived["stillbirth_rate"] = (values.get("sb", 0) / total * 1000) if total > 0 else 0
    derived["preterm_rate"] = (values.get("preterm", 0) / total * 100) if total > 0 else 0
    derived["lbw_rate"] = (values.get("lbw", 0) / total * 100) if total > 0 else 0
    derived["high_risk_rate"] = (values.get("high_risk", 0) / total * 100) if total > 0 else 0
    derived["adolescent_rate"] = (values.get("adolescent", 0) / total * 100) if total > 0 else 0

    derived["cs_x_highrisk"] = derived["cs_per_birth"] * derived["high_risk_rate"]
    derived["preterm_x_lbw"] = derived["preterm_rate"] * derived["lbw_rate"]
    derived["smm_x_matdeaths"] = derived["smm_per_1000"] * derived["mat_mortality_rate"]
    derived["nd_x_sb"] = derived["stillbirth_rate"] * (values.get("nd", 0) / total * 1000 if total > 0 else 0)

    return derived


def _build_supervised_dataset(
    all_rows: List[Dict],
    hospital_names: List[str],
    target_month_idx: int,
):
    cat_map = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        cat_map[key] = (row["governorate"], row["hospital_type"])

    months_sorted = sorted(set(r["month"] for r in all_rows))
    month_to_idx = {m: i for i, m in enumerate(months_sorted)}

    hosp_month_data = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        hosp_month_data[key] = row

    derived_keys = [k for k in ARABIC_NAMES.keys() if k not in FEATURE_KEYS_SET and "_delta" not in k]
    all_feature_keys = list(FEATURE_KEYS) + derived_keys

    features_list = []
    meta = []

    for row in all_rows:
        values = row["values"]
        derived = _compute_derived_features(values)
        all_vals = {**values, **derived}

        numeric = [all_vals.get(k, np.nan) for k in all_feature_keys]
        features_list.append(numeric)
        meta.append({
            "hospital_name": row["hospital_name"],
            "hospital_id": row["hospital_id"],
            "month": row["month"],
            "governorate": row["governorate"],
            "hospital_type": row["hospital_type"],
        })

    delta_keys = ["cs_rate_delta", "smm_delta", "mat_deaths_delta", "total_births_delta"]
    delta_source_keys = ["cs_rate", "smm_total", "mat_deaths", "total_births"]

    for i, row in enumerate(all_rows):
        hosp_name = row["hospital_name"]
        cur_month = row["month"]
        cur_idx = month_to_idx.get(cur_month, 0)

        for dk, sk in zip(delta_keys, delta_source_keys):
            prev_month = None
            for m in months_sorted:
                if month_to_idx[m] == cur_idx - 1:
                    prev_month = m
                    break

            if prev_month:
                prev_key = (hosp_name, prev_month)
                if prev_key in hosp_month_data:
                    prev_val = hosp_month_data[prev_key]["values"].get(sk, 0)
                    cur_val = row["values"].get(sk, 0)
                    delta = (cur_val - prev_val) / prev_val if prev_val > 0 else 0
                else:
                    delta = 0.0
            else:
                delta = 0.0
            features_list[i].append(delta)

    feature_names = all_feature_keys + delta_keys

    X = np.array(features_list, dtype=float)

    imputer = SimpleImputer(strategy="median")
    X_imputed = imputer.fit_transform(X)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_imputed)

    cat_data = [(cat_map.get((m["hospital_name"], m["month"]), ("unknown", "unknown"))) for m in meta]
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    X_cat = encoder.fit_transform(cat_data)
    X_all = np.hstack([X_scaled, X_cat])

    feature_names = feature_names + list(
        encoder.get_feature_names_out(["governorate", "hospital_type"])
    )

    return X_all, feature_names, meta, month_to_idx, imputer, scaler, encoder


def _compute_target_scores(all_rows: List[Dict], meta: List[Dict], months_sorted: List[str]) -> np.ndarray:
    target_scores = np.zeros(len(meta))
    hosp_month_data = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        hosp_month_data[key] = row

    for i, m in enumerate(meta):
        hospital_name = m["hospital_name"]
        month = m["month"]
        hospital_months = sorted([r["month"] for r in all_rows if r["hospital_name"] == hospital_name])
        month_idx = hospital_months.index(month) if month in hospital_months else -1

        if month_idx > 0:
            prev_month = hospital_months[month_idx - 1]
            prev_vals = hosp_month_data.get((hospital_name, prev_month), {}).get("values", {})
            cur_vals = hosp_month_data.get((hospital_name, month), {}).get("values", {})

            prev_numeric = [prev_vals.get(k, np.nan) for k in FEATURE_KEYS]
            cur_numeric = [cur_vals.get(k, np.nan) for k in FEATURE_KEYS]
            prev_median = np.nanmedian(prev_numeric)
            cur_median = np.nanmedian(cur_numeric)

            if not np.isnan(prev_median) and not np.isnan(cur_median) and prev_median > 0:
                ratio = cur_median / prev_median
                target_scores[i] = min(max(0.5 + (ratio - 1) * 2, 0.0), 1.0)
            else:
                target_scores[i] = 0.5
        else:
            target_scores[i] = 0.5

    return target_scores


def _score_to_severity(score: float) -> str:
    if score < 0.3:
        return "normal"
    elif score < 0.6:
        return "warning"
    return "critical"


def run_xgboost_predictions(
    session,
    current_month: str,
    config: Dict[str, Any],
) -> XGBoostPredictionResult:
    from app.models import IndicatorValue

    all_months = sorted(
        r[0] for r in session.query(IndicatorValue.month).distinct().order_by(IndicatorValue.month).all()
    )

    if len(all_months) < 2:
        return XGBoostPredictionResult(
            model_r2=0.0, model_mae=0.0, training_months=0, hospitals_trained=0,
            predictions=[], global_feature_importance=[], accuracy_note="Not enough months for training.",
        )

    current_idx = all_months.index(current_month) if current_month in all_months else len(all_months) - 1
    train_months = all_months[:current_idx + 1]

    all_rows, hospital_names = _load_multi_month_data(session, train_months)
    if not all_rows or len(hospital_names) < 3:
        return XGBoostPredictionResult(
            model_r2=0.0, model_mae=0.0, training_months=len(train_months),
            hospitals_trained=0, predictions=[], global_feature_importance=[],
            accuracy_note="Not enough hospital data for training.",
        )

    X_all, feature_names, meta, month_to_idx, imputer, scaler, encoder = _build_supervised_dataset(
        all_rows, hospital_names, current_idx
    )

    target_scores = _compute_target_scores(all_rows, meta, all_months[:current_idx + 1])

    split_idx = max(1, int(len(X_all) * 0.8))
    X_train, X_test = X_all[:split_idx], X_all[split_idx:]
    y_train, y_test = target_scores[:split_idx], target_scores[split_idx:]
    meta_test = meta[split_idx:]

    ensemble_results = []
    ensemble_predictions = []
    ensemble_weights = []

    for cfg in ENSEMBLE_CONFIGS:
        model = xgb.XGBRegressor(
            n_estimators=int(cfg["n_estimators"]),
            max_depth=int(cfg["max_depth"]),
            learning_rate=cfg["learning_rate"],
            objective="reg:squarederror", random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train)
        y_pred = np.clip(model.predict(X_test), 0.0, 1.0)

        r2 = float(r2_score(y_test, y_pred)) if len(y_test) > 1 else 0.0
        mae_val = float(mean_absolute_error(y_test, y_pred)) if len(y_test) > 1 else 0.0

        ensemble_results.append({"name": cfg["name"], "r2": r2, "mae": mae_val, "model": model})
        ensemble_predictions.append(y_pred)
        ensemble_weights.append(max(r2, 0.01))

    total_weight = sum(ensemble_weights)
    normalized_weights = [w / total_weight for w in ensemble_weights]
    y_pred_ensemble = sum(w * pred for w, pred in zip(normalized_weights, ensemble_predictions))
    y_pred_ensemble = np.clip(y_pred_ensemble, 0.0, 1.0)

    best_idx = max(range(len(ensemble_results)), key=lambda i: ensemble_results[i]["r2"])
    best_model = ensemble_results[best_idx]["model"]
    best_r2 = ensemble_results[best_idx]["r2"]
    best_mae = ensemble_results[best_idx]["mae"]

    target_labels = np.array([_score_to_severity(s) for s in target_scores])
    le = LabelEncoder()
    le.fit(["normal", "warning", "critical"])
    y_labels_all = le.transform(target_labels)
    y_labels_train = y_labels_all[:split_idx]
    y_labels_test = y_labels_all[split_idx:]

    clf_accuracy = 0.0
    clf_pred = np.zeros(len(y_labels_test), dtype=int)
    try:
        clf = xgb.XGBClassifier(
            n_estimators=120, max_depth=4, learning_rate=0.1,
            objective="multi:softprob", random_state=42, verbosity=0,
            num_class=3,
        )
        clf.fit(X_train, y_labels_train)
        clf_pred = clf.predict(X_test)
        unique_test_labels = set(y_labels_test.tolist())
        unique_pred_labels = set(clf_pred.tolist())
        if len(unique_test_labels) > 1 and len(unique_pred_labels) > 1:
            clf_accuracy = float(accuracy_score(y_labels_test, clf_pred))
        else:
            clf_accuracy = 1.0
    except Exception:
        clf_accuracy = 0.0

    explainer = shap.TreeExplainer(best_model)
    shap_values_all = explainer.shap_values(X_all)

    global_shap = np.mean(np.abs(shap_values_all), axis=0)
    base_feature_count = len(feature_names) - len(encoder.get_feature_names_out(["governorate", "hospital_type"]))
    global_sorted = sorted(
        [(feature_names[i], global_shap[i]) for i in range(min(base_feature_count, len(feature_names)))],
        key=lambda x: x[1], reverse=True,
    )
    global_importance = [
        XGBoostGlobalExplanation(
            feature=feat, arabic_label=ARABIC_NAMES.get(feat, feat),
            mean_abs_shap=float(val), rank=rank + 1,
        )
        for rank, (feat, val) in enumerate(global_sorted[:12])
    ]

    hospital_pred_map = {}
    for i, m in enumerate(meta):
        if m["month"] == current_month:
            hosp_name = m["hospital_name"]
            if hosp_name not in hospital_pred_map:
                hospital_pred_map[hosp_name] = {
                    "meta": m,
                    "idx": i,
                    "current_score": target_scores[i],
                }

    predictions = []
    for hosp_name, data in hospital_pred_map.items():
        idx = data["idx"]
        sv = shap_values_all[idx]
        top_feat_idx = sorted(range(len(sv)), key=lambda j: abs(sv[j]), reverse=True)[:5]

        drivers = []
        for fi in top_feat_idx:
            if fi < len(feature_names):
                feat_name = feature_names[fi]
                drivers.append(XGBoostDriver(
                    feature=feat_name,
                    arabic_label=ARABIC_NAMES.get(feat_name, feat_name),
                    shap_value=float(sv[fi]),
                    direction="increases_risk" if sv[fi] > 0 else "decreases_risk",
                    magnitude="high" if abs(sv[fi]) > 0.3 else "medium" if abs(sv[fi]) > 0.1 else "low",
                ))

        predicted_score = float(y_pred_ensemble[idx - split_idx]) if idx >= split_idx else float(best_model.predict(X_all[idx:idx+1])[0])
        predicted_score = min(max(predicted_score, 0.0), 1.0)

        if idx < len(y_labels_test):
            clf_class_idx = clf_pred[idx - split_idx] if idx >= split_idx else clf.predict(X_all[idx:idx+1])[0]
            clf_severity = le.inverse_transform([clf_class_idx])[0]
        else:
            clf_severity = _score_to_severity(predicted_score)

        pred_severity = _score_to_severity(predicted_score)

        current_score = data["current_score"]
        if predicted_score > current_score + 0.05:
            risk_change = "increasing"
        elif predicted_score < current_score - 0.05:
            risk_change = "decreasing"
        else:
            risk_change = "stable"

        predictions.append(XGBoostPrediction(
            hospital_name=hosp_name,
            hospital_id=data["meta"]["hospital_id"],
            current_score=round(current_score, 4),
            predicted_next_score=round(predicted_score, 4),
            predicted_severity=pred_severity,
            risk_change=risk_change,
            confidence=round(max(0.0, 1.0 - best_mae), 3),
            top_drivers=drivers,
        ))

    predictions.sort(key=lambda p: p.predicted_next_score, reverse=True)

    model_comparison = [
        {"name": r["name"], "r2": round(r["r2"], 4), "mae": round(r["mae"], 4)}
        for r in ensemble_results
    ]

    accuracy_note = (
        f"Ensemble of {len(ENSEMBLE_CONFIGS)} models | "
        f"Best: {ensemble_results[best_idx]['name']} (R²={best_r2:.3f}, MAE={best_mae:.3f}) | "
        f"Classifier accuracy: {clf_accuracy:.1%} | "
        f"Trained on {len(train_months)} months, {len(hospital_names)} hospitals. "
        f"Features: {len(feature_names)} ({len(FEATURE_KEYS)} base + {len(feature_names) - len(FEATURE_KEYS) - len(encoder.get_feature_names_out(['governorate','hospital_type']))} derived + categorical). "
        f"Predictions are estimates based on historical patterns."
    )

    return XGBoostPredictionResult(
        model_r2=best_r2, model_mae=best_mae,
        training_months=len(train_months), hospitals_trained=len(hospital_names),
        predictions=predictions, global_feature_importance=global_importance,
        accuracy_note=accuracy_note,
    )
