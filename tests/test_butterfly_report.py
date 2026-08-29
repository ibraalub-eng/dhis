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
