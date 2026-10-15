"""Tests for governorate analysis: FDR-controlled cross-correlations and adjusted R^2."""
import numpy as np
import pandas as pd

from app.engine.smart.governorate_analysis import (
    _fdr_filter_correlations,
    _compute_xgboost_governorate_insights,
)


def test_fdr_filter_keeps_only_survivors():
    candidates = [
        {"indicator_a": "a", "indicator_b": "b", "p_value": 0.001},
        {"indicator_a": "c", "indicator_b": "d", "p_value": 0.04},
        {"indicator_a": "e", "indicator_b": "f", "p_value": 0.09},
    ]
    kept = _fdr_filter_correlations(candidates, q=0.05)
    # BH thresholds (m=3): 0.0167, 0.0333, 0.05 -> only p=0.001 passes
    assert [c["p_value"] for c in kept] == [0.001]


def test_fdr_filter_empty():
    assert _fdr_filter_correlations([], q=0.05) == []


def test_xgboost_insights_include_adjusted_r2():
    n = 8
    df = pd.DataFrame({
        "governorate": [f"G{i % 2}" for i in range(n)],
        "cs_rate": [10.0 + 2 * i for i in range(n)],
        "smm_total": [1.0 + 0.5 * i for i in range(n)],
        "nd": [float(i) for i in range(n)],
        "sb": [0.5 * i for i in range(n)],
    })
    res = _compute_xgboost_governorate_insights(df, ["cs_rate", "smm_total", "nd", "sb"])
    assert "cs_rate" in res
    assert "model_r2_adj" in res["cs_rate"]
    assert res["cs_rate"]["model_r2_adj"] <= res["cs_rate"]["model_r2"] + 1e-9
