"""D11 — UI reliability contract tests.

These pin the four D11 fixes so a later edit cannot silently undo them:

* static assets: only versioned URLs are cached for a year, bare URLs revalidate;
* the shell: the screen is carried in the URL, so Back/Forward and refresh
  restore the screen the history entry represents;
* the alert dialog: real dialog semantics, focus trap and focus restoration;
* a capped alert's engine sentence is labelled as the pre-cap assessment.

They are source/header contracts (the browser behaviour itself is verified
manually in the D11 acceptance run), and they never touch the database.
"""
from __future__ import annotations

import io
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _text(rel: str) -> str:
    return io.open(ROOT / rel, encoding="utf-8", newline="").read()


# ── 1. static asset caching ──────────────────────────────────────────────
@pytest.fixture()
def static_client(tmp_path):
    from app.main import CachedStaticFiles

    (tmp_path / "app.css").write_text("body{color:red}", encoding="utf-8")
    (tmp_path / "app.js").write_text("var x = 1;", encoding="utf-8")
    (tmp_path / "fragment.html").write_text("<p>fragment</p>", encoding="utf-8")

    app = FastAPI()
    app.mount("/static", CachedStaticFiles(directory=str(tmp_path)))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("asset", ["app.css", "app.js"])
def test_versioned_asset_is_cached_for_a_year(static_client, asset):
    response = static_client.get(f"/static/{asset}?v=1700000000000")
    assert response.status_code == 200
    cache = response.headers["cache-control"].lower()
    assert "max-age=31536000" in cache
    assert "immutable" in cache


@pytest.mark.parametrize("asset", ["app.css", "app.js"])
def test_unversioned_asset_revalidates_instead_of_caching_for_a_year(static_client, asset):
    response = static_client.get(f"/static/{asset}")
    assert response.status_code == 200
    cache = response.headers["cache-control"].lower()
    assert "no-cache" in cache, cache
    assert "max-age=31536000" not in cache, cache


def test_html_fragment_is_never_stored(static_client):
    response = static_client.get("/static/fragment.html?v=1")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"].lower()


def test_dashboard_html_stays_uncached_and_fingerprinted():
    source = _text("app/main.py")
    # The document keeps the per-file ?v= rewrite and must never be stored.
    assert '_STATIC_ASSET_RE.sub(_bust, html)' in source
    assert '"Cache-Control": "no-store, max-age=0"' in source


# ── 2. screen in the URL: Back / Forward / refresh ───────────────────────
def test_tab_history_writes_the_screen_into_the_url():
    source = _text("static/js/main.js")
    assert "function _screenUrl(name)" in source
    assert "function _screenFromUrl()" in source
    assert "function _pushTrail(name)" in source
    assert "'?screen=' + encodeURIComponent(name)" in source


def test_popstate_restores_the_screen_named_by_the_history_entry():
    source = _text("static/js/main.js")
    handler = source[source.index("window.addEventListener('popstate'"):]
    handler = handler[: handler.index("// Forward = replay")]
    assert "_screenFromUrl()" in handler, "popstate must read the screen from the URL"
    assert "switchTab(screen)" in handler
    # An overlay still closes before any navigation happens.
    assert handler.index("_closeAnyOverlay()") < handler.index("switchTab(screen)")


def test_boot_keeps_the_screen_but_drops_handoff_context():
    source = _text("static/js/main.js")
    boot = source[source.index("export function applyBootScreen()"):]
    boot = boot[: boot.index("function _initTab(name)")]
    assert "_screenUrl(resolved)" in boot, "refresh must keep ?screen= in the address bar"
    assert "window.location.pathname" not in boot, "the boot handler must not blank the screen"
    assert "_tabTrailCurrent = resolved" in boot


def test_reopening_the_active_screen_does_not_add_a_duplicate_entry():
    source = _text("static/js/main.js")
    assert "_sameEntry" in source
    assert "if (!_sameEntry) _pushTrail(name);" in source


def test_every_trail_entry_carries_its_screen():
    source = _text("static/js/main.js")
    calls = [line for line in source.splitlines() if "history.pushState(" in line]
    assert calls, "expected the shell to write history entries"
    for line in calls:
        assert "_screenUrl(" in line, "history entry without its screen: " + line.strip()


# ── 3. the detail dialog is a dialog, and focus is managed ───────────────
def test_detail_modal_has_native_dialog_semantics():
    html = _text("static/index.html")
    tag = html[html.index('id="detailModal"'):]
    tag = tag[: tag.index(">") + 1]
    assert 'role="dialog"' in tag
    assert 'aria-modal="true"' in tag
    assert 'aria-labelledby="modalTitle"' in tag
    assert 'aria-label="Close"' in html


def test_modal_moves_focus_in_traps_tab_and_restores_it():
    source = _text("static/js/quality-alerts.js")
    assert "function _installDetailModalA11y()" in source
    assert "_installDetailModalA11y();" in source.split("export async function initQualityAlerts()")[1]
    assert "function _modalTrapTab(event)" in source
    assert "event.shiftKey && document.activeElement === first" in source
    assert "_modalReturnFocus" in source
    # A dialog opened from inside itself must not capture its own close
    # button as the place to send focus back to.
    assert "contains?.(_opener)" in source
    assert "_modalReturnFocus.focus()" in source
    # Keyboard support listens on the dialog itself, not on the document.
    assert "modal.addEventListener('keydown'" in source


def test_modal_does_not_fake_a_role_where_native_markup_exists():
    source = _text("static/js/quality-alerts.js")
    assert 'role="dialog"' not in source
    assert 'role="button"' not in source


# ── 4. capped alert: the engine sentence is labelled, not rewritten ──────
def test_cap_note_explains_the_pre_cap_sentence():
    source = _text("static/js/quality-alerts.js")
    assert "function _capExplanationNote(a)" in source
    assert "_capExplanationNote(a) +" in source
    assert "pre-cap assessment (stored severity {stored})" in source
    # It restates the operational band from effective severity.
    assert "a.effective_severity || a.severity" in source
    # A row that was never capped gets no note.
    assert "cap.stored_severity === cap.severity) return ''" in source


def test_cap_note_has_arabic_copy():
    source = _text("static/js/i18n.js")
    assert "This explanation reports the pre-cap assessment" in source
    assert "النطاق التشغيلي هو" in source


def test_cap_note_is_styled_in_both_themes_by_tokens():
    css = _text("static/css/styles.css")
    assert ".qa-cap-note {" in css
    rule = css[css.index(".qa-cap-note {"):]
    rule = rule[: rule.index("}")]
    assert "var(--text-secondary)" in rule
    assert "var(--bg-hover" in rule
