from types import SimpleNamespace

import pytest

from app.engine import indicator_calc
from app.engine.anomaly.zscore import detect_anomalies
from app.engine.clinical import compute_all_classifications, run_clinical_analysis
from app.engine.indicator_service import ResolvedIndicator
from app.engine.rate_config import compute_rate
from app.engine.smart.indicator_forecast import indicator_rate_from_values


def test_rate_consumers_use_the_shared_ratio_evaluator():
    assert compute_rate(
        {"5": 10, "2": 200}, ("5",), ("2",), 1000
    ) == pytest.approx(50)
    assert compute_rate({"5": 10}, ("5",), ("2",), 100) is None

    assert indicator_rate_from_values(
        "cs_rate", {"5": 10, "2": 200}
    ) == pytest.approx(5)
    assert indicator_rate_from_values(
        "cs_rate", {"5": 10}
    ) is None


def test_regional_analytics_uses_registry_rates():
    from app.engine.smart.regional import _gov_metrics

    metrics = _gov_metrics({
        "sums": {
            "deliveries": 200,
            "cs_count": 20,
            "live_births": 300,
            "preterm": 30,
            "lbw": 45,
            "sb": 9,
            "smm": 6,
            "mat_deaths": 2,
            "nd": 3,
            "high_risk": 60,
            "adol_a": 15,
            "adol_b": 15,
        },
    })

    assert metrics["nmr"] == pytest.approx(10)
    assert metrics["mmr"] == pytest.approx(2000 / 3)
    assert metrics["stillbirth_rate"] == pytest.approx(30)
    assert metrics["cs_rate"] == pytest.approx(10)
    assert metrics["preterm_rate"] == pytest.approx(10)
    assert metrics["lbw_rate"] == pytest.approx(15)
    assert metrics["smm_rate"] == pytest.approx(30)
    assert metrics["adolescent_rate"] == pytest.approx(10)
    assert metrics["high_risk_rate"] == pytest.approx(20)


def test_clinical_rates_do_not_turn_an_unreported_numerator_into_zero():
    rows = compute_all_classifications({"2": 200})
    cs_rate = next(row for row in rows if row.indicator_code == "rate_cs")
    assert cs_rate.value is None
    assert cs_rate.classification == "unknown"


def test_clinical_analysis_loads_active_managed_definitions(db_session):
    from app.models import IndicatorDefinition

    db_session.add(IndicatorDefinition(
        code="managed_clinical_rate",
        name="Managed Clinical Rate",
        formula_type="expression",
        expression="{5} / {2} * 100",
        result_type="percentage",
        unit="%",
        direction="higher_is_better",
        threshold_low=10,
        is_active=True,
        version=2,
    ))
    db_session.flush()

    result = run_clinical_analysis(
        hospital="Test Hospital",
        month="2026-03",
        values={"5": 20, "2": 100},
        include_ai=False,
        session=db_session,
    )
    custom = next(
        row for row in result.classifications
        if row.indicator_code == "managed_clinical_rate"
    )
    assert custom.value == pytest.approx(20)
    assert custom.classification == "normal"
    assert custom.indicator_id.startswith("derived:")
    assert custom.formula_version == "2"


def test_outlier_analysis_calculates_and_identifies_managed_definitions():
    from app.engine.anomaly.comparison import compare_hospitals

    definition = SimpleNamespace(
        code="custom_rate",
        name="Custom Rate",
        formula_type="expression",
        expression="{5} / {2} * 100",
        numerator_codes=None,
        denominator_codes=None,
        multiplier=1,
        aggregation="sum",
        precision=None,
        rounding="half_up",
    )
    resolved = ResolvedIndicator(
        source="derived",
        code="custom_rate",
        name="Custom Rate",
        indicator_id="derived:42",
        formula_version="3",
        formula="{5} / {2} * 100",
        ref_codes=["5", "2"],
        definition=definition,
    )
    data = {
        "target": {"5": 80, "2": 100},
        "peer-a": {"5": 20, "2": 100},
        "peer-b": {"5": 25, "2": 100},
        "peer-c": {"5": 30, "2": 100},
    }

    result = detect_anomalies(
        data,
        "target",
        "2026-03",
        additional_indicators=[resolved],
    )
    custom_rate = next(row for row in result if row.indicator_id == "derived:42")
    assert custom_rate.value == pytest.approx(80)
    assert custom_rate.indicator_code == "custom_rate"
    assert custom_rate.formula == "{5} / {2} * 100"
    assert custom_rate.formula_version == "3"
    assert custom_rate.benchmark == pytest.approx(25)

    comparisons = compare_hospitals(
        {name: {"2026-03": values} for name, values in data.items()},
        "2026-03",
        additional_indicators=[resolved],
    )
    managed_comparisons = [
        row for row in comparisons if row.indicator_id == "derived:42"
    ]
    assert len(managed_comparisons) == 4
    assert managed_comparisons[0].formula_version == "3"


def test_audit_benchmark_includes_managed_definition(db_session):
    from app.engine.audit.benchmark import get_benchmark
    from app.models import Hospital, Indicator, IndicatorDefinition, IndicatorValue

    raw_indicators = {
        indicator.code: indicator
        for indicator in db_session.query(Indicator).filter(
            Indicator.code.in_(("5", "2"))
        ).all()
    }
    assert set(raw_indicators) == {"5", "2"}
    hospitals = [
        Hospital(name=name)
        for name in ("Managed target", "Managed peer one", "Managed peer two")
    ]
    db_session.add_all(hospitals)
    db_session.flush()
    monthly_values = ((80, 100), (20, 100), (30, 100))
    for hospital, (numerator, denominator) in zip(hospitals, monthly_values):
        db_session.add_all([
            IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=raw_indicators["5"].id,
                month="2026-03",
                value=numerator,
            ),
            IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=raw_indicators["2"].id,
                month="2026-03",
                value=denominator,
            ),
        ])
    db_session.add(IndicatorDefinition(
        code="managed_audit_rate",
        name="Managed Audit Rate",
        formula_type="expression",
        expression="{5} / {2} * 100",
        result_type="percentage",
        unit="%",
        is_active=True,
        version=4,
    ))
    db_session.commit()

    result = get_benchmark(db_session, hospitals[0].id, "2026-03")
    comparison = result["comparisons"]["Managed Audit Rate"]
    assert comparison["hospital_value"] == pytest.approx(80)
    assert comparison["peer_average"] == pytest.approx(25)
    assert comparison["indicator_id"].startswith("derived:")
    assert comparison["formula_version"] == "4"


def test_ratio_evaluator_reports_zero_denominator_without_fabricating_value():
    outcome = indicator_calc.evaluate_ratio_values(
        ["5"], ["2"], {"5": 10, "2": 0}, multiplier=100
    )
    assert outcome.status == indicator_calc.STATUS_ZERO_DENOMINATOR
    assert outcome.value is None


def test_stored_anomaly_keeps_formula_version_provenance(db_session):
    from app.engine.anomaly.zscore import AnomalyResultData
    from app.engine.pipeline import _save_anomaly_results
    from app.models import AnomalyResult, Hospital

    hospital = Hospital(name="Indicator provenance hospital")
    db_session.add(hospital)
    db_session.flush()

    _save_anomaly_results(
        db_session,
        hospital.id,
        "2026-03",
        [
            AnomalyResultData(
                indicator_code="custom_rate",
                rate_name="Custom Rate",
                value=20,
                benchmark=10,
                z_score=2,
                is_outlier=True,
                indicator_id="derived:42",
                formula="{5} / {2} * 100",
                formula_version="3",
            )
        ],
    )

    stored = db_session.query(AnomalyResult).filter_by(
        hospital_id=hospital.id, month="2026-03"
    ).one()
    assert stored.indicator_id == "derived:42"
    assert stored.formula == "{5} / {2} * 100"
    assert stored.formula_version == "3"
