# US-11 — Audit Trail Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `/audit/explain` result traceable end-to-end (Raw Data → Validation → Issue → Evidence → Root Cause → Impact → Recommendation → Action) by adding a `trail` payload, extending `chain` to 8 stages for per-issue kinds, and adding a deep-linkable Audit Trail view.

**Architecture:** All backend logic is added to `app/engine/audit/explain.py` as small private helpers around the existing `build_explanation` dispatcher. The dispatcher body is renamed to `_dispatch_explanation` and a thin `build_explanation` wrapper attaches the `trail` and rewrites `chain` for per-issue kinds. Root-cause data is reused from `generate_root_cause_analysis` (no new tables, on-demand only). Frontend adds a "View full trail" button in the Why popup and a Trail mode renderer in the Audit tab.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, pytest monkeypatch; vanilla ES modules, `node --check` / `node scripts/check-js.js` / `node scripts/validate-imports.js`.

**Spec:** `docs/superpowers/specs/2026-10-15-us11-audit-trail-unification-design.md`

## Global Constraints

- TDD: write the failing test, watch it fail for the expected reason, then implement.
- Tests run with `.\\.venv\\Scripts\\python.exe -m pytest`.
- Scope is exactly three files: `app/engine/audit/explain.py`, `static/js/explain.js`, `static/js/audit.js`. Do NOT modify `app/api/*`, `app/engine/root_cause.py`, `app/models.py`, `static/js/app.js`, or `static/js/i18n.js` (reuse them).
- No new tables, no schema changes, no persistence. On-demand computation only.
- Backward compatible: existing `chain` step names `"Source Data"` and `"Validation"` must remain reachable by name; `chain` for aggregate kinds stays 4 entries with its existing `endpoint`s.
- Bilingual AR+EN on every trail stage: `detail` is a `{ar,en}` dict when the two differ, a plain string when equal. Graceful N/A stages carry a bilingual `na_reason` and `status="na"`.
- Do not introduce new ruff errors in the touched file (`npm run lint:py`).
- Frontend chrome labels avoid new `i18n.js` keys by using `currentLang` ternaries; payload-driven content uses the backend AR/EN fields.

---

## File Structure

- **Modify** `app/engine/audit/explain.py` — add trail primitives, root-cause cache/narrowing, per-issue + aggregate trail builders, and the `build_explanation` wrapper (rename of the existing dispatcher to `_dispatch_explanation`).
- **Modify** `static/js/explain.js` — add the "View full trail" footer action + `window._explainJumpTrail`.
- **Modify** `static/js/audit.js` — add `export function openAuditTrail(opts)`, the trail renderer, and `mode=trail` URL detection; expose `window.openAuditTrail`.
- **Create** `tests/test_explain_trail.py` — backend trail contract, narrowing, caching, graceful degradation.
- **Create** `tests/test_ui_audit_trail.py` — static frontend contract for the button/trail renderer + digest-guard regression.

---

### Task 1: Trail primitives (`_bilingual`, `_na_stage`, `_deep_link`, `_evidence_item`, `_stage`, `_chain_from_trail`)

**Files:**
- Modify: `app/engine/audit/explain.py` (add imports after line 30; add helpers before `build_explanation`, around line 1913)
- Test: `tests/test_explain_trail.py`

**Interfaces:**
- Produces:
  - `_bilingual(ar: str, en: str) -> str | dict`
  - `_na_stage(key: str, order: int, ar_label: str, en_label: str, ar_reason: str, en_reason: str) -> dict`
  - `_deep_link(endpoint: str | None = None, query: dict | None = None, hash_: str | None = None) -> dict | None`
  - `_evidence_item(label_ar: str, label_en: str, value, unit: str | None = None) -> dict`
  - `_stage(key, order, detail_ar, detail_en, status="has_content", na_reason=None, evidence_items=None, deep_link=None, source_engine=None) -> dict`
  - `_chain_from_trail(trail: list[dict]) -> list[dict]`
  - module constants `_TRAIL_STAGE_META: dict`, `_PER_ISSUE_KINDS: set`, `_CHAIN_STEP_NAMES: dict`

- [ ] **Step 1: Write the failing tests** — create `tests/test_explain_trail.py`:

```python
"""Tests for the US-11 unified audit trail (trail + 8-stage chain)."""
from app.engine.audit.explain import (
    _bilingual,
    _chain_from_trail,
    _deep_link,
    _evidence_item,
    _na_stage,
    _stage,
)


def test_bilingual_equal_returns_string():
    assert _bilingual("A", "A") == "A"


def test_bilingual_diff_returns_dict():
    assert _bilingual("\u0623", "A") == {"ar": "\u0623", "en": "A"}


def test_na_stage_carries_reason_and_status():
    st = _na_stage("root_cause", 5, "\u0627\u0644\u0633\u0628\u0628", "Root Cause", "\u0644\u0627", "No")
    assert st["status"] == "na"
    assert st["key"] == "root_cause"
    assert st["order"] == 5
    assert st["detail"] is None
    assert st["na_reason"] == {"ar": "\u0644\u0627", "en": "No"}


def test_evidence_item_optional_unit():
    assert _evidence_item("Effort AR", "Effort", "low") == {
        "label_ar": "Effort AR", "label_en": "Effort", "value": "low",
    }
    assert _evidence_item("p", "Points", 3, unit="quality points")["unit"] == "quality points"


def test_deep_link_builds_endpoint_and_hash():
    assert _deep_link(endpoint="/x") == {"endpoint": "/x"}
    assert _deep_link(hash_="audit?mode=trail") == {"hash": "audit?mode=trail"}
    assert _deep_link() is None


def test_chain_from_trail_uses_legacy_step_names_and_english_detail():
    trail = [
        _stage("raw_data", 1, "\u0623", "12 indicator values"),
        _stage("validation", 2, "\u0628", "none failed"),
        _stage("issue", 3, "\u062c", "issue"),
        _stage("evidence", 4, "\u062f", "evidence"),
        _stage("root_cause", 5, "\u0647", "rc"),
        _stage("impact", 6, "\u0648", "impact"),
        _stage("recommendation", 7, "\u0632", "rec"),
        _stage("action", 8, "\u062d", "act"),
    ]
    chain = _chain_from_trail(trail)
    assert len(chain) == 8
    assert chain[0]["step"] == "Source Data"
    assert chain[1]["step"] == "Validation"
    assert chain[2]["step"] == "Issue"
    assert chain[0]["detail"] == "12 indicator values"
    assert chain[0]["key"] == "raw_data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `ImportError: cannot import name '_bilingual'`.

- [ ] **Step 3: Implement the primitives** — edit `app/engine/audit/explain.py`.

Add imports (after line 30, `from typing import Optional`):

```python
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
```

Add `ConfidenceScore` to the model import block (lines 45-54):

```python
from app.models import (
    AnomalyResult,
    ConfidenceScore,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    Rule,
    ValidationResult,
)
```

Add constants + helpers immediately before `def build_explanation(` (line 1913):

```python
# ─────────────── US-11 unified audit trail (on-demand) ────────────────
_TRAIL_STAGE_META = {
    "raw_data": ("\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0623\u0635\u0644\u064a\u0629", "Raw Data"),
    "validation": ("\u0627\u0644\u062a\u062d\u0642\u0642", "Validation"),
    "issue": ("\u0627\u0644\u0645\u0634\u0643\u0644\u0629", "Issue"),
    "evidence": ("\u0627\u0644\u0623\u062f\u0644\u0629", "Evidence"),
    "root_cause": ("\u0627\u0644\u0633\u0628\u0628 \u0627\u0644\u062c\u0630\u0631\u064a", "Root Cause"),
    "impact": ("\u0627\u0644\u0623\u062b\u0631", "Impact"),
    "recommendation": ("\u0627\u0644\u062a\u0648\u0635\u064a\u0629", "Recommendation"),
    "action": ("\u0627\u0644\u0625\u062c\u0631\u0627\u0621", "Action"),
    # aggregate data-origin stages
    "calculation": ("\u0627\u0644\u062d\u0633\u0627\u0628 / \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a", "Calculation / Constituents"),
    "finding": ("\u0627\u0644\u0646\u062a\u064a\u062c\u0629", "Finding"),
}
_PER_ISSUE_KINDS = {
    "quality_score", "anomaly", "layered_outlier", "rule",
    "comparison_row", "trend_row", "time_period_point", "heatmap_cell",
}
_CHAIN_STEP_NAMES = {
    "raw_data": "Source Data",       # legacy name kept for backward compatibility
    "validation": "Validation",
    "issue": "Issue",
    "evidence": "Evidence",
    "root_cause": "Root Cause",
    "impact": "Impact",
    "recommendation": "Recommendation",
    "action": "Action",
}
_RC_NA_REASON = {
    "ar": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0628\u064a\u0627\u0646\u0627\u062a \u0633\u0628\u0628 \u062c\u0630\u0631 \u0645\u062d\u062f\u062f\u0629 \u0644\u0647\u0630\u0647 \u0627\u0644\u0645\u0634\u0643\u0644\u0629",
    "en": "No specific root cause data for this issue",
}


def _bilingual(ar, en):
    return ar if ar == en else {"ar": ar, "en": en}


def _na_stage(key, order, ar_label, en_label, ar_reason, en_reason):
    return {
        "key": key,
        "order": order,
        "ar": ar_label,
        "en": en_label,
        "status": "na",
        "detail": None,
        "na_reason": {"ar": ar_reason, "en": en_reason},
    }


def _deep_link(endpoint=None, query=None, hash_=None):
    if not endpoint and not hash_:
        return None
    link = {}
    if endpoint:
        link["endpoint"] = endpoint
    if query:
        link["query"] = {k: v for k, v in query.items() if v is not None}
    if hash_:
        link["hash"] = hash_
    return link


def _evidence_item(label_ar, label_en, value, unit=None):
    item = {"label_ar": label_ar, "label_en": label_en, "value": value}
    if unit is not None:
        item["unit"] = unit
    return item


def _stage(key, order, detail_ar, detail_en, status="has_content",
           na_reason=None, evidence_items=None, deep_link=None, source_engine=None):
    ar_label, en_label = _TRAIL_STAGE_META.get(key, (key, key))
    st = {
        "key": key,
        "order": order,
        "ar": ar_label,
        "en": en_label,
        "status": status,
        "detail": _bilingual(detail_ar, detail_en),
    }
    if na_reason is not None:
        st["na_reason"] = na_reason
    if evidence_items:
        st["evidence_items"] = evidence_items
    if deep_link:
        st["deep_link"] = deep_link
    if source_engine:
        st["source_engine"] = source_engine
    return st


def _link_url(link):
    if not link:
        return None
    if link.get("hash"):
        return link["hash"]
    endpoint = link.get("endpoint")
    if not endpoint:
        return None
    query = link.get("query") or {}
    return endpoint + ("?" + urlencode(query) if query else "")


def _chain_from_trail(trail):
    chain = []
    for st in trail:
        detail = st.get("detail")
        detail_str = detail.get("en", "") if isinstance(detail, dict) else (detail or "")
        chain.append({
            "step": _CHAIN_STEP_NAMES.get(st.get("key"), st.get("en", st.get("key"))),
            "detail": detail_str,
            "key": st.get("key"),
            "status": st.get("status"),
            "endpoint": _link_url(st.get("deep_link")),
        })
    return chain
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): add audit-trail primitives and 8-stage chain mapper"
```

---

### Task 2: Root-cause cache, narrowing, and impact/recommendation/action derivation

**Files:**
- Modify: `app/engine/audit/explain.py` (add helpers after `_chain_from_trail`)
- Test: `tests/test_explain_trail.py`

**Interfaces:**
- Consumes: `_evidence_item`, `_deep_link` (Task 1); `app.engine.root_cause.generate_root_cause_analysis`, `RootCauseReport`, `CausalChain`, `RuleFailurePattern`, `QualityDriver`, `PriorityActionDetail`; `app.engine.pipeline.run_full_analysis`.
- Produces:
  - `_load_root_cause_cached(db, hid: int, month: str, rc_cache: dict) -> RootCauseReport | None`
  - `_narrow_root_cause(rc_report, kind, rate_name=None, rule_code=None, indicator_code=None, component=None) -> dict` with keys `chain, rule_fail, qdriver, paction, general`
  - `_impact_from_narrowed(narrowed) -> dict` (`quantified, value, unit, severity`)
  - `_recommendation_from_narrowed(narrowed, kind) -> dict` (`ar, en, source`)
  - `_action_from_narrowed(narrowed, kind) -> dict` (`ar, en, effort, roi, impact, source`)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_explain_trail.py`:

```python
from app.engine.root_cause import (
    CausalChain,
    PriorityActionDetail,
    QualityDriver,
    RootCauseReport,
    RuleFailurePattern,
)
from app.engine.audit.explain import (
    _action_from_narrowed,
    _impact_from_narrowed,
    _load_root_cause_cached,
    _narrow_root_cause,
    _recommendation_from_narrowed,
)


def _sample_report():
    return RootCauseReport(
        hospital="General Hospital", hospital_id=1, month="2026-04",
        overall_quality_score=60.0, overall_confidence=50.0, critical_issues_count=1,
        top_rule_failures=[RuleFailurePattern(
            rule_code="R001", rule_description="deliveries total", severity="HIGH",
            failure_count=3, total_runs=4, failure_rate=75.0,
            primary_cause="totals mismatch", recommendation="reconcile totals",
            primary_cause_ar="\u0639\u062f\u0645 \u062a\u0637\u0627\u0628\u0642",
        )],
        quality_drivers=[QualityDriver(
            component="completeness", value=40.0, weight=0.25, impact=15.0,
            status="needs_improvement", recommendation="improve completeness",
        )],
        confidence_gaps=[], anomaly_patterns=[],
        summary="s", priority_actions=["reconcile totals"],
        priority_action_details=[PriorityActionDetail(
            action="Reconcile delivery totals for R001", source="rule",
            severity="HIGH", impact=12.0, effort=2, roi=6.0,
        )],
        causal_chains=[CausalChain(
            root_cause="R001 failing at 75%", root_cause_arabic="\u0641\u0634\u0644 R001",
            confidence=0.8, evidence=["e"], affected_factors=["R001"],
            recommended_action="Repair totals", impact_if_fixed=12.0,
            implementation_priority="HIGH", chain_path=["R001"],
            chain_path_arabic="R001",
        )],
    )


def test_narrow_rule_matches_by_rule_code():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    assert n["rule_fail"].rule_code == "R001"
    assert n["chain"] is not None
    assert n["general"] is False


def test_narrow_quality_score_matches_component_driver():
    n = _narrow_root_cause(_sample_report(), "quality_score", component="completeness")
    assert n["qdriver"].component == "completeness"
    assert n["general"] is False


def test_narrow_unknown_falls_back_to_general_chain():
    n = _narrow_root_cause(_sample_report(), "anomaly", rate_name="No Such Rate")
    assert n["general"] is True
    assert n["chain"] is not None  # top chain reused as general context


def test_impact_quantified_from_chain():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    imp = _impact_from_narrowed(n)
    assert imp["quantified"] is True
    assert imp["value"] == 12.0
    assert imp["unit"] == "quality points"


def test_recommendation_prefers_causal_chain():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    rec = _recommendation_from_narrowed(n, "rule")
    assert rec["en"] == "Repair totals"
    assert rec["source"] == "causal_chain"


def test_action_prefers_priority_action_detail():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    act = _action_from_narrowed(n, "rule")
    assert act["en"] == "Reconcile delivery totals for R001"
    assert act["effort"] == 2 and act["roi"] == 6.0


def test_load_root_cause_cached_calls_once(monkeypatch, db_session):
    from app.engine.audit import explain
    from app.models import ConfidenceScore, QualityScore

    db_session.add(QualityScore(
        hospital_id=1, month="2026-04", score=50.0,
        rule_compliance=50.0, completeness=50.0, consistency=50.0, outlier_penalty=0.0,
    ))
    db_session.add(ConfidenceScore(
        hospital_id=1, month="2026-04", overall_confidence=50.0, level="MEDIUM",
    ))
    db_session.commit()

    calls = {"n": 0}

    def fake_generate(session, hid, month, **kwargs):
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.engine.root_cause.generate_root_cause_analysis", fake_generate)
    cache = {}
    explain._load_root_cause_cached(db_session, 1, "2026-04", cache)
    explain._load_root_cause_cached(db_session, 1, "2026-04", cache)
    assert calls["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `ImportError: cannot import name '_narrow_root_cause'`.

- [ ] **Step 3: Implement the helpers** — append after `_chain_from_trail` in `app/engine/audit/explain.py`:

```python
def _load_root_cause_cached(db, hid, month, rc_cache):
    """Load (and cache per (hid, month)) the root-cause report — on demand."""
    if hid is None or not month:
        return None
    key = (hid, month)
    if key in rc_cache:
        return rc_cache[key]
    report = None
    try:
        from app.engine.pipeline import run_full_analysis
        from app.engine.root_cause import generate_root_cause_analysis

        qs = (
            db.query(QualityScore)
            .filter(QualityScore.hospital_id == hid, QualityScore.month == month)
            .first()
        )
        cs = (
            db.query(ConfidenceScore)
            .filter(ConfidenceScore.hospital_id == hid, ConfidenceScore.month == month)
            .first()
        )
        quality_data = None
        confidence_data = None
        if qs:
            quality_data = {
                "score": qs.score,
                "rule_compliance": qs.rule_compliance,
                "completeness": qs.completeness,
                "consistency": qs.consistency,
                "outlier_penalty": qs.outlier_penalty,
                "issues": json.loads(qs.issues) if qs.issues else [],
            }
        if cs:
            confidence_data = {
                "overall_confidence": cs.overall_confidence,
                "level": cs.level,
                "indicators": json.loads(cs.indicators_data) if cs.indicators_data else [],
                "by_level": {
                    "HIGH": cs.high_count, "MEDIUM": cs.medium_count,
                    "LOW": cs.low_count, "CRITICAL": cs.critical_count,
                },
            }
        if not quality_data or not confidence_data:
            full = run_full_analysis(db, hid, month)
            quality_data = quality_data or {
                "score": full.get("data_quality_score", 0),
                "rule_compliance": full.get("rule_compliance", 0),
                "completeness": full.get("completeness", 0),
                "consistency": full.get("consistency", 0),
                "outlier_penalty": full.get("outlier_penalty", 0),
                "issues": full.get("issues", []),
            }
            confidence_data = confidence_data or full.get("confidence", {})
        report = generate_root_cause_analysis(
            db, hid, month,
            quality_data=quality_data,
            confidence_data=confidence_data,
            include_history=True,
            compare_peers=False,
            months_back=6,
            peer_mode="auto",
        )
    except Exception as exc:  # graceful: later stages degrade to N/A
        logger.warning("trail: root cause failed for %s/%s: %s", hid, month, exc)
        report = None
    rc_cache[key] = report
    return report


def _narrow_root_cause(rc_report, kind, rate_name=None, rule_code=None,
                       indicator_code=None, component=None):
    """Pick the causal chain / rule failure / quality driver best matching an issue.

    Only narrows when an explicit match key exists; otherwise falls back to the
    hospital-month summary and flags ``general`` (never invents a link).
    """
    result = {"chain": None, "rule_fail": None, "qdriver": None, "paction": None, "general": True}
    if rc_report is None:
        return result

    if rule_code:
        for fail in rc_report.top_rule_failures:
            if fail.rule_code == rule_code:
                result["rule_fail"] = fail
                break
        for chain in rc_report.causal_chains:
            factors = set(chain.affected_factors or []) | set(chain.chain_path or [])
            if rule_code in factors:
                result["chain"] = chain
                result["general"] = False
                break

    if result["chain"] is None and component:
        for driver in rc_report.quality_drivers:
            if driver.component == component:
                result["qdriver"] = driver
                result["general"] = False
                break

    token = rate_name or indicator_code
    if result["chain"] is None and result["qdriver"] is None and token:
        base = token.replace(" (trend)", "")
        for pattern in rc_report.anomaly_patterns:
            if (pattern.rate_name or "").replace(" (trend)", "") == base:
                result["general"] = False
                break
        for driver in rc_report.quality_drivers:
            if driver.component == token:
                result["qdriver"] = driver
                result["general"] = False
                break
        for fail in rc_report.top_rule_failures:
            if token.lower() in (fail.rule_description or "").lower():
                result["rule_fail"] = fail
                result["general"] = False
                break

    if result["chain"] is None and rc_report.causal_chains:
        result["chain"] = rc_report.causal_chains[0]  # general hospital-month context

    source_pref = {"rule": "rule", "quality_score": "quality",
                   "time_period_point": "quality", "anomaly": "anomaly",
                   "layered_outlier": "anomaly"}.get(kind)
    details = rc_report.priority_action_details or []
    result["paction"] = (
        next((p for p in details if p.source == source_pref), None)
        if source_pref else (details[0] if details else None)
    )
    if result["paction"] is None and details:
        result["paction"] = details[0]
    return result


def _impact_from_narrowed(narrowed):
    chain = narrowed.get("chain")
    if chain is not None and getattr(chain, "impact_if_fixed", 0):
        return {"quantified": True, "value": float(chain.impact_if_fixed),
                "unit": "quality points",
                "severity": getattr(chain, "implementation_priority", "") or ""}
    driver = narrowed.get("qdriver")
    if driver is not None and getattr(driver, "impact", 0):
        return {"quantified": True, "value": float(driver.impact),
                "unit": "quality points", "severity": getattr(driver, "status", "") or ""}
    fail = narrowed.get("rule_fail")
    return {"quantified": False, "value": None, "unit": None,
            "severity": getattr(fail, "severity", "") if fail is not None else ""}


def _recommendation_from_narrowed(narrowed, kind):
    chain = narrowed.get("chain")
    if chain is not None and getattr(chain, "recommended_action", ""):
        return {"ar": getattr(chain, "root_cause_arabic", "") or "",
                "en": chain.recommended_action, "source": "causal_chain"}
    fail = narrowed.get("rule_fail")
    if fail is not None and getattr(fail, "recommendation", ""):
        return {"ar": getattr(fail, "primary_cause_ar", "") or "",
                "en": fail.recommendation, "source": "rule_failure"}
    driver = narrowed.get("qdriver")
    if driver is not None and getattr(driver, "recommendation", ""):
        return {"ar": "", "en": driver.recommendation, "source": "quality_driver"}
    return {"ar": "", "en": "", "source": "derived"}


def _action_from_narrowed(narrowed, kind):
    paction = narrowed.get("paction")
    if paction is not None:
        return {"ar": "", "en": paction.action, "effort": paction.effort,
                "roi": paction.roi, "impact": paction.impact, "source": paction.source}
    rec = _recommendation_from_narrowed(narrowed, kind)
    en = ("Implement: " + rec["en"]) if rec["en"] else ""
    return {"ar": rec["ar"], "en": en, "effort": None, "roi": None,
            "impact": None, "source": "derived"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): root-cause trail cache, narrowing, impact/recommendation/action"
```

---

### Task 3: Per-issue trail stages 1-4 (raw data, validation, issue, evidence)

**Files:**
- Modify: `app/engine/audit/explain.py` (add stage builders after `_action_from_narrowed`)
- Test: `tests/test_explain_trail.py`

**Interfaces:**
- Consumes: `get_data_audit` (`app.engine.audit.data_auditor`), payload fields `where`, `failed_rules`, `data_problems`, `what`, `reproduce`, `how`.
- Produces: `_raw_data_stage(db, hid, month, kind, payload)`, `_validation_stage(db, hid, month, kind, payload)`, `_issue_stage(kind, payload)`, `_evidence_stage(db, hid, month, kind, payload)` — each returns a stage dict.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_explain_trail.py`:

```python
from app.engine.audit.explain import (
    _evidence_stage,
    _issue_stage,
    _raw_data_stage,
    _validation_stage,
)


def test_raw_data_stage_for_anomaly_names_the_indicator(db_session):
    payload = {
        "kind": "anomaly", "month": "2026-04", "hospital_id": 1,
        "where": {"indicator_name": "Caesarean Sections", "source_files": ["upload.xlsx"]},
    }
    st = _raw_data_stage(db_session, 1, "2026-04", "anomaly", payload)
    assert st["key"] == "raw_data"
    assert "Caesarean Sections" in st["detail"] or "Caesarean Sections" in st["detail"]["en"]
    assert st["deep_link"]["endpoint"] == "/audit/data-auditor/1"


def test_validation_stage_names_failed_rule_codes():
    payload = {"failed_rules": [
        {"rule_code": "R_TEST", "severity": "HIGH"},
        {"rule_code": "R_OTHER", "severity": "LOW"},
    ]}
    st = _validation_stage(None, 1, "2026-04", "quality_score", payload)
    detail = st["detail"] if isinstance(st["detail"], str) else st["detail"]["en"]
    assert "R_TEST" in detail
    assert st["status"] == "has_content"


def test_issue_stage_is_always_content():
    st = _issue_stage("quality_score", {"what": "Score 42 for 2026-04"})
    assert st["status"] == "has_content"
    assert st["key"] == "issue"


def test_layered_evidence_stage_links_analysis_view():
    st = _evidence_stage(None, 1, "2026-04", "layered_outlier", {"reproduce": {}})
    assert st["deep_link"]["endpoint"] == "/analysis/layered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `ImportError: cannot import name '_raw_data_stage'`.

- [ ] **Step 3: Implement the stage builders** — append after `_action_from_narrowed`:

```python
def _raw_data_stage(db, hid, month, kind, payload):
    where = payload.get("where") or {}
    sources = where.get("source_files") or []
    data_audit = None
    if hid and month and db is not None:
        try:
            from app.engine.audit.data_auditor import get_data_audit
            data_audit = get_data_audit(db, hid, month)
        except Exception:
            data_audit = None
    n = where.get("raw_value_count")
    if n is None and data_audit:
        completeness = data_audit.get("completeness") or {}
        n = (completeness.get("present") or 0) + (completeness.get("covered") or 0)
    n = n if n is not None else 0
    suffix_en = f" from {len(sources)} file(s)" if sources else ""
    suffix_ar = f" \u0645\u0646 {len(sources)} \u0645\u0644\u0641" if sources else ""
    detail_en = f"{n} indicator values{suffix_en}"
    detail_ar = f"{n} \u0642\u064a\u0645\u0629 \u0645\u0624\u0634\u0631{suffix_ar}"
    ind_name = where.get("indicator_name")
    if ind_name:
        detail_en = f"{detail_en} \u2014 {ind_name}"
        detail_ar = f"{detail_ar} \u2014 {ind_name}"
    evidence = []
    if data_audit:
        completeness = data_audit.get("completeness") or {}
        evidence = [
            _evidence_item("\u0627\u0644\u062d\u0627\u0636\u0631", "Present", completeness.get("present")),
            _evidence_item("\u0627\u0644\u0645\u063a\u0637\u0649", "Covered", completeness.get("covered")),
            _evidence_item("\u0627\u062e\u062a\u064a\u0627\u0631\u064a", "Optional", completeness.get("optional")),
            _evidence_item("\u0627\u0644\u0645\u0641\u0642\u0648\u062f", "Missing", completeness.get("missing")),
        ]
    link = _deep_link(endpoint=f"/audit/data-auditor/{hid}", query={"month": month}) if hid and month else None
    return _stage("raw_data", 1, detail_ar, detail_en,
                  evidence_items=evidence or None, deep_link=link, source_engine="data_auditor")


def _validation_stage(db, hid, month, kind, payload):
    failed = payload.get("failed_rules") or []
    problems = payload.get("data_problems") or []
    codes = [str(r.get("rule_code")) for r in failed if r.get("rule_code")][:5]
    codes_str = ", ".join(codes)
    if failed:
        detail_en = f"Business rules evaluated on the raw values \u2014 {len(failed)} failed ({codes_str})"
        detail_ar = f"\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u2014 \u0641\u0634\u0644 {len(failed)} ({codes_str})"
    elif problems:
        detail_en = f"Business rules evaluated \u2014 {len(problems)} raw-data problem(s) detected"
        detail_ar = f"\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0627\u0644\u0642\u0648\u0627\u0639\u062f \u2014 {len(problems)} \u0645\u0634\u0643\u0644\u0629 \u0641\u064a \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a"
    else:
        detail_en = "Business rules evaluated on the raw values \u2014 none failed"
        detail_ar = "\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u2014 \u0644\u0645 \u062a\u0641\u0634\u0644 \u0623\u064a \u0642\u0627\u0639\u062f\u0629"
    evidence = []
    if failed:
        evidence.append(_evidence_item("\u0642\u0648\u0627\u0639\u062f \u0641\u0627\u0634\u0644\u0629", "Failed rules", len(failed)))
        for r in failed[:5]:
            evidence.append(_evidence_item("\u0642\u0627\u0639\u062f\u0629", "Rule", r.get("rule_code"), unit=r.get("severity")))
    link = _deep_link(endpoint=f"/audit/data-auditor/{hid}", query={"month": month}) if hid and month else None
    return _stage("validation", 2, detail_ar, detail_en,
                  evidence_items=evidence or None, deep_link=link, source_engine="data_auditor")


def _issue_stage(kind, payload):
    detail_en = payload.get("what") or payload.get("description") or "Detected issue"
    return _stage("issue", 3, detail_en, detail_en, source_engine=payload.get("kind", kind))


def _evidence_stage(db, hid, month, kind, payload):
    repro = payload.get("reproduce") or {}
    evidence = []
    for key, ar, en in (
        ("expected", "\u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected"),
        ("stored", "\u0627\u0644\u0645\u062e\u0632\u0651\u0646", "Stored"),
        ("expected_rate", "\u0627\u0644\u0645\u0639\u062f\u0644 \u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected rate"),
        ("expected_z", "z \u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected z"),
    ):
        if repro.get(key) is not None:
            evidence.append(_evidence_item(ar, en, repro.get(key)))
    if "verified" in repro:
        evidence.append(_evidence_item("\u0645\u064f\u062a\u062d\u0642\u0651\u0642", "Verified", bool(repro.get("verified"))))
    if kind == "layered_outlier":
        link = _deep_link(endpoint="/analysis/layered")
    elif hid and month:
        link = _deep_link(endpoint=f"/audit/calculation-steps/{hid}", query={"month": month})
    else:
        link = None
    return _stage("evidence", 4,
                  "\u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0625\u0646\u062a\u0627\u062c \u0648\u0627\u0644\u0645\u062f\u062e\u0644\u0627\u062a \u0645\u0646 \u0627\u0644\u062d\u0633\u0627\u0628",
                  "Reproduction and inputs from the calculation",
                  evidence_items=evidence or None, deep_link=link, source_engine="calculation_steps")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): per-issue trail stages 1-4 (raw data, validation, issue, evidence)"
```

---

### Task 4: Per-issue trail stages 5-8 (root cause, impact, recommendation, action) with graceful N/A

**Files:**
- Modify: `app/engine/audit/explain.py` (add `_root_cause_stages` + `_build_issue_trail` after `_evidence_stage`)
- Test: `tests/test_explain_trail.py`

**Interfaces:**
- Consumes: `_load_root_cause_cached`, `_narrow_root_cause`, `_impact_from_narrowed`, `_recommendation_from_narrowed`, `_action_from_narrowed`, `_na_stage`, `_stage`, `_deep_link`, `_evidence_item`, `_RC_NA_REASON`.
- Produces:
  - `_root_cause_stages(db, hid, month, kind, rate_name, rule_code, indicator_code, component, payload, rc_cache) -> list[dict]` (exactly 4 stages, keys `root_cause, impact, recommendation, action`; all `status="na"` + bilingual `na_reason` when no report)
  - `_build_issue_trail(db, hid, month, kind, rate_name, rule_code, indicator_code, component, payload, rc_cache) -> list[dict]` (8 stages in canonical order)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_explain_trail.py`:

```python
from app.engine.audit.explain import _build_issue_trail, _root_cause_stages


def test_root_cause_stages_are_na_without_report(db_session):
    stages = _root_cause_stages(
        db_session, 1, "2026-04", "quality_score",
        None, None, None, "completeness", {}, {},
    )
    assert [s["key"] for s in stages] == ["root_cause", "impact", "recommendation", "action"]
    assert all(s["status"] == "na" for s in stages)
    assert all(s["na_reason"]["ar"] and s["na_reason"]["en"] for s in stages)


def test_root_cause_stages_use_narrowed_chain(monkeypatch, db_session):
    from app.engine.audit import explain

    monkeypatch.setattr(explain, "_load_root_cause_cached",
                        lambda db, hid, month, cache: _sample_report())
    stages = _root_cause_stages(
        db_session, 1, "2026-04", "rule", None, "R001", None, None, {}, {},
    )
    assert stages[0]["key"] == "root_cause"
    assert stages[0]["status"] == "has_content"
    assert stages[0]["deep_link"]["endpoint"] == "/root-cause/1"
    assert stages[1]["key"] == "impact"
    assert stages[2]["recommendation"]["detail"]["en"] == "Repair totals"
    assert stages[3]["action"]["evidence_items"][0]["value"] == 2  # effort


def test_build_issue_trail_has_eight_ordered_stages(monkeypatch, db_session):
    from app.engine.audit import explain

    monkeypatch.setattr(explain, "_load_root_cause_cached",
                        lambda db, hid, month, cache: _sample_report())
    trail = _build_issue_trail(
        db_session, 1, "2026-04", "rule", None, "R001", None, None,
        {"kind": "rule", "what": "R001 failed", "failed_rules": [{"rule_code": "R001"}]},
        {},
    )
    assert [s["key"] for s in trail] == [
        "raw_data", "validation", "issue", "evidence",
        "root_cause", "impact", "recommendation", "action",
    ]
    assert [s["order"] for s in trail] == [1, 2, 3, 4, 5, 6, 7, 8]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `ImportError: cannot import name '_root_cause_stages'`.

- [ ] **Step 3: Implement the stages** — append after `_evidence_stage`:

```python
def _root_cause_stages(db, hid, month, kind, rate_name, rule_code,
                       indicator_code, component, payload, rc_cache):
    report = _load_root_cause_cached(db, hid, month, rc_cache)
    if report is None:
        na = _RC_NA_REASON
        return [
            _na_stage("root_cause", 5, *_TRAIL_STAGE_META["root_cause"], na["ar"], na["en"]),
            _na_stage("impact", 6, *_TRAIL_STAGE_META["impact"], na["ar"], na["en"]),
            _na_stage("recommendation", 7, *_TRAIL_STAGE_META["recommendation"], na["ar"], na["en"]),
            _na_stage("action", 8, *_TRAIL_STAGE_META["action"], na["ar"], na["en"]),
        ]

    narrowed = _narrow_root_cause(report, kind, rate_name=rate_name,
                                  rule_code=rule_code, indicator_code=indicator_code,
                                  component=component)
    general_note_en = "general to this hospital/month"
    general_note_ar = "\u0639\u0627\u0645 \u0644\u0647\u0630\u0627 \u0627\u0644\u0645\u0633\u062a\u0634\u0641\u0649/\u0627\u0644\u0634\u0647\u0631"
    rc_link = _deep_link(endpoint=f"/root-cause/{hid}",
                         query={"month": month, "include_history": "true", "compare_peers": "false"})

    chain = narrowed["chain"]
    fail = narrowed["rule_fail"]
    driver = narrowed["qdriver"]
    if chain is not None:
        rc_en = chain.root_cause or ""
        rc_ar = chain.root_cause_arabic or rc_en
        if narrowed["general"]:
            rc_en = f"{rc_en} ({general_note_en})"
            rc_ar = f"{rc_ar} ({general_note_ar})"
        rc_evidence = [_evidence_item("\u0627\u0644\u062b\u0642\u0629", "Confidence", chain.confidence)]
        if chain.chain_path:
            rc_evidence.append(_evidence_item(
                "\u0645\u0633\u0627\u0631 \u0627\u0644\u0633\u0644\u0633\u0644\u0629", "Chain path",
                chain.chain_path_arabic or " \u2192 ".join(chain.chain_path),
            ))
        if chain.affected_factors:
            rc_evidence.append(_evidence_item(
                "\u0627\u0644\u0639\u0648\u0627\u0645\u0644 \u0627\u0644\u0645\u062a\u0623\u062b\u0631\u0629",
                "Affected factors", ", ".join(chain.affected_factors),
            ))
        if chain.implementation_priority:
            rc_evidence.append(_evidence_item(
                "\u0627\u0644\u0623\u0648\u0644\u0648\u064a\u0629", "Priority", chain.implementation_priority,
            ))
        root_stage = _stage("root_cause", 5, rc_ar, rc_en,
                            evidence_items=rc_evidence, deep_link=rc_link,
                            source_engine="root_cause")
    elif fail is not None:
        rc_en = f"{fail.rule_code}: {fail.primary_cause} ({general_note_en})"
        rc_ar = fail.primary_cause_ar or fail.primary_cause or fail.rule_code
        rc_ar = f"{rc_ar} ({general_note_ar})"
        root_stage = _stage("root_cause", 5, rc_ar, rc_en,
                            evidence_items=[_evidence_item(
                                "\u0645\u0639\u062f\u0644 \u0627\u0644\u0641\u0634\u0644", "Failure rate",
                                fail.failure_rate)],
                            deep_link=rc_link, source_engine="root_cause")
    elif driver is not None:
        rc_en = f"{driver.component} driver ({driver.status}) ({general_note_en})"
        root_stage = _stage("root_cause", 5, rc_en, rc_en,
                            evidence_items=[_evidence_item(
                                "\u0627\u0644\u0642\u064a\u0645\u0629", "Value", driver.value)],
                            deep_link=rc_link, source_engine="root_cause")
    else:
        na = _RC_NA_REASON
        root_stage = _na_stage("root_cause", 5, *_TRAIL_STAGE_META["root_cause"], na["ar"], na["en"])

    impact = _impact_from_narrowed(narrowed)
    if impact["quantified"]:
        impact_en = f"{impact['value']} {impact['unit']} recoverable (severity {impact['severity'] or 'n/a'})"
        impact_ar = f"{impact['value']} \u0646\u0642\u0637\u0629 \u062c\u0648\u062f\u0629 \u0642\u0627\u0628\u0644\u0629 \u0644\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639"
        impact_evidence = [
            _evidence_item("\u0627\u0644\u0623\u062b\u0631", "Impact", impact["value"], unit=impact["unit"]),
            _evidence_item("\u0627\u0644\u062e\u0637\u0648\u0631\u0629", "Severity", impact["severity"]),
        ]
    else:
        sev = impact["severity"] or "n/a"
        impact_en = f"Not quantified \u2014 severity {sev}"
        impact_ar = f"\u063a\u064a\u0631 \u0645\u0642\u0627\u0633 \u2014 \u0627\u0644\u062e\u0637\u0648\u0631\u0629 {sev}"
        impact_evidence = [_evidence_item("\u0627\u0644\u062e\u0637\u0648\u0631\u0629", "Severity", sev)]
    impact_stage = _stage("impact", 6, impact_ar, impact_en,
                          evidence_items=impact_evidence, deep_link=rc_link, source_engine="root_cause")

    rec = _recommendation_from_narrowed(narrowed, kind)
    if rec["en"]:
        rec_stage = _stage("recommendation", 7, rec["ar"] or rec["en"], rec["en"],
                           evidence_items=[_evidence_item(
                               "\u0627\u0644\u0645\u0635\u062f\u0631", "Source", rec["source"])],
                           deep_link=rc_link, source_engine="root_cause")
    else:
        rec_stage = _na_stage("recommendation", 7, *_TRAIL_STAGE_META["recommendation"],
                              _RC_NA_REASON["ar"], _RC_NA_REASON["en"])

    act = _action_from_narrowed(narrowed, kind)
    if act["en"]:
        act_evidence = [_evidence_item("\u0627\u0644\u0645\u0635\u062f\u0631", "Source", act["source"])]
        if act["effort"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u062c\u0647\u062f", "Effort", act["effort"]))
        if act["roi"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u0639\u0627\u0626\u062f", "ROI", act["roi"]))
        if act["impact"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u0623\u062b\u0631", "Impact", act["impact"]))
        act_stage = _stage("action", 8, act["ar"] or act["en"], act["en"],
                           evidence_items=act_evidence, deep_link=rc_link, source_engine="root_cause")
    else:
        act_stage = _na_stage("action", 8, *_TRAIL_STAGE_META["action"],
                              _RC_NA_REASON["ar"], _RC_NA_REASON["en"])

    return [root_stage, impact_stage, rec_stage, act_stage]


def _build_issue_trail(db, hid, month, kind, rate_name, rule_code,
                       indicator_code, component, payload, rc_cache):
    stages = [
        _raw_data_stage(db, hid, month, kind, payload),
        _validation_stage(db, hid, month, kind, payload),
        _issue_stage(kind, payload),
        _evidence_stage(db, hid, month, kind, payload),
    ]
    stages.extend(_root_cause_stages(db, hid, month, kind, rate_name,
                                     rule_code, indicator_code, component,
                                     payload, rc_cache))
    return stages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: PASS (20 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): per-issue trail stages 5-8 with graceful N/A"
```

---

### Task 5: Aggregate 4-stage data-origin trail

**Files:**
- Modify: `app/engine/audit/explain.py` (add `_build_aggregate_trail` after `_build_issue_trail`)
- Test: `tests/test_explain_trail.py`

**Interfaces:**
- Produces: `_build_aggregate_trail(kind, payload) -> list[dict]` (4 stages, keys `raw_data, validation, calculation, finding`).

- [ ] **Step 1: Write the failing test** — append to `tests/test_explain_trail.py`:

```python
from app.engine.audit.explain import _build_aggregate_trail


def test_aggregate_trail_is_four_data_origin_stages():
    payload = {
        "kind": "month_overview", "what": "Month average 62 for 2026-04",
        "chain": [{"step": "Source Data", "detail": "x", "endpoint": "/audit/data-auditor/1?month=2026-04"}],
    }
    trail = _build_aggregate_trail("month_overview", payload)
    assert [s["key"] for s in trail] == ["raw_data", "validation", "calculation", "finding"]
    assert [s["order"] for s in trail] == [1, 2, 3, 4]
    assert trail[3]["detail"] == "Month average 62 for 2026-04"
    assert trail[0]["deep_link"]["endpoint"].startswith("/audit/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `ImportError: cannot import name '_build_aggregate_trail'`.

- [ ] **Step 3: Implement** — append after `_build_issue_trail`:

```python
def _build_aggregate_trail(kind, payload):
    where = payload.get("where") or {}
    sources = where.get("source_files") or []
    n = where.get("raw_value_count")
    hospitals = payload.get("hospitals") or []
    if n is None and hospitals:
        n = len(hospitals)
    if n is not None:
        raw_en = f"{n} constituent values" + (f" from {len(sources)} file(s)" if sources else "")
        raw_ar = f"{n} \u0642\u064a\u0645\u0629 \u0645\u0643\u0648\u0651\u0646\u0629" + (f" \u0645\u0646 {len(sources)} \u0645\u0644\u0641" if sources else "")
    else:
        raw_en = "Constituent data across the aggregate"
        raw_ar = "\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a \u0644\u0644\u062a\u062c\u0645\u064a\u0639"
    link = None
    for node in (payload.get("chain") or []):
        if node.get("endpoint"):
            link = _deep_link(endpoint=node["endpoint"])
            break
    what = payload.get("what") or "Aggregate finding"
    return [
        _stage("raw_data", 1, raw_ar, raw_en, deep_link=link, source_engine="data_auditor"),
        _stage("validation", 2,
               "\u062a\u062f\u0642\u064a\u0642 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u0639\u0644\u0649 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0629",
               "Business rules evaluated on the constituent data",
               deep_link=link, source_engine="data_auditor"),
        _stage("calculation", 3,
               "\u062d\u0633\u0627\u0628 \u0627\u0644\u062a\u062c\u0645\u064a\u0639 (\u0645\u062a\u0648\u0633\u0637/\u0646\u0637\u0627\u0642/\u0639\u062f\u062f) \u0639\u0628\u0631 \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a",
               "Aggregate computed across constituents (average / range / count)",
               deep_link=link, source_engine="calculation_steps"),
        _stage("finding", 4, what, what, source_engine=payload.get("kind", kind)),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: PASS (21 passed).

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): aggregate 4-stage data-origin trail"
```

---

### Task 6: `build_explanation` integration — attach `trail`, extend `chain` to 8 for per-issue kinds

**Files:**
- Modify: `app/engine/audit/explain.py` (rename `def build_explanation` at line 1913 to `def _dispatch_explanation`; add `_build_trail` + new `build_explanation` wrapper)
- Test: `tests/test_explain_trail.py` (integration via TestClient); verify no regression in `tests/test_explain*.py`, `tests/test_layered_api.py`

**Interfaces:**
- Consumes: `_build_issue_trail`, `_build_aggregate_trail`, `_chain_from_trail`, `_PER_ISSUE_KINDS`.
- Produces: `build_explanation(db, kind, hospital_id, month, rate_name=None, indicator_code=None, rule_code=None, component=None, hospital_name=None) -> dict` (unchanged public signature; now always attaches `trail`; `chain` becomes 8 stages for per-issue kinds and stays as-is for aggregates).

- [ ] **Step 1: Write the failing integration tests** — append to `tests/test_explain_trail.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.models import ConfidenceScore, IndicatorValue, QualityScore


@pytest.fixture()
def client(db_session):
    from app.main import app
    yield TestClient(app)


def _seed_score(db, month="2026-04", hid=1, score=60.0):
    db.add(QualityScore(
        hospital_id=hid, month=month, score=score,
        rule_compliance=60.0, completeness=50.0, consistency=55.0, outlier_penalty=0.0,
    ))
    db.commit()


def _add_raw(db, hid, month, value=120):
    from app.models import Indicator
    ind = db.query(Indicator).filter(Indicator.code == "2").first()
    db.add(IndicatorValue(hospital_id=hid, indicator_id=ind.id, month=month,
                          value=value, source_file="upload.xlsx"))
    db.commit()


def test_quality_score_payload_gains_eight_stage_trail_and_chain(db_session, client):
    hid = db_session.query(QualityScore).first() or 1
    hid = 1
    _add_raw(db_session, hid, "2026-04")
    _seed_score(db_session, "2026-04", hid)
    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={hid}&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert [s["key"] for s in p["trail"]] == [
        "raw_data", "validation", "issue", "evidence",
        "root_cause", "impact", "recommendation", "action",
    ]
    assert [s["order"] for s in p["trail"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert len(p["chain"]) == 8
    assert p["chain"][0]["step"] == "Source Data"
    assert p["chain"][1]["step"] == "Validation"
    for stage in p["trail"]:
        assert stage["status"] in ("has_content", "na")
        assert "ar" in stage and "en" in stage


def test_aggregate_kind_gets_four_stage_trail_and_keeps_four_chain(db_session, client):
    _seed_score(db_session, "2026-04", 1)
    resp = client.get("/audit/explain?kind=quality_score&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "month_overview"
    assert [s["key"] for s in p["trail"]] == ["raw_data", "validation", "calculation", "finding"]
    assert len(p["chain"]) == 4
    assert any("/audit/" in (n.get("endpoint") or "") for n in p["chain"])


def test_trail_stages_5_to_8_are_na_when_root_cause_unavailable(monkeypatch, db_session, client):
    def boom(*args, **kwargs):
        raise RuntimeError("no root cause available")
    monkeypatch.setattr("app.engine.root_cause.generate_root_cause_analysis", boom)
    _add_raw(db_session, 1, "2026-05")
    _seed_score(db_session, "2026-05", 1)
    db_session.add(ConfidenceScore(hospital_id=1, month="2026-05",
                                   overall_confidence=50.0, level="MEDIUM"))
    db_session.commit()
    resp = client.get("/audit/explain?kind=quality_score&hospital_id=1&month=2026-05")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    for stage in p["trail"][4:]:
        assert stage["status"] == "na"
        assert stage["na_reason"]["ar"]
        assert stage["na_reason"]["en"]


def test_no_trail_model_or_table_is_introduced():
    from app import models
    for name in dir(models):
        assert "Trail" not in name, f"unexpected model {name}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py -q`
Expected: FAIL — `KeyError: 'trail'` (the last 4 tests).

- [ ] **Step 3: Implement the integration** — rename line 1913 `def build_explanation(` to `def _dispatch_explanation(` (leave its body and docstring intact). Then, immediately after the renamed function's `return {"error": f"Unknown explanation kind: {kind!r}"}` (end of file, line 1999), append:

```python
def _build_trail(db, hid, month, kind, rate_name, rule_code,
                 indicator_code, component, payload, rc_cache):
    if kind in _PER_ISSUE_KINDS:
        return _build_issue_trail(db, hid, month, kind, rate_name, rule_code,
                                  indicator_code, component, payload, rc_cache)
    return _build_aggregate_trail(kind, payload)


def build_explanation(
    db: Session,
    kind: str,
    hospital_id: Optional[object],
    month: str,
    rate_name: Optional[str] = None,
    indicator_code: Optional[str] = None,
    rule_code: Optional[str] = None,
    component: Optional[str] = None,
    hospital_name: Optional[str] = None,
) -> dict:
    """US-11 wrapper: dispatch the base explanation, then attach the unified
    ``trail`` and extend ``chain`` to 8 stages for per-issue kinds."""
    payload = _dispatch_explanation(
        db, kind, hospital_id, month,
        rate_name=rate_name, indicator_code=indicator_code, rule_code=rule_code,
        component=component, hospital_name=hospital_name,
    )
    if not isinstance(payload, dict) or "error" in payload:
        return payload

    emitted_kind = payload.get("kind", kind)
    hid = payload.get("hospital_id")
    if not isinstance(hid, int):
        hid = (payload.get("where") or {}).get("hospital_id")
    if not isinstance(hid, int):
        hid = hospital_id if isinstance(hospital_id, int) else None
    resolved_month = payload.get("month", month)

    rc_cache = {}
    trail = _build_trail(db, hid, resolved_month, emitted_kind, rate_name,
                         rule_code, indicator_code, component, payload, rc_cache)
    payload["trail"] = trail
    if emitted_kind in _PER_ISSUE_KINDS:
        payload["chain"] = _chain_from_trail(trail)
    return payload
```

- [ ] **Step 4: Run scoped tests to verify pass + no regression**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py tests/test_explain.py tests/test_explain_comparative.py tests/test_explain_anomaly_reproduce.py tests/test_explain_covered_missing.py tests/test_layered_api.py tests/test_smart_explain.py tests/test_ui_explain_digest.py -q`
Expected: PASS (all). In particular `test_explain.py::test_quality_score_explanation_names_failed_rules` (`Validation` step detail names R_TEST), the anomaly Source Data test, and `test_layered_api` `/analysis/layered` endpoint assertion remain green.

- [ ] **Step 5: Commit**

```bash
git add app/engine/audit/explain.py tests/test_explain_trail.py
git commit -m "feat(explain): attach unified trail and extend chain to 8 stages (US-11)"
```

---

### Task 7: Frontend — "View full trail" button in the Why popup (`explain.js`)

**Files:**
- Modify: `static/js/explain.js` (`_renderAuditScreenLink` around line 159; add `window._explainJumpTrail` near `window._explainJumpFooter` at line 451)
- Test: `tests/test_ui_audit_trail.py`

**Interfaces:**
- Produces: `window._explainJumpTrail()` — reads `_lastOpts`, closes the popup, and calls `window.openAuditTrail(opts)` (fallback `window.SwitchTab('audit')`).
- Consumes: `window.openAuditTrail` (Task 8), existing `_lastOpts`, `closeWhyPopup`, `currentLang` import.

- [ ] **Step 1: Write the failing static test** — create `tests/test_ui_audit_trail.py`:

```python
"""Static contract for the US-11 Audit Trail view (no browser needed)."""
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static" / "js"
EXPLAIN_JS = JS / "explain.js"
AUDIT_JS = JS / "audit.js"


def _src(path):
    return path.read_text(encoding="utf-8")


def test_why_popup_has_view_full_trail_button():
    src = _src(EXPLAIN_JS)
    assert "View full trail" in src
    assert "window._explainJumpTrail" in src
    assert "window.openAuditTrail" in src


def test_digest_footer_contract_intact():
    src = _src(EXPLAIN_JS)
    assert "data-explain-footer" in src
    assert "window._explainJumpFooter" in src
    assert "Digest only" in src


def test_audit_exposes_open_audit_trail():
    src = _src(AUDIT_JS)
    assert "openAuditTrail" in src
    assert "window.openAuditTrail" in src


def test_audit_renders_trail_stages_status_and_evidence():
    src = _src(AUDIT_JS)
    assert "trail" in src
    assert "evidence_items" in src
    assert "na_reason" in src
    assert "has_content" in src


def test_audit_detects_trail_mode_from_url():
    src = _src(AUDIT_JS)
    assert "mode=trail" in src or "mode === 'trail'" in src
```

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ui_audit_trail.py -q`
Expected: FAIL — `test_why_popup_has_view_full_trail_button`.

- [ ] **Step 2: Implement the button** — edit `static/js/explain.js`.

Change the import at line 28 to include `currentLang`:

```javascript
import { __, currentLang } from './i18n.js';
```

Keep the existing `data-explain-footer` wrapper, its digest text span, and the "Open in audit screen" button **unchanged** — only add the second "View full trail" button inside the same footer. The digest text span must stay verbatim: `test_ui_explain_digest.py::test_footer_remains_the_single_audit_pointer` asserts `"Digest only"` is present, and that span (line 161) is its only occurrence in the file.

```javascript
function _renderAuditScreenLink() {
    const trailLabel = currentLang === 'ar' ? '\u0639\u0631\u0636 \u0627\u0644\u0645\u0633\u0627\u0631 \u0627\u0644\u0643\u0627\u0645\u0644' : 'View full trail';
    return '<div data-explain-footer style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-top:0.9rem;padding:0.55rem 0.7rem;border-top:1px solid var(--border-default,#ddd);">' +
        '<span style="font-size:0.72rem;color:var(--text-muted,#888);">' + __('Digest only — every number here is verified step-by-step on the Audit screen') + '</span>' +
        '<button onclick="window._explainJumpFooter()" style="background:var(--accent-blue,#1565c0);color:#fff;border:none;border-radius:4px;padding:4px 12px;font-size:0.72rem;font-weight:700;cursor:pointer;white-space:nowrap;">' + __('Open in audit screen') + ' \u2192</button>' +
        '<button data-explain-trail onclick="window._explainJumpTrail()" style="background:transparent;color:var(--accent-blue,#1565c0);border:1px solid var(--accent-blue,#1565c0);border-radius:4px;padding:4px 12px;font-size:0.72rem;font-weight:700;cursor:pointer;white-space:nowrap;">' + trailLabel + ' \u2192</button>' +
        '</div>';
}
```

Add after `window._explainJumpFooter` (line 451):

```javascript
window._explainJumpTrail = function () {
    if (!_lastOpts) return;
    closeWhyPopup();
    if (typeof window.closeModal === 'function') { try { window.closeModal(); } catch (e) { /* non-fatal */ } }
    const opts = {
        kind: _lastOpts.kind,
        hospitalId: _lastOpts.hospitalId,
        month: _lastOpts.month,
        rateName: _lastOpts.rateName,
        indicatorCode: _lastOpts.indicatorCode,
        ruleCode: _lastOpts.ruleCode,
        component: _lastOpts.component,
    };
    if (typeof window.openAuditTrail === 'function') {
        window.openAuditTrail(opts);
    } else if (typeof window.SwitchTab === 'function') {
        window.SwitchTab('audit');
    }
};
```

- [ ] **Step 3: Verify syntax + static tests**

Run: `node --check static/js/explain.js`
Expected: no output (exit 0).

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ui_audit_trail.py tests/test_ui_explain_digest.py -q`
Expected: PASS (trail button present; digest guard still green).

- [ ] **Step 4: Commit**

```bash
git add static/js/explain.js tests/test_ui_audit_trail.py
git commit -m "feat(explain-ui): add View full trail button to the Why popup"
```

---

### Task 8: Frontend — Trail mode renderer + deep link + URL detection (`audit.js`)

**Files:**
- Modify: `static/js/audit.js` (import `currentLang` at line 2; add `openAuditTrail`/`_renderTrail`/`_trailFromUrl` near the end; expose `window.openAuditTrail`)
- Test: `tests/test_ui_audit_trail.py`; syntax via `node --check` / `npm run check:js` / `npm run check:imports`

**Interfaces:**
- Consumes: `apiGet`, `esc`, `__`, `currentLang`, `window.SwitchTab`.
- Produces: `export function openAuditTrail(opts)` and `window.openAuditTrail`; renders `payload.trail` (8 or 4 stages) into `#auditResults`.

- [ ] **Step 1: Confirm the failing static test**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ui_audit_trail.py -q`
Expected: FAIL — `test_audit_exposes_open_audit_trail`.

- [ ] **Step 2: Implement** — edit `static/js/audit.js`.

Update the i18n import at line 2:

```javascript
import { __, currentLang } from './i18n.js';
```

Append near the end of the module (after `downloadAuditCSV`):

```javascript
// ── US-11 Audit Trail view (deep-linked from the Why popup) ──────────
function _trailQuery(opts) {
    const params = new URLSearchParams();
    if (opts.kind) params.set('kind', opts.kind);
    if (opts.hospitalId !== undefined && opts.hospitalId !== null) params.set('hospital_id', String(opts.hospitalId));
    if (opts.month) params.set('month', opts.month);
    if (opts.rateName) params.set('rate_name', opts.rateName);
    if (opts.indicatorCode) params.set('indicator_code', opts.indicatorCode);
    if (opts.ruleCode) params.set('rule_code', opts.ruleCode);
    if (opts.component) params.set('component', opts.component);
    return params.toString();
}

function _trailLinkUrl(link) {
    if (!link) return null;
    if (link.hash) return link.hash;
    if (!link.endpoint) return null;
    const q = link.query ? new URLSearchParams(link.query).toString() : '';
    return link.endpoint + (q ? '?' + q : '');
}

function _renderTrail(payload) {
    const container = document.getElementById('auditResults');
    if (!container) return;
    const isAr = currentLang === 'ar';
    const trail = payload.trail || [];
    let html = '<div class="card" data-audit-trail style="margin-bottom:0.8rem;padding:0.7rem 0.9rem;">';
    html += '<div style="font-weight:700;font-size:0.9rem;margin-bottom:0.5rem;">' +
        (isAr ? '\u0645\u0633\u0627\u0631 \u0627\u0644\u062a\u062f\u0642\u064a\u0642' : 'Audit Trail') +
        '</div>';
    trail.forEach(function (st) {
        const isNa = st.status === 'na';
        const label = isAr ? (st.ar || st.en) : (st.en || st.ar);
        const detail = typeof st.detail === 'string'
            ? st.detail
            : (st.detail ? (isAr ? st.detail.ar : st.detail.en) : '');
        html += '<div style="border-left:3px solid ' + (isNa ? 'var(--text-muted)' : 'var(--accent-blue)') +
            ';padding:0.4rem 0.6rem;margin:0.4rem 0;background:var(--bg-elevated);border-radius:0 4px 4px 0;">';
        html += '<div style="display:flex;justify-content:space-between;gap:0.6rem;align-items:center;">' +
            '<strong style="font-size:0.8rem;">' + (st.order) + '. ' + esc(label) + '</strong>' +
            '<span class="' + (isNa ? 'badge badge-medium' : 'badge badge-low') + '">' +
            esc(isNa ? __('N/A') : __('Available')) + '</span></div>';
        if (isNa && st.na_reason) {
            html += '<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.2rem;">' +
                esc(isAr ? st.na_reason.ar : st.na_reason.en) + '</div>';
        } else if (detail) {
            html += '<div style="font-size:0.78rem;margin-top:0.2rem;">' + esc(detail) + '</div>';
        }
        if (st.evidence_items && st.evidence_items.length) {
            html += '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.3rem;">';
            st.evidence_items.forEach(function (it) {
                const lbl = isAr ? (it.label_ar || it.label_en) : (it.label_en || it.label_ar);
                const unit = it.unit ? ' ' + it.unit : '';
                html += '<span style="font-size:0.68rem;background:var(--bg-surface-hover);border-radius:4px;padding:1px 6px;">' +
                    esc(lbl) + ': <strong>' + esc(it.value) + '</strong>' + esc(unit) + '</span>';
            });
            html += '</div>';
        }
        const url = _trailLinkUrl(st.deep_link);
        if (url) {
            html += '<div style="margin-top:0.3rem;"><button onclick="window.open(\'' +
                esc(url) + '\', \'_blank\')" style="background:none;border:1px solid var(--border-default);border-radius:4px;padding:2px 8px;font-size:0.68rem;cursor:pointer;color:var(--accent-blue);">' +
                (isAr ? '\u0641\u062a\u062d \u0627\u0644\u0645\u0635\u062f\u0631' : 'Open source') + '</button></div>';
        }
        html += '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
}

export function openAuditTrail(opts) {
    opts = opts || {};
    if (typeof window.SwitchTab === 'function') window.SwitchTab('audit');
    let tries = 0;
    (function _go() {
        const container = document.getElementById('auditResults');
        if (!container && ++tries < 80) { setTimeout(_go, 100); return; }
        if (!container) return;
        container.innerHTML = emptyState('\u23f3', __('Loading...'), '');
        apiGet('/audit/explain?' + _trailQuery(opts)).then(function (payload) {
            _renderTrail(payload);
        }).catch(function (err) {
            container.innerHTML = '<p style="color:var(--accent-red);padding:1rem;">' + __('Error: ') +
                esc(err && err.message ? err.message : 'error') + '</p>';
        });
    })();
}

window.openAuditTrail = openAuditTrail;

function _trailFromUrl() {
    try {
        const search = window.location.search || '';
        const hash = window.location.hash || '';
        const params = new URLSearchParams(search.indexOf('?') === 0 ? search : '?' + search);
        const hay = search + hash;
        if (hay.indexOf('mode=trail') === -1) return;
        const opts = {
            kind: params.get('kind'),
            hospitalId: params.get('hospital_id'),
            month: params.get('month'),
            rateName: params.get('rate_name'),
            indicatorCode: params.get('indicator_code'),
            ruleCode: params.get('rule_code'),
            component: params.get('component'),
        };
        if (opts.kind) openAuditTrail(opts);
    } catch (e) { /* malformed URL — ignore */ }
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _trailFromUrl);
} else {
    _trailFromUrl();
}
```

- [ ] **Step 3: Verify syntax, imports, and static tests**

Run: `node --check static/js/audit.js`
Expected: no output (exit 0).

Run: `npm run check:js`
Expected: `All NN JS files passed syntax validation.`

Run: `npm run check:imports`
Expected: exit 0 (no broken imports).

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ui_audit_trail.py tests/test_ui_explain_digest.py -q`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add static/js/audit.js tests/test_ui_audit_trail.py
git commit -m "feat(audit-ui): Trail mode renderer, deep link, and URL mode detection"
```

---

### Task 9: Full verification and acceptance

- [ ] **Step 1: Scoped regression suite**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_explain_trail.py tests/test_explain.py tests/test_explain_comparative.py tests/test_explain_anomaly_reproduce.py tests/test_explain_covered_missing.py tests/test_layered_api.py tests/test_smart_explain.py tests/test_root_cause.py tests/test_root_cause_improvements.py tests/test_ui_explain_digest.py tests/test_ui_audit_trail.py -q`
Expected: PASS.

- [ ] **Step 2: Ruff on the touched file**

Run: `.\\.venv\\Scripts\\python.exe -m ruff check app/engine/audit/explain.py`
Expected: no new errors (pre-existing repo dirt is acceptable only if unchanged).

- [ ] **Step 3: Frontend checks**

Run: `npm run check:js`
Run: `npm run check:imports`
Expected: both exit 0.

- [ ] **Step 4: Full suite (regression guard — do not fix unrelated failures)**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/ -q -p no:warnings --no-header`
Expected: no NEW failures versus the pre-change baseline (known env-only failures may remain).

- [ ] **Step 5: Manual acceptance (documented, not automated)**

Start `python -m uvicorn app.main:app` and verify:
1. Open any dashboard Why popup → "View full trail" appears next to "Open in audit screen".
2. Clicking it opens the Audit tab in Trail mode showing 8 stages in order with bilingual labels, status badges, evidence chips, and per-stage deep-link buttons.
3. A month-level aggregate explanation shows a 4-stage data-origin trail.
4. On a month without root-cause data, stages 5-8 show `N/A` with the bilingual reason and no crash.
5. Deep link `audit.html?tab=audit&mode=trail&kind=quality_score&hospital_id=<id>&month=YYYY-MM` opens the trail directly.

---

## Self-Review

- **Spec coverage:**
  - §1 payload `trail` + TrailStage fields → Tasks 1, 3, 4, 5, 6.
  - §2 stage mapping (raw data, validation, issue, evidence, root cause, impact, recommendation, action) → Tasks 3, 4.
  - §3 backend helpers + integration + rc cache + graceful degradation → Tasks 1, 2, 4, 6.
  - §4 frontend Explain button + Audit Trail mode + deep links + no new menu → Tasks 7, 8.
  - §5 tests (trail shape, aggregate 4-stage, degradation, narrowing, call-once cache, no new tables, reproduction preserved, JS syntax) → Tasks 1-9.
  - §6 risks: helper extraction (Tasks 1-6), popup stays a digest (Task 7 keeps `data-explain-footer`/Digest contract), no invented links (Task 2 `general` flag), rc cache (Task 2), bilingual (all tasks).
  - §7 scope restriction → only the three allowed files are modified.
- **Placeholder scan:** no TBD/TODO; every code step contains runnable code; every verification step has an exact command and expected result.
- **Type consistency:** `_stage`, `_na_stage`, `_deep_link`, `_evidence_item`, `_bilingual`, `_chain_from_trail`, `_load_root_cause_cached`, `_narrow_root_cause`, `_impact_from_narrowed`, `_recommendation_from_narrowed`, `_action_from_narrowed`, `_raw_data_stage`, `_validation_stage`, `_issue_stage`, `_evidence_stage`, `_root_cause_stages`, `_build_issue_trail`, `_build_aggregate_trail`, `_build_trail`, `_PER_ISSUE_KINDS`, `_CHAIN_STEP_NAMES`, `_TRAIL_STAGE_META`, `_RC_NA_REASON` are defined before use; `openAuditTrail`/`_explainJumpTrail` names match across Tasks 7-8. `_dispatch_explanation` is the renamed former `build_explanation` body and retains its exact signature.
- **Backward compatibility:** legacy chain step names `"Source Data"` and `"Validation"` are preserved by `_CHAIN_STEP_NAMES`; aggregate `chain` (4 stages, `/audit/` endpoints) is untouched; layered `/analysis/layered` endpoint is carried through the evidence stage.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-15-us11-audit-trail-unification.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task with review between tasks.
2. **Inline Execution** — execute tasks in this session using executing-plans with checkpoints.

Which approach?
