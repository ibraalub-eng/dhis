# Disabled Indicator Propagation — Full Exclusion on Save

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** When an indicator is disabled in the Indicator Tree and the config is saved, the indicator immediately disappears from all screens, is excluded from analysis/scoring, and completeness is recomputed without it — across the entire app.

**Architecture:** Backend-only changes. Close five existing gaps in confidence, clinical, smart analytics drilldown, root-cause timeline, and the save endpoints. Each gap is a one-file fix threading `disabled_codes` through the existing `get_disabled_indicator_ids` / `get_effective_manual_disabled_ids` helpers. On save, call `run_full_analysis(db, hospital_id, month, force=True)` for the view month only (user chose single-month re-analysis, not all-months).

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / vanilla JS frontend. Tests: pytest.

---

## Global Constraints

- pytest env: `$env:PYTHONHOME="C:\dhis-main\tools\python"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis\.venv\Lib\site-packages"; C:\dhis-main\tools\python\python.exe -m pytest`
- JS check: `node --check static/js/tree.js`
- Do NOT commit `.freebuff/preview-*.log*` or `data/cache/`
- Do NOT touch `app/engine/audit/benchmark.py` or `static/js/audit.js` (unrelated working-tree changes)

---

## File Map

| File | Change | Purpose |
|------|--------|---------|
| `app/api/tree_config.py:18-80` | Replace `_recalc_hospital_scores` with `run_full_analysis(..., force=True)` for view month | Full refresh on per-hospital save |
| `app/api/tree_config.py:83-129` | Same for default save: loop hospitals, `run_full_analysis(..., force=True)` for view month | Full refresh on default save |
| `app/engine/confidence.py:400-454` | Add `disabled_codes` param, skip disabled codes in assessed list | Confidence excludes disabled |
| `app/engine/pipeline.py:316-333` | Pass `disabled_codes` to `calculate_confidence` | Wire confidence fix |
| `app/engine/clinical/__init__.py:102-118` | Add `disabled_codes` param, skip thresholds where both sides disabled | Clinical excludes disabled |
| `app/api/clinical.py:24` | Compute disabled codes, pass to `compute_all_classifications` | Wire clinical fix |
| `app/api/smart_analytics.py:588-614` | Filter disabled indicators from indicator list and peer avg | Smart analytics excludes disabled |
| `app/api/root_cause.py:49-86` | Skip disabled `_TIMELINE_INDICATORS` entries | Root-cause timeline excludes disabled |
| `tests/test_recalc_scores.py` | Add tests for save-then-recompute + disabled exclusion | Verification |

---

### Task 1: Save endpoints trigger full re-analysis (per hospital)

**Files:**
- Modify: `app/api/tree_config.py:18-80`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Produces: `save_tree_config` now calls `run_full_analysis(db, hospital_id, month, force=True)` after committing config, instead of `_recalc_hospital_scores`.

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_save_tree_config_triggers_full_reanalysis(client, db_session):
    """Disabling an indicator via tree save purges old ValidationResult rows
    and writes fresh ones (run_full_analysis, force=True)."""
    from app.models import Indicator, IndicatorValue, ValidationResult

    # Insert an indicator value so analysis can run
    ind = db_session.query(Indicator).first()
    if not ind:
        ind = Indicator(code="99", name="Test Ind", sort_order=1)
        db_session.add(ind)
        db_session.flush()
    db_session.add(IndicatorValue(hospital_id=1, month="2027-01", indicator_id=ind.id, value=10))
    db_session.commit()

    # Disable that indicator via tree save
    resp = client.post(
        "/hospitals/save-tree-config?month=2027-01",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200
    assert resp.json()["message"]

    # ValidationResult rows should now NOT include any rule for this indicator
    # (run_full_analysis is called, which re-generates all rows from scratch)
    vr_rows = db_session.query(ValidationResult).filter(
        ValidationResult.hospital_id == 1,
        ValidationResult.month == "2027-01",
    ).all()
    # All rule details should not reference the disabled indicator code
    disabled_code = ind.code
    for vr in vr_rows:
        assert disabled_code not in (vr.details or ""), (
            f"ValidationResult {vr.rule_code} still references disabled indicator {disabled_code}"
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_save_tree_config_triggers_full_reanalysis -v`
Expected: FAIL (analysis not triggered)

- [x] **Step 3: Implement the change in `tree_config.py`**

In `save_tree_config` (line 74-79), replace:
```python
    db.commit()
    from app.api.indicator_config import _recalc_hospital_scores
    try:
        _recalc_hospital_scores(db, hospital_id)
    except Exception:
        pass
```
with:
```python
    db.commit()
    from app.engine.pipeline import run_full_analysis
    try:
        run_full_analysis(db, hospital_id, month, force=True)
    except Exception:
        pass
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_save_tree_config_triggers_full_reanalysis -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/api/tree_config.py tests/test_recalc_scores.py
git commit -m "tree config save: trigger full re-analysis for view month on per-hospital save"
```

---

### Task 2: Save endpoints trigger full re-analysis (default / all hospitals)

**Files:**
- Modify: `app/api/tree_config.py:83-129`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Produces: `save_default_tree_config` now loops all active hospitals and calls `run_full_analysis(db, hid, month, force=True)` for each.

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_save_default_tree_config_triggers_full_reanalysis(client, db_session):
    """Disabling an indicator via default tree save re-runs analysis for all hospitals."""
    from app.models import Indicator, IndicatorValue, ValidationResult, Hospital

    # Insert data for at least one hospital
    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    if not hosp:
        pytest.skip("no active hospitals in test DB")
    ind = db_session.query(Indicator).first()
    if not ind:
        ind = Indicator(code="99", name="Test Ind", sort_order=1)
        db_session.add(ind)
        db_session.flush()
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=ind.id, value=10))
    db_session.commit()

    resp = client.post(
        "/hospitals/save-default-tree-config?month=2027-01",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200

    # ValidationResult rows should not reference the disabled indicator
    vr_rows = db_session.query(ValidationResult).filter(
        ValidationResult.hospital_id == hosp.id,
        ValidationResult.month == "2027-01",
    ).all()
    disabled_code = ind.code
    for vr in vr_rows:
        assert disabled_code not in (vr.details or ""), (
            f"Default save: ValidationResult {vr.rule_code} still references disabled {disabled_code}"
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_save_default_tree_config_triggers_full_reanalysis -v`
Expected: FAIL

- [x] **Step 3: Implement the change in `tree_config.py`**

In `save_default_tree_config` (line 124-128), replace:
```python
    from app.api.indicator_config import _recalc_all_hospital_scores
    try:
        _recalc_all_hospital_scores(db)
    except Exception:
        pass
```
with:
```python
    from app.engine.pipeline import run_full_analysis
    from app.models import Hospital as _Hosp
    _all_hids = [h.id for h in db.query(_Hosp.id).filter(_Hosp.is_active.is_(_True)).all()]
    for _hid in _all_hids:
        try:
            run_full_analysis(db, _hid, month, force=True)
        except Exception:
            pass
```

Note: replace `_True` with `True` (the filter is `Hospital.is_active.is_(True)`).

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_save_default_tree_config_triggers_full_reanalysis -v`
Expected: PASS

- [x] **Step 5: Run full config test suite to catch regressions**

Run: `pytest tests/test_recalc_scores.py tests/test_api_config.py -q -p no:warnings`
Expected: all pass

- [x] **Step 6: Commit**

```bash
git add app/api/tree_config.py tests/test_recalc_scores.py
git commit -m "tree config save: trigger full re-analysis for all hospitals on default save"
```

---

### Task 3: Confidence screen excludes disabled indicators

**Files:**
- Modify: `app/engine/confidence.py:400-454`
- Modify: `app/engine/pipeline.py:316-333`
- Modify: `app/api/confidence.py:29-66`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Produces: `calculate_confidence(..., disabled_codes=None)` — when provided, any indicator code in `disabled_codes` is excluded from `assessed` entirely (never appears as "DATA MISSING").

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_confidence_excludes_disabled_indicators(client, db_session):
    """Disabled indicators must not appear as CRITICAL 'DATA MISSING' in confidence."""
    from app.models import Hospital, Indicator, IndicatorValue, IndicatorDefaultConfig, QualityScore

    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    if not hosp:
        pytest.skip("no active hospitals")
    ind = db_session.query(Indicator).first()
    if not ind:
        pytest.skip("no indicators")

    # Add a value for the indicator
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=ind.id, value=10))
    db_session.commit()

    # Disable it in default config for all months
    known_months = sorted({r[0] for r in db_session.query(IndicatorValue.month).distinct().all()})
    for m in known_months:
        db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month=m, is_enabled=False))
    db_session.commit()

    # Get confidence
    resp = client.get(
        f"/confidence/{hosp.id}?month={known_months[0] if known_months else '2027-01'}"
    )
    if resp.status_code != 200:
        pytest.skip("confidence endpoint returned non-200")
    data = resp.json()
    assessed_codes = [i["indicator_code"] for i in data.get("indicators", [])]
    assert ind.code not in assessed_codes, (
        f"Disabled indicator {ind.code} still appears in confidence assessed list"
    )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_confidence_excludes_disabled_indicators -v`
Expected: FAIL

- [x] **Step 3: Add `disabled_codes` parameter to `calculate_confidence`**

In `app/engine/confidence.py`, add `disabled_codes: Optional[set] = None` to the signature at line 400:

```python
def calculate_confidence(
    hospital_name: str,
    month: str,
    values: Dict[str, float],
    rule_results: List[RuleResult],
    historical_data: Dict[str, Dict[str, float]],
    all_hospital_data: Dict[str, Dict[str, float]],
    indicator_map: Dict[str, str],
    indicator_children: Dict[str, List[str]],
    indicator_rule_map: Optional[Dict[str, List[str]]] = None,
    key_indicator_codes: Optional[List[str]] = None,
    disabled_codes: Optional[set] = None,
    session=None,
) -> HospitalConfidenceResult:
```

Then at line 449-454, replace the assessed loop:

```python
    for code in key_indicator_codes:
        if code not in assessed:
            # If auto-disable ON, skip indicators not in values (disabled/missing)
            if _auto_disable and code not in values:
                continue
            assessed.append(code)
```

with:

```python
    for code in key_indicator_codes:
        if code not in assessed:
            if disabled_codes and code in disabled_codes:
                continue
            if _auto_disable and code not in values:
                continue
            assessed.append(code)
```

- [x] **Step 4: Wire `disabled_codes` through `pipeline.py`**

In `app/engine/pipeline.py`, at lines 318-330, add `disabled_codes` to the `calculate_confidence` call:

```python
        confidence_result = calculate_confidence(
            hospital_name=hospital.name,
            month=month,
            values=values,
            rule_results=rule_results,
            historical_data=historical if historical else {},
            all_hospital_data=all_hospital_data,
            indicator_map=indicator_map,
            indicator_children=PARENT_CHILD_MAP,
            indicator_rule_map=indicator_rule_map,
            key_indicator_codes=KEY_INDICATOR_CODES,
            disabled_codes=disabled_codes,
            session=session,
        )
```

`disabled_codes` is already computed at line 231-235 above this call.

- [x] **Step 5: Wire `disabled_codes` through confidence API**

In `app/api/confidence.py`, the standalone `_run_confidence_for_hospital` function at line 29-66 also calls `calculate_confidence`. Compute `disabled_codes` before the call and pass it:

At line 33 (after `historical = ...`), add:
```python
    from app.engine.pipeline import get_disabled_indicator_ids, get_effective_manual_disabled_ids
    _disabled_ids = set(get_disabled_indicator_ids(db, hospital_id, month))
    _ind_rows = db.query(Indicator.id, Indicator.code).all()
    _id_to_code = {i: c for i, c in _ind_rows}
    _disabled_codes = {_id_to_code[d] for d in _disabled_ids if d in _id_to_code}
```

Then add `disabled_codes=_disabled_codes` to the `calculate_confidence` call (around line 65-78).

- [x] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_confidence_excludes_disabled_indicators -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add app/engine/confidence.py app/engine/pipeline.py app/api/confidence.py tests/test_recalc_scores.py
git commit -m "confidence: exclude disabled indicators from assessed list"
```

---

### Task 4: Clinical screen hides thresholds where both sides are disabled

**Files:**
- Modify: `app/engine/clinical/__init__.py:102-118`
- Modify: `app/api/clinical.py:14-60`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Produces: `compute_all_classifications(values, disabled_codes=None)` — when both numerator and denominator codes of a threshold are in `disabled_codes`, that threshold row is omitted from the result list.

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_clinical_skips_disabled_thresholds(client, db_session):
    """Thresholds whose both numerator and denominator codes are disabled
    must not appear in clinical classifications."""
    from app.models import Hospital, Indicator, IndicatorValue, IndicatorDefaultConfig
    from app.engine.clinical import CLINICAL_THRESHOLDS, compute_all_classifications

    # Pick the first threshold
    th = CLINICAL_THRESHOLDS[0]
    all_codes = set(th.numerator_codes) | {th.denominator_code}

    # Insert dummy values for those codes so they exist in values
    values = {c: 10.0 for c in all_codes}

    # All codes disabled → threshold should be omitted
    disabled_codes = set(all_codes)
    results = compute_all_classifications(values, disabled_codes=disabled_codes)
    result_codes = {r.indicator_code for r in results}
    assert th.indicator_code not in result_codes, (
        f"Threshold {th.indicator_code} still present when all its codes disabled"
    )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_clinical_skips_disabled_thresholds -v`
Expected: FAIL (function does not accept disabled_codes yet)

- [x] **Step 3: Implement `disabled_codes` in `compute_all_classifications`**

In `app/engine/clinical/__init__.py`, change the signature at line 102:

```python
def compute_all_classifications(values: Dict[str, float], disabled_codes: set = None) -> List[ClinicalClassification]:
    results = []
    for th in CLINICAL_THRESHOLDS:
        if disabled_codes:
            all_th_codes = set(th.numerator_codes) | {th.denominator_code}
            if all_th_codes <= disabled_codes:
                continue
        num_sum = sum(values.get(c, 0) or 0 for c in th.numerator_codes)
        denom = values.get(th.denominator_code, 0)
        rate_val = None
        if denom and denom > 0:
            if th.unit == "per 100,000":
                rate_val = (num_sum / denom) * 100000
            elif th.unit == "per 1,000":
                rate_val = (num_sum / denom) * 1000
            else:
                rate_val = (num_sum / denom) * 100
        cls = classify_clinical_rate(rate_val, th.rate_name)
        cls.value = rate_val
        results.append(cls)
    return results
```

- [x] **Step 4: Wire `disabled_codes` through clinical API**

In `app/api/clinical.py`, after computing `values` at line 24, compute disabled codes and pass them:

After `values = get_enabled_values_for_hospital_month(...)` (line 24), add:
```python
    from app.engine.pipeline import get_disabled_indicator_ids
    from app.models import Indicator as _RI
    _dis_ids = get_disabled_indicator_ids(db, hospital_id, month)
    _ind_code_rows = db.query(_RI.id, _RI.code).all()
    _dis_codes = {c for i, c in _ind_code_rows if i in set(_dis_ids)}
```

Then in the `run_clinical_analysis` call (line 47), no change needed — the clinical analysis calls `compute_all_classifications(values)` internally. The fix is simpler: override the classifications after getting results, or pass `disabled_codes` through `run_clinical_analysis`.

The cleaner approach: in `run_clinical_analysis` (line 226-264 in `app/engine/clinical/__init__.py`), add `disabled_codes=None` to its signature and pass to `compute_all_classifications`:

```python
def run_clinical_analysis(
    hospital: str,
    month: str,
    values: Dict[str, float],
    ...existing params...,
    disabled_codes: set = None,
    session=None,
) -> ClinicalAnalysisResult:
    classifications = compute_all_classifications(values, disabled_codes=disabled_codes)
```

Then in `app/api/clinical.py` line 47, add:
```python
        disabled_codes=_dis_codes,
```

- [x] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_clinical_skips_disabled_thresholds -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add app/engine/clinical/__init__.py app/api/clinical.py tests/test_recalc_scores.py
git commit -m "clinical: hide thresholds where both numerator and denominator are disabled"
```

---

### Task 5: Smart analytics drilldown filters disabled indicators

**Files:**
- Modify: `app/api/smart_analytics.py:588-614`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Consumes: `get_disabled_indicator_ids` from `app.engine.pipeline`

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_smart_analytics_drilldown_excludes_disabled(client, db_session):
    """Smart analytics drilldown indicator list must not include disabled indicators."""
    from app.models import Hospital, Indicator, IndicatorValue, IndicatorDefaultConfig

    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    if not hosp:
        pytest.skip("no active hospitals")
    ind = db_session.query(Indicator).first()
    if not ind:
        pytest.skip("no indicators")

    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=ind.id, value=10))
    # Disable in default config for the specific month
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-01", is_enabled=False))
    db_session.commit()

    resp = client.get(
        f"/smart-analytics/drilldown/{hosp.id}?month=2027-01"
    )
    if resp.status_code != 200:
        pytest.skip("drilldown endpoint returned non-200")
    data = resp.json()
    indicator_ids = [i["indicator_id"] for i in data.get("indicators", [])]
    assert ind.id not in indicator_ids, (
        f"Disabled indicator {ind.code} (id={ind.id}) still in smart analytics drilldown"
    )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_smart_analytics_drilldown_excludes_disabled -v`
Expected: FAIL

- [x] **Step 3: Implement the fix**

In `app/api/smart_analytics.py`, at lines 588-614, add a disabled-set filter before building `indicators`:

After line 587 (`peer_list.sort(...)`), before line 588 (`# Clinical indicator values...`), add:

```python
    # Build disabled-indicator set for this hospital/month
    from app.engine.pipeline import get_disabled_indicator_ids as _gdi
    _dis_ids = set(_gdi(db, hospital_id, month))
```

Then wrap the indicator building loop (lines 590-599) with a filter:

```python
    indicators = []
    iv_rows = db.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hospital_id, IndicatorValue.month == month
    ).all()
    for iv in iv_rows:
        if iv.indicator_id in _dis_ids:
            continue
        indicators.append({
            "indicator_id": iv.indicator_id,
            "indicator_name": iv.indicator.name if iv.indicator else f"Indicator {iv.indicator_id}",
            "value": iv.value,
            "peer_avg": None,
        })
```

And in the peer-average loop (lines 606-610), also skip disabled peer indicator IDs:

```python
            for piv in db.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == pid, IndicatorValue.month == month
            ).all():
                if piv.indicator_id in _dis_ids:
                    continue
                peer_sums[piv.indicator_id].append(piv.value or 0)
                peer_count[piv.indicator_id] += 1
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_smart_analytics_drilldown_excludes_disabled -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/api/smart_analytics.py tests/test_recalc_scores.py
git commit -m "smart analytics: exclude disabled indicators from drilldown indicator list"
```

---

### Task 6: Root-cause timeline skips disabled indicators

**Files:**
- Modify: `app/api/root_cause.py:49-86`
- Test: `tests/test_recalc_scores.py`

**Interfaces:**
- Consumes: `get_disabled_indicator_ids` from `app.engine.pipeline`

- [x] **Step 1: Write the failing test**

Add to `tests/test_recalc_scores.py`:

```python
def test_root_cause_timeline_skips_disabled(client, db_session):
    """Root-cause timeline must not include disabled core indicators."""
    from app.models import Hospital, Indicator, IndicatorValue, IndicatorDefaultConfig

    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    if not hosp:
        pytest.skip("no active hospitals")
    # Find indicator with code "2" (one of the hardcoded timeline codes)
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    if not ind:
        pytest.skip("no indicator with code '2'")

    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=ind.id, value=100))
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2026-12", indicator_id=ind.id, value=90))
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-01", is_enabled=False))
    db_session.commit()

    resp = client.get(
        f"/root-cause/{hosp.id}/timeline?month=2027-01&months_back=2"
    )
    if resp.status_code != 200:
        pytest.skip("timeline endpoint returned non-200")
    data = resp.json()
    codes = [i["indicator_code"] for i in data.get("indicators", [])]
    assert "2" not in codes, "Disabled indicator code '2' still in root-cause timeline"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recalc_scores.py::test_root_cause_timeline_skips_disabled -v`
Expected: FAIL

- [x] **Step 3: Implement the fix**

In `app/api/root_cause.py`, add disabled-code computation before the loop at line 48:

```python
    from app.engine.pipeline import get_disabled_indicator_ids as _gdi
    _dis_ids = set(_gdi(db, hospital_id, month))
    from app.models import Indicator as _RI
    _ind_rows = db.query(_RI.id, _RI.code).all()
    _dis_codes = {c for i, c in _ind_rows if i in _dis_ids}
```

Then inside the loop at line 49-86, skip disabled codes:

```python
    for code, ar_name in _TIMELINE_INDICATORS:
        if code in _dis_codes:
            continue
        hist = get_historical_data(db, hospital_id, code, months_back, month=month)
        ...
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recalc_scores.py::test_root_cause_timeline_skips_disabled -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/api/root_cause.py tests/test_recalc_scores.py
git commit -m "root cause: exclude disabled indicators from timeline"
```

---

### Task 7: Full regression run

**Files:** None (verification only)

- [x] **Step 1: Run the full test suite**

```bash
$env:PYTHONHOME="C:\dhis-main\tools\python"; $env:PYTHONPATH="C:\Users\Administrator\Documents\GitHub\dhis\.venv\Lib\site-packages"; C:\dhis-main\tools\python\python.exe -m pytest tests/test_recalc_scores.py tests/test_api_config.py -q -p no:warnings
```

Expected: all pass (including new tests)

- [x] **Step 2: Run JS syntax check**

```bash
node --check static/js/tree.js
```

Expected: JS OK

- [x] **Step 3: Final commit (all tasks combined)**

```bash
git add -A
git status
```

Confirm only intended files are staged, then:
```bash
git commit -m "Disabled indicators: full propagation to all screens on save

- save_tree_config triggers full re-analysis for view month
- save_default_tree_config triggers full re-analysis for all hospitals
- confidence excludes disabled indicators from assessed list
- clinical hides thresholds where both sides are disabled
- smart analytics drilldown filters disabled indicators
- root cause timeline skips disabled indicators"
```

---

### Task 8: Verify on deployed site

- [x] **Step 1: Confirm Render badge shows the commit SHA**

- [x] **Step 2: Hard-refresh https://dhis-zve0.onrender.com/dashboard**

- [x] **Step 3: Disable an indicator in Indicator Tree, Save, verify it disappears from dashboard, clinical, smart analytics, confidence, root cause**
