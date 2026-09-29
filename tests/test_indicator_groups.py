# -*- coding: utf-8 -*-
"""Indicator Groups feature tests (design rev 2).

Covers the acceptance criteria that live in the backend:
  * CRUD + member management with exclusive membership (eviction)
  * bulk toggle for both scopes writing the RIGHT config tables
  * the hospital-scope month-agnostic hard constraint (422)
  * derived group state with no stored is_enabled flag
  * requirement_type exclusion from the completeness denominator at the
    dashboard recalc and per-hospital recalc call sites
  * idempotent toggling
  * impact preview denominator math: predicted before/after denominators
    must equal what a REAL toggle produces (requirement_type, the
    auto_disable_null_indicators setting, and hospital-override shielding
    all accounted for)
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorGroup,
    IndicatorGroupMember,
    IndicatorValue,
    QualityScore,
)


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


def _iid(db, code):
    ind = db.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    return ind.id


class TestGroupCrud:
    def test_create_and_get_group(self, client, db_session):
        resp = client.post("/indicator-groups", json={
            "name": "Maternal Health",
            "scope_type": "all",
            "month_from": "2026-01",
            "month_to": "2026-12",
            "indicator_ids": [_iid(db_session, "10"), _iid(db_session, "11"), _iid(db_session, "12")],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["member_count"] == 3
        assert body["is_enabled"] is True
        assert [m["indicator_code"] for m in body["members"]] == ["10", "11", "12"]

        detail = client.get(f"/indicator-groups/{body['id']}").json()
        assert detail["name"] == "Maternal Health"

    def test_duplicate_name_rejected(self, client, db_session):
        client.post("/indicator-groups", json={"name": "Dup", "scope_type": "all"})
        resp = client.post("/indicator-groups", json={"name": "Dup", "scope_type": "all"})
        assert resp.status_code == 400

    def test_scope_all_with_hospital_rejected(self, client):
        resp = client.post("/indicator-groups", json={"name": "X", "scope_type": "all", "hospital_id": 1})
        assert resp.status_code == 422

    def test_hospital_scope_without_hospital_rejected(self, client):
        resp = client.post("/indicator-groups", json={"name": "X", "scope_type": "hospital"})
        assert resp.status_code == 422

    def test_bad_month_format_rejected(self, client):
        resp = client.post("/indicator-groups", json={
            "name": "X", "scope_type": "all", "month_from": "2026-13",
        })
        assert resp.status_code == 422

    def test_hospital_scope_with_month_range_rejected(self, client, db_session):
        """HARD CONSTRAINT: hospital overrides are month-agnostic — a range
        on a hospital-scoped group can never apply, so creation is a 422."""
        hosp = db_session.query(Hospital).first()
        resp = client.post("/indicator-groups", json={
            "name": "NICU", "scope_type": "hospital", "hospital_id": hosp.id,
            "month_from": "2026-03",
        })
        assert resp.status_code == 422
        assert "month" in resp.json()["detail"].lower()

    def test_update_group(self, client, db_session):
        gid = client.post("/indicator-groups", json={"name": "G1", "scope_type": "all"}).json()["id"]
        resp = client.put(f"/indicator-groups/{gid}", json={"description": "updated"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "updated"

    def test_delete_group_keeps_config_rows(self, client, db_session):
        """Deleting the macro must never undo the configs its toggle wrote."""
        gid = client.post("/indicator-groups", json={
            "name": "Deletable", "scope_type": "all", "month_from": "2026-07",
            "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert db_session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.indicator_id == _iid(db_session, "10"),
        ).count() > 0

        resp = client.delete(f"/indicator-groups/{gid}")
        assert resp.status_code == 200
        assert db_session.query(IndicatorDefaultConfig).count() > 0


class TestBulkToggleAllScope:
    def test_toggle_off_writes_default_configs_for_range(self, client, db_session):
        ids = [_iid(db_session, c) for c in ("10", "11", "12")]
        gid = client.post("/indicator-groups", json={
            "name": "Maternal", "scope_type": "all",
            "month_from": "2026-01", "month_to": "2026-03",
            "indicator_ids": ids,
        }).json()["id"]

        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["months"] == ["2026-01", "2026-02", "2026-03"]

        rows = db_session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.indicator_id.in_(ids),
        ).all()
        assert len(rows) == 9  # 3 indicators × 3 months
        assert all(not r.is_enabled for r in rows)

    def test_toggle_is_idempotent(self, client, db_session):
        gid = client.post("/indicator-groups", json={
            "name": "Idem", "scope_type": "all", "month_from": "2026-05",
            "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        body = resp.json()
        assert body["enabled"] is False
        assert body["config_rows"] == 0  # second pass changes nothing

    def test_toggle_on_reenables(self, client, db_session):
        gid = client.post("/indicator-groups", json={
            "name": "ReEn", "scope_type": "all", "month_from": "2026-02",
            "indicator_ids": [_iid(db_session, "16")],
        }).json()["id"]
        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": True})
        assert resp.json()["enabled"] is True
        cfg = db_session.query(IndicatorDefaultConfig).filter(
            IndicatorDefaultConfig.indicator_id == _iid(db_session, "16"),
        ).first()
        assert cfg.is_enabled is True

    def test_empty_range_uses_known_months(self, client, db_session):
        """No range → every month known to the DB (toggle-default __all__ fallback)."""
        db_session.add(IndicatorValue(hospital_id=1, indicator_id=_iid(db_session, "10"), month="2027-01", value=5))
        db_session.commit()
        db_session.add(IndicatorDefaultConfig(indicator_id=_iid(db_session, "11"), month="2027-02", is_enabled=True))
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "AllMonths", "scope_type": "all",
            "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        # Known months = value months ∪ default-config months (same union as
        # _all_known_months used by toggle-default month='__all__').
        assert resp.json()["months"] == ["2027-01", "2027-02"]

    def test_empty_group_rejected(self, client):
        gid = client.post("/indicator-groups", json={"name": "Empty", "scope_type": "all"}).json()["id"]
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert resp.status_code == 400


class TestBulkToggleHospitalScope:
    def test_toggle_writes_hospital_configs_only(self, client, db_session):
        hosp = db_session.query(Hospital).first()
        other = db_session.query(Hospital).filter(Hospital.id != hosp.id).first()
        gid = client.post("/indicator-groups", json={
            "name": "NICU-A", "scope_type": "hospital", "hospital_id": hosp.id,
            "indicator_ids": [_iid(db_session, "16")],
        }).json()["id"]
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert resp.status_code == 200

        rows = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.indicator_id == _iid(db_session, "16"),
        ).all()
        assert len(rows) == 1
        assert rows[0].hospital_id == hosp.id
        assert rows[0].is_enabled is False
        # Other hospital untouched (no rows at all).
        assert db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == other.id,
        ).all() == []

    def test_hospital_toggle_ignores_stored_range_guard(self, client, db_session):
        """A hospital group (rangeless by construction) toggles fine and stays month-agnostic."""
        hosp = db_session.query(Hospital).first()
        gid = client.post("/indicator-groups", json={
            "name": "HOnly", "scope_type": "hospital", "hospital_id": hosp.id,
            "indicator_ids": [_iid(db_session, "17")],
        }).json()["id"]
        resp = client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert resp.status_code == 200
        assert "month" not in resp.json()


class TestExclusiveMembership:
    def test_adding_to_second_group_evicts_from_first(self, client, db_session):
        g1 = client.post("/indicator-groups", json={
            "name": "One", "scope_type": "all", "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        g2 = client.post("/indicator-groups", json={
            "name": "Two", "scope_type": "all", "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]

        assert db_session.query(IndicatorGroupMember).filter(
            IndicatorGroupMember.group_id == g1,
        ).count() == 0, "indicator must be evicted from the first group"
        assert db_session.query(IndicatorGroupMember).filter(
            IndicatorGroupMember.group_id == g2,
        ).count() == 1

    def test_add_members_endpoint_evicts_too(self, client, db_session):
        g1 = client.post("/indicator-groups", json={
            "name": "A", "scope_type": "all", "indicator_ids": [_iid(db_session, "11")],
        }).json()["id"]
        g2 = client.post("/indicator-groups", json={"name": "B", "scope_type": "all"}).json()["id"]
        resp = client.post(f"/indicator-groups/{g2}/members", json={"indicator_ids": [_iid(db_session, "11")]})
        assert resp.status_code == 200
        assert db_session.query(IndicatorGroupMember).filter(
            IndicatorGroupMember.group_id == g1,
        ).count() == 0

    def test_unknown_indicator_rejected(self, client):
        g = client.post("/indicator-groups", json={"name": "U", "scope_type": "all"}).json()["id"]
        resp = client.post(f"/indicator-groups/{g}/members", json={"indicator_ids": [999999]})
        assert resp.status_code == 404

    def test_remove_member_and_reorder(self, client, db_session):
        ids = [_iid(db_session, c) for c in ("10", "11", "12")]
        g = client.post("/indicator-groups", json={
            "name": "R", "scope_type": "all", "indicator_ids": ids,
        }).json()["id"]
        resp = client.delete(f"/indicator-groups/{g}/members/{ids[0]}")
        assert resp.status_code == 200
        resp = client.put(f"/indicator-groups/{g}/members/reorder",
                          json={"indicator_ids": [ids[2], ids[1]]})
        assert resp.status_code == 200
        detail = client.get(f"/indicator-groups/{g}").json()
        assert [m["indicator_id"] for m in detail["members"]] == [ids[2], ids[1]]


class TestDerivedState:
    def test_list_reflects_toggle_without_stored_flag(self, client, db_session):
        """is_enabled must derive from config rows: toggling a member updates it."""
        gid = client.post("/indicator-groups", json={
            "name": "Derived", "scope_type": "all", "month_from": "2026-04",
            "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        assert client.get("/indicator-groups").json()[0]["is_enabled"] is True

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})  # noqa: range known
        assert client.get("/indicator-groups").json()[0]["is_enabled"] is False
        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": True})
        assert client.get("/indicator-groups").json()[0]["is_enabled"] is True

    def test_single_indicator_edit_updates_derived_state(self, client, db_session):
        """Rev 2 rationale: a stored flag would go stale here; derived state does not."""
        gid = client.post("/indicator-groups", json={
            "name": "Stale", "scope_type": "all", "month_from": "2026-06",
            "indicator_ids": [_iid(db_session, "10")],
        }).json()["id"]
        # Toggle ONE member directly (outside the group).
        client.put(f"/hospitals/indicators/{_iid(db_session, '10')}/toggle-default?month=2026-06")
        assert client.get("/indicator-groups").json()[0]["is_enabled"] is False

    def test_hospital_scope_derived_state(self, client, db_session):
        hosp = db_session.query(Hospital).first()
        gid = client.post("/indicator-groups", json={
            "name": "HDerived", "scope_type": "hospital", "hospital_id": hosp.id,
            "indicator_ids": [_iid(db_session, "12")],
        }).json()["id"]
        db_session.add(HospitalIndicatorConfig(
            hospital_id=hosp.id, indicator_id=_iid(db_session, "12"), is_enabled=False,
        ))
        db_session.commit()
        assert client.get("/indicator-groups").json()[0]["is_enabled"] is False


class TestRequirementType:
    def test_set_endpoint_validates(self, client, db_session):
        ind_id = _iid(db_session, "10")
        resp = client.put(f"/hospitals/indicators/{ind_id}/requirement-type",
                          json={"requirement_type": "Bogus"})
        assert resp.status_code == 422
        resp = client.put(f"/hospitals/indicators/{ind_id}/requirement-type",
                          json={"requirement_type": "Optional"})
        assert resp.status_code == 200
        assert db_session.query(Indicator).get(ind_id).requirement_type == "Optional"

    def test_optional_excluded_from_dashboard_recalc_denominator(self, client, db_session):
        """Optional indicator missing its value must NOT drag completeness down."""
        from app.models import IndicatorValue
        code = "12"
        ind_id = _iid(db_session, code)
        # Hospital 1 reports everything except indicator 12 in this month.
        for other in db_session.query(Indicator).filter(Indicator.code != "0").all():
            if other.code == code:
                continue
            db_session.add(IndicatorValue(hospital_id=1, indicator_id=other.id, month="2027-09", value=1))
        db_session.add(QualityScore(hospital_id=1, month="2027-09", score=50.0))
        db_session.commit()

        client.post("/dashboard/recalculate-completeness")
        qs_required = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == 1, QualityScore.month == "2027-09",
        ).first()
        completeness_required = qs_required.completeness

        # Mark it Optional → the gap vanishes from the denominator.
        client.put(f"/hospitals/indicators/{ind_id}/requirement-type",
                   json={"requirement_type": "Optional"})
        qs_optional = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == 1, QualityScore.month == "2027-09",
        ).first()
        assert qs_optional.completeness > completeness_required
        # And restoring Required brings the gap back.
        client.put(f"/hospitals/indicators/{ind_id}/requirement-type",
                   json={"requirement_type": "Required"})
        qs_back = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == 1, QualityScore.month == "2027-09",
        ).first()
        assert qs_back.completeness == completeness_required

    def test_optional_excluded_from_hospital_recalc_denominator(self, db_session):
        from app.api.indicator_config import _recalc_hospital_scores
        from app.models import IndicatorValue

        missing = _iid(db_session, "12")
        for other in db_session.query(Indicator).filter(Indicator.code != "0").all():
            if other.id == missing:
                continue
            db_session.add(IndicatorValue(hospital_id=2, indicator_id=other.id, month="2027-10", value=1))
        db_session.add(QualityScore(hospital_id=2, month="2027-10", score=50.0))
        db_session.commit()
        _recalc_hospital_scores(db_session, 2)
        before = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == 2, QualityScore.month == "2027-10",
        ).first().completeness

        db_session.query(Indicator).filter(Indicator.id == missing).update(
            {"requirement_type": "Optional"}, synchronize_session=False)
        db_session.commit()
        _recalc_hospital_scores(db_session, 2)
        after = db_session.query(QualityScore).filter(
            QualityScore.hospital_id == 2, QualityScore.month == "2027-10",
        ).first().completeness
        assert after > before

    def test_pipeline_helper_filters_optional_and_disabled(self, db_session):
        from app.engine.pipeline import get_required_indicator_ids
        missing = _iid(db_session, "12")
        db_session.query(Indicator).filter(Indicator.id == missing).update(
            {"requirement_type": "Optional"}, synchronize_session=False)
        db_session.commit()
        required = get_required_indicator_ids(db_session, hospital_id=1, month="2027-11")
        assert missing not in required
        # All defaults are Required → everything enabled counts.
        db_session.query(Indicator).filter(Indicator.id == missing).update(
            {"requirement_type": "Required"}, synchronize_session=False)
        db_session.commit()
        required = get_required_indicator_ids(db_session, hospital_id=1, month="2027-11")
        assert missing in required


class TestImpactPreviewDenominatorMath:
    """Regression: the impact preview's predicted denominators must equal what
    a REAL toggle produces. The first cut of the preview ignored requirement_type
    and the auto_disable_null_indicators setting, so it predicted a −4/hospital
    completeness drop for a disable whose real effect was +4.
    """

    def _preview_completeness(self, client, gid, enabled, hospital_id=None):
        url = f"/indicator-groups/{gid}/impact?enabled={'true' if enabled else 'false'}"
        if hospital_id is not None:
            url += f"&hospital_id={hospital_id}"
        return client.get(url).json()["completeness"]

    def _real_denominator(self, db, hospital_id, month):
        from app.engine.pipeline import get_required_indicator_ids
        return len(get_required_indicator_ids(db, hospital_id, month))

    def test_disable_prediction_matches_real_toggle(self, client, db_session):
        """Plain Required members, auto-disable OFF: before/after predicted == real."""
        ids = [_iid(db_session, c) for c in ("10", "11")]
        db_session.add(IndicatorValue(hospital_id=1, indicator_id=ids[0], month="2027-01", value=5))
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "PlainDisable", "scope_type": "all",
            "indicator_ids": ids,
        }).json()["id"]

        real_before = self._real_denominator(db_session, 1, "2027-01")
        comp = self._preview_completeness(client, gid, False, hospital_id=1)
        assert comp["per_hospital"][0]["hospital_id"] == 1
        assert comp["per_hospital"][0]["before"] == real_before
        assert comp["per_hospital"][0]["after"] == real_before - 2

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        real_after = self._real_denominator(db_session, 1, "2027-01")
        assert comp["per_hospital"][0]["after"] == real_after

    def test_optional_member_never_counts(self, client, db_session):
        """An Optional member is outside the denominator BEFORE and AFTER the
        toggle — disabling it must predict zero denominator change."""
        ids = [_iid(db_session, c) for c in ("10", "11")]
        db_session.add(IndicatorValue(hospital_id=1, indicator_id=ids[0], month="2027-05", value=5))
        db_session.query(Indicator).filter(Indicator.id == ids[1]).update(
            {"requirement_type": "Optional"}, synchronize_session=False)
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "OptionalMember", "scope_type": "all",
            "indicator_ids": ids,
        }).json()["id"]

        real_before = self._real_denominator(db_session, 1, "2027-05")
        comp = self._preview_completeness(client, gid, False, hospital_id=1)
        assert comp["per_hospital"][0]["before"] == real_before
        # Only member 10 leaves the denominator — the Optional member was
        # never in it, so it contributes no delta.
        assert comp["per_hospital"][0]["after"] == real_before - 1

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        assert self._real_denominator(db_session, 1, "2027-05") == real_before - 1
        assert comp["per_hospital"][0]["after"] == self._real_denominator(db_session, 1, "2027-05")

    def test_auto_disable_null_means_null_members_predict_zero_change(self, client, db_session):
        """With auto_disable_null_indicators ON, a null-row member and a
        no-row member are ALREADY outside the denominator — the preview must
        predict zero change (the live miss this regression pins down)."""
        from app.models import SystemSetting
        db_session.add(SystemSetting(key="auto_disable_null_indicators", value="true"))
        ids = [_iid(db_session, c) for c in ("10", "11")]
        # Hospital 1 @ 2027-02: member 10 has a NULL row, member 11 has NO row.
        db_session.add(IndicatorValue(hospital_id=1, indicator_id=ids[0], month="2027-02", value=None))
        for ind in db_session.query(Indicator).all():
            if ind.id in ids:
                continue
            db_session.add(IndicatorValue(hospital_id=1, indicator_id=ind.id, month="2027-02", value=5))
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "AutoNull", "scope_type": "all",
            "indicator_ids": ids,
        }).json()["id"]

        real_before = self._real_denominator(db_session, 1, "2027-02")
        comp = self._preview_completeness(client, gid, False, hospital_id=1)
        assert comp["per_hospital"][0]["before"] == real_before
        assert comp["per_hospital"][0]["after"] == real_before  # zero predicted change

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        real_after = self._real_denominator(db_session, 1, "2027-02")
        assert real_after == real_before
        assert comp["per_hospital"][0]["after"] == real_after

    def test_hospital_override_shields_member_from_default_toggle(self, client, db_session):
        """A hospital override outranks the defaults a scope-'all' toggle writes:
        the overridden member must not change that hospital's denominator."""
        ids = [_iid(db_session, c) for c in ("10", "11")]
        db_session.add(IndicatorValue(hospital_id=1, indicator_id=ids[0], month="2027-03", value=5))
        db_session.add(HospitalIndicatorConfig(hospital_id=1, indicator_id=ids[0], is_enabled=False))
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "Shielded", "scope_type": "all",
            "indicator_ids": ids,
        }).json()["id"]

        real_before = self._real_denominator(db_session, 1, "2027-03")
        comp = self._preview_completeness(client, gid, False, hospital_id=1)
        # Only member 11 can change for hospital 1 — the override pins 10 off.
        assert comp["per_hospital"][0]["before"] == real_before
        assert comp["per_hospital"][0]["after"] == real_before - 1

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        real_after = self._real_denominator(db_session, 1, "2027-03")
        assert real_after == real_before - 1
        assert comp["per_hospital"][0]["after"] == real_after

    def test_hospital_scope_prediction_matches_real_toggle(self, client, db_session):
        """Hospital-scope groups: month-agnostic override rows, latest month sampled."""
        iid16 = _iid(db_session, "16")
        db_session.add(IndicatorValue(hospital_id=2, indicator_id=iid16, month="2027-04", value=5))
        db_session.commit()
        gid = client.post("/indicator-groups", json={
            "name": "HospScope", "scope_type": "hospital", "hospital_id": 1,
            "indicator_ids": [iid16],
        }).json()["id"]

        real_before = self._real_denominator(db_session, 1, "2027-04")
        comp = self._preview_completeness(client, gid, False)
        assert comp["per_hospital"][0]["before"] == real_before
        assert comp["per_hospital"][0]["after"] == real_before - 1

        client.put(f"/indicator-groups/{gid}/toggle", json={"enabled": False})
        real_after = self._real_denominator(db_session, 1, "2027-04")
        assert real_after == real_before - 1
        assert comp["per_hospital"][0]["after"] == real_after
        row = db_session.query(HospitalIndicatorConfig).filter(
            HospitalIndicatorConfig.hospital_id == 1,
            HospitalIndicatorConfig.indicator_id == iid16,
        ).first()
        assert row is not None and row.is_enabled is False
