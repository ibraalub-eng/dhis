"""Explain: the routed top-band verdict, its four states and its wording.

Two seams, one contract:

* the API payload (``cross_check.perspectives[].top_band_eligibility`` and
  ``cross_check.diagnostic.top_band_eligibility``) states the decision, the
  route, the threshold that was used and the policy sentence — the same values
  the Quality Alerts screen and Diagnostics show for the same row;
* the popup prints that verdict in words, and ``not_applicable`` prints
  NOTHING: a note there would describe a row the policy did not judge.

The JavaScript half executes the REAL ``_eligibilityNote`` extracted from the
shipped source in node (the repository's static-UI convention), so a renamed
key or a dropped state fails here instead of in the browser.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.layered import (
    LEVEL_HIGH,
    LEVEL_VERY_HIGH,
    METHOD_PEER_ZSCORE,
    METHOD_ZSCORE,
    PEER_Z_THRESHOLD_DEFAULT,
)
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
)

MONTH = "2027-06"
# 24 against (1, 30, 0, 4): the robust score saturates, the dispersion does not.
WIDE_WINDOW = (1.0, 30.0, 0.0, 4.0)

EXPLAIN_JS = (Path(__file__).resolve().parents[1]
              / "static" / "js" / "explain.js")
I18N_JS = (Path(__file__).resolve().parents[1]
           / "static" / "js" / "i18n.js")


@pytest.fixture
def client(app):
    """TestClient over the conftest app (auth + db already overridden)."""
    return TestClient(app)


def _add_alert(db, hospital_id, *, perspective, method=METHOD_ZSCORE,
               severity=LEVEL_VERY_HIGH, code="rate_cs", threshold=2.5):
    evidence = {
        "history": [[f"2027-0{i + 1}", v] for i, v in enumerate(WIDE_WINDOW)],
        "stats": {"mean": 8.75, "std": 1.0, "points": len(WIDE_WINDOW)},
    }
    if threshold is not None:
        evidence["z_threshold"] = threshold
    alert = QualityAlert(
        hospital_id=hospital_id, month=MONTH, perspective=perspective,
        indicator_code=code, indicator_name="C-section rate", unit="%",
        formula="{5} / {2} * 100", severity=severity, score=1.0,
        method=method, current_value=24.0, baseline_value=8.75, z_score=None,
        peer_count=len(WIDE_WINDOW), status="New", active=True,
        direction="lower_is_better", interpretation="statistical_only",
        confidence="high", evidence=evidence,
    )
    db.add(alert)
    db.commit()
    return alert


def _add_row(db, hospital_id, *, provenance=None, code="rate_cs"):
    row = LayeredOutlierResult(
        hospital_id=hospital_id, analysis_code=code, month=MONTH,
        raw_value=24.0, previous_value=10.0, denominator=100.0, rate=24.0,
        raw_value_outlier_score=1.0, rate_outlier_score=1.0,
        historical_outlier_score=1.0, volume_anomaly_score=0.0,
        outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
        outlier_method=METHOD_ZSCORE, interpretation="statistical_only",
        investigation_route="none",
        history_provenance={"values": list(WIDE_WINDOW)},
        classification_provenance=provenance,
    )
    db.add(row)
    db.commit()
    return row


def _history_values(db, hospital_id):
    for month in ("2027-03", "2027-04", "2027-05"):
        for code, value in (("2", 100.0), ("5", 10.0)):
            ind = db.query(Indicator).filter(Indicator.code == code).first()
            assert ind is not None, f"seeded indicator {code} missing"
            db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                                  month=month, value=value))
    db.commit()


def _explain(client, hospital_id):
    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={hospital_id}"
        f"&month={MONTH}&indicator_code=rate_cs")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── API payload ────────────────────────────────────────────────────────────

def test_each_perspective_states_its_own_decision_and_policy(db_session, client):
    hospital = db_session.query(Hospital).first()
    _history_values(db_session, hospital.id)
    _add_row(db_session, hospital.id)
    _add_alert(db_session, hospital.id, perspective="history")
    _add_alert(db_session, hospital.id, perspective="ownership",
               method=METHOD_PEER_ZSCORE)

    payload = _explain(client, hospital.id)
    perspectives = {p["perspective"]: p for p in payload["cross_check"]["perspectives"]}

    history = perspectives["history"]["top_band_eligibility"]
    assert history["decision"] == "ineligible"
    assert history["route"] == "history"
    assert history["threshold"] == PEER_Z_THRESHOLD_DEFAULT
    # The policy sentence is the shared gate's own text, not a paraphrase.
    assert history["policy"]
    assert "VERY_HIGH" in history["policy"]

    peer = perspectives["ownership"]["top_band_eligibility"]
    assert peer["decision"] == "undecided"
    assert peer["route"] == "peer"
    assert peer["policy"] and "peer" in peer["policy"].lower()
    # Undecided preserves the band the peer policy already allowed.
    assert perspectives["ownership"]["severity"] == LEVEL_VERY_HIGH


def test_the_diagnostic_row_carries_the_same_verdict_shape(db_session, client):
    hospital = db_session.query(Hospital).first()
    _history_values(db_session, hospital.id)
    _add_row(db_session, hospital.id)
    _add_alert(db_session, hospital.id, perspective="history")

    diagnostic = _explain(client, hospital.id)["cross_check"]["diagnostic"]
    verdict = diagnostic["top_band_eligibility"]
    assert verdict["decision"] == "ineligible"
    assert verdict["route"] == "history"
    assert verdict["band"] == LEVEL_HIGH
    assert verdict["stored_band"] == LEVEL_VERY_HIGH
    assert verdict["policy"]


def test_a_row_below_the_top_band_reports_not_applicable(db_session, client):
    hospital = db_session.query(Hospital).first()
    _history_values(db_session, hospital.id)
    _add_row(db_session, hospital.id)
    _add_alert(db_session, hospital.id, perspective="history",
               severity=LEVEL_HIGH)

    payload = _explain(client, hospital.id)
    verdict = payload["cross_check"]["perspectives"][0]["top_band_eligibility"]
    assert verdict["decision"] == "not_applicable"
    assert verdict["applicable"] is False
    assert verdict["eligible"] is None


def test_the_payload_reports_the_threshold_the_row_recorded(db_session, client):
    """A stored 3.5 is not replaced by the configured 2.5."""
    hospital = db_session.query(Hospital).first()
    _history_values(db_session, hospital.id)
    _add_row(db_session, hospital.id, provenance={"zscore_threshold": 3.5})
    _add_alert(db_session, hospital.id, perspective="history", threshold=3.5)

    payload = _explain(client, hospital.id)
    cc = payload["cross_check"]
    assert cc["perspectives"][0]["top_band_eligibility"]["threshold"] == 3.5
    assert cc["diagnostic"]["top_band_eligibility"]["threshold"] == 3.5


# ── The popup's wording (real source, executed) ─────────────────────────────

def _eligibility_note_source():
    """The module-scope helper, extracted with its balanced braces."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    start = src.index("function _eligibilityNote(")
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError("unterminated _eligibilityNote")


def _run_note(cases):
    code = (
        "globalThis.__ = function (s) { return s; };\n"
        + _function_source("_codeLabel") + "\n"
        + _eligibility_note_source()
        + "\nconst cases = " + json.dumps(cases) + ";\n"
        + "console.log(JSON.stringify(cases.map(function (c) {"
          " return _eligibilityNote(c); })));\n"
    )
    # Node writes UTF-8; decoding with the console's legacy code page turned
    # every non-ASCII character (the em dash in the peer sentences) into
    # mojibake, so the harness compares mojibake against the real sentence.
    out = subprocess.run(["node", "-e", code], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_note_has_one_sentence_per_state():
    assert _run_note([
        {"decision": "ineligible"},
        {"decision": "undecided"},
        {"decision": "eligible"},
    ]) == [
        "top band refused by the history window",
        "not judged",
        "history window supports the top band",
    ]


def test_not_applicable_and_missing_input_render_no_note():
    """Absent is not a fourth sentence: nothing is printed."""
    assert _run_note([
        {"decision": "not_applicable"},
        {},
        None,
        {"decision": "unknown-label"},
    ]) == ["", "", "", ""]


def test_undecided_is_never_silent_or_called_normal():
    note = _run_note([{"decision": "undecided"}])[0]
    assert note
    assert "normal" not in note.lower()
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "if (el.decision === 'undecided') return ''" not in src


def test_the_helper_is_module_scope_not_inside_the_render_body():
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert src.index("function _eligibilityNote") < src.index(
        "function _renderPayload")
    # And the cross-check block still guards against the absent state.
    assert "diagEl.decision !== 'not_applicable'" in src


def test_the_arabic_strings_exist_and_are_arabic():
    i18n = I18N_JS.read_text(encoding="utf-8")
    for key in ("top band refused by the history window", "not judged",
                "history window supports the top band", "Top band",
                "Diagnostics row top band"):
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"missing translation for {key!r}"
        value = match.group(1)
        assert re.search(r"[\u0600-\u06FF]", value), (key, value)


# ── Peer verdicts: the peer METHOD, never the history window ──────────────
# Rule B grades a peer claim on the comparison group's robust scales. Each
# sentence names its own REASON (both scales vs one usable scale are the same
# verdict with different evidence) and separates the statistical verdict from
# hospital comparability, which this policy never establishes.

PEER_NOTES = [
    ("eligible", "BOTH_SCALES_SUPPORT",
     "peer top band supported by both robust scales \u2014 "
     "statistical: eligible, comparability: not verified"),
    ("eligible", "ONLY_AVAILABLE_SCALE_SUPPORTS",
     "peer top band supported by the only usable robust scale \u2014 "
     "statistical: eligible, comparability: not verified"),
    ("undecided", "SCALES_DISAGREE",
     "peer robust scales disagree \u2014 "
     "statistical: not judged, comparability: not verified"),
    ("undecided", "ONLY_AVAILABLE_SCALE_REFUSES",
     "the only usable peer scale rejects the top band \u2014 "
     "statistical: not judged, comparability: not verified"),
    ("undecided", "DEFINITION_NOT_ESTABLISHABLE",
     "peer indicator definition not establishable \u2014 "
     "statistical: not judged, comparability: not verified"),
    ("insufficient_robust_scale", "NO_ROBUST_SCALE",
     "no usable robust scale in the peer group \u2014 "
     "statistical: insufficient robust scale, comparability: not verified"),
]


@pytest.mark.parametrize("decision,reason,expected", PEER_NOTES)
def test_a_peer_verdict_is_explained_by_its_own_reason(decision, reason,
                                                       expected):
    note = _run_note([{"route": "peer", "decision": decision,
                       "reason": reason}])[0]
    assert note == expected
    # The method named is the peer group's, never the hospital's window.
    assert "history" not in note.lower()
    # The two questions stay apart in every peer sentence.
    assert "statistical:" in note and "comparability:" in note


def test_comparability_is_read_from_the_payload_not_hardcoded():
    """The verdict carries the dimension; the sentence must not invent it."""
    base = {"route": "peer", "decision": "eligible",
            "reason": "BOTH_SCALES_SUPPORT"}
    verified, absent, unknown = _run_note([
        dict(base, group_comparability_status="verified"),
        base,
        dict(base, group_comparability_status="partially_evidenced"),
    ])
    assert verified.endswith("comparability: verified")
    # Missing evidence must never read as verified.
    assert absent.endswith("comparability: not verified")
    # An unseen status is made readable rather than swapped for a known label.
    assert unknown.endswith("comparability: partially evidenced")


def test_the_definition_tier_is_named_only_when_it_is_not_complete():
    base = {"route": "peer", "decision": "eligible",
            "reason": "BOTH_SCALES_SUPPORT"}
    complete, catalog, self_contained = _run_note([
        dict(base, definition_status="complete_from_row"),
        dict(base, definition_status="catalog_only"),
        dict(base, definition_status="self_contained_no_catalog"),
    ])
    assert "definition:" not in complete
    assert catalog.endswith("\u00b7 definition: catalog only")
    assert self_contained.endswith("\u00b7 definition: self contained no catalog")
    # Statistical eligibility still does not claim comparability.
    for note in (complete, catalog, self_contained):
        assert "comparability:" in note


def test_the_two_eligible_peer_verdicts_are_different_sentences():
    """Same verdict, different evidence: the reason decides the wording."""
    both, one = _run_note([
        {"route": "peer", "decision": "eligible",
         "reason": "BOTH_SCALES_SUPPORT"},
        {"route": "peer", "decision": "eligible",
         "reason": "ONLY_AVAILABLE_SCALE_SUPPORTS"},
    ])
    assert both != one
    assert "both robust scales" in both
    assert "only usable robust scale" in one


def test_a_missing_peer_reason_still_says_something_and_never_history():
    for case in ({"route": "peer", "decision": "undecided"},
                 {"route": "peer", "decision": "undecided",
                  "reason": "SOMETHING_NEW"}):
        note = _run_note([case])[0]
        assert note
        assert "history" not in note.lower()
        assert "normal" not in note.lower()
        assert "reason not reported" in note


def test_an_insufficient_scale_verdict_is_never_blank():
    """A row with no route stated is still surfaced, not silently dropped."""
    note = _run_note([{"decision": "insufficient_robust_scale",
                       "reason": "NO_ROBUST_SCALE"}])[0]
    assert note
    assert "insufficient robust scale" in note
    assert "history" not in note.lower()


HISTORY_NOTES = [
    ("ineligible", "top band refused by the history window"),
    ("undecided", "not judged"),
    ("eligible", "history window supports the top band"),
]


@pytest.mark.parametrize("decision,expected", HISTORY_NOTES)
def test_history_wording_is_unchanged_on_the_history_route(decision, expected):
    assert _run_note([{"route": "history", "decision": decision}])[0] == \
        expected


@pytest.mark.parametrize("decision,expected", HISTORY_NOTES)
def test_a_row_without_a_stated_route_keeps_the_history_wording(decision,
                                                               expected):
    """Legacy payloads carry no route; their behaviour must not change."""
    assert _run_note([{"decision": decision}])[0] == expected


def test_every_peer_sentence_has_an_arabic_translation():
    i18n = I18N_JS.read_text(encoding="utf-8")
    keys = [sentence.split(", comparability:")[0]
            for _decision, _reason, sentence in PEER_NOTES]
    keys.append("peer comparison not judged \u2014 statistical: reason not "
                "reported")
    for key in keys:
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"missing translation for {key!r}"
        assert re.search(r"[\u0600-\u06FF]", match.group(1)), key


def test_the_two_appended_dimensions_have_arabic_labels():
    i18n = I18N_JS.read_text(encoding="utf-8")
    for key in ("comparability", "definition", "not_verified", "verified",
                "catalog_only", "self_contained_no_catalog",
                "not_establishable", "Diagnostics row top band"):
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"missing translation for {key!r}"
        assert re.search(r"[\u0600-\u06FF]", match.group(1)), key


def test_the_diagnostic_verdict_names_the_record_it_describes():
    """Both verdicts are printed: the reader must know which one is which."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "__('Diagnostics row top band')" in src
    assert "'Diagnostics row top band':" in I18N_JS.read_text(encoding="utf-8")


# ── The policy sentences themselves (API text, English) ───────────────────

def test_the_peer_route_policy_names_rule_b_not_the_old_caps_only_rule():
    """The diagnostic block quotes this sentence for a peer top band."""
    from app.engine.anomaly import layered

    text = layered.TOP_BAND_ROUTE_POLICY[layered.ROUTE_PEER]
    assert "Rule B" in text
    assert "STATISTICAL" in text
    # Comparability is stated as a separate, unverified dimension.
    assert "not_verified" in text
    # Thin group and zero spread are named as caps of their own, not as Rule B.
    assert "thin-peer" in text and "zero-spread" in text
    assert "not Rule B's verdict" in text
    # And the peer band is no longer described as capped-only.
    assert "policies judge" not in text
    assert "no measurable spread;" not in text


def test_the_peer_eligibility_policy_separates_statistics_from_comparability():
    from app.engine.anomaly import layered

    text = layered.PEER_ELIGIBILITY_POLICY
    assert "Rule B" in text
    assert "STATISTICALLY" in text
    assert "insufficient_robust_scale" in text
    assert "definition must be established" in text
    assert "not_verified" in text
    # Never presented as proof of comparability or of data quality.
    assert "not evidence of" in text
    assert "comparability or of data quality" in text


def test_a_peer_note_never_reuses_the_cap_messages():
    """Thin peer and zero spread are their own explanations, not Rule B's."""
    notes = _run_note([{"route": "peer", "decision": decision,
                        "reason": reason}
                       for decision, reason, _expected in PEER_NOTES])
    for note in notes:
        low = note.lower()
        assert "no spread" not in low
        assert "no z" not in low
        assert "too few peer hospitals" not in low
        assert "capped" not in low


def test_the_cap_messages_remain_distinct_translations():
    i18n = I18N_JS.read_text(encoding="utf-8")
    spread = re.search(r"'no spread':\s*'([^']+)'", i18n)
    no_z = re.search(r"'no z':\s*'([^']+)'", i18n)
    assert spread and no_z
    assert spread.group(1) != no_z.group(1)


# ── The window judges the history route only ────────────
# A volume or raw-count claim is not graded by a history window, and a peer
# claim is graded by Rule B above; quoting the window for them described a
# method that never ran.

@pytest.mark.parametrize("route,decision", [
    ("volume", "ineligible"), ("volume", "eligible"),
    ("raw_count", "ineligible"), ("no_top_layer", "eligible"),
])
def test_another_route_is_never_attributed_to_the_history_window(route,
                                                                 decision):
    note = _run_note([{"route": route, "decision": decision}])[0]
    assert "history" not in note.lower()
    assert note == "not judged"


def test_the_two_peer_reasons_that_used_to_share_a_sentence_differ():
    """``PEER_POLICY`` says who owns the claim, not that evidence is missing.

    The same reason covers a legacy alert with no stored group and a
    Diagnostics row whose group IS stored but which deliberately does not
    apply Rule B; one sentence could not be true of both.
    """
    owned, missing = _run_note([
        {"route": "peer", "decision": "undecided", "reason": "PEER_POLICY"},
        {"route": "peer", "decision": "undecided",
         "reason": "NO_STORED_PEER_VALUES"},
    ])
    assert owned != missing
    assert "not recorded" not in owned
    assert "not recorded" in missing
    for note in (owned, missing):
        assert "history" not in note.lower()
        assert "statistical:" in note
        # No comparability clause: neither reason judged a stored group, so
        # "comparability: not verified" would report a comparison that never
        # ran. The status clause is printed only when the payload carries one.
        assert "comparability:" not in note


def test_every_remaining_peer_reason_has_an_arabic_sentence():
    i18n = I18N_JS.read_text(encoding="utf-8")
    keys = [
        "peer claim not graded on this record \u2014 statistical: not judged",
        "peer comparison group not recorded \u2014 statistical: not judged",
        "too few usable peer values \u2014 statistical: not judged",
        "current value missing \u2014 statistical: not judged",
    ]
    for key in keys:
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"missing translation for {key!r}"
        assert re.search(r"[\u0600-\u06FF]", match.group(1)), key


# ── The backend policy sentences, quoted in the popup ──────────────────────
# The popup prints the routed policy sentence the API sends. Those sentences
# are generated in Python, so the translation key has to equal the backend
# string byte for byte: a copy that drifts silently falls back to English.

def test_the_peer_policy_sentences_are_translated_without_drift():
    from app.engine.anomaly import layered

    i18n = I18N_JS.read_text(encoding="utf-8")
    for text in (layered.TOP_BAND_ROUTE_POLICY[layered.ROUTE_PEER],
                 layered.PEER_ELIGIBILITY_POLICY):
        key = text.replace("'", "\\'")
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"no translation for the peer policy {text[:50]!r}..."
        arabic = match.group(1)
        assert re.search(r"[\u0600-\u06FF]", arabic)
        assert arabic != text
        # A translation has to keep the machine identifiers a reviewer checks
        # against the code and the alert record (the Arabic itself renders the
        # rule name as "القاعدة B", so only the literal tokens are pinned).
        for token in ("VERY_HIGH", "insufficient_robust_scale"):
            if token in text:
                assert token in arabic, token


def test_the_policy_sentence_is_looked_up_through_the_translator():
    """A raw print of the English sentence would leave Arabic users behind."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "_policyLabel(cc.policy)" in src
    assert "_policyLabel(diagEl.policy)" in src
    assert "+ cc.policy" not in src and "+ diagEl.policy" not in src


def test_both_cap_policy_sentences_have_arabic():
    """The two approved cap sentences are translated, not quoted in English.

    THIN_PEER_POLICY is formatted with a peer count, so its KEY is the template
    and the placeholder has to survive into the Arabic string the popup builds.
    """
    from app.engine.anomaly import layered

    i18n = I18N_JS.read_text(encoding="utf-8")
    for text in (layered.ZERO_SPREAD_POLICY, layered.THIN_PEER_POLICY):
        key = text.replace("'", "\\'")
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"no Arabic for the cap policy {text[:45]!r}..."
        arabic = match.group(1)
        assert re.search(r"[\u0600-\u06FF]", arabic), text
        assert "HIGH" in arabic, "the capped band stays a machine identifier"
        if "{peers}" in text:
            assert "{peers}" in arabic, "the formatter's placeholder must survive"


def test_a_missing_peer_group_is_not_an_unverified_comparison():
    """No stored group and an unverified comparison are two different claims.

    The gate states ``group_comparability_status`` only when it actually judged
    a stored group; a claim graded on another record carries no comparability
    field at all, which is why the popup must not default one in.
    """
    from app.engine.quality_alerts import top_band_gate

    _level, _cap, no_group = top_band_gate("VERY_HIGH", perspective="type")
    assert no_group["reason"] == "PEER_POLICY"
    assert "group_comparability_status" not in no_group

    _level, _cap, judged = top_band_gate(
        "VERY_HIGH", perspective="type", current=10.0,
        threshold=2.5,
        peer_values={"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0},
        peer_definition={"formula": "a/b", "numerator": 1,
                         "denominator": 2, "catalog_resolved": False},
    )
    assert judged["group_comparability_status"] == "not_verified"


def test_the_popup_hides_the_comparability_clause_when_no_group_was_stored():
    """A missing group must not be printed as an unverified comparison."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "const no_group = el.reason === 'NO_STORED_PEER_VALUES'" in src
    assert "|| 'not_verified'" not in src, \
        "a missing status must not be defaulted into the sentence"
    assert "else if (!no_group && el.reason)" in src


# ── Peer wording never borrows the history window's language ────────────────

def test_no_peer_sentence_attributes_the_band_to_the_history_window():
    """Rule B grades a peer claim, so no peer sentence may quote the window.

    Every peer sentence ends in its statistical verdict (``— statistical: …``),
    which is the marker used here: the route policy's own disclaimer — that the
    window's dispersion never decides a peer claim — does not carry it, so the
    sentence that says a peer claim is NOT a window claim is not caught.
    """
    i18n = I18N_JS.read_text(encoding="utf-8")
    peer_lines = [line for line in i18n.splitlines() if "statistical:" in line]
    assert peer_lines, "the peer sentences must be translated"
    for line in peer_lines:
        assert "history window" not in line, line


def test_the_history_window_wording_is_unchanged():
    """The history route keeps its own three sentences, untouched."""
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert "'top band refused by the history window'" in src
    assert "'history window supports the top band'" in src
    assert "__('not judged')" in src


# ── Step 6B: stored Quality Alerts peer perspectives ──────────────────────
# The cross-check already finds the same identity (hospital + month +
# canonical formula). These tests pin the extra collection that lists the
# peer perspectives stored on that identity, one card per record, with Rule B
# read from BOTH the verdict and the reason code.

STEP_6A_CASES = [
    # (analysis code, month, [(alert id, perspective, current, peer values,
    #                          verdict, reason)])
    ("6.d", "2026-07", [
        (6348, "ownership", 17.0, [1.0, 5.0, 0.0, 1.0, 2.0, 4.0, 6.0],
         "eligible", "BOTH_SCALES_SUPPORT"),
    ]),
    ("8.b", "2026-04", [
        (4007, "governorate", 12.0, [0.0, 2.0, 3.0, 5.0],
         "eligible", "BOTH_SCALES_SUPPORT"),
    ]),
    ("2.l", "2026-07", [
        (6243, "ownership", 13.0, [0.0, 1.0, 2.0, 0.0, 3.0, 0.0],
         "eligible", "BOTH_SCALES_SUPPORT"),
        (6245, "governorate", 13.0, [0.0, 1.0, 3.0, 0.0],
         "eligible", "BOTH_SCALES_SUPPORT"),
    ]),
    ("9", "2026-06", [
        (5679, "type", 8.0, [0.0, 0.0, 0.0, 1.0],
         "eligible", "ONLY_AVAILABLE_SCALE_SUPPORTS"),
    ]),
    ("13", "2026-07", [
        (6090, "type", 344.0, [73.0, 100.0, 152.0, 85.0, 187.0],
         "undecided", "SCALES_DISAGREE"),
    ]),
    ("2.i", "2026-07", [
        (6224, "type", 17.0, [2.0, 3.0, 5.0, 5.0, 5.0],
         "eligible", "ONLY_AVAILABLE_SCALE_SUPPORTS"),
    ]),
    ("6.d", "2026-08", [
        (878, "type", 12.0, [2.0, 1.0, 2.0, 6.0, 2.0, 1.0],
         "eligible", "BOTH_SCALES_SUPPORT"),
    ]),
]


def _peer_evidence(code, month, perspective, values, threshold=2.5):
    """Stored ``evidence.comparison_policy`` for one peer alert."""
    return {
        "z_threshold": threshold,
        "comparison_policy": {
            "perspective_scope": "stratified",
            "peer": {
                "policy_version": "2026-10-24.1",
                "group": "stratified:" + perspective,
                "group_label": perspective,
                "month": month,
                "min_peers": 2,
                "eligible_count": len(values),
                "peer_ids": [1000 + i for i in range(len(values))],
                "values": {str(1000 + i): float(v)
                           for i, v in enumerate(values)},
            },
        },
        "canonical": {"key": f"test-{code}-{month}", "code": code,
                      "registered_codes": [code]},
    }


def _add_case_alert(db, hospital_id, *, alert_id, month, code, perspective,
                    current, values, severity=LEVEL_VERY_HIGH,
                    with_peer_evidence=True):
    evidence = (_peer_evidence(code, month, perspective, values)
                if with_peer_evidence else {
                    "z_threshold": 2.5,
                    "canonical": {"key": f"test-{code}-{month}", "code": code,
                                  "registered_codes": [code]},
                })
    alert = QualityAlert(
        id=alert_id, hospital_id=hospital_id, month=month,
        perspective=perspective, indicator_code=code,
        indicator_name="Test indicator", unit="%", formula=None,
        severity=severity, score=1.0, method=METHOD_PEER_ZSCORE,
        current_value=current, baseline_value=None, z_score=None,
        peer_count=(len(values) if values is not None else 5),
        status="New", active=True, direction="none",
        interpretation="statistical_only", confidence="high",
        evidence=evidence,
    )
    db.add(alert)
    db.commit()
    return alert


def _add_case_row(db, hospital_id, *, month, code):
    row = LayeredOutlierResult(
        hospital_id=hospital_id, analysis_code=code, month=month,
        raw_value=24.0, previous_value=10.0, denominator=100.0, rate=24.0,
        raw_value_outlier_score=1.0, rate_outlier_score=1.0,
        historical_outlier_score=1.0, volume_anomaly_score=0.0,
        outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
        outlier_method=METHOD_ZSCORE, interpretation="statistical_only",
        investigation_route="none",
        history_provenance={"values": list(WIDE_WINDOW)},
        classification_provenance={},
    )
    db.add(row)
    db.commit()
    return row


def _explain_case(client, hospital_id, month, code):
    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={hospital_id}"
        f"&month={month}&indicator_code={code}")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("code,month,alerts", STEP_6A_CASES)
def test_all_eight_step_6a_peer_perspectives_are_represented(
        db_session, client, code, month, alerts):
    """7 identities / 8 perspectives, each with its own stored verdict."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month=month, code=code)
    for alert_id, perspective, current, values, _verdict, _reason in alerts:
        _add_case_alert(db_session, hospital.id, alert_id=alert_id,
                        month=month, code=code, perspective=perspective,
                        current=current, values=values)

    cc = _explain_case(client, hospital.id, month, code)["cross_check"]
    got = [(p["alert_id"], p["perspective"], p["verdict"], p["reason_code"])
           for p in cc["peer_perspectives"]]
    expected = [(a[0], a[1], a[4], a[5]) for a in alerts]
    assert got == expected


def test_h22_two_perspectives_are_two_separate_cards_in_required_order(
        db_session, client):
    """A. h22 / 2026-07 / 2.l: exactly #6243 then #6245, never merged."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month="2026-07", code="2.l")
    _add_case_alert(db_session, hospital.id, alert_id=6243,
                    month="2026-07", code="2.l", perspective="ownership",
                    current=13.0, values=[0.0, 1.0, 2.0, 0.0, 3.0, 0.0])
    _add_case_alert(db_session, hospital.id, alert_id=6245,
                    month="2026-07", code="2.l", perspective="governorate",
                    current=13.0, values=[0.0, 1.0, 3.0, 0.0])
    # A lower-band perspective is stored too, but it is not a top-band peer
    # claim and must not become a third card.
    _add_case_alert(db_session, hospital.id, alert_id=6242,
                    month="2026-07", code="2.l", perspective="type",
                    current=13.0, values=[0.0, 1.0, 2.0, 0.0, 3.0, 0.0],
                    severity=LEVEL_HIGH)

    cc = _explain_case(client, hospital.id, "2026-07", "2.l")["cross_check"]
    assert [(p["alert_id"], p["perspective"])
            for p in cc["peer_perspectives"]] == [
        (6243, "ownership"), (6245, "governorate")]
    # The cross-check list still names the stored HIGH type perspective; only
    # the two qualifying top-band peer claims become cards.
    assert len(cc["perspectives"]) == 3

    html = _run_peer_render(cc)
    assert html.count("Alert #") == 2
    assert "Ownership peers" in html
    assert "Regional peers (governorate)" in html
    assert html.index("Ownership peers") < html.index(
        "Regional peers (governorate)")
    assert "#6242" not in html
    assert "Quality Alerts \u2014 Peer Perspectives" in html
    assert "Diagnostics shows this analysis row" in html
    assert "does not imply that the Diagnostics historical assessment" in html
    assert ("Only qualifying top-band peer perspectives are shown as cards."
            in html)


def test_h36_undecided_never_reads_as_confirmed_or_eligible(db_session,
                                                            client):
    """B. h36 / 2026-07 / 13: #6090 is undecided and says so."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month="2026-07", code="13")
    _add_case_alert(db_session, hospital.id, alert_id=6090,
                    month="2026-07", code="13", perspective="type",
                    current=344.0, values=[73.0, 100.0, 152.0, 85.0, 187.0])

    cc = _explain_case(client, hospital.id, "2026-07", "13")["cross_check"]
    card = cc["peer_perspectives"][0]
    assert card["alert_id"] == 6090
    assert card["verdict"] == "undecided"
    assert card["reason_code"] == "SCALES_DISAGREE"
    assert card["mad"] == {"value": 27.0, "band": "VERY_HIGH",
                           "usable": True}
    assert card["iqr"] == {"value": 67.0, "band": "MODERATE",
                           "usable": True}

    html = _run_peer_render(cc)
    assert "Not confirmed \u2014 the available robust scales disagree." in html
    assert "Confirmed \u2014" not in html
    assert "eligible" not in html.lower()


def test_h36_zero_heavy_case_names_iqr_as_the_only_usable_scale(
        db_session, client):
    """C. h36 / 2026-06 / 9: #5679, zero_share 0.75, only IQR supports."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month="2026-06", code="9")
    _add_case_alert(db_session, hospital.id, alert_id=5679,
                    month="2026-06", code="9", perspective="type",
                    current=8.0, values=[0.0, 0.0, 0.0, 1.0])

    cc = _explain_case(client, hospital.id, "2026-06", "9")["cross_check"]
    card = cc["peer_perspectives"][0]
    assert card["alert_id"] == 5679
    assert card["zero_share"] == 0.75
    assert card["zero_share_warning"] is True
    assert card["reason_code"] == "ONLY_AVAILABLE_SCALE_SUPPORTS"
    assert card["mad"] == {"value": 0.0, "band": None, "usable": False}
    assert card["iqr"] == {"value": 0.25, "band": "VERY_HIGH",
                           "usable": True}
    # The stored evidence does not record which scales supported the result.
    assert card["scales_supporting"] is None

    html = _run_peer_render(cc)
    assert "MAD: 0 \u00b7 unusable" in html
    assert "IQR: 0.25 (Very high) \u00b7 usable" in html
    assert "Scales supporting: unavailable" in html
    assert ("75% of peer values are zero. Review the source-data semantics."
            in html)


def test_h36_mad_unusable_only_iqr_supports(db_session, client):
    """D. h36 / 2026-07 / 2.i: #6224, MAD unusable, only IQR supports."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month="2026-07", code="2.i")
    _add_case_alert(db_session, hospital.id, alert_id=6224,
                    month="2026-07", code="2.i", perspective="type",
                    current=17.0, values=[2.0, 3.0, 5.0, 5.0, 5.0])

    cc = _explain_case(client, hospital.id, "2026-07", "2.i")["cross_check"]
    card = cc["peer_perspectives"][0]
    assert card["alert_id"] == 6224
    assert card["reason_code"] == "ONLY_AVAILABLE_SCALE_SUPPORTS"
    assert card["mad"] == {"value": 0.0, "band": None, "usable": False}
    assert card["iqr"] == {"value": 2.0, "band": "VERY_HIGH",
                           "usable": True}
    assert card["zero_share"] == 0.0
    assert card["zero_share_warning"] is False

    html = _run_peer_render(cc)
    assert "MAD: 0 \u00b7 unusable" in html
    assert "IQR: 2 (Very high) \u00b7 usable" in html
    assert "of peer values are zero" not in html


def test_missing_peer_evidence_is_unavailable_not_inferred(db_session,
                                                           client):
    """E. No stored group: no verdict, reason, scales or comparability."""
    hospital = db_session.query(Hospital).first()
    _add_case_row(db_session, hospital.id, month="2026-07", code="2.l")
    _add_case_alert(db_session, hospital.id, alert_id=9999,
                    month="2026-07", code="2.l", perspective="ownership",
                    current=13.0, values=None, with_peer_evidence=False)

    cc = _explain_case(client, hospital.id, "2026-07", "2.l")["cross_check"]
    card = cc["peer_perspectives"][0]
    assert card["alert_id"] == 9999
    assert card["peer_count"] == 5  # stored on the row, not recomputed
    assert card["current"] == 13.0
    assert card["verdict"] is None
    assert card["reason_code"] is None
    assert card["mad"] == {"value": None, "band": None, "usable": None}
    assert card["iqr"] == {"value": None, "band": None, "usable": None}
    assert card["scales_supporting"] is None
    assert card["group_comparability_status"] is None
    assert card["zero_share"] is None
    assert card["zero_share_warning"] is None
    assert "peer_eligibility" not in card

    html = _run_peer_render(cc)
    for text in ("Rule B verdict: unavailable", "Reason: unavailable",
                 "MAD: unavailable", "IQR: unavailable",
                 "Scales supporting: unavailable",
                 "Comparability: unavailable", "Zero share: unavailable"):
        assert text in html
    assert "eligible" not in html.lower()


def test_identity_matching_never_crosses_hospital_month_or_formula(
        db_session, client):
    """F. Only the same hospital + month + canonical formula is paired."""
    hospital = db_session.query(Hospital).first()
    other = Hospital(name="Other Hospital", region="Region C")
    db_session.add(other)
    db_session.commit()
    _add_case_row(db_session, hospital.id, month="2026-07", code="2.l")
    _add_case_alert(db_session, hospital.id, alert_id=9001,
                    month="2026-07", code="2.l", perspective="ownership",
                    current=13.0, values=[0.0, 1.0, 2.0, 0.0, 3.0, 0.0])
    # Same hospital, other month.
    _add_case_alert(db_session, hospital.id, alert_id=9002,
                    month="2026-06", code="2.l", perspective="governorate",
                    current=13.0, values=[0.0, 1.0, 3.0, 0.0])
    # Same hospital and month, other canonical formula.
    _add_case_alert(db_session, hospital.id, alert_id=9003,
                    month="2026-07", code="13", perspective="type",
                    current=344.0, values=[73.0, 100.0, 152.0, 85.0, 187.0])
    # Other hospital, same month and formula.
    _add_case_alert(db_session, other.id, alert_id=9004,
                    month="2026-07", code="2.l", perspective="type",
                    current=13.0, values=[0.0, 1.0, 2.0, 0.0, 3.0, 0.0])

    cc = _explain_case(client, hospital.id, "2026-07", "2.l")["cross_check"]
    ids = [p["alert_id"] for p in cc["peer_perspectives"]]
    assert ids == [9001]
    assert len(ids) == len(set(ids))


def test_peer_perspectives_leave_the_diagnostics_row_unchanged(db_session,
                                                               client):
    """G. Presentation only: stored band, historical gate and row are intact."""
    from app.engine.anomaly.layered import row_very_high_eligibility

    hospital = db_session.query(Hospital).first()
    row = _add_case_row(db_session, hospital.id, month="2026-07", code="2.l")
    _add_case_alert(db_session, hospital.id, alert_id=6243,
                    month="2026-07", code="2.l", perspective="ownership",
                    current=13.0, values=[0.0, 1.0, 2.0, 0.0, 3.0, 0.0])
    before = (row.outlier_level, row.outlier_type, row.historical_outlier_score,
              row.peer_outlier_score, row.peer_count,
              row.history_provenance, row.classification_provenance)

    cc = _explain_case(client, hospital.id, "2026-07", "2.l")["cross_check"]
    db_session.expire_all()
    stored = (db_session.query(LayeredOutlierResult)
              .filter(LayeredOutlierResult.hospital_id == hospital.id,
                      LayeredOutlierResult.month == "2026-07",
                      LayeredOutlierResult.analysis_code == "2.l")
              .one())
    after = (stored.outlier_level, stored.outlier_type,
             stored.historical_outlier_score, stored.peer_outlier_score,
             stored.peer_count, stored.history_provenance,
             stored.classification_provenance)
    assert after == before
    # The stored VERY_HIGH row is still stored VERY_HIGH; the existing
    # historical gate still resolves it to HIGH with its own reason.
    assert stored.outlier_level == LEVEL_VERY_HIGH
    assert cc["diagnostic"]["level"] == LEVEL_VERY_HIGH
    assert cc["diagnostic"]["type"] == "HISTORICAL_ANOMALY"
    assert (cc["diagnostic"]["top_band_eligibility"]
            == row_very_high_eligibility(stored))
    gate = cc["diagnostic"]["top_band_eligibility"]
    assert gate["decision"] == "ineligible"
    assert gate["reason"] == "DISPERSION_BAND_BELOW_VERY_HIGH"
    assert gate["band"] == LEVEL_HIGH


# ── Step 6B: the peer-perspective renderer (real source, executed) ────────

def _function_source(name):
    src = EXPLAIN_JS.read_text(encoding="utf-8")
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


def _run_peer_render(cross_check):
    code = (
        "globalThis.__ = function (s) { return s; };\n"
        "globalThis.esc = function (s) { return String(s); };\n"
        "globalThis._sectionTitle = function (t) { return '[' + t + ']'; };\n"
        + _function_source("_codeLabel") + "\n"
        + _function_source("_peerPerspectiveReason") + "\n"
        + _function_source("_peerScaleLine") + "\n"
        + _function_source("_renderPeerPerspectives") + "\n"
        + "const cc = " + json.dumps(cross_check) + ";\n"
        + "console.log(JSON.stringify(_renderPeerPerspectives(cc)));\n"
    )
    out = subprocess.run(["node", "-e", code], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_peer_perspective_reason_uses_verdict_and_reason_code():
    """Both fields decide the wording; a verdict alone is never a claim."""
    cases = [
        ({"verdict": "eligible", "reason_code": "BOTH_SCALES_SUPPORT"},
         "Confirmed \u2014 both robust scales support the top band."),
        ({"verdict": "eligible",
          "reason_code": "ONLY_AVAILABLE_SCALE_SUPPORTS"},
         "Confirmed \u2014 the only usable robust scale supports the top band."),
        ({"verdict": "undecided", "reason_code": "SCALES_DISAGREE"},
         "Not confirmed \u2014 the available robust scales disagree."),
        ({"verdict": "undecided",
          "reason_code": "ONLY_AVAILABLE_SCALE_REFUSES"},
         "Not confirmed \u2014 the only usable scale does not support the top band."),
        ({"verdict": "undecided",
          "reason_code": "DEFINITION_NOT_ESTABLISHABLE"},
         "Not confirmed \u2014 the indicator definition cannot be established."),
        ({"verdict": "insufficient_robust_scale",
          "reason_code": "NO_ROBUST_SCALE"},
         "Not confirmed \u2014 the peer group has no usable robust scale."),
        ({"verdict": "undecided", "reason_code": "NO_STORED_PEER_VALUES"},
         "Not confirmed \u2014 no stored peer values are available."),
        ({"verdict": "undecided", "reason_code": "INSUFFICIENT_PEER_VALUES"},
         "Not confirmed \u2014 too few usable peer values are available."),
        ({"verdict": "undecided", "reason_code": "CURRENT_VALUE_MISSING"},
         "Not confirmed \u2014 the current value is missing."),
        # No field may be inferred from the other one.
        ({"verdict": "eligible"}, "unavailable"),
        ({"reason_code": "BOTH_SCALES_SUPPORT"}, "unavailable"),
        ({"verdict": "undecided", "reason_code": "BOTH_SCALES_SUPPORT"},
         "Not interpreted \u2014 the policy verdict and reason do not agree."),
    ]
    code = (
        "globalThis.__ = function (s) { return s; };\n"
        + _function_source("_peerPerspectiveReason") + "\n"
        + "const cases = " + json.dumps([c[0] for c in cases]) + ";\n"
        + "console.log(JSON.stringify(cases.map(function (c) {"
          " return _peerPerspectiveReason(c); })));\n"
    )
    out = subprocess.run(["node", "-e", code], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [
        c[1] for c in cases]


def test_peer_perspective_block_is_module_scope_and_called_once():
    src = EXPLAIN_JS.read_text(encoding="utf-8")
    assert src.index("function _renderPeerPerspectives") < src.index(
        "function _renderPayload")
    assert "html += _renderPeerPerspectives(cc);" in src


def test_peer_perspective_translations_exist_in_both_languages():
    """H. Every new key is translated; perspective names already are."""
    i18n = I18N_JS.read_text(encoding="utf-8")
    keys = [
        "Quality Alerts \u2014 Peer Perspectives",
        "Diagnostics shows this analysis row and its own analytical layers. "
        "Quality Alerts may contain separate peer perspectives for the same "
        "hospital, month, and indicator. These are different analytical "
        "records evaluated under different policies. A peer result at the very high band "
        "does not imply that the Diagnostics historical assessment is also at that band.",
        "Alert", "Rule B verdict", "Reason", "eligible", "undecided",
        "ineligible", "insufficient_robust_scale", "not_applicable",
        "Confirmed \u2014 both robust scales support the top band.",
        "Confirmed \u2014 the only usable robust scale supports the top band.",
        "Not confirmed \u2014 the available robust scales disagree.",
        "Not confirmed \u2014 the only usable scale does not support the top band.",
        "Not confirmed \u2014 the indicator definition cannot be established.",
        "Not confirmed \u2014 the peer group has no usable robust scale.",
        "Not confirmed \u2014 both usable robust scales refuse the top band.",
        "Not confirmed \u2014 no stored peer values are available.",
        "Not confirmed \u2014 too few usable peer values are available.",
        "Not confirmed \u2014 the current value is missing.",
        "Not interpreted \u2014 the policy verdict and reason do not agree.",
        "Not interpreted \u2014 the policy reason is not recognised.",
        "unavailable", "usable", "unusable", "MAD", "IQR",
        "Scales supporting", "Comparability", "Zero share",
        "of peer values are zero. Review the source-data semantics.",
    ]
    for key in keys:
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(key), i18n)
        assert match, f"missing translation for {key!r}"
        assert re.search(r"[\u0600-\u06FF]", match.group(1)), key
    for label in ("Ownership peers", "Similar hospitals (type)",
                  "Regional peers (governorate)", "All hospitals"):
        match = re.search(r"'%s':\s*'([^']+)'" % re.escape(label), i18n)
        assert match and re.search(r"[\u0600-\u06FF]", match.group(1)), label
