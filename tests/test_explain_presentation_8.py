"""Step 8 — the four presentation repairs.

F1  The layered Explain headline quotes the band the Diagnostics screen
    renders (``row_level_assessment``), not the band stored on the row, and the
    row is assessed ONCE so the headline and the cross-check cannot disagree.
    The stored band stays available (``outlier_level`` / ``diagnostic.level``);
    the database value is never rewritten.
F4  Every series point carries BOTH bands, and the popup legend labels the
    effective one, naming a refused stored band separately.
F2  The trend row's ``why`` is a registered prose shape: English stays
    byte-identical, Arabic translates the wording and keeps every number,
    sign, percentage and unit; an unknown word is preserved, never invented.
F3  The app-shell header wraps its controls at <=480px instead of pushing the
    document sideways; no control is hidden.

Non-ASCII is written as escapes so the file survives any editor or console
encoding, matching the convention of tests/test_explain_localization_6h.py.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from app.engine.anomaly.layered import row_level_assessment
from app.engine.audit.explain import explain_layered_outlier
from app.models import Hospital, LayeredOutlierResult

MONTH = "2027-07"
CODE = "17"                      # count indicator seeded by conftest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "explain-prose.js"
RUNNER_PATH = ROOT / "tests" / "_tmp_prose_runner_8.mjs"

# The Arabic half of the shared label function (``_codeLabel``) for the trend
# engine's direction/severity vocabulary (app/engine/anomaly/trends.py).
AR_LABELS = {
    "increasing": "\u0645\u062a\u0632\u0627\u064a\u062f",
    "decreasing": "\u0645\u062a\u0646\u0627\u0642\u0635",
    "stable": "\u0645\u0633\u062a\u0642\u0631",
    "negligible": "\u0645\u0647\u0645\u0644",
    "low": "\u0645\u0646\u062e\u0641\u0636",
    "moderate": "\u0645\u062a\u0648\u0633\u0637",
    "high": "\u0645\u0631\u062a\u0641\u0639",
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


# ── The stored row under test ──────────────────────────────────────────────

def _stored_row(db, *, history=(10.0, 20.0, 35.0, 15.0),
                peers=(10.0, 11.0, 12.0), peer_count=3,
                historical_score=1.0, level="VERY_HIGH",
                outlier_type="HISTORICAL_ANOMALY"):
    """A row exactly as the pre-policy scan stored it (no provenance block).

    ``history=(10, 20, 35, 15)`` is the window the approved history gate
    refuses: the stored VERY_HIGH stays on disk while Diagnostics shows HIGH.
    """
    hospital = db.query(Hospital).order_by(Hospital.id).first()
    row = LayeredOutlierResult(
        hospital_id=hospital.id, analysis_code=CODE, month=MONTH,
        raw_value=2.0, previous_value=1.0, denominator=None, rate=None,
        raw_value_outlier_score=None, rate_outlier_score=None,
        historical_outlier_score=historical_score, volume_anomaly_score=None,
        peer_outlier_score=1.0, peer_count=peer_count,
        peer_mean=sum(peers) / len(peers),
        peer_provenance={"values": {str(i): v for i, v in enumerate(peers)}},
        history_provenance={"values": list(history)} if history else None,
        outlier_level=level, outlier_type=outlier_type,
        outlier_method="peer_zscore", investigation_route="data_quality",
        interpretation="Deviation from this hospital's own recent baseline.",
    )
    db.add(row)
    db.commit()
    return row


# ── F1: the headline quotes the DISPLAYED band ────────────────────────────

def test_the_headline_quotes_the_band_the_diagnostics_table_shows(db_session):
    row = _stored_row(db_session)
    assert row.outlier_level == "VERY_HIGH", "stored band on disk"
    assert row_level_assessment(row)[0] == "HIGH", \
        "fixture must be a row the history gate refuses"

    payload = explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)

    assert "(HIGH level)" in payload["what"], payload["what"]
    assert "VERY_HIGH level" not in payload["what"], payload["what"]


def test_stored_and_displayed_bands_stay_independently_available(db_session):
    row = _stored_row(db_session)

    payload = explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)

    assert payload["outlier_level"] == "VERY_HIGH", "stored band preserved"
    assert payload["displayed_outlier_level"] == "HIGH"
    diag = payload["cross_check"]["diagnostic"]
    assert diag["level"] == "VERY_HIGH"
    assert diag["stored_level"] == "VERY_HIGH"
    assert diag["displayed_level"] == "HIGH"
    assert diag["effective_level"] == diag["displayed_level"]


def test_headline_and_cross_check_always_agree(db_session):
    row = _stored_row(db_session)

    payload = explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)

    shown = payload["cross_check"]["diagnostic"]["displayed_level"]
    assert payload["displayed_outlier_level"] == shown
    assert f"({shown} level)" in payload["what"], payload["what"]


def test_a_policy_allowed_top_band_is_still_quoted_as_very_high(db_session):
    row = _stored_row(db_session, history=None, historical_score=None,
                      peers=(10.0, 20.0, 30.0), peer_count=9,
                      outlier_type="PEER_ANOMALY")
    payload = explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)
    assert payload["displayed_outlier_level"] == "VERY_HIGH"
    assert "(VERY_HIGH level)" in payload["what"], payload["what"]


def test_the_stored_row_is_never_rewritten(db_session):
    row = _stored_row(db_session)
    explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)
    db_session.expire_all()
    again = db_session.query(LayeredOutlierResult).filter_by(id=row.id).one()
    assert again.outlier_level == "VERY_HIGH"


# ── F4: the series carries both bands for the legend ──────────────────────

def test_series_points_carry_the_stored_and_the_displayed_band(db_session):
    row = _stored_row(db_session)

    payload = explain_layered_outlier(db_session, row.hospital_id, MONTH, CODE)
    point = next(p for p in payload["series"] if p["current"])

    assert point["level"] == "VERY_HIGH", "stored band, unchanged"
    assert point["displayed_level"] == "HIGH", "band the table renders"


def test_the_legend_labels_the_effective_band_and_the_stored_one():
    explain = (ROOT / "static" / "js" / "explain.js").read_text(encoding="utf-8")
    assert "bandPoint.displayed_level || bandPoint.level" in explain
    assert "__('Band at this month')" in explain
    assert "__('stored band')" in explain

    i18n = (ROOT / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "'Band at this month':" in i18n
    assert "'stored band':" in i18n


# ── F2: trend.why is a registered prose shape ─────────────────────────────

# Real backend shapes (explain.py::explain_trend_row), consecutive clause
# optional: "slope {s:+.2f}%/mo -> direction '{d}' (stable band ±{t}%);
# severity '{v}'; {n} consecutive {d} months; last vs mean {x:+.1f}%; CV {c}%"
WHY_CONSECUTIVE = (
    "slope -3.60%/mo \u2192 direction 'decreasing' (stable band \u00b15.0%); "
    "severity 'low'; 2 consecutive decreasing months; "
    "last vs mean -17.9%; CV 14.5%"
)
WHY_PLAIN = (
    "slope +0.20%/mo \u2192 direction 'stable' (stable band \u00b15.0%); "
    "severity 'negligible'; last vs mean +0.1%; CV 4.2%"
)


def test_english_trend_why_is_byte_identical():
    out = _run([{"text": t, "lang": "en"}
                for t in (WHY_CONSECUTIVE, WHY_PLAIN)])
    assert out == [WHY_CONSECUTIVE, WHY_PLAIN]


def test_arabic_trend_why_is_localized_and_keeps_every_number():
    for text in (WHY_CONSECUTIVE, WHY_PLAIN):
        got = _ar(text)
        assert got and AR.search(got), f"still English: {text}"
        assert "slope" not in got, got
        assert "severity" not in got, got
        assert "stable band" not in got, got
        for token in re.findall(r"[+\-]?\d+(?:\.\d+)?", text):
            assert token in got, f"{token!r} lost in {got}"


def test_arabic_trend_why_translates_direction_and_severity():
    got = _ar(WHY_CONSECUTIVE)
    assert "decreasing" not in got, got
    assert AR_LABELS["decreasing"] in got, got
    assert AR_LABELS["low"] in got, got
    assert "2" in got and "-17.9" in got and "14.5" in got, got


def test_unknown_trend_words_are_preserved_not_invented():
    unknown = (
        "slope -1.00%/mo \u2192 direction 'wobbling' (stable band \u00b15.0%); "
        "severity 'severe'; last vs mean -2.0%; CV 9.0%"
    )
    got = _ar(unknown)
    assert "wobbling" in got, got
    assert "severe" in got, got
    assert "-1.00" in got and "-2.0" in got and "9.0" in got, got


def test_unregistered_trend_prose_is_kept_verbatim():
    longer = WHY_CONSECUTIVE + " plus a note"
    assert _ar(longer) in (None, longer)


def test_the_localized_headline_carries_the_effective_band():
    """The headline that reaches the popup carries the EFFECTIVE band."""
    text = ("Neonatal deaths 2 vs 1 previous (+100%) \u2014 HISTORICAL_ANOMALY "
            "(HIGH level)")
    got = _ar(text)
    assert got and AR.search(got), got
    assert "(HIGH)" in got, got
    assert "VERY_HIGH" not in got, got


# ── F3: the header wraps instead of overflowing ───────────────────────────

def test_mobile_header_wraps_and_hides_nothing():
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 480px) {" in css
    block = css.split("@media (max-width: 480px) {", 1)[1].split("\n}", 1)[0]

    assert ".header > div:last-child" in block
    assert "flex-wrap: wrap" in block
    assert "min-width: 0" in block
    # The fix must not be "hide the control": both toggles stay in the DOM.
    assert "langToggle" not in block
    assert "themeToggle" not in block
