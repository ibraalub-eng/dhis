"""Static contract for the US-11 Audit Trail view (no browser needed)."""
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static" / "js"
EXPLAIN_JS = JS / "explain.js"
AUDIT_JS = JS / "audit.js"


def _src(path):
    return path.read_text(encoding="utf-8")


def test_why_popup_has_view_full_trail_button():
    src = _src(EXPLAIN_JS)
    assert "View full trail" in src
    assert "window._explainJumpTrail" in src
    assert "window.openAuditTrail" in src


def test_digest_footer_contract_intact():
    src = _src(EXPLAIN_JS)
    assert "data-explain-footer" in src
    assert "window._explainJumpFooter" in src
    assert "Digest only" in src


def test_audit_exposes_open_audit_trail():
    src = _src(AUDIT_JS)
    assert "openAuditTrail" in src
    assert "window.openAuditTrail" in src


def test_audit_renders_trail_stages_status_and_evidence():
    src = _src(AUDIT_JS)
    assert "trail" in src
    assert "evidence_items" in src
    assert "na_reason" in src
    assert "has_content" in src


def test_audit_detects_trail_mode_from_url():
    src = _src(AUDIT_JS)
    assert "mode=trail" in src or "mode === 'trail'" in src
