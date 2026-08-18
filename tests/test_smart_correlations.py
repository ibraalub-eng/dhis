import pytest
import numpy as np
from app.engine.smart.correlations import analyze_correlations


@pytest.fixture
def sample_data():
    np.random.seed(42)
    n = 10
    data = {}
    for i in range(n):
        cs_rate = np.random.uniform(20, 40)
        smm = cs_rate * 0.15 + np.random.normal(0, 1)
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": "Gaza",
            "hospital_type": "general",
            "values": {
                "cs_rate": cs_rate,
                "smm_total": max(0, smm),
                "mat_deaths": max(0, smm * 0.1),
                "nd": np.random.uniform(0, 5),
                "sb": np.random.uniform(0, 2),
                "preterm": np.random.uniform(5, 15),
                "lbw": np.random.uniform(4, 12),
                "total_births": np.random.uniform(100, 300),
                "high_risk": np.random.uniform(5, 25),
                "adolescent": np.random.uniform(1, 8),
            },
        }
    return data


@pytest.fixture
def default_config():
    return {}


def test_returns_correlation_result(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert result is not None
    assert len(result.indicators) > 0


def test_matrix_is_symmetric(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    for ind_a in result.matrix:
        for ind_b in result.matrix[ind_a]:
            if ind_b in result.matrix and ind_a in result.matrix[ind_b]:
                v1 = result.matrix[ind_a][ind_b]
                v2 = result.matrix[ind_b][ind_a]
                assert abs(v1 - v2) < 0.001


def test_strong_correlation_detected(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    strong = [c for c in result.strong_correlations if abs(c.pearson_r) > 0.5]
    assert len(strong) > 0


def test_feature_importance_present(sample_data, default_config):
    result = analyze_correlations(sample_data, default_config)
    assert len(result.feature_importance) > 0
    for fi in result.feature_importance:
        assert len(fi.features) > 0


def test_bh_correction_flags_only_significant():
    """تصحيح FDR يبقي فقط الاختبارات الأصغر من عتبة Benjamini-Hochberg."""
    from app.engine.smart.correlations import _bh_significant
    pvals = np.array([0.5, 0.3, 0.01])
    mask = _bh_significant(pvals, q=0.05)
    assert mask.tolist() == [False, False, True]


def test_bh_correction_none_significant():
    from app.engine.smart.correlations import _bh_significant
    mask = _bh_significant(np.array([0.9, 0.8, 0.7]), q=0.05)
    assert not mask.any()


def test_bh_correction_empty():
    from app.engine.smart.correlations import _bh_significant
    mask = _bh_significant(np.array([]))
    assert len(mask) == 0


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = analyze_correlations(data, {})
    assert result is not None
    assert len(result.strong_correlations) == 0


def test_correlations_serialized_as_plain_dicts(sample_data, default_config):
    """التسلسل للواجهة يحوّل strong_correlations/feature_importance لقواميس بمفاتيح رقمية صالحة."""
    from app.api.smart_analytics import _correlations_to_dict
    result = analyze_correlations(sample_data, default_config)
    serialized = _correlations_to_dict(result)
    assert isinstance(serialized, dict)
    assert "matrix" in serialized and "indicators" in serialized
    assert isinstance(serialized["strong_correlations"], list)
    for pair in serialized["strong_correlations"]:
        assert isinstance(pair, dict)
        assert "pearson_r" in pair and "spearman_r" in pair
        assert isinstance(pair["pearson_r"], float)
        assert abs(pair["pearson_r"]) <= 1.0
    assert isinstance(serialized["feature_importance"], list)
    for fi in serialized["feature_importance"]:
        assert isinstance(fi, dict)
        assert all(isinstance(e, dict) for e in fi["features"])


def test_correlations_serialization_sanitizes_nan():
    """القيم غير المنتهية داخل pearson_r تُنظف إلى 0.0 بدل التسريب كـ NaN."""
    import math
    from app.api.smart_analytics import _correlations_to_dict
    from app.engine.smart.schemas import (
        SmartCorrelationResult, CorrelationPair, FeatureImportance, ImportanceEntry,
    )
    result = SmartCorrelationResult(
        matrix={"cs_rate": {"cs_rate": 1.0}},
        indicators=["cs_rate"],
        strong_correlations=[CorrelationPair(
            indicator_a="cs_rate", indicator_b="smm_total",
            pearson_r=float("nan"), spearman_r=0.8, p_value=0.001, strength="strong_positive",
        )],
        feature_importance=[FeatureImportance(
            target_indicator="cs_rate",
            features=[ImportanceEntry(feature_name="x", importance=0.3, rank=1)],
        )],
    )
    serialized = _correlations_to_dict(result)
    pair = serialized["strong_correlations"][0]
    assert pair["pearson_r"] == 0.0
    assert not math.isnan(pair["pearson_r"])