"""Scoring provenance: one multiplier, a recorded fingerprint, and auditable
recomputation of stored Quality Scores.

The reported defect: the outlier multiplier had a seeded 2.0 and a hidden 1.5
fallback, so a path with no AppConfig row scored differently from every path
that loaded one. These tests pin the single approved value, prove each stored
score records the configuration that produced it, and exercise the controlled
recompute (dry run -> apply -> append-only revisions).
"""
from types import SimpleNamespace

import pytest

from app.engine.quality.scoring import (
    OUTLIER_MULTIPLIER_DEFAULT,
    OUTLIER_MULTIPLIER_KEY,
    PREVIOUS_OUTLIER_MULTIPLIER,
    scoring_config_with_multiplier,
    anomaly_outlier_penalty,
    calculate_quality_score,
    combine_quality_score,
    layered_outlier_penalty,
    resolve_scoring_config,
    scoring_config_fingerprint,
)
from app.engine.quality.scoring_audit import (
    STATE_PREVIOUS_CONFIG,
    STATE_UNKNOWN,
    identify_scores,
    recompute_quality_scores,
)
from app.models import (
    AnomalyResult,
    Hospital,
    QualityScore,
    QualityScoreRevision,
    ValidationResult,
)


def _hospital(db):
    return db.query(Hospital).first()


def _anomaly(is_outlier: bool):
    """The shape calculate_quality_score reads from a classic anomaly result."""
    return SimpleNamespace(is_outlier=is_outlier, rate_name="rate",
                           z_score=3.0, indicator_code="IND")


def _seed_outliers(db, hospital, month, total=4, flagged=1):
    """Persisted classic anomaly rows: `flagged` of `total` are outliers."""
    for i in range(total):
        db.add(AnomalyResult(
            hospital_id=hospital.id,
            month=month,
            indicator_code=f"IND{i}",
            rate_name=f"rate_{i}",
            value=1.0,
            is_outlier=i < flagged,
        ))
    db.commit()


def _legacy_row(db, hospital, month, penalty, score=None):
    """A row written before provenance existed: no fingerprint."""
    row = QualityScore(
        hospital_id=hospital.id, month=month,
        rule_compliance=90.0, completeness=80.0, consistency=70.0,
        outlier_penalty=penalty,
        score=(combine_quality_score(90.0, 80.0, 70.0, penalty, {})
               if score is None else score),
        issues="[]",
    )
    db.add(row)
    db.commit()
    return row


# ── 1. One authoritative multiplier ────────────────────────────────

def test_approved_multiplier_is_the_default_with_or_without_appconfig():
    assert OUTLIER_MULTIPLIER_DEFAULT == 2.0
    assert resolve_scoring_config({})[OUTLIER_MULTIPLIER_KEY] == 2.0
    # A stored setting still wins; the fallback is no longer a second policy.
    assert resolve_scoring_config({OUTLIER_MULTIPLIER_KEY: 3})[
        OUTLIER_MULTIPLIER_KEY] == 3.0


@pytest.mark.parametrize("config", [{}, {OUTLIER_MULTIPLIER_KEY: 2.0}])
def test_both_penalty_components_apply_the_approved_multiplier(config):
    anomalies = [_anomaly(i < 1) for i in range(4)]
    layered = [SimpleNamespace(outlier_level=("HIGH" if i < 1 else "NORMAL"))
               for i in range(4)]

    # 1 flagged / 4 analysed * approved 2.0 = 50% penalty.
    assert anomaly_outlier_penalty(anomalies, config) == pytest.approx(0.5)
    assert layered_outlier_penalty(layered, config) == pytest.approx(0.5)


def test_calculate_quality_score_uses_the_approved_multiplier():
    anomalies = [_anomaly(i < 1) for i in range(4)]
    quality = calculate_quality_score([], {}, anomalies, set(), {})
    assert quality["outlier_penalty"] == pytest.approx(50.0)


def test_previous_multiplier_is_recognised_but_never_used_as_default():
    anomalies = [_anomaly(i < 1) for i in range(4)]
    assert anomaly_outlier_penalty(
        anomalies, {OUTLIER_MULTIPLIER_KEY: PREVIOUS_OUTLIER_MULTIPLIER}
    ) == pytest.approx(0.375)


# ── 2. Fingerprint generation and persistence ──────────────────────

def test_fingerprint_is_stable_across_input_shape_and_sensitive_to_every_setting():
    baseline = scoring_config_fingerprint({})
    assert baseline == scoring_config_fingerprint(resolve_scoring_config({}))
    assert len(baseline) == 16

    for changed in (
        {OUTLIER_MULTIPLIER_KEY: PREVIOUS_OUTLIER_MULTIPLIER},
        {"quality_completeness": 0.3},
        {"severity_critical": 4.0},
    ):
        assert scoring_config_fingerprint(changed) != baseline


def test_calculated_score_carries_configuration_and_fingerprint():
    quality = calculate_quality_score([], {}, [], set(), {})
    resolved = resolve_scoring_config({})
    assert quality["scoring_config"] == resolved
    assert quality["scoring_fingerprint"] == scoring_config_fingerprint(resolved)


def test_persistence_stamps_new_rows_and_revisions_existing_rows(db_session):
    from app.engine.pipeline import _save_quality_score

    hospital = _hospital(db_session)
    _legacy_row(db_session, hospital, "2026-01", penalty=40.0, score=70.0)

    anomalies = [_anomaly(i < 1) for i in range(4)]
    quality = calculate_quality_score([], {}, anomalies, set(), {})

    # Existing (legacy) row: values change and the old evidence is recorded.
    _save_quality_score(db_session, hospital.id, "2026-01", quality)
    row = db_session.query(QualityScore).filter_by(
        hospital_id=hospital.id, month="2026-01").one()
    assert row.scoring_fingerprint == quality["scoring_fingerprint"]
    assert row.scoring_config == quality["scoring_config"]

    revision = db_session.query(QualityScoreRevision).filter_by(
        hospital_id=hospital.id, month="2026-01").one()
    assert revision.action == "analysis"
    assert revision.previous_score == 70.0
    assert revision.previous_values["outlier_penalty"] == 40.0
    assert revision.previous_values["scoring_fingerprint"] is None
    assert revision.new_values["outlier_penalty"] == 50.0
    assert revision.config[OUTLIER_MULTIPLIER_KEY] == 2.0

    # Re-saving identical values adds no noise.
    _save_quality_score(db_session, hospital.id, "2026-01", quality)
    assert db_session.query(QualityScoreRevision).count() == 1

    # A brand-new row is stamped on insert.
    _save_quality_score(db_session, hospital.id, "2026-02", quality)
    fresh = db_session.query(QualityScore).filter_by(
        hospital_id=hospital.id, month="2026-02").one()
    assert fresh.scoring_fingerprint == quality["scoring_fingerprint"]


# ── 3. Identification of scores computed under an older configuration ──

def test_legacy_row_matching_approved_config_is_unknown_but_not_affected(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-03")
    # 50.0 is what the approved (2.0) multiplier produces: the row is simply
    # missing provenance, NOT wrong.
    _legacy_row(db_session, hospital, "2026-03", penalty=50.0)

    report = identify_scores(db_session)
    assert report["by_state"][STATE_UNKNOWN] == 1
    assert report["affected_count"] == 0
    assert report["recomputable_count"] == 1


def test_legacy_row_consistent_with_old_multiplier_is_identified(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-04")
    _legacy_row(db_session, hospital, "2026-04", penalty=37.5)

    report = identify_scores(db_session)
    assert report["affected_count"] == 1
    assert report["affected"][0]["state"] == STATE_UNKNOWN
    assert report["affected"][0]["expected_outlier_penalty"] == 50.0
    assert report["affected"][0]["source"] == "anomaly"


def test_row_stamped_with_the_previous_configuration_is_classified(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2027-01")
    row = _legacy_row(db_session, hospital, "2027-01", penalty=37.5)
    row.scoring_fingerprint = scoring_config_fingerprint(
        scoring_config_with_multiplier(PREVIOUS_OUTLIER_MULTIPLIER, {}))
    db_session.commit()

    report = identify_scores(db_session)
    assert report["by_state"][STATE_PREVIOUS_CONFIG] == 1
    assert report["affected_count"] == 1


def test_row_without_persisted_outlier_rows_needs_deep_recompute(db_session):
    hospital = _hospital(db_session)
    _legacy_row(db_session, hospital, "2026-05", penalty=10.0)

    report = identify_scores(db_session)
    assert report["needs_deep_recompute"] == 1
    assert report["affected_count"] == 0


def test_tolerance_absorbs_rounding_only(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-06")
    _legacy_row(db_session, hospital, "2026-06", penalty=50.05)

    assert identify_scores(db_session)["affected_count"] == 0


# ── 4. Deterministic, auditable recomputation ──────────────────────

def test_dry_run_changes_nothing_and_is_repeatable(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-07")
    _legacy_row(db_session, hospital, "2026-07", penalty=37.5)

    first = recompute_quality_scores(db_session, apply=False)
    second = recompute_quality_scores(db_session, apply=False)

    assert first == second
    assert first["apply"] is False
    assert first["changed_count"] == 1
    assert first["changes"][0]["expected_outlier_penalty"] == 50.0
    assert db_session.query(QualityScoreRevision).count() == 0
    row = db_session.query(QualityScore).filter_by(
        hospital_id=hospital.id, month="2026-07").one()
    assert row.outlier_penalty == 37.5
    assert row.scoring_fingerprint is None


def test_apply_recomputes_and_preserves_the_previous_evidence(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-08")
    row = _legacy_row(db_session, hospital, "2026-08", penalty=37.5)
    old_score = row.score

    result = recompute_quality_scores(db_session, apply=True, actor="tester")

    assert result["changed_count"] == 1
    assert result["revisions_recorded"] == 1
    db_session.refresh(row)
    assert row.outlier_penalty == 50.0
    assert row.score == combine_quality_score(
        row.rule_compliance, row.completeness, row.consistency, 50.0,
        resolve_scoring_config({}))
    assert row.scoring_fingerprint == scoring_config_fingerprint({})

    revision = db_session.query(QualityScoreRevision).one()
    assert revision.actor == "tester"
    assert revision.action == "recompute_scoring_config"
    assert revision.previous_score == old_score
    assert revision.previous_values["outlier_penalty"] == 37.5
    assert revision.new_values["outlier_penalty"] == 50.0
    assert revision.previous_fingerprint is None
    assert revision.new_fingerprint == row.scoring_fingerprint

    # A second apply is a no-op: the recompute converges deterministically.
    again = recompute_quality_scores(db_session, apply=True, actor="tester")
    assert again["changed_count"] == 0
    assert db_session.query(QualityScoreRevision).count() == 1


def test_recompute_scope_filters_by_hospital_and_month(db_session):
    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-09")
    _legacy_row(db_session, hospital, "2026-09", penalty=37.5)

    assert recompute_quality_scores(
        db_session, hospital_id=hospital.id, month_from="2026-10",
    )["changed_count"] == 0
    assert recompute_quality_scores(
        db_session, hospital_id=hospital.id, month_from="2026-09",
        month_to="2026-09",
    )["changed_count"] == 1


# ── 5. API: audit, dry-run default, revision history ───────────────

def test_admin_scoring_audit_and_recompute_endpoints(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    hospital = _hospital(db_session)
    _seed_outliers(db_session, hospital, "2026-11")
    _legacy_row(db_session, hospital, "2026-11", penalty=37.5)
    client = TestClient(app)

    audit = client.get("/admin/quality-scores/scoring-audit")
    assert audit.status_code == 200
    assert audit.json()["affected_count"] == 1
    assert audit.json()["approved_multiplier"] == 2.0

    dry = client.post("/admin/quality-scores/recompute")
    assert dry.status_code == 200
    assert dry.json()["apply"] is False
    assert dry.json()["changed_count"] == 1
    assert db_session.query(QualityScoreRevision).count() == 0

    applied = client.post("/admin/quality-scores/recompute", params={"apply": True})
    assert applied.status_code == 200
    assert applied.json()["revisions_recorded"] == 1

    history = client.get(
        f"/admin/quality-scores/{hospital.id}/2026-11/revisions")
    assert history.status_code == 200
    assert len(history.json()["revisions"]) == 1
    assert history.json()["revisions"][0]["previous_values"]["outlier_penalty"] == 37.5


def test_no_data_sentinel_rows_are_left_alone(db_session):
    """A sentinel row (no analyzable data) has no outlier rows and no evidence
    to recompute — it must be reported, never rewritten."""
    hospital = _hospital(db_session)
    db_session.add(ValidationResult(
        hospital_id=hospital.id, month="2026-12", rule_code="R001",
        rule_description="x", status="PASS", severity="HIGH", rule_type="LOGIC"))
    sentinel = QualityScore(
        hospital_id=hospital.id, month="2026-12", score=0.0,
        rule_compliance=0.0, completeness=0.0, consistency=0.0,
        outlier_penalty=0.0, issues='["No data found for this hospital/month"]')
    db_session.add(sentinel)
    db_session.commit()

    result = recompute_quality_scores(db_session, apply=True)
    assert result["changed_count"] == 0
    db_session.refresh(sentinel)
    assert sentinel.score == 0.0
    assert sentinel.scoring_fingerprint is None
