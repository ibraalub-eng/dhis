"""Quality Alerts consume the canonical layered evidence (Phase 3).

There is ONE stored account of a comparison: the ``LayeredOutlierResult`` row
the layered engine writes. Where the alert scan asks the SAME question — the
hospital's own history window, and the detection baseline of every active
hospital — it now reads that stored score instead of computing it a second
time. A stratified perspective (type / ownership / facility type / governorate)
is a different population, keeps its own approved calculation and says so.

These tests pin:

1. an equivalent comparison consumes the stored layered score;
2. the same hospital/indicator/month reports one effective band on Quality
   Alerts, Outlier Diagnostics and Outliers;
3. the zero-spread cap, 4. the thin-peer cap and 5. the top-band gate agree;
6. stratified perspectives stay available and are identified as independent;
7. missing canonical evidence is explicit, never silently substituted;
8. a rescan does not duplicate alerts;
9. alert identity and closure behaviour are unchanged.
"""
import statistics

import pytest
from fastapi.testclient import TestClient

from app.api import quality_alerts as qa_api
from app.engine import quality_alerts as qa
from app.engine.anomaly.projection import projection_codes
from app.models import (
    AnomalyResult,
    FacilityOwnership,
    FacilityType,
    Governorate,
    Hospital,
    HospitalType,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityAlert,
    QualityAlertEvent,
)

MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08"]
SCAN_MONTH = MONTHS[-1]
ELEMENT_CODE = "QA_CANON"


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def dataset(db_session):
    """Three hospitals with real metadata + a data element that spikes."""
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:3]
    assert len(hospitals) == 3, hospitals
    governorate = Governorate(name="Canon Governorate")
    hospital_type = HospitalType(name="Canon Type")
    ownership = FacilityOwnership(name="Canon Ownership")
    facility_type = FacilityType(name="Canon Facility Type")
    db_session.add_all([governorate, hospital_type, ownership, facility_type])
    db_session.flush()
    for hospital in hospitals:
        hospital.governorate_id = governorate.id
        hospital.hospital_type_id = hospital_type.id
        hospital.facility_ownership_id = ownership.id
        hospital.facility_type_id = facility_type.id

    element = Indicator(code=ELEMENT_CODE, name="Canonical QA element")
    db_session.add(element)
    db_session.flush()

    series = {
        0: [10.0, 12.0, 11.0, 40.0],   # spikes in the scanned month
        1: [10.0, 12.0, 11.0, 12.0],
        2: [11.0, 12.0, 10.0, 12.0],
    }
    for index, hospital in enumerate(hospitals):
        for month, value in zip(MONTHS, series[index]):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=element.id,
                month=month, value=value))
    db_session.commit()
    return {"hospitals": hospitals, "element": element}


def _alerts(db, hospital_id, perspective=None, month=SCAN_MONTH):
    query = db.query(QualityAlert).filter(
        QualityAlert.hospital_id == hospital_id,
        QualityAlert.indicator_code == ELEMENT_CODE,
        QualityAlert.month == month)
    if perspective:
        query = query.filter(QualityAlert.perspective == perspective)
    return query.order_by(QualityAlert.id).all()


def _add_layered(db, hospital_id, month, **overrides):
    fields = dict(
        hospital_id=hospital_id, analysis_code=ELEMENT_CODE, month=month,
        raw_value=40.0, rate=None, outlier_level="VERY_HIGH",
        outlier_type="HISTORICAL_ANOMALY", outlier_method="zscore",
        historical_outlier_score=1.0,
        classification_provenance={"zero_spread_layers": [],
                                   "thin_peer_layers": [],
                                   "level": "VERY_HIGH", "cap": None},
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


# ── 1. An equivalent comparison consumes the stored layered score ──────────

def test_scan_consumes_canonical_layered_score_for_an_equivalent_history(
        db_session, dataset):
    """The stored layered score answers the alert instead of a second calc."""
    hospital = dataset["hospitals"][0]
    first = qa.scan(db_session, SCAN_MONTH)
    assert first["created"] > 0, first

    alert = _alerts(db_session, hospital.id, "history")[0]
    # The first scan had no canonical row to read: it says so, and it kept its
    # own calculation.
    assert alert.evidence["evidence_source"] == qa.EVIDENCE_SCAN
    assert (alert.evidence["canonical_evidence"]["status"]
            == qa.CANONICAL_MISSING)

    window = alert.evidence["history"]
    months = [month for month, _value in window]
    values = [value for _month, value in window]
    row = _add_layered(
        db_session, hospital.id, SCAN_MONTH,
        historical_outlier_score=0.93,
        historical_mean=statistics.fmean(values),
        historical_z_score=29.0,
        history_provenance={"months": months, "values": values},
    )

    second = qa.scan(db_session, SCAN_MONTH)
    assert second["created"] == 0, second
    assert second["updated"] >= 1, second

    refreshed = _alerts(db_session, hospital.id, "history")[0]
    assert refreshed.id == alert.id
    # The scan reuses the stored score rather than the 1.0 its own calculation
    # produces for this window, which is what proves the consumption.
    assert refreshed.score == pytest.approx(0.93)
    assert refreshed.evidence["evidence_source"] == qa.EVIDENCE_CANONICAL
    canonical = refreshed.evidence["canonical_evidence"]
    assert canonical["status"] == qa.CANONICAL_EQUIVALENT
    assert canonical["layer"] == qa.LAYER_HISTORY
    assert canonical["layered_result_id"] == row.id
    assert canonical["perspective"] == "history"
    assert canonical["score"] == pytest.approx(0.93)
    assert canonical["stored_level"] == "VERY_HIGH"


# ── 7. Missing / non-comparable evidence is explicit ───────────────────────

def test_missing_canonical_evidence_is_explicit(db_session, dataset):
    """With no stored layered row the scan keeps its own calculation — loudly."""
    qa.scan(db_session, SCAN_MONTH)
    rows = _alerts(db_session, dataset["hospitals"][0].id)
    assert rows
    for alert in rows:
        assert alert.evidence["evidence_source"] == qa.EVIDENCE_SCAN
        block = alert.evidence["canonical_evidence"]
        assert block["status"] in {qa.CANONICAL_MISSING,
                                   qa.CANONICAL_INDEPENDENT}
        assert block["source"] == qa.EVIDENCE_SCAN


def test_a_different_window_is_not_treated_as_equivalent(db_session, dataset):
    """A stored row describing another window is never substituted."""
    hospital = dataset["hospitals"][0]
    qa.scan(db_session, SCAN_MONTH)
    alert = _alerts(db_session, hospital.id, "history")[0]
    window = alert.evidence["history"]
    months = [month for month, _value in window]
    values = [value for _month, value in window]

    _add_layered(
        db_session, hospital.id, SCAN_MONTH,
        historical_outlier_score=0.31,
        history_provenance={"months": months, "values": values[:-1] + [999.0]},
    )
    qa.scan(db_session, SCAN_MONTH)

    refreshed = _alerts(db_session, hospital.id, "history")[0]
    assert refreshed.score != pytest.approx(0.31)
    assert refreshed.evidence["evidence_source"] == qa.EVIDENCE_SCAN
    assert (refreshed.evidence["canonical_evidence"]["status"]
            == qa.CANONICAL_NOT_EQUIVALENT)


# ── 6. Stratified perspectives stay independent and identified ────────────

def test_stratified_perspective_stays_independent_and_identified(
        db_session, dataset):
    """A regional/type peer group is not the detection baseline."""
    qa.scan(db_session, SCAN_MONTH)
    hospital = dataset["hospitals"][0]
    stratified = [a for a in _alerts(db_session, hospital.id)
                  if a.perspective not in {"history", "all"}]
    assert stratified, "stratified perspectives must remain available"
    for alert in stratified:
        assert alert.evidence["evidence_source"] == qa.EVIDENCE_SCAN
        block = alert.evidence["canonical_evidence"]
        assert block["status"] == qa.CANONICAL_INDEPENDENT
        assert block["perspective_scope"] == "stratified"
        assert (alert.evidence["comparison_policy"]["perspective_scope"]
                == "stratified")
    # The detection baseline is still its own row, labelled as such.
    all_rows = _alerts(db_session, hospital.id, "all")
    assert all_rows
    assert (all_rows[0].evidence["comparison_policy"]["perspective_scope"]
            == "detection_baseline")


# ── 2-5. One stored comparison, one band on all three screens ─────────────

def _rate_code(db):
    return projection_codes(db)["rate_cs"]


def _seed_parity(db, month, *, layer, alert):
    """One layered row + its projected Outliers row + its Quality Alert."""
    hospital = db.query(Hospital).order_by(Hospital.id).first()
    code = _rate_code(db)
    fields = dict(
        hospital_id=hospital.id, analysis_code="rate_cs", month=month,
        raw_value=25.0, rate=25.0, outlier_level="VERY_HIGH",
        outlier_type="PEER_ANOMALY", outlier_method="peer_zscore",
    )
    fields.update(layer)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.add(AnomalyResult(
        hospital_id=hospital.id, month=month, indicator_code=code,
        rate_name="C-section rate", value=25.0, benchmark=20.0,
        z_score=3.1, is_outlier=True))
    alert_fields = dict(
        hospital_id=hospital.id, month=month, perspective="all",
        indicator_code=code, indicator_name="C-section rate",
        severity="VERY_HIGH", score=1.0, method="peer_zscore",
        current_value=25.0, baseline_value=20.0, peer_count=8,
        status="New", active=True,
    )
    alert_fields.update(alert)
    record = QualityAlert(**alert_fields)
    db.add(record)
    db.commit()
    return row, record


def _three_bands(client, month, alert):
    """(Quality Alerts band, Diagnostics band, Outliers band)."""
    diagnostics = client.get("/analysis/layered", params={"month": month})
    assert diagnostics.status_code == 200, diagnostics.text
    diag_rows = diagnostics.json()["data"]
    assert len(diag_rows) == 1, diag_rows

    outliers = client.get("/analysis/outliers",
                          params={"month": month, "limit": 100})
    assert outliers.status_code == 200, outliers.text
    outlier_rows = outliers.json()["data"]
    assert len(outlier_rows) == 1, outlier_rows

    return (qa_api._effective_severity(alert),
            diag_rows[0]["outlier_level"],
            outlier_rows[0]["layered_level"])


_PARITY_CASES = {
    "zero_spread": (
        dict(peer_outlier_score=1.0, peer_count=8, peer_mean=10.0,
             peer_provenance={"values": {str(i): 10.0 for i in range(8)}}),
        dict(peer_count=8,
             evidence={"stats": {"mean": 10.0, "std": 0.0}}),
        "HIGH",
    ),
    "thin_peer": (
        dict(peer_outlier_score=1.0, peer_count=3, peer_mean=11.0,
             peer_provenance={"values": {"1": 10.0, "2": 11.0, "3": 12.0}}),
        dict(peer_count=3,
             evidence={"stats": {"mean": 11.0, "std": 1.0}}),
        "HIGH",
    ),
    "gate": (
        dict(peer_outlier_score=None, peer_count=None, peer_mean=None,
             peer_provenance=None, historical_outlier_score=1.0,
             outlier_type="HISTORICAL_ANOMALY", outlier_method="zscore",
             history_provenance={"values": [10.0, 20.0, 35.0, 15.0]}),
        dict(perspective="history", method="zscore", peer_count=4,
             current_value=25.0, baseline_value=20.0,
             evidence={
                 "stats": {"mean": 20.0,
                           "std": statistics.stdev([10.0, 20.0, 35.0, 15.0])},
                 "history": [["2029-09", 10.0], ["2029-10", 20.0],
                             ["2029-11", 35.0], ["2029-12", 15.0]],
                 "z_threshold": 2.5,
             }),
        "HIGH",
    ),
    "measured": (
        dict(peer_outlier_score=1.0, peer_count=9, peer_mean=20.0,
             peer_provenance={"values": {"1": 10.0, "2": 20.0, "3": 30.0}}),
        dict(peer_count=9,
             evidence={"stats": {"mean": 20.0, "std": 10.0}}),
        "VERY_HIGH",
    ),
}


@pytest.mark.parametrize("kind", sorted(_PARITY_CASES))
def test_three_screens_report_the_same_band(db_session, client, kind):
    """The exact disagreement this phase removes: three readers, one band."""
    layer, alert_fields, expected = _PARITY_CASES[kind]
    _row, alert = _seed_parity(db_session, "2029-01", layer=layer,
                               alert=alert_fields)

    alerts_band, diag_band, outliers_band = _three_bands(
        client, "2029-01", alert)
    assert alerts_band == diag_band == outliers_band == expected


def test_zero_spread_cap_is_identical_on_all_three_screens(db_session, client):
    layer, alert_fields, _expected = _PARITY_CASES["zero_spread"]
    _row, alert = _seed_parity(db_session, "2029-02", layer=layer,
                               alert=alert_fields)

    assert _three_bands(client, "2029-02", alert) == ("HIGH", "HIGH", "HIGH")
    payload = qa_api._alert_dict(alert)
    assert payload["severity"] == "HIGH"
    assert payload["stored_severity"] == "VERY_HIGH"
    assert payload["severity_cap"]["dispersion"]["zero_spread"] is True


def test_thin_peer_cap_is_identical_on_all_three_screens(db_session, client):
    layer, alert_fields, _expected = _PARITY_CASES["thin_peer"]
    _row, alert = _seed_parity(db_session, "2029-03", layer=layer,
                               alert=alert_fields)

    assert _three_bands(client, "2029-03", alert) == ("HIGH", "HIGH", "HIGH")
    payload = qa_api._alert_dict(alert)
    assert payload["severity_cap"]["thin_peer_group"]["peer_count"] == 3


def test_top_band_gate_is_identical_on_all_three_screens(db_session, client):
    layer, alert_fields, _expected = _PARITY_CASES["gate"]
    _row, alert = _seed_parity(db_session, "2029-04", layer=layer,
                               alert=alert_fields)

    assert _three_bands(client, "2029-04", alert) == ("HIGH", "HIGH", "HIGH")
    payload = qa_api._alert_dict(alert)
    gate = payload["severity_cap"]["very_high_eligibility"]
    assert gate["eligible"] is False
    assert gate["final_level"] == "HIGH"


# ── 8-9. Alert identity, deduplication and closure ────────────────────────

def test_rescan_does_not_duplicate_alerts(db_session, dataset):
    hospital = dataset["hospitals"][0]
    first = qa.scan(db_session, SCAN_MONTH)
    rows = _alerts(db_session, hospital.id)
    assert len(rows) == first["created"]
    ids = [row.id for row in rows]

    second = qa.scan(db_session, SCAN_MONTH)
    assert second["created"] == 0
    assert [row.id for row in _alerts(db_session, hospital.id)] == ids


def test_rescan_preserves_alert_identity_and_closure(db_session, dataset):
    hospital = dataset["hospitals"][0]
    qa.scan(db_session, SCAN_MONTH)
    alert = _alerts(db_session, hospital.id, "history")[0]
    events_before = db_session.query(QualityAlertEvent).filter(
        QualityAlertEvent.alert_id == alert.id).count()

    alert.status = "Resolved"
    alert.assignee = "qa-reviewer"
    db_session.commit()

    qa.scan(db_session, SCAN_MONTH)
    refreshed = _alerts(db_session, hospital.id, "history")[0]
    assert refreshed.id == alert.id
    # The scan refreshes statistics; it never reopens, re-creates or
    # duplicates the finding, and it appends no event of its own.
    assert refreshed.status == "Resolved"
    assert refreshed.assignee == "qa-reviewer"
    assert refreshed.active is True
    assert db_session.query(QualityAlertEvent).filter(
        QualityAlertEvent.alert_id == refreshed.id).count() == events_before
