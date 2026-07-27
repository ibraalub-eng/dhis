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
            "hospital_type": {"hospital_percentile": 12.5}
        },
    }

    result = _local_root_cause_fallback_enhanced(report_data)

    assert len(result) > 0
    assert any("Historical Decline" in r.category or "Peer Comparison" in r.category
               for r in result)
