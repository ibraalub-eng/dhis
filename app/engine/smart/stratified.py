import pandas as pd
from typing import Dict, Any, List

from app.engine.smart.schemas import StratifiedComparison
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


def _get_peer_group(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    gov = df.loc[idx, "governorate"]
    typ = df.loc[idx, "hospital_type"]

    mask = (df["governorate"] == gov) & (df["hospital_type"] == typ)
    if mask.sum() >= 3:
        return df[mask]

    mask = df["governorate"] == gov
    if mask.sum() >= 3:
        return df[mask]

    mask = df["hospital_type"] == typ
    if mask.sum() >= 3:
        return df[mask]

    return df


def run_stratified_analysis(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
) -> List[StratifiedComparison]:
    if len(all_hospital_data) < 3:
        return []

    df = _build_dataframe(all_hospital_data)
    numeric_cols = [c for c in FEATURE_KEYS if c in df.columns]
    results = []

    for indicator in numeric_cols:
        if indicator not in df.columns:
            continue

        for idx in df.index:
            peer = _get_peer_group(df, idx)
            peer_values = peer[indicator].dropna()
            if len(peer_values) < 2:
                continue

            hospital_value = df.loc[idx, indicator]
            if pd.isna(hospital_value):
                continue

            mean = peer_values.mean()
            std = peer_values.std()
            if std < 1e-10:
                continue

            deviation_pct = ((hospital_value - mean) / mean * 100) if mean != 0 else 0.0
            rank = int(peer_values.rank(ascending=False)[idx])

            z = (hospital_value - mean) / std
            if z > 1.5:
                label = "significantly_above"
            elif z > 0.5:
                label = "above_average"
            elif z < -1.5:
                label = "significantly_below"
            elif z < -0.5:
                label = "below_average"
            else:
                label = "average"

            results.append(StratifiedComparison(
                hospital_name=df.loc[idx, "hospital_name"],
                hospital_id=int(df.loc[idx, "hospital_id"]),
                indicator=indicator,
                hospital_value=float(hospital_value),
                peer_group_mean=float(mean),
                peer_group_std=float(std),
                deviation_pct=float(deviation_pct),
                rank_in_peer_group=rank,
                peer_group_size=len(peer_values),
                label=label,
                governorate=df.loc[idx, "governorate"],
                hospital_type=df.loc[idx, "hospital_type"],
            ))

    return results
