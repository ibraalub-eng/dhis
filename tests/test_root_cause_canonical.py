"""Root Cause consumes the canonical layered evidence (Phase 4).

Root Cause explains a finding the layered engine already detected. It must
therefore read that finding's stored evidence — the band through
``effective_severity`` and the detection-baseline peer statistics — instead of
grading the same comparison again. The pattern label is read FROM THE BAND, not
from a fixed |z| cut-off, so no second severity scale can disagree with the one
Outliers, Diagnostics and Quality Alerts count.

These tests pin:

1. the canonical peer evidence is consumed when the comparison is equivalent;
2. the effective severity matches Outliers and Diagnostics;
3. canonical statistics are not independently recomputed;
4. the old |z| thresholds cannot assign a conflicting severity;
5. independent diagnostic patterns (recurrence, descriptions) remain;
6. non-equivalent perspectives are identified;
7. missing layered evidence is explicit, never LOW;
8. different peer populations are not merged;
9. root cause stays read-only and repeatable;
10. the API keeps its existing keys and adds the provenance.
"""
import statistics

import pytest
from fastapi.testclient import TestClient

from app.engine import root_cause as rc
from app.engine.anomaly.projection import projection_codes
from app.models import (
    AnomalyResult,
    Hospital,
    HospitalType,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
)

MONTH = "2026-06"


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def peer_dataset(db_session):
    """A target hospital and four peers with shared type and reported data."""
    hospital_type = HospitalType(name="RC Type")
    db_session.add(hospital_type)
    db_session.flush()
    target = Hospital(name="RC Target", hospital_type_id=hospital_type.id,
                      is_active=True)
    peers = [Hospital(name=f"RC Peer {i}", hospital_type_id=hospital_type.id,
                      is_active=True) for i in range(4)]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_ids = {code: iid for iid, code in
                db_session.query(Indicator.id, Indicator.code).all()}
    base = {"2": 200, "6": 190, "10": 5, "17": 3, "7": 2, "6.f": 10,
            "6.g": 8, "2.n": 20, "2.c": 1, "2.d": 1}
    for hospital in [target] + peers:
        cs = 80 if hospital is target else 40 + peers.index(hospital)
        values = dict(base, **{"5": cs})
        for code, value in values.items():
            if code in code_ids:
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, indicator_id=code_ids[code],
                    month=MONTH, value=value))
    db_session.commit()
    return {"target": target, "peers": peers, "code_ids": code_ids}


def _add_layered(db, hospital_id, analysis_code, **overrides):
    fields = dict(
        hospital_id=hospital_id, analysis_code=analysis_code, month=MONTH,
        outlier_level="VERY_HIGH", outlier_type="PEER_ANOMALY",
        outlier_method="peer_zscore", peer_outlier_score=1.0,
        peer_count=4, peer_mean=40.0,
        peer_provenance={"group": "all_active_reporting",
                         "values": {str(i): 40.0 + i for i in range(4)}},
        classification_provenance={"zero_spread_layers": [],
                                   "thin_peer_layers": [],
                                   "level": "VERY_HIGH", "cap": None},
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


# ── 1 + 4. The band comes from the canonical row, not from |z| ────────────

def test_pattern_label_comes_from_the_canonical_band_not_the_z_threshold(
        db_session, peer_dataset):
    target = peer_dataset["target"]
    code = projection_codes(db_session)["rate_cs"]
    db_session.add(AnomalyResult(
        hospital_id=target.id, month=MONTH, indicator_code=code,
        rate_name="C-section rate", value=80.0, benchmark=40.0,
        z_score=3.5, is_outlier=True))
    db_session.commit()
    row = _add_layered(db_session, target.id, "rate_cs",
                       outlier_level="HIGH", peer_outlier_score=0.80)

    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    # |z| = 3.5 used to be labelled "severe" by a hardcoded threshold; the
    # canonical band (HIGH) decides now.
    assert pattern.pattern_type == "moderate"
    assert pattern.effective_level == "HIGH"
    assert pattern.stored_level == "HIGH"
    assert pattern.evidence_source == "canonical_layered"
    assert pattern.evidence_status == "equivalent"
    assert pattern.layered_result_id == row.id
    assert pattern.analysis_code == "rate_cs"
    assert pattern.score == pytest.approx(0.80)
    assert "|z|=3.5" in pattern.description


# ── 7. Missing canonical evidence is explicit, never LOW ──────────────────

def test_missing_canonical_evidence_is_explicit_not_low(db_session, peer_dataset):
    target = peer_dataset["target"]
    code = projection_codes(db_session)["rate_cs"]
    db_session.add(AnomalyResult(
        hospital_id=target.id, month=MONTH, indicator_code=code,
        rate_name="C-section rate", value=80.0, benchmark=40.0,
        z_score=3.5, is_outlier=True))
    db_session.commit()

    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    assert pattern.pattern_type == "unclassified"
    assert pattern.effective_level is None
    assert pattern.stored_level is None
    assert pattern.evidence_source == "independent_diagnostic"
    assert pattern.evidence_status == "missing_layered_result"
    assert "canonical layered evidence is missing" in pattern.description


# ── 2. Same effective severity as Outliers and Diagnostics ────────────────

def test_effective_severity_matches_diagnostics_and_outliers(
        client, db_session, peer_dataset):
    target = peer_dataset["target"]
    code = projection_codes(db_session)["rate_cs"]
    db_session.add(AnomalyResult(
        hospital_id=target.id, month=MONTH, indicator_code=code,
        rate_name="C-section rate", value=80.0, benchmark=40.0,
        z_score=3.5, is_outlier=True))
    db_session.commit()
    # A peer group too small to measure a spread: the policy caps it at HIGH.
    row = _add_layered(db_session, target.id, "rate_cs", peer_count=3,
                       peer_mean=41.0,
                       peer_provenance={"group": "all_active_reporting",
                                        "values": {"1": 40.0, "2": 41.0,
                                                   "3": 42.0}})

    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    diagnostics = client.get("/analysis/layered", params={"month": MONTH})
    assert diagnostics.status_code == 200, diagnostics.text
    diag_rows = [r for r in diagnostics.json()["data"]
                 if r["analysis_code"] == "rate_cs"]
    assert len(diag_rows) == 1, diag_rows

    outliers = client.get("/analysis/outliers",
                          params={"month": MONTH, "limit": 100})
    assert outliers.status_code == 200, outliers.text
    outlier_rows = [r for r in outliers.json()["data"]
                    if r.get("layered_level")]
    assert len(outlier_rows) == 1, outlier_rows

    assert (pattern.effective_level
            == diag_rows[0]["outlier_level"]
            == outlier_rows[0]["layered_level"]
            == "HIGH")
    assert pattern.stored_level == row.outlier_level == "VERY_HIGH"


# ── 3. Canonical statistics are not recomputed ────────────────────────────

def test_peer_comparison_consumes_stored_canonical_evidence(
        db_session, peer_dataset):
    target = peer_dataset["target"]
    feature_codes = rc._feature_analysis_codes(db_session)
    analysis_code = feature_codes["cs_rate"]
    peer_ids, _ = rc._find_peer_hospital_ids(
        db_session, target.id, peer_mode="all", month=MONTH)
    # The stored mean is deliberately impossible to derive from this month's
    # values: only consuming the stored evidence can produce it.
    row = _add_layered(
        db_session, target.id, analysis_code,
        peer_mean=999.0, peer_count=len(peer_ids), peer_outlier_score=0.93,
        peer_provenance={"group": "all_active_reporting",
                         "values": {str(hid): 40.0 for hid in peer_ids}})

    report = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="all")
    comp = report.peer_comparisons["cs_rate"]
    assert comp.peer_mean == pytest.approx(999.0)
    assert comp.evidence_source == "canonical_layered"
    assert comp.evidence_status == "equivalent"
    assert comp.layered_result_id == row.id
    assert comp.analysis_code == analysis_code
    assert comp.score == pytest.approx(0.93)
    assert comp.effective_level == "HIGH"      # a flat peer group is capped
    assert comp.peer_count == len(peer_ids)


# ── 6 + 8. A different population is labelled and never merged ────────────

def test_stratified_peer_comparison_is_labelled_independent(
        db_session, peer_dataset):
    target = peer_dataset["target"]
    analysis_code = rc._feature_analysis_codes(db_session)["cs_rate"]
    peer_ids, group = rc._find_peer_hospital_ids(
        db_session, target.id, peer_mode="type", month=MONTH)
    _add_layered(
        db_session, target.id, analysis_code, peer_mean=999.0,
        peer_count=len(peer_ids), peer_outlier_score=0.93,
        peer_provenance={"group": "all_active_reporting",
                         "values": {str(hid): 40.0 for hid in peer_ids}})

    report = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="type")
    comp = report.peer_comparisons["cs_rate"]
    assert comp.peer_group == group == "type"
    assert comp.evidence_source == "independent_diagnostic"
    assert comp.evidence_status == "not_equivalent"
    # The stratified population keeps its own mean; the canonical one is not
    # merged into it.
    assert comp.peer_mean != pytest.approx(999.0)
    # Peers report 40..43 of 200 births, i.e. 20.0-21.5%: the stratified group
    # keeps its own mean instead of adopting the canonical one.
    assert comp.peer_mean == pytest.approx(20.75)
    assert comp.layered_result_id is None


# ── 5. Independent pattern descriptions survive ───────────────────────────

def test_independent_diagnostic_patterns_remain(db_session, peer_dataset):
    target = peer_dataset["target"]
    code = projection_codes(db_session)["rate_cs"]
    for month in ("2026-04", "2026-05", MONTH):
        db_session.add(AnomalyResult(
            hospital_id=target.id, month=month, indicator_code=code,
            rate_name="C-section rate", value=80.0, benchmark=40.0,
            z_score=3.5, is_outlier=True))
    # Recurrence is measured over the months the hospital reported data for.
    for month in ("2026-04", "2026-05"):
        db_session.add(IndicatorValue(
            hospital_id=target.id,
            indicator_id=peer_dataset["code_ids"]["2"],
            month=month, value=200))
    db_session.commit()
    _add_layered(db_session, target.id, "rate_cs", outlier_level="VERY_HIGH",
                 peer_outlier_score=1.0, peer_mean=40.0)

    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    assert pattern.recurrence_count == 2
    assert "recurring anomaly" in pattern.description
    assert pattern.hospital_count == 1
    assert pattern.avg_z_score == pytest.approx(3.5)


# ── 9. Read-only and repeatable ───────────────────────────────────────────

def test_root_cause_is_read_only_and_repeatable(db_session, peer_dataset):
    target = peer_dataset["target"]
    analysis_code = rc._feature_analysis_codes(db_session)["cs_rate"]
    _add_layered(db_session, target.id, analysis_code)
    before = (db_session.query(LayeredOutlierResult).count(),
              db_session.query(AnomalyResult).count())

    first = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="all")
    second = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="all")

    after = (db_session.query(LayeredOutlierResult).count(),
             db_session.query(AnomalyResult).count())
    assert before == after
    assert [p.pattern_type for p in first.anomaly_patterns] == \
        [p.pattern_type for p in second.anomaly_patterns]
    assert ({k: v.evidence_source for k, v in first.peer_comparisons.items()}
            == {k: v.evidence_source for k, v in second.peer_comparisons.items()})


# ── 10. API contract ──────────────────────────────────────────────────────

def test_api_payload_keeps_contract_and_exposes_provenance(
        client, db_session, peer_dataset):
    target = peer_dataset["target"]
    analysis_code = rc._feature_analysis_codes(db_session)["cs_rate"]
    _add_layered(db_session, target.id, analysis_code)
    code = projection_codes(db_session)["rate_cs"]
    db_session.add(AnomalyResult(
        hospital_id=target.id, month=MONTH, indicator_code=code,
        rate_name="C-section rate", value=80.0, benchmark=40.0,
        z_score=3.5, is_outlier=True))
    db_session.commit()

    response = client.get(f"/root-cause/{target.id}",
                          params={"month": MONTH, "compare_peers": "true"})
    assert response.status_code == 200, response.text
    body = response.json()

    pattern = body["anomaly_patterns"][0]
    for key in ("rate_name", "avg_z_score", "recurrence_count",
                "pattern_type", "description"):
        assert key in pattern
    assert pattern["evidence_source"] == "canonical_layered"
    assert pattern["evidence_status"] == "equivalent"
    assert pattern["effective_level"].upper() in {"LOW", "MODERATE", "HIGH",
                                                  "VERY_HIGH"}

    comp = body["peer_comparisons"]["cs_rate"]
    for key in ("indicator_code", "indicator_name", "hospital_value",
                "peer_group", "peer_count", "peer_mean", "peer_std",
                "hospital_percentile", "hospital_z_score", "gap_pct",
                "z_provenance", "peer_governorates"):
        assert key in comp, key
    assert comp["evidence_source"] in {"canonical_layered",
                                       "independent_diagnostic"}
    assert comp["evidence_status"] in {"equivalent", "missing_layered_result",
                                       "not_equivalent"}


# ── Phase 8: a read failure is not missing evidence and not independence ──

def _seed_pattern(db_session, peer_dataset):
    target = peer_dataset["target"]
    code = projection_codes(db_session)["rate_cs"]
    db_session.add(AnomalyResult(
        hospital_id=target.id, month=MONTH, indicator_code=code,
        rate_name="C-section rate", value=80.0, benchmark=40.0,
        z_score=3.5, is_outlier=True))
    db_session.commit()
    return target


def test_canonical_read_failure_is_reported_as_unavailable(
        monkeypatch, db_session, peer_dataset):
    target = _seed_pattern(db_session, peer_dataset)

    def _boom(*args, **kwargs):
        raise RuntimeError("canonical plane unreadable")

    monkeypatch.setattr(rc, "_canonical_rows", _boom)

    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    assert pattern.evidence_status == "canonical_evidence_unavailable"
    assert pattern.evidence_source == "canonical_evidence_unavailable"
    assert pattern.evidence_source != "independent_diagnostic"
    assert pattern.effective_level is None
    assert pattern.pattern_type == "unclassified"
    assert "unavailable" in pattern.description

    report = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="all")
    comp = report.peer_comparisons["cs_rate"]
    assert comp.evidence_status == "canonical_evidence_unavailable"
    assert comp.evidence_source == "canonical_evidence_unavailable"
    assert comp.effective_level is None
    assert comp.layered_result_id is None


def test_missing_row_stays_distinct_from_a_read_failure(
        db_session, peer_dataset):
    target = _seed_pattern(db_session, peer_dataset)
    pattern = rc.analyze_anomaly_patterns(db_session, target.id, MONTH)[0]
    assert pattern.evidence_status == "missing_layered_result"
    assert pattern.evidence_source == "independent_diagnostic"

    report = rc.generate_root_cause_analysis(
        db_session, target.id, MONTH,
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        compare_peers=True, peer_mode="all")
    comp = report.peer_comparisons["cs_rate"]
    assert comp.evidence_status == "missing_layered_result"
    assert comp.evidence_status != "canonical_evidence_unavailable"
