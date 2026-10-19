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
    Rule,
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


# ─────────────── failed validation rules in the Why popup ───────────────

def _add_rule(db, code, name, severity="HIGH", expression_type="parent_le"):
    from app.models import Rule

    db.add(Rule(
        code=code, name=name, rule_type="LOGIC", severity=severity,
        category="MATERNAL", expression_type=expression_type, params="{}",
    ))
    db.commit()


def test_quality_score_explanation_names_failed_rules(db_session, client):
    """Rule compliance can sit ABOVE its target while rules still fail.

    The Why popup must name them — otherwise "all components meet their
    targets" reads as "nothing failed" while the hospital has open alerts.
    """
    from app.models import Rule  # noqa: F401  (ensures the table exists)

    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-08", {"2": 300})
    _add_rule(db_session, "R_TEST", "Severe maternal morbidity must not exceed its children")
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-08", score=99.2,
        rule_compliance=98.7, completeness=100.0, consistency=100.0, outlier_penalty=0.0,
    ))
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-08", rule_code="R_TEST",
        rule_description="Severe maternal morbidity must not exceed its children",
        status="FAIL", severity="HIGH", rule_type="LOGIC",
        details="SMM=14.0 but children sum=9.0",
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-08&component=rule_compliance"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()

    assert p["failed_rule_count"] == 1
    fr = p["failed_rules"][0]
    assert fr["rule_code"] == "R_TEST"
    # The live Rule name wins over the denormalized description.
    assert fr["rule_name"] == "Severe maternal morbidity must not exceed its children"
    assert fr["details"] == "SMM=14.0 but children sum=9.0"
    assert fr["severity"] == "HIGH"

    # The Why sentence must not claim good data quality while a rule fails.
    assert "R_TEST" in p["why"]
    assert "good data quality" not in p["why"]
    validation_step = next(c for c in p["chain"] if c["step"] == "Validation")
    assert "R_TEST" in validation_step["detail"]


def test_failed_rules_are_sorted_worst_severity_first(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-09", {"2": 300})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-09", score=70.0,
        rule_compliance=60.0, completeness=80.0, consistency=80.0, outlier_penalty=0.0,
    ))
    for code, sev in (("R_LOW", "LOW"), ("R_CRIT", "CRITICAL"), ("R_HIGH", "HIGH")):
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-09", rule_code=code,
            rule_description=f"{code} description", status="FAIL",
            severity=sev, rule_type="LOGIC", details=f"{code} details",
        ))
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-09", rule_code="R_OK",
        rule_description="passed rule", status="PASS", severity="LOW", rule_type="LOGIC",
    ))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-09")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    # PASS rows never appear.
    assert [f["rule_code"] for f in p["failed_rules"]] == ["R_CRIT", "R_HIGH", "R_LOW"]
    # A component below target keeps its own sentence AND gains the rule sentence.
    assert "below target" in p["why"]
    assert "3 validation rule(s) failed" in p["why"]


def test_month_without_failed_rules_says_so_plainly(db_session, client):
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-10", {"2": 300})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-10", score=90.0,
        rule_compliance=90.0, completeness=95.0, consistency=95.0, outlier_penalty=0.0,
    ))
    db_session.commit()

    resp = client.get(f"/audit/explain?kind=quality_score&hospital_id={h.id}&month=2026-10")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["failed_rules"] == []
    assert p["failed_rule_count"] == 0
    assert p["why"].endswith("All components meet their targets — the score reflects good data quality")


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
    import statistics

    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})

    # The anomaly engine reproduces z from the UNROUNDED peer rates in
    # peers_detail (ddof=1, the pipeline's convention), not from the rounded
    # benchmark/std columns — so the fixture must be self-consistent: the
    # stored z, benchmark and peer_std are all derived from the same peer list.
    # (Peers 40..45 next to peer_std=25 claimed z=6.0 while the peer list
    # implies 84.19; the engine was right and the fixture contradicted itself.)
    peers = [40.0, 52.0, 61.0, 70.0, 84.0, 97.0]
    peer_mean = statistics.fmean(peers)
    peer_std = statistics.stdev(peers)  # ddof=1
    stored_z = round((200.0 - peer_mean) / peer_std, 2)
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=round(peer_mean, 2),
        z_score=stored_z, is_outlier=True,
        peer_count=len(peers), peer_std=round(peer_std, 2),
        peer_min=min(peers), peer_max=max(peers),
        peer_median=round(statistics.median(peers), 2),
        peers_detail=[{"hospital": f"P{i}", "rate": r} for i, r in enumerate(peers)],
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()

    assert p["what"].startswith("C-section rate")
    assert f"|z| = {stored_z:.2f}" in p["why"]
    assert p["reproduce"]["expected_z"] == stored_z
    assert p["reproduce"]["stored_z"] == stored_z
    assert p["reproduce"]["verified"] is True
    # Raw values are clean → this is a statistical/clinical finding, not bad data.
    assert p["classification"] in ("statistical_finding", "clinical_finding")
    # Peer inputs surface in the how table.
    inputs_text = json.dumps(p["how"]["inputs"])
    assert "Peer count" in inputs_text and str(len(peers)) in inputs_text
    # Chain links the outlier back to the data auditor / benchmark endpoints.
    assert any("data-auditor" in (c.get("endpoint") or "") for c in p["chain"])


def test_stale_anomaly_benchmark_is_not_reported_as_reproduced(db_session, client):
    """The digest must check the benchmark against the DATA, not just against
    itself.

    Recomputing z from the row's own `peers_detail` proves nothing about which
    hospitals were compared: a benchmark over the wrong population — or one
    stored before a peer's indicator was disabled — reproduces perfectly from
    its own list and would be signed off as "verified" while disagreeing with
    the engine by any margin. Here the row claims z=6.0 over six invented
    peers while the uploaded data gives z≈0.4, so the digest must refuse to
    verify it, say why, and stop calling it a clinical finding.
    """
    import statistics

    h = _first_hospital(db_session)
    # two real peers with real C-section rates, plus this hospital at 200%
    peers = db_session.query(Hospital).offset(1).all()[:2]
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})
    for i, p in enumerate(peers):
        _add_values(db_session, p.id, "2026-04", {"5": 50 + i, "2": 100})

    invented = [40.0, 52.0, 61.0, 70.0, 84.0, 97.0]
    peer_std = statistics.stdev(invented)
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0,
        benchmark=round(statistics.fmean(invented), 2),
        z_score=round((200.0 - statistics.fmean(invented)) / peer_std, 2),
        is_outlier=True, peer_count=len(invented), peer_std=round(peer_std, 2),
        peer_min=min(invented), peer_max=max(invented),
        peer_median=round(statistics.median(invented), 2),
        peers_detail=[{"hospital": f"P{i}", "rate": r} for i, r in enumerate(invented)],
    ))
    db_session.commit()

    p = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    ).json()

    check = p["peer_check"]
    assert check is not None, "the benchmark must be recomputed from the data"
    assert check["peer_count"] == 2, check
    assert check["stored_peer_count"] == len(invented)
    assert check["peer_set_matches"] is False
    assert check["peers_missing_from_row"], check
    assert check["verified"] is False
    # the stored columns still agree with each other …
    assert p["reproduce"]["expected_z"] == p["reproduce"]["stored_z"]
    # … but the digest must not sign that off against the real data
    assert p["reproduce"]["verified"] is False
    assert "Benchmark" in (p["reproduce"]["note"] or "")
    stale = [d for d in p["data_problems"] if d["kind"] == "stale_benchmark"]
    assert stale, p["data_problems"]
    assert stale[0]["severity"] == "high"
    assert p["classification"] == "data_problem", (
        "an out-of-date benchmark is a data problem, not a clinical finding")


def test_fresh_anomaly_benchmark_verifies_against_the_data(db_session, client):
    """The positive case: when the row was written from the population the
    engine itself uses, the recomputation confirms it exactly."""
    import statistics

    h = _first_hospital(db_session)
    # the engine only benchmarks against ACTIVE hospitals
    peers = (db_session.query(Hospital).filter(Hospital.is_active.is_(True))
             .filter(Hospital.id != h.id).limit(2).all())
    if len(peers) < 2:
        pytest.skip("needs two active peer hospitals")
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})
    for i, p in enumerate(peers):
        _add_values(db_session, p.id, "2026-04", {"5": 40 + 20 * i, "2": 100})

    rates = [40.0, 60.0]
    peer_std = statistics.stdev(rates)
    peer_mean = statistics.fmean(rates)
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=round(peer_mean, 2),
        z_score=round((200.0 - peer_mean) / peer_std, 2), is_outlier=True,
        peer_count=len(rates), peer_std=round(peer_std, 2),
        peer_min=min(rates), peer_max=max(rates),
        peer_median=round(statistics.median(rates), 2),
        peers_detail=[{"hospital": p.name, "rate": round(r, 4)} for p, r in zip(peers, rates)],
    ))
    db_session.commit()

    p = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    ).json()
    check = p["peer_check"]
    assert check["peer_set_matches"] is True, check
    assert check["peer_count"] == check["stored_peer_count"] == 2
    assert check["expected_z"] == p["reproduce"]["stored_z"]
    assert check["verified"] is True
    assert p["reproduce"]["benchmark_verified"] is True
    assert p["reproduce"]["verified"] is True
    assert not [d for d in p["data_problems"] if d["kind"] == "stale_benchmark"]


def test_anomaly_with_a_stale_own_value_is_not_verified(db_session, client):
    """The peer list can be perfectly right while the row is still out of date.

    If the hospital's own numerator is corrected after the anomaly ran, the
    stored z no longer matches the uploaded rate even though the benchmark
    population is unchanged — the case where checking only the peer set would
    wave the row through. The digest must compare the recomputed z as well.
    """
    import statistics

    h = _first_hospital(db_session)
    peers = (db_session.query(Hospital).filter(Hospital.is_active.is_(True))
             .filter(Hospital.id != h.id).limit(2).all())
    if len(peers) < 2:
        pytest.skip("needs two active peer hospitals")
    for i, p in enumerate(peers):
        _add_values(db_session, p.id, "2026-04", {"5": 40 + 20 * i, "2": 100})

    rates = [40.0, 60.0]
    peer_mean = statistics.fmean(rates)
    peer_std = statistics.stdev(rates)
    # The row was written when this hospital reported 200% …
    _add_values(db_session, h.id, "2026-04", {"5": 200, "2": 100})
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2026-04", indicator_code="5",
        rate_name="C-section rate", value=200.0, benchmark=round(peer_mean, 2),
        z_score=round((200.0 - peer_mean) / peer_std, 2), is_outlier=True,
        peer_count=len(rates), peer_std=round(peer_std, 2),
        peer_min=min(rates), peer_max=max(rates),
        peer_median=round(statistics.median(rates), 2),
        peers_detail=[{"hospital": p.name, "rate": r} for p, r in zip(peers, rates)],
    ))
    db_session.commit()
    # … and a later upload corrects it to 100%. The schema forbids inserting a
    # second row for the same (hospital, indicator, month), so simulate the
    # correction as the import really does: an UPDATE of the existing row.
    ind5 = _indicator_by_code(db_session, "5")
    owned_row = db_session.query(IndicatorValue).filter_by(
        hospital_id=h.id, indicator_id=ind5.id, month="2026-04").one()
    owned_row.value = 100.0
    db_session.commit()

    p = client.get(
        f"/audit/explain?kind=anomaly&hospital_id={h.id}&month=2026-04&rate_name=C-section%20rate"
    ).json()
    check = p["peer_check"]
    assert check["peer_set_matches"] is True, "the peer population is unchanged"
    assert check["peer_count"] == 2
    assert check["expected_z"] != p["reproduce"]["stored_z"], check
    assert check["verified"] is False
    assert p["reproduce"]["verified"] is False
    assert [d for d in p["data_problems"] if d["kind"] == "stale_benchmark"]


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
    """Two layers protect against double-counted raw rows.

    The renamed schema now enforces (hospital, indicator, month) uniqueness
    with a DB constraint — a true duplicate can never be INSERTed, so the
    persistence layer rejects it outright. The audit's duplicate check remains
    as defense-in-depth for databases stamped before that constraint, and is
    pinned here directly on the detector (feeding the function the raw-row
    list that used to be reachable through a pre-uniqueness DB)."""
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"5": 80, "2": 100}, source_file="a.xlsx")

    # Layer 1: the DB itself refuses a second row for the same key.
    from sqlalchemy.exc import IntegrityError as _IE
    ind = _indicator_by_code(db_session, "5")
    db_session.add(IndicatorValue(
        hospital_id=h.id, indicator_id=ind.id, month="2026-04", value=80,
        source_file="a.xlsx"))
    with pytest.raises(_IE):
        db_session.commit()
    db_session.rollback()  # expected flush failure — reset for the assertions below

    # Layer 2: if such a row pair somehow existed, the auditor still flags it.
    from app.engine.audit.explain import find_data_problems, _raw_values
    values = _raw_values(db_session, h.id, "2026-04")
    values.append(dict(values[0]))  # simulate the legacy duplicate pair
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


def test_passing_rule_is_not_labelled_a_finding(db_session, client):
    """A rule that PASSED is not a finding: it must carry no classification
    badge, and it must not be buried under the month's unrelated data gaps
    (the badge used to say 'Data problem' on any rule whenever the month had
    any missing indicator)."""
    h = _first_hospital(db_session)
    _add_values(db_session, h.id, "2026-04", {"2": 300})
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-04", rule_code="R_PASS",
        rule_description="Total deliveries consistency",
        status="PASS", severity="MEDIUM", rule_type="LOGIC",
        details="Total Deliveries=300.0 == children sum=300.0",
    ))
    db_session.commit()

    p = client.get(
        f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-04&rule_code=R_PASS"
    ).json()
    assert p["classification"] is None
    assert p["data_problems"] == []


def test_failing_rule_is_only_a_data_problem_when_its_own_input_is_missing(db_session, client):
    """The classification must describe THIS rule's failure.

    - a failure whose own input is an empty (NULL) uploaded cell is a data
      problem, and the digest must name the missing indicator;
    - the same failure with every input present is a real finding;
    - an unrelated empty cell elsewhere in the month must NOT relabel it (the
      badge used to read 'Data problem' whenever the month had any gap).
    """
    h = _first_hospital(db_session)
    db_session.add(Rule(
        code="R_PARENT_CHILD", name="Deliveries >= births",
        rule_type="LOGIC", severity="HIGH", category="BASIC_LOGIC",
        expression_type="ge",
        params=json.dumps({"parent": "2", "children": ["5"]}),
        description="Total Deliveries must be >= Caesarean Sections",
    ))
    db_session.flush()
    for month in ("2026-01", "2026-02", "2026-03"):
        db_session.add(ValidationResult(
            hospital_id=h.id, month=month, rule_code="R_PARENT_CHILD",
            rule_description="Deliveries >= births", status="FAIL",
            severity="HIGH", rule_type="LOGIC",
            details="Total Deliveries=100.0 < children sum=120.0",
        ))
    db_session.commit()

    # its own child cell is empty and no total covers it → data problem
    _add_values(db_session, h.id, "2026-01", {"5": None})
    # every input present, but an unrelated indicator is empty → still a finding
    _add_values(db_session, h.id, "2026-02", {"2": 100, "5": 120, "6": None})
    # every input present, nothing empty → a finding
    _add_values(db_session, h.id, "2026-03", {"2": 100, "5": 120, "6": 40})

    a = client.get(
        f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-01&rule_code=R_PARENT_CHILD"
    ).json()
    assert a["classification"] == "data_problem", a["classification"]
    assert [d.get("indicator_code") for d in a["data_problems"]] == ["5"]

    b = client.get(
        f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-02&rule_code=R_PARENT_CHILD"
    ).json()
    assert b["classification"] == "clinical_finding", b["classification"]
    assert b["data_problems"] == [], "an unrelated empty cell must not be listed"

    c = client.get(
        f"/audit/explain?kind=rule&hospital_id={h.id}&month=2026-03&rule_code=R_PARENT_CHILD"
    ).json()
    assert c["classification"] == "clinical_finding", c["classification"]
    assert c["data_problems"] == []


def test_benchmark_validation_failure_cannot_be_explained(db_session, client):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()
    assert len(hospitals) >= 3
    per_hospital = {
        hospitals[0].id: {"10": 11, "2": 40},   # 27.5%
        hospitals[1].id: {"10": 4, "2": 60},    # 6.67%
        hospitals[2].id: {"10": 5, "2": 55},    # 9.09%
    }
    for hid, vals in per_hospital.items():
        _add_values(db_session, hid, "2026-08", vals)
    db_session.add(ValidationResult(
        hospital_id=hospitals[0].id, month="2026-08", rule_code="R049",
        rule_description="SMM Rate outlier across hospitals",
        status="FAIL", severity="HIGH", rule_type="BENCHMARK",
        details="Rate=27.5%, mean=14.4%, z=1.41 (outlier)",
    ))
    db_session.commit()

    resp = client.get(
        f"/audit/explain?kind=rule&hospital_id={hospitals[0].id}&month=2026-08&rule_code=R049"
    )
    assert resp.status_code == 404, resp.text
    assert "No validation result" in resp.json()["detail"]


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


def test_month_overview_names_the_months_failing_rules(db_session, client):
    """The aggregate digest must not read "range 84-100, weakest: X" while 8
    rules failed network-wide: each failing row carries its own hospital so the
    chip drills into that hospital's rule."""
    h1 = db_session.query(Hospital).first()
    h2 = db_session.query(Hospital).offset(1).first()
    for h, score in ((h1, 91.0), (h2, 84.0)):
        _add_values(db_session, h.id, "2026-09", {"2": 300})
        db_session.add(QualityScore(
            hospital_id=h.id, month="2026-09", score=score,
            rule_compliance=score, completeness=score, consistency=score,
        ))
    db_session.add(ValidationResult(
        hospital_id=h1.id, month="2026-09", rule_code="R061",
        rule_description="Severe maternal morbidity", status="FAIL",
        severity="HIGH", rule_type="LOGIC", details="parent 14.0 vs children 9.0",
    ))
    db_session.commit()

    resp = client.get("/audit/explain?kind=quality_score&month=2026-09")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["failed_rule_count"] == 1
    row = p["failed_rules"][0]
    assert row["rule_code"] == "R061"
    assert row["hospital_id"] == h1.id
    assert row["hospital"]
    # The narrative line names the failure, not just the score range.
    assert "R061" in p["why"]
    assert "validation rule failure" in p["why"]


def test_month_overview_failed_rules_stay_capped(db_session, client):
    """Dozens of network-wide failures must not ship an unbounded chip list;
    the count stays exact so the overflow line is honest."""
    h = db_session.query(Hospital).first()
    _add_values(db_session, h.id, "2026-10", {"2": 300})
    db_session.add(QualityScore(
        hospital_id=h.id, month="2026-10", score=90.0,
        rule_compliance=90.0, completeness=90.0, consistency=90.0,
    ))
    for i in range(30):
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-10", rule_code=f"R{i:03d}",
            rule_description=f"Rule {i}", status="FAIL", severity="LOW",
            rule_type="LOGIC", details="x",
        ))
    db_session.commit()

    p = client.get("/audit/explain?kind=quality_score&month=2026-10").json()
    assert p["failed_rule_count"] == 30
    assert len(p["failed_rules"]) == 25


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
