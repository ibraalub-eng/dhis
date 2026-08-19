# Root Cause Analysis Quality Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve RCA analysis quality via a three-level dynamic rule diagnosis system (English + Arabic) and display peer governorates/types in the peer comparison section.

**Architecture:** Backend `app/engine/root_cause.py` gains `_extract_rule_type`, `_build_dynamic_diagnosis`, `_diagnose_rule_failure_v2`, `_diagnose_rule_failure_v2_ar`. `analyze_rule_failures()` fetches `r.params` and passes params through to the new diagnosis functions. `PeerIndicatorComparison` gains `peer_governorates`, `peer_governorate_counts`, `peer_types` populated from `_load_hospital_data()` entries. API serializes new fields; frontend `static/js/settings.js` renders them.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / SQLite, vanilla JS (ES modules), pytest.

## Global Constraints

- Do NOT remove Plotly.js from `static/index.html` — still used by smart-analytics.js and validation.js.
- Chart.js is already loaded via `static/vendor/chart.umd.min.js` — no new chart work in this plan.
- All user-facing UI strings on this screen are Arabic; backend causes/recommendations are bilingual (English + Arabic).
- Tests run with `python -m pytest tests/... -q`.
- Follow existing patterns in `app/engine/root_cause.py` (dataclasses, `text()` SQL, `Tuple[str, str]` returns).

---

### Task 1: Add `primary_cause_ar` field and API serialization

**Files:**
- Modify: `app/engine/root_cause.py:36-47` (RuleFailurePattern dataclass)
- Modify: `app/api/root_cause.py:182-192` (top_rule_failures serialization)

**Interfaces:**
- Produces: `RuleFailurePattern.primary_cause_ar: str` — Arabic cause text, default `""`.
- Produces: API response `top_rule_failures[].primary_cause_ar`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py`:

```python
def test_api_returns_primary_cause_ar(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, ValidationResult

    h = Hospital(name="ARHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R041",
        rule_description="C-section rate", status="FAIL",
        severity="HIGH", rule_type="BENCHMARK",
    ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(f"/root-cause/{h.id}?month=2026-06")
        assert resp.status_code == 200
        data = resp.json()
        failures = data["top_rule_failures"]
        assert len(failures) >= 1
        assert "primary_cause_ar" in failures[0]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_api_returns_primary_cause_ar -q`
Expected: FAIL with `KeyError: 'primary_cause_ar'` or assertion error.

- [ ] **Step 3: Add field to dataclass**

In `app/engine/root_cause.py`, change `RuleFailurePattern`:

```python
@dataclass
class RuleFailurePattern:
    rule_code: str
    rule_description: str
    severity: str
    failure_count: int
    total_runs: int
    failure_rate: float
    primary_cause: str
    recommendation: str
    rule_type: str = "LOGIC"
    primary_cause_ar: str = ""
```

- [ ] **Step 4: Serialize in API**

In `app/api/root_cause.py`, inside the `top_rule_failures` list comprehension add:

```python
                "primary_cause": f.primary_cause,
                "recommendation": f.recommendation,
                "primary_cause_ar": f.primary_cause_ar,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_api_returns_primary_cause_ar -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/engine/root_cause.py app/api/root_cause.py tests/test_root_cause_improvements.py
git commit -m "feat: add primary_cause_ar field to RuleFailurePattern"
```

---

### Task 2: Refactor cause maps into module constants

**Files:**
- Modify: `app/engine/root_cause.py:856-944` (`_diagnose_rule_failure`, `_diagnose_rule_failure_ar`)

**Interfaces:**
- Produces: module constants `_CAUSE_MAP: Dict[str, Tuple[str, str]]` and `_CAUSE_MAP_AR: Dict[str, Tuple[str, str]]` (English and Arabic).
- Consumes: none (self-contained refactor). Preserves existing public signatures `_diagnose_rule_failure(rule_code, details) -> Tuple[str, str]` and `_diagnose_rule_failure_ar(rule_code, details) -> Tuple[str, str]`.

- [ ] **Step 1: Verify existing tests pass before refactor**

Run: `python -m pytest tests/test_root_cause.py::TestDiagnoseRuleFailure -q`
Expected: 9 passed

- [ ] **Step 2: Extract English cause map**

In `app/engine/root_cause.py`, replace the inline `cause_map` dict in `_diagnose_rule_failure` (lines 857-882) with a module-level constant placed just above the function:

```python
_CAUSE_MAP: Dict[str, Tuple[str, str]] = {
    "R001": ("Parent-child sum mismatch: sub-indicators don't add up to total",
             "Verify all sub-categories are reported. Check if any sub-indicator is missing or miscoded."),
    "R002": ("Parity breakdown doesn't match total deliveries",
             "Review primigravida/multigravida data entry. Ensure both fields are filled."),
    "R004": ("Facility type breakdown mismatch",
             "Confirm in-facility vs out-of-facility classification is correct."),
    "R005": ("Risk classification mismatch",
             "Verify low-risk/high-risk classification criteria are consistently applied."),
    "R041": ("C-section rate exceeds safe threshold",
             "Review indication for C-sections. Consider audit of unnecessary C-sections."),
    "R042": ("Normal delivery rate too low",
             "Investigate if NVDs are being under-reported or misclassified as C-sections."),
    "R051": ("Deliveries spiked >2x compared to previous month",
             "Verify data accuracy. Could indicate duplicate reporting or a real surge (e.g., referral influx)."),
    "R052": ("Deliveries dropped >50% from previous month",
             "Check if data was fully reported. Could indicate data collection gap."),
    "R054": ("Maternal deaths surged above threshold",
             "CRITICAL: Immediate investigation required. Review each maternal death case."),
    "R055": ("Neonatal deaths surged above threshold",
             "CRITICAL: Immediate investigation required. Review neonatal care protocols."),
    "R058": ("Total Deliveries indicator is missing",
             "Core indicator not reported. Facility may not have submitted complete data."),
    "R059": ("Live Births indicator is missing",
             "Core indicator not reported. Required for neonatal mortality rate calculation."),
    "R003": ("Age-group breakdown doesn't sum to total deliveries",
             "Verify all age-group fields are filled and sum to Total Deliveries."),
    "R006": ("Emergency + Planned C-sections don't sum to Total C-sections",
             "Review the emergency/planned C-section split. Both sub-fields must sum to the total."),
    "R060": ("All key indicators reported as zero — facility may be non-operational or data missing",
             "CRITICAL: Confirm whether the facility operated this month; if it did, verify submission completeness."),
}
```

Then update `_diagnose_rule_failure`:

```python
def _diagnose_rule_failure(rule_code: str, details: str) -> Tuple[str, str]:
    if rule_code in _CAUSE_MAP:
        return _CAUSE_MAP[rule_code]
    low = details.lower()
    if "exceeds" in low or ">" in details or "duplicate" in low:
        return ("Value exceeds expected threshold or is duplicated",
                "Review the data value. If accurate, investigate underlying causes.")
    if "missing" in low or "not reported" in low:
        return ("Required indicator value not reported",
                "Ensure all mandatory indicators are filled before submission.")
    if "negative" in low:
        return ("Negative value reported for count indicator",
                "Negative counts are impossible. Check data entry for sign errors.")
    if "decimal" in low:
        return ("Decimal value reported for count field",
                "Counts must be integers. Check if value was incorrectly entered.")
    if "zero" in low or "all zeros" in low:
        return ("Zero value reported for an indicator expected to be non-zero",
                "Verify the facility was operational and data was fully reported.")
    if "mismatch" in low or "inconsistent" in low:
        return ("Reported values are inconsistent or mismatched",
                "Reconcile the reported values against source records.")
    return ("Rule validation check failed",
            "Review the specific indicator values and verify against source records.")
```

- [ ] **Step 3: Extract Arabic cause map**

Add module constant `_CAUSE_MAP_AR` with the same 15 keys (12 existing + R003, R006, R060) using the Arabic texts from lines 904-927 for the existing 12, plus:

```python
    "R003": ("تفصيل الفئات العمرية لا يطابق إجمالي الولادات",
             "تحقق من ملء جميع حقول الفئات العمرية ومطابقتها لإجمالي الولادات."),
    "R006": ("مجموع القيصرية الطارئة والمخطط لها لا يطابق إجمالي العمليات القيصرية",
             "راجع توزيع العمليات القيصرية؛ يجب أن يطابق مجموع الحقلين الإجمالي."),
    "R060": ("جميع المؤشرات الرئيسية صفر — قد تكون المنشأة غير عاملة أو البيانات مفقودة",
             "حرج: تحقق إن كانت المنشأة تعمل هذا الشهر؛ وإن كانت تعمل فتأكد من اكتمال الإرسال."),
```

Then update `_diagnose_rule_failure_ar` to use `_CAUSE_MAP_AR` and add the same Level 3 keywords in Arabic:

```python
def _diagnose_rule_failure_ar(rule_code: str, details: str) -> Tuple[str, str]:
    if rule_code in _CAUSE_MAP_AR:
        return _CAUSE_MAP_AR[rule_code]
    low = details.lower()
    if "exceeds" in low or ">" in details or "duplicate" in low:
        return ("القيمة تتجاوز العتبة المتوقعة أو مكررة",
                "راجع القيمة؛ إن كانت دقيقة فحقق في الأسباب الكامنة.")
    if "missing" in low or "not reported" in low:
        return ("قيمة المؤشر المطلوب غير مُبلَّغ عنها",
                "تأكد من ملء جميع المؤشرات الإلزامية قبل الإرسال.")
    if "negative" in low:
        return ("قيمة سالبة لمؤشر عددي",
                "القيم السالبة مستحيلة؛ راجع الإدخال بحثاً عن أخطاء الإشارة.")
    if "decimal" in low:
        return ("قيمة عشرية لحقل عددي",
                "يجب أن تكون العدّادات أرقاماً صحيحة؛ تحقق من صحة الإدخال.")
    if "zero" in low or "all zeros" in low:
        return ("قيمة صفرية لمؤشر يُتوقع أن يكون غير صفري",
                "تحقق من أن المنشأة كانت تعمل وأن البيانات أُرسلت كاملة.")
    if "mismatch" in low or "inconsistent" in low:
        return ("القيم المُبلَّغ عنها غير متسقة أو غير متطابقة",
                "طابق القيم المُبلَّغ عنها مع السجلات المصدرية.")
    return ("فشل فحص التحقق من القاعدة",
            "راجع قيم المؤشرات المحددة وتحقق منها مقابل السجلات المصدرية.")
```

- [ ] **Step 4: Run tests to verify refactor preserves behavior**

Run: `python -m pytest tests/test_root_cause.py::TestDiagnoseRuleFailure -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py
git commit -m "refactor: extract rule cause maps to module constants"
```

---

### Task 3: Add `_extract_rule_type` and `_build_dynamic_diagnosis`

**Files:**
- Modify: `app/engine/root_cause.py` (add functions near `_diagnose_rule_failure`)
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Produces: `_extract_rule_type(params: dict) -> str` — returns one of `"SUM"`, `"PART"`, `"RATE"`, `"EXISTS"`, `"GENERIC"`.
- Produces: `_build_dynamic_diagnosis(rule_code: str, params: dict, details: str) -> Tuple[str, str]` — English cause + recommendation from structure; returns `("", "")` if params has no recognizable structure.
- Consumes: `_CAUSE_MAP` from Task 2; `INDICATOR_NAMES` (already imported at module top).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause.py`:

```python
from app.engine.root_cause import _extract_rule_type, _build_dynamic_diagnosis


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause.py::TestExtractRuleType tests/test_root_cause.py::TestBuildDynamicDiagnosis -q`
Expected: FAIL with ImportError (`cannot import name`).

- [ ] **Step 3: Implement the two functions**

In `app/engine/root_cause.py`, add before `_diagnose_rule_failure`:

```python
def _extract_rule_type(params: dict) -> str:
    """Classify a rule's params shape: SUM / PART / RATE / EXISTS / GENERIC."""
    if not isinstance(params, dict):
        return "GENERIC"
    if isinstance(params.get("children"), list) and params["children"]:
        return "SUM"
    if params.get("child") and params.get("parent"):
        return "PART"
    if params.get("num_code") and params.get("den_code"):
        return "RATE"
    if params.get("code"):
        return "EXISTS"
    return "GENERIC"


def _build_dynamic_diagnosis(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Generate (cause, recommendation) from a rule's structure. Returns ("", "") when no structure."""
    rtype = _extract_rule_type(params)
    if rtype == "SUM":
        children = ", ".join(str(x) for x in params["children"][:3])
        total = params.get("parent") or params.get("child") or "total"
        return (
            f"Sub-indicators ({children}) don't sum to total ({total}). Check for missing or duplicate sub-indicator reporting.",
            "Verify all sub-categories are reported and sum correctly to the parent indicator.",
        )
    if rtype == "PART":
        child, parent = params.get("child"), params.get("parent")
        return (
            f"Component ({child}) doesn't reconcile with total ({parent}). Verify the component is correctly classified.",
            "Confirm the breakdown value is classified under the correct category.",
        )
    if rtype == "RATE":
        num, den = params.get("num_code"), params.get("den_code")
        return (
            f"Rate ({num}/{den}) outside expected bounds. Review the raw counts feeding the ratio.",
            "Verify numerator and denominator source values are accurate and complete.",
        )
    if rtype == "EXISTS":
        code = params.get("code")
        return (
            f"Required indicator ({code}) missing or not reported. Confirm submission completeness.",
            "Ensure all mandatory indicators are filled before submission.",
        )
    return ("", "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_root_cause.py::TestExtractRuleType tests/test_root_cause.py::TestBuildDynamicDiagnosis -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat: add dynamic rule type classification and structural diagnosis"
```

---

### Task 4: Add `_diagnose_rule_failure_v2` and `_diagnose_rule_failure_v2_ar`

**Files:**
- Modify: `app/engine/root_cause.py`
- Test: `tests/test_root_cause.py`

**Interfaces:**
- Produces: `_diagnose_rule_failure_v2(rule_code: str, params: dict, details: str) -> Tuple[str, str]` — Level 1 map → Level 2 dynamic → Level 3 details patterns.
- Produces: `_diagnose_rule_failure_v2_ar(rule_code: str, params: dict, details: str) -> Tuple[str, str]` — same ladder in Arabic.
- Consumes: `_CAUSE_MAP`, `_CAUSE_MAP_AR` (Task 2), `_build_dynamic_diagnosis` (Task 3).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause.py`:

```python
from app.engine.root_cause import _diagnose_rule_failure_v2, _diagnose_rule_failure_v2_ar


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause.py::TestDiagnoseRuleFailureV2 -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `_diagnose_rule_failure_v2`**

In `app/engine/root_cause.py`, after `_diagnose_rule_failure`:

```python
def _diagnose_rule_failure_v2(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Three-level diagnosis: explicit map -> structural -> details patterns (English)."""
    if rule_code in _CAUSE_MAP:
        return _CAUSE_MAP[rule_code]
    cause, rec = _build_dynamic_diagnosis(rule_code, params, details)
    if cause:
        return cause, rec
    return _diagnose_rule_failure(rule_code, details)
```

- [ ] **Step 4: Implement `_diagnose_rule_failure_v2_ar`**

Add after `_diagnose_rule_failure_ar`:

```python
_CAUSE_MAP_AR_STRUCT = {
    "SUM": ("المؤشرات الفرعية لا تجمع للإجمالي. تحقق من نقص أو تكرار الإبلاغ عن مؤشر فرعي.",
            "تأكد من إبلاغ جميع الفئات الفرعية وأن مجموعها يطابق المؤشر الأصلي."),
    "PART": ("المكوّن لا يتطابق مع الإجمالي. تحقق من صحة تصنيف المكوّن.",
             "تأكد من تصنيف القيمة التفصيلية تحت الفئة الصحيحة."),
    "RATE": ("نسبة المؤشرين خارج الحدود المتوقعة. راجع القيم الخام المغذية للنسبة.",
             "تحقق من صحة واكتمال قيم البسط والمقام المصدرية."),
    "EXISTS": ("المؤشر المطلوب غير مُبلّغ. تأكد من اكتمال الإرسال.",
               "تأكد من ملء جميع المؤشرات الإلزامية قبل الإرسال."),
}


def _diagnose_rule_failure_v2_ar(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Three-level diagnosis: explicit map -> structural -> details patterns (Arabic)."""
    if rule_code in _CAUSE_MAP_AR:
        return _CAUSE_MAP_AR[rule_code]
    rtype = _extract_rule_type(params)
    if rtype in _CAUSE_MAP_AR_STRUCT:
        return _CAUSE_MAP_AR_STRUCT[rtype]
    return _diagnose_rule_failure_ar(rule_code, details)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_root_cause.py::TestDiagnoseRuleFailureV2 -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause.py
git commit -m "feat: add three-level dynamic rule diagnosis (en + ar)"
```

---

### Task 5: Wire params through `analyze_rule_failures`

**Files:**
- Modify: `app/engine/root_cause.py:810-853` (`analyze_rule_failures`)
- Test: `tests/test_root_cause_improvements.py`

**Interfaces:**
- Consumes: `_diagnose_rule_failure_v2`, `_diagnose_rule_failure_v2_ar` (Task 4).
- Produces: `RuleFailurePattern.primary_cause_ar` populated with Arabic cause for each failure.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py`:

```python
def test_analyze_rule_failures_populates_arabic_cause(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import analyze_rule_failures

    h = Hospital(name="ArCauseHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R041",
        rule_description="C-section rate", status="FAIL",
        severity="HIGH", rule_type="BENCHMARK",
    ))
    db_session.commit()

    patterns = analyze_rule_failures(db_session, h.id, "2026-06")
    assert len(patterns) >= 1
    assert patterns[0].primary_cause_ar


def test_analyze_rule_failures_dynamic_structure(db_session):
    """قاعدة مع params ينتج سبباً عربياً/إنجليزياً محدداً من المستوى الثاني."""
    from app.models import Hospital, ValidationResult, Rule
    from app.engine.root_cause import analyze_rule_failures

    h = Hospital(name="DynHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    rule = Rule(code="RDYN1", name="Dyn", rule_type="LOGIC", severity="HIGH",
                category="BASIC_LOGIC", expression_type="ge",
                params='{"parent": "2", "children": ["3", "4", "5"]}',
                description="Dyn rule")
    db_session.add(rule)
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="RDYN1",
        rule_description="Dyn rule", status="FAIL", severity="HIGH", rule_type="LOGIC",
    ))
    db_session.commit()

    patterns = analyze_rule_failures(db_session, h.id, "2026-06")
    assert any(p.rule_code == "RDYN1" for p in patterns)
    dyn = [p for p in patterns if p.rule_code == "RDYN1"][0]
    assert dyn.primary_cause
    assert dyn.primary_cause_ar
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_analyze_rule_failures_populates_arabic_cause tests/test_root_cause_improvements.py::test_analyze_rule_failures_dynamic_structure -q`
Expected: FAIL — either `AttributeError: 'RuleFailurePattern' object has no attribute 'primary_cause_ar'` or empty assertion.

- [ ] **Step 3: Update the SQL query and diagnosis call**

In `app/engine/root_cause.py`, `analyze_rule_failures`, change the first query to also select `r.params`:

```python
    result = session.execute(text("""
        SELECT vr.rule_code, vr.rule_description, vr.severity,
               COALESCE(r.rule_type, vr.rule_type, 'LOGIC') as rule_type,
               COUNT(*) as failure_count, vr.details, r.params
        FROM validation_results vr
        LEFT JOIN rules r ON r.code = vr.rule_code
        WHERE vr.hospital_id = :hid AND vr.month = :mth AND vr.status = 'FAIL'
        GROUP BY vr.rule_code
        ORDER BY COUNT(*) DESC
    """), {"hid": hospital_id, "mth": month})
```

Then update the loop body:

```python
        failure_count = row[4]
        details = row[5] or ""
        params_raw = row[6]
        try:
            params = json.loads(params_raw) if params_raw else {}
        except (ValueError, TypeError):
            params = {}
```

And replace the diagnosis line:

```python
        primary_cause, recommendation = _diagnose_rule_failure_v2(rule_code, params, details)
        primary_cause_ar, _ = _diagnose_rule_failure_v2_ar(rule_code, params, details)
```

And add to the `RuleFailurePattern(...)` constructor:

```python
            primary_cause=primary_cause,
            recommendation=recommendation,
            primary_cause_ar=primary_cause_ar,
            rule_type=rule_type,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_analyze_rule_failures_populates_arabic_cause tests/test_root_cause_improvements.py::test_analyze_rule_failures_dynamic_structure -q`
Expected: PASS

- [ ] **Step 5: Run full root cause test suite**

Run: `python -m pytest tests/test_root_cause.py tests/test_root_cause_improvements.py -q`
Expected: all pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause_improvements.py
git commit -m "feat: wire dynamic diagnosis into analyze_rule_failures"
```

---

### Task 6: Extend `PeerIndicatorComparison` with governorate/type fields

**Files:**
- Modify: `app/engine/root_cause.py:139-151` (dataclass)
- Test: `tests/test_root_cause_improvements.py`

**Interfaces:**
- Produces: new `PeerIndicatorComparison` fields:
  - `peer_governorates: List[str]` (default `[]`)
  - `peer_governorate_counts: Dict[str, int]` (default `{}`)
  - `peer_types: List[str]` (default `[]`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py`:

```python
def test_peer_comparison_includes_governorates(db_session):
    from app.models import Hospital, HospitalType, Governorate, Indicator, IndicatorValue
    from app.engine.root_cause import generate_root_cause_analysis

    gov = Governorate(name="North")
    htype = HospitalType(name="Gov")
    db_session.add_all([gov, htype])
    db_session.flush()
    target = Hospital(name="Target2", hospital_type_id=htype.id,
                      governorate_id=gov.id, is_active=True)
    peers = [
        Hospital(name=f"P2{i}", hospital_type_id=htype.id,
                 governorate_id=gov.id, is_active=True)
        for i in range(4)
    ]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        high = h is target
        vals = {"2": 200, "5": 80 if high else 40, "6": 190}
        for code, v in vals.items():
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=v))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, target.id, "2026-06",
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        include_history=False, compare_peers=True,
    )
    comps = report.peer_comparisons
    assert comps
    for comp in comps.values():
        assert comp.peer_governorates
        assert comp.peer_types
        assert comp.peer_governorate_counts.get("North", 0) >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_peer_comparison_includes_governorates -q`
Expected: FAIL with `AttributeError: 'PeerIndicatorComparison' object has no attribute 'peer_governorates'`.

- [ ] **Step 3: Extend the dataclass**

In `app/engine/root_cause.py`:

```python
@dataclass
class PeerIndicatorComparison:
    """مقارنة قيمة المستشفى الفعلية بمتوسط النظير لنفس المؤشر — لا مقارنة درجة الجودة بقيمة عشوائية."""
    indicator_code: str
    indicator_name: str
    hospital_value: float
    peer_group: str
    peer_count: int
    peer_mean: float
    peer_std: float
    hospital_percentile: float
    hospital_z_score: float
    gap_pct: float
    peer_governorates: List[str] = field(default_factory=list)
    peer_governorate_counts: Dict[str, int] = field(default_factory=dict)
    peer_types: List[str] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes (may still fail on data population)**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_peer_comparison_includes_governorates -q`
Expected: If test passes, skip ahead to commit. If it fails because fields are empty, proceed to Task 7 before committing.

- [ ] **Step 5: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause_improvements.py
git commit -m "feat: add peer governorate/type fields to PeerIndicatorComparison"
```

---

### Task 7: Populate peer governorate/type data in `generate_root_cause_analysis`

**Files:**
- Modify: `app/engine/root_cause.py:1434-1477` (peer_comparisons block)

**Interfaces:**
- Consumes: `PeerIndicatorComparison` new fields (Task 6); `_load_hospital_data` entries with `governorate`/`hospital_type`.
- Produces: populated `peer_governorates`, `peer_governorate_counts`, `peer_types` on every `PeerIndicatorComparison`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py` (this is the same test as Task 6 Step 1 — reuse `test_peer_comparison_includes_governorates`):

Run: `python -m pytest tests/test_root_cause_improvements.py::test_peer_comparison_includes_governorates -q`
Expected: FAIL because fields are empty (assertion `assert comp.peer_governorates` fails).

- [ ] **Step 2: Implement collection**

In `app/engine/root_cause.py`, in `generate_root_cause_analysis`, the peer block starts at:

```python
    peer_comparisons = {}
    if compare_peers:
        peer_groups = identify_peer_groups(session, hospital_id)
        if peer_groups:
            from app.engine.smart import _load_hospital_data
            month_data = _load_hospital_data(session, month)
            hospital_map = {}
            peer_values: Dict[str, List[float]] = {}
```

Replace the two-line initialization with:

```python
            month_data = _load_hospital_data(session, month)
            hospital_map = {}
            peer_values: Dict[str, List[float]] = {}
            peer_governorates: List[str] = []
            peer_governorate_counts: Dict[str, int] = {}
            peer_types: List[str] = []
            for name, entry in month_data.items():
                if entry["hospital_id"] == hospital_id:
                    hospital_map = entry.get("values", {})
                    continue
                gov = entry.get("governorate") or "unknown"
                peer_governorates.append(gov)
                peer_governorate_counts[gov] = peer_governorate_counts.get(gov, 0) + 1
                htype = entry.get("hospital_type") or "unknown"
                if htype not in peer_types:
                    peer_types.append(htype)
                for code in FEATURE_KEYS:
                    v = entry.get("values", {}).get(code)
                    if v is not None:
                        peer_values.setdefault(code, []).append(float(v))
```

Then in the `PeerIndicatorComparison(...)` constructor add:

```python
                    peer_count=len(pvals),
                    peer_mean=round(mean, 2),
                    peer_std=round(std, 2),
                    hospital_percentile=round(percentile, 1),
                    hospital_z_score=round(z, 2),
                    gap_pct=round(gap_pct, 2),
                    peer_governorates=list(peer_governorates),
                    peer_governorate_counts=dict(peer_governorate_counts),
                    peer_types=list(peer_types),
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_peer_comparison_includes_governorates -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/engine/root_cause.py tests/test_root_cause_improvements.py
git commit -m "feat: populate peer governorate/type breakdown in comparisons"
```

---

### Task 8: Serialize new fields in the API

**Files:**
- Modify: `app/api/root_cause.py:260-274` (peer_comparisons serialization)
- Test: `tests/test_root_cause_improvements.py`

**Interfaces:**
- Consumes: new `PeerIndicatorComparison` fields (Task 6).
- Produces: API response `peer_comparisons[k].peer_governorates` (array), `.peer_governorate_counts` (object), `.peer_types` (array).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py`:

```python
def test_api_returns_peer_governorates(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, HospitalType, Governorate, Indicator, IndicatorValue

    gov = Governorate(name="South")
    htype = HospitalType(name="Gov2")
    db_session.add_all([gov, htype])
    db_session.flush()
    target = Hospital(name="ApiTarget", hospital_type_id=htype.id,
                      governorate_id=gov.id, is_active=True)
    peers = [
        Hospital(name=f"ApiPeer{i}", hospital_type_id=htype.id,
                 governorate_id=gov.id, is_active=True)
        for i in range(4)
    ]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        high = h is target
        vals = {"2": 200, "5": 80 if high else 40, "6": 190}
        for code, v in vals.items():
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=v))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(f"/root-cause/{target.id}?month=2026-06&compare_peers=true")
        assert resp.status_code == 200
        data = resp.json()
        comps = data.get("peer_comparisons") or {}
        assert comps
        first = next(iter(comps.values()))
        assert "peer_governorates" in first
        assert first["peer_governorates"]
        assert first["peer_types"]
        assert first["peer_governorate_counts"].get("South", 0) >= 4
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_api_returns_peer_governorates -q`
Expected: FAIL — `"peer_governorates" not in first`.

- [ ] **Step 3: Update serialization**

In `app/api/root_cause.py`, in the `peer_comparisons` dict comprehension add:

```python
                "hospital_percentile": v.hospital_percentile,
                "hospital_z_score": v.hospital_z_score,
                "gap_pct": v.gap_pct,
                "peer_governorates": v.peer_governorates,
                "peer_governorate_counts": v.peer_governorate_counts,
                "peer_types": v.peer_types,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_api_returns_peer_governorates -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/root_cause.py tests/test_root_cause_improvements.py
git commit -m "feat: serialize peer governorate/type fields in root-cause API"
```

---

### Task 9: Render peer governorates/types in the frontend

**Files:**
- Modify: `static/js/settings.js:569-580` (peer comparison render block)
- Test: `tests/test_root_cause_improvements.py`

**Interfaces:**
- Consumes: API fields `peer_governorates`, `peer_governorate_counts`, `peer_types` (Task 8).
- Produces: A third row in each peer comparison card showing governorate and type breakdown.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_root_cause_improvements.py`:

```python
def test_frontend_renders_peer_governorates():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "peer_governorate_counts" in content
    assert "peer_types" in content
    assert "النظير" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_frontend_renders_peer_governorates -q`
Expected: FAIL — `assert "peer_governorate_counts" in content`.

- [ ] **Step 3: Update the render block**

In `static/js/settings.js`, in the peer comparison render block (currently lines 569-580), replace the return statement's inner markup. The current code is:

```js
                        peerEl.innerHTML = entries.slice(0, 10).map(c => {
                            const gap = c.gap_pct || 0;
                            const over = gap > 0;
                            const color = Math.abs(gap) > 20 ? (over ? '#c62828' : '#1565c0') : '#888';
                            return '<div style="padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                    '<span style="font-weight:600;font-size:0.78rem;">' + esc(c.indicator_name || c.indicator_code) + '</span>' +
                                    '<span style="font-size:0.7rem;color:' + color + ';font-weight:700;">' + (over ? '▲ +' : '▼ ') + Math.abs(gap).toFixed(1) + '%</span>' +
                                '</div>' +
                                '<div style="font-size:0.68rem;color:#888;">المستشفى ' + c.hospital_value + ' مقابل متوسط النظير ' + c.peer_mean + ' (' + c.peer_count + ' مستشفى) — مئوية ' + c.hospital_percentile + ' | z=' + c.hospital_z_score + '</div>' +
                            '</div>';
                        }).join('');
```

Replace with:

```js
                        peerEl.innerHTML = entries.slice(0, 10).map(c => {
                            const gap = c.gap_pct || 0;
                            const over = gap > 0;
                            const color = Math.abs(gap) > 20 ? (over ? '#c62828' : '#1565c0') : '#888';
                            const govs = (c.peer_governorate_counts || {});
                            const govParts = Object.entries(govs).sort((a, b) => b[1] - a[1])
                                .map(g => g[0] + ' (' + g[1] + ')').join('، ');
                            const types = (c.peer_types || []).join('، ');
                            return '<div style="padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                    '<span style="font-weight:600;font-size:0.78rem;">' + esc(c.indicator_name || c.indicator_code) + '</span>' +
                                    '<span style="font-size:0.7rem;color:' + color + ';font-weight:700;">' + (over ? '▲ +' : '▼ ') + Math.abs(gap).toFixed(1) + '%</span>' +
                                '</div>' +
                                '<div style="font-size:0.68rem;color:#888;">المستشفى ' + c.hospital_value + ' مقابل متوسط النظير ' + c.peer_mean + ' (' + c.peer_count + ' مستشفى) — مئوية ' + c.hospital_percentile + ' | z=' + c.hospital_z_score + '</div>' +
                                (govParts || types ? '<div style="font-size:0.66rem;color:#aaa;margin-top:0.1rem;">النظير: محافظات: ' + (govParts || '—') + ' | أنواع: ' + (types || '—') + '</div>' : '') +
                            '</div>';
                        }).join('');
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_root_cause_improvements.py::test_frontend_renders_peer_governorates -q`
Expected: PASS

- [ ] **Step 5: Run full frontend + root cause test suites**

Run: `python -m pytest tests/test_root_cause.py tests/test_root_cause_improvements.py tests/test_chart_migration.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add static/js/settings.js tests/test_root_cause_improvements.py
git commit -m "feat: display peer governorate/type breakdown in UI"
```

---

### Task 10: Full regression run and documentation update

**Files:**
- Test: all test files
- Create: `README.md` (already exists from prior work — update if it references diagnosis behavior)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass (109+ previously; expect same or more).

- [ ] **Step 2: Verify no Plotly regression**

Confirm `static/index.html` still contains `plotly.min.js` and `static/js/smart-analytics.js`/`static/js/validation.js` still reference Plotly.

Run: `Select-String -Path "static\index.html" -Pattern "plotly"`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: note RCA diagnosis improvements and peer governorate display"
```

Only commit if README actually changed; otherwise skip the commit.
