# HEALTH-ai Architecture Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bugs, split large files into focused packages, add Alembic migrations, and expand test coverage.

**Architecture:** Incremental refactoring — fix bugs first, then split files one package at a time with tests after each split, then add Alembic, then expand test coverage.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, SQLite, Pytest, Alembic

## Global Constraints

- All tests must pass after each task (151 tests baseline)
- No breaking changes to API endpoints or response shapes
- Follow existing code patterns (naming, error handling, import style)
- Each file split must maintain backward compatibility via `__init__.py` re-exports
- TDD: write tests before implementation for new code
- DRY: remove duplicated code, don't introduce new duplication
- YAGNI: only implement what the spec requires

---

## File Structure Map

### Files to Modify
| File | Tasks | Changes |
|---|---|---|
| `app/engine/clinical.py` | 2 | Fix bug, then split into package |
| `app/engine/quality_score.py` | 1, 3 | Fix Severity.HIGH bug |
| `app/engine/quality.py` | 3 | Remove duplicate calculate_quality_score |
| `app/main.py` | 4 | Replace seeding with script imports, add Alembic |
| `app/database.py` | 9 | Remove _migrate_schema, keep init_db |
| `app/api/hospitals.py` | 7 | Split into 3 files |
| `app/api/analysis.py` | 1, 3, 6 | Update imports after splits |
| `app/api/reports.py` | 3 | Update imports after splits |
| `app/api/dashboard.py` | 3, 6 | Update imports after splits |
| `app/api/config_api.py` | 6 | Update imports after splits |
| `requirements.txt` | 10 | Add pytest-cov, alembic, ruff |

### Files to Create
| File | Tasks | Purpose |
|---|---|---|
| `app/engine/clinical/__init__.py` | 2 | Re-exports for clinical package |
| `app/engine/clinical/thresholds.py` | 2 | WHO/FIGO thresholds |
| `app/engine/clinical/risk_profile.py` | 2 | Risk metrics |
| `app/engine/clinical/morbidity.py` | 2 | Morbidity analysis |
| `app/engine/clinical/recommendations.py` | 2 | Recommendation engine |
| `app/engine/clinical/summary.py` | 2 | Summary generation |
| `app/engine/quality/__init__.py` | 3 | Re-exports for quality package |
| `app/engine/quality/rules.py` | 3 | Rule execution |
| `app/engine/quality/scoring.py` | 3 | Quality scoring |
| `app/engine/quality/definitions.py` | 3 | Rate definitions |
| `app/engine/anomaly/__init__.py` | 5 | Re-exports for anomaly package |
| `app/engine/anomaly/zscore.py` | 5 | Z-score detection |
| `app/engine/anomaly/trends.py` | 5 | Trend analysis |
| `app/engine/anomaly/comparison.py` | 5 | Hospital comparison |
| `app/plugins/ai/__init__.py` | 6 | Re-exports for AI package |
| `app/plugins/ai/providers.py` | 6 | API provider classes |
| `app/plugins/ai/prompts.py` | 6 | Prompt builders |
| `app/plugins/ai/cache.py` | 6 | AI caching |
| `app/api/indicator_config.py` | 7 | Indicator config API |
| `app/api/tree_config.py` | 7 | Tree config API |
| `alembic.ini` | 9 | Alembic config |
| `alembic/env.py` | 9 | Alembic environment |
| `alembic/versions/*.py` | 9 | Migration files |
| `tests/test_pipeline.py` | 8 | Pipeline tests |
| `tests/test_confidence.py` | 8 | Confidence tests |
| `tests/test_root_cause.py` | 8 | Root cause tests |
| `tests/test_api_hospitals.py` | 8 | Hospital API tests |
| `tests/test_api_rules.py` | 8 | Rules API tests |
| `tests/test_api_config.py` | 8 | Config API tests |
| `tests/test_api_file_ops.py` | 8 | File ops API tests |

---

### Task 1: Fix Critical Bugs

**Files:**
- Modify: `app/engine/clinical.py:368`
- Modify: `app/engine/quality_score.py:61`
- Test: `tests/test_clinical.py`
- Test: `tests/test_quality_score.py`

**Interfaces:**
- Consumes: Existing test fixtures from `tests/conftest.py`
- Produces: Fixed bug-free code, passing tests

- [ ] **Step 1: Fix clinical.py rate calculation bug**

Read `app/engine/clinical.py` around line 368. Find the line:
```python
(100 if "%" in str else 1)
```
Replace `str` with the correct variable name from the surrounding context (likely `indicator` or `rate_name`). The intent is to check if the indicator name contains "%" to determine if the value should be multiplied by 100.

- [ ] **Step 2: Verify quality_score.py Severity.HIGH fix**

Read `app/engine/quality_score.py` line 61. Ensure `Severity.HIGH` is used (not `.HIGH`). The import at line 2 should be:
```python
from app.engine.quality import RuleResult, RuleStatus, Severity
```

- [ ] **Step 3: Run existing tests**

Run: `python -m pytest tests/test_clinical.py tests/test_quality_score.py -v`
Expected: All tests pass (previously 151 total, these subsets should pass)

- [ ] **Step 4: Commit**

```bash
git add app/engine/clinical.py app/engine/quality_score.py
git commit -m "fix: correct str bug in clinical.py and verify Severity.HIGH in quality_score.py"
```

---

### Task 2: Split clinical.py into Package

**Files:**
- Create: `app/engine/clinical/__init__.py`
- Create: `app/engine/clinical/thresholds.py`
- Create: `app/engine/clinical/risk_profile.py`
- Create: `app/engine/clinical/morbidity.py`
- Create: `app/engine/clinical/recommendations.py`
- Create: `app/engine/clinical/summary.py`
- Modify: `app/engine/clinical.py` → rename to `app/engine/clinical/_legacy.py` (temporary, then delete)
- Modify: `app/api/clinical.py` — update imports
- Test: `tests/test_clinical.py` — should still pass

**Interfaces:**
- Consumes: Task 1 (bug fixes)
- Produces: `run_clinical_analysis()` re-exported from `app.engine.clinical`, all clinical functions accessible via package

- [ ] **Step 1: Create thresholds.py**

Read `app/engine/clinical.py` and extract the threshold-related code. Create `app/engine/clinical/thresholds.py`:

```python
"""WHO/FIGO clinical thresholds for maternal and neonatal health indicators."""
from enum import Enum
from typing import Optional


class Classification(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


CLINICAL_THRESHOLDS: dict[str, dict] = {
    # Extract threshold data from the original clinical.py
    # Each entry: {"indicator_code": {"elevated": X, "high": Y, "critical": Z, "direction": "high|low"}}
    # Copy the threshold definitions from the original file
}

NARRATIVE_TEMPLATES: dict[str, str] = {
    # Copy narrative templates from original file
}


def get_threshold(indicator_code: str) -> Optional[dict]:
    """Get threshold configuration for an indicator."""
    return CLINICAL_THRESHOLDS.get(indicator_code)


def classify_rate(value: Optional[float], indicator_code: str) -> tuple[Classification, str, str]:
    """Classify a rate value against clinical thresholds.
    
    Returns: (classification, label, color)
    """
    threshold = get_threshold(indicator_code)
    if threshold is None or value is None:
        return Classification.NORMAL, "Normal", "#2e7d32"
    
    # Direction: "high" means higher values are worse, "low" means lower values are worse
    direction = threshold.get("direction", "high")
    elevated = threshold["elevated"]
    high = threshold["high"]
    critical = threshold["critical"]
    
    if direction == "high":
        if value >= critical:
            return Classification.CRITICAL, "Critical", "#b71c1c"
        elif value >= high:
            return Classification.HIGH, "High", "#c62828"
        elif value >= elevated:
            return Classification.ELEVATED, "Elevated", "#e65100"
        else:
            return Classification.NORMAL, "Normal", "#2e7d32"
    else:  # direction == "low"
        if value <= critical:
            return Classification.CRITICAL, "Critical", "#b71c1c"
        elif value <= high:
            return Classification.HIGH, "High", "#c62828"
        elif value <= elevated:
            return Classification.ELEVATED, "Elevated", "#e65100"
        else:
            return Classification.NORMAL, "Normal", "#2e7d32"


def generate_narrative(indicator_code: str, value: float, classification: Classification, rate_name: str) -> str:
    """Generate a clinical narrative for a classified rate."""
    template = NARRATIVE_TEMPLATES.get(indicator_code, "")
    if not template:
        return f"{rate_name} is {classification.value} at {value}"
    return template.format(value=value, rate_name=rate_name, classification=classification.value)
```

- [ ] **Step 2: Create risk_profile.py**

Extract risk profile computation from `app/engine/clinical.py`. Create `app/engine/clinical/risk_profile.py`:

```python
"""Risk profile computation for clinical analysis."""
from typing import Optional
from .thresholds import classify_rate, Classification


def compute_risk_profile(classifications: list[dict], deliveries: int) -> dict:
    """Compute overall risk profile from individual indicator classifications.
    
    Args:
        classifications: List of classification dicts with rate_name, value, classification, label, color, narrative
        deliveries: Number of deliveries (used to scale risk)
    
    Returns:
        Risk profile dict with overall_risk_level, metrics, key_findings
    """
    if not classifications or deliveries == 0:
        return {
            "overall_risk_level": "low",
            "metrics": [],
            "key_findings": ["Insufficient data for risk assessment"],
        }
    
    # Count severity levels
    severity_counts = {"critical": 0, "high": 0, "elevated": 0, "normal": 0}
    for c in classifications:
        level = c.get("classification", "normal").lower()
        severity_counts[level] = severity_counts.get(level, 0) + 1
    
    # Determine overall risk level
    if severity_counts["critical"] > 0:
        overall_risk = "critical"
    elif severity_counts["high"] >= 2:
        overall_risk = "high"
    elif severity_counts["high"] >= 1 or severity_counts["elevated"] >= 3:
        overall_risk = "moderate"
    else:
        overall_risk = "low"
    
    # Build metrics list
    metrics = []
    for c in classifications:
        metrics.append({
            "metric_name": c["rate_name"],
            "value": c.get("value"),
            "severity": c.get("classification", "normal").lower(),
            "interpretation": c.get("narrative", ""),
            "unit": c.get("unit", ""),
        })
    
    # Build key findings
    key_findings = []
    for c in classifications:
        if c.get("classification") in (Classification.CRITICAL, Classification.HIGH):
            key_findings.append(f"{c['rate_name']}: {c.get('narrative', '')}")
    
    if not key_findings:
        key_findings.append("All indicators within acceptable ranges")
    
    return {
        "overall_risk_level": overall_risk,
        "metrics": metrics,
        "key_findings": key_findings,
    }
```

- [ ] **Step 3: Create morbidity.py**

Extract morbidity profile computation. Create `app/engine/clinical/morbidity.py`:

```python
"""Morbidity-mortality profile computation."""
from typing import Optional
from .thresholds import classify_rate, Classification


def compute_morbidity_profile(classifications: list[dict], deliveries: int) -> dict:
    """Compute morbidity-mortality profile.
    
    Args:
        classifications: List of classification dicts
        deliveries: Number of deliveries
    
    Returns:
        Morbidity profile dict with key_findings, mortality_preventability_signals, metrics
    """
    if not classifications or deliveries == 0:
        return {
            "key_findings": ["Insufficient data for morbidity assessment"],
            "mortality_preventability_signals": [],
            "metrics": [],
        }
    
    # Extract mortality-related indicators
    mortality_indicators = [c for c in classifications if any(
        kw in c.get("rate_name", "").lower() 
        for kw in ["mmr", "nmr", "stillbirth", "maternal", "neonatal", "mortality"]
    )]
    
    # Build preventability signals
    signals = []
    for ind in mortality_indicators:
        if ind.get("classification") in (Classification.CRITICAL, Classification.HIGH):
            signals.append(f"Elevated {ind['rate_name']} suggests preventable factors")
    
    if not signals:
        signals.append("No immediate preventability concerns identified")
    
    # Build metrics
    metrics = []
    for c in classifications:
        if any(kw in c.get("rate_name", "").lower() for kw in ["mmr", "nmr", "stillbirth", "morbidity", "smm"]):
            metrics.append({
                "metric_name": c["rate_name"],
                "value": c.get("value"),
                "severity": c.get("classification", "normal").lower(),
                "interpretation": c.get("narrative", ""),
                "unit": c.get("unit", ""),
            })
    
    # Key findings
    key_findings = []
    critical_mortality = [m for m in mortality_indicators if m.get("classification") == Classification.CRITICAL]
    if critical_mortality:
        key_findings.append(f"Critical mortality indicators: {', '.join(m['rate_name'] for m in critical_mortality)}")
    
    high_mortality = [m for m in mortality_indicators if m.get("classification") == Classification.HIGH]
    if high_mortality:
        key_findings.append(f"Elevated mortality indicators: {', '.join(m['rate_name'] for m in high_mortality)}")
    
    if not key_findings:
        key_findings.append("Mortality indicators within acceptable ranges")
    
    return {
        "key_findings": key_findings,
        "mortality_preventability_signals": signals,
        "metrics": metrics,
    }
```

- [ ] **Step 4: Create recommendations.py**

Extract recommendation engine. Create `app/engine/clinical/recommendations.py`:

```python
"""Clinical recommendation engine based on rule-based analysis."""
from typing import Optional


RECOMMENDATION_RULES: list[dict] = [
    # Copy recommendation rules from original clinical.py
    # Each rule: {"id": str, "condition": callable, "priority": str, "title": str, "description": str, ...}
]


def generate_recommendations(
    classifications: list[dict],
    risk_profile: dict,
    quality_score: Optional[float] = None,
    rule_failures: Optional[list] = None,
) -> list[dict]:
    """Generate prioritized clinical recommendations.
    
    Args:
        classifications: List of classification dicts
        risk_profile: Risk profile dict from compute_risk_profile
        quality_score: Overall quality score (0-100)
        rule_failures: List of rule failure dicts
    
    Returns:
        List of recommendation dicts sorted by priority
    """
    recommendations = []
    
    # Priority order: critical > high > medium > low
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    
    # Generate recommendations based on risk profile
    if risk_profile.get("overall_risk_level") in ("critical", "high"):
        recommendations.append({
            "priority": "critical" if risk_profile["overall_risk_level"] == "critical" else "high",
            "title": "Urgent Clinical Review Required",
            "description": f"Overall risk level is {risk_profile['overall_risk_level']}. Immediate review of all critical indicators recommended.",
            "action_items": [
                "Review all critical and high severity indicators",
                "Conduct root cause analysis for outlier metrics",
                "Implement corrective action plans",
            ],
            "triggered_by_rules": [],
            "indicators_monitored": [m["metric_name"] for m in risk_profile.get("metrics", [])],
        })
    
    # Generate recommendations based on classifications
    for c in classifications:
        if c.get("classification") in ("critical", "high"):
            recommendations.append({
                "priority": c.get("classification", "medium"),
                "title": f"Address {c['rate_name']}",
                "description": c.get("narrative", ""),
                "action_items": [f"Investigate {c['rate_name']} trends", "Review data collection methods"],
                "triggered_by_rules": [],
                "indicators_monitored": [c["rate_name"]],
            })
    
    # Generate recommendations based on rule failures
    if rule_failures:
        critical_rules = [r for r in rule_failures if r.get("severity") == "CRITICAL"]
        if critical_rules:
            recommendations.append({
                "priority": "critical",
                "title": "Critical Data Quality Issues",
                "description": f"{len(critical_rules)} critical rule failures detected. Data integrity must be addressed before clinical analysis.",
                "action_items": ["Review data entry processes", "Validate source data", "Re-run analysis after corrections"],
                "triggered_by_rules": [r.get("rule_code", "") for r in critical_rules],
                "indicators_monitored": [],
            })
    
    # Sort by priority
    recommendations.sort(key=lambda r: priority_order.get(r.get("priority", "low"), 3))
    
    return recommendations
```

- [ ] **Step 5: Create summary.py**

Extract summary generation. Create `app/engine/clinical/summary.py`:

```python
"""Clinical summary generation."""
from typing import Optional


def generate_clinical_summary(
    classifications: list[dict],
    risk_profile: dict,
    morbidity_profile: dict,
    recommendations: list[dict],
    quality_score: Optional[float] = None,
) -> dict:
    """Generate a comprehensive clinical summary.
    
    Args:
        classifications: List of classification dicts
        risk_profile: Risk profile dict
        morbidity_profile: Morbidity profile dict
        recommendations: List of recommendation dicts
        quality_score: Overall quality score (0-100)
    
    Returns:
        Summary dict with overall_assessment, overview, key_findings, clinical_indicators
    """
    # Overall assessment
    risk_level = risk_profile.get("overall_risk_level", "low")
    if risk_level == "critical":
        overall = "CRITICAL — Immediate intervention required"
    elif risk_level == "high":
        overall = "HIGH — Urgent review recommended"
    elif risk_level == "moderate":
        overall = "ATTENTION — Several indicators need monitoring"
    else:
        overall = "Good — All indicators within acceptable ranges"
    
    # Overview
    total_indicators = len(classifications)
    critical_count = sum(1 for c in classifications if c.get("classification") == "critical")
    high_count = sum(1 for c in classifications if c.get("classification") == "high")
    
    overview = f"Analyzed {total_indicators} clinical indicators. "
    if critical_count > 0:
        overview += f"{critical_count} critical, "
    if high_count > 0:
        overview += f"{high_count} high severity. "
    if quality_score is not None:
        overview += f"Data quality score: {quality_score:.0f}%."
    
    # Key findings
    key_findings = risk_profile.get("key_findings", [])
    if morbidity_profile.get("key_findings"):
        key_findings.extend(morbidity_profile["key_findings"])
    
    # Clinical indicators summary
    clinical_indicators = []
    for c in classifications:
        clinical_indicators.append(f"{c['rate_name']}: {c.get('value', 'N/A')}")
    
    return {
        "overall_assessment": overall,
        "overview": overview,
        "key_findings": key_findings[:10],  # Limit to 10
        "clinical_indicators": clinical_indicators,
        "morbidity_assessment": morbidity_profile.get("key_findings", ["No morbidity concerns"])[0] if morbidity_profile.get("key_findings") else "No morbidity concerns",
    }
```

- [ ] **Step 6: Create __init__.py with re-exports**

Create `app/engine/clinical/__init__.py`:

```python
"""Clinical analysis engine — WHO/FIGO-based classification, risk, morbidity, recommendations."""
from .thresholds import classify_rate, get_threshold, Classification, CLINICAL_THRESHOLDS, NARRATIVE_TEMPLATES
from .risk_profile import compute_risk_profile
from .morbidity import compute_morbidity_profile
from .recommendations import generate_recommendations, RECOMMENDATION_RULES
from .summary import generate_clinical_summary


def run_clinical_analysis(
    classifications: list[dict],
    deliveries: int,
    quality_score: float | None = None,
    rule_failures: list | None = None,
) -> dict:
    """Run full clinical analysis pipeline.
    
    This is the main entry point that orchestrates all clinical sub-modules.
    """
    risk_profile = compute_risk_profile(classifications, deliveries)
    morbidity_profile = compute_morbidity_profile(classifications, deliveries)
    recommendations = generate_recommendations(
        classifications, risk_profile, quality_score, rule_failures
    )
    summary = generate_clinical_summary(
        classifications, risk_profile, morbidity_profile, recommendations, quality_score
    )
    
    return {
        "classifications": classifications,
        "risk_profile": risk_profile,
        "morbidity_profile": morbidity_profile,
        "recommendations": recommendations,
        "summary": summary,
    }


__all__ = [
    "run_clinical_analysis",
    "classify_rate",
    "get_threshold",
    "Classification",
    "compute_risk_profile",
    "compute_morbidity_profile",
    "generate_recommendations",
    "generate_clinical_summary",
    "CLINICAL_THRESHOLDS",
    "NARRATIVE_TEMPLATES",
    "RECOMMENDATION_RULES",
]
```

- [ ] **Step 7: Update imports in app/api/clinical.py**

Read `app/api/clinical.py`. Update any imports from `app.engine.clinical` (the old file) to `app.engine.clinical` (the new package). Since `__init__.py` re-exports everything, the import paths should remain the same:

```python
from app.engine.clinical import run_clinical_analysis
```

This should still work because `__init__.py` re-exports `run_clinical_analysis`.

- [ ] **Step 8: Run clinical tests**

Run: `python -m pytest tests/test_clinical.py -v`
Expected: All tests pass (same count as before the split)

- [ ] **Step 9: Delete old clinical.py**

After confirming tests pass, delete `app/engine/clinical.py` (the original monolithic file).

- [ ] **Step 10: Commit**

```bash
git add app/engine/clinical/ app/api/clinical.py
git rm app/engine/clinical.py
git commit -m "refactor: split clinical.py into focused package (thresholds, risk, morbidity, recommendations, summary)"
```

---

### Task 3: Split quality.py + Remove Duplicate

**Files:**
- Create: `app/engine/quality/__init__.py`
- Create: `app/engine/quality/rules.py`
- Create: `app/engine/quality/scoring.py`
- Create: `app/engine/quality/definitions.py`
- Modify: `app/engine/quality.py` → delete after split
- Modify: `app/engine/quality_score.py` → merge into quality/scoring.py
- Modify: `app/api/analysis.py` — update imports
- Modify: `app/api/reports.py` — update imports
- Modify: `app/api/dashboard.py` — update imports
- Test: `tests/test_quality_score.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 1 (bug fixes), Task 2 (clinical split — no dependency, parallel)
- Produces: `run_quality_analysis()`, `ALL_RULES`, `dispatch_rule`, `calculate_quality_score` re-exported from `app.engine.quality`

- [ ] **Step 1: Create definitions.py**

Extract rate definitions and indicator mappings from `app/engine/quality.py`. Create `app/engine/quality/definitions.py`:

```python
"""Rate definitions and indicator mappings for quality analysis."""

RATE_DEFINITIONS: list[dict] = [
    # Copy RATE_DEFINITIONS from app/engine/quality.py
    # Each entry: {"name": str, "numerator": str, "denominator": str, "unit": str, ...}
]

INDICATOR_PARENT_MAP: dict[str, str] = {
    # Copy indicator parent mappings from app/engine/quality.py
}

UNIT_CONFIGS: dict[str, str] = {
    # Copy unit configurations from app/engine/quality.py
}
```

- [ ] **Step 2: Create rules.py**

Extract rule execution logic. Create `app/engine/quality/rules.py`:

```python
"""Validation rule engine — compiled rules + DB-driven dispatch."""
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class RuleResult:
    rule_code: str
    rule_description: str
    rule_type: str
    severity: Severity
    status: RuleStatus
    details: str = ""
    indicator_code: str = ""


# Copy ALL_RULES from app/engine/quality.py
ALL_RULES: list[dict] = [...]


def dispatch_rule(rule_code: str, values: dict, context: dict) -> RuleResult:
    """Dispatch a rule by code and execute it.
    
    Args:
        rule_code: Rule identifier (e.g., "R001")
        values: Indicator values dict {code: value}
        context: Additional context (hospital_id, month, etc.)
    
    Returns:
        RuleResult with status, severity, details
    """
    # Copy rule dispatch logic from app/engine/quality.py
    # This includes the rule lookup and execution
    pass


def run_all_rules(values: dict, context: dict, custom_rules: Optional[list] = None) -> list[RuleResult]:
    """Run all validation rules against indicator values.
    
    Args:
        values: Indicator values dict
        context: Analysis context
        custom_rules: Optional DB-driven rules to run in addition to compiled rules
    
    Returns:
        List of RuleResult objects
    """
    results = []
    
    # Run compiled rules
    for rule_def in ALL_RULES:
        result = dispatch_rule(rule_def["code"], values, context)
        results.append(result)
    
    # Run custom rules if provided
    if custom_rules:
        for rule in custom_rules:
            result = dispatch_rule(rule["code"], values, context)
            results.append(result)
    
    return results
```

- [ ] **Step 3: Create scoring.py**

Move `calculate_quality_score` from `app/engine/quality_score.py` here. Create `app/engine/quality/scoring.py`:

```python
"""Quality score calculation based on rule results and anomaly detection."""
from typing import List, Dict
from .rules import RuleResult, RuleStatus, Severity


def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    active_indicator_count: int,
) -> Dict:
    """Calculate overall data quality score (0-100).
    
    Args:
        rule_results: List of RuleResult from run_all_rules
        values: Indicator values
        anomaly_results: Anomaly detection results
        active_indicator_count: Number of active indicators
    
    Returns:
        Dict with score, completeness, rule_compliance, anomaly_penalty, issues
    """
    if active_indicator_count == 0:
        return {"score": 0, "completeness": 0, "rule_compliance": 0, "anomaly_penalty": 0, "issues": []}
    
    # Rule compliance score
    total_rules = len(rule_results)
    passed_rules = sum(1 for r in rule_results if r.status == RuleStatus.PASS)
    rule_compliance = (passed_rules / total_rules * 100) if total_rules > 0 else 100
    
    # Completeness score
    filled_indicators = sum(1 for v in values.values() if v is not None)
    completeness = (filled_indicators / active_indicator_count * 100) if active_indicator_count > 0 else 0
    
    # Anomaly penalty
    outlier_count = sum(1 for a in anomaly_results if a.get("is_outlier"))
    anomaly_penalty = min(outlier_count * 5, 30)  # Cap at 30 points
    
    # Weighted score
    score = (rule_compliance * 0.5 + completeness * 0.5) - anomaly_penalty
    score = max(0, min(100, score))  # Clamp to 0-100
    
    # Collect issues
    issues = []
    for r in rule_results:
        if r.status == RuleStatus.FAIL:
            issues.append({
                "rule_code": r.rule_code,
                "severity": r.severity.value if isinstance(r.severity, Severity) else r.severity,
                "details": r.details,
            })
    
    return {
        "score": round(score, 1),
        "completeness": round(completeness, 1),
        "rule_compliance": round(rule_compliance, 1),
        "anomaly_penalty": anomaly_penalty,
        "issues": issues,
    }
```

- [ ] **Step 4: Create __init__.py with re-exports**

Create `app/engine/quality/__init__.py`:

```python
"""Quality analysis engine — rules, scoring, definitions."""
from .rules import ALL_RULES, dispatch_rule, run_all_rules, RuleResult, RuleStatus, Severity
from .scoring import calculate_quality_score
from .definitions import RATE_DEFINITIONS, INDICATOR_PARENT_MAP, UNIT_CONFIGS


def run_quality_analysis(values: dict, context: dict, custom_rules: list | None = None) -> dict:
    """Run full quality analysis pipeline.
    
    Orchestrates rule execution and quality scoring.
    """
    from .scoring import calculate_quality_score
    
    rule_results = run_all_rules(values, context, custom_rules)
    
    # Get anomaly results from context if available
    anomaly_results = context.get("anomaly_results", [])
    active_count = context.get("active_indicator_count", len(values))
    
    score = calculate_quality_score(rule_results, values, anomaly_results, active_count)
    
    return {
        "rule_results": rule_results,
        "quality_score": score,
    }


__all__ = [
    "run_quality_analysis",
    "run_all_rules",
    "dispatch_rule",
    "calculate_quality_score",
    "ALL_RULES",
    "RuleResult",
    "RuleStatus",
    "Severity",
    "RATE_DEFINITIONS",
    "INDICATOR_PARENT_MAP",
    "UNIT_CONFIGS",
]
```

- [ ] **Step 5: Update imports across the codebase**

Search for all imports of `app.engine.quality` and `app.engine.quality_score` and update them:

In `app/api/analysis.py`:
```python
# Old:
from app.engine.quality import run_full_analysis  # or similar
from app.engine.quality_score import calculate_quality_score

# New:
from app.engine.quality import run_quality_analysis, calculate_quality_score, ALL_RULES
```

In `app/api/reports.py`:
```python
# Old:
from app.engine.quality import ...

# New:
from app.engine.quality import ...
```

In `app/api/dashboard.py`:
```python
# Old:
from app.engine.quality import ...

# New:
from app.engine.quality import ...
```

In `app/engine/pipeline.py`:
```python
# Old:
from app.engine.quality import ...
from app.engine.quality_score import calculate_quality_score

# New:
from app.engine.quality import run_quality_analysis, calculate_quality_score
```

- [ ] **Step 6: Delete old files**

Delete `app/engine/quality.py` and `app/engine/quality_score.py` (merged into the package).

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_rules.py tests/test_quality_score.py -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add app/engine/quality/ app/api/analysis.py app/api/reports.py app/api/dashboard.py app/engine/pipeline.py
git rm app/engine/quality.py app/engine/quality_score.py
git commit -m "refactor: split quality.py into focused package (rules, scoring, definitions), remove duplicate"
```

---

### Task 4: Deduplicate Seeding Logic

**Files:**
- Modify: `app/main.py`
- Modify: `scripts/seed_indicators.py` — ensure it exports seed function
- Modify: `scripts/seed_rules.py` — ensure it exports seed function
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: None (independent task)
- Produces: `main.py` uses imported seed functions instead of duplicated code

- [ ] **Step 1: Read scripts/seed_indicators.py**

Read `scripts/seed_indicators.py` and identify the seeding logic. Ensure it has a callable function that can be imported:

```python
def seed_indicators(session=None):
    """Seed indicator tree from INDICATOR_FLAT_LIST."""
    # ... existing logic ...
    pass
```

If it doesn't have a function wrapper, add one.

- [ ] **Step 2: Read scripts/seed_rules.py**

Read `scripts/seed_rules.py` and ensure it has a callable function:

```python
def seed_rules(session=None):
    """Seed rules from RULES data."""
    # ... existing logic ...
    pass
```

- [ ] **Step 3: Update main.py to use imported seed functions**

In `app/main.py`, replace the `_seed_indicators()` and `_seed_rules()` functions with imports:

```python
# Old (remove these ~80 lines):
# def _seed_indicators():
#     ...
# def _seed_rules():
#     ...

# New:
from scripts.seed_indicators import seed_indicators
from scripts.seed_rules import seed_rules
```

Update the lifespan function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        seed_indicators(session)
        seed_rules(session)
    finally:
        session.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    yield
```

- [ ] **Step 4: Run integration tests**

Run: `python -m pytest tests/test_integration.py -v`
Expected: All tests pass (indicators and rules are still seeded correctly)

- [ ] **Step 5: Commit**

```bash
git add app/main.py scripts/seed_indicators.py scripts/seed_rules.py
git commit -m "refactor: deduplicate seeding logic — import from scripts instead of duplicating in main.py"
```

---

### Task 5: Split anomaly_trends.py into Package

**Files:**
- Create: `app/engine/anomaly/__init__.py`
- Create: `app/engine/anomaly/zscore.py`
- Create: `app/engine/anomaly/trends.py`
- Create: `app/engine/anomaly/comparison.py`
- Modify: `app/engine/anomaly_trends.py` → delete after split
- Modify: `app/api/analysis.py` — update imports
- Modify: `app/api/reports.py` — update imports
- Test: `tests/test_anomaly.py`

**Interfaces:**
- Consumes: Tasks 1-3 (bug fixes, quality split)
- Produces: `detect_anomalies()`, `analyze_historical_trends()`, `compare_hospitals()` re-exported from `app.engine.anomaly`

- [ ] **Step 1: Create zscore.py**

Extract z-score anomaly detection. Create `app/engine/anomaly/zscore.py`:

```python
"""Z-score based anomaly detection for cross-hospital comparison."""
from typing import Optional
import numpy as np


def detect_anomalies(
    values: dict[str, float],
    hospital_id: int,
    month: str,
    all_hospital_values: dict[int, dict[str, float]],
    z_threshold: float = 2.0,
) -> list[dict]:
    """Detect anomalies using cross-hospital z-scores.
    
    Args:
        values: Indicator values for this hospital/month
        hospital_id: Current hospital ID
        month: Month string (YYYY-MM)
        all_hospital_values: All hospitals' values {hospital_id: {indicator_code: value}}
        z_threshold: Z-score threshold for outlier detection
    
    Returns:
        List of anomaly result dicts
    """
    results = []
    
    for indicator_code, value in values.items():
        if value is None:
            continue
        
        # Collect values from all hospitals
        other_values = []
        for hid, hvals in all_hospital_values.items():
            if hid != hospital_id and hvals.get(indicator_code) is not None:
                other_values.append(hvals[indicator_code])
        
        if len(other_values) < 3:
            continue  # Need at least 3 data points
        
        mean = np.mean(other_values)
        std = np.std(other_values)
        
        if std == 0:
            continue
        
        z_score = (value - mean) / std
        is_outlier = abs(z_score) > z_threshold
        
        results.append({
            "indicator_code": indicator_code,
            "value": value,
            "mean": float(mean),
            "std": float(std),
            "z_score": float(z_score),
            "is_outlier": is_outlier,
            "hospital_id": hospital_id,
            "month": month,
        })
    
    return results
```

- [ ] **Step 2: Create trends.py**

Extract trend analysis. Create `app/engine/anomaly/trends.py`:

```python
"""Linear regression trend analysis for historical data."""
from typing import Optional
import numpy as np


def analyze_historical_trends(
    hospital_id: int,
    historical_data: list[dict],
    min_months: int = 6,
) -> dict:
    """Analyze historical trends using linear regression.
    
    Args:
        hospital_id: Hospital ID
        historical_data: List of {month, indicator_code, value} dicts
        min_months: Minimum months needed for trend analysis
    
    Returns:
        Trend analysis dict with trends, findings, slope percentages
    """
    # Group by indicator
    by_indicator: dict[str, list] = {}
    for row in historical_data:
        code = row["indicator_code"]
        by_indicator.setdefault(code, []).append(row)
    
    trends = []
    findings = []
    
    for code, rows in by_indicator.items():
        if len(rows) < min_months:
            findings.append(f"{code}: insufficient history ({len(rows)} < {min_months} months)")
            continue
        
        # Sort by month
        rows.sort(key=lambda r: r["month"])
        values = [r["value"] for r in rows if r["value"] is not None]
        
        if len(values) < min_months:
            continue
        
        # Linear regression
        x = np.arange(len(values))
        y = np.array(values)
        
        slope, intercept = np.polyfit(x, y, 1)
        r_squared = np.corrcoef(x, y)[0, 1] ** 2
        
        # Slope as percentage
        mean_val = np.mean(y)
        slope_pct = (slope / mean_val * 100) if mean_val != 0 else 0
        
        # Determine trend direction
        if abs(slope_pct) < 1:
            direction = "stable"
        elif slope_pct > 0:
            direction = "increasing"
        else:
            direction = "decreasing"
        
        trends.append({
            "indicator_code": code,
            "slope": float(slope),
            "slope_pct": float(slope_pct),
            "r_squared": float(r_squared),
            "direction": direction,
            "data_points": len(values),
        })
        
        # Add findings for significant trends
        if abs(slope_pct) > 5 and r_squared > 0.5:
            findings.append(f"{code}: {direction} trend ({slope_pct:+.1f}%/month, R²={r_squared:.2f})")
    
    return {
        "trends": trends,
        "findings": findings,
        "hospital_id": hospital_id,
    }


def detect_trend_anomalies(trend_result: dict, cv_threshold: float = 0.5) -> list[dict]:
    """Detect anomalies in trend data using coefficient of variation.
    
    Args:
        trend_result: Result from analyze_historical_trends
        cv_threshold: CV threshold for anomaly detection
    
    Returns:
        List of trend anomaly dicts
    """
    anomalies = []
    
    for trend in trend_result.get("trends", []):
        # High variability suggests data quality issues
        if trend.get("r_squared", 0) < 0.3 and trend.get("data_points", 0) > 6:
            anomalies.append({
                "indicator_code": trend["indicator_code"],
                "type": "high_variability",
                "r_squared": trend["r_squared"],
                "message": f"High variability in {trend['indicator_code']} (R²={trend['r_squared']:.2f})",
            })
    
    return anomalies
```

- [ ] **Step 3: Create comparison.py**

Extract hospital comparison logic. Create `app/engine/anomaly/comparison.py`:

```python
"""Hospital-to-hospital comparison logic."""
from typing import Optional
import numpy as np


def compare_hospitals(
    hospital_id_1: int,
    hospital_id_2: int,
    month: str,
    values_1: dict[str, float],
    values_2: dict[str, float],
) -> list[dict]:
    """Compare two hospitals' indicator values.
    
    Args:
        hospital_id_1: First hospital ID
        hospital_id_2: Second hospital ID
        month: Month string
        values_1: First hospital's values
        values_2: Second hospital's values
    
    Returns:
        List of comparison dicts
    """
    comparisons = []
    
    all_codes = set(values_1.keys()) | set(values_2.keys())
    
    for code in all_codes:
        v1 = values_1.get(code)
        v2 = values_2.get(code)
        
        if v1 is None or v2 is None:
            continue
        
        if v2 == 0:
            deviation_pct = float("inf") if v1 != 0 else 0
        else:
            deviation_pct = ((v1 - v2) / v2) * 100
        
        comparisons.append({
            "indicator_code": code,
            "hospital_1_value": v1,
            "hospital_2_value": v2,
            "deviation_pct": deviation_pct,
        })
    
    return comparisons


def compare_all_hospitals(
    month: str,
    all_values: dict[int, dict[str, float]],
) -> dict[str, list]:
    """Compare all hospitals for a given month.
    
    Args:
        month: Month string
        all_values: All hospitals' values
    
    Returns:
        Dict with per-indicator statistics across hospitals
    """
    # Collect all indicator codes
    all_codes = set()
    for vals in all_values.values():
        all_codes.update(vals.keys())
    
    result = {}
    
    for code in all_codes:
        values = []
        for vals in all_values.values():
            if vals.get(code) is not None:
                values.append(vals[code])
        
        if len(values) < 2:
            continue
        
        result[code] = {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "count": len(values),
        }
    
    return result
```

- [ ] **Step 4: Create __init__.py with re-exports**

Create `app/engine/anomaly/__init__.py`:

```python
"""Anomaly detection and trend analysis engine."""
from .zscore import detect_anomalies
from .trends import analyze_historical_trends, detect_trend_anomalies
from .comparison import compare_hospitals, compare_all_hospitals


__all__ = [
    "detect_anomalies",
    "analyze_historical_trends",
    "detect_trend_anomalies",
    "compare_hospitals",
    "compare_all_hospitals",
]
```

- [ ] **Step 5: Update imports**

In `app/api/analysis.py`:
```python
# Old:
from app.engine.anomaly_trends import detect_anomalies, analyze_historical_trends

# New:
from app.engine.anomaly import detect_anomalies, analyze_historical_trends, compare_hospitals
```

In `app/api/reports.py` and `app/api/dashboard.py`:
```python
# Old:
from app.engine.anomaly_trends import ...

# New:
from app.engine.anomaly import ...
```

- [ ] **Step 6: Delete old file**

Delete `app/engine/anomaly_trends.py`.

- [ ] **Step 7: Run anomaly tests**

Run: `python -m pytest tests/test_anomaly.py -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add app/engine/anomaly/ app/api/analysis.py app/api/reports.py app/api/dashboard.py
git rm app/engine/anomaly_trends.py
git commit -m "refactor: split anomaly_trends.py into focused package (zscore, trends, comparison)"
```

---

### Task 6: Split AI Plugin + hospitals.py API

**Files:**
- Create: `app/plugins/ai/__init__.py`
- Create: `app/plugins/ai/providers.py`
- Create: `app/plugins/ai/prompts.py`
- Create: `app/plugins/ai/cache.py`
- Create: `app/api/indicator_config.py`
- Create: `app/api/tree_config.py`
- Modify: `app/plugins/ai.py` → delete after split
- Modify: `app/api/hospitals.py` → reduce to CRUD only
- Modify: `app/main.py` — register new routers
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: Tasks 1-5 (all previous splits)
- Produces: AI provider classes, indicator config API, tree config API

- [ ] **Step 1: Split AI plugin**

Read `app/plugins/ai.py` and split into:

`app/plugins/ai/providers.py`:
```python
"""AI provider implementations — OpenAI, Anthropic, local."""
import httpx
from typing import Optional


class AIProvider:
    """Base AI provider interface."""
    
    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4"):
        self.api_key = api_key
        self.model = model
    
    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "claude-3-sonnet"):
        self.api_key = api_key
        self.model = model
    
    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]


def get_provider(provider_type: str, api_key: str, model: str) -> AIProvider:
    """Factory function to get the appropriate AI provider."""
    if provider_type == "openai":
        return OpenAIProvider(api_key, model)
    elif provider_type == "anthropic":
        return AnthropicProvider(api_key, model)
    else:
        raise ValueError(f"Unknown provider: {provider_type}")
```

`app/plugins/ai/prompts.py`:
```python
"""Prompt builders for clinical and root cause analysis."""


def build_clinical_prompt(data: dict) -> str:
    """Build prompt for clinical analysis recommendations."""
    return f"""Analyze the following clinical data and provide recommendations:
    
    Hospital: {data.get('hospital', 'Unknown')}
    Month: {data.get('month', 'Unknown')}
    Risk Level: {data.get('risk_level', 'Unknown')}
    
    Classifications:
    {data.get('classifications', [])}
    
    Provide:
    1. Key findings
    2. Priority recommendations
    3. Action items
    """


def build_root_cause_prompt(data: dict) -> str:
    """Build prompt for root cause analysis."""
    return f"""Analyze the following data quality issues and identify root causes:
    
    Hospital: {data.get('hospital', 'Unknown')}
    Month: {data.get('month', 'Unknown')}
    Quality Score: {data.get('quality_score', 'N/A')}
    
    Rule Failures:
    {data.get('rule_failures', [])}
    
    Provide:
    1. Root cause analysis
    2. Contributing factors
    3. Recommended corrective actions
    """
```

`app/plugins/ai/cache.py`:
```python
"""AI response caching with TTL."""
import time
from typing import Optional


class AICache:
    """Simple TTL cache for AI responses."""
    
    def __init__(self, ttl: int = 3600):
        self._cache: dict[str, tuple[float, str]] = {}
        self._ttl = ttl
    
    def get(self, key: str) -> Optional[str]:
        """Get cached response if not expired."""
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value: str):
        """Cache a response."""
        self._cache[key] = (time.time(), value)
    
    def clear(self):
        """Clear all cached responses."""
        self._cache.clear()


ai_cache = AICache()
```

`app/plugins/ai/__init__.py`:
```python
"""AI plugin — provider management, prompts, caching."""
from .providers import get_provider, AIProvider, OpenAIProvider, AnthropicProvider
from .prompts import build_clinical_prompt, build_root_cause_prompt
from .cache import ai_cache, AICache


__all__ = [
    "get_provider",
    "AIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "build_clinical_prompt",
    "build_root_cause_prompt",
    "ai_cache",
    "AICache",
]
```

- [ ] **Step 2: Create indicator_config.py API**

Create `app/api/indicator_config.py`:

```python
"""Indicator configuration API — enable/disable, bulk toggle."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import HospitalIndicatorConfig, Indicator

router = APIRouter(tags=["indicator-config"])


@router.get("/hospitals/indicators")
def list_indicators(db: Session = Depends(get_db)):
    """List all indicators with their configuration status."""
    indicators = db.query(Indicator).all()
    return [{"id": i.id, "code": i.code, "name": i.name, "level": i.level} for i in indicators]


@router.get("/hospitals/{hospital_id}/indicators")
def get_hospital_indicators(hospital_id: int, db: Session = Depends(get_db)):
    """Get indicator configuration for a specific hospital."""
    configs = db.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id == hospital_id
    ).all()
    return [{"indicator_id": c.indicator_id, "enabled": c.enabled} for c in configs]


@router.put("/hospitals/{hospital_id}/indicators/{indicator_id}/toggle")
def toggle_indicator(hospital_id: int, indicator_id: int, db: Session = Depends(get_db)):
    """Toggle an indicator's enabled status for a hospital."""
    config = db.query(HospitalIndicatorConfig).filter_by(
        hospital_id=hospital_id, indicator_id=indicator_id
    ).first()
    
    if not config:
        config = HospitalIndicatorConfig(
            hospital_id=hospital_id,
            indicator_id=indicator_id,
            enabled=True,
        )
        db.add(config)
    else:
        config.enabled = not config.enabled
    
    db.commit()
    return {"indicator_id": indicator_id, "enabled": config.enabled}


@router.post("/hospitals/indicators/bulk-toggle")
def bulk_toggle_indicators(
    hospital_ids: list[int],
    indicator_id: int,
    enabled: bool,
    db: Session = Depends(get_db),
):
    """Bulk toggle an indicator for multiple hospitals."""
    for hospital_id in hospital_ids:
        config = db.query(HospitalIndicatorConfig).filter_by(
            hospital_id=hospital_id, indicator_id=indicator_id
        ).first()
        
        if not config:
            config = HospitalIndicatorConfig(
                hospital_id=hospital_id,
                indicator_id=indicator_id,
                enabled=enabled,
            )
            db.add(config)
        else:
            config.enabled = enabled
    
    db.commit()
    return {"updated": len(hospital_ids), "enabled": enabled}
```

- [ ] **Step 3: Create tree_config.py API**

Create `app/api/tree_config.py`:

```python
"""Tree configuration API — reparent, save, re-analyze."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, Indicator

router = APIRouter(tags=["tree-config"])


@router.get("/hospitals/{hospital_id}/indicator-tree")
def get_indicator_tree(hospital_id: int, month: str, db: Session = Depends(get_db)):
    """Get the indicator tree for a hospital/month."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(404, "Hospital not found")
    
    # Build tree from indicators
    indicators = db.query(Indicator).all()
    tree = _build_tree(indicators, hospital_id, month, db)
    return tree


@router.post("/hospitals/{hospital_id}/re-analyze")
def reanalyze_hospital(hospital_id: int, month: str, db: Session = Depends(get_db)):
    """Re-run analysis for a specific hospital/month."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(404, "Hospital not found")
    
    # Trigger re-analysis
    # This would call the pipeline
    return {"status": "queued", "hospital_id": hospital_id, "month": month}


@router.post("/hospitals/{hospital_id}/save-tree-config")
def save_tree_config(hospital_id: int, month: str, db: Session = Depends(get_db)):
    """Save the current tree configuration."""
    return {"status": "saved", "hospital_id": hospital_id, "month": month}


def _build_tree(indicators, hospital_id, month, db):
    """Build indicator tree structure."""
    # Copy tree building logic from hospitals.py
    pass
```

- [ ] **Step 4: Update hospitals.py to CRUD only**

Read `app/api/hospitals.py` and remove indicator config and tree config endpoints (moved to new files). Keep only:
- `GET /hospitals/` — list hospitals
- `POST /hospitals/` — create hospital
- `GET /hospitals/{id}` — get hospital
- `PUT /hospitals/{id}` — update hospital
- `DELETE /hospitals/{id}` — delete hospital
- `GET /hospitals/months` — list months with data

- [ ] **Step 5: Register new routers in main.py**

In `app/main.py`, add:
```python
from app.api import indicator_config, tree_config

app.include_router(indicator_config.router)
app.include_router(tree_config.router)
```

- [ ] **Step 6: Delete old ai.py**

Delete `app/plugins/ai.py` after confirming the split works.

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_integration.py -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add app/plugins/ai/ app/api/indicator_config.py app/api/tree_config.py app/api/hospitals.py app/main.py
git rm app/plugins/ai.py
git commit -m "refactor: split AI plugin and hospitals API into focused modules"
```

---

### Task 7: Add Alembic Migrations

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/001_initial_schema.py`
- Create: `alembic/versions/002_seed_indicators.py`
- Create: `alembic/versions/003_seed_rules.py`
- Modify: `app/database.py` — remove _migrate_schema
- Modify: `app/main.py` — replace _migrate_schema with alembic upgrade
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: Tasks 1-6 (all previous refactoring)
- Produces: Alembic migration infrastructure, clean startup flow

- [ ] **Step 1: Install Alembic**

Add to `requirements.txt`:
```
alembic
```

Run: `pip install alembic`

- [ ] **Step 2: Initialize Alembic**

Run: `alembic init alembic`

This creates:
- `alembic.ini` — configuration file
- `alembic/` directory with `env.py`, `script.py.mako`, `versions/`

- [ ] **Step 3: Configure alembic.ini**

Edit `alembic.ini`:
```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:///data/health_ai.db
```

- [ ] **Step 4: Configure alembic/env.py**

Edit `alembic/env.py`:
```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.models import Base  # Import your SQLAlchemy Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Generate initial migration**

Run: `alembic revision --autogenerate -m "initial schema"`

Review the generated migration in `alembic/versions/`. Ensure it matches the current schema.

- [ ] **Step 6: Update database.py**

In `app/database.py`, remove `_migrate_schema()` function. Keep only:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Initialize database engine and session factory."""
    # Enable WAL mode for SQLite
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()


def get_db():
    """FastAPI dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 7: Update main.py lifespan**

In `app/main.py`, update the lifespan function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    
    # Run Alembic migrations
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    
    # Seed data
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        seed_indicators(session)
        seed_rules(session)
    finally:
        session.close()
    
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    yield
```

- [ ] **Step 8: Run integration tests**

Run: `python -m pytest tests/test_integration.py -v`
Expected: All tests pass (database is migrated via Alembic instead of raw SQL)

- [ ] **Step 9: Commit**

```bash
git add alembic/ alembic.ini app/database.py app/main.py requirements.txt
git commit -m "feat: add Alembic migrations, remove raw SQL _migrate_schema"
```

---

### Task 8: Expand Test Coverage

**Files:**
- Create: `tests/test_pipeline.py`
- Create: `tests/test_confidence.py`
- Create: `tests/test_root_cause.py`
- Create: `tests/test_api_hospitals.py`
- Create: `tests/test_api_rules.py`
- Create: `tests/test_api_config.py`
- Create: `tests/test_api_file_ops.py`
- Modify: `requirements.txt` — add pytest-cov

**Interfaces:**
- Consumes: Tasks 1-7 (all refactoring complete)
- Produces: Comprehensive test suite with 80%+ coverage

- [ ] **Step 1: Add pytest-cov to requirements**

Add to `requirements.txt`:
```
pytest-cov
```

- [ ] **Step 2: Create test_pipeline.py**

```python
"""Tests for the analysis pipeline orchestrator."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, init_db


@pytest.fixture
def client():
    init_db()
    return TestClient(app)


def test_pipeline_run_full_analysis(client, sample_values):
    """Test that run_full_analysis completes successfully."""
    # Upload data
    response = client.post("/upload/", files={"file": ("test.xlsx", b"...", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    # Or use the analysis endpoint directly
    
    # Verify analysis completes
    assert response.status_code == 200
    data = response.json()
    assert "reports" in data or "message" in data


def test_pipeline_caching(client):
    """Test that repeated analysis uses cache."""
    # First run
    response1 = client.post("/analysis/run-full")
    assert response1.status_code == 200
    
    # Second run (should use cache)
    response2 = client.post("/analysis/run-full")
    assert response2.status_code == 200


def test_pipeline_force_rerun(client):
    """Test that force rerun bypasses cache."""
    response = client.post("/analysis/run-full?force=true")
    assert response.status_code == 200


def test_pipeline_no_data(client):
    """Test pipeline with no data."""
    response = client.get("/analysis/outliers")
    assert response.status_code == 200
    data = response.json()
    # Should return empty or paginated response with 0 items
    assert len(data.get("data", data)) == 0
```

- [ ] **Step 3: Create test_confidence.py**

```python
"""Tests for confidence scoring engine."""
import pytest
from app.engine.confidence import calculate_confidence, SIGNAL_WEIGHTS


def test_confidence_basic(sample_values):
    """Test basic confidence calculation."""
    result = calculate_confidence(sample_values)
    assert "score" in result
    assert 0 <= result["score"] <= 100


def test_confidence_signals(sample_values):
    """Test that all 5 signals are calculated."""
    result = calculate_confidence(sample_values)
    assert "signals" in result
    assert len(result["signals"]) == 5


def test_confidence_missing_data():
    """Test confidence with missing data."""
    result = calculate_confidence({})
    assert result["score"] == 0


def test_confidence_weights():
    """Test that weights sum to 1.0."""
    total = sum(SIGNAL_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001
```

- [ ] **Step 4: Create test_root_cause.py**

```python
"""Tests for root cause analysis."""
import pytest
from app.engine.root_cause import analyze_root_cause


def test_root_cause_basic(sample_values):
    """Test basic root cause analysis."""
    result = analyze_root_cause(sample_values)
    assert "causes" in result
    assert "recommendations" in result


def test_root_cause_empty():
    """Test root cause with empty data."""
    result = analyze_root_cause({})
    assert "causes" in result
```

- [ ] **Step 5: Create test_api_hospitals.py**

```python
"""Tests for hospital API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_hospitals(client):
    """Test GET /hospitals/."""
    response = client.get("/hospitals/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_hospital(client):
    """Test GET /hospitals/{id}."""
    response = client.get("/hospitals/1")
    assert response.status_code in (200, 404)


def test_list_hospital_months(client):
    """Test GET /hospitals/months."""
    response = client.get("/hospitals/months")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

- [ ] **Step 6: Create test_api_rules.py**

```python
"""Tests for rules API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_rules(client):
    """Test GET /rules/."""
    response = client.get("/rules/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0  # Rules are seeded


def test_toggle_rule(client):
    """Test PUT /rules/{id}/toggle."""
    response = client.get("/rules/")
    rules = response.json()
    if rules:
        rule_id = rules[0]["id"]
        response = client.put(f"/rules/{rule_id}/toggle")
        assert response.status_code == 200
```

- [ ] **Step 7: Create test_api_config.py**

```python
"""Tests for config API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_config(client):
    """Test GET /config/."""
    response = client.get("/config/")
    assert response.status_code == 200


def test_get_ai_settings(client):
    """Test GET /config/ai/settings."""
    response = client.get("/config/ai/settings")
    assert response.status_code == 200
```

- [ ] **Step 8: Create test_api_file_ops.py**

```python
"""Tests for file operations API."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_saved_files(client):
    """Test GET /analysis/saved-files."""
    response = client.get("/analysis/saved-files")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

- [ ] **Step 9: Run all tests with coverage**

Run: `python -m pytest tests/ -v --cov=app --cov-report=term-missing`
Expected: All tests pass, coverage >= 80%

- [ ] **Step 10: Commit**

```bash
git add tests/test_pipeline.py tests/test_confidence.py tests/test_root_cause.py tests/test_api_hospitals.py tests/test_api_rules.py tests/test_api_config.py tests/test_api_file_ops.py requirements.txt
git commit -m "test: expand test coverage to 80%+ (pipeline, confidence, root_cause, API endpoints)"
```

---

### Task 9: Final Cleanup and Verification

**Files:**
- Modify: `requirements.txt` — add ruff
- Create: `.pre-commit-config.yaml` (optional)
- Modify: All files — fix any remaining lint issues

**Interfaces:**
- Consumes: All previous tasks
- Produces: Clean, linted codebase with passing tests

- [ ] **Step 1: Add ruff to requirements**

Add to `requirements.txt`:
```
ruff
```

- [ ] **Step 2: Run ruff**

Run: `ruff check app/ tests/`
Fix any issues found.

- [ ] **Step 3: Run final test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (should be 200+ tests now)

- [ ] **Step 4: Run coverage report**

Run: `python -m pytest tests/ --cov=app --cov-report=html`
Open the HTML report and verify coverage >= 80%.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: final cleanup — ruff linting, coverage verification"
```

---

## Task Dependencies

```
Task 1 (Bug Fixes) ──────────────────────────────────────────────┐
Task 2 (Clinical Split) ──── parallel ──── Task 3 (Quality Split) │
Task 5 (Anomaly Split) ──────────────────────────────────────────┤
Task 4 (Seed Dedup) ─────────────────────────────────────────────┤
Task 6 (AI + API Split) ─────────────────────────────────────────┤
Task 7 (Alembic) ────────────────────────────────────────────────┤
Task 8 (Tests) ──────────────────────────────────────────────────┤
Task 9 (Cleanup) ────────────────────────────────────────────────┘
```

Tasks 1-3 are independent and can run in parallel. Tasks 4-6 depend on 1-3 being complete. Task 7 depends on all splits being complete (imports must be stable). Task 8 depends on all refactoring being complete. Task 9 is final verification.

## Global Constraints Reminder

- All tests must pass after each task
- No breaking API changes
- Follow existing patterns
- TDD for new code
- DRY, YAGNI, frequent commits
