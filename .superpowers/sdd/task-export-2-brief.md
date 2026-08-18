### Task 2: Export Engine — Smart Analysis, Report from Cache, Build Package

**Files:**
- Modify: `app/engine/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: Task 1 helpers `_sanitize`, `_get_available_months`, `_get_master_data`, `_get_indicator_values`, `NoDataError`.
- Consumes: `get_stored_report(session, month, lang)` from `app.engine.comparative.report_cache`.
- Consumes: `run_smart_analytics(session, month)` from `app.engine.smart`.
- Produces (consumed by Task 3):
  - `build_full_export(session, month: str, lang: str) -> dict` with shape:
    `{meta: {exported_at, lang, scope, schema_version}, master_data, indicator_values, analysis: {month: {"smart": {...}, "comprehensive_report": {...}|None}}}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# --- build_full_export ---

def test_build_full_export_structure(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["meta"]["scope"] == "2026-06"
    assert pkg["meta"]["lang"] == "ar"
    assert pkg["meta"]["schema_version"] == 1
    assert "master_data" in pkg
    assert "indicator_values" in pkg
    assert "analysis" in pkg
    assert "2026-06" in pkg["analysis"]


def test_build_full_export_smart_sections(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    smart = pkg["analysis"]["2026-06"]["smart"]
    for key in ("kpi", "anomalies", "clustering", "correlations", "residuals",
                "stratified", "explanations", "geo"):
        assert key in smart


@patch("app.engine.export.run_smart_analytics")
def test_build_full_export_month_error_embedded(mock_analytics, db_session):
    mock_analytics.side_effect = RuntimeError("boom")
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert "error" in pkg["analysis"]["2026-06"]
    assert "boom" in pkg["analysis"]["2026-06"]["error"]


def test_build_full_export_all_months(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import build_full_export
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    pkg = build_full_export(db_session, "all", "ar")
    assert pkg["meta"]["scope"] == "all"
    assert set(pkg["indicator_values"].keys()) == {"2026-05", "2026-06"}
    assert set(pkg["analysis"].keys()) == {"2026-05", "2026-06"}


def test_build_full_export_comprehensive_report_null_when_uncached(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["analysis"]["2026-06"]["comprehensive_report"] is None


@patch("app.engine.comparative.report_cache._call_api")
def test_export_never_calls_ai(mock_api, db_session):
    from app.engine.export import build_full_export
    build_full_export(db_session, "all", "ar")
    assert mock_api.call_count == 0


def test_build_full_export_report_from_cache(db_session):
    from app.engine.comparative.report_cache import store_report
    from app.engine.export import build_full_export
    store_report(db_session, "2026-06", "ar", {"report": "نص مخزن", "report_source": "ai", "month": "2026-06"})
    pkg = build_full_export(db_session, "2026-06", "ar")
    rep = pkg["analysis"]["2026-06"]["comprehensive_report"]
    assert rep == {"report": "نص مخزن", "report_source": "ai"}


def test_build_full_export_no_data_raises(db_session):
    from app.models import Hospital
    from app.engine.export import build_full_export, NoDataError
    db_session.query(Hospital).delete()
    db_session.commit()
    try:
        build_full_export(db_session, "all", "ar")
        assert False, "expected NoDataError"
    except NoDataError:
        pass
```

Add `from unittest.mock import patch` to the top of `tests/test_export.py` if not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "build_full_export or never_calls_ai" -q`
Expected: FAIL — `ImportError: cannot import name 'build_full_export'` (and `run_smart_analytics` not patched since `app.engine.export` has no such symbol yet).

- [ ] **Step 3: Implement the changes**

Append to `app/engine/export.py`:

```python
from datetime import datetime

from app.engine.smart import run_smart_analytics
from app.engine.comparative.report_cache import get_stored_report

SCHEMA_VERSION = 1


def _get_smart_analysis(session: Session, month: str) -> Dict[str, Any]:
    """Full smart analytics output for a month, serialized to JSON-safe dicts."""
    result = run_smart_analytics(session, month)
    data = {
        "kpi": result.kpi.__dict__ if result.kpi else {},
        "anomalies": [a.__dict__ for a in result.anomalies],
        "clustering": result.clustering.__dict__ if result.clustering else {},
        "correlations": result.correlations.__dict__ if result.correlations else {},
        "residuals": [r.__dict__ for r in result.residuals],
        "stratified": [s.__dict__ for s in result.stratified],
        "explanations": [
            {**e.__dict__, "top_factors": [f.__dict__ for f in e.top_factors]}
            for e in result.explanations
        ],
        "geo": {
            "governorates": [g.__dict__ for g in result.geo.governorates],
        } if result.geo else None,
    }
    if result.xgboost_predictions:
        xgb = result.xgboost_predictions
        data["xgboost"] = {
            "model_r2": xgb.model_r2,
            "model_mae": xgb.model_mae,
            "training_months": xgb.training_months,
            "hospitals_trained": xgb.hospitals_trained,
            "accuracy_note": xgb.accuracy_note,
            "predictions": [
                {
                    **p.__dict__,
                    "top_drivers": [d.__dict__ for d in p.top_drivers],
                }
                for p in xgb.predictions
            ],
            "global_feature_importance": [fi.__dict__ for fi in xgb.global_feature_importance],
        }
    return _sanitize(data)


def _get_comprehensive_report(session: Session, month: str, lang: str) -> Optional[Dict[str, str]]:
    """Cached comprehensive report text only. Never triggers AI generation."""
    cached = get_stored_report(session, month, lang)
    if not cached:
        return None
    return {"report": cached.get("report"), "report_source": cached.get("report_source")}


def build_full_export(session: Session, month: str, lang: str) -> Dict[str, Any]:
    """Build the complete export package for month ('all' or 'YYYY-MM') and lang."""
    months = _get_available_months(session) if month == "all" else [month]
    master = _get_master_data(session)

    if not master["hospitals"] and not months:
        raise NoDataError("لا توجد بيانات للتصدير / No data available to export")

    analysis = {}
    for m in months:
        try:
            analysis[m] = {
                "smart": _get_smart_analysis(session, m),
                "comprehensive_report": _get_comprehensive_report(session, m, lang),
            }
        except Exception as e:
            analysis[m] = {"error": str(e)}

    return {
        "meta": {
            "exported_at": datetime.now().isoformat(),
            "lang": lang,
            "scope": month,
            "schema_version": SCHEMA_VERSION,
        },
        "master_data": master,
        "indicator_values": _get_indicator_values(session, months),
        "analysis": analysis,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -k "build_full_export or never_calls_ai" -q`
Expected: 7 passed

- [ ] **Step 5: Run the full export suite**

Run: `python -m pytest tests/test_export.py -q`
Expected: all pass (14 total)

- [ ] **Step 6: Commit**

```bash
git add app/engine/export.py tests/test_export.py
git commit -m "feat: build full data export package with analysis and cached reports"
```


