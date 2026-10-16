"""Tests for the US-11 unified audit trail (trail + 8-stage chain)."""
from app.engine.audit.explain import (
    _bilingual,
    _chain_from_trail,
    _deep_link,
    _evidence_item,
    _na_stage,
    _stage,
)


def test_bilingual_equal_returns_string():
    assert _bilingual("A", "A") == "A"


def test_bilingual_diff_returns_dict():
    assert _bilingual("\u0623", "A") == {"ar": "\u0623", "en": "A"}


def test_na_stage_carries_reason_and_status():
    st = _na_stage("root_cause", 5, "\u0627\u0644\u0633\u0628\u0628", "Root Cause", "\u0644\u0627", "No")
    assert st["status"] == "na"
    assert st["key"] == "root_cause"
    assert st["order"] == 5
    assert st["detail"] is None
    assert st["na_reason"] == {"ar": "\u0644\u0627", "en": "No"}


def test_evidence_item_optional_unit():
    assert _evidence_item("Effort AR", "Effort", "low") == {
        "label_ar": "Effort AR", "label_en": "Effort", "value": "low",
    }
    assert _evidence_item("p", "Points", 3, unit="quality points")["unit"] == "quality points"


def test_deep_link_builds_endpoint_and_hash():
    assert _deep_link(endpoint="/x") == {"endpoint": "/x"}
    assert _deep_link(hash_="audit?mode=trail") == {"hash": "audit?mode=trail"}
    assert _deep_link() is None


def test_chain_from_trail_uses_legacy_step_names_and_english_detail():
    trail = [
        _stage("raw_data", 1, "\u0623", "12 indicator values"),
        _stage("validation", 2, "\u0628", "none failed"),
        _stage("issue", 3, "\u062c", "issue"),
        _stage("evidence", 4, "\u062f", "evidence"),
        _stage("root_cause", 5, "\u0647", "rc"),
        _stage("impact", 6, "\u0648", "impact"),
        _stage("recommendation", 7, "\u0632", "rec"),
        _stage("action", 8, "\u062d", "act"),
    ]
    chain = _chain_from_trail(trail)
    assert len(chain) == 8
    assert chain[0]["step"] == "Source Data"
    assert chain[1]["step"] == "Validation"
    assert chain[2]["step"] == "Issue"
    assert chain[0]["detail"] == "12 indicator values"
    assert chain[0]["key"] == "raw_data"
