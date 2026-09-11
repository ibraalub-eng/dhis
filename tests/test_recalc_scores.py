"""Regression tests for score recalculation paths.

Guards against stale model-name imports (SystemConfig was renamed to
AppConfig but two API modules still referenced the old name), which made
POST /dashboard/recalculate-completeness return 500 and made indicator
toggles silently skip score recalculation.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import QualityScore


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


def test_recalculate_completeness_empty_db(client):
    """Empty DB must return 200 with zero counts — a stale model import would 500 here."""
    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    assert resp.json() == {"updated": 0, "total": 0}


def test_recalculate_completeness_updates_scores(client, db_session):
    """With an existing quality score, completeness is recomputed and reported as updated."""
    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["updated"] == 1


def test_recalc_hospital_scores_no_crash(db_session):
    """Indicator score recalculation must not raise (regression: SystemConfig ImportError)."""
    from app.api.indicator_config import _recalc_hospital_scores

    db_session.add(QualityScore(hospital_id=1, month="2027-01", score=70.0))
    db_session.commit()

    # The imports inside the function run before any try/except, so the old
    # stale model name raised an ImportError here — assert it completes.
    _recalc_hospital_scores(db_session, 1)

    refreshed = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == "2027-01"
    ).first()
    assert refreshed is not None
    assert refreshed.completeness is not None


def test_toggle_indicator_endpoint(client, db_session):
    """Toggling an indicator returns the expected shape and doesn't crash recalculation."""
    from app.models import Indicator

    indicator = db_session.query(Indicator).first()
    assert indicator is not None

    resp = client.put(f"/hospitals/1/indicators/{indicator.id}/toggle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hospital_id"] == 1
    assert data["indicator_id"] == indicator.id
    assert data["is_enabled"] is False
    assert "message" in data


def test_default_disabled_inherited_by_hospital(client, db_session):
    """A default-disabled indicator must be disabled for a hospital with no override."""
    from app.engine.pipeline import get_effective_manual_disabled_ids
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    disabled = get_effective_manual_disabled_ids(db_session, hospital_id=1, month="2027-02")
    assert ind.id in disabled


def test_hospital_override_exempts_from_default_disabled(client, db_session):
    """A per-hospital enabled override must exempt that hospital from the default-disable."""
    from app.engine.pipeline import get_effective_manual_disabled_ids
    from app.models import HospitalIndicatorConfig, Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.add(HospitalIndicatorConfig(hospital_id=1, indicator_id=ind.id, is_enabled=True))
    db_session.commit()

    disabled = get_effective_manual_disabled_ids(db_session, hospital_id=1, month="2027-02")
    assert ind.id not in disabled

    # Other hospitals without an override still inherit the default.
    disabled2 = get_effective_manual_disabled_ids(db_session, hospital_id=2, month="2027-02")
    assert ind.id in disabled2


def test_hospital_own_disabled_stays_disabled_even_if_default_enabled(client, db_session):
    """A per-hospital disabled override must keep the indicator disabled even when the default is enabled."""
    from app.engine.pipeline import get_effective_manual_disabled_ids
    from app.models import HospitalIndicatorConfig, Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=True))
    db_session.add(HospitalIndicatorConfig(hospital_id=1, indicator_id=ind.id, is_enabled=False))
    db_session.commit()

    disabled = get_effective_manual_disabled_ids(db_session, hospital_id=1, month="2027-02")
    assert ind.id in disabled


def test_default_is_month_scoped(client, db_session):
    """A default-disable for one month must NOT leak into another month."""
    from app.engine.pipeline import get_effective_manual_disabled_ids
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    disabled_feb = get_effective_manual_disabled_ids(db_session, hospital_id=1, month="2027-02")
    disabled_mar = get_effective_manual_disabled_ids(db_session, hospital_id=1, month="2027-03")
    assert ind.id in disabled_feb
    assert ind.id not in disabled_mar


def test_default_all_months_aggregates_disabled(client, db_session):
    """Effective default for '__all__' must disable an indicator disabled in ANY month."""
    from app.engine.pipeline import get_default_disabled_indicator_ids
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    disabled_all = get_default_disabled_indicator_ids(db_session, "__all__")
    assert ind.id in disabled_all


def test_toggle_default_all_months(client, db_session):
    """PUT toggle-default with month='__all__' must write config rows for every known month."""
    from app.models import Indicator, IndicatorDefaultConfig, IndicatorValue

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=1, month="2027-01", indicator_id=ind.id, value=5))
    db_session.add(IndicatorValue(hospital_id=1, month="2027-02", indicator_id=ind.id, value=6))
    db_session.add(IndicatorValue(hospital_id=1, month="2027-03", indicator_id=ind.id, value=7))
    db_session.commit()

    resp = client.put(f"/hospitals/indicators/{ind.id}/toggle-default?month=__all__")
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False

    rows = db_session.query(IndicatorDefaultConfig).filter(
        IndicatorDefaultConfig.indicator_id == ind.id,
    ).all()
    assert len(rows) == 3
    assert all(not r.is_enabled for r in rows)


def test_hospital_tree_all_months_inherits_default(client, db_session):
    """A hospital with no override must show inherited default in the '__all__' tree."""
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    resp = client.get("/hospitals/1/indicator-tree?month=__all__")
    assert resp.status_code == 200
    data = resp.json()

    def _find(node, indicator_id):
        if node.get("indicator_id") == indicator_id:
            return node
        for child in node.get("children", []):
            found = _find(child, indicator_id)
            if found is not None:
                return found
        return None

    node = _find({"children": data["children"]}, ind.id)
    assert node is not None
    assert node["is_enabled"] is False


def test_save_default_tree_config_all_months(client, db_session):
    """save-default-tree-config with month='__all__' must persist to every known month."""
    from app.models import Indicator, IndicatorDefaultConfig, IndicatorValue

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=1, month="2027-01", indicator_id=ind.id, value=5))
    db_session.add(IndicatorValue(hospital_id=1, month="2027-02", indicator_id=ind.id, value=6))
    db_session.commit()

    resp = client.post(
        "/hospitals/save-default-tree-config?month=__all__",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200

    rows = db_session.query(IndicatorDefaultConfig).filter(
        IndicatorDefaultConfig.indicator_id == ind.id,
    ).all()
    assert len(rows) == 2
    assert all(not r.is_enabled for r in rows)


def test_save_tree_config_persists_override(client, db_session):
    from app.models import Indicator, HospitalIndicatorConfig

    ind = db_session.query(Indicator).first()
    resp = client.post(
        "/hospitals/2/save-tree-config?month=__all__",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200

    cfg = db_session.query(HospitalIndicatorConfig).filter(
        HospitalIndicatorConfig.hospital_id == 2,
        HospitalIndicatorConfig.indicator_id == ind.id,
    ).first()
    assert cfg is not None
    assert cfg.is_enabled is False


def test_default_tree_aggregates_hospital_values(client, db_session):
    """The default-scope tree must aggregate values across hospitals per month."""
    from app.models import Indicator, IndicatorValue

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=1, month="2027-01", indicator_id=ind.id, value=5))
    db_session.add(IndicatorValue(hospital_id=2, month="2027-01", indicator_id=ind.id, value=7))
    db_session.commit()

    resp = client.get("/hospitals/indicator-tree/default?month=2027-01")
    assert resp.status_code == 200
    data = resp.json()

    def _find(node):
        if node.get("indicator_id") == ind.id:
            return node
        for child in node.get("children", []):
            found = _find(child)
            if found is not None:
                return found
        return None

    node = _find({"children": data["children"]})
    assert node is not None
    assert node["value"] == 12
    assert sorted(node["per_hospital"], key=lambda p: p["hospital_id"]) == [
        {"hospital_id": 1, "hospital": "General Hospital", "value": 5.0},
        {"hospital_id": 2, "hospital": "Central Medical", "value": 7.0},
    ]


def test_default_tree_per_hospital_breakdown_all_months(client, db_session):
    """Default-scope __all__ must aggregate per hospital across months."""
    from app.models import Indicator, IndicatorValue

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=1, month="2027-01", indicator_id=ind.id, value=5))
    db_session.add(IndicatorValue(hospital_id=1, month="2027-02", indicator_id=ind.id, value=3))
    db_session.add(IndicatorValue(hospital_id=2, month="2027-01", indicator_id=ind.id, value=7))
    db_session.add(IndicatorValue(hospital_id=3, month="2027-03", indicator_id=ind.id, value=9))
    db_session.commit()

    resp = client.get("/hospitals/indicator-tree/default?month=__all__")
    assert resp.status_code == 200
    data = resp.json()

    def _find(node):
        if node.get("indicator_id") == ind.id:
            return node
        for child in node.get("children", []):
            found = _find(child)
            if found is not None:
                return found
        return None

    node = _find({"children": data["children"]})
    assert node is not None
    assert node["value"] == 24
    assert sorted(node["per_hospital"], key=lambda p: p["hospital_id"]) == [
        {"hospital_id": 1, "hospital": "General Hospital", "value": 8.0},
        {"hospital_id": 2, "hospital": "Central Medical", "value": 7.0},
        {"hospital_id": 3, "hospital": "Community Clinic", "value": 9.0},
    ]


def test_toggle_default_endpoint(client, db_session):
    """PUT /hospitals/indicators/{id}/toggle-default must write an IndicatorDefaultConfig row."""
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    resp = client.put(f"/hospitals/indicators/{ind.id}/toggle-default?month=2027-02")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_enabled"] is False

    cfg = db_session.query(IndicatorDefaultConfig).filter(
        IndicatorDefaultConfig.indicator_id == ind.id,
        IndicatorDefaultConfig.month == "2027-02",
    ).first()
    assert cfg is not None
    assert cfg.is_enabled is False


def test_default_tree_endpoint_reflects_default_config(client, db_session):
    """The default-scope tree endpoint must show disabled state from IndicatorDefaultConfig."""
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    resp = client.get("/hospitals/indicator-tree/default?month=2027-02")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_scope"] is True
    assert data["hospital"] == "Default (All Hospitals)"

    def _find(node, indicator_id):
        if node.get("indicator_id") == indicator_id:
            return node
        for child in node.get("children", []):
            found = _find(child, indicator_id)
            if found is not None:
                return found
        return None

    node = _find({"children": data["children"]}, ind.id)
    assert node is not None
    assert node["is_enabled"] is False


def test_hospital_tree_reflects_inherited_default(client, db_session):
    """A hospital with no override must show the inherited default state in its tree."""
    from app.models import Indicator, IndicatorDefaultConfig

    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorDefaultConfig(indicator_id=ind.id, month="2027-02", is_enabled=False))
    db_session.commit()

    resp = client.get("/hospitals/1/indicator-tree?month=2027-02")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_scope"] is False

    def _find(node, indicator_id):
        if node.get("indicator_id") == indicator_id:
            return node
        for child in node.get("children", []):
            found = _find(child, indicator_id)
            if found is not None:
                return found
        return None

    node = _find({"children": data["children"]}, ind.id)
    assert node is not None
    assert node["is_enabled"] is False


def _insert_indicator_value(db_session, hospital_id, month, code, value):
    from app.models import Indicator, IndicatorValue

    ind = db_session.query(Indicator).filter(Indicator.code == code).first()
    assert ind is not None, f"indicator {code} not seeded"
    db_session.add(IndicatorValue(
        hospital_id=hospital_id,
        month=month,
        indicator_id=ind.id,
        value=value,
    ))


def _all_active_indicator_count(db_session):
    from app.models import Indicator
    return db_session.query(Indicator).count()


def test_recalc_completeness_ignores_covered_children(client, db_session):
    """Missing sibling children whose partial sum equals the parent total must NOT
    reduce completeness in the dashboard recalculate path."""
    from app.models import QualityScore

    month = "2027-02"
    # Parent (Total Deliveries) fully accounted for by a subset of age groups.
    # 2.c, 2.d, 2.j are missing but 2.e+2.f+2.g+2.h+2.i == 2 (within tolerance).
    _insert_indicator_value(db_session, 1, month, "2", 27)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    total_indicators = _all_active_indicator_count(db_session)
    db_session.add(QualityScore(hospital_id=1, month=month, score=50.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["updated"] == 1

    qs = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month
    ).first()
    # present=6 (parent + 5 children), covered=3 (2.c, 2.d, 2.j),
    # active denominator excludes covered.
    filled_active = 6
    active_denom = total_indicators - 3
    expected_pct = round(filled_active / active_denom * 100, 1)
    assert qs.completeness == expected_pct


def test_recalc_completeness_still_penalizes_real_gaps(client, db_session):
    """When the partial age-group sum does NOT equal the total, the missing
    children remain missing and completeness reflects the true gap."""
    from app.models import QualityScore

    month = "2027-03"
    # 2.e+2.f+2.g+2.h+2.i == 27 but parent 2 == 31 -> 4 unaccounted -> NOT covered.
    _insert_indicator_value(db_session, 1, month, "2", 31)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    total_indicators = _all_active_indicator_count(db_session)
    db_session.add(QualityScore(hospital_id=1, month=month, score=50.0))
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200

    qs = db_session.query(QualityScore).filter(
        QualityScore.hospital_id == 1, QualityScore.month == month
    ).first()
    # present=6 (parent + 5 children), missing=3 not covered -> all active.
    expected_pct = round(6 / total_indicators * 100, 1)
    assert qs.completeness == expected_pct


def test_component_diagnostics_drilldown_excludes_covered_children(client, db_session):
    """The Completeness KPI drilldown must NOT list covered-by-parent indicators
    among its missing indicators."""
    from app.models import QualityScore

    month = "2027-04"
    # Parent fully accounted for by reported age groups; 2.c, 2.d, 2.j are covered.
    _insert_indicator_value(db_session, 1, month, "2", 27)
    for code, val in [("2.e", 9), ("2.f", 12), ("2.g", 4), ("2.h", 1), ("2.i", 1)]:
        _insert_indicator_value(db_session, 1, month, code, val)
    db_session.add(QualityScore(hospital_id=1, month=month, score=30.0))
    db_session.commit()

    resp = client.get(
        "/dashboard/component-diagnostics?",
        params={
            "hospital_id": 1,
            "month_from": month,
            "month_to": month,
            "metric": "completeness",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    # Collect every missing indicator listed anywhere in the completeness drilldown
    listed_missing = set()
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                listed_missing.update(h.get("missing_indicators", []))

    # Covered children must not appear as missing
    from app.models import Indicator
    covered_names = {ind.name for ind in db_session.query(Indicator).filter(
        Indicator.code.in_(["2.c", "2.d", "2.j"])
    ).all()}
    overlap = listed_missing & covered_names
    assert not overlap, f"covered children listed as missing: {overlap}"

    # Genuinely missing indicators (e.g. 3, 4, 5) still appear
    non_covered_missing = db_session.query(Indicator.name).filter(
        Indicator.parent_id.is_not(None),
        Indicator.code.notin_(["2.c", "2.d", "2.j", "2.e", "2.f", "2.g", "2.h", "2.i"]),
    ).limit(1).first()
    if non_covered_missing:
        assert listed_missing, "expected some genuinely missing indicators in drilldown"


def test_component_diagnostics_missing_by_indicator_months(client, db_session):
    """Affected-hospital drilldown must report, per missing indicator, the months
    it was missing in (so users know the missing month for every indicator)."""
    from app.models import QualityScore

    # Hospital 1 missing e.g. '3' in two months. Hospital 1 has values for '2' only.
    for month in ("2027-05", "2027-06"):
        _insert_indicator_value(db_session, 1, month, "2", 10)
        db_session.add(QualityScore(hospital_id=1, month=month, score=30.0))
    db_session.commit()

    resp = client.get(
        "/dashboard/component-diagnostics?",
        params={"metric": "completeness", "hospital_id": 1, "month_from": "2027-05", "month_to": "2027-06"},
    )
    assert resp.status_code == 200
    data = resp.json()

    hospital_rows = []
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                if h["hospital_id"] == 1:
                    hospital_rows.append(h)

    assert hospital_rows, "hospital 1 should appear as affected"
    for h in hospital_rows:
        assert "missing_by_indicator" in h
        if h["missing_by_indicator"]:
            for item in h["missing_by_indicator"]:
                assert "indicator" in item and "months" in item
                missing_month = item["months"]
                assert set(missing_month) <= {"2027-05", "2027-06"}

    # Every indicator reported missing overall must map to at least one month
    all_months_by_ind = {}
    for comp in data.get("components", []):
        for cause in comp.get("causes", []):
            for h in cause.get("affected_hospitals", []):
                if h["hospital_id"] == 1:
                    for item in h.get("missing_by_indicator", []):
                        all_months_by_ind.setdefault(item["indicator"], set()).update(item["months"])
    for name, months in all_months_by_ind.items():
        assert months, f"indicator {name!r} missing but has no reported months"

    # Month-by-Month Detail must include a per-month missing indicator list
    cp_comp = next((c for c in data.get("components", []) if c.get("key") == "completeness"), None)
    assert cp_comp is not None
    monthly_rows = cp_comp.get("monthly", [])
    assert any(r.get("missing_indicators") for r in monthly_rows), (
        "expected missing_indicators in completeness monthly rows"
    )

    # Single-hospital responses must carry the FULL missing list (no 10-cap),
    # since the QR Completeness tab uses it to list everything still missing.
    for r in monthly_rows:
        if r.get("missing_indicators"):
            assert len(r["missing_indicators"]) == r["missing_count"], (
                f"month {r['month']}: expected {r['missing_count']} missing indicators, "
                f"got {len(r['missing_indicators'])}"
            )


def test_save_tree_config_triggers_full_reanalysis(client, db_session):
    """Disabling an indicator via tree save must call run_full_analysis(force=True),
    which purges stale stored rows and writes fresh ones."""
    from app.models import Indicator, IndicatorValue, AnomalyResult

    ind = db_session.query(Indicator).first()
    assert ind is not None, "no indicators seeded"
    _insert_indicator_value(db_session, 1, "2027-01", ind.code, 10)
    db_session.commit()

    # Seed a stale AnomalyResult that references the indicator
    db_session.add(AnomalyResult(
        hospital_id=1, month="2027-01",
        indicator_code=ind.code, rate_name="STALE_RATE",
        value=10, benchmark=5, z_score=1.0, is_outlier=True,
    ))
    db_session.commit()

    stale_count = db_session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == 1,
        AnomalyResult.month == "2027-01",
        AnomalyResult.rate_name == "STALE_RATE",
    ).count()
    assert stale_count >= 1

    # Disable that indicator via tree save
    resp = client.post(
        f"/hospitals/1/save-tree-config?month=2027-01",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200

    # Stale AnomalyResult rows must have been purged and replaced
    # by run_full_analysis (which calls _save_anomaly_results that
    # deletes old rows first). The stale row with STALE_RATE should be gone.
    stale_rows = db_session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == 1,
        AnomalyResult.month == "2027-01",
        AnomalyResult.rate_name == "STALE_RATE",
    ).count()
    assert stale_rows == 0, (
        f"Stale AnomalyResult with STALE_RATE still present after save — "
        f"run_full_analysis was not called"
    )


def test_save_default_tree_config_triggers_full_reanalysis(client, db_session):
    """Disabling an indicator via default tree save must re-run analysis for all hospitals."""
    from app.models import Indicator, IndicatorValue, AnomalyResult, Hospital

    ind = db_session.query(Indicator).first()
    assert ind is not None, "no indicators seeded"
    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    assert hosp is not None, "no active hospitals seeded"

    # Insert value for the indicator
    _insert_indicator_value(db_session, hosp.id, "2027-01", ind.code, 10)
    db_session.commit()

    # Seed a stale AnomalyResult
    db_session.add(AnomalyResult(
        hospital_id=hosp.id, month="2027-01",
        indicator_code=ind.code, rate_name="STALE_DEFAULT_RATE",
        value=10, benchmark=5, z_score=1.0, is_outlier=True,
    ))
    db_session.commit()

    stale_count = db_session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hosp.id,
        AnomalyResult.month == "2027-01",
        AnomalyResult.rate_name == "STALE_DEFAULT_RATE",
    ).count()
    assert stale_count >= 1

    # Disable that indicator via default tree save
    resp = client.post(
        "/hospitals/save-default-tree-config?month=2027-01",
        json={"items": [{"indicator_id": ind.id, "is_enabled": False}]},
    )
    assert resp.status_code == 200

    # Stale AnomalyResult must have been purged
    stale_rows = db_session.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hosp.id,
        AnomalyResult.month == "2027-01",
        AnomalyResult.rate_name == "STALE_DEFAULT_RATE",
    ).count()
    assert stale_rows == 0, (
        f"Stale AnomalyResult with STALE_DEFAULT_RATE still present after default save — "
        f"run_full_analysis was not called for all hospitals"
    )


def test_confidence_excludes_disabled_indicators(client, db_session):
    """Disabled indicators must not appear as CRITICAL 'DATA MISSING' in confidence."""
    from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig

    hosp = db_session.query(Hospital).filter(Hospital.is_active.is_(True)).first()
    assert hosp is not None, "no active hospitals"
    # Use indicator code "2" (a key indicator code in confidence calculation)
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    assert ind is not None, "no indicator with code '2'"

    # Add a value for the disabled indicator and another enabled one
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=ind.id, value=100))
    other_ind = db_session.query(Indicator).filter(Indicator.code == "3").first()
    assert other_ind is not None, "no indicator with code '3'"
    db_session.add(IndicatorValue(hospital_id=hosp.id, month="2027-01", indicator_id=other_ind.id, value=50))
    db_session.commit()

    # Disable indicator "2" via hospital config
    db_session.add(HospitalIndicatorConfig(
        hospital_id=hosp.id, indicator_id=ind.id, is_enabled=False
    ))
    db_session.commit()

    # Get confidence
    resp = client.get(
        f"/confidence/{hosp.id}?month=2027-01"
    )
    assert resp.status_code == 200
    data = resp.json()
    assessed_codes = [i["indicator_code"] for i in data.get("indicators", [])]
    assert ind.code not in assessed_codes, (
        f"Disabled indicator {ind.code} still appears in confidence assessed list"
    )