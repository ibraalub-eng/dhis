"""Regression: the ✕ (close) buttons on the Why popup and the detail modal
must ALWAYS close their modal.

Symptom: "cross icon sometimes does not close the modal".

1. The Why popup's ✕ (#explainModalClose) had NO click listener wired at
   all — only backdrop clicks and Escape worked, so clicking ✕ did nothing.
   The X is now handled by a delegated listener on the overlay (survives any
   body re-render) and the button has a fixed 34px hit-area so it can never
   shrink to a 1-2px target (the generic .modal-close float rule also
   mis-positions it under RTL, so the popup uses its own flex styling).

2. The detail modal's ✕ uses inline onclick="closeModal()". window.closeModal
   started as an app.js stub that only logs; if clinical.js (the real owner)
   failed to load, the stub swallowed every click and the modal became
   unclosable. app.js now defines a property-backed fallback that closes the
   modal directly when the real module never binds.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

EXPLAIN_JS = STATIC / "js" / "explain.js"
APP_JS = STATIC / "js" / "app.js"
QA_JS = STATIC / "js" / "quality-alerts.js"
CSS = STATIC / "css" / "styles.css"


def test_explain_x_button_has_delegated_click_handler():
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    # The overlay click handler must dispatch on the close button...
    assert "closest('#explainModalClose')" in src
    # ...via delegation from the overlay (not a one-shot bind on innerHTML).
    assert "_modalEl.addEventListener('click'" in src
    assert "closeWhyPopup()" in src


def test_explain_x_button_has_fixed_hit_area():
    """A 1-2px glyph target is effectively unclickable. The button must own a
    real box (34px) independent of RTL float rules."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "width:34px;height:34px" in src
    # must NOT reuse the floating .modal-close class (breaks under RTL)
    assert 'class="modal-close"' not in src.split("explainModalClose")[0][-400:]


def test_close_why_popup_hides_every_overlay_clone():
    """closeWhyPopup must be defensive: hide any #explainModalOverlay clone
    (hot reload / double import) so the backdrop can never stay stuck."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    fn = src[src.index("export function closeWhyPopup"):]
    fn = fn[:fn.index("}", fn.index("{")) + 1]
    assert "querySelectorAll('#explainModalOverlay')" in fn
    assert "style.display = 'none'" in fn


def test_app_js_close_modal_has_working_fallback():
    """The stub must be backed by a property fallback that actually hides
    #detailModal, so the ✕ works even if clinical.js never loads."""
    src = APP_JS.read_text(encoding="utf-8")
    assert "Object.defineProperty(window, 'closeModal'" in src
    assert "_defaultCloseModal" in src
    assert "getElementById('detailModal')" in src
    assert "classList.remove('show')" in src


def test_quality_alert_modal_opens_via_show_class():
    """Quality Alerts opened #detailModal with an inline `display:block`.

    closeModal() (and the app.js fallback) only remove the `.show` class, while
    `#detailModal.show{display:flex}` is a stylesheet rule — an inline display
    outranks it, so ✕, backdrop click and Escape all left the modal on screen.
    The opener must use the class (and clear any stale inline override).
    """
    src = QA_JS.read_text(encoding="utf-8")
    opener = src[src.index("export async function openQualityAlert"):]
    opener = opener[:opener.index("\n}\n")]
    assert "modal.classList.add('show')" in opener
    assert "modal.style.display = ''" in opener
    assert "style.display = 'block'" not in opener


def test_detail_modal_close_not_hidden_under_content():
    """CSS guard: .modal-close must stay clickable — no negative z-index and
    no zero-size box."""
    css = CSS.read_text(encoding="utf-8")
    close_rule = css[css.index(".modal-close"):]
    close_rule = close_rule[:close_rule.index("}")]
    assert "z-index" not in close_rule
    assert "display: none" not in close_rule and "display:none" not in close_rule
