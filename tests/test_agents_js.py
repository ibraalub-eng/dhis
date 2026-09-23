# tests/test_agents_js.py
"""Static sanity checks for agents.js + i18n keys."""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AGENTS_JS = BASE / "static" / "js" / "agents.js"
I18N_JS = BASE / "static" / "js" / "i18n.js"
ADMIN_JS = BASE / "static" / "js" / "admin.js"
RULES_JS = BASE / "static" / "js" / "rules-manager.js"


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


def test_admin_view_registered():
    src = ADMIN_JS.read_text(encoding="utf-8")
    assert "loadAgentsAdmin" in src
    assert "/ai/agents/runs" in src
    assert "/ai/agents/admin" in src


def test_admin_view_has_role_provider_selects():
    src = ADMIN_JS.read_text(encoding="utf-8")
    for role in ("qa", "explainer", "report_writer", "triage"):
        assert role + "_role" in src or "agent_role_" + role in src


def test_ai_settings_form_carries_agent_keys():
    src = RULES_JS.read_text(encoding="utf-8")
    assert "agents_enabled" in src
    assert "agents_provider" in src
    assert "agent_provider_roles" in src


def test_agents_js_loaded_in_index_html():
    src = (BASE / "static" / "index.html").read_text(encoding="utf-8")
    assert 'src="/static/js/agents.js"' in src


def test_agent_panels_present_in_dashboard_template():
    src = (BASE / "static" / "tabs" / "dashboard.html").read_text(encoding="utf-8")
    assert 'data-agent-panel="chat"' in src
    assert 'data-agent-panel="digest"' in src


def test_agentui_init_called_on_tab_load():
    src = (BASE / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert "AgentUI" in src
    assert "AgentUI.init" in src
