"""Quality Score outlier component ↔ DATA TREE (2026-10-22).

The stored Quality Score used to take its outlier penalty only from the
classic anomaly rows, whose candidate set is the Indicators-screen registry
(``resolve_active_definitions(site="zscore")`` — 7 rate definitions). Deactivating
those definitions zeroed the penalty while the Outlier Diagnostics screen kept
flagging data-tree elements.

Contract now: when the pipeline supplies the layered rows for the
hospital+month (every non-synthetic Data Tree element + the active rate specs),
the penalty is the share of those rows flagged HIGH/VERY_HIGH. The classic
registry-based penalty remains the fallback when layered results are
unavailable.
"""
from types import SimpleNamespace

import pytest

from app.engine.quality import FLAGGED_LEVELS, calculate_quality_score


def _layered(level, name="Element"):
    return SimpleNamespace(
        spec=SimpleNamespace(name=name, analysis_code=name),
        classification=SimpleNamespace(outlier_level=level, outlier_type="NORMAL"),
    )


def _rows(levels):
    return [_layered(level, name=f"Element {i}") for i, level in enumerate(levels)]


def test_penalty_is_share_of_flagged_tree_rows():
    rows = _rows(["HIGH"] * 4 + ["NONE"] * 96)
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 2}, layered_results=rows)
    # 4 / 100 * 2 = 8%
    assert score["outlier_penalty"] == pytest.approx(8.0)


@pytest.mark.parametrize("level", ["NONE", "LOW", "MODERATE"])
def test_mild_deviations_do_not_penalize(level):
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 2},
        layered_results=_rows([level] * 50))
    assert score["outlier_penalty"] == 0.0


def test_very_high_counts_as_outlier():
    assert "VERY_HIGH" in FLAGGED_LEVELS
    rows = _rows(["VERY_HIGH"] * 10 + ["NONE"] * 90)
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 2}, layered_results=rows)
    assert score["outlier_penalty"] == pytest.approx(20.0)
    # No rule failures (100%) and no required codes (completeness 0%):
    # 100*0.35 + 0*0.25 + 100*0.25 + (100-20)*0.15 = 72.0
    assert score["score"] == pytest.approx(72.0)


def test_layered_rows_replace_the_registry_only_penalty():
    """Classic rows (registry definitions) must not decide the penalty when the
    data-tree rows are available — otherwise a deactivated definition set
    silently zeroes (or inflates) the component."""
    from app.engine.anomaly import AnomalyResultData

    registry_anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 4.0, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 3.5, True),
    ]
    tree_rows = _rows(["NONE"] * 98 + ["HIGH"] * 2)
    score = calculate_quality_score(
        [], {}, registry_anomalies, set(), {"outlier_multiplier": 2},
        layered_results=tree_rows)
    # 2 / 100 * 2 = 4% — not 2 / 2 * 2 = 100%
    assert score["outlier_penalty"] == pytest.approx(4.0)
    assert not any("C-section rate" in issue for issue in score["issues"])


def test_classic_penalty_remains_the_fallback():
    from app.engine.anomaly import AnomalyResultData

    registry_anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 4.0, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 3.5, False),
    ]
    score = calculate_quality_score(
        [], {}, registry_anomalies, set(), {"outlier_multiplier": 2})
    assert score["outlier_penalty"] == pytest.approx(100.0)
    assert any("C-section rate" in issue for issue in score["issues"])


def test_issues_name_flagged_tree_indicators_and_stay_readable():
    rows = _rows(["HIGH"] * 15 + ["NONE"] * 85)
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 2}, layered_results=rows)
    flagged_issues = [i for i in score["issues"] if i.startswith("Anomaly: ")]
    assert len(flagged_issues) == 10  # MAX_LAYERED_ISSUES
    assert any("and 5 more flagged indicator" in i for i in score["issues"])


def test_empty_layered_rows_mean_no_penalty():
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 2}, layered_results=[])
    assert score["outlier_penalty"] == 0.0


def test_pipeline_penalty_matches_its_layered_rows(db_session, sample_values):
    """End-to-end: run_full_analysis stores a QualityScore whose
    outlier_penalty is the data-tree ratio, over far more indicators than the
    registry's zscore slice."""
    from app.config_utils import get_config_dict
    from app.engine import indicator_service
    from app.engine.pipeline import run_full_analysis
    from app.models import Hospital, Indicator, IndicatorValue, LayeredOutlierResult, QualityScore

    hospital = db_session.query(Hospital).first()
    month = "2031-05"
    for code, value in sample_values.items():
        ind = db_session.query(Indicator).filter(Indicator.code == code).first()
        if ind:
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=ind.id,
                month=month, value=value))
    db_session.commit()

    run_full_analysis(db_session, hospital.id, month, force=True)

    rows = (
        db_session.query(LayeredOutlierResult)
        .filter(LayeredOutlierResult.hospital_id == hospital.id,
                LayeredOutlierResult.month == month)
        .all()
    )
    assert rows, "layered analysis must persist data-tree rows"
    registry = indicator_service.resolve_active_definitions(
        db_session, site="zscore")
    assert len(rows) > len(registry), (
        "the score must cover the data tree, not only the registry slice")

    multiplier = float(get_config_dict(db_session, "quality").get(
        "outlier_multiplier", 1.5))
    flagged = sum(1 for r in rows if r.outlier_level in FLAGGED_LEVELS)
    expected = min(1.0, flagged / len(rows) * multiplier) * 100

    qs = (
        db_session.query(QualityScore)
        .filter(QualityScore.hospital_id == hospital.id,
                QualityScore.month == month)
        .first()
    )
    assert qs is not None
    assert qs.outlier_penalty == pytest.approx(expected, abs=0.1)

    # The score's own components still combine with the published formula.
    from app.engine.quality import combine_quality_score
    cfg = get_config_dict(db_session, "quality")
    assert qs.score == pytest.approx(combine_quality_score(
        qs.rule_compliance, qs.completeness, qs.consistency,
        qs.outlier_penalty, cfg), abs=0.1)
