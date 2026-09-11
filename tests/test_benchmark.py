"""Regression tests for the audit benchmark peer breakdown."""

from app.engine.audit.benchmark import get_benchmark
from app.models import Hospital, Indicator, IndicatorValue


def _indicator_id(db, code):
    return db.query(Indicator).filter(Indicator.code == code).first().id


def _add_values(db, hospital_id, month, values):
    for code, value in values.items():
        db.add(IndicatorValue(
            hospital_id=hospital_id,
            indicator_id=_indicator_id(db, code),
            month=month,
            value=value,
        ))
    db.flush()


def test_benchmark_peer_breakdown(db_session):
    gh, cm, cc = db_session.query(Hospital).order_by(Hospital.id).all()
    month = "2026-08"

    # Target GH and one full peer (CM). Community Clinic reports data but with a
    # zero NICU denominator, so it cannot produce a NICU rate. Two hospitals have
    # no data at all; one inactive hospital has data but must be excluded.
    _add_values(db_session, gh.id, month, {"16": 8, "6": 100})
    _add_values(db_session, cm.id, month, {"16": 5, "6": 100})
    _add_values(db_session, cc.id, month, {"6": 0})
    inactive = Hospital(name="Inactive Extra", is_active=False)
    no_data_a = Hospital(name="No Data A")
    no_data_b = Hospital(name="No Data B")
    db_session.add_all([inactive, no_data_a, no_data_b])
    db_session.flush()
    _add_values(db_session, inactive.id, month, {"16": 99, "6": 100})

    result = get_benchmark(db_session, gh.id, month)

    assert "error" not in result
    assert result["hospital"] == "General Hospital"
    assert result["month"] == month
    assert "NICU admission rate" in result["comparisons"]

    nicu = result["comparisons"]["NICU admission rate"]
    assert nicu["hospital_value"] == 8.0
    assert nicu["peer_average"] == 5.0
    assert nicu["peer_median"] == 5.0
    assert nicu["peer_min"] == nicu["peer_max"] == 5.0
    assert nicu["peer_count"] == 1
    assert nicu["percentile"] == 100.0  # only peer is strictly below -> rank 1 of 1
    assert nicu["peers_below"] == 1
    assert nicu["z_score"] == 0.0  # single peer -> zero std

    assert nicu["peer_breakdown"] == {
        "total_active": 5,  # 3 seeded + 2 with no data (inactive excluded)
        "excluded_target": 1,
        "no_data_month_count": 2,
        "no_data_month_names": ["No Data A", "No Data B"],
        "no_denominator_count": 1,
        "no_denominator_names": ["Community Clinic"],
    }
    # The peer pool arithmetic must reconcile for every rate.
    for c in result["comparisons"].values():
        breakdown = c["peer_breakdown"]
        assert (
            breakdown["excluded_target"]
            + breakdown["no_data_month_count"]
            + breakdown["no_denominator_count"]
            + c["peer_count"]
            == breakdown["total_active"]
        )


def test_benchmark_no_data_returns_error(db_session):
    gh = db_session.query(Hospital).first()
    result = get_benchmark(db_session, gh.id, "2099-01")
    assert result["error"] == f"No data for {gh.name} / 2099-01"

def test_benchmark_percentile_reports_ties_honestly(db_session):
    """A hospital that ties every peer must report the median (50th), not 100th."""
    gh, cm, cc = db_session.query(Hospital).order_by(Hospital.id).all()
    month = "2026-08"
    _add_values(db_session, gh.id, month, {"16": 0, "6": 100})
    _add_values(db_session, cm.id, month, {"16": 0, "6": 100})

    result = get_benchmark(db_session, gh.id, month)
    nicu = result["comparisons"]["NICU admission rate"]
    assert nicu["hospital_value"] == 0.0
    assert nicu["peer_count"] == 1
    assert nicu["peers_below"] == 0
    assert nicu["percentile"] == 50.0  # full tie -> median, not "better than everyone"
