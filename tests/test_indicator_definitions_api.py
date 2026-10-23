"""Indicators management API tests (Indicators tab, 2026-10-18).

Contract covered:
* the catalog lists existing indicators exactly once (no duplication),
  alongside existing system rate definitions and managed derived ones;
* drafts are validated before save (syntax, unknown/synthetic refs,
  duplicates, self-reference, threshold conflicts, period applicability);
* C-Section Rate computes from real test data through the safe engine;
* versioning + audit history; historical results are never silently
  rewritten (stale flags until an explicit recompute);
* safe deletion refuses to destroy stored results without purge.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.main import app
from app.models import (
    Indicator,
    IndicatorDefinitionVersion,
    IndicatorResult,
    IndicatorValue,
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


CS_DRAFT = {
    "code": "managed_cs_rate",
    "name": "C-Section Rate",
    "description": "Caesarean sections as a share of total deliveries",
    "group_name": "SRMNH Inpatient Indicators",
    "formula_type": "ratio",
    "numerator_codes": ["5"],
    "denominator_codes": ["2"],
    "operator": "/",
    "multiplier": 100.0,
    "aggregation": "sum",
    "result_type": "percentage",
    "unit": "%",
    "direction": "none",
}


def _seed_values(db, values, hospital_id=1, month="2026-03"):
    for code, value in values.items():
        ind = db.query(Indicator).filter(Indicator.code == code).first()
        assert ind is not None, f"seeded catalog must contain {code}"
        db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                              month=month, value=value))
    db.commit()


def _create(client, **overrides):
    payload = {**CS_DRAFT, **overrides}
    resp = client.post("/indicators", json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# catalog listing — existing indicators appear, no duplicates
# ═══════════════════════════════════════════════════════════════════════════

def test_list_contains_every_existing_indicator_exactly_once(client, db_session):
    resp = client.get("/indicators")
    assert resp.status_code == 200
    data = resp.json()

    expected_raw = {i.code for i in db_session.query(Indicator).all()
                    if i.code not in SYNTHETIC_INDICATOR_CODES}
    raw_items = [i for i in data["items"] if i["kind"] == "raw"]
    assert {i["code"] for i in raw_items} == expected_raw
    # "2" and "5" (the C-Section inputs) must be there
    assert {"2", "5"} <= expected_raw
    # synthetic form-label code stays hidden
    assert not (SYNTHETIC_INDICATOR_CODES & {i["code"] for i in data["items"]})
    # no duplicated codes anywhere in the merged catalog
    codes = [i["code"] for i in data["items"]]
    assert len(codes) == len(set(codes))
    assert data["count"] == len(data["items"])


def test_list_includes_existing_system_rate_definitions_readonly(client):
    resp = client.get("/indicators")
    items = resp.json()["items"]
    rate_items = {i["code"]: i for i in items if i["kind"] == "rate_spec"}
    assert "rate_cs" in rate_items
    cs = rate_items["rate_cs"]
    assert "5" in (cs["numerator_codes"] or [])
    assert "2" in (cs["denominator_codes"] or [])
    assert cs["formula"] and "{5}" in cs["formula"] and "{2}" in cs["formula"]
    assert cs["status"] in ("active", "inactive")


def test_system_rate_row_is_editable_and_keeps_variants_in_step(client, db_session):
    """The catalog collapses the per-site variants of a system rate into ONE
    row, so that row must be editable — and saving it must move the whole
    group, otherwise the outlier (zscore), clinical and forecast engines would
    keep computing the old formula from their own hidden variant."""
    from app.api.indicator_definitions import _rate_variant_siblings
    from app.models import IndicatorDefinition

    row = next(i for i in client.get("/indicators").json()["items"]
               if i["code"] == "rate_cs" and i["kind"] == "rate_spec")
    defn = db_session.get(IndicatorDefinition, row["definition_id"])
    group = [defn] + _rate_variant_siblings(db_session, defn)
    assert defn.is_system is True
    assert len(group) > 1                     # clinical + zscore + forecast
    registry_code, legacy_code = defn.code, defn.legacy_code

    resp = client.put("/indicators/%d" % defn.id, json={
        "numerator_codes": ["13"], "denominator_codes": ["2"],
    })
    assert resp.status_code == 200, resp.text

    for variant in group:
        db_session.refresh(variant)
        assert variant.numerator_codes == ["13"], variant.code
        assert variant.is_system is True      # still a system definition
    # identity/analysis keys never move
    assert defn.code == registry_code and defn.legacy_code == legacy_code

    # The merge stays intact: one row, new formula.
    rows = [i for i in client.get("/indicators").json()["items"]
            if i["code"] == "rate_cs" and i["kind"] == "rate_spec"]
    assert len(rows) == 1 and "{13}" in rows[0]["formula"]

    # …and system definitions still cannot be deleted.
    assert client.delete("/indicators/%d" % defn.id).status_code == 409


def test_toggling_a_system_rate_flips_the_whole_group(client, db_session):
    """A system rate is one catalog row but one definition per analysis site.

    The row's Status cell is a direct Active/Inactive action, so the flip must
    cover every variant: changing only the visible one left the merged row
    reading "Active" (the catalog prefers an active member) while the outlier
    engine already skipped the rate.
    """
    from app.api.indicator_definitions import _rate_variant_siblings
    from app.engine.rate_config import invalidate_rate_specs_cache, load_rate_specs
    from app.models import IndicatorDefinition, RateConfig

    def _row():
        return next(i for i in client.get("/indicators").json()["items"]
                    if i["code"] == "rate_nmr" and i["kind"] == "rate_spec")

    defn = db_session.get(IndicatorDefinition, _row()["definition_id"])
    group = [defn] + _rate_variant_siblings(db_session, defn)
    assert len(group) > 1, "the catalog row must stand for more than one variant"

    resp = client.put("/indicators/%d/toggle" % defn.id, json={"is_active": False})
    assert resp.status_code == 200, resp.text

    for variant in group:
        db_session.refresh(variant)
        assert variant.is_active is False, variant.code
    assert _row()["status"] == "inactive"
    engine_row = db_session.query(RateConfig).filter_by(rate_code="rate_nmr").one()
    assert engine_row.is_active is False
    invalidate_rate_specs_cache()
    assert "rate_nmr" not in load_rate_specs(db_session)

    assert client.put("/indicators/%d/toggle" % defn.id,
                      json={"is_active": True}).status_code == 200
    for variant in group:
        db_session.refresh(variant)
        assert variant.is_active is True, variant.code
    assert _row()["status"] == "active"
    invalidate_rate_specs_cache()
    assert load_rate_specs(db_session)["rate_nmr"].rate_multiplier == 1000.0


def test_editing_a_system_rate_moves_the_engine_rate_config(client, db_session):
    """The same rate is stored twice: the registry row the Indicators screen
    shows and the rate_config row the Outlier Scan / Quality engine computes
    with. Editing the multiplier on the screen must move the engine's row,
    otherwise Neonatal mortality rate reads ``{17} / {6} * 1000`` on one screen
    and ``{17} / {6} * 100`` in the Quality explanation."""
    from app.engine.rate_config import invalidate_rate_specs_cache, load_rate_specs
    from app.models import IndicatorDefinition, RateConfig

    invalidate_rate_specs_cache()
    assert load_rate_specs(db_session)["rate_nmr"].rate_multiplier == 1000.0

    row = next(i for i in client.get("/indicators").json()["items"]
               if i["code"] == "rate_nmr" and i["kind"] == "rate_spec")
    defn = db_session.get(IndicatorDefinition, row["definition_id"])

    resp = client.put("/indicators/%d" % defn.id, json={"multiplier": 10000.0})
    assert resp.status_code == 200, resp.text

    engine_row = db_session.query(RateConfig).filter_by(rate_code="rate_nmr").one()
    assert engine_row.rate_multiplier == 10000.0
    spec = load_rate_specs(db_session)["rate_nmr"]
    assert spec.rate_multiplier == 10000.0
    # The unit is registry-owned as well — the engine must report per-1,000,
    # not the legacy per-100 label.
    assert spec.unit == "per 1,000"

    # Restoring the standard scaling round-trips through the same sync.
    assert client.put("/indicators/%d" % defn.id,
                      json={"multiplier": 1000.0}).status_code == 200
    assert db_session.query(RateConfig).filter_by(
        rate_code="rate_nmr").one().rate_multiplier == 1000.0
    invalidate_rate_specs_cache()
    assert load_rate_specs(db_session)["rate_nmr"].rate_multiplier == 1000.0


def test_catalog_hides_count_aliases_that_duplicate_one_raw_element(client):
    response = client.get("/indicators")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    rate_codes = {
        item["code"] for item in items if item["kind"] == "rate_spec"
    }

    # These system keys are identity wrappers around the raw data element.
    assert not ({"cs_count", "total_births"} & rate_codes)
    # A count combining multiple raw elements is still a distinct metric.
    assert "adolescent" in rate_codes
    raw_codes = {item["code"] for item in items if item["kind"] == "raw"}
    assert "5" in raw_codes
    assert "6" in raw_codes


def test_catalog_shows_identical_system_rates_only_once(client):
    response = client.get("/indicators")
    assert response.status_code == 200, response.text
    rate_items = [
        item for item in response.json()["items"]
        if item["kind"] == "rate_spec"
    ]
    definitions = [
        (item["formula"], item["unit"])
        for item in rate_items if item["formula"]
    ]

    assert len(definitions) == len(set(definitions))
    codes = {item["code"] for item in rate_items}
    assert "rate_cs" in codes
    assert "cs_rate" not in codes
    assert "rate_lbw" in codes
    assert "lbw_rate" not in codes
    assert "rate_preterm" in codes
    assert "preterm_rate" not in codes


def test_every_listed_system_rate_has_a_detail_view(client):
    catalog = client.get("/indicators")
    assert catalog.status_code == 200, catalog.text
    rate_codes = {
        item["code"] for item in catalog.json()["items"]
        if item["kind"] == "rate_spec"
    }
    assert rate_codes

    for code in rate_codes:
        detail = client.get(f"/indicators/rate/{code}")
        assert detail.status_code == 200, f"{code}: {detail.text}"
        assert detail.json()["code"] == code


def test_list_filters_q_kind_status_group(client):
    _create(client)
    all_items = client.get("/indicators").json()["items"]

    derived = client.get("/indicators", params={"kind": "derived"}).json()["items"]
    assert [i["code"] for i in derived] == ["managed_cs_rate"]
    assert all(i["kind"] == "derived" for i in derived)

    by_q = client.get("/indicators", params={"q": "caesarean"}).json()["items"]
    assert any(i["code"] == "managed_cs_rate" for i in by_q)

    by_status = client.get("/indicators",
                           params={"status": "active"}).json()["items"]
    # Raw data elements report "active" too (2026-10-21 — the "catalog"
    # status collapsed the Active filter to derivatives only); every not-
    # inactive row is active, and the legacy ?status=catalog alias still
    # resolves to the Data Element kind.
    assert all(i["status"] != "inactive" for i in by_status)
    raw_codes = {i["code"] for i in all_items if i["kind"] == "raw"}
    assert {i["code"] for i in by_status if i["kind"] == "raw"} == raw_codes
    legacy = client.get("/indicators", params={"status": "catalog"}).json()["items"]
    assert legacy and all(i["kind"] == "raw" for i in legacy)

    by_group = client.get("/indicators",
                          params={"group": "SRMNH Inpatient Indicators"}).json()
    assert all(i["group_name"] == "SRMNH Inpatient Indicators"
               for i in by_group["items"])
    assert "SRMNH Inpatient Indicators" in by_group["groups"]
    assert by_group["types"]

    inactive = client.get("/indicators", params={"status": "inactive"}).json()
    assert inactive["items"] == []


def test_catalog_uses_a_two_value_category_axis(client, db_session):
    """Category is the two-value kind axis; a group name is metadata only."""
    _create(client)  # carries group_name="SRMNH Inpatient Indicators"
    db_session.add(Indicator(code="zz_ungrouped", name="Ungrouped element",
                             level=1, group_name=None))
    db_session.commit()

    data = client.get("/indicators").json()
    by_code = {item["code"]: item for item in data["items"]}

    # a stored group never becomes a category — but it stays metadata
    assert by_code["managed_cs_rate"]["category"] == "Derivative Indicator"
    assert by_code["managed_cs_rate"]["group_name"] == "SRMNH Inpatient Indicators"
    assert by_code["zz_ungrouped"]["category"] == "Data Element"
    assert all(item["category"] for item in data["items"])
    # the registry exposes exactly TWO categories, never a group name
    assert set(data["categories"]) == {"Data Element", "Derivative Indicator"}
    assert not {"Managed indicators", "System rates"} & set(data["categories"])

    # every raw row is a Data Element, grouped or not — the category filter
    # selects the KIND, never a group
    filtered = client.get("/indicators", params={"category": "Data Element"}).json()
    assert all(item["kind"] == "raw" for item in filtered["items"])
    assert "zz_ungrouped" in [item["code"] for item in filtered["items"]]
    assert "managed_cs_rate" not in [item["code"] for item in filtered["items"]]
    assert filtered["categories"] == data["categories"]

    derived_cat = client.get("/indicators",
                             params={"category": "Derivative Indicator"}).json()
    assert "managed_cs_rate" in [i["code"] for i in derived_cat["items"]]
    assert all(item["kind"] != "raw" for item in derived_cat["items"])


# ═══════════════════════════════════════════════════════════════════════════
# validation — errors surface BEFORE save
# ═══════════════════════════════════════════════════════════════════════════

def test_validate_accepts_good_draft_and_returns_canonical_formula(client):
    resp = client.post("/indicators/validate", json={"draft": CS_DRAFT})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []
    assert "{5}" in data["expression"] and "{2}" in data["expression"]
    codes = {r["code"]: r for r in data["refs"]}
    assert codes["5"]["exists"] and "Caesarean" in (codes["5"]["name"] or "")
    assert data["formula_display"] and "Total Deliveries" in data["formula_display"]


def test_validate_rejects_duplicate_system_rate_code(client):
    draft = {**CS_DRAFT, "code": "rate_cs"}
    data = client.post("/indicators/validate", json={"draft": draft}).json()
    assert data["valid"] is False
    assert any("already registered as a system rate" in error
               for error in data["errors"])


def test_validate_rejects_broken_syntax(client):
    draft = {**CS_DRAFT, "formula_type": "expression",
             "expression": "{5} $ {2} 100",
             "numerator_codes": None, "denominator_codes": None}
    resp = client.post("/indicators/validate", json={"draft": draft})
    data = resp.json()
    assert data["valid"] is False
    assert any("Invalid formula" in e for e in data["errors"])


def test_validate_rejects_unknown_and_synthetic_refs(client):
    draft = {**CS_DRAFT, "numerator_codes": ["9.9.9"]}
    data = client.post("/indicators/validate", json={"draft": draft}).json()
    assert data["valid"] is False
    assert any("Unknown data element" in e for e in data["errors"])

    draft = {**CS_DRAFT, "numerator_codes": ["0"]}
    data = client.post("/indicators/validate", json={"draft": draft}).json()
    assert data["valid"] is False
    assert any("form-header label" in e for e in data["errors"])


def test_validate_rejects_duplicate_and_conflicting_codes(client):
    _create(client)
    dup = client.post("/indicators/validate",
                      json={"draft": CS_DRAFT}).json()
    assert dup["valid"] is False
    assert any("already exists" in e for e in dup["errors"])
    # editing itself must NOT self-collide
    defn_id = next(i["ref_id"] for i in
                   client.get("/indicators").json()["items"]
                   if i["kind"] == "derived")
    ok = client.post("/indicators/validate",
                     json={"draft": CS_DRAFT, "exclude_id": defn_id}).json()
    assert ok["valid"] is True

    raw_clash = client.post("/indicators/validate",
                            json={"draft": {**CS_DRAFT, "code": "5"}}).json()
    assert any("raw data element" in e for e in raw_clash["errors"])


def test_validate_rejects_self_reference_and_missing_denominator(client):
    self_ref = client.post("/indicators/validate", json={"draft": {
        **CS_DRAFT, "code": "x_rate",
        "formula_type": "expression", "expression": "{x_rate} * 2",
        "numerator_codes": None, "denominator_codes": None,
    }}).json()
    assert any("cannot reference itself" in e for e in self_ref["errors"])

    no_den = client.post("/indicators/validate", json={"draft": {
        **CS_DRAFT, "denominator_codes": [],
    }}).json()
    assert any("denominator" in e for e in no_den["errors"])


def test_validate_rejects_threshold_conflicts_and_bad_enums(client):
    resp = client.post("/indicators/validate", json={"draft": {
        **CS_DRAFT,
        "threshold_low": 90.0, "threshold_high": 10.0,
        "direction": "target_range", "target_min": None, "target_max": None,
        "aggregation": "median",
    }})
    errors = " | ".join(resp.json()["errors"])
    assert "cannot exceed" in errors
    assert "target min and max" in errors
    assert "Aggregation" in errors


def test_validate_warns_on_parent_child_double_count(client):
    data = client.post("/indicators/validate", json={"draft": {
        **CS_DRAFT, "code": "dd_rate",
        "numerator_codes": ["2", "2.a"], "denominator_codes": ["3"],
    }}).json()
    assert data["valid"] is True
    assert any("double-counts" in w for w in data["warnings"])


def test_validate_warns_when_period_has_no_data(client):
    data = client.post("/indicators/validate", json={
        "draft": CS_DRAFT, "hospital_id": 1, "month": "2099-01"}).json()
    assert data["valid"] is True
    assert any("No data for the selected period" in w for w in data["warnings"])
    assert data["preview"]["status"] == "no_data"


def test_validate_rejects_bad_month_format(client):
    data = client.post("/indicators/validate", json={
        "draft": CS_DRAFT, "hospital_id": 1, "month": "March 2026"}).json()
    assert any("YYYY-MM" in e for e in data["errors"])


def test_create_endpoint_refuses_invalid_draft_with_422(client):
    resp = client.post("/indicators", json={**CS_DRAFT, "numerator_codes": ["zzz"]})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("Unknown data element" in e for e in detail["errors"])
    assert client.get("/indicators").json()["count"] == len(
        [i for i in client.get("/indicators").json()["items"]
         if i["kind"] != "derived"])  # nothing was created


# ═══════════════════════════════════════════════════════════════════════════
# C-Section Rate end-to-end: create → preview → compute
# ═══════════════════════════════════════════════════════════════════════════

def test_create_c_section_rate_and_version_history(client, db_session):
    created = _create(client)
    assert created["id"] > 0
    assert created["code"] == "managed_cs_rate"
    assert created["version"] == 1
    assert created["is_active"] is True
    assert created["formula_display"]
    assert "Caesarean Sections [5]" in created["formula_display"]
    assert "Total Deliveries [2]" in created["formula_display"]
    assert "× 100" in created["formula_display"]

    versions = client.get(f"/indicators/{created['id']}/versions").json()
    assert len(versions) == 1
    assert versions[0]["action"] == "created"
    assert versions[0]["snapshot"]["numerator_codes"] == ["5"]
    assert versions[0]["changed_fields"] == ["*"]

    # refs resolve to real raw elements with data coverage
    refs = client.get(f"/indicators/{created['id']}/refs").json()
    by_code = {r["code"]: r for r in refs}
    assert by_code["5"]["exists"] and by_code["5"]["name"]
    assert by_code["5"]["data_count"] == 0  # no values seeded yet


def test_c_section_rate_preview_from_test_data(client, db_session):
    created = _create(client)
    _seed_values(db_session, {"5": 30.0, "2": 150.0}, hospital_id=1,
                 month="2026-03")

    resp = client.post(f"/indicators/{created['id']}/preview",
                       json={"hospital_id": 1, "month": "2026-03"})
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["status"] == "ok"
    assert preview["value"] == pytest.approx(20.0)
    assert preview["numerator"] == 30.0
    assert preview["denominator"] == 150.0
    inputs = {i["code"]: i for i in preview["inputs"]}
    assert inputs["5"]["value"] == 30.0 and inputs["5"]["missing"] is False
    assert inputs["2"]["value"] == 150.0


def test_preview_reports_zero_denominator_and_missing_separately(client, db_session):
    created = _create(client)
    _seed_values(db_session, {"5": 30.0, "2": 0.0}, hospital_id=1,
                 month="2026-03")
    _seed_values(db_session, {"5": 10.0}, hospital_id=2, month="2026-03")

    zero = client.post(f"/indicators/{created['id']}/preview",
                       json={"hospital_id": 1, "month": "2026-03"}).json()
    assert zero["status"] == "zero_denominator"
    assert zero["value"] is None

    missing = client.post(f"/indicators/{created['id']}/preview",
                          json={"hospital_id": 2, "month": "2026-03"}).json()
    assert missing["status"] == "missing_data"
    assert missing["value"] is None


def test_recompute_stores_results_and_flags_staleness(client, db_session):
    created = _create(client)
    def_id = created["id"]
    _seed_values(db_session, {"5": 30.0, "2": 150.0}, hospital_id=1,
                 month="2026-03")
    _seed_values(db_session, {"5": 45.0, "2": 150.0}, hospital_id=2,
                 month="2026-03")

    summary = client.post("/indicators/recompute",
                          json={"month": "2026-03"}).json()
    assert summary["month"] == "2026-03"
    assert summary["computed"] == summary["hospitals"] == 3
    assert summary["counts"]["ok"] == 2          # hospitals 1 + 2 compute
    assert summary["counts"]["no_data"] == 1     # hospital 3 reported nothing

    results = client.get(f"/indicators/{def_id}/results").json()
    assert results["count"] == 3
    by_hosp = {r["hospital_id"]: r for r in results["items"]}
    assert by_hosp[1]["value"] == pytest.approx(20.0)
    assert by_hosp[2]["value"] == pytest.approx(30.0)
    assert by_hosp[3]["status"] == "no_data" and by_hosp[3]["value"] is None
    assert all(r["stale"] is False for r in results["items"])

    # edit the formula → stored historical rows are NOT rewritten,
    # they surface as stale until an explicit recompute.
    resp = client.put(f"/indicators/{def_id}", json={"multiplier": 50.0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    results = client.get(f"/indicators/{def_id}/results").json()
    assert all(r["stale"] is True for r in results["items"])
    assert all(r["definition_version"] == 1 for r in results["items"])
    assert db_session.query(IndicatorResult).count() == 3

    summary = client.post("/indicators/recompute",
                          json={"month": "2026-03"}).json()
    assert summary["computed"] == 3
    results = client.get(f"/indicators/{def_id}/results").json()
    assert all(r["stale"] is False for r in results["items"])
    assert all(r["definition_version"] == 2 for r in results["items"])


def test_recompute_never_touches_raw_values(client, db_session):
    _create(client)
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    raw_before = db_session.query(IndicatorValue).count()
    client.post("/indicators/recompute", json={"month": "2026-03"})
    assert db_session.query(IndicatorValue).count() == raw_before


# ═══════════════════════════════════════════════════════════════════════════
# edit / activate / deactivate — versioning rules
# ═══════════════════════════════════════════════════════════════════════════

def test_update_bumps_version_and_records_changed_fields(client):
    created = _create(client)
    def_id = created["id"]

    resp = client.put(f"/indicators/{def_id}",
                      json={"multiplier": 1000.0, "unit": "per 1,000"})
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["version"] == 2
    assert updated["multiplier"] == 1000.0

    versions = client.get(f"/indicators/{def_id}/versions").json()
    actions = [v["action"] for v in versions]
    assert actions[0] == "updated" and actions[1] == "created"
    assert set(versions[0]["changed_fields"]) == {"multiplier", "unit"}
    # stored canonical expression regenerated for the ratio shape
    assert updated["expression"] and "* 1000" in updated["expression"]


def test_invalid_update_is_rejected_without_mutating_the_row(client):
    created = _create(client)
    def_id = created["id"]

    resp = client.put(f"/indicators/{def_id}",
                      json={"numerator_codes": ["nope.404"]})
    assert resp.status_code == 422
    assert any("Unknown data element" in e
               for e in resp.json()["detail"]["errors"])

    fresh = client.get(f"/indicators/{def_id}").json()
    assert fresh["version"] == created["version"] == 1
    assert fresh["numerator_codes"] == ["5"]
    versions = client.get(f"/indicators/{def_id}/versions").json()
    assert [v["action"] for v in versions] == ["created"]


def test_noop_update_does_not_bump_version(client):
    created = _create(client)
    def_id = created["id"]
    resp = client.put(f"/indicators/{def_id}", json={"name": created["name"]})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    assert len(client.get(f"/indicators/{def_id}/versions").json()) == 1


def test_activate_deactivate_records_history_without_content_version(client):
    created = _create(client)
    def_id = created["id"]

    resp = client.put(f"/indicators/{def_id}/toggle", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert resp.json()["version"] == 1  # status is not a formula change

    versions = client.get(f"/indicators/{def_id}/versions").json()
    assert versions[0]["action"] == "deactivated"

    # idempotent toggle
    resp = client.put(f"/indicators/{def_id}/toggle", json={"is_active": False})
    assert resp.status_code == 200
    assert len(client.get(f"/indicators/{def_id}/versions").json()) == 2

    resp = client.put(f"/indicators/{def_id}/toggle", json={"is_active": True})
    assert resp.json()["is_active"] is True


def test_toggle_status_is_visible_in_the_catalog(client):
    """The quick action must survive a reload: the catalog row reports the
    stored status and the status filter agrees with it."""
    created = _create(client)
    def_id = created["id"]

    def catalog_row():
        items = client.get("/indicators").json()["items"]
        return next(i for i in items if i["code"] == "managed_cs_rate")

    assert catalog_row()["status"] == "active"

    client.put(f"/indicators/{def_id}/toggle", json={"is_active": False})
    assert catalog_row()["status"] == "inactive"
    assert client.get(f"/indicators/{def_id}").json()["is_active"] is False
    inactive = client.get("/indicators", params={"status": "inactive"}).json()
    assert "managed_cs_rate" in [i["code"] for i in inactive["items"]]

    client.put(f"/indicators/{def_id}/toggle", json={"is_active": True})
    assert catalog_row()["status"] == "active"


def test_deactivation_keeps_stored_results_and_history(client, db_session):
    """Switching an indicator off must never delete what it already produced."""
    created = _create(client)
    def_id = created["id"]
    db_session.add(IndicatorResult(
        definition_id=def_id, definition_code=created["code"],
        hospital_id=1, month="2026-03", value=12.5, status="ok",
        definition_version=1,
    ))
    db_session.commit()

    resp = client.put(f"/indicators/{def_id}/toggle", json={"is_active": False})
    assert resp.status_code == 200

    results = client.get(f"/indicators/{def_id}/results").json()
    assert results["count"] == 1
    assert results["items"][0]["value"] == 12.5
    # the audit trail records the switch-off, and the content version is intact
    versions = client.get(f"/indicators/{def_id}/versions").json()
    assert [v["action"] for v in versions][0] == "deactivated"
    assert client.get(f"/indicators/{def_id}").json()["version"] == 1

    # the ONE central definition source stops offering it for new calculations…
    from app.engine import indicator_service
    active = {r.code for r in indicator_service.resolve_active_definitions(db_session)}
    assert created["code"] not in active
    # …and re-activation brings it back without touching the stored rows
    client.put(f"/indicators/{def_id}/toggle", json={"is_active": True})
    active = {r.code for r in indicator_service.resolve_active_definitions(db_session)}
    assert created["code"] in active
    assert client.get(f"/indicators/{def_id}/results").json()["count"] == 1


def test_data_element_status_mirrors_the_data_tree(client, db_session):
    """Raw status is owned by the Data Tree: flipping its global switch shows
    up in the catalog, and the row carries no definition id to toggle."""
    from app.models import IndicatorDefaultConfig

    el = _raw_element(db_session)

    def raw_row():
        items = client.get("/indicators", params={"kind": "raw"}).json()["items"]
        return next(i for i in items if i["code"] == el.code)

    assert raw_row()["status"] == "active"
    assert raw_row().get("definition_id") is None  # no quick action in the UI

    db_session.add(IndicatorDefaultConfig(indicator_id=el.id, month="2026-03",
                                          is_enabled=False))
    db_session.commit()

    assert raw_row()["status"] == "inactive"   # Data Tree change is reflected
    assert raw_row().get("definition_id") is None


# ═══════════════════════════════════════════════════════════════════════════
# safe deletion
# ═══════════════════════════════════════════════════════════════════════════

def test_delete_without_results_is_allowed_and_history_survives(client, db_session):
    created = _create(client)
    resp = client.delete(f"/indicators/{created['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert client.get(f"/indicators/{created['id']}").status_code == 404

    rows = client.get("/indicators").json()["items"]
    assert not any(i["kind"] == "derived" for i in rows)

    # audit trail outlives the definition (queryable by code, detached)
    trail = (db_session.query(IndicatorDefinitionVersion)
             .filter_by(definition_code="managed_cs_rate").all())
    assert {v.action for v in trail} == {"created", "deleted"}
    assert all(v.definition_id is None for v in trail)

    # the ID is freed again → the same draft validates cleanly
    assert client.post("/indicators/validate",
                       json={"draft": CS_DRAFT}).json()["valid"] is True


def test_delete_with_results_requires_purge(client, db_session):
    created = _create(client)
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    client.post("/indicators/recompute", json={"month": "2026-03"})
    assert db_session.query(IndicatorResult).count() > 0

    resp = client.delete(f"/indicators/{created['id']}")
    assert resp.status_code == 409
    assert "stored result" in resp.json()["detail"]
    assert client.get(f"/indicators/{created['id']}").status_code == 200
    assert db_session.query(IndicatorResult).count() > 0

    resp = client.delete(f"/indicators/{created['id']}", params={"purge": "true"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["results_deleted"] == 3
    assert db_session.query(IndicatorResult).count() == 0

    # history rows survive, detached from the deleted definition
    trail = (db_session.query(IndicatorDefinitionVersion)
             .filter_by(definition_code="managed_cs_rate").all())
    assert {v.action for v in trail} == {"created", "deleted"}
    assert all(v.definition_id is None for v in trail)
    created_row = [v for v in trail if v.action == "created"][0]
    assert '"5"' in created_row.snapshot and '"2"' in created_row.snapshot


# ═══════════════════════════════════════════════════════════════════════════
# read-only detail for raw + system-rate rows
# ═══════════════════════════════════════════════════════════════════════════

def test_raw_detail_shows_coverage_and_derived_references(client, db_session):
    created = _create(client)
    _seed_values(db_session, {"5": 30.0})

    resp = client.get("/indicators/raw/5")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "raw"
    assert "Caesarean" in data["name"]
    assert data["data_rows"] == 1
    assert data["latest_month"] == "2026-03"
    assert any(r["id"] == created["id"] for r in data["referenced_by"])

    assert client.get("/indicators/raw/zzz").status_code == 404


def test_rate_spec_detail_resolves_underlying_elements(client):
    resp = client.get("/indicators/rate/rate_cs")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "rate_spec"
    assert data["multiplier"] > 0
    refs = {r["code"]: r for r in data["refs"]}
    assert refs["5"]["name"] and refs["2"]["name"]
    assert set(refs["5"].keys()) >= {"code", "name", "role"}
    assert client.get("/indicators/rate/nope").status_code == 404


def test_detail_endpoint_for_derived_indicator(client):
    created = _create(client)
    resp = client.get(f"/indicators/{created['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "managed_cs_rate"
    assert data["formula_type"] == "ratio"
    assert data["threshold_low"] is None
    assert client.get("/indicators/999999").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# expression-mode indicators
# ═══════════════════════════════════════════════════════════════════════════

def test_expression_mode_indicator_computes(client, db_session):
    draft = {
        "code": "mh_rate",
        "name": "Maternal Hemorrhage Share",
        "formula_type": "expression",
        "expression": "{10.a.1} / {10.a} * 100",
        "result_type": "percentage",
        "unit": "%",
        "multiplier": 1.0,
        "aggregation": "sum",
        "operator": "/",
    }
    created = _create(client, **draft)
    _seed_values(db_session, {"10.a.1": 4.0, "10.a": 8.0})

    preview = client.post(f"/indicators/{created['id']}/preview",
                          json={"hospital_id": 1, "month": "2026-03"}).json()
    assert preview["status"] == "ok"
    assert preview["value"] == pytest.approx(50.0)

    # canonical expression is stored for audit
    assert "{10.a.1}" in created["expression"]


# ── dynamic groups (reuse surface for other screens) ────────────────────────

def test_groups_endpoint_reports_dynamic_suitable_groups(client):
    """GET /indicators/groups reports whatever the active catalog contains:
    canonical clinical domains first, no technical site-key labels."""
    resp = client.get("/indicators/groups")
    assert resp.status_code == 200
    rows = resp.json()
    names = [r["name"] for r in rows]

    assert names[0] == "Delivery & Surgery"   # canonical order first
    assert "Maternal Outcomes" in names
    assert "Newborn Outcomes" in names
    assert not any(n.startswith("System indicators /") for n in names)
    for r in rows:
        assert r["total"] >= 1, "empty groups are never reported"

    maternal = next(r for r in rows if r["name"] == "Maternal Outcomes")
    assert maternal["total"] >= 2
    assert maternal["active"] >= 1
    assert "rate_spec" in maternal["kinds"] or "derived" in maternal["kinds"]
    assert "clinical" in maternal["sites"]


def test_group_filter_agrees_with_groups_counts(client):
    """The catalog's group= filter returns exactly the members the groups
    endpoint counted — one shared source of truth."""
    rows = client.get("/indicators/groups").json()
    maternal = next(r for r in rows if r["name"] == "Maternal Outcomes")

    listed = client.get("/indicators",
                        params={"group": "Maternal Outcomes"}).json()
    assert listed["count"] == maternal["total"]
    assert all(i["group_name"] == "Maternal Outcomes"
               for i in listed["items"])


# ═══════════════════════════════════════════════════════════════════════════
# raw data element editing (2026-10-21: Edit button on Data Element rows)
# ═══════════════════════════════════════════════════════════════════════════

def _raw_element(db_session, code="5"):
    el = db_session.query(Indicator).filter(Indicator.code == code).first()
    assert el is not None, "seeded catalog must contain a raw element"
    return el


def test_raw_detail_exposes_id_and_layered_config(client, db_session):
    el = _raw_element(db_session)
    d = client.get(f"/indicators/raw/{el.code}").json()
    assert d["id"] == el.id
    assert "minimum_history_period" in d
    assert "outlier_method" in d
    assert "historical_enabled" in d
    assert "peer_comparison_enabled" in d


def test_data_elements_are_edited_in_the_data_tree_not_in_the_registry(client, db_session):
    """Data Elements are mirrored read-only on the Indicators screen: the
    registry exposes no element-update route. Their one editor is the Data
    Tree config API, which stays the source of truth."""
    el = _raw_element(db_session)

    # the registry never shipped an element editor — and must not
    assert client.put(f"/indicators/element/{el.id}",
                      json={"name": "x"}).status_code in (404, 405)

    # the Data Tree endpoint does the edit (name is mutable there, code is not)
    resp = client.put(f"/hospitals/indicators/{el.id}",
                      json={"name": "Total Deliveries (renamed)"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["code"] == el.code
    assert out["name"] == "Total Deliveries (renamed)"
    db_session.expire_all()
    fresh = db_session.query(Indicator).filter(Indicator.id == el.id).first()
    assert fresh.name == "Total Deliveries (renamed)"
