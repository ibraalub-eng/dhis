"""Browser Back must walk the in-app tab trail, not exit the app.

The app is a single-page app with no hash routes: previously the browser Back
button left the whole application ("close project"). main.js now keeps an
in-page tab trail: every switchTab() pushes a history state marked
__tabtrail, popstate closes any open overlay first, then switches to the
previous tab; Forward replays from an in-page future stack.
"""

from pathlib import Path

MAIN_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "main.js"
EXPLAIN_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "explain.js"


def _read_main_js():
    return MAIN_JS.read_text(encoding="utf-8")


def test_switchtab_pushes_tabtrail_history_state():
    js = _read_main_js()
    # every user-driven tab activation records a history entry
    assert "history.pushState({ __tabtrail: true, tab: name }, '')" in js
    # trail bookkeeping lives in switchTab, guarded against popstate-driven switches
    assert "_tabTrailGuard" in js
    assert "_tabTrail.push(_tabTrailCurrent)" in js
    # a new navigation invalidates the forward stack
    assert "_tabFuture = []" in js


def test_popstate_walks_back_through_tab_trail():
    js = _read_main_js()
    # Back handler exists and switches to the previous tab
    assert "window.addEventListener('popstate'" in js
    assert "_tabTrail.pop()" in js
    assert "switchTab(prev)" in js
    # foreign/missing marker entries are re-marked so Back keeps working
    assert "history.state && history.state.__tabtrail" in js


def test_back_closes_open_overlay_before_switching_tabs():
    """Back with an open overlay must close the overlay first and NOT change
    the active tab — one press = one step back."""
    js = _read_main_js()
    assert "_closeAnyOverlay()" in js
    overlay_closer = js[js.index("function _closeAnyOverlay"):js.index("window._closeAnyOverlay")]
    for overlay in ("explainModalOverlay", "ruleTestModal", "detailModal", "ruleEditModal", "searchOverlay"):
        assert overlay in overlay_closer, f"overlay closer must handle {overlay}"
    # after closing an overlay the history entry is restored WITH the trail
    # marker so the next Back keeps walking the tab trail
    assert "history.pushState({ __tabtrail: true, tab: _tabTrailCurrent }, '')" in js


def test_back_with_why_popup_open_closes_popup_not_tab():
    """Back while the Why popup is open must close THE POPUP and keep the tab.
    closeWhyPopup is module-internal, so explain.js must expose a global hook
    and main.js's overlay closer must consult it FIRST (the popup sits above
    every other overlay)."""
    explain = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "window.closeWhyPopup = function" in explain
    js = _read_main_js()
    closer = js[js.index("function _closeAnyOverlay"):js.index("window._closeAnyOverlay")]
    # Why popup is checked before the other overlays
    assert closer.index("explainModalOverlay") < closer.index("detailModal")
    assert "window.closeWhyPopup" in closer
    # and each overlay closes with its own function (no blanket closeModal)
    assert "window.closeRuleTestModal" in closer
    assert "window.closeRuleModal" in closer


def test_forward_replays_from_inpage_future_stack():
    js = _read_main_js()
    assert "window._tabGoForward" in js
    forward = js[js.index("window._tabGoForward"):]
    assert "_tabFuture.pop()" in forward
    assert "switchTab(next)" in forward


def test_trail_guard_cannot_latch_on_failed_switch():
    """The guard is consumed at the TOP of switchTab so an unknown-tab early
    return can never leave it latched (the next user click must always be
    recorded as a fresh navigation)."""
    js = _read_main_js()
    fn_start = js.index("export async function switchTab")
    body = js[fn_start:fn_start + 1200]
    assert "var _isTrailSwitch = _tabTrailGuard;" in body
    assert "_tabTrailGuard = false;" in body
