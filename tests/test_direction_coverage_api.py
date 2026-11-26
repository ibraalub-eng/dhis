"""Direction Coverage screen: gap list, suggestions and reviewed bulk apply.

The screen exists because an alert can only say whether a deviation is good or
bad when the indicator carries a direction. These tests pin:

* the list contains registered indicator families only — a raw Data Element is
  edited on the element itself and never joins this queue,
* only families with NO recorded direction appear,
* the order is by ACTIVE alerts (archived rows never count),
* a suggestion names its basis and is never invented: a clinical guideline or
  an explicit "no basis",
* bulk apply writes the family on its representative definition with the
  version audit, skips no-ops, rejects raw items, and rejects an invalid batch
  before writing anything.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorDefinitionVersion,
    QualityAlert,
)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def coverage_dataset(db_session):
    """One family directed by guideline plus a second, unmapped family; their
    raw source elements stay unlisted even though three carry alerts."""
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
    for month in months:
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
    # The second family carries fewer active alerts, so it sorts below.
    db_session.add(QualityAlert(
        hospital_id=hospital.id, month="2026-01", perspective="history",
        indicator_code="DC_OTHER_RATE", indicator_name="DC Unmapped Rate",
        severity="MODERATE", method="zscore", active=True,
    ))
    # Raw elements carry alerts of their own; they must not appear in the list.
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

def test_list_covers_families_only_and_counts_active_alerts(
        client, db_session, coverage_dataset):
    payload = _items(client)
    items = _by_code(payload)

    # Raw data elements never join the queue: their direction is edited on the
    # element itself, not applied from this screen.
    assert all(item["kind"] == "family" for item in payload["items"])
    for code in ("DC_CS_NUM", "DC_DELIVERIES", "DC_OTHER_NUM",
                 "DC_UNRELATED"):
        assert code not in items
    assert "elements" not in payload["summary"]

    # The family has 3 active + 1 archived alert; the second family has 1.
    assert items["DC_CS_RATE"]["active_alerts"] == 3
    assert items["DC_OTHER_RATE"]["active_alerts"] == 1
    codes = [item["code"] for item in payload["items"]]
    assert codes.index("DC_CS_RATE") < codes.index("DC_OTHER_RATE")
    assert payload["summary"]["families"] >= 2
    assert payload["summary"]["active_alerts"] >= 4

    # A recorded direction removes the family.
    coverage_dataset["family"].global_direction = "lower_is_better"
    db_session.commit()
    assert "DC_CS_RATE" not in _by_code(_items(client))


def test_suggestion_names_its_guideline_or_stays_empty(client, coverage_dataset):
    items = _by_code(_items(client))

    family = items["DC_CS_RATE"]
    assert family["suggested_direction"] == "lower_is_better"
    assert family["suggestion_basis"] == "clinical_guideline"
    assert "WHO" in family["suggestion_reason"]

    # Nothing invents a direction for a family no guideline covers.
    other = items["DC_OTHER_RATE"]
    assert other["suggested_direction"] is None
    assert other["suggestion_basis"] == "none"
    assert other["suggestion_reason"] is None


# ── bulk apply ──────────────────────────────────────────────────────────────

def test_bulk_apply_writes_the_family_with_its_audit(
        client, db_session, coverage_dataset):
    body = {"items": [
        {"kind": "family", "code": "DC_CS_RATE",
         "direction": "lower_is_better"},
    ]}
    resp = client.post("/direction-coverage/apply", json=body)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["applied"] == 1
    assert result["skipped"] == 0
    assert result["rescan_required"] is True
    # 3 alerts on the family.
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

    # The raw element used by the family is untouched.
    db_session.refresh(coverage_dataset["num"])
    assert coverage_dataset["num"].global_direction is None

    # Re-applying the same reviewed list changes nothing.
    again = client.post("/direction-coverage/apply", json=body)
    assert again.status_code == 200, again.text
    assert again.json()["applied"] == 0
    assert again.json()["skipped"] == 1
    assert again.json()["rescan_required"] is False
    db_session.refresh(family)
    assert family.version == 2

    # The family leaves the coverage list.
    assert "DC_CS_RATE" not in _by_code(_items(client))


def test_only_families_and_valid_batches_are_applied(
        client, db_session, coverage_dataset):
    # A raw Data Element is not applicable from this screen.
    raw = client.post("/direction-coverage/apply", json={"items": [
        {"kind": "raw", "code": "DC_UNRELATED", "direction": "lower_is_better"},
    ]})
    assert raw.status_code == 422, raw.text
    db_session.refresh(coverage_dataset["unrelated"])
    assert coverage_dataset["unrelated"].global_direction is None

    bad = client.post("/direction-coverage/apply", json={"items": [
        {"kind": "family", "code": "DC_CS_RATE", "direction": "target_range"},
    ]})
    assert bad.status_code == 422, bad.text
    db_session.refresh(coverage_dataset["family"])
    assert coverage_dataset["family"].global_direction is None

    unknown = client.post("/direction-coverage/apply", json={"items": [
        {"kind": "family", "code": "NOPE", "direction": "lower_is_better"},
    ]})
    assert unknown.status_code == 422, unknown.text

    empty = client.post("/direction-coverage/apply", json={"items": []})
    assert empty.status_code == 422, empty.text
