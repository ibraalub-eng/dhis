"""Screen ↔ indicator-type contract (2026-10-21).

* **Outlier Analysis** (``outliers`` tab, fed by AnomalyResult rows written by
  the pipeline's ``detect_anomalies``) works on **DERIVATIVE indicators**:
  every candidate carries a denominator — no raw data elements, no
  count-type forecast specs.
* **Outlier Diagnostics** (``layered`` tab) works on **DATA ELEMENTS**:
  its indicator filter never offers rate rows (synthetic ``rate_*`` codes /
  persisted numerator+denominator rows) — those belong to the Analysis
  screen.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "..", "static")


def _read(*parts):
    with open(os.path.join(_STATIC, *parts), encoding="utf-8") as f:
        return f.read()


# ── Outlier Analysis = derivative indicators only ──────────────────────────

def test_outlier_analysis_candidates_are_derivative_only(db_session):
    """The pipeline's candidate set is the DERIVATIVE registry: every row is
    an active ``IndicatorDefinition`` (source ``derived``), never a raw data
    element.

    Coverage is the whole derivative catalog, not the zscore slice alone —
    the clinical/forecast derivatives (breastfeeding, LBW, hysterectomy, SMM
    per 1,000 deliveries, …) are the Indicators screen's derivative indicators
    and must reach the Outlier Analysis screen too. A count-type derivative
    ("Adolescent cases") qualifies as well: it is computed from data elements
    even though it has no denominator.
    """
    from app.engine import indicator_service

    candidates = indicator_service.resolve_outlier_candidates(db_session)
    assert candidates, "seeded registry should provide outlier candidates"
    for r in candidates:
        assert r.source == indicator_service.SOURCE_DERIVED, (
            f"{r.code} is a {r.source} indicator — a raw data element must "
            f"never reach the Outlier Analysis candidate set")
        assert r.definition is not None and r.definition.is_active, (
            f"{r.code} is not an active registry definition")
    sites = {r.site for r in candidates}
    assert "clinical" in sites and "zscore" in sites, (
        "clinical derivatives (breastfeeding, LBW, hysterectomy, …) must be "
        "scanned — not only the zscore slice")


def test_outlier_analysis_selector_is_labelled_derivative():
    html = _read("tabs", "outliers.html")
    assert 'data-i18n="Derivative Indicator"' in html
    # the dropdown keeps its id (wiring) and states the type in its tooltip
    assert 'id="outlierRateFilter"' in html
    assert "Derivative indicators only" in html


# ── Outlier Diagnostics = data elements only ───────────────────────────────

def test_diagnostics_indicator_filter_offers_data_elements_only():
    js = _read("js", "layered.js")
    assert "function _isRateRow(" in js
    # rate rows are recognised by their synthetic code or persisted
    # numerator+denominator and never registered as filter options
    assert "/^rate_/" in js
    assert "!_isRateRow(d)" in js


def test_diagnostics_selector_is_labelled_data_element():
    html = _read("tabs", "layered.html")
    assert 'data-i18n="Data Element"' in html
    assert 'id="layeredIndicatorFilter"' in html
