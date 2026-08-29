"""Tests for the Butterfly Intelligence comprehensive report structure."""
import pytest
from app.engine.comparative.report_generator import (
    SECTIONS, _build_local_sections, _parse_sections,
)

SECTION_KEYS = SECTIONS  # the 17 keys, order preserved


def test_sections_constant_has_all_keys():
    assert len(SECTIONS) == 17
    assert SECTIONS[0] == "exec_summary"
    assert SECTIONS[-1] == "appendix"


def test_local_sections_cover_all_keys():
    sections = _build_local_sections(None, lang="ar")
    for key in SECTIONS:
        assert key in sections, f"missing section: {key}"
        assert isinstance(sections[key], str) and sections[key].strip()


def test_english_local_sections_cover_all_keys():
    sections = _build_local_sections(None, lang="en")
    for key in SECTIONS:
        assert key in sections
        assert sections[key].strip()


def test_parse_sections_returns_all_keys():
    sample = "\n\n".join(f"## {key}\nنص قسم {key}" for key in SECTIONS)
    parsed = _parse_sections(sample, SECTIONS)
    for key in SECTIONS:
        assert key in parsed
        assert parsed[key].strip()


def test_local_sections_avoid_causation_words():
    sections = _build_local_sections(None, lang="ar")
    joined = "\n".join(sections.values())
    for bad in ("يؤدي إلى", "سببّية", "causes", "leads to"):
        assert bad not in joined, f"found forbidden wording: {bad}"
    # واقعي: يوجد تحذير الارتباط لا يعني السببية بشكل آمن
    assert "ارتباط" in " ".join(sections.values())


def test_parse_sections_tolerates_ai_noise():
    noisy = ("مقدمة غير مقصودة\n\n"
             "## exec_summary\nالمحتوى الأول\n\n"
             "## key_messages\n- بند 1\n- بند 2\n\n"
             "## appendix\nنهاية")
    parsed = _parse_sections(noisy, SECTIONS)
    assert parsed["exec_summary"].strip() == "المحتوى الأول"
    assert parsed["key_messages"].strip() == "- بند 1\n- بند 2"
    assert parsed["appendix"].strip() == "نهاية"
    # الأقسام غير المذكورة تُملأ بسرد فارغ → تُهدى لاحقاً للحتمي
    assert "geo_risk" in parsed
