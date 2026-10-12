"""Tests for quality score calculation (engine.quality)."""
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
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] >= 70
    assert score["rule_compliance"] == 100.0


def test_all_fail():
    results = [
        _rr("R01", "Test", RuleStatus.FAIL, Severity.HIGH),
        _rr("R02", "Test", RuleStatus.FAIL, Severity.MEDIUM),
    ]
    values = {"2": 100.0, "6": 100.0}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] < 80
    assert score["rule_compliance"] == 0.0
    assert len(score["issues"]) == 2


def test_completeness_low():
    results = []
    values = {"2": 100.0}
    required = {str(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], required)
    assert score["completeness"] == 1.0


def test_completeness_high():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["completeness"] == 100.0


def test_completeness_zero_indicators():
    results = []
    values = {"2": 100.0}
    score = calculate_quality_score(results, values, [], set())
    assert score["completeness"] == 0.0


def test_completeness_covered_children_not_penalized():
    # required = total "2" + siblings "2.a", "2.b"; "2.b" missing but covered.
    results = []
    values = {"2": 100.0, "2.a": 100.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.b"})
    assert score["completeness"] == 100.0


def test_completeness_covered_counted_from_required():
    # 3 required, 1 filled, 1 covered -> denominator 2 -> 50%.
    results = []
    values = {"2": 10.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.a"})
    assert score["completeness"] == 50.0


def test_completeness_no_covered_change():
    results = []
    values = {"2": 10.0}
    required = {"2", "2.a", "2.b"}
    before = calculate_quality_score(results, values, [], required)
    after = calculate_quality_score(results, values, [], required, covered_codes=set())
    assert before["completeness"] == after["completeness"]


def test_score_clamps_to_100():
    results = [_rr("R01", "Test", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] <= 100.0


def test_score_never_negative():
    results = [_rr(f"R{i}", "Test", RuleStatus.FAIL, Severity.CRITICAL) for i in range(30)]
    values = {}
    score = calculate_quality_score(results, values, [], set())
    assert score["score"] >= 0.0


def test_outlier_penalty_zero():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["outlier_penalty"] == 0.0


def test_outlier_penalty_with_anomalies():
    from app.engine.anomaly import AnomalyResultData
    anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 3.5, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 2.8, True),
    ]
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, anomalies, set(values))
    assert score["outlier_penalty"] > 0.0


def test_issues_list_from_failures():
    results = [
        _rr("R001", "Total deliveries", RuleStatus.FAIL, Severity.HIGH),
        _rr("R041", "CS rate high", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    values = {"2": 100}
    score = calculate_quality_score(results, values, [], {str(i) for i in range(60)})
    assert any("R001" in i for i in score["issues"])
    assert any("R041" in i for i in score["issues"])
