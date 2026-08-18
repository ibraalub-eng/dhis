def test_local_root_cause_fallback_enhanced():
    from app.plugins.ai.providers import _local_root_cause_fallback_enhanced

    report_data = {
        "overall_quality_score": 62.0,
        "overall_confidence": 45.0,
        "top_rule_failures": [
            {"rule_code": "R001", "severity": "CRITICAL", "failure_rate": 70}
        ],
        "confidence_gaps": [
            {"level": "LOW", "indicator_name": "CS_rate"}
        ],
        "anomaly_patterns": [
            {"pattern_type": "severe", "rate_name": "CS Rate"}
        ],
        "historical_trends": {
            "R001": {"direction": "declining", "slope": -2.5}
        },
        "peer_comparisons": {
            "cs_rate": {
                "indicator_code": "cs_rate", "indicator_name": "cs_rate",
                "gap_pct": 35.0, "hospital_z_score": 1.5,
            }
        },
    }

    result = _local_root_cause_fallback_enhanced(report_data)

    assert len(result) > 0
    assert any("Historical Decline" in r.category or "Peer Comparison" in r.category
               for r in result)
    # كل توصية ثنائية اللغة: حقول عربية حقيقية بجانب الإنجليزية
    for r in result:
        assert r.title and r.title_ar
        assert r.description and r.description_ar
        assert r.action_items and r.action_items_ar
    peer = [r for r in result if r.category == "Peer Comparison"]
    assert peer and "35" in peer[0].title_ar


def test_generate_root_cause_ai_uses_enhanced_prompt_with_historical_data():
    from app.plugins.ai import generate_root_cause_ai
    from app.plugins.ai.providers import _local_root_cause_fallback_enhanced

    report_data = {
        "hospital": "Test Hospital",
        "month": "2026-06",
        "overall_quality_score": 62.0,
        "overall_confidence": 45.0,
        "historical_trends": {
            "R001": {"direction": "declining", "slope": -2.5}
        },
        "peer_comparisons": {
            "cs_rate": {
                "indicator_code": "cs_rate", "indicator_name": "cs_rate",
                "gap_pct": 35.0, "hospital_z_score": 1.5,
            }
        },
    }

    result = generate_root_cause_ai(report_data)

    assert len(result) > 0
    assert any("Historical Decline" in r.category or "Peer Comparison" in r.category
               for r in result)


def test_generate_root_cause_ai_uses_basic_fallback_without_historical_data(monkeypatch):
    from app.plugins.ai import generate_root_cause_ai
    import app.plugins.ai as ai_module
    # تعطيل الذكاء الاصطناعي بشكل حتمي حتى يُختبر المسار الاحتياطي المحلي
    # (لا نعتمد على استجابة نموذج خارجي — الاستدعاء الفعلي يُغطى باختبارات أخرى)
    monkeypatch.setattr(ai_module, "AI_ENABLED", False)

    report_data = {
        "hospital": "Test Hospital",
        "month": "2026-06",
        "overall_quality_score": 62.0,
        "overall_confidence": 45.0,
        "top_rule_failures": [
            {"rule_code": "R001", "severity": "CRITICAL", "failure_rate": 70}
        ],
    }

    result = generate_root_cause_ai(report_data)

    assert len(result) > 0
    assert any("Data Validation" in r.category or "Data Quality" in r.category
               for r in result)
