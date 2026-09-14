"""Static checks for the Rules Manager frontend module (static/js/rules.js)."""
import os


def _read_rules_js():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "rules.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_rules_js_imports_confirm_destructive():
    """deleteRule() awaits confirmDestructive(). Without the import the rule
    delete buttons silently no-op because confirmDestructive is module-scoped
    (confirm-modal.js) and never exposed on window."""
    js = _read_rules_js()
    assert "import { confirmDestructive } from './confirm-modal.js';" in js


def test_rules_js_uses_confirm_destructive():
    """Sanity guard: the delete confirmation path must actually be present."""
    js = _read_rules_js()
    assert "confirmDestructive({" in js