"""US-12: a Dashboard KPI number and its drilldown must answer the same
question over the SAME filtered dataset. The drilldown (``/dashboard/
component-diagnostics``) must apply the exact same "actually analyzed",
disabled-month, hospital-scope and user-scope filters as ``/dashboard/kpi``,
so clicking a KPI card can always explain the number shown on it.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


_INDICATORS = {"2": 100, "2.a": 60, "2.b": 40, "3": 50, "4": 30}


def _seed(db, hospital_id, month, values=_INDICATORS):
    from app.models import Indicator, IndicatorValue
    for code, value in values.items():
        ind = db.query(Indicator).filter(Indicator.code == code).first()
        if ind is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital_id, month=month,
                              indicator_id=ind.id, value=value))
    db.commit()


def _analyze(db, hospital_id, month):
    from app.api.indicator_config import _recalc_hospital_scores
    from app.engine.pipeline import run_full_analysis
    run_full_analysis(db, hospital_id, month, force=True)
    _recalc_hospital_scores(db, hospital_id)


def _seed_analyze(db, hospital_id, month, values=_INDICATORS):
    _seed(db, hospital_id, month, values)
    _analyze(db, hospital_id, month)


def _kpis(client, **params):
    r = client.get("/dashboard/kpi", params=params)
    assert r.status_code == 200
    return {k["id"]: k for k in r.json()["kpis"]}


def _comps(client, **params):
    r = client.get("/dashboard/component-diagnostics", params=params)
    assert r.status_code == 200
    return {c["key"]: c for c in r.json()["components"]}


_PARITY_KEYS = ["rule_compliance", "completeness", "consistency", "outlier_score"]


def _assert_parity(kpis, comps):
    assert set(_PARITY_KEYS).issubset(comps), f"missing component keys: {comps.keys()}"
    for key in _PARITY_KEYS:
        assert kpis[key]["value"] == pytest.approx(comps[key]["avg"], abs=0.2), (
            f"{key}: KPI={kpis[key]['value']} drilldown={comps[key]['avg']}")


def test_single_month_parity(client, db_session):
    for hid in (1, 2, 3):
        _seed_analyze(db_session, hid, "2026-03")
    kpis = _kpis(client, month="2026-03")
    comps = _comps(client, month_from="2026-03", month_to="2026-03")
    _assert_parity(kpis, comps)


def test_range_parity(client, db_session):
    for hid in (1, 2):
        _seed_analyze(db_session, hid, "2026-01")
        _seed_analyze(db_session, hid, "2026-02")
    kpis = _kpis(client, month_from="2026-01", month_to="2026-02")
    comps = _comps(client, month_from="2026-01", month_to="2026-02")
    _assert_parity(kpis, comps)


def test_year_parity(client, db_session):
    for hid in (1, 3):
        _seed_analyze(db_session, hid, "2026-04")
        _seed_analyze(db_session, hid, "2025-04")
    kpis = _kpis(client, year="2026")
    comps = _comps(client, year="2026")
    _assert_parity(kpis, comps)


def test_hospital_filter_parity(client, db_session):
    _seed_analyze(db_session, 1, "2026-05")
    _seed_analyze(db_session, 2, "2026-05", {"2": 80, "2.a": 20})
    kpis = _kpis(client, hospital_id=1, month="2026-05")
    comps = _comps(client, hospital_id=1, month_from="2026-05", month_to="2026-05")
    _assert_parity(kpis, comps)


def test_disabled_month_excluded_from_both(client, db_session):
    """A month disabled for a hospital must leave the drilldown exactly as it
    leaves the KPI. The KPI already drops it; if the drilldown keeps it the
    number the KPI card shows becomes unexplainable."""
    from app.models import SystemSetting

    _seed_analyze(db_session, 1, "2026-01")
    _seed_analyze(db_session, 1, "2026-02", {"2": 100, "3": 0})
    db_session.add(SystemSetting(key="month_enabled_1_2026-02", value="false"))
    db_session.commit()

    params = {"hospital_id": 1, "month_from": "2026-01", "month_to": "2026-02"}
    kpis = _kpis(client, **params)
    comps = _comps(client, **params)
    # the KPI is a statement about 2026-01 only (2026-02 disabled)
    assert comps["rule_compliance"]["monthly"], "drilldown returned no monthly series"
    assert all(m["month"] != "2026-02" for m in comps["rule_compliance"]["monthly"]), (
        "disabled month leaked into the drilldown")
    _assert_parity(kpis, comps)


def test_user_hospital_scope_applies_to_both(client, db_session, monkeypatch):
    """A hospital-restricted user must see the same reduced dataset in the KPI
    and its drilldown (never a network-wide drilldown under a scoped KPI)."""
    _seed_analyze(db_session, 1, "2026-06", {"2": 100, "2.a": 100})
    _seed_analyze(db_session, 2, "2026-06", {"2": 100, "3": 0})
    monkeypatch.setattr("app.api.dashboard.get_user_hospital_ids",
                        lambda user, db: [1])

    params = {"month_from": "2026-06", "month_to": "2026-06"}
    kpis = _kpis(client, **params)
    comps = _comps(client, **params)
    # the scoped KPI must equal a hospital-1-only KPI, never the network number
    h1_kpi = _kpis(client, hospital_id=1, **params)
    assert kpis["rule_compliance"]["value"] == pytest.approx(
        h1_kpi["rule_compliance"]["value"], abs=0.1)
    _assert_parity(kpis, comps)


def test_empty_window_returns_no_components(client, db_session):
    """A window with no analyzed rows is NO DATA in both: the KPI reports null
    and the drilldown reports no components (not a fabricated 0.0)."""
    _seed_analyze(db_session, 1, "2026-07")
    kpis = _kpis(client, year="2099")
    comps = _comps(client, year="2099")
    assert kpis["quality_score"]["value"] is None
    assert comps == {}


def test_optional_element_not_listed_as_missing_gap(client, db_session):
    """The completeness drilldown names missing REQUIRED elements only.

    An Optional element (Data Tree flag) sits outside the completeness
    denominator, so listing it under "missing indicators" contradicts the very
    score the drilldown explains — the same false gap the Why popup showed as
    "🔧 Indicator 17.g has no value for this month".
    """
    from app.cache import cache
    from app.models import Hospital, Indicator, IndicatorValue, QualityScore

    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    req = db_session.query(Indicator).filter(Indicator.code == "2").one()
    opt = db_session.query(Indicator).filter(Indicator.code == "19").one()
    opt.requirement_type = "Optional"
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-05",
                                 indicator_id=req.id, value=10))
    db_session.add(QualityScore(hospital_id=hosp.id, month="2027-05",
                                score=40.0, completeness=10.0))
    db_session.commit()
    cache.invalidate()

    comps = _comps(client, hospital_id=hosp.id, month="2027-05")
    rows = [r for cause in comps["completeness"]["causes"]
            for r in cause["affected_hospitals"]]
    assert rows, "the hospital must appear in the completeness drilldown"
    missing = {name for row in rows for name in row.get("missing_indicators", [])}
    assert opt.name not in missing, (
        "an Optional element must never be reported as a missing gap"
    )
    assert req.name not in missing, "a reported element is not missing"
    assert missing, "genuinely missing required elements must still be listed"
