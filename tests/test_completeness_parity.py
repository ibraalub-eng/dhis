"""One fixture with Required, Optional, covered, zero and missing values must
produce the same completeness at every site (US-04)."""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _insert(db, hospital_id, month, code, value):
    from app.models import Indicator, IndicatorValue
    ind = db.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    db.add(IndicatorValue(hospital_id=hospital_id, month=month,
                          indicator_id=ind.id, value=value))


def test_completeness_parity_across_all_sites(client, db_session):
    from app.api.indicator_config import _recalc_hospital_scores
    from app.engine.pipeline import compute_hospital_completeness, run_full_analysis
    from app.models import Indicator, QualityScore

    month = "2028-01"
    # Required total "2" filled; child "2.a" filled so "2.b" becomes covered.
    _insert(db_session, 1, month, "2", 100)
    _insert(db_session, 1, month, "2.a", 60)
    # A required indicator that is genuinely missing ("3" left absent).
    # A required indicator with an explicit zero ("4") -> Filled.
    _insert(db_session, 1, month, "4", 0)
    # An Optional indicator WITH a value -> numerator only, never denominator.
    opt = db_session.query(Indicator).filter(Indicator.code == "16").first()
    from app.models import IndicatorValue
    db_session.add(IndicatorValue(hospital_id=1, month=month,
                                  indicator_id=opt.id, value=7))
    db_session.query(Indicator).filter(Indicator.id == opt.id).update(
        {"requirement_type": "Optional"}, synchronize_session=False)
    db_session.commit()

    # 1. Engine persists a QualityScore row.
    run_full_analysis(db_session, 1, month, force=True)
    stored = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month).first()
    assert stored is not None
    engine = stored.completeness

    # 2. Shared DB wrapper.
    wrapper = round(compute_hospital_completeness(db_session, 1, month), 1)

    # 3. KPI card.
    kpi = {x["id"]: x["value"] for x in client.get(
        "/dashboard/kpi", params={"hospital_id": 1, "month": month}).json()["kpis"]}

    # 4. Component-diagnostics drilldown.
    comp = client.get(
        "/dashboard/component-diagnostics",
        params={"hospital_id": 1, "month_from": month, "month_to": month,
                "metric": "completeness"},
    ).json()["components"][0]["avg"]

    # 5. Toggle recalc writes the same number.
    _recalc_hospital_scores(db_session, 1)
    toggled = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month).first().completeness

    assert wrapper == pytest.approx(engine, abs=0.1), (wrapper, engine)
    assert kpi["completeness"] == pytest.approx(engine, abs=0.2), (kpi["completeness"], engine)
    assert comp == pytest.approx(engine, abs=0.2), (comp, engine)
    assert toggled == pytest.approx(engine, abs=0.1), (toggled, engine)
