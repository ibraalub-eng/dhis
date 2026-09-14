"""Tests for Arabic i18n coverage of rule expression strings."""
import os
import re

_I18N_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
_RULES_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "js", "rules.js")

# Keys added with the new gt / lt / ge_factor expressions
_NEW_BUILDER_KEYS = [
    "parent > sum(children)",
    "parent \\u00d7 factor \\u2265 sum(children)",
    "child < parent",
]

# Pre-existing builder keys (translated now for consistency)
_EXISTING_BUILDER_KEYS = [
    "parent \\u2265 sum(children)",
    "parent = sum(children)",
    "child \\u2264 parent",
    "child \\u2265 sum(children)",
]

# Dropdown option labels (index.html ruleEditExpr)
_DROPDOWN_KEYS = [
    "ge — parent >= sum(children)",
    "gt — parent > sum(children)",
    "ge_factor — parent × factor >= sum(children)",
    "eq — parent == sum(children)",
    "le — child <= parent",
    "lt — child < parent",
    "le_sum — child >= sum(children)",
]

# EXPR_EXPLANATIONS titles
_EXPLANATION_TITLES = [
    "parent >= sum(children)",
    "parent > sum(children)",
    "parent × factor >= sum(children)",
    "parent == sum(children)",
    "child <= parent",
    "child < parent",
    "child >= sum(children)",
]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _translations_object():
    content = _read(_I18N_PATH)
    start = content.index("{", content.index("export const translations"))
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    raise AssertionError("unbalanced braces in translations object")


def _arabic_value_for(obj, key):
    """Return the Arabic value for an exact 'key': 'value' pair, or None."""
    pattern = re.compile(r"'(" + re.escape(key) + r")'\s*:\s*'((?:[^'\\]|\\.)*)'")
    m = pattern.search(obj)
    return m.group(2) if m else None


def test_new_builder_keys_have_arabic():
    obj = _translations_object()
    for key in _NEW_BUILDER_KEYS + _EXISTING_BUILDER_KEYS:
        val = _arabic_value_for(obj, key)
        assert val is not None, f"missing translation key: {key}"
        assert re.search(r"[\u0600-\u06FF]", val), f"no Arabic characters for: {key}"


def test_dropdown_labels_have_arabic():
    obj = _translations_object()
    for key in _DROPDOWN_KEYS:
        val = _arabic_value_for(obj, key)
        assert val is not None, f"missing translation key: {key}"
        # Keep the machine-readable expression code untranslated (LTR) at the start
        assert re.match(r"^[a-z_]+ —", val), f"expression code should stay untranslated: {key}"


def test_explanation_titles_have_arabic():
    obj = _translations_object()
    for key in _EXPLANATION_TITLES:
        val = _arabic_value_for(obj, key)
        assert val is not None, f"missing explanation title key: {key}"
        assert re.search(r"[\u0600-\u06FF]", val), f"no Arabic characters for title: {key}"


def test_explanation_texts_have_arabic():
    obj = _translations_object()
    # Verify by distinctive fragments of each EXPR_EXPLANATIONS text
    fragments = [
        "Strict version of ge",
        "Strict version of le",
        "multiplied by a factor",
        "sum of its child indicators",
        "reverse ge",
    ]
    for frag in fragments:
        pattern = re.compile(r"'((?:[^'\\]|\\.)*" + re.escape(frag) + r"(?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'")
        m = pattern.search(obj)
        assert m, f"no translation entry containing: {frag}"
        assert re.search(r"[\u0600-\u06FF]", m.group(2)), f"no Arabic characters for text containing: {frag}"


def test_rules_js_wraps_explanations_with_i18n():
    content = _read(_RULES_JS_PATH)
    assert "__(expl.title)" in content
    assert "__(expl.text)" in content


def test_no_duplicate_expression_keys():
    obj = _translations_object()
    keys = re.findall(r"'((?:[^'\\]|\\.)*)'\s*:", obj)
    important = _NEW_BUILDER_KEYS + _DROPDOWN_KEYS + [
        "parent >= sum(children)",
        "parent == sum(children)",
        "child <= parent",
        "child >= sum(children)",
        "FAIL if indicator has no value",
        "FAIL if any listed code is negative",
    ]
    for k in important:
        assert keys.count(k) <= 1, f"duplicate translation key: {k}"
