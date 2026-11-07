"""Step 10D-6e — Quality Alerts KPI cards read comparison IDENTITY.

The renderer half executes the REAL ``_comparisonBreakdownHtml`` helper from
``static/js/quality-alerts.js`` in node, as the repository's static-UI tests do.
Pinned here:

* the five categories are the server's identity fields and partition
  Very High only (``70 + 225 + 59 + 0 + 0 = 354`` on the 10D-4/5 snapshot);
* ``Very High only + Mixed severity`` reconciles with ``Very High issues``;
* a failed balance prints both stored figures and is never repaired;
* a missing field renders as a dash, never as a measured zero;
* relationship subcategories stay secondary detail and never inflate a total;
* the legacy perspective-label count is visible, labelled legacy, and is not
  the headline number;
* every sentence the block prints exists in Arabic with no English words.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js" / "quality-alerts.js"
I18N_JS = ROOT / "static" / "js" / "i18n.js"
FRAGMENT = ROOT / "static" / "tabs" / "quality-alerts.html"

HELPERS = ("_countOrNull", "_countText", "_fillSentence", "_breakdownNote",
           "_tipHelp", "_breakdownSentence", "_breakdownCell",
           "_relationshipHtml", "_comparisonBreakdownHtml")
CONSTANTS = ("_COMPARISON_CATEGORY_ROWS", "_RELATIONSHIP_ROWS")

SNAPSHOT = {
    "total_issues": 2658,
    "very_high_issues": 801,
    "very_high_only_issues": 354,
    "mixed_severity_issues": 447,
    "very_high_multiple_peer_issues": 70,
    "very_high_single_peer_issues": 225,
    "very_high_temporal_only_issues": 59,
    "very_high_unknown_identity_issues": 0,
    "very_high_invalid_evidence_issues": 0,
    "very_high_only_corroborated_issues": 71,
    "very_high_comparison_shadow": {
        "multiple_peer": 70,
        "multiple_peer_by_relationship": {
            "all_disjoint": 0, "nested_only": 55,
            "overlapping_only": 2, "mixed_relationships": 13,
        },
    },
}


def _js():
    return JS.read_text(encoding="utf-8")


def _declaration_source(name):
    src = _js()
    start = src.index("const " + name + " = ")
    end = src.index("\n];", start) + len("\n];")
    return src[start:end]


def _function_source(name):
    src = _js()
    start = src.index("function " + name + "(")
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(f"unterminated {name}")


def _node(code):
    out = subprocess.run(["node", "-e", code], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def _render(summary, lang="en", labels=None, state=None):
    dictionary = dict(labels or {})
    prelude = (
        "const AR = " + json.dumps(dictionary) + ";\n"
        "const currentLang = " + json.dumps(lang) + ";\n"
        "globalThis.__ = function (s) { return (currentLang === 'ar' && AR[s]) || s; };\n"
        "globalThis.esc = function (s) { return String(s); };\n"
        "let _tipSeq = 0;\n"
        "let _state = " + json.dumps(state or {"comparisonCategory": None})
        + ";\n"
    )
    code = (prelude
            + "\n".join(_declaration_source(name) for name in CONSTANTS)
            + "\n"
            + "\n".join(_function_source(name) for name in HELPERS)
            + "\nconsole.log(JSON.stringify(_comparisonBreakdownHtml("
            + json.dumps(summary) + ")));\n")
    return json.loads(_node(code))


def _ar_for(key):
    i18n = I18N_JS.read_text(encoding="utf-8")
    needle = "'" + key.replace("\\", "\\\\").replace("'", "\\'") + "':"
    idx = i18n.find(needle)
    if idx == -1:
        return None
    match = re.match(r"\s*'([^']*)'", i18n[idx + len(needle):])
    return match.group(1) if match else None


# ── Card structure ──────────────────────────────────────────────────────────

def test_overall_risk_cards_name_their_units():
    frag = FRAGMENT.read_text(encoding="utf-8")
    for element, label in (("qaKpiTotal", "Total issues"),
                           ("qaKpiVeryHighIssues", "Very High issues"),
                           ("qaKpiMixed", "Mixed severity"),
                           ("qaKpiVeryHighOnly", "Very High only")):
        assert f'id="{element}"' in frag, element
        assert f'data-i18n="{label}"' in frag, label
    # The identity breakdown lives on its own panel, fed by the summary.
    assert 'id="qaComparisonBreakdown"' in frag
    assert "Very High only · evidence breakdown" in frag


def test_breakdown_reads_only_the_published_identity_fields():
    src = _js()
    for field in ("very_high_multiple_peer_issues",
                  "very_high_single_peer_issues",
                  "very_high_temporal_only_issues",
                  "very_high_unknown_identity_issues",
                  "very_high_invalid_evidence_issues",
                  "very_high_only_issues",
                  "very_high_issues",
                  "mixed_severity_issues",
                  "very_high_comparison_shadow"):
        assert field in src, field
    # Comparison identity is consumed, never derived, in JavaScript.
    for forbidden in ("peer_ids", "identity_hash", "sha256", "pairwise"):
        assert forbidden not in src, forbidden


def test_relationship_counts_are_not_part_of_any_issue_total():
    src = _js()
    renderer = src[src.index("function _comparisonBreakdownHtml("):]
    renderer = renderer[:renderer.index("function _renderComparisonBreakdown(")]
    # The partition sum is built from the five category cells only.
    assert "categories.reduce" in renderer
    assert "by_relationship" not in renderer.split("_relationshipHtml(")[0]
    assert "very_high_comparison_shadow" in renderer
    assert "are not additional issues" in src


# ── Rendering: partition and reconciliation ─────────────────────────────────

def test_snapshot_partition_renders_the_stored_numbers():
    html = _render(SNAPSHOT)
    for value in ("70", "225", "59"):
        assert value in html, value
    assert "70 + 225 + 59 + 0 + 0 = 354" in html
    assert "Very High only + Mixed severity = Very High issues" in html
    assert re.search(r'dir="ltr"[^>]*>354 \+ 447 = 801<', html),\
        "the balance figures must sit in their own LTR line"
    # No discrepancy wording when every balance holds.
    assert "nothing was adjusted" not in html


def test_category_order_and_labels_are_the_exclusive_five():
    html = _render(SNAPSHOT)
    order = [html.index(text) for text in
             ("Multiple peer comparisons", "Single peer comparison",
              "Temporal-only", "Unknown comparison identity", "Invalid evidence")]
    assert order == sorted(order)
    for element in ("qaKpiMultiplePeer", "qaKpiSinglePeer", "qaKpiTemporalOnly",
                    "qaKpiUnknownIdentity", "qaKpiInvalidEvidence"):
        assert f'id="{element}"' in html, element


def test_relationship_detail_is_secondary_and_reconciles_to_multiple_peer():
    html = _render(SNAPSHOT)
    assert "Comparison relationships (inside multiple peer comparisons)" in html
    assert "Secondary detail — these are not additional issues" in html
    for label in ("All disjoint", "Nested only", "Overlapping only",
                  "Mixed relationships"):
        assert label in html, label
    # 0 + 55 + 2 + 13 = 70, so no relationship discrepancy is printed.
    assert "Relationship counts add up to" not in html
    # And the relationship numbers never appear in the issue equation.
    balance = html[html.index(">354 + 447 = 801<"):html.index("Comparison relationships")]
    assert "55" not in balance and "13" not in balance


def test_failed_partition_balance_is_reported_not_repaired():
    broken = dict(SNAPSHOT, very_high_single_peer_issues=226)  # 355 vs 354
    html = _render(broken)
    assert "The categories add up to 355 but Very High only is 354" in html
    assert "(difference 1)" in html
    assert "nothing was adjusted" in html
    # Both stored figures survive untouched.
    assert "226" in html and "354" in html
    assert "70 + 226 + 59 + 0 + 0 = 354" in html


def test_failed_very_high_balance_is_reported_not_repaired():
    broken = dict(SNAPSHOT, very_high_issues=800)  # 354 + 447 = 801
    html = _render(broken)
    assert "does not match Very High issues (800)" in html
    assert "difference 1" in html
    assert "nothing was adjusted" in html


def test_failed_relationship_balance_is_reported_not_repaired():
    broken = json.loads(json.dumps(SNAPSHOT))
    broken["very_high_comparison_shadow"]["multiple_peer_by_relationship"][
        "mixed_relationships"] = 12  # 0 + 55 + 2 + 12 = 69
    html = _render(broken)
    assert "Relationship counts add up to 69" in html
    assert "Multiple peer comparisons is 70" in html
    assert "difference 1" in html


def test_missing_field_is_a_dash_never_a_zero():
    broken = dict(SNAPSHOT, very_high_temporal_only_issues=None)
    html = _render(broken)
    assert "Comparison evidence not available for this scope" in html
    # No equation is invented from the four fields that did arrive.
    assert "= 354" not in html
    assert 'id="qaKpiTemporalOnly"' in html


def test_missing_very_high_issues_is_a_dash():
    html = _render({"very_high_only_issues": 0, "mixed_severity_issues": 0,
                    "very_high_multiple_peer_issues": 0,
                    "very_high_single_peer_issues": 0,
                    "very_high_temporal_only_issues": 0,
                    "very_high_unknown_identity_issues": 0,
                    "very_high_invalid_evidence_issues": 0})
    assert "0 + 0 + 0 + 0 + 0 = 0" in html
    assert "does not match Very High issues" not in html


def test_empty_scope_renders_without_fabricated_counts():
    html = _render({})
    assert "Comparison evidence not available for this scope" in html
    assert "0 + 0" not in html


# ── Legacy diagnostic ───────────────────────────────────────────────────────

def test_legacy_label_count_is_visible_and_labelled():
    frag = FRAGMENT.read_text(encoding="utf-8")
    assert "Legacy diagnostic (perspective labels)" in frag
    assert "counts perspective labels, not peer comparison groups" in frag
    # Still clickable: the existing `corroborated` scope keeps working.
    line = next(l for l in frag.splitlines() if 'id="qaCardCorroborated"' in l)
    assert "qualityAlertsToggleVeryHighScope('corroborated')" in line
    assert 'role="button"' in line and 'tabindex="0"' in line
    # The legacy number has its own element, outside the identity breakdown.
    assert 'id="qaKpiCorroborated"' in frag
    src = _js()
    renderer = src[src.index("function _comparisonBreakdownHtml("):]
    renderer = renderer[:renderer.index("function _renderComparisonBreakdown(")]
    assert "very_high_only_corroborated_issues" not in renderer,         "the legacy count must not feed the identity breakdown"


def test_filters_and_scope_are_unchanged():
    src = _js()
    assert "p.set('very_high_scope', _state.vhScope)" in src
    assert "_state.vhScope = _state.vhScope === scope ? null : scope;" in src
    api = (ROOT / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")
    # D7: the scope moved onto the shared validator so an empty value means
    # "no scope" like every other optional filter; unknown values stay 422.
    assert "def _very_high_scope_filter(" in api
    assert 'VERY_HIGH_SCOPES = ("only", "mixed", "corroborated")' in api


# ── The breakdown cells are filters ─────────────────────────────────────────

def test_every_measured_cell_filters_by_its_own_category():
    html = _render(SNAPSHOT)
    for category in ("multiple_peer", "single_peer", "temporal_only",
                     "unknown_identity", "invalid_evidence"):
        assert 'data-category="' + category + '"' in html
    # One handler per cell: the native <button> supplies Enter/Space itself, so
    # there is no second inline keydown path to keep in sync.
    assert html.count(
        "qualityAlertsToggleComparisonCategory(this.dataset.category)") == 5
    assert html.count('<button type="button"') == 5
    assert 'onkeydown' not in html
    assert html.count('aria-pressed="false"') == 5


def test_an_unmeasured_cell_is_not_a_button():
    broken = dict(SNAPSHOT, very_high_temporal_only_issues=None)
    html = _render(broken)
    assert 'data-category="temporal_only"' not in html
    assert html.count('<button type="button"') == 4
    assert 'role="button"' not in html


def test_the_active_cell_marks_itself_and_offers_to_clear():
    html = _render(SNAPSHOT, state={"comparisonCategory": "single_peer"})
    assert html.count('qa-breakdown-cell is-active') == 1
    assert 'aria-pressed="true"' in html
    assert "click the cell again to clear" in html


def test_the_screen_sends_the_chosen_category_and_the_fragment_says_so():
    src = _js()
    assert "p.set('comparison_category', _state.comparisonCategory)" in src
    assert "export function qualityAlertsToggleComparisonCategory" in src
    assert "_state.comparisonCategory === category ? null : category" in src
    # The screen's inline handlers only see globals: the loader must export it.
    app = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "_bind(mod, 'qualityAlertsToggleComparisonCategory');" in app
    frag = FRAGMENT.read_text(encoding="utf-8")
    assert ("Click a category to filter the list; click it again to clear"
            in frag)
    assert "def _comparison_category_filter(" in (
        ROOT / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")


# ── Localization ────────────────────────────────────────────────────────────

def test_every_printed_label_has_arabic_without_english_words():
    src = _js()
    block = src[src.index("const _COMPARISON_CATEGORY_ROWS"):]
    block = block[:block.index("function _renderComparisonBreakdown(")]
    keys = set(re.findall(r"__\('((?:[^'\\]|\\.)+)'\)", block))
    keys |= set(re.findall(r"_fillSentence\(\s*'((?:[^'\\]|\\.)+)'", block))
    keys |= set(re.findall(r"^\s*'([^']+)',?$", block, re.M))
    # "Temporal-only" is a label without a space; nothing here is CSS.
    keys = {k for k in keys if re.search(r"[A-Za-z]", k)}

    missing = sorted(k for k in keys if not _ar_for(k))
    assert not missing, f"missing Arabic: {missing}"

    latin = []
    for key in keys:
        value = _ar_for(key) or ""
        stripped = re.sub(r"\{[a-z]+\}", "", value)
        if re.search(r"[A-Za-z]{2,}", stripped):
            latin.append((key, value))
    assert not latin, f"English words inside Arabic: {latin}"

    placeholders = [(k, set(re.findall(r"\{([a-z]+)\}", k)),
                     set(re.findall(r"\{([a-z]+)\}", _ar_for(k) or "")))
                    for k in keys]
    mismatched = [p for p in placeholders if p[1] != p[2]]
    assert not mismatched, f"placeholder mismatch: {mismatched}"


def _quoted_strings(block):
    """Every single- or double-quoted literal in ``block``.

    A naive ``'`` scan desynchronises on an apostrophe inside a double-quoted
    tooltip ("the hospital's own earlier months"), so each quote is matched
    against its own kind, escapes included.
    """
    found = set()
    i = 0
    while i < len(block):
        ch = block[i]
        if ch not in ("'", '"'):
            i += 1
            continue
        j = i + 1
        while j < len(block):
            if block[j] == "\\":
                j += 2
                continue
            if block[j] == ch:
                break
            j += 1
        found.add(block[i + 1:j])
        i = j + 1
    return found


def test_arabic_render_keeps_no_english_labels():
    src = _js()
    block = src[src.index("const _COMPARISON_CATEGORY_ROWS"):]
    block = block[:block.index("function _renderComparisonBreakdown(")]
    dictionary = {}
    for key in _quoted_strings(block):
        if not re.search(r"[A-Za-z]", key):
            continue
        value = _ar_for(key)
        if value:
            dictionary[key] = value
    html = _render(SNAPSHOT, lang="ar", labels=dictionary)
    for english in ("Multiple peer comparisons", "Single peer comparison",
                    "Temporal-only", "Comparison relationships",
                    "Secondary detail", "All disjoint", "Nested only"):
        assert english not in html, english
    assert "مقارنات متعددة مع النظراء" in html


# ── 10D-8: equation split, desktop grid, accessible tooltips ────────────────

def _arabic_dictionary():
    src = _js()
    block = src[src.index("const _COMPARISON_CATEGORY_ROWS"):]
    block = block[:block.index("function _renderComparisonBreakdown(")]
    out = {}
    for key in _quoted_strings(block):
        if not re.search(r"[A-Za-z]", key):
            continue
        value = _ar_for(key)
        if value:
            out[key] = value
    return out


def test_arabic_balance_sentence_is_rtl_and_equation_ltr():
    html = _render(SNAPSHOT, lang="ar", labels=_arabic_dictionary())
    # The sentence carries no figures, so it stays a plain RTL sentence.
    assert "عالية جداً فقط + شدة مختلطة = مشكلات عالية جداً" in html
    # The figures are their own node, forced LTR: 354 + 447 = 801, never 801 = …
    assert re.search(r'dir="ltr"[^>]*>354 \+ 447 = 801<', html)
    assert re.search(r'dir="ltr"[^>]*>70 \+ 225 \+ 59 \+ 0 \+ 0 = 354<', html)
    # No Arabic word is inside either equation node.
    for eq in re.findall(r'dir="ltr"[^>]*>([^<]*)<', html):
        assert not re.search(r"[؀-ۿ]", eq), eq


def test_tooltips_use_describedby_and_never_title():
    frag = FRAGMENT.read_text(encoding="utf-8")
    rendered = _render(SNAPSHOT)
    for name, doc in (("fragment", frag), ("renderer", rendered)):
        assert ' title="' not in doc, name + " still relies on title="
        ids = re.findall(r'aria-describedby="([^"]+)"', doc)
        assert ids, name + " has no described-by tooltips"
        for tip_id in ids:
            assert 'id="%s"' % tip_id in doc, (name, tip_id)
            at = doc.index('id="%s"' % tip_id)
            assert 'role="tooltip"' in doc[at:at + 160], (name, tip_id)


def test_tooltip_hosts_are_focusable():
    frag = FRAGMENT.read_text(encoding="utf-8")
    rendered = _render(SNAPSHOT)
    for name, doc in (("fragment", frag), ("renderer", rendered)):
        tags = re.findall(r'<[^>]*aria-describedby="[^"]+"[^>]*>', doc)
        assert len(tags) >= 3, name
        for tag in tags:
            assert 'tabindex="0"' in tag, (name, tag[:120])


def test_tooltip_reveal_css_covers_hover_focus_and_touch():
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".qa-tip:hover > .qa-tip-help" in css
    assert ".qa-tip:focus > .qa-tip-help" in css
    assert "visibility:hidden" in css


def test_no_duplicate_tooltip_announcement():
    src = _js()
    assert "el.title = hint" not in src
    assert "aria-label', hint" not in src
    assert "help.textContent = hint" in src


def test_desktop_kpi_grid_is_a_balanced_four_by_two():
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    frag = FRAGMENT.read_text(encoding="utf-8")
    assert 'class="qa-kpis"' in frag
    assert "grid-template-columns:repeat(auto-fit,minmax(150px,1fr))" in css
    assert "@media (min-width:1100px)" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css


def test_no_element_carries_two_class_attributes():
    """A duplicate class= attribute is silently dropped by HTML parsers.

    The Mixed / Very High only cards had class="kpi-card" and class="qa-tip"
    on the same div, so the browser kept only the first: .qa-tip never
    applied, the tooltip lost its positioned parent and the page grew 88px
    wider than a 390px viewport.
    """
    frag = FRAGMENT.read_text(encoding="utf-8")
    offenders = [tag for tag in re.findall(r"<[a-z][^>]*>", frag)
                 if tag.count('class="') > 1]
    assert not offenders, offenders
