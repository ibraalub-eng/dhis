"""Regression: the Why popup must not report a "covered" missing indicator.

Symptom: for الصحابة/مستشفيات/مستشفى الخير 2026-02, indicator 2.n (High risk
deliveries) had a persisted None row, but the reported children of the parent
sum rule already explained its absence — compute_covered_codes marked it
"covered", so completeness correctly did NOT penalize it. The Why popup's data
problems sweep, however, called find_data_problems without that gate and told
the user "🔧 Indicator 2.n has no value for this month" — contradicting the
completeness math on the very same popup.

Fix: find_data_problems(values, db) now applies the same covered-code gate as
completeness before flagging a None row as missing_value.
"""
import pytest
from fastapi.testclient import TestClient

from app.models import Hospital, Indicator, IndicatorValue, QualityScore
from app.cache import cache


@pytest.fixture()
def covered_month(db_session):
    """h1 2027-01: parent 2 == 2.a + 2.b with 2.a reported equal to the total,
    so 2.b is covered; 2.n also None but NOT covered (no rule explains it)."""
    from app.engine.quality import set_rules_config

    h = db_session.query(Hospital).order_by(Hospital.id).first()
    ids = {}
    for code in ("2", "2.a", "2.b", "2.n"):
        ind = db_session.query(Indicator).filter(Indicator.code == code).first()
        if not ind:
            ind = Indicator(code=code, name=f"Ind {code}", unit="count")
            db_session.add(ind)
            db_session.flush()
        ids[code] = ind.id

    vals = {"2": 100.0, "2.a": 100.0, "2.b": None, "2.n": None}
    for code, v in vals.items():
        db_session.add(IndicatorValue(
            hospital_id=h.id, month="2027-01", indicator_id=ids[code], value=v,
            source_file="covered_test.xlsx",
        ))
    db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=90.0))
    db_session.commit()
    cache.invalidate("analysis:months")
    # make the eq(2 == 2.a + 2.b) rule resolvable even without DB rules
    set_rules_config({"eq_tolerance": 0.01})
    return h


def _client(app):
    return TestClient(app)


def test_covered_missing_not_flagged_in_explanation(app, db_session, covered_month):
    """The Why payload must NOT contain a missing_value problem for 2.b
    (covered by the reported total) — while 2.n (genuinely missing, nothing
    explains it) must still be flagged."""
    h = covered_month
    client = _client(app)
    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2027-01")
    assert resp.status_code == 200
    payload = resp.json()

    problems = payload.get("data_problems") or []
    flagged = {p.get("indicator_code") for p in problems if p.get("kind") == "missing_value"}
    assert "2.b" not in flagged, (
        "covered indicator 2.b must not be reported as a missing-value problem "
        "— completeness already forgives it (the popup contradicted itself)"
    )
    assert "2.n" in flagged, "a genuinely missing, uncovered indicator must stay flagged"


def test_find_data_problems_covered_gate_unit(db_session, covered_month):
    """Unit level: with db, covered codes are skipped; without db, legacy
    behaviour flags every None row."""
    from app.engine.audit.explain import find_data_problems, _raw_values

    h = covered_month
    values = _raw_values(db_session, h.id, "2027-01")
    with_gate = {p["indicator_code"] for p in find_data_problems(values, db_session)}
    assert "2.b" not in with_gate
    assert "2.n" in with_gate

    legacy = {p["indicator_code"] for p in find_data_problems(values)}
    assert "2.b" in legacy and "2.n" in legacy, "db=None keeps legacy behaviour"
