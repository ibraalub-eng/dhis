def test_build_root_cause_prompt_enhanced():
    from app.plugins.ai.prompts import _build_root_cause_prompt_enhanced

    report_data = {
        "hospital": "Al-Shifa",
        "month": "2026-06",
        "overall_quality_score": 62.0,
        "overall_confidence": 45.0,
        "critical_issues_count": 2,
        "top_rule_failures": [
            {"rule_code": "R001", "severity": "CRITICAL", "failure_rate": 70,
             "description": "Sum mismatch", "primary_cause": "Data entry error"}
        ],
        "quality_drivers": [
            {"component": "Rule Compliance", "value": 55, "status": "critical"}
        ],
        "confidence_gaps": [
            {"indicator_name": "CS_rate", "level": "LOW", "confidence": 30}
        ],
        "anomaly_patterns": [
            {"rate_name": "CS Rate", "avg_z_score": 3.2, "pattern_type": "severe"}
        ],
        "historical_trends": {
            "R001": {"direction": "declining", "slope": -2.5, "significant_change": True}
        },
        "peer_comparisons": {
            "hospital_type": {
                "hospital_percentile": 12.5,
                "hospital_z_score": 2.1,
                "gap_to_benchmark": 35
            }
        },
        "causal_chains": [
            {
                "root_cause_arabic": "فشل R001 بنسبة 70%",
                "confidence": 0.85,
                "impact_if_fixed": 16.5
            }
        ],
    }

    prompt = _build_root_cause_prompt_enhanced(report_data)

    assert "Al-Shifa" in prompt
    assert "2026-06" in prompt
    assert "62.0" in prompt
    assert "historical" in prompt.lower() or "Historical" in prompt
    assert "peer" in prompt.lower() or "Peer" in prompt
    assert "causal" in prompt.lower() or "Causal" in prompt
