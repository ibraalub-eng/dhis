"""Step 6H — the three remaining English headlines in the Explain popup.

Step 6G left three backend-composed headlines unregistered, so the Arabic popup
still opened with an English sentence:

  * Time Periods row   "Quality score 97.1 for 2026-08 (-1.2 vs 2026-07)"
  * Compare row        "C-section rate for <hospital> in 2026-08: 27.66 vs
                        peer benchmark 27.47 (normal)"
  * Trend Analysis row "<rate> trend for <hospital>: decreasing (low),
                        slope -3.6%/mo over 8 months"

This suite drives the REAL ``static/js/explain-prose.js`` through node and pins
the three registered shapes: English stays byte-identical, Arabic carries every
number, month, hospital and rate name untouched, and the closed vocabularies
(the comparison label set and the trend direction/severity words) are
translated while an unknown word is preserved instead of guessed.

Every non-ASCII character is written as an escape so the file cannot be
corrupted by an editor or a console encoding.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "explain-prose.js"
RUNNER_PATH = ROOT / "tests" / "_tmp_prose_runner_6h.mjs"

# The Arabic side of the shared label function (``_codeLabel``): the comparison
# engine's label set (app/engine/anomaly/comparison.py) and the trend engine's
# direction/severity words (app/engine/anomaly/trends.py).
AR_LABELS = {
    "normal": "\u0637\u0628\u064a\u0639\u064a",
    "above average": "\u0623\u0639\u0644\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637",
    "below average": "\u0623\u062f\u0646\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637",
    "significantly above average": (
        "\u0623\u0639\u0644\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637 "
        "\u0628\u062f\u0631\u062c\u0629 \u062f\u0627\u0644\u0629"),
    "significantly below average": (
        "\u0623\u062f\u0646\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637 "
        "\u0628\u062f\u0631\u062c\u0629 \u062f\u0627\u0644\u0629"),
    "critically above average": (
        "\u0623\u0639\u0644\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637 "
        "\u0628\u062f\u0631\u062c\u0629 \u062d\u0631\u062c\u0629"),
    "critically below average": (
        "\u0623\u062f\u0646\u0649 \u0645\u0646 \u0627\u0644\u0645\u062a\u0648\u0633\u0637 "
        "\u0628\u062f\u0631\u062c\u0629 \u062d\u0631\u062c\u0629"),
    "increasing": "\u0645\u062a\u0632\u0627\u064a\u062f",
    "decreasing": "\u0645\u062a\u0646\u0627\u0642\u0635",
    "stable": "\u0645\u0633\u062a\u0642\u0631",
    "negligible": "\u0645\u0647\u0645\u0644",
    "low": "\u0645\u0646\u062e\u0641\u0636",
    "moderate": "\u0645\u062a\u0648\u0633\u0637",
    "high": "\u0645\u0631\u062a\u0641\u0639",
    "critical": "\u062d\u0631\u062c",
}

RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.argv[2]).href);
const AR = JSON.parse(process.argv[3]);
const payload = JSON.parse(readFileSync(0, 'utf8'));

const out = payload.cases.map(function (c) {
  const lang = c.lang || 'ar';
  const label = lang === 'en'
    ? function (code) { return code; }
    : function (code) { return AR[code] || code; };
  return mod.localizeProse(c.text, lang, label);
});
process.stdout.write(JSON.stringify(out));
"""

AR = re.compile("[\u0600-\u06FF]")
HOSP = "\u0645\u0633\u062a\u0634\u0641\u0649 \u0627\u0644\u0635\u0644\u064a\u0628"
HOSP2 = "\u0645\u0633\u062a\u0634\u0641\u0649 \u0627\u0644\u062b\u0648\u0631\u0629"
RATE = "C-section rate"
RATE2 = "Unplanned admission to ICU"

# Real payload ``what`` fields (explain.py::explain_time_period_point,
# ::explain_comparison_row, ::explain_trend_row).
TP = "Quality score 97.1 for 2026-08 (-1.2 vs 2026-07)"
TP_NONE = "Quality score 74.5 for 2026-01 (no earlier analyzed month to compare)"
CMP = (f"{RATE} for {HOSP} in 2026-08: 27.66 vs peer benchmark 27.47 (normal)")
CMP_SIG = (f"{RATE2} for {HOSP2} in 2026-08: +12.3 vs peer benchmark 4.5 "
           f"(critically above average)")
TREND = (f"{RATE} trend for {HOSP} in 2026-01: decreasing (low), "
         f"slope -3.6%/mo over 8 months")
TREND_STABLE = (f"{RATE2} trend for {HOSP2}: stable (negligible), "
                f"slope +0.2%/mo over 12 months")
TREND_UP = f"{RATE} trend for {HOSP}: increasing (critical), slope +9.9%/mo over 3 months"

HEADLINES = [TP, TP_NONE, CMP, CMP_SIG, TREND, TREND_STABLE, TREND_UP]


def _run(cases):
    RUNNER_PATH.write_text(RUNNER, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(RUNNER_PATH), str(MODULE), json.dumps(AR_LABELS)],
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


def _ar(text):
    return _run([{"text": text, "lang": "ar"}])[0]


# ── 1. English is the backend's own wording, byte for byte ──────────────────


def test_english_round_trip_is_identical_for_every_headline():
    out = _run([{"text": t, "lang": "en"} for t in HEADLINES])
    broken = [(t, g) for t, g in zip(HEADLINES, out, strict=True) if g != t]
    assert not broken, "\n".join(
        f"  in : {t}\n  out: {g or 'NULL'}" for t, g in broken)


# ── 2. Arabic renders the sentence and keeps every analytical token ─────────


def test_arabic_headlines_are_arabic_and_keep_every_number():
    out = _run([{"text": t, "lang": "ar"} for t in HEADLINES])
    for text, got in zip(HEADLINES, out, strict=True):
        assert got, f"no AR rendering: {text}"
        assert AR.search(got), f"still English: {got}"
        for token in re.findall(r"\d+(?:[.,]\d+)?%?", text):
            assert token in got, f"{token!r} lost in {got}"
        for month in re.findall(r"\d{4}-\d{2}", text):
            assert month in got, f"month {month!r} lost in {got}"


def test_arabic_keeps_the_rate_name_hospital_and_slope_sign():
    got = _ar(TREND)
    assert RATE in got, got                    # indicator name is identity
    assert HOSP in got, got                    # hospital name is identity
    assert "-3.6" in got, got                  # sign and one decimal kept
    assert "8" in got, got                     # month count kept
    got = _ar(CMP)
    assert RATE in got and HOSP in got, got
    assert "27.66" in got and "27.47" in got, got


# ── 3. The three shapes no longer keep an English word ─────────────────────


def test_quality_score_headline_is_localized():
    got = _ar(TP)
    assert "Quality score" not in got, got
    assert "vs" not in got, got
    assert "97.1" in got and "2026-08" in got, got


def test_comparison_headline_is_localized():
    got = _ar(CMP)
    assert "peer benchmark" not in got, got
    assert " for " not in got, got
    assert not re.search(r"\b(normal)\b", got), got


def test_trend_headline_is_localized():
    got = _ar(TREND)
    assert " trend for " not in got, got
    assert "slope" not in got, got
    assert "months" not in got, got
    assert "decreasing" not in got and "low" not in got, got
    assert AR_LABELS["decreasing"] in got, got
    assert AR_LABELS["low"] in got, got


# ── 4. Closed vocabularies: every known word, no invented one ──────────────


def test_every_comparison_label_is_translated():
    cases = [f"{RATE} for {HOSP} in 2026-08: 5.0 vs peer benchmark 4.0 ({label})"
             for label in AR_LABELS if label not in
             ("increasing", "decreasing", "stable", "negligible", "low",
              "moderate", "high", "critical")]
    out = _run([{"text": t, "lang": "ar"} for t in cases])
    for text, got in zip(cases, out, strict=True):
        label = text.rsplit("(", 1)[1].rstrip(")")
        assert AR_LABELS[label] in got, f"{label!r} not translated: {got}"
        assert label not in got, f"{label!r} left in English: {got}"
        assert "5.0" in got and "4.0" in got, got


def test_unknown_comparison_label_is_preserved_not_invented():
    unknown = "moderately above average"
    got = _ar(f"{RATE} for {HOSP} in 2026-08: 5.0 vs peer benchmark 4.0 ({unknown})")
    assert unknown in got, got                 # preserved verbatim
    assert AR.search(got), got                 # the sentence is still Arabic


def test_unknown_trend_severity_is_preserved_not_invented():
    got = _ar(f"{RATE} trend for {HOSP}: increasing (severe), slope +1.1%/mo over 5 months")
    assert "severe" in got, got
    assert AR_LABELS["increasing"] in got, got
    assert "1.1" in got and "5" in got, got


# ── 5. Anchoring: only the row's own headline is rewritten ─────────────────


def test_a_longer_sentence_containing_the_shape_is_not_rewritten():
    """A sentence that adds text AFTER the shape is not this row's headline.

    Known limit: a PREFIX is absorbed by the leading parameter (``{rate}``),
    because a rate name is free text; ``what`` is the whole field, so the popup
    never produces one. Nothing is dropped in that case — the prefix is copied
    verbatim — so the limit is presentation noise, not lost meaning.
    """
    longer = [
        TP + " and one more clause",
        CMP + " with extra words",
        TREND + " plus a note",
    ]
    out = _run([{"text": t, "lang": "ar"} for t in longer])
    for text, got in zip(longer, out, strict=True):
        # ``null`` is the module's "nothing matched" answer: the popup keeps the
        # backend's text (``_prose``) instead of guessing a translation.
        assert got in (None, text), f"rewritten beyond its shape: {got}"


def test_no_machine_code_is_introduced():
    out = _run([{"text": t, "lang": "ar"} for t in HEADLINES])
    for got in out:
        assert got, "headline did not render"
        assert not re.search(r"\b[A-Z]{2,}_[A-Z_]+\b", got), got
        assert not re.search(r"\b(?:VERY_HIGH|HIGH|MODERATE|LOW|NONE)\b", got), got
