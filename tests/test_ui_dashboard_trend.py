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


def test_trend_axis_fits_the_data_instead_of_a_fixed_0_100_scale():
    """A narrow score band (e.g. 88–94) looked flat on a 0–100 axis.

    The dashboard trend fits its y-axis to the series: zoom to the data, keep
    at least a few steps of height so a genuinely flat series still looks
    flat, snap to round tick values and never leave 0–100.
    """
    js = _read_js()
    helper = _fn_src(js, "function scoreTrendAxis(points)", 900)
    assert "stepSize" in helper
    assert "Math.max(0, Math.floor" in helper
    assert "Math.min(100, Math.ceil" in helper
    assert "stepSize * 3" in helper

    dashboard = _fn_src(js, "export function loadDashboard", 9000)
    assert "const trendAxis = scoreTrendAxis(trendPoints)" in dashboard

    chart = _fn_src(js, "trendChartInstance = new Chart", 2400)
    assert "min: trendAxis.min" in chart and "max: trendAxis.max" in chart
    assert "stepSize: trendAxis.stepSize" in chart
    assert "min: 0, max: 100, ticks" not in chart, \
        "the dashboard trend must not pin the axis to the full score range"
    assert "callback: v => v + '%'" in chart


def test_trend_chart_and_sparkline_use_trend_endpoint_data():
    js = _read_js()
    src = _fn_src(js, "export function loadDashboard", 9000)
    # chart + sparkline consume the filter-immune endpoint's series...
    assert "trendData.quality_trend" in src
    assert "trendPoints" in src
    # ...and no longer read the overview's (filtered) quality_trend
    assert "data.quality_trend" not in src
