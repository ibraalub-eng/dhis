"""Per-month analysis status for the upload screen.

``POST /upload/`` keeps its published response (no task id), so the browser
cannot poll ``/tasks/{id}`` for the analysis it queues. ``GET
/upload/analysis-status`` answers the same question keyed by month: is the
background analysis for this month running, finished, or failed? These tests
pin the three states, the running-task precedence over an old stored row, and
that the upload response itself did not change.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine.pipeline import FALLBACK_ANALYSIS_ISSUE
from app.main import app
from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorValue,
    QualityScore,
    SystemSetting,
)
from app.tasks import _lock, _task_store, create_task, run_task, set_progress

MONTH = "2027-03"


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


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
    hospital = Hospital(name="Status Fixture Hospital", is_active=True)
    db_session.add(hospital)
    db_session.commit()
    indicator = db_session.query(Indicator).first()
    assert indicator is not None, "the app fixture seeds the indicator catalog"
    db_session.add(IndicatorValue(
        hospital_id=hospital.id,
        indicator_id=indicator.id,
        month=MONTH,
        value=10.0,
    ))
    db_session.commit()
    return hospital


def _score_row(hospital_id, fallback=False):
    issues = [FALLBACK_ANALYSIS_ISSUE] if fallback else []
    return QualityScore(
        hospital_id=hospital_id,
        month=MONTH,
        score=0.0,
        issues=json.dumps(issues),
    )


def _add_hospital(db_session, *, value=10.0, month=MONTH):
    """Another active hospital with one non-null value for ``month``."""
    hospital = Hospital(name="Status Extra Hospital", is_active=True)
    db_session.add(hospital)
    db_session.commit()
    indicator = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(
        hospital_id=hospital.id,
        indicator_id=indicator.id,
        month=month,
        value=value,
    ))
    db_session.commit()
    return hospital, indicator


def _one_month(client, months=MONTH):
    resp = client.get("/upload/analysis-status", params={"months": months})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["months"]
    assert len(rows) == 1, rows
    return rows[0]


class TestUploadAnalysisStatus:
    def test_running_analysis_reports_analyzing_with_progress(self, client, hospital):
        task_id = create_task("upload", meta={"months": [MONTH]})
        set_progress(task_id, 40)
        row = _one_month(client)
        assert row["month"] == MONTH
        assert row["status"] == "analyzing"
        assert row["progress"] == 40
        assert row["hospitals"] == 1

    def test_stored_result_reports_complete(self, client, hospital, db_session):
        db_session.add(_score_row(hospital.id))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "complete"
        assert row["analyzed"] == 1
        assert row["failed"] == 0

    def test_failed_analysis_row_reports_failed(self, client, hospital, db_session):
        db_session.add(_score_row(hospital.id, fallback=True))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "failed"
        assert row["failed"] == 1
        assert row["error"]

    def test_running_task_wins_over_an_old_stored_result(self, client, hospital, db_session):
        db_session.add(_score_row(hospital.id))
        db_session.commit()
        create_task("upload", meta={"months": [MONTH]})
        assert _one_month(client)["status"] == "analyzing"

    def test_errored_task_reports_failed_when_the_month_has_no_result(self, client, hospital):
        task_id = create_task("upload", meta={"months": [MONTH]})

        def _boom():
            raise RuntimeError("engine exploded")

        run_task(task_id, _boom)
        row = _one_month(client)
        assert row["status"] == "failed"
        assert "engine exploded" in row["error"]

    def test_fully_analyzed_month_is_complete_despite_an_old_error(self, client, hospital, db_session):
        db_session.add(_score_row(hospital.id))
        db_session.commit()
        task_id = create_task("upload", meta={"months": [MONTH]})

        def _boom():
            raise RuntimeError("previous run failed")

        run_task(task_id, _boom)
        assert _one_month(client)["status"] == "complete"

    def test_without_months_parameter_a_running_task_names_the_months(self, client, hospital):
        create_task("upload", meta={"months": [MONTH]})
        resp = client.get("/upload/analysis-status")
        assert resp.status_code == 200, resp.text
        assert [row["month"] for row in resp.json()["months"]] == [MONTH]

    def test_without_months_or_running_task_is_empty(self, client, hospital):
        resp = client.get("/upload/analysis-status")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"months": []}

    def test_invalid_month_values_are_ignored(self, client, hospital):
        resp = client.get("/upload/analysis-status", params={"months": "nope,2027-3,"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"months": []}

    def test_month_without_values_is_complete_not_queued(self, client, hospital):
        row = _one_month(client, months="2028-01")
        assert row["status"] == "complete"
        assert (row["hospitals"], row["analyzed"], row["failed"]) == (0, 0, 0)

    def test_ineligible_pair_does_not_hold_the_month_open(self, client, hospital, db_session):
        """The pair the pipeline never analyses must not count as unfinished."""
        db_session.add(_score_row(hospital.id))
        other, indicator = _add_hospital(db_session)
        db_session.add(HospitalIndicatorConfig(
            hospital_id=other.id, indicator_id=indicator.id, is_enabled=False,
        ))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "complete"
        assert (row["hospitals"], row["analyzed"], row["failed"]) == (1, 1, 0)

    def test_all_indicators_disabled_for_a_pair_keeps_it_out_of_the_month(self, client, hospital, db_session):
        indicator = db_session.query(Indicator).first()
        db_session.add(HospitalIndicatorConfig(
            hospital_id=hospital.id, indicator_id=indicator.id, is_enabled=False,
        ))
        # A stale fallback row for the same ineligible pair is not a failure of
        # this month either: the pipeline does not analyse that pair at all.
        db_session.add(_score_row(hospital.id, fallback=True))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "complete"
        assert (row["hospitals"], row["analyzed"], row["failed"]) == (0, 0, 0)

    def test_disabled_pair_keeps_its_hospital_out_of_the_month(self, client, hospital, db_session):
        db_session.add(SystemSetting(
            key=f"month_enabled_{hospital.id}_{MONTH}", value="false",
        ))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "complete"
        assert (row["hospitals"], row["analyzed"], row["failed"]) == (0, 0, 0)

    def test_disabled_pair_is_skipped_while_another_hospital_is_analysed(self, client, hospital, db_session):
        db_session.add(_score_row(hospital.id))
        other, _indicator = _add_hospital(db_session)
        db_session.add(SystemSetting(
            key=f"month_enabled_{other.id}_{MONTH}", value="false",
        ))
        db_session.commit()
        row = _one_month(client)
        assert row["status"] == "complete"
        assert (row["hospitals"], row["analyzed"], row["failed"]) == (1, 1, 0)

    def test_task_reported_failure_without_a_stored_row_is_failed(
        self, client, hospital,
    ):
        """An analysis that raised before writing a row must not stay Queued.

        No QualityScore row exists for the pair, so the stored rows alone would
        report ``pending`` forever; the task's own failure report is the only
        evidence that the month is finished — as a failure.
        """
        task_id = create_task("upload", meta={"months": [MONTH]})
        run_task(task_id, lambda: {
            "recomputed": 0, "skipped": 0, "total": 1,
            "failed": [{"hospital_id": hospital.id, "month": MONTH,
                        "error": "engine exploded"}],
        })

        row = _one_month(client)
        assert row["status"] == "failed"
        assert (row["analyzed"], row["failed"]) == (0, 1)
        assert "1 hospital(s) could not be analysed" in row["error"]

    def test_failure_reported_for_another_month_does_not_fail_this_one(
        self, client, hospital, db_session,
    ):
        db_session.add(_score_row(hospital.id))
        db_session.commit()
        task_id = create_task("upload", meta={"months": [MONTH]})
        run_task(task_id, lambda: {
            "recomputed": 0, "skipped": 0, "total": 1,
            "failed": [{"hospital_id": hospital.id, "month": "2027-02",
                        "error": "other month"}],
        })

        assert _one_month(client)["status"] == "complete"

    def test_reported_failure_does_not_override_a_stored_result(
        self, client, hospital, db_session,
    ):
        """A pair that has a row now must not be counted failed by an older report."""
        db_session.add(_score_row(hospital.id))
        db_session.commit()
        task_id = create_task("upload", meta={"months": [MONTH]})
        run_task(task_id, lambda: {
            "recomputed": 0, "skipped": 0, "total": 1,
            "failed": [{"hospital_id": hospital.id, "month": MONTH,
                        "error": "engine exploded"}],
        })

        row = _one_month(client)
        assert row["status"] == "complete"
        assert (row["analyzed"], row["failed"]) == (1, 0)


def test_upload_response_shape_is_unchanged():
    """The status is a separate reader on purpose: adding task_id (or any
    status field) to POST /upload/ would change its published response."""
    from app.schemas import UploadResponse

    assert set(UploadResponse.model_fields) == {
        "filename",
        "hospitals_processed",
        "rows_imported",
        "message",
        "hospitals",
        "months",
        "new_indicators",
    }
