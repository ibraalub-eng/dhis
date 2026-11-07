"""Evidence provenance is displayed, not only returned (Phase 8).

The APIs already distinguish effective vs stored bands, canonical vs
independent evidence and missing/unavailable states. These static contracts
pin that the three deferred screens now render that qualification, and that
every new label has an Arabic translation instead of falling back to English.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js"
I18N = JS / "i18n.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _translations() -> dict:
    src = _read(I18N)
    body = src.split("export const translations = {", 1)[1]
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']*)'", body))


def test_quality_score_popup_qualifies_the_evidence():
    """A stored-only band must not read as verified canonical severity."""
    js = _read(JS / "explain.js")
    assert "o.stored_level" in js
    assert "o.cap_policy" in js
    assert "o.evidence_status === 'stored_level_only'" in js
    assert "Stored level only: this row has no layer scores" in js
    assert "__('Cap applied')" in js
    assert "__('Stored level')" in js
    # Effective versus stored and the evidence status are labelled explicitly.
    assert "__('Effective level')" in js
    assert "__('Evidence status')" in js
    assert "_evidenceStatusLabel(o.evidence_status)" in js
    assert "p.evidence_status" in js
    assert "_evidenceStatusLabel(p.evidence_status)" in js


def test_quality_alerts_modal_shows_base_and_final_severity():
    js = _read(JS / "quality-alerts.js")
    for token in (
        "a.base_severity",
        "a.final_severity",
        "a.trend_assessment",
        "a.evidence_source",
        "a.canonical_evidence",
        "Canonical base severity",
        "Trend assessment",
        "Final alert severity",
        "Evidence provenance",
        "Evidence source",
        "Evidence status",
    ):
        assert token in js, token
    # The final band is labelled operational, never canonical.
    assert "__('operational')" in js


def test_audit_and_root_cause_labels_have_arabic_translations():
    translations = _translations()
    for key in (
        "Canonical: ",
        "Stored: ",
        "Canonical layered",
        "Independent audit",
        "Independent perspective",
        "No canonical layered result",
        "Canonical evidence unavailable",
        "Missing layered result",
        "Equivalent",
        "Not equivalent",
        "Unclassified",
    ):
        assert key in translations, key
        assert re.search(r"[\u0600-\u06FF]", translations[key]), key


def test_evidence_and_severity_labels_have_arabic_translations():
    translations = _translations()
    for key in (
        "Stored level",
        "Effective level",
        "Stored level only",
        "Stored level only: this row has no layer scores, so no cap or gate could be verified",
        "Cap applied",
        "Canonical base severity",
        "Canonical severity",
        "Trend assessment",
        "Operational escalation",
        "Not escalated",
        "Final alert severity",
        "operational",
        "Evidence source",
        "Evidence status",
        "Evidence provenance",
        "Perspective",
    ):
        assert key in translations, key
        assert re.search(r"[\u0600-\u06FF]", translations[key]), key
