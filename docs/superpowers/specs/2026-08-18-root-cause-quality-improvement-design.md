# Root Cause Analysis Quality Improvement Design

**Date:** 2026-08-18
**Status:** Approved
**Author:** AI Assistant

---

## Overview

Improve the quality of root cause analysis outputs on the Root Cause Analysis screen. This plan has two components:

1. **Dynamic rule diagnosis system** — Expand beyond the 12 hardcoded rules to dynamically diagnose any rule failure with specific causes and recommendations (Arabic + English).
2. **Peer governorates display** — Show which governorates and hospital types the peer hospitals belong to in the peer comparison section.

---

## Current State

### Component 1: Rule Diagnosis (`app/engine/root_cause.py`)

- `_diagnose_rule_failure()` (line 856) uses a **hardcoded cause map** covering only ~12 rules:
  - R001, R002, R004, R005, R041, R042, R051, R052, R054, R055, R058, R059
- Rules not in the map fall back to 4 generic text patterns:
  - "exceeds" → value exceeds threshold
  - "missing" → required indicator not reported
  - "negative" → negative value reported
  - "decimal" → decimal value in count field
- All other rules return the generic: *"Rule validation check failed"*
- `_diagnose_rule_failure_ar()` (line 901) is the Arabic mirror with the same limitation.
- `_extract_rule_structure()` (line 573) already reads `rules.params` JSON and builds `{rule_code: {total, parts}}`, but it is only used for causal chain building — not for diagnosis.
- The `rules` table contains the rule type (`rule_type`) and parameter structure (`params`).

### Component 2: Peer Governorates (`app/engine/root_cause.py`)

- `PeerIndicatorComparison` dataclass (line 140) currently has:
  - `indicator_code`, `indicator_name`, `hospital_value`, `peer_group`, `peer_count`, `peer_mean`, `peer_std`, `hospital_percentile`, `hospital_z_score`, `gap_pct`
- **No governorate or hospital type breakdown** of the peer hospitals.
- Peer comparisons are built in `generate_root_cause_analysis()` (line 1434-1477) using `_load_hospital_data()` from `app/engine/smart/__init__.py` (line 16), which already provides `governorate` and `hospital_type` per hospital — but this data is discarded.
- `app/api/root_cause.py` serializes `peer_comparisons` (line 260-274) but the new fields are not included.
- The frontend (`static/js/settings.js`) renders `peer_comparisons` in the `rcPeerComparisons` element showing only hospital value vs peer mean.

---

## Design: Component 1 — Dynamic Rule Diagnosis System

### Architecture

Three-level diagnosis, in priority order:

```
Level 1: Explicit map  →  Level 2: Dynamic structure  →  Level 3: Details text
(hardcoded known rules)  (read rules.params)           (regex on details)
```

### Level 1: Explicit Cause Map (existing, extended)

Keep the existing 12-rule map. Add additional rules found in the `rules` table. Each entry has `(cause, recommendation)` in both languages.

### Level 2: Dynamic Structure Diagnosis (new)

New function `_extract_rule_type(params: Dict) -> str` classifies a rule by its `params` shape:

| Type | Detection | Diagnosis (English) | Diagnosis (Arabic) |
|------|-----------|--------------------|--------------------|
| `SUM` | has `children` list | "Sub-indicators {parts} don't sum to total {total}. Check for missing or duplicate sub-indicator reporting." | "المؤشرات الفرعية {parts} لا تجمع للإجمالي {total}. تحقق من نقص أو تكرار الإبلاغ عن مؤشر فرعي." |
| `PART` | has `parent` + `child` | "Component {child} doesn't reconcile with total {parent}. Verify the component is correctly classified." | "المكوّن {child} لا يتطابق مع الإجمالي {parent}. تحقق من صحة تصنيف المكوّن." |
| `RATE` | has `num_code` + `den_code` | "Rate numerator {num} vs denominator {den} outside expected bounds. Review the raw counts." | "نسبة البسط {num} إلى المقام {den} خارج الحدود المتوقعة. راجع القيم الخام." |
| `EXISTS` | has `parent` only, no children | "Required indicator {total} missing or not reported. Confirm submission completeness." | "المؤشر المطلوب {total} غير مُبلّغ. تأكد من اكتمال الإرسال." |

### Level 3: Details Text Patterns (enhanced)

Expand the current 4 patterns to also catch:
- "duplicate" / "مكرر" → duplicate reporting
- "zero" / "صفر" → zero value for non-zero-expected indicator
- "mismatch" / "لا يطابق" → reconciliation mismatch
- "inconsistent" / "غير متسق" → inconsistent values

### New Functions

```python
def _extract_rule_type(params: dict) -> str:
    """Classify rule as SUM / PART / RATE / EXISTS from params shape."""

def _build_dynamic_diagnosis(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Generate (cause, recommendation) from rule structure. Returns ("", "") if no structure."""

def _diagnose_rule_failure_v2(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Level 1 → Level 2 → Level 3 diagnosis (English)."""

def _diagnose_rule_failure_v2_ar(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Level 1 → Level 2 → Level 3 diagnosis (Arabic)."""
```

### Integration

`analyze_rule_failures()` (line 810) will:
1. Fetch the rule's `params` alongside `rule_type` in its SQL query.
2. Parse `params` JSON once.
3. Call `_diagnose_rule_failure_v2()` for English and `_diagnose_rule_failure_v2_ar()` for Arabic.
4. Store both in the `RuleFailurePattern` (add `primary_cause_ar` field).

### Data Structure Change

```python
@dataclass
class RuleFailurePattern:
    # existing fields...
    primary_cause_ar: str = ""   # NEW
```

---

## Design: Component 2 — Peer Governorates Display

### Data Structure Change

```python
@dataclass
class PeerIndicatorComparison:
    # existing fields...
    peer_governorates: List[str] = field(default_factory=list)        # NEW
    peer_governorate_counts: Dict[str, int] = field(default_factory=dict)  # NEW
    peer_types: List[str] = field(default_factory=list)               # NEW
```

### Collection Logic

In `generate_root_cause_analysis()` (line 1434-1477), while iterating `month_data.items()`:
- For each peer hospital entry (not the current hospital), capture:
  - `entry["governorate"]` (name) → append to `peer_governorates`, increment `peer_governorate_counts[gov]`
  - `entry["hospital_type"]` → append to `peer_types` (deduplicated)
- Pass these lists into the `PeerIndicatorComparison` constructor.

### API Serialization

In `app/api/root_cause.py` (line 260-274), add to the `peer_comparisons` serialization:
- `peer_governorates`
- `peer_governorate_counts`
- `peer_types`

### Frontend Display

In `static/js/settings.js` (the `rcPeerComparisons` render, ~line 490-511), extend each comparison row to show:
```
المستشفى X مقابل متوسط النظير Y (Z مستشفى) — مئوية P | z=Q
النظير: محافظات: غزة (3)، خان يونس (2) | أنواع: حكومي (4)، أهلي (1)
```
Built from `peer_governorate_counts` (sorted desc by count) and `peer_types`.

---

## Files to Modify

| File | Change |
|------|--------|
| `app/engine/root_cause.py` | Add `_extract_rule_type`, `_build_dynamic_diagnosis`, `_diagnose_rule_failure_v2`, `_diagnose_rule_failure_v2_ar`; extend map; add `primary_cause_ar`; extend `PeerIndicatorComparison`; collect peer governorates/types |
| `app/api/root_cause.py` | Serialize new peer fields |
| `static/js/settings.js` | Render peer governorates/types in `rcPeerComparisons` |

---

## Tests

- `tests/test_root_cause.py` — add tests for:
  - `_diagnose_rule_failure_v2` covers Level 1, Level 2 (all 4 types), Level 3 patterns
  - `_diagnose_rule_failure_v2_ar` Arabic outputs
  - `_extract_rule_type` classification for each shape
  - `analyze_rule_failures` includes `primary_cause_ar`
- `tests/test_root_cause_improvements.py` — add tests for:
  - `PeerIndicatorComparison` carries `peer_governorates`/`peer_types`
  - API response includes new fields
- `tests/test_export.py` — verify frontend renders peer governorates

---

## Success Criteria

1. ✅ Any rule failure gets a specific diagnosis (no generic fallback for structured rules)
2. ✅ Both English and Arabic causes/recommendations are produced
3. ✅ Peer comparison shows governorate and type breakdown
4. ✅ All existing tests pass
5. ✅ No regression in causal chain building

---

## Out of Scope

- Governorate-level analysis (selecting a governorate instead of a hospital) — separate plan
- Causal inference improvements (Granger/lag analysis) — future work
- Integration of smart analytics (XGBoost, patterns) into root cause — future work
