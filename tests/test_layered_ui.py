"""Static tests for the layered classification UI (design spec 2026-10-08 §10A/§10B).

Outliers-tab classification column first; the Layered tab (§10B) appends its
tab-registration tests here. Mirrors the test_outliers_js.py idiom: the tabs
are plain HTML/JS, so the contract lives in the file contents."""
import os


def _read(*parts):
    path = os.path.join(os.path.dirname(__file__), "..", "static", *parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_outliers_table_has_classification_column_before_why():
    html = _read("tabs", "outliers.html")
    assert 'data-col="layered_type"' in html
    assert html.index('data-col="layered_type"') < html.index('data-i18n="Why"')
    # Column header + legend entry both carry the i18n key.
    assert html.count('data-i18n="Classification"') >= 2


def test_classification_badge_colors_follow_spec():
    """Spec §10A: red / orange / blue / amber, gray for NORMAL + unmatched."""
    js = _read("js", "outliers.js")
    assert "export function classificationBadge" in js
    for type_name, css_class in (
        ("POSSIBLE_DATA_ENTRY_ERROR", "badge-critical"),
        ("CLINICAL_INVESTIGATION_REQUIRED", "badge-medium"),
        ("PEER_ANOMALY", "badge-low"),
        ("VOLUME_DRIVEN_ANOMALY", "badge-amber"),
    ):
        assert type_name in js, type_name
        assert css_class in js, css_class
    assert "badge-muted" in js                      # NORMAL / unmatched / other
    assert "layered_type" in js and "layered_interpretation" in js


def test_outliers_colspan_grew_to_ten_columns():
    js = _read("js", "outliers.js")
    assert js.count('colspan="9"') == 0
    assert js.count('colspan="10"') == 3            # loading, error, empty rows


def test_outliers_csv_carries_classification():
    js = _read("js", "outliers.js")
    assert "'Classification'" in js
    assert "d.layered_type" in js


def test_outliers_why_button_still_opens_anomaly_explanation():
    """Spec §10A: the Why button is unchanged — classification rides in the
    badge tooltip (the one-line interpretation), not in a new popup path."""
    js = _read("js", "outliers.js")
    assert "showWhyPopup(\\'anomaly\\'" in js


def test_classification_badge_styles_exist():
    css = _read("css", "styles.css")
    assert ".badge-amber" in css
    assert ".badge-muted" in css


def test_layered_legend_page_exists_and_is_print_ready():
    """One-page A4 legend for the 8 classifications — admins print/share it.
    Self-contained (no external CSS/JS), Arabic-first, all 8 types present."""
    html = _read("tabs", "layered-legend.html")
    assert "@page" in html and "A4" in html          # print-safe page setup
    for t in ("POSSIBLE_DATA_ENTRY_ERROR", "CLINICAL_INVESTIGATION_REQUIRED",
              "VOLUME_DRIVEN_ANOMALY", "PEER_ANOMALY", "HISTORICAL_ANOMALY",
              "RATE_ANOMALY", "RAW_VALUE_ANOMALY", "NORMAL"):
        assert t in html, t
    # External references would break printing offline.
    assert "<script src=" not in html and '<link rel="stylesheet"' not in html


def test_layered_tab_links_to_the_legend():
    html = _read("tabs", "layered.html")
    assert "/static/tabs/layered-legend.html" in html
    assert 'data-i18n="Classification legend"' in html
    i18n = _read("js", "i18n.js")
    assert "'Classification legend':" in i18n


def test_layered_faq_page_exists_and_is_self_contained():
    """FAQ page following the layered-legend pattern: print-safe @page setup,
    self-contained (no external CSS/JS), covers the core questions."""
    html = _read("tabs", "layered-faq.html")
    assert "@page" in html
    assert "<script src=" not in html and '<link rel="stylesheet"' not in html
    for topic in ("Raw value", "Rate", "HISTORICAL_ANOMALY", "RAW_VALUE_ANOMALY",
                  "VOLUME_DRIVEN_ANOMALY", "PEER_ANOMALY", "NORMAL"):
        assert topic in html, topic
    # Cross-references the printable legend.
    assert "/static/tabs/layered-legend.html" in html


def test_layered_tab_links_to_the_faq():
    html = _read("tabs", "layered.html")
    assert "/static/tabs/layered-faq.html" in html
    assert 'data-i18n="FAQ"' in html
    i18n = _read("js", "i18n.js")
    assert "'FAQ':" in i18n


def test_classification_label_is_translated():
    i18n = _read("js", "i18n.js")
    assert "'Classification': '" in i18n


# ── Task 17: Layered Analysis tab (§10B) ─────────────────────────────

def test_index_has_layered_tab_div():
    html = _read("index.html")
    assert 'id="tab-layered"' in html
    div = html.split('id="tab-layered"')[1].split("</div>")[0]
    assert "/static/tabs/layered.html" in div
    assert 'data-loaded="false"' in div


def test_menu_registry_registers_layered_tab():
    from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY

    spec = TAB_REGISTRY["layered"]
    assert spec["label"] == "Outlier Diagnostics"
    assert spec["permission"] == "analysis.read"
    oversight = next(g for g in DEFAULT_GROUPS if g["name"] == "Oversight")
    assert oversight["items"].index("layered") == oversight["items"].index("outliers") + 1


def test_auth_maps_layered_tab_to_analysis_permission():
    js = _read("js", "auth.js")
    assert "'tab-layered': 'analysis.read'" in js


def test_main_inits_labels_and_searches_the_layered_tab():
    js = _read("js", "main.js")
    assert "_tryInit('loadLayered', 10)" in js
    assert "layered: 'Outlier Diagnostics'" in js
    assert "{tab:'layered'" in js


def test_app_binds_the_layered_module():
    js = _read("js", "app.js")
    assert "['layered'" in js
    assert "import('./layered.js')" in js
    assert "window.loadLayered = _stub('loadLayered')" in js
    assert "_bind(mod, 'loadLayered')" in js
    assert "_bind(mod, 'exportLayeredCSV')" in js


def test_sidebar_fallback_lists_layered_in_oversight():
    js = _read("js", "renderSidebar.js")
    assert "tab_key:'layered'" in js
    assert js.index("tab_key:'layered'") > js.index("tab_key:'outliers'")


def test_layered_tab_html_shape():
    html = _read("tabs", "layered.html")
    for el_id in ("layeredHospitalFilter", "layeredMonthFilter", "layeredIndicatorFilter",
                  "layeredClassificationFilter", "layeredLevelFilter", "layeredInvestigationFilter",
                  "layeredSummary", "layeredTbody", "layeredCount", "layeredPageInfo",
                  "layeredExportBtn", "layeredLoading"):
        assert f'id="{el_id}"' in html, el_id


def test_layered_columns_follow_spec_order():
    """Sidebar columns: Hospital, Month, Indicator, Raw value (Δ%), Rate (Δ%),
    Level, Classification, Why — Denominator and Peer were removed from the
    table (both are restated in full by the Why popup); The Why button carries
    everything the two removed columns showed."""
    html = _read("tabs", "layered.html")
    thead = html.split("<thead>")[1].split("</thead>")[0]
    order = [
        'data-i18n="Hospital"', 'data-i18n="Month"', 'data-i18n="Indicator"',
        'data-i18n="Raw value (Δ%)"', 'data-i18n="Rate (Δ%)"',
        'data-i18n="Level"', 'data-i18n="Classification"', 'data-i18n="Why"',
    ]
    pos = [thead.index(tok) for tok in order]
    assert pos == sorted(pos), pos
    assert 'data-i18n="Denominator (Δ%)"' not in thead
    assert 'data-i18n="Peer"' not in thead


def test_layered_sortable_headers_use_endpoint_sort_keys():
    """The table pages server-side, so only endpoint whitelist keys may be
    sortable (month|level|type|raw_value|rate|denominator); DOM sorting the
    loaded page would order at most 50 rows."""
    html = _read("tabs", "layered.html")
    thead = html.split("<thead>")[1].split("</thead>")[0]
    for col in ("month", "raw_value", "rate", "level", "type"):
        assert f'data-col="{col}"' in thead, col
    for col in ("hospital", "indicator", "peer", "denominator"):
        assert f'data-col="{col}"' not in thead, col


def test_layered_static_filter_options_cover_the_enums():
    html = _read("tabs", "layered.html")
    for type_name in ("NORMAL", "RAW_VALUE_ANOMALY", "RATE_ANOMALY", "HISTORICAL_ANOMALY",
                      "VOLUME_DRIVEN_ANOMALY", "PEER_ANOMALY",
                      "POSSIBLE_DATA_ENTRY_ERROR", "CLINICAL_INVESTIGATION_REQUIRED"):
        assert f'value="{type_name}"' in html, type_name
    for lvl in ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH"):
        assert f'value="{lvl}"' in html, lvl
    for route in ("none", "data_quality", "clinical", "contextual"):
        assert f'value="{route}"' in html, route


def test_layered_js_contract():
    js = _read("js", "layered.js")
    for fn in ("export async function loadLayered", "export function layeredFilterChange",
               "export function layeredPage", "export async function exportLayeredCSV"):
        assert fn in js, fn
    assert "'/analysis/layered?'" in js
    assert "'/analysis/layered/summary?'" in js
    assert "'/analysis/months'" in js
    assert "'/hospitals/'" in js
    assert "page_size=500" in js                # export re-query at the endpoint cap
    assert "classificationBadge" in js           # one badge implementation (Task 16)
    assert "fetch(" not in js                    # apiGet only; the global fetch sweep also checks


def test_layered_why_opens_the_layered_explanation():
    js = _read("js", "layered.js")
    # The source escapes the quotes (the onclick attribute is one JS string),
    # exactly like outliers.js:208 — hence the doubled backslashes here.
    assert "showWhyPopup({kind:\\'layered_outlier\\'" in js
    assert "indicatorCode" in js
    # Narrowed from 'anomaly' not in js: volume_anomaly_score (a legitimate
    # stored layer column the sparkline reads) contains the substring; the
    # actual guard is the OLD dispatcher kind never appearing as a Why target.
    assert "kind:\\'anomaly\\'" not in js


def test_layered_why_uses_the_persistent_drawer():
    """Layered Why buttons route mode='drawer' to explain.js's persistent
    side panel: the panel is appended once to document.body and each row
    click only re-renders its body, so it stays open across rows for the
    comparison workflow (the reason this screen exists).
    """
    js = _read("js", "layered.js")
    assert "mode:\\'drawer\\'" in js
    ex = _read("js", "explain.js")
    assert "function _ensureDrawer" in ex
    assert "export function showWhyDrawer" in ex
    assert "export function closeWhyDrawer" in ex
    assert "document.body.appendChild(_drawerEl)" in ex   # survives row/tab reloads
    assert "id=\"whyDrawerBody\"" in ex                   # body-only re-render per row
    # The popup's fetch flow must share the query/error builders (one pipeline).
    assert "function _buildExplainQuery" in ex
    assert "let q = _buildExplainQuery(opts)" in ex
    # Stale-response guard: a late reply for a previous row never clobbers
    # the currently shown one.
    assert "seq !== _drawerSeq" in ex
    i18n = _read("js", "i18n.js")
    assert "'Why — fixed comparison panel':" in i18n


def test_layered_summary_badges_are_clickable_filters():
    """Summary badges act as classification filters: they must be real
    buttons carrying data-classification, toggling the classification
    select and re-running the load on click. Active state is derived from
    the select's own value at render time, so the badge and the hidden
    Advanced-filter select can never disagree.
    """
    js = _read("js", "layered.js")
    assert "button type=\"button\" data-classification" in js
    assert "sel.value = (sel.value === this.dataset.classification) ? '' : this.dataset.classification" in js
    assert "layeredFilterChange();" in js
    # Active state sourced from the filter select itself, not ad-hoc JS state.
    assert "layeredClassificationFilter" in js
    assert "e.outlier_type === activeCls" in js
    # The title tooltip must be translated via the i18n helper, not hardcoded.
    assert "__('Filter by this classification')" in js
    i18n = _read("js", "i18n.js")
    assert "'Filter by this classification':" in i18n


def test_layered_heatmap_card_elements_and_keys():
    """Hospital × month grid card sits above the table, colored per worst
    classification (the Quality-Score-heatmap doctrine on this screen)."""
    html = _read("tabs", "layered.html")
    assert 'id="layeredHeatmapCard"' in html
    assert "layeredHeatmapBody" in html
    # The card precedes the table card in the DOM (request: above the screen).
    assert html.index('id="layeredHeatmapCard"') < html.index('id="layeredTbody"')
    i18n = _read("js", "i18n.js")
    assert "'Hospital × month heatmap (worst classification)':" in i18n
    assert "'Worst classification per cell; click a cell to filter the table to that hospital and month.':" in i18n


def test_layered_js_heatmap_contract():
    js = _read("js", "layered.js")
    assert "'/analysis/layered/heatmap?'" in js          # same filter-set endpoint
    assert "_renderLayeredHeatmap" in js
    assert "loadLayeredHeatmap();" in js                 # wired into loadLayered
    assert "_TREND_COLORS" in js                         # same color map as the trend
    # Clicking a cell narrows the table to that hospital + month (i18n tooltips).
    assert "window._layeredHeatmapClick" in js
    assert "_|:1" not in js                              # no separator junk


def test_layered_layers_sparkline_column():
    """Small severity strip per row: five colored squares (one per detection
    layer) so the reviewer sees WHY before opening Why. Scores come straight
    from /analysis/layered; the band boundary is a client mirror of
    BAND_CUTOFFS, and the colors come from the level-badge variables so the
    strip agrees with the Level column.
    """
    html = _read("tabs", "layered.html")
    # Column sits between Rate and Level, translated via the i18n map.
    assert html.index('data-i18n="Rate (Δ%)"') < html.index('data-i18n="Layers"') < html.index('data-col="level"')

    js = _read("js", "layered.js")
    for col in ("raw_value_outlier_score", "rate_outlier_score",
                "historical_outlier_score", "volume_anomaly_score",
                "peer_outlier_score"):
        assert f"'{col}'" in js, col
    # Band mirror of BAND_CUTOFFS (first bound a score is <).
    assert "if (s < 0.25) return 'NONE'" in js
    assert "if (s < 0.50) return 'LOW'" in js
    assert "if (s < 0.75) return 'MODERATE'" in js
    assert "if (s < 0.90) return 'HIGH'" in js
    assert "return 'VERY_HIGH'" in js
    # N/A layer is a dashed '·', never a scary color.
    assert "'no data'" in js
    assert "1px dashed var(--border-default" in js
    # The extra column widens every full-width placeholder row.
    assert js.count('colspan="9"') == 3
    assert 'colspan="8"' not in js

    i18n = _read("js", "i18n.js")
    assert "'Layers':" in i18n
    assert "'History':" in i18n


def test_layered_i18n_keys_exist():
    import re

    html = _read("tabs", "layered.html")
    i18n = _read("js", "i18n.js")
    for key in re.findall(r'data-i18n="([^"]+)"', html):
        assert f"'{key}':" in i18n, key
    for key in ("'Layered Analysis'", "'Raw value (Δ%)'", "'Rate (Δ%)'",
                "'No layered findings for the selected criteria.'"):
        assert f"{key}:" in i18n, key


# ── Trend chart: raw value across months, adaptive to the filter ─────

def test_layered_trend_card_elements_and_keys():
    """The chart card sits above the table with its own plot + hint nodes."""
    html = _read("tabs", "layered.html")
    for el_id in ("layeredTrendCard", "layeredTrendChart", "layeredTrendHint",
                  "layeredTrendToggle"):
        assert f'id="{el_id}"' in html, el_id
    assert 'data-i18n="Raw value trend across months"' in html
    # The card precedes the filter/table card in the DOM.
    assert html.index('id="layeredTrendCard"') < html.index('id="layeredTbody"')


def test_layered_js_trend_requires_indicator():
    """A raw-value trend is only meaningful for one indicator (one shared
    unit): the chart asks for an indicator, then plots the hospitals for it
    month by month."""
    js = _read("js", "layered.js")
    assert "'/analysis/layered/trend?'" in js
    assert "loadLayeredTrend" in js
    assert "layeredTrendChart" in js
    assert "Plotly" in js
    assert "layeredTrendHint" in js
    # No indicator chosen → hint instead of a misleading mixed-unit plot.
    assert "Select an indicator to view the trend." in js
    assert "layeredIndicatorFilter" in js
    # Still the authenticated apiGet only (never raw fetch).
    assert "fetch(" not in js
    # The chart reuses global Plotly; it must not pull in the smart module
    # (whose core.js installs document-level listeners on import).
    assert "smart/charts" not in js


def test_layered_js_trend_i18n_keys_exist():
    i18n = _read("js", "i18n.js")
    for key in ("'Raw value trend across months'",
                "'Select an indicator to view the trend.'",
                "'Hide'", "'Show'"):
        assert f"{key}:" in i18n, key
