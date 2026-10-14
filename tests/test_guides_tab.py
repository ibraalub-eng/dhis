"""Guides tab (System group) — الإستعلامات والأدلة hub page.

Static contract like the layered tab: registry entry, index div, sidebar
fallback, auth permission map, Ctrl+K search, and the hub page itself.
"""
import os


_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "..", "static")


def _read(*parts):
    with open(os.path.join(_STATIC, *parts), encoding="utf-8") as f:
        return f.read()


def test_registry_has_guides_in_system_group():
    from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY

    spec = TAB_REGISTRY["guides"]
    assert spec["label"] == "Guides"
    assert spec["permission"] == "dashboard.read"
    sys_group = next(g for g in DEFAULT_GROUPS if g["name"] == "System")
    assert "guides" in sys_group["items"]
    # Between System Control and Settings.
    assert sys_group["items"].index("guides") > sys_group["items"].index("admin")
    assert sys_group["items"].index("guides") < sys_group["items"].index("settings")


def test_index_has_guides_tab_div():
    html = _read("index.html")
    assert 'id="tab-guides"' in html
    div = html.split('id="tab-guides"')[1].split("</div>")[0]
    assert "/static/tabs/guides.html" in div
    assert 'data-loaded="false"' in div


def test_auth_maps_guides_to_dashboard_read():
    js = _read("js", "auth.js")
    assert "'tab-guides': 'dashboard.read'" in js


def test_sidebar_fallback_lists_guides():
    js = _read("js", "renderSidebar.js")
    assert "tab_key:'guides'" in js
    assert "dashboard.read" in js


def test_main_search_includes_guides():
    js = _read("js", "main.js")
    assert "{tab:'guides'" in js
    assert "guides: 'Guides'" in js
    assert "guides: '📚'" in js


def test_guides_hub_page_shape_and_bilingual_keys():
    html = _read("tabs", "guides.html")
    # Every data-i18n key used on the page has a translation entry.
    i18n = _read("js", "i18n.js")
    import re

    keys = set(re.findall(r'data-i18n="([^"]+)"', html))
    assert keys, "guides.html has no data-i18n keys"
    for k in keys:
        # Keys with an apostrophe are double-quoted in i18n.js, the rest single.
        assert (f"'{k}':" in i18n) or (f'"{k}":' in i18n), k
    # Links to the merged printable FAQ+legend page.
    assert "/static/tabs/layered-faq.html" in html
    # All explained screens named on the page.
    for screen in ("Outlier Diagnostics", "Outlier Scan", "Quality Reports",
                   "Alerts", "Audit Log", "Root Cause", "FAQ"):
        assert screen in html, screen


def test_guides_page_is_static_no_api_calls():
    html = _read("tabs", "guides.html")
    assert "apiGet" not in html and "fetch(" not in html
