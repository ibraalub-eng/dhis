"""Insufficient-history classification policy (Anomaly Diagnostics).

Reported defect: a hospital/month whose own-history baseline was not evaluable
was classified NORMAL/NONE, so a strong peer deviation was silently discarded
(Hospital 22, February 2026: several rows scored HIGH against peers and were
still stored as NORMAL).

Approved policy under test:

* rule 1 — history insufficient and peer band below HIGH
  -> ``INSUFFICIENT_HISTORY`` at level NONE (assessment withheld, not normal);
* rule 11 — history insufficient and peer band HIGH/VERY_HIGH
  -> ``PEER_ANOMALY`` at the peer band (the peer evidence is the finding);
* the stored peer score, historical score (NULL here) and methods survive.

Existing severity bands are untouched: a peer score is never promoted above
its own band.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.classify import (
    TYPE_HISTORICAL_ANOMALY,
    TYPE_INSUFFICIENT_HISTORY,
    TYPE_NORMAL,
    TYPE_PEER_ANOMALY,
    classify_layered,
)
from app.engine.anomaly.layered import (
    METHOD_INSUFFICIENT_HISTORY,
    METHOD_PEER_ZSCORE,
    AnalysisSpec,
    Thresholds,
    analyze_layered_entry,
    is_detection_outlier,
    level_for_score,
    run_layered_analysis,
)
from app.models import Hospital, LayeredOutlierResult, QualityAlert

CURRENT = "2026-02"


def _rate_spec() -> AnalysisSpec:
    return AnalysisSpec(
        analysis_code="rate_cs", name="C-section rate", indicator_type="rate",
        numerator_codes=("5",), denominator_codes=("2",), rate_multiplier=100.0,
        unit="%",
    )


def _classify(**kw):
    defaults = dict(spec=_rate_spec(), raw_score=None, rate_score=None,
                    hist_score=None, volume_score=None, peer_score=None,
                    den_ok=True, history_ok=False)
    defaults.update(kw)
    return classify_layered(**defaults)


# ── 1. Insufficient history + strong peer evidence ────────────────────────

def test_insufficient_history_with_high_peer_score_is_a_peer_anomaly():
    c = _classify(peer_score=0.8553462646447416)
    assert c.rule_number == 11
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.outlier_level == "HIGH"          # the peer band, not promoted
    assert c.method == METHOD_PEER_ZSCORE
    assert c.investigation_required is True
    assert c.investigation_route == "contextual"
    assert "own baseline is not assessable" in c.interpretation
    assert "peer comparison HIGH" in c.interpretation
    assert "not a confirmed normal result" not in c.interpretation


def test_peer_band_is_preserved_never_promoted():
    high = _classify(peer_score=0.76)          # HIGH band (0.75-0.90)
    very_high = _classify(peer_score=0.95)     # VERY_HIGH band
    assert high.outlier_type == TYPE_PEER_ANOMALY
    assert high.outlier_level == "HIGH"
    assert very_high.outlier_type == TYPE_PEER_ANOMALY
    assert very_high.outlier_level == "VERY_HIGH"


# ── 2. Insufficient history with no meaningful peer evidence ──────────────

def test_insufficient_history_without_peer_evidence_is_withheld_not_normal():
    c = _classify(peer_score=None)
    assert c.rule_number == 1
    assert c.outlier_type == TYPE_INSUFFICIENT_HISTORY
    assert c.outlier_level == "NONE"
    assert c.method == METHOD_INSUFFICIENT_HISTORY
    assert c.investigation_required is False
    assert c.investigation_route == "none"
    assert not is_detection_outlier(c.outlier_level)
    assert "not a confirmed normal result" in c.interpretation
    assert "peer comparison unavailable" in c.interpretation


def test_insufficient_history_moderate_peer_evidence_stays_withheld():
    """MODERATE is real evidence but not enough to classify (rules 6/7
    require HIGH); the score stays stored for the layer strip."""
    spec = _rate_spec()
    history = {"2026-01": {"5": 10, "2": 100}, CURRENT: {"5": 25, "2": 100}}
    # Peer mean 9.0, sample sd 5.0 → z = 3.2 → peer score 0.64 (MODERATE).
    peers = [("all", {2: 4.0, 3: 4.0, 4: 9.0, 5: 14.0, 6: 14.0})]
    result = analyze_layered_entry(spec, history, CURRENT, peers,
                                   Thresholds(), self_id=1)
    assert result.history_ok is False
    assert 0.25 <= result.peer.score < 0.75    # MODERATE band
    assert result.classification.outlier_type == TYPE_INSUFFICIENT_HISTORY
    assert result.classification.outlier_level == "NONE"
    assert result.classification.method == METHOD_INSUFFICIENT_HISTORY
    assert "below the HIGH threshold" in result.classification.interpretation


# ── 3. Sufficient history, normal result ──────────────────────────────────

def test_sufficient_history_normal_result_stays_normal():
    c = _classify(history_ok=True, raw_score=0.10, rate_score=0.10,
                  hist_score=0.10, volume_score=0.10, peer_score=0.10)
    assert c.rule_number == 10
    assert c.outlier_type == TYPE_NORMAL
    assert c.outlier_level == "NONE"
    assert c.interpretation.startswith("No layer exceeded its threshold")
    assert c.outlier_type != TYPE_INSUFFICIENT_HISTORY


# ── 4. Conflicting historical and peer evidence ───────────────────────────

def test_history_high_with_quiet_peers_stays_historical_anomaly():
    c = _classify(history_ok=True, raw_score=0.60, rate_score=0.60,
                  hist_score=0.95, volume_score=0.0, peer_score=0.10)
    assert c.rule_number == 5
    assert c.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert c.outlier_level == "VERY_HIGH"
    assert "peers do not share this deviation" in c.interpretation


def test_peer_high_with_quiet_history_names_both_sides():
    c = _classify(history_ok=True, raw_score=0.10, rate_score=0.10,
                  hist_score=0.10, volume_score=0.0, peer_score=0.95)
    assert c.rule_number == 6
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.outlier_level == "VERY_HIGH"
    assert "no deviation from its own baseline" in c.interpretation


def test_both_sources_high_is_one_confirmed_historical_anomaly():
    c = _classify(history_ok=True, raw_score=0.60, rate_score=0.60,
                  hist_score=0.95, volume_score=0.0, peer_score=0.95)
    assert c.rule_number == 5                     # rule-table precedence
    assert c.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert "peer comparison also VERY_HIGH" in c.interpretation


# ── 5. Regression: Hospital 22 / February 2026 ────────────────────────────

def test_hospital_22_february_2026_keeps_strong_peer_evidence():
    """One prior month (history not evaluable) and a stillbirth rate ~27.5 per
    1,000 against a peer mean of 3.0 — the stored row used to say NORMAL/NONE
    while Quality Alerts reported HIGH/VERY_HIGH for the same month."""
    spec = AnalysisSpec(
        analysis_code="rate_stillbirth", name="Stillbirth rate",
        indicator_type="rate", numerator_codes=("7",),
        denominator_codes=("6",), rate_multiplier=1000.0, unit="per 1,000",
    )
    history = {"2026-01": {"7": 2, "6": 109}, CURRENT: {"7": 3, "6": 109}}
    # 12 peers: eleven at 1.268 / 1,000 and one at 22.05 / 1,000 → mean 3.0,
    # sample sd 6.0 → z ≈ 4.09 → peer score ≈ 0.82 (HIGH).
    peer_values = {hid: {CURRENT: {"7": 1.268, "6": 1000.0}}
                   for hid in range(2, 14)}
    peer_values[14] = {CURRENT: {"7": 22.05, "6": 1000.0}}

    result = run_layered_analysis([spec], history, CURRENT, 1, peer_values, {},
                                  Thresholds())[0]

    assert result.history_ok is False
    assert result.classification.rule_number == 11
    assert result.classification.outlier_type == TYPE_PEER_ANOMALY
    assert result.classification.outlier_level == "HIGH"
    assert result.classification.outlier_level == level_for_score(result.peer.score)
    assert result.classification.method == METHOD_PEER_ZSCORE
    # Unavailable history is stored as NULL, never as a reassuring 0.0.
    assert result.historical.score is None
    assert result.classification.interpretation.startswith("Not enough history")
    assert "peer average" in result.classification.interpretation

    # Without the peer group the same month is an assessment withheld — the
    # old NORMAL label was the defect.
    alone = run_layered_analysis([spec], history, CURRENT, 1,
                                 {1: history}, {}, Thresholds())[0]
    assert alone.classification.outlier_type == TYPE_INSUFFICIENT_HISTORY
    assert alone.classification.outlier_level == "NONE"


# ── 6. Stored rows and Quality Alerts stay consistent ─────────────────────

@pytest.fixture
def client(app):
    return TestClient(app)


def test_stored_row_filter_summary_and_quality_alert_cross_check(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    row = LayeredOutlierResult(
        hospital_id=hospital.id, analysis_code="rate_cs", month="2027-09",
        raw_value=25.0, previous_value=10.0, denominator=100.0, rate=25.0,
        historical_mean=None, historical_outlier_score=None,
        peer_outlier_score=0.10, peer_mean=26.0, peer_count=10,
        outlier_level="NONE", outlier_type=TYPE_INSUFFICIENT_HISTORY,
        outlier_method=METHOD_INSUFFICIENT_HISTORY,
        interpretation="Not enough history: needs at least 3 prior months.",
        investigation_required=False, investigation_route="none",
    )
    db_session.add(row)
    db_session.add(QualityAlert(
        hospital_id=hospital.id, month="2027-09", perspective="governorate",
        indicator_code="rate_cs", indicator_name="C-section rate",
        method="peer_zscore", severity="VERY_HIGH", score=1.0,
        peer_count=4, current_value=25.0, baseline_value=4.0,
        evidence={
            "canonical": {"key": "test-key", "code": "rate_cs",
                          "registered_codes": ["rate_cs"]},
            "comparison_policy": {"perspective_scope": "stratified"},
        },
    ))
    db_session.commit()

    listed = client.get("/analysis/layered?classification=INSUFFICIENT_HISTORY")
    assert listed.status_code == 200, listed.text
    assert [r["analysis_code"] for r in listed.json()["data"]] == ["rate_cs"]

    summary = client.get("/analysis/layered/summary?month=2027-09").json()
    assert {"outlier_type": TYPE_INSUFFICIENT_HISTORY, "count": 1} in \
        summary["by_classification"]

    explained = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={hospital.id}"
        "&month=2027-09&indicator_code=rate_cs"
    )
    assert explained.status_code == 200, explained.text
    payload = explained.json()
    assert payload["classification"] == TYPE_INSUFFICIENT_HISTORY
    # The stored row is reproducible under the current policy (no evaluable
    # history, peer band below HIGH).
    assert payload["reproduce"]["history_ok"] is False
    assert payload["reproduce"]["verified"] is True
    cross = payload["cross_check"]
    assert cross["agreement"] == "differs_by_perspective"
    assert cross["perspectives"][0]["perspective"] == "governorate"
    assert cross["perspectives"][0]["scope"] == "stratified"
    assert "stratified comparison" in cross["explanation"]
    # The diagnostic never claims the peer evidence is absent.
    assert cross["diagnostic"]["peer_score"] == pytest.approx(0.10)
    assert "Quality Alerts reports VERY_HIGH" in payload["why"]
