"""Step 6D — Explain UI repair: wrapping, readable labels, no duplicate prose.

The JavaScript half executes the REAL helpers extracted from the shipped
``static/js/explain.js`` in node (the repository's static-UI convention), so a
dropped helper or an untranslated identifier fails here instead of in the
browser.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

EXPLAIN_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "explain.js"
I18N_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "i18n.js"

LONG_VALUE = ("Quality Alerts reports VERY_HIGH under \"Ownership peers\" (n=6), "
              "a narrower stratified comparison; the all-hospital baseline "
              "classifies the row HISTORICAL_ANOMALY at HIGH.")
SCOPE_EN = ("Only qualifying top-band peer perspectives are shown as cards. "
            "Other perspectives may appear in the cross-check list.")


def _src():
    return EXPLAIN_JS.read_text(encoding="utf-8")


def _function_source(name):
    src = _src()
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


def _run(expr):
    code = ("globalThis.__ = function (s) { return s; };\n"
            + _function_source("_codeLabel") + "\n"
            + _function_source("_alreadyShown") + "\n"
            + _function_source("_humanizeCodes") + "\n"
            + "console.log(JSON.stringify(" + expr + "));\n")
    return json.loads(_node(code))


def _render_peer(cross_check, ar_labels=None):
    """Render the real peer block; ``ar_labels`` switches the fake ``__`` to AR."""
    ar = dict(ar_labels or {})
    prelude = (
        "const AR = " + json.dumps(ar) + ";\n"
        "globalThis.__ = function (s) { return AR[s] || s; };\n"
        "globalThis.esc = function (s) { return String(s); };\n"
        "globalThis._sectionTitle = function (t) { return '[' + t + ']'; };\n"
    )
    code = (prelude
            + _function_source("_codeLabel") + "\n"
            + _function_source("_peerPerspectiveReason") + "\n"
            + _function_source("_peerScaleLine") + "\n"
            + _function_source("_renderPeerPerspectives") + "\n"
            + "const cc = " + json.dumps(cross_check) + ";\n"
            + "console.log(JSON.stringify(_renderPeerPerspectives(cc)));\n")
    return json.loads(_node(code))


def _ar_for(key):
    """The Arabic value stored under ``key`` in the shipped dictionary."""
    i18n = I18N_JS.read_text(encoding="utf-8")
    needle = "'" + key.replace("\\", "\\\\").replace("'", "\\'") + "':"
    idx = i18n.find(needle)
    if idx == -1:
        return None
    match = re.match(r"\s*'([^']*)'", i18n[idx + len(needle):])
    return match.group(1) if match else None


def _card(**overrides):
    card = {
        "alert_id": 6243, "perspective": "ownership",
        "label": "Ownership peers", "verdict": "undecided",
        "reason_code": "SCALES_DISAGREE", "peer_count": 6, "current": 13.0,
        "threshold": 2.5,
        "mad": {"value": 27.0, "band": "VERY_HIGH", "usable": True},
        "iqr": {"value": 67.0, "band": "MODERATE", "usable": True},
        "scales_supporting": None,
        "group_comparability_status": "not_verified",
        "zero_share": 0.0, "zero_share_warning": False,
    }
    card.update(overrides)
    return card


# ── A. Cross-check rows wrap; nothing is clipped ───────────────────────────

def test_kv_rows_lets_both_columns_shrink_and_wrap():
    block = _function_source("_kvRows")
    # flex-shrink:0 made the sentence claim its max-content width and pushed
    # the whole popup sideways.
    assert "flex-shrink:0;" not in block
    assert block.count("min-width:0") >= 2
    assert "overflow-wrap:anywhere" in block
    assert "white-space:nowrap" not in block
    assert "text-overflow" not in block
    assert "overflow:hidden" not in block


def test_kv_rows_renders_the_whole_long_value():
    code = ("globalThis.esc = function (s) { return String(s); };\n"
            + _function_source("_kvRows")
            + "\nconst h = _kvRows([{input: 'Ownership peers (n=6)', value: "
            + json.dumps(LONG_VALUE) + "}]);\n"
            + "console.log(JSON.stringify(h));\n")
    html = json.loads(_node(code))
    assert LONG_VALUE in html
    assert "ellipsis" not in html
    assert "overflow:hidden" not in html


def test_kv_rows_still_renders_a_short_numeric_row():
    code = ("globalThis.esc = function (s) { return String(s); };\n"
            + _function_source("_kvRows")
            + "\nconsole.log(JSON.stringify(_kvRows([{input: 'peer_count', "
              "value: 6}, {input: 'missing', value: null}])));\n")
    html = json.loads(_node(code))
    assert "peer_count" in html and ">6<" in html
    assert ">--<" in html


# ── B. Stored identifiers become words ─────────────────────────────────────

KNOWN_EN = {
    "VERY_HIGH": "Very high",
    "MODERATE": "Moderate",
    "NONE": "None",
    "not_verified": "not verified",
    "catalog_only": "catalog only",
    "verified": "verified",
}


def test_known_identifiers_render_as_words_not_codes():
    codes = list(KNOWN_EN)
    got = _run("[" + ",".join(json.dumps(c) for c in codes) + "].map(_codeLabel)")
    assert got == [KNOWN_EN[c] for c in codes]


def test_unknown_identifier_falls_back_to_a_readable_code():
    # Never an empty cell, and never a label the code might not mean.
    assert _run("_codeLabel('SOME_FUTURE_REASON')") == "Some future reason"
    assert _run("_codeLabel(null)") == "unavailable"
    assert _run("_codeLabel('')") == "unavailable"
    assert _run("String(_codeLabel(undefined))") == "unavailable"


AR_REQUIRED = [
    "VERY_HIGH", "MODERATE", "NONE",
    "agree", "differs", "differs_by_perspective", "no_stored_alert",
    "BOTH_SCALES_SUPPORT", "ONLY_AVAILABLE_SCALE_SUPPORTS",
    "SCALES_DISAGREE", "ONLY_AVAILABLE_SCALE_REFUSES",
    "DEFINITION_NOT_ESTABLISHABLE", "NO_ROBUST_SCALE",
    "BOTH_USABLE_SCALES_REFUSE", "NO_STORED_PEER_VALUES",
    "INSUFFICIENT_PEER_VALUES", "CURRENT_VALUE_MISSING",
    "not_verified", "catalog_only", "verified",
    "Historical baseline", "Patient volume", "Peer comparison",
]


def test_every_shown_identifier_has_an_arabic_label():
    for code in AR_REQUIRED:
        value = _ar_for(code)
        assert value, f"missing Arabic label for {code!r}"
        assert re.search(r"[\u0600-\u06FF]", value), (code, value)


def test_route_and_cap_policy_sentences_are_translated():
    from app.engine.anomaly.layered import (
        TOP_BAND_ROUTE_POLICY,
        VERY_HIGH_ELIGIBILITY_POLICY,
    )
    for text in list(TOP_BAND_ROUTE_POLICY.values()) + [VERY_HIGH_ELIGIBILITY_POLICY]:
        value = _ar_for(text)
        assert value, f"missing Arabic policy for {text[:50]!r}..."
        assert re.search(r"[\u0600-\u06FF]", value)


def test_cross_check_policy_sentence_is_translated():
    text = ("Quality Alerts scores each labelled perspective (history, type, "
            "ownership, facility type, governorate, all hospitals); Outlier "
            "Diagnostics classifies against the single all-hospital detection "
            "baseline and its own-history baseline.")
    explain_py = (Path(__file__).resolve().parents[1]
                  / "app" / "engine" / "audit" / "explain.py")
    assert "classifies against the single all-hospital detection" in explain_py.read_text(
        encoding="utf-8")
    assert _ar_for(text), "cross-check policy sentence has no Arabic label"


def test_rendered_card_prints_no_raw_bands_reasons_or_statuses():
    html = _render_peer({"peer_perspectives": [_card()]})
    for raw in ("VERY_HIGH", "MODERATE", "SCALES_DISAGREE", "not_verified"):
        assert raw not in html, raw
    assert "Very high" in html and "Moderate" in html
    assert "Comparability: not verified" in html
    assert "Reason: Scales disagree" in html


def test_arabic_card_uses_the_dictionary_labels():
    html = _render_peer(
        {"peer_perspectives": [_card()]},
        ar_labels={
            "VERY_HIGH": "\u0645\u0631\u062a\u0641\u0639 \u062c\u062f\u064b\u0627",
            "SCALES_DISAGREE": "\u0645\u0642\u0627\u064a\u064a\u0633 \u0627\u0644\u062a\u0628\u0627\u064a\u0646 \u0645\u062a\u0639\u0627\u0631\u0636\u0629",
            "not_verified": "\u063a\u064a\u0631 \u0645\u064f\u062a\u062d\u0642\u0642",
        })
    assert "\u0645\u0631\u062a\u0641\u0639 \u062c\u062f\u064b\u0627" in html
    assert "VERY_HIGH" not in html
    assert "SCALES_DISAGREE" not in html
    assert "not_verified" not in html


# ── C. The cross-check paragraph is not printed twice ──────────────────────

def test_already_shown_normalises_whitespace_and_is_exact_otherwise():
    assert _run("_alreadyShown('Rule 3 fired.  Quality Alerts reports HIGH.', "
                "'Quality Alerts reports HIGH.')") is True
    assert _run("_alreadyShown('Rule 3 fired.', 'A different sentence.')") is False
    assert _run("_alreadyShown('', '')") is False


def test_cross_check_explanation_is_rendered_once():
    src = _src()
    assert "!_alreadyShown(p.why, cc.explanation)" in src
    assert "esc(cc.explanation || '')" not in src


# ── D. Perspective scope: list vs cards ────────────────────────────────────

def test_scope_sentence_is_rendered_in_the_peer_block():
    assert SCOPE_EN in _src()
    html = _render_peer({"peer_perspectives": [_card()]})
    assert SCOPE_EN in html


def test_scope_sentence_has_an_arabic_translation():
    value = _ar_for(SCOPE_EN)
    assert value and re.search(r"[\u0600-\u06FF]", value)


def test_cards_come_only_from_the_qualifying_peer_perspectives():
    """A 3-perspective cross-check still yields 2 cards, and says why."""
    cc = {"peer_perspectives": [_card(), _card(alert_id=6245,
                                                perspective="governorate",
                                                label="Regional peers (governorate)")]}
    html = _render_peer(cc)
    assert html.count("Alert #") == 2
    assert SCOPE_EN in html


def test_peer_block_does_not_select_or_merge_a_card():
    src = _func = _function_source("_renderPeerPerspectives")
    assert "rows.slice().sort(" in src
    assert "peer_perspectives" in src
    # No card is promoted to the block's verdict.
    assert "strongest" not in src


# ── E. Backend prose no longer leaks machine codes into the popup ──────────

def test_backend_prose_codes_are_made_readable_not_reinterpreted():
    prose = ("Out-of-facility deliveries 24 vs 10 previous (+140%) "
             "\u2014 HISTORICAL_ANOMALY (VERY_HIGH level)")
    assert _run("_humanizeCodes(" + json.dumps(prose) + ")") == (
        "Out-of-facility deliveries 24 vs 10 previous (+140%) "
        "\u2014 Historical anomaly (Very high level)")
    # An unseen code only loses its underscores; it keeps its own words.
    assert _run("_humanizeCodes('SOME_FUTURE_CODE raised')") == (
        "Some future code raised")
    # Lower-case stored values (the interpretation code) are just as machine-
    # facing as the upper-case ones.
    assert _run("_humanizeCodes('Stored interpretation: statistical_only')") == (
        "Stored interpretation: statistical only")
    # Ordinary prose is returned untouched.
    assert _run("_humanizeCodes('No stored alert for this row.')") == (
        "No stored alert for this row.")
    assert _run("_humanizeCodes('')") == ""


def test_every_backend_prose_field_is_humanized_at_render_time():
    """Every prose field renders through _prose(), which localizes a
    registered template and otherwise keeps the original text with machine
    codes made readable (Step 6E)."""
    src = _src()
    for rendered in ("_prose(p.what || '')",
                     "_prose(p.why)",
                     "_prose(cc.explanation)",
                     "_prose(o.interpretation)",
                     "_prose(L.detail)",
                     "_prose(d.message)",
                     "_prose(r.note)",
                     "_humanizeCodes(__(policy), true)"):
        assert rendered in src, rendered
    # Unregistered prose still gets Step 6D's humanization.
    assert "return localized === null ? _humanizeCodes(text) : localized;" in src
