"""Regression tests: the dashboard KPI drilldown must honor the dashboard's
From/To month filter (window._dashboardDateRange).

Symptom before the fix: the KPI cards showed the filtered value (they send
month_from/month_to), but clicking a card — e.g. "Validation rule — Drilldown"
or "Completeness — Drilldown" — fetched /dashboard/kpi, /dashboard/overview and
/dashboard/component-diagnostics with only hospital_id and year, so the modal
showed unfiltered all-months data.
"""

from pathlib import Path

JS_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "rules-manager.js"


def _read_js():
    return JS_PATH.read_text(encoding="utf-8")


def _fn_src(js, marker, span):
    start = js.index(marker)
    return js[start:start + span]


def test_kpi_drilldown_sends_month_range_on_all_fetches():
    js = _read_js()
    src = _fn_src(js, "window.openKPIDrilldown = function", 3000)
    assert "window._dashboardDateRange" in src
    for urlvar in ("kpiUrl", "overviewUrl", "diagUrl"):
        assert f"if (dr && dr.from) {urlvar} += 'month_from=' + dr.from + '&';" in src, (
            f"{urlvar} must send month_from from the dashboard date range"
        )
        assert f"if (dr && dr.to) {urlvar} += 'month_to=' + dr.to + '&';" in src, (
            f"{urlvar} must send month_to from the dashboard date range"
        )


def test_kpi_cards_and_drilldown_read_the_same_filter_state():
    """The cards and the drilldown must consume the same filter source so their
    numbers can never silently diverge again."""
    js = _read_js()
    cards = _fn_src(js, "function renderKpiCards", 900)
    drill = _fn_src(js, "window.openKPIDrilldown = function", 3000)
    assert "window._dashboardDateRange" in cards
    assert "window._dashboardDateRange" in drill


def test_zero_affected_causes_get_explanatory_collapsible_note():
    """A cause with zero affected hospitals must render a green 'No hospitals
    affected' badge plus a collapsible note listing the months analyzed, so an
    empty list reads as 'nothing to fix' instead of a broken render."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 26000)
    assert "No hospitals affected" in drill
    assert "_zero-note" in drill
    # collapsible: the note starts hidden and the badge carries its toggle chevron
    assert "_zero-note hidden" in drill
    assert "_zero-chev" in drill
    assert "_cause-zero" in drill
    # the note explains why the list is empty and which months were analyzed
    assert "No hospital-month in this range falls under this cause" in drill
    assert "Months analyzed" in drill
    assert "c.monthly" in drill


def test_zero_affected_note_is_translated():
    """The new strings must have Arabic translations in i18n.js."""
    i18n = (Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for key in ("No hospitals affected", "Months analyzed",
                "No hospital-month in this range falls under this cause \u2014 nothing to fix here."):
        assert f"'{key}'" in i18n, f"missing i18n entry: {key}"
