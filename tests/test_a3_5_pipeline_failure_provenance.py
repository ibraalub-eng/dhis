"""P3.3.3b — pipeline policy-failure and provenance contract.

These tests pin the boundary between a policy outage and an ordinary analytical
failure, prove that failed runs never carry a normal Confidence payload, and
record the exact snapshot used by a successful calculation. The cached-report
tests also document the current cache decision: cache ordering is unchanged,
so a cached row is labelled as having unavailable policy provenance rather than
receiving a freshly resolved policy.
"""
from __future__ import annotations

from app.engine import pipeline
from app.engine.confidence_policy import WEIGHT_KEYS
from app.engine.config_resolver import PolicyUnavailable, resolve_policy
from app.models import Hospital, Indicator, IndicatorValue, QualityScore

MONTH = "2026-06"
WEIGHT_PREFIX = "confidence.weight."


def _seed_month(db, sample_values, month=MONTH):
    hospital = db.query(Hospital).first()
    for code, value in sample_values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=indicator.id,
                                  month=month, value=value))
    db.commit()
    return hospital


def _assert_no_confidence(result):
    assert "confidence" not in result
    assert result.get("confidence") is None


# ── policy failures are distinct and machine-readable ────────────────────────
def test_policy_unavailable_has_a_machine_readable_failure(
        db_session, monkeypatch, sample_values):
    hospital = _seed_month(db_session, sample_values)

    def boom(_db, **_kwargs):
        raise PolicyUnavailable("connection detail that must not leak")

    monkeypatch.setattr(pipeline, "load_policy_snapshot", boom)

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE
    assert result["policy_provenance"] is None
    assert result["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_UNAVAILABLE
    assert result["data_quality_score"] == 0
    _assert_no_confidence(result)
    assert "connection detail" not in repr(result)

    # Existing fallback persistence remains in force, and the session is safe
    # for the next hospital/month after the rollback.
    stored = db_session.query(QualityScore).filter_by(
        hospital_id=hospital.id, month=MONTH).first()
    assert stored is not None and stored.score == 0
    assert db_session.query(Hospital).count() >= 1


def test_invalid_confidence_policy_has_a_distinct_failure(
        db_session, monkeypatch, sample_values):
    hospital = _seed_month(db_session, sample_values)
    invalid = resolve_policy({"confidence_high": -5.0}, {})
    assert invalid.confidence_policy is None

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True, policy=invalid)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_CONFIDENCE_POLICY_INVALID
    assert result["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_AVAILABLE
    assert result["policy_provenance"]["validation_status"] == "invalid"
    assert "read_error" not in result["policy_provenance"]
    assert result["data_quality_score"] == 0
    _assert_no_confidence(result)


def test_ordinary_analysis_failure_is_not_reported_as_a_policy_failure(
        db_session, monkeypatch, sample_values):
    hospital = _seed_month(db_session, sample_values)

    def boom(*_args, **_kwargs):
        raise RuntimeError("ordinary analytical failure")

    monkeypatch.setattr(pipeline, "_compute_full_analysis", boom)

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_ANALYSIS_ERROR
    assert result["failure_kind"] not in {
        pipeline.FAILURE_POLICY_UNAVAILABLE,
        pipeline.FAILURE_CONFIDENCE_POLICY_INVALID,
    }
    assert result["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_AVAILABLE
    _assert_no_confidence(result)


# ── provenance for successful policy-backed calculations ─────────────────────
def test_successful_run_exposes_the_snapshot_that_was_used(
        db_session, monkeypatch, sample_values):
    hospital = _seed_month(db_session, sample_values)
    resolved = []
    real_load = pipeline.load_policy_snapshot

    def counting(db, **kwargs):
        snapshot = real_load(db, **kwargs)
        resolved.append(snapshot)
        return snapshot

    monkeypatch.setattr(pipeline, "load_policy_snapshot", counting)

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert result["failure_kind"] is None
    assert result["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_AVAILABLE
    assert "confidence" in result
    assert len(resolved) == 1, "success resolved more than one snapshot"

    provenance = result["policy_provenance"]
    snapshot = resolved[0]
    assert provenance["digest"] == snapshot.digest
    assert provenance["resolver_version"] == snapshot.resolver_version
    assert provenance["confidence_policy_version"] == \
        snapshot.component_versions["confidence"]
    assert provenance["validation_status"] == "default"
    assert provenance["confidence"]["defaults_applied"] is True
    assert provenance["confidence"]["sources"] == ["default"]
    assert "read_error" not in provenance


def test_default_policy_provenance_is_explicit(
        db_session, sample_values):
    hospital = _seed_month(db_session, sample_values)
    policy = resolve_policy({}, {})

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True, policy=policy)

    provenance = result["policy_provenance"]
    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert provenance["validation_status"] == "default"
    assert provenance["confidence"]["defaults_applied"] is True
    assert provenance["confidence"]["sources"] == ["default"]
    assert provenance["digest"] == policy.digest


def test_invalid_weights_fallback_provenance_is_explicit(
        db_session, sample_values):
    hospital = _seed_month(db_session, sample_values)
    policy = resolve_policy(
        {}, {}, confidence_weights={key: 0.0 for key in WEIGHT_KEYS})
    assert policy.confidence_policy is not None  # defaults keep analysis valid

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True, policy=policy)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    provenance = result["policy_provenance"]
    assert provenance["validation_status"] == "fallback"
    assert provenance["confidence"]["defaults_applied"] is False
    assert provenance["confidence"]["fallback_keys"] == sorted(
        f"{WEIGHT_PREFIX}{key}" for key in WEIGHT_KEYS)
    assert "invalid" in provenance["confidence"]["sources"]
    assert "confidence" in result


# ── cache behavior: unchanged, but its identity is explicit ──────────────────
def test_cached_result_is_ok_but_has_no_fresh_policy_provenance(
        db_session, monkeypatch, sample_values):
    """Decision: cache ordering and semantics are intentionally unchanged.

    A cached row predates this call and stores no policy identity, so the
    result is marked ``cached_unavailable`` and never receives the snapshot
    resolved for the cache lookup.
    """
    hospital = _seed_month(db_session, sample_values)
    first = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True)
    assert first["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_AVAILABLE

    calls = []
    real_load = pipeline.load_policy_snapshot

    def counting(db, **kwargs):
        snapshot = real_load(db, **kwargs)
        calls.append(snapshot)
        return snapshot

    monkeypatch.setattr(pipeline, "load_policy_snapshot", counting)
    cached = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert len(calls) == 1, "cache lookup did not resolve the current policy"
    assert cached["cached"] is True
    assert cached["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert cached["failure_kind"] is None
    assert cached["policy_provenance"] is None
    assert cached["policy_provenance_status"] == \
        pipeline.POLICY_PROVENANCE_CACHED


def test_cached_report_is_not_returned_when_policy_resolution_fails(
        db_session, monkeypatch, sample_values):
    """Documented current cache decision: a policy outage wins over cache.

    This suite deliberately does not change that behavior. Changing it would
    require a stored policy identity contract for cached rows.
    """
    hospital = _seed_month(db_session, sample_values)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH, force=True)

    def boom(_db, **_kwargs):
        raise PolicyUnavailable("configuration store unavailable")

    monkeypatch.setattr(pipeline, "load_policy_snapshot", boom)
    result = pipeline.run_full_analysis(db_session, hospital.id, MONTH)

    assert result["cached"] is False
    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_FAILED
    assert result["failure_kind"] == pipeline.FAILURE_POLICY_UNAVAILABLE
    _assert_no_confidence(result)
