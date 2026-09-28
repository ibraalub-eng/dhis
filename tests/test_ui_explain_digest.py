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
