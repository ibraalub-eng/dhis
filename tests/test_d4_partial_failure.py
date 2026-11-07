"""D4 — silent partial failures are no longer silent.

Two confirmed paths used to hide a failure:

1. ``recompute_hospital_months`` swallowed every month's exception, kept
   looping, and returned a bare success count — a batch where every month blew
   up returned 0 and could be reported as a clean (if empty) run.
2. ``_compute_full_analysis`` logged a Confidence persistence failure and then
   returned a result labelled successful, with a confidence payload the
   database never accepted.

The contract pinned here:
* the batch returns a :class:`RecomputeResult` — still an ``int`` equal to the
  successful count, so every existing caller is unchanged — plus
  ``requested``/``succeeded``/``failed``/``failures`` with hospital id, month,
  stable kind and a safe reason;
* one failing month never stops the others, and a failed-analysis placeholder
  is not counted as a recompute;
* a Confidence persistence failure is reported as ``failed`` with
  ``failure_kind == "confidence_persistence_failed"``, carries no confidence
  payload, and keeps the genuine QualityScore row;
* successful persistence behaves exactly as before.
"""
from __future__ import annotations

import inspect

from app.engine import pipeline
from app.models import ConfidenceScore, Hospital, Indicator, IndicatorValue, QualityScore


def _hospital(db):
    return db.query(Hospital).first()


def _indicator(db):
    return db.query(Indicator).first()


def _seed_month(db, hospital, month, value=10.0):
    db.add(IndicatorValue(hospital_id=hospital.id,
                          indicator_id=_indicator(db).id,
                          month=month, value=value))
    db.commit()


def _ok_result(hospital_id, month):
    return {"hospital": f"H{hospital_id}", "month": month,
            "data_quality_score": 80.0, "issues": [], "outliers": [],
            "analysis_status": "ok", "failure_kind": None}


# ── 1-3: the batch contract ────────────────────────────────────────────────
def test_all_batch_months_succeed(db_session, monkeypatch):
    hospital = _hospital(db_session)
    months = ["2027-05", "2027-06", "2027-07"]
    monkeypatch.setattr(
        pipeline, "run_full_analysis",
        lambda session, hid, month, force=False, policy=None: _ok_result(hid, month))

    result = pipeline.recompute_hospital_months(db_session, hospital.id, months)

    assert isinstance(result, int)
    assert result == 3
    assert (result.requested, result.succeeded, result.failed) == (3, 3, 0)
    assert result.failures == []
    assert result.as_dict()["failures"] == []


def test_one_failing_month_does_not_stop_the_others(db_session, monkeypatch):
    hospital = _hospital(db_session)
    months = ["2027-05", "2027-06", "2027-07"]
    seen = []

    def fake(session, hid, month, force=False, policy=None):
        seen.append(month)
        if month == months[0]:
            raise RuntimeError("exploded before persisting")
        return _ok_result(hid, month)

    monkeypatch.setattr(pipeline, "run_full_analysis", fake)

    result = pipeline.recompute_hospital_months(db_session, hospital.id, months)

    # The later months were still attempted and their successes counted.
    assert seen == months
    assert result == 2
    assert (result.requested, result.succeeded, result.failed) == (3, 2, 1)
    assert [f["month"] for f in result.failures] == ["2027-05"]


def test_all_months_failing_reports_every_failure(db_session, monkeypatch):
    hospital = _hospital(db_session)
    months = ["2027-05", "2027-06", "2027-07"]

    def always_fails(session, hid, month, force=False, policy=None):
        raise RuntimeError(f"cannot analyze {month}")

    monkeypatch.setattr(pipeline, "run_full_analysis", always_fails)

    result = pipeline.recompute_hospital_months(db_session, hospital.id, months)

    assert result == 0
    assert (result.requested, result.succeeded, result.failed) == (3, 0, 3)
    assert [f["month"] for f in result.failures] == months


# ── 4: failure details identify the hospital/month, safely ────────────────
def test_failure_details_identify_hospital_month_and_reason(db_session, monkeypatch):
    hospital = _hospital(db_session)

    def fails_one(session, hid, month, force=False, policy=None):
        if month == "2027-06":
            raise RuntimeError("line one\nline two " + "x" * 800)
        return _ok_result(hid, month)

    monkeypatch.setattr(pipeline, "run_full_analysis", fails_one)

    result = pipeline.recompute_hospital_months(db_session, hospital.id,
                                                ["2027-05", "2027-06"])

    failure = result.failures[0]
    assert failure["hospital_id"] == hospital.id
    assert failure["month"] == "2027-06"
    assert failure["failure_kind"] == pipeline.FAILURE_RECOMPUTE_ERROR
    assert failure["error_type"] == "RuntimeError"
    assert "line one line two" in failure["reason"]
    assert "\n" not in failure["reason"]
    assert len(failure["reason"]) <= 300


def test_failed_analysis_placeholder_is_not_counted_as_recomputed(db_session, monkeypatch):
    """A stored fallback is a failure, not a successful recompute."""
    hospital = _hospital(db_session)

    def fallback(session, hid, month, force=False, policy=None):
        if month == "2027-07":
            return {"hospital": "H", "month": month, "data_quality_score": 0,
                    "issues": ["fallback"], "outliers": [],
                    "analysis_status": "failed",
                    "failure_kind": pipeline.FAILURE_POLICY_UNAVAILABLE}
        return _ok_result(hid, month)

    monkeypatch.setattr(pipeline, "run_full_analysis", fallback)

    result = pipeline.recompute_hospital_months(db_session, hospital.id,
                                                ["2027-06", "2027-07"])

    assert result == 1
    assert result.failed == 1
    assert result.failures[0]["month"] == "2027-07"
    assert result.failures[0]["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE


# ── 5: existing callers keep working ──────────────────────────────────────
def test_existing_callers_keep_the_integer_contract(db_session, monkeypatch):
    """Every caller inspects the return as a count; none of them changes."""
    params = list(inspect.signature(pipeline.recompute_hospital_months).parameters)
    assert params == ["session", "hospital_id", "months", "force",
                      "progress_cb", "policy"]

    hospital = _hospital(db_session)
    months = ["2027-05", "2027-06", "2027-07"]

    def one_fails(session, hid, month, force=False, policy=None):
        if month == "2027-06":
            raise RuntimeError("boom")
        return _ok_result(hid, month)

    monkeypatch.setattr(pipeline, "run_full_analysis", one_fails)
    result = pipeline.recompute_hospital_months(db_session, hospital.id, months)

    # app/api/admin.py::_run_deep_recompute
    n = result
    recomputed, failed = 0, 0
    if n is None:  # kept verbatim from the caller
        n = 0
    recomputed += n
    failed += len(months) - n
    assert (recomputed, failed) == (2, 1)
    assert failed == result.failed

    # tests/test_remove_data.py compares against a plain int
    assert result == 2
    # scripts/restore_indicator_values.py formats it directly
    assert f"{result}/{len(months)}" == "2/3"
    assert str(result) == "2"
    # arithmetic yields a plain int, which is what callers store
    assert type(result + 0) is int


# ── 6-8: confidence persistence failure vs success ────────────────────────
class _FakeConfidence:
    """A successful Confidence calculation (formulas untouched)."""

    def to_dict(self):
        return {
            "overall_confidence": 88.0,
            "level": "HIGH",
            "by_level": {"HIGH": 1, "MEDIUM": 0, "LOW": 0, "CRITICAL": 0},
            "by_group": {},
            "indicator_count": 1,
            "indicators": [{"indicator_code": "X", "confidence": 88.0,
                            "level": "HIGH"}],
            "priority_verify": [],
            "summary": "calculated",
        }


def test_confidence_persistence_failure_is_not_reported_as_success(db_session, monkeypatch):
    hospital = _hospital(db_session)
    _seed_month(db_session, hospital, "2027-10")
    monkeypatch.setattr(pipeline, "calculate_confidence",
                        lambda **kwargs: _FakeConfidence())

    def cannot_persist(*args, **kwargs):
        raise RuntimeError("confidence table unavailable")

    monkeypatch.setattr(pipeline, "_save_confidence_score", cannot_persist)

    result = pipeline.run_full_analysis(db_session, hospital.id, "2027-10",
                                        force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_CONFIDENCE_PERSISTENCE
    # The persistence failure is distinguishable from a calculation failure.
    assert result["failure_kind"] != pipeline.FAILURE_ANALYSIS_ERROR
    assert result["failure_kind"] != pipeline.FAILURE_POLICY_UNAVAILABLE
    # No false confidence-success payload is exposed.
    assert result.get("confidence") is None
    assert db_session.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital.id,
        ConfidenceScore.month == "2027-10",
    ).first() is None
    # The QualityScore fallback behavior is untouched: the genuine, computed
    # row is preserved and NOT rewritten as a failed-analysis placeholder.
    stored = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == hospital.id,
        QualityScore.month == "2027-10",
    ).first()
    assert stored is not None
    assert not pipeline.is_fallback_quality_row(stored)


def test_successful_persistence_preserves_existing_behavior(db_session, monkeypatch):
    hospital = _hospital(db_session)
    _seed_month(db_session, hospital, "2027-11")
    monkeypatch.setattr(pipeline, "calculate_confidence",
                        lambda **kwargs: _FakeConfidence())

    result = pipeline.run_full_analysis(db_session, hospital.id, "2027-11",
                                        force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert result["failure_kind"] is None
    assert result["confidence"]["overall_confidence"] == 88.0
    stored = db_session.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital.id,
        ConfidenceScore.month == "2027-11",
    ).first()
    assert stored is not None
    assert stored.overall_confidence == 88.0
    assert stored.level == "HIGH"
