"""Regression tests: the rule-change recompute notice in rules.js.

Saving a rule re-runs the latest month in the background, and every
"Validation rule" percentage on screen is the pre-edit value until it finishes.
`_watchRuleRecompute` is the only thing that tells the user when the numbers
have caught up, so its contract matters:

- one "updating" notice while the pass runs, one "updated" notice when it ends;
- NO "updated" notice when there was nothing to apply (the first poll already
  reports idle) — claiming an update that never happened is worse than silence;
- a failing status endpoint is advisory and must stay silent;
- the poll gives up instead of running forever.

The shipped function is executed in node against a fake clock and a stubbed
endpoint, so the assertions are about the real source rather than a restatement
of it.
"""
import json
import os
import re
import subprocess
import tempfile

import pytest

RULES_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "js", "rules.js")


def _function_src(name):
    """Exact source of a top-level `export function <name>(…) { … }` in
    rules.js, with the module-only `export` keyword stripped so node can run
    it as a plain declaration."""
    with open(RULES_JS, encoding="utf-8") as f:
        js = f.read()
    start = js.index("export function %s(" % name)
    src = js[start:]
    i = src.index("{")
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[:j + 1].replace("export ", "", 1)
    raise AssertionError("unterminated %s" % name)


_HARNESS = r"""
var __toasts = [], __reloads = 0, __polls = 0, __timers = [], __cleared = [];
function API() { return '/api'; }
function __(s) { return s; }
function toastInfo(m) { __toasts.push('info:' + m); }
function toastSuccess(m) { __toasts.push('success:' + m); }
function toastWarning(m) { __toasts.push('warning:' + m); }
function toastError(m) { __toasts.push('error:' + m); }
function loadRulesManager() { __reloads += 1; }
function setTimeout(fn, delay) { __timers.push({ fn: fn, delay: delay }); return __timers.length; }
function clearTimeout(id) { __cleared.push(id); if (id) { var i = id - 1; if (__timers[i]) __timers[i] = null; } }
var authFetch = function (url) {
  __polls += 1;
  var next = __statuses.length ? __statuses.shift() : { running: false };
  return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(next); } });
};
async function __drain(limit) {
  var fired = 0;
  for (var i = 0; i < (limit || 300); i++) {
    await new Promise(function (r) { setImmediate(r); });
    // skip cancelled slots left behind by clearTimeout
    while (__timers.length && __timers[0] === null) __timers.shift();
    if (!__timers.length) return fired;
    var t = __timers.shift();
    fired += 1;
    t.fn();
  }
  return fired;
}
"""


def _run(src, statuses):
    """Run _watchRuleRecompute against a scripted sequence of status payloads."""
    script = _HARNESS + "var __statuses = " + json.dumps(statuses) + ";\n"
    script += src + "\n"
    script += (
        "(async function () {\n"
        "  _watchRuleRecompute();\n"
        "  var fired = await __drain();\n"
        "  await new Promise(function (r) { setImmediate(r); });\n"
        "  process.stdout.write(JSON.stringify({ toasts: __toasts, reloads: __reloads,"
        " polls: __polls, fired: fired, pending: __timers.length }));\n"
        "})();\n"
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
    return json.loads(res.stdout)


SRC = _function_src("_watchRuleRecompute") if os.path.exists(RULES_JS) else None


@pytest.mark.skipif(not os.path.exists(RULES_JS), reason="rules.js missing")
class TestRuleChangeRecomputeNotice:

    def test_running_pass_ends_with_one_updated_notice(self):
        out = _run(SRC, [{"running": True, "progress": 20},
                         {"running": True, "progress": 80},
                         {"running": False}])
        assert out["toasts"] == ["info:Updating quality scores for the latest month...",
                                 "success:Quality scores updated."], out
        assert out["reloads"] == 1, "the impact view must be reloaded once it changed"
        assert out["polls"] == 3

    def test_nothing_to_recompute_is_reported_silently(self):
        """A rule edit with no data to recompute (or one that finished inside
        the first 1.5s) must not claim the scores were updated."""
        out = _run(SRC, [{"running": False}])
        assert out["toasts"] == [], out
        assert out["reloads"] == 0

    def test_status_endpoint_failure_stays_silent(self):
        src = SRC.replace("if (!res.ok) throw new Error('HTTP ' + res.status);", "")
        broken = _HARNESS.replace(
            "return Promise.resolve({ ok: true, status: 200, json: function () "
            "{ return Promise.resolve(next); } });",
            "return Promise.resolve({ ok: false, status: 500, json: function () "
            "{ return Promise.reject(new Error('boom')); } });",
        )
        script = (broken + "var __statuses = [];\n" + src + "\n"
                  "(async function () {\n"
                  "  _watchRuleRecompute();\n"
                  "  await __drain(5);\n"
                  "  await new Promise(function (r) { setImmediate(r); });\n"
                  "  process.stdout.write(JSON.stringify({ toasts: __toasts,"
                  " reloads: __reloads, polls: __polls }));\n"
                  "})();\n")
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
        out = json.loads(res.stdout)
        assert out["toasts"] == [], out
        assert out["reloads"] == 0

    def test_polling_stops_instead_of_running_forever(self):
        """A pass that never finishes (a wedged worker, a status endpoint that
        always says running) must not keep a timer alive forever."""
        out = _run(SRC, [{"running": True, "progress": 1}] * 500)
        assert out["polls"] == 80, out  # 1.5s × 80 = the 120s cap
        assert out["pending"] == 0, "the poll must give up instead of rescheduling"
        assert out["toasts"] == ["info:Updating quality scores for the latest month..."]

    def test_second_save_cancels_the_first_watch(self):
        """Two rule saves in a row must not leave two poll loops running (each
        would toast independently)."""
        script = _HARNESS + "var __statuses = [{running:false},{running:false}];\n"
        script += SRC + "\n"
        script += (
            "(async function () {\n"
            "  _watchRuleRecompute();\n"
            "  _watchRuleRecompute();\n"
            "  await __drain(10);\n"
            "  await new Promise(function (r) { setImmediate(r); });\n"
            "  process.stdout.write(JSON.stringify({ toasts: __toasts,"
            " polls: __polls, cleared: __cleared.length, pending: __timers.length }));\n"
            "})();\n"
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
        out = json.loads(res.stdout)
        assert out["cleared"] >= 1, "the first watch must be cancelled"
        assert out["polls"] == 1, out  # only the surviving loop polls


def test_notice_strings_are_translated():
    """The two notices are user-facing copy: both must go through __() so the
    Arabic UI does not show English."""
    with open(RULES_JS, encoding="utf-8") as f:
        js = f.read()
    for text in ("Updating quality scores for the latest month...",
                 "Quality scores updated."):
        assert re.search(r"__\(\s*['\"]%s['\"]" % re.escape(text), js), text