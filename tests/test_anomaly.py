"""Tests for anomaly detection and statistical trend analysis (engine.anomaly)."""
import pytest
import numpy as np
from app.engine.anomaly import (
    compute_rate,
    detect_anomalies,
    detect_monthly_trend,
    AnomalyResultData,
    analyze_historical_trends,
    compare_hospitals,
    detect_trend_anomalies,
    generate_historical_summary,
    RATE_DEFINITIONS,
    TrendResult,
    HospitalComparison,
    set_trends_config,
)


# ── compute_rate ──────────────────────────────────────────────

def test_compute_rate_normal():
    values = {"5": 80, "2": 300}
    rate = compute_rate(values, "5", "2")
    assert rate == pytest.approx(26.67, rel=0.01)


def test_compute_rate_zero_denominator():
    values = {"5": 80, "2": 0}
    rate = compute_rate(values, "5", "2")
    assert rate is None


def test_compute_rate_missing_data():
    values = {"5": 80}
    rate = compute_rate(values, "5", "2")
    assert rate is None


def test_compute_rate_both_missing():
    rate = compute_rate({}, "5", "2")
    assert rate is None


def test_compute_rate_zero_numerator():
    rate = compute_rate({"5": 0, "2": 100}, "5", "2")
    assert rate == 0.0


# ── detect_anomalies ──────────────────────────────────────────

def test_detect_anomalies_outlier():
    normal_data = {f"Hosp{i}": {"5": 30 + i, "2": 100 + i * 2} for i in range(10)}
    normal_data["OutlierHosp"] = {"5": 90, "2": 100}
    results = detect_anomalies(normal_data, "OutlierHosp", "2026-04")
    cs_result = [r for r in results if r.rate_name == "C-section rate"]
    if cs_result:
        assert cs_result[0].is_outlier or cs_result[0].z_score > 2


def test_detect_anomalies_no_data():
    results = detect_anomalies({}, "TestHosp", "2026-04")
    assert results == []


def test_detect_anomalies_single_hospital():
    data = {"Hosp1": {"5": 50, "2": 200}}
    results = detect_anomalies(data, "Hosp1", "2026-04")
    assert len(results) == 0


def test_detect_anomalies_all_same():
    data = {f"H{i}": {"5": 50, "2": 200} for i in range(5)}
    results = detect_anomalies(data, "H0", "2026-04")
    for r in results:
        assert r.z_score == 0.0
        assert not r.is_outlier


def test_detect_anomalies_returns_anomaly_result_data():
    data = {f"H{i}": {"5": 30 + i * 5, "2": 100} for i in range(5)}
    results = detect_anomalies(data, "H0", "2026-04")
    for r in results:
        assert isinstance(r, AnomalyResultData)
        assert r.rate_name
        assert r.indicator_code


def test_detect_anomalies_custom_config():
    data = {f"H{i}": {"5": 30 + i, "2": 100} for i in range(5)}
    data["Out"] = {"5": 50, "2": 100}
    results = detect_anomalies(data, "Out", "2026-04", config={"zscore_threshold": 1.0})
    cs = [r for r in results if r.rate_name == "C-section rate"]
    if cs:
        assert cs[0].is_outlier


# ── detect_monthly_trend ──────────────────────────────────────

def test_detect_monthly_trend_outlier():
    history = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 27, "2": 200},
        "2026-03": {"5": 26, "2": 200},
    }
    current = {"5": 60, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    cs = [r for r in results if "C-section" in r.rate_name]
    if cs:
        assert cs[0].is_outlier or cs[0].z_score > 2


def test_detect_monthly_trend_stable():
    history = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 25, "2": 200},
        "2026-03": {"5": 25, "2": 200},
    }
    current = {"5": 25, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    for r in results:
        assert not r.is_outlier


def test_detect_monthly_trend_insufficient_history():
    history = {"2026-03": {"5": 25, "2": 200}}
    current = {"5": 60, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    assert len(results) == 0


# ── analyze_historical_trends ─────────────────────────────────

def test_analyze_historical_trends_basic():
    monthly = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 28, "2": 200},
        "2026-03": {"5": 30, "2": 200},
        "2026-04": {"5": 35, "2": 200},
    }
    results = analyze_historical_trends("TestHosp", monthly)
    assert len(results) > 0
    for t in results:
        assert isinstance(t, TrendResult)
        assert t.rate_name
        assert t.trend_direction in ("increasing", "decreasing", "stable")
        assert t.trend_severity in ("negligible", "low", "moderate", "high", "critical")


def test_analyze_historical_trends_increasing():
    monthly = {f"2026-{i:02d}": {"5": 20 + i * 10, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "increasing"


def test_analyze_historical_trends_decreasing():
    monthly = {f"2026-{i:02d}": {"5": 50 - i * 5, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "decreasing"


def test_analyze_historical_trends_stable():
    monthly = {f"2026-{i:02d}": {"5": 30, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "stable"


def test_analyze_historical_trends_insufficient_data():
    monthly = {"2026-01": {"5": 25, "2": 200}}
    results = analyze_historical_trends("TestHosp", monthly)
    assert len(results) == 0


def test_analyze_historical_trends_findings():
    monthly = {f"2026-{i:02d}": {"5": 20 + i * 15, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs and cs[0].is_significant:
        assert len(cs[0].findings) > 0


def test_analyze_historical_trends_consecutive():
    monthly = {
        "2026-01": {"5": 30, "2": 200},
        "2026-02": {"5": 32, "2": 200},
        "2026-03": {"5": 34, "2": 200},
        "2026-04": {"5": 36, "2": 200},
    }
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].consecutive_count >= 1


# ── compare_hospitals ─────────────────────────────────────────

def test_compare_hospitals_basic():
    all_data = {
        "Hosp1": {"2026-04": {"5": 30, "2": 200}},
        "Hosp2": {"2026-04": {"5": 25, "2": 200}},
        "Hosp3": {"2026-04": {"5": 35, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) >= 3
    for c in comparisons:
        assert isinstance(c, HospitalComparison)
        assert c.comparison_label


def test_compare_hospitals_single():
    all_data = {"Hosp1": {"2026-04": {"5": 30, "2": 200}}}
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) == 0


def test_compare_hospitals_no_month():
    all_data = {
        "Hosp1": {"2026-03": {"5": 30, "2": 200}},
        "Hosp2": {"2026-03": {"5": 25, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) == 0


def test_compare_hospitals_labels():
    all_data = {
        "Hosp1": {"2026-04": {"5": 50, "2": 200}},
        "Hosp2": {"2026-04": {"5": 25, "2": 200}},
        "Hosp3": {"2026-04": {"5": 25, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    labels = [c.comparison_label for c in comparisons]
    assert any("above" in l or "below" in l or "normal" in l for l in labels)


# ── detect_trend_anomalies ────────────────────────────────────

def test_detect_trend_anomalies_outlier():
    monthly = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 26, "2": 200},
        "2026-03": {"5": 27, "2": 200},
        "2026-04": {"5": 80, "2": 200},
    }
    results = detect_trend_anomalies("TestHosp", monthly)
    cs = [r for r in results if "C-section" in r.rate_name]
    if cs:
        assert cs[0].is_outlier


def test_detect_trend_anomalies_insufficient():
    monthly = {"2026-01": {"5": 25, "2": 200}, "2026-02": {"5": 26, "2": 200}}
    results = detect_trend_anomalies("TestHosp", monthly)
    assert len(results) == 0


# ── generate_historical_summary ───────────────────────────────

def test_generate_historical_summary():
    trends = [TrendResult(
        hospital="H", indicator_code="5", rate_name="C-section rate",
        months=["2026-01", "2026-02"], values=[25, 30],
        mean=27.5, std=2.5, slope=2.5, slope_pct=9.1,
        trend_direction="increasing", trend_severity="moderate",
        is_significant=True, cv=9.1, last_vs_mean_pct_change=9.1,
        consecutive_direction="increasing", consecutive_count=2,
        findings=["test finding"],
    )]
    comparisons = [HospitalComparison(
        hospital="H", indicator_code="5", rate_name="C-section rate",
        value=30, benchmark=25, deviation_pct=20,
        percentile_rank=80, comparison_label="above average",
    )]
    summary = generate_historical_summary(trends, comparisons, [], [])
    assert "total_rates_analyzed" in summary
    assert summary["total_rates_analyzed"] >= 1
    assert summary["increasing_trends"] >= 1


def test_generate_historical_summary_empty():
    summary = generate_historical_summary([], [], [], [])
    assert summary["total_rates_analyzed"] == 0


# ── RATE_DEFINITIONS ──────────────────────────────────────────

def test_rate_definitions_count():
    assert len(RATE_DEFINITIONS) == 7


def test_rate_definitions_structure():
    for entry in RATE_DEFINITIONS:
        assert len(entry) == 4
        name, num, den, typical = entry
        assert isinstance(name, str)
        assert isinstance(num, str)
        assert isinstance(den, str)