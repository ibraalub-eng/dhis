import json
import os
import re
import subprocess

RULES_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "js", "rules.js")


def _read():
    with open(RULES_JS, encoding="utf-8") as f:
        return f.read()


def _extract_nested_fn():
    """Pull the real _vbNestedChildren source out of rules.js so the test
    exercises shipped code rather than a copy of it."""
    js = _read()
    start = js.index("export function _vbNestedChildren")
    # walk braces to find the end of the function body
    i = js.index("{", start)
    depth = 0
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[start:j + 1]
    raise AssertionError("unterminated _vbNestedChildren")


def _run(fn_src, cases):
    """Execute the extracted function in node and return its result per case."""
    script = (
        fn_src.replace("export function", "function") + "\n"
        "const cases = " + json.dumps(cases) + ";\n"
        "const out = cases.map(c => _vbNestedChildren(c));\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_nested_children_flags_parent_plus_descendants():
    """A chosen list that mixes a parent with its own children must be
    reported: summing them counts the same cases more than once."""
    fn = _extract_nested_fn()
    # The exact shape that was silently saved for R061.
    user = ["10.a", "10.a.1", "10.a.1.1", "10.a.1.2", "10.a.2", "10.a.2.1",
            "10.a.2.2", "10.a.3"]
    out = _run(fn, [user])
    pairs = out[0]
    parents = sorted({p for p, _ in pairs})
    assert "10.a" in parents
    assert "10.a.1" in parents
    # node returns JSON, so each pair comes back as a list
    assert ["10.a", "10.a.1"] in pairs


def test_nested_children_clean_flat_list_is_quiet():
    """The correct definition for indicator 10 is one level down (10.a..10.o)
    and must produce no warning at all."""
    fn = _extract_nested_fn()
    flat = ["10.a", "10.b", "10.c", "10.d", "10.e", "10.f", "10.g", "10.h",
            "10.i", "10.j", "10.k", "10.l", "10.m", "10.n", "10.o"]
    assert _run(fn, [flat])[0] == []


def test_nested_children_edge_cases():
    """Siblings are not nested, and a longer sibling name that merely shares a
    prefix (10.a vs 10.ab) must not count as ancestry."""
    fn = _extract_nested_fn()
    out = _run(fn, [None, [], ["10.a", "10.b"], ["10.a", "10.ab"], ["10.a"]])
    assert out[0] == []
    assert out[1] == []
    assert out[2] == []
    assert out[3] == []
    assert out[4] == []


def test_nesting_warning_is_wired_into_the_preview():
    """The guard must actually surface while editing, not just exist."""
    js = _read()
    preview = js[js.index("window.updateRuleExprPreview = function"):]
    preview = preview[:preview.index("\n        };")]
    assert "_vbNestingWarningHTML" in preview
    assert "_vbNestedChildren" in preview
    assert "ruleExprPreviewWarn" in preview


def test_preview_checks_both_children_and_codes():
    """Sum-based rules populate `children`, set-based rules populate `codes`.
    Checking only one would leave half the expressions unguarded."""
    js = _read()
    preview = js[js.index("window.updateRuleExprPreview = function"):]
    assert "[p.children, p.codes]" in preview