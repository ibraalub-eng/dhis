"""Indicators tab (Indicators group, 2026-10-18) — wiring contract.

Static-contract test in the same style as test_guides_tab.py /
test_layered_ui.py: registry entry, index div, module loading, sidebar
fallback, auth permission map, Ctrl+K search, i18n, and the shape of the
tab fragment + module itself.

The tab is the management UI for app/api/indicator_definitions.py:
searchable catalog (raw + rate_spec + derived), Indicator Builder with
server-side validation BEFORE save, live preview against real data,
version history and safe deletion.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "..", "static")


def _read(*parts):
    with open(os.path.join(_STATIC, *parts), encoding="utf-8") as f:
        return f.read()


# ── menu registration ───────────────────────────────────────────────────────

def test_registry_has_indicators_tab_with_settings_permission():
    from app.menu_registry import TAB_REGISTRY

    spec = TAB_REGISTRY["indicators"]
    assert spec["label"] == "Indicators"
    assert spec["icon"] == "\U0001F4D0"          # 📐
    assert spec["permission"] == "settings.read"


def test_default_groups_data_group_orders_indicators_after_groups():
    from app.menu_registry import DEFAULT_GROUPS

    data_group = next(g for g in DEFAULT_GROUPS if g["name"] == "Data")
    items = data_group["items"]
    assert "indicators" in items
    # right after Data Group, before Validation Rules
    assert items.index("indicators") == items.index("indicator-groups") + 1
    assert items.index("indicators") < items.index("rules-manager")


def test_menu_backfill_covers_new_tab():
    """The startup merge must place the tab for pre-existing installs."""
    from app.menu_registry import TAB_REGISTRY

    assert "indicators" in TAB_REGISTRY  # seed/backfill iterates the registry


# ── index.html fragment mount ───────────────────────────────────────────────

def test_index_has_indicators_tab_div():
    html = _read("index.html")
    assert ('id="tab-indicators" class="tab-content" data-loaded="false"'
            in html)
    assert 'data-src="/static/tabs/indicators.html"' in html
    # mounted right after the Data Group tab block
    assert html.index('id="tab-indicators"') > html.index('id="tab-indicator-groups"')
    assert html.index('id="tab-indicators"') < html.index('id="tab-rules-manager"')


# ── main.js: init branch, labels, icons, Ctrl+K search ──────────────────────

def test_main_js_initializes_indicators_tab():
    js = _read("js", "main.js")
    assert "_tryInit('initIndicators', 10)" in js
    assert "indicators: 'Indicators'" in js          # _tabLabels
    assert "indicators: '\U0001F4D0'" in js          # _tabIcons
    assert "{tab:'indicators',kw:" in js             # _searchItems


# ── app.js: stub + dynamic module + bind case ───────────────────────────────

def test_app_js_stubs_loads_and_binds_indicators_module():
    js = _read("js", "app.js")
    assert "window.initIndicators = _stub('initIndicators')" in js
    assert "['indicators', () => import('./indicators.js')]" in js
    assert "case 'indicators':" in js
    assert "_bind(mod, 'initIndicators')" in js
    # handler bindings (must all be exported by indicators.js)
    for fn in ("openIndicatorBuilder", "closeIndicatorBuilder",
               "saveIndicator", "validateIndicatorDraft",
               "closeIndicatorDrawer", "toggleIndicatorActive",
               "deleteIndicator", "recomputeIndicators"):
        assert "_bind(mod, '%s')" % fn in js, fn


# ── sidebar fallback + auth + i18n ──────────────────────────────────────────

def test_sidebar_fallback_lists_indicators_tab():
    js = _read("js", "renderSidebar.js")
    assert ("{tab_key:'indicators', label:'Indicators', icon:'\U0001F4D0',"
            " permission:'settings.read'}" in js)


def test_auth_gates_indicators_tab_on_settings_read():
    js = _read("js", "auth.js")
    assert "'tab-indicators': 'settings.read'" in js


def test_i18n_translates_indicators_tab():
    i18n = _read("js", "i18n.js")
    assert "'Indicators': 'المؤشرات'" in i18n


def test_fragment_data_i18n_keys_are_translated():
    """Every data-i18n key used by the fragment must exist in i18n.js."""
    import re
    html = _read("tabs", "indicators.html")
    i18n = _read("js", "i18n.js")
    keys = set(re.findall(r'data-i18n="([^"]+)"', html))
    assert keys, "fragment should use data-i18n attributes"
    missing = [k for k in sorted(keys) if ("'%s':" % k) not in i18n]
    assert missing == [], "missing i18n entries: %s" % missing


# ── fragment shape ──────────────────────────────────────────────────────────

def test_fragment_has_catalog_and_builder_and_drawer():
    html = _read("tabs", "indicators.html")
    for el_id in (
        # catalog toolbar
        "indSearch", "indCategoryFilter", "indTypeFilter",
        "indStatusFilter", "indCount", "btnNewIndicator", "btnRecomputeAll",
        "indTbody",
        # detail drawer
        "indDrawerOverlay", "indDrawer", "indDrawerBody",
        "indResultsBody", "indVersionsBody",
        # builder modal
        "indBuilderModal", "indBuilderTitle", "indAdvancedOptions",
        "indFormulaMode", "indCode",
        "indName", "indDesc", "indGroup", "indPaletteSearch", "indPalette",
        "indNumZone", "indDenZone", "indExpr", "indAggregation", "indOperator",
        "indMultiplier", "indResultType", "indUnit", "indDirection",
        "indThresholdLow", "indThresholdHigh", "indTargetMin", "indTargetMax",
        "indFormulaPreview", "btnValidateIndicator", "btnSaveIndicator",
        "indValidationMsgs",
    ):
        assert 'id="%s"' % el_id in html, "missing element: %s" % el_id


def test_catalog_has_one_category_filter_and_column():
    """Kind and Group are merged into a single Category dimension."""
    html = _read("tabs", "indicators.html")
    assert 'id="indCategoryFilter"' in html
    assert 'data-i18n="All categories"' in html
    # the two old controls are gone
    assert 'id="indKindFilter"' not in html
    assert 'id="indGroupFilter"' not in html
    # ...and so are the old columns in the catalog table
    thead = html[html.index("<thead>"):html.index("</thead>")]
    assert 'data-i18n="Kind"' not in thead
    assert 'data-i18n="Group"' not in thead
    assert 'data-i18n="Category"' in thead
    # header + builder label, and the matching loading colspan
    assert html.count('data-i18n="Category"') == 2
    assert 'colspan="7"' in html


def test_fragment_write_controls_require_permission():
    html = _read("tabs", "indicators.html")
    # settings.write-gated controls carry data-requires (auth.js hides them)
    assert 'id="btnNewIndicator"' in html and "data-requires" in html


def test_indicator_builder_keeps_advanced_fields_collapsed_and_generates_id():
    html = _read("tabs", "indicators.html")
    js = _read("js", "indicators.js")
    assert '<details id="indAdvancedOptions"' in html
    assert 'data-i18n="Advanced options"' in html
    assert 'id="indCode"' in html
    assert 'id="indCode" placeholder="Automatically created from the name" disabled' in html
    assert "Automatically generated from the indicator name and cannot be edited" in html
    assert "nameInput.addEventListener('input', _onNameChange)" in js
    assert "function _onNameChange()" in js
    assert "function _generatedName()" in js
    assert "function _codeFromName(name)" in js
    assert "const refs = _selectedCodes().map(code =>" in js
    assert "'indicator_' + refs.join('_')" in js
    assert "_syncGeneratedFields();" in js
    assert "indicator name and ID are generated automatically" in html


def test_fragment_is_rtl_or_plain_but_self_contained():
    html = _read("tabs", "indicators.html")
    # fragment must not include its own <script> or reference App globals
    assert "<script" not in html
    assert "window.App" not in html


# ── module shape ────────────────────────────────────────────────────────────

def test_indicators_js_exports_and_uses_safe_api():
    js = _read("js", "indicators.js")

    def _exported(name):
        # `export async function` is a valid export too — app.js _bind only
        # requires the function to be exported, async handlers are fine.
        return (("export function %s" % name) in js
                or ("export async function %s" % name) in js)

    assert _exported("initIndicators")
    for fn in ("openIndicatorBuilder", "closeIndicatorBuilder",
               "saveIndicator", "validateIndicatorDraft",
               "closeIndicatorDrawer", "toggleIndicatorActive",
               "deleteIndicator", "recomputeIndicators"):
        assert _exported(fn), fn
    # module talks to the dedicated API, not the raw-catalog CRUD
    assert "'/hospitals/indicators'" in js           # palette of raw elements
    assert "'/indicators/validate'" in js            # validate BEFORE save
    assert "'/indicators/recompute'" in js
    assert "/toggle" in js
    assert "purge" in js                             # safe-delete flow
    # uses the shared api helpers + destructive-confirm dialog
    assert "apiGet" in js and "apiPostJSON" in js and "apiPut" in js
    assert "apiDelete" in js
    assert "confirmDestructive" in js
    # never execute user formula text client-side
    assert "eval(" not in js
    assert "new Function" not in js
    # builder palette is filtered client-side over the raw catalog
    assert "fetchPalette" in js or "loadPalette" in js


def test_indicators_js_status_and_safety_semantics():
    js = _read("js", "indicators.js")
    # statuses mirror app/engine/indicator_calc.py — keep them in sync
    for status in ("ok", "missing_data", "zero_denominator", "no_data", "error"):
        assert "'%s'" % status in js, status
    # zero-denominator is explained, never displayed as 0
    assert "zero_denominator" in js
    # stale results (older definition_version) are flagged after edits
    assert "stale" in js
