"""D10 follow-up contracts: modal band, perspective localization, row keyboard.

These are source-level tests on purpose, like the rest of the Quality Alerts UI
suite: the screen is plain ES modules with no build step and no JS test runner
in this repo, so the contract is asserted against the shipped source (the same
text the browser executes). The behaviour itself was exercised in a real
browser against an isolated copy of the database; see the D10 follow-up report.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CSS = ROOT / "static" / "css"
TABS = ROOT / "static" / "tabs"
DOCS = ROOT / "docs"


def _read(path):
    return path.read_text(encoding="utf-8")


def _bind_body(js):
    """The body of _bindRowKeyboard, so assertions cannot be satisfied by an
    unrelated part of the file."""
    start = js.index("function _bindRowKeyboard(body)")
    end = js.index("\n}", start)
    return js[start:end]


# ── 1. Modal shows the EFFECTIVE band ───────────────────────────────────────

def test_detail_modal_renders_effective_severity_and_explains_the_cap():
    """The modal header shows the band the policy assigns now, not the stored one.

    ``severity``/``effective_severity`` are the cap-applied band every KPI and
    the list count; ``stored_severity`` is the pre-cap value on the row. Showing
    the stored band in the modal would contradict the row that opened it.
    """
    js = _read(JS / "quality-alerts.js")
    assert "esc(_severityLabel(a.effective_severity || a.severity))" in js, \
        "the modal header must prefer the effective band"
    assert "_severityLabel(a.stored_severity)" not in js, \
        "stored severity must never stand in for the effective band"
    # The cap explanation stays: a difference is disclosed, not hidden.
    assert "_cappedBadge(a.severity_cap)" in js
    # The contract that defines both names is documented.
    contract = _read(DOCS / "QUALITY-ALERTS-SEVERITY-CONTRACT.md")
    assert "effective_severity" in contract and "stored_severity" in contract


# ── 2. Perspective labels follow the language ───────────────────────────────

_PERSPECTIVE_LABELS = (
    "Hospital history",
    "Similar hospitals (type)",
    "Ownership peers",
    "Facility-type peers",
    "Regional peers (governorate)",
    "All hospitals",
)


def test_perspective_chips_are_rebuilt_from_one_vocabulary():
    """Label and count live in separate nodes, and the label is re-translated.

    The regression: the chip count was appended into the label's own text node,
    and ``translateDOM`` only swaps a node whose ENTIRE text is a dictionary
    key — so an Arabic chip could never become English again on a live switch.
    """
    js = _read(JS / "quality-alerts.js")
    assert "data-label=\"' + esc(p.label || '')" in js, \
        "the canonical label must travel on the chip"
    assert '<span class="qa-chip-label">' in js
    assert "_perspectiveLabel(btn.getAttribute('data-label'), key)" in js, \
        "chip labels must be rebuilt through the one vocabulary helper"
    assert "qa-chip-count" in js and "countEl.textContent = ' (' + count + ')'" in js, \
        "the count must be its own node"
    # The old whole-node rewrite is gone.
    assert "btn.textContent = count === undefined ? base" not in js


def test_language_switch_rebuilds_perspective_chips_without_a_reload():
    """The language event re-renders the chips and the table scope in place."""
    js = _read(JS / "quality-alerts.js")
    assert "window.addEventListener('dhis:lang'" in js
    handler = js[js.index("window.addEventListener('dhis:lang'"):]
    handler = handler[:handler.index("});") + 3]
    assert "_renderPerspectiveChips(_state.meta.perspectives" in handler, \
        "chips must be re-rendered on a language change"
    assert "_updateChipCounts(_state.summary)" in handler
    assert "_renderTable()" in handler
    # i18n announces the change it already applies.
    i18n = _read(JS / "i18n.js")
    assert "new CustomEvent('dhis:lang'" in i18n


def test_every_perspective_label_has_an_arabic_entry():
    """Both directions come from one dictionary: EN label -> Arabic value."""
    i18n = _read(JS / "i18n.js")
    for label in _PERSPECTIVE_LABELS:
        match = re.search(r"'%s': '([^']+)'" % re.escape(label), i18n)
        assert match, f"missing Arabic label for {label!r}"
        assert re.search(r"[\u0600-\u06FF]", match.group(1)), \
            f"{label!r} is not translated to Arabic: {match.group(1)!r}"
    # English mode returns the key unchanged, so no Arabic can leak.
    assert "if (currentLang === 'ar' && translations[text]) return translations[text];" in i18n


def test_perspective_labels_are_not_hardcoded_in_the_screen():
    """One dictionary, not a second copy of the translations in the screen."""
    js = _read(JS / "quality-alerts.js")
    for arabic in ("مستشفيات مشابهة (النوع)", "نظراء الملكية", "نظراء المحافظة"):
        assert arabic not in js, \
            f"{arabic!r} must live in i18n.js only, not in the screen module"


# ── 3. Issue rows are reachable and operable by keyboard ────────────────────

def test_issue_rows_are_focusable_without_faking_a_role():
    """Rows join the tab order and keep their table semantics.

    ``role="button"`` on a ``<tr>`` would take the row out of the table for a
    screen reader, which is worse than no affordance at all.
    """
    js = _read(JS / "quality-alerts.js")
    assert "'<tr class=\"qa-issue-row\" tabindex=\"0\" onclick=\"openQualityAlert('" in js
    assert '<tr class="qa-issue-row" tabindex="0" role=' not in js
    assert 'role="button"' not in js


def test_enter_and_space_activate_a_row_exactly_once():
    """One delegated listener replays the row's own click, never a second path."""
    js = _read(JS / "quality-alerts.js")
    body = _bind_body(js)
    assert "e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar'" in body
    assert "row.click();" in body
    assert "openQualityAlert(" not in body, \
        "the key handler must replay the row click, not open the modal itself"
    # A held key must not reopen the modal, and a control inside a row keeps
    # its own keys.
    assert "e.repeat" in body
    assert "row !== e.target" in body
    assert "e.preventDefault();" in body


def test_row_keyboard_listener_is_bound_once():
    """Rows are rebuilt on every load; a per-row listener would stack."""
    js = _read(JS / "quality-alerts.js")
    assert "let _rowKeyboardBound = false;" in js
    assert "if (_rowKeyboardBound || !body) return;" in js
    assert "_rowKeyboardBound = true;" in js
    assert "    _bindRowKeyboard(body);" in js


def test_focused_row_has_a_visible_indicator():
    """A focusable row with no visible ring is unusable with a keyboard."""
    css = _read(CSS / "styles.css")
    assert ".qa-issue-row:focus," in css, "the ring must not depend on :focus-visible alone"
    rule = css[css.index(".qa-issue-row:focus,"):]
    rule = rule[:rule.index("}")]
    assert "outline" in rule
    assert "outline-offset" in rule


def test_row_markup_uses_no_direction_dependent_styling():
    """RTL must come from the document direction, not from the row markup."""
    js = _read(JS / "quality-alerts.js")
    assert "qa-issue-row\" tabindex=\"0\" onclick=\"openQualityAlert(" in js
    assert "margin-left" not in _read(CSS / "styles.css").split(".qa-issue-row:focus-visible")[1]
