import numpy as np
import pandas as pd
from typing import Dict, Any
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import OneHotEncoder

from app.engine.smart.schemas import (
    SmartCorrelationResult, CorrelationPair, FeatureImportance, ImportanceEntry,
)
from app.engine.smart.anomaly import FEATURE_KEYS


def _build_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, entry in all_hospital_data.items():
        row = {"hospital_name": name}
        row.update(entry.get("values", {}))
        row["governorate"] = entry.get("governorate", "unknown")
        row["hospital_type"] = entry.get("hospital_type", "unknown")
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_correlations(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> SmartCorrelationResult:
    if len(all_hospital_data) < 3:
        available = [k for k in FEATURE_KEYS if any(
            k in v.get("values", {}) for v in all_hospital_data.values()
        )]
        return SmartCorrelationResult(
            matrix={}, indicators=available, strong_correlations=[], feature_importance=[],
        )

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]

    matrix = {}
    strong_correlations = []

    for i, ind_a in enumerate(numeric_cols):
        matrix[ind_a] = {}
        for j, ind_b in enumerate(numeric_cols):
            valid = df[[ind_a, ind_b]].dropna()
            if len(valid) < 3:
                matrix[ind_a][ind_b] = 0.0
                continue
            a_vals = np.asarray(valid[ind_a], dtype=float).ravel()
            b_vals = np.asarray(valid[ind_b], dtype=float).ravel()
            if np.std(a_vals) < 1e-10 or np.std(b_vals) < 1e-10:
                r = 0.0
                p = 1.0
            else:
                r_val, p_val = pearsonr(a_vals, b_vals)
                r = float(r_val)
                p = float(p_val)
            matrix[ind_a][ind_b] = r

            if j > i and abs(r) > 0.7 and p < 0.05:
                s_r_val, _ = spearmanr(a_vals, b_vals)
                s_r = float(s_r_val)
                if abs(r) > 0.9:
                    strength = "strong_positive" if r > 0 else "strong_negative"
                elif abs(r) > 0.7:
                    strength = "moderate_positive" if r > 0 else "moderate_negative"
                else:
                    strength = "weak"
                strong_correlations.append(CorrelationPair(
                    indicator_a=ind_a, indicator_b=ind_b,
                    pearson_r=r, spearman_r=s_r,
                    p_value=p, strength=strength,
                ))

    feature_importance = []
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    cat_data = df[["governorate", "hospital_type"]].fillna("unknown")
    cat_encoded = encoder.fit_transform(cat_data)

    for target in numeric_cols:
        available = df.dropna(subset=[target])
        if len(available) < 5:
            continue

        y = available[target].values
        X_numeric = available[numeric_cols].drop(columns=[target]).fillna(0).values
        X_cat = cat_encoded[available.index]
        X = np.hstack([X_numeric, X_cat])

        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        cv_scores = cross_val_score(rf, X, y, cv=min(3, len(available)), scoring="r2")

        if cv_scores.mean() < 0.3:
            continue

        rf.fit(X, y)
        importances = rf.feature_importances_

        feature_names = [c for c in numeric_cols if c != target]
        feature_names += list(encoder.get_feature_names_out(["governorate", "hospital_type"]))

        ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
        features = [
            ImportanceEntry(feature_name=name, importance=float(imp), rank=rank + 1)
            for rank, (name, imp) in enumerate(ranked[:5])
        ]
        feature_importance.append(FeatureImportance(target_indicator=target, features=features))

    return SmartCorrelationResult(
        matrix=matrix, indicators=numeric_cols,
        strong_correlations=strong_correlations, feature_importance=feature_importance,
    )