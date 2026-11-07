"""Outliers screen consumes the Single Outlier Engine (Phase 1).

The screen is a READER: ``LayeredOutlierResult`` is the stored evidence and
classification, the effective band comes from the one policy entry point
(``layered.effective_severity``), and the join is keyed by the canonical
analysis code the projection wrote — never by a display name. These tests pin
that contract and the rule that missing evidence is reported as missing rather
than rendered as a valid classification.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.layered import build_analysis_specs
from app.engine.anomaly.projection import projection_codes
from app.models import AnomalyResult, Hospital, LayeredOutlierResult


@pytest.fixture
def client(app):
    """TestClient over the conftest app (auth and DB already overridden)."""
    return TestClient(app)


def _codes(db):
    return projection_codes(db)


def _add_layered_row(db, hospital_id, month, *, analysis_code="rate_cs", **overrides):
    fields = dict(
        hospital_id=hospital_id,
        analysis_code=analysis_code,
        month=month,
        raw_value=25.0,
        previous_value=10.0,
        denominator=100.0,
        rate=25.0,
        raw_value_outlier_score=None,
        rate_outlier_score=None,
        historical_outlier_score=None,
        volume_anomaly_score=None,
        peer_outlier_score=None,
        peer_count=None,
        peer_mean=None,
        historical_std=None,
        history_provenance=None,
        peer_provenance=None,
        classification_provenance=None,
        outlier_level="VERY_HIGH",
        outlier_type="HISTORICAL_ANOMALY",
        outlier_method="zscore",
        interpretation="stored evidence",
        investigation_route="contextual",
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def _peer_row(db, hospital_id, month, *, peers, peer_count,
              historical_score=None, history=None, analysis_code="rate_cs",
              **overrides):
    """A stored row whose peer layer can be graded (or capped) on read."""
    fields = dict(
        analysis_code=analysis_code,
        peer_outlier_score=1.0,
        peer_count=peer_count,
        peer_mean=(sum(peers) / len(peers) if peers else None),
        peer_provenance={"values": {str(i): value
                                    for i, value in enumerate(peers)}},
        outlier_method="peer_zscore",
        outlier_type="PEER_ANOMALY",
    )
    if history is not None:
        fields["history_provenance"] = {"values": list(history)}
        fields["historical_outlier_score"] = historical_score
    fields.update(overrides)
    return _add_layered_row(db, hospital_id, month, **fields)


def _add_projected_row(db, hospital_id, month, *, analysis_code="rate_cs",
                       rate_name="C-section rate", indicator_code=None,
                       **overrides):
    fields = dict(
        hospital_id=hospital_id,
        month=month,
        indicator_code=(indicator_code or _codes(db)[analysis_code]),
        rate_name=rate_name,
        value=90.0,
        benchmark=40.0,
        z_score=3.1,
        is_outlier=True,
    )
    fields.update(overrides)
    row = AnomalyResult(**fields)
    db.add(row)
    db.commit()
    return row


def _listed(client, month):
    resp = client.get("/analysis/outliers", params={"month": month, "limit": 100})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1, rows
    return rows[0]


# ── the join: canonical analysis code, never a display name ────────────────

def test_join_survives_a_renamed_indicator(db_session, client):
    """A registry rename changes the label, not the classification.

    The old join looked the layered row up by ``rate_name``; renaming a rate
    dropped the classification of every row it had already produced.
    """
    h = db_session.query(Hospital).first()
    _peer_row(db_session, h.id, "2028-01", peers=[10.0, 20.0, 30.0],
              peer_count=9)
    _add_projected_row(db_session, h.id, "2028-01",
                       rate_name="C-section rate (renamed 2026)")

    row = _listed(client, "2028-01")
    assert row["severity_status"] == "graded"
    assert row["layered_level"] == "VERY_HIGH"
    assert row["layered_type"] == "PEER_ANOMALY"


def test_join_follows_the_registry_mapping_when_the_codes_differ(
        db_session, client, monkeypatch):
    """A rate_config analysis code can resolve to a different definition code.

    That is exactly the case the name lookup used to paper over: the layered
    row is stored under the analysis code, the projected row under the
    definition code, and only the shared mapping knows they are the same rate.
    """
    import app.engine.anomaly.projection as projection

    real = projection.projection_codes
    monkeypatch.setattr(
        projection, "projection_codes",
        lambda db: {**real(db), "rate_cs": "cs_rate_alias"})

    h = db_session.query(Hospital).first()
    _add_layered_row(db_session, h.id, "2028-02", analysis_code="rate_cs",
                     outlier_level="HIGH")
    _add_projected_row(db_session, h.id, "2028-02",
                       indicator_code="cs_rate_alias")

    row = _listed(client, "2028-02")
    assert row["severity_status"] == "graded"
    assert row["layered_level"] == "HIGH"


def test_projection_codes_cover_rate_specs_only(db_session):
    """Data elements are never projected, so they never get a join entry."""
    specs = build_analysis_specs(db_session)
    codes = projection_codes(db_session)

    assert set(codes) == {s.analysis_code for s in specs if s.is_rate}
    assert codes["rate_cs"]
    count_codes = {s.analysis_code for s in specs if not s.is_rate}
    assert not (set(codes) & count_codes)


# ── missing evidence is named, not graded ─────────────────────────────────

def test_missing_layered_result_is_reported_as_missing(db_session, client):
    h = db_session.query(Hospital).first()
    _add_projected_row(db_session, h.id, "2028-03")

    row = _listed(client, "2028-03")
    assert row["severity_status"] == "missing_layered_result"
    assert row["layered_level"] is None
    assert row["layered_stored_level"] is None
    assert row["layered_type"] is None
    assert row["layered_is_detection"] is None


# ── one severity policy, applied by the backend ───────────────────────────

def test_zero_spread_cap_reaches_the_outliers_screen(db_session, client):
    h = db_session.query(Hospital).first()
    _peer_row(db_session, h.id, "2028-04", peers=[10.0] * 8, peer_count=8)
    _add_projected_row(db_session, h.id, "2028-04")

    row = _listed(client, "2028-04")
    assert row["layered_stored_level"] == "VERY_HIGH", "the row is not rewritten"
    assert row["layered_level"] == "HIGH"
    assert row["severity_cap"]["zero_spread_layers"] == ["peer"]


def test_thin_peer_cap_reaches_the_outliers_screen(db_session, client):
    h = db_session.query(Hospital).first()
    _peer_row(db_session, h.id, "2028-05", peers=[10.0, 11.0, 12.0],
              peer_count=3)
    _add_projected_row(db_session, h.id, "2028-05")

    row = _listed(client, "2028-05")
    assert row["layered_level"] == "HIGH"
    cap = row["severity_cap"]
    assert cap["thin_peer_group"]["capped"] is True
    assert cap["thin_peer_group"]["peer_count"] == 3


def test_very_high_gate_reaches_the_outliers_screen(db_session, client):
    """The history window does not support the top band → HIGH, stored kept."""
    h = db_session.query(Hospital).first()
    _add_layered_row(
        db_session, h.id, "2028-06",
        historical_outlier_score=1.0,
        history_provenance={"values": [10.0, 20.0, 35.0, 15.0]},
        outlier_type="HISTORICAL_ANOMALY", outlier_method="zscore")
    _add_projected_row(db_session, h.id, "2028-06")

    row = _listed(client, "2028-06")
    assert row["layered_stored_level"] == "VERY_HIGH"
    assert row["layered_level"] == "HIGH"
    assert row["severity_cap"]["route"] == "history"
    assert row["severity_cap"]["very_high_eligibility"]["capped"] is True


def test_outliers_and_diagnostics_report_the_same_band(db_session, client):
    """Two readers, one policy: the same row cannot show two severities."""
    h = db_session.query(Hospital).first()
    _peer_row(db_session, h.id, "2028-07", peers=[10.0, 11.0, 12.0],
              peer_count=3)
    _add_projected_row(db_session, h.id, "2028-07")

    outliers = _listed(client, "2028-07")
    diagnostics = client.get(
        "/analysis/layered", params={"month": "2028-07"}).json()["data"][0]

    assert outliers["layered_level"] == diagnostics["outlier_level"] == "HIGH"
    assert (outliers["layered_stored_level"]
            == diagnostics["stored_outlier_level"] == "VERY_HIGH")
    assert (outliers["severity_cap"]["severity"]
            == diagnostics["severity_cap"]["severity"] == "HIGH")


# ── existing filters are untouched ────────────────────────────────────────

def test_inactive_hospital_rows_are_not_listed(db_session, client):
    h = db_session.query(Hospital).first()
    _peer_row(db_session, h.id, "2028-08", peers=[10.0, 20.0, 30.0],
              peer_count=9)
    _add_projected_row(db_session, h.id, "2028-08")

    h.is_active = False
    db_session.commit()
    try:
        resp = client.get("/analysis/outliers", params={"month": "2028-08"})
        assert resp.status_code == 200
        assert resp.json()["data"] == []
    finally:
        h.is_active = True
        db_session.commit()


# ── the browser displays what the backend decided ─────────────────────────

def test_frontend_displays_the_backend_band_and_never_regrades():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js",
                        "outliers.js")
    with open(path, encoding="utf-8") as handle:
        js = handle.read()

    assert "d.layered_level" in js
    assert "d.layered_stored_level" in js
    assert "severity_status" in js
    assert "No evidence" in js
    # No policy reimplementation in the browser.
    assert "level_for_score" not in js
    assert "row_level_assessment" not in js
    assert "effective_severity" not in js

    html_path = os.path.join(os.path.dirname(__file__), "..", "static",
                             "tabs", "outliers.html")
    with open(html_path, encoding="utf-8") as handle:
        html = handle.read()
    assert 'data-col="layered_level"' in html
