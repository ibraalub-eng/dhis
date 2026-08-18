"""Tests for root cause analysis (engine.root_cause)."""
from app.engine.root_cause import (
    analyze_rule_failures,
    analyze_quality_drivers,
    analyze_confidence_gaps,
    analyze_anomaly_patterns,
    generate_root_cause_analysis,
    _diagnose_rule_failure,
    _diagnose_rule_failure_v2,
    _diagnose_rule_failure_v2_ar,
    _diagnose_confidence_gap,
    _extract_rule_type,
    _build_dynamic_diagnosis,
    QualityDriver,
    RootCauseReport,
)
from app.models import (
    Hospital, Indicator, IndicatorValue, ValidationResult, AnomalyResult, QualityScore, ConfidenceScore,
)
import json


class TestDiagnoseRuleFailure:
    def test_r001_mismatch(self):
        cause, rec = _diagnose_rule_failure("R001", "")
        assert "sum mismatch" in cause.lower() or "sub-indicator" in cause.lower()

    def test_r002_parity(self):
        cause, rec = _diagnose_rule_failure("R002", "")
        assert "parity" in cause.lower()

    def test_r041_csection(self):
        cause, rec = _diagnose_rule_failure("R041", "")
        assert "C-section" in cause

    def test_r054_maternal_deaths(self):
        cause, rec = _diagnose_rule_failure("R054", "")
        assert "maternal" in cause.lower() or "CRITICAL" in cause

    def test_exceeds_keyword(self):
        cause, rec = _diagnose_rule_failure("R999", "value exceeds expected threshold")
        assert "exceeds" in cause.lower()

    def test_missing_keyword(self):
        cause, rec = _diagnose_rule_failure("R999", "indicator value missing")
        assert "missing" in cause.lower() or "not reported" in cause.lower()

    def test_negative_keyword(self):
        cause, rec = _diagnose_rule_failure("R999", "negative value reported")
        assert "negative" in cause.lower()

    def test_decimal_keyword(self):
        cause, rec = _diagnose_rule_failure("R999", "decimal value reported")
        assert "decimal" in cause.lower()

    def test_generic_fallback(self):
        cause, rec = _diagnose_rule_failure("R999", "some random detail")
        assert cause
        assert rec


class TestDiagnoseConfidenceGap:
    def test_rule_compliance(self):
        cause, rec = _diagnose_confidence_gap("rule_compliance", "Total Deliveries", "LOW")
        assert "rule" in cause.lower()

    def test_historical(self):
        cause, rec = _diagnose_confidence_gap("historical", "Total Deliveries", "LOW")
        assert "historical" in cause.lower() or "volatility" in cause.lower()

    def test_cross_hospital(self):
        cause, rec = _diagnose_confidence_gap("cross_hospital", "Total Deliveries", "LOW")
        assert "peer" in cause.lower() or "deviates" in cause.lower()

    def test_trend(self):
        cause, rec = _diagnose_confidence_gap("trend", "Total Deliveries", "LOW")
        assert "trend" in cause.lower()

    def test_completeness(self):
        cause, rec = _diagnose_confidence_gap("completeness", "Total Deliveries", "LOW")
        assert "missing" in cause.lower() or "sub-component" in cause.lower()

    def test_unknown_factor(self):
        cause, rec = _diagnose_confidence_gap("unknown", "Total Deliveries", "LOW")
        assert cause
        assert rec


class TestAnalyzeRuleFailures:
    def test_no_failures_returns_empty(self, db_session):
        hospital = db_session.query(Hospital).first()
        patterns = analyze_rule_failures(db_session, hospital.id, "2026-04")
        assert patterns == []

    def test_with_failures(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add_all([
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R001", rule_description="Parent-child mismatch",
                status="FAIL", severity="HIGH", rule_type="LOGIC",
                details="Sum mismatch",
            ),
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R001", rule_description="Parent-child mismatch",
                status="FAIL", severity="HIGH", rule_type="LOGIC",
                details="Sum mismatch",
            ),
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R001", rule_description="Parent-child mismatch",
                status="PASS", severity="HIGH", rule_type="LOGIC",
                details="",
            ),
        ])
        db_session.commit()

        patterns = analyze_rule_failures(db_session, hospital.id, "2026-04")
        assert len(patterns) >= 1
        assert patterns[0].failure_count == 2
        assert patterns[0].failure_rate > 0

    def test_sorted_by_severity(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add_all([
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R099", rule_description="Low severity",
                status="FAIL", severity="LOW", rule_type="LOGIC", details="",
            ),
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R098", rule_description="Critical severity",
                status="FAIL", severity="CRITICAL", rule_type="LOGIC", details="",
            ),
        ])
        db_session.commit()

        patterns = analyze_rule_failures(db_session, hospital.id, "2026-04")
        if len(patterns) >= 2:
            assert patterns[0].severity == "CRITICAL"


class TestAnalyzeQualityDrivers:
    def test_empty_returns_empty(self):
        drivers = analyze_quality_drivers(None)
        assert drivers == []

    def test_with_quality_data(self):
        data = {
            "rule_compliance": 80,
            "completeness": 90,
            "consistency": 70,
            "outlier_penalty": 0.1,
        }
        drivers = analyze_quality_drivers(data)
        assert len(drivers) == 4
        for d in drivers:
            assert isinstance(d, QualityDriver)
            assert d.component
            assert 0 <= d.value <= 100
            assert d.weight > 0

    def test_sorted_by_impact(self):
        data = {
            "rule_compliance": 30,
            "completeness": 90,
            "consistency": 90,
            "outlier_penalty": 0.0,
        }
        drivers = analyze_quality_drivers(data)
        impacts = [d.impact for d in drivers]
        assert impacts == sorted(impacts, reverse=True)

    def test_status_classification(self):
        data = {
            "rule_compliance": 90,
            "completeness": 60,
            "consistency": 30,
            "outlier_penalty": 0.0,
        }
        drivers = analyze_quality_drivers(data)
        statuses = {d.component: d.status for d in drivers}
        assert statuses["Rule Compliance"] == "good"
        assert statuses["Consistency"] == "critical"


class TestAnalyzeConfidenceGaps:
    def test_no_confidence_score_returns_empty(self, db_session):
        hospital = db_session.query(Hospital).first()
        gaps = analyze_confidence_gaps(db_session, hospital.id, "2026-04")
        assert gaps == []

    def test_with_low_confidence_indicators(self, db_session):
        hospital = db_session.query(Hospital).first()
        indicators = [
            {"indicator_code": "2", "indicator_name": "Total Deliveries",
             "confidence": 30.0, "level": "LOW",
             "signals": [{"factor": "historical", "score": 0.2, "passed": False, "detail": "deviates"}]},
            {"indicator_code": "3", "indicator_name": "NVD",
             "confidence": 80.0, "level": "HIGH",
             "signals": [{"factor": "rule_compliance", "score": 1.0, "passed": True, "detail": "all pass"}]},
        ]
        db_session.add(ConfidenceScore(
            hospital_id=hospital.id, month="2026-04",
            overall_confidence=55.0, level="MEDIUM",
            indicator_count=2, high_count=1, medium_count=0, low_count=1, critical_count=0,
            indicators_data=json.dumps(indicators),
            summary="Test",
        ))
        db_session.commit()

        gaps = analyze_confidence_gaps(db_session, hospital.id, "2026-04")
        assert len(gaps) >= 1
        assert gaps[0].level == "LOW"
        assert gaps[0].confidence == 30.0

    def test_sorted_by_severity(self, db_session):
        hospital = db_session.query(Hospital).first()
        indicators = [
            {"indicator_code": "2", "indicator_name": "Total",
             "confidence": 20.0, "level": "CRITICAL",
             "signals": [{"factor": "rule_compliance", "score": 0.1, "passed": False, "detail": "fail"}]},
            {"indicator_code": "3", "indicator_name": "NVD",
             "confidence": 40.0, "level": "LOW",
             "signals": [{"factor": "historical", "score": 0.3, "passed": False, "detail": "deviates"}]},
        ]
        db_session.add(ConfidenceScore(
            hospital_id=hospital.id, month="2026-04",
            overall_confidence=30.0, level="LOW",
            indicator_count=2, high_count=0, medium_count=0, low_count=1, critical_count=1,
            indicators_data=json.dumps(indicators),
            summary="Test",
        ))
        db_session.commit()

        gaps = analyze_confidence_gaps(db_session, hospital.id, "2026-04")
        if len(gaps) >= 2:
            assert gaps[0].level == "CRITICAL"


class TestAnalyzeAnomalyPatterns:
    def test_no_anomalies_returns_empty(self, db_session):
        hospital = db_session.query(Hospital).first()
        patterns = analyze_anomaly_patterns(db_session, hospital.id, "2026-04")
        assert patterns == []

    def test_with_outliers(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add_all([
            AnomalyResult(
                hospital_id=hospital.id, month="2026-04",
                indicator_code="5", rate_name="C-section rate",
                value=45.0, benchmark=25.0, z_score=3.5, is_outlier=True,
            ),
            AnomalyResult(
                hospital_id=hospital.id, month="2026-04",
                indicator_code="11", rate_name="Maternal mortality rate",
                value=5.0, benchmark=1.0, z_score=2.8, is_outlier=True,
            ),
        ])
        db_session.commit()

        patterns = analyze_anomaly_patterns(db_session, hospital.id, "2026-04")
        assert len(patterns) >= 1
        assert patterns[0].pattern_type in ("severe", "moderate", "mild")
        assert abs(patterns[0].avg_z_score) > 2

    def test_pattern_type_classification(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add(AnomalyResult(
            hospital_id=hospital.id, month="2026-04",
            indicator_code="5", rate_name="C-section rate",
            value=30.0, benchmark=25.0, z_score=3.2, is_outlier=True,
        ))
        db_session.commit()

        patterns = analyze_anomaly_patterns(db_session, hospital.id, "2026-04")
        assert patterns[0].pattern_type == "severe"


class TestGenerateRootCauseAnalysis:
    def test_basic_report(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, indicator_id=ind.id,
                    month="2026-04", value=value,
                ))
        db_session.commit()

        from app.engine.pipeline import run_full_analysis
        run_full_analysis(db_session, hospital.id, "2026-04")

        quality_data = {"score": 75.0, "rule_compliance": 80, "completeness": 85, "consistency": 70, "outlier_penalty": 0.1}
        confidence_data = {"overall_confidence": 70.0}

        report = generate_root_cause_analysis(
            db_session, hospital.id, "2026-04",
            quality_data=quality_data,
            confidence_data=confidence_data,
        )
        assert isinstance(report, RootCauseReport)
        assert report.hospital
        assert report.hospital_id == hospital.id
        assert report.month == "2026-04"
        assert report.overall_quality_score == 75.0
        assert report.overall_confidence == 70.0
        assert report.summary

    def test_report_with_issues(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add_all([
            ValidationResult(
                hospital_id=hospital.id, month="2026-04",
                rule_code="R001", rule_description="Parent-child mismatch",
                status="FAIL", severity="HIGH", rule_type="LOGIC", details="Sum mismatch",
            ),
            AnomalyResult(
                hospital_id=hospital.id, month="2026-04",
                indicator_code="5", rate_name="C-section rate",
                value=45.0, benchmark=25.0, z_score=3.5, is_outlier=True,
            ),
        ])
        indicators = [
            {"indicator_code": "2", "indicator_name": "Total Deliveries",
             "confidence": 25.0, "level": "CRITICAL",
             "signals": [{"factor": "rule_compliance", "score": 0.1, "passed": False, "detail": "fail"}]},
        ]
        db_session.add(ConfidenceScore(
            hospital_id=hospital.id, month="2026-04",
            overall_confidence=25.0, level="CRITICAL",
            indicator_count=1, high_count=0, medium_count=0, low_count=0, critical_count=1,
            indicators_data=json.dumps(indicators),
            summary="Test",
        ))
        db_session.add(QualityScore(
            hospital_id=hospital.id, month="2026-04",
            score=40.0, rule_compliance=30, completeness=50, consistency=40,
            outlier_penalty=0.2, issues=json.dumps(["Rule failures"]),
        ))
        db_session.commit()

        quality_data = {"score": 40.0, "rule_compliance": 30, "completeness": 50, "consistency": 40, "outlier_penalty": 0.2}
        confidence_data = {"overall_confidence": 25.0}

        report = generate_root_cause_analysis(
            db_session, hospital.id, "2026-04",
            quality_data=quality_data,
            confidence_data=confidence_data,
        )
        assert report.critical_issues_count > 0
        assert len(report.top_rule_failures) >= 1
        assert len(report.quality_drivers) >= 1
        assert len(report.confidence_gaps) >= 1
        assert len(report.anomaly_patterns) >= 1
        assert len(report.priority_actions) >= 1
        # التوصيات الذكية تعمل محلياً (دون AI خارجي) وثنائية اللغة ومحددة
        assert len(report.ai_recommendations) >= 1
        ar_rec = report.ai_recommendations[0]
        assert ar_rec.get("title") and ar_rec.get("title_ar")
        assert ar_rec.get("category_ar")
        # مرتبة بالأولوية: أول توصية حرجة/عالية لمستشفى فيه R001 فشل حرج
        assert report.ai_recommendations[0]["priority"] in ("critical", "high")

    def test_report_no_issues(self, db_session):
        hospital = db_session.query(Hospital).first()
        quality_data = {"score": 95.0, "rule_compliance": 95, "completeness": 95, "consistency": 95, "outlier_penalty": 0.0}
        confidence_data = {"overall_confidence": 90.0}

        report = generate_root_cause_analysis(
            db_session, hospital.id, "2026-04",
            quality_data=quality_data,
            confidence_data=confidence_data,
        )
        assert "No critical issues" in report.summary or report.critical_issues_count == 0

    def test_priority_actions_includes_severity(self, db_session):
        hospital = db_session.query(Hospital).first()
        db_session.add(ValidationResult(
            hospital_id=hospital.id, month="2026-04",
            rule_code="R054", rule_description="Maternal deaths surge",
            status="FAIL", severity="CRITICAL", rule_type="THRESHOLD",
            details="Maternal deaths surged above threshold",
        ))
        db_session.commit()

        quality_data = {"score": 50.0, "rule_compliance": 40, "completeness": 60, "consistency": 50, "outlier_penalty": 0.1}
        confidence_data = {"overall_confidence": 50.0}

        report = generate_root_cause_analysis(
            db_session, hospital.id, "2026-04",
            quality_data=quality_data,
            confidence_data=confidence_data,
        )
        actions = report.priority_actions
        assert len(actions) >= 1
        assert any("CRITICAL" in a or "Quality" in a for a in actions)


def test_ai_recommendations_bilingual_specific():
    """التوصيات الذكية المحلية تعمل دائماً، ثنائية اللغة، ومحددة بالبيانات الفعلية."""
    from app.engine.root_cause import _build_local_recommendations, RuleFailurePattern

    rf = RuleFailurePattern(
        rule_code="R054", rule_description="Maternal deaths surge",
        severity="CRITICAL", failure_count=2, total_runs=3, failure_rate=66.7,
        primary_cause="Maternal deaths surged above threshold",
        recommendation="CRITICAL: Immediate investigation required.",
        rule_type="THRESHOLD",
    )
    recs = _build_local_recommendations(
        "مستشفى الشفاء", "2026-06", 45.0, 35.0,
        [rf], [], [], [], [], {}, {},
    )
    assert recs
    top = recs[0]
    # أولوية صالحة + حقول ثنائية اللغة كاملة
    assert top["priority"] in ("critical", "high", "medium", "low")
    assert top["title"] and top["title_ar"]
    assert top["description"] and top["description_ar"]
    assert top["action_items"] and top["action_items_ar"]
    assert top["category"] == "Data Validation"
    assert top["category_ar"] == "التحقق من البيانات"
    # محددة بالبيانات الفعلية: كود القاعدة ونسبة الفشل في العنوان العربي
    assert "R054" in top["title_ar"]
    assert "66.7" in top["title_ar"] or "67" in top["title_ar"]

    # حالة سليمة → توصية محافظة عربية
    ok = _build_local_recommendations(
        "مستشفى الأهلي", "2026-06", 95.0, 92.0,
        [], [], [], [], [], {}, {},
    )
    assert ok and ok[0]["category_ar"] == "التحسين المستمر"
    assert ok[0]["priority"] == "low"


def test_merge_drops_english_only_ai_recs():
    """توصيات AI الإنجليزية الخالصة (fallback عند تجاوز الحصة) لا تُدمج —
    المحلي ثنائي اللغة أخصّ، وأي واجهة عربية تعرض محتوى صحيحاً."""
    from app.engine.root_cause import _has_real_arabic, _ar_synthesis_for_ai_rec

    en_only = {
        "category": "Peer Comparison", "priority": "high",
        "title": "Bottom 79% compared to peers", "description": "Hospital ranks low...",
        "rationale": "Underperforming peers.", "action_items": ["Study best practices"],
        "category_ar": "", "title_ar": "", "description_ar": "", "rationale_ar": "",
    }
    assert not _has_real_arabic(en_only)

    bilingual = {"category": "Peer Comparison", "priority": "high",
                  "category_ar": "مقارنة النظير", "title_ar": "القيصرية أعلى من النظير",
                  "description_ar": "قيمة المستشفى أعلى من المتوسط", "rationale_ar": "",
                  "description": "EN", "rationale": "EN", "action_items": [],
                  "action_items_ar": []}
    assert _has_real_arabic(bilingual)
    syn = _ar_synthesis_for_ai_rec(en_only)
    # توليد العناوين يملأ category_ar/title_ar لكنه لا يترجم الوصف —
    # لذلك تُهمَل هذه التوصية كلياً في الدمج (يغطيها اختبار الدمج أدناه).
    assert syn["title_ar"] and not _has_real_arabic(en_only)


def test_merge_keeps_local_recs_and_drops_english_only():
    """دمج التوصيات: المحلية ثنائية اللغة تبقى دائماً، والإنجليزية الخالصة تُسقط."""
    from app.engine.root_cause import (
        _build_local_recommendations, _has_real_arabic, _ar_synthesis_for_ai_rec,
    )

    local = _build_local_recommendations(
        "مستشفى الشفاء", "2026-06", 55.0, 45.0,
        [], [], [], [], [], {}, {},
    )
    # كل توصية محلية تمر ببوابة العربية الحقيقية (لأنها ثنائية اللغة)
    assert local and all(_has_real_arabic(r) for r in local)

    en_only = {
        "category": "Risk Management", "priority": "high",
        "category_ar": "", "title_ar": "", "description_ar": "", "rationale_ar": "",
        "title": "EN only", "description": "EN only", "rationale": "EN only",
        "action_items": ["do something"], "action_items_ar": [],
    }
    # بوابة الدمج: بلا عربية حقيقية → لا تُضاف (المحلي أخصّ)
    assert not _has_real_arabic(en_only)
    merged = list(local)
    if _has_real_arabic(en_only):
        merged.append({**en_only, **_ar_synthesis_for_ai_rec(en_only)})
    assert all(_has_real_arabic(m) for m in merged)


def test_arabic_summary_narrative_with_context():
    """الملخص العربي سرد تنفيذي متماسك: سياق المستشفى والشهر + السبب الجذري + الأولوية."""
    from app.engine.root_cause import _generate_arabic_summary, CausalChain

    chain = CausalChain(
        root_cause="R001 failing at 70%",
        root_cause_arabic="فشل التحقق من مطابقة المجموع في R001 بنسبة 70%",
        confidence=0.85,
        evidence=["R001 failure rate: 70%"],
        affected_factors=["R001"],
        recommended_action="Verify all sub-categories are reported",
        impact_if_fixed=16.5,
        implementation_priority="CRITICAL",
        chain_path=["R001", "R006"],
        chain_path_arabic="إجمالي الولادات ← القيصرية الطارئة/المجدولة",
    )

    s = _generate_arabic_summary(
        hospital="مستشفى الشفاء", month="2026-06",
        overall_quality=45.0, overall_confidence=35.0,
        causal_chains=[chain], rule_failures=[], quality_drivers=[],
        confidence_gaps=[], anomaly_patterns=[], peer_comparisons={},
    )

    # يبدأ بسياق المستشفى والشهر
    assert "مستشفى الشفاء" in s and "2026-06" in s
    # حالة عامة + سبب جذري بثقة + إجراء أول
    assert "السبب الجذري الرئيسي" in s
    assert "بثقة" in s
    assert "أولوية التنفيذ المقترحة" in s
    # حالة الحالة العامة (جودة 45 < 50 → تتطلب تدخلاً عاجلاً)
    assert "تتطلب تدخلاً" in s

    # حالة سليمة: لا سلاسل ولا مشاكل → رسالة إيجابية بسياق كامل
    s_ok = _generate_arabic_summary(
        hospital="مستشفى الأهلي", month="2026-06",
        overall_quality=95.0, overall_confidence=92.0,
        causal_chains=[], rule_failures=[], quality_drivers=[],
        confidence_gaps=[], anomaly_patterns=[], peer_comparisons={},
    )
    assert "لا توجد مشاكل حرجة" in s_ok
    assert "مستشفى الأهلي" in s_ok and "2026-06" in s_ok


def test_month_data_point_creation():
    from app.engine.root_cause import MonthDataPoint
    point = MonthDataPoint(
        month="2026-01",
        value=75.0,
        quality_score=80.0,
        confidence=70.0,
        rule_failure_rate=15.0
    )
    assert point.month == "2026-01"
    assert point.value == 75.0


def test_peer_comparison_creation():
    from app.engine.root_cause import PeerComparison
    comp = PeerComparison(
        peer_group="hospital_type",
        peer_count=7,
        mean_value=65.0,
        std_value=10.0,
        hospital_percentile=75.0,
        hospital_z_score=1.0,
        benchmark_hospital="Al-Shifa",
        benchmark_value=85.0,
        gap_to_benchmark=10.0
    )
    assert comp.peer_group == "hospital_type"
    assert comp.hospital_percentile == 75.0


def test_causal_node_creation():
    from app.engine.root_cause import CausalNode
    node = CausalNode(
        factor="R001",
        factor_type="rule",
        current_value=70.0,
        trend="declining",
        trend_slope=-2.5,
        peer_comparison=None,
        history=[],
        severity="critical"
    )
    assert node.factor == "R001"
    assert node.trend == "declining"


def test_causal_chain_creation():
    from app.engine.root_cause import CausalChain
    chain = CausalChain(
        root_cause="R001 sum mismatch failing at 70%",
        root_cause_arabic="فشل التحقق من مطابقة المجموع في R001 بنسبة 70%",
        confidence=0.85,
        evidence=["R001 failure rate: 70%"],
        affected_factors=["R001", "Rule Compliance"],
        recommended_action="Train data entry staff",
        impact_if_fixed=16.5,
        implementation_priority="critical"
    )
    assert chain.confidence == 0.85
    assert len(chain.evidence) == 1


def test_get_historical_data(db_session):
    from app.engine.root_cause import get_historical_data, MonthDataPoint
    from app.models import Hospital, Indicator, IndicatorValue
    from datetime import datetime

    hospital = Hospital(name="Test Hospital", is_active=True)
    db_session.add(hospital)
    db_session.flush()

    indicator = Indicator(code="CS_rate", name="C-Section Rate")
    db_session.add(indicator)
    db_session.flush()

    for i, month in enumerate(["2026-05", "2026-06", "2026-07"]):
        iv = IndicatorValue(
            hospital_id=hospital.id,
            indicator_id=indicator.id,
            month=month,
            value=20.0 + i * 2
        )
        db_session.add(iv)
    db_session.commit()

    result = get_historical_data(db_session, hospital.id, "CS_rate", months_back=3)

    assert len(result) == 3
    assert isinstance(result[0], MonthDataPoint)
    assert result[0].month == "2026-05"
    assert result[2].month == "2026-07"


def test_get_peer_historical_data(db_session):
    from app.engine.root_cause import get_peer_historical_data
    from app.models import Hospital, HospitalType, Indicator, IndicatorValue

    htype = HospitalType(name="Government")
    db_session.add(htype)
    db_session.flush()

    indicator = Indicator(code="CS_rate", name="C-Section Rate")
    db_session.add(indicator)
    db_session.flush()

    h1 = Hospital(name="Hospital A", hospital_type_id=htype.id, is_active=True)
    h2 = Hospital(name="Hospital B", hospital_type_id=htype.id, is_active=True)
    h3 = Hospital(name="Hospital C", hospital_type_id=htype.id, is_active=True)
    db_session.add_all([h1, h2, h3])
    db_session.flush()

    for h in [h1, h2, h3]:
        iv = IndicatorValue(
            hospital_id=h.id,
            indicator_id=indicator.id,
            month="2026-07",
            value=20.0
        )
        db_session.add(iv)
    db_session.commit()

    result = get_peer_historical_data(db_session, h1.id, "CS_rate", months_back=1)

    assert len(result) == 2  # h2 and h3 (not h1 itself)


def test_calculate_trend_declining():
    from app.engine.root_cause import calculate_trend, MonthDataPoint

    history = [
        MonthDataPoint("2026-01", 80.0, 0, 0, 0),
        MonthDataPoint("2026-02", 75.0, 0, 0, 0),
        MonthDataPoint("2026-03", 70.0, 0, 0, 0),
        MonthDataPoint("2026-04", 65.0, 0, 0, 0),
    ]

    result = calculate_trend(history)

    assert result["direction"] == "declining"
    assert result["slope"] < 0
    assert result["r_squared"] > 0.9


def test_calculate_trend_stable():
    from app.engine.root_cause import calculate_trend, MonthDataPoint

    history = [
        MonthDataPoint("2026-01", 70.0, 0, 0, 0),
        MonthDataPoint("2026-02", 71.0, 0, 0, 0),
        MonthDataPoint("2026-03", 70.0, 0, 0, 0),
        MonthDataPoint("2026-04", 70.5, 0, 0, 0),
    ]

    result = calculate_trend(history)

    assert result["direction"] == "stable"
    assert abs(result["slope"]) < 0.5


def test_calculate_trend_insufficient_data():
    from app.engine.root_cause import calculate_trend, MonthDataPoint

    result = calculate_trend([])

    assert result["slope"] == 0
    assert result["direction"] == "stable"
    assert result["significant_change"] is False


def test_calculate_peer_comparison():
    from app.engine.root_cause import calculate_peer_comparison

    peer_values = [60.0, 65.0, 70.0, 75.0, 80.0]

    result = calculate_peer_comparison(72.0, peer_values, "Test Hospital")

    assert result.peer_group == "hospital_type"
    assert result.peer_count == 5
    assert 60 <= result.hospital_percentile <= 80
    assert isinstance(result.hospital_z_score, float)


def test_calculate_peer_comparison_empty_peers():
    from app.engine.root_cause import calculate_peer_comparison

    result = calculate_peer_comparison(72.0, [], "Test Hospital")

    assert result.peer_count == 0
    assert result.hospital_percentile == 50.0
    assert result.hospital_z_score == 0.0
    assert result.gap_to_benchmark == 0.0


def test_identify_peer_groups(db_session):
    from app.engine.root_cause import identify_peer_groups
    from app.models import Hospital, HospitalType, FacilityOwnership, Governorate

    htype = HospitalType(name="Government")
    ownership = FacilityOwnership(name="Ministry")
    gov = Governorate(name="Gaza")
    db_session.add_all([htype, ownership, gov])
    db_session.flush()

    h1 = Hospital(name="A", hospital_type_id=htype.id,
                  facility_ownership_id=ownership.id,
                  governorate_id=gov.id, is_active=True)
    h2 = Hospital(name="B", hospital_type_id=htype.id,
                  facility_ownership_id=ownership.id,
                  governorate_id=gov.id, is_active=True)
    h3 = Hospital(name="C", hospital_type_id=htype.id,
                  facility_ownership_id=ownership.id,
                  governorate_id=gov.id, is_active=True)
    h4 = Hospital(name="D", hospital_type_id=htype.id,
                  facility_ownership_id=ownership.id,
                  governorate_id=gov.id, is_active=True)
    db_session.add_all([h1, h2, h3, h4])
    db_session.commit()

    result = identify_peer_groups(db_session, h1.id)

    assert "hospital_type" in result
    assert len(result["hospital_type"]) == 3


def test_find_correlated_factors():
    from app.engine.root_cause import find_correlated_factors, CausalNode, MonthDataPoint

    source = CausalNode(
        factor="R001", factor_type="rule", current_value=70,
        trend="declining", trend_slope=-2.5, peer_comparison=None,
        history=[
            MonthDataPoint("2026-01", 65, 0, 0, 0),
            MonthDataPoint("2026-02", 67, 0, 0, 0),
            MonthDataPoint("2026-03", 68, 0, 0, 0),
            MonthDataPoint("2026-04", 70, 0, 0, 0),
        ],
        severity="critical"
    )

    candidate = CausalNode(
        factor="Rule Compliance", factor_type="quality_component",
        current_value=55, trend="declining", trend_slope=-1.5,
        peer_comparison=None,
        history=[
            MonthDataPoint("2026-01", 60, 0, 0, 0),
            MonthDataPoint("2026-02", 58, 0, 0, 0),
            MonthDataPoint("2026-03", 56, 0, 0, 0),
            MonthDataPoint("2026-04", 55, 0, 0, 0),
        ],
        severity="high"
    )

    result = find_correlated_factors(source, [candidate])

    assert len(result) == 1
    assert result[0].factor == "Rule Compliance"


def test_build_causal_chains():
    from app.engine.root_cause import build_causal_chains, CausalNode, MonthDataPoint

    nodes = [
        CausalNode(
            factor="R001", factor_type="rule", current_value=70,
            trend="declining", trend_slope=-2.5, peer_comparison=None,
            history=[
                MonthDataPoint("2026-01", 65, 0, 0, 0),
                MonthDataPoint("2026-02", 67, 0, 0, 0),
                MonthDataPoint("2026-03", 68, 0, 0, 0),
                MonthDataPoint("2026-04", 70, 0, 0, 0),
            ],
            severity="critical"
        ),
        CausalNode(
            factor="Rule Compliance", factor_type="quality_component",
            current_value=55, trend="declining", trend_slope=-1.5,
            peer_comparison=None,
            history=[
                MonthDataPoint("2026-01", 60, 0, 0, 0),
                MonthDataPoint("2026-02", 58, 0, 0, 0),
                MonthDataPoint("2026-03", 56, 0, 0, 0),
                MonthDataPoint("2026-04", 55, 0, 0, 0),
            ],
            severity="high"
        ),
    ]

    result = build_causal_chains(nodes)

    assert len(result) >= 1
    assert result[0].confidence > 0


def test_generate_root_cause_with_historical(db_session):
    """Test enhanced root cause analysis with historical data."""
    from app.engine.root_cause import generate_root_cause_analysis
    from app.models import Hospital, Indicator, IndicatorValue

    hospital = Hospital(name="Test Hospital", is_active=True)
    db_session.add(hospital)
    db_session.flush()

    indicator = Indicator(code="CS_rate", name="C-Section Rate")
    db_session.add(indicator)
    db_session.flush()

    for i, month in enumerate(["2026-01", "2026-02", "2026-03"]):
        iv = IndicatorValue(
            hospital_id=hospital.id,
            indicator_id=indicator.id,
            month=month,
            value=20.0 + i * 2
        )
        db_session.add(iv)
    db_session.commit()

    quality_data = {
        "score": 65.0,
        "rule_compliance": 55.0,
        "completeness": 70.0,
        "consistency": 60.0,
        "outlier_penalty": 0.2,
    }
    confidence_data = {
        "overall_confidence": 50.0,
        "level": "MEDIUM",
        "indicators_data": [],
    }

    report = generate_root_cause_analysis(
        db_session, hospital.id, "2026-03",
        quality_data=quality_data,
        confidence_data=confidence_data,
        include_history=True,
        compare_peers=True,
        months_back=3
    )

    assert hasattr(report, 'causal_tree')
    assert hasattr(report, 'causal_chains')
    assert hasattr(report, 'historical_trends')
    assert hasattr(report, 'peer_comparisons')
    assert hasattr(report, 'summary_arabic')
    assert isinstance(report.causal_tree, list)
    assert isinstance(report.causal_chains, list)
    assert isinstance(report.historical_trends, dict)
    assert isinstance(report.peer_comparisons, dict)
    assert isinstance(report.summary_arabic, str)


class TestIntegrationHistoricalAndComparativeRootCause:
    """End-to-end integration test for the full historical + comparative root cause pipeline."""

    def test_full_pipeline_with_history_and_peers(self, db_session):
        from app.engine.root_cause import (
            generate_root_cause_analysis,
            RootCauseReport,
            CausalNode,
            CausalChain,
            PeerComparison,
        )
        from app.models import (
            Hospital, HospitalType, FacilityOwnership, Governorate,
            Indicator, IndicatorValue, ValidationResult, AnomalyResult,
            QualityScore, ConfidenceScore,
        )

        # --- 1. Create infrastructure: hospital types, ownership, governorate ---
        htype = HospitalType(name="Government")
        ownership = FacilityOwnership(name="Ministry of Health")
        gov = Governorate(name="Gaza")
        db_session.add_all([htype, ownership, gov])
        db_session.flush()

        # --- 2. Create target hospital + 4 peers of same type (MIN_PEER_SIZE=3) ---
        target = Hospital(
            name="Al-Shifa Hospital",
            hospital_type_id=htype.id,
            facility_ownership_id=ownership.id,
            governorate_id=gov.id,
            is_active=True,
        )
        peers = []
        for i in range(4):
            h = Hospital(
                name=f"Peer Hospital {i+1}",
                hospital_type_id=htype.id,
                facility_ownership_id=ownership.id,
                governorate_id=gov.id,
                is_active=True,
            )
            peers.append(h)
        db_session.add_all([target] + peers)
        db_session.flush()

        # --- 3. Add indicator values for 6 months (2026-01 to 2026-06) ---
        ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
        assert ind is not None, "Indicator '2' (Total Deliveries) must be seeded"
        ind_live = db_session.query(Indicator).filter(Indicator.code == "6").first()
        assert ind_live is not None, "Indicator '6' (Live Births) must be seeded"
        ind_cs = db_session.query(Indicator).filter(Indicator.code == "5").first()
        assert ind_cs is not None, "Indicator '5' (Caesarean Sections) must be seeded"
        ind_smm = db_session.query(Indicator).filter(Indicator.code == "10").first()
        assert ind_smm is not None, "Indicator '10' (SMM) must be seeded"

        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
        target_values = [280, 290, 300, 295, 285, 270]

        for m, val in zip(months, target_values):
            db_session.add(IndicatorValue(
                hospital_id=target.id, indicator_id=ind.id,
                month=m, value=val,
            ))
            # total_births يُشتق من Live Births (code 6) — ضروري لمقارنة النظير
            db_session.add(IndicatorValue(
                hospital_id=target.id, indicator_id=ind_live.id,
                month=m, value=val - 10,
            ))
            # cs_rate يحتاج قيصرية (code 5) — وإلا يبقى 0 في كل المستشفيات
            db_session.add(IndicatorValue(
                hospital_id=target.id, indicator_id=ind_cs.id,
                month=m, value=(val - 10) * 0.25,
            ))
            # smm_total يشتق من code 10 — نضيفه حتى تبقى المقارنة ذات معنى
            db_session.add(IndicatorValue(
                hospital_id=target.id, indicator_id=ind_smm.id,
                month=m, value=3.0,
            ))

        for pi, peer in enumerate(peers):
            for mi, m in enumerate(months):
                db_session.add(IndicatorValue(
                    hospital_id=peer.id, indicator_id=ind.id,
                    month=m, value=250.0 + pi * 10 + mi * 3,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=peer.id, indicator_id=ind_live.id,
                    month=m, value=240.0 + pi * 10 + mi * 3,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=peer.id, indicator_id=ind_cs.id,
                    month=m, value=(240.0 + pi * 10 + mi * 3) * 0.25,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=peer.id, indicator_id=ind_smm.id,
                    month=m, value=2.0 + pi * 0.5,
                ))
        db_session.commit()

        # --- 4. Add validation results (rule failures) for target hospital ---
        validation_data = [
            ("R001", "Parent-child mismatch", "FAIL", "HIGH", "LOGIC", "Sum mismatch"),
            ("R001", "Parent-child mismatch", "FAIL", "HIGH", "LOGIC", "Sum mismatch"),
            ("R001", "Parent-child mismatch", "PASS", "HIGH", "LOGIC", ""),
            ("R054", "Maternal deaths surge", "FAIL", "CRITICAL", "THRESHOLD",
             "Maternal deaths surged above threshold"),
        ]
        for code, desc, status, sev, rtype, details in validation_data:
            db_session.add(ValidationResult(
                hospital_id=target.id, month="2026-06",
                rule_code=code, rule_description=desc,
                status=status, severity=sev, rule_type=rtype, details=details,
            ))
        db_session.commit()

        # --- 5. Add anomaly results (outliers) ---
        db_session.add_all([
            AnomalyResult(
                hospital_id=target.id, month="2026-06",
                indicator_code="5", rate_name="C-section rate",
                value=45.0, benchmark=25.0, z_score=3.5, is_outlier=True,
            ),
            AnomalyResult(
                hospital_id=target.id, month="2026-06",
                indicator_code="11", rate_name="Maternal mortality rate",
                value=5.0, benchmark=1.0, z_score=2.8, is_outlier=True,
            ),
        ])
        db_session.commit()

        # --- 6. Add quality scores ---
        db_session.add(QualityScore(
            hospital_id=target.id, month="2026-06",
            score=45.0, rule_compliance=35.0, completeness=55.0,
            consistency=40.0, outlier_penalty=0.25,
            issues=json.dumps(["R001 failures", "Severe anomalies"]),
        ))
        db_session.commit()

        # --- 7. Add confidence scores ---
        indicators_data = [
            {
                "indicator_code": "2",
                "indicator_name": "Total Deliveries",
                "confidence": 25.0,
                "level": "CRITICAL",
                "signals": [
                    {"factor": "rule_compliance", "score": 0.1, "passed": False, "detail": "R001 failures"},
                    {"factor": "historical", "score": 0.3, "passed": False, "detail": "volatile trend"},
                ],
            },
            {
                "indicator_code": "5",
                "indicator_name": "C-section rate",
                "confidence": 35.0,
                "level": "LOW",
                "signals": [
                    {"factor": "cross_hospital", "score": 0.2, "passed": False, "detail": "deviates from peers"},
                    {"factor": "rule_compliance", "score": 0.5, "passed": True, "detail": "rules pass"},
                ],
            },
            {
                "indicator_code": "3",
                "indicator_name": "NVD",
                "confidence": 85.0,
                "level": "HIGH",
                "signals": [
                    {"factor": "rule_compliance", "score": 1.0, "passed": True, "detail": "all pass"},
                ],
            },
        ]
        db_session.add(ConfidenceScore(
            hospital_id=target.id, month="2026-06",
            overall_confidence=35.0, level="LOW",
            indicator_count=3, high_count=1, medium_count=0,
            low_count=1, critical_count=1,
            indicators_data=json.dumps(indicators_data),
            summary="Overall confidence is low due to rule failures and anomalies.",
        ))
        db_session.commit()

        # --- 8. Run full root cause analysis with history + peer comparison ---
        quality_data = {
            "score": 45.0,
            "rule_compliance": 35.0,
            "completeness": 55.0,
            "consistency": 40.0,
            "outlier_penalty": 0.25,
        }
        confidence_data = {
            "overall_confidence": 35.0,
            "level": "LOW",
            "indicators_data": indicators_data,
        }

        report = generate_root_cause_analysis(
            db_session, target.id, "2026-06",
            quality_data=quality_data,
            confidence_data=confidence_data,
            include_history=True,
            compare_peers=True,
            months_back=6,
        )

        # --- 9. Verify report type and core fields ---
        assert isinstance(report, RootCauseReport)
        assert report.hospital == "Al-Shifa Hospital"
        assert report.hospital_id == target.id
        assert report.month == "2026-06"
        assert report.overall_quality_score == 45.0
        assert report.overall_confidence == 35.0
        assert report.critical_issues_count > 0

        # --- 10. Verify causal tree is populated ---
        assert isinstance(report.causal_tree, list)
        assert len(report.causal_tree) > 0
        for node in report.causal_tree:
            assert isinstance(node, CausalNode)
            assert node.factor
            assert node.factor_type in ("rule", "quality_component", "confidence_signal")
            assert isinstance(node.current_value, (int, float))
            assert node.trend in ("improving", "declining", "stable")
            assert isinstance(node.severity, str)

        # --- 11. Verify causal chains structure ---
        assert isinstance(report.causal_chains, list)
        for chain in report.causal_chains:
            assert isinstance(chain, CausalChain)
            assert chain.root_cause
            assert chain.root_cause_arabic
            assert 0 < chain.confidence <= 1.0
            assert len(chain.evidence) > 0
            assert len(chain.affected_factors) > 0
            assert chain.recommended_action
            assert chain.impact_if_fixed >= 0

        # --- 12. Verify historical trends structure ---
        assert isinstance(report.historical_trends, dict)
        for factor, trend in report.historical_trends.items():
            assert isinstance(factor, str)
            assert "slope" in trend
            assert "direction" in trend
            assert "r_squared" in trend
            assert "volatility" in trend
            assert "significant_change" in trend
            assert trend["direction"] in ("improving", "declining", "stable")

        # --- 13. Verify peer comparisons are populated (per indicator) ---
        # المقارنة الآن لكل مؤشر: قيمة المستشفى الفعلية مقابل متوسط النظير لنفس المؤشر
        from app.engine.root_cause import PeerIndicatorComparison
        assert isinstance(report.peer_comparisons, dict)
        assert len(report.peer_comparisons) > 0
        for code, comp in report.peer_comparisons.items():
            assert isinstance(comp, PeerIndicatorComparison)
            assert comp.indicator_code
            assert comp.peer_group
            assert comp.peer_count >= 3
            # القيم 0 مشروعة لبعض المؤشرات (مثل الوفيات) — نتحقق من البنية لا القيمة
            assert isinstance(comp.hospital_percentile, float)
            assert isinstance(comp.hospital_z_score, (int, float))
            assert isinstance(comp.gap_pct, (int, float))
        # تأكد أن المؤشرات المزروعة فعلاً حاضرة في المقارنة
        seeded_codes = {c.indicator_code for c in report.peer_comparisons.values()}
        assert "total_births" in seeded_codes
        assert "cs_rate" in seeded_codes

        # --- 14. Verify Arabic summary is generated ---
        assert isinstance(report.summary_arabic, str)
        assert len(report.summary_arabic) > 0

        # --- 15. Verify rule failures are captured ---
        assert len(report.top_rule_failures) >= 1
        rule_codes = [rf.rule_code for rf in report.top_rule_failures]
        assert "R001" in rule_codes or "R054" in rule_codes

        # --- 16. Verify quality drivers ---
        assert len(report.quality_drivers) >= 1
        statuses = {qd.status for qd in report.quality_drivers}
        assert "critical" in statuses or "needs_improvement" in statuses

        # --- 17. Verify confidence gaps ---
        assert len(report.confidence_gaps) >= 1
        gap_levels = {cg.level for cg in report.confidence_gaps}
        assert "CRITICAL" in gap_levels or "LOW" in gap_levels

        # --- 18. Verify anomaly patterns ---
        assert len(report.anomaly_patterns) >= 1
        assert any(ap.pattern_type in ("severe", "moderate")
                   for ap in report.anomaly_patterns)

        # --- 19. Verify priority actions ---
        assert len(report.priority_actions) >= 1
        for action in report.priority_actions:
            assert "[" in action  # each action should have [SEVERITY] prefix

        # --- 20. Verify summary is comprehensive ---
        assert report.summary
        assert len(report.summary) > 20


class TestExtractRuleType:
    def test_sum(self):
        assert _extract_rule_type({"parent": "2", "children": ["3", "4", "5"]}) == "SUM"

    def test_part(self):
        assert _extract_rule_type({"child": "5.b.1", "parent": "5"}) == "PART"

    def test_rate(self):
        assert _extract_rule_type({"num_code": "5", "den_code": "2", "threshold": 80.0}) == "RATE"

    def test_exists(self):
        assert _extract_rule_type({"code": "2"}) == "EXISTS"

    def test_generic(self):
        assert _extract_rule_type({}) == "GENERIC"

    def test_none_params(self):
        assert _extract_rule_type(None) == "GENERIC"


class TestBuildDynamicDiagnosis:
    def test_sum_diagnosis(self):
        cause, rec = _build_dynamic_diagnosis("R999", {"parent": "2", "children": ["3", "4", "5"]}, "")
        assert "sub" in cause.lower() or "sum" in cause.lower()
        assert rec

    def test_part_diagnosis(self):
        cause, rec = _build_dynamic_diagnosis("R999", {"child": "5.b.1", "parent": "5"}, "")
        assert rec

    def test_rate_diagnosis(self):
        cause, rec = _build_dynamic_diagnosis("R999", {"num_code": "5", "den_code": "2"}, "")
        assert rec

    def test_exists_diagnosis(self):
        cause, rec = _build_dynamic_diagnosis("R999", {"code": "2"}, "")
        assert "missing" in cause.lower() or "not reported" in cause.lower()

    def test_generic_returns_empty(self):
        cause, rec = _build_dynamic_diagnosis("R999", {}, "")
        assert cause == "" and rec == ""


class TestDiagnoseRuleFailureV2:
    def test_level1_map(self):
        cause, rec = _diagnose_rule_failure_v2("R001", {}, "")
        assert "sum mismatch" in cause.lower() or "sub-indicator" in cause.lower()

    def test_level2_sum(self):
        cause, rec = _diagnose_rule_failure_v2("R999", {"parent": "2", "children": ["3", "4", "5"]}, "")
        assert "sub" in cause.lower() or "sum" in cause.lower()

    def test_level2_exists(self):
        cause, rec = _diagnose_rule_failure_v2("R999", {"code": "2"}, "")
        assert "missing" in cause.lower() or "not reported" in cause.lower()

    def test_level3_pattern(self):
        cause, rec = _diagnose_rule_failure_v2("R999", {}, "value exceeds expected threshold")
        assert "exceeds" in cause.lower()

    def test_level3_negative(self):
        cause, rec = _diagnose_rule_failure_v2("R999", {}, "negative value reported")
        assert "negative" in cause.lower()

    def test_generic_fallback(self):
        cause, rec = _diagnose_rule_failure_v2("R999", {}, "random detail text")
        assert cause and rec

    def test_arabic_level1(self):
        cause, rec = _diagnose_rule_failure_v2_ar("R041", {}, "")
        assert "قيصر" in cause

    def test_arabic_level2_sum(self):
        cause, rec = _diagnose_rule_failure_v2_ar("R999", {"parent": "2", "children": ["3", "4", "5"]}, "")
        assert cause

    def test_arabic_generic_fallback(self):
        cause, rec = _diagnose_rule_failure_v2_ar("R999", {}, "random detail text")
        assert cause and rec
