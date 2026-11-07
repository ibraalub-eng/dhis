"""Quality Score consumes the canonical layered severity (Phase 5).

The layered engine is the sole author of a finding's band. The Quality Score
must therefore count the EFFECTIVE band (caps and top-band gate included), and
the Why popup must explain the very same band — a stored VERY_HIGH that the
policy lowered to HIGH may never be reported as if VERY_HIGH had been scored,
and a month with no stored layered rows is missing evidence, not a clean result.

Scoring mathematics is untouched: the four weights, the formula and the
eligibility denominator are asserted here so later work cannot move them.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine.anomaly.layered import effective_severity
from app.engine.audit.explain import _layered_evidence_status, _outliers_behind_score
from app.engine.quality.scoring import (
    FLAGGED_LEVELS,
    OUTLIER_MULTIPLIER_DEFAULT,
    _calc_layered_outlier_penalty,
    combine_quality_score,
    layered_severity,
    quality_weights,
    resolve_scoring_config,
    scoring_config_fingerprint,
)
from app.engine.quality.scoring_audit import _is_fallback, score_snapshot
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)

MONTH = "2027-05"
ELIGIBLE = {f"E{i}" for i in range(10)}


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def hospital(db_session):
    return db_session.query(Hospital).order_by(Hospital.id).first()


def _row(db, hospital_id, code, month=MONTH, **overrides):
    fields = dict(
        hospital_id=hospital_id, month=month, analysis_code=code,
        outlier_level="VERY_HIGH",
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def _quality(db, hospital_id, penalty=0.0, month=MONTH, **overrides):
    fields = dict(hospital_id=hospital_id, month=month, score=70.0,
                  rule_compliance=90.0, completeness=80.0,
                  consistency=85.0, outlier_penalty=penalty)
    fields.update(overrides)
    score = QualityScore(**fields)
    db.add(score)
    db.commit()
    return score


# ── 1. The penalty counts the canonical band ──────────────────────────────

def test_penalty_consumes_the_effective_band_not_the_stored_level(db_session, hospital):
    # Stored VERY_HIGH, but its only measured layer scores a MODERATE band:
    # the policy no longer supports a top-band finding.
    _row(db_session, hospital.id, "derated", historical_outlier_score=0.55)
    # Stored VERY_HIGH, and a measured peer layer still holds it.
    _row(db_session, hospital.id, "held", peer_outlier_score=0.95,
         peer_count=5,
         peer_provenance={"group": "all_active_reporting",
                          "values": {"1": 10.0, "2": 12.0, "3": 14.0,
                                     "4": 16.0, "5": 18.0}})

    rows = db_session.query(LayeredOutlierResult).all()
    levels = {r.analysis_code: layered_severity(r)["level"] for r in rows}
    assert levels == {"derated": "MODERATE", "held": "VERY_HIGH"}

    penalty = _calc_layered_outlier_penalty(
        rows, {"outlier_multiplier": OUTLIER_MULTIPLIER_DEFAULT},
        eligible_codes=ELIGIBLE)
    # One finding / ten eligible units * the approved multiplier 2.0.
    assert penalty == pytest.approx(1 / 10 * OUTLIER_MULTIPLIER_DEFAULT)
    # A stored-level count would have returned two findings.
    assert sum(1 for r in rows if r.outlier_level in FLAGGED_LEVELS) == 2


# ── 2. Explanation severity == scoring severity ───────────────────────────

def test_explanation_lists_exactly_the_rows_the_penalty_counts(db_session, hospital):
    _row(db_session, hospital.id, "derated", historical_outlier_score=0.55)
    _row(db_session, hospital.id, "held", peer_outlier_score=0.95,
         peer_count=5,
         peer_provenance={"group": "all_active_reporting",
                          "values": {"1": 10.0, "2": 12.0, "3": 14.0,
                                     "4": 16.0, "5": 18.0}})

    drivers = _outliers_behind_score(db_session, hospital.id, MONTH)
    scored = [r for r in db_session.query(LayeredOutlierResult).all()
              if layered_severity(r)["level"] in FLAGGED_LEVELS]
    assert {d["indicator_code"] for d in drivers} == \
        {r.analysis_code for r in scored} == {"held"}
    assert drivers[0]["level"] == layered_severity(scored[0])["level"]


# ── 3. Stored and effective severity both preserved ───────────────────────

def test_stored_and_effective_levels_are_both_kept_when_they_differ(db_session, hospital):
    row = _row(db_session, hospital.id, "thin", peer_outlier_score=0.95,
               peer_count=3, peer_mean=10.0,
               peer_provenance={"group": "all_active_reporting",
                                "values": {"1": 9.0, "2": 10.0, "3": 11.0}})

    grade = layered_severity(row)
    assert grade["stored_level"] == "VERY_HIGH"
    assert grade["level"] == "HIGH"
    assert grade["capped"] is True
    assert grade["evidence_status"] == "canonical_layered"

    driver = _outliers_behind_score(db_session, hospital.id, MONTH)[0]
    assert driver["level"] == driver["effective_level"] == "HIGH"
    assert driver["stored_level"] == "VERY_HIGH"
    assert driver["capped"] is True
    assert driver["cap"]
    assert driver["layered_result_id"] == row.id
    # The finding is still a finding: HIGH stays in the scored band.
    assert "HIGH" in FLAGGED_LEVELS
    assert _calc_layered_outlier_penalty(
        [row], {}, eligible_codes=ELIGIBLE) == pytest.approx(
            1 / 10 * OUTLIER_MULTIPLIER_DEFAULT)


# ── 4. Zero-spread cap ────────────────────────────────────────────────────

def test_zero_spread_cap_is_used_consistently(db_session, hospital):
    row = _row(db_session, hospital.id, "flat", peer_outlier_score=0.95,
               peer_count=6,
               peer_provenance={"group": "all_active_reporting",
                                "values": {str(i): 40.0 for i in range(6)}})

    grade = layered_severity(row)
    assert grade["stored_level"] == "VERY_HIGH"
    assert grade["level"] == "HIGH"
    driver = _outliers_behind_score(db_session, hospital.id, MONTH)[0]
    assert driver["level"] == "HIGH"
    assert driver["stored_level"] == "VERY_HIGH"
    assert driver["cap_policy"]


# ── 5. Thin-peer cap ──────────────────────────────────────────────────────

def test_thin_peer_cap_is_used_consistently(db_session, hospital):
    row = _row(db_session, hospital.id, "thin2", peer_outlier_score=0.97,
               peer_count=3,
               peer_provenance={"group": "all_active_reporting",
                                "values": {"1": 8.0, "2": 9.0, "3": 10.0}})
    grade = layered_severity(row)
    assert grade["level"] == "HIGH"
    assert grade["stored_level"] == "VERY_HIGH"
    assert _calc_layered_outlier_penalty(
        [row], {}, eligible_codes=ELIGIBLE) == pytest.approx(
            1 / 10 * OUTLIER_MULTIPLIER_DEFAULT)


# ── 6. Top-band gate ──────────────────────────────────────────────────────

def test_top_band_gate_is_used_consistently(db_session, hospital):
    # A stored VERY_HIGH resting on own history, with a window that shows no
    # top-band dispersion and a current value sitting on the mean.
    row = _row(db_session, hospital.id, "gate", raw_value=10.05,
               historical_outlier_score=0.95,
               outlier_method="zscore",
               history_provenance={"values": [8.0, 10.0, 12.0, 10.0]},
               classification_provenance={"zscore_threshold": 2.5})

    grade = effective_severity(row)
    assert grade["stored_level"] == "VERY_HIGH"
    assert grade["level"] == "HIGH"
    assert grade["capped"] is True

    driver = _outliers_behind_score(db_session, hospital.id, MONTH)[0]
    assert driver["level"] == grade["level"] == "HIGH"
    assert driver["stored_level"] == "VERY_HIGH"


# ── 7. Missing layered evidence is not a clean month ──────────────────────

def test_missing_layered_evidence_is_reported_as_missing(client, db_session, hospital):
    indicator = db_session.query(Indicator).filter(Indicator.code == "2").one()
    db_session.add(IndicatorValue(hospital_id=hospital.id, month=MONTH,
                                  indicator_id=indicator.id, value=100))
    _quality(db_session, hospital.id, penalty=0.0)
    db_session.commit()

    status = _layered_evidence_status(db_session, hospital.id, MONTH)
    assert status["status"] == "missing_layered_result"
    assert status["rows"] == 0
    assert _outliers_behind_score(db_session, hospital.id, MONTH) == []

    payload = client.get(
        "/audit/explain",
        params={"kind": "quality_score", "hospital_id": hospital.id,
                "month": MONTH, "component": "outlier_score"},
    ).json()
    assert payload["evidence_status"] == "missing_layered_result"
    assert "missing" in payload["why"]
    assert "No indicator reached" not in payload["why"]


# ── 8. Scoring weights and formula unchanged ──────────────────────────────

def test_weights_and_formula_are_unchanged():
    assert quality_weights({}) == {
        "rule_compliance": 0.35, "completeness": 0.25,
        "consistency": 0.25, "outlier_penalty": 0.15,
    }
    assert resolve_scoring_config({})["outlier_multiplier"] == \
        OUTLIER_MULTIPLIER_DEFAULT == 2.0
    # 90*.35 + 80*.25 + 70*.25 + (100-10)*.15
    assert combine_quality_score(90, 80, 70, 10, {}) == pytest.approx(82.5)
    assert combine_quality_score(100, 100, 100, 0, {}) == pytest.approx(100.0)


# ── 9. D5 policy digest and revision snapshots unchanged ──────────────────

def test_d5_policy_identity_and_revision_snapshot_unchanged(db_session, hospital):
    first = scoring_config_fingerprint({})
    second = scoring_config_fingerprint(resolve_scoring_config({}))
    assert first == second and len(first) == 16

    row = _quality(db_session, hospital.id, penalty=12.0, policy_digest="d5-abc")
    snapshot = score_snapshot(row)
    assert snapshot["policy_digest"] == "d5-abc"
    assert snapshot["outlier_penalty"] == 12.0
    assert set(snapshot) == {
        "score", "rule_compliance", "completeness", "consistency",
        "outlier_penalty", "issues", "scoring_fingerprint", "scoring_config",
        "policy_digest",
    }


# ── 10. Genuine zero vs failed fallback ───────────────────────────────────

def test_genuine_zero_and_failed_fallback_remain_distinguishable():
    from app.engine.pipeline import FALLBACK_ANALYSIS_ISSUE

    assert _is_fallback([FALLBACK_ANALYSIS_ISSUE]) is True
    assert _is_fallback(None) is False
    assert _is_fallback(["Anomaly: rate_cs (HIGH)"]) is False

    # A real month with nothing flagged scores a genuine zero penalty and
    # raises no issue; it is not a fallback row.
    assert _calc_layered_outlier_penalty(
        [], {}, eligible_codes=ELIGIBLE) == 0.0


# ── API: the popup exposes both bands and the source row ──────────────────

def test_outlier_component_api_exposes_both_bands(client, db_session, hospital):
    indicator = db_session.query(Indicator).filter(Indicator.code == "2").one()
    db_session.add(IndicatorValue(hospital_id=hospital.id, month=MONTH,
                                  indicator_id=indicator.id, value=100))
    row = _row(db_session, hospital.id, "thin_api", peer_outlier_score=0.95,
               peer_count=3,
               peer_provenance={"group": "all_active_reporting",
                                "values": {"1": 9.0, "2": 10.0, "3": 11.0}})
    _quality(db_session, hospital.id, penalty=20.0)
    db_session.commit()

    payload = client.get(
        "/audit/explain",
        params={"kind": "quality_score", "hospital_id": hospital.id,
                "month": MONTH, "component": "outlier_score"},
    ).json()
    assert payload["evidence_status"] == "canonical_layered"
    driver = payload["outliers"][0]
    assert driver["layered_result_id"] == row.id
    assert driver["effective_level"] == "HIGH"
    assert driver["stored_level"] == "VERY_HIGH"
    assert driver["capped"] is True
    assert driver["evidence_status"] == "canonical_layered"
