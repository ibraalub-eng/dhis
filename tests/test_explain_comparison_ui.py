"""Step 10D-5 UI — the Explain popup renders comparison IDENTITY, not labels.

The renderer half executes the REAL ``_renderComparisonEvidence`` helper from
``static/js/explain.js`` in node (the repository's static-UI convention). The
tests pin the distinctions the block exists to make:

* two perspective labels over one peer set are ONE comparison;
* nested / overlapping / disjoint peer sets are named as such, never as
  "independent comparisons" and never as clinical confirmation;
* temporal (history) evidence is its own section and never a peer count;
* unknown, invalid, truncated, conflicting and mixed-policy evidence stays
  visible beside a valid comparison;
* every sentence the block can emit exists in Arabic with no English words.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

EXPLAIN_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "explain.js"
I18N_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "i18n.js"

HELPERS = ("_codeLabel", "_cmpRelationWord", "_cmpList", "_cmpSentence",
           "_cmpRow", "_cmpLine", "_renderComparisonEvidence")


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


def _render(evidence, lang="en", labels=None):
    """Render the block with the shipped helper and a dictionary-backed ``__``."""
    dictionary = dict(labels or {})
    prelude = (
        "const AR = " + json.dumps(dictionary) + ";\n"
        "const currentLang = " + json.dumps(lang) + ";\n"
        "globalThis.__ = function (s) { return (currentLang === 'ar' && AR[s]) || s; };\n"
        "globalThis.esc = function (s) { return String(s); };\n"
        "globalThis._sectionTitle = function (t) { return '[' + t + ']'; };\n"
    )
    code = (prelude
            + "\n".join(_function_source(name) for name in HELPERS)
            + "\nconst ev = " + json.dumps(evidence) + ";\n"
            + "console.log(JSON.stringify("
              "_renderComparisonEvidence({comparison_evidence: ev})));\n")
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


def _comparison(**overrides):
    entry = {
        "identity": "abc123def456",
        "identity_hash": "abc123def4567890",
        "source": "peer_policy",
        "peer_count": 6,
        "peer_ids": [1, 2, 3, 4, 5, 6],
        "perspectives": ["ownership"],
        "perspective_labels": ["Ownership peers"],
        "perspective_rows": 1,
        "alert_ids": [6243],
        "policy_versions": ["2026-10-24.1"],
        "effective_severity": "VERY_HIGH",
        "stored_severities": ["VERY_HIGH"],
        "relationships": [],
        "evidence_conflict": False,
        "conflict_fields": [],
    }
    entry.update(overrides)
    return entry


def _evidence(*, comparisons, duplicate=0, peer_rows=None, temporal=(),
              unreadable=(), **overrides):
    present_temporal = list(temporal)
    evidence = {
        "perspective_rows": ((peer_rows if peer_rows is not None
                              else sum(c["perspective_rows"]
                                       for c in comparisons))
                             + len(present_temporal) + len(unreadable)),
        "peer_rows": (peer_rows if peer_rows is not None
                      else sum(c["perspective_rows"] for c in comparisons)),
        "distinct_peer_comparisons": len(comparisons),
        "duplicate_perspective_rows": duplicate,
        "comparisons": comparisons,
        "temporal_rows": len(present_temporal),
        "temporal": present_temporal,
        "temporal_present": bool(present_temporal),
        "temporal_state": (
            "valid" if any(t["state"] == "valid" for t in present_temporal)
            else "unknown") if present_temporal else None,
        "unknown_rows": sum(1 for item in unreadable
                            if item["state"] != "invalid"),
        "unknown_evidence_present": any(item["state"] != "invalid"
                                        for item in unreadable),
        "invalid_rows": sum(1 for item in unreadable
                            if item["state"] == "invalid"),
        "invalid_evidence_present": any(item["state"] == "invalid"
                                        for item in unreadable),
        "truncated_evidence_present": any(
            item["reason"] in ("truncated_nested_peer_ids",
                               "top_level_truncation_possible",
                               "incomplete_top_level_peer_ids")
            for item in unreadable),
        "evidence_conflict": any(c["evidence_conflict"] for c in comparisons),
        "policy_mixed": False,
        "policy_versions": [],
        "relationships": [],
        "unreadable": list(unreadable),
    }
    evidence.update(overrides)
    return evidence


# ── A. Labels are not comparisons ──────────────────────────────────────────

def test_identical_peer_sets_under_two_labels_are_one_comparison():
    html = _render(_evidence(
        comparisons=[_comparison(perspectives=["all", "facility_type"],
                                 perspective_labels=["All hospitals",
                                                     "Facility type"],
                                 perspective_rows=2,
                                 alert_ids=[7001, 7002])],
        duplicate=1))
    assert "Peer comparison 1" in html
    assert "Peer comparison 2" not in html
    assert "All hospitals" in html and "Facility type" in html
    assert "counted once" in html


def test_three_perspectives_over_two_peer_sets_say_so():
    first = _comparison(perspectives=["type", "facility_type"],
                        perspective_labels=["Type peers", "Facility type"],
                        perspective_rows=2, alert_ids=[1, 2])
    second = _comparison(identity="123456789abc", perspective_labels=["Ownership peers"],
                         identity_hash="123456789abcdef", peer_ids=[7, 8, 9, 10],
                         alert_ids=[3])
    html = _render(_evidence(comparisons=[first, second], duplicate=1))
    assert "Peer comparison 1" in html and "Peer comparison 2" in html
    assert "distinct peer comparisons" in html
    assert "add no second comparison" in html


def test_no_readable_peer_group_is_stated_not_invented():
    html = _render(_evidence(
        comparisons=[],
        unreadable=[{"alert_id": 1, "perspective": "ownership",
                     "label": "Ownership peers", "state": "unknown",
                     "reason": "no_stored_peer_ids"}]))
    assert "no peer comparison is described here" in html
    assert "Peer comparison 1" not in html
    assert "Unknown evidence" in html


# ── B. Relationship wording ───────────────────────────────────────────────

def _pair(kind, shared):
    left = _comparison(perspective_labels=["Type peers"],
                       relationships=[{"identity": "123456789abc",
                                       "relationship": kind,
                                       "shared_peers": shared}])
    right = _comparison(identity="123456789abc",
                        identity_hash="123456789abcdef",
                        perspective_labels=["Ownership peers"],
                        peer_ids=[7, 8, 9, 10],
                        relationships=[{"identity": "abc123def456",
                                        "relationship": kind,
                                        "shared_peers": shared}])
    return _evidence(comparisons=[left, right])


def test_nested_overlapping_and_disjoint_use_peer_set_terms():
    nested = _render(_pair("nested", 4))
    overlapping = _render(_pair("overlapping", 2))
    disjoint = _render(_pair("disjoint", 0))
    assert "Nested peer groups" in nested and "shared hospitals" in nested
    assert "Overlapping peer groups" in overlapping
    assert "Disjoint peer groups" in disjoint
    for html in (nested, overlapping, disjoint):
        lowered = html.lower()
        for banned in ("independent", "clinical", "confirmed"):
            assert banned not in lowered, banned


def test_unknown_relationship_is_named_not_guessed():
    html = _render(_pair("unreadable", 0))
    assert "Unknown relationship" in html


# ── C. Temporal evidence is separate ──────────────────────────────────────

def test_precision_history_is_its_own_section_and_never_a_peer_count():
    html = _render(_evidence(
        comparisons=[_comparison()],
        temporal=[{"alert_id": 9, "perspective": "history",
                   "label": "History", "state": "valid", "reason": None,
                   "observations": 12, "band": "HIGH",
                   "stored_severity": "HIGH"}]))
    assert "Temporal evidence (history)" in html
    assert "Observations: 12" in html
    assert "Peer comparison 2" not in html
    assert "is never counted as a peer comparison" in html
    # The history row is not folded into the peer comparison's label list.
    assert "History" not in html.split("Temporal evidence (history)")[0]


def test_history_without_a_readable_window_reads_as_unknown():
    html = _render(_evidence(
        comparisons=[],
        temporal=[{"alert_id": 9, "perspective": "history",
                   "label": "History", "state": "unknown",
                   "reason": "no_readable_history_window", "observations": 0,
                   "band": "HIGH", "stored_severity": "HIGH"}]))
    assert "no readable window" in html
    assert "Unknown evidence" in html
    assert "Peer comparison 1" not in html


# ── D. Evidence quality stays visible ─────────────────────────────────────

def test_unknown_and_invalid_evidence_survive_beside_a_valid_comparison():
    html = _render(_evidence(
        comparisons=[_comparison()],
        unreadable=[
            {"alert_id": 2, "perspective": "governorate",
             "label": "Regional peers", "state": "unknown",
             "reason": "top_level_truncation_possible"},
            {"alert_id": 3, "perspective": "type", "label": "Type peers",
             "state": "invalid", "reason": "peer_count_mismatch"},
        ]))
    assert "Peer comparison 1" in html
    assert "Unknown evidence" in html
    assert "Invalid evidence" in html
    assert "Truncated peer evidence" in html
    assert "incomplete" in html
    assert "contradicts itself" in html


def test_conflicting_statistics_are_one_comparison_not_two():
    html = _render(_evidence(
        comparisons=[_comparison(perspective_labels=["Type peers",
                                                     "Ownership peers"],
                                 perspectives=["type", "ownership"],
                                 perspective_rows=2,
                                 evidence_conflict=True,
                                 conflict_fields=["current_value"])],
        duplicate=1))
    assert "Peer comparison 2" not in html
    assert "Conflicting statistics" in html
    assert "current value" in html
    assert "not a second comparison" in html


def test_mixed_policy_versions_are_provenance_not_a_second_sample():
    html = _render(_evidence(
        comparisons=[_comparison(policy_versions=["2026-06-01.1",
                                                  "2026-10-24.1"])],
        policy_mixed=True,
        policy_versions=["2026-06-01.1", "2026-10-24.1"]))
    assert "Mixed policy versions" in html
    assert "2026-06-01.1" in html and "2026-10-24.1" in html
    assert "provenance" in html
    assert "Peer comparison 2" not in html


def test_block_omitted_when_payload_has_no_comparison_evidence():
    for cc in ({}, {"comparison_evidence": None}):
        code = ("const currentLang = 'en';\n"
                "globalThis.__ = function (s) { return s; };\n"
                "globalThis.esc = function (s) { return String(s); };\n"
                + _function_source("_renderComparisonEvidence")
                + "\nconsole.log(JSON.stringify(_renderComparisonEvidence("
                + json.dumps(cc) + ")));\n")
        assert json.loads(_node(code)) == ""


def test_cross_check_payload_renders_the_block():
    src = _src()
    assert "html += _renderComparisonEvidence(cc);" in src
    assert "renderComparisonEvidence(cc);\n        html += _renderPeerPerspectives(cc);" in src


# ── E. Arabic coverage ────────────────────────────────────────────────────

NEW_KEYS = [
    "Peer comparison evidence",
    "No stored perspective label holds a complete peer group, so no peer "
    "comparison is described here.",
    "{rows} stored perspective labels describe one peer comparison: the "
    "labels name the same peer set, so it is counted once.",
    "One stored perspective label describes one peer comparison ({labels}).",
    "{rows} stored perspective labels describe {comparisons} distinct peer "
    "comparisons.",
    "{duplicates} of those labels name a peer set that is already counted, "
    "so they add no second comparison.",
    "Stored labels", "Effective severity", "Stored severity",
    "Comparison identity", "Comparison source", "Policy version",
    "Relationship", "shared hospitals",
    "Nested peer groups", "Overlapping peer groups", "Disjoint peer groups",
    "Unknown relationship",
    "Temporal evidence (history)", "Observations", "Evidence quality flags",
    "The history perspective is temporal evidence, not a peer comparison: "
    "it compares the hospital with its own earlier months and is never "
    "counted as a peer comparison.",
    "The history perspective stores no readable window, so its temporal "
    "evidence is unknown; it is not turned into a peer comparison.",
    "Unknown evidence", "Invalid evidence", "Truncated peer evidence",
    "Conflicting statistics", "Mixed policy versions",
    "{label}: the stored peer evidence contradicts itself ({reason}), so it "
    "is not counted as a comparison.",
    "{label}: the stored peer evidence is incomplete, so the comparison "
    "cannot be established and is reported as unknown.",
    "{label}: the stored peer evidence does not name the compared hospitals "
    "({reason}), so the comparison is unknown.",
    "{labels}: the stored rows on this one peer set disagree on {fields}; "
    "that is conflicting statistics on one comparison, not a second "
    "comparison.",
    "More than one comparison-policy version is stored for this formula "
    "({versions}); that is provenance, not another sample.",
    "current_value", "stored_severity", "peer_count",
    "no_readable_history_window", "truncated_nested_peer_ids",
    "top_level_truncation_possible", "peer_count_mismatch",
]


def test_every_new_sentence_and_identifier_has_an_arabic_value():
    for key in NEW_KEYS:
        value = _ar_for(key)
        assert value, f"missing Arabic value for {key!r}"
        assert re.search(r"[\u0600-\u06FF]", value), (key, value)
        # No English words: placeholders and identifiers are not words.
        stripped = re.sub(r"\{[a-z_]+\}", "", value)
        assert not re.search(r"[A-Za-z]{2,}", stripped), (key, value)


def test_arabic_render_contains_no_english_labels():
    ar = {}
    # Every key the block can print: the new sentences/labels, plus the
    # pre-existing labels it reuses (perspective names, bands).
    for key in NEW_KEYS + ["Peer comparison", "Peer hospitals", "VERY_HIGH",
                           "HIGH", "Ownership peers", "History",
                           "unavailable", "Type peers", "Regional peers"]:
        value = _ar_for(key)
        if value:
            ar[key] = value
    html = _render(_evidence(
        comparisons=[_comparison(evidence_conflict=True,
                                 conflict_fields=["current_value"],
                                 relationships=[{"identity": "123456789abc",
                                                 "relationship": "nested",
                                                 "shared_peers": 4}])],
        temporal=[{"alert_id": 9, "perspective": "history",
                   "label": "History", "state": "unknown",
                   "reason": "no_readable_history_window", "observations": 0,
                   "band": "HIGH", "stored_severity": "HIGH"}],
        unreadable=[{"alert_id": 3, "perspective": "type",
                     "label": "Type peers", "state": "invalid",
                     "reason": "peer_count_mismatch"}],
        policy_mixed=True,
        policy_versions=["2026-06-01.1", "2026-10-24.1"]),
        lang="ar", labels=ar)
    for english in ("Peer comparison", "Effective severity", "Stored labels",
                    "Temporal evidence", "Unknown evidence", "provenance",
                    "No stored perspective label"):
        assert english not in html, english
    assert re.search(r"[\u0600-\u06FF]", html)
