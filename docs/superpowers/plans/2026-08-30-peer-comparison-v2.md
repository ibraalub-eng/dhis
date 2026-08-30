# Peer Comparison v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild hospital peer comparison to rank by `anomaly_score` (risk), expose an ascending-risk percentile, label by risk level, and make the `comparison_type` scope (all/governorate/type) functional.

**Architecture:** Replace the volume-based ranking in `compare_peers` with an anomaly-score ranking sourced from a single `run_smart_analytics` call (reordered to avoid double compute), filter by the reference hospital's governorate/type per `comparison_type`, and expose `anomaly_score` in the API response. Update the frontend label/color mapping and add an `anomaly_score` column.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, pytest (test-first), vanilla JS (report.js).

## Global Constraints

- File scope: `app/engine/comparative/advanced_comparison.py`, `app/api/comparative.py`, `static/js/smart/report.js`, `tests/test_comparative.py` only.
- Data source for ranking: `run_smart_analytics(session, month).anomalies` (each anomaly has fields `hospital_id: int`, `hospital_name: str`, `anomaly_score: float`, `governorate: str`, `hospital_type: str`).
- Risk percentile is **ascending-risk**: most risky (rank 1) -> 100.
- Labels: `critical`(حرج)/`high`(عالي)/`moderate`(متوسط)/`low`(منخفض) via risk-percentile thresholds 75/50/25.
- `PeerComparison` gains a final field `anomaly_score: float` (after `comparison_label`).
- Do NOT touch caching/performance work (out of scope). Do NOT modify `generate_comparison_chart` beyond leaving it as-is.
- Windows/PowerShell: no heredoc `python - <<'PY'`; write temp `.py` files for repro, set `$env:PYTHONPATH="C:\ibra\HEALTH-ai"`. Commit hook runs JS syntax + ES module import validation.

---

### Task 1: Rebuild compare_peers with risk-based ranking + scope filtering

**Files:**
- Modify: `app/engine/comparative/advanced_comparison.py` (the `PeerComparison` dataclass ~line 17, `compare_peers` ~line 128, `perform_advanced_comparison` ~line 66)
- Test: `tests/test_comparative.py` (peer label tests ~line 771)

**Interfaces:**
- Consumes: `run_smart_analytics(session, month) -> SmartAnalyticsResult` (`.anomalies` list of `SmartAnomalyResult`); `app.models.Hospital` (has `.id`, `.name`, `.governorate`, `.hospital_type`, `.is_active`).
- Produces: `compare_peers(session, month, comparison_type="all", hospital_id=None, lang="ar", analytics=None) -> List[PeerComparison]` where `PeerComparison(hospital_id, hospital_name, percentile, rank, total_hospitals, comparison_label, anomaly_score)`, with `percentile` = ascending-risk (rank 1 -> 100).

- [ ] **Step 1: Replace the obsolete peer label tests with new risk-semantics tests (write first, TDD).**

Replace lines 771-790 (the `# --- Peer Comparison Label Tests ---` block incl. `test_peer_comparison_label_percentile_25/50/75/100`) with:

```python
# --- Peer Comparison v2: Risk-Based Label Tests ---

def test_peer_risk_label_thresholds():
    """حواف مئين المخاطرة: 75/50/25 -> critical/high/moderate/low (نصوص ضرورية)."""
    # نختبر دالة التسمية مباشرة إن وُجدت، وإلا نختبر عبر بناء صفوف
    from app.engine.comparative.advanced_comparison import _risk_label
    assert _risk_label(100.0, "ar") == "حرج"
    assert _risk_label(75.0, "ar") == "حرج"
    assert _risk_label(74.9, "ar") == "عالي"
    assert _risk_label(50.0, "ar") == "عالي"
    assert _risk_label(49.9, "ar") == "متوسط"
    assert _risk_label(25.0, "ar") == "متوسط"
    assert _risk_label(24.9, "ar") == "منخفض"
    assert _risk_label(0.0, "ar") == "منخفض"
    assert _risk_label(100.0, "en") == "critical"
    assert _risk_label(60.0, "en") == "high"
```

- [ ] **Step 2: Run the new test to verify it fails.**

Run: `python -m pytest "tests/test_comparative.py::test_peer_risk_label_thresholds" -q --tb=short`
Expected: FAIL with `ImportError`/`ModuleNotFoundError` for `_risk_label` (function not defined yet).

- [ ] **Step 3: Add `anomaly_score` to the dataclass and implement `_risk_label` + risk-based `compare_peers`.**

In `app/engine/comparative/advanced_comparison.py`, change the `PeerComparison` dataclass to:

```python
@dataclass
class PeerComparison:
    """مقارنة الأقران"""
    hospital_id: str
    hospital_name: str
    percentile: float
    rank: int
    total_hospitals: int
    comparison_label: str
    anomaly_score: float = 0.0
```

Replacing the entire old `compare_peers` function (lines ~128-186) with:

```python
_RISK_LABELS = {
    "ar": {"critical": "حرج", "high": "عالي", "moderate": "متوسط", "low": "منخفض"},
    "en": {"critical": "critical", "high": "high", "moderate": "moderate", "low": "low"},
}


def _risk_label(risk_percentile: float, lang: str = "ar") -> str:
    """تسمية مستوى الخطر حسب مئين المخاطرة الصاعد (الأعلى = الأخطر)."""
    labels = _RISK_LABELS.get(lang, _RISK_LABELS["ar"])
    if risk_percentile >= 75:
        return labels["critical"]
    if risk_percentile >= 50:
        return labels["high"]
    if risk_percentile >= 25:
        return labels["moderate"]
    return labels["low"]


def _anomaly_map(analytics) -> Dict[int, dict]:
    """خريطة hospital_id -> {name, score, governorate, hospital_type} من نتائج التحليل."""
    out = {}
    for a in (analytics.anomalies or []) if analytics else []:
        out[a.hospital_id] = {
            "name": a.hospital_name,
            "score": a.anomaly_score,
            "governorate": a.governorate,
            "hospital_type": a.hospital_type,
        }
    return out


def compare_peers(
    session: Session,
    month: str,
    comparison_type: str = "all",
    hospital_id: Optional[str] = None,
    lang: str = "ar",
    analytics=None,
) -> List[PeerComparison]:
    """مقارنة المستشفيات بدرجة الخطر (anomaly_score) داخل مجموعة النظير.

    - المعيار: anomaly_score تنازلياً (الرتبة 1 = الأخطر).
    - مئين المخاطرة صاعد: الرتبة 1 -> 100.
    - النطاق: all = كل النشطة؛ governorate/type تتطلب hospital_id وتفلتر بالمحافظة/النوع.
    """
    ana_map = _anomaly_map(analytics)

    hospitals = session.query(Hospital).filter(Hospital.is_active.is_(True)).all()
    # الفلتر حسب النطاق أولاً
    ref = None
    if comparison_type in ("governorate", "type"):
        if not hospital_id:
            return []
        ref = session.query(Hospital).get(int(hospital_id))
        if ref is None:
            return []

    candidates = []
    for h in hospitals:
        info = ana_map.get(h.id)
        if info is None:
            continue  # لا بيانات للمستشفى هذا الشهر
        if comparison_type == "governorate" and h.governorate != ref.governorate:
            continue
        if comparison_type == "type" and h.hospital_type != ref.hospital_type:
            continue
        candidates.append((h.id, info["name"], info["score"]))

    if len(candidates) < 2:
        return []

    # ترتيب تنازلي بالدرجة، وكسر تعادل حتمي بالاسم
    candidates.sort(key=lambda c: (-c[2], c[1]))

    total = len(candidates)
    comparisons = []
    for rank, (hosp_id, name, score) in enumerate(candidates, 1):
        risk_percentile = round(100.0 * (total - rank + 1) / total, 1)
        comparisons.append(PeerComparison(
            hospital_id=str(hosp_id),
            hospital_name=name,
            percentile=risk_percentile,
            rank=rank,
            total_hospitals=total,
            comparison_label=_risk_label(risk_percentile, lang),
            anomaly_score=round(score, 4),
        ))
    return comparisons
```

- [ ] **Step 4: Run the new test to verify it passes.**

Run: `python -m pytest "tests/test_comparative.py::test_peer_risk_label_thresholds" -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Update `perform_advanced_comparison` to compute analytics once and pass to `compare_peers`.**

In `app/engine/comparative/advanced_comparison.py`, replace the body (the part after `trends = analyze_trends(...)` and the reordering) so the function reads:

```python
    historical_data = get_historical_data(session, month, hospital_id)

    trends = analyze_trends(historical_data, hospital_id)

    current_analytics = run_smart_analytics(session, month)
    predictions = current_analytics.xgboost_predictions.__dict__ if current_analytics.xgboost_predictions else {}

    peer_comparisons = compare_peers(
        session, month, comparison_type, hospital_id=hospital_id, lang=lang,
        analytics=current_analytics,
    )

    chart_config = generate_comparison_chart(trends, peer_comparisons)
```

- [ ] **Step 6: Run the whole peer/chart test group to verify no regression from the reorder.**

Run: `python -m pytest tests/test_comparative.py -q --tb=short -k "chart or peer or trend" 2>&1 | Select-Object -Last 6`
Expected: the peer v2 test passes; pre-existing `test_local_report_includes_monthly_trends` and `test_comprehensive_report_includes_forecast_section` may still fail (pre-existing, unrelated). No NEW failures introduced by this task.

- [ ] **Step 7: Commit**

```bash
git add app/engine/comparative/advanced_comparison.py tests/test_comparative.py
git commit -m "feat: risk-based peer ranking with functional scope filtering"
```

---

### Task 2: Expose anomaly_score in the API response

**Files:**
- Modify: `app/api/comparative.py:48` (peer_comparison serialization)
- Test: `tests/test_comparative.py` (peer_comparison structure test ~line 826)

**Interfaces:**
- Consumes: `PeerComparison.anomaly_score` (Task 1).
- Produces: each entry in `comparison_data.peer_comparison` now includes `"anomaly_score": p.anomaly_score`.

- [ ] **Step 1: Write the failing test (extend the structure test).**

In `tests/test_comparative.py`, modify `test_advanced_comparison_peer_comparison_structure` (line ~826) to also assert the new field:

```python
def test_advanced_comparison_peer_comparison_structure(client):
    response = client.get("/comparative/advanced-comparison/2026-06")
    data = response.json()
    for peer in data["comparison_data"]["peer_comparison"]:
        assert "hospital_id" in peer
        assert "hospital_name" in peer
        assert "percentile" in peer
        assert "rank" in peer
        assert "total_hospitals" in peer
        assert "comparison_label" in peer
        assert "anomaly_score" in peer
```

- [ ] **Step 2: Run the test to verify it fails.**

Run: `python -m pytest "tests/test_comparative.py::test_advanced_comparison_peer_comparison_structure" -q --tb=short`
Expected: FAIL with `KeyError: 'anomaly_score'` (field not yet in the API payload).

- [ ] **Step 3: Add `anomaly_score` to the API serialization.**

In `app/api/comparative.py:48`, add the field to the `peer_comparison` list comprehension:

```python
                "peer_comparison": [{"hospital_id": p.hospital_id, "hospital_name": p.hospital_name, "percentile": p.percentile, "rank": p.rank, "total_hospitals": p.total_hospitals, "comparison_label": p.comparison_label, "anomaly_score": p.anomaly_score} for p in result.peer_comparisons],
```

- [ ] **Step 4: Run the test to verify it passes.**

Run: `python -m pytest "tests/test_comparative.py::test_advanced_comparison_peer_comparison_structure" -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/comparative.py tests/test_comparative.py
git commit -m "feat: expose anomaly_score in advanced-comparison peer payload"
```

---

### Task 3: Frontend — new label/color mapping + anomaly_score column

**Files:**
- Modify: `static/js/smart/report.js` (`_LABEL_LEVELS` ~line 12, `renderComparison` ~line 189)
- Test: commit hook route (JS syntax + ES module import validation)

**Interfaces:**
- Consumes: API `peer_comparison` entries that now include `anomaly_score` and `comparison_label` in {حرج/عالي/متوسط/منخفض} or {critical/high/moderate/low}.
- Produces: `_LABEL_LEVELS` covers the new labels; table shows an `anomaly_score` column.

- [ ] **Step 1: Update `_LABEL_LEVELS` with the new risk labels.**

In `static/js/smart/report.js`, replace the `_LABEL_LEVELS` object (lines 12-26) with:

```js
const _LABEL_LEVELS = {
  // Arabic risk labels
  'حرج': 'critical',
  'عالي': 'warning',
  'متوسط': 'normal',
  'منخفض': 'normal',
  // English risk labels
  'critical': 'critical',
  'high': 'warning',
  'moderate': 'normal',
  'low': 'normal',
};
```

(Keep `_labelToLevel` and `_labelColor` unchanged — they consume this map.)

- [ ] **Step 2: Add an `anomaly_score` column to the peer table.**

In `static/js/smart/report.js`, inside the `renderComparison` table build (lines 215-221), change the header row and body rows to add a score column:

```js
    if (peer) {
      peer.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
        <th>${_t('Rank')}</th><th>${_t('Hospital')}</th><th>${_t('Anomaly score')}</th><th>${_t('Percentile')}</th><th>${_t('Assessment')}</th></tr></thead><tbody>` +
        peers.map(p => `<tr><td style="text-align:center;font-weight:600;">${p.rank}</td>
          <td>${_smartEscapeHtml(p.hospital_name)}</td>
          <td style="text-align:center;">${_fmtNum(p.anomaly_score)}</td>
          <td style="text-align:center;">${p.percentile.toFixed(1)}%</td>
          <td>${_riskBadge(p.comparison_label, _labelToLevel(p.comparison_label))}</td></tr>`).join('') +
        `</tbody></table></div>`;
    }
```

- [ ] **Step 3: Verify JS syntax and ES-module imports.**

Run: `node --check static/js/smart/report.js`
Expected: no output (`node --check` prints nothing on success).

Then run the ES-module import validation the commit hook uses. If the hook is unknown, at minimum confirm `node --check` passes; committing runs the full validation.

- [ ] **Step 4: Commit**

```bash
git add static/js/smart/report.js
git commit -m "feat: peer table shows anomaly score + new risk label colors"
```

---

### Task 4: Full regression + cleanup

**Files:**
- Run-suite only.

- [ ] **Step 1: Run the full regression suite.**

Run: `python -m pytest tests/test_butterfly_report.py tests/test_chart_migration.py tests/test_auth.py -q --tb=short 2>&1 | Select-Object -Last 3`
Expected: `79 passed` (same as before; the peer v2 changes are isolated).

- [ ] **Step 2: Run the peer/chart tests once more to confirm green.**

Run: `python -m pytest tests/test_comparative.py -q --tb=short -k "peer or chart" 2>&1 | Select-Object -Last 4`
Expected: all new + retained peer/chart tests pass; only unrelated pre-existing failures (`test_local_report_includes_monthly_trends`, `test_comprehensive_report_includes_forecast_section`) appear if selected.

- [ ] **Step 3: Push**

```bash
git push origin main
```

## Self-Review notes
- **Spec coverage:** risk ranking (Task 1), ascending percentile (Task 1), labels (Task 1 `_risk_label`), scope filtering (Task 1), double-analytics reorder (Task 1 Step 5), API field (Task 2), frontend mapping + column (Task 3). No spec requirement left unaddressed.
- **Type consistency:** `_risk_label(percentile, lang)` defined in Task 1 and used there and nowhere else; `compare_peers(..., analytics=None)` matches `perform_advanced_comparison` call in Task 1 Step 5; `PeerComparison.anomaly_score` consumed in Task 2. No name drift.
- **Obsolete tests replaced:** old `test_peer_comparison_label_percentile_*` (volume semantics) removed in Task 1 Step 1, replaced by `test_peer_risk_label_thresholds`.
