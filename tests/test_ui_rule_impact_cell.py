"""Regression tests: the Rules Manager "Impact" cell.

The cell carries three separate claims and each of them used to be wrong or
missing:

- how many hospitals fail the rule RIGHT NOW (live, from /rules/impact);
- whether the rule is disabled — a disabled rule must not read as "clean", and
  its impact is still shown so it can be tuned;
- how many alerts it has logged historically, so a rule that passes today but
  failed repeatedly before (R060) does not look like it never failed.

They are built by string concatenation inside a row renderer, so the tests
execute the SHIPPED block in node against synthetic impact payloads and read
the resulting HTML.
"""
import json
import os
import re
import subprocess
import tempfile

RULES_MANAGER_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "js", "rules-manager.js")


def _read():
    with open(RULES_MANAGER_JS, encoding="utf-8") as f:
        return f.read()


def _impact_cell_src():
    """The impact-cell statements: from `let impactCell = …` up to the row
    markup that consumes it."""
    js = _read()
    start = js.index("let impactCell = ")
    anchor = js.index("html += '<tr class=\"rule-row\"", start)
    block = js[start:anchor]
    # the block ends with the closing brace of the `if (imp) {` guard
    return block.rstrip().rstrip() + "\n"


def _cell(imp, rule=None):
    """Run the shipped impact-cell block and return the resulting HTML."""
    rule = rule or {"code": "R060", "enabled": True, "rule_type": "LOGIC",
                    "severity": "HIGH"}
    # the block reads the rule row as `r` and its impact entry as `imp`
    script = (
        "function __(s) { return s; }\n"
        "function esc(s) { return String(s); }\n"
        "var r = " + json.dumps(rule) + ";\n"
        "var imp = " + json.dumps(imp) + ";\n"
        + _impact_cell_src()
        + "\nprocess.stdout.write(String(impactCell));"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                     delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        res = subprocess.run(["node", path], capture_output=True, text=True,
                             encoding="utf-8")
    finally:
        os.unlink(path)
    assert res.returncode == 0, f"node failed:\n{res.stderr}"
    return res.stdout


def test_live_failures_are_shown_with_their_month():
    html = _cell({"enabled": True, "month": "2026-08",
                  "hospitals_affected": [{"hospital_id": 10}, {"hospital_id": 16}],
                  "alert_count": 0})
    assert ">2<" in html, html
    assert "2026-08" in html, "the number must say which month it describes"


def test_clean_rule_reads_zero_not_dash():
    html = _cell({"enabled": True, "month": "2026-08", "hospitals_affected": [],
                  "alert_count": 0})
    assert ">0<" in html, html
    assert ">--<" not in html, "a saved rule always has an impact entry"


def test_missing_impact_entry_still_renders_the_cell():
    html = _cell(None)
    assert ">--<" in html, html


def test_disabled_rule_is_labelled_and_explains_it_is_not_alerting():
    """A disabled rule produces no alerts, so a bare "0" reads as "clean" and
    "3" reads as a live problem. The cell must carry a visible muted label (not
    only a tooltip, which a manager scanning the column never sees) and say in
    the tooltip of a non-zero count that nothing is being alerted."""
    zero = _cell({"enabled": False, "month": "2026-08", "hospitals_affected": [],
                  "alert_count": 0})
    assert ">disabled</span>" in zero, zero
    assert "nothing is being evaluated or alerted" in zero, zero

    live = _cell({"enabled": False, "month": "2026-08",
                  "hospitals_affected": [{"hospital_id": 10}, {"hospital_id": 12}],
                  "alert_count": 0})
    assert ">disabled</span>" in live
    assert "not being alerted" in live, live


def test_historical_alerts_are_counted_separately_from_live_failures():
    """A rule that passes now but failed before must still show its history,
    with the hospital count and last failing month."""
    html = _cell({"enabled": True, "month": "2026-08", "hospitals_affected": [],
                  "alert_count": 4, "alert_hospitals": 3,
                  "last_alert_month": "2026-05"})
    assert "4 logged" in html, html
    assert "3 hospital(s)" in html, html
    assert "2026-05" in html, html


def test_no_history_line_when_nothing_was_ever_logged():
    html = _cell({"enabled": True, "month": "2026-08", "hospitals_affected": [],
                  "alert_count": 0})
    assert "logged" not in html, html


def test_labels_are_translated():
    """The two user-facing labels must go through __() so the Arabic Rules
    Manager is not half-English."""
    js = _read()
    block = _impact_cell_src()
    for text in re.findall(r"__\('([^']+)'\)", block):
        assert "'%s'" % text in js or text in js
    # the translated strings exist in the catalogue
    with open(os.path.join(os.path.dirname(RULES_MANAGER_JS), "i18n.js"),
              encoding="utf-8") as f:
        i18n = f.read()
    assert "'disabled':" in i18n, "the disabled label must be translated"
    assert "This rule is disabled" in i18n