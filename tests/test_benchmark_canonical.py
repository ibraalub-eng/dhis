"""The Audit Benchmark consumes canonical severity where it is the same finding.

The benchmark keeps its own audited statistics (sample standard deviation, z,
percentile, status ladder) — that is its purpose. What it must not do is grade
a finding the layered engine already graded, nor present an independent
comparison as if it were canonical. These tests pin:

1. an equivalent comparison reuses the stored canonical evidence;
2. the canonical band equals what Outliers/Diagnostics display;
3. the stored band stays distinguishable from the effective one;
4. a different peer population stays independent;
5. the benchmark's methodology and thresholds are unchanged;
6. a missing layered row is explicit, never "normal";
7. an unreadable canonical plane is reported as unavailable, not as independence;
8. renaming indicators does not break the identity join;
9. a different rate/formula prevents unsafe reuse;
10. the API and UI keep their contracts and expose the provenance.
"""
import statistics

import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.layered import build_analysis_specs
from app.engine.audit.benchmark import get_benchmark
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    LayeredOutlierResult,
)

MONTH = "2028-07"
RATE_NAME = "NICU admission rate"


@pytest.fixture()
def client(app):
    return TestClient(app)


def _put(db, hospital_id, month, values):
    for code, value in values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).one()
        db.add(IndicatorValue(hospital_id=hospital_id, month=month,
                              indicator_id=indicator.id, value=value))
    db.flush()


@pytest.fixture()
def bench(db_session):
    """Target 8/100 with four peers reporting 5, 6, 6 and 9 per 100."""
    target = db_session.query(Hospital).order_by(Hospital.id).first()
    peers = [Hospital(name=f"Bench Peer {i}", is_active=True)
             for i in range(4)]
    db_session.add_all(peers)
    db_session.flush()
    for hospital, nicu in zip([target] + peers, [8, 5, 6, 6, 9]):
        _put(db_session, hospital.id, MONTH, {"16": nicu, "6": 100})
    db_session.commit()
    return {"target": target, "peers": peers}


def _spec(db):
    return next(spec for spec in build_analysis_specs(db)
                if spec.name == RATE_NAME)


def _canonical_row(db, target, peers, **overrides):
    spec = _spec(db)
    values = {str(peer.id): rate for peer, rate in
              zip(peers, [5.0, 6.0, 6.0, 9.0])}
    fields = dict(
        hospital_id=target.id, month=MONTH, analysis_code=spec.analysis_code,
        rate=8.0, outlier_level="VERY_HIGH", outlier_type="PEER_ANOMALY",
        outlier_method="peer_zscore", peer_outlier_score=0.95,
        peer_mean=6.5, peer_count=len(peers),
        peer_provenance={"group": "all_active_reporting", "values": values},
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def _comparison(result, name=RATE_NAME):
    return result["comparisons"][name]


# ── 1. Equivalent comparison reuses canonical evidence ────────────────────

def test_equivalent_comparison_reuses_canonical_evidence(db_session, bench):
    row = _canonical_row(db_session, bench["target"], bench["peers"])

    result = get_benchmark(db_session, bench["target"].id, MONTH)
    nicu = _comparison(result)
    assert nicu["evidence_status"] == "equivalent"
    assert nicu["evidence_source"] == "canonical_layered"
    assert nicu["layered_result_id"] == row.id
    assert nicu["analysis_code"] == row.analysis_code
    assert nicu["canonical_effective_level"] == "VERY_HIGH"
    assert nicu["canonical_stored_level"] == "VERY_HIGH"
    assert nicu["canonical_peer_mean"] == 6.5
    assert nicu["canonical_peer_count"] == 4
    assert nicu["canonical_score"] == pytest.approx(0.95)
    # The benchmark's own audited numbers are untouched.
    assert nicu["peer_average"] == 6.5
    assert nicu["peer_count"] == 4
    assert nicu["z_score"] == round(
        (8.0 - 6.5) / statistics.stdev([5, 6, 6, 9]), 2)
    assert result["evidence_summary"]["canonical_layered"] >= 1


# ── 2. Canonical band matches Diagnostics ─────────────────────────────────

def test_canonical_band_matches_diagnostics(client, db_session, bench):
    row = _canonical_row(db_session, bench["target"], bench["peers"])

    result = get_benchmark(db_session, bench["target"].id, MONTH)
    nicu = _comparison(result)

    diagnostics = client.get("/analysis/layered", params={"month": MONTH})
    assert diagnostics.status_code == 200, diagnostics.text
    stored = [r for r in diagnostics.json()["data"]
              if r["analysis_code"] == row.analysis_code]
    assert len(stored) == 1
    assert stored[0]["outlier_level"] == nicu["canonical_effective_level"]


# ── 3. Stored and effective bands stay distinguishable ────────────────────

@pytest.fixture()
def thin_bench(db_session):
    target = db_session.query(Hospital).order_by(Hospital.id).first()
    peers = [Hospital(name=f"Thin Peer {i}", is_active=True) for i in range(3)]
    db_session.add_all(peers)
    db_session.flush()
    for hospital, nicu in zip([target] + peers, [8, 5, 6, 7]):
        _put(db_session, hospital.id, MONTH, {"16": nicu, "6": 100})
    db_session.commit()
    return {"target": target, "peers": peers}


def test_stored_and_effective_bands_remain_distinguishable(db_session, thin_bench):
    row = _canonical_row(db_session, thin_bench["target"], thin_bench["peers"],
                         peer_outlier_score=0.97, peer_mean=6.0,
                         peer_provenance={
                             "group": "all_active_reporting",
                             "values": {str(p.id): v for p, v in
                                        zip(thin_bench["peers"], [5.0, 6.0, 7.0])}})
    nicu = _comparison(get_benchmark(db_session, thin_bench["target"].id, MONTH))
    assert nicu["evidence_status"] == "equivalent"
    assert nicu["canonical_stored_level"] == "VERY_HIGH"
    assert nicu["canonical_effective_level"] == "HIGH"
    assert nicu["canonical_capped"] is True
    assert nicu["layered_result_id"] == row.id


# ── 4. A different population stays independent ───────────────────────────

def test_different_comparison_population_stays_independent(db_session, bench):
    _canonical_row(db_session, bench["target"], bench["peers"],
                   peer_provenance={"group": "stratified:type",
                                    "values": {str(p.id): 5.0
                                               for p in bench["peers"]}})
    nicu = _comparison(get_benchmark(db_session, bench["target"].id, MONTH))
    assert nicu["evidence_status"] == "not_equivalent"
    assert nicu["evidence_source"] == "independent_audit"
    assert nicu["canonical_effective_level"] is None
    assert nicu["layered_result_id"] is None
    # The independent status is still reported as the benchmark's own verdict.
    assert nicu["status"] in {"normal", "elevated", "high", "critical"}


# ── 5. Independent methodology and thresholds unchanged ───────────────────

def test_benchmark_methodology_and_thresholds_are_unchanged(db_session, bench):
    nicu = _comparison(get_benchmark(db_session, bench["target"].id, MONTH))
    peers = [5.0, 6.0, 6.0, 9.0]
    avg = sum(peers) / len(peers)
    std = statistics.stdev(peers)
    z = round((8.0 - avg) / std, 2)

    assert nicu["peer_average"] == round(avg, 2)
    assert nicu["peer_std"] == round(std, 2)
    assert nicu["z_score"] == z
    assert nicu["percentile"] == 75.0
    assert nicu["z_provenance"]["z_produced"] is True
    expected_status = ("critical" if abs(z) >= 3 else
                       "high" if abs(z) >= 2 else
                       "elevated" if abs(z) >= 1.5 else "normal")
    assert nicu["status"] == expected_status
    assert nicu["comparison_methodology"] == \
        "benchmark_sample_stdev_ddof1_peer_zscore"
    assert nicu["evidence_status"] == "missing_layered_result"


# ── 6. Missing layered evidence is explicit ───────────────────────────────

def test_missing_layered_evidence_is_explicit(db_session, bench):
    result = get_benchmark(db_session, bench["target"].id, MONTH)
    nicu = _comparison(result)
    assert nicu["evidence_status"] == "missing_layered_result"
    assert nicu["evidence_source"] == "canonical_evidence_unavailable"
    assert nicu["canonical_effective_level"] is None
    assert result["evidence_summary"]["missing_layered_result"] >= 1


# ── 7. A read failure is not independence ─────────────────────────────────

def test_canonical_read_failure_is_distinct_from_independence(
        monkeypatch, db_session, bench):
    def _boom(*args, **kwargs):
        raise RuntimeError("canonical plane unreadable")

    monkeypatch.setattr(
        "app.engine.anomaly.projection.projection_codes", _boom)
    nicu = _comparison(get_benchmark(db_session, bench["target"].id, MONTH))
    assert nicu["evidence_status"] == "canonical_evidence_unavailable"
    assert nicu["evidence_source"] == "canonical_evidence_unavailable"
    assert nicu["evidence_status"] != "not_equivalent"


# ── 8. Renaming does not break the identity join ──────────────────────────

def test_renamed_indicator_still_matches_canonically(db_session, bench):
    row = _canonical_row(db_session, bench["target"], bench["peers"])
    definition = (db_session.query(IndicatorDefinition)
                  .filter(IndicatorDefinition.name == RATE_NAME).first())
    assert definition is not None, "the benchmark rate must come from a definition"
    definition.name = "Renamed NICU rate"
    db_session.commit()

    result = get_benchmark(db_session, bench["target"].id, MONTH)
    matches = [c for c in result["comparisons"].values()
               if c["layered_result_id"] == row.id]
    assert len(matches) == 1
    assert matches[0]["evidence_status"] == "equivalent"
    assert matches[0]["analysis_code"] == row.analysis_code


# ── 9. A different rate prevents unsafe reuse ─────────────────────────────

def test_different_rate_prevents_unsafe_reuse(db_session, bench):
    _canonical_row(db_session, bench["target"], bench["peers"], rate=7.0)
    nicu = _comparison(get_benchmark(db_session, bench["target"].id, MONTH))
    assert nicu["evidence_status"] == "not_equivalent"
    assert nicu["evidence_source"] == "independent_audit"
    assert nicu["canonical_effective_level"] is None


# ── 10. API and UI contracts ──────────────────────────────────────────────

def test_api_and_ui_contracts_are_preserved(client, db_session, bench):
    row = _canonical_row(db_session, bench["target"], bench["peers"])
    payload = client.get(f"/audit/benchmark/{bench['target'].id}",
                         params={"month": MONTH}).json()

    assert payload["hospital"] == bench["target"].name
    assert payload["month"] == MONTH
    assert "evidence_summary" in payload
    nicu = payload["comparisons"][RATE_NAME]
    for key in ("hospital_value", "peer_average", "peer_median", "peer_min",
                "peer_max", "peer_count", "peer_std", "z_score",
                "z_provenance", "percent_deviation", "percentile",
                "peers_below", "status", "confidence_interval_95",
                "formula", "formula_version", "unit", "indicator_id",
                "peer_breakdown"):
        assert key in nicu, key
    for key in ("evidence_source", "evidence_status",
                "canonical_effective_level", "canonical_stored_level",
                "layered_result_id", "analysis_code",
                "comparison_methodology", "comparison_population"):
        assert key in nicu, key
    assert nicu["layered_result_id"] == row.id
    assert nicu["comparison_population"]["target_excluded"] is True

    with open("static/js/audit.js", "r", encoding="utf-8") as handle:
        script = handle.read()
    assert "Canonical: " in script
    assert "Independent audit" in script
    assert "No canonical layered result" in script
