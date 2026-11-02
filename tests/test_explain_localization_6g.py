"""Step 6G — Explain localization repair (partial paragraphs, interpretation).

The Step 6F audit found that a COMPOSED backend paragraph was localized only
until its first unregistered sentence: the remaining sentences stayed English
and, worse, carried raw machine codes (``peer comparison also VERY_HIGH``) into
the Arabic popup. The repair localizes each sentence and each ``; ``-separated
clause of that sentence on its own, and makes the identifiers of an unmatched
sentence readable instead of copying them into the prose.

These tests drive the REAL ``static/js/explain-prose.js`` and the REAL render
helpers extracted from ``static/js/explain.js`` through node, so a dropped
template, a lost number or a re-leaked code fails here rather than in the
browser. Every non-ASCII character is written as an escape so the file cannot be
corrupted by an editor or a console encoding.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "explain-prose.js"
EXPLAIN = ROOT / "static" / "js" / "explain.js"
RUNNER_PATH = ROOT / "tests" / "_tmp_prose_runner_6g.mjs"
RENDER_PATH = ROOT / "tests" / "_tmp_render_runner_6g.mjs"

# Mirrors the Arabic values of ``_codeLabel`` in the popup.
AR_LABELS = {
    "VERY_HIGH": "\u0645\u0631\u062a\u0641\u0639 \u062c\u062f\u064b\u0627",
    "HIGH": "\u0645\u0631\u062a\u0641\u0639",
    "MODERATE": "\u0645\u062a\u0648\u0633\u0637",
    "LOW": "\u0645\u0646\u062e\u0641\u0636",
    "NONE": "\u0644\u0627 \u0634\u064a\u0621",
    "HISTORICAL_ANOMALY": "\u0634\u0630\u0648\u0630 \u062a\u0627\u0631\u064a\u062e\u064a",
    "RAW_VALUE_ANOMALY": "\u0634\u0630\u0648\u0630 \u0627\u0644\u0642\u064a\u0645\u0629 \u0627\u0644\u062e\u0627\u0645",
    "Completeness": "\u0627\u0644\u0627\u0643\u062a\u0645\u0627\u0644",
}

RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.argv[2]).href);
const payload = JSON.parse(readFileSync(0, 'utf8'));
const AR = JSON.parse(process.argv[3]);

// The renderer passes ``_humanizeCodes`` in: a machine code inside an unmatched
// sentence becomes readable words, and nothing else in that sentence changes.
const humanize = function (t) {
  return String(t).replace(/\\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\\b/g, function (code) {
    const words = code.replace(/_/g, ' ').toLowerCase();
    return /^[A-Z0-9_]+$/.test(code)
      ? words.charAt(0).toUpperCase() + words.slice(1)
      : words;
  });
};

const out = payload.cases.map(function (c) {
  const lang = c.lang || 'en';
  const label = lang === 'en'
    ? function (code) { return code; }
    : function (code) { return AR[code] || code; };
  return mod.localizeProse(c.text, lang, label, c.humanize ? humanize : undefined);
});
process.stdout.write(JSON.stringify(out));
"""

RENDER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.argv[2]).href);
const payload = JSON.parse(readFileSync(0, 'utf8'));
const AR = JSON.parse(process.argv[3]);
const src = readFileSync(process.argv[4], 'utf8');

function extract(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start === -1) throw new Error('missing ' + name);
  const open = src.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (!depth) return src.slice(start, i + 1);
    }
  }
  throw new Error('unterminated ' + name);
}

const body = [
  extract('_codeLabel'),
  extract('_humanizeCodes'),
  extract('_layerValue'),
  extract('_templateOnly'),
  'return { _codeLabel: _codeLabel, _layerValue: _layerValue, _templateOnly: _templateOnly };',
].join('\\n');

const build = new Function('localizeProse', '__', 'currentLang', body);
// EN uses the same identity dictionary the app uses in English mode.
const lookup = payload.lang === 'en'
  ? function (key) { return key; }
  : function (key) { return AR[key] || key; };
const helpers = build(mod.localizeProse, lookup, payload.lang || 'ar');

const out = payload.calls.map(function (call) {
  const value = helpers[call.fn].apply(null, call.args);
  return value === undefined ? null : String(value);
});
process.stdout.write(JSON.stringify(out));
"""


def _node(script, payload):
    proc = subprocess.run(
        ["node", str(script), str(MODULE), json.dumps(AR_LABELS), str(EXPLAIN)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run(cases):
    RUNNER_PATH.write_text(RUNNER, encoding="utf-8")
    try:
        return _node(RUNNER_PATH, {"cases": cases})
    finally:
        RUNNER_PATH.unlink(missing_ok=True)


def _render(calls, lang="ar"):
    RENDER_PATH.write_text(RENDER, encoding="utf-8")
    try:
        return _node(RENDER_PATH, {"calls": calls, "lang": lang})
    finally:
        RENDER_PATH.unlink(missing_ok=True)


EM = "\u2014"
ARROW = "\u2192"
AR = re.compile("[\u0600-\u06FF]")
SEMI_AR = "\u061b"

# Real backend sentences (app/engine/anomaly/classify.py::build_interpretation).
HIST_PRIMARY = (
    f"Deviation from this hospital's own recent baseline. "
    f"Unplanned admission to ICU 10 vs 4 (+150% vs previous month); "
    f"+218% above baseline mean 3.14286; peer average 0.7 across 9 hospitals; "
    f"peer comparison also VERY_HIGH."
)
NONE_PRIMARY = (
    f"No layer exceeded its threshold. "
    f"Hypertensive disorders 0 vs 1 (-100% vs previous month); "
    f"+100% below baseline mean 0.714286; peer average 5.5 across 13 hospitals; "
    f"peer comparison NONE - peers do not share this deviation; "
    f"raw-value comparison has no spread (all values identical) - the deviation "
    f"cannot be graded, so the level is capped at HIGH."
)
PEER_ONLY = (
    f"Not enough history: needs at least 3 prior months, but the peer comparison "
    f"is significant - a peer deviation is confirmed while the hospital's own "
    f"baseline is not assessable. Unplanned admission to ICU 12 vs 12 previous "
    f"(0% vs previous month); peer comparison HIGH (score 1.00)."
)
DATA_ENTRY = (
    "All layers spike together while the denominator is stable - consistent with "
    "a data-entry error; verify source values before acting. Out-of-facility "
    "deliveries 90 vs 20 (+350% vs previous month); rate 90.0%; small "
    "denominator (2 < 5) - confidence lowered, level capped at LOW."
)
COMPOSITE_SCORE = (
    "1 raw-data problem(s) detected; 1 component(s) below target; "
    "weakest: Outlier score (87.6% vs 90% target)."
)
COMPOSITE_RULES = (
    "2 validation rule(s) failed (R001, R002) " + ARROW +
    " rule compliance 86.5%. No validation rule failed this month."
)
FORMULA_COUNT = "Unplanned admission to ICU = count of indicator 10.m"
FORMULA_PROPORTION = "Hemorrhage Proportion of SMM = (10.a) / (10) \u00d7 100"
UNKNOWN = "A future engine sentence no template knows about."
UNKNOWN_WITH_CODE = "A future clause mentions VERY_HIGH and HISTORICAL_ANOMALY."

NEW_SENTENCES = [
    "No layer exceeded its threshold.",
    "Deviation from this hospital's own recent baseline.",
    "Rate deviates from its recent pattern.",
    "Raw value deviates from its recent pattern.",
    HIST_PRIMARY,
    NONE_PRIMARY,
    PEER_ONLY,
    DATA_ENTRY,
    COMPOSITE_SCORE,
    COMPOSITE_RULES,
    FORMULA_COUNT,
    "peer comparison MODERATE (score 0.60) is below the HIGH threshold - not "
    "enough to classify without history",
    "peer comparison NONE (score 0.40) - no peer deviation",
    "peer comparison unavailable - no independent peer evidence either way",
    "own history NONE - no deviation from its own baseline",
    "own history not assessable - the peer comparison is the evidence",
    "denominator missing or zero - rate layers not computable",
    "denominator 100 (+10% vs previous)",
    "denominator 100",
    "rate 24.0%",
    "peer comparison has fewer than 4 peer hospitals - too few to measure a "
    "spread, so the level is capped at HIGH and no z-score is produced for it; "
    "the deviation itself is still reported",
    "own-history baseline: the percentage change is not graded on its own - it "
    "is clamped to the level the same window's z-score supports, because a "
    "relative change ignores how much the series normally varies",
    "Not enough history: needs at least 3 prior months - this month is not "
    "assessable against its own baseline, so it is not a confirmed normal result.",
]

# ── 1 + 8. English is unchanged ────────────────────────────────────────────


def test_english_round_trip_is_identical_for_every_new_sentence():
    """EN output is the backend's own wording, byte for byte (no drift)."""
    out = _run([{"text": t, "lang": "en"} for t in NEW_SENTENCES])
    broken = [(t, g) for t, g in zip(NEW_SENTENCES, out, strict=True)
              if g != t]
    assert not broken, "\n".join(
        f"  in : {t.encode('unicode_escape').decode()}\n"
        f"  out: {(g or 'NULL').encode('unicode_escape').decode()}"
        for t, g in broken)


def test_arabic_never_changes_a_number_or_a_percentage():
    """Every numeric token survives the sentence/clause split untouched."""
    out = _run([{"text": t, "lang": "ar"} for t in NEW_SENTENCES])
    for text, got in zip(NEW_SENTENCES, out, strict=True):
        assert got, f"no AR rendering: {text}"
        assert AR.search(got), got
        for token in re.findall(r"\d+(?:[.,]\d+)?%?", text):
            assert token in got, f"{token!r} lost: {got}"


# ── 2. Partial paragraph: no leaked machine code ───────────────────────────


def test_partially_translated_paragraph_humanizes_machine_codes():
    """A known sentence is Arabic; the unknown neighbour keeps its wording but
    its identifiers become readable words (never raw codes)."""
    text = (f"Rule 5 of the layered rule table fired {ARROW} HISTORICAL_ANOMALY. "
            + UNKNOWN_WITH_CODE)
    got = _run([{"text": text, "lang": "ar", "humanize": True}])[0]
    assert got
    # the registered sentence is Arabic
    assert AR.search(got.split(".")[0]), got
    assert "HISTORICAL_ANOMALY" not in got, got
    # the unregistered sentence is NOT translated ...
    assert "A future clause mentions" in got, got
    # ... but it carries no raw code
    assert "VERY_HIGH" not in got, got
    assert "Very high" in got and "Historical anomaly" in got, got


def test_partial_paragraph_without_a_humanize_hook_keeps_the_sentence_verbatim():
    text = (f"Rule 5 of the layered rule table fired {ARROW} HISTORICAL_ANOMALY. "
            + UNKNOWN)
    got = _run([{"text": text, "lang": "ar"}])[0]
    assert UNKNOWN in got


# ── 3 + 4. Interpretation: localized, numbers intact, routes distinct ──────


def test_arabic_outlier_interpretation_is_localized_and_numerically_intact():
    got = _run([{"text": HIST_PRIMARY, "lang": "ar"}])[0]
    assert got
    # lead
    assert "\u0627\u0646\u062d\u0631\u0627\u0641 \u0639\u0646 \u062e\u0637" in got, got
    # level through the shared label, never the code
    assert "VERY_HIGH" not in got, got
    assert AR_LABELS["VERY_HIGH"] in got, got
    # no English sentence survives
    assert "peer comparison also" not in got, got
    assert "baseline mean" not in got, got
    # every number and the indicator name survive
    for token in ("10", "4", "150%", "218%", "3.14286", "0.7", "9",
                  "Unplanned admission to ICU"):
        assert token in got, f"{token!r} lost: {got}"
    # the clauses are separated with the Arabic semicolon
    assert SEMI_AR in got, got


def test_history_and_peer_policy_wording_stay_distinct_in_arabic():
    """The own-history and peer routes are different claims and stay different."""
    hist, none = _run([
        {"text": HIST_PRIMARY, "lang": "ar"},
        {"text": NONE_PRIMARY, "lang": "ar"},
    ])
    assert hist != none
    # own-history lead vs "no layer exceeded" lead
    assert "\u0627\u0646\u062d\u0631\u0627\u0641 \u0639\u0646 \u062e\u0637" in hist
    assert "\u0644\u0645 \u064a\u062a\u062c\u0627\u0648\u0632" in none
    # a peer deviation the peers do NOT share says so, in Arabic
    assert "\u0644\u0627 \u064a\u0634\u0627\u0631\u0643 \u0627\u0644\u0646\u0638\u0631\u0627\u0621" in none, none
    # the zero-spread cap is named, with the capped band localized
    assert "HIGH" not in none, none
    assert AR_LABELS["HIGH"] in none, none
    assert "no spread" not in none, none


def test_insufficient_history_lead_and_peer_only_route_are_localized():
    got = _run([{"text": PEER_ONLY, "lang": "ar"}])[0]
    assert "\u0627\u0644\u062a\u0627\u0631\u064a\u062e \u063a\u064a\u0631 \u0643\u0627\u0641" in got, got
    assert "Not enough history" not in got, got
    assert "peer comparison" not in got, got
    assert "12" in got


def test_data_entry_lead_survives_its_own_semicolon_and_localizes():
    """A lead that itself contains '; ' must not be split into fragments."""
    got = _run([{"text": DATA_ENTRY, "lang": "ar"}])[0]
    assert "\u062e\u0637\u0623 \u0641\u064a \u0625\u062f\u062e\u0627\u0644" in got, got
    assert "data-entry error" not in got, got
    assert "\u0645\u0642\u0627\u0645 \u0635\u063a\u064a\u0631" in got, got
    assert "90" in got and "350%" in got


# ── 5. Composite quality-score reason ──────────────────────────────────────


def test_composite_quality_score_reason_is_fully_arabic():
    got = _run([{"text": COMPOSITE_SCORE, "lang": "ar"}])[0]
    assert got
    for english in ("raw-data problem", "component(s) below target",
                    "weakest:", "vs 90% target"):
        assert english not in got, f"{english!r} still English: {got}"
    # the dynamic counts and values are carried over
    assert "1" in got and "87.6" in got and "90" in got
    # all three clauses are Arabic
    assert got.count(SEMI_AR) >= 2, got


def test_composite_rule_and_no_rule_clauses_are_localized_side_by_side():
    got = _run([{"text": COMPOSITE_RULES, "lang": "ar"}])[0]
    assert "validation rule(s) failed" not in got, got
    assert "No validation rule failed" not in got, got
    assert "86.5" in got and "R001" in got and "R002" in got


# ── 6. Detection-layer values ──────────────────────────────────────────────


def test_detection_layer_values_use_the_registered_templates():
    values = [
        "10 (previous 4, +150.0%)",
        "not applicable (count indicator)",
        "not computable (denominator missing or zero)",
        "insufficient history",
        "+218.2% vs baseline mean 3.14286",
        "0.666667 across 9 peer hospitals",
        "not computable (fewer than 2 hospitals reported it)",
    ]
    got = _render([{"fn": "_layerValue", "args": [v]} for v in values])
    for source, rendered in zip(values, got, strict=True):
        assert AR.search(rendered), (source, rendered)
        for token in re.findall(r"\d+(?:[.,]\d+)?%?", source):
            assert token in rendered, f"{token!r} lost in {rendered}"
    # a bare number and a missing value are not prose and stay as they are
    bare = _render([
        {"fn": "_layerValue", "args": [42]},
        {"fn": "_layerValue", "args": [None]},
        {"fn": "_layerValue", "args": [12.5]},
    ])
    assert bare == ["42", "\u2014", "12.5"]


def test_unregistered_layer_value_is_kept_verbatim():
    value = "a future layer shape 4 (previous 3)"
    got = _render([{"fn": "_layerValue", "args": [value]}])[0]
    assert got == value


# ── 7. Formula and failed-rule text keep their identifiers ────────────────


def test_formula_connector_is_translated_and_the_identifier_is_kept():
    got = _render([{"fn": "_templateOnly", "args": [FORMULA_COUNT]}])[0]
    assert AR.search(got), got
    assert "10.m" in got and "Unplanned admission to ICU" in got, got
    assert "count of indicator" not in got, got


def test_mathematical_formula_is_never_rewritten():
    """A proportion formula is meaning, not prose: only an exact template may
    touch it, and none is registered for it."""
    got = _render([{"fn": "_templateOnly", "args": [FORMULA_PROPORTION]}])[0]
    assert got == FORMULA_PROPORTION
    assert _run([{"text": FORMULA_PROPORTION, "lang": "ar"}])[0] is None


def test_failed_rule_name_and_details_route_through_the_localizer():
    src = EXPLAIN.read_text(encoding="utf-8")
    assert "esc(_prose(r.rule_name || r.rule_description || code))" in src
    assert "esc(_prose(r.details))" in src


# ── Unknown fallback ───────────────────────────────────────────────────────


def test_unknown_sentence_falls_back_without_inventing_a_translation():
    out = _run([{"text": UNKNOWN, "lang": "ar"},
                {"text": "", "lang": "ar"}, {"text": None, "lang": "ar"}])
    assert out == [None, None, None]


# ── P3. Stored labels keep their capitalization ────────────────────────────


def test_stored_labels_keep_their_capitalization_and_codes_stay_readable():
    got = _render([
        {"fn": "_codeLabel", "args": ["Similar hospitals (type)"]},
        {"fn": "_codeLabel", "args": ["Ownership peers"]},
        {"fn": "_codeLabel", "args": ["VERY_HIGH"]},
        {"fn": "_codeLabel", "args": ["MODERATE"]},
        {"fn": "_codeLabel", "args": ["NONE"]},
        {"fn": "_codeLabel", "args": ["not_verified"]},
        {"fn": "_codeLabel", "args": ["catalog_only"]},
        {"fn": "_codeLabel", "args": ["agree"]},
        {"fn": "_codeLabel", "args": [None]},
    ], lang="en")
    assert got[0] == "Similar hospitals (type)", got
    assert got[1] == "Ownership peers", got
    assert got[2] == "Very high", got
    assert got[3] == "Moderate", got
    assert got[4] == "None", got
    assert got[5] == "not verified", got
    assert got[6] == "catalog only", got
    assert got[7] == "agree", got


# ── 9. RTL rendering and mobile wrapping guards ────────────────────────────


def test_localized_text_is_escaped_and_keeps_the_mobile_wrapping_guards():
    """The repaired fields render through ``esc`` inside shrinkable, wrapping
    cells — the same markup the Arabic popup was checked in at 390x844."""
    src = EXPLAIN.read_text(encoding="utf-8")
    # every repaired field is escaped and localized
    assert "esc(_layerValue(L.value))" in src
    assert "esc(_templateOnly(p.how.formula_readable))" in src
    assert "esc(_prose(d.message))" in src
    # the detection-layer value cell still shrinks and wraps
    block = src[src.index("Detection layers"):]
    block = block[: block.index("Quality Alerts cross-check")]
    assert "min-width:0" in block
    assert "max-width:100%" in block
    assert "overflow-wrap:anywhere" in block
    assert "unicode-bidi:plaintext" in block or "unicode-bidi:plaintext" in src
    # the dialog itself keeps its viewport-bounded width
    assert "max-width:min(720px,94vw)" in src
    assert "overflow-wrap:break-word" in src
