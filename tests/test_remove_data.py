"""Tests for the Remove Data feature (POST /hospitals/remove-data).

Covers: deleting one month for one hospital or all hospitals, retention of
other months, month-calendar bookkeeping, the no-op path, that the tree node
set never changes (only values clear), and the shared recompute helper.

The undo snapshot is shared with the Hospitals tab's Clear Data endpoint
(PUT /hospitals/{id}/clear-data), so both delete paths are covered here.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import (
    Hospital, Indicator, IndicatorValue, QualityScore, ValidationResult,
    AnomalyResult, ConfidenceScore, ClinicalInsight,
)


@pytest.fixture(autouse=True)
def _clear_undo_store():
    """The snapshot store is process-local, so isolate every test from the rest."""
    from app import undo_store

    undo_store.clear()
    yield
    undo_store.clear()


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


def _tree_codes(tree):
    out = []

    def walk(node):
        out.append(node["code"])
        for child in node.get("children", []):
            walk(child)

    for child in tree.get("children", []):
        walk(child)
    return out


def _tree_values(tree):
    out = []

    def walk(node):
        out.append(node.get("value"))
        for child in node.get("children", []):
            walk(child)

    for child in tree.get("children", []):
        walk(child)
    return out


def _remove(client, month, hospital_id, recompute=False):
    return client.post(
        "/hospitals/remove-data",
        json={"month": month, "hospital_id": hospital_id, "recompute": recompute},
    )


def _undo(client, token):
    return client.post("/hospitals/remove-data/undo", json={"token": token})


def _clear(client, hospital_id, month=None, recompute=False):
    path = f"/hospitals/{hospital_id}/clear-data?recompute={'true' if recompute else 'false'}"
    if month:
        path += f"&month={month}"
    return client.put(path)


class TestRemoveData:
    def test_one_hospital_one_month(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-01", value=10.0))
        db_session.add(QualityScore(
            hospital_id=hospital.id, month="2027-01", score=50.0, issues="[]"))
        db_session.commit()

        resp = _remove(client, "2027-01", hospital.id)
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "hospital"
        assert body["removed"]["indicator_values"] == 1
        assert body["removed"]["quality_scores"] == 1
        assert body["recompute_task_id"] is None

        assert db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-01",
        ).count() == 0
        assert db_session.query(QualityScore).filter(
            QualityScore.hospital_id == hospital.id,
            QualityScore.month == "2027-01",
        ).count() == 0

    def test_other_months_retained(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        for month in ("2027-01", "2027-02"):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=ind.id, month=month, value=10.0))
        db_session.commit()

        resp = _remove(client, "2027-01", hospital.id)
        assert resp.status_code == 200
        assert db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-01",
        ).count() == 0
        assert db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-02",
        ).count() == 1

    def test_all_hospitals_one_month(self, client, db_session):
        hospitals = db_session.query(Hospital).all()[:2]
        ind = db_session.query(Indicator).first()
        for h in hospitals:
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind.id, month="2027-03", value=5.0))
            db_session.add(QualityScore(
                hospital_id=h.id, month="2027-03", score=10.0, issues="[]"))
        db_session.commit()

        resp = _remove(client, "2027-03", None)
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "all_hospitals"
        assert body["month_still_available"] is False
        for h in hospitals:
            assert db_session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == h.id,
                IndicatorValue.month == "2027-03",
            ).count() == 0
            assert db_session.query(QualityScore).filter(
                QualityScore.hospital_id == h.id,
                QualityScore.month == "2027-03",
            ).count() == 0

    def test_month_kept_when_another_hospital_still_has_it(self, client, db_session):
        h1, h2 = db_session.query(Hospital).all()[:2]
        ind = db_session.query(Indicator).first()
        for h in (h1, h2):
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind.id, month="2027-05", value=1.0))
            db_session.add(QualityScore(
                hospital_id=h.id, month="2027-05", score=10.0, issues="[]"))
        db_session.commit()

        resp = _remove(client, "2027-05", h1.id)
        assert resp.status_code == 200
        assert resp.json()["month_still_available"] is True

    def test_rejects_all_months(self, client):
        resp = _remove(client, "__all__", None)
        assert resp.status_code == 400

    def test_rejects_malformed_month(self, client):
        resp = _remove(client, "2027", None)
        assert resp.status_code == 400

    def test_noop_when_no_rows(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        resp = _remove(client, "2019-01", hospital.id)
        assert resp.status_code == 200
        body = resp.json()
        assert body["removed"]["indicator_values"] == 0
        assert body["recompute_task_id"] is None
        assert "nothing removed" in body["message"]

    def test_unknown_hospital(self, client):
        resp = _remove(client, "2027-01", 999999)
        assert resp.status_code == 404

    def test_derived_tables_all_cleared(self, client, db_session):
        """Anomalies, confidence and clinical rows must go too, not just scores."""
        hospital = db_session.query(Hospital).first()
        month = "2027-07"
        db_session.add(ValidationResult(
            hospital_id=hospital.id, month=month, rule_code="R1",
            rule_description="x", status="FAIL", severity="HIGH", details="d"))
        db_session.add(AnomalyResult(
            hospital_id=hospital.id, month=month, indicator_code="2",
            rate_name="r", value=1.0, is_outlier=True))
        db_session.add(ConfidenceScore(
            hospital_id=hospital.id, month=month, overall_confidence=0.5, level="MEDIUM"))
        db_session.add(ClinicalInsight(
            hospital_id=hospital.id, month=month, analysis_data="{}"))
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month=month, value=1.0))
        db_session.commit()

        resp = _remove(client, month, hospital.id)
        assert resp.status_code == 200
        removed = resp.json()["removed"]
        assert removed["validation_results"] == 1
        assert removed["anomaly_results"] == 1
        assert removed["confidence_scores"] == 1
        assert removed["clinical_insights"] == 1

        for model in (ValidationResult, AnomalyResult, ConfidenceScore, ClinicalInsight):
            assert db_session.query(model).filter(
                model.hospital_id == hospital.id, model.month == month).count() == 0

    def test_tree_node_set_unchanged_and_values_cleared(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-04", value=42.0))
        db_session.commit()

        url = f"/hospitals/{hospital.id}/indicator-tree?month=2027-04"
        before = client.get(url).json()
        codes_before = _tree_codes(before)

        assert _remove(client, "2027-04", hospital.id).status_code == 200

        after = client.get(url).json()
        assert _tree_codes(after) == codes_before
        assert all(v is None for v in _tree_values(after))


class TestUndoRemoveData:
    def test_undo_restores_the_deleted_month(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-01",
            value=12.5, source_file="jan.xlsx"))
        db_session.commit()

        removed = _remove(client, "2027-01", hospital.id).json()
        assert removed["removed"]["indicator_values"] == 1
        assert removed["undo"] and removed["undo"]["token"]
        assert removed["undo"]["rows"] == 1
        assert "Undo is available" in removed["message"]

        resp = _undo(client, removed["undo"]["token"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["restored"]["indicator_values"] == 1
        assert body["restored"]["skipped_existing"] == 0
        assert body["month"] == "2027-01"

        row = db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-01",
        ).one()
        assert row.value == 12.5
        assert row.source_file == "jan.xlsx"

    def test_undo_token_is_single_use(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-02", value=1.0))
        db_session.commit()

        token = _remove(client, "2027-02", hospital.id).json()["undo"]["token"]
        assert _undo(client, token).status_code == 200
        assert _undo(client, token).status_code == 404

    def test_undo_all_hospitals_restores_every_hospital(self, client, db_session):
        hospitals = db_session.query(Hospital).all()[:2]
        ind = db_session.query(Indicator).first()
        for h in hospitals:
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=ind.id, month="2027-03", value=8.0))
        db_session.commit()

        removed = _remove(client, "2027-03", None).json()
        assert removed["scope"] == "all_hospitals"
        assert removed["undo"]["rows"] == 2

        body = _undo(client, removed["undo"]["token"]).json()
        assert body["restored"]["indicator_values"] == 2
        for h in hospitals:
            assert db_session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == h.id,
                IndicatorValue.month == "2027-03",
            ).count() == 1

    def test_undo_skips_values_that_reappeared(self, client, db_session):
        """A re-upload between remove and undo must not be duplicated or clobbered."""
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-04", value=3.0))
        db_session.commit()

        token = _remove(client, "2027-04", hospital.id).json()["undo"]["token"]
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-04", value=99.0))
        db_session.commit()

        body = _undo(client, token).json()
        assert body["restored"]["indicator_values"] == 0
        assert body["restored"]["skipped_existing"] == 1
        rows = db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-04",
        ).all()
        assert len(rows) == 1
        assert rows[0].value == 99.0

    def test_undo_rejects_missing_and_unknown_tokens(self, client):
        assert client.post("/hospitals/remove-data/undo", json={}).status_code == 400
        assert _undo(client, "deadbeef").status_code == 404

    def test_no_snapshot_when_nothing_removed(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        body = _remove(client, "2019-05", hospital.id).json()
        assert body["undo"] is None


class TestClearDataUndo:
    """Clear Data must offer the same undo protection as Remove Data."""

    def test_clear_one_month_returns_a_restorable_snapshot(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-01",
            value=4.5, source_file="jan.xlsx"))
        db_session.add(QualityScore(
            hospital_id=hospital.id, month="2027-01", score=3.0, issues="[]"))
        db_session.commit()

        resp = _clear(client, hospital.id, "2027-01")
        assert resp.status_code == 200
        body = resp.json()
        assert body["month"] == "2027-01"
        assert body["months"] == ["2027-01"]
        assert body["removed"]["indicator_values"] == 1
        assert body["undo"] and body["undo"]["token"]
        assert body["undo"]["rows"] == 1
        assert "Undo is available" in body["message"]

        assert db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-01",
        ).count() == 0

        restored = _undo(client, body["undo"]["token"])
        assert restored.status_code == 200
        assert restored.json()["restored"]["indicator_values"] == 1
        row = db_session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == "2027-01",
        ).one()
        assert row.value == 4.5
        assert row.source_file == "jan.xlsx"

    def test_clear_all_months_restores_every_month(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        for m in ("2027-02", "2027-03"):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=ind.id, month=m, value=2.0))
        db_session.commit()

        body = _clear(client, hospital.id).json()
        assert body["month"] is None
        assert sorted(body["months"]) == ["2027-02", "2027-03"]
        assert body["undo"]["rows"] == 2

        restored = _undo(client, body["undo"]["token"]).json()
        assert restored["restored"]["indicator_values"] == 2
        assert restored["months"] == ["2027-02", "2027-03"]
        for m in ("2027-02", "2027-03"):
            assert db_session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == hospital.id,
                IndicatorValue.month == m,
            ).count() == 1

    def test_clear_undo_token_is_single_use(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-04", value=1.0))
        db_session.commit()

        token = _clear(client, hospital.id, "2027-04").json()["undo"]["token"]
        assert _undo(client, token).status_code == 200
        assert _undo(client, token).status_code == 404

    def test_clear_undo_skips_values_that_reappeared(self, client, db_session):
        """A re-upload between clear and undo must not be duplicated."""
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-05", value=3.0))
        db_session.commit()

        token = _clear(client, hospital.id, "2027-05").json()["undo"]["token"]
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-05", value=77.0))
        db_session.commit()

        body = _undo(client, token).json()
        assert body["restored"]["indicator_values"] == 0
        assert body["restored"]["skipped_existing"] == 1

    def test_clear_without_data_has_no_undo(self, client, db_session):
        hospital = db_session.query(Hospital).first()
        body = _clear(client, hospital.id, "2019-01").json()
        assert body["removed"]["indicator_values"] == 0
        assert body["undo"] is None

    def test_clear_recompute_skips_the_cleared_month(self, client, db_session, monkeypatch):
        """Surviving months are re-analysed; the cleared month never is."""
        import app.api.hospitals as hospitals_api

        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        for m in ("2027-06", "2027-07"):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=ind.id, month=m, value=9.0))
        db_session.commit()

        spawned = []

        class _RecordingThread:
            def __init__(self, target=None, args=(), daemon=None, **kwargs):
                spawned.append(args)

            def start(self):
                pass

        monkeypatch.setattr(hospitals_api.threading, "Thread", _RecordingThread)

        body = _clear(client, hospital.id, "2027-06", recompute=True).json()
        assert body["recompute_task_id"]
        assert spawned, "expected a background recompute worker"
        pairs = spawned[0][2]
        assert (hospital.id, "2027-07") in pairs
        assert all(m != "2027-06" for _hid, m in pairs)


class TestUndoStore:
    def test_expired_snapshot_is_unavailable(self, monkeypatch):
        from app import undo_store

        rows = [{"hospital_id": 1, "indicator_id": 1, "month": "2027-01", "value": 1.0}]
        monkeypatch.setattr(undo_store, "TTL_SECONDS", 600)
        descriptor = undo_store.create(rows, {"month": "2027-01"})
        assert undo_store.get(descriptor["token"]) is not None

        monkeypatch.setattr(undo_store, "TTL_SECONDS", -1)
        stale = undo_store.create(rows, {"month": "2027-01"})
        assert undo_store.get(stale["token"]) is None

    def test_oversized_snapshot_is_refused(self, monkeypatch):
        from app import undo_store

        monkeypatch.setattr(undo_store, "MAX_ROWS", 2)
        rows = [{"hospital_id": 1, "indicator_id": i, "month": "2027-01"} for i in range(3)]
        assert undo_store.create(rows, {}) is None
        assert undo_store.create(rows[:2], {})["rows"] == 2

    def test_oldest_snapshot_evicted(self, monkeypatch):
        from app import undo_store

        monkeypatch.setattr(undo_store, "MAX_SNAPSHOTS", 1)
        first = undo_store.create([{"hospital_id": 1, "indicator_id": 1, "month": "2027-01"}], {})
        second = undo_store.create([{"hospital_id": 1, "indicator_id": 2, "month": "2027-02"}], {})
        assert undo_store.get(first["token"]) is None
        assert undo_store.get(second["token"]) is not None

    def test_drop_removes_snapshot(self):
        from app import undo_store

        descriptor = undo_store.create([{"hospital_id": 1, "indicator_id": 1, "month": "2027-01"}], {})
        undo_store.drop(descriptor["token"])
        assert undo_store.get(descriptor["token"]) is None


class TestRecomputeHelper:
    def test_recompute_refreshes_rows(self, db_session):
        from app.engine.pipeline import recompute_hospital_months

        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        db_session.add(IndicatorValue(
            hospital_id=hospital.id, indicator_id=ind.id, month="2027-06", value=10.0))
        db_session.add(QualityScore(
            hospital_id=hospital.id, month="2027-06", score=1.0, issues="[]"))
        db_session.commit()

        done = recompute_hospital_months(db_session, hospital.id, ["2027-06"])
        assert done == 1
        rows = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == hospital.id,
            QualityScore.month == "2027-06",
        ).all()
        assert len(rows) == 1                  # upsert, never duplicated
        assert rows[0].score != 1.0            # stale marker replaced

    def test_recompute_defaults_to_all_months_with_values(self, db_session):
        from app.engine.pipeline import recompute_hospital_months

        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).first()
        for month in ("2027-08", "2027-09"):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=ind.id, month=month, value=7.0))
        db_session.commit()

        done = recompute_hospital_months(db_session, hospital.id)
        assert done == 2
