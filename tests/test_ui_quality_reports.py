"""Regression tests: the Quality Reports grid must NOT render gray
'Analysis disabled' cards for reports flagged is_enabled=false (months with
no analyzed data — e.g. the poisoned '__all__' rows the old tree save bug
created). They are hidden and summarized in a count note instead.
"""

from pathlib import Path

JS_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "upload.js"
I18N_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js"


def test_disabled_reports_are_hidden_not_rendered():
    js = JS_PATH.read_text(encoding="utf-8")
    start = js.index("export function filterQualityReports")
    src = js[start:js.index("\n        let currentValidation")]
    # strip // comments so doc comments don't trip the 'must be gone' checks
    code = "\n".join(ln for ln in src.split("\n") if not ln.strip().startswith("//"))
    # disabled rows must be filtered OUT of the card list...
    assert "r.is_enabled === false" in code
    # ...and no code path may append a 'report-card disabled' element anymore
    assert "report-card disabled" not in code, (
        "the gray 'Analysis disabled' card must not be rendered anymore"
    )
    assert "Analysis disabled" not in code
    # a count note must be appended when disabled reports exist
    assert "qualityDisabledNote" in code
    assert "disabled report(s) not shown" in code


def test_disabled_note_is_translated():
    i18n = I18N_PATH.read_text(encoding="utf-8")
    assert "'disabled report(s) not shown':" in i18n


def test_report_detail_merges_element_outliers_and_shows_peer_tooltip():
    """Data-element outliers come from the layered table and must be merged
    into the report's outlier list, with the peer group exposed as a tooltip
    (the table already has a Peers column; the names did not fit in it)."""
    js = JS_PATH.read_text(encoding="utf-8")
    assert "report.layered_results" in js, \
        "data-element outliers must be merged into the anomaly list"
    assert "peerTip" in js, "the Peers cell must carry a peer tooltip"
    assert "title=\"'+esc(peerTip)+'\"" in js
    assert "__('Data element')" in js, \
        "element rows must be distinguishable from derived rates"


def test_anomaly_table_shows_the_layer_breakdown_inline():
    """Each outlier row carries a raw/rate/history/volume/peer strip, built
    from the stored layer scores — never recomputed in the browser."""
    js = JS_PATH.read_text(encoding="utf-8")
    assert "const LAYER_ORDER = ['raw', 'rate', 'historical', 'volume', 'peer']" in js
    assert "function _layerStrip(" in js
    assert "_layerStrip(a)" in js, "the strip must be rendered in the table row"
    assert "'<th title=\"' + esc(__('Layer breakdown" in js, \
        "the table needs a Layers column header"
    # Merged data-element rows must keep their layers and peer statistics.
    assert "layers: x.layers || []" in js
    assert "peer_stats: x.peer_stats || null" in js
    # A layer that could not run must never look like a clean one.
    assert "layer-chip-off" in js


def test_layer_chips_use_the_peer_statistics():
    """The peer chip explains itself with the group's n / mean / sigma / range
    / median, computed only when the API did not supply them."""
    js = JS_PATH.read_text(encoding="utf-8")
    assert "function _peerStats(" in js
    assert "if (a.peer_stats && a.peer_stats.count) return a.peer_stats;" in js
    assert "function _peerStatLines(" in js
    for label in ("'Peer mean'", "'Peer std'", "'Peer range'", "'Peer median'"):
        assert label in js


def test_layer_strip_has_styles():
    css = (Path(__file__).resolve().parent.parent
           / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".layer-strip" in css
    assert ".layer-chip-off" in css


def test_anomaly_outlier_filter_reads_the_inline_dropdown_global():
    """The Outlier dropdown is an inline handler, so it writes a window global.
    Reading a module-local variable made every filter choice a no-op."""
    js = JS_PATH.read_text(encoding="utf-8")
    assert "window.anomFilterOutlier = 'all'" in js
    assert "const outlierFilter = window.anomFilterOutlier" in js


def test_empty_state_still_shows_when_nothing_at_all():
    js = JS_PATH.read_text(encoding="utf-8")
    start = js.index("export function filterQualityReports")
    src = js[start:js.index("\n        let currentValidation")]
    # the 'no reports match' empty state must survive and consider disabled rows
    assert "No reports match the selected filters." in src
    assert "!filtered.length && !disabled.length" in src
