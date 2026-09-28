# -*- coding: utf-8 -*-
"""Terminology guard tests — the Arabic UI must keep one term per concept.

Companion to docs/ARABIC-TERMINOLOGY.md (the mandatory glossary). These tests
fail the build if a banned/conflicting term reappears in static/js/i18n.js or
if the glossary's core key pairs drift out of both anchor regions.

Background: the 2026-09-26 audit (1079 pairs) found seven real conflicts —
peer rendered three different ways, network as the vague "الشبكة", confidence
mislabeled as "التحقق" (colliding with validation), score as "النتيجة"
(colliding with finding), avg as "المعدل" (colliding with rate), plus the
"المواشر" typo and the stilted "إكلينيكي". All were unified; this file keeps
them unified.
"""

from pathlib import Path

I18N_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js"
GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "docs" / "ARABIC-TERMINOLOGY.md"


def _read_i18n() -> str:
    return I18N_PATH.read_text(encoding="utf-8")


# ── 1. Banned terms must never return ────────────────────────────────
# (banned substring, approved replacement, why it was banned)
BANNED = [
    ("النظير", "النظراء", "peer was scattered across three terms"),
    ("الأقران", "النظراء", "second peer synonym"),
    ("أقراني", "النظراء", "second peer synonym"),
    ("المماثلة", "نطاق النظراء", "third peer synonym (Peer Range)"),
    ("إكلينيكي", "سريري", "stilted MSA clinical term"),
    ("القواعد التحققية", "الالتزام بقواعد التحقق", "unnatural + inconsistent with the compliance label"),
    ("المواشر", "المؤشرات", "typo (ب instead of ص)"),
    ("توزيع التحقق", "توزيع الثقة حسب المؤشر", "confidence mislabeled as validation"),
    ("إشارات التحقق", "إشارات الثقة", "confidence mislabeled as validation"),
    ("عناصر التحقق", "عناصر الثقة", "confidence mislabeled as validation"),
    ("النتيجة الموحّدة", "الدرجة الموحّدة", "score must be الدرجة"),
    ("نتيجة نهائية تجريبية", "مثال على الدرجة النهائية", "score must be الدرجة"),
]


def test_no_banned_terms_in_i18n():
    i18n = _read_i18n()
    offenders = []
    for banned, approved, reason in BANNED:
        if banned in i18n:
            offenders.append(f"'{banned}' -> use '{approved}' ({reason})")
    assert not offenders, (
        "Banned terminology returned to i18n.js — see docs/ARABIC-TERMINOLOGY.md:\n"
        + "\n".join(offenders)
    )


def test_score_key_uses_approved_term_in_both_regions():
    i18n = _read_i18n()
    assert i18n.count("'score': 'الدرجة'") == 2, (
        "the generic 'score' key must be 'الدرجة' in BOTH anchor regions"
    )


def test_network_keys_present_in_both_regions():
    """The KPI benchmark keys must exist exactly twice (one per anchor region).
    The EN source itself is descriptive: 'vs other hospitals', never the bare
    word 'network' in any user-facing string."""
    i18n = _read_i18n()
    assert i18n.count("'Other hospitals average': 'متوسط بقية المستشفيات'") == 2
    assert i18n.count("'vs other hospitals': 'مقابل متوسط بقية المستشفيات'") == 2
    assert "'vs network'" not in i18n
    assert "'Network average'" not in i18n


# ── 2. Concept collision detectors (structural, not just literals) ───


def test_confidence_family_uses_thiqa_not_tahaqquq():
    """Any Arabic rendering of 'Confidence ...' keys must use الثقة, never
    التحقق. Long compound sentences that merely mention confidence in a list
    are exempt — the guard targets confidence *labels*, where the collision
    with Validation actually misleads users."""
    import re

    i18n = _read_i18n()
    # every pair whose EN key mentions confidence must translate with الثقة
    pairs = re.findall(r"'((?:[^'\\]|\\.)*[Cc]onfidence(?:[^'\\]|\\.)*)'\s*:\s*'([^']*)'", i18n)
    assert pairs, "confidence keys missing from i18n entirely?"
    bad = [
        (en, ar)
        for en, ar in pairs
        if "تحقق" in ar and len(en) < 80  # labels only, not full sentences
    ]
    assert not bad, f"confidence labels translated with التحقق (collides with Validation): {bad[:5]}"


def test_avg_is_mutawassit_not_muaddal():
    """'avg' must be المتوسط — المعدل is reserved for rate/rates."""
    i18n = _read_i18n()
    assert "'avg': 'المتوسط'" in i18n
    assert "'avg': 'المعدل'" not in i18n


# ── 3. The glossary itself must stay intact ──────────────────────────


def test_glossary_doc_exists_with_mandatory_rule():
    text = GLOSSARY_PATH.read_text(encoding="utf-8")
    assert "القاعدة الإلزامية" in text
    assert "مصطلحات محظورة" in text
    # every banned term is documented with its replacement
    for banned, approved, _ in BANNED:
        assert banned in text, f"glossary must document banned term '{banned}'"
        assert approved in text, f"glossary must document approved term '{approved}'"


def test_glossary_documents_network_and_peer_decisions():
    text = GLOSSARY_PATH.read_text(encoding="utf-8")
    assert "متوسط بقية المستشفيات" in text
    assert "النظراء" in text
