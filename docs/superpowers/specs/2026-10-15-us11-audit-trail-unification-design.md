# US-11 — Audit Trail Unification Design

**Date:** 2026-10-15  
**Status:** Approved (brainstorming complete)  
**Related:** `docs/superpowers/reports/2026-10-15-us10-ai-ml-audit.md`, existing `app/engine/audit/explain.py` (explanation engine), `app/engine/root_cause.py`

## Goal
As a DHIS auditor, I want every detected issue to be traceable from evidence to recommendation, so I can understand why the system reached a specific conclusion. The unified traceability chain is: **Raw Data → Validation → Issue → Evidence → Root Cause → Impact → Recommendation → Action**. Each result from the Dashboard must be traceable to the original data and the calculation that produced it.

## Approved Decisions (from clarification)
1. **Persistence model:** On-demand unification only. No new tables. "Action" = the system's recommended action (not human workflow). Fits the existing "ghost doctrine" (no derived tables).
2. **Trail surface:** Extend explain chain + dedicated trail view. Add a `trail` object to `/audit/explain` payload and extend `chain` to 8 stages for per-issue kinds (backward compatible). Add an Audit Trail mode in the Audit tab deep-linked from the Why popup.
3. **Issue scope:** All three classes (`data_problem`, `statistical_finding`, `clinical_finding`) with graceful degradation. Each stage either has content or an explicit "not applicable / insufficient data" reason.
4. **Language:** Bilingual AR primary + EN, consistent with existing i18n and root-cause AR/EN fields.
5. **View placement:** New "Trail" mode in the Audit tab (reuse `audit.read` permission; no new menu entry). Deep-linkable from Why popup.
6. **Impact/Recommendation/Action:** Impact = quantified consequence where engines produce it (quality points lost, risk level/score, affected factors/volume), else severity + "not quantified". Recommendation = strategy/what+why (root-cause fix). Action = concrete executable next step (from `priority_action_details` with effort/ROI), else derived imperative.
7. **Root-cause linkage:** Reuse hospital+month root-cause analysis (`generate_root_cause_analysis`) and narrow to the best matching causal chain/rule failure/quality driver (rule_code/rate/indicator/component). Fallback to hospital-month summary with note "general to this hospital/month". Graceful degradation.
8. **Kind scope:** Per-issue kinds get full 8-stage trail (quality_score, anomaly, layered_outlier, rule, comparison_row, trend_row, time_period_point, heatmap_cell). Aggregate kinds get a 4-stage data-origin trail (indicator_aggregate, governorate_row, ranking_entry, month_overview).

## Non-Functional Constraints
- TDD where applicable; minimal changes. Do not introduce new dependencies.
- Backward compatible: extend existing `chain` (array) to 8 stages for per-issue kinds; add new `trail` top-level field (non-breaking). Existing UI that iterates over `chain` continues to work.
- On-demand only (no new tables, no persistence). Reuse existing endpoints for deep links.
- Bilingual strings throughout (ar/en). Graceful N/A with explicit reasons.
- No unrelated lint fixes; don't introduce new ruff errors in touched files.

## 1) Unified Trail Contract (Payload Shape)

The `/audit/explain` response becomes a superset. For **per-issue kinds**, add:

```jsonc
{
  "trail": [
    {"key":"raw_data","order":1,"ar":"البيانات الأصلية","en":"Raw Data","status":"has_content","detail":{"ar":"...","en":"..."},"evidence_items":[...],"deep_link":{"endpoint":"/audit/data-auditor/{hid}","query":{"month":"YYYY-MM"}},"source_engine":"data_auditor"},
    ...
    {"key":"action","order":8,"ar":"الإجراء","en":"Action","status":"has_content","detail":{"ar":"...","en":"..."},"evidence_items":[{"label_ar":"الجهد","label_en":"Effort","value":"low"}],"deep_link":{"hash":"audit?tab=audit&mode=trail&..."},"source_engine":"root_cause"}
  ],
  "chain": [ /* extended to 8 stages in the same order/semantics */ ]
}
```

**TrailStage fields:**
- `key`: `raw_data|validation|issue|evidence|root_cause|impact|recommendation|action` (4 for aggregates)
- `order`: 1-8
- `ar,en`: bilingual labels
- `detail`: string or `{ar,en}`
- `status`: `has_content` | `na`
- `na_reason` (optional): `{ar,en}` when `na`
- `evidence_items` (optional): list of small key-value pairs `{label_ar,label_en,value,unit?}`
- `deep_link` (optional): `{endpoint?, query?, hash?}` pointing to existing endpoints (data-auditor, calculation-steps, root-cause, audit trail mode)
- `source_engine`: `data_auditor|calculation_steps|benchmark|explain|root_cause|clinical|quality|layered`

**Aggregates:** `chain` remains 4-stage (Source Data → Validation → Calculation → Finding). `trail` is a **4-stage data-origin trail** with the same keys mapped to data-origin semantics (Raw Data, Validation, Calculation/Constituents, Finding). Status/links still present.

**Backward compatibility:** `chain` values may gain richer detail text (AR/EN where natural) but structure/order is preserved conceptually and extended to 8 for per-issue kinds. The existing UI iterates over `chain` and will render additional steps.

## 2) Stage Mapping Rules (Per-Issue Kinds)

**1. Raw Data** (order 1)
- Sources: `_raw_values`, `get_data_audit` (completeness counts: total/present/covered/optional/missing), `IndicatorValue` (source_file). For rates, include numerator/denominator codes present.
- detail: e.g. `{ar:"{n} قيمة مؤشر", en:"{n} indicator values"}` + sources.
- deep_link: `/audit/data-auditor/{hid}?month={month}`
- evidence_items: present/covered/optional/missing counts, sources.

**2. Validation** (order 2)
- Sources: `get_data_audit` rule failures, `find_data_problems` (missing/negative/duplicate), `explain_rule` context where applicable.
- detail: failed count + none if clean. Classify data problems.
- deep_link: `/audit/data-auditor/{hid}?month={month}` (rule failures/problems section)
- evidence_items: failed rule codes/counts, data problem kinds.

**3. Issue** (order 3)
- Sources: the specific kind's headline (`what` from explain) — quality score below target, failed rule, anomaly, layered outlier, comparison/trend point, heatmap cell.
- detail: bilingual headline of the detected issue.
- status: has_content. No deep link required (self).

**4. Evidence** (order 4)
- Sources: reproduce/inputs from explain, benchmark (peer stats), calculation steps (num/den/values), z-score, classification/data_problems.
- detail: reproduction summary (verified where possible).
- evidence_items: reproduce.expected/stored/verified, inputs table essentials (value, benchmark, z, peer_count/std/min/max/median, peers_detail count, rate num/den if rate). Include "reproduced/verified" state.
- deep_link: `/audit/calculation-steps/{hid}?month={month}` and/or data-auditor as appropriate.

**5. Root Cause** (order 5) — per-issue only
- Resolve: call `generate_root_cause_analysis(db, hid, month, quality_data, confidence_data, include_history=True, compare_peers=False/True as needed, months_back=6, peer_mode='auto')` once per (hid,month) when any per-issue kind needs trail stages 5-8; cache in a dict for the current call to avoid duplicates. Compute `quality_data`/`confidence_data` from DB (QualityScore/ConfidenceScore) or fallback to `run_full_analysis` (existing pattern from root_cause API).
- Narrow: match by best key in order: `rule_code` (if kind==rule), `(rate_name or indicator_code)` (anomaly/layered/comparison/trend_row), `component` (quality_score/time_period_point), heatmap_cell → general hospital-month. Score matches: exact rule_code wins; rate/indicator substring or code match; else general.
- detail: selected `CausalChain.root_cause` + `root_cause_arabic` if matched; else hospital-month summary (top causal chain or "general to this hospital/month").
- evidence_items: `confidence`, `chain_path`/`chain_path_arabic`, `affected_factors` (compact), `implementation_priority`.
- deep_link: `/root-cause/{hid}?month={month}&include_history=true&compare_peers=false`
- na_reason when unmatched and no general chain usable: `{ar:"لا توجد بيانات سبب جذر محددة لهذه المشكلة", en:"No specific root cause data for this issue"}`

**6. Impact** (order 6) — quantified where available
- From narrowed causal chain: `impact_if_fixed` (quality points). From quality drivers/priority actions: impact/roi where meaningful. Map to numeric + label. If absent: severity from source + "not quantified".
- detail: bilingual quantified impact or severity+not quantified.
- evidence_items: impact value, unit ("quality points"), severity.
- deep_link: root-cause view (same as 5).

**7. Recommendation** (order 7) — strategy/what+why
- From narrowed: `CausalChain.recommended_action` (AR+EN if available), else `top_rule_failures.recommendation`, else `clinical/recommendations` or `confidence_gaps.recommendation`. Otherwise derive from primary cause.
- detail: bilingual recommendation text.
- evidence_items: source (causal_chain/rule_failure/quality_driver/derived).
- deep_link: root-cause.

**8. Action** (order 8) — concrete next step
- From narrowed/priority: prefer `PriorityActionDetail` matching the issue (action, effort, roi, impact, source). If none matched, derive imperative from recommendation (e.g., "Implement: ..."). Distinguish "do this now".
- detail: bilingual action text (imperative). Include effort/ROI when present.
- evidence_items: effort, roi, impact, source.
- deep_link: root-cause (priority actions section).

**Aggregates (data-origin trail, 4 stages):** Raw Data = constituent hospitals/counts + data sources; Validation = aggregate validation note; Calculation/Constituents = how aggregate computed (avg/range/std/count) with deep link to the aggregate's source view (indicator_aggregate/governorate/ranking/month_overview endpoints or existing explain deep links); Finding = aggregate headline. Graceful N/A only where meaningless.

## 3) Backend Implementation (explain.py)

**Files touched:** `app/engine/audit/explain.py` (primary). No new tables.

**Add helpers (inside explain.py):**
- `_na_stage(key, ar_label, en_label, ar_reason=None, en_reason=None) -> dict`
- `_bilingual(detail_ar, detail_en) -> any` (string if equal else {ar,en})
- `_deep_link(**kw) -> dict|None`
- `_evidence_item(label_ar,label_en,value,unit=None) -> dict`
- `_rc_cache_key(hid,month):` not needed; just dict `{(hid,month): report}`
- `_load_root_cause_cached(db, hid, month, rc_cache: dict)` → `RootCauseReport|None`
- `_narrow_root_cause(rc_report, kind, rate_name, rule_code, indicator_code, component)` → dict with best match: `{chain: CausalChain|None, rule_fail: RuleFailurePattern|None, qdriver: QualityDriver|None, paction: PriorityActionDetail|None, general: bool}`
- `_impact_from_narrowed(narrowed)` → dict (value, unit, severity, quantified bool, ar,en)
- `_recommendation_from_narrowed(narrowed, kind)` → dict (ar,en,source)
- `_action_from_narrowed(narrowed, kind)` → dict (ar,en,effort,roi,impact,source)
- `_evidence_items_for(kind, explain_payload, narrowed=None)` → list
- `_build_trail_stages(db, hid, month, kind, rate_name, rule_code, indicator_code, component, explain_payload, rc_cache: dict)` → list[dict]

**Integration in `build_explanation`:**
- For each call producing a payload, after building the base explain dict for a kind, compute `trail = _build_trail_stages(...)`. 
- For **per-issue kinds**, set `chain` to 8 stages (map trail stages 1-8 into chain entries with same bilingual detail/semantics and deep links). Keep existing chain structure fields where present.
- For **aggregates**, set `trail` to 4-stage data-origin; `chain` remains 4-stage as today (or enriched but length preserved in meaning; aggregates use 4-stage).
- Attach `trail` to payload. Do not mutate cached external state.

**Root-cause call pattern:** mirror root_cause API: prefer DB QualityScore/ConfidenceScore; else `run_full_analysis`. Handle exceptions gracefully (log warning, set later trail stages to N/A with reason).

**Graceful degradation:** every stage has `status` and `na_reason` when absent. No invented causal links.

## 4) API/Frontend (Audit Trail View + Popup)

**Backend:** No new endpoint required; `/audit/explain` returns `trail`. Deep links reuse existing endpoints.

**Frontend — `static/js/explain.js`:**
- Add "View full trail" button in the Why popup (when a result is shown). Link to Audit tab Trail mode with all params: `kind, hospital_id, month, rate_name, rule_code, indicator_code, component, hospital_name` (serialize safely, handle nulls).
- Popup may continue to render `chain` (now 8-stage) compactly; the new button is the primary jump to full trail.

**Frontend — `static/js/audit.js`:**
- Add Trail mode: detect `mode=trail` from URL/query/hash (support `location.search` and hash). On init, if `mode==='trail'`, render full-width Audit Trail view.
- Trail view: render 8 vertical stages (timeline) with ar/en labels, detail, status badges (has_content/na), evidence_items as compact key-value, and action buttons for deep_link (open in same tab or new). For aggregates show 4-stage data-origin trail.
- Fetch explanation via `GET /audit/explain` with the same params (deep-linked). Handle loading/error states.
- Bilingual rendering (respect UI language if present, default AR primary per app).

**Frontend — `static/html/audit.html` (if needed):** no structural change required; audit.js renders modes dynamically.

**Deep-link format:** `audit.html?tab=audit&mode=trail&kind=quality_score&hospital_id=5&month=2026-10` (+ optional params). Also support hash form for SPA navigation.

## 5) Testing & Verification

**Backend tests (pytest):**
- `tests/test_explain.py` / existing explain tests still pass (backward compatible).
- New tests: per-issue kind produces `trail` with 8 stages, correct order/keys, bilingual present, deep links non-empty where applicable. Aggregate kinds produce 4-stage data-origin trail.
- Graceful degradation: missing root-cause data → stages 5-8 have `status='na'` with bilingual reason; no crash.
- Narrowing: rule kind matches by `rule_code`; anomaly matches by rate/indicator; quality_score by component.
- On-demand: root-cause called once per (hid,month) (cache behavior) when multiple lookups not needed; no new tables created.
- Reproduction/verified preserved in Evidence.

**Frontend:** `node --check static/js/audit.js static/js/explain.js` (syntax). No new deps.

**Regression guard:** run full suite; do not fix unrelated pre-existing failures. Focus on touched areas.

## 6) Risks & Mitigations
- `build_explanation` grows: extract helpers into small private functions (mitigated). Keep per-kind branches unchanged.
- Popup cramped: solved by linking to full trail view, not inlining everything.
- False causal linkage: only narrow when explicit match keys exist; else general + explicit note. Never invent links.
- Duplicate root-cause calls: per (hid,month) cache in `rc_cache` dict during a single `build_explanation` call.
- Bilingual consistency: use existing AR strings from root_cause/i18n where possible; add minimal new labels.

## 7) Scope Restriction
**Only**: `app/engine/audit/explain.py`, `static/js/explain.js`, `static/js/audit.js`. Do **not** modify root_cause/api endpoints, models, or other engines (we reuse them). No schema changes.