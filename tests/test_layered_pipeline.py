"""Persistence and lifecycle of layered_outlier_results (design spec §7).

The layered engine itself is covered by tests/test_layered_engine.py; these
tests prove the pipeline writes, replaces, purges and isolates the rows.
"""
import pytest

from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)

PRIOR_MONTHS = ["2027-01", "2027-02", "2027-03", "2027-04", "2027-05"]
CURRENT = "2027-06"


def _seed_values(db, hospital_id, month, values):
    code_to_ind = {i.code: i for i in db.query(Indicator).all()}
    for code, val in values.items():
        ind = code_to_ind.get(code)
        if ind is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                              month=month, value=val))
    db.commit()


def _seed_history(db, name, current_values, prior_values=None):
    """Active hospital with five prior months of history plus CURRENT."""
    prior_values = prior_values or {"2": 100, "5": 10}
    hosp = Hospital(name=name, region="Region A")
    db.add(hosp)
    db.flush()
    for month in PRIOR_MONTHS:
        _seed_values(db, hosp.id, month, prior_values)
    _seed_values(db, hosp.id, CURRENT, current_values)
    return hosp


def _rows(db, hospital_id, month=CURRENT):
    return (
        db.query(LayeredOutlierResult)
        .filter(LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month)
        .all()
    )


def test_pipeline_persists_layered_rows(db_session):
    """Full analysis writes one row per observed analysis unit with scores,
    classification and interpretation attached (spec §7)."""
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Persist", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)

    rows = _rows(db_session, hosp.id)
    assert len(rows) >= 3
    by_code = {r.analysis_code: r for r in rows}

    rate_row = by_code["rate_cs"]
    assert rate_row.rate == pytest.approx(25.0)
    assert rate_row.numerator == pytest.approx(25.0)
    assert rate_row.denominator == pytest.approx(100.0)
    assert rate_row.previous_value == pytest.approx(10.0)
    assert rate_row.previous_denominator == pytest.approx(100.0)
    assert rate_row.denominator_change_percent == pytest.approx(0.0)
    assert rate_row.historical_mean == pytest.approx(10.0)
    assert rate_row.historical_median == pytest.approx(10.0)
    assert rate_row.historical_change_percent == pytest.approx(150.0)
    assert rate_row.raw_value_outlier_score == pytest.approx(1.0)
    assert rate_row.rate_outlier_score >= 0.75        # rule 4 premise (HIGH)
    assert rate_row.historical_outlier_score >= 0.75
    assert rate_row.volume_anomaly_score == pytest.approx(0.0)
    assert rate_row.peer_mean is None                 # sole reporting hospital
    assert rate_row.peer_count == 0
    assert rate_row.outlier_type == "CLINICAL_INVESTIGATION_REQUIRED"
    assert rate_row.outlier_level == "VERY_HIGH"
    assert rate_row.investigation_required is True
    assert rate_row.investigation_route == "clinical"
    assert rate_row.outlier_method
    assert "25" in rate_row.interpretation            # actual numbers in text

    count_row = by_code["5"]
    assert count_row.indicator_id is not None
    assert count_row.rate is None
    assert count_row.volume_anomaly_score is None     # volume layer: count rows
    assert count_row.raw_value == pytest.approx(25.0)
    assert count_row.previous_value == pytest.approx(10.0)
    assert count_row.outlier_type == "HISTORICAL_ANOMALY"
    assert count_row.outlier_level == "VERY_HIGH"
    assert count_row.investigation_required is False
    assert count_row.investigation_route == "contextual"
    assert "own recent baseline" in count_row.interpretation

    normal_row = by_code["2"]
    assert normal_row.outlier_type == "NORMAL"
    assert normal_row.outlier_level == "NONE"
    assert normal_row.raw_value == pytest.approx(100.0)
    assert normal_row.investigation_route == "none"
    assert "No layer exceeded its threshold" in normal_row.interpretation

    # Core quality score is written alongside — layered rows are additive (Q3).
    qs = (db_session.query(QualityScore)
          .filter_by(hospital_id=hosp.id, month=CURRENT).first())
    assert qs is not None


def test_reanalysis_replaces_rows_without_duplicates(db_session):
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Dup", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    first = sorted(r.analysis_code for r in _rows(db_session, hosp.id))
    assert first

    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    second = _rows(db_session, hosp.id)
    assert sorted(r.analysis_code for r in second) == first
    ids = [r.id for r in second]
    assert len(ids) == len(set(ids))


def test_peer_inputs_flow_into_persisted_rows(db_session):
    """Peer tiers are built from all_hospital_data re-keyed by hospital id
    (tier attributes straight from the Hospital columns)."""
    from app.engine.pipeline import run_full_analysis

    target = _seed_history(db_session, "PeerFlow Target", {"2": 100, "5": 25})
    for name, csections in (("PeerFlow B", 10), ("PeerFlow C", 10)):
        peer = Hospital(name=name, region="Region A")
        db_session.add(peer)
        db_session.flush()
        _seed_values(db_session, peer.id, CURRENT, {"2": 100, "5": csections})
    db_session.commit()

    run_full_analysis(db_session, target.id, CURRENT, force=True)

    rate_row = {r.analysis_code: r
                for r in _rows(db_session, target.id)}["rate_cs"]
    assert rate_row.peer_count == 2
    assert rate_row.peer_mean == pytest.approx(10.0)
    assert rate_row.peer_outlier_score == pytest.approx(1.0)  # stdev 0, 25 != 10
    # The peer layer never rescues the clinical rule: rate + history high
    # with a stable denominator still classifies as clinical (rule 4 first).
    assert rate_row.outlier_type == "CLINICAL_INVESTIGATION_REQUIRED"


def test_purge_derived_results_includes_layered_rows(db_session):
    from app.engine.pipeline import purge_derived_results, run_full_analysis

    hosp = _seed_history(db_session, "Layered Purge", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    n = len(_rows(db_session, hosp.id))
    assert n > 0

    counts = purge_derived_results(db_session, hosp.id, CURRENT)
    assert counts["layered_outlier_results"] == n
    assert _rows(db_session, hosp.id) == []


def test_force_recompute_with_no_data_clears_layered_rows(db_session):
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Empty", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    assert _rows(db_session, hosp.id)

    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hosp.id
    ).delete(synchronize_session=False)
    db_session.commit()

    result = run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    assert result["data_quality_score"] == 0
    assert _rows(db_session, hosp.id) == []


def test_layered_failure_does_not_break_core_analysis(db_session, monkeypatch):
    """A crash inside layered persistence must not fall back to the zero-score
    error report (run_full_analysis's outer handler) — the layered try/except
    inside _compute_full_analysis isolates it."""
    import app.engine.anomaly.layered as layered_mod
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Isolated", {"2": 100, "5": 25})

    def _boom(session):
        raise RuntimeError("injected layered failure")

    monkeypatch.setattr(layered_mod, "build_analysis_specs", _boom)
    result = run_full_analysis(db_session, hosp.id, CURRENT, force=True)

    assert "Analysis failed during report generation" not in (result.get("issues") or [])
    assert _rows(db_session, hosp.id) == []
    assert (db_session.query(QualityScore)
            .filter_by(hospital_id=hosp.id, month=CURRENT).first()) is not None
