"""Step 6E -- dynamic Explain prose localization (structured templates).

The backend composes explanation prose in English. ``static/js/explain-prose.js``
registers each STABLE sentence shape as a message (key + parameters) with an
English and an Arabic rendering; anything unregistered falls back to the
original text. These tests drive the real module through node and assert:

A. every registered template round-trips ENGLISH unchanged (no meaning drift),
B. the Arabic rendering keeps every number, percentage and identifier intact,
C. analytical codes are rendered through the shared label function, never
   copied raw into an Arabic sentence,
D. unknown templates, empty and null input fall back safely (``None``),
E. the renderer routes every prose field through ``_prose``.

Every non-ASCII character in this file is written as an escape so the test
cannot be corrupted by an editor or console encoding.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "explain-prose.js"
EXPLAIN = ROOT / "static" / "js" / "explain.js"
RUNNER_PATH = ROOT / "tests" / "_tmp_prose_runner.mjs"

# Arabic label map used by the AR rendering (mirrors _codeLabel in the popup).
AR_LABELS = {
    "HISTORICAL_ANOMALY": "\u0634\u0630\u0648\u0630 \u062a\u0627\u0631\u064a\u062e\u064a",
    "INSUFFICIENT_HISTORY": "\u062a\u0627\u0631\u064a\u062e \u063a\u064a\u0631 \u0643\u0627\u0641\u064d",
    "PEER_ANOMALY": "\u0634\u0630\u0648\u0630 \u0628\u064a\u0646 \u0627\u0644\u0646\u0637\u064a\u0631",
    "VERY_HIGH": "\u0645\u0631\u062a\u0641\u0639 \u062c\u062f\u064b\u0627",
    "HIGH": "\u0645\u0631\u062a\u0641\u0639",
    "MODERATE": "\u0645\u062a\u0648\u0633\u0637",
    "LOW": "\u0645\u0646\u062e\u0641\u0636",
    "NONE": "\u0644\u0627 \u0634\u064a\u0621",
}

RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.argv[2]).href);
const payload = JSON.parse(readFileSync(0, 'utf8'));
const AR = JSON.parse(process.argv[3]);
const out = payload.cases.map(function (c) {
  const lang = c.lang || 'en';
  // EN is the backend's own wording, so an identity label proves the template
  // reproduces it exactly; AR renders codes through the shared label map.
  const label = lang === 'en'
    ? function (code) { return code; }
    : function (code) { return AR[code] || code; };
  return mod.localizeProse(c.text, lang, label);
});
process.stdout.write(JSON.stringify(out));
"""


def _run(cases, labels=None):
    """Render every case through the real module in one node process."""
    RUNNER_PATH.write_text(RUNNER, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(RUNNER_PATH), str(MODULE), json.dumps(labels or AR_LABELS)],
            input=json.dumps({"cases": cases}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    finally:
        RUNNER_PATH.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


EM = "\u2014"      # em dash the backend uses
ARROW = "\u2192"   # arrow the backend uses
GE = "\u2265"      # "≥ 2 others"

# Exact backend strings (app/engine/audit/explain.py), one per template.
KNOWN = [
    # -- layered outlier ---------------------------------------------------
    f"Out-of-facility deliveries 24 vs 10 previous (+140%) {EM} HISTORICAL_ANOMALY (VERY_HIGH level)",
    f"Out-of-facility deliveries {EM} INSUFFICIENT_HISTORY (NONE level)",
    f"Rule 2 of the layered rule table fired {ARROW} HISTORICAL_ANOMALY. "
    "The reported value rose far beyond its own history.",
    "The stored classification no longer matches the current history (recomputed: "
    f"INSUFFICIENT_HISTORY) {EM} recalculate this month. Stored interpretation: "
    "The stored classification no longer matches the current history.",
    "Stored interpretation: The reported value rose far beyond its own history.",
    "Under the current classification policy this row recomputes to "
    f"INSUFFICIENT_HISTORY NONE (stored: HISTORICAL_ANOMALY VERY_HIGH) {EM} "
    "recalculate this month.",
    "this month's analysis value vs its own recent distribution",
    "rate vs its own recent distribution",
    "count indicators have no separate rate layer",
    "0 valid prior months against a 3-observation minimum",
    "denominator change guards against volume-driven spikes",
    "count indicators have no denominator layer",
    f"every hospital reporting the indicator this month ({GE} 2 others), self excluded",
    "Fewer than 4 peer hospitals cannot measure a spread, so no z-score is produced "
    "for this comparison",
    "not computable",
    "24 (previous 10, +140.0%)",
    "not applicable (count indicator)",
    "not computable (denominator missing or zero)",
    "insufficient history",
    "+140.0% vs baseline mean 10",
    "12.5 across 6 peer hospitals",
    "not computable (fewer than 2 hospitals reported it)",
    "Stored layer scores and the current history reproduce the stored classification.",
    "Re-running the rule table over the stored scores with the CURRENT history gives "
    f"a different result {EM} the history changed since this row was written; "
    "recalculate this month.",
    f"raw {ARROW} rate/volume {ARROW} historical {ARROW} peer (recorded method: auto)",
    "Rule 2: HISTORICAL_ANOMALY at VERY_HIGH, route none",
    # -- anomaly -----------------------------------------------------------
    "Out-of-facility deliveries is an outlier: value 24 vs benchmark 10 (z=3.4)",
    "Out-of-facility deliveries is within normal range: value 12 vs benchmark 10 (z=0.4)",
    f"|z| = 3.40 exceeds the 2.5 threshold {ARROW} flagged as outlier (rate above the benchmark)",
    "Flagged by the anomaly detection pipeline (trend/regression rule) with z=3.4, "
    "threshold 2.5",
    f"|z| = 0.40 is within the 2.5 threshold {ARROW} not an outlier",
    "Zero-denominator and range checks run before rate computation",
    "Anomaly row #42 (outlier=True)",
    f"Raw numerator/denominator missing {EM} rate cannot be reproduced from stored values",
    "Benchmark recomputed and matches the current data.",
    "Benchmark could not be reproduced from the current data.",
    # -- data problems -----------------------------------------------------
    "Indicator 2.l (Out-of-facility deliveries) has no value for this month",
    "Indicator 2.l has no value for this month",
    "Indicator 2.l (Out-of-facility deliveries) has a negative value (-3)",
    "Indicator 2.l (Out-of-facility deliveries) = 24 from 'q3.xlsx' appears 2 times "
    "(uploaded more than once)",
    f"Only 2 peer hospital(s) {EM} the benchmark is statistically fragile",
    "The stored benchmark (10, z=3.4) no longer matches the uploaded data: recomputing "
    "Out-of-facility deliveries over the same population gives 11 (z=2.9). The anomaly "
    f"row is out of date with the current values or indicator configuration {EM} "
    "recalculate this month.",
    # -- quality score -----------------------------------------------------
    f"Data quality score 82.4 for 2026-07 {EM} weighted mix of rule compliance, "
    "completeness, consistency and outlier score",
    f"Outlier score 91 for 2026-07 {EM} 100 minus the penalty from 2 indicator(s) at "
    "HIGH/VERY_HIGH",
    "This month has a score row but no raw data behind it (never analyzed or data was "
    "removed). The score is a placeholder, not a performance result.",
    "1 component(s) below target; weakest: Completeness (71.2% vs 90% target).",
    f"2 validation rule(s) failed (R001, R002) {ARROW} rule compliance 86.5%",
    "No validation rule failed this month",
    "All components meet their targets (No validation rule failed this month)",
    f"All components meet their targets {EM} the score reflects good data quality",
    "3 raw-data problem(s) detected;",
    "Outlier score 91% = 100 - 9 penalty, from 2 indicator(s) at HIGH/VERY_HIGH: "
    "2.l (VERY_HIGH), 17 (HIGH)",
    f"No indicator reached HIGH or VERY_HIGH this month {EM} outlier score 100% "
    "(penalty 0).",
    "Missing cells are counted under completeness, not here",
    "+3 more",
    # -- Quality Alerts cross-check ---------------------------------------
    "No active Quality Alert is stored for this formula and month, so there is no "
    "second verdict to compare with.",
    "Re-scan the month if an alert was expected.",
    'Quality Alerts reports VERY_HIGH under "Ownership peers" (n=6), a narrower '
    "stratified comparison.",
    "Outlier Diagnostics classifies this row INSUFFICIENT_HISTORY at NONE against the "
    "single all-hospital detection baseline (peer score n/a / not available), and the "
    "hospital's own history is not assessable.",
    "the hospital's own history could not be assessed either.",
    "its own history stayed within its band.",
    "The stored history-perspective alert is more severe than this diagnostic row "
    "although both use the same history baseline; recalculate the month before relying "
    "on either.",
    'The stored alert (VERY_HIGH, "Ownership peers") is more severe than this diagnostic '
    "row (HIGH) under the same detection baseline, so the two stored results disagree.",
    "Recalculate this month to reconcile them.",
    'Quality Alerts and Outlier Diagnostics agree: the most severe stored alert '
    '(VERY_HIGH, "Ownership peers") is consistent with this diagnostic level '
    "(VERY_HIGH).",
    "The matching Quality Alert was closed by a reviewer (Resolved / skipped as False "
    "Positive), so it no longer raises on the Quality Alerts screen; closing records the "
    "investigation decision and changes neither detection result.",
    'The stored alert was written VERY_HIGH, but the approved cap policy assigns it HIGH '
    '("Ownership peers"): the comparison group holds 2 other hospital(s) and measuring a '
    "spread needs at least 4, so its z-score is not a measurement.",
    "Quality Alerts shows that policy band while Outlier Diagnostics classifies the peer "
    "layer without the cap (HISTORICAL_ANOMALY at VERY_HIGH).",
    "The stored row keeps VERY_HIGH until the month is re-scanned.",
    "every hospital in that comparison reported the same value, so the deviation has no "
    "measurable scale",
    "the hospital's own history window does not support the top band (the same window's "
    "dispersion-aware band is HIGH)",
    'The stored alert (VERY_HIGH, "Ownership peers") is consistent with the stored '
    "diagnostic row, but that row was written under an older classification policy.",
    # -- rules -------------------------------------------------------------
    "Rule R001 FAILED: Denominator must be positive",
    "Rule R001 passed: Denominator must be positive",
]

UNKNOWN = ["A future engine sentence no template knows about."]


# The three outlier-score sentences name the severity bands in the backend's
# machine form (``at HIGH/VERY_HIGH``, ``2.l (VERY_HIGH)``). The popup renders
# those band identifiers as words in BOTH languages — the same readability the
# outliers list already gets — so English differs from the backend text for
# these three sentences and only for the band words; every number, percentage
# and indicator code must still be identical.
BAND_WORDS = {
    "VERY_HIGH": "Very high",
    "HIGH": "High",
    "MODERATE": "Moderate",
    "LOW": "Low",
}


def _en_expected(text):
    import re

    if not text.startswith(("Outlier score", "No indicator reached")):
        return text
    for code, word in BAND_WORDS.items():
        text = re.sub(r"\b" + code + r"\b", word, text)
    return text


def test_english_round_trip_preserves_every_registered_message():
    """Every template must reproduce the backend's English text exactly.

    The one documented exception is the machine band names inside the
    outlier-score sentences, which are shown as words (see ``BAND_WORDS``).
    """
    out = _run([{"text": text, "lang": "en"} for text in KNOWN])
    missing = [(text, got) for text, got in zip(KNOWN, out, strict=True)
               if got != _en_expected(text)]
    assert not missing, "template does not round-trip EN:\n" + "\n".join(
        f"  in : {t.encode('unicode_escape').decode()}\n"
        f"  out: {(g or 'NULL').encode('unicode_escape').decode()}\n"
        f"  exp: {_en_expected(t).encode('unicode_escape').decode()}"
        for t, g in missing)


def test_arabic_rendering_is_translated_and_keeps_every_number():
    """AR output is Arabic, and no numeric value or percentage is altered."""
    import re

    out = _run([{"text": text, "lang": "ar"} for text in KNOWN])
    for text, got in zip(KNOWN, out, strict=True):
        assert got, f"no AR rendering for: {text.encode('unicode_escape').decode()}"
        assert re.search("[\u0600-\u06FF]", got), got
        # The template FRAME is Arabic: a sentence that stayed fully ASCII means
        # the template was not applied.
        assert not re.fullmatch(r"[\x00-\x7F]*", got), got
        for token in re.findall(r"\d+(?:[.,]\d+)?%?", text):
            assert token in got, f"{token!r} lost in AR rendering: {got}"


def test_analytical_codes_use_the_shared_label_not_raw_codes():
    """Codes are rendered by the label function, never pasted raw."""
    cases = [
        f"Out-of-facility deliveries 24 vs 10 previous (+140%) {EM} HISTORICAL_ANOMALY "
        "(VERY_HIGH level)",
        f"Rule 2 of the layered rule table fired {ARROW} HISTORICAL_ANOMALY.",
        "Under the current classification policy this row recomputes to "
        f"INSUFFICIENT_HISTORY NONE (stored: HISTORICAL_ANOMALY VERY_HIGH) {EM} "
        "recalculate this month.",
        'Quality Alerts reports VERY_HIGH under "Ownership peers" (n=6), a narrower '
        "stratified comparison.",
    ]
    out = _run([{"text": text, "lang": "ar"} for text in cases])
    very_high = AR_LABELS["VERY_HIGH"]
    hist = AR_LABELS["HISTORICAL_ANOMALY"]
    for _text, got in zip(cases, out, strict=True):
        assert very_high in got or hist in got, got
        assert "VERY_HIGH" not in got and "HISTORICAL_ANOMALY" not in got, got


def test_known_template_with_unknown_analysis_code_keeps_the_label_fallback():
    """A new analysis TYPE in a known sentence shape is still safe: the band is
    localized and the unknown code keeps the caller's own fallback."""
    text = (f"Out-of-facility deliveries 24 vs 10 previous (+140%) {EM} NEW_TYPE "
            "(VERY_HIGH level)")
    out = _run([{"text": text, "lang": "ar"}])[0]
    assert out is not None
    assert "NEW_TYPE" in out
    assert "VERY_HIGH" not in out
    assert "24" in out and "140%" in out


def test_unknown_and_missing_inputs_fall_back_safely():
    out = _run(
        [{"text": text, "lang": "ar"} for text in UNKNOWN]
        + [{"text": "", "lang": "ar"}, {"text": None, "lang": "ar"},
           {"text": None, "lang": "en"}]
    )
    assert out[: len(UNKNOWN)] == [None]
    assert out[len(UNKNOWN):] == [None, None, None]


def test_partially_known_paragraph_keeps_the_unlocalized_sentence_verbatim():
    """A paragraph with one known and one unknown sentence keeps the latter."""
    text = (
        f"Rule 2 of the layered rule table fired {ARROW} HISTORICAL_ANOMALY. "
        "A brand new sentence the registry has never seen."
    )
    out = _run([{"text": text, "lang": "ar"}])[0]
    rule_frame = (
        "\u0627\u0646\u0637\u0628\u0642\u062a \u0627\u0644\u0642\u0627\u0639\u062f\u0629 2"
    )
    assert rule_frame in out
    assert "A brand new sentence the registry has never seen." in out


def test_mixed_english_terms_and_units_survive():
    out = _run([
        {"text": "12.5 across 6 peer hospitals", "lang": "ar"},
        {"text": "24 (previous 10, +140.0%)", "lang": "ar"},
        {"text": "+140.0% vs baseline mean 10", "lang": "ar"},
        {"text": "Rule 2: HISTORICAL_ANOMALY at VERY_HIGH, route none", "lang": "ar"},
    ])
    assert "12.5" in out[0] and "6" in out[0]
    assert "140.0%" in out[1] and "24" in out[1]
    assert "140.0%" in out[2] and "10" in out[2]
    # The recorded method/route stay verbatim (they are stored identifiers).
    assert "none" in out[3]


def test_templates_are_anchored_and_fallback_returns_null():
    """Guard the architecture: whole-sentence matchers, null on no match."""
    src = MODULE.read_text(encoding="utf-8")
    assert "export function localizeProse" in src
    assert "if (!matched) return null;" in src
    # Every matcher is anchored at both ends: a template describes a whole
    # sentence, it never rewrites a fragment in place.
    assert src.count("', /^") + src.count('", /^') >= 70
    assert "'/^" not in src


def test_renderer_routes_every_prose_field_through_prose():
    src = EXPLAIN.read_text(encoding="utf-8")
    assert "import { localizeProse } from './explain-prose.js';" in src
    assert "function _prose(text)" in src
    for site in ("_prose(p.what || '')", "_prose(p.why)", "_prose(cc.explanation)",
                 "_prose(L.detail)", "_prose(L.name || L.key)",
                 "_prose(o.interpretation)", "_prose(d.message)", "_prose(r.note)"):
        assert site in src, site
    assert "esc(_humanizeCodes(p.why))" not in src
    assert "esc(_humanizeCodes(cc.explanation))" not in src
