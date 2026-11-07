"""P3.3.3b-Fix — a failed fallback must never be cached as a successful analysis.

The confirmed defect: a policy outage persists a score-0 fallback
``QualityScore``; after the policy recovers, the next NON-forced analysis read
that row from cache and returned ``analysis_status="ok"``,
``failure_kind=None``, ``cached=True`` — a previous failure presented as a
successful analysis.

Contract pinned here:

* a stored fallback is served back as a FAILURE (``stored_fallback``), never ok;
* the original live failure keeps its exact ``failure_kind``;
* a real (forced) analysis supersedes the fallback, and only then is the month
  cacheable again as a genuine success;
* a genuine zero-score analysis (real issues) stays cacheable;
* historical fallback rows written before the fix are recognised unchanged.
"""
from __future__ import annotations

import json

from app.engine import pipeline
from app.engine.config_resolver import PolicyUnavailable
from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    QualityScoreRevision,
)

MONTH = "2026-06"


def _seed(db, sample_values, month=MONTH):
    hospital = db.query(Hospital).first()
    for code, value in sample_values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=indicator.id,
                                  month=month, value=value))
    db.commit()
    return hospital


def _stored(db, hospital, month=MONTH):
    db.expire_all()
    return db.query(QualityScore).filter_by(
        hospital_id=hospital.id, month=month).first()


def _fail_with_policy(db, hospital, monkeypatch):
    def boom(_db, **_kwargs):
        raise PolicyUnavailable("configuration store unavailable")

    monkeypatch.setattr(pipeline, "load_policy_snapshot", boom)
    return pipeline.run_full_analysis(db, hospital.id, MONTH, force=True)


# ── the exact reported sequence ─────────────────────────────────────────────
def test_policy_failure_is_not_cached_as_success_after_recovery(
        db_session, monkeypatch, sample_values):
    hospital = _seed(db_session, sample_values)

    # 1-2: the policy outage returns a failed result with its own kind.
    failed = _fail_with_policy(db_session, hospital, monkeypatch)
    assert failed["cached"] is False
    assert failed["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert failed["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE
    assert "confidence" not in failed

    # 3: the fallback row is still persisted, and is recognisable as a failure.
    row = _stored(db_session, hospital)
    assert row is not None and row.score == 0
    assert pipeline.is_fallback_quality_row(row) is True

    # 4: the policy recovers — the real resolver is back.
    monkeypatch.undo()

    # 5-6: a non-forced call must never report that fallback as a success.
    served = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert served["cached"] is True, "the stored row is what was read"
    assert served["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert served["analysis_status"] != pipeline.ANALYSIS_STATUS_OK
    assert served["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK
    assert "confidence" not in served
    assert served["policy_provenance"] is None, (
        "a freshly resolved policy must not be attributed to a stored row")
    assert served["policy_provenance_status"] == pipeline.POLICY_PROVENANCE_CACHED

    # Reading it back never rewrites the stored failure.
    reread = _stored(db_session, hospital)
    assert reread.score == 0 and json.loads(reread.issues) == [
        pipeline.FALLBACK_ANALYSIS_ISSUE]

    # 7: a genuine analysis supersedes it, and that result IS cacheable.
    fresh = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    assert fresh["cached"] is False
    assert fresh["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert fresh["failure_kind"] is None
    assert pipeline.is_fallback_quality_row(_stored(db_session, hospital)) is False

    cached_ok = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert cached_ok["cached"] is True
    assert cached_ok["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert cached_ok["failure_kind"] is None
    assert cached_ok["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_CACHED


def test_ordinary_analysis_failure_is_not_cached_as_success_after_recovery(
        db_session, monkeypatch, sample_values):
    """An ordinary failure gets the same protection as a policy failure."""
    hospital = _seed(db_session, sample_values)
    real_compute = pipeline._compute_full_analysis

    def boom(*_args, **_kwargs):
        raise RuntimeError("ordinary analytical failure")

    monkeypatch.setattr(pipeline, "_compute_full_analysis", boom)
    failed = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    assert failed["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert failed["failure_kind"] == pipeline.FAILURE_ANALYSIS_ERROR
    assert pipeline.is_fallback_quality_row(_stored(db_session, hospital)) is True

    monkeypatch.setattr(pipeline, "_compute_full_analysis", real_compute)
    served = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert served["cached"] is True
    assert served["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert served["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK

    # Recovery still works through a real analysis.
    fresh = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    assert fresh["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert fresh["cached"] is False


# ── rows created before this fix ────────────────────────────────────────────
def test_historical_fallback_row_is_never_served_as_success(
        db_session, sample_values):
    """A pre-fix row carries only the fallback sentence and no scoring
    provenance; it must follow the same contract with no rewrite."""
    hospital = _seed(db_session, sample_values)
    db_session.add(QualityScore(
        hospital_id=hospital.id, month=MONTH, score=0,
        rule_compliance=0, completeness=0, consistency=0, outlier_penalty=0,
        issues=json.dumps([pipeline.FALLBACK_ANALYSIS_ISSUE])))
    db_session.commit()
    before = _stored(db_session, hospital).issues

    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert result["cached"] is True
    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK
    assert _stored(db_session, hospital).issues == before, (
        "historical rows are read, never rewritten")


# ── genuine zeros stay cacheable ────────────────────────────────────────────
def test_genuine_zero_score_result_remains_cacheable(db_session, sample_values):
    """A real analysis that legitimately scores 0 has real rule issues, so it
    is not a fallback and must stay eligible for the cache."""
    hospital = _seed(db_session, sample_values)
    db_session.add(QualityScore(
        hospital_id=hospital.id, month=MONTH, score=0,
        rule_compliance=0, completeness=0, consistency=0, outlier_penalty=0,
        issues=json.dumps(["R001: Total deliveries below the sum of children"])))
    db_session.commit()

    assert pipeline.is_fallback_quality_row(_stored(db_session, hospital)) is False

    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert result["cached"] is True
    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert result["failure_kind"] is None


# ── the detection contract itself ───────────────────────────────────────────
def test_fallback_identity_requires_only_the_exact_marker():
    """The marker alone identifies a fallback — never the numeric score.

    Scoring repair rewrites the score from stored evidence while leaving
    ``issues`` untouched, so gating on ``score == 0`` used to let a repaired
    fallback stop being recognised.
    """
    class Row:
        def __init__(self, score, issues):
            self.score = score
            self.issues = issues

    marker = pipeline.FALLBACK_ANALYSIS_ISSUE
    assert pipeline.is_fallback_quality_row(Row(0, json.dumps([marker]))) is True
    # A repaired fallback carries a non-zero score and must stay a fallback.
    assert pipeline.is_fallback_quality_row(Row(87.3, json.dumps([marker]))) is True
    assert pipeline.is_fallback_quality_row(Row(None, json.dumps([marker]))) is True
    # The marker is still found alongside other stored entries.
    assert pipeline.is_fallback_quality_row(
        Row(12.0, json.dumps([marker, "R001: real issue"]))) is True
    # Exactness: a longer sentence that merely contains the marker is not it.
    assert pipeline.is_fallback_quality_row(
        Row(0, json.dumps([marker + " (timeout)"]))) is False
    # Unreadable/empty/shaped issues never masquerade as a failure.
    assert pipeline.is_fallback_quality_row(Row(0, None)) is False
    assert pipeline.is_fallback_quality_row(Row(0, "")) is False
    assert pipeline.is_fallback_quality_row(Row(0, "not-json")) is False
    assert pipeline.is_fallback_quality_row(Row(0, json.dumps(marker))) is False
    assert pipeline.is_fallback_quality_row(
        Row(0, json.dumps({"issues": [marker]}))) is False
    # Real analysis text is never a fallback, whatever the score.
    assert pipeline.is_fallback_quality_row(
        Row(0, json.dumps(["R001: Total deliveries below the sum of children"]))
    ) is False
    assert pipeline.is_fallback_quality_row(None) is False


def test_recomputed_fallback_never_becomes_a_cached_success(
        db_session, monkeypatch, sample_values):
    """A repair that raises the stored score cannot resurrect the failure.

    ``recompute_quality_scores(apply=True)`` calls ``apply_score_update`` with
    the new numbers and never touches ``issues``, so the marker survives and
    the row stays a stored fallback for every later cache read.
    """
    from app.engine.quality.scoring_audit import apply_score_update

    hospital = _seed(db_session, sample_values)
    failed = _fail_with_policy(db_session, hospital, monkeypatch)
    assert failed["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    row = _stored(db_session, hospital)
    assert row.score == 0
    assert pipeline.is_fallback_quality_row(row) is True

    monkeypatch.undo()

    # Simulate the repair exactly: same helper, same action, numbers change.
    apply_score_update(db_session, row, {}, "recompute_scoring_config",
                       score=42.5, outlier_penalty=0.0)
    db_session.commit()

    repaired = _stored(db_session, hospital)
    assert repaired.score == 42.5
    assert json.loads(repaired.issues) == [pipeline.FALLBACK_ANALYSIS_ISSUE]
    assert repaired.scoring_fingerprint is not None
    assert pipeline.is_fallback_quality_row(repaired) is True

    served = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert served["cached"] is True
    assert served["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert served["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK


def test_failure_marker_is_single_sourced():
    """The persisted marker is a constant, not a literal sprinkled per site."""
    import inspect

    source = inspect.getsource(pipeline._analysis_failure_result)
    assert "[FALLBACK_ANALYSIS_ISSUE]" in source
    assert '"Analysis failed during report generation"' not in source


# ── session safety ──────────────────────────────────────────────────────────
def test_session_stays_usable_and_the_cache_read_does_not_write(
        db_session, monkeypatch, sample_values):
    hospital = _seed(db_session, sample_values)
    _fail_with_policy(db_session, hospital, monkeypatch)
    monkeypatch.undo()

    before = _stored(db_session, hospital)
    snapshot = (before.id, before.score, before.issues)

    pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    after = _stored(db_session, hospital)
    assert (after.id, after.score, after.issues) == snapshot
    # The session remained usable for the next hospital/month.
    assert db_session.query(Hospital).count() >= 1


def test_failed_run_over_an_existing_success_persists_the_fallback(
        db_session, monkeypatch, sample_values):
    """A failure AFTER a completed analysis must still leave the marker.

    Otherwise the previous successful row would outlive a failed run and the
    very next non-forced call would report it as ``ok`` again.
    """
    hospital = _seed(db_session, sample_values)
    good = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    assert good["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert pipeline.is_fallback_quality_row(_stored(db_session, hospital)) is False

    failed = _fail_with_policy(db_session, hospital, monkeypatch)
    assert failed["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED

    row = _stored(db_session, hospital)
    assert row.score == 0
    assert pipeline.is_fallback_quality_row(row) is True
    # The marker replaces the previous issues wholesale — no duplication.
    assert json.loads(row.issues) == [pipeline.FALLBACK_ANALYSIS_ISSUE]
    # A fallback is not a scoring event: it must not claim a scoring config.
    assert row.scoring_fingerprint is None and row.scoring_config is None

    monkeypatch.undo()
    served = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert served["cached"] is True
    assert served["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert served["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK


def test_failure_over_existing_success_records_one_revision_with_prior_provenance(
        db_session, monkeypatch, sample_values):
    """The overwrite is only acceptable because the revision keeps the old row.

    A failed run replaces a genuine score (see the test above), so the ONE
    record of what the month used to be is the ``QualityScoreRevision`` written
    before the numbers change. This pins that record end-to-end: the previous
    score and all four components, the previous scoring fingerprint/config and
    the previous policy digest; and a new state that is an identifiable
    fallback carrying no scoring provenance of its own.
    """
    hospital = _seed(db_session, sample_values)
    good = pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)
    assert good["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert good["cached"] is False

    before = _stored(db_session, hospital)
    previous = {
        "score": before.score,
        "rule_compliance": before.rule_compliance,
        "completeness": before.completeness,
        "consistency": before.consistency,
        "outlier_penalty": before.outlier_penalty,
        "scoring_fingerprint": before.scoring_fingerprint,
        "scoring_config": before.scoring_config,
        "policy_digest": before.policy_digest,
    }
    # The genuine result really did carry provenance — otherwise preserving it
    # in the revision would prove nothing.
    assert previous["scoring_fingerprint"] is not None
    assert isinstance(previous["scoring_config"], dict)
    assert previous["policy_digest"] is not None
    assert pipeline.is_fallback_quality_row(before) is False

    failed = _fail_with_policy(db_session, hospital, monkeypatch)
    assert failed["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert failed["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE
    assert failed["cached"] is False

    # The current row is the fallback, with no scoring provenance left on it.
    row = _stored(db_session, hospital)
    assert pipeline.is_fallback_quality_row(row) is True
    assert row.score == 0
    assert row.scoring_fingerprint is None
    assert row.scoring_config is None
    assert row.policy_digest is None

    revisions = (db_session.query(QualityScoreRevision)
                 .filter_by(hospital_id=hospital.id, month=MONTH)
                 .order_by(QualityScoreRevision.id).all())
    assert len(revisions) == 1, "exactly one revision for the overwrite"
    revision = revisions[0]
    assert revision.action == "analysis"
    assert revision.actor == "system"

    # Previous state is preserved verbatim.
    assert revision.previous_score == previous["score"]
    assert revision.previous_values["score"] == previous["score"]
    for component in ("rule_compliance", "completeness", "consistency",
                      "outlier_penalty"):
        assert revision.previous_values[component] == previous[component]
        assert revision.new_values[component] == 0
    assert revision.previous_fingerprint == previous["scoring_fingerprint"]
    assert revision.previous_values["scoring_fingerprint"] == \
        previous["scoring_fingerprint"]
    assert revision.previous_values["scoring_config"] == \
        previous["scoring_config"]
    assert revision.previous_policy_digest == previous["policy_digest"]
    assert revision.previous_values["policy_digest"] == \
        previous["policy_digest"]
    # The replaced state was a genuine result, not a previous fallback.
    assert pipeline.FALLBACK_ANALYSIS_ISSUE not in \
        (revision.previous_values["issues"] or "")

    # New state: an identified fallback with no scoring provenance.
    assert revision.new_score == 0
    assert revision.new_fingerprint is None
    assert revision.new_values["scoring_fingerprint"] is None
    assert revision.new_values["scoring_config"] is None
    assert revision.config is None
    assert revision.new_policy_digest is None
    assert revision.new_values["policy_digest"] is None
    assert json.loads(revision.new_values["issues"]) == [
        pipeline.FALLBACK_ANALYSIS_ISSUE]

    # Serving the stored fallback back must not append a second revision.
    monkeypatch.undo()
    served = pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert served["cached"] is True
    assert served["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert served["failure_kind"] == pipeline.FAILURE_STORED_FALLBACK
    assert db_session.query(QualityScoreRevision).filter_by(
        hospital_id=hospital.id, month=MONTH).count() == 1
