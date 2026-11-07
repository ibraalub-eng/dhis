"""P3.3.3a-Fix — Confidence API policy propagation and failure safety.

These tests pin the API contract independently of the analytical suite:

* ``/compare/all`` resolves one display snapshot and one ConfidencePolicy per
  batch, then passes that exact object to every hospital;
* every policy failure is an HTTP 503, including a failure on a later hospital
  in the batch (no 200 with partial results);
* the single-hospital and summary endpoints use the same 503 contract.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import confidence as confidence_api
from app.engine.config_resolver import PolicyUnavailable, resolve_policy
from app.engine.policy_view import ConfidencePolicyInvalid

MONTH = "2026-04"
POLICY_DETAIL = (
    "Confidence policy unavailable; configuration could not be resolved."
)


class _FakeResult:
    """The small shape ``compare_hospital_confidence`` reads from a result."""

    def to_dict(self):
        return {
            "hospital": "Test Hospital",
            "month": MONTH,
            "overall_confidence": 80.0,
            "level": "HIGH",
            "by_level": {
                "CRITICAL": 0,
                "LOW": 0,
                "MEDIUM": 0,
                "HIGH": 0,
            },
        }


def _enable_all_hospitals(monkeypatch):
    monkeypatch.setattr(
        confidence_api,
        "get_enabled_values_for_hospital_month",
        lambda *_args, **_kwargs: {"2": 1.0},
    )


def _capture_helper_calls(monkeypatch):
    calls = []

    def fake_run(_db, hospital_id, _month, **kwargs):
        calls.append((
            hospital_id,
            kwargs["display_policy"],
            kwargs["confidence_policy"],
        ))
        return _FakeResult()

    monkeypatch.setattr(confidence_api, "_run_confidence_for_hospital", fake_run)
    return calls


def test_compare_all_resolves_one_snapshot_and_one_policy_per_batch(
        app, monkeypatch):
    _enable_all_hospitals(monkeypatch)
    loads = []
    adapters = []
    real_load = confidence_api.load_display_policy
    real_adapter = confidence_api.confidence_policy_from_snapshot

    def counting_load(db):
        snapshot = real_load(db)
        loads.append(snapshot)
        return snapshot

    def counting_adapter(snapshot):
        policy = real_adapter(snapshot)
        adapters.append(policy)
        return policy

    monkeypatch.setattr(confidence_api, "load_display_policy", counting_load)
    monkeypatch.setattr(
        confidence_api, "confidence_policy_from_snapshot", counting_adapter)
    calls = _capture_helper_calls(monkeypatch)

    response = TestClient(app).get(
        "/confidence/compare/all", params={"month": MONTH})

    assert response.status_code == 200, response.text
    assert len(calls) == 3
    assert len(loads) == 1, "the display snapshot was resolved more than once"
    assert len(adapters) == 1, "the adapter ran more than once for one batch"
    assert all(call[1] is loads[0] for call in calls)


def test_compare_all_passes_the_same_policy_object_to_every_hospital(
        app, monkeypatch):
    _enable_all_hospitals(monkeypatch)
    loads = []
    real_load = confidence_api.load_display_policy

    def counting_load(db):
        snapshot = real_load(db)
        loads.append(snapshot)
        return snapshot

    monkeypatch.setattr(confidence_api, "load_display_policy", counting_load)
    calls = _capture_helper_calls(monkeypatch)

    response = TestClient(app).get(
        "/confidence/compare/all", params={"month": MONTH})

    assert response.status_code == 200, response.text
    assert len(calls) == 3
    batches = [call[2] for call in calls]
    assert batches[0] is batches[1] is batches[2]
    assert batches[0] is loads[0].confidence_policy


@pytest.mark.parametrize("path", [
    "/confidence/1",
    "/confidence/1/summary",
])
@pytest.mark.parametrize("error_type", [
    PolicyUnavailable,
    ConfidencePolicyInvalid,
])
def test_single_hospital_endpoints_map_policy_failures_to_503(
        app, path, error_type, monkeypatch):
    def fail(*_args, **_kwargs):
        raise error_type("internal diagnostic must not be exposed")

    monkeypatch.setattr(confidence_api, "_run_confidence_for_hospital", fail)

    response = TestClient(app).get(path, params={"month": MONTH})

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": POLICY_DETAIL}
    assert "internal diagnostic" not in response.text


def test_compare_all_snapshot_failure_returns_503(app, monkeypatch):
    invalid = resolve_policy({}, {}, strict=False,
                             read_error="configuration store unavailable")
    monkeypatch.setattr(
        confidence_api, "load_display_policy", lambda _db: invalid)

    response = TestClient(app).get(
        "/confidence/compare/all", params={"month": MONTH})

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": POLICY_DETAIL}
    assert "configuration store unavailable" not in response.text


@pytest.mark.parametrize("error_type", [
    PolicyUnavailable,
    ConfidencePolicyInvalid,
])
def test_compare_all_policy_failure_on_a_later_hospital_returns_503(
        app, error_type, monkeypatch):
    _enable_all_hospitals(monkeypatch)
    calls = []

    def fail_on_second(_db, hospital_id, _month, **_kwargs):
        calls.append(hospital_id)
        if len(calls) == 2:
            raise error_type("internal diagnostic must not be exposed")
        return _FakeResult()

    monkeypatch.setattr(
        confidence_api, "_run_confidence_for_hospital", fail_on_second)

    response = TestClient(app).get(
        "/confidence/compare/all", params={"month": MONTH})

    assert len(calls) == 2, "the batch skipped the later hospital"
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": POLICY_DETAIL}
    assert "internal diagnostic" not in response.text
