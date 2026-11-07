"""P3.3.3d — Confidence Weights API against the ``ConfidencePolicy`` owner.

The endpoints must use the same validation/normalization/duplicate rules as
the resolver and the analysis path:

* GET is read-only: no insert, no commit, defaults when no row exists;
* duplicate rows select the lowest id and are reported, never modified;
* an invalid stored row is exposed as invalid, never served as if valid;
* PUT validates the complete resulting policy before writing, persists the
  submitted (not normalized) values, and is atomic on failure;
* invalid input is 422, an unreadable store is 503, persistence failure 500.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api import confidence as confidence_api
from app.engine.confidence_policy import DEFAULT_WEIGHTS, WEIGHT_KEYS
from app.models import ConfidenceWeights

URL = "/confidence/weights"
DEFAULTS = {key: DEFAULT_WEIGHTS[key] for key in WEIGHT_KEYS}


def _client(app) -> TestClient:
    return TestClient(app)


def _rows(db):
    db.expire_all()
    return db.query(ConfidenceWeights).order_by(ConfidenceWeights.id).all()


def _add(db, values=None) -> ConfidenceWeights:
    row = ConfidenceWeights(**(values or dict(DEFAULTS)))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _values(row) -> dict:
    return {key: getattr(row, key) for key in WEIGHT_KEYS}


def _put(client, payload) -> "object":
    """Send raw JSON so NaN/Infinity reach the server as JSON tokens."""
    return client.put(URL, content=json.dumps(payload),
                      headers={"Content-Type": "application/json"})


def _assert_weights(actual: dict, expected: dict) -> None:
    for key in WEIGHT_KEYS:
        assert actual[key] == pytest.approx(expected[key]), key


# ── GET ─────────────────────────────────────────────────────────────────────

def test_get_without_rows_returns_defaults_and_writes_nothing(app, db_session):
    before = db_session.query(ConfidenceWeights).count()

    response = _client(app).get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "default"
    assert body["validation"] == "default"
    assert body["valid"] is True
    assert body["normalized"] is False
    assert body["row_id"] is None
    assert body["row_ids"] == []
    assert body["conflict"] is False
    _assert_weights(body, DEFAULTS)
    _assert_weights(body["submitted"], DEFAULTS)
    _assert_weights(body["effective"], DEFAULTS)
    assert db_session.query(ConfidenceWeights).count() == before == 0


def test_get_with_valid_stored_weights(app, db_session):
    row = _add(db_session)

    body = _client(app).get(URL).json()

    assert body["source"] == "database"
    assert body["validation"] == "ok"
    assert body["valid"] is True
    assert body["normalized"] is False
    assert body["row_id"] == row.id
    assert body["row_ids"] == [row.id]
    _assert_weights(body, DEFAULTS)
    assert db_session.query(ConfidenceWeights).count() == 1


def test_get_with_non_normalized_valid_weights_reports_both_views(
        app, db_session):
    stored = {
        "rule_compliance": 1.1,
        "historical": 0.2,
        "cross_hospital": 0.2,
        "trend": 0.2,
        "completeness": 0.3,
    }
    total = sum(stored.values())
    _add(db_session, stored)

    body = _client(app).get(URL).json()

    assert body["source"] == "database"
    assert body["validation"] == "ok"
    assert body["normalized"] is True
    # The submitted/stored view is what the form edits and what is persisted.
    _assert_weights(body["submitted"], stored)
    _assert_weights(body, stored)
    # The effective view is the normalized policy used for calculation.
    _assert_weights(body["effective"], {k: v / total for k, v in stored.items()})
    assert sum(body["effective"].values()) == pytest.approx(1.0)


def test_get_with_invalid_stored_weights_is_exposed_not_served_as_valid(
        app, db_session):
    _add(db_session, {key: 0.0 for key in WEIGHT_KEYS})

    response = _client(app).get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "default"
    assert body["validation"] == "invalid"
    assert body["valid"] is False
    assert body["error"] and "zero" in body["error"]
    # Documented defaults are shown, but explicitly labelled as the fallback.
    _assert_weights(body["effective"], DEFAULTS)
    _assert_weights(body["submitted"], DEFAULTS)
    # Nothing was repaired, rewritten or deleted.
    _assert_weights(_values(_rows(db_session)[0]), {k: 0.0 for k in WEIGHT_KEYS})
    assert db_session.query(ConfidenceWeights).count() == 1


def test_get_with_duplicate_rows_selects_the_lowest_id_only(app, db_session):
    first = _add(db_session)
    second = _add(db_session, {key: 0.2 for key in WEIGHT_KEYS})

    body = _client(app).get(URL).json()

    assert body["row_id"] == first.id
    assert body["row_ids"] == [first.id, second.id]
    assert body["conflict"] is True
    assert body["validation"] == "conflict"
    assert body["valid"] is True
    _assert_weights(body["submitted"], DEFAULTS)
    # The other row is untouched and still present.
    rows = _rows(db_session)
    assert len(rows) == 2
    _assert_weights(_values(rows[1]), {key: 0.2 for key in WEIGHT_KEYS})


# ── PUT ─────────────────────────────────────────────────────────────────────

def test_put_valid_weights_summing_to_one_persists_them_unchanged(
        app, db_session):
    payload = {
        "rule_compliance": 0.5,
        "historical": 0.15,
        "cross_hospital": 0.15,
        "trend": 0.1,
        "completeness": 0.1,
    }

    response = _put(_client(app), payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["normalized"] is False
    assert body["source"] == "database"
    assert body["validation"] == "ok"
    _assert_weights(body["submitted"], payload)
    _assert_weights(body["effective"], payload)
    rows = _rows(db_session)
    assert len(rows) == 1
    _assert_weights(_values(rows[0]), payload)


def test_put_valid_weights_not_summing_to_one_persist_submitted_values(
        app, db_session):
    payload = {
        "rule_compliance": 0.3,
        "historical": 0.2,
        "cross_hospital": 0.2,
        "trend": 0.2,
        "completeness": 0.2,
    }
    total = sum(payload.values())
    assert total != pytest.approx(1.0)

    response = _put(_client(app), payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["normalized"] is True
    # Effective values are normalized for calculation...
    _assert_weights(body["effective"], {k: v / total for k, v in payload.items()})
    # ...but the stored values remain exactly what was submitted.
    _assert_weights(body["submitted"], payload)
    _assert_weights(_values(_rows(db_session)[0]), payload)


def test_put_partial_merges_with_the_current_valid_configuration(
        app, db_session):
    _add(db_session)

    response = _put(_client(app), {"historical": 0.2})

    assert response.status_code == 200, response.text
    expected = dict(DEFAULTS, historical=0.2)
    body = response.json()
    _assert_weights(body["submitted"], expected)
    _assert_weights(_values(_rows(db_session)[0]), expected)
    assert body["normalized"] is True  # 1.10 total


def test_put_partial_without_rows_merges_with_the_defaults(app, db_session):
    expected = dict(DEFAULTS, trend=0.05)

    response = _put(_client(app), {"trend": 0.05})

    assert response.status_code == 200, response.text
    _assert_weights(response.json()["submitted"], expected)
    rows = _rows(db_session)
    assert len(rows) == 1
    _assert_weights(_values(rows[0]), expected)


@pytest.mark.parametrize("name,payload", [
    ("negative", {"rule_compliance": -0.1}),
    ("all_zero", {key: 0.0 for key in WEIGHT_KEYS}),
    ("nan", {"rule_compliance": float("nan")}),
    ("infinity", {"rule_compliance": float("inf")}),
    ("boolean", {"rule_compliance": True}),
    ("string", {"rule_compliance": "0.55"}),
    ("unknown_key", {"extra": 0.1}),
    ("empty", {}),
])
def test_put_rejects_every_invalid_input_category(
        app, db_session, name, payload):
    response = _put(_client(app), payload)

    assert response.status_code == 422, (name, response.text)
    assert db_session.query(ConfidenceWeights).count() == 0


def test_put_validation_failure_leaves_the_stored_row_unchanged(app, db_session):
    row = _add(db_session)

    response = _client(app).put(URL, json={"rule_compliance": -1.0})

    assert response.status_code == 422, response.text
    rows = _rows(db_session)
    assert len(rows) == 1 and rows[0].id == row.id
    _assert_weights(_values(rows[0]), DEFAULTS)


def test_put_persistence_failure_rolls_back_the_stored_row(
        app, db_session, monkeypatch):
    row = _add(db_session)
    payload = {
        "rule_compliance": 0.5,
        "historical": 0.15,
        "cross_hospital": 0.15,
        "trend": 0.1,
        "completeness": 0.1,
    }

    def boom():
        raise SQLAlchemyError("simulated write failure")

    monkeypatch.setattr(db_session, "commit", boom)
    response = _put(_client(app), payload)
    monkeypatch.undo()

    assert response.status_code == 500, response.text
    rows = _rows(db_session)
    assert len(rows) == 1 and rows[0].id == row.id
    _assert_weights(_values(rows[0]), DEFAULTS)


def test_put_with_duplicate_rows_updates_only_the_lowest_id(app, db_session):
    first = _add(db_session)
    second = _add(db_session, {key: 0.2 for key in WEIGHT_KEYS})
    payload = {
        "rule_compliance": 0.4,
        "historical": 0.15,
        "cross_hospital": 0.15,
        "trend": 0.15,
        "completeness": 0.15,
    }

    response = _put(_client(app), payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conflict"] is True
    assert body["row_id"] == first.id
    rows = _rows(db_session)
    assert [r.id for r in rows] == [first.id, second.id]
    _assert_weights(_values(rows[0]), payload)
    _assert_weights(_values(rows[1]), {key: 0.2 for key in WEIGHT_KEYS})


def test_put_partial_over_an_invalid_stored_row_is_refused(app, db_session):
    _add(db_session, {key: 0.0 for key in WEIGHT_KEYS})

    response = _put(_client(app), {"historical": 0.2})

    assert response.status_code == 503, response.text
    _assert_weights(
        _values(_rows(db_session)[0]), {key: 0.0 for key in WEIGHT_KEYS})


def test_put_complete_payload_replaces_an_invalid_stored_row(app, db_session):
    _add(db_session, {key: 0.0 for key in WEIGHT_KEYS})
    payload = dict(DEFAULTS)

    response = _put(_client(app), payload)

    assert response.status_code == 200, response.text
    _assert_weights(_values(_rows(db_session)[0]), payload)


# ── error mapping ───────────────────────────────────────────────────────────

def test_get_read_failure_maps_to_503_without_leaking_details(app, monkeypatch):
    def boom(_db):
        raise SQLAlchemyError("internal connection string leaked")

    monkeypatch.setattr(confidence_api, "_confidence_weight_rows", boom)

    response = _client(app).get(URL)

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": confidence_api._WEIGHTS_READ_DETAIL}
    assert "internal connection string" not in response.text


def test_put_read_failure_maps_to_503_without_leaking_details(app, monkeypatch):
    def boom(_db):
        raise SQLAlchemyError("internal connection string leaked")

    monkeypatch.setattr(confidence_api, "_confidence_weight_rows", boom)

    response = _put(_client(app), dict(DEFAULTS))

    assert response.status_code == 503, response.text
    assert "internal connection string" not in response.text
