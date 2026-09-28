# -*- coding: utf-8 -*-
"""Never-reported indicators: one-click disable for ghost completeness gaps.

After every new import, indicators the SRMNH form carries but no hospital ever
reports (16 NICU admissions, 2.k, 2.l, 11.a, 11.b, 12, 21, 26, ...) resurface
in missing-indicator lists and drag completeness down for every hospital/month.

The synthetic form-header label code "0" ("Main elements complete ratio") is
NOT among them — it is already hidden by SYNTHETIC_INDICATOR_CODES and never
counts as missing. These tests lock both behaviours.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import Hospital, HospitalIndicatorConfig, Indicator, IndicatorValue


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


def _add_values(db_session, code, months=("2026-01",), value=10):
    ind = db_session.query(Indicator).filter(Indicator.code == code).first()
    hosp = db_session.query(Hospital).first()
    for m in months:
        db_session.add(IndicatorValue(
            hospital_id=hosp.id, indicator_id=ind.id, month=m, value=value,
        ))
    db_session.commit()


class TestNeverReportedListing:
    def test_seeded_db_lists_never_reported_excluding_synthetic(self, client, db_session):
        """Fresh seeds: NICU admissions (16) and friends appear, code "0" does not."""
        resp = client.get("/hospitals/indicators/never-reported")
        assert resp.status_code == 200
        data = resp.json()
        codes = {i["code"] for i in data["indicators"]}
        assert "16" in codes          # NICU admissions — the reported complaint
        assert "0" not in codes       # synthetic label is never listed
        assert data["count"] == len(data["indicators"])

    def test_reported_indicators_are_excluded(self, client, db_session):
        """An indicator with at least one value row is never listed."""
        _add_values(db_session, "16", months=("2026-03",))
        resp = client.get("/hospitals/indicators/never-reported")
        codes = {i["code"] for i in resp.json()["indicators"]}
        assert "16" not in codes


class TestDisableNeverReported:
    def test_dry_run_writes_nothing(self, client, db_session):
        resp = client.post("/hospitals/indicators/disable-never-reported?dry_run=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert body["count"] > 0
        rows = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.is_enabled.is_(False)
        ).all()
        assert rows == []

    def test_disable_creates_config_rows_for_all_hospitals(self, client, db_session):
        resp = client.post("/hospitals/indicators/disable-never-reported")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is False
        codes = {d["code"] for d in body["disabled"]}
        assert "16" in codes and "0" not in codes

        disabled_ids = {
            c.indicator_id for c in db_session.query(HospitalIndicatorConfig).filter(
                HospitalIndicatorConfig.is_enabled.is_(False)
            ).all()
        }
        nicu = db_session.query(Indicator).filter(Indicator.code == "16").first()
        assert nicu.id in disabled_ids
        n_hospitals = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).count()
        n_disabled_for_nicu = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == nicu.id,
            HospitalIndicatorConfig.is_enabled.is_(False),
        ).count()
        assert n_disabled_for_nicu == n_hospitals

    def test_disable_skips_already_disabled(self, client, db_session):
        """A second run re-enables nothing and stays idempotent."""
        client.post("/hospitals/indicators/disable-never-reported")
        resp = client.post("/hospitals/indicators/disable-never-reported")
        assert resp.status_code == 200
        nicu = db_session.query(Indicator).filter(Indicator.code == "16").first()
        still_disabled = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == nicu.id,
            HospitalIndicatorConfig.is_enabled.is_(False),
        ).count()
        n_hospitals = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).count()
        assert still_disabled == n_hospitals

    def test_reported_indicator_not_disabled(self, client, db_session):
        """Indicators with data keep working after the bulk disable."""
        _add_values(db_session, "16", months=("2026-01", "2026-02"))
        resp = client.post("/hospitals/indicators/disable-never-reported")
        codes = {d["code"] for d in resp.json()["disabled"]}
        assert "16" not in codes
        nicu = db_session.query(Indicator).filter(Indicator.code == "16").first()
        rows = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == nicu.id
        ).all()
        assert rows == []
