"""The hospital-month audit trail: who enabled/disabled a month, and when.

The setting itself only ever holds the latest value, so the trail is what makes
a hidden month explainable after the fact. These tests pin three guarantees:
one row per REAL change (re-saving the same value records nothing), the acting
user and timestamp are stored, and the read endpoint filters/orders correctly.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.models import Hospital, HospitalMonthAudit, SystemSetting, User


@pytest.fixture()
def client(app):
    """TestClient over the conftest app — `_bypass_auth` already overrides
    get_current_user (superadmin) and get_db (db_session)."""
    return TestClient(app)


@pytest.fixture()
def hospital(db_session):
    return db_session.query(Hospital).order_by(Hospital.id).first()


def _put(client, hospital_id, month, enabled):
    return client.put("/config/month-settings",
                      json={"hospital_id": hospital_id, "month": month,
                            "enabled": enabled})


def _rows(db_session):
    return (db_session.query(HospitalMonthAudit)
            .order_by(HospitalMonthAudit.id).all())


def test_disabling_a_month_records_who_and_when(client, db_session, hospital):
    response = _put(client, hospital.id, "2026-03", False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["changed"] is True
    assert body["previous_state"] == "unset"

    rows = _rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.hospital_id == hospital.id
    assert row.hospital_name == hospital.name
    assert row.month == "2026-03"
    assert row.action == "disabled"
    assert row.previous_state == "unset", \
        "a first disable must say the month was on by default"
    assert row.actor == "testadmin"
    assert row.actor_id == 99999
    assert row.created_at is not None

    setting = (db_session.query(SystemSetting)
               .filter(SystemSetting.key == f"month_enabled_{hospital.id}_2026-03")
               .one())
    assert setting.value == "false"


def test_repeating_the_same_value_records_nothing(client, db_session, hospital):
    assert _put(client, hospital.id, "2026-03", False).json()["changed"] is True
    again = _put(client, hospital.id, "2026-03", False)
    assert again.status_code == 200
    assert again.json()["changed"] is False
    assert len(_rows(db_session)) == 1, "a no-op save is not a change"

    # Enabling an untouched month (no setting row) is also not a change.
    fresh = _put(client, hospital.id, "2026-04", True)
    assert fresh.json()["changed"] is False
    assert len(_rows(db_session)) == 1


def test_enabling_after_disable_records_the_previous_state(client, db_session,
                                                           hospital):
    _put(client, hospital.id, "2026-03", False)
    enabled = _put(client, hospital.id, "2026-03", True)
    assert enabled.json()["changed"] is True
    assert enabled.json()["previous_state"] == "disabled"

    rows = _rows(db_session)
    assert [r.action for r in rows] == ["disabled", "enabled"]
    assert rows[1].previous_state == "disabled"


def test_audit_endpoint_filters_and_orders_newest_first(client, db_session,
                                                        hospital):
    other = (db_session.query(Hospital)
             .filter(Hospital.id != hospital.id).first())
    _put(client, hospital.id, "2026-05", False)
    _put(client, hospital.id, "2026-06", False)
    _put(client, other.id, "2026-05", False)

    everything = client.get("/config/month-settings/audit").json()
    assert len(everything) == 3
    ids = [entry["id"] for entry in everything]
    assert ids == sorted(ids, reverse=True), "newest change first"

    mine = client.get("/config/month-settings/audit",
                      params={"hospital_id": hospital.id}).json()
    assert {entry["month"] for entry in mine} == {"2026-05", "2026-06"}
    assert {entry["hospital"] for entry in mine} == {hospital.name}

    one = client.get("/config/month-settings/audit",
                     params={"hospital_id": hospital.id, "month": "2026-05"}).json()
    assert len(one) == 1
    assert {k: one[0][k] for k in ("month", "action", "actor", "previous_state")} == {
        "month": "2026-05", "action": "disabled",
        "actor": "testadmin", "previous_state": "unset"}

    newest = client.get("/config/month-settings/audit",
                        params={"limit": 1}).json()
    assert [entry["id"] for entry in newest] == [everything[0]["id"]]


def test_a_quoted_false_disables_and_is_audited(client, db_session, hospital):
    """Only an explicit false disables the month — a JSON string too."""
    response = client.put("/config/month-settings", json={
        "hospital_id": hospital.id, "month": "2026-07", "enabled": "false"})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    setting = (db_session.query(SystemSetting)
               .filter(SystemSetting.key == f"month_enabled_{hospital.id}_2026-07")
               .one())
    assert setting.value == "false"
    assert [r.action for r in _rows(db_session)] == ["disabled"]


def test_rejections_leave_no_setting_and_no_audit_row(client, db_session,
                                                      hospital):
    before_rows = len(_rows(db_session))
    before_settings = db_session.query(SystemSetting).count()

    missing = _put(client, 9999999, "2026-03", False)
    assert missing.status_code == 404

    bad_month = _put(client, hospital.id, "all", False)
    assert bad_month.status_code == 400

    bad_hospital = client.put("/config/month-settings", json={
        "hospital_id": "not-an-id", "month": "2026-03", "enabled": False})
    assert bad_hospital.status_code == 400

    assert len(_rows(db_session)) == before_rows
    assert db_session.query(SystemSetting).count() == before_settings


def test_the_trail_records_the_real_account_not_the_request(
        client, db_session, hospital, app):
    """`who` is the authenticated user behind the write, not client input."""
    actor = User(username="month.auditor", email="month@example.test",
                 full_name="Month Auditor", password_hash="x",
                 is_active=True, is_superuser=True)
    db_session.add(actor)
    db_session.commit()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        assert _put(client, hospital.id, "2026-08", False).status_code == 200
    finally:
        if previous is not None:
            app.dependency_overrides[get_current_user] = previous
        else:
            app.dependency_overrides.pop(get_current_user, None)

    row = _rows(db_session)[-1]
    assert row.actor == "month.auditor"
    assert row.actor_id == actor.id
