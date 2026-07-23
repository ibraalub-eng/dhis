import numpy as np
from typing import Dict, Any, List, Tuple
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import r2_score, mean_absolute_error
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
    "cs_rate": "\u0645\u0639\u062f\u0644 \u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a \u0627\u0644\u0642\u064a\u0635\u0627\u0631\u064a\u0629",
    "smm_total": "\u0627\u0644\u0645\u0636\u0627\u0639\u0641\u0627\u062a \u0627\u0644\u062e\u0637\u064a\u0631\u0629",
    "mat_deaths": "\u0627\u0644\u0648\u0641\u064a\u0627\u062a \u0627\u0644\u0623\u0645\u0648\u0645\u064a\u0629",
    "nd": "\u0627\u0644\u0648\u0641\u064a\u0627\u062a \u0627\u0644\u062c\u062f\u064a\u062f\u0629",
    "sb": "\u0627\u0644\u0648\u0644\u0627\u062f\u0627\u062a \u0627\u0644\u0645\u064a\u062a\u0629",
    "preterm": "\u0627\u0644\u0648\u0644\u0627\u062f\u0627\u062a \u0627\u0644\u0633\u0627\u0628\u0642\u0629 \u0644\u0623\u0646\u0648\u0627\u0639\u0647\u0627",
    "lbw": "\u0646\u0642\u0635 \u0648\u0632\u0646 \u0627\u0644\u0648\u0644\u0627\u062f\u0629",
    "total_births": "\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0645\u0648\u0627\u0644\u064a\u062f",
    "high_risk": "\u062d\u0627\u0644\u0627\u062a \u0627\u0644\u062e\u0637\u0631 \u0627\u0644\u0639\u0627\u0644\u064a",
    "adolescent": "\u0627\u0644\u062d\u0627\u0644\u0627\u062a \u0627\u0644\u0645\u0631\u0627\u0647\u0642\u0629",
}


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


def _build_supervised_dataset(
    all_rows: List[Dict],
    hospital_names: List[str],
    target_month_idx: int,
):
    cat_map = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        cat_map[key] = (row["governorate"], row["hospital_type"])

    features_list = []
    targets = []
    meta = []

    for row in all_rows:
        values = row["values"]
        numeric = [values.get(k, np.nan) for k in FEATURE_KEYS]
        features_list.append(numeric)
        meta.append({
            "hospital_name": row["hospital_name"],
            "hospital_id": row["hospital_id"],
            "month": row["month"],
            "governorate": row["governorate"],
            "hospital_type": row["hospital_type"],
        })

    X = np.array(features_list, dtype=float)
    months = sorted(set(r["month"] for r in all_rows))
    month_to_idx = {m: i for i, m in enumerate(months)}

    imputer = SimpleImputer(strategy="median")
    X_imputed = imputer.fit_transform(X)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_imputed)

    cat_data = [(cat_map.get((m["hospital_name"], m["month"]), ("unknown", "unknown"))) for m in meta]
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    X_cat = encoder.fit_transform(cat_data)
    X_all = np.hstack([X_scaled, X_cat])

    feature_names = list(FEATURE_KEYS) + list(
        encoder.get_feature_names_out(["governorate", "hospital_type"])
    )

    return X_all, feature_names, meta, month_to_idx, imputer, scaler, encoder


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

    target_scores = np.zeros(len(meta))
    for i, m in enumerate(meta):
        hospital_name = m["hospital_name"]
        month = m["month"]
        hospital_rows = [r for r in all_rows if r["hospital_name"] == hospital_name]
        month_vals = [r["values"] for r in hospital_rows]
        if len(month_vals) > 1:
            prev_vals = month_vals[-2] if month_vals[-1] == month else month_vals[-1]
            prev_numeric = [prev_vals.get(k, np.nan) for k in FEATURE_KEYS]
            prev_median = np.nanmedian(prev_numeric)
            cur_numeric = [month_vals[-1].get(k, np.nan) for k in FEATURE_KEYS]
            cur_median = np.nanmedian(cur_numeric)
            if not np.isnan(prev_median) and not np.isnan(cur_median) and prev_median > 0:
                ratio = cur_median / prev_median
                target_scores[i] = min(max(0.5 + (ratio - 1) * 2, 0.0), 1.0)
            else:
                target_scores[i] = 0.5
        else:
            target_scores[i] = 0.5

    split_idx = max(1, int(len(X_all) * 0.8))
    X_train, X_test = X_all[:split_idx], X_all[split_idx:]
    y_train, y_test = target_scores[:split_idx], target_scores[split_idx:]
    meta_test = meta[split_idx:]

    n_est = int(min(config.get("xgb_n_estimators", 100), 200))
    max_d = int(min(config.get("xgb_max_depth", 4), 8))

    model = xgb.XGBRegressor(
        n_estimators=n_est, max_depth=max_d, learning_rate=0.1,
        objective="reg:squarederror", random_state=42, verbosity=0,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_pred = np.clip(y_pred, 0.0, 1.0)

    r2 = float(r2_score(y_test, y_pred)) if len(y_test) > 1 else 0.0
    mae_val = float(mean_absolute_error(y_test, y_pred)) if len(y_test) > 1 else 0.0

    explainer = shap.TreeExplainer(model)
    shap_values_all = explainer.shap_values(X_all)

    global_shap = np.mean(np.abs(shap_values_all), axis=0)
    global_sorted = sorted(
        [(feature_names[i], global_shap[i]) for i in range(len(feature_names)) if i < len(FEATURE_KEYS)],
        key=lambda x: x[1], reverse=True,
    )
    global_importance = [
        XGBoostGlobalExplanation(
            feature=feat, arabic_label=ARABIC_NAMES.get(feat, feat),
            mean_abs_shap=float(val), rank=rank + 1,
        )
        for rank, (feat, val) in enumerate(global_sorted[:10])
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
            if fi < len(FEATURE_KEYS):
                feat_name = feature_names[fi]
                drivers.append(XGBoostDriver(
                    feature=feat_name,
                    arabic_label=ARABIC_NAMES.get(feat_name, feat_name),
                    shap_value=float(sv[fi]),
                    direction="increases_risk" if sv[fi] > 0 else "decreases_risk",
                    magnitude="high" if abs(sv[fi]) > 0.3 else "medium" if abs(sv[fi]) > 0.1 else "low",
                ))

        predicted_score = float(y_pred[idx - split_idx]) if idx >= split_idx else float(model.predict(X_all[idx:idx+1])[0])
        predicted_score = min(max(predicted_score, 0.0), 1.0)

        if predicted_score < 0.3:
            pred_severity = "normal"
        elif predicted_score < 0.6:
            pred_severity = "warning"
        else:
            pred_severity = "critical"

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
            confidence=round(max(0.0, 1.0 - mae_val), 3),
            top_drivers=drivers,
        ))

    predictions.sort(key=lambda p: p.predicted_next_score, reverse=True)

    accuracy_note = (
        f"Trained on {len(train_months)} months, {len(hospital_names)} hospitals. "
        f"R\u00b2={r2:.3f}, MAE={mae_val:.3f}. "
        f"Predictions are estimates based on historical patterns."
    )

    return XGBoostPredictionResult(
        model_r2=r2, model_mae=mae_val,
        training_months=len(train_months), hospitals_trained=len(hospital_names),
        predictions=predictions, global_feature_importance=global_importance,
        accuracy_note=accuracy_note,
    )
