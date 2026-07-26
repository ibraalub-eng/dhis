# Historical & Comparative Root Cause Analysis Design

**Date:** 2026-07-26
**Status:** Approved
**Author:** AI Assistant

---

## Overview

Enhance the existing root cause analysis system with historical trend analysis and comprehensive peer comparison capabilities. The goal is to help hospitals understand not just *what* went wrong, but *why* it went wrong by comparing their patterns against similar hospitals and tracking changes over time.

---

## Current State

### Existing Components (`app/engine/root_cause.py`)
- **Rule Failure Analysis**: Identifies failed validation rules with hardcoded cause map (15 rules)
- **Quality Driver Analysis**: 4-component weighted scoring (compliance, completeness, consistency, outlier)
- **Confidence Gap Analysis**: 5-signal confidence scoring with weakest signal identification
- **Anomaly Pattern Analysis**: Z-score based outlier detection

### Existing AI Integration (`app/plugins/ai/`)
- 3 providers: Gemini, OpenAI, MiniMax
- Local fallback with rule-based recommendations
- Prompt-based root cause analysis

### Limitations
1. Single-month snapshot only (no historical context)
2. No comparison with peer hospitals
3. Hardcoded rule causes (only 15 mapped)
4. No causal chain linking factors across time

---

## Design: Causal Tree Model

### Data Structures

```python
@dataclass
class MonthDataPoint:
    month: str
    value: float
    quality_score: float
    confidence: float
    rule_failure_rate: float

@dataclass
class PeerComparison:
    peer_group: str  # "hospital_type", "ownership", "regional"
    peer_count: int
    mean_value: float
    std_value: float
    hospital_percentile: float
    hospital_z_score: float
    benchmark_hospital: str
    benchmark_value: float
    gap_to_benchmark: float

@dataclass
class CausalNode:
    factor: str
    factor_type: str  # "rule", "quality_component", "confidence_signal", "indicator"
    current_value: float
    trend: str  # "improving", "declining", "stable"
    trend_slope: float
    peer_comparison: PeerComparison
    history: List[MonthDataPoint]
    severity: str  # "critical", "high", "medium", "low"

@dataclass
class CausalChain:
    root_cause: str
    root_cause_arabic: str
    confidence: float
    evidence: List[str]
    affected_factors: List[str]
    recommended_action: str
    impact_if_fixed: float
    implementation_priority: str

@dataclass
class HistoricalComparativeReport:
    hospital_id: int
    hospital_name: str
    current_month: str
    causal_tree: List[CausalNode]
    causal_chains: List[CausalChain]
    historical_trends: Dict[str, List[MonthDataPoint]]
    peer_comparisons: Dict[str, PeerComparison]
    summary_arabic: str
    priority_actions: List[str]
```

### Causal Chain Algorithm

```python
def build_causal_chains(nodes: List[CausalNode]) -> List[CausalChain]:
    """
    Build causal chains by linking related factors:
    
    Example chain:
    R001 fails (70%) → Rule Compliance low (55%) → Quality Score low (62) 
    → Confidence drops (40) → Anomaly detected (Z=3.2)
    
    Each link in the chain is validated by:
    1. Temporal correlation (did they change together?)
    2. Peer comparison (is this unique to this hospital?)
    3. Statistical significance (p-value < 0.05)
    """
    chains = []
    # Group factors by type
    rule_factors = [n for n in nodes if n.factor_type == "rule"]
    quality_factors = [n for n in nodes if n.factor_type == "quality_component"]
    confidence_factors = [n for n in nodes if n.factor_type == "confidence_signal"]
    
    # Find correlated declining factors
    for rule in rule_factors:
        if rule.severity in ("critical", "high"):
            # Find related quality components
            related_quality = find_correlated_factors(rule, quality_factors)
            related_confidence = find_correlated_factors(rule, confidence_factors)
            
            chain = CausalChain(
                root_cause=f"{rule.factor}: {rule.factor} failing at {rule.current_value}%",
                root_cause_arabic=f"فشل {rule.factor}: {rule.current_value}%",
                confidence=calculate_chain_confidence(rule, related_quality, related_confidence),
                evidence=build_evidence_list(rule, related_quality, related_confidence),
                affected_factors=[rule.factor] + [f.factor for f in related_quality + related_confidence],
                recommended_action=generate_chain_recommendation(rule, related_quality),
                impact_if_fixed=estimate_impact(rule, related_quality, related_confidence),
                implementation_priority=calculate_priority(rule, related_quality),
            )
            chains.append(chain)
    
    return sorted(chains, key=lambda c: c.confidence, reverse=True)
```

---

## Design: Historical Analysis

### Data Retrieval

```python
def get_historical_data(
    session: Session,
    hospital_id: int,
    months_back: int = 6
) -> Dict[str, List[MonthDataPoint]]:
    """
    Retrieve last N months of data for a hospital.
    
    Returns: {indicator_code: [MonthDataPoint, ...]}
    """
    # Query indicator_values + quality_scores + confidence_scores
    # for the last N months
    pass

def get_peer_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6
) -> Dict[str, List[MonthDataPoint]]:
    """
    Retrieve historical data for peer hospitals (same type).
    
    Returns: {peer_hospital_name: [MonthDataPoint, ...]}
    """
    # Identify peer group (same hospital_type_id)
    # Query their indicator values for the same period
    pass
```

### Trend Analysis

```python
def calculate_trend(history: List[MonthDataPoint]) -> Dict:
    """
    Calculate trend metrics for a factor over time.
    
    Returns:
    - slope: linear regression slope (positive = improving)
    - r_squared: how well the trend fits (0-1)
    - volatility: standard deviation of changes
    - direction: "improving" / "declining" / "stable"
    - significant_change: bool (p-value < 0.05)
    """
    values = [p.value for p in history]
    months = list(range(len(values)))
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(months, values)
    
    return {
        "slope": slope,
        "r_squared": r_value ** 2,
        "volatility": np.std(np.diff(values)),
        "direction": "improving" if slope > 0.1 else "declining" if slope < -0.1 else "stable",
        "significant_change": p_value < 0.05,
    }
```

### Comparative Metrics

```python
def calculate_peer_comparison(
    hospital_value: float,
    peer_values: List[float],
    hospital_name: str
) -> PeerComparison:
    """
    Calculate how hospital compares to peers.
    
    Metrics:
    - Percentile: rank among peers (0-100)
    - Z-score: standard deviations from mean
    - Gap to benchmark: difference from best performer
    """
    mean_val = np.mean(peer_values)
    std_val = np.std(peer_values) if len(peer_values) > 1 else 0
    
    percentile = stats.percentileofscore(peer_values, hospital_value)
    z_score = (hospital_value - mean_val) / std_val if std_val > 0 else 0
    
    best_idx = np.argmax(peer_values)
    benchmark_value = peer_values[best_idx]
    
    return PeerComparison(
        peer_group="hospital_type",
        peer_count=len(peer_values),
        mean_value=round(mean_val, 2),
        std_value=round(std_val, 2),
        hospital_percentile=round(percentile, 1),
        hospital_z_score=round(z_score, 2),
        benchmark_hospital=hospital_name,
        benchmark_value=round(benchmark_value, 2),
        gap_to_benchmark=round(benchmark_value - hospital_value, 2),
    )
```

---

## Design: Comparative Analysis

### Peer Group Identification

```python
def identify_peer_groups(session: Session, hospital_id: int) -> Dict[str, List[int]]:
    """
    Identify three peer groups:
    1. Same hospital_type_id (e.g., government hospitals)
    2. Same facility_ownership_id (e.g., Ministry of Health)
    3. Same governorate (regional average)
    
    Returns: {peer_group_name: [hospital_ids]}
    """
    hospital = session.query(Hospital).get(hospital_id)
    
    peers_by_type = session.query(Hospital.id).filter(
        Hospital.hospital_type_id == hospital.hospital_type_id,
        Hospital.id != hospital_id,
        Hospital.is_active == True
    ).all()
    
    peers_by_ownership = session.query(Hospital.id).filter(
        Hospital.facility_ownership_id == hospital.facility_ownership_id,
        Hospital.id != hospital_id,
        Hospital.is_active == True
    ).all()
    
    peers_by_region = session.query(Hospital.id).filter(
        Hospital.governorate_id == hospital.governorate_id,
        Hospital.id != hospital_id,
        Hospital.is_active == True
    ).all()
    
    return {
        "hospital_type": [p[0] for p in peers_by_type],
        "ownership": [p[0] for p in peers_by_ownership],
        "regional": [p[0] for p in peers_by_region],
    }
```

### Insight Generation

```python
def generate_comparative_insights(
    hospital_id: int,
    factor: str,
    hospital_value: float,
    comparisons: Dict[str, PeerComparison]
) -> List[str]:
    """
    Generate human-readable insights from comparisons.
    
    Examples:
    - "المستشفى يتأخر عن 62% من المستشفيات المشابهة في Rule Compliance"
    - "الفجوة largest في R001 مقارنة بالأقران (34 نقطة)"
    - "الاتجاه: يسوء منذ 3 أشهر بينما الأقران يتحسنون"
    """
    insights = []
    
    type_comp = comparisons.get("hospital_type")
    if type_comp and type_comp.hospital_percentile < 50:
        insights.append(
            f"المستشفى في المئوية {type_comp.hospital_percentile:.0f} "
            f"مقارنة بالمستشفيات المشابهة في النوع"
        )
    
    if type_comp and type_comp.gap_to_benchmark > 20:
        insights.append(
            f"الفجوة largest مقارنة بأفضل أداء ({type_comp.benchmark_hospital}) "
            f"بـ {type_comp.gap_to_benchmark:.0f} نقطة"
        )
    
    return insights
```

---

## API Changes

### Enhanced Root Cause Endpoint

**Current:** `GET /root-cause/{hospital_id}?month=YYYY-MM`

**Enhanced:** `GET /root-cause/{hospital_id}?month=YYYY-MM&include_history=true&compare_peers=true&months_back=6`

**New Response Fields:**
```json
{
  "hospital": "Al-Shifa",
  "month": "2026-06",
  "causal_tree": [
    {
      "factor": "R001",
      "factor_type": "rule",
      "current_value": 70,
      "trend": "declining",
      "trend_slope": -2.5,
      "peer_comparison": {
        "peer_group": "hospital_type",
        "peer_count": 7,
        "mean_value": 35,
        "hospital_percentile": 12.5,
        "hospital_z_score": 2.1,
        "gap_to_benchmark": 35
      },
      "history": [
        {"month": "2026-01", "value": 65},
        {"month": "2026-02", "value": 67},
        {"month": "2026-03", "value": 68},
        {"month": "2026-04", "value": 69},
        {"month": "2026-05", "value": 70},
        {"month": "2026-06", "value": 70}
      ],
      "severity": "critical"
    }
  ],
  "causal_chains": [
    {
      "root_cause": "R001 sum mismatch failing at 70%",
      "root_cause_arabic": "فشل التحقق من مطابقة المجموع في R001 بنسبة 70%",
      "confidence": 0.85,
      "evidence": [
        "R001 failure rate: 70% (peer average: 35%)",
        "Trend: declining over 6 months",
        "Correlated with Rule Compliance drop (55%)"
      ],
      "impact_if_fixed": 16.5,
      "recommended_action": "Train data entry staff on sub-indicator reporting"
    }
  ],
  "historical_trends": {
    "R001": {
      "slope": -2.5,
      "direction": "declining",
      "significant_change": true,
      "months_analyzed": 6
    }
  },
  "peer_comparisons": {
    "hospital_type": { ... },
    "ownership": { ... },
    "regional": { ... }
  },
  "summary_arabic": "المستشفى يعاني من تراجع مستمر في مطابقة البيانات الفرعية منذ 6 أشهر...",
  "priority_actions": [
    "[CRITICAL] R001: تدريب الموظفين على إدخال البيانات الفرعية",
    "[HIGH] Rule Compliance: مراجعة إجراءات التحقق قبل التسليم"
  ]
}
```

---

## AI Enhancement

### Enhanced Root Cause Prompt

Add to `_build_root_cause_prompt` in `app/plugins/ai/prompts.py`:

```python
def _build_root_cause_prompt_enhanced(report_data: dict) -> str:
    lines = []
    lines.append("You are a maternal health data quality expert analyzing ROOT CAUSES with HISTORICAL and COMPARATIVE context.")
    lines.append("")
    lines.append("## Current Analysis")
    lines.append(f"Hospital: {report_data.get('hospital', 'Unknown')}")
    lines.append(f"Month: {report_data.get('month', 'Unknown')}")
    lines.append(f"Quality Score: {report_data.get('overall_quality_score', 'N/A')}")
    lines.append(f"Confidence: {report_data.get('overall_confidence', 'N/A')}")
    lines.append("")
    
    # Add historical trends
    if report_data.get("historical_trends"):
        lines.append("## Historical Trends (Last 6 Months)")
        for factor, trend in report_data["historical_trends"].items():
            lines.append(f"  {factor}: {trend.get('direction', 'unknown')} "
                        f"(slope={trend.get('slope', 0):.2f})")
        lines.append("")
    
    # Add peer comparisons
    if report_data.get("peer_comparisons"):
        lines.append("## Peer Comparisons")
        for group, comp in report_data["peer_comparisons"].items():
            lines.append(f"  {group}: percentile={comp.get('hospital_percentile', 0)}, "
                        f"z-score={comp.get('hospital_z_score', 0)}")
        lines.append("")
    
    # Add causal chains
    if report_data.get("causal_chains"):
        lines.append("## Causal Chains Detected")
        for chain in report_data["causal_chains"]:
            lines.append(f"  Root Cause: {chain.get('root_cause_arabic', '')}")
            lines.append(f"  Confidence: {chain.get('confidence', 0)}")
            lines.append(f"  Impact if fixed: {chain.get('impact_if_fixed', 0)} points")
        lines.append("")
    
    lines.append("""Based on the historical trends and peer comparisons above, provide:
1. Root cause analysis with historical context
2. Why this hospital differs from peers
3. Specific actionable recommendations with timelines
4. Expected impact if recommendations are implemented

Return JSON array of recommendation objects with fields:
- category, priority, title, description, rationale
- action_items (with specific timelines)
- affected_indicators
- expected_impact (numeric improvement estimate)
- implementation_timeline (e.g., "1-2 weeks", "1 month")""")
    
    return "\n".join(lines)
```

---

## Local Fallback Enhancement

Update `_local_root_cause_fallback` in `app/plugins/ai/providers.py` to include:

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
                    title=f"{factor} declining rapidly",
                    description=f"{factor} has been declining at {abs(slope):.1f} points/month",
                    rationale="Rapid decline indicates systemic issue that will worsen without intervention",
                    action_items=[
                        f"Investigate root cause of {factor} decline",
                        "Compare with peer hospitals to identify unique factors",
                        "Implement corrective action within 2 weeks",
                    ],
                    indicators_monitored=[factor],
                ))
    
    # Check peer comparisons
    comparisons = report_data.get("peer_comparisons", {})
    for group, comp_data in comparisons.items():
        if comp_data.get("hospital_percentile", 100) < 25:
            recs.append(AIRuleDef(
                category="Peer Comparison",
                priority="high",
                title=f"Below 25th percentile in {group}",
                description=f"Hospital ranks in bottom 25% compared to {group} peers",
                rationale="Consistently underperforming peers indicates structural issues",
                action_items=[
                    "Study best practices from benchmark hospitals",
                    "Identify process differences with top performers",
                    "Set improvement targets based on peer benchmarks",
                ],
                indicators_monitored=[],
            ))
    
    return recs
```

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `app/engine/root_cause.py` | **Extend** | Add CausalNode, CausalChain, historical/peer analysis functions |
| `app/engine/root_cause.py` | **Extend** | Enhance `generate_root_cause_analysis` to return new fields |
| `app/api/root_cause.py` | **Extend** | Add query params for history/peer comparison |
| `app/plugins/ai/prompts.py` | **Extend** | Add enhanced root cause prompt with historical context |
| `app/plugins/ai/providers.py` | **Extend** | Enhance local fallback with historical/comparative logic |
| `app/plugins/ai/__init__.py` | **Extend** | Pass new data to AI provider |
| `tests/test_root_cause.py` | **Extend** | Add tests for new functionality |

---

## Testing Strategy

1. **Unit Tests**: Test each new function in isolation
   - `test_causal_chain_building()`
   - `test_historical_trend_calculation()`
   - `test_peer_comparison_percentile()`
   - `test_peer_comparison_z_score()`

2. **Integration Tests**: Test API endpoint with mock data
   - `test_root_cause_with_history()`
   - `test_root_cause_with_peers()`
   - `test_root_cause_full_comparative()`

3. **Edge Cases**:
   - Hospital with no historical data
   - Hospital with no peers (only one of its type)
   - Hospital with all indicators at same level as peers
   - Rapidly improving vs rapidly declining trends

---

## Implementation Order

1. **Phase 1** (Core): Add data structures + historical data retrieval
2. **Phase 2** (Comparison): Add peer group identification + comparison metrics
3. **Phase 3** (Causal): Build causal chain algorithm
4. **Phase 4** (API): Extend endpoint with new parameters
5. **Phase 5** (AI): Enhance prompts and local fallback
6. **Phase 6** (Tests): Add comprehensive test coverage

---

## Success Criteria

- [ ] Historical data retrieved for last 6 months
- [ ] Peer comparisons calculated for 3 groups
- [ ] Causal chains identified with confidence scores
- [ ] API returns new fields when requested
- [ ] AI enhanced with historical context
- [ ] Local fallback enhanced with comparative logic
- [ ] All tests passing
- [ ] No regression in existing functionality
