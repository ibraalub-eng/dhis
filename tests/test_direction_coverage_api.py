"""Direction Coverage screen: gap list, suggestions and reviewed bulk apply.

The screen exists because an alert can only say whether a deviation is good or
bad when the indicator carries a direction. These tests pin:

* the list contains only indicators with NO recorded direction,
* the order is by ACTIVE alerts (archived rows never count),
* a suggestion always names its basis and is never invented: a guideline, a
  numerator role, or an explicit "no basis",
* bulk apply writes families on their representative definition (with the
  version audit) and raw elements on the element (with the direction audit),
  skips no-ops, and rejects an invalid batch before writing anything.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorDefinitionVersion,
    IndicatorDirectionHistory,
    QualityAlert,
)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def coverage_dataset(db_session):
    """One directed-by-guideline family, its numerator and denominator, and an
    unrelated element with the most active alerts."""
    family = IndicatorDefinition(
        code="DC_CS_RATE",
        name="DC C-Section Rate",
        legacy_code="rate_cs",
        formula_type="ratio",
        numerator_codes=["DC_CS_NUM"],
        denominator_codes=["DC_DELIVERIES"],
        operator="/",
        multiplier=100.0,
        result_type="percentage",
        unit="%",
        is_active=True,
    )
    other = IndicatorDefinition(
        code="DC_OTHER_RATE",
        name="DC Unmapped Rate",
        formula_type="ratio",
        numerator_codes=["DC_OTHER_NUM"],
        denominator_codes=["DC_DELIVERIES"],
        operator="/",
        multiplier=100.0,
        result_type="percentage",
        unit="%",
        is_active=True,
    )
    num = Indicator(code="DC_CS_NUM", name="DC caesareans")
    den = Indicator(code="DC_DELIVERIES", name="DC deliveries")
    other_num = Indicator(code="DC_OTHER_NUM", name="DC other numerator")
    unrelated = Indicator(code="DC_UNRELATED", name="DC unrelated count")
    db_session.add_all([family, other, num, den, other_num, unrelated])
    db_session.flush()

    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    months = ["2026-01", "2026-02", "2026-03"]
    for index, month in enumerate(months):
        db_session.add(QualityAlert(
            hospital_id=hospital.id, month=month, perspective="history",
            indicator_code="DC_CS_RATE", indicator_name="DC C-Section Rate",
            severity="HIGH", method="zscore", active=True,
        ))
    # Archived rows are not "affected alerts" any more.
    db_session.add(QualityAlert(
        hospital_id=hospital.id, month="2025-12", perspective="history",
        indicator_code="DC_CS_RATE", indicator_name="DC C-Section Rate",
        severity="HIGH", method="zscore", active=False,
    ))
    for index in range(5):
        db_session.add(QualityAlert(
            hospital_id=hospital.id, month=months[index % 3],
            perspective="perspective_%d" % index,
            indicator_code="DC_UNRELATED", indicator_name="DC unrelated count",
            severity="MODERATE", method="zscore", active=True,
        ))
    db_session.add(QualityAlert(
        hospital_id=hospital.id, month="2026-01", perspective="history",
        indicator_code="DC_DELIVERIES", indicator_name="DC deliveries",
        severity="LOW", method="zscore", active=True,
    ))
    db_session.commit()
    return {"family": family, "other": other, "num": num, "den": den,
            "other_num": other_num, "unrelated": unrelated,
            "hospital": hospital}


def _items(client):
    resp = client.get("/direction-coverage")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_code(payload):
    return {item["code"]: item for item in payload["items"]}


# ── list + suggestions ──────────────────────────────────────────────────────

def test_list_order_and_scope_use_active_alerts_only(client, db_session,
                                                     coverage_dataset):
    payload = _items(client)
    items = _by_code(payload)
    # The family has 3 active + 1 archived alert.
    assert items["DC_CS_RATE"]["active_alerts"] == 3
    assert items["DC_UNRELATED"]["active_alerts"] == 5

    codes = [item["code"] for item in payload["items"]]
    assert codes.index("DC_UNRELATED") < codes.index("DC_CS_RATE")
    # Directed definitions/elements are not in the list at all.
    assert "DC_OTHER_RATE" in items
    assert payload["summary"]["families"] >= 2
    assert payload["summary"]["active_alerts"] >= 9

    # A recorded direction removes the item.
    coverage_dataset["family"].global_direction = "lower_is_better"
    db_session.commit()
    assert "DC_CS_RATE" not in _by_code(_items(client))


def test_suggestions_name_their_basis_or_stay_empty(client, coverage_dataset):
    items = _by_code(_items(client))

    family = items["DC_CS_RATE"]
    assert family["kind"] == "family"
    assert family["suggested_direction"] == "lower_is_better"
    assert family["suggestion_basis"] == "clinical_guideline"
    assert "WHO" in family["suggestion_reason"]

    # A numerator of a directed rate moves the rate the same way.
    numerator = items["DC_CS_NUM"]
    assert numerator["suggested_direction"] == "lower_is_better"
    assert numerator["suggestion_basis"] == "numerator_of"
    assert "DC C-Section Rate" in numerator["suggestion_reason"]

    # The denominator has no clinical meaning of its own.
    denominator = items["DC_DELIVERIES"]
    assert denominator["suggested_direction"] is None
    assert denominator["suggestion_basis"] == "none"
    assert "Denominator" in denominator["suggestion_reason"]

    # Nothing invents a direction for an unrelated element.
    unrelated = items["DC_UNRELATED"]
    assert unrelated["suggested_direction"] is None
    assert unrelated["suggestion_basis"] == "none"


# ── bulk apply ──────────────────────────────────────────────────────────────

def test_bulk_apply_writes_both_kinds_with_their_audit(
        client, db_session, coverage_dataset):
    body = {"items": [
        {"kind": "family", "code": "DC_CS_RATE",
         "direction": "lower_is_better"},
        {"kind": "raw", "code": "DC_CS_NUM", "direction": "lower_is_better"},
    ]}
    resp = client.post("/direction-coverage/apply", json=body)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["applied"] == 2
    assert result["skipped"] == 0
    assert result["rescan_required"] is True
    # 3 alerts on the family + 0 on its numerator.
    assert result["affected_alerts"] == 3

    family = coverage_dataset["family"]
    db_session.refresh(family)
    assert family.global_direction == "lower_is_better"
    assert family.version == 2
    version = (db_session.query(IndicatorDefinitionVersion)
               .filter_by(definition_id=family.id)
               .order_by(IndicatorDefinitionVersion.id.desc()).first())
    assert version is not None
    assert version.action == "updated"
    assert json.loads(version.changed_fields) == ["global_direction"]
    assert version.changed_by == "testadmin"

    raw = coverage_dataset["num"]
    db_session.refresh(raw)
    assert raw.global_direction == "lower_is_better"
    history = (db_session.query(IndicatorDirectionHistory)
               .filter_by(indicator_code="DC_CS_NUM")
               .all())
    assert len(history) == 1
    assert history[0].previous_value is None
    assert history[0].new_value == "lower_is_better"
    assert history[0].changed_by == "testadmin"

    # Re-applying the same reviewed list changes nothing and adds no rows.
    again = client.post("/direction-coverage/apply", json=body)
    assert again.status_code == 200, again.text
    assert again.json()["applied"] == 0
    assert again.json()["skipped"] == 2
    assert again.json()["rescan_required"] is False
    db_session.refresh(family)
    assert family.version == 2
    assert (db_session.query(IndicatorDirectionHistory)
            .filter_by(indicator_code="DC_CS_NUM").count()) == 1

    # Both rows leave the coverage list.
    items = _by_code(_items(client))
    assert "DC_CS_RATE" not in items
    assert "DC_CS_NUM" not in items


def test_invalid_batch_is_rejected_before_anything_is_written(
        client, db_session, coverage_dataset):
    bad = client.post("/direction-coverage/apply", json={"items": [
        {"kind": "raw", "code": "DC_UNRELATED",
         "direction": "lower_is_better"},
        {"kind": "family", "code": "DC_CS_RATE", "direction": "target_range"},
    ]})
    assert bad.status_code == 422, bad.text
    db_session.refresh(coverage_dataset["unrelated"])
    assert coverage_dataset["unrelated"].global_direction is None

    unknown = client.post("/direction-coverage/apply", json={"items": [
        {"kind": "family", "code": "NOPE", "direction": "lower_is_better"},
    ]})
    assert unknown.status_code == 422, unknown.text

    empty = client.post("/direction-coverage/apply", json={"items": []})
    assert empty.status_code == 422, empty.text
