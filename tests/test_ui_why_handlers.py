"""Regression tests: every generated Why button must be valid, runnable
JavaScript that opens the digest with the right options.

The handlers are built by string concatenation inside HTML attributes, so a
typo (a stray comma where a statement belongs, a missing bracket in a filter
callback, an unclosed quote) is invisible to `npm run check` — that validates
the file's own syntax, never the text it concatenates. Such a handler fails
only when a user clicks the button, and then it throws instead of opening the
explanation.

These tests execute the REAL statements from the shipped source in node inside
a sandbox whose unknown identifiers resolve to permissive stubs. The resulting
markup is checked two ways: every onclick payload must parse as a function
body, and the Why payloads must actually reach window.showWhyPopup with the
options the digest needs (hospital, month, component, rule code).
"""
import html as htmllib
import json
import os
import re
import subprocess
import tempfile

RULES_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "js", "rules-manager.js")

# Sandbox: every identifier the payload references is pre-declared as a
# permissive stub, and every showWhyPopup() call is recorded. Stubs are
# functions returning themselves so they can be called, compared and
# stringified like the DOM objects the real handler touches.
_HARNESS = r"""
var __calls = [];
function __stub() {
  var stub = function () { return stub; };
  stub.toString = function () { return '1'; };
  stub.valueOf = function () { return 1; };
  return stub;
}
function __el() {
  var el = function () { return el; };
  el.toString = function () { return 'el'; };
  el.style = {};
  el.dataset = {};
  el.classList = {
    hidden: false,
    toggle: function () { el.classList.hidden = !el.classList.hidden; return el.classList.hidden; },
    add: function () {}, remove: function () {}, contains: function () { return false; }
  };
  el.parentElement = el;
  el.nextElementSibling = el;
  el.previousElementSibling = el;
  el.firstElementChild = el;
  el.querySelector = function () { return el; };
  el.querySelectorAll = function () { return []; };
  el.closest = function () { return el; };
  el.getAttribute = function () { return null; };
  el.setAttribute = function () {};
  el.addEventListener = function () {};
  el.removeEventListener = function () {};
  el.stopPropagation = function () {};
  el.preventDefault = function () {};
  el.focus = function () {};
  el.click = function () {};
  return el;
}
var __win = {
  showWhyPopup: function (o) { __calls.push(o); },
  openKPIDrilldown: function () {},
  _explainJumpTo: function () {}
};
var window = __win;
function __(s) { return s; }
function __ser(v, d) {
  d = d || 0;
  if (d > 3) return '<deep>';
  if (v === null) return null;
  var t = typeof v;
  if (t === 'function') return '<stub>';
  if (t !== 'object') return v;
  if (Array.isArray(v)) return v.map(function (x) { return __ser(x, d + 1); });
  var o = {};
  for (var k in v) {
    if (k === 'toString' || k === 'valueOf') continue;
    try { o[k] = __ser(v[k], d + 1); } catch (e) { o[k] = '<unreadable>'; }
  }
  return o;
}
"""

# Names the sandbox provides itself, or that are language/host globals.
_PROVIDED = {
    "__calls", "__stub", "__win", "__ser", "__", "window", "document", "console",
    "JSON", "Math", "Number", "String", "Object", "Array", "Boolean", "Date",
    "RegExp", "Error", "Promise", "Set", "Map", "Symbol",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent",
    "decodeURIComponent", "undefined", "NaN", "Infinity", "this", "arguments",
}

_RESERVED = {
    "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally", "for",
    "function", "if", "import", "in", "instanceof", "let", "new", "return",
    "super", "switch", "throw", "try", "typeof", "var", "void", "while",
    "with", "yield", "await", "static", "get", "set", "of", "async", "true",
    "false", "null", "null",
}


def _stub_decls(code):
    """`var x = __stub();` for every free identifier in `code`."""
    names = set()
    for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)", code):
        name = m.group(1)
        if name in _PROVIDED or name in _RESERVED:
            continue
        names.add(name)
    return "".join(f"var {n} = __stub();\n" for n in sorted(names))


def _read():
    with open(RULES_JS, encoding="utf-8") as f:
        return f.read()


def _drilldown_src():
    """The drilldown builder: the only place where onclick payloads are
    concatenated from hospital/cause data."""
    js = _read()
    start = js.index("window.openKPIDrilldown = function")
    i = js.index("{", start)
    depth = 0
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[start:j + 1]
    raise AssertionError("unterminated openKPIDrilldown")


def _statements_with(src, needle):
    """Return (offset, statement_source) for every markup statement in `src`
    containing `needle`.

    Statements are anchored on their `html +=` opener and scanned forward with
    string awareness, so the `;` and `(` inside a concatenated onclick payload
    never truncate the statement. Statements are deduped: many buttons share
    the builder that emits them.
    """
    out = []
    seen = set()
    pos = 0
    while True:
        at = src.find(needle, pos)
        if at == -1:
            return out
        pos = at + 1
        anchor = max(src.rfind("html +=", 0, at), src.rfind("html =", 0, at))
        if anchor == -1 or anchor in seen:
            continue
        i = anchor
        quote = None
        depth = 0
        while i < len(src):
            c = src[i]
            if quote:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "'\"`":
                quote = c
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == ";" and depth <= 0:
                break
            i += 1
        if i >= len(src):
            continue
        seen.add(anchor)
        out.append((src.count("\n", 0, anchor) + 1, src[anchor:i + 1].strip()))


def _run(script):
    """Run JS in node from a UTF-8 file: `-e` would re-encode the payload
    through the console code page and mangle non-ASCII text."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                     delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        res = subprocess.run(["node", path], capture_output=True, text=True,
                             encoding="utf-8")
    finally:
        os.unlink(path)
    assert res.returncode == 0, f"node failed:\n{script}\n{res.stderr}"
    return res.stdout


def _render(statement):
    """Execute one shipped markup statement and return the HTML it builds."""
    script = (_HARNESS + _stub_decls(statement)
              + "var html = '';\n(function () {" + statement + "})();\n"
              + "process.stdout.write(String(html));")
    return _run(script)


def _onclick_payloads(markup):
    return [htmllib.unescape(p) for p in re.findall(r'onclick="([^"]*)"', markup)]


def _parse_payload(payload):
    """Syntax-only check: the payload is embedded as a JSON string literal so
    the quotes inside it cannot break the surrounding node script."""
    _run(_HARNESS
         + "var __src = " + json.dumps(payload) + ";\n"
         + "new Function('return function(){' + __src + '}');")


_WINDOW_KNOWN = {"showWhyPopup", "openKPIDrilldown", "_explainJumpTo"}


def _win_decls(code):
    """Record no-op handlers for every `window.x` the payload calls, so a
    cross-screen jump is not reported as a missing function."""
    names = set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)", code)) - _WINDOW_KNOWN
    return "".join(f"__win.{n} = function () {{ __calls.push({{ window: '{n}' }}); }};\n"
                   for n in sorted(names))


def _run_payload(payload):
    """Execute a payload as a click handler and return every options object it
    opened."""
    script = (_HARNESS + _win_decls(payload) + _stub_decls(payload)
              + "var event = __el();\n"
              + "(function () {" + payload + "}).call(__el());\n"
              + "process.stdout.write(JSON.stringify(__ser(__calls, 0)));")
    return json.loads(_run(script) or "[]")


def test_every_generated_onclick_handler_is_valid_javascript():
    """Each onclick payload must parse as a function body — the check npm
    cannot do, because it only sees the concatenation, not its result."""
    js = _read()
    checked = 0
    for line, statement in _statements_with(_drilldown_src(), "onclick="):
        for payload in _onclick_payloads(_render(statement)):
            if not payload.strip():
                continue
            _parse_payload(payload)
            checked += 1
    assert checked >= 4, f"expected many generated handlers, only checked {checked}"


def test_generated_onclick_handlers_execute_without_throwing():
    """Parsing is not enough: the handler must run top to bottom (the shape of
    the bug this file guards against — a broken map callback threw only on
    click)."""
    js = _read()
    ran = 0
    for line, statement in _statements_with(_drilldown_src(), "onclick="):
        for payload in _onclick_payloads(_render(statement)):
            if not payload.strip():
                continue
            _run_payload(payload)
            ran += 1
    assert ran >= 4, f"expected many generated handlers, only ran {ran}"


def test_generated_why_handlers_reach_the_popup_with_their_options():
    """The affected-hospital score Why button must open the object-form digest
    naming hospital, month and component, so the popup explains that hospital's
    worst month FOR THAT COMPONENT."""
    js = _read()
    opts = None
    for line, statement in _statements_with(_drilldown_src(), "window.showWhyPopup("):
        for payload in _onclick_payloads(_render(statement)):
            for o in _run_payload(payload):
                if isinstance(o, dict) and o.get("kind") == "quality_score":
                    opts = o
    assert opts is not None, "no object-form quality_score Why handler was generated"
    for key in ("hospitalId", "month", "component"):
        assert key in opts, f"score Why handler must pass {key}: {opts}"