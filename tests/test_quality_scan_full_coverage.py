"""Coverage guard: the Quality Alerts scan searches every catalog kind.

The contract this file locks (``app/engine/quality_alerts.py``):

* **registered indicators** — every ACTIVE ``IndicatorDefinition``, whether a
  system rate spec or a user-managed derivative formula — are computed by the
  shared indicator engine and persisted with ``indicator_id`` + formula/version
  provenance;
* **raw catalog data elements** (``Indicator`` rows) are read as stored: no
  formula is invented for them, so their alerts carry ``indicator_id = NULL``,
  no formula and no clinical direction;
* the synthetic form-header label (``SYNTHETIC_INDICATOR_CODES``, ``"0"``) is
  never a candidate, and a data element whose code collides with a registry
  definition never shadows it.

The dataset uses the conftest's three hospitals (peer perspectives need
``alerts_min_peers = 2`` other hospitals) and four months (the history
perspective needs ``alerts_min_history = 3`` priors).
"""
import pytest
from fastapi.testclient import TestClient

from app.engine import quality_alerts as qa
from app.engine.quality_alerts import (
    INTERP_HIGH_CONCERN,
    INTERP_STATISTICAL_ONLY,
    resolve_data_elements,
    resolve_registry,
)
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    QualityAlert,
)

MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08"]
SCAN_MONTH = MONTHS[-1]

ELEMENT_CODE = "QA_ELEMENT_COUNT"   # raw data element, scanned as stored
NUM_CODE = "QA_RAW_NUM"             # inputs of the derivative formula
DEN_CODE = "QA_RAW_DEN"
DERIVED_CODE = "QA_DERIVED_RATE"    # non-system (user-managed) definition


@pytest.fixture
def client(app):
    """TestClient over the conftest app (`_bypass_auth` overrides auth/db)."""
    return TestClient(app)


def _hospitals(db_session):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(3).all()
    assert len(hospitals) == 3, "conftest seeds three active hospitals"
    return hospitals


def _add_values(db_session, indicator, rows):
    """rows = {hospital_index: [v_may, v_jun, v_jul, v_aug]}"""
    hospitals = _hospitals(db_session)
    for index, values in rows.items():
        for month, value in zip(MONTHS, values, strict=True):
            db_session.add(IndicatorValue(
                hospital_id=hospitals[index].id,
                indicator_id=indicator.id,
                month=month,
                value=value,
            ))


@pytest.fixture
def dataset(db_session):
    """One raw element + one derivative rate over the same three hospitals.

    Hospital 1 spikes in the scan month for both kinds; hospitals 2 and 3 stay
    flat, so the element has both history and peer evidence.
    """
    element = Indicator(code=ELEMENT_CODE, name="QA data element",
                        indicator_type="count")
    num = Indicator(code=NUM_CODE, name="QA numerator",
                    indicator_type="count")
    den = Indicator(code=DEN_CODE, name="QA denominator",
                    indicator_type="count")
    db_session.add_all([element, num, den])
    db_session.flush()

    derived = IndicatorDefinition(
        code=DERIVED_CODE,
        name="QA derived rate",
        formula_type="ratio",
        numerator_codes=[NUM_CODE],
        denominator_codes=[DEN_CODE],
        operator="/",
        multiplier=100.0,
        result_type="percentage",
        unit="%",
        direction="lower_is_better",
        is_active=True,
        is_system=False,
    )
    db_session.add(derived)
    db_session.flush()

    _add_values(db_session, element, {
        0: [1.0, 1.0, 2.0, 10.0],
        1: [1.0, 1.0, 1.0, 1.0],
        2: [2.0, 2.0, 1.0, 1.0],
    })
    _add_values(db_session, num, {
        0: [10.0, 10.0, 10.0, 80.0],
        1: [10.0, 10.0, 10.0, 10.0],
        2: [9.0, 9.0, 9.0, 9.0],
    })
    _add_values(db_session, den, {0: [100.0] * 4, 1: [100.0] * 4,
                                  2: [100.0] * 4})
    db_session.commit()
    return {"derived": derived}


def _scan(client, month=SCAN_MONTH):
    resp = client.post("/quality-alerts/scan", json={"month": month})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _alerts(db_session, code):
    return (db_session.query(QualityAlert)
            .filter(QualityAlert.indicator_code == code)
            .all())


# ── 1. Raw data elements are scanned as stored ──────────────────────────────

def test_raw_data_element_is_scanned_as_stored(client, db_session, dataset):
    payload = _scan(client)
    assert payload["hospitals_scanned"] == 3
    assert not payload["errors"], payload["errors"]

    alerts = _alerts(db_session, ELEMENT_CODE)
    assert alerts, "raw data elements must be scanned (spec §10)"
    spike = [a for a in alerts if a.current_value == pytest.approx(10.0)]
    assert spike, "the stored value itself must be profiled, not a formula"
    for alert in alerts:
        # No registry definition exists for a data element: the provenance
        # columns must stay empty instead of pointing at some other formula.
        assert alert.indicator_id is None
        assert alert.formula is None
        assert alert.direction == "none"
        assert alert.interpretation == INTERP_STATISTICAL_ONLY


# ── 2. Non-system (derivative) definitions are scanned ──────────────────────

def test_derivative_definition_is_scanned_with_registry_provenance(
        client, db_session, dataset):
    payload = _scan(client)
    assert not payload["errors"], payload["errors"]

    alerts = _alerts(db_session, DERIVED_CODE)
    assert alerts, "user-managed derived definitions must be scanned"

    spike = [a for a in alerts if a.current_value == pytest.approx(80.0)]
    assert spike, "the rate must be computed from its registry formula"
    for alert in alerts:
        assert alert.indicator_id == dataset["derived"].id
        assert alert.formula and NUM_CODE in alert.formula
        assert alert.formula_version == "1"
        assert alert.unit == "%"
    # direction="lower_is_better" is definition metadata: a high rate is a
    # review trigger, never a bare statistical deviation.
    assert any(a.interpretation == INTERP_HIGH_CONCERN for a in spike)


# ── 3. One scan covers both kinds together ──────────────────────────────────

def test_scan_searches_raw_and_derivative_kinds_in_one_pass(
        client, db_session, dataset):
    scanned_codes = {r.code for r in resolve_registry(db_session)}
    assert DERIVED_CODE in scanned_codes
    element_codes = {e.code for e in resolve_data_elements(db_session)}
    assert ELEMENT_CODE in element_codes

    payload = _scan(client)
    codes = {a.indicator_code for a in db_session.query(QualityAlert).all()}
    assert {ELEMENT_CODE, DERIVED_CODE} <= codes, (
        "a single scan must produce findings for both catalog kinds")
    assert payload["created"] >= 2


# ── 4. The synthetic form-header label is never a candidate ─────────────────

def test_synthetic_form_header_code_is_never_scanned(client, db_session):
    assert "0" in SYNTHETIC_INDICATOR_CODES
    header = db_session.query(Indicator).filter_by(code="0").one()
    for hospital in _hospitals(db_session):
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=header.id,
            month=SCAN_MONTH, value=1e9))
    db_session.commit()

    assert "0" not in {e.code for e in resolve_data_elements(db_session)}

    _scan(client)
    assert db_session.query(QualityAlert).filter_by(indicator_code="0").count() == 0


# ── 5. A data element never shadows a registry definition ───────────────────

def test_element_code_colliding_with_a_definition_loses_to_it(
        client, db_session, dataset):
    # A stray catalog row reusing the derivative's code, with its own value.
    stray = Indicator(code=DERIVED_CODE, name="Stray element",
                      indicator_type="count")
    db_session.add(stray)
    db_session.flush()
    _add_values(db_session, stray, {0: [999.0] * 4, 1: [999.0] * 4,
                                    2: [999.0] * 4})
    db_session.commit()

    _scan(client)

    alerts = _alerts(db_session, DERIVED_CODE)
    assert alerts
    assert all(a.indicator_id == dataset["derived"].id for a in alerts), (
        "the managed definition must own a code that also exists as an element")
    assert not any(a.current_value == pytest.approx(999.0) for a in alerts)


# ── 6. History is fetched once per hospital, not per item ───────────────────

def test_history_fetched_once_per_hospital_not_per_item(
        client, db_session, dataset, monkeypatch):
    """With 100+ catalog items this must stay O(hospitals), not O(items)."""
    calls = {"n": 0}
    real = qa.get_historical_months

    def counting(session, hospital_id, month):
        calls["n"] += 1
        return real(session, hospital_id, month)

    monkeypatch.setattr(qa, "get_historical_months", counting)

    payload = _scan(client)
    assert payload["hospitals_scanned"] == 3
    # Exactly one fetch per participating hospital: >0 proves the history
    # perspective actually ran, ==3 prevents a per-item regression.
    assert calls["n"] == 3, (
        f"history fetched {calls['n']}× — must be cached per hospital per scan")
