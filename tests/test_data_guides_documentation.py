"""Inventory checks for the Data-section user guide.

The guide system must stay complete: every screen of the Data menu needs its
own guide module, every guide must point at a real application tab with a real
permission, and every screenshot it references must exist. These checks read
the frontend sources directly, so a new Data screen added without a guide (or a
guide left behind after a screen is removed) fails here.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES_DIR = ROOT / "static" / "js" / "guides"
IMAGES_DIR = ROOT / "static" / "guides" / "img"

from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY  # noqa: E402


def _data_menu_items():
    for group in DEFAULT_GROUPS:
        if group["name"] == "Data":
            return list(group["items"])
    pytest.fail("no Data group in DEFAULT_GROUPS")


def _guide_modules():
    modules = {}
    for path in sorted(GUIDES_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        meta = {}
        for field in ("key", "tab", "permission", "shot"):
            match = re.search(r"^\s*" + field + r":\s*'([^']+)'", text, re.M)
            if match:
                meta[field] = match.group(1)
        if meta.get("key"):
            modules[meta["key"]] = (path, meta)
    return modules


def test_every_data_menu_screen_has_a_guide():
    guides = _guide_modules()
    missing = [key for key in _data_menu_items() if key not in guides]
    assert not missing, "Data screens without a user guide: %s" % missing


def test_no_guide_without_a_screen():
    guides = _guide_modules()
    unknown = [key for key in guides if key not in TAB_REGISTRY]
    assert not unknown, "Guides without a tab in TAB_REGISTRY: %s" % unknown


def test_guide_points_at_its_own_tab():
    for key, (path, meta) in _guide_modules().items():
        assert meta.get("tab") == key, "%s documents tab %r instead of %r" % (path.name, meta.get("tab"), key)
        assert key in TAB_REGISTRY, "%s: tab %r is not registered" % (path.name, key)
        assert meta.get("permission") == TAB_REGISTRY[key]["permission"], (
            "%s documents permission %r but the tab requires %r"
            % (path.name, meta.get("permission"), TAB_REGISTRY[key]["permission"])
        )


def test_every_guide_screenshot_exists():
    for key, (path, meta) in _guide_modules().items():
        shot = meta.get("shot")
        assert shot, "%s has no screenshot reference" % path.name
        assert (IMAGES_DIR / shot).is_file(), "%s references missing image %s" % (path.name, shot)


def test_guide_index_lists_exactly_the_data_menu():
    source = (ROOT / "static" / "js" / "guide-data.js").read_text(encoding="utf-8")
    imported = re.findall(r"from '\./guides/([a-z0-9-]+)\.js'", source)
    keys = set(_guide_modules())
    assert len(imported) == len(keys), (
        "guide-data.js imports %d modules but only %d carry a key" % (len(imported), len(keys))
    )
    assert keys == set(_data_menu_items()), (
        "the guide index covers %s, the Data menu has %s"
        % (sorted(keys), sorted(_data_menu_items()))
    )


def test_sidebar_lists_the_guides_as_a_submenu():
    sidebar = (ROOT / "static" / "js" / "renderSidebar.js").read_text(encoding="utf-8")
    assert "DATA_GUIDES" in sidebar, "the sidebar no longer reads the guide inventory"
    assert "sidebar-subitem" in sidebar, "the User Guide item has no submenu items"
    # The manuals are read by the user-guide tab, so they hang off its entry.
    mount_head = "\n".join(sidebar.split("function _mountGuideSubmenu()", 1)[1].splitlines()[:3])
    assert 'data-tab="user-guide"' in mount_head, (
        "the guide submenu is no longer mounted under the User Guide item"
    )
    assert 'data-tab="guides"' not in mount_head, (
        "the guide submenu still hangs off the Guides item"
    )


def test_user_guide_entry_point_is_wired():
    registry = (ROOT / "app" / "menu_registry.py").read_text(encoding="utf-8")
    assert '"user-guide"' in registry
    index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="tab-user-guide"' in index_html
    assert (ROOT / "static" / "tabs" / "user-guide.html").is_file()
    renderer = (ROOT / "static" / "js" / "user-guide.js").read_text(encoding="utf-8")
    assert "initUserGuide" in renderer and "switchTab" in renderer
