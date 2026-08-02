# Full Data Export Design

> **Status:** Approved
> **Date:** 2026-08-02
> **Language of spec:** This feature is part of the Arabic/English Health AI system. The design decisions below are language-agnostic; the UI labels are bilingual (ar/en).

## Goal

Add an "تصدير البيانات / Export Data" button to the **smart analytics page** (`التحليل الذكي`) and the **comprehensive report page** (`التقرير الشامل`). Both buttons produce the **same full JSON package** containing:

- Generated analysis outputs (smart analytics results + comprehensive report text)
- Hospital master data, including locations/regions and governorates
- Indicators and indicator values

The purpose is to let an external tool (Excel, Python, Power BI, etc.) analyze the data or produce its own report.

## Requirements (from brainstorming)

1. **Format:** single JSON file.
2. **Scope:** both the currently selected month and all months. The user picks via a small selector next to the button: "الشهر المحدد" / "كل الأشهر".
3. **Analysis content:** everything — full smart analytics results AND the comprehensive report text (when available).
4. **Language:** follows the page's current language. The comparative page sends its `reportLang`; the smart analytics page sends `ar` (its default). Indicator names are exported from the DB as-is (English) plus the `code` field. The comprehensive report text is generated/cached per language.
5. **AI quota safety:** export must NEVER trigger AI generation. Comprehensive report text is read from the persistent cache only (`get_stored_report`); months without a cached report get `comprehensive_report: null`.
6. **Both pages export the identical full package** (single shared backend endpoint).

## Architecture

### New backend modules

- `app/engine/export.py` — pure logic, no FastAPI dependency:
  - `build_full_export(session, month, lang) -> dict` builds the complete package.
  - `_get_available_months(session) -> List[str]` — distinct `IndicatorValue.month` values (sorted).
  - `_get_master_data(session) -> dict` — governorates, hospitals, indicators, hospital indicator configs.
  - `_get_indicator_values(session, months) -> dict[month -> list]`.
  - `_get_smart_analysis(session, month) -> dict` — calls `run_smart_analytics(session, month)` and serializes dataclasses to JSON-safe dicts.
  - `_get_comprehensive_report(session, month, lang) -> Optional[dict]` — `get_stored_report(session, month, lang)`, returns `{"report": ..., "report_source": ...}` or `None`.
  - `_sanitize(obj)` — recursive numpy/NaN/Inf → native JSON-safe values (mirror the pattern in `app/api/smart_analytics.py:14`).

- `app/api/export.py` — FastAPI router:
  - `router = APIRouter(prefix="/export", tags=["Export"])`
  - `GET /export/full-data?month=YYYY-MM|all&lang=ar|en`
    - `month: str = Query(...)`, `lang: str = Query("ar", pattern="^(ar|en)$")`
    - If `month == "all"`: use `_get_available_months`.
    - If no data exists at all → `HTTPException(404, detail=...)` (bilingual message).
    - Wrap result with `meta`, run `_sanitize`, return `StreamingResponse(media_type="application/json", headers={"Content-Disposition": f"attachment; filename=health_export_YYYY-MM-DD.json"})`.
    - Per-month analysis failure: catch, embed `{"error": str(e)}` for that month, continue.

- Register router in `app/main.py` (`include_router(export_router)`).

### Output JSON structure

```json
{
  "meta": {
    "exported_at": "ISO timestamp",
    "lang": "ar|en",
    "scope": "all | 2026-06",
    "schema_version": 1
  },
  "master_data": {
    "governorates": [{ "id": 1, "name": "غزة" }],
    "hospitals": [{
      "id": 1, "name": "الشفاء", "region": "...", "address": "...",
      "governorate_name": "غزة", "hospital_type_name": "...",
      "facility_ownership_name": "...", "facility_type_name": "...", "is_active": true
    }],
    "indicators": [{ "code": "2", "name": "Total Deliveries", "level": 0, "group_name": "...", "parent_code": null }],
    "hospital_indicator_configs": [{ "hospital_id": 1, "indicator_code": "2", "is_enabled": true, "weight_override": null }]
  },
  "indicator_values": {
    "2026-06": [{ "hospital_id": 1, "hospital_name": "الشفاء", "indicator_code": "2", "indicator_name": "Total Deliveries", "value": 300, "source_file": null }],
    "2026-05": []
  },
  "analysis": {
    "2026-06": {
      "smart": {
        "kpi": { "total_anomalies": 2, "critical_count": 1, "warning_count": 1, "affected_governorates": 1, "top_contributing_factor": "...", "month_status": "attention_needed" },
        "anomalies": [],
        "clustering": {},
        "correlations": {},
        "residuals": [],
        "stratified": [],
        "explanations": [],
        "geo": {},
        "xgboost": {}
      },
      "comprehensive_report": { "report": "text...", "report_source": "ai|local" }
    }
  }
}
```

**Serialization rule:** smart dataclasses serialize via `dataclasses.asdict` (recursive), then `_sanitize` (numpy → native). The `smart` dict mirrors the existing `_envelope` structure returned by `app/api/smart_analytics.py` (`kpi`, `anomalies`, `clustering`, `correlations`, `residuals`, `stratified`, `explanations`, `geo`, `xgboost`).

## Frontend

- **Smart analytics page** (`static/tabs/smart-analytics.html`, controls bar lines 12–29):
  - Add a "تصدير البيانات / Export Data" button (`id="smart-export-btn"`, class `btn btn-sm btn-outline` or the existing gradient style).
  - Add a small scope selector: `<select id="smart-export-scope"><option value="current">الشهر المحدد</option><option value="all">كل الأشهر</option></select>`.
- **Comprehensive report page** (`static/tabs/comparative.html`, controls bar lines 20–45):
  - Add `id="comparative-export-btn"` + `id="comparative-export-scope"` similarly.
- **JS handlers** (`static/js/smart-analytics.js`, `static/js/comparative.js`):
  - On click: build URL `/export/full-data?month=<currentMonth-or-all>&lang=<pageLang>`.
  - Use `window.open(url)` or an `<a download>` trigger so the browser saves the file (server returns `Content-Disposition: attachment`).
  - Show the existing loading overlay during export; hide after `load`/`error` of the download.
- **Language source:**
  - comparative.js: `reportLang` variable.
  - smart-analytics.js: constant `'ar'`.

## Error Handling

- Empty dataset → `404` with bilingual detail.
- A single month's analysis fails → that month gets `"error"` in `analysis[month]`; export still succeeds.
- Invalid `lang` → 422 via FastAPI `pattern` validation.
- JSON serialization of unexpected types → `_sanitize` normalizes; any residual failure is surfaced per-month.

## Testing

New file `tests/test_export.py`:

1. `test_export_meta_and_structure` — response 200, Content-Type json, filename header, `meta` present.
2. `test_export_master_data` — hospitals/governorates/indicators/configs present and correct.
3. `test_export_indicator_values` — values grouped by month, correct columns.
4. `test_export_smart_analysis` — `analysis[month].smart` has kpi/anomalies/clustering/etc.
5. `test_export_all_months` — `month=all` returns every available month.
6. `test_export_comprehensive_report_null_when_uncached` — no cache row → `comprehensive_report` is `None`; and no AI call is made (patch `_call_api`, assert not called).
7. `test_export_comprehensive_report_from_cache` — after storing a report via `store_report`, export returns it.
8. `test_export_empty_db_404` — no data → 404.
9. `test_export_invalid_lang_422` — `lang=xx` → 422.
10. `test_export_sanitizes_numpy` — smart output with numpy values serializes to native types.

Use existing test fixtures (`db_session`, `client` from `tests/conftest.py` / `tests/test_api.py` pattern).

## Non-Goals

- No new export formats (XLSX/CSV) in this feature.
- No AI generation during export.
- No changes to the existing report caching behavior.
- No pagination/streaming of huge files — the JSON is built fully in memory (acceptable for current dataset size).
