"""Static checks: the Why popup is a DIGEST, not a copy of the Audit screen.

The popup answers what / where / why + a ✓/✗ verdict, then hands over to the
Audit screen (single source of truth) via ONE footer button. Everything the
Audit screen already shows — the traceability chain, the expanded inputs
table, expected-vs-stored numbers, the full data-problem sweep — must NOT be
duplicated in the popup.
"""
from pathlib import Path

EXPLAIN_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "explain.js"


def _src():
    return EXPLAIN_JS.read_text(encoding="utf-8")


def _extract_wrapper():
    """Pull the real global wrapper out of explain.js so it can be executed
    (not just pattern-matched) in node."""
    js = _src()
    start = js.index("window.showWhyPopup = function (kindOrOpts")
    i = js.index("{", start)
    depth = 0
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[start:j + 1]
    raise AssertionError("unterminated window.showWhyPopup wrapper")


def test_popup_does_not_render_the_traceability_chain():
    """The chain strip renders identically on the Audit screen; the popup's
    footer button is THE pointer to it."""
    src = _src()
    assert "_chainView" not in src
    assert "Traceability chain" not in src


def test_reproduce_block_shows_verdict_only():
    """✓/✗ verdict + note stay; the expected-vs-stored numbers and weighted
    contributions belong to the Audit screen's verification."""
    src = _src()
    assert "Verified — the number reproduces exactly" in src
    assert "Not verified — recomputed value differs" in src
    for audit_only in ("Expected from formula", "Rate from raw values",
                       "Recomputed z", "Show weighted component contributions"):
        assert audit_only not in src, audit_only


def test_data_problems_capped_at_three():
    """Digest shows at most 3 example problems + an overflow line; the full
    sweep lives in the Audit screen's Data Auditor section."""
    src = _src()
    assert "slice(0, 3)" in src
    assert "'... and {n} more'" in src


def test_stale_benchmark_is_never_the_problem_that_gets_cut():
    """A month can carry 30 missing cells and one out-of-date anomaly
    benchmark. Only the staleness changes the verdict, so the 3-example cap
    must not be allowed to hide it behind the month's noise."""
    src = _src()
    assert "d.kind === 'stale_benchmark' ? 0" in src
    assert "slice().sort(" in src, "the list must be ordered before capping"


def test_inputs_table_collapsed_behind_details():
    """Inputs used collapses behind a toggle with its row count."""
    src = _src()
    assert "<details" in src
    assert "__('Inputs used') + ' ('" in src


def test_footer_remains_the_single_audit_pointer():
    src = _src()
    assert "data-explain-footer" in src
    assert "window._explainJumpFooter" in src
    assert "Digest only" in src


def test_header_documents_the_digest_contract():
    src = _src()
    assert "renders a slim DIGEST" in src


def test_failed_rules_are_listed_with_a_drill_into_each_rule():
    """The score only carries a rule-compliance percentage, so a hospital can
    sit above target while rules fail. The popup must name them, and each code
    re-opens the popup on kind=rule for its own calculation."""
    src = _src()
    assert "_renderFailedRules(p)" in src
    assert "p.failed_rules" in src
    assert "__('Failed rules')" in src
    assert "window.showWhyPopup(\\'rule\\'" in src


def test_failed_rules_block_is_capped_at_ten():
    """Digest level: 10 failures + an overflow line, not the whole alert wall."""
    src = _src()
    assert "rows.slice(0, 10)" in src
    assert "rows.length - 10" in src


def test_global_hook_accepts_both_call_styles():
    """Inline onclick handlers call window.showWhyPopup both positionally
    ('rule', hid, month) and with an object ({kind, hospitalId, month,
    component}). The global hook must forward the object form as-is; treating
    it as `kind` built the request as "?kind=[object Object]"."""
    src = _src()
    assert "window.showWhyPopup = function (kindOrOpts" in src
    assert "if (kindOrOpts && typeof kindOrOpts === 'object')" in src

    import json
    import subprocess

    script = (
        "const captured = [];\n"
        "function showWhyPopup(opts) { captured.push(opts); }\n"
        "global.window = {};\n"
        + _extract_wrapper() + "\n"
        # the rules-manager.js call site: object form with a component
        "window.showWhyPopup({kind:'quality_score', hospitalId:12, month:'2026-08', component:'rule_compliance'});\n"
        # the alerts/outliers call sites: positional form
        "window.showWhyPopup('rule', 12, '2026-08', null, 'R061');\n"
        "process.stdout.write(JSON.stringify(captured));\n"
    )
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out[0]["kind"] == "quality_score"
    assert out[0]["hospitalId"] == 12
    assert out[0]["month"] == "2026-08"
    assert out[0]["component"] == "rule_compliance"
    assert out[1]["kind"] == "rule"
    assert out[1]["hospitalId"] == 12
    assert out[1]["ruleCode"] == "R061"


def test_failed_rule_chips_use_the_row_hospital_for_aggregate_digests():
    """Month-overview rows carry their own hospital; the chip must drill into
    THAT hospital's rule, not into a hospital the digest does not have."""
    src = _src()
    assert "r.hospital_id !== undefined && r.hospital_id !== null" in src
    assert "const rowHid = " in src
    assert "r.hospital ? '<span" in src


def test_drilldown_why_button_opens_the_worst_component_month():
    """The KPI drilldown's hospital cards list problem months for ONE component
    tab. The Why button must open the month that bottomed out for that
    component (not the oldest problem month) and plot that same component."""
    src = (EXPLAIN_JS.parent / "rules-manager.js").read_text(encoding="utf-8")
    assert "c.hosp_monthly[String(h.hospital_id)]" in src
    assert "pt.value < _worst.value" in src
    assert "component:\\'' + _ckey + '\\'" in src
    # …and it must no longer pick problemMonths[0] (the oldest month).
    assert "problemMonths.slice().sort()[0]" not in src


def test_attention_strip_opens_the_full_failure_list_when_several_rules_failed():
    """A row that says "3 critical/high rule failures" must not open the digest
    of only the top rule."""
    src = (EXPLAIN_JS.parent / "rules-manager.js").read_text(encoding="utf-8")
    assert "whyCount: a.count" in src
    assert "var _oneRule = _w.kind === 'rule' && !(r.whyCount > 1);" in src
