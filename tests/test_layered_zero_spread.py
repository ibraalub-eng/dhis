"""Zero-dispersion cap in Anomaly Diagnostics (the second screen).

Quality Alerts refuses to let a comparison whose members all reported the same
value claim the top band: the spread is 0, the z-score is undefined, and the
shared score builders fall back to 1.0 ("maximal deviation"). Diagnostics used
the same builders and the same 1.0 fallback, so the same hospital/month could
be HIGH on one screen and VERY_HIGH on the other.

The cap is now shared (`layered.cap_zero_spread`) and applied to the LAYER
band: a degenerate peer group or a flat own-history baseline cannot reach
VERY_HIGH, while a layer with real spread — or a percentage change against a
flat baseline, which is measurable — keeps the band its magnitude earns.
"""
import statistics

import pytest

from app.engine.anomaly.classify import TYPE_PEER_ANOMALY, classify_layered
from app.engine.anomaly.layered import (
    LEVEL_HIGH,
    METHOD_PCT_CHANGE,
    METHOD_PEER_ZSCORE,
    ZERO_SPREAD_LEVEL_CAP,
    AnalysisSpec,
    Thresholds,
    analyze_layered_entry,
    cap_zero_spread,
    compute_peer_layer,
    no_dispersion,
    spread_used,
    zero_dispersion,
)
from app.engine.audit.explain import explain_layered_outlier
from app.engine.pipeline import _save_layered_results
from app.models import Hospital, Indicator, IndicatorValue, LayeredOutlierResult

CURRENT = "2027-04"
PRIOR = ["2027-01", "2027-02", "2027-03"]


def _count_spec() -> AnalysisSpec:
    return AnalysisSpec(analysis_code="17", name="Neonatal deaths",
                        indicator_type="count")


def _rate_spec() -> AnalysisSpec:
    return AnalysisSpec(
        analysis_code="rate_cs", name="C-section rate", indicator_type="rate",
        numerator_codes=("5",), denominator_codes=("2",),
        rate_multiplier=100.0, unit="%",
    )


# ── The shared predicate ───────────────────────────────────────────────────

def test_zero_dispersion_only_applies_to_spread_based_methods():
    assert zero_dispersion(0.0, METHOD_PEER_ZSCORE) is True
    assert zero_dispersion(0.0, "rolling_median_mad") is True
    assert zero_dispersion(0.0, "iqr") is True
    # A percentage change divides by the baseline, not the spread.
    assert zero_dispersion(0.0, METHOD_PCT_CHANGE) is False
    assert zero_dispersion(1.5) is False
    assert zero_dispersion(None) is False


def test_a_robust_method_is_graded_by_its_own_divisor():
    """MAD/IQR = 0 is a degenerate comparison even when std is not.

    ``[0, 0, 0, 1, 4, 0, 0]`` has MAD = 0 and IQR = 0 but std > 0, so the
    std-only test let a ``rolling_median_mad`` / ``iqr`` row claim VERY_HIGH
    on a scale its own method did not have (533 rows on the live store).
    """
    series = [0.0, 0.0, 0.0, 1.0, 4.0, 0.0, 0.0]
    assert statistics.stdev(series) > 0                 # std is NOT degenerate
    assert spread_used("rolling_median_mad", series) == (0.0, "mad")
    assert spread_used("zscore", series)[1] == "std"

    # A single spike in a zero window collapses BOTH robust divisors.
    spike = [0.0, 0.0, 0.0, 0.0, 0.0, 18.87, 0.0]
    assert statistics.stdev(spike) > 0
    assert spread_used("rolling_median_mad", spike) == (0.0, "mad")
    assert spread_used("iqr", spike) == (0.0, "iqr")
    assert no_dispersion("iqr", spike) is True
    assert no_dispersion("rolling_median_mad", series) is True
    # Its IQR is 0.5, so the IQR method IS measurable on this window.
    assert no_dispersion("iqr", series) is False
    # A z-score divides by std, which is real for this window.
    assert no_dispersion("zscore", series) is False
    assert no_dispersion(METHOD_PCT_CHANGE, series) is False

    # A measured robust spread keeps the band it earned.
    measured = [1.0, 4.0, 9.0, 16.0]
    assert no_dispersion("rolling_median_mad", measured) is False
    assert no_dispersion("iqr", measured) is False


def test_cap_refuses_the_top_band_and_records_what_was_implied():
    level, provenance = cap_zero_spread("VERY_HIGH", 0.0, METHOD_PEER_ZSCORE)
    assert level == ZERO_SPREAD_LEVEL_CAP == LEVEL_HIGH
    assert provenance["capped"] is True
    assert provenance["resolved_level"] == "VERY_HIGH"
    assert provenance["final_level"] == "HIGH"
    # Bands at or below the cap are untouched, and measured spreads are free.
    assert cap_zero_spread("MODERATE", 0.0, METHOD_PEER_ZSCORE)[0] == "MODERATE"
    assert cap_zero_spread("VERY_HIGH", 0.8, METHOD_PEER_ZSCORE) == (
        "VERY_HIGH", None)


# ── Classification: per-layer cap, never per-row ──────────────────────────

def test_degenerate_peer_band_is_capped_but_still_classifies():
    common = dict(spec=_rate_spec(), raw_score=None, rate_score=None,
                  hist_score=None, volume_score=None, peer_score=1.0,
                  den_ok=True, history_ok=False)

    plain = classify_layered(**common)
    assert plain.rule_number == 11
    assert plain.outlier_type == TYPE_PEER_ANOMALY
    assert plain.outlier_level == "VERY_HIGH"
    assert plain.zero_spread_layers == ()
    assert plain.level_capped_from is None

    capped = classify_layered(**common, degenerate_layers=("peer",))
    assert capped.rule_number == 11, "the peer evidence still classifies"
    assert capped.outlier_type == TYPE_PEER_ANOMALY
    assert capped.outlier_level == "HIGH"
    assert capped.zero_spread_layers == ("peer",)
    assert capped.level_capped_from == "VERY_HIGH"
    assert "peer comparison has no spread" in capped.interpretation
    assert "capped at HIGH" in capped.interpretation
    # The band quoted for the peer layer is the capped one, never VERY_HIGH.
    assert "peer comparison VERY_HIGH" not in capped.interpretation


def test_measured_layer_still_reaches_very_high_beside_a_degenerate_one():
    c = classify_layered(
        _rate_spec(), raw_score=0.60, rate_score=0.60, hist_score=0.95,
        volume_score=0.0, peer_score=1.0, den_ok=True, history_ok=True,
        degenerate_layers=("peer",),
    )
    assert c.outlier_type == "HISTORICAL_ANOMALY"
    assert c.outlier_level == "VERY_HIGH", "own history measured the magnitude"
    assert c.zero_spread_layers == ()
    assert c.level_capped_from is None


# ── Entry point: real series -> layer flags -> stored level ───────────────

def test_flat_peer_group_marks_the_peer_layer_and_caps_the_row():
    history = {month: {"17": 0} for month in PRIOR}
    history[CURRENT] = {"17": 2}
    peers = [("all", {1: 2.0, 2: 0.0, 3: 0.0, 4: 0.0})]

    result = analyze_layered_entry(_count_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=1)

    assert result.peer.zero_spread is True
    assert result.peer.z is None
    assert result.peer.score == pytest.approx(1.0)   # evidence preserved
    assert result.historical.zero_spread is True      # the history is flat too
    assert "peer" in result.classification.zero_spread_layers
    assert "historical" in result.classification.zero_spread_layers
    assert result.classification.outlier_level == "HIGH"
    assert result.classification.level_capped_from == "VERY_HIGH"
    assert "capped at HIGH" in result.classification.interpretation


def test_flat_history_judged_by_pct_change_is_not_degenerate():
    """+700% over a flat 10% is a measured magnitude, not a 0/0 comparison."""
    history = {month: {"5": 10, "2": 100} for month in PRIOR}
    history[CURRENT] = {"5": 80, "2": 100}
    # Peers differ from each other, so the peer layer has real spread.
    peers = [("all", {1: 80.0, 2: 20.0, 3: 40.0})]

    result = analyze_layered_entry(_rate_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=1)

    assert result.historical.method == METHOD_PCT_CHANGE
    assert result.historical.std == pytest.approx(0.0)
    assert result.historical.zero_spread is False
    assert result.classification.zero_spread_layers == ()
    assert result.classification.outlier_level == "VERY_HIGH"


def test_compute_peer_layer_flags_a_group_with_no_spread():
    layer = compute_peer_layer(
        AnalysisSpec(analysis_code="17", name="x", indicator_type="count"),
        self_id=1, current_value=2.0,
        peer_tiers=[("all", {1: 2.0, 2: 0.0, 3: 0.0})],
    )
    assert layer.peer_std == pytest.approx(0.0)
    assert layer.zero_spread is True
    assert layer.score == pytest.approx(1.0)


# ── Persistence + Why popup ───────────────────────────────────────────────

@pytest.fixture
def stored_flat_peer_row(db_session):
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    indicator = db_session.query(Indicator).filter_by(code="17").first()
    assert indicator is not None, "conftest seeds indicator 17"
    for month in PRIOR:
        db_session.add(IndicatorValue(hospital_id=hospital.id, month=month,
                                      indicator_id=indicator.id, value=0.0))
    db_session.add(IndicatorValue(hospital_id=hospital.id, month=CURRENT,
                                  indicator_id=indicator.id, value=2.0))
    db_session.commit()

    history = {month: {"17": 0} for month in PRIOR}
    history[CURRENT] = {"17": 2}
    # History rows must match the database (the popup recomputes sufficiency
    # from stored values); peers are all-identical, which is the case here.
    peers = [("all", {hospital.id: 2.0, hospital.id + 1: 0.0,
                      hospital.id + 2: 0.0})]
    result = analyze_layered_entry(_count_spec(), history, CURRENT, peers,
                                   Thresholds(), self_id=hospital.id)
    _save_layered_results(db_session, hospital.id, CURRENT, [result])
    return hospital


def test_pipeline_persists_the_layers_it_capped(db_session, stored_flat_peer_row):
    row = (db_session.query(LayeredOutlierResult)
           .filter_by(hospital_id=stored_flat_peer_row.id, month=CURRENT,
                      analysis_code="17").one())
    provenance = row.classification_provenance
    assert provenance["zero_spread_layers"], "the cap must travel with the row"
    assert "peer" in provenance["zero_spread_layers"]
    assert provenance["level"] == "HIGH"
    assert provenance["level_from_layers"] == "VERY_HIGH"
    assert provenance["cap"] == ZERO_SPREAD_LEVEL_CAP
    assert row.outlier_level == "HIGH"
    assert row.peer_outlier_score == pytest.approx(1.0)


def test_popup_reproduces_the_capped_row_and_shows_the_capped_band(
        db_session, stored_flat_peer_row):
    payload = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                      CURRENT, "17")
    assert payload["reproduce"]["verified"] is True
    assert payload["reproduce"]["zero_spread_layers"]
    assert payload["reproduce"]["level_from_layers"] == "VERY_HIGH"
    assert payload["outlier_level"] == "HIGH"
    assert payload["classification_provenance"]["level"] == "HIGH"

    peer_layer = next(layer for layer in payload["layers"] if layer["key"] == "peer")
    assert peer_layer["score"] == pytest.approx(1.0)
    assert peer_layer["zero_spread"] is True
    assert peer_layer["level"] == "HIGH", "strip must not quote the uncapped band"


# ── Cross-check vs closed alerts (Quality Alerts investigation workflow) ──

def _stored_alert(db_session, hospital, *, severity="VERY_HIGH", status="New",
                  perspective="all", method="zscore", peer_count=None):
    from app.models import QualityAlert
    alert = QualityAlert(
        hospital_id=hospital.id, month=CURRENT, perspective=perspective,
        indicator_code="17", indicator_name="Neonatal deaths", unit="",
        severity=severity, score=1.0, method=method, peer_count=peer_count,
        current_value=2.0, baseline_value=0.0, status=status, active=True,
    )
    db_session.add(alert)
    db_session.commit()
    return alert


# ── The cross-check quotes the POLICY band, not the stored one ────────────

def test_cross_check_quotes_the_policy_band_for_a_thin_peer_alert(
        db_session, stored_flat_peer_row):
    """A row stored above what the policy allows must not be re-quoted as is.

    The Quality Alerts screen shows the band the approved cap policy assigns
    (too few peers to measure a spread is not very high). Diagnostics quoting
    the STORED band instead made the two screens name different severities for
    one stored alert — the exact disagreement this block exists to explain.
    """
    _stored_alert(db_session, stored_flat_peer_row, severity="VERY_HIGH",
                  perspective="all", method=METHOD_PEER_ZSCORE, peer_count=2)
    cc = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                 CURRENT, "17")["cross_check"]
    shown = cc["perspectives"][0]

    assert shown["severity"] == "HIGH", "must quote the policy band"
    assert shown["stored_severity"] == "VERY_HIGH", "stored band preserved"
    assert shown["level_capped"] is True
    assert shown["capped_from"] == "VERY_HIGH"
    assert shown["severity_cap"]["thin_peer_group"]["capped"] is True
    assert cc["strongest_alert"]["severity"] == "HIGH"


def test_cross_check_marks_a_closed_alert_instead_of_quoting_it_as_live(
        db_session, stored_flat_peer_row):
    """A resolved alert no longer raises — the popup must say so.

    Otherwise Diagnostics would quote a closed alert as the second verdict and
    the reader would think Quality Alerts is still raising it.
    """
    _stored_alert(db_session, stored_flat_peer_row, status="Resolved")
    cc = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                 CURRENT, "17")["cross_check"]

    assert cc["strongest_alert"]["closed"] is True
    assert cc["strongest_alert"]["status"] == "Resolved"
    assert cc["perspectives"][0]["closed"] is True
    assert "closed by a reviewer" in cc["explanation"]


def test_cross_check_compares_against_the_open_alert_not_the_closed_one(
        db_session, stored_flat_peer_row):
    """The open row is what the other screen shows, so it is the comparison."""
    _stored_alert(db_session, stored_flat_peer_row, status="Resolved",
                  perspective="all")
    _stored_alert(db_session, stored_flat_peer_row, severity="HIGH",
                  status="New", perspective="history")

    cc = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                 CURRENT, "17")["cross_check"]

    assert cc["strongest_alert"]["severity"] == "HIGH"
    assert cc["strongest_alert"]["closed"] is False
    assert "closed by a reviewer" not in cc["explanation"]
    closed_rows = [p for p in cc["perspectives"] if p["closed"]]
    assert len(closed_rows) == 1
    assert closed_rows[0]["severity"] == "VERY_HIGH"


def test_false_positive_alert_is_closed_like_resolved(
        db_session, stored_flat_peer_row):
    _stored_alert(db_session, stored_flat_peer_row, status="False Positive")
    cc = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                 CURRENT, "17")["cross_check"]
    assert cc["strongest_alert"]["closed"] is True
    assert "closed by a reviewer" in cc["explanation"]


def test_legacy_row_without_provenance_is_reported_for_recalculation(
        db_session, stored_flat_peer_row):
    row = (db_session.query(LayeredOutlierResult)
           .filter_by(hospital_id=stored_flat_peer_row.id, month=CURRENT,
                      analysis_code="17").one())
    row.classification_provenance = None
    db_session.commit()

    payload = explain_layered_outlier(db_session, stored_flat_peer_row.id,
                                      CURRENT, "17")
    assert payload["reproduce"]["verified"] is False
    assert "recalculate this month" in payload["why"]
    # The stored peer group is still recognisable as no-spread evidence.
    assert payload["cross_check"]["diagnostic"]["peer_zero_spread"] is True
    assert payload["cross_check"]["diagnostic"]["peer_level"] == "HIGH"
