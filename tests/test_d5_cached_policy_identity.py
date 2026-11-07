"""D5 — cached policy identity and meaningful revision detection.

A stored Quality Score now records the identity of the policy whose run
produced it. That makes a cached read attributable (``recorded``/``unknown``)
without re-resolving a policy, and without exposing raw policy values, config
row ids or read errors.

Revision detection distinguishes *identity* changes from numeric ones:

* a failed-analysis placeholder (score 0, fallback marker) becoming a genuine
  result — including a genuine **zero** — is a change and is recorded, even
  though the number is 0 in both rows;
* the reverse (genuine → placeholder) is recorded the same way;
* same numbers under a different recorded policy identity is a change;
* a genuine zero re-analysed under the same identity is NOT a change, and a
  legacy row gaining its first identity is provenance being added, not a new
  result.
"""
from __future__ import annotations

import json

from app.engine import pipeline
from app.engine.quality.scoring_audit import apply_score_update
from app.models import Hospital, Indicator, IndicatorValue, QualityScore, QualityScoreRevision

MONTH = "2026-06"
OTHER_MONTH = "2026-07"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

_UNSET = object()


def _hospital(db):
    return db.query(Hospital).first()


def _seed(db, sample_values, month=MONTH):
    hospital = _hospital(db)
    for code, value in sample_values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=indicator.id,
                                  month=month, value=value))
    db.commit()
    return hospital


def _row(db, hospital, *, score=80.0, issues="[]", digest=None, month=OTHER_MONTH):
    row = QualityScore(
        hospital_id=hospital.id, month=month, score=score,
        rule_compliance=90.0, completeness=80.0, consistency=70.0,
        outlier_penalty=0.0, issues=issues, policy_digest=digest,
    )
    db.add(row)
    db.commit()
    return row


def _revisions(db, row):
    db.expire_all()
    return (db.query(QualityScoreRevision)
            .filter_by(hospital_id=row.hospital_id, month=row.month)
            .order_by(QualityScoreRevision.id).all())


def _apply(db, row, *, score=None, issues=None, digest=_UNSET):
    changes = {}
    if score is not None:
        changes["score"] = score
    if issues is not None:
        changes["issues"] = issues
    if digest is _UNSET:
        changed = apply_score_update(db, row, None, "analysis", **changes)
    else:
        changed = apply_score_update(db, row, None, "analysis",
                                     policy_digest=digest,
                                     set_policy_identity=True, **changes)
    db.commit()
    db.expire_all()
    return changed


# ── 1. Revision detection: identity vs numbers ─────────────────────
def test_genuine_zero_to_genuine_zero_is_not_a_change(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=0.0, issues="[]", digest=DIGEST_A)

    assert _apply(db_session, row, score=0.0, issues="[]",
                  digest=DIGEST_A) is False
    assert _revisions(db_session, row) == []
    assert row.policy_digest == DIGEST_A


def test_failed_zero_to_genuine_zero_records_a_revision(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=0.0,
               issues=json.dumps([pipeline.FALLBACK_ANALYSIS_ISSUE]))

    assert _apply(db_session, row, score=0.0, issues="[]",
                  digest=DIGEST_A) is True
    revisions = _revisions(db_session, row)
    assert len(revisions) == 1
    revision = revisions[0]
    # Same NUMBER, different result: a failed 0 is not a genuine 0.
    assert revision.previous_score == 0
    assert revision.new_score == 0
    assert revision.previous_policy_digest is None
    assert revision.new_policy_digest == DIGEST_A
    assert pipeline.FALLBACK_ANALYSIS_ISSUE in revision.previous_values["issues"]


def test_genuine_zero_to_failed_zero_records_a_revision(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=0.0, issues="[]", digest=DIGEST_A)

    assert _apply(db_session, row, score=0.0,
                  issues=json.dumps([pipeline.FALLBACK_ANALYSIS_ISSUE]),
                  digest=None) is True
    assert row.policy_digest is None
    revision = _revisions(db_session, row)[0]
    assert revision.previous_score == 0 and revision.new_score == 0
    assert revision.previous_policy_digest == DIGEST_A
    assert revision.new_policy_digest is None
    assert pipeline.FALLBACK_ANALYSIS_ISSUE in revision.new_values["issues"]


def test_same_score_under_a_different_policy_records_a_revision(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=80.0, digest=DIGEST_A)

    assert _apply(db_session, row, score=80.0, issues="[]",
                  digest=DIGEST_B) is True
    revision = _revisions(db_session, row)[0]
    assert revision.previous_score == revision.new_score == 80.0
    assert revision.previous_policy_digest == DIGEST_A
    assert revision.new_policy_digest == DIGEST_B


def test_ordinary_numeric_change_keeps_its_revision_contract(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=80.0, digest=DIGEST_A)

    assert _apply(db_session, row, score=72.0, issues="[]",
                  digest=DIGEST_A) is True
    revision = _revisions(db_session, row)[0]
    assert revision.previous_score == 80.0
    assert revision.new_score == 72.0
    assert revision.previous_policy_digest == DIGEST_A
    assert revision.new_policy_digest == DIGEST_A


def test_legacy_identity_upgrade_is_provenance_not_a_result_change(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=80.0, digest=None)

    assert _apply(db_session, row, score=80.0, issues="[]",
                  digest=DIGEST_A) is False
    assert row.policy_digest == DIGEST_A
    assert _revisions(db_session, row) == []


def test_recalculation_writer_does_not_erase_the_recorded_identity(db_session):
    hospital = _hospital(db_session)
    row = _row(db_session, hospital, score=80.0, digest=DIGEST_A)

    # No policy identity is passed: a repair/recalculation writer.
    assert _apply(db_session, row, score=70.0) is True
    assert row.policy_digest == DIGEST_A
    revision = _revisions(db_session, row)[0]
    assert revision.previous_policy_digest == DIGEST_A
    assert revision.new_policy_digest == DIGEST_A


# ── 2. Cached read identity ────────────────────────────────────────
def test_fresh_analysis_records_policy_identity(db_session, sample_values):
    hospital = _seed(db_session, sample_values)

    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH,
                                        force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert result["policy_identity_status"] == pipeline.POLICY_IDENTITY_RECORDED
    assert len(result["policy_digest"]) == 64
    db_session.expire_all()
    row = db_session.query(QualityScore).filter_by(
        hospital_id=hospital.id, month=MONTH).one()
    assert row.policy_digest == result["policy_digest"]


def test_cached_read_reports_the_recorded_identity(db_session, sample_values):
    hospital = _seed(db_session, sample_values)
    fresh = pipeline.run_full_analysis(db_session, hospital.id, MONTH,
                                       force=True)
    digest = fresh["policy_digest"]

    cached = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert cached["cached"] is True
    assert cached["policy_identity_status"] == pipeline.POLICY_IDENTITY_RECORDED
    assert cached["policy_digest"] == digest
    # D1-D4 behaviour is unchanged: a cached row still carries no run snapshot.
    assert cached["policy_provenance"] is None
    assert cached["policy_provenance_status"] == pipeline.POLICY_PROVENANCE_CACHED
    # Only the digest is exposed -- no raw policy values, row ids or errors.
    assert "id" not in cached
    assert "read_error" not in json.dumps(cached, default=str)


def test_cached_legacy_row_reports_unknown_identity(db_session):
    hospital = _hospital(db_session)
    _row(db_session, hospital, score=42.0, issues="[]", digest=None,
         month=MONTH)

    cached = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert cached["cached"] is True
    assert cached["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert cached["policy_identity_status"] == pipeline.POLICY_IDENTITY_UNKNOWN
    assert cached["policy_digest"] is None


def test_cached_genuine_zero_is_still_a_success(db_session):
    hospital = _hospital(db_session)
    _row(db_session, hospital, score=0.0, issues="[]", digest=DIGEST_A,
         month=MONTH)

    cached = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert cached["cached"] is True
    assert cached["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert cached["analysis_status"] != pipeline.ANALYSIS_STATUS_FAILED
    assert cached["policy_identity_status"] == pipeline.POLICY_IDENTITY_RECORDED
    assert cached["policy_digest"] == DIGEST_A
