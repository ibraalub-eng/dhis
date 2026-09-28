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
PY_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "app" / "api" / "dashboard.py"


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


def test_drilldown_modal_has_component_tabs():
    """The drilldown modal must render a tab bar (Overview + one tab per quality
    component) instead of stacking every component's diagnostics in one long
    collapsible page."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    # tab bar is injected at the top of the modal body, sticky via CSS
    assert "_dd-tabs" in drill
    assert "_dd-tab" in drill
    assert 'data-tabpane="overview"' in drill
    # a pane per component keyed by the component key
    assert 'data-tabpane="' in drill and "+ c.key +" in drill
    # switcher toggles panes and highlights the active tab
    assert "window._kpiDrilldownSwitchTab" in drill
    # switching back to overview re-renders the Chart.js canvas
    assert "_kpiDrilldownRedraw" in drill
    # overview component cards jump to the component's tab (onclick is
    # attribute-escaped in the generated markup, hence the \' in the source)
    assert "window._kpiDrilldownSwitchTab(\\'" in drill


def test_drilldown_tab_strings_are_translated():
    """New tab strings must have Arabic translations in i18n.js."""
    i18n = (Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for key in ("Overview", "View details", "Improving", "Declining", "Stable"):
        assert f"'{key}'" in i18n, f"missing i18n entry: {key}"


def test_zero_affected_causes_get_explanatory_collapsible_note():
    """A cause with zero affected hospitals must render a green 'No hospitals
    affected' badge plus a collapsible note listing the months analyzed, so an
    empty list reads as 'nothing to fix' instead of a broken render."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 44000)
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


def test_affected_hospital_card_is_compact_and_highlighted():
    """Affected-hospital cards inside a drilldown cause must not crowd or
    duplicate information: score appears once (header), long month lists
    collapse to a first→last (N months) summary, >6 failed-rule chips hide
    behind a '+N more' toggle, and the header row has a hover highlight."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    # hover highlight class on the card header
    assert '_hosp-head' in drill
    # months summary collapses long lists (first → last + count) and is LTR-safe
    assert "' → '" in drill or "\u2192" in drill
    assert 'dir="ltr"' in drill
    # failed rules: capped inline list with a +N more expander
    assert "Failed rules" in drill
    assert "fr.slice(0, 6)" in drill
    assert "+' + (fr.length - 6) + '" in drill
    # no duplicated score render inside the expanded body (header owns the %);
    # rows are defensively normalized (avgNum/hName/failedRules) so odd payload
    # shapes can never break a card into an invisible stub.
    expanded = _fn_src(drill, "Hospital body (hidden until expanded)", 4000)
    assert expanded.count("avgNum") == 1
    assert "Array.isArray(h.failed_rules)" in drill
    assert "typeof rawH === 'string'" in drill


def test_affected_card_strings_are_translated():
    """New drilldown card strings must exist in i18n.js."""
    i18n = (Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for key in ("Failed rules", "more", "show less", "months"):
        assert f"'{key}'" in i18n, f"missing i18n entry: {key}"


def test_missing_indicators_are_never_truncated_with_more_row():
    """The affected-hospitals table must render the FULL missing-indicator list:
    the '+ N more missing indicators' placeholder row is gone from the UI and the
    backend no longer caps the payload at 10 rows."""
    js = _read_js()
    assert "more missing indicators" not in js, (
        "drilldown must render all missing indicators, not a '+ N more' row"
    )
    py = PY_DASHBOARD_PATH.read_text(encoding="utf-8")
    assert 'missing_indicators": sorted(list(ha["missing_indicators"]))[:10]' not in py
    assert 'for k, v in sorted(ha["missing_by_indicator"].items())\n                    ][:10]' not in py


# ── Cross-screen navigation from the drilldown ────────────────────────────
# Every drilldown finding must be one press from its full verification:
# hospital rows jump to the Audit screen, failed-rule chips deep-link into
# the Rules Manager, and 🔧 data-problem causes offer the Data Auditor.


def test_affected_hospital_row_has_direct_audit_screen_jump():
    """Affected-hospital cards keep ONE navigation button: 'Why' opens the
    digest popup, whose footer carries the audit-screen jump. A separate
    'Audit' button must NOT be duplicated on the row itself."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    # Why popup is the row's single entry point...
    assert "window.showWhyPopup(\\'quality_score\\'" in drill
    # ...and no second Audit button on the row
    assert "\\u2696" not in drill
    # the shared jump helper still exists globally (popup footer + DA causes use it)
    src = (Path(__file__).resolve().parent.parent / "static" / "js" / "explain.js").read_text(encoding="utf-8")
    assert "window._explainJumpTo = function" in src


def test_explain_jump_to_helper_exposes_audit_jump_globally():
    """explain.js must expose _explainJumpTo (hospital, month, mode) so any
    screen can deep-link into the Audit screen without opening the digest
    popup first; the popup's own footer jump must route through it too."""
    src = (Path(__file__).resolve().parent.parent / "static" / "js" / "explain.js").read_text(encoding="utf-8")
    assert "window._explainJumpTo = function" in src
    # closes the Why popup and any open detail modal before switching screens
    assert "closeWhyPopup();" in src
    assert "window.closeModal" in src
    # the existing footer/endpoint jump path reuses the same helper
    assert "window._explainJumpTo(hid, month, jump);" in src


def test_failed_rule_chips_jump_to_rules_manager_with_rule_preselected():
    """Failed-rule chips must be clickable and deep-link into the Rules Manager
    with the rule preselected. main.js resets the rules search on every screen
    activation, so the preselection lands after the switch via the pending
    global + loadRulesManager's app-state restore."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    # chips are buttons now (pointer + stopPropagation so the card doesn't toggle)
    assert "window._kpiDrilldownOpenRule(" in drill
    assert "event.stopPropagation()" in drill
    # helper switches tab first, then applies the pending selection
    helper = _fn_src(js, "window._kpiDrilldownOpenRule = function", 2000)
    assert "window._kpiPendingRuleSelect" in helper
    assert "switchTab('rules-manager')" in helper
    assert "rulesSearchInput" in helper
    assert "window.onRulesSearch" in helper or "window.renderRulesManager" in helper


def test_data_problem_causes_offer_data_auditor_jump():
    """🔧 data-problem causes must show a 'Data Auditor' button that jumps to
    the audit screen's Data Auditor section (mode 'da'), preselecting the
    cause's first month when present."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    assert r"\'da\'" in drill
    assert "_isDataProblem" in drill
    assert "cause.first_month" in drill


def test_drilldown_navigation_strings_are_translated():
    """New navigation strings must have Arabic translations in i18n.js."""
    i18n = (Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for key in ("Audit", "Data Auditor", "full verification for this hospital-month",
                "open this rule in the Rules Manager",
                "Open the Data Auditor to inspect the source values for this hospital-month"):
        assert f"'{key}'" in i18n, f"missing i18n entry: {key}"


def test_affected_hospital_rows_render_mini_trend_sparklines():
    """Expanded hospital cards must include a mini-trend canvas drawn from the
    component's monthly series; the canvas is painted by _kpiDrilldownDrawSparks
    both after the modal renders and whenever a tab pane becomes visible."""
    js = _read_js()
    drill = _fn_src(js, "window.openKPIDrilldown = function", 64000)
    assert "_dd-spark" in drill
    assert "window._kpiDrilldownDrawSparks" in drill
    assert "_kpiDrilldownCompMeta" in drill
    # drawn lazily on tab switches too, not just after initial render
    switch = _fn_src(js, "window._kpiDrilldownSwitchTab = function", 2000)
    assert "_kpiDrilldownDrawSparks" in switch
