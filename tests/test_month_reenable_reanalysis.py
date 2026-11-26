"""Re-enabling a hospital month refreshes the score the workers skipped.

While a pair is disabled the analysis workers skip it, so a score stored before
values were uploaded to that hidden month is stale. Returning the pair to active
readers must show the current data, not the older score: ``PUT
/config/month-settings`` queues a one-pair re-analysis for the
disabled -> enabled transition (and only for it).
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    SystemSetting,
)
from app.tasks import _lock, _task_store, list_tasks

MONTH = "2027-06"
STALE_FINGERPRINT = "stale-before-reenable"


@pytest.fixture()
def client(app):
    """conftest overrides get_current_user and get_db for the whole app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_task_store():
    """The task store is process-global; keep these tasks out of other tests."""
    with _lock:
        saved = dict(_task_store)
        _task_store.clear()
    yield
    with _lock:
        _task_store.clear()
        _task_store.update(saved)


@pytest.fixture()
def hospital(db_session):
    hospital = Hospital(name="Re-enable Fixture", is_active=True)
    db_session.add(hospital)
    db_session.commit()
    return hospital


def _seed_values(db, hospital_id, month, values):
    for code, value in values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(
                hospital_id=hospital_id,
                indicator_id=indicator.id,
                month=month,
                value=value,
            ))
    db.commit()


def _set_disabled(db, hospital_id, month):
    db.add(SystemSetting(
        key=f"month_enabled_{hospital_id}_{month}", value="false",
    ))
    db.commit()


def _put(client, hospital_id, month, enabled):
    return client.put("/config/month-settings", json={
        "hospital_id": hospital_id, "month": month, "enabled": enabled,
    })


def _reenable_tasks(month):
    return [
        task for task in list_tasks()
        if task["name"].startswith("re-enable:")
        and month in ((task.get("meta") or {}).get("months") or [])
    ]


def _wait_for_reenable(month, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for task in _reenable_tasks(month):
            if task["status"] in ("done", "error"):
                return task
        time.sleep(0.05)
    raise AssertionError(f"no re-enable analysis task finished: {_reenable_tasks(month)}")


def _stored_row(db, hospital_id, month):
    db.expire_all()
    return (db.query(QualityScore)
            .filter(QualityScore.hospital_id == hospital_id,
                    QualityScore.month == month)
            .first())


def test_stored_score_is_refreshed_after_reenable(client, db_session, hospital,
                                                  sample_values):
    """The row stored while the month was hidden is replaced by a current one."""
    _seed_values(db_session, hospital.id, MONTH, sample_values)
    db_session.add(QualityScore(
        hospital_id=hospital.id,
        month=MONTH,
        score=15.0,
        rule_compliance=15.0,
        completeness=15.0,
        consistency=15.0,
        outlier_penalty=0.0,
        scoring_fingerprint=STALE_FINGERPRINT,
    ))
    db_session.commit()
    _set_disabled(db_session, hospital.id, MONTH)
    stale = _stored_row(db_session, hospital.id, MONTH)
    assert stale.scoring_fingerprint == STALE_FINGERPRINT

    response = _put(client, hospital.id, MONTH, True)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["previous_state"] == "disabled"

    task = _wait_for_reenable(MONTH)
    assert task["status"] == "done", task
    assert task["result"]["recomputed"] == 1

    refreshed = _stored_row(db_session, hospital.id, MONTH)
    assert refreshed is not None, "the pair must keep a stored score"
    assert refreshed.scoring_fingerprint != STALE_FINGERPRINT, \
        "the pre-disable score was served again after re-enabling"
    assert refreshed.scoring_fingerprint, \
        "a current analysis stamps its scoring fingerprint"
    stale_score = 15.0
    if refreshed.score != stale_score:
        return
    # The current analysis happened to produce the seeded score: prove it came
    # from the data (not from the untouched old row) by re-running it directly
    # and comparing.
    from app.engine.pipeline import run_full_analysis
    run_full_analysis(db_session, hospital.id, MONTH, force=True)
    again = _stored_row(db_session, hospital.id, MONTH)
    assert again.scoring_fingerprint != STALE_FINGERPRINT
    assert again.score == refreshed.score


def test_pair_without_values_is_not_queued_for_analysis(client, db_session, hospital):
    """Nothing to analyse means no fallback row and no wasted worker."""
    indicator = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(
        hospital_id=hospital.id, indicator_id=indicator.id,
        month=MONTH, value=None,
    ))
    db_session.commit()
    _set_disabled(db_session, hospital.id, MONTH)

    response = _put(client, hospital.id, MONTH, True)
    assert response.status_code == 200, response.text
    time.sleep(1.5)
    assert _reenable_tasks(MONTH) == []
    assert _stored_row(db_session, hospital.id, MONTH) is None


def test_saving_an_already_enabled_month_does_not_reanalyse(client, db_session,
                                                            hospital, sample_values):
    _seed_values(db_session, hospital.id, MONTH, sample_values)

    response = _put(client, hospital.id, MONTH, True)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is False
    time.sleep(1.5)
    assert _reenable_tasks(MONTH) == []


def test_disabling_a_month_does_not_reanalyse(client, db_session, hospital,
                                              sample_values):
    _seed_values(db_session, hospital.id, MONTH, sample_values)

    response = _put(client, hospital.id, MONTH, False)
    assert response.status_code == 200, response.text
    time.sleep(1.5)
    assert _reenable_tasks(MONTH) == []
