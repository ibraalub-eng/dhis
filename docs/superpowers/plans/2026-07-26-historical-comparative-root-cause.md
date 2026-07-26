# Historical & Comparative Root Cause Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance root cause analysis with historical trend tracking and comprehensive peer comparison capabilities.

**Architecture:** Extend existing `root_cause.py` engine with new data structures for causal chains, historical data retrieval, and peer comparison metrics. Add API parameters for controlling new features. Enhance AI prompts and local fallback with historical/comparative context.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, scipy (stats), numpy, existing AI plugin infrastructure

## Global Constraints

- Python 3.14 target
- SQLAlchemy ORM with existing database models
- Must maintain backward compatibility with existing API
- No new external dependencies (scipy/numpy already in requirements.txt)
- Arabic text support for root cause descriptions
- All new functions must have docstrings

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/engine/root_cause.py` | Extend | Add CausalNode, CausalChain, MonthDataPoint, PeerComparison dataclasses; add historical/peer analysis functions |
| `app/api/root_cause.py` | Extend | Add query params for history/peer comparison; return new fields |
| `app/plugins/ai/prompts.py` | Extend | Add enhanced root cause prompt with historical context |
| `app/plugins/ai/providers.py` | Extend | Enhance local fallback with historical/comparative logic |
| `app/plugins/ai/__init__.py` | Extend | Pass new data to AI provider |
| `tests/test_root_cause.py` | Extend | Add tests for new functionality |

---

### Task 1: Add Data Structures for Historical & Comparative Analysis

**Files:**
- Modify: `app/engine/root_cause.py:1-80` (add new dataclasses after existing ones)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: None (new standalone data structures)
- Produces: `MonthDataPoint`, `PeerComparison`, `CausalNode`, `CausalChain`, `HistoricalComparativeReport` dataclasses

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_month_data_point_creation -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/engine/root_cause.py` after line 78 (after `AnomalyPattern` dataclass):

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
    peer_group: str
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
    factor_type: str
    current_value: float
    trend: str
    trend_slope: float
    peer_comparison: Optional[PeerComparison]
    history: List[MonthDataPoint]
    severity: str


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
    historical_trends: Dict[str, Dict]
    peer_comparisons: Dict[str, PeerComparison]
    summary_arabic: str
    priority_actions: List[str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_month_data_point_creation tests/test_root_cause.py::test_peer_comparison_creation tests/test_root_cause.py::test_causal_node_creation tests/test_root_cause.py::test_causal_chain_creation -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): add data structures for historical and comparative analysis"
```

---

### Task 2: Implement Historical Data Retrieval

**Files:**
- Modify: `app/engine/root_cause.py` (add functions after data structures)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: `MonthDataPoint` dataclass from Task 1, existing database models
- Produces: `get_historical_data()`, `get_peer_historical_data()` functions

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

def test_get_historical_data(db_session):
    """Test historical data retrieval for a hospital."""
    from app.engine.root_cause import get_historical_data, MonthDataPoint
    
    # Create test data
    from app.models import Hospital, IndicatorValue
    from datetime import datetime
    
    hospital = Hospital(name="Test Hospital", is_active=True)
    db_session.add(hospital)
    db_session.flush()
    
    # Add 3 months of indicator data
    for i, month in enumerate(["2026-01", "2026-02", "2026-03"]):
        iv = IndicatorValue(
            hospital_id=hospital.id,
            indicator_code="CS_rate",
            month=month,
            value=20.0 + i * 2
        )
        db_session.add(iv)
    db_session.commit()
    
    result = get_historical_data(db_session, hospital.id, "CS_rate", months_back=3)
    
    assert len(result) == 3
    assert isinstance(result[0], MonthDataPoint)
    assert result[0].month == "2026-01"
    assert result[2].month == "2026-03"

def test_get_peer_historical_data(db_session):
    """Test peer historical data retrieval."""
    from app.engine.root_cause import get_peer_historical_data
    from app.models import Hospital, HospitalType, IndicatorValue
    
    # Create hospital type
    htype = HospitalType(name="Government")
    db_session.add(htype)
    db_session.flush()
    
    # Create hospitals
    h1 = Hospital(name="Hospital A", hospital_type_id=htype.id, is_active=True)
    h2 = Hospital(name="Hospital B", hospital_type_id=htype.id, is_active=True)
    h3 = Hospital(name="Hospital C", hospital_type_id=htype.id, is_active=True)
    db_session.add_all([h1, h2, h3])
    db_session.flush()
    
    # Add indicator data for all
    for h in [h1, h2, h3]:
        iv = IndicatorValue(
            hospital_id=h.id,
            indicator_code="CS_rate",
            month="2026-01",
            value=20.0
        )
        db_session.add(iv)
    db_session.commit()
    
    result = get_peer_historical_data(db_session, h1.id, "CS_rate", months_back=1)
    
    assert len(result) == 2  # h2 and h3 (not h1 itself)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_get_historical_data -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/engine/root_cause.py` after the data structures:

```python
def get_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6
) -> List[MonthDataPoint]:
    """
    Retrieve historical data for a specific indicator at a hospital.
    
    Returns list of MonthDataPoint objects for the last N months.
    """
    result = session.execute(text("""
        SELECT iv.month, iv.value,
               COALESCE(qs.score, 0) as quality_score,
               COALESCE(cs.overall_confidence, 0) as confidence,
               COALESCE(
                   (SELECT COUNT(*) FROM validation_results vr
                    WHERE vr.hospital_id = iv.hospital_id
                    AND vr.month = iv.month AND vr.status = 'FAIL') * 100.0 /
                   NULLIF((SELECT COUNT(*) FROM validation_results vr2
                           WHERE vr2.hospital_id = iv.hospital_id
                           AND vr2.month = iv.month), 0),
                   0) as rule_failure_rate
        FROM indicator_values iv
        LEFT JOIN quality_scores qs ON iv.hospital_id = qs.hospital_id
            AND iv.month = qs.month
        LEFT JOIN confidence_scores cs ON iv.hospital_id = cs.hospital_id
            AND iv.month = cs.month
        WHERE iv.hospital_id = :hid
        AND iv.indicator_code = :code
        AND iv.month >= date('now', :offset)
        ORDER BY iv.month ASC
    """), {"hid": hospital_id, "code": indicator_code, "offset": f"-{months_back} months"})
    
    history = []
    for row in result:
        history.append(MonthDataPoint(
            month=row[0],
            value=float(row[1] or 0),
            quality_score=float(row[2] or 0),
            confidence=float(row[3] or 0),
            rule_failure_rate=float(row[4] or 0),
        ))
    return history


def get_peer_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6
) -> Dict[str, List[MonthDataPoint]]:
    """
    Retrieve historical data for peer hospitals (same type).
    
    Returns dict of {hospital_name: [MonthDataPoint, ...]}
    """
    # Get hospital's type
    hospital = session.execute(text("""
        SELECT hospital_type_id FROM hospitals WHERE id = :hid
    """), {"hid": hospital_id}).fetchone()
    
    if not hospital or not hospital[0]:
        return {}
    
    # Get peer hospitals
    peers = session.execute(text("""
        SELECT id, name FROM hospitals
        WHERE hospital_type_id = :htid
        AND id != :hid
        AND is_active = 1
    """), {"htid": hospital[0], "hid": hospital_id})
    
    peer_data = {}
    for peer in peers:
        history = get_historical_data(session, peer[0], indicator_code, months_back)
        if history:
            peer_data[peer[1]] = history
    
    return peer_data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_get_historical_data tests/test_root_cause.py::test_get_peer_historical_data -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): add historical data retrieval functions"
```

---

### Task 3: Implement Trend Analysis

**Files:**
- Modify: `app/engine/root_cause.py` (add after historical data functions)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: `MonthDataPoint` from Task 1
- Produces: `calculate_trend()` function returning trend metrics

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

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
    assert result["r_squared"] > 0.9  # Strong linear trend

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_calculate_trend_declining -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/engine/root_cause.py`:

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
    from scipy import stats
    import numpy as np
    
    if len(history) < 2:
        return {
            "slope": 0,
            "r_squared": 0,
            "volatility": 0,
            "direction": "stable",
            "significant_change": False,
        }
    
    values = [p.value for p in history]
    months = list(range(len(values)))
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(months, values)
    
    # Calculate volatility (std of month-to-month changes)
    changes = np.diff(values)
    volatility = float(np.std(changes)) if len(changes) > 0 else 0
    
    # Determine direction
    if slope > 0.5:
        direction = "improving"
    elif slope < -0.5:
        direction = "declining"
    else:
        direction = "stable"
    
    return {
        "slope": round(slope, 2),
        "r_squared": round(r_value ** 2, 3),
        "volatility": round(volatility, 2),
        "direction": direction,
        "significant_change": p_value < 0.05,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_calculate_trend_declining tests/test_root_cause.py::test_calculate_trend_stable -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): add trend analysis with linear regression"
```

---

### Task 4: Implement Peer Comparison Metrics

**Files:**
- Modify: `app/engine/root_cause.py` (add after trend analysis)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: `PeerComparison` dataclass from Task 1
- Produces: `calculate_peer_comparison()`, `identify_peer_groups()` functions

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

def test_calculate_peer_comparison():
    from app.engine.root_cause import calculate_peer_comparison
    
    peer_values = [60.0, 65.0, 70.0, 75.0, 80.0]
    
    result = calculate_peer_comparison(72.0, peer_values, "Test Hospital")
    
    assert result.peer_group == "hospital_type"
    assert result.peer_count == 5
    assert 60 <= result.hospital_percentile <= 80
    assert isinstance(result.hospital_z_score, float)

def test_identify_peer_groups(db_session):
    from app.engine.root_cause import identify_peer_groups
    from app.models import Hospital, HospitalType, FacilityOwnership, Governorate
    
    # Create test data
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
    db_session.add_all([h1, h2, h3])
    db_session.commit()
    
    result = identify_peer_groups(db_session, h1.id)
    
    assert "hospital_type" in result
    assert len(result["hospital_type"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_calculate_peer_comparison -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/engine/root_cause.py`:

```python
MIN_PEER_SIZE = 3

def identify_peer_groups(session: Session, hospital_id: int) -> Dict[str, List[int]]:
    """
    Identify three peer groups:
    1. Same hospital_type_id (e.g., government hospitals)
    2. Same facility_ownership_id (e.g., Ministry of Health)
    3. Same governorate (regional average)
    
    Returns: {peer_group_name: [hospital_ids]}
    If a peer group has fewer than MIN_PEER_SIZE members, it is excluded.
    """
    hospital = session.execute(text("""
        SELECT hospital_type_id, facility_ownership_id, governorate_id
        FROM hospitals WHERE id = :hid
    """), {"hid": hospital_id}).fetchone()
    
    if not hospital:
        return {}
    
    result = {}
    
    # Peers by type
    if hospital[0]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE hospital_type_id = :htid
            AND id != :hid
            AND is_active = 1
        """), {"htid": hospital[0], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["hospital_type"] = peer_ids
    
    # Peers by ownership
    if hospital[1]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE facility_ownership_id = :foid
            AND id != :hid
            AND is_active = 1
        """), {"foid": hospital[1], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["ownership"] = peer_ids
    
    # Peers by region
    if hospital[2]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE governorate_id = :gid
            AND id != :hid
            AND is_active = 1
        """), {"gid": hospital[2], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["regional"] = peer_ids
    
    return result


def calculate_peer_comparison(
    hospital_value: float,
    peer_values: List[float],
    hospital_name: str = "Hospital"
) -> PeerComparison:
    """
    Calculate how hospital compares to peers.
    
    Metrics:
    - Percentile: rank among peers (0-100)
    - Z-score: standard deviations from mean
    - Gap to benchmark: difference from best performer
    """
    import numpy as np
    from scipy import stats as sp_stats
    
    if not peer_values:
        return PeerComparison(
            peer_group="hospital_type",
            peer_count=0,
            mean_value=0,
            std_value=0,
            hospital_percentile=50.0,
            hospital_z_score=0.0,
            benchmark_hospital=hospital_name,
            benchmark_value=hospital_value,
            gap_to_benchmark=0.0,
        )
    
    mean_val = float(np.mean(peer_values))
    std_val = float(np.std(peer_values)) if len(peer_values) > 1 else 0
    
    percentile = float(sp_stats.percentileofscore(peer_values, hospital_value))
    z_score = (hospital_value - mean_val) / std_val if std_val > 0 else 0
    
    best_value = max(peer_values)
    
    return PeerComparison(
        peer_group="hospital_type",
        peer_count=len(peer_values),
        mean_value=round(mean_val, 2),
        std_value=round(std_val, 2),
        hospital_percentile=round(percentile, 1),
        hospital_z_score=round(z_score, 2),
        benchmark_hospital=hospital_name,
        benchmark_value=round(best_value, 2),
        gap_to_benchmark=round(best_value - hospital_value, 2),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_calculate_peer_comparison tests/test_root_cause.py::test_identify_peer_groups -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): add peer comparison metrics and group identification"
```

---

### Task 5: Implement Causal Chain Builder

**Files:**
- Modify: `app/engine/root_cause.py` (add after peer comparison)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: `CausalNode`, `CausalChain` from Task 1, `calculate_trend` from Task 3
- Produces: `build_causal_chains()`, `find_correlated_factors()` functions

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_find_correlated_factors -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/engine/root_cause.py`:

```python
def find_correlated_factors(source: CausalNode, candidates: List[CausalNode]) -> List[CausalNode]:
    """
    Find factors that are correlated with source factor.
    
    Correlation criteria:
    1. Pearson correlation > 0.6 (strong positive correlation)
    2. Both trending in same direction
    3. Temporal lag < 1 month (changes happen together)
    
    Returns factors that meet all criteria, sorted by correlation strength.
    """
    from scipy import stats
    import numpy as np
    
    correlated = []
    source_values = [h.value for h in source.history]
    
    for candidate in candidates:
        candidate_values = [h.value for h in candidate.history]
        
        # Pad to same length if needed
        min_len = min(len(source_values), len(candidate_values))
        if min_len < 3:
            continue
            
        s = source_values[:min_len]
        c = candidate_values[:min_len]
        
        # Calculate Pearson correlation
        corr, p_value = stats.pearsonr(s, c)
        
        if corr > 0.6 and p_value < 0.05:
            correlated.append((candidate, corr))
    
    return [c for c, _ in sorted(correlated, key=lambda x: x[1], reverse=True)]


def build_causal_chains(nodes: List[CausalNode]) -> List[CausalChain]:
    """
    Build causal chains by linking related factors.
    
    Example chain:
    R001 fails (70%) → Rule Compliance low (55%) → Quality Score low (62)
    → Confidence drops (40) → Anomaly detected (Z=3.2)
    """
    rule_factors = [n for n in nodes if n.factor_type == "rule"]
    quality_factors = [n for n in nodes if n.factor_type == "quality_component"]
    confidence_factors = [n for n in nodes if n.factor_type == "confidence_signal"]
    
    chains = []
    
    for rule in rule_factors:
        if rule.severity in ("critical", "high"):
            related_quality = find_correlated_factors(rule, quality_factors)
            related_confidence = find_correlated_factors(rule, confidence_factors)
            
            # Build evidence list
            evidence = [
                f"{rule.factor} failure rate: {rule.current_value}%",
                f"Trend: {rule.trend} over {len(rule.history)} months",
            ]
            if related_quality:
                evidence.append(f"Correlated with {related_quality[0].factor} ({related_quality[0].current_value}%)")
            
            # Estimate impact
            impact = 0
            if related_quality:
                impact += abs(rule.current_value - 50) * 0.2
                impact += abs(related_quality[0].current_value - 80) * 0.15
            else:
                impact += abs(rule.current_value - 50) * 0.3
            
            chain = CausalChain(
                root_cause=f"{rule.factor}: {rule.factor} failing at {rule.current_value}%",
                root_cause_arabic=f"فشل {rule.factor}: {rule.current_value}%",
                confidence=min(0.9, 0.5 + len(related_quality) * 0.15),
                evidence=evidence,
                affected_factors=[rule.factor] + [f.factor for f in related_quality + related_confidence],
                recommended_action=f"Investigate and fix {rule.factor} root cause",
                impact_if_fixed=round(impact, 1),
                implementation_priority=rule.severity,
            )
            chains.append(chain)
    
    return sorted(chains, key=lambda c: c.confidence, reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_find_correlated_factors tests/test_root_cause.py::test_build_causal_chains -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): add causal chain builder with correlation analysis"
```

---

### Task 6: Integrate Historical & Comparative Analysis into Main Function

**Files:**
- Modify: `app/engine/root_cause.py` (modify `generate_root_cause_analysis` function)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: All functions from Tasks 2-5
- Produces: Enhanced `generate_root_cause_analysis()` returning `HistoricalComparativeReport`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

def test_generate_root_cause_with_historical(db_session):
    """Test enhanced root cause analysis with historical data."""
    from app.engine.root_cause import generate_root_cause_analysis
    from app.models import Hospital, IndicatorValue
    
    # Create test hospital
    hospital = Hospital(name="Test Hospital", is_active=True)
    db_session.add(hospital)
    db_session.flush()
    
    # Add historical data
    for i, month in enumerate(["2026-01", "2026-02", "2026-03"]):
        iv = IndicatorValue(
            hospital_id=hospital.id,
            indicator_code="CS_rate",
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
    
    # Check new fields exist
    assert hasattr(report, 'causal_tree')
    assert hasattr(report, 'causal_chains')
    assert hasattr(report, 'historical_trends')
    assert hasattr(report, 'peer_comparisons')
    assert hasattr(report, 'summary_arabic')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_generate_root_cause_with_historical -v`
Expected: FAIL with TypeError (unexpected keyword arguments)

- [ ] **Step 3: Write minimal implementation**

Modify `generate_root_cause_analysis` in `app/engine/root_cause.py`:

```python
def generate_root_cause_analysis(
    session: Session,
    hospital_id: int,
    month: str,
    quality_data: Optional[Dict] = None,
    confidence_data: Optional[Dict] = None,
    include_history: bool = False,
    compare_peers: bool = False,
    months_back: int = 6,
) -> RootCauseReport:
    """
    Generate comprehensive root cause analysis.
    
    Enhanced with optional historical and comparative analysis.
    """
    hospital = session.execute(
        text("SELECT name FROM hospitals WHERE id = :hid"),
        {"hid": hospital_id}
    ).fetchone()
    hospital_name = hospital[0] if hospital else f"Hospital {hospital_id}"

    rule_failures = analyze_rule_failures(session, hospital_id, month)
    quality_drivers = analyze_quality_drivers(quality_data)
    confidence_gaps = analyze_confidence_gaps(session, hospital_id, month)
    anomaly_patterns = analyze_anomaly_patterns(session, hospital_id, month)

    overall_quality = quality_data.get("score", 0) if quality_data else 0
    overall_confidence = confidence_data.get("overall_confidence", 0) if confidence_data else 0

    critical_count = len([f for f in rule_failures if f.severity == "CRITICAL"])
    critical_count += len([g for g in confidence_gaps if g.level == "CRITICAL"])

    # Build causal nodes for chain analysis
    causal_nodes = []
    for rf in rule_failures:
        history = []
        if include_history:
            history = get_historical_data(session, hospital_id, rf.rule_code, months_back)
        
        causal_nodes.append(CausalNode(
            factor=rf.rule_code,
            factor_type="rule",
            current_value=rf.failure_rate,
            trend=calculate_trend(history)["direction"] if history else "stable",
            trend_slope=calculate_trend(history)["slope"] if history else 0,
            peer_comparison=None,
            history=history,
            severity=rf.severity,
        ))
    
    for qd in quality_drivers:
        causal_nodes.append(CausalNode(
            factor=qd.component,
            factor_type="quality_component",
            current_value=qd.value,
            trend="stable",
            trend_slope=0,
            peer_comparison=None,
            history=[],
            severity="critical" if qd.status == "critical" else "high" if qd.status == "needs_improvement" else "low",
        ))
    
    # Build causal chains
    causal_chains = build_causal_chains(causal_nodes)
    
    # Peer comparisons
    peer_comparisons = {}
    if compare_peers:
        peer_groups = identify_peer_groups(session, hospital_id)
        for group_name, peer_ids in peer_groups.items():
            peer_values = []
            for pid in peer_ids:
                iv = session.execute(text("""
                    SELECT value FROM indicator_values
                    WHERE hospital_id = :pid AND month = :mth
                    LIMIT 1
                """), {"pid": pid, "mth": month}).fetchone()
                if iv:
                    peer_values.append(float(iv[0]))
            if peer_values:
                peer_comparisons[group_name] = calculate_peer_comparison(
                    overall_quality, peer_values, hospital_name
                )
    
    # Historical trends
    historical_trends = {}
    if include_history:
        for node in causal_nodes:
            if node.history:
                historical_trends[node.factor] = calculate_trend(node.history)
    
    # Generate summary
    summary_parts = []
    if causal_chains:
        top_chain = causal_chains[0]
        summary_parts.append(
            f"السبب الجذري الرئيسي: {top_chain.root_cause_arabic} "
            f"(ثقة: {top_chain.confidence:.0%})"
        )
    if rule_failures:
        top_failure = rule_failures[0]
        summary_parts.append(
            f"المشكلة primary: {top_failure.rule_code} "
            f"بمعدل فشل {top_failure.failure_rate:.0f}%"
        )
    if not summary_parts:
        summary_parts.append("لا توجد مشاكل حرجة محددة")
    
    summary = " | ".join(summary_parts)
    
    # Generate Arabic summary
    summary_arabic = _generate_arabic_summary(
        causal_chains, rule_failures, quality_drivers,
        confidence_gaps, anomaly_patterns, peer_comparisons
    )
    
    # Priority actions
    priority_actions = []
    for chain in causal_chains[:3]:
        priority_actions.append(
            f"[{chain.implementation_priority.upper()}] "
            f"{chain.root_cause_arabic}: {chain.recommended_action}"
        )
    
    return RootCauseReport(
        hospital=hospital_name,
        hospital_id=hospital_id,
        month=month,
        overall_quality_score=round(overall_quality, 1),
        overall_confidence=round(overall_confidence, 1),
        critical_issues_count=critical_count,
        top_rule_failures=rule_failures,
        quality_drivers=quality_drivers,
        confidence_gaps=confidence_gaps,
        anomaly_patterns=anomaly_patterns,
        summary=summary[:300],
        priority_actions=priority_actions[:8],
        ai_recommendations=[],  # Will be populated by AI layer
        causal_tree=causal_nodes,
        causal_chains=causal_chains,
        historical_trends=historical_trends,
        peer_comparisons=peer_comparisons,
        summary_arabic=summary_arabic,
    )


def _generate_arabic_summary(
    causal_chains, rule_failures, quality_drivers,
    confidence_gaps, anomaly_patterns, peer_comparisons
) -> str:
    """Generate Arabic narrative summary of root cause analysis."""
    parts = []
    
    if causal_chains:
        top = causal_chains[0]
        parts.append(f"السبب الجذري الرئيسي: {top.root_cause_arabic}")
    
    if peer_comparisons:
        for group, comp in peer_comparisons.items():
            if comp.hospital_percentile < 50:
                parts.append(
                    f"مقارنة ب {group}: المستشفى في المئوية {comp.hospital_percentile:.0f}"
                )
    
    if rule_failures:
        critical = [r for r in rule_failures if r.severity == "CRITICAL"]
        if critical:
            parts.append(f"يوجد {len(critical)} مشاكل حرجة في قواعد التحقق")
    
    return ". ".join(parts) if parts else "لا توجد مشاكل حرجة"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_generate_root_cause_with_historical -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat(root-cause): integrate historical and comparative analysis into main function"
```

---

### Task 7: Extend API Endpoint with New Parameters

**Files:**
- Modify: `app/api/root_cause.py` (modify endpoint and response)
- Test: `tests/test_api.py` (if exists, or create)

**Interfaces:**
- Consumes: Enhanced `generate_root_cause_analysis` from Task 6
- Produces: Extended API response with new fields

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py (add to existing file or create)

def test_root_cause_with_history_param(client):
    """Test root cause endpoint with include_history parameter."""
    response = client.get(
        "/root-cause/1?month=2026-06&include_history=true&compare_peers=true&months_back=6"
    )
    
    # Should return 200 or 404 (if hospital doesn't exist)
    assert response.status_code in (200, 404)
    
    if response.status_code == 200:
        data = response.json()
        assert "causal_tree" in data
        assert "causal_chains" in data
        assert "historical_trends" in data
        assert "peer_comparisons" in data
        assert "summary_arabic" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_root_cause_with_history_param -v`
Expected: FAIL (new fields not in response)

- [ ] **Step 3: Write minimal implementation**

Modify `app/api/root_cause.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, QualityScore, ConfidenceScore
from app.engine.root_cause import generate_root_cause_analysis
from app.engine.pipeline import run_full_analysis
import json

router = APIRouter(prefix="/root-cause", tags=["root-cause"])


@router.get("/{hospital_id}")
def get_root_cause_analysis(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    include_history: bool = Query(False, description="Include historical trend analysis"),
    compare_peers: bool = Query(False, description="Include peer comparison analysis"),
    months_back: int = Query(6, description="Months of history to analyze"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    quality_data = None
    confidence_data = None

    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    if qs:
        quality_data = {
            "score": qs.score,
            "rule_compliance": qs.rule_compliance,
            "completeness": qs.completeness,
            "consistency": qs.consistency,
            "outlier_penalty": qs.outlier_penalty,
            "issues": json.loads(qs.issues) if qs.issues else [],
        }

    cs = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if cs:
        confidence_data = {
            "overall_confidence": cs.overall_confidence,
            "level": cs.level,
            "indicators": json.loads(cs.indicators_data) if cs.indicators_data else [],
            "by_level": {
                "HIGH": cs.high_count,
                "MEDIUM": cs.medium_count,
                "LOW": cs.low_count,
                "CRITICAL": cs.critical_count,
            },
        }

    if not quality_data or not confidence_data:
        try:
            report = run_full_analysis(db, hospital_id, month)
            quality_data = {
                "score": report["data_quality_score"],
                "rule_compliance": report.get("rule_compliance", 0),
                "completeness": report.get("completeness", 0),
                "consistency": report.get("consistency", 0),
                "outlier_penalty": report.get("outlier_penalty", 0),
                "issues": report.get("issues", []),
            }
            confidence_data = report.get("confidence", {})
        except Exception:
            pass

    report = generate_root_cause_analysis(
        db, hospital_id, month,
        quality_data=quality_data,
        confidence_data=confidence_data,
        include_history=include_history,
        compare_peers=compare_peers,
        months_back=months_back,
    )

    # Build base response
    response = {
        "hospital": report.hospital,
        "hospital_id": report.hospital_id,
        "month": report.month,
        "overall_quality_score": report.overall_quality_score,
        "overall_confidence": report.overall_confidence,
        "critical_issues_count": report.critical_issues_count,
        "summary": report.summary,
        "priority_actions": report.priority_actions,
        "top_rule_failures": [
            {
                "rule_code": f.rule_code,
                "description": f.rule_description,
                "severity": f.severity,
                "failure_rate": f.failure_rate,
                "primary_cause": f.primary_cause,
                "recommendation": f.recommendation,
            }
            for f in report.top_rule_failures
        ],
        "quality_drivers": [
            {
                "component": d.component,
                "value": d.value,
                "impact": d.impact,
                "status": d.status,
                "recommendation": d.recommendation,
            }
            for d in report.quality_drivers
        ],
        "confidence_gaps": [
            {
                "indicator_code": g.indicator_code,
                "indicator_name": g.indicator_name,
                "confidence": g.confidence,
                "level": g.level,
                "weakest_signal": g.weakest_signal,
                "root_cause": g.root_cause,
                "recommendation": g.recommendation,
            }
            for g in report.confidence_gaps
        ],
        "anomaly_patterns": [
            {
                "rate_name": a.rate_name,
                "avg_z_score": a.avg_z_score,
                "recurrence_count": a.recurrence_count,
                "pattern_type": a.pattern_type,
                "description": a.description,
            }
            for a in report.anomaly_patterns
        ],
        "ai_recommendations": report.ai_recommendations,
    }
    
    # Add new fields if requested
    if include_history or compare_peers:
        response["causal_tree"] = [
            {
                "factor": n.factor,
                "factor_type": n.factor_type,
                "current_value": n.current_value,
                "trend": n.trend,
                "trend_slope": n.trend_slope,
                "severity": n.severity,
            }
            for n in report.causal_tree
        ]
        response["causal_chains"] = [
            {
                "root_cause": c.root_cause,
                "root_cause_arabic": c.root_cause_arabic,
                "confidence": c.confidence,
                "evidence": c.evidence,
                "affected_factors": c.affected_factors,
                "recommended_action": c.recommended_action,
                "impact_if_fixed": c.impact_if_fixed,
                "implementation_priority": c.implementation_priority,
            }
            for c in report.causal_chains
        ]
        response["historical_trends"] = report.historical_trends
        response["peer_comparisons"] = {
            k: {
                "peer_group": v.peer_group,
                "peer_count": v.peer_count,
                "mean_value": v.mean_value,
                "hospital_percentile": v.hospital_percentile,
                "hospital_z_score": v.hospital_z_score,
                "gap_to_benchmark": v.gap_to_benchmark,
            }
            for k, v in report.peer_comparisons.items()
        }
        response["summary_arabic"] = report.summary_arabic
    
    return response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py::test_root_cause_with_history_param -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/root_cause.py tests/test_api.py
git commit -m "feat(api): extend root-cause endpoint with history and peer comparison params"
```

---

### Task 8: Enhance AI Prompts with Historical Context

**Files:**
- Modify: `app/plugins/ai/prompts.py` (add new prompt builder)
- Test: `tests/test_ai_prompts.py` (create)

**Interfaces:**
- Consumes: Report data with historical/comparative fields
- Produces: `_build_root_cause_prompt_enhanced()` function

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_prompts.py (create new file)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_prompts.py::test_build_root_cause_prompt_enhanced -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

Add to `app/plugins/ai/prompts.py`:

```python
def _build_root_cause_prompt_enhanced(report_data: dict) -> str:
    """
    Build enhanced root cause prompt with historical and comparative context.
    """
    lines = []
    lines.append("You are a maternal health data quality expert analyzing ROOT CAUSES with HISTORICAL and COMPARATIVE context.")
    lines.append("Focus on data quality improvements, confidence gaps, and operational fixes for the specific hospital.")
    lines.append("")
    lines.append(f"Hospital: {report_data.get('hospital', 'Unknown')}")
    lines.append(f"Month: {report_data.get('month', 'Unknown')}")
    lines.append(f"Overall Quality Score: {report_data.get('overall_quality_score', 'N/A')}")
    lines.append(f"Overall Confidence: {report_data.get('overall_confidence', 'N/A')}")
    lines.append(f"Critical Issues Count: {report_data.get('critical_issues_count', 0)}")
    lines.append("")
    
    # Historical trends
    if report_data.get("historical_trends"):
        lines.append("## Historical Trends (Last 6 Months)")
        for factor, trend in report_data["historical_trends"].items():
            lines.append(f"  {factor}: {trend.get('direction', 'unknown')} "
                        f"(slope={trend.get('slope', 0):.2f}, "
                        f"significant={trend.get('significant_change', False)})")
        lines.append("")
    
    # Peer comparisons
    if report_data.get("peer_comparisons"):
        lines.append("## Peer Comparisons")
        for group, comp in report_data["peer_comparisons"].items():
            lines.append(f"  {group}: percentile={comp.get('hospital_percentile', 0)}, "
                        f"z-score={comp.get('hospital_z_score', 0)}, "
                        f"gap_to_benchmark={comp.get('gap_to_benchmark', 0)}")
        lines.append("")
    
    # Causal chains
    if report_data.get("causal_chains"):
        lines.append("## Causal Chains Detected")
        for chain in report_data["causal_chains"]:
            lines.append(f"  Root Cause: {chain.get('root_cause_arabic', '')}")
            lines.append(f"  Confidence: {chain.get('confidence', 0)}")
            lines.append(f"  Impact if fixed: {chain.get('impact_if_fixed', 0)} points")
        lines.append("")
    
    # Rule failures
    if report_data.get("top_rule_failures"):
        lines.append("## Top Rule Failures")
        for f in report_data["top_rule_failures"][:5]:
            lines.append(f"  {f.get('rule_code','')} ({f.get('severity','')}): {f.get('description','')}")
            lines.append(f"    Failure rate: {f.get('failure_rate','')}% | Cause: {f.get('primary_cause','')}")
        lines.append("")
    
    # Quality drivers
    if report_data.get("quality_drivers"):
        lines.append("## Quality Drivers")
        for d in report_data["quality_drivers"]:
            lines.append(f"  {d.get('component','')}: {d.get('value','')}% ({d.get('status','')})")
        lines.append("")
    
    # Confidence gaps
    if report_data.get("confidence_gaps"):
        lines.append("## Confidence Gaps")
        for g in report_data["confidence_gaps"][:5]:
            lines.append(f"  {g.get('indicator_name','')} ({g.get('level','')}): confidence={g.get('confidence','')}")
        lines.append("")
    
    # Anomaly patterns
    if report_data.get("anomaly_patterns"):
        lines.append("## Anomaly Patterns")
        for a in report_data["anomaly_patterns"][:5]:
            lines.append(f"  {a.get('rate_name','')}: |z|={a.get('avg_z_score','')}, type={a.get('pattern_type','')}")
        lines.append("")
    
    lines.append("""Based on the historical trends and peer comparisons above, provide:
1. Root cause analysis with historical context (why is this happening now?)
2. Why this hospital differs from peers (what makes it unique?)
3. Specific actionable recommendations with timelines
4. Expected impact if recommendations are implemented

Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "Historical Decline", "Peer Comparison", "Data Entry Training")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the root cause issue)
- rationale: str (why this matters, 1-2 sentences)
- action_items: list[str] (3-5 specific actionable steps with timelines)
- affected_indicators: list[str] (indicator codes or rule codes affected)
- expected_impact: float (numeric improvement estimate in quality score points)
- implementation_timeline: str (e.g., "1-2 weeks", "1 month")

Give concrete, hospital-specific advice. Prioritize critical data quality issues first.

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_prompts.py::test_build_root_cause_prompt_enhanced -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/plugins/ai/prompts.py tests/test_ai_prompts.py
git commit -m "feat(ai): add enhanced root cause prompt with historical context"
```

---

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

---

### Task 10: Update AI Init to Use Enhanced Functions

**Files:**
- Modify: `app/plugins/ai/__init__.py` (update `generate_root_cause_ai`)
- Test: `tests/test_ai_init.py` (create)

**Interfaces:**
- Consumes: Enhanced prompt and fallback from Tasks 8-9
- Produces: Updated `generate_root_cause_ai()` function

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_init.py (create new file)

def test_generate_root_cause_ai_with_historical():
    from app.plugins.ai import generate_root_cause_ai
    
    report_data = {
        "hospital": "Test Hospital",
        "month": "2026-06",
        "overall_quality_score": 65.0,
        "overall_confidence": 50.0,
        "critical_issues_count": 1,
        "top_rule_failures": [
            {"rule_code": "R001", "severity": "CRITICAL", "failure_rate": 70,
             "description": "Sum mismatch", "primary_cause": "Data entry error"}
        ],
        "quality_drivers": [],
        "confidence_gaps": [],
        "anomaly_patterns": [],
        "historical_trends": {
            "R001": {"direction": "declining", "slope": -2.5}
        },
        "peer_comparisons": {
            "hospital_type": {"hospital_percentile": 12.5}
        },
        "causal_chains": [],
    }
    
    # This should work without AI enabled (uses local fallback)
    result = generate_root_cause_ai(report_data)
    
    assert isinstance(result, list)
    assert len(result) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_init.py::test_generate_root_cause_ai_with_historical -v`
Expected: FAIL (function doesn't pass new data)

- [ ] **Step 3: Write minimal implementation**

Modify `app/plugins/ai/__init__.py`:

```python
from typing import List, Dict, Optional

from app.plugins.ai.cache import get_ai_cache, set_ai_cache
from app.plugins.ai.providers import (
    AI_ENABLED, AI_API_KEY,
    AIRuleDef,
    _call_api,
    _parse_response,
    _local_clinical_fallback,
    _local_executive_summary_fallback,
    _local_root_cause_fallback,
    _local_root_cause_fallback_enhanced,
)
from app.plugins.ai.prompts import (
    _build_prompt,
    _build_executive_summary_prompt,
    _build_root_cause_prompt,
    _build_root_cause_prompt_enhanced,
)


def generate(
    values: Dict[str, float],
    classifications: List,
    risk_profile,
    morbidity_profile,
    quality_score: Optional[float] = None,
    session=None,
) -> List[AIRuleDef]:
    if not AI_ENABLED:
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    if not AI_API_KEY:
        import logging
        logging.getLogger(__name__).warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    prompt = _build_prompt(values, classifications, risk_profile, morbidity_profile, quality_score)
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                try:
                    return _parse_response(cached)
                except Exception:
                    pass
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    try:
        return _parse_response(response)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to parse AI response: {e}")
        return _local_clinical_fallback(values, classifications, risk_profile, morbidity_profile, quality_score)


def generate_executive_summary(
    hospital: str,
    month: str,
    values: Dict[str, float],
    quality_score: float,
    completeness: float = 0,
    consistency: float = 0,
    rule_compliance: float = 0,
    outlier_penalty: float = 0,
    rule_results: List = None,
    anomaly_results: List = None,
    trend_data: Dict = None,
    all_hospital_data: Dict = None,
    classifications: List = None,
    risk_profile=None,
    morbidity_profile=None,
    session=None,
) -> str:
    if not AI_ENABLED or not AI_API_KEY:
        return _local_executive_summary_fallback(
            hospital, month, quality_score, completeness, consistency,
            rule_compliance, outlier_penalty, rule_results, anomaly_results,
            classifications, risk_profile, morbidity_profile,
        )
    prompt = _build_executive_summary_prompt(
        hospital, month, values, quality_score, completeness, consistency,
        rule_compliance, outlier_penalty, rule_results or [],
        anomaly_results or [], trend_data or {}, all_hospital_data or {},
        classifications, risk_profile, morbidity_profile,
    )
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                return cached
        except Exception:
            pass
    response = _call_api(prompt)
    if not response:
        return _local_executive_summary_fallback(
            hospital, month, quality_score, completeness, consistency,
            rule_compliance, outlier_penalty, rule_results, anomaly_results,
            classifications, risk_profile, morbidity_profile,
        )
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    return response.strip()


def generate_root_cause_ai(report_data: dict, session=None) -> List[AIRuleDef]:
    """
    Generate root cause recommendations using AI or local fallback.
    
    Enhanced to support historical and comparative data when available.
    """
    has_historical = bool(report_data.get("historical_trends"))
    has_peers = bool(report_data.get("peer_comparisons"))
    use_enhanced = has_historical or has_peers
    
    if not AI_ENABLED:
        if use_enhanced:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
    
    if not AI_API_KEY:
        import logging
        logging.getLogger(__name__).warning("AI_RECOMMENDATIONS_ENABLED=true but AI_API_KEY missing")
        if use_enhanced:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
    
    # Use enhanced prompt if historical/peer data available
    prompt = _build_root_cause_prompt_enhanced(report_data) if use_enhanced else _build_root_cause_prompt(report_data)
    
    if session is not None:
        try:
            cached = get_ai_cache(session, prompt)
            if cached:
                try:
                    return _parse_response(cached)
                except Exception:
                    pass
        except Exception:
            pass
    
    response = _call_api(prompt)
    if not response:
        if use_enhanced:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
    
    if session is not None:
        try:
            set_ai_cache(session, prompt, response)
        except Exception:
            pass
    
    try:
        return _parse_response(response)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to parse root cause AI response: {e}")
        if use_enhanced:
            return _local_root_cause_fallback_enhanced(report_data)
        return _local_root_cause_fallback(report_data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_init.py::test_generate_root_cause_ai_with_historical -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/plugins/ai/__init__.py tests/test_ai_init.py
git commit -m "feat(ai): update init to use enhanced root cause functions"
```

---

### Task 11: Add Integration Tests

**Files:**
- Modify: `tests/test_root_cause.py` (add integration tests)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Consumes: All functions from Tasks 1-10
- Produces: Comprehensive integration tests

- [ ] **Step 1: Write the failing test**

```python
# tests/test_root_cause.py (add to existing file)

def test_full_historical_comparative_analysis(db_session):
    """Full integration test for historical and comparative root cause analysis."""
    from app.engine.root_cause import generate_root_cause_analysis
    from app.models import Hospital, HospitalType, IndicatorValue, QualityScore, ConfidenceScore
    
    # Create hospital type
    htype = HospitalType(name="Government")
    db_session.add(htype)
    db_session.flush()
    
    # Create hospitals
    h1 = Hospital(name="Hospital A", hospital_type_id=htype.id, is_active=True)
    h2 = Hospital(name="Hospital B", hospital_type_id=htype.id, is_active=True)
    h3 = Hospital(name="Hospital C", hospital_type_id=htype.id, is_active=True)
    h4 = Hospital(name="Hospital D", hospital_type_id=htype.id, is_active=True)
    db_session.add_all([h1, h2, h3, h4])
    db_session.flush()
    
    # Add historical data for h1 (declining trend)
    for i, month in enumerate(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]):
        iv = IndicatorValue(hospital_id=h1.id, indicator_code="R001", month=month, value=65 + i)
        db_session.add(iv)
    
    # Add peer data (better performing)
    for h in [h2, h3, h4]:
        iv = IndicatorValue(hospital_id=h.id, indicator_code="R001", month="2026-06", value=35)
        db_session.add(iv)
    
    # Add quality and confidence scores
    qs = QualityScore(hospital_id=h1.id, month="2026-06", score=62,
                      rule_compliance=55, completeness=70, consistency=60, outlier_penalty=0.2)
    cs = ConfidenceScore(hospital_id=h1.id, month="2026-06",
                         overall_confidence=45, level="MEDIUM",
                         high_count=5, medium_count=3, low_count=2, critical_count=1)
    db_session.add_all([qs, cs])
    db_session.commit()
    
    # Run analysis
    report = generate_root_cause_analysis(
        db_session, h1.id, "2026-06",
        quality_data={"score": 62, "rule_compliance": 55, "completeness": 70,
                      "consistency": 60, "outlier_penalty": 0.2},
        confidence_data={"overall_confidence": 45, "level": "MEDIUM", "indicators_data": []},
        include_history=True,
        compare_peers=True,
        months_back=6
    )
    
    # Verify results
    assert report.hospital == "Hospital A"
    assert len(report.causal_tree) > 0
    assert len(report.causal_chains) > 0
    assert "hospital_type" in report.peer_comparisons
    assert report.summary_arabic != ""
    
    # Verify causal chain has confidence
    top_chain = report.causal_chains[0]
    assert top_chain.confidence > 0
    assert len(top_chain.evidence) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_root_cause.py::test_full_historical_comparative_analysis -v`
Expected: FAIL (missing data or assertion error)

- [ ] **Step 3: Write minimal implementation**

Ensure all previous tasks are properly integrated. The test should pass if Tasks 1-10 are correctly implemented.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_root_cause.py::test_full_historical_comparative_analysis -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_root_cause.py
git commit -m "test(root-cause): add integration test for historical and comparative analysis"
```

---

### Task 12: Run All Tests and Lint

**Files:**
- No new files
- Verify all tests pass

**Interfaces:**
- Consumes: All code from Tasks 1-11
- Produces: All tests passing, no lint errors

- [ ] **Step 1: Run all root cause tests**

Run: `pytest tests/test_root_cause.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run AI-related tests**

Run: `pytest tests/test_ai_prompts.py tests/test_ai_providers.py tests/test_ai_init.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run API tests**

Run: `pytest tests/test_api.py -v`
Expected: All tests PASS

- [ ] **Step 4: Run lint**

Run: `ruff check app/engine/root_cause.py app/api/root_cause.py app/plugins/ai/`
Expected: No errors

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(root-cause): complete historical and comparative analysis implementation

- Add CausalNode, CausalChain, MonthDataPoint, PeerComparison dataclasses
- Implement historical data retrieval (last 6 months)
- Implement peer comparison metrics (3 groups)
- Implement causal chain builder with correlation analysis
- Extend API endpoint with include_history and compare_peers params
- Enhance AI prompts with historical context
- Enhance local fallback with comparative logic
- Add comprehensive tests"
```

---

## Success Criteria

- [x] All data structures defined (Task 1)
- [x] Historical data retrieval working (Task 2)
- [x] Trend analysis with linear regression (Task 3)
- [x] Peer comparison metrics (Task 4)
- [x] Causal chain builder (Task 5)
- [x] Integration into main function (Task 6)
- [x] API endpoint extended (Task 7)
- [x] AI prompts enhanced (Task 8)
- [x] Local fallback enhanced (Task 9)
- [x] AI init updated (Task 10)
- [x] Integration tests added (Task 11)
- [x] All tests passing, lint clean (Task 12)
