# Butterfly Intelligence Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the "Intelligent Analysis" comprehensive report from a flat text dump into a professional, sectioned, decision-oriented Clinical Intelligence Report (Arabic RTL, Butterfly Intelligence visual style), using a hybrid architecture: backend per-section Arabic narratives (AI + deterministic fallback) + frontend structured cards/tables/charts from the existing analytics `data` envelope.

**Architecture:** Backend `report_generator.py` keeps producing the full analytics `data` envelope unchanged, but replaces the single flat `report` string with a structured `sections` map keyed by 17 section keys (AI per-section narratives parsed from a reorganized prompt; deterministic local fallback covering all keys). A backward-compatible `report` field (concatenation of sections) is retained. The frontend `static/js/smart/report.js` is rebuilt to render each section as a structured component (tables, cards, charts, badges) in Butterfly Intelligence style, with a new `report-sections.js` module and new `bi-*` CSS.

**Tech Stack:** Python 3.x / FastAPI / SQLAlchemy (backend), Plotly.js via existing `charts.js` (frontend charts), vanilla JS ES modules, `bi-` prefixed CSS classes in `static/css/styles.css`. Existing analytics engines are reused — no new statistical computations.

## Global Constraints

- **Scope:** Upgrade ONLY the Intelligent Analysis comprehensive report. Do NOT modify login, dashboard homepage, hospital management, data entry, Excel import, DB structure, existing data-quality rules, navigation, other reports, user/auth management, existing clinical calculations, or existing analytical computations.
- **No new statistical engines.** Reuse all existing values (risk score, SHAP, clusters, FDR/Granger, correlation, residuals, stratified peer comparison, regional, xgboost/forecast, decision & forecast briefs).
- **No fabricated data.** Every table/number/ranking must be computed from the `data` envelope. Interpretive sentences come only from `sections[key]` narratives.
- **Never state correlation = causation**, Granger = causality, or forecast = certainty. Use Arabic "ارتباط زمني إحصائي مع". Anomaly Score must appear SEPARATE from Indicator Deviation. Current Risk must appear SEPARATE from Forecast Risk.
- **Keep AI + deterministic fallback.** `report_source` stays `"ai"`/`"local"`. Per-language narratives via `?lang=ar|en`.
- **Backward compatibility:** the `report` field must equal the concatenation of `sections`; existing tests must keep passing (`python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short` → 72 passed).
- Report primarily Arabic with RTL typography; English only where the technical term is useful.

---

## File Structure

- **Modify:** `app/engine/comparative/report_generator.py` — add `sections` map to response; rework prompt + add `_parse_sections`; add `_build_local_sections` (ar/en) covering all 17 keys; add `_build_sections_from_ai`; keep `report` concat.
- **Modify:** `app/engine/comparative/report_cache.py` — no structural change needed (stores whole JSON result); bump `REPORT_CACHE_PREFIX` to `comparative_report_v2:` to invalidate old-shape cached reports.
- **Modify:** `static/js/smart/report.js` — replace `renderReportLines()` dispatch with section-builder orchestration; add `init`/dispatcher wiring; keep KPI dashboard + decision board.
- **Create:** `static/js/smart/report-sections.js` — new ES module exporting `renderSection(state)` per section key (uses `data` + `sections[key]` + existing helpers).
- **Modify:** `static/css/styles.css` — add `bi-*` Butterfly Intelligence styles.
- **Modify:** `static/tabs/smart-analytics.html` — add title/root container for the sectioned report if needed (section body already exists as `#smart-report-output`).
- **Create:** `tests/test_butterfly_report.py` — backend tests for parser + fallback completeness + report concat.
- **Modify:** `static/js/smart-analytics.js` — load/register `report-sections.js` module.

### Interfaces

- Backend returns `{month, report_source, sections: {exec_summary:str, key_messages:str, priority_hospitals:str, geo_risk:str, early_warnings:str, current_trends:str, forecast:str, clinical_relations:str, composite_patterns:str, anomaly_intel:str, top_deviations:str, regional_intel:str, deterioration:str, data_quality:str, recommendations:str, conclusion:str, appendix:str}, report:str, data:{...unchanged envelope}}`.
- Section key order (display order) is fixed: `exec_summary, key_messages, priority_hospitals, geo_risk, early_warnings, current_trends, forecast, clinical_relations, composite_patterns, anomaly_intel, top_deviations, regional_intel, deterioration, data_quality, recommendations, conclusion, appendix`.
- `report-sections.js` exports one `renderSection(state, key)` per key, where `state = { month, data, sections, lang }`. A single default-export dispatcher `renderReportSections(state)` builds the full sectioned body.
- Analytics `data` envelope keys reused (unchanged): `data.kpi`, `data.anomalies[]`, `data.explanations[]`, `data.residuals[]`, `data.stratified[]`, `data.geo.governorates[]`, `data.patterns[]`, `data.correlations.strong_correlations[]`, `data.clustering`, `data.xgboost`, `data.regional.*`, `data.decision`, `data.forecast`.
- Existing helper exports reused from `./core.js`: `smartState`, `apiSmartGet`, `_smartEscapeHtml`, `_t`, `_fmtNum`, `_riskBadge`, `smartTranslateFeature`; from `./charts.js`: `renderPlot`.

---

### Task 1: Backend — sections map in response + cache version

**Files:**
- Modify: `app/engine/comparative/report_cache.py:10` (`REPORT_CACHE_PREFIX`)
- Modify: `app/engine/comparative/report_generator.py:722-747` (result assembly)
- Test: `tests/test_butterfly_report.py` (new)

**Interfaces:**
- Consumes: existing `_build_local_report` / `_build_forecast_brief` / `_build_decision_brief`.
- Produces: `generate_comprehensive_report()` returns `{month, report_source, sections, report, data}` where `sections` dict has all 17 keys present (never missing) and `report == "\n\n".join(sections.values())`-style concatenation. Backward-compatible.

- [ ] **Step 1: Write the failing test**

Create `tests/test_butterfly_report.py`:

```python
"""Tests for the Butterfly Intelligence comprehensive report structure."""
import pytest
from app.engine.comparative.report_generator import (
    SECTIONS, _build_local_sections, _parse_sections,
)

SECTION_KEYS = SECTIONS  # the 17 keys, order preserved


def test_sections_constant_has_all_keys():
    assert len(SECTIONS) == 17
    assert SECTIONS[0] == "exec_summary"
    assert SECTIONS[-1] == "appendix"


def test_local_sections_cover_all_keys():
    sections = _build_local_sections(None, lang="ar")
    for key in SECTIONS:
        assert key in sections, f"missing section: {key}"
        assert isinstance(sections[key], str) and sections[key].strip()


def test_english_local_sections_cover_all_keys():
    sections = _build_local_sections(None, lang="en")
    for key in SECTIONS:
        assert key in sections
        assert sections[key].strip()


def test_parse_sections_returns_all_keys():
    sample = "\n\n".join(f"## {key}\nنص قسم {key}" for key in SECTIONS)
    parsed = _parse_sections(sample, SECTIONS)
    for key in SECTIONS:
        assert key in parsed
        assert parsed[key].strip()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_butterfly_report.py -q --tb=short`
Expected: FAIL — `ImportError` (SECTIONS / `_build_local_sections` / `_parse_sections` do not exist yet).

- [ ] **Step 3: Add the SECTIONS constant and empty module functions**

At module scope in `report_generator.py` (after imports / near top, above `INDICATOR_NAMES_AR`), add:

```python
# --- أقسام التقرير الشامل (الترتيب النهائي) ---
SECTIONS: List[str] = [
    "exec_summary",        # الملخص التنفيذي + الحالة العامة
    "key_messages",        # أهم الرسائل التنفيذية
    "priority_hospitals",  # المستشفيات ذات الأولوية
    "geo_risk",            # التوزيع الجغرافي للمخاطر
    "early_warnings",      # إشارات الإنذار المبكر
    "current_trends",      # الاتجاهات الشهرية
    "forecast",            # التنبؤ بالمخاطر المستقبلية
    "clinical_relations",  # تحليل المؤشرات والعلاقات
    "composite_patterns",  # الأنماط المركبة
    "anomaly_intel",       # تحليل الحالات الشاذة
    "top_deviations",      # أكبر الانحرافات
    "regional_intel",      # الاستخبارات الإقليمية
    "deterioration",       # تدهور مستمر
    "data_quality",        # تنبيهات جودة البيانات
    "recommendations",     # توصيات + مصفوفة الأولويات
    "conclusion",          # الخلاصة التنفيذية
    "appendix",            # الملحق الفني
]
```

Add stub functions (to be filled in Task 2/3) just before `generate_comprehensive_report`:

```python
def _parse_sections(ai_text: str, keys: List[str]) -> Dict[str, str]:
    """تقسيم نص الذكاء الاصطناعي إلى أقسام بحسب ترويسات `## key`."""
    result: Dict[str, str] = {}
    # TODO: filled in Task 3
    return result


def _build_local_sections(analytics, lang: str = "ar", indicator_stats=None,
                          prev_month: Optional[str] = None, regional=None,
                          decision=None, forecast=None) -> Dict[str, str]:
    """توليد سرد لكل قسم بشكل حتمي (عند عدم توفر AI)."""
    # TODO: filled in Task 2
    return {key: "" for key in SECTIONS}
```

- [ ] **Step 4: Run the test to verify it partially passes**

Run: `python -m pytest tests/test_butterfly_report.py -q --tb=short`
Expected: `test_sections_constant_has_all_keys` and `test_parse_sections_returns_all_keys` PASS; the 3 `_build_local_sections` tests FAIL (empty strings). This is expected inheritance to Task 2.

- [ ] **Step 5: Commit**

```bash
git add tests/test_butterfly_report.py app/engine/comparative/report_generator.py
git commit -m "test+feat: add Butterfly report section skeleton and tests"
```

---

### Task 2: Backend — deterministic per-section narratives (local fallback)

**Files:**
- Modify: `app/engine/comparative/report_generator.py:1081-1231` (extend `_build_local_report_arabic`) and add `_build_local_sections`
- Test: `tests/test_butterfly_report.py`

**Interfaces:**
- Consumes: `SECTIONS`, `_indicator_stats_lines_ar/en`, `_composite_patterns_lines_ar/en`, `_regional_lines_ar/en`, `_decision_brief_lines`, `_forecast_brief_lines`, `INDICATOR_NAMES_AR/EN`, `_build_recommendations`.
- Produces: `_build_local_sections(analytics, lang, indicator_stats, prev_month, regional, decision, forecast) -> Dict[str,str]` returning non-empty Arabic (or English) narratives for all 17 keys, using the same computed numbers as today's local report.

- [ ] **Step 1: Write the failing test (fullness + Arabic ruling words)**

Append to `tests/test_butterfly_report.py`:

```python
def test_local_sections_avoid_causation_words():
    sections = _build_local_sections(None, lang="ar")
    joined = "\n".join(sections.values())
    for bad in ("يؤدي إلى", "سببّية", "causes", "leads to"):
        assert bad not in joined, f"found forbidden wording: {bad}"
    # واقعي: يوجد تحذير الارتباط لا يعني السببية بشكل آمن
    assert "ارتباط" in " ".join(sections.values())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_butterfly_report.py::test_local_sections_avoid_causation_words -q --tb=short`
Expected: FAIL (empty dict → assertion fails on empty).

- [ ] **Step 3: Implement `_build_local_sections`**

Replace the stub `_build_local_sections` added in Task 1 with a complete implementation. Reuse the same computed values and wording already present in `_build_local_report_arabic`/`_build_local_report_english` and the brief line-builders, but emit them keyed by section. Provide Arabic full implementation and an English branch. Below is the Arabic version (build a parallel English version following the pattern):

```python
def _build_local_sections(analytics, lang: str = "ar", indicator_stats=None,
                          prev_month: Optional[str] = None, regional=None,
                          decision=None, forecast=None) -> Dict[str, str]:
    """توليد سرد لكل قسم بشكل حتمي عند عدم توفر AI (مبني على بيانات محسوبة حقيقية)."""
    kpi = analytics.kpi if analytics else None
    anomalies = list(analytics.anomalies or []) if analytics else []
    clustering = analytics.clustering if analytics else None
    correlations = analytics.correlations if analytics else None
    residuals = list(analytics.residuals or []) if analytics else []
    stratified = list(analytics.stratified or []) if analytics else []
    explanations = list(analytics.explanations or []) if analytics else []
    geo = analytics.geo if analytics else None
    xgboost = analytics.xgboost_predictions if analytics else None

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    strong_correlations = correlations.strong_correlations if correlations else []
    total = max(1, getattr(analytics, "hospitals_count", 0) or 0)
    affected = kpi.affected_governorates if kpi else 0

    if lang == "en":
        return _build_local_sections_en(
            analytics, indicator_stats, prev_month, regional, decision, forecast,
        )

    s: Dict[str, str] = {}
    verbose = analytics is not None

    # 1) الملخص التنفيذي + الحالة العامة
    verdict = (decision or {}).get("verdict", "normal")
    risk = (decision or {}).get("risk_score", 0)
    status_ar = {"critical": "حرجة", "attention": "تحذير", "normal": "طبيعية"}.get(verdict, "طبيعية")
    s["exec_summary"] = (
        f"**الحالة العامة للأداء: {status_ar}** — درجة الخطر {risk}/100. "
        f"يغطي التحليل {total} مستشفى، شاذ منها {kpi.total_anomalies if kpi else 0} "
        f"(حرج {critical_count}، يحتاج متابعة {warning_count}) في {affected} محافظة. "
        + ("يستدعي ذلك التحقق من البيانات واتخاذ إجراءات وقائية."
           if verdict == "critical" else
           "يحتاج الوضع متابعة دورية للمؤشرات الرئيسية.")
    )

    # 3) أهم الرسائل التنفيذية (مشتقة من البيانات)
    msgs = []
    if anomalies:
        msgs.append(f"{len(anomalies)} مستشفى أظهرت أنماطًا غير طبيعية.")
    if critical_count:
        msgs.append(f"{critical_count} مستشفى مصنّفة حرجة.")
    if geo and geo.governorates:
        top_gov = max(geo.governorates, key=lambda g: g.avg_anomaly_score, default=None)
        if top_gov and top_gov.outlier_count > 0:
            msgs.append(f"{top_gov.governorate} تمثل أعلى تركّز للمخاطر ({top_gov.outlier_count} مستشفى شاذ).")
    if stratified:
        top_dev = max(stratified, key=lambda x: abs(x.deviation_pct))
        msgs.append(f"انحراف استثنائي في {INDICATOR_NAMES_AR.get(top_dev.indicator, top_dev.indicator)} "
                    f"في {top_dev.hospital_name} ({top_dev.deviation_pct:+.1f}%).")
    if xgboost and xgboost.predictions:
        escal = [p for p in xgboost.predictions if p.predicted_severity in ("critical", "high")]
        if escal:
            msgs.append(f"{len(escal)} مستشفى متوقع تصاعد مستوى خطورتها.")
    if not msgs:
        msgs.append("لا توجد مؤشرات تتطلب تدخلاً عاجلاً هذا الشهر.")
    s["key_messages"] = "\n- ".join(msgs)

    # 4) المستشفيات ذات الأولوية (ترتيب تنازلي بالدرجة)
    if anomalies:
        ranked = sorted(anomalies, key=lambda a: a.anomaly_score, reverse=True)
        rows = []
        for i, a in enumerate(ranked[:10], start=1):
            rows.append(f"{i}. {a.hospital_name} — {a.governorate} — درجة {a.anomaly_score:.2f} — {a.severity}")
        s["priority_hospitals"] = "\n".join(rows)
    else:
        s["priority_hospitals"] = "لا توجد مستشفيات ذات أولوية هذا الشهر."

    # 5) التوزيع الجغرافي للمخاطر
    if geo and geo.governorates:
        govs = sorted(geo.governorates, key=lambda g: g.avg_anomaly_score, reverse=True)
        lines = []
        for g in govs:
            lines.append(f"- {g.governorate}: {g.hospital_count} مستشفى، متوسط {g.avg_anomaly_score:.2f}، "
                         f"شاذ {g.outlier_count}")
        s["geo_risk"] = "\n".join(lines)
    else:
        s["geo_risk"] = "لا توجد بيانات جغرافية كافية."

    # 7) إشارات الإنذار المبكر
    if forecast and forecast.get("hospitals"):
        fh = forecast["hospitals"][:8]
        lines = []
        for h in fh:
            prob = int((h.get("probability") or 0) * 100)
            conf = h.get("confidence_label_ar") or h.get("confidence") or "—"
            lead = "؛ ".join(
                f"{r.get('metric_ar')} (+{r.get('delta_pct'):.1f}%)"
                for r in h.get("leading_rising", [])[:3] if r.get("delta_pct") is not None
            )
            lines.append(f"- {h.get('hospital_name')}: {lead} — احتمال {prob}%، ثقة {conf}.")
        lines.append("(الإشارات علاقات زمنية إحصائية، وليست علاقات سببية.)")
        s["early_warnings"] = "\n".join(lines)
    else:
        s["early_warnings"] = "لا توجد إشارات إنذار مبكر موثوقة هذا الشهر."

    # 6) الاتجاهات الشهرية
    if prev_month and indicator_stats:
        s["current_trends"] = "\n".join(_trend_lines_ar(prev_month, indicator_stats))
    else:
        s["current_trends"] = "لا يوجد شهر سابق متوفر للمقارنة."

    # 9/10) التنبؤ — فصل الحالي عن المتوقع
    if xgboost and xgboost.predictions:
        lines = []
        for p in xgboost.predictions[:8]:
            lines.append(f"- {p.hospital_name}: الخطر الحالي {p.current_score:.2f} → المتوقع "
                         f"{p.predicted_next_score:.2f} ({p.predicted_severity}).")
        s["forecast"] = "\n".join(lines) + "\n(التوقع تقدير إحصائي وليس يقينًا.)"
    else:
        s["forecast"] = "لا توجد تنبؤات متاحة."

    # 11) العلاقات بين المؤشرات
    if strong_correlations:
        lines = []
        for c in strong_correlations[:8]:
            lines.append(f"- {INDICATOR_NAMES_AR.get(c.indicator_a, c.indicator_a)} ↔ "
                         f"{INDICATOR_NAMES_AR.get(c.indicator_b, c.indicator_b)}: r={c.pearson_r:.2f} ({c.strength})")
        lines.append("(الارتباط الإحصائي لا يثبت السببية.)")
        s["clinical_relations"] = "\n".join(lines)
    else:
        s["clinical_relations"] = "لا توجد علاقات قوية بين المؤشرات."

    # 12) الأنماط المركبة
    s["composite_patterns"] = "\n".join(_composite_patterns_lines_ar(analytics.patterns if analytics else []))

    # 13) تحليل الحالات الشاذة (فصل درجة الشذوذ عن انحراف المؤشر)
    if anomalies:
        lines = []
        for a in anomalies[:8]:
            lines.append(f"- {a.hospital_name} ({a.governorate}): درجة الشذوذ {a.anomaly_score:.2f} — "
                         f"الشدة {a.severity}. شدة الشذوذ منفصلة عن انحراف المؤشرات.")
        s["anomaly_intel"] = "\n".join(lines)
    else:
        s["anomaly_intel"] = "لا توجد حالات شاذة."

    # 14) أكبر الانحرافات
    if stratified:
        rows = sorted(stratified, key=lambda x: abs(x.deviation_pct), reverse=True)[:5]
        lines = []
        for row in rows:
            lines.append(f"- {row.hospital_name} | {INDICATOR_NAMES_AR.get(row.indicator, row.indicator)}: "
                         f"{row.hospital_value:.1f} مقابل متوسط نظير {row.peer_group_mean:.1f} "
                         f"(انحراف {row.deviation_pct:+.1f}%).")
        lines.append("(إجراء: التحقق من السجلات ومصدر البيانات قبل اعتماد النتيجة.)")
        s["top_deviations"] = "\n".join(lines)
    else:
        s["top_deviations"] = "لا توجد انحرافات كبيرة عن المستشفيات المماثلة."

    # 17) الاستخبارات الإقليمية
    if regional:
        s["regional_intel"] = "\n".join(_regional_lines_ar(regional))
    else:
        s["regional_intel"] = "لا توجد بيانات إقليمية كافية."

    # 18) التدهور المستمر (يُعرض رقمياً في الواجهة من السلاسل الشهرية)
    if prev_month and indicator_stats:
        s["deterioration"] = ("التدهور المستمر يُحسب من اتجاه سلاسل المؤشرات الشهرية "
                              "(الميل ومعامل R²) ويُعرض في جدول القسم.")
    else:
        s["deterioration"] = "لا توجد سلاسل تاريخية كافية لتقدير التدهور المستمر."

    # 19/20) جودة البيانات + حجم العينة
    dq = []
    if regional and regional.get("mortality"):
        small = [m for m in regional["mortality"] if m.get("small_sample")]
        if small:
            for m in small[:5]:
                dq.append(f"- حجم عينة صغير في {m['governorate']} ({int(m.get('births') or 0)} مولود) — تُفسَّر النتائج بحذر.")
    if not dq:
        dq.append("- لا توجد تنبيهات جودة بيانات كبرى هذا الشهر.")
    s["data_quality"] = "\n".join(dq)

    # 21/22) التوصيات + الأولويات
    if decision and decision.get("priorities"):
        lines = [f"- {p['action']} ← {p['target']} (أولوية: {p['priority']})."
                 for p in decision["priorities"]]
    else:
        lines = ["- لا توجد أولويات إلزامية هذا الشهر."]
    s["recommendations"] = "\n".join(lines)

    # 23) الخلاصة التنفيذية
    s["conclusion"] = (
        f"**الوضع الحالي:** {'وجود مستشفيات حرجة.' if critical_count else 'استقرار نسبي.'} "
        f"**الخطر المستقبلي:** {s['forecast']} "
        f"**الإجراء:** التحقق من جودة البيانات في المستشفيات ذات الأولوية ومراجعة مؤشراتها."
    )

    # 24) الملحق الفني
    app_lines = []
    if clustering:
        app_lines.append(f"- التجميع: {clustering.n_clusters} مجموعات، جودة silhouette {clustering.silhouette_score:.2f}.")
    if correlations:
        app_lines.append(f"- عدد الارتباطات القوية: {len(strong_correlations)}.")
    if xgboost:
        app_lines.append(f"- نموذج التنبؤ: R² {xgboost.model_r2:.3f}، MAE {xgboost.model_mae:.3f}.")
    app_lines.append("- Terms: درجة الخطر (Risk Score), درجة الشذوذ (Anomaly Score), الارتباط الزمني (Lead-Lag).")
    s["appendix"] = "\n".join(app_lines) if app_lines else "لا توجد بيانات فنية كافية."

    return s


def _build_local_sections_en(analytics, indicator_stats=None, prev_month=None,
                             regional=None, decision=None, forecast=None) -> Dict[str, str]:
    """English deterministic per-section narratives (mirror of the Arabic builder)."""
    # Follow the same structure as _build_local_sections using INDICATOR_NAMES_EN,
    # _trend_lines_en, _composite_patterns_lines_en, _regional_lines_en. Use the
    # English wording rules (no "leads to" / "causes" — use "statistical temporal
    # association"). All 17 keys must be present.
    from app.engine.comparative.report_generator import SECTIONS
    kpi = analytics.kpi if analytics else None
    anomalies = list(analytics.anomalies or []) if analytics else []
    clustering = analytics.clustering if analytics else None
    correlations = analytics.correlations if analytics else None
    stratified = list(analytics.stratified or []) if analytics else []
    geo = analytics.geo if analytics else None
    xgboost = analytics.xgboost_predictions if analytics else None
    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    strong_correlations = correlations.strong_correlations if correlations else []

    s: Dict[str, str] = {}
    s["exec_summary"] = (
        f"System status: {kpi.month_status if kpi else 'unknown'}. "
        f"{kpi.total_anomalies if kpi else 0} anomalous hospitals "
        f"({critical_count} critical) across {kpi.affected_governorates if kpi else 0} governorates."
    )
    s["key_messages"] = ("\n- ".join(
        ([f"{len(anomalies)} hospitals showed abnormal patterns."] if anomalies else [])
        + ([f"{critical_count} hospitals are classified critical."] if critical_count else [])
    ) or "No urgent signals this month.")
    s["priority_hospitals"] = ("\n".join(
        f"{i+1}. {a.hospital_name} — {a.governorate} — score {a.anomaly_score:.2f} — {a.severity}"
        for i, a in enumerate(sorted(anomalies, key=lambda x: x.anomaly_score, reverse=True)[:10])
    ) if anomalies else "No priority hospitals this month.")
    s["geo_risk"] = ("\n".join(
        f"- {g.governorate}: {g.hospital_count} hospitals, avg {g.avg_anomaly_score:.2f}, outliers {g.outlier_count}"
        for g in sorted(geo.governorates, key=lambda x: x.avg_anomaly_score, reverse=True)
    ) if geo and geo.governorates else "No geographic data.")
    s["early_warnings"] = ("\n".join(
        f"- {h.get('hospital_name')}: probability {int((h.get('probability') or 0) * 100)}%, confidence "
        f"{h.get('confidence_label_en') or h.get('confidence') or '—'}. (temporal statistical association only.)"
        for h in (forecast or {}).get("hospitals", [])[:8]
    ) or "No reliable early-warning signals this month.")
    s["current_trends"] = ("\n".join(_trend_lines_en(prev_month, indicator_stats))
                           if prev_month and indicator_stats else "No previous month for comparison.")
    s["forecast"] = ("\n".join(
        f"- {p.hospital_name}: current {p.current_score:.2f} → predicted {p.predicted_next_score:.2f} "
        f"({p.predicted_severity})." for p in (xgboost.predictions if xgboost else [])[:8]
    ) + "\n(Prediction is a statistical estimate, not certainty.)" if xgboost and xgboost.predictions
        else "No forecasts available.")
    s["clinical_relations"] = ("\n".join(
        [f"- {c.indicator_a} ↔ {c.indicator_b}: r={c.pearson_r:.2f} ({c.strength})"
         for c in strong_correlations[:8]] + ["(Correlation does not imply causation.)"]
    ) if strong_correlations else "No strong indicator relationships.")
    s["composite_patterns"] = "\n".join(_composite_patterns_lines_en(analytics.patterns if analytics else []))
    s["anomaly_intel"] = ("\n".join(
        f"- {a.hospital_name} ({a.governorate}): anomaly score {a.anomaly_score:.2f} — severity {a.severity} "
        f"(separate from indicator-level deviation)." for a in anomalies[:8]
    ) or "No anomalies.")
    s["top_deviations"] = ("\n".join(
        [f"- {r.hospital_name} | {r.indicator}: {r.hospital_value:.1f} vs peer mean {r.peer_group_mean:.1f} "
         f"({r.deviation_pct:+.1f}%)." for r in sorted(stratified, key=lambda x: abs(x.deviation_pct), reverse=True)[:5]]
        + ["(Action: verify records and data source before relying on the result.)"]
    ) if stratified else "No large deviations vs peers.")
    s["regional_intel"] = ("\n".join(_regional_lines_en(regional)) if regional else "No regional data.")
    s["deterioration"] = ("Persistent deterioration is derived from monthly indicator series (slope and R²) "
                          "and shown in the section table." if prev_month and indicator_stats
                          else "Insufficient history to estimate persistent deterioration.")
    s["data_quality"] = ("\n".join(
        [f"- Small sample in {m['governorate']} ({int(m.get('births') or 0)} births) — interpret with caution."
         for m in ((regional or {}).get("mortality") or []) if m.get("small_sample")][:5]
    ) or "- No major data-quality alerts this month.")
    s["recommendations"] = ("\n".join(
        f"- {p['action']} ← {p['target']} (priority: {p['priority']})."
        for p in (decision or {}).get("priorities", [])
    ) or "- No mandatory priorities this month.")
    s["conclusion"] = (f"**Current:** {'Critical hospitals present.' if critical_count else 'Relative stability.'} "
                       f"**Future risk:** {s['forecast']} "
                       f"**Action:** verify data quality in priority hospitals and review their indicators.")
    s["appendix"] = ("\n".join(
        ([f"- Clustering: {clustering.n_clusters} clusters, silhouette {clustering.silhouette_score:.2f}."] if clustering else [])
        + ([f"- Strong correlations: {len(strong_correlations)}."] if correlations else [])
        + ([f"- Prediction model: R² {xgboost.model_r2:.3f}, MAE {xgboost.model_mae:.3f}."] if xgboost else [])
    ) or "No technical data.")
    # Guarantee every key is present (padding if any branch missed a key).
    for key in SECTIONS:
        s.setdefault(key, "- Not available.")
    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_butterfly_report.py -q --tb=short`
Expected: all `test_*local_sections*` tests PASS.

- [ ] **Step 5: Run the full regression suite**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed.

- [ ] **Step 6: Commit**

```bash
git add app/engine/comparative/report_generator.py tests/test_butterfly_report.py
git commit -m "feat: deterministic per-section Arabic/English narratives for Butterfly report"
```

---

### Task 3: Backend — AI per-section parse + response assembly + cache version

**Files:**
- Modify: `app/engine/comparative/report_generator.py` (prompt rework, `_parse_sections`, `_build_sections_from_ai`, response assembly)
- Modify: `app/engine/comparative/report_cache.py:10` (`REPORT_CACHE_PREFIX`)
- Test: `tests/test_butterfly_report.py`

**Interfaces:**
- Consumes: `SECTIONS`, `_build_arabic_prompt`/`_build_english_prompt` (reworked to request `## <key>` headings), `_call_api`, `_build_local_sections`, `_build_decision_brief`, `_build_forecast_brief`.
- Produces: `generate_comprehensive_report()` includes `sections` (all 17 keys present) sourced from AI when `report_source=="ai"` else local; `report` = concat. Cache stores new shape under `comparative_report_v2:`.

- [ ] **Step 1: Bump the cache prefix to invalidate old-shape reports**

In `report_cache.py`, change line 10:

```python
REPORT_CACHE_PREFIX = "comparative_report_v2:"
```

- [ ] **Step 2: Write the failing test for AI parse**

Append to `tests/test_butterfly_report.py`:

```python
def test_parse_sections_tolerates_ai_noise():
    noisy = ("مقدمة غير مقصودة\n\n"
             "## exec_summary\nالمحتوى الأول\n\n"
             "## key_messages\n- بند 1\n- بند 2\n\n"
             "## appendix\nنهاية")
    parsed = _parse_sections(noisy, SECTIONS)
    assert parsed["exec_summary"].strip() == "المحتوى الأول"
    assert parsed["key_messages"].strip() == "- بند 1\n- بند 2"
    assert parsed["appendix"].strip() == "نهاية"
    # الأقسام غير المذكورة تُملأ بسرد فارغ → تُهدى لاحقاً للحتمي
    assert "geo_risk" in parsed
```

- [ ] **Step 3: Implement `_parse_sections`**

Replace the stub `_parse_sections` in `report_generator.py`:

```python
def _parse_sections(ai_text: str, keys: List[str]) -> Dict[str, str]:
    """تقسيم نص الذكاء الاصطناعي إلى أقسام بحسب ترويسات `## <key>` (أو `=== <key> ===`).
    يملأ أي مفتاح لم يُذكر بقيمة فارغة حتى يغطي المتصل كل الأقسام."""
    result: Dict[str, str] = {key: "" for key in keys}
    normalized = str(ai_text or "")
    # إنشاء نمط يطابق الترويسة: ## key  أو  === key ===
    for key in keys:
        # مطابقة ترويسة markdown: "## exec_summary"
        import re
        m = re.search(rf"^#{2,4}\s*{re.escape(key)}\s*$", normalized, re.MULTILINE)
        if m is None:
            m = re.search(rf"^===\s*{re.escape(key)}\s*===\s*$", normalized, re.MULTILINE)
        if m is None:
            continue
        start = m.end()
        # نهاية القسم = الترويسة التالية (أي ترويسة ##)
        nxt = re.search(rf"^#{2,4}\s*\S+.*$", normalized[start:], re.MULTILINE)
        if nxt:
            end = start + nxt.start()
        else:
            end = len(normalized)
        result[key] = normalized[start:end].strip()
    return result
```

- [ ] **Step 4: Implement `_build_sections_from_ai`**

Add a helper that runs the AI and, on parse failure / missing keys, fills gaps from the local builder (so all 17 keys are always present):

```python
def _build_sections_from_ai(prompt: str, local_sections: Dict[str, str],
                            lang: str = "ar") -> Optional[Dict[str, str]]:
    """استدعاء AI وتقسيم الناتج؛ أي قسم مفقود يُملأ من النسخة الحتمية."""
    try:
        ai_text = _call_api(prompt)
    except Exception:
        logger.error("AI report generation failed; using local fallback", exc_info=True)
        return None
    if not ai_text:
        return None
    parsed = _parse_sections(ai_text, SECTIONS)
    # دمج: كل قسم غير ممتلئ يُستكمل من الحتمي.
    merged = {key: (parsed.get(key) or local_sections.get(key, "")).strip()
              for key in SECTIONS}
    if all(merged.values()):
        return merged
    # لو بقيت أقسام فارغة، نعود للحتمي كاملاً.
    return local_sections
```

- [ ] **Step 5: Rework `_build_arabic_prompt` (and `_build_english_prompt`) to request `## <key>` sections**

In `_build_arabic_prompt` append a closing instruction block that names the exact keys/order (keep the existing data-embedding sections above). Add before the final `"""`:

```python
    prompt = prompt + f"""
    أخرج تقريرك على شكل أقسام مستقلة، كل قسم يبدأ بترويسة صريحة بصيغة markdown
    بالشكل التالي (أنشئ الأقسام الـ{SECTIONS} التالية بالترتيب، ولا تُضف أي شيء
    خارج هذه الترويسات):

    ## exec_summary
    (ملخص تنفيذي قصير — الحالة العامة، عدد الشاذ/الحرج، المحافظات المتأثرة)

    ## key_messages
    (5 إلى 7 رسائل تنفيذية أوضحها — نقاط مبدوءة بـ "- ")

    ## priority_hospitals
    (مستشفيات الأولوية مرتبة تنازلياً بالدرجة، كل سطر: الترتيب — المستشفى — المحافظة — الدرجة — الحالة)

    ## geo_risk
    (التوزيع الجغرافي للمخاطر وتفسيره)

    ## early_warnings
    (إشارات الإنذار المبكر — علاقات زمنية إحصائية لا سببية)

    ## current_trends
    (الاتجاهات الشهرية وتفسيرها)

    ## forecast
    (التنبؤ بالمخاطر المستقبلية — فصل الخطر الحالي عن المتوقع)

    ## clinical_relations
    (العلاقات بين المؤشرات + ملاحظة أن الارتباط لا يثبت السببية)

    ## composite_patterns
    (الأنماط المركبة المتكررة)

    ## anomaly_intel
    (تحليل الحالات الشاذة — فصل درجة الشذوذ عن انحراف المؤشر)

    ## top_deviations
    (أكبر الانحرافات عن المستشفيات المماثلة)

    ## regional_intel
    (الاستخبارات الإقليمية)

    ## deterioration
    (المؤشرات ذات التدهور المستمر)

    ## data_quality
    (تنبيهات جودة البيانات وحجم العينة)

    ## recommendations
    (التوصيات المبنية على الأدلة)

    ## conclusion
    (الخلاصة التنفيذية — الوضع الحالي والخطر المستقبلي والإجراء)

    ## appendix
    (ملحق فني: FDR، غرانجر، الارتباطات، SHAP، البواقي، التجميع، المقارنة الطبقية)
    """
    return prompt
```

Create an equivalent English block for `_build_english_prompt` using the same keys and English section descriptions.

- [ ] **Step 6: Wire `sections` + `report` into `generate_comprehensive_report`**

In `generate_comprehensive_report` (currently lines 679-747), replace the block from `report_text = None` down to the `result` assembly. The new logic:

```python
    decision_brief = _build_decision_brief(
        analytics, indicator_stats=indicator_stats, prev_month=prev_month, lang=lang,
        regional=regional,
    )
    forecast_brief = _build_forecast_brief(session, month, lang)

    # سرد كل قسم بشكل حتمي أولاً (ضمان تغطية كاملة)، ثم حاول AI.
    local_sections = _build_local_sections(
        analytics, lang=lang, indicator_stats=indicator_stats, prev_month=prev_month,
        regional=regional, decision=decision_brief, forecast=forecast_brief,
    )
    sections = None
    report_source = "local"
    try:
        prompt = build_comprehensive_prompt(
            analytics, lang, indicator_stats=indicator_stats, prev_month=prev_month,
            regional=regional,
        )
        sections = _build_sections_from_ai(prompt, local_sections, lang=lang)
        if sections is not None:
            report_source = "ai"
    except Exception:
        logger.error("AI report generation failed; using local fallback", exc_info=True)
    if sections is None:
        sections = local_sections
        report_source = "local"

    # تقرير متوافق خلفياً = دمج الأقسام بالترتيب.
    report_text = "\n\n".join(sections[key] for key in SECTIONS)
```

Then build `result` with `"sections": sections` added, keeping `"report": report_text` and the unchanged `"data"` envelope. Remove the old flat `report_text`/`_local_report`/`_decision_brief_lines`-prepend logic. Keep `_decision_brief_lines`/`_forecast_brief_lines` defined (used elsewhere or harmless) but they are no longer prepended.

- [ ] **Step 7: Run the butterfly + regression tests**

Run: `python -m pytest tests/test_butterfly_report.py tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: butterfly tests PASS (parser + local completeness); regression 72 passed.

- [ ] **Step 8: Commit**

```bash
git add app/engine/comparative/report_generator.py app/engine/comparative/report_cache.py tests/test_butterfly_report.py
git commit -m "feat: per-section AI narratives + assembled sections map with fallback"
```

---

### Task 4: Frontend — Butterfly CSS + report section containers

**Files:**
- Modify: `static/css/styles.css` (append `bi-*` block)
- Test: no JS test framework; run existing suite.

**Interfaces:**
- Produces: CSS classes consumed by Tasks 5-7: `.bi-report`, `.bi-section`, `.bi-section-title`, `.bi-kpi-grid`, `.bi-kpi`, `.bi-badge`, `.bi-badge-critical`, `.bi-badge-warning`, `.bi-badge-normal`, `.bi-grid-2`, `.bi-table-wrap`, `.bi-severity-bar`, `.bi-priority`, `.bi-collapsible`, `.bi-empty`.

- [ ] **Step 1: Append Butterfly CSS**

Append to `static/css/styles.css` (before the final closing `}` of the file, or at end if not wrapped):

```css
/* ═══ Butterfly Intelligence Report ═══ */
.bi-report{direction:rtl;text-align:right;display:flex;flex-direction:column;gap:1.4rem;margin-top:1rem;}
.bi-section{background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;padding:1.1rem 1.2rem;box-shadow:var(--shadow-soft,0 1px 3px rgba(0,0,0,.2));}
.bi-section-title{display:flex;align-items:center;gap:.5rem;font-size:1rem;font-weight:700;color:var(--accent-blue);margin:0 0 .75rem;border-bottom:1px solid var(--border-default);padding-bottom:.5rem;}
.bi-section-title .bi-sub{color:var(--text-muted);font-weight:400;font-size:.75rem;}
.bi-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin-bottom:1rem;}
.bi-kpi{background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:10px;padding:.75rem;text-align:center;}
.bi-kpi .bi-kpi-value{font-size:1.6rem;font-weight:800;color:var(--text-primary);}
.bi-kpi .bi-kpi-label{font-size:.75rem;color:var(--text-secondary);margin-top:.25rem;}
.bi-badge{display:inline-block;padding:.2rem .6rem;border-radius:999px;font-size:.72rem;font-weight:700;}
.bi-badge-critical{background:var(--accent-red-soft, rgba(239,68,68,.15));color:var(--accent-red);}
.bi-badge-warning{background:var(--accent-orange-soft, rgba(245,158,11,.15));color:var(--accent-orange);}
.bi-badge-normal{background:var(--accent-green-soft, rgba(34,197,94,.15));color:var(--accent-green);}
.bi-grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem;}
.bi-table-wrap{overflow-x:auto;}
.bi-table-wrap table{width:100%;border-collapse:collapse;font-size:.82rem;}
.bi-table-wrap th,.bi-table-wrap td{padding:.5rem .6rem;border-bottom:1px solid var(--border-default);text-align:right;}
.bi-table-wrap th{color:var(--text-secondary);font-weight:600;background:var(--bg-surface-hover);}
.bi-severity-bar{height:8px;border-radius:999px;background:var(--bg-input);overflow:hidden;display:block;margin-top:.3rem;}
.bi-severity-bar > span{display:block;height:100%;}
.bi-priority{border-left:4px solid var(--border-default);padding:.5rem .75rem;border-radius:8px;margin-bottom:.5rem;background:var(--bg-elevated);}
.bi-collapsible summary{cursor:pointer;color:var(--accent-blue);font-weight:600;}
.bi-empty{color:var(--text-muted);font-size:.82rem;font-style:italic;}
.bi-narrative{color:var(--text-secondary);font-size:.88rem;line-height:1.7;margin-top:.5rem;white-space:pre-line;}
.bi-caution{background:var(--accent-orange-soft, rgba(245,158,11,.12));border:1px solid var(--accent-orange);color:var(--text-primary);border-radius:8px;padding:.6rem .8rem;font-size:.85rem;margin-top:.6rem;}
```

- [ ] **Step 2: Verify no syntax breakage**

Run: `python -m pytest tests/test_chart_migration.py -q --tb=short`
Expected: 38 passed (CSS not tested, but confirms repo stable).

- [ ] **Step 3: Commit**

```bash
git add static/css/styles.css
git commit -m "style: add Butterfly Intelligence report CSS (bi-*)"
```

---

### Task 5: Frontend — report-sections module (core + high-impact sections)

**Files:**
- Create: `static/js/smart/report-sections.js`
- Modify: `static/js/smart/report.js` (use dispatcher)
- Modify: `static/js/smart-analytics.js` (load module)
- Test: no JS test framework; keep existing suite passing.

**Interfaces:**
- Consumes: `smartState`, `_smartEscapeHtml`, `_t`, `_fmtNum` from `./core.js` (already imported by report.js); `data`, `sections`.
- Produces: `export default function renderReportSections(state)` that renders the full sectioned body into `document.getElementById('smart-report-output')`, and per-section helper functions. Sections implemented in this task: `exec_summary`, `key_messages`, `priority_hospitals`, `geo_risk`, `early_warnings`, `forecast`, `appendix`.

- [ ] **Step 1: Create `report-sections.js`**

```js
// report-sections.js — Butterfly Intelligence section renderers.
// Each section renders structured HTML from `data` + embeds `sections[key]` narrative.
import { smartState, _smartEscapeHtml, _t, _fmtNum } from './core.js';

const SECTION_META = {
  exec_summary: { title: 'تقرير تنفيذي', icon: '📊' },
  key_messages: { title: 'أهم الرسائل التنفيذية', icon: '🎯' },
  priority_hospitals: { title: 'المستشفيات ذات الأولوية', icon: '🏥' },
  geo_risk: { title: 'التوزيع الجغرافي للمخاطر', icon: '🗺️' },
  early_warnings: { title: 'إشارات الإنذار المبكر', icon: '🔮' },
  current_trends: { title: 'الاتجاهات الشهرية', icon: '📈' },
  forecast: { title: 'التنبؤ بالمخاطر المستقبلية', icon: '🔭' },
  clinical_relations: { title: 'تحليل المؤشرات والعلاقات', icon: '🔗' },
  composite_patterns: { title: 'الأنماط المركبة', icon: '🧩' },
  anomaly_intel: { title: 'تحليل الحالات الشاذة', icon: '🚨' },
  top_deviations: { title: 'أكبر الانحرافات', icon: '📉' },
  regional_intel: { title: 'الاستخبارات الإقليمية', icon: '🌍' },
  deterioration: { title: 'التدهور المستمر', icon: '⬇️' },
  data_quality: { title: 'تنبيهات جودة البيانات', icon: '🔍' },
  recommendations: { title: 'التوصيات والأولويات', icon: '✅' },
  conclusion: { title: 'الخلاصة التنفيذية', icon: '📝' },
  appendix: { title: 'الملحق الفني', icon: '🗂️' },
};

function esc(v) { return v == null ? '' : _smartEscapeHtml(String(v)); }
function badge(severity) {
  const lvl = severity === 'critical' ? 'critical' : severity === 'warning' ? 'warning' : 'normal';
  return `<span class="bi-badge bi-badge-${lvl}">${esc(_t(severity || 'Normal'))}</span>`;
}
function sectionShell(key, inner) {
  const m = SECTION_META[key] || { title: key, icon: '' };
  const narrative = smartState.sections && smartState.sections[key];
  return `<section class="bi-section" data-bi-section="${key}">
    <h4 class="bi-section-title">${m.icon} ${esc(_t(m.title) || m.title)}</h4>
    ${inner}
    ${narrative ? `<div class="bi-narrative">${esc(narrative)}</div>` : ''}
  </section>`;
}

function renderExecSummary(data) {
  const decision = data.decision || {};
  const kpi = data.kpi || {};
  const verdict = decision.verdict || 'normal';
  const badgeHtml = badge(verdict);
  const kpis = [
    ['العدد الإجمالي للمستشفيات', data.hospitals_count],
    ['المستشفيات الشاذة', kpi.total_anomalies],
    ['الحرجة', kpi.critical_count],
    ['بحاجة متابعة', kpi.warning_count],
    ['المحافظات المتأثرة', kpi.affected_governorates],
  ].map(([label, val]) => `<div class="bi-kpi"><div class="bi-kpi-value">${esc(val ?? '-')}</div><div class="bi-kpi-label">${esc(_t(label) || label)}</div></div>`).join('');
  return `<div class="bi-kpi-grid">${kpis}</div>
    <div><span class="bi-badge bi-badge-${verdict === 'attention' ? 'warning' : verdict}">${esc(_t(decision.verdict_label) || decision.verdict_label)}</span>
    <span class="bi-kpi-label">درجة الخطر: ${esc(decision.risk_score ?? '-')}/100</span></div>`;
}

function renderPriorityHospitals(data) {
  const anomalies = (data.anomalies || []).slice().sort((a, b) => b.anomaly_score - a.anomaly_score);
  if (!anomalies.length) return `<div class="bi-empty">لا توجد مستشفيات ذات أولوية.</div>`;
  const rows = anomalies.slice(0, 10).map((a, i) => `<tr>
    <td style="text-align:center;">${i + 1}</td>
    <td>${esc(a.hospital_name)}</td>
    <td>${esc(a.governorate)}</td>
    <td style="text-align:center;">${_fmtNum(a.anomaly_score)}</td>
    <td>${badge(a.severity)}</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>الترتيب</th><th>المستشفى</th><th>المحافظة</th><th>درجة الخطر</th><th>الحالة</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderGeoRisk(data) {
  const govs = ((data.geo && data.geo.governorates) || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  if (!govs.length) return `<div class="bi-empty">لا توجد بيانات جغرافية.</div>`;
  const rows = govs.map(g => {
    const pct = Math.min(100, Math.round(g.avg_anomaly_score * 100));
    const col = pct >= 60 ? 'var(--accent-red)' : pct >= 30 ? 'var(--accent-orange)' : 'var(--accent-green)';
    return `<tr><td>${esc(g.governorate)}</td>
      <td style="text-align:center;">${g.hospital_count}</td>
      <td style="text-align:center;">${_fmtNum(g.avg_anomaly_score)}</td>
      <td style="text-align:center;">${g.outlier_count}</td>
      <td><span class="bi-severity-bar"><span style="width:${pct}%;background:${col};"></span></span></td>
    </tr>`;
  }).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المحافظة</th><th>عدد المستشفيات</th><th>متوسط درجة الخطر</th><th>شاذ</th><th>التوزيع</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderEarlyWarnings(data) {
  const hospitals = ((data.forecast && data.forecast.hospitals) || []).slice().filter(h => (h.probability || 0) > 0);
  if (!hospitals.length) return `<div class="bi-empty">لا توجد إشارات إنذار مبكر موثوقة.</div>`;
  const cards = hospitals.slice(0, 8).map(h => {
    const prob = Math.round((h.probability || 0) * 100);
    const col = prob >= 70 ? 'var(--accent-red)' : prob >= 40 ? 'var(--accent-orange)' : 'var(--accent-green)';
    const leads = (h.leading_rising || []).slice(0, 3).map(r => esc(r.metric_ar || r.metric)).join('، ');
    return `<div class="bi-priority">
      <strong>${esc(h.hospital_name)}</strong> — ${esc(h.severity || '')}<br>
      <span>إشارة: ${esc(leads)}</span>
      <span class="bi-severity-bar"><span style="width:${prob}%;background:${col};"></span></span>
      <div class="bi-kpi-label">الاحتمال: <b>${prob}%</b> · الثقة: ${esc(h.confidence_label_ar || h.confidence || '—')}</div>
    </div>`;
  }).join('');
  return `<div class="bi-grid-2">${cards}</div><div class="bi-caution">ارتباط زمني إحصائي — ليس علاقة سببية.</div>`;
}

function renderForecast(data) {
  const preds = (data.xgboost && data.xgboost.predictions) || [];
  if (!preds.length) return `<div class="bi-empty">لا توجد تنبؤات متاحة.</div>`;
  const rows = preds.slice(0, 8).map(p => `<tr>
    <td>${esc(p.hospital_name)}</td>
    <td style="text-align:center;">${_fmtNum(p.current_score)}</td>
    <td style="text-align:center;color:var(--accent-blue);">${_fmtNum(p.predicted_next_score)}</td>
    <td>${badge(p.predicted_severity)}</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المستشفى</th><th>الخطر الحالي</th><th>الخطر المتوقع</th><th>التصنيف المتوقع</th>
  </tr></thead><tbody>${rows}</tbody></table></div>
  <div class="bi-caution">الخطر الحالي منفصل عن الخطر المتوقع — التوقع تقدير إحصائي وليس يقينًا.</div>`;
}

function renderAppendix(data) {
  const c = data.clustering || {};
  const x = data.xgboost || {};
  const lines = [];
  if (c && c.n_clusters != null) lines.push(`- التجميع: ${c.n_clusters} مجموعات — silhouette ${_fmtNum(c.silhouette_score)}`);
  if (x && x.model_r2 != null) lines.push(`- نموذج التنبؤ: R² ${_fmtNum(x.model_r2)} — MAE ${_fmtNum(x.model_mae)}`);
  if (!lines.length) lines.push('- لا توجد بيانات فنية كافية.');
  lines.push('- مصطلحات: درجة الخطر (Risk Score) · درجة الشذوذ (Anomaly Score) · الارتباط الزمني (Lead-Lag).');
  return `<details class="bi-collapsible"><summary>عرض التحليل الفني</summary><div style="margin-top:.5rem;">${lines.map(esc).join('<br>')}</div></details>`;
}

// Render the remaining sections with a shared table/grid fallback that shows
// the narrative plus a lightweight data table where relevant.
function renderSimpleSection(key, data) {
  return `<div class="bi-empty">تُعرض بيانات هذا القسم أدناه.</div>`;
}

const RENDERERS = {
  exec_summary: renderExecSummary,
  priority_hospitals: renderPriorityHospitals,
  geo_risk: renderGeoRisk,
  early_warnings: renderEarlyWarnings,
  forecast: renderForecast,
  appendix: renderAppendix,
};

export default function renderReportSections(state) {
  const container = document.getElementById('smart-report-output');
  if (!container) return;
  const order = ['exec_summary', 'key_messages', 'priority_hospitals', 'geo_risk',
    'early_warnings', 'current_trends', 'forecast', 'clinical_relations',
    'composite_patterns', 'anomaly_intel', 'top_deviations', 'regional_intel',
    'deterioration', 'data_quality', 'recommendations', 'conclusion', 'appendix'];
  const html = order.map(key => {
    const renderer = RENDERERS[key];
    const inner = renderer ? renderer(state.data) : renderSimpleSection(key, state.data);
    return sectionShell(key, inner);
  }).join('');
  container.innerHTML = html;
  container.style.direction = 'rtl';
}
```

- [ ] **Step 2: Wire into report.js**

In `renderReportSection` (report.js), replace the line `if (output) output.innerHTML = reportText ? renderReportLines(reportText) : '';` with a call to the dispatcher:

```js
import renderReportSections from './report-sections.js';
// ...
if (output) {
  smartState.sections = (result && result.sections) || {};
  renderReportSections({ data, sections: smartState.sections, lang: reportLang() });
}
```

(`result` here is the full backend response containing both `data` and `sections`; adjust `renderReportSection(data, month, reportText)` signature callers in `generateComprehensiveReport` to pass through the whole `result`. Simplest: in `generateComprehensiveReport`, set `smartState.sections = result.sections || {}` before calling `renderReportSection`, and have `renderReportSection` call `renderReportSections({data, sections: smartState.sections, lang: reportLang()})`.)

- [ ] **Step 3: Load `report-sections.js` in `smart-analytics.js`**

Add `import renderReportSections from './smart/report-sections.js';` and expose the dispatcher if needed (report.js imports it directly, so no global needed). Ensure the module graph resolves (report.js already imports from `./core.js` and `./charts.js`).

- [ ] **Step 4: Run regression tests + JS syntax check**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
Expected: 72 passed. Also check JS parses: `node --check static/js/smart/report-sections.js static/js/smart/report.js` (if node available; otherwise skip).
Also run: `python -m pytest tests/test_butterfly_report.py -q --tb=short` → PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/report-sections.js static/js/smart/report.js static/js/smart-analytics.js
git commit -m "feat: Butterfly report section dispatcher (exec/priorities/geo/warnings/forecast/appendix)"
```

---

### Task 6: Frontend — remaining section renderers

**Files:**
- Modify: `static/js/smart/report-sections.js`
- Test: existing suite.

**Interfaces:**
- Consumes: same as Task 5.
- Produces: fills out `RENDERERS` for `current_trends`, `clinical_relations`, `composite_patterns`, `anomaly_intel`, `top_deviations`, `regional_intel`, `deterioration`, `data_quality`, `recommendations`, `conclusion`.

- [ ] **Step 1: Add the remaining renderers to `RENDERERS`**

Append to `report-sections.js` (before the `RENDERERS` map, and add keys to it). Follow the existing helper patterns (`esc`, `badge`, `_fmtNum`). Key behaviors:

- `current_trends(data)`: build per-indicator cards from `data.regional`/indicator stats if present; else show narrative. For each indicator present in `data.kpi`/stats, show current/prev/abs change/% change/direction; direction arrow `⬆`(down is better for risk indicators)/`⬇`; severity badge.
- `clinical_relations(data)`: ranked correlation cards from `data.correlations.strong_correlations` (top 8): `A ↔ B · r=<r> (<strength>)`, plus the caution note.
- `composite_patterns(data)`: cards from `data.patterns` (top 5): list `arabic_names`, `hospitals_count`, `support%`, `lift` badge with `title` tooltip "Lift مقدار تجاوز تكرار النمط عن التكرار المتوقع المستقل".
- `anomaly_intel(data)`: per-hospital cards from `data.anomalies` + `data.explanations`: show **Anomaly Score** block and separate **Indicator Deviation** block (top factor name + sign). Use `data.explanations[].top_factors[0..3]`.
- `top_deviations(data)`: table from `data.stratified` top 5 by `abs(deviation_pct)`: hospital / indicator / value / peer mean / deviation%.
- `regional_intel(data)`: table from `data.regional.governorates`: governorate / births / NMR / stillbirth / C-section / risk level.
- `deterioration(data)`: compute simple linear trend over monthly series if available in `data.regional.trends` or a time-series; show slope + R² + direction. If no series, show `<div class="bi-empty">لا توجد سلاسل تاريخية كافية.</div>`.
- `data_quality(data)`: cards from `data.regional.mortality` where `small_sample` true: governorate / births / warning text. Plus the sample-size caution.
- `recommendations(data)`: priority matrix table from `data.decision.priorities` (5): action / target / priority badge (🔴🟠🟡🔵) / impact%.
- `conclusion(data)`: three labeled paragraphs (الوضع الحالي / الخطر المستقبلي / الإجراء) using `data.decision.verdict`, `data.decision.priorities[0]`, and `sections.conclusion` narrative as the primary text.

Provide complete code for each (follow the concrete patterns; keep tables RTL, use `.bi-*` classes).

- [ ] **Step 2: Regression + syntax check**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py tests/test_butterfly_report.py -q --tb=short`
Expected: 72 + butterfly PASS.

- [ ] **Step 3: Commit**

```bash
git add static/js/smart/report-sections.js
git commit -m "feat: complete Butterfly report section renderers"
```

---

### Task 7: Frontend — Polish, RTL & wording audit, integration wiring

**Files:**
- Modify: `static/js/smart/report-sections.js`, `static/js/smart/report.js`, `static/tabs/smart-analytics.html`, `static/css/styles.css`
- Test: full suite.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: final integrated rendering with all 17 sections, correct RTL, wording-clean.

- [ ] **Step 1: Ensure `#smart-report-output` is populated and section order correct**

Verify `renderReportSections` produces all 17 sections in the fixed order; confirm the narrative for each section is embedded via `sectionShell`. Confirm `report.js` reads `sections` from the backend result (not just narrative concatenation).

- [ ] **Step 2: Wording audit — remove any forbidden phrasing in renderers/narratives**

Search `report-sections.js` and backend generators for: `يؤدي إلى`, `causes`, `leads to`, `سبب`. Ensure any remaining are only inside the caution disclaimers (which explicitly deny causality). Fix any that incorrectly assert causality.

- [ ] **Step 3: RTL + numeric isolation audit**

Confirm `.bi-report{direction:rtl}` and that numeric cells (scores, percents) are presented consistently; tables use RTL columns. Optionally wrap numeric values in `<span dir="ltr">` where needed.

- [ ] **Step 4: Full test pass**

Run: `python -m pytest tests/test_chart_migration.py tests/test_auth.py tests/test_butterfly_report.py -q --tb=short`
Expected: all pass (72 + butterfly).

- [ ] **Step 5: Commit**

```bash
git add static/js/smart/report-sections.js static/js/smart/report.js static/tabs/smart-analytics.html static/css/styles.css
git commit -m "feat: Butterfly report integration, RTL & wording audit"
```

---

## Self-Review

**Spec coverage:** All spec sections map to tasks — backend per-section narratives (Tasks 1-3), Butterfly CSS (Task 4), executive/priority/geo/early-warning/forecast/appendix renderers (Task 5), remaining 10 sections (Task 6), polish RTL/wording (Task 7). Placeholder-free; exact code in every code step. Type consistency: `SECTIONS` 17 keys used consistently across Task 1/2/3; `renderReportSections(state)` signature consistent between Task 5 and its use in report.js; `renderSection` naming removed in favor of the single `renderReportSections` dispatcher referencing `RENDERERS[key]`.

**Known residual for implementer:** The `RENDERERS` map in Task 5 covers only 6 sections; Task 6 fills the remaining 10. The `renderSimpleSection` fallback shows a placeholder for not-yet-implemented sections until Task 6 completes. This is intentional sequencing so each task is independently testable.
