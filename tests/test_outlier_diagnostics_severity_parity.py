"""One severity policy for Outliers and Outlier Diagnostics (Phase 2).

Both screens read the SAME stored evidence (``LayeredOutlierResult``) and must
name the SAME effective band for it. The Outliers endpoint joins the layered row
to its projected ``AnomalyResult``; Diagnostics lists the layered row directly.
Both call ``layered.effective_severity``, which composes the policy ONCE: the
score bands, the zero-spread cap, the thin-peer cap and the top-band eligibility
gate. Nothing in the API or the browser re-derives a band.

Each test seeds one hospital/indicator/month, asks BOTH endpoints the same
question and asserts they answer identically — including the caps, the gate,
the HIGH/VERY_HIGH filters and the missing-evidence state.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.projection import projection_codes
from app.models import AnomalyResult, Hospital, LayeredOutlierResult


@pytest.fixture
def client(app):
    """TestClient over the conftest app (auth and DB already overridden)."""
    return TestClient(app)


def _hospital(db):
    return db.query(Hospital).order_by(Hospital.id).first()


def _add_layered(db, hospital_id, month, *, analysis_code="rate_cs", **overrides):
    """A stored row whose severity evidence the read path can grade."""
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
        outlier_level="VERY_HIGH",
        outlier_type="PEER_ANOMALY",
        outlier_method="peer_zscore",
        interpretation="stored evidence",
        investigation_route="data_quality",
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def _add_projected(db, hospital_id, month, *, analysis_code="rate_cs"):
    """The projected row the Outliers screen lists — same analysis unit."""
    row = AnomalyResult(
        hospital_id=hospital_id, month=month,
        indicator_code=projection_codes(db)[analysis_code],
        rate_name="C-section rate", value=90.0, benchmark=40.0,
        z_score=3.1, is_outlier=True,
    )
    db.add(row)
    db.commit()
    return row


def _peer_row(db, hospital_id, month, *, peers, peer_count, **overrides):
    """A row whose peer layer can be graded, capped or gated on read."""
    fields = dict(
        peer_outlier_score=1.0,
        peer_count=peer_count,
        peer_mean=(sum(peers) / len(peers) if peers else None),
        peer_provenance={"values": {str(i): value
                                    for i, value in enumerate(peers)}},
        outlier_method="peer_zscore",
        outlier_type="PEER_ANOMALY",
    )
    fields.update(overrides)
    return _add_layered(db, hospital_id, month, **fields)


def _seed(db, month, kind):
    """Seed one (hospital, rate, month) and its projected Outliers row."""
    hospital = _hospital(db)
    if kind == "zero_spread":
        _peer_row(db, hospital.id, month, peers=[10.0] * 8, peer_count=8)
    elif kind == "thin_peer":
        _peer_row(db, hospital.id, month, peers=[10.0, 11.0, 12.0],
                  peer_count=3)
    elif kind == "gate":
        # A history layer whose own window does not support the top band:
        # 25 against [10, 20, 35, 15] is not a maximal deviation.
        _add_layered(
            db, hospital.id, month,
            historical_outlier_score=1.0,
            history_provenance={"values": [10.0, 20.0, 35.0, 15.0]},
            outlier_type="HISTORICAL_ANOMALY", outlier_method="zscore",
            investigation_route="contextual",
        )
    elif kind == "measured":
        _peer_row(db, hospital.id, month, peers=[10.0, 20.0, 30.0],
                  peer_count=9)
    elif kind == "missing":
        # A stored row whose own severity was never written (legacy/aborted
        # write). The evidence exists; the band does not.
        _add_layered(db, hospital.id, month, outlier_level=None,
                     outlier_type="NORMAL", outlier_method="zscore")
    else:  # pragma: no cover - a typo in a test must fail loudly
        raise AssertionError(kind)
    _add_projected(db, hospital.id, month)
    return hospital


def _screens(client, month):
    """(Outliers row, Diagnostics row) for the one seeded result."""
    outliers = client.get("/analysis/outliers",
                          params={"month": month, "limit": 100})
    assert outliers.status_code == 200, outliers.text
    rows = outliers.json()["data"]
    assert len(rows) == 1, rows

    diag = client.get("/analysis/layered", params={"month": month})
    assert diag.status_code == 200, diag.text
    body = diag.json()
    assert body["total"] == 1, body
    return rows[0], body["data"][0]


def _band_filter(client, month, level):
    resp = client.get("/analysis/layered",
                      params={"month": month, "level": level})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. One row, one severity ───────────────────────────────────────────────

@pytest.mark.parametrize("kind,month,expected", [
    ("zero_spread", "2029-01", "HIGH"),
    ("thin_peer", "2029-02", "HIGH"),
    ("gate", "2029-03", "HIGH"),
    ("measured", "2029-04", "VERY_HIGH"),
])
def test_the_same_row_reports_the_same_band_on_both_screens(
        db_session, client, kind, month, expected):
    """The exact disagreement this phase removes: two readers, one band."""
    _seed(db_session, month, kind)

    outliers, diag = _screens(client, month)
    assert diag["outlier_level"] == outliers["layered_level"] == expected
    assert (diag["stored_outlier_level"]
            == outliers["layered_stored_level"] == "VERY_HIGH")
    assert diag["is_detection"] == outliers["layered_is_detection"] is True
    assert diag["severity_status"] == outliers["severity_status"] == "graded"
    if expected == "HIGH":
        assert (diag["severity_cap"]["severity"]
                == outliers["severity_cap"]["severity"] == "HIGH")
        assert (diag["severity_cap"]["stored_severity"]
                == outliers["severity_cap"]["stored_severity"] == "VERY_HIGH")
    else:
        assert "severity_cap" not in diag
        assert outliers["severity_cap"] is None


# ── 2. HIGH / VERY_HIGH filtering uses the effective band ─────────────────

def test_high_and_very_high_filters_follow_the_effective_band(
        db_session, client):
    """A row the policy caps to HIGH cannot be listed under VERY_HIGH."""
    _seed(db_session, "2029-05", "thin_peer")

    high = _band_filter(client, "2029-05", "HIGH")
    assert high["total"] == 1
    assert high["data"][0]["outlier_level"] == "HIGH"
    assert high["data"][0]["stored_outlier_level"] == "VERY_HIGH"

    top = _band_filter(client, "2029-05", "VERY_HIGH")
    assert top["total"] == 0 and top["data"] == []
    # …and the Outliers screen never calls it VERY_HIGH either.
    assert _screens(client, "2029-05")[0]["layered_level"] == "HIGH"


def test_the_top_band_filter_keeps_a_row_the_policy_still_allows(
        db_session, client):
    """The filter is a policy filter, not a blanket downgrade."""
    _seed(db_session, "2029-06", "measured")

    assert _band_filter(client, "2029-06", "VERY_HIGH")["total"] == 1
    assert _band_filter(client, "2029-06", "HIGH")["total"] == 0


# ── 3-5. The caps and the gate, on both screens ───────────────────────────

def test_zero_spread_cap_is_identical_on_both_screens(db_session, client):
    _seed(db_session, "2029-07", "zero_spread")

    outliers, diag = _screens(client, "2029-07")
    assert diag["outlier_level"] == outliers["layered_level"] == "HIGH"
    diag_cap, out_cap = diag["severity_cap"], outliers["severity_cap"]
    assert diag_cap["zero_spread_layers"] == out_cap["zero_spread_layers"] == ["peer"]
    assert diag_cap["thin_peer_group"] == out_cap["thin_peer_group"] is None
    assert diag_cap["cap"] == out_cap["cap"] == "HIGH"


def test_thin_peer_cap_is_identical_on_both_screens(db_session, client):
    _seed(db_session, "2029-08", "thin_peer")

    outliers, diag = _screens(client, "2029-08")
    assert diag["outlier_level"] == outliers["layered_level"] == "HIGH"
    diag_cap, out_cap = diag["severity_cap"], outliers["severity_cap"]
    assert diag_cap["thin_peer_group"] == out_cap["thin_peer_group"]
    assert diag_cap["thin_peer_group"]["peer_count"] == 3
    assert diag_cap["thin_peer_group"]["capped"] is True
    assert diag_cap["zero_spread_layers"] == out_cap["zero_spread_layers"] == []


def test_top_band_gate_is_identical_on_both_screens(db_session, client):
    _seed(db_session, "2029-09", "gate")

    outliers, diag = _screens(client, "2029-09")
    assert diag["outlier_level"] == outliers["layered_level"] == "HIGH"
    gate = diag["severity_cap"]["very_high_eligibility"]
    assert gate == outliers["severity_cap"]["very_high_eligibility"]
    assert (diag["severity_cap"]["route"]
            == outliers["severity_cap"]["route"] == "history")
    assert gate["capped"] is True
    assert gate["eligible"] is False
    assert gate["resolved_level"] == "VERY_HIGH"
    assert gate["final_level"] == "HIGH"
    assert gate["history_window"] == 4


# ── 6. Missing evidence is not a band ─────────────────────────────────────

def test_missing_severity_evidence_is_never_read_as_low(db_session, client):
    """No stored band → no band. Never LOW, and never a graded NONE either."""
    _seed(db_session, "2029-10", "missing")

    outliers, diag = _screens(client, "2029-10")
    assert diag["outlier_level"] is None
    assert diag["stored_outlier_level"] is None
    assert diag["is_detection"] is None
    assert (diag["severity_status"]
            == outliers["severity_status"] == "missing_layered_severity")
    assert outliers["layered_level"] is None
    assert outliers["layered_stored_level"] is None
    assert outliers["layered_is_detection"] is None
    assert "severity_cap" not in diag and outliers["severity_cap"] is None

    # It matches no band filter at all — LOW and NONE included.
    for level in ("LOW", "NONE", "MODERATE", "HIGH", "VERY_HIGH"):
        assert _band_filter(client, "2029-10", level)["total"] == 0, level


# ── 7. Disabled / inactive behaviour is unchanged ────────────────────────

def test_inactive_hospital_keeps_its_existing_behaviour(db_session, client):
    hospital = _seed(db_session, "2029-11", "measured")
    hospital.is_active = False
    db_session.commit()
    try:
        assert client.get(
            "/analysis/layered", params={"month": "2029-11"}).json()["total"] == 0
        assert client.get(
            "/analysis/outliers",
            params={"month": "2029-11"}).json()["data"] == []
    finally:
        hospital.is_active = True
        db_session.commit()


def test_disabled_month_keeps_its_existing_behaviour(db_session, client):
    from app.models import SystemSetting

    hospital = _seed(db_session, "2029-12", "measured")
    db_session.add(SystemSetting(key=f"month_enabled_{hospital.id}_2029-12",
                                 value="false"))
    db_session.commit()

    assert client.get(
        "/analysis/layered", params={"month": "2029-12"}).json()["total"] == 0
    assert client.get(
        "/analysis/outliers", params={"month": "2029-12"}).json()["data"] == []


# ── The browser renders the backend band, it never re-derives one ─────────

def test_the_diagnostics_frontend_renders_the_backend_band():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js",
                        "layered.js")
    with open(path, encoding="utf-8") as handle:
        js = handle.read()

    # Effective band + stored band + evidence state all come off the payload.
    assert "d.outlier_level" in js
    assert "d.stored_outlier_level" in js
    assert "d.severity_status" in js
    # Missing evidence has its own label, distinct from LOW and from NONE.
    assert "No evidence" in js
    assert "missing_layered_severity" in js
    # No policy reimplementation in the browser.
    for forbidden in ("level_for_score", "row_level_assessment",
                      "effective_severity"):
        assert forbidden not in js, forbidden
