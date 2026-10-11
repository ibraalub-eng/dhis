"""Static tests for outliers.js."""
import os


def _read_outliers():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "outliers.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_outliers_exports_expected_api():
    js = _read_outliers()
    for name in ["loadOutliers", "togglePeerPopover"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name


def test_outlier_rows_have_no_native_peer_tooltip():
    """The hospital-name cell must show only the hospital name.

    A native `title` attribute on <tr> makes a browser tooltip with peer
    mean/std/median pop up over the hospital name, which reads as the peer
    stats being attached to the hospital column.
    """
    js = _read_outliers()
    assert "\ttitle=" not in js
    assert "peerTip" not in js


def test_outlier_peer_cell_keeps_drill_down():
    """Removing the tooltip must not remove the clickable Peers cell."""
    js = _read_outliers()
    assert "togglePeerPopover" in js
    assert "peers_detail" in js


def test_peer_popover_keeps_fractional_rates():
    """Tiny-but-nonzero peer rates must not render as 0.00%."""
    js = _read_outliers()
    assert "toFixed(2)" in js
    assert "0.00%" not in js


def test_rule_failures_export_includes_month():
    """The Rule Failures CSV must carry the month, plus every field the
    /analysis/rule-failures endpoint returns.

    The table already had a Month column, but the export omitted it, so a CSV
    covering several months could not be told apart row by row. The old header
    row also mislabelled rule_type as "Indicator" and details as "Failed
    Months".
    """
    js = _read_outliers()
    body = js.split("exportRuleFailuresCSV")[1]
    body = body.split("export function")[0]
    assert "'Month'" in body
    for header in ["'Hospital ID'", "'Hospital'", "'Rule Code'", "'Description'",
                   "'Status'", "'Severity'", "'Type'", "'Details'"]:
        assert header in body, header
    assert "d.month" in body
    assert "d.status" in body
    assert "d.hospital_id" in body
    # Old mislabelled headers must be gone.
    assert "'Indicator'" not in body
    assert "'Failed Months'" not in body


def test_rule_failures_export_uses_full_page_size():
    """Export must not silently truncate to the 100 rows the table loaded.

    window._lastRuleFailureData only ever holds one page (limit=100), so the
    export re-queries with the endpoint's maximum page size.
    """
    js = _read_outliers()
    body = js.split("exportRuleFailuresCSV")[1]
    assert "limit=1000" in body
    assert "async function exportRuleFailuresCSV" in js


def test_alerts_export_button_has_id():
    """The button id lets the export show a busy state while it re-queries."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "alerts.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert 'id="ruleFailExportBtn"' in html
    assert "exportRuleFailuresCSV()" in html


def _read_alerts_tab():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "alerts.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_alerts_tab_has_a_search_box_for_rule_failures():
    """The alert screen's main list is the Rule Failures table; it had only
    drop-down filters, so finding one hospital/rule meant scrolling."""
    html = _read_alerts_tab()
    assert 'id="ruleFailSearch"' in html
    assert "window.onRuleFailSearch()" in html
    js = _read_outliers()
    assert "ruleFailSearch" in js
    # Debounced, and Enter skips the wait.
    assert "setTimeout" in js
    assert "300" in js


def test_alerts_search_reaches_the_server_not_just_the_page():
    """Client-side filtering would only see the loaded page (limit=100)."""
    js = _read_outliers()
    body = js.split("export function loadRuleFailures")[1]
    body = body.split("function updateRuleFailUI")[0]
    assert "'q=' + encodeURIComponent(search)" in body
    # The CSV export must honour the same search.
    filt = js.split("function _ruleFailureFilterQuery")[1].split("export async function")[0]
    assert "'q=' + encodeURIComponent(search)" in filt


def test_alerts_tab_has_a_sort_control():
    html = _read_alerts_tab()
    assert 'id="ruleFailSort"' in html
    for value in ["hospital:asc", "hospital:desc", "month:desc", "month:asc"]:
        assert f'value="{value}"' in html, value


def test_rule_failure_sort_is_server_side():
    """Sorting the loaded DOM rows ordered only the first 100 rows and compared
    months as numbers ('2026-08' -> 2026), so every month of a year tied. The
    header must now drive a server sort over the whole filtered set."""
    js = _read_outliers()
    body = js.split("function wireRuleFailSort")[1].split("let outlierSortCol")[0]
    assert "loadRuleFailures()" in body
    assert "sortTableRows" not in body
    assert "col !== 'month'" in body  # first Month click = newest first


def test_alerts_empty_state_distinguishes_a_search_miss():
    """Otherwise a working search reads as 'nothing failed'."""
    js = _read_outliers()
    assert "No rule failures match" in js
    assert "currentSearch" in js


def test_alerts_search_does_not_shrink_the_filter_dropdowns():
    """Rebuilding the hospital/month lists from searched rows would delete the
    very options the user still needs to switch to."""
    js = _read_outliers()
    body = js.split("function updateRuleFailUI")[1]
    assert "if (!currentSearch) {" in body