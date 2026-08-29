# Butterfly Intelligence — Intelligent Analysis Comprehensive Report Redesign

**Date:** 2026-08-29
**Status:** Approved design
**Scope:** Upgrade ONLY the "Intelligent Analysis" / "التحليل الذكي" module's comprehensive report presentation.
**Architecture:** Hybrid — backend produces per-section Arabic narratives (AI with deterministic fallback); frontend builds structured cards/tables/charts from the existing analytics `data` envelope.

## 1. Objective

Transform the current Intelligent Analysis output from a long plain-text technical dump into a professional, comprehensive, decision-oriented **Clinical Intelligence Report** following the logic:

> Current Situation → Risk → Where → Why → Early Warning → Forecast → Evidence → Recommended Action

Serving two audiences:
- **Executive** (MOH managers, hospital directors): information first.
- **Technical** (MEAL/M&E, epidemiologists, analysts): evidence later in the same report.

## 2. Key Decisions (from brainstorming)

1. **Architecture = Hybrid.** Backend produces per-section Arabic narratives (AI via `_call_api`, split into per-section strings; deterministic local fallback when AI unavailable). Frontend lays out those narratives inside structured section cards/tables/charts it builds from the existing `data` envelope.
2. **No new statistical engines.** Reuse all existing analytics (risk score, SHAP, clusters, FDR/Granger, correlation, residuals, stratified peer comparison, regional, xgboost/forecast, decision & forecast briefs).
3. **Keep AI generation**, split into per-section narratives, deterministic fallback (as today).
4. **Presentation-only derivations** where the spec implies new analytics:
   - Persistent deterioration (R²): simple linear trend computed on the frontend from existing monthly trend series.
   - Small-sample warnings: derive from existing `regional.mortality[].small_sample` / birth counts.
   - Data-quality alerts: limited to what is derivable from the existing envelope (small sample, zero, extreme deviation). No full missing/duplicate scanning.
5. **Approach A** — Sectioned renderer + narrative map (not generic JSON block renderer, not minimal wrapper).

## 3. Non-Goals / Scope Boundary

Do NOT modify:
- Login, dashboard homepage, hospital management, data entry, Excel import, DB structure, existing data-quality rules, navigation, other reports, user/auth management, existing clinical calculations, or existing analytical computations.
- Backend APIs only change in ways strictly needed to support this report (`/comparative/comprehensive-report/{month}` response shape + the report generator + report cache).

Preserve all existing analytical calculations and the `data` envelope value.

## 4. Architecture

### 4.1 Data Flow
- `generate_comprehensive_report()` (unchanged orchestrator) runs `run_smart_analytics`, reuses regional cache, builds `_build_decision_brief` and `_build_forecast_brief`.
- The flat `report` string assembly is replaced by a **structured `sections` map**: `{ section_key: narrative_arabic }`.
- The AI prompt is reorganized into a per-section prompt; AI/local output is parsed into `sections` keyed by section key.
- The `data` envelope is unchanged and returned in full (all numbers needed for tables/charts).
- Language toggle (`?lang=ar|en`) still works: per-section narratives re-generated per language; `data` numbers stay language-agnostic.
- AI persistence (`report_cache.py`) extended to cache the `sections` map alongside the stored result.

### 4.2 New Response Shape
```jsonc
{
  "month": "2025-01",
  "report_source": "ai" | "local",
  "sections": {
    "exec_summary": "...",
    "key_messages": "...",
    "priority_hospitals": "...",
    "geo_risk": "...",
    "early_warnings": "...",
    "current_trends": "...",
    "forecast": "...",
    "clinical_relations": "...",
    "composite_patterns": "...",
    "anomaly_intel": "...",
    "top_deviations": "...",
    "regional_intel": "...",
    "deterioration": "...",
    "data_quality": "...",
    "recommendations": "...",
    "conclusion": "...",
    "appendix": "..."
  },
  "report": "<backward-compat concatenation of sections>",
  "data": { /* unchanged envelope: hospitals_count, kpi, anomalies, clustering,
              correlations, residuals, stratified, explanations, geo, patterns,
              xgboost, regional, decision, forecast */ }
}
```
The `report` field (concatenation of sections) is kept for backward compatibility so any existing consumer reading `.report` (including the prior flat renderer path) still works.

## 5. Report Section Model

Final order = the required report hierarchy (spec sec. 28).

| # | Section key | Title (Ar) | Data source (in `data`) | Primary component |
|---|---|---|---|---|
| 1 | `exec_summary` | الملخص التنفيذي + الحالة العامة | `decision` (verdict, risk_score), `kpi` (counts), `geo.governorates` (affected govs) | Status header (Critical/Warning/Normal badge) + KPI row |
| 2 | `key_messages` | أهم الرسائل التنفيذية | `kpi`, anomalies count, `decision.risk_score`/hotspots, top pattern/driver | 5–7 bullet cards, icon + short text |
| 3 | `priority_hospitals` | المستشفيات ذات الأولوية | `anomalies` (severity, score), `explanations` (top factors) | Table: الترتيب/المستشفى/المحافظة/درجة الخطر/الحالة/سبب الأولوية; sorted by risk desc |
| 4 | `geo_risk` | التوزيع الجغرافي للمخاطر | `geo.governorates` (avg/max score, outlier_count) | Gaza SVG map (existing) + governorate table, highlight max-risk |
| 5 | `early_warnings` | إشارات الإنذار المبكر | `forecast`, `residuals`, lag analysis | Warning cards with EARLY WARNING SCORE bar (probability/confidence) |
| 6 | `current_trends` | الاتجاهات الشهرية | `regional.trends`, indicator stats (prev-month deltas) | Per-indicator cards: current/prev/abs change/% change/direction/severity + interpretation |
| 7 | `forecast` | التنبؤ بالمخاطر المستقبلية | `forecast.hospitals`, `xgboost.predictions` | Table + trajectory; current vs predicted SEPARATED (two-column, not mixed) |
| 8 | `clinical_relations` | تحليل المؤشرات والعلاقات | `correlations.strong_correlations` (r) | Ranked correlation cards + tip "الارتباط لا يثبت السببية" |
| 9 | `composite_patterns` | الأنماط المركبة | `patterns` (indicators, support, lift) | Pattern cards with Lift badge + tooltip |
| 10 | `anomaly_intel` | تحليل الحالات الشاذة | `anomalies`, `explanations` (SHAP), `residuals` | Per-hospital cards: Anomaly Score SEPARATED from indicator deviation; SHAP top factors in Arabic; residual insight |
| 11 | `top_deviations` | أكبر الانحرافات عن المستشفيات المماثلة | `stratified` (peer deviation) | Table: top 5 by deviation%, + الإجراء |
| 12 | `regional_intel` | Regional Health Intelligence | `regional.governorates` (rates, benchmarks, percentile) | Regional comparison table + auto interpretation |
| 13 | `deterioration` | تدهور مستمر | Frontend-computed linear trend (slope + R²) from existing monthly trend series | Cards: indicator/gov/monthly change/R²/direction/severity |
| 14 | `data_quality` | تنبيهات جودة البيانات + حجم العينة | small-sample (`regional.mortality[].small_sample`), zero, extreme deviation | Alert cards: Severity/Issue/Affected hospital/Affected indicator/Recommended verification |
| 15 | `recommendations` | توصيات + مصفوفة الأولويات | `decision.priorities`, forecast, top deviations | Priority matrix table (🔴🟠🟡🔵) + evidence-linked recommendations |
| 16 | `conclusion` | الخلاصة التنفيذية | Aggregated verdict + forecast + top actions | 3-part conclusion (الوضع/الخطر القادم/الإجراء) |
| 17 | `appendix` | الملحق الفني | All raw: FDR/corr/SHAP/residuals/clustering/silhouette/peer/prediction | Collapsible technical appendix |

## 6. Frontend Renderer

- `static/js/smart/report.js` keeps orchestration: fetch, language toggle, section container, KPI dashboard, decision board, peer comparison (all existing blocks retained/enriched, not removed).
- Replace the flat `renderReportLines()` with a **section dispatcher**.
- New module `static/js/smart/report-sections.js`: exports one `renderSection(sectionKey, data, narrative)` per section. Dispatcher maps each key → renderer → CSS container.
- Every renderer builds structured HTML (tables, cards, badges, priority matrix) and embeds the matching `sections[key]` narrative at the top or bottom of that card.
- Charts via existing Plotly `charts.js` helpers. Gaza SVG map and PCA-biplot logic already exist and are reused.
- RTL: Arabic-first layout, `direction: rtl` on report container, LTR on numeric/technical cells.

### 6.1 CSS — "Butterfly Intelligence"
New block in `static/css/styles.css` with `bi-` prefixed classes:
- Balanced two-column layouts (`.bi-grid-2`), central intelligence cards.
- Clean KPI cards (`.bi-kpi`), severity badges (`.bi-badge-critical/warning/normal`).
- Symmetrical visual hierarchy, clear section separators (`.bi-section`, `.bi-section-title`), consistent spacing.
- Professional charts (reuse Plotly), minimal colors, severity map (green→orange→red).
- Use cards only for important information (not every metric).

### 6.2 Data-derived vs Narrative-derived discipline
- Tables/numbers/rankings/charts → computed from the `data` envelope only (real analytics, never fabricated).
- Interpretive sentences (interpretation, "why", conclusions, warnings) → from `sections[key]` narrative only.
- No sentence is both; the narrative never introduces numbers not in the envelope; the renderer never fabricates numbers.

## 7. Backend Narrative Split

- `build_comprehensive_prompt()` reorganized to ask AI for a response mapped to section keys (numbered/JSON), given the same computed stats.
- Parser `_parse_sections(ai_text, keys)` extracts per-section narratives; on parse failure or AI failure → `_build_local_sections()` (deterministic Arabic templates filling in the same real numbers).
- Deterministic fallback covers **all 17 section keys** so non-AI deployments still get a complete structured report.
- `report_source` stays `"ai"`/`"local"` for transparency.
- Cache: `report_cache.py` stores full `sections` + report. Bump cache version/key if shape changes.

## 8. Language Rules (spec sec. 25)

- Report primarily Arabic. English only where the technical term is useful: e.g. **درجة الخطر (Risk Score)**, **درجة الشذوذ (Anomaly Score)**, **الارتباط الزمني (Lead-Lag Relationship)**, **التفسير القابل للشرح (SHAP Explainability)**.
- Never say "leads to" / "causes". Use **"ارتباط زمني إحصائي مع"**.

## 9. Critical Statistical Rules (spec sec. 26)

- Never state correlation = causation.
- Never state Granger = medical causality.
- Never state forecast = certainty.
- Use: statistical association / temporal association / early warning signal / predicted risk / requires clinical or data validation.
- Always keep Anomaly Score separate from Indicator Deviation; display in separate labeled blocks.
- Always keep Current Risk separate from Forecast Risk; display separately (two-column, never mixed).

## 10. Visual Style (spec sec. 27)
Premium clinical "Butterfly Intelligence": balanced two-column layouts, central intelligence cards, symmetrical hierarchy, clean KPI cards, severity badges, minimal colors, professional charts, clear section separators, Arabic RTL typography, consistent spacing, strong visual hierarchy. Do not turn every metric into a card.

## 11. Technical Appendix (section 17 / spec 24)
At end of same report, collapsible, for technical reviewers: FDR results, Granger/lead-lag results, correlation coefficients, SHAP values, residuals, clustering + silhouette score, peer comparison, prediction methodology, statistical thresholds.

## 12. Testing

Backend unit tests:
- `_parse_sections` parses AI output into all keys.
- Deterministic fallback completeness: all 17 keys present.
- `report` field = concatenation of `sections`.
- Existing tests still pass: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short` (72 passing).

Frontend: no new test framework; keep existing tests passing. No new statistical computations to unit-test (presentation only).

## 13. Implementation Phases

- **Phase A — Backend**: `sections` map + per-section prompt + parser + local fallback + cache + backward-compat `report`.
- **Phase B — Frontend renderer**: Butterfly CSS + section dispatcher + the 17 section renderers (exec_summary, priority_hospitals, geo_risk, early_warnings, forecast, appendix first; then the rest).
- **Phase C — Polish & verify**: RTL audit, wording audit (sec 25/26), full test pass, manual review.

## 14. Final Acceptance Criteria

- [ ] Comprehensive structured report
- [ ] Executive summary first
- [ ] Critical hospitals clearly identified
- [ ] Geographic risk clearly presented (Gaza map)
- [ ] Early warning section with score bars
- [ ] Forecast section
- [ ] Current vs predicted risk separated
- [ ] Correlation separated from causation (wording)
- [ ] Anomaly Score separated from indicator deviation
- [ ] SHAP explained in simple Arabic
- [ ] Regional comparison table
- [ ] Persistent deterioration (R²)
- [ ] Composite patterns
- [ ] Data quality warnings (derivable subset)
- [ ] Small sample warnings
- [ ] Evidence-based recommendations (priority matrix)
- [ ] Technical appendix (collapsible)
- [ ] RTL Arabic
- [ ] Professional Butterfly-style visualization
- [ ] Existing analytics preserved
- [ ] No fabricated data
- [ ] No hard-coded findings
- [ ] No changes outside the Intelligent Analysis module (plus the report generator/cache as strictly required)
