import pandas as pd
from typing import Dict, Any, List
from statsmodels.formula.api import ols

from app.engine.smart.schemas import ResidualResult
from app.engine.smart.anomaly import FEATURE_KEYS


def _build_dataframe(all_hospital_data: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, entry in all_hospital_data.items():
        row = {"hospital_name": name, "hospital_id": entry.get("hospital_id", 0)}
        row.update(entry.get("values", {}))
        row["governorate"] = entry.get("governorate", "unknown")
        row["hospital_type"] = entry.get("hospital_type", "unknown")
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_residuals(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    threshold_z: float = 2.0,
) -> List[ResidualResult]:
    if len(all_hospital_data) < 5:
        return []

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]
    results = []

    for indicator in numeric_cols:
        valid = df.dropna(subset=[indicator]).copy()
        if len(valid) < 5:
            continue

        try:
            formula = f'{indicator} ~ C(governorate) + C(hospital_type)'
            model = ols(formula, data=valid).fit()
            residuals = model.resid
        except Exception:
            continue

        if residuals.std() < 1e-10:
            continue

        residual_z = (residuals - residuals.mean()) / residuals.std()

        for idx in valid.index:
            name = valid.loc[idx, "hospital_name"]
            hospital_id = all_hospital_data[name].get("hospital_id", 0)
            actual = float(valid.loc[idx, indicator])
            predicted = float(model.fittedvalues[idx])
            resid = float(residuals[idx])
            z = float(residual_z[idx])
            is_anomaly = abs(z) > threshold_z

            if abs(z) > threshold_z:
                severity = "critical"
            elif abs(z) > 1.5:
                severity = "warning"
            else:
                severity = "normal"

            results.append(ResidualResult(
                hospital_name=name, hospital_id=hospital_id, indicator=indicator,
                actual_value=actual, predicted_value=predicted, residual=resid,
                residual_z_score=z, is_anomaly=is_anomaly, severity=severity,
            ))

    return results
