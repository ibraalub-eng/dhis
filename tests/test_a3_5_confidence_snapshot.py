"""P3.3.2 — Confidence weights in the resolver snapshot.

The resolver is the only place that reads ``ConfidenceWeights``; this suite
pins the resulting effective policy, the missing/invalid/duplicate provenance,
and the digest contract. All database work uses the temporary SQLite fixtures.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import math
from threading import Barrier
from types import MappingProxyType

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.engine import config_resolver as cr
from app.engine.confidence_policy import (
    CONFIDENCE_POLICY_VERSION,
    DEFAULT_WEIGHTS,
    WEIGHT_KEYS,
)
from app.engine.config_resolver import (
    PolicyUnavailable,
    load_policy_snapshot,
    resolve_policy,
)
from app.engine.policy_view import (
    ConfidencePolicyInvalid,
    confidence_policy_from_snapshot,
    snapshot_provenance,
)
from app.models import AppConfig, ConfidenceWeights

WEIGHT_PREFIX = "confidence.weight."


def _weights(**overrides):
    return {**DEFAULT_WEIGHTS, **overrides}


def _row(db, **overrides):
    db.add(ConfidenceWeights(**_weights(**overrides)))
    db.commit()


def _clear_rows(db):
    db.query(ConfidenceWeights).delete(synchronize_session=False)
    db.commit()


def _replace_entry(snapshot, key, **changes):
    entries = dict(snapshot.entries)
    entries[key] = replace(entries[key], **changes)
    return replace(snapshot, entries=MappingProxyType(entries))


def _assert_default_entries(snapshot, *, source="default"):
    for key in WEIGHT_KEYS:
        entry = snapshot.entries[f"{WEIGHT_PREFIX}{key}"]
        assert entry.value == pytest.approx(DEFAULT_WEIGHTS[key])
        assert entry.source == source
        assert entry.component == "confidence"
        assert entry.storage == "confidence_weights"
        if source == "default":
            assert entry.validation == "fallback"


def test_missing_row_uses_defaults_without_creating_a_row(db_session):
    _clear_rows(db_session)
    snapshot = load_policy_snapshot(db_session)

    _assert_default_entries(snapshot)
    assert db_session.query(ConfidenceWeights).count() == 0
    assert snapshot.confidence_policy is not None
    assert dict(snapshot.confidence_policy.submitted_weights) == dict(DEFAULT_WEIGHTS)
    assert dict(snapshot.confidence_policy.effective_weights) == dict(DEFAULT_WEIGHTS)
    assert snapshot.confidence_policy.normalization_applied is False
    assert confidence_policy_from_snapshot(snapshot) is snapshot.confidence_policy
    assert snapshot.component_versions["confidence"] == CONFIDENCE_POLICY_VERSION
    assert snapshot.resolver_version == "1.4.0"


def test_one_unit_sum_row_is_used_without_normalization(db_session):
    _clear_rows(db_session)
    values = {key: 0.2 for key in WEIGHT_KEYS}
    _row(db_session, **values)

    snapshot = load_policy_snapshot(db_session)
    for key in WEIGHT_KEYS:
        entry = snapshot.entries[f"{WEIGHT_PREFIX}{key}"]
        assert entry.value == pytest.approx(0.2)
        assert entry.source == "database"
        assert entry.storage == "confidence_weights"
        assert entry.validation == "ok"
    assert snapshot.confidence_policy.normalization_applied is False
    assert dict(snapshot.confidence_policy.submitted_weights) == values
    assert dict(snapshot.confidence_policy.effective_weights) == values


def test_non_unit_row_is_normalized_and_the_original_is_retained(db_session):
    _clear_rows(db_session)
    submitted = _weights(rule_compliance=0.54)  # 0.99 total
    _row(db_session, **submitted)

    snapshot = load_policy_snapshot(db_session)
    policy = snapshot.confidence_policy
    assert policy is not None
    assert policy.normalization_applied is True
    assert dict(policy.submitted_weights) == submitted
    assert dict(policy.effective_weights) == pytest.approx(
        {key: submitted[key] / 0.99 for key in WEIGHT_KEYS})
    for key in WEIGHT_KEYS:
        entry = snapshot.entries[f"{WEIGHT_PREFIX}{key}"]
        assert entry.value == pytest.approx(policy.effective_weights[key])
        assert entry.source == "database"
        assert entry.validation == "ok"
    assert not any(error.key == cr.CONFIDENCE_WEIGHTS_ERROR_KEY
                   for error in snapshot.errors)


def _assert_invalid_snapshot(snapshot):
    for key in WEIGHT_KEYS:
        entry = snapshot.entries[f"{WEIGHT_PREFIX}{key}"]
        assert entry.value == pytest.approx(DEFAULT_WEIGHTS[key])
        assert entry.source == "invalid"
        assert entry.validation == "fallback"
        assert entry.storage == "confidence_weights"
    errors = [error for error in snapshot.errors
              if error.key == cr.CONFIDENCE_WEIGHTS_ERROR_KEY]
    assert len(errors) == 1
    assert errors[0].fallback == pytest.approx(dict(DEFAULT_WEIGHTS))
    assert snapshot.confidence_policy is not None
    assert snapshot.confidence_policy.normalization_applied is False
    assert dict(snapshot.confidence_policy.effective_weights) == dict(DEFAULT_WEIGHTS)


@pytest.mark.parametrize("bad", [
    {key: 0.0 for key in WEIGHT_KEYS},
    _weights(rule_compliance=-0.01),
])
def test_invalid_row_falls_back_to_the_complete_default_set(db_session, bad):
    _clear_rows(db_session)
    _row(db_session, **bad)
    _assert_invalid_snapshot(load_policy_snapshot(db_session))


@pytest.mark.parametrize("bad", [
    _weights(rule_compliance=float("nan")),
    _weights(rule_compliance=float("inf")),
])
def test_non_finite_row_falls_back_to_the_complete_default_set(bad):
    # SQLite maps NaN to NULL and the model is NOT NULL, so exercise the
    # resolver's pure row-input path for both non-finite values.
    _assert_invalid_snapshot(
        resolve_policy({}, {}, confidence_weights=bad))


def test_duplicate_rows_use_lowest_id_and_report_all_observed_ids(db_session):
    _clear_rows(db_session)
    selected = ConfidenceWeights(**{key: 0.2 for key in WEIGHT_KEYS})
    db_session.add(selected)
    db_session.commit()
    db_session.add(ConfidenceWeights(**{key: 0.3 for key in WEIGHT_KEYS}))
    db_session.commit()

    snapshot = load_policy_snapshot(db_session)
    assert snapshot.confidence_policy is not None
    assert dict(snapshot.confidence_policy.submitted_weights) == {
        key: 0.2 for key in WEIGHT_KEYS}
    for key in WEIGHT_KEYS:
        entry = snapshot.entries[f"{WEIGHT_PREFIX}{key}"]
        assert entry.value == pytest.approx(0.2)
        assert entry.source == "database"
        assert entry.validation == "conflict"
    conflict = next(error for error in snapshot.errors
                    if error.key == cr.CONFIDENCE_WEIGHTS_ERROR_KEY)
    assert conflict.raw["row_ids"] == [
        selected.id,
        db_session.query(ConfidenceWeights)
        .order_by(ConfidenceWeights.id.desc()).first().id,
    ]
    assert conflict.raw["count"] == 2
    assert db_session.query(ConfidenceWeights).count() == 2


def test_an_unrepresentable_stored_cutoff_keeps_its_entry_and_drops_the_policy():
    """A corrupt cutoff keeps its old resolved value; no policy is invented.

    Cutoffs are not this phase's input and must keep their previous behaviour
    (reported unclamped), so P3.3.2 may not turn one into a resolver crash.
    ``ConfidencePolicy`` cannot hold a negative cutoff, so the weights still
    resolve, the entry is unchanged, and the snapshot says why it carries no
    policy object instead of substituting different scalars.
    """
    snapshot = resolve_policy({"confidence_high": -5.0}, {})

    assert snapshot.values["confidence.high"] == -5.0
    assert snapshot.entries["confidence.high"].source == "database"
    assert snapshot.values[f"{WEIGHT_PREFIX}rule_compliance"] == pytest.approx(
        DEFAULT_WEIGHTS["rule_compliance"])
    assert snapshot.confidence_policy is None
    error = next(error for error in snapshot.errors
                 if error.key == cr.CONFIDENCE_POLICY_ERROR_KEY)
    assert error.raw["high"] == -5.0
    assert error.fallback is None


def test_identical_effective_policies_have_identical_digests():
    one = resolve_policy({}, {}, confidence_weights=dict(DEFAULT_WEIGHTS))
    doubled = resolve_policy(
        {}, {}, confidence_weights={key: value * 2
                                    for key, value in DEFAULT_WEIGHTS.items()})
    different = resolve_policy(
        {}, {}, confidence_weights={key: 0.2 for key in WEIGHT_KEYS})

    assert dict(one.confidence_policy.effective_weights) == pytest.approx(
        dict(DEFAULT_WEIGHTS))
    assert dict(doubled.confidence_policy.effective_weights) == pytest.approx(
        dict(DEFAULT_WEIGHTS))
    assert one.digest == doubled.digest
    assert one.canonical_json() == doubled.canonical_json()
    assert doubled.confidence_policy.normalization_applied is True
    assert one.digest != different.digest
    assert one.canonical_json() != different.canonical_json()


def test_digest_does_not_depend_on_weight_submission_or_row_identity(db_session):
    _clear_rows(db_session)
    _row(db_session, **{key: 0.2 for key in WEIGHT_KEYS})
    single = load_policy_snapshot(db_session)

    db_session.add(ConfidenceWeights(**{key: 0.2 for key in WEIGHT_KEYS}))
    db_session.commit()
    duplicate = load_policy_snapshot(db_session)

    assert duplicate.confidence_policy.submitted_weights == pytest.approx(
        single.confidence_policy.submitted_weights)
    assert duplicate.digest == single.digest
    assert duplicate.canonical_json() == single.canonical_json()
    assert any(error.key == cr.CONFIDENCE_WEIGHTS_ERROR_KEY
               for error in duplicate.errors)


def test_existing_planes_and_cutoffs_remain_unchanged(db_session):
    db_session.add(AppConfig(key="zscore_threshold", value=99.0,
                             category="thresholds", label="z"))
    db_session.add(AppConfig(key="confidence_high", value=95.0,
                             category="thresholds", label="high"))
    db_session.add(AppConfig(key="confidence_medium", value=55.0,
                             category="thresholds", label="medium"))
    db_session.add(AppConfig(key="confidence_low", value=30.0,
                             category="thresholds", label="low"))
    db_session.add(AppConfig(key="alerts_min_peers", value=3.0,
                             category="alerts", label="peers"))
    _row(db_session, **{key: 0.2 for key in WEIGHT_KEYS})
    db_session.commit()

    snapshot = load_policy_snapshot(db_session)

    assert snapshot.values["confidence.high"] == 95.0
    assert snapshot.values["confidence.medium"] == 55.0
    assert snapshot.values["confidence.low"] == 30.0
    assert snapshot.values["confidence.zscore_threshold"] == 99.0
    assert snapshot.values["alerts.min_peers"] == 3
    assert snapshot.values["severity.zscore_threshold"] == 5.0
    assert snapshot.values["alerts.z_threshold"] == 99.0
    assert snapshot.component_versions["confidence"] == CONFIDENCE_POLICY_VERSION
    assert snapshot.component_versions["comparison"] == "2026-10-24.1"


def test_concurrent_sessions_resolve_independent_weight_policies(tmp_path):
    engines = []
    sessions = []
    try:
        for name, weights in (("a", dict(DEFAULT_WEIGHTS)),
                              ("b", {key: 0.2 for key in WEIGHT_KEYS})):
            engine = create_engine(
                f"sqlite:///{tmp_path / (name + '.db')}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            session = sessionmaker(bind=engine)()
            session.add(ConfidenceWeights(**weights))
            session.commit()
            engines.append(engine)
            sessions.append(session)

        barrier = Barrier(2)

        def resolve(session):
            barrier.wait(timeout=10)
            return load_policy_snapshot(session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = (future.result(timeout=15) for future in (
                pool.submit(resolve, sessions[0]),
                pool.submit(resolve, sessions[1]),
            ))

        assert first.values[f"{WEIGHT_PREFIX}rule_compliance"] == pytest.approx(0.55)
        assert second.values[f"{WEIGHT_PREFIX}rule_compliance"] == pytest.approx(0.2)
        assert first.confidence_policy is not second.confidence_policy
        assert first.digest != second.digest
    finally:
        for session in sessions:
            session.close()
        for engine in engines:
            engine.dispose()


# ── P3.3.2a — adapter refusal and typed invalid-policy behaviour ───────────
def test_read_error_snapshot_is_refused_by_the_confidence_adapter():
    snapshot = resolve_policy({}, {}, strict=False,
                              read_error="database unavailable")

    assert snapshot.confidence_policy is None
    with pytest.raises(PolicyUnavailable) as exc:
        confidence_policy_from_snapshot(snapshot)
    assert "database unavailable" in str(exc.value)


@pytest.mark.parametrize("key", [
    "confidence.weight.rule_compliance",
    "confidence.weight.historical",
    "confidence.weight.cross_hospital",
    "confidence.weight.trend",
    "confidence.weight.completeness",
])
def test_unavailable_weight_entry_is_refused(key):
    snapshot = _replace_entry(resolve_policy({}, {}), key,
                              source="unavailable")

    with pytest.raises(PolicyUnavailable) as exc:
        confidence_policy_from_snapshot(snapshot)
    assert key in str(exc.value)


@pytest.mark.parametrize("key", [
    "confidence.high",
    "confidence.medium",
    "confidence.low",
    "confidence.zscore_threshold",
])
def test_unavailable_cutoff_or_z_entry_is_refused(key):
    snapshot = _replace_entry(resolve_policy({}, {}), key,
                              source="unavailable")

    with pytest.raises(PolicyUnavailable) as exc:
        confidence_policy_from_snapshot(snapshot)
    assert key in str(exc.value)


def test_valid_snapshot_returns_the_attached_policy():
    snapshot = resolve_policy({}, {})

    assert confidence_policy_from_snapshot(snapshot) is snapshot.confidence_policy


def test_supported_manual_snapshot_without_attached_policy_still_resolves():
    snapshot = replace(resolve_policy({}, {}), confidence_policy=None)

    policy = confidence_policy_from_snapshot(snapshot)

    assert policy.high == pytest.approx(80.0)
    assert policy.medium == pytest.approx(50.0)
    assert policy.low == pytest.approx(25.0)
    assert policy.zscore_threshold == pytest.approx(2.5)
    assert policy.normalization_applied is False


@pytest.mark.parametrize("key", [
    "confidence.weight.rule_compliance",
    "confidence.high",
    "confidence.zscore_threshold",
])
def test_missing_required_entry_is_refused(key):
    entries = dict(resolve_policy({}, {}).entries)
    del entries[key]
    snapshot = replace(resolve_policy({}, {}),
                       entries=MappingProxyType(entries))

    with pytest.raises(PolicyUnavailable) as exc:
        confidence_policy_from_snapshot(snapshot)
    assert key in str(exc.value)


@pytest.mark.parametrize("raw_key,entry_key,bad", [
    ("confidence_high", "confidence.high", -5.0),
    ("confidence_high", "confidence.high", float("nan")),
    ("confidence_medium", "confidence.medium", float("inf")),
    ("zscore_threshold", "confidence.zscore_threshold", -2.5),
    ("zscore_threshold", "confidence.zscore_threshold", float("nan")),
])
def test_invalid_cutoff_or_z_raises_typed_error_and_preserves_entry(
        raw_key, entry_key, bad):
    snapshot = resolve_policy({raw_key: bad}, {})
    entry = snapshot.entries[entry_key]

    assert snapshot.confidence_policy is None
    assert entry.source == "database"
    if math.isfinite(bad):
        assert entry.value == pytest.approx(bad)
    elif math.isnan(bad):
        assert math.isnan(entry.value)
    else:
        assert math.isinf(entry.value)
    error = next(error for error in snapshot.errors
                 if error.key == cr.CONFIDENCE_POLICY_ERROR_KEY)
    assert error.fallback is None

    with pytest.raises(ConfidencePolicyInvalid) as exc:
        confidence_policy_from_snapshot(snapshot)
    assert "ConfidencePolicy" in str(exc.value)


def test_provenance_exposes_invalid_weight_fallback_without_raw_values():
    snapshot = resolve_policy(
        {}, {}, confidence_weights={key: 0.0 for key in WEIGHT_KEYS})
    provenance = snapshot_provenance(snapshot)
    confidence = provenance["confidence"]

    assert confidence["invalid_keys"] == sorted(
        f"{WEIGHT_PREFIX}{key}" for key in WEIGHT_KEYS)
    assert confidence["fallback_keys"] == sorted(
        f"{WEIGHT_PREFIX}{key}" for key in WEIGHT_KEYS)
    assert set(confidence["validation"].values()) == {"fallback"}
    assert any(error["key"] == cr.CONFIDENCE_WEIGHTS_ERROR_KEY
               for error in provenance["errors"])
    assert "raw" not in provenance["errors"][0]


def test_provenance_exposes_duplicate_conflict_without_row_ids():
    snapshot = resolve_policy(
        {}, {}, confidence_weights=dict(DEFAULT_WEIGHTS),
        confidence_weights_row_ids=(1, 2),
        confidence_weights_conflict=True,
    )
    provenance = snapshot_provenance(snapshot)
    confidence = provenance["confidence"]

    assert confidence["conflict_keys"] == sorted(
        f"{WEIGHT_PREFIX}{key}" for key in WEIGHT_KEYS)
    assert set(confidence["validation"].values()) == {"conflict"}
    assert any(error["key"] == cr.CONFIDENCE_WEIGHTS_ERROR_KEY
               for error in provenance["errors"])
    assert "row_ids" not in repr(provenance)
