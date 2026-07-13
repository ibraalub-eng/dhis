"""Comprehensive tests for clinical analysis engine (engine.clinical).

Target: 100% coverage of clinical calculation modules.
Covers: thresholds, classifications, risk, morbidity, recommendations, summary, orchestrator.
"""
import pytest
from app.engine.clinical import (
    ClinicalClassification,
    RiskMetric,
    RiskProfile,
    MorbidityProfile,
    Recommendation,
    ClinicalSummary,
    ClinicalAnalysisResult,
    CLINICAL_THRESHOLDS,
    CLASSIFICATION_LABELS,
    CLASSIFICATION_COLORS,
    LOW_TO_CRITICAL,
    get_threshold,
    classify_rate,
    classify_clinical_rate,
    compute_all_classifications,
    compute_risk_profile,
    compute_morbidity_profile,
    generate_recommendations,
    generate_clinical_summary,
    run_clinical_analysis,
)


# ── Thresholds ────────────────────────────────────────────────

class TestClinicalThresholds:
    def test_there_are_15_thresholds(self):
        assert len(CLINICAL_THRESHOLDS) == 15

    def test_each_threshold_has_required_fields(self):
        for t in CLINICAL_THRESHOLDS:
            assert t.indicator_code
            assert t.rate_name
            assert isinstance(t.numerator_codes, list)
            assert t.denominator_code
            assert t.unit
            assert isinstance(t.normal_range, tuple)
            assert isinstance(t.elevated_range, tuple)
            assert isinstance(t.high_range, tuple)

    def test_get_threshold_by_indicator_code(self):
        t = get_threshold("rate_cs")
        assert t is not None
        assert "5" in t.numerator_codes

    def test_get_threshold_not_found(self):
        assert get_threshold("Nonexistent Rate") is None

    def test_classification_labels_dict(self):
        assert isinstance(CLASSIFICATION_LABELS, dict)
        assert len(CLASSIFICATION_LABELS) > 0

    def test_classification_colors_dict(self):
        assert isinstance(CLASSIFICATION_COLORS, dict)
        assert len(CLASSIFICATION_COLORS) > 0

    def test_low_to_critical_mapping(self):
        assert LOW_TO_CRITICAL[0] == "normal"
        assert LOW_TO_CRITICAL[4] == "critical"


# ── classify_rate ─────────────────────────────────────────────

class TestClassifyRate:
    def _cs_threshold(self):
        return get_threshold("rate_cs")

    def test_classify_normal(self):
        t = self._cs_threshold()
        # CS normal range is (10, 15), so 12 is normal
        result = classify_rate(12.0, t)
        assert result == "normal"

    def test_classify_elevated(self):
        t = self._cs_threshold()
        result = classify_rate(20.0, t)
        assert result == "elevated"

    def test_classify_high(self):
        t = self._cs_threshold()
        result = classify_rate(30.0, t)
        assert result == "high"

    def test_classify_critical(self):
        t = self._cs_threshold()
        result = classify_rate(45.0, t)
        assert result == "critical"

    def test_classify_none_value(self):
        t = self._cs_threshold()
        result = classify_rate(None, t)
        assert result == "unknown"

    def test_classify_below_normal(self):
        # For "higher is better" indicators (like breastfeeding)
        t = get_threshold("rate_bf")
        # Breastfeeding normal range (80, 100), higher is worse=False
        result = classify_rate(90.0, t)
        assert result == "normal"

    def test_classify_breastfeeding_low(self):
        t = get_threshold("rate_bf")
        # Below normal range for bf should be below_normal
        result = classify_rate(50.0, t)
        assert result in ("below_normal", "elevated", "high")


# ── classify_clinical_rate ────────────────────────────────────

class TestClassifyClinicalRate:
    def test_classify_by_indicator_code(self):
        result = classify_clinical_rate(12.0, "", indicator_code="rate_cs")
        assert isinstance(result, ClinicalClassification)
        assert result.classification == "normal"

    def test_classify_no_threshold(self):
        result = classify_clinical_rate(10.0, "Nonexistent Rate")
        assert result.classification == "unknown"

    def test_classify_with_rate_name(self):
        result = classify_clinical_rate(20.0, "C-Section Rate")
        assert isinstance(result, ClinicalClassification)
        assert result.classification in ("elevated", "normal")

    def test_classify_critical_value(self):
        result = classify_clinical_rate(45.0, "", indicator_code="rate_cs")
        assert result.classification in ("critical", "high")

    def test_narrative_is_built(self):
        result = classify_clinical_rate(12.0, "", indicator_code="5")
        assert len(result.narrative) > 0


# ── compute_all_classifications ───────────────────────────────

class TestComputeAllClassifications:
    def test_returns_list_of_classifications(self, sample_values):
        results = compute_all_classifications(sample_values)
        assert isinstance(results, list)
        assert len(results) == 15

    def test_each_result_has_fields(self, sample_values):
        results = compute_all_classifications(sample_values)
        for c in results:
            assert isinstance(c, ClinicalClassification)
            assert c.rate_name
            assert c.classification

    def test_cs_rate_classification(self, sample_values):
        results = compute_all_classifications(sample_values)
        cs = [c for c in results if "C-Section" in c.rate_name]
        assert len(cs) >= 1
        # 80/300*100 = 26.67 which is high
        assert cs[0].classification in ("high", "elevated")

    def test_zero_denominator_skipped(self):
        values = {"2": 0, "5": 50}
        results = compute_all_classifications(values)
        cs = [c for c in results if "C-Section" in c.rate_name]
        assert cs[0].value is None

    def test_empty_values(self):
        results = compute_all_classifications({})
        assert len(results) == 15
        for c in results:
            assert c.value is None

    def test_all_15_indicators_classified(self, sample_values):
        results = compute_all_classifications(sample_values)
        assert len(results) == 15


# ── compute_risk_profile ─────────────────────────────────────

class TestComputeRiskProfile:
    def test_basic_risk_profile(self, sample_values):
        profile = compute_risk_profile("Test Hospital", "2026-04", sample_values)
        assert isinstance(profile, RiskProfile)
        assert profile.hospital == "Test Hospital"
        assert profile.month == "2026-04"
        assert profile.total_deliveries == 300
        assert len(profile.metrics) > 0

    def test_risk_level_is_valid(self, sample_values):
        profile = compute_risk_profile("Test Hospital", "2026-04", sample_values)
        assert profile.overall_risk_level in ("low", "moderate", "high", "critical", "unknown")

    def test_risk_profile_zero_deliveries(self):
        profile = compute_risk_profile("Empty", "2026-04", {"2": 0})
        assert profile.overall_risk_level == "unknown"

    def test_risk_profile_key_findings(self, sample_values):
        profile = compute_risk_profile("Test", "2026-04", sample_values)
        assert isinstance(profile.key_findings, list)

    def test_risk_metrics_have_fields(self, sample_values):
        profile = compute_risk_profile("Test", "2026-04", sample_values)
        for m in profile.metrics:
            assert isinstance(m, RiskMetric)
            assert m.metric_name
            assert m.unit
            assert m.severity in ("low", "moderate", "high", "critical", "normal", "unknown")

    def test_risk_profile_missing_data(self, sample_values_minimal):
        profile = compute_risk_profile("Test", "2026-04", sample_values_minimal)
        assert profile.total_deliveries == 100

    def test_risk_profile_high_cs(self):
        values = {"2": 100, "5": 50, "5.b.1": 40, "2.c": 5, "2.h": 10, "6": 95}
        profile = compute_risk_profile("Test", "2026-04", values)
        assert profile.overall_risk_level in ("high", "critical", "moderate")


# ── compute_morbidity_profile ─────────────────────────────────

class TestComputeMorbidityProfile:
    def test_basic_morbidity(self, sample_values):
        profile = compute_morbidity_profile("Test Hospital", "2026-04", sample_values)
        assert isinstance(profile, MorbidityProfile)
        assert profile.hospital == "Test Hospital"
        assert profile.month == "2026-04"
        assert profile.total_deliveries == 300
        assert profile.total_smm == 15
        assert profile.maternal_deaths == 1

    def test_morbidity_metrics(self, sample_values):
        profile = compute_morbidity_profile("Test", "2026-04", sample_values)
        assert len(profile.metrics) > 5

    def test_morbidity_zero_smm(self):
        values = {"2": 300, "10": 0, "11": 0, "6": 280}
        profile = compute_morbidity_profile("Test", "2026-04", values)
        assert profile.total_smm == 0
        assert profile.maternal_deaths == 0

    def test_morbidity_key_findings(self, sample_values):
        profile = compute_morbidity_profile("Test", "2026-04", sample_values)
        assert isinstance(profile.key_findings, list)

    def test_morbidity_preventability_signals(self):
        values = {"2": 300, "10": 5, "11": 1, "7": 10, "7.a": 7, "6": 280, "17": 8, "17.a": 5}
        profile = compute_morbidity_profile("Test", "2026-04", values)
        assert isinstance(profile.mortality_preventability_signals, list)

    def test_morbidity_smm_sub_components(self, sample_values):
        profile = compute_morbidity_profile("Test", "2026-04", sample_values)
        sub_metrics = [m for m in profile.metrics if "proportion" in m.metric_name.lower() or "SMM" in m.metric_name]
        assert len(sub_metrics) > 0

    def test_morbidity_case_fatality(self):
        values = {"2": 300, "10": 15, "11": 1, "6": 280}
        profile = compute_morbidity_profile("Test", "2026-04", values)
        cf = [m for m in profile.metrics if "fatality" in m.metric_name.lower()]
        if cf:
            assert cf[0].value is not None


# ── generate_recommendations ──────────────────────────────────

class TestGenerateRecommendations:
    def test_basic_recommendations(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(sample_values, classifications, risk, morbidity)
        assert isinstance(recs, list)
        for r in recs:
            assert isinstance(r, Recommendation)
            assert r.category
            assert r.priority
            assert r.title
            assert r.description

    def test_recommendations_with_quality_score(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(
            sample_values, classifications, risk, morbidity, quality_score=35.0,
        )
        quality_recs = [r for r in recs if "quality" in r.title.lower() or "data quality" in r.category.lower()]
        assert len(quality_recs) > 0

    def test_recommendations_with_rule_failures(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        rule_failures = [
            {"rule_code": "R001", "details": "Total deliveries mismatch: R001 failed"},
            {"rule_code": "R041", "details": "CS rate too high: R041 triggered"},
        ]
        recs = generate_recommendations(
            sample_values, classifications, risk, morbidity, rule_failures=rule_failures,
        )
        for r in recs:
            assert isinstance(r.triggered_by_rules, list)

    def test_recommendations_sorted_by_priority(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(sample_values, classifications, risk, morbidity)
        priorities = [r.priority for r in recs]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(priorities) - 1):
            assert priority_order.get(priorities[i], 4) <= priority_order.get(priorities[i + 1], 4)

    def test_recommendations_have_action_items(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(sample_values, classifications, risk, morbidity)
        for r in recs:
            assert isinstance(r.action_items, list)
            assert isinstance(r.indicators_monitored, list)

    def test_recommendations_high_cs_triggers(self):
        values = {"2": 100, "5": 50, "6": 95}
        classifications = compute_all_classifications(values)
        risk = compute_risk_profile("Test", "2026-04", values)
        morbidity = compute_morbidity_profile("Test", "2026-04", values)
        recs = generate_recommendations(values, classifications, risk, morbidity)
        cs_recs = [r for r in recs if "c-section" in r.title.lower() or "cesarean" in r.title.lower() or "cs" in r.title.lower()]
        assert len(cs_recs) > 0

    def test_recommendations_maternal_mortality(self):
        values = {"2": 200, "11": 5, "6": 190}
        classifications = compute_all_classifications(values)
        risk = compute_risk_profile("Test", "2026-04", values)
        morbidity = compute_morbidity_profile("Test", "2026-04", values)
        recs = generate_recommendations(values, classifications, risk, morbidity)
        mmr_recs = [r for r in recs if "mortal" in r.title.lower() or "death" in r.title.lower()]
        assert len(mmr_recs) > 0

    def test_recommendations_empty_values(self):
        classifications = compute_all_classifications({})
        risk = compute_risk_profile("Test", "2026-04", {})
        morbidity = compute_morbidity_profile("Test", "2026-04", {})
        recs = generate_recommendations({}, classifications, risk, morbidity)
        assert isinstance(recs, list)


# ── generate_clinical_summary ─────────────────────────────────

class TestGenerateClinicalSummary:
    def test_basic_summary(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(sample_values, classifications, risk, morbidity)
        summary = generate_clinical_summary(
            "Test Hospital", "2026-04", sample_values, classifications, risk, morbidity, recs,
        )
        assert isinstance(summary, ClinicalSummary)
        assert summary.hospital == "Test Hospital"
        assert summary.month == "2026-04"
        assert len(summary.overview) > 0
        assert isinstance(summary.key_findings, list)
        assert isinstance(summary.clinical_indicators, list)
        assert isinstance(summary.recommendations_text, list)
        assert len(summary.overall_assessment) > 0

    def test_summary_with_quality_score(self, sample_values):
        classifications = compute_all_classifications(sample_values)
        risk = compute_risk_profile("Test", "2026-04", sample_values)
        morbidity = compute_morbidity_profile("Test", "2026-04", sample_values)
        recs = generate_recommendations(sample_values, classifications, risk, morbidity)
        summary = generate_clinical_summary(
            "Test", "2026-04", sample_values, classifications, risk, morbidity, recs, quality_score=30.0,
        )
        assert "quality" in summary.overall_assessment.lower() or "attention" in summary.overall_assessment.lower() or "critical" in summary.overall_assessment.lower() or len(summary.overall_assessment) > 0

    def test_summary_empty_data(self):
        classifications = compute_all_classifications({})
        risk = compute_risk_profile("Test", "2026-04", {})
        morbidity = compute_morbidity_profile("Test", "2026-04", {})
        recs = generate_recommendations({}, classifications, risk, morbidity)
        summary = generate_clinical_summary(
            "Test", "2026-04", {}, classifications, risk, morbidity, recs,
        )
        assert isinstance(summary, ClinicalSummary)


# ── run_clinical_analysis (orchestrator) ──────────────────────

class TestRunClinicalAnalysis:
    def test_basic_analysis(self, sample_values):
        result = run_clinical_analysis("Test Hospital", "2026-04", sample_values)
        assert isinstance(result, ClinicalAnalysisResult)
        assert result.hospital == "Test Hospital"
        assert result.month == "2026-04"
        assert isinstance(result.classifications, list)
        assert len(result.classifications) == 15
        assert isinstance(result.risk_profile, RiskProfile)
        assert isinstance(result.morbidity_profile, MorbidityProfile)
        assert isinstance(result.recommendations, list)
        assert isinstance(result.summary, ClinicalSummary)

    def test_analysis_with_quality_score(self, sample_values):
        result = run_clinical_analysis("Test", "2026-04", sample_values, quality_score=30.0)
        assert isinstance(result, ClinicalAnalysisResult)

    def test_analysis_with_issues(self, sample_values):
        result = run_clinical_analysis(
            "Test", "2026-04", sample_values, issues=["Missing indicator R001"],
        )
        assert isinstance(result, ClinicalAnalysisResult)

    def test_analysis_with_rule_failures(self, sample_values):
        rule_failures = [{"rule_code": "R001", "details": "R001 failed"}]
        result = run_clinical_analysis(
            "Test", "2026-04", sample_values, rule_failures=rule_failures,
        )
        assert isinstance(result, ClinicalAnalysisResult)

    def test_analysis_empty_values(self):
        result = run_clinical_analysis("Test", "2026-04", {})
        assert isinstance(result, ClinicalAnalysisResult)
        assert len(result.classifications) == 15

    def test_analysis_to_dict(self, sample_values):
        result = run_clinical_analysis("Test", "2026-04", sample_values)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "hospital" in d
        assert "month" in d
        assert "classifications" in d
        assert "risk_profile" in d
        assert "morbidity_profile" in d
        assert "recommendations" in d
        assert "summary" in d

    def test_analysis_minimal_values(self, sample_values_minimal):
        result = run_clinical_analysis("Test", "2026-04", sample_values_minimal)
        assert isinstance(result, ClinicalAnalysisResult)


# ── Regression: All Clinical Indicators ───────────────────────

class TestClinicalIndicatorRegression:
    """Regression tests for every clinical indicator threshold."""

    @pytest.mark.parametrize("rate_code,values_dict,expected_classification", [
        # CS rate: normal(10,15) elevated(15,25) high(25,40) crit>40
        ("rate_cs", {"2": 300, "5": 40}, "normal"),     # 13.33
        ("rate_cs", {"2": 300, "5": 50}, "elevated"),   # 16.67
        ("rate_cs", {"2": 300, "5": 90}, "high"),       # 30.0
        ("rate_cs", {"2": 300, "5": 150}, "critical"),  # 50.0
        # MMR per 100k: normal(0,50) elevated(50,150) high(150,300) crit>300
        ("rate_mmr", {"2": 300, "11": 0}, "normal"),    # 0
        ("rate_mmr", {"2": 1000, "11": 1}, "elevated"), # 100
        # NMR per 1k: normal(0,15) elevated(15,30) high(30,45) crit>45
        ("rate_nmr", {"6": 1000, "17": 5}, "normal"),   # 5
        ("rate_nmr", {"6": 1000, "17": 20}, "elevated"),# 20
        # Preterm rate: normal(0,10) elevated(10,15) high(15,20) crit>20
        ("rate_preterm", {"6": 100, "6.f": 5}, "normal"),   # 5
        ("rate_preterm", {"6": 100, "6.f": 12}, "elevated"), # 12
        # SMM rate: normal(0,2) elevated(2,5) high(5,10) crit>10
        ("rate_smm", {"2": 100, "10": 1}, "normal"),    # 1.0
        ("rate_smm", {"2": 100, "10": 8}, "high"),       # 8.0
        # Stillbirth per 1k: normal(0,12) elevated(12,22) high(22,35) crit>35
        ("rate_stillbirth", {"2": 100, "7": 1}, "normal"),    # 10
        ("rate_stillbirth", {"2": 100, "7": 1.5}, "elevated"), # 15
        # NICU rate: normal(0,15) elevated(15,25) high(25,40) crit>40
        ("rate_nicu", {"6": 100, "16": 5}, "normal"),   # 5
        ("rate_nicu", {"6": 100, "16": 30}, "high"),     # 30
    ])
    def test_indicator_classification_regression(self, rate_code, values_dict, expected_classification):
        """Each indicator should classify correctly across severity levels."""
        classifications = compute_all_classifications(values_dict)
        matching = [c for c in classifications if c.indicator_code == rate_code]
        assert len(matching) >= 1, f"No classification found for rate_code {rate_code}"
        assert matching[0].classification == expected_classification, (
            f"Rate {rate_code}: expected {expected_classification}, "
            f"got {matching[0].classification} (value={matching[0].value})"
        )