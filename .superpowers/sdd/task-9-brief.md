### Task 9: Enhance Local Fallback with Comparative Logic

**Files:**
- Modify: `app/plugins/ai/providers.py` (add enhanced fallback function)
- Test: `tests/test_ai_providers.py` (create)

**Interfaces:**
- Consumes: Report data with historical/comparative fields
- Produces: `_local_root_cause_fallback_enhanced()` function

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_providers.py (create new file)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_providers.py::test_local_root_cause_fallback_enhanced -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/plugins/ai/providers.py`:

```python
def _local_root_cause_fallback_enhanced(report_data: dict) -> List[AIRuleDef]:
    """
    Enhanced fallback that uses historical and comparative data
    even without AI.
    """
    recs = []
    
    # Check historical trends
    trends = report_data.get("historical_trends", {})
    for factor, trend_data in trends.items():
        if trend_data.get("direction") == "declining":
            slope = trend_data.get("slope", 0)
            if slope < -2:  # Rapidly declining
                recs.append(AIRuleDef(
                    category="Historical Decline",
                    priority="critical",
                    title=f"{factor} declining rapidly (slope={slope:.1f})",
                    description=f"{factor} has been declining at {abs(slope):.1f} points/month over the last 6 months.",
                    rationale="Rapid decline indicates systemic issue that will worsen without intervention.",
                    action_items=[
                        f"Investigate root cause of {factor} decline in the last 3 months",
                        "Compare with peer hospitals to identify unique factors",
                        "Implement corrective action within 2 weeks",
                        "Monitor weekly until trend reverses",
                    ],
                    indicators_monitored=[factor],
                ))
            elif slope < -1:  # Moderately declining
                recs.append(AIRuleDef(
                    category="Historical Decline",
                    priority="high",
                    title=f"{factor} showing gradual decline",
                    description=f"{factor} is declining at {abs(slope):.1f} points/month.",
                    rationale="Gradual decline may indicate process drift or training gaps.",
                    action_items=[
                        f"Review {factor} data entry procedures",
                        "Schedule refresher training for data entry staff",
                        "Set up monthly monitoring alerts",
                    ],
                    indicators_monitored=[factor],
                ))
    
    # Check peer comparisons
    comparisons = report_data.get("peer_comparisons", {})
    for group, comp_data in comparisons.items():
        percentile = comp_data.get("hospital_percentile", 100)
        z_score = comp_data.get("hospital_z_score", 0)
        
        if percentile < 25:
            recs.append(AIRuleDef(
                category="Peer Comparison",
                priority="high",
                title=f"Bottom {100-percentile:.0f}% compared to {group} peers",
                description=f"Hospital ranks in bottom {100-percentile:.0f}% compared to {group} peers (percentile={percentile:.0f}).",
                rationale="Consistently underperforming peers indicates structural issues that need addressing.",
                action_items=[
                    "Study best practices from benchmark hospitals",
                    "Identify process differences with top performers",
                    "Set improvement targets based on peer benchmarks",
                    "Schedule site visit to high-performing peer hospital",
                ],
                indicators_monitored=[],
            ))
        
        if abs(z_score) > 2:
            direction = "above" if z_score > 0 else "below"
            recs.append(AIRuleDef(
                category="Peer Comparison",
                priority="medium",
                title=f"Significant deviation from {group} mean",
                description=f"Hospital is {abs(z_score):.1f} standard deviations {direction} the {group} mean.",
                rationale="Large deviation from peers suggests unique factors affecting this hospital.",
                action_items=[
                    "Investigate what makes this hospital different from peers",
                    "Determine if deviation is positive (best practice) or negative (needs improvement)",
                    "Document and share any unique practices",
                ],
                indicators_monitored=[],
            ))
    
    # If no issues found, provide general recommendation
    if not recs:
        recs.append(AIRuleDef(
            category="Continuous Improvement",
            priority="low",
            title="Maintain Data Quality Standards",
            description="No critical historical or comparative issues detected. Continue regular monitoring.",
            rationale="Sustained data quality requires ongoing attention even when no immediate issues are present.",
            action_items=[
                "Continue monthly quality reviews",
                "Document best practices for data entry",
                "Schedule quarterly training refreshers",
            ],
            indicators_monitored=[],
        ))
    
    return recs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_providers.py::test_local_root_cause_fallback_enhanced -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/plugins/ai/providers.py tests/test_ai_providers.py
git commit -m "feat(ai): enhance local fallback with historical and comparative logic"
```
