"""One detection truth: layered results are computed once, everything else reads
them.

Regression guard for the duplication this module's change removed: the pipeline
used to run two independent detectors (`detect_anomalies` for derived rates and
`run_layered_analysis` for rates + data elements). They used different peer
groups, so the same hospital/month was an outlier on one screen and normal on
another. Now:

* the layered engine is the only place a statistic is computed (one peer group:
  every hospital reporting the indicator that month);
* ``anomaly_results`` rows are a PROJECTION of the layered rows;
* the Quality report card counts the layered rows at the engine's own detection
  floor.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine.anomaly.layered import (
    AnalysisSpec,
    Thresholds,
    build_analysis_specs,
    is_detection_outlier,
    run_layered_analysis,
    should_persist,
)
from app.engine.pipeline import run_full_analysis
from app.main import app
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)

MONTH = "2026-04"


# ── detection floor ────────────────────────────────────────────────────────

def test_detection_floor_matches_the_z_threshold():
    # |z| == threshold maps to score 0.5 -> MODERATE; anything milder is a
    # deviation worth showing, not a detection.
    assert is_detection_outlier("VERY_HIGH")
    assert is_detection_outlier("HIGH")
    assert is_detection_outlier("MODERATE")
    assert not is_detection_outlier("LOW")
    assert not is_detection_outlier("NONE")
    assert not is_detection_outlier(None)


# ── one peer group ─────────────────────────────────────────────────────────

def test_peer_group_is_every_hospital_reporting_the_indicator():
    """Different facility type / ownership / governorate must not exclude a
    hospital from the baseline: the same month has one answer everywhere."""
    spec = AnalysisSpec(analysis_code="5", name="C-sections", indicator_type="count")
    history = {"2026-01": {"5": 10}, "2026-02": {"5": 10},
               "2026-03": {"5": 10}, MONTH: {"5": 10}}
    peers = {
        1: history,
        2: {MONTH: {"5": 20}},
        3: {MONTH: {"5": 30}},
    }
    attributes = {
        1: {"type": 1, "ownership": 7, "governorate": 100},
        2: {"type": 2, "ownership": 8, "governorate": 101},
        3: {"type": 3, "ownership": 9, "governorate": 102},
    }
    results = run_layered_analysis([spec], history, MONTH, 1, peers,
                                   attributes, Thresholds())
    peer = results[0].peer
    assert peer.peer_count == 2
    assert peer.peer_values == {2: 20.0, 3: 30.0}
    assert peer.peer_mean == pytest.approx(25.0)
    assert peer.peer_min == pytest.approx(20.0)
    assert peer.peer_max == pytest.approx(30.0)
    assert peer.peer_median == pytest.approx(25.0)


# ── projection ─────────────────────────────────────────────────────────────

def _seed_values(db, hospital, values):
    for code, value in values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(hospital_id=hospital.id, month=MONTH,
                                  indicator_id=indicator.id, value=value))
    db.commit()


def test_anomaly_rows_are_a_projection_of_layered_rows(db_session, sample_values):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(3).all()
    assert len(hospitals) == 3, "peer comparison needs more than one hospital"
    for hospital in hospitals:
        _seed_values(db_session, hospital, sample_values)

    run_full_analysis(db_session, hospitals[0].id, MONTH, force=True)

    layered = (db_session.query(LayeredOutlierResult)
               .filter(LayeredOutlierResult.hospital_id == hospitals[0].id,
                       LayeredOutlierResult.month == MONTH)
               .all())
    projected = (db_session.query(AnomalyResult)
                 .filter(AnomalyResult.hospital_id == hospitals[0].id,
                         AnomalyResult.month == MONTH)
                 .all())

    rate_rows = [r for r in layered
                 if r.indicator_id is None and r.rate is not None]
    assert rate_rows, "the seeded values must produce rate rows"
    spec_names = {s.analysis_code: s.name for s in build_analysis_specs(db_session)}

    # Same numbers, same verdict — read from two tables. Matched per value
    # because one display name can cover two formulas (stillbirths per
    # delivery and per live birth are both "Stillbirth rate").
    for row in rate_rows:
        name = spec_names[row.analysis_code]
        match = [p for p in projected
                 if p.rate_name == name
                 and p.value == pytest.approx(row.rate, abs=0.01)]
        assert match, (name, row.rate, [(p.rate_name, p.value) for p in projected])
        projected_row = match[0]
        if row.peer_mean is not None:
            assert projected_row.benchmark == pytest.approx(row.peer_mean, abs=0.01)
        assert projected_row.is_outlier == is_detection_outlier(row.outlier_level)

    # Provenance survives the projection: the registry definition supplies the
    # id the Quality report's stale-formula check reads.
    assert any(row.indicator_id for row in projected)


def test_report_card_counts_only_detection_level_layered_rows(client_db):
    client, db, hospital = client_db
    listed = client.get("/reports/", params={"hospital_id": hospital.id})
    assert listed.status_code == 200

    outliers = listed.json()[0]["outliers"]
    kinds = sorted(o["kind"] for o in outliers)
    assert kinds == ["element", "rate"]          # LOW and NONE stay out
    assert {o["level"] for o in outliers} == {"HIGH", "MODERATE"}
    element_outlier = next(o for o in outliers if o["kind"] == "element")
    assert element_outlier["value"] == pytest.approx(90.0)


@pytest.fixture
def client_db(db_session):
    """A hospital with one QualityScore and four layered rows: two above the
    detection floor, one below it, one NONE."""
    hospital = Hospital(name="Single Truth Hospital")
    db_session.add(hospital)
    db_session.flush()
    db_session.add(QualityScore(hospital_id=hospital.id, month=MONTH,
                                score=80.0, rule_compliance=90.0,
                                completeness=90.0, consistency=90.0,
                                outlier_penalty=5.0))

    element = db_session.query(Indicator).filter(Indicator.code == "5").first()
    assert element is not None
    assert element.name
    rows = [
        dict(analysis_code="rate_cs", indicator_id=None, rate=26.0,
             peer_mean=7.5, peer_count=4, outlier_level="HIGH",
             outlier_type="PEER_ANOMALY", kind="rate"),
        dict(analysis_code=element.code, indicator_id=element.id, raw_value=90,
             peer_mean=40.0, peer_count=4, outlier_level="MODERATE",
             outlier_type="PEER_ANOMALY", kind="element"),
        dict(analysis_code="rate_nmr", indicator_id=None, rate=12.0,
             peer_mean=9.0, peer_count=4, outlier_level="LOW",
             outlier_type="RATE_ANOMALY", kind="rate"),
        dict(analysis_code="11", indicator_id=None, rate=120.0,
             peer_mean=118.0, peer_count=4, outlier_level="NONE",
             outlier_type="NORMAL", kind="rate"),
    ]
    for row in rows:
        row.pop("kind")
        db_session.add(LayeredOutlierResult(hospital_id=hospital.id,
                                            month=MONTH, **row))
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), db_session, hospital
    finally:
        app.dependency_overrides.clear()


def test_rate_without_denominator_is_not_an_outlier():
    """A rate whose denominator was not reported has no unit value to compare.

    Its numerator jump must not create a VERY_HIGH finding: that is how a
    missing (often Optional) source element used to penalize the Quality Score
    as if the rate itself were an outlier. The row is still persisted so the
    missing denominator stays visible.
    """
    spec = AnalysisSpec(
        analysis_code="rate_cs", name="C-section rate", indicator_type="rate",
        numerator_codes=("5",), denominator_codes=("2",), rate_multiplier=100.0,
    )
    history = {"2026-01": {"5": 0}, "2026-02": {"5": 0},
               "2026-03": {"5": 0}, MONTH: {"5": 40}}     # deliveries (2) missing
    result = run_layered_analysis([spec], history, MONTH, 1, {1: history}, {},
                                  Thresholds())[0]

    assert result.rate.rate is None
    assert result.classification.outlier_level == "NONE"
    assert not is_detection_outlier(result.classification.outlier_level)
    assert result.classification.outlier_type == "NORMAL"
    assert should_persist(result) is True
    assert "not classified as an outlier" in result.classification.interpretation
