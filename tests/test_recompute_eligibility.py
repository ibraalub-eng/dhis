"""The background recompute must not spend its budget on pairs nothing shows.

``_recompute_hospital_months_bg`` used to recompute every hospital-month with
any IndicatorValue row — including disabled pairs and pairs whose indicators
are all disabled. The readers never present those, so the work was wasted and
the task's progress disagreed with what the month actually contains. The
worker now applies the pipeline gate (``disabled_pairs`` +
``get_enabled_values_for_hospital_month``) before it orders its work.
"""
import time

import pytest

from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorValue,
    SystemSetting,
)
from app.tasks import _lock, _task_store, get_task

MONTH = "2027-05"
OLDER_MONTH = "2027-04"


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


@pytest.fixture
def hospital(db_session):
    """An active hospital with one non-null value for ``MONTH``."""
    hospital = Hospital(name="Eligibility Fixture", is_active=True)
    db_session.add(hospital)
    db_session.commit()
    indicator = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(
        hospital_id=hospital.id,
        indicator_id=indicator.id,
        month=MONTH,
        value=10.0,
    ))
    db_session.commit()
    return hospital, indicator


def _stub_analysis(monkeypatch):
    """Record what the worker asks to recompute instead of running the engine."""
    import app.api.file_ops as file_ops
    import app.api.upload as upload_api

    calls = []
    monkeypatch.setattr(
        file_ops, "recompute_hospital_months",
        lambda db, h_id, months, force=True: calls.append((h_id, list(months))) or 0,
    )
    monkeypatch.setattr(upload_api, "_precompute_smart_bg", lambda months: None)
    return calls


def _run_bg(hospital_ids, months):
    from app.api.file_ops import _recompute_hospital_months_bg

    task_id = _recompute_hospital_months_bg(
        list(hospital_ids), list(months), "test-eligibility",
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = get_task(task_id)
        if task and task["status"] in ("done", "error"):
            return task
        time.sleep(0.05)
    raise AssertionError(f"background task did not finish: {get_task(task_id)}")


def test_disabled_pair_is_not_recomputed(db_session, monkeypatch, hospital):
    eligible, indicator = hospital
    other = Hospital(name="Disabled Pair Hospital", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.add(IndicatorValue(
        hospital_id=other.id, indicator_id=indicator.id, month=MONTH, value=12.0,
    ))
    db_session.add(SystemSetting(
        key=f"month_enabled_{other.id}_{MONTH}", value="false",
    ))
    db_session.commit()

    calls = _stub_analysis(monkeypatch)
    task = _run_bg([eligible.id, other.id], [MONTH])

    assert task["status"] == "done", task
    assert calls == [(eligible.id, [MONTH])]
    assert task["result"] == {
        "recomputed": 1, "skipped": 0, "total": 1, "failed": [],
    }


def test_pair_without_enabled_values_is_not_recomputed(db_session, monkeypatch, hospital):
    eligible, indicator = hospital
    other = Hospital(name="All Indicators Disabled", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.add(IndicatorValue(
        hospital_id=other.id, indicator_id=indicator.id, month=MONTH, value=12.0,
    ))
    db_session.add(HospitalIndicatorConfig(
        hospital_id=other.id, indicator_id=indicator.id, is_enabled=False,
    ))
    db_session.commit()

    calls = _stub_analysis(monkeypatch)
    task = _run_bg([eligible.id, other.id], [MONTH])

    assert task["status"] == "done", task
    assert calls == [(eligible.id, [MONTH])]
    assert task["result"]["total"] == 1


def test_null_only_older_month_is_not_recomputed(db_session, monkeypatch, hospital):
    """The gate applies to the historical baseline months too, not just the
    uploaded ones."""
    eligible, indicator = hospital
    db_session.add(IndicatorValue(
        hospital_id=eligible.id,
        indicator_id=indicator.id,
        month=OLDER_MONTH,
        value=None,
    ))
    db_session.commit()

    calls = _stub_analysis(monkeypatch)
    task = _run_bg([eligible.id], [MONTH])

    assert calls == [(eligible.id, [MONTH])]
    assert task["result"]["total"] == 1


def test_nothing_eligible_finishes_without_any_analysis(db_session, monkeypatch, hospital):
    only, _indicator = hospital
    db_session.add(SystemSetting(
        key=f"month_enabled_{only.id}_{MONTH}", value="false",
    ))
    db_session.commit()

    calls = _stub_analysis(monkeypatch)
    task = _run_bg([only.id], [MONTH])

    assert task["status"] == "done", task
    assert calls == []
    assert task["result"] == {
        "recomputed": 0, "skipped": 0, "total": 0, "failed": [],
    }


def test_pair_that_raises_is_reported_not_counted_as_done(db_session, monkeypatch,
                                                          hospital):
    """A failed analysis must not look like finished work.

    The exception is raised before any row is written; the old worker still did
    ``done += len(months)``, so the task reported success and the month waited
    on Queued with no explanation.
    """
    import app.api.file_ops as file_ops
    import app.api.upload as upload_api

    eligible, _indicator = hospital

    def _boom(db, h_id, months, force=True):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(file_ops, "recompute_hospital_months", _boom)
    monkeypatch.setattr(upload_api, "_precompute_smart_bg", lambda months: None)

    task = _run_bg([eligible.id], [MONTH])

    assert task["status"] == "done", task
    assert task["result"] == {
        "recomputed": 0,
        "skipped": 0,
        "total": 1,
        "failed": [{
            "hospital_id": eligible.id,
            "month": MONTH,
            "error": "engine exploded",
        }],
    }
