"""Zero-dispersion comparisons must not claim the top severity band.

In the live database 889 stored alerts had a baseline of exactly 0, a score of
1.0 and no z-score — 24% of every VERY_HIGH row. The baseline was not
miscalculated: every hospital in the comparison group reported the same value
(almost always 0), so the group has no spread, the z-score is undefined, and
the shared score builders fall back to 1.0 — "maximal deviation". That made
"only this hospital reports this indicator" the loudest finding on the screen.

Policy (approved): keep the finding — being the only reporter IS evidence —
cap its level at HIGH, and record the cap next to the evidence so the screens
explain the number instead of quoting an unmeasurable maximum. Comparisons
with real spread are untouched, so the existing thresholds still decide every
measured deviation.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine.quality_alerts import (
    ZERO_SPREAD_LEVEL_CAP,
    _history_score,
    cap_zero_spread,
    scan,
    zero_spread,
)
from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    QualityAlert,
)

PRIOR_MONTHS = ["2027-01", "2027-02", "2027-03"]
CURRENT = "2027-04"


# ── The documented policy, as a pure function ──────────────────────────────

def test_zero_spread_detection_requires_a_known_zero_std():
    assert zero_spread({"std": 0.0, "mean": 0.0}) is True
    assert zero_spread({"std": 0, "mean": 5.0}) is True   # flat at a non-zero level
    assert zero_spread({"std": 1.5}) is False             # real spread
    assert zero_spread({"std": None}) is False            # not computable
    assert zero_spread(None) is False


def test_cap_ignores_a_measured_percentage_change():
    """A flat history judged by pct_change is measurable, not degenerate.

    "+700% against a flat 10%" has a real magnitude even though the spread is
    0; only the methods that divide by the spread are undefined.
    """
    assert zero_spread({"std": 0.0}, "pct_change") is False
    assert cap_zero_spread("VERY_HIGH", {"std": 0.0}, "pct_change") == (
        "VERY_HIGH", None)
    assert zero_spread({"std": 0.0}, "peer_zscore") is True
    assert zero_spread({"std": 0.0}, "rolling_median_mad") is True
    assert zero_spread({"std": 0.0}, "iqr") is True


def test_a_zero_median_deviation_is_degenerate_even_when_std_is_not():
    """MAD = 0 and IQR = 0 are degenerate comparisons, not measured ones.

    A zero-window spike (``[0, 0, 0, 0, 0, 18.9, 0]``) has MAD 0 and IQR 0
    while its std is 7.13, so testing std alone saw a measured comparison and
    the row kept VERY_HIGH — the live store carried 533 such rows, 491 of them
    with std > 0 (e.g. alert 346: hospital 13, ``sys_forecast_smm_per_1000``,
    2026-08, score 1.0, std 7.13, IQR 0).
    """
    series = [0.0, 0.0, 0.0, 0.0, 0.0, 18.867924528301884, 0.0]
    stats = {"std": 7.13, "mean": 2.695}

    assert zero_spread(stats, "rolling_median_mad", series) is True
    assert zero_spread(stats, "iqr", series) is True
    # A z-score divides by std, which IS measurable for this window.
    assert zero_spread(stats, "zscore", series) is False

    level, provenance = cap_zero_spread("VERY_HIGH", stats,
                                        "rolling_median_mad", series)
    assert level == "HIGH"
    assert provenance["std"] == pytest.approx(7.13)    # std is recorded, not 0
    assert provenance["dispersion"] == {"kind": "mad", "value": 0.0}
    assert "capped at HIGH" in provenance["policy"]

    # A measured robust spread keeps its band.
    measured = {"std": 4.0}
    assert zero_spread(measured, "rolling_median_mad", [1.0, 4.0, 9.0, 16.0]) is False
    assert cap_zero_spread("VERY_HIGH", measured, "iqr",
                           [1.0, 4.0, 9.0, 16.0]) == ("VERY_HIGH", None)


def test_a_recorded_divisor_is_used_without_the_series():
    """New rows record MAD/IQR; a legacy row with neither keeps the std test."""
    assert zero_spread({"std": 3.0, "mad": 0.0}, "rolling_median_mad") is True
    assert zero_spread({"std": 3.0, "iqr": 0.0}, "iqr") is True
    assert zero_spread({"std": 3.0, "mad": 1.5}, "rolling_median_mad") is False
    assert zero_spread({"std": 3.0, "iqr": 2.0}, "iqr") is False
    # Nothing recorded to divide by: the std-only test still applies.
    assert zero_spread({"std": 0.0}, "rolling_median_mad") is True
    assert zero_spread({"std": 2.0}, "rolling_median_mad") is False


def test_the_scan_records_the_divisor_it_scored_with():
    """Reproduces the reported hospital-36 row: MAD 0, std 1.50, score 1.0."""
    score, method, _z, stats = _history_score(
        "count", [0.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0], 2.0, 2.5,
        outlier_method="rolling_median_mad")

    assert method == "rolling_median_mad"
    assert score == pytest.approx(1.0)
    assert stats["mad"] == pytest.approx(0.0)
    # The IQR is recorded beside it and is NOT zero — only the divisor the
    # method actually used may decide the cap.
    assert stats["iqr"] == pytest.approx(0.5)
    assert stats["std"] > 0

    assert zero_spread(stats, method) is True
    assert cap_zero_spread("VERY_HIGH", stats, method)[0] == "HIGH"


def test_cap_only_lowers_the_top_band_of_a_degenerate_comparison():
    level, provenance = cap_zero_spread("VERY_HIGH", {"std": 0.0})
    assert level == "HIGH"
    assert provenance["capped"] is True
    assert provenance["resolved_level"] == "VERY_HIGH"
    assert provenance["cap"] == ZERO_SPREAD_LEVEL_CAP
    assert "capped at HIGH" in provenance["policy"]

    # A level the comparison actually earned is never lowered further.
    assert cap_zero_spread("MODERATE", {"std": 0.0})[0] == "MODERATE"
    assert cap_zero_spread("HIGH", {"std": 0.0})[0] == "HIGH"

    # Measured comparisons keep their band and carry no provenance block.
    assert cap_zero_spread("VERY_HIGH", {"std": 0.42}) == ("VERY_HIGH", None)


# ── Scan: the two shapes side by side ──────────────────────────────────────

@pytest.fixture
def spread_dataset(db_session):
    """One indicator with a flat peer group, one with a real spread.

    ``ZS_FLAT`` — the flagged hospital reports a case while its peers report
    0 for every month, so the peer group and the hospital's own history are
    both zero-dispersion.
    ``ZS_SPREAD`` — the same hospital spikes while its peers differ from each
    other (0, 10, 20, 30), so the comparison has a measurable scale.

    FOUR peers, not two: a comparison group below
    ``layered.MIN_PEERS_FOR_TOP_BAND`` cannot measure a spread, so its band is
    capped at HIGH and no z-score is produced for it. The control case needs a
    group that CAN be graded, otherwise "measured spread keeps its band" would
    be untestable here.
    """
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()
    assert len(hospitals) >= 3, "conftest seeds 3 hospitals"
    hospitals = hospitals[:3]
    for index in range(3, 5):
        extra = Hospital(name=f"Zero-spread peer {index}", region="Region A")
        db_session.add(extra)
        hospitals.append(extra)
    db_session.flush()

    definitions = {}
    for code in ("ZS_FLAT", "ZS_SPREAD", "ZS_JUMP"):
        num = Indicator(code=f"{code}_NUM", name=f"{code} numerator")
        den = Indicator(code=f"{code}_DEN", name=f"{code} denominator")
        db_session.add_all([num, den])
        db_session.flush()
        definition = IndicatorDefinition(
            code=code,
            name=f"{code} test rate",
            description="zero-spread policy fixture",
            formula_type="ratio",
            numerator_codes=[num.code],
            denominator_codes=[den.code],
            operator="/",
            multiplier=100.0,
            result_type="percentage",
            unit="%",
            direction="lower_is_better",
            is_active=True,
        )
        db_session.add(definition)
        db_session.flush()
        definitions[code] = {"num": num, "den": den}

    # numerator values per (code, hospital index, month index)
    flat = {0: [0.0, 0.0, 0.0, 10.0], 1: [0.0] * 4, 2: [0.0] * 4,
            3: [0.0] * 4, 4: [0.0] * 4}
    spread = {0: [5.0, 6.0, 7.0, 100.0], 1: [0.0] * 4, 2: [20.0] * 4,
              3: [10.0] * 4, 4: [30.0] * 4}
    # Flat non-zero history for the flagged hospital (pct_change applies) and
    # flat peers (z applies) on the same issue.
    jump = {0: [10.0, 10.0, 10.0, 80.0], 1: [10.0] * 4, 2: [10.0] * 4,
            3: [10.0] * 4, 4: [10.0] * 4}
    for code, series in (("ZS_FLAT", flat), ("ZS_SPREAD", spread),
                         ("ZS_JUMP", jump)):
        for hi, hospital in enumerate(hospitals):
            for mi, month in enumerate(PRIOR_MONTHS + [CURRENT]):
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, month=month,
                    indicator_id=definitions[code]["num"].id,
                    value=series[hi][mi]))
                db_session.add(IndicatorValue(
                    hospital_id=hospital.id, month=month,
                    indicator_id=definitions[code]["den"].id, value=100.0))
    db_session.commit()
    return {"hospitals": hospitals, "definitions": definitions}


def _alerts(db, hospital_id, code, month=CURRENT):
    return (db.query(QualityAlert)
            .filter_by(hospital_id=hospital_id, indicator_code=code,
                       month=month)
            .all())


def test_flat_peer_group_keeps_the_finding_but_caps_it_at_high(
        db_session, spread_dataset):
    scan(db_session, CURRENT)
    flagged = spread_dataset["hospitals"][0]
    alerts = _alerts(db_session, flagged.id, "ZS_FLAT")

    assert alerts, "the only reporting hospital must still be flagged"
    for alert in alerts:
        # Level: capped. Evidence: preserved verbatim.
        assert alert.severity == "HIGH"
        assert alert.score == pytest.approx(1.0)
        assert alert.baseline_value == pytest.approx(0.0)
        assert alert.z_score is None
        assert alert.evidence["stats"]["std"] == pytest.approx(0.0)

    dispersion = alerts[0].evidence["dispersion"]
    assert dispersion["zero_spread"] is True
    assert dispersion["resolved_level"] == "VERY_HIGH"
    assert dispersion["final_level"] == "HIGH"
    assert dispersion["capped"] is True
    # The stored explanation says why, next to the numbers it explains.
    assert "capped at HIGH" in (alerts[0].reason or "")


def test_scan_stores_the_capped_band_for_a_zero_iqr_history(db_session):
    """The write side caps a zero-IQR window instead of leaving it to readers.

    ``[0, 0, 0, 0, 10]`` has IQR 0 while its std is 4.47: an ``iqr`` row has
    nothing to divide by, so its band is capped the moment it is stored. Before
    this, only the read-time cap lowered such a row, so months nobody rescanned
    kept a stored VERY_HIGH that the audit reported as stored-vs-policy drift.
    """
    current = "2027-06"
    history_months = ["2027-01", "2027-02", "2027-03", "2027-04", "2027-05"]
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:2]
    element = Indicator(
        code="ZS_IQR_ZERO", name="Zero-IQR window", indicator_type="count",
        outlier_method="iqr", minimum_history_period=3,
    )
    db_session.add(element)
    db_session.flush()
    for month, values in zip(
            history_months + [current],
            [[0.0, 5.0], [0.0, 5.0], [0.0, 5.0], [0.0, 5.0], [10.0, 5.0],
             [10.0, 5.0]]):
        for hospital, value in zip(hospitals, values):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, month=month,
                indicator_id=element.id, value=value))
    db_session.commit()

    scan(db_session, current)

    alerts = _alerts(db_session, hospitals[0].id, "ZS_IQR_ZERO", current)
    history = next(a for a in alerts if a.perspective == "history")
    assert history.method == "iqr"
    assert history.evidence["stats"]["iqr"] == pytest.approx(0.0)
    assert history.evidence["stats"]["std"] > 0, "std alone would look measured"
    assert history.severity == "HIGH", "the divisor the method used decides"

    dispersion = history.evidence["dispersion"]
    assert dispersion["dispersion"] == {"kind": "iqr", "value": 0.0}
    assert dispersion["resolved_level"] == "VERY_HIGH"
    assert dispersion["final_level"] == "HIGH"
    assert "capped at HIGH" in (history.reason or "")


def test_measured_spread_still_reaches_very_high(db_session, spread_dataset):
    """The guard must not become a blanket downgrade."""
    scan(db_session, CURRENT)
    flagged = spread_dataset["hospitals"][0]
    alert = next(a for a in _alerts(db_session, flagged.id, "ZS_SPREAD")
                 if a.perspective == "all")

    assert alert.severity == "VERY_HIGH"
    assert alert.score == pytest.approx(1.0)
    assert alert.z_score is not None
    assert alert.evidence["stats"]["std"] > 0
    assert alert.evidence.get("dispersion") is None


def test_flat_history_judged_by_pct_change_keeps_its_band(
        db_session, spread_dataset):
    """Only dispersion-based scores are capped; a flat baseline does not
    turn a measurable percentage jump into "unmeasurable"."""
    scan(db_session, CURRENT)
    flagged = spread_dataset["hospitals"][0]
    rows = {a.perspective: a for a in _alerts(db_session, flagged.id, "ZS_JUMP")}

    history = rows["history"]
    assert history.method == "pct_change"
    assert history.evidence["stats"]["std"] == pytest.approx(0.0)
    assert history.severity == "VERY_HIGH", "+700% is measured, not degenerate"
    assert history.evidence.get("dispersion") is None

    # The peer group on the same issue IS degenerate (both peers report the
    # same value), so that perspective alone is capped.
    peers = rows["all"]
    assert peers.severity == "HIGH"
    assert peers.evidence["dispersion"]["capped"] is True


def test_issue_rows_expose_the_zero_spread_flag(app, db_session, spread_dataset):
    """The list needs the flag to label a 0 baseline as unmeasured."""
    scan(db_session, CURRENT)
    client = TestClient(app)
    flagged = spread_dataset["hospitals"][0]

    resp = client.get("/quality-alerts/issues",
                      params={"month": CURRENT, "indicator": "ZS_FLAT",
                              "page_size": 200})
    assert resp.status_code == 200, resp.text
    items = [i for i in resp.json()["items"]
             if i["hospital_id"] == flagged.id]
    assert items, "the flagged issue must be listed"
    flat = {p["perspective"]: p for p in items[0]["perspectives"]}
    assert flat and all(p["zero_spread"] is True for p in flat.values())
    assert all(p["severity"] == "HIGH" for p in flat.values())

    resp = client.get("/quality-alerts/issues",
                      params={"month": CURRENT, "indicator": "ZS_SPREAD",
                              "page_size": 200})
    control = next(i for i in resp.json()["items"]
                   if i["hospital_id"] == flagged.id)
    measured = {p["perspective"]: p for p in control["perspectives"]}
    assert measured["all"]["zero_spread"] is False
    assert measured["all"]["severity"] == "VERY_HIGH"
