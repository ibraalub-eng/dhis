# tests/test_agents_js.py
"""Static sanity checks for agents.js + i18n keys."""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AGENTS_JS = BASE / "static" / "js" / "agents.js"
I18N_JS = BASE / "static" / "js" / "i18n.js"


def test_agents_js_exists():
    assert AGENTS_JS.exists()


def test_status_gating_used():
    src = AGENTS_JS.read_text(encoding="utf-8")
    assert "agents_enabled" in src or "enabled" in src
    assert "/ai/agents/status" in src


def test_explain_renders_sections():
    src = AGENTS_JS.read_text(encoding="utf-8")
    for marker in ("facts", "analysis", "contributors", "actions"):
        assert marker in src.lower()


def test_digest_button_label_uses_i18n():
    sjs = AGENTS_JS.read_text(encoding="utf-8")
    ijs = I18N_JS.read_text(encoding="utf-8")
    keys = re.findall(r"__\('([^']+)'\)", sjs)
    assert keys, "agents.js must use __() for every literal"
    for k in keys:
        assert k in ijs, f"missing i18n key: {k}"
