"""Regression tests: the dashboard Quality Score Trend widget must never be
narrowed by the dashboard's filters (hospital, year, From/To date range).

The chart and the Avg Quality Score sparkline fetch a dedicated
/dashboard/trend endpoint with no query params, while /dashboard/overview keeps
sending month_from/month_to so the KPI cards and drilldown modals stay filtered.
"""
from pathlib import Path

JS_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "rules-manager.js"


def _read_js():
    return JS_PATH.read_text(encoding="utf-8")


def _fn_src(js, marker, span):
    start = js.index(marker)
    return js[start:start + span]


def test_load_dashboard_sources_trend_from_filter_immune_endpoint():
    js = _read_js()
    src = _fn_src(js, "export function loadDashboard", 9000)
    # the trend widget hits its own endpoint with a constant, param-less URL
    assert "const trendUrl = '/dashboard/trend'" in src
    # while the overview fetch (which drives the filtered KPI cards) still
    # sends the date range — defined before trendUrl in the same function
    before_trend = src.split("const trendUrl = '/dashboard/trend'")[0]
    assert "month_from=" in before_trend
    assert "month_to=" in before_trend


def test_trend_chart_and_sparkline_use_trend_endpoint_data():
    js = _read_js()
    src = _fn_src(js, "export function loadDashboard", 9000)
    # chart + sparkline consume the filter-immune endpoint's series...
    assert "trendData.quality_trend" in src
    assert "trendPoints" in src
    # ...and no longer read the overview's (filtered) quality_trend
    assert "data.quality_trend" not in src
