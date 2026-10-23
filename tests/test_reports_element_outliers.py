"""Quality report must surface DATA-ELEMENT outliers, with their peers.

The classic anomaly engine only analyses derived rates, so reading its table
alone made every raw-element outlier invisible on the Quality report while the
Outlier Diagnostics screen showed them. These tests pin the layered merge and
the peer group that backs the report's tooltip.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.layered import build_analysis_specs
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)

MONTH = "2026-08"
CODE = "QA_REPORT_ELEMENT"


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def dataset(db_session):
    hospitals = db_session.query(Hospital).filter(
        Hospital.is_active.is_(True)).order_by(Hospital.id).limit(3).all()
    assert len(hospitals) == 3

    element = Indicator(code=CODE, name="QA report element",
                        indicator_type="count")
    db_session.add(element)
    db_session.flush()

    # The report hospital is far above both peers, so the layered engine has a
    # real comparison to show; every hospital has a value for the month.
    for hospital, value in zip(hospitals, (300.0, 40.0, 50.0), strict=True):
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=element.id,
            month=MONTH, value=value))

    db_session.add(QualityScore(
        hospital_id=hospitals[0].id, month=MONTH, score=88.0,
        rule_compliance=100.0, completeness=100.0, consistency=100.0,
        outlier_penalty=0.0, issues="[]"))

    # A real rate spec, so the rate row's AnomalyResult can be joined back to
    # the layered row that produced it (the report must not guess the link).
    spec = next(s for s in build_analysis_specs(db_session)
                if s.is_rate and s.analysis_code != "rate_cs")

    db_session.add_all([
        LayeredOutlierResult(
            hospital_id=hospitals[0].id, indicator_id=element.id,
            analysis_code=CODE, month=MONTH, raw_value=300.0,
            historical_mean=280.0, historical_z_score=1.2,
            peer_count=2, peer_mean=45.0,
            raw_value_outlier_score=1.0, rate_outlier_score=None,
            historical_outlier_score=0.35, volume_anomaly_score=None,
            peer_outlier_score=0.9, outlier_level="VERY_HIGH",
            outlier_type="PEER_OUTLIER", outlier_method="peer_zscore",
            interpretation="Peer outlier"),
        # A rate row: already covered by AnomalyResult, must not be duplicated.
        LayeredOutlierResult(
            hospital_id=hospitals[0].id, indicator_id=None,
            analysis_code="rate_cs", month=MONTH, rate=27.7,
            outlier_level="HIGH", outlier_type="RATE_OUTLIER"),
        # The rate's own layered row, with every layer scored.
        LayeredOutlierResult(
            hospital_id=hospitals[0].id, indicator_id=None,
            analysis_code=spec.analysis_code, month=MONTH,
            numerator=37.0, denominator=300.0, rate=12.34,
            previous_value=30.0, previous_denominator=280.0,
            historical_mean=11.0, historical_z_score=0.9,
            raw_value_outlier_score=0.10, rate_outlier_score=0.95,
            historical_outlier_score=0.40, volume_anomaly_score=0.20,
            peer_outlier_score=0.80, peer_mean=11.5, peer_count=2,
            outlier_level="VERY_HIGH", outlier_type="RATE_ANOMALY",
            outlier_method="peer_zscore", interpretation="Rate outlier"),
        # The projection row the report's anomaly table reads.
        AnomalyResult(
            hospital_id=hospitals[0].id, month=MONTH,
            indicator_code=spec.analysis_code, rate_name=spec.name,
            value=12.34, benchmark=11.5, z_score=0.4, is_outlier=True,
            peer_count=2, peer_std=2.1213, peer_min=10.0, peer_max=13.0,
            peer_median=11.5,
            peers_detail=[{"hospital": "Peer A", "rate": 10.0},
                          {"hospital": "Peer B", "rate": 13.0}]),
    ])
    db_session.commit()
    return {"hospital": hospitals[0], "peers": hospitals[1:],
            "element": element, "spec_name": spec.name}


def test_detail_lists_element_outliers_with_peer_hospitals(
        client, db_session, dataset):
    resp = client.get(f"/reports/detail/{dataset['hospital'].id}",
                      params={"month": MONTH})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    rows = payload["layered_results"]
    assert rows, "data-element outliers must be part of the quality report"
    assert "rate_cs" not in {r["analysis_code"] for r in rows}, \
        "rate rows are already covered by anomaly_results"

    row = next(r for r in rows if r["analysis_code"] == CODE)
    assert row["name"] == "QA report element"
    assert row["value"] == pytest.approx(300.0)
    assert row["outlier_level"] == "VERY_HIGH"
    assert row["is_outlier"] is True
    assert row["kind"] == "element"

    # The peer group the tooltip shows: exactly the other hospitals, with the
    # values the month actually holds.
    assert {p["name"] for p in row["peers"]} == {
        h.name for h in dataset["peers"]}
    assert {p["value"] for p in row["peers"]} == {40.0, 50.0}
    assert row["peer_count"] == 2


def test_element_row_carries_all_five_layers(client, dataset):
    """The report table shows the layer strip inline: every layer appears, in
    the engine's order, and one that could not be computed is reported as not
    applicable rather than as a clean zero."""
    resp = client.get(f"/reports/detail/{dataset['hospital'].id}",
                      params={"month": MONTH})
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["layered_results"]
               if r["analysis_code"] == CODE)

    layers = row["layers"]
    assert [layer["key"] for layer in layers] == [
        "raw", "rate", "historical", "volume", "peer"]
    by_key = {layer["key"]: layer for layer in layers}

    assert by_key["raw"]["score"] == pytest.approx(1.0)
    assert by_key["raw"]["level"] == "VERY_HIGH"
    assert by_key["raw"]["applicable"] is True
    assert by_key["historical"]["level"] == "LOW"
    assert by_key["peer"]["level"] == "VERY_HIGH"   # score 0.9

    # A count element has no rate and no denominator: those layers never ran.
    for key in ("rate", "volume"):
        assert by_key[key]["score"] is None
        assert by_key[key]["level"] is None
        assert by_key[key]["applicable"] is False

    assert by_key["raw"]["value"] == pytest.approx(300.0)


def test_element_row_reports_the_peer_statistics(client, dataset):
    """The peer layer shows the group it scored against: n, mean, ddof=1
    standard deviation, range and median — the same numbers the engine used."""
    resp = client.get(f"/reports/detail/{dataset['hospital'].id}",
                      params={"month": MONTH})
    row = next(r for r in resp.json()["layered_results"]
               if r["analysis_code"] == CODE)
    stats = row["peer_stats"]
    assert stats["count"] == 2
    assert stats["mean"] == pytest.approx(45.0)
    assert stats["std"] == pytest.approx(7.0711, rel=1e-3)
    assert stats["min"] == pytest.approx(40.0)
    assert stats["max"] == pytest.approx(50.0)
    assert stats["median"] == pytest.approx(45.0)


def test_rate_row_joins_its_layered_breakdown(client, dataset):
    """Rate findings get the same strip: the projection keeps one row per
    registry code, so the report resolves the layered row by rate name and
    falls back to the stored rate value."""
    resp = client.get(f"/reports/detail/{dataset['hospital'].id}",
                      params={"month": MONTH})
    assert resp.status_code == 200, resp.text
    rate_row = next(a for a in resp.json()["anomaly_results"]
                    if a["rate_name"] == dataset["spec_name"])

    by_key = {layer["key"]: layer for layer in rate_row["layers"]}
    assert list(by_key) == ["raw", "rate", "historical", "volume", "peer"]
    assert by_key["rate"]["score"] == pytest.approx(0.95)
    assert by_key["volume"]["applicable"] is True
    assert by_key["peer"]["level"] == "HIGH"        # score 0.8, not 0.9

    stats = rate_row["peer_stats"]
    assert stats["count"] == 2
    assert stats["mean"] == pytest.approx(11.5)
    assert stats["std"] == pytest.approx(2.1213, rel=1e-3)
    assert stats["min"] == pytest.approx(10.0)
    assert stats["max"] == pytest.approx(13.0)


def test_unmatched_rate_row_shows_no_layers_instead_of_guessing(client, dataset,
                                                               db_session):
    """An AnomalyResult whose rate name matches no analysis spec (renamed or
    removed) must not borrow another rate's breakdown: an empty strip is the
    honest answer."""
    db_session.add(AnomalyResult(
        hospital_id=dataset["hospital"].id, month=MONTH,
        indicator_code="rate_removed", rate_name="No Such Rate",
        value=99.0, is_outlier=True))
    db_session.commit()

    resp = client.get(f"/reports/detail/{dataset['hospital'].id}",
                      params={"month": MONTH})
    row = next(a for a in resp.json()["anomaly_results"]
               if a["rate_name"] == "No Such Rate")
    assert row["layers"] == []
    assert row["peer_stats"]["count"] == 0


def test_report_list_counts_element_outliers_for_the_card(client, dataset):
    resp = client.get("/reports/", params={"hospital_id": dataset["hospital"].id})
    assert resp.status_code == 200, resp.text
    report = next(r for r in resp.json() if r["month"] == MONTH)
    ids = {o["indicator_id"] for o in report["outliers"]}
    assert f"element:{CODE}" in ids, \
        "the card's outlier count must include data elements"
    entry = next(o for o in report["outliers"]
                 if o["indicator_id"] == f"element:{CODE}")
    assert entry["value"] == pytest.approx(300.0)
    assert entry["formula"] is None, "raw elements have no formula"
