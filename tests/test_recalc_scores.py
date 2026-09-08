"""Regression tests for score recalculation paths.

Guards against stale model-name imports (SystemConfig was renamed to
AppConfig but two API modules still referenced the old name), which made
POST /dashboard/recalculate-completeness return 500 and made indicator
toggles silently skip score recalculation.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import QualityScore


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_recalculate_completeness_empty_db(client):
    """Empty DB must return 200 with zero counts — a stale model import would 500 here."""
    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    assert resp.json() == {"updated": 0, "total": 0}


def test_recalculate_completeness_updates_scores(client, db_session):
    """With an existing quality score, completeness is recomputed and reported as updated."""
    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["updated"] == 1


def test_recalc_hospital_scores_no_crash(db_session):
    """Indicator score recalculation must not raise (regression: SystemConfig ImportError)."""
    from app.api.indicator_config import _recalc_hospital_scores

    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    # The imports inside the function run before any try/except, so the old
    # stale model name raised an ImportError here — assert it completes.
    _recalc_hospital_scores(db_session, 1)

    refreshed = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == "2027-01"
    ).first()
    assert refreshed is not None
    assert refreshed.completeness is not None


def test_toggle_indicator_endpoint(client, db_session):
    """Toggling an indicator returns the expected shape and doesn't crash recalculation."""
    from app.models import Indicator

    indicator = db_session.query(Indicator).first()
    assert indicator is not None

    resp = client.put(f"/hospitals/1/indicators/{indicator.id}/toggle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hospital_id"] == 1
    assert data["indicator_id"] == indicator.id
    assert data["is_enabled"] is False
    assert "message" in data


def _insert_indicator_value(db_session, hospital_id, month, code, value):
    from app.models import Indicator, IndicatorValue

    ind = db_session.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    db_session.add(IndicatorValue(
        hospital_id=hospital_id,
        month=month,
        indicator_id=ind.id,
        value=value,
    ))


def _all_active_indicator_count(db_session):
    from app.models import Indicator
    return db_session.query(Indicator).count()


def test_recalc_completeness_ignores_covered_children(client, db_session):
    """Missing sibling children whose partial sum equals the parent total must NOT
    reduce completeness in the dashboard recalculate path."""
    from app.models import QualityScore

    month = "2027-02"
    # Parent (Total Deliveries) fully accounted for by a subset of age groups.
    # 2.c, 2.d, 2.j are missing but 2.e+2.f+2.g+2.h+2.i == 2 (within tolerance).
    _insert_indicator_value(db_session, 1, month, "2", 27)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    total_indicators = _all_active_indicator_count(db_session)
    db_session.add(QualityScore(hospital_id=1, month=month, score=50.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["updated"] == 1

    qs = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month
    ).first()
    # present=6 (parent + 5 children), covered=3 (2.c, 2.d, 2.j),
    # active denominator excludes covered.
    filled_active = 6
    active_denom = total_indicators - 3
    expected_pct = round(filled_active / active_denom * 100, 1)
    assert qs.completeness == expected_pct


def test_recalc_completeness_still_penalizes_real_gaps(client, db_session):
    """When the partial age-group sum does NOT equal the total, the missing
    children remain missing and completeness reflects the true gap."""
    from app.models import QualityScore

    month = "2027-03"
    # 2.e+2.f+2.g+2.h+2.i == 27 but parent 2 == 31 -> 4 unaccounted -> NOT covered.
    _insert_indicator_value(db_session, 1, month, "2", 31)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    total_indicators = _all_active_indicator_count(db_session)
    db_session.add(QualityScore(hospital_id=1, month=month, score=50.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200

    qs = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month
    ).first()
    # present=6 (parent + 5 children), missing=3 not covered -> all active.
    expected_pct = round(6 / total_indicators * 100, 1)
    assert qs.completeness == expected_pct


def test_component_diagnostics_drilldown_excludes_covered_children(client, db_session):
    """The Completeness KPI drilldown must NOT list covered-by-parent indicators
    among its missing indicators."""
    from app.models import QualityScore

    month = "2027-04"
    # Parent fully accounted for by reported age groups; 2.c, 2.d, 2.j are covered.
    _insert_indicator_value(db_session, 1, month, "2", 27)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    db_session.add(QualityScore(hospital_id=1, month=month, score=30.0))
    db_session.commit()

    resp = client.get(
        "/dashboard/component-diagnostics?",
        params={
            "hospital_id": 1,
            "month_from": month,
            "month_to": month,
            "metric": "completeness",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    # Collect every missing indicator listed anywhere in the completeness drilldown
    listed_missing = set()
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                listed_missing.update(h.get("missing_indicators", []))

    # Covered children must not appear as missing
    from app.models import Indicator
    covered_names = {ind.name for ind in db_session.query(Indicator).filter(
        Indicator.code.in_(["2.c", "2.d", "2.j"])
    ).all()}
    overlap = listed_missing & covered_names
    assert not overlap, f"covered children listed as missing: {overlap}"

    # Genuinely missing indicators (e.g. 3, 4, 5) still appear
    non_covered_missing = db_session.query(Indicator.name).filter(
        Indicator.parent_id.is_not(None),
        Indicator.code.notin_(["2.c", "2.d", "2.j", "2.e", "2.f", "2.g", "2.h", "2.i"]),
    ).limit(1).first()
    if non_covered_missing:
        assert listed_missing, "expected some genuinely missing indicators in drilldown"


def test_component_diagnostics_missing_by_indicator_months(client, db_session):
    """Affected-hospital drilldown must report, per missing indicator, the months
    it was missing in (so users know the missing month for every indicator)."""
    from app.models import QualityScore

    # Hospital 1 missing e.g. '3' in two months. Hospital 1 has values for '2' only.
    for month in ("2027-05", "2027-06"):
        _insert_indicator_value(db_session, 1, month, "2", 10)
        db_session.add(QualityScore(hospital_id=1, month=month, score=30.0))
    db_session.commit()

    resp = client.get(
        "/dashboard/component-diagnostics?",
        params={"metric": "completeness", "month_from": "2027-05", "month_to": "2027-06"},
    )
    assert resp.status_code == 200
    data = resp.json()

    hospital_rows = []
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                if h["hospital_id"] == 1:
                    hospital_rows.append(h)

    assert hospital_rows, "hospital 1 should appear as affected"
    for h in hospital_rows:
        assert "missing_by_indicator" in h
        if h["missing_by_indicator"]:
            for item in h["missing_by_indicator"]:
                assert "indicator" in item and "months" in item
                missing_month = item["months"]
                assert set(missing_month) <= {"2027-05", "2027-06"}

    # Every indicator reported missing overall must map to at least one month
    all_months_by_ind = {}
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                if h["hospital_id"] == 1:
                    for item in h.get("missing_by_indicator", []):
                        all_months_by_ind.setdefault(item["indicator"], set()).update(item["months"])
    for name, months in all_months_by_ind.items():
        assert months, f"indicator {name!r} missing but has no reported months"