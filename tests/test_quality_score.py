"""Tests for quality score calculation (engine.quality)."""
import pytest
from app.engine.quality import (
    calculate_quality_score,
    RuleResult,
    RuleStatus,
    Severity,
    RuleType,
)


def _rr(code, desc, status, sev, rtype=RuleType.LOGIC):
    return RuleResult(code, desc, status, sev, rtype, "detail")


def test_perfect_score():
    results = [_rr("R01", "Test rule", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], 60)
    assert score["score"] >= 70
    assert score["rule_compliance"] == 100.0


def test_all_fail():
    results = [
        _rr("R01", "Test", RuleStatus.FAIL, Severity.HIGH),
        _rr("R02", "Test", RuleStatus.FAIL, Severity.MEDIUM),
    ]
    values = {"2": 100.0, "6": 100.0}
    score = calculate_quality_score(results, values, [], 60)
    assert score["score"] < 80
    assert score["rule_compliance"] == 0.0
    assert len(score["issues"]) == 2


def test_completeness_low():
    results = []
    values = {"2": 100.0}
    score = calculate_quality_score(results, values, [], 100)
    assert score["completeness"] == 1.0


def test_completeness_high():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], 60)
    assert score["completeness"] == 100.0


def test_completeness_zero_indicators():
    results = []
    values = {"2": 100.0}
    score = calculate_quality_score(results, values, [], 0)
    assert score["completeness"] == 0.0


def test_score_clamps_to_100():
    results = [_rr("R01", "Test", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], 100)
    assert score["score"] <= 100.0


def test_score_never_negative():
    results = [_rr(f"R{i}", f"Test", RuleStatus.FAIL, Severity.CRITICAL) for i in range(30)]
    values = {}
    score = calculate_quality_score(results, values, [], 100)
    assert score["score"] >= 0.0


def test_outlier_penalty_zero():
    from app.engine.anomaly import AnomalyResultData
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], 60)
    assert score["outlier_penalty"] == 0.0


def test_outlier_penalty_with_anomalies():
    from app.engine.anomaly import AnomalyResultData
    anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 3.5, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 2.8, True),
    ]
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, anomalies, 60)
    assert score["outlier_penalty"] > 0.0


def test_issues_list_from_failures():
    results = [
        _rr("R001", "Total deliveries", RuleStatus.FAIL, Severity.HIGH),
        _rr("R041", "CS rate high", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    values = {"2": 100}
    score = calculate_quality_score(results, values, [], 60)
    assert any("R001" in i for i in score["issues"])
    assert any("R041" in i for i in score["issues"])