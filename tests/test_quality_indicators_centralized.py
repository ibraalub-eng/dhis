"""Quality section must consume centralized indicators only.

Every clinical rate shown under Quality Reports (the anomaly sub-tab and its
PDF/Excel exports) must resolve through the Indicators Registry and the shared
calculation engine. No Quality module may own a clinical rate formula, and a
stored value must never be presented as current after its formula changed.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine import indicator_calc, indicator_service
from app.engine.anomaly.zscore import detect_anomalies
from app.main import app
from app.models import (
    AnomalyResult,
    Hospital,
    IndicatorDefinition,
    LayeredOutlierResult,
    QualityScore,
)

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_JS = ROOT / "static" / "js" / "upload.js"
REPORTS_PY = ROOT / "app" / "api" / "reports.py"
QUALITY_ENGINE = ROOT / "app" / "engine" / "quality"


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


def _quality_js() -> str:
    js = UPLOAD_JS.read_text(encoding="utf-8")
    start = js.index("let allQualityReports")
    return js[start:]


def _cs_definition(db_session) -> IndicatorDefinition:
    definition = (
        db_session.query(IndicatorDefinition)
        .filter(
            IndicatorDefinition.source_site == "zscore",
            IndicatorDefinition.legacy_code == "rate_cs",
        )
        .one()
    )
    return definition


def _resolved_cs(db_session):
    return next(
        resolved
        for resolved in indicator_service.resolve_active_definitions(
            db_session, site="zscore"
        )
        if resolved.definition is not None
        and resolved.definition.legacy_code == "rate_cs"
    )


# ── static guards: no clinical formula may live in the Quality section ───────

def test_quality_rule_engine_has_no_duplicated_rate_rules():
    rules = (QUALITY_ENGINE / "rules.py").read_text(encoding="utf-8")
    # The R041-R050 benchmark-rate rules computed (num/den)*100 themselves.
    for marker in ("def _rate(", "def _benchmark_rate", "def _rate_low",
                   "def _cross_hospital_rate", "_cross_hospital_rate(s."):
        assert marker not in rules, marker
    assert '"R041"' not in rules and '"R050"' not in rules
    # Data-quality trend rules may keep generic percentage-change arithmetic.
    assert "_month_over" in rules


def test_quality_report_api_does_not_compute_clinical_rates():
    source = REPORTS_PY.read_text(encoding="utf-8")
    # No indicator-specific numerator/denominator or mortality formula.
    assert not re.search(r"maternal|neonatal|stillbirth|cesarean|C-section", source, re.I)
    assert not re.search(r"['\"]1[17]['\"]\s*/\s*['\"]2['\"]", source)
    assert "* 1000" not in source and "*1000" not in source


def test_quality_reports_js_does_not_recalculate_rates():
    quality_js = _quality_js()
    assert "* 100" not in quality_js
    assert "* 1000" not in quality_js
    assert "/ 1000" not in quality_js
    # Values must be rendered from registry metadata, never re-derived.
    assert "_fmtAnomalyValue" in quality_js
    assert "_formulaCell" in quality_js
    assert "a.unit" in quality_js
    assert "formula_status" in quality_js
    # The anomaly table renders 10 columns (Layer breakdown included), so the
    # empty-state row must span all of them.
    assert 'colspan="10"' in quality_js


# ── registry is the source of every Quality anomaly value ────────────────────

def test_quality_anomaly_value_matches_shared_engine_and_registry(db_session):
    resolved = _resolved_cs(db_session)
    data = {
        "Quality target": {"5": 80, "2": 300},
        "Peer one": {"5": 20, "2": 300},
        "Peer two": {"5": 25, "2": 300},
    }

    rows = detect_anomalies(
        data, "Quality target", "2026-03", additional_indicators=[resolved])
    row = next(r for r in rows if r.indicator_id == resolved.indicator_id)

    expected = indicator_service.calculate_from_values(
        resolved, data["Quality target"], hospital_id=0, month="2026-03")
    assert expected.status == indicator_calc.STATUS_OK
    assert row.value == pytest.approx(round(expected.value, 2))
    assert row.indicator_id == resolved.indicator_id
    assert row.formula_version == resolved.formula_version


def test_registry_formula_change_changes_quality_anomaly_value(db_session):
    definition = _cs_definition(db_session)
    data = {
        "Quality target": {"5": 80, "2": 300},
        "Peer one": {"5": 20, "2": 300},
        "Peer two": {"5": 25, "2": 300},
    }
    resolved_before = _resolved_cs(db_session)
    before = detect_anomalies(
        data, "Quality target", "2026-03",
        additional_indicators=[resolved_before])
    before_row = next(
        r for r in before if r.indicator_id == resolved_before.indicator_id)
    assert before_row.value == pytest.approx(26.67)

    # Edit the registry formula exactly the way the Indicators API does:
    # bump the version and change the configured multiplier.
    definition.multiplier = 1000.0
    definition.version = 2
    db_session.commit()

    resolved = _resolved_cs(db_session)
    assert resolved.formula_version == "2"
    after = detect_anomalies(
        data, "Quality target", "2026-03", additional_indicators=[resolved])
    after_row = next(
        r for r in after if r.indicator_id == resolved.indicator_id)
    assert after_row.value == pytest.approx(266.67)
    assert after_row.formula_version == "2"


# ── report detail: units + formula freshness ─────────────────────────────────

def _seed_quality_report(db_session, definition):
    hospital = Hospital(name="Quality Rate Hospital")
    db_session.add(hospital)
    db_session.flush()
    db_session.add(QualityScore(
        hospital_id=hospital.id,
        month="2026-03",
        score=91.0,
        rule_compliance=95.0,
        completeness=90.0,
        consistency=88.0,
        outlier_penalty=5.0,
    ))
    db_session.add(AnomalyResult(
        hospital_id=hospital.id,
        month="2026-03",
        indicator_code="rate_cs",
        indicator_id=f"derived:{definition.id}",
        formula="{5} / {2} * 100",
        formula_version="1",
        rate_name="C-section rate",
        value=26.67,
        benchmark=7.5,
        z_score=3.1,
        is_outlier=True,
    ))
    # The layered row is the detection truth now; the report card counts it and
    # AnomalyResult is projected from it during analysis.
    db_session.add(LayeredOutlierResult(
        hospital_id=hospital.id,
        month="2026-03",
        analysis_code="rate_cs",
        indicator_id=None,
        raw_value=80,
        rate=26.67,
        peer_mean=7.5,
        peer_count=3,
        historical_mean=7.1,
        outlier_level="HIGH",
        outlier_type="PEER_ANOMALY",
        outlier_method="peer_zscore",
        investigation_required=True,
        investigation_route="contextual",
    ))
    db_session.commit()
    return hospital


def test_quality_detail_attaches_unit_and_marks_current_formula(client, db_session):
    definition = _cs_definition(db_session)
    hospital = _seed_quality_report(db_session, definition)

    response = client.get(
        f"/reports/detail/{hospital.id}", params={"month": "2026-03"})
    assert response.status_code == 200
    row = response.json()["anomaly_results"][0]
    assert row["unit"] == "%"
    assert row["formula_status"] == "current"
    assert row["current_formula_version"] == "1"


def test_quality_detail_flags_stale_formula_version(client, db_session):
    definition = _cs_definition(db_session)
    hospital = _seed_quality_report(db_session, definition)
    definition.multiplier = 1000.0
    definition.version = 2
    db_session.commit()

    response = client.get(
        f"/reports/detail/{hospital.id}", params={"month": "2026-03"})
    assert response.status_code == 200
    row = response.json()["anomaly_results"][0]
    assert row["formula_status"] == "stale"
    assert row["current_formula_version"] == "2"
    # The stored value is not silently replaced; it is explicitly marked stale.
    assert row["value"] == pytest.approx(26.67)


def test_quality_report_list_and_detail_agree_on_the_same_indicator(client, db_session):
    definition = _cs_definition(db_session)
    hospital = _seed_quality_report(db_session, definition)

    listed = client.get("/reports/", params={"hospital_id": hospital.id})
    assert listed.status_code == 200
    outlier = listed.json()[0]["outliers"][0]
    detail = client.get(
        f"/reports/detail/{hospital.id}", params={"month": "2026-03"})
    stored = detail.json()["anomaly_results"][0]

    # The card counts the layered row (the detection truth) and names the same
    # indicator at the same value the detail shows.
    assert outlier["indicator"] == stored["rate_name"] == "C-section rate"
    assert outlier["value"] == stored["value"] == pytest.approx(26.67)
    assert outlier["level"] == "HIGH"
    assert stored["indicator_id"] == f"derived:{definition.id}"


def test_quality_excel_export_carries_unit_and_formula_status(client, db_session):
    import io

    import openpyxl

    definition = _cs_definition(db_session)
    hospital = _seed_quality_report(db_session, definition)
    response = client.get(
        f"/reports/export/{hospital.id}/excel", params={"month": "2026-03"})
    assert response.status_code == 200

    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    rows = list(workbook.active.iter_rows(values_only=True))
    cells = {str(value) for row in rows for value in row if value is not None}
    assert "Unit" in cells and "Formula" in cells
    assert "%" in cells and "current" in cells
    # The exported value must be the same stored registry result the detail
    # endpoint returns (not a re-derived or rounded-by-someone-else number).
    header_index = next(
        index for index, row in enumerate(rows) if row and row[0] == "Rate Name")
    anomaly_row = rows[header_index + 1]
    assert anomaly_row[1] == "26.67"
    assert anomaly_row[4] == "%"


def test_quality_pdf_export_renders_with_registry_columns(client, db_session):
    definition = _cs_definition(db_session)
    hospital = _seed_quality_report(db_session, definition)
    response = client.get(
        f"/reports/export/{hospital.id}/pdf", params={"month": "2026-03"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")


def test_quality_tab_is_declared_as_an_indicator_consumer(db_session):
    resolved = _resolved_cs(db_session)
    dependency_ids = {
        dependency["id"] for dependency in indicator_service.dependencies(resolved)
    }
    assert "quality" in dependency_ids


def test_legacy_rate_spec_id_resolves_to_the_registry_row(db_session):
    definition = _cs_definition(db_session)
    provenance = indicator_service.registry_provenance(
        db_session, "rate:zscore:rate_cs", "1")
    assert provenance["indicator_id"] == f"derived:{definition.id}"
    assert provenance["unit"] == "%"
    assert provenance["formula_status"] == "current"


# ── missing / zero-denominator / unregistered handling ───────────────────────

def test_zero_denominator_is_unavailable_not_zero(db_session):
    resolved = _resolved_cs(db_session)
    outcome = indicator_service.calculate_from_values(
        resolved, {"5": 10, "2": 0}, hospital_id=0, month="2026-03")
    assert outcome.status == indicator_calc.STATUS_ZERO_DENOMINATOR
    assert outcome.value is None


def test_missing_numerator_does_not_create_a_quality_anomaly(db_session):
    resolved = _resolved_cs(db_session)
    data = {
        "Quality target": {"2": 300},
        "Peer one": {"5": 20, "2": 300},
        "Peer two": {"5": 25, "2": 300},
    }
    rows = detect_anomalies(
        data, "Quality target", "2026-03", additional_indicators=[resolved])
    assert all(r.indicator_id != resolved.indicator_id for r in rows)


def test_zero_denominator_does_not_create_a_quality_anomaly(db_session):
    resolved = _resolved_cs(db_session)
    data = {
        "Quality target": {"5": 10, "2": 0},
        "Peer one": {"5": 20, "2": 300},
        "Peer two": {"5": 25, "2": 300},
    }
    rows = detect_anomalies(
        data, "Quality target", "2026-03", additional_indicators=[resolved])
    assert all(r.indicator_id != resolved.indicator_id for r in rows)


def test_unregistered_stored_indicator_is_reported_not_hidden(db_session):
    provenance = indicator_service.registry_provenance(
        db_session, "derived:999999", "1")
    assert provenance["formula_status"] == "unregistered"
    assert provenance["is_active"] is False


def test_missing_formula_version_is_unverified(db_session):
    definition = _cs_definition(db_session)
    provenance = indicator_service.registry_provenance(
        db_session, f"derived:{definition.id}", None)
    assert provenance["formula_status"] == "unverified"


def test_quality_indicator_uses_the_requested_hospital_and_month(db_session):
    from app.models import Indicator, IndicatorValue

    raw = {
        indicator.code: indicator
        for indicator in db_session.query(Indicator)
        .filter(Indicator.code.in_(("5", "2")))
        .all()
    }
    first = Hospital(name="Indicator scope one")
    second = Hospital(name="Indicator scope two")
    db_session.add_all([first, second])
    db_session.flush()

    samples = [
        (first, "2026-01", 10, 100),
        (first, "2026-02", 50, 100),
        (second, "2026-02", 20, 100),
    ]
    for hospital, month, numerator, denominator in samples:
        db_session.add_all([
            IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=raw["5"].id,
                month=month,
                value=numerator,
            ),
            IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=raw["2"].id,
                month=month,
                value=denominator,
            ),
        ])
    db_session.commit()

    january = indicator_service.calculate(
        db_session, "rate_cs", first.id, "2026-01", site="zscore")
    february_first = indicator_service.calculate(
        db_session, "rate_cs", first.id, "2026-02", site="zscore")
    february_second = indicator_service.calculate(
        db_session, "rate_cs", second.id, "2026-02", site="zscore")

    assert january.value == pytest.approx(10)
    assert february_first.value == pytest.approx(50)
    assert february_second.value == pytest.approx(20)
    assert january.month == "2026-01" and february_second.hospital_id == second.id
