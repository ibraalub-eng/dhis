"""Outlier-penalty denominator (docs/OUTLIER-PENALTY-DENOMINATOR.md).

The layered penalty used to divide flagged rows by the rows that happened to be
evaluated.  Rows only exist when the month has an observation, so an incomplete
month could inflate the same absolute finding.  The denominator is now the
approved eligible assessment set; completeness keeps its own component.
"""
from types import SimpleNamespace

import pytest

from app.engine.quality import FLAGGED_LEVELS, calculate_quality_score
from app.engine.quality.scoring import (
    OUTLIER_MULTIPLIER_DEFAULT,
    _calc_layered_outlier_penalty,
)
from app.models import (
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    SystemSetting,
)


def _rows(levels, prefix="R"):
    return [SimpleNamespace(outlier_level=level, analysis_code=f"{prefix}{i}")
            for i, level in enumerate(levels)]


def _codes(count, prefix="E"):
    return {f"{prefix}{i}" for i in range(count)}


def _hospital(db):
    return db.query(Hospital).order_by(Hospital.id).first()


def _indicator(db, code):
    return db.query(Indicator).filter(Indicator.code == code).first()


def _put(db, hospital_id, month, values):
    for code, value in values.items():
        ind = _indicator(db, code)
        if ind is not None:
            db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                                  month=month, value=value))
    db.commit()


def _disable_all_except(db, hospital_id, keep):
    keep_ids = {i.id for i in db.query(Indicator)
                .filter(Indicator.code.in_(set(keep))).all()}
    for (ind_id,) in db.query(Indicator.id).all():
        if ind_id not in keep_ids:
            db.add(HospitalIndicatorConfig(
                hospital_id=hospital_id, indicator_id=ind_id, is_enabled=False))
    db.commit()


def test_penalty_divides_by_eligible_units_not_by_evaluated_rows():
    eligible = _codes(40)
    complete = _rows(["HIGH"] + ["NONE"] * 39)
    sparse = _rows(["HIGH"])

    assert _calc_layered_outlier_penalty(
        complete, {}, eligible_codes=eligible) == pytest.approx(1 / 40 * 2.0)
    assert _calc_layered_outlier_penalty(
        sparse, {}, eligible_codes=eligible) == pytest.approx(1 / 40 * 2.0)
    # Legacy callers keep the evaluated-row divisor.
    assert _calc_layered_outlier_penalty(sparse, {}) == pytest.approx(1.0)


def test_flagged_row_outside_the_set_still_counts_as_a_finding():
    rows = [SimpleNamespace(outlier_level="VERY_HIGH",
                            analysis_code="NOT_LISTED")]
    assert _calc_layered_outlier_penalty(
        rows, {}, eligible_codes=_codes(10)) == pytest.approx(1 / 10 * 2.0)


def test_quality_score_accepts_the_eligible_denominator_alias():
    rows = _rows(["VERY_HIGH"] * 4)
    score = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 5},
        layered_results=rows, eligible_codes=_codes(4))
    assert score["outlier_penalty"] == pytest.approx(100.0)

    wide = calculate_quality_score(
        [], {}, [], set(), {"outlier_multiplier": 5},
        layered_results=rows, eligible_codes=_codes(40))
    assert wide["outlier_penalty"] == pytest.approx(4 / 40 * 5 * 100)
    assert 0.0 <= wide["score"] <= 100.0


def test_empty_denominator_is_zero_and_deterministic():
    rows = _rows(["HIGH"])
    assert _calc_layered_outlier_penalty(
        rows, {}, eligible_codes=set()) == 0.0
    first = _calc_layered_outlier_penalty(rows, {}, eligible_codes=_codes(3))
    second = _calc_layered_outlier_penalty(
        list(reversed(rows)), {}, eligible_codes=_codes(3))
    assert first == second


def test_missing_required_stays_in_the_denominator(db_session):
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital = _hospital(db_session)
    keep = {"9", "11", "12", "13", "14"}
    _disable_all_except(db_session, hospital.id, keep)
    full_month, thin_month = "2031-01", "2031-02"
    _put(db_session, hospital.id, full_month,
         {"9": 1, "11": 1, "12": 3, "13": 2, "14": 1})
    _put(db_session, hospital.id, thin_month, {"9": 1, "11": 0})

    full = get_outlier_eligible_codes(
        db_session, hospital.id, full_month,
        evaluated_codes=["9", "11", "12", "13", "14"])
    thin = get_outlier_eligible_codes(
        db_session, hospital.id, thin_month, evaluated_codes=["9", "11"])
    assert full == keep
    assert thin == keep

    flagged_full = [SimpleNamespace(outlier_level="HIGH", analysis_code="9")]
    flagged_full += [SimpleNamespace(outlier_level="NONE", analysis_code=c)
                     for c in sorted(keep - {"9"})]
    flagged_thin = [SimpleNamespace(outlier_level="HIGH", analysis_code="9")]

    assert _calc_layered_outlier_penalty(
        flagged_full, {}, eligible_codes=full) == pytest.approx(
            len(flagged_thin) / len(keep) * OUTLIER_MULTIPLIER_DEFAULT)
    assert _calc_layered_outlier_penalty(
        flagged_thin, {}, eligible_codes=thin) == pytest.approx(
            len(flagged_thin) / len(keep) * OUTLIER_MULTIPLIER_DEFAULT)


def test_optional_is_counted_only_when_assessed(db_session):
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital = _hospital(db_session)
    ind = _indicator(db_session, "14")
    ind.requirement_type = "Optional"
    db_session.commit()
    _disable_all_except(db_session, hospital.id, {"9", "14"})
    _put(db_session, hospital.id, "2031-03", {"9": 1, "14": 2})
    _put(db_session, hospital.id, "2031-04", {"9": 1})

    reported = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-03", evaluated_codes=["9", "14"])
    absent = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-04", evaluated_codes=["9"])
    assert reported == {"9", "14"}
    assert absent == {"9"}


def test_optional_by_inheritance_needs_its_own_assessment(db_session):
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital = _hospital(db_session)
    parent = Indicator(code="TST_P", name="Parent", requirement_type="Required")
    child = Indicator(code="TST_C", name="Child", requirement_type="Optional")
    db_session.add_all([parent, child])
    db_session.flush()
    child.parent_id = parent.id
    db_session.commit()
    _disable_all_except(db_session, hospital.id, {"TST_P", "TST_C"})
    _put(db_session, hospital.id, "2031-05", {"TST_C": 4})

    absent = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-06", evaluated_codes=[])
    assessed = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-05", evaluated_codes=["TST_C"])
    assert "TST_P" not in absent
    assert assessed == {"TST_C"}


def test_manual_disable_removes_the_element_and_its_rates(db_session):
    from app.engine.anomaly.layered import build_analysis_specs
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital = _hospital(db_session)
    _put(db_session, hospital.id, "2031-07", {"2": 300, "5": 80, "6": 280, "9": 1})
    ind = _indicator(db_session, "2")
    db_session.add(HospitalIndicatorConfig(
        hospital_id=hospital.id, indicator_id=ind.id, is_enabled=False))
    db_session.commit()

    eligible = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-07", evaluated_codes=["5", "6", "9"])
    assert "2" not in eligible
    for spec in build_analysis_specs(db_session):
        if not spec.is_rate:
            continue
        inputs = set(spec.numerator_codes) | set(spec.denominator_codes)
        if "2" in inputs:
            assert spec.analysis_code not in eligible


def test_covered_required_element_leaves_the_denominator(db_session):
    from app.engine.pipeline import get_outlier_eligible_codes
    from app.engine.quality import compute_covered_codes

    hospital = _hospital(db_session)
    values = {"2": 120.0, "2.a": 120.0, "9": 1.0}
    _put(db_session, hospital.id, "2031-08", values)
    covered = compute_covered_codes(values, set(), db_session)
    assert covered, "fixture must produce a covered-by-total code"
    code = sorted(covered)[0]

    eligible = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-08",
        evaluated_codes=["2", "2.a", "9"])
    assert code not in eligible
    assert "2" in eligible


def test_auto_disable_on_null_does_not_shrink_the_denominator(db_session):
    from app.engine.pipeline import (
        get_outlier_eligible_codes,
        get_required_indicator_codes,
    )

    db_session.add(SystemSetting(key="auto_disable_null_indicators", value="true"))
    db_session.commit()
    hospital = _hospital(db_session)
    _put(db_session, hospital.id, "2031-09", {"9": 1})

    auto_required = get_required_indicator_codes(
        db_session, hospital.id, "2031-09", auto_disable_null=True)
    eligible = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-09", evaluated_codes=["9"])
    assert "12" not in auto_required
    assert "12" in eligible


def test_zero_is_assessed_but_missing_is_not(db_session):
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital = _hospital(db_session)
    ind = _indicator(db_session, "14")
    ind.requirement_type = "Optional"
    db_session.commit()
    _disable_all_except(db_session, hospital.id, {"9", "14"})
    _put(db_session, hospital.id, "2031-10", {"9": 1, "14": 0})
    _put(db_session, hospital.id, "2031-11", {"9": 1})

    reported = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-10", evaluated_codes=["9", "14"])
    absent = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-11", evaluated_codes=["9"])
    assert "14" in reported
    assert "14" not in absent


def _run_pipeline(db, month, values):
    from app.engine.pipeline import run_full_analysis
    hospital = _hospital(db)
    _put(db, hospital.id, month, values)
    run_full_analysis(db, hospital.id, month, force=True)
    rows = (db.query(LayeredOutlierResult)
            .filter(LayeredOutlierResult.hospital_id == hospital.id,
                    LayeredOutlierResult.month == month).all())
    score = (db.query(QualityScore)
             .filter(QualityScore.hospital_id == hospital.id,
                     QualityScore.month == month).first())
    assert rows and score is not None
    return hospital, rows, score


def test_pipeline_divides_by_the_eligible_set(db_session, sample_values):
    from app.config_utils import get_config_dict
    from app.engine.pipeline import get_outlier_eligible_codes

    hospital, rows, score = _run_pipeline(db_session, "2031-12", sample_values)
    eligible = get_outlier_eligible_codes(
        db_session, hospital.id, "2031-12",
        evaluated_codes=[r.analysis_code for r in rows])
    assert len(eligible) > len(rows), (
        "an incomplete month must keep its unreported Required units")
    flagged = sum(1 for r in rows if r.outlier_level in FLAGGED_LEVELS)
    multiplier = float(get_config_dict(db_session, "quality").get(
        "outlier_multiplier", OUTLIER_MULTIPLIER_DEFAULT))
    expected = min(1.0, flagged / len(eligible) * multiplier) * 100
    assert score.outlier_penalty == pytest.approx(expected, abs=0.1)
    assert 0.0 <= score.outlier_penalty <= 100.0
    assert 0.0 <= score.score <= 100.0


def test_rescoring_reproduces_the_eligible_denominator(db_session, sample_values):
    from app.config_utils import get_config_dict
    from app.engine.pipeline import get_outlier_eligible_codes, revalidate_hospital_months

    hospital, rows, _ = _run_pipeline(db_session, "2032-01", sample_values)
    rows[0].outlier_level = "VERY_HIGH"
    db_session.commit()
    revalidate_hospital_months(db_session, hospital.id, months=["2032-01"])

    stored_rows = (db_session.query(LayeredOutlierResult)
                   .filter(LayeredOutlierResult.hospital_id == hospital.id,
                           LayeredOutlierResult.month == "2032-01").all())
    eligible = get_outlier_eligible_codes(
        db_session, hospital.id, "2032-01",
        evaluated_codes=[r.analysis_code for r in stored_rows])
    flagged = sum(1 for r in stored_rows if r.outlier_level in FLAGGED_LEVELS)
    multiplier = float(get_config_dict(db_session, "quality").get(
        "outlier_multiplier", OUTLIER_MULTIPLIER_DEFAULT))
    expected = min(1.0, flagged / len(eligible) * multiplier) * 100
    qs = (db_session.query(QualityScore)
          .filter(QualityScore.hospital_id == hospital.id,
                  QualityScore.month == "2032-01").one())
    assert qs.outlier_penalty == pytest.approx(expected, abs=0.1)


def test_scoring_audit_reports_eligible_and_evaluated(db_session, app, sample_values):
    from fastapi.testclient import TestClient

    _run_pipeline(db_session, "2032-02", sample_values)
    client = TestClient(app)
    response = client.get("/admin/quality-scores/scoring-audit")
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["month"] == "2032-02")
    penalty = item["penalty"]
    assert penalty["available"] is True
    assert penalty["eligible"] > penalty["evaluated"]
    assert penalty["matches"] is True
    assert penalty["scored_under_evaluated_rows_denominator"] is False
