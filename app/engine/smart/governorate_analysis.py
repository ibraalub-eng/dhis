import numpy as np
import pandas as pd
from typing import Dict, Any, List
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
import xgboost as xgb
import shap

from app.engine.smart.anomaly import FEATURE_KEYS
from app.engine.smart.xgboost_predictor import _compute_derived_features, ARABIC_NAMES

FEATURE_KEYS_SET = set(FEATURE_KEYS)


def _build_governorate_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, entry in all_hospital_data.items():
        values = entry.get("values", {})
        derived = _compute_derived_features(values)
        all_vals = {**values, **derived}
        row = {
            "hospital_name": name,
            "governorate": entry.get("governorate", "unknown"),
            "hospital_type": entry.get("hospital_type", "unknown"),
        }
        row.update(all_vals)
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_governorate_correlations(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    if len(all_hospital_data) < 3:
        return {"governorate_profiles": [], "cross_governorate_correlations": [], "indicator_governorate_heatmap": {}}

    df = _build_governorate_dataframe(all_hospital_data)
    all_feature_cols = [c for c in df.columns if c in set(list(ARABIC_NAMES.keys()))]

    gov_profiles = []
    for gov in df["governorate"].unique():
        gov_df = df[df["governorate"] == gov]
        profile = {
            "governorate": gov,
            "hospital_count": len(gov_df),
            "indicators": {},
        }
        for col in all_feature_cols:
            vals = gov_df[col].dropna()
            if len(vals) > 0:
                profile["indicators"][col] = {
                    "mean": round(float(vals.mean()), 4),
                    "std": round(float(vals.std()), 4) if len(vals) > 1 else 0.0,
                    "min": round(float(vals.min()), 4),
                    "max": round(float(vals.max()), 4),
                }
        gov_profiles.append(profile)

    gov_means = {}
    for profile in gov_profiles:
        gov_means[profile["governorate"]] = {
            k: v["mean"] for k, v in profile["indicators"].items()
        }

    cross_correlations = []
    gov_list = list(gov_means.keys())
    indicators = list(FEATURE_KEYS)

    for ind_a in indicators:
        for ind_b in indicators:
            if ind_a >= ind_b:
                continue
            vals_a = []
            vals_b = []
            for gov in gov_list:
                if ind_a in gov_means[gov] and ind_b in gov_means[gov]:
                    vals_a.append(gov_means[gov][ind_a])
                    vals_b.append(gov_means[gov][ind_b])
            if len(vals_a) >= 3:
                vals_a = np.array(vals_a)
                vals_b = np.array(vals_b)
                if np.std(vals_a) > 1e-10 and np.std(vals_b) > 1e-10:
                    from scipy.stats import pearsonr
                    r, p = pearsonr(vals_a, vals_b)
                    if abs(r) > 0.6 and p < 0.1:
                        cross_correlations.append({
                            "indicator_a": ind_a,
                            "indicator_b": ind_b,
                            "correlation": round(float(r), 4),
                            "p_value": round(float(p), 4),
                            "governorate_count": len(vals_a),
                            "strength": "strong" if abs(r) > 0.8 else "moderate",
                            "direction": "positive" if r > 0 else "negative",
                        })

    cross_correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    heatmap = {}
    for ind in indicators:
        heatmap[ind] = {}
        for gov in gov_list:
            if ind in gov_means[gov]:
                heatmap[ind][gov] = gov_means[gov][ind]
            else:
                heatmap[ind][gov] = 0.0

    xgb_insights = _compute_xgboost_governorate_insights(df, all_feature_cols)

    return {
        "governorate_profiles": gov_profiles,
        "cross_governorate_correlations": cross_correlations[:20],
        "indicator_governorate_heatmap": heatmap,
        "xgboost_insights": xgb_insights,
    }


def _compute_xgboost_governorate_insights(df: pd.DataFrame, feature_cols: List[str]) -> Dict[str, Any]:
    if len(df) < 5:
        return {"feature_importance_by_governorate": {}, "governorate_predictions": {}}

    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    gov_data = df[["governorate"]].fillna("unknown")
    gov_encoded = encoder.fit_transform(gov_data)
    gov_feature_names = list(encoder.get_feature_names_out(["governorate"]))

    results = {}
    target_indicators = [k for k in ["cs_rate", "smm_total", "mat_deaths", "total_births"] if k in df.columns]

    for target in target_indicators:
        available = df.dropna(subset=[target])
        if len(available) < 5:
            continue

        y = available[target].values
        numeric_features = [c for c in feature_cols if c != target and c in available.columns]
        X_numeric = available[numeric_features].fillna(0).values
        X_cat = gov_encoded[available.index]
        X = np.hstack([X_numeric, X_cat])
        all_names = numeric_features + gov_feature_names

        model = xgb.XGBRegressor(n_estimators=80, max_depth=4, learning_rate=0.1, random_state=42, verbosity=0)
        model.fit(X, y)

        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X)
        mean_abs_shap = np.mean(np.abs(shap_vals), axis=0)

        gov_shap = {}
        for i, name in enumerate(gov_feature_names):
            if i < len(mean_abs_shap):
                gov_shap[name.replace("governorate_", "")] = round(float(mean_abs_shap[i]), 6)

        gov_shap_sorted = sorted(gov_shap.items(), key=lambda x: x[1], reverse=True)

        gov_means = {}
        for gov in df["governorate"].unique():
            gov_vals = df[df["governorate"] == gov][target].dropna()
            if len(gov_vals) > 0:
                gov_means[gov] = round(float(gov_vals.mean()), 4)

        results[target] = {
            "governorate_impact": [{"governorate": g, "impact": v} for g, v in gov_shap_sorted],
            "governorate_means": gov_means,
            "model_r2": round(float(model.score(X, y)), 4),
        }

    return results
