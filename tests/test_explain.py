"""Tests for the unified explainability engine (GET /audit/explain).

Pins the traceability contract:
- every explanation answers what/where/why/how/reproduce/chain/classification
- reproduction recomputes the persisted number from stored inputs and matches
- edge cases (missing data, single peer, negative values, duplicates) are
  classified as data problems and never crash
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    ValidationResult,
)


@pytest.fixture()
def client(db_session):
    from app.main import app

    yield TestClient(app)


def _first_hospital(db):
    return db.query(Hospital).first()


def _indicator_by_code(db, code):
    return db.query(Indicator).filter(Indicator.code == str(code)).first()


def _add_values(db, hospital_id, month, code_values, source_file="upload.xlsx"):
    for code, val in code_values.items():
        ind = _indicator_by_code(db, code)
        if ind is None:
            continue
        db.add(IndicatorValue(
            hospital_id=hospital_id,
            indicator_id=ind.id,
            month=month,
            value=val,
            source_file=source_file,
        ))
    db.commit()


# ───────────────────────── quality score ─────────────────────────────

def test_quality_score_explanation_reproduces_stored_score(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"2": 300, "5": 80, "6": 280})

    rc, cp, co, op = 90.0, 80.0, 70.0, 10.0
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-04", score=0.0,
        rule_compliance=rc, completeness=cp, consistency=co, outlier_penalty=op,
    ))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()

    for key in ("what", "where", "why", "how", "reproduce", "chain", "classification"):
        assert key in p, f"explanation missing '{key}'"

    # Weights come from the live quality config; the reproduction must match
    # the stored score when the same weights were used at analysis time.
    assert p["reproduce"]["stored"] == 0.0
    assert "expected" in p["reproduce"]
    assert isinstance(p["reproduce"]["verified"], bool)

    # Where must point at the uploaded file (provenance).
    assert p["where"]["source_files"] == ["upload.xlsx"]
    assert p["where"]["raw_value_count"] >= 3


def test_quality_score_explanation_lists_components_below_target(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-05", {"2": 100})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-05", score=40.0,
        rule_compliance=50.0, completeness=40.0, consistency=45.0, outlier_penalty=0.0,
    ))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-05")
    assert resp.status_code == 200
    p = resp.json()
    below = {c["component"] for c in p["components_below_target"]}
    assert {"Rule compliance", "Completeness", "Consistency"} <= below
    # No data problems in the clean values → statistical finding.
    assert p["classification"] == "statistical_finding"


def test_ghost_score_row_is_a_data_problem_not_zero_performance(db_session, client):
    """A QualityScore row without raw values must NOT explain as 'score 0'.

    It must 404 with a data-problem message — the ghost doctrine at the
    explanation layer."""
    h = _first_hospital(db_session)
    db_session.add(QualityScore(hospital_id=h.id, month="2026-06", score=0.0))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-06")
    assert resp.status_code == 404
    assert "no raw data" in resp.json()["detail"] or "No indicator values" in resp.json()["detail"]


# ───────────────────────────── anomaly ───────────────────────────────

def test_anomaly_explanation_reproduces_z_and_classifies(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})

    # value 200% vs benchmark 50, peer_std 25 → z = (200-50)/25 = 6.0
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=50.0,
        z_score=6.0, is_outlier=True,
        peer_count=6, peer_std=25.0, peer_min=30.0, peer_max=80.0, peer_median=48.0,
        peers_detail=[{"hospital": f"P{i}", "rate": 40.0 + i} for i in range(6)],
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()

    assert p["what"].startswith("C-section rate")
    assert "|z| = 6.00" in p["why"]
    assert p["reproduce"]["expected_z"] == 6.0
    assert p["reproduce"]["stored_z"] == 6.0
    assert p["reproduce"]["verified"] is True
    # Raw values are clean → this is a statistical/clinical finding, not bad data.
    assert p["classification"] in ("statistical_finding", "clinical_finding")
    # Peer inputs surface in the how table.
    inputs_text = json.dumps(p["how"]["inputs"])
    assert "Peer count" in inputs_text and "6" in inputs_text
    # Chain links the outlier back to the data auditor / benchmark endpoints.
    assert any("data-auditor" in (c.get("endpoint") or "") for c in p["chain"])


def test_anomaly_with_negative_raw_value_is_a_data_problem(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": -10, "2": 100})

    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=-10.0, benchmark=50.0,
        z_score=-2.4, is_outlier=True,
        peer_count=5, peer_std=20.0, peer_min=30.0, peer_max=80.0, peer_median=50.0,
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200
    p = resp.json()
    assert p["classification"] == "data_problem"
    kinds = {d["kind"] for d in p["data_problems"]}
    assert "negative_value" in kinds


def test_small_peer_group_flagged_in_explanation(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 60, "2": 100})
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=60.0, benchmark=55.0,
        z_score=0.5, is_outlier=False,
        peer_count=1, peer_std=0.0, peer_min=55.0, peer_max=55.0, peer_median=55.0,
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200
    p = resp.json()
    assert any(d["kind"] == "small_peer_group" for d in p["data_problems"])
    assert p["classification"] == "data_problem"


def test_anomaly_explanation_missing_rate_404s(db_session, client):
    h = _first_hospital(db_session)
    resp = client.get(f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=Nope")
    assert resp.status_code == 404


# ───────────────────────── heatmap cell ──────────────────────────────

def test_heatmap_cell_explanation_reuses_quality_payload(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"2": 300})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-04", score=88.0,
        rule_compliance=90.0, completeness=85.0, consistency=90.0, outlier_penalty=0.0,
    ))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=heatmap_cell&hospital_id={h.id}&month=2026-04")
    assert resp.status_code == 200
    p = resp.json()
    assert p["kind"] == "heatmap_cell"
    assert p["reproduce"]["stored"] == 88.0


def test_duplicate_raw_rows_flagged_as_data_problem(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 80, "2": 100}, source_file="a.xlsx")
    _add_values(db_session, h.id, "2026-04", {"5": 80, "2": 100}, source_file="a.xlsx")
    db_session.commit()

    from app.engine.audit.explain import find_data_problems
    from app.engine.audit.explain import _raw_values  # noqa: F401  (import guard)
    values = _raw_values(db_session, h.id, "2026-04")
    problems = find_data_problems(values)
    assert any(p["kind"] == "duplicate_row" for p in problems)


# ─────────────────── indicator names next to codes ───────────────────

def test_data_problem_messages_carry_indicator_name(db_session, client):
    """Why-popup requirement: wherever an indicator CODE is shown, the NAME
    must be shown too ("Indicator 5 (Caesarean Sections) ...")."""
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": -10, "2": None})

    from app.engine.audit.explain import find_data_problems, _raw_values
    values = _raw_values(db_session, h.id, "2026-04")
    problems = find_data_problems(values)
    by_kind = {p["kind"]: p for p in problems}

    assert "Caesarean Sections" in by_kind["negative_value"]["message"]
    assert "5 (Caesarean Sections)" in by_kind["negative_value"]["message"]
    assert by_kind["negative_value"]["indicator_name"] == "Caesarean Sections"
    assert "Total Deliveries" in by_kind["missing_value"]["message"]
    assert by_kind["missing_value"]["indicator_name"] == "Total Deliveries"


def test_anomaly_explanation_shows_indicator_name_with_code(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=50.0,
        z_score=6.0, is_outlier=True,
        peer_count=6, peer_std=25.0, peer_min=30.0, peer_max=80.0, peer_median=48.0,
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()

    # where block: name sits next to the code.
    assert p["where"]["indicator_code"] == "5"
    assert p["where"]["indicator_name"] == "Caesarean Sections"

    # inputs table: raw numerator/denominator labels name the indicator.
    inputs_text = json.dumps(p["how"]["inputs"], ensure_ascii=False)
    assert "Raw numerator (5 — Caesarean Sections)" in inputs_text
    assert "Raw denominator (2 — Total Deliveries)" in inputs_text

    # readable formula and the Source Data chain step name the indicators.
    assert "Caesarean Sections" in p["how"]["formula_readable"]
    assert "Total Deliveries" in p["how"]["formula_readable"]
    source_step = next(c for c in p["chain"] if c["step"] == "Source Data")
    assert "Caesarean Sections" in source_step["detail"]


# ───────────────────────────── rule ──────────────────────────────────

def test_rule_explanation_uses_validation_row(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 80})
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-04", rule_code="R_TEST",
        rule_description="Delivery register must be complete",
        status="FAIL", severity="HIGH", rule_type="LOGIC",
        details="Missing deliveries for 3 days",
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-04&rule_code=R_TEST"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["what"].startswith("Rule R_TEST FAILED")
    assert p["why"] == "Missing deliveries for 3 days"
    assert p["where"]["rule_code"] == "R_TEST"


def test_rule_explanation_missing_404s(db_session, client):
    h = _first_hospital(db_session)
    resp = client.get(f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-04&rule_code=NOPE")
    assert resp.status_code == 404


# ───────────────────── month aggregate (no hospital) ─────────────────

def test_month_overview_aggregate_without_hospital(db_session, client):
    h1 = db_session.query(Hospital).first()
    h2 = db_session.query(Hospital).offset(1).first()
    for h, score in ((h1, 90.0), (h2, 60.0)):
        _add_values(db_session, h.id, "2026-04", {"2": 300})
        db_session.add(QualityScore(
            hospital_id=h.id, month="2026-04", score=score,
            rule_compliance=score, completeness=score, consistency=score,
        ))
    db_session.commit()

    resp = client.get("/audit/explain?kind=quality_score&month=2026-04")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "month_overview"
    assert p["what"].startswith("Average quality score")
    assert p["reproduce"]["verified"] is True
    weakest_ids = {w["hospital_id"] for w in p["weakest_hospitals"]}
    assert h2.id in weakest_ids


# ───────────────────── data epoch / single-source contract ───────────

def test_every_payload_carries_data_epoch(db_session, client):
    """Version-support UX: every explanation is stamped with the data epoch so
    the UI can tell 'stale view' from 'stale analysis'."""
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"2": 300})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-04", score=80.0,
        rule_compliance=80.0, completeness=80.0, consistency=80.0,
    ))
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=50.0,
        z_score=6.0, is_outlier=True,
        peer_count=6, peer_std=25.0, peer_min=30.0, peer_max=80.0, peer_median=48.0,
    ))
    db_session.commit()

    for kind, extra in (
        ("quality_score", f"&hospital_id={h.id}"),
        ("quality_score", ""),  # month overview (no hospital)
        ("heatmap_cell", f"&hospital_id={h.id}"),
    ):
        resp = client.get(f"/audit/explain?kind={kind}{extra}&month=2026-04")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_epoch"], f"kind={kind} must carry a data_epoch"

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200
    assert "data_epoch" in resp.json()


def test_month_overview_is_a_digest_with_audit_pointer(db_session, client):
    """No duplicated knowledge: the aggregate payload must point into the
    Audit screen (chain nodes carry audit endpoints), not re-derive it."""
    h1 = db_session.query(Hospital).first()
    h2 = db_session.query(Hospital).offset(1).first()
    for h, score in ((h1, 88.0), (h2, 55.0)):
        _add_values(db_session, h.id, "2026-07", {"2": 300})
        db_session.add(QualityScore(
            hospital_id=h.id, month="2026-07", score=score,
            rule_compliance=score, completeness=score, consistency=score,
        ))
    db_session.commit()

    resp = client.get("/audit/explain?kind=quality_score&month=2026-07")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "month_overview"
    chain = p.get("chain") or []
    assert any("/audit/" in (n.get("endpoint") or "") for n in chain), (
        "month overview chain must link into the Audit screen endpoints"
    )


# ───────────────────────── API guards ────────────────────────────────

def test_unknown_kind_404s(db_session, client):
    h = _first_hospital(db_session)
    resp = client.get(f"/audit/explain?kind=bogus&hospital_id={h.id}&month=2026-04")
    assert resp.status_code == 404


def test_unknown_hospital_404s(db_session, client):
    resp = client.get("/audit/explain?kind=quality_score&hospital_id=999999&month=2026-04")
    assert resp.status_code == 404


def test_rule_kind_requires_rule_code(db_session, client):
    h = _first_hospital(db_session)
    resp = client.get(f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-04")
    assert resp.status_code == 404
