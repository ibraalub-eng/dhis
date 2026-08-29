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


def _seed_report_data(db_session, months):
    from app.models import Hospital, HospitalType, Indicator, IndicatorValue
    htype = HospitalType(name="ReportGov")
    db_session.add(htype)
    db_session.flush()
    hospitals = [Hospital(name=f"RepH{i}", hospital_type_id=htype.id, is_active=True) for i in range(3)]
    db_session.add_all(hospitals)
    db_session.flush()
    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in hospitals:
        for mi, m in enumerate(months):
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id["2"], month=m, value=200 + mi * 5))
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id["6"], month=m, value=120 + mi * 3))
    db_session.commit()


def test_comprehensive_report_endpoint_contract(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    try:
        _seed_report_data(db_session, ["2026-05", "2026-06"])
        client = TestClient(app)
        resp = client.get("/comparative/comprehensive-report/2026-06?lang=ar")
        assert resp.status_code == 200
        body = resp.json()
        assert body["month"] == "2026-06"
        assert body["report_source"] in ("ai", "local")
        sections = body.get("sections")
        assert sections is not None
        for key in SECTIONS:
            assert key in sections and str(sections[key]).strip(), f"empty/absent section: {key}"
        assert body["report"] == "\n\n".join(str(sections[k]) for k in SECTIONS)
        assert "data" in body and "decision" in body["data"] and "kpi" in body["data"]
    finally:
        app.dependency_overrides.pop(get_db, None)
