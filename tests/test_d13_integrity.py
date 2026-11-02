"""D13 regression — one authoritative engine, one band policy.

These tests pin the reconciliation established by the D12 audit:

* Quality Alerts and Outlier Diagnostics score a window through the SAME
  function (``layered.score_window_detail``), so identical inputs give
  identical scores and methods.
* Both gate the top band through the SAME policy
  (``layered.very_high_eligibility``), so the same question gets the same
  answer: a history claim the window refuses becomes HIGH on both screens.
* A layered row reports the MAX across its measured layers. An alert row
  scores ONE labelled perspective. The two therefore differ only when a
  different layer holds the top band (e.g. the peer layer), which is a
  different question — not a second calculation.
* The approved caps still run first and are never bypassed by the gate.

Nothing here rewrites a stored band, and no threshold or cutoff is changed.
"""
from types import SimpleNamespace

from app.engine import quality_alerts as qa
from app.engine.anomaly import layered

SERIES = [9.0, 2.0, 26.0, 16.0, 16.0, 13.0, 27.0]
CURRENT = 55.0
THRESHOLD = 2.5


def _row(**overrides):
    """A stored LayeredOutlierResult-shaped row (only fields the policy reads)."""
    base = dict(
        outlier_level=layered.LEVEL_VERY_HIGH,
        raw_value_outlier_score=0.95,
        rate_outlier_score=None,
        historical_outlier_score=0.95,
        volume_anomaly_score=None,
        peer_outlier_score=0.544,
        history_provenance={"values": list(SERIES)},
        classification_provenance={},
        peer_provenance={"values": [1.0, 2.0, 3.0]},
        peer_count=13,
        rate=None,
        raw_value=CURRENT,
        historical_std=8.885515232803384,
        outlier_method=layered.METHOD_IQR,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Shared scoring path ─────────────────────────────────────────────────────

def test_alert_and_diagnostics_score_one_window_identically():
    cases = [
        ("pct_change", [45.0, 38.0, 15.0], 29.0),
        ("rolling_median_mad", SERIES, CURRENT),
        ("iqr", SERIES, CURRENT),
    ]
    for explicit, series, current in cases:
        score, method, _z, _stats = qa._history_score(
            "count", series, current, THRESHOLD, outlier_method=explicit)
        shared, _before_cap = layered.score_window_detail(
            method, series, current, series[-1], THRESHOLD)
        assert method == explicit, method
        assert score == shared, (explicit, score, shared)


def test_percentage_change_is_capped_by_the_same_window_dispersion():
    series = [45.0, 38.0, 15.0]
    alert_score, _method, _z, _stats = qa._history_score(
        "count", series, 29.0, THRESHOLD, outlier_method="pct_change")
    raw = layered.score_from_pct_change(
        layered.percent_change(29.0, series[-1]))
    assert raw > alert_score == layered.cap_pct_change(
        raw, series, 29.0, THRESHOLD)


# ── Same question, same answer (history top band) ──────────────────────────

def test_history_top_band_is_refused_identically_on_both_screens():
    alert_band = qa.effective_severity(
        layered.LEVEL_VERY_HIGH, stats={"std": 8.885, "mean": 15.57},
        method=layered.METHOD_IQR, peer_count=13, series=SERIES,
        current=CURRENT, perspective="history", threshold=THRESHOLD)
    assert alert_band == layered.LEVEL_HIGH

    row_band, cap = layered.row_level_assessment(_row())
    assert row_band == layered.LEVEL_HIGH
    assert layered.effective_row_level(_row()) == layered.LEVEL_HIGH
    assert cap["very_high_eligibility"]["reason"] == (
        layered.INELIGIBLE_DISPERSION)
    assert cap["very_high_eligibility"]["final_level"] == layered.LEVEL_HIGH


def test_the_gate_never_lowers_a_band_below_high():
    verdict = layered.very_high_eligibility(
        layered.LEVEL_VERY_HIGH, [3.0, 3.0, 1.0, 3.0, 6.0, 2.0, 4.0],
        10.0, THRESHOLD)
    assert verdict["applicable"] is True
    assert verdict["eligible"] is False
    assert verdict["final_band"] == layered.LEVEL_HIGH


# ── Different question: layer max vs one perspective ───────────────────────

def test_row_reports_max_across_layers_and_names_the_holding_layer():
    row = _row(peer_outlier_score=1.0)
    verdict = layered.row_very_high_eligibility(row)
    assert "peer" in verdict["top_layers"]
    assert verdict["route"] == layered.ROUTE_PEER
    assert verdict["decision"] == layered.DECISION_UNDECIDED
    assert verdict["band"] == layered.LEVEL_VERY_HIGH
    assert layered.effective_row_level(row) == layered.LEVEL_VERY_HIGH


def test_layer_bands_apply_caps_but_not_the_gate():
    row = _row()
    bands, _zero, _thin = layered.row_layer_bands(row)
    assert bands["historical"] == layered.LEVEL_VERY_HIGH
    # The gate is a row-level question, applied by row_level_assessment only.
    assert layered.effective_row_level(row) == layered.LEVEL_HIGH


def test_peer_perspective_is_never_judged_by_the_history_window():
    band = qa.effective_severity(
        layered.LEVEL_VERY_HIGH, method=layered.METHOD_PEER_ZSCORE,
        peer_count=13, series=SERIES, current=5.0, perspective="all",
        threshold=THRESHOLD)
    assert band == layered.LEVEL_VERY_HIGH
    assessment = qa.eligibility_assessment(
        layered.LEVEL_VERY_HIGH, method=layered.METHOD_PEER_ZSCORE,
        peer_count=13, series=SERIES, current=5.0, perspective="all",
        threshold=THRESHOLD)
    assert assessment["route"] == layered.ROUTE_PEER
    assert assessment["decision"] == layered.DECISION_UNDECIDED


# ── Approved caps still run first, and stored stays distinguishable ────────

def test_caps_still_refuse_the_top_band_before_the_gate():
    thin = qa.effective_severity(
        layered.LEVEL_VERY_HIGH, method=layered.METHOD_PEER_ZSCORE,
        peer_count=2, perspective="all")
    assert thin == layered.LEVEL_HIGH

    flat = qa.effective_severity(
        layered.LEVEL_VERY_HIGH, stats={"std": 0.0},
        method=layered.METHOD_ZSCORE, series=[5.0] * 6, current=5.0,
        perspective="history", threshold=THRESHOLD)
    assert flat == layered.LEVEL_HIGH


def test_effective_band_is_idempotent_and_stored_band_stays_visible():
    kwargs = dict(stats={"std": 8.885, "mean": 15.57},
                  method=layered.METHOD_IQR, peer_count=13, series=SERIES,
                  current=CURRENT, perspective="history",
                  threshold=THRESHOLD)
    capped = qa.effective_severity(layered.LEVEL_VERY_HIGH, **kwargs)
    assert capped == layered.LEVEL_HIGH
    assert qa.effective_severity(capped, **kwargs) == capped

    provenance = qa.severity_cap(layered.LEVEL_VERY_HIGH, **kwargs)
    assert provenance["stored_severity"] == layered.LEVEL_VERY_HIGH
    assert provenance["severity"] == layered.LEVEL_HIGH
    assert provenance["route"] == layered.ROUTE_HISTORY
