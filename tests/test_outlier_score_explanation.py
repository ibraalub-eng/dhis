"""The outlier-score Why popup must explain the outliers that moved it.

Symptom: clicking "Why" on the Outlier Score KPI showed a list of source-data
gaps ("Indicator 14 has no value for this month", …) and nothing about the
outliers themselves. Missing cells belong to completeness — they create no
outlier row, so they cannot explain this component — and the popup now names
the stored HIGH/VERY_HIGH rows the penalty actually counts.
"""
import pytest
from fastapi.testclient import TestClient

from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)

MONTH = "2027-03"


@pytest.fixture()
def month_with_outliers(db_session):
    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    required = db_session.query(Indicator).filter(Indicator.code == "2").one()
    missing = db_session.query(Indicator).filter(Indicator.code == "17").one()

    db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                  indicator_id=required.id, value=100))
    db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                  indicator_id=missing.id, value=None))
    db_session.add(QualityScore(hospital_id=hosp.id, month=MONTH, score=80.0,
                                rule_compliance=90.0, completeness=80.0,
                                consistency=90.0, outlier_penalty=12.4))
    db_session.add_all([
        LayeredOutlierResult(
            hospital_id=hosp.id, month=MONTH, analysis_code="rate_cs",
            indicator_id=None, rate=26.0, peer_mean=7.5, peer_count=5,
            outlier_level="VERY_HIGH", outlier_type="PEER_ANOMALY",
            interpretation="Differs from the peer baseline",
            investigation_route="contextual",
        ),
        LayeredOutlierResult(
            hospital_id=hosp.id, month=MONTH, analysis_code="5",
            indicator_id=required.id, raw_value=90.0, peer_mean=40.0,
            peer_count=5, outlier_level="HIGH",
            outlier_type="HISTORICAL_ANOMALY",
            interpretation="Above this hospital's own baseline",
        ),
    ])
    db_session.commit()
    return hosp


def _explain(app, hosp, component):
    client = TestClient(app)
    response = client.get(
        f"/audit/explain?kind=quality_score&hospital_id={hosp.id}"
        f"&month={MONTH}&component={component}"
    )
    assert response.status_code == 200
    return response.json()


def test_outlier_score_names_the_drivers(app, db_session, month_with_outliers):
    payload = _explain(app, month_with_outliers, "outlier_score")

    drivers = payload.get("outliers") or []
    assert len(drivers) == 2
    # Worst first: the popup must read like the penalty.
    assert drivers[0]["level"] == "VERY_HIGH"
    assert drivers[0]["indicator_code"] == "rate_cs"
    assert drivers[1]["indicator_code"] == "5"

    why = payload["why"]
    assert "VERY_HIGH" in why
    assert "has no value" not in why
    assert payload["what"].startswith("Outlier score")
    assert payload["component"] == "outlier_score"


def test_outlier_component_does_not_list_missing_cells(
        app, db_session, month_with_outliers):
    payload = _explain(app, month_with_outliers, "outlier_score")
    kinds = {p.get("kind") for p in payload.get("data_problems") or []}
    assert "missing_value" not in kinds, (
        "missing cells create no outlier row — they cannot explain this score"
    )


def test_completeness_component_still_reports_the_missing_cell(
        app, db_session, month_with_outliers):
    payload = _explain(app, month_with_outliers, "completeness")
    missing = {p.get("indicator_code") for p in payload.get("data_problems") or []
               if p.get("kind") == "missing_value"}
    assert missing == {"17"}, "the gate is scoped to the outlier component only"


def test_optional_element_without_data_never_reaches_the_outlier_scan(
        app, db_session):
    """An Optional data element with no value this month is skipped, not flagged.

    Doctrine (COVERAGE-DISABLE-DOCTRINE): an element flagged Optional on the
    Data Tree is legitimately absent. It creates no outlier row (there is no
    value to compare), so it can neither be listed in the outlier scan nor
    explain/lower the outlier score.
    """
    from app.engine.anomaly.layered import (
        Thresholds,
        build_analysis_specs,
        run_layered_analysis,
        should_persist,
    )

    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    optional = db_session.query(Indicator).filter(Indicator.code == "17.a").one()
    optional.requirement_type = "Optional"
    db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                  indicator_id=optional.id, value=None))
    db_session.add(QualityScore(hospital_id=hosp.id, month=MONTH, score=88.0,
                                rule_compliance=95.0, completeness=90.0,
                                consistency=90.0, outlier_penalty=0.0))
    db_session.commit()

    # The scan runs one spec per data element; the Optional element has no
    # value, so its result must not be persisted as an outlier row.
    spec = next(s for s in build_analysis_specs(db_session)
                if s.analysis_code == "17.a")
    values = {"2": 100.0, "17.c": 4.0}
    results = run_layered_analysis(
        [spec], {MONTH: values}, MONTH, hosp.id,
        {hosp.id: {MONTH: values}}, {}, Thresholds(),
    )
    assert len(results) == 1
    assert results[0].raw.value is None
    assert should_persist(results[0]) is False
    assert results[0].classification.outlier_level in (None, "NONE")

    # …and the outlier-score popup names no driver and no missing cell.
    client = TestClient(app)
    payload = client.get(
        f"/audit/explain?kind=quality_score&hospital_id={hosp.id}"
        f"&month={MONTH}&component=outlier_score"
    ).json()
    assert payload["outliers"] == []
    assert "has no value" not in payload["why"]
    assert payload["data_problems"] == []


def test_why_popup_renders_the_outlier_section():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "js" / "explain.js").read_text(encoding="utf-8")
    assert "'Outliers that lowered the score'" in js
    assert "p.outliers" in js

    i18n = (root / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "'Outliers that lowered the score':" in i18n
