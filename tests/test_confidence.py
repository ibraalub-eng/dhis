"""Tests for confidence scoring (engine.confidence)."""
from app.engine.confidence import (
    calculate_confidence,
    build_indicator_rule_map,
    _signal_rule_compliance,
    _signal_historical,
    _signal_cross_hospital,
    _signal_trend,
    _signal_completeness,
    _compute_level,
    _build_recommendations,
    _build_summary,
    _extract_codes_from_params,
    ConfidenceSignal,
    IndicatorConfidence,
    HospitalConfidenceResult,
)
from app.engine.quality import RuleResult, RuleStatus, Severity, RuleType
from app.models import Rule


class TestExtractCodesFromParams:
    def test_ge_expression(self):
        codes = _extract_codes_from_params("ge", {"parent": "2", "children": ["3", "4", "5"]})
        assert "2" in codes
        assert "3" in codes

    def test_le_expression(self):
        codes = _extract_codes_from_params("le", {"child": "5", "parent": "2"})
        assert "5" in codes
        assert "2" in codes

    def test_benchmark_rate(self):
        codes = _extract_codes_from_params("benchmark_rate", {"num_code": "5", "den_code": "2"})
        assert "5" in codes
        assert "2" in codes

    def test_month_over(self):
        codes = _extract_codes_from_params("month_over", {"code": "2"})
        assert "2" in codes

    def test_neg_check(self):
        codes = _extract_codes_from_params("neg_check", {"codes": ["2", "3", "4"]})
        assert "2" in codes
        assert "3" in codes

    def test_missing(self):
        codes = _extract_codes_from_params("missing", {"code": "11"})
        assert "11" in codes

    def test_all_zero(self):
        codes = _extract_codes_from_params("all_zero", {"codes": ["2", "3"]})
        assert "2" in codes

    def test_empty_params(self):
        codes = _extract_codes_from_params("ge", {})
        assert codes == []


class TestSignalRuleCompliance:
    def test_no_rules_returns_pass(self):
        signal = _signal_rule_compliance("2", [], {})
        assert signal.passed is True
        assert signal.score == 1.0

    def test_all_pass(self):
        results = [
            RuleResult("R001", "test", RuleStatus.PASS, Severity.LOW, RuleType.LOGIC, ""),
            RuleResult("R002", "test", RuleStatus.PASS, Severity.LOW, RuleType.LOGIC, ""),
        ]
        signal = _signal_rule_compliance("2", results, {"2": ["R001", "R002"]})
        assert signal.passed is True
        assert signal.score == 1.0

    def test_some_fail(self):
        results = [
            RuleResult("R001", "test", RuleStatus.PASS, Severity.LOW, RuleType.LOGIC, ""),
            RuleResult("R002", "test", RuleStatus.FAIL, Severity.HIGH, RuleType.LOGIC, "failed"),
        ]
        signal = _signal_rule_compliance("2", results, {"2": ["R001", "R002"]})
        assert signal.passed is False
        assert signal.score == 0.5


class TestSignalHistorical:
    def test_missing_value(self):
        signal = _signal_historical("2", None, {})
        assert signal.passed is False
        assert signal.score == 0.0

    def test_insufficient_history(self):
        signal = _signal_historical("2", 100, {"2026-01": {"2": 90}})
        assert signal.score == 0.7

    def test_stable_history(self):
        hist = {
            "2026-01": {"2": 100},
            "2026-02": {"2": 100},
            "2026-03": {"2": 100},
        }
        signal = _signal_historical("2", 100, hist)
        assert signal.passed is True
        assert signal.score == 1.0

    def test_outlier_value(self):
        hist = {
            "2026-01": {"2": 100},
            "2026-02": {"2": 100},
            "2026-03": {"2": 100},
        }
        signal = _signal_historical("2", 500, hist)
        assert signal.passed is True
        assert signal.score <= 0.5


class TestSignalCrossHospital:
    def test_missing_value(self):
        signal = _signal_cross_hospital("2", None, {}, "Hosp1")
        assert signal.passed is False

    def test_few_hospitals(self):
        data = {"Hosp1": {"2": 100}}
        signal = _signal_cross_hospital("2", 100, data, "Hosp1")
        assert signal.score == 0.7

    def test_normal_value(self):
        data = {
            "Hosp1": {"2": 100},
            "Hosp2": {"2": 110},
            "Hosp3": {"2": 95},
        }
        signal = _signal_cross_hospital("2", 100, data, "Hosp1")
        assert signal.passed is True

    def test_outlier_value(self):
        data = {
            "Hosp1": {"5": 150, "2": 200},
            "Hosp2": {"5": 50, "2": 200},
            "Hosp3": {"5": 55, "2": 200},
            "Hosp4": {"5": 45, "2": 200},
            "Hosp5": {"5": 48, "2": 200},
            "Hosp6": {"5": 52, "2": 200},
            "Hosp7": {"5": 47, "2": 200},
            "Hosp8": {"5": 53, "2": 200},
        }
        signal = _signal_cross_hospital("5", 150, data, "Hosp1")
        assert signal.passed is True
        assert signal.score <= 0.5


class TestSignalTrend:
    def test_missing_value(self):
        signal = _signal_trend("2", None, {})
        assert signal.passed is False

    def test_insufficient_history(self):
        hist = {"2026-01": {"2": 100}, "2026-02": {"2": 105}}
        signal = _signal_trend("2", 110, hist)
        assert signal.score == 0.7

    def test_follows_trend(self):
        hist = {
            "2026-01": {"2": 100},
            "2026-02": {"2": 110},
            "2026-03": {"2": 120},
        }
        signal = _signal_trend("2", 130, hist)
        assert signal.score >= 0.5

    def test_breaks_trend(self):
        hist = {
            "2026-01": {"2": 100},
            "2026-02": {"2": 100},
            "2026-03": {"2": 100},
        }
        signal = _signal_trend("2", 500, hist)
        assert signal.score < 0.8


class TestSignalCompleteness:
    def test_missing_value(self):
        signal = _signal_completeness("2", None, {}, {})
        assert signal.passed is False

    def test_no_children(self):
        signal = _signal_completeness("9", 5, {"9": 5}, {})
        assert signal.passed is True
        assert signal.score == 1.0

    def test_all_children_present(self):
        children = {"2": ["3", "4", "5"]}
        values = {"2": 300, "3": 200, "4": 20, "5": 80}
        signal = _signal_completeness("2", 300, values, children)
        assert signal.passed is True
        assert signal.score == 1.0

    def test_missing_children(self):
        children = {"2": ["3", "4", "5"]}
        values = {"2": 300, "3": 200}
        signal = _signal_completeness("2", 300, values, children)
        assert signal.passed is False
        assert signal.score < 1.0


class TestComputeLevel:
    def test_high(self):
        assert _compute_level(85) == "HIGH"

    def test_medium(self):
        assert _compute_level(65) == "MEDIUM"

    def test_low(self):
        assert _compute_level(35) == "LOW"

    def test_critical(self):
        assert _compute_level(10) == "CRITICAL"

    def test_boundary_high(self):
        assert _compute_level(80) == "HIGH"

    def test_boundary_medium(self):
        assert _compute_level(50) == "MEDIUM"

    def test_custom_config(self):
        assert _compute_level(90, {"confidence_high": 95}) == "MEDIUM"


class TestBuildRecommendations:
    def test_missing_value_low_level(self):
        recs = _build_recommendations("2", "Total Deliveries", None, [], "LOW")
        assert any("DATA MISSING" in r for r in recs)

    def test_critical_level(self):
        recs = _build_recommendations("2", "Total Deliveries", 300, [], "CRITICAL")
        assert any("IMMEDIATE VERIFICATION" in r for r in recs)

    def test_low_level_with_value(self):
        recs = _build_recommendations("2", "Total Deliveries", 300, [], "LOW")
        assert any("Verify" in r for r in recs)

    def test_failed_signal_recommendation(self):
        signals = [ConfidenceSignal("historical", False, 0.1, "deviates")]
        recs = _build_recommendations("2", "Total Deliveries", 300, signals, "CRITICAL")
        assert any("source register" in r for r in recs)


class TestBuildSummary:
    def test_basic_summary(self):
        summary = _build_summary("Test Hospital", 75.0, "MEDIUM", {"HIGH": 5, "LOW": 2, "CRITICAL": 1}, [])
        assert "Test Hospital" in summary
        assert "75.0" in summary

    def test_includes_critical_count(self):
        summary = _build_summary("H", 50.0, "LOW", {"CRITICAL": 3, "LOW": 2}, [])
        assert "3 indicator(s) at CRITICAL" in summary

    def test_includes_priority(self):
        priority = [
            IndicatorConfidence("2", "Total Deliveries", 300, 20.0, "LOW", [], ["Verify"]),
        ]
        summary = _build_summary("H", 50.0, "LOW", {"LOW": 1}, priority)
        assert "Priority verification" in summary


class TestIndicatorConfidence:
    def test_to_dict(self):
        ic = IndicatorConfidence("2", "Total", 300, 75.0, "HIGH", [], [])
        d = ic.to_dict()
        assert d["indicator_code"] == "2"
        assert d["confidence"] == 75.0
        assert d["level"] == "HIGH"


class TestHospitalConfidenceResult:
    def test_to_dict(self):
        result = HospitalConfidenceResult(
            hospital="Test", month="2026-04", overall_confidence=75.0,
            level="HIGH", indicator_count=10,
            by_level={"HIGH": 8, "MEDIUM": 2, "LOW": 0, "CRITICAL": 0},
            by_group={"Deliveries": 80.0},
            indicators=[], priority_verify=[],
            summary="Test summary",
        )
        d = result.to_dict()
        assert d["hospital"] == "Test"
        assert d["overall_confidence"] == 75.0
        assert d["by_level"]["HIGH"] == 8


class TestBuildIndicatorRuleMap:
    def test_returns_dict(self, db_session):
        mapping = build_indicator_rule_map(db_session)
        assert isinstance(mapping, dict)

    def test_maps_codes_to_rules(self, db_session):
        mapping = build_indicator_rule_map(db_session)
        rules = db_session.query(Rule).filter(Rule.enabled).all()
        assert len(rules) > 0
        all_mapped_codes = set()
        for codes in mapping.values():
            all_mapped_codes.update(codes)
        assert len(all_mapped_codes) > 0


class TestCalculateConfidence:
    def test_basic_calculation(self):
        values = {"2": 300, "3": 200, "5": 80}
        rule_results = []
        result = calculate_confidence(
            hospital_name="Test Hospital",
            month="2026-04",
            values=values,
            rule_results=rule_results,
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total Deliveries", "3": "NVD", "5": "C-sections"},
            indicator_children={},
            indicator_rule_map={},
        )
        assert result.overall_confidence >= 0
        assert result.overall_confidence <= 100
        assert result.level in ("HIGH", "MEDIUM", "LOW", "CRITICAL")
        assert result.indicator_count == 3

    def test_with_historical_data(self):
        values = {"2": 300}
        historical = {
            "2026-01": {"2": 290},
            "2026-02": {"2": 295},
            "2026-03": {"2": 298},
        }
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data=historical,
            all_hospital_data={},
            indicator_map={"2": "Total Deliveries"},
            indicator_children={},
            indicator_rule_map={},
        )
        assert result.indicator_count >= 1

    def test_with_cross_hospital_data(self):
        values = {"2": 300}
        all_data = {
            "Hosp1": {"2": 280},
            "Hosp2": {"2": 310},
            "Hosp3": {"2": 295},
        }
        result = calculate_confidence(
            hospital_name="Hosp1",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data={},
            all_hospital_data=all_data,
            indicator_map={"2": "Total Deliveries"},
            indicator_children={},
            indicator_rule_map={},
        )
        assert result.indicator_count >= 1

    def test_priority_verify_sorted_by_confidence(self):
        values = {"2": 300, "3": 200}
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total", "3": "NVD"},
            indicator_children={},
            indicator_rule_map={},
        )
        confidences = [i.confidence for i in result.priority_verify]
        assert confidences == sorted(confidences)

    def test_by_level_counts(self):
        values = {"2": 300, "3": 200, "5": 80}
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total", "3": "NVD", "5": "CS"},
            indicator_children={},
            indicator_rule_map={},
        )
        total = sum(result.by_level.values())
        assert total == result.indicator_count

    def test_by_group_computed(self):
        values = {"2": 300, "3": 200, "4": 20, "5": 80}
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total", "3": "NVD", "4": "Facility", "5": "CS"},
            indicator_children={},
            indicator_rule_map={},
        )
        assert "Deliveries" in result.by_group

    def test_to_dict_roundtrip(self):
        values = {"2": 300}
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=[],
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total"},
            indicator_children={},
            indicator_rule_map={},
        )
        d = result.to_dict()
        assert d["overall_confidence"] == round(result.overall_confidence, 1)
        assert d["level"] == result.level
        assert d["indicator_count"] == result.indicator_count

    def test_with_rule_failures(self):
        values = {"2": 300, "5": 80}
        rule_results = [
            RuleResult("R041", "C-section rate high", RuleStatus.FAIL, Severity.HIGH, RuleType.BENCHMARK, "Rate exceeds threshold"),
        ]
        result = calculate_confidence(
            hospital_name="Test",
            month="2026-04",
            values=values,
            rule_results=rule_results,
            historical_data={},
            all_hospital_data={},
            indicator_map={"2": "Total", "5": "CS"},
            indicator_children={},
            indicator_rule_map={"5": ["R041"]},
        )
        assert result.indicator_count >= 2
        ind5 = [i for i in result.indicators if i.indicator_code == "5"]
        if ind5:
            assert ind5[0].confidence <= 100
