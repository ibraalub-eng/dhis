"""Derived-indicator calculation engine tests (2026-10-18 feature).

Covers the safety doctrine: safe parser (no code execution), missing vs
legitimate zero, division-by-zero status, aggregation strictness, and
result storage that never touches raw indicator_values.
"""
import json
from types import SimpleNamespace

import pytest

from app.engine import indicator_calc as calc


def _ratio(num, den, operator="/", multiplier=100.0, aggregation="sum",
           code="cs_rate", result_type="percentage"):
    return SimpleNamespace(
        code=code, name="C-Section Rate", formula_type="ratio",
        expression=None, numerator_codes=num, denominator_codes=den,
        operator=operator, multiplier=multiplier, aggregation=aggregation,
        result_type=result_type, version=1,
    )


def _expr(expression, multiplier=1.0, code="expr_rate"):
    return SimpleNamespace(
        code=code, name="Expr", formula_type="expression",
        expression=expression, numerator_codes=None, denominator_codes=None,
        operator="/", multiplier=multiplier, aggregation="sum",
        result_type="ratio", version=1,
    )


def _orm_ratio(db, num, den, **overrides):
    """Persisted IndicatorDefinition (same shape as the API creates)."""
    from app.models import IndicatorDefinition
    fields = dict(
        code="test_cs_rate", name="C-Section Rate", formula_type="ratio",
        numerator_codes=num, denominator_codes=den, operator="/",
        multiplier=100.0, aggregation="sum", result_type="percentage",
        is_active=True, version=1,
    )
    fields.update(overrides)
    defn = IndicatorDefinition(**fields)
    db.add(defn)
    db.flush()
    return defn


def _seed_values(db, values, hospital_id=1, month="2026-03"):
    from app.models import Indicator, IndicatorValue
    for code, value in values.items():
        ind = db.query(Indicator).filter(Indicator.code == code).first()
        assert ind is not None, f"seeded catalog must contain {code}"
        db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                              month=month, value=value))
    db.commit()


# ── parser safety ───────────────────────────────────────────────────────────

def test_parse_valid_expression_and_render_roundtrip():
    ast = calc.parse_expression("({5} / {2}) * 100")
    assert calc.ast_codes(ast) == ["5", "2"]
    rendered = calc.render_expression(ast)
    # rendered form is itself parseable — deterministic audit string
    ast2 = calc.parse_expression(rendered)
    assert calc.ast_codes(ast2) == ["5", "2"]


def test_parse_respects_precedence_and_unary_minus():
    ast = calc.parse_expression("2 + 3 * 4")
    value, status = calc.evaluate(ast, {})
    assert status == calc.STATUS_OK and value == 14.0

    ast = calc.parse_expression("-{5} + 10")
    value, status = calc.evaluate(ast, {"5": 4})
    assert status == calc.STATUS_OK and value == 6.0


@pytest.mark.parametrize("bad", [
    "",                      # empty
    "{5} / {2} 100",         # missing operator (trailing junk)
    "5 +",                   # incomplete
    "(5 / 2",                # unbalanced
    "5 / 2)",                # unbalanced
    "{5} $ {2}",             # illegal character
    "__import__('os')",      # not our language
    "5 .. 2",                # malformed number
    "{}",                    # empty reference
    "{5",                    # unclosed reference
    "os.system('rm')",       # identifiers outside {code} are rejected
])
def test_parser_rejects_unsafe_or_broken_input(bad):
    with pytest.raises(calc.FormulaError):
        calc.parse_expression(bad)


# ── ratio computation ───────────────────────────────────────────────────────

def test_c_section_rate_from_valid_test_data():
    """(Caesarean Sections {5} / Total Deliveries {2}) x 100 = 20%."""
    defn = _ratio(["5"], ["2"], multiplier=100.0)
    outcome = calc.evaluate_definition(defn, {"5": 30.0, "2": 150.0})
    assert outcome.status == calc.STATUS_OK
    assert outcome.value == pytest.approx(20.0)
    assert outcome.numerator == 30.0
    assert outcome.denominator == 150.0


def test_zero_denominator_yields_null_value_not_crash_and_not_zero():
    defn = _ratio(["5"], ["2"])
    outcome = calc.evaluate_definition(defn, {"5": 30.0, "2": 0.0})
    assert outcome.status == calc.STATUS_ZERO_DENOMINATOR
    assert outcome.value is None
    assert outcome.numerator == 30.0


def test_reported_zero_numerator_is_a_legitimate_value():
    defn = _ratio(["5"], ["2"])
    outcome = calc.evaluate_definition(defn, {"5": 0.0, "2": 150.0})
    assert outcome.status == calc.STATUS_OK
    assert outcome.value == 0.0  # real 0, not missing


def test_missing_rows_distinguish_no_data_from_missing_part():
    defn = _ratio(["5"], ["2"])
    # nothing reported at all this month
    no_data = calc.evaluate_definition(defn, {})
    assert no_data.status == calc.STATUS_NO_DATA
    assert no_data.value is None
    # numerator reported, denominator not → missing (not zero!)
    missing = calc.evaluate_definition(defn, {"5": 30.0})
    assert missing.status == calc.STATUS_MISSING
    assert missing.missing_codes == ["2"]
    assert missing.value is None


def test_null_value_row_counts_as_missing_not_zero():
    defn = _ratio(["5"], ["2"])
    outcome = calc.evaluate_definition(defn, {"5": None, "2": 150.0})
    assert outcome.status == calc.STATUS_MISSING
    assert outcome.value is None


def test_aggregation_methods_and_strictness():
    defn = _ratio(["2.a", "2.b"], ["2.c"], aggregation="avg", multiplier=1.0)
    ok = calc.evaluate_definition(defn, {"2.a": 10.0, "2.b": 20.0, "2.c": 3.0})
    assert ok.status == calc.STATUS_OK
    assert ok.numerator == pytest.approx(15.0)
    # one missing member invalidates the whole part (no silent understatement)
    partial = calc.evaluate_definition(defn, {"2.a": 10.0, "2.c": 3.0})
    assert partial.status == calc.STATUS_MISSING
    assert partial.missing_codes == ["2.b"]


def test_non_division_operators_and_count_shape():
    plus = _ratio(["5"], ["2"], operator="+", multiplier=2.0)
    outcome = calc.evaluate_definition(plus, {"5": 3.0, "2": 4.0})
    assert outcome.status == calc.STATUS_OK
    assert outcome.value == 14.0  # (3 + 4) * 2

    count = _ratio(["5"], [], operator="/", multiplier=1.0, result_type="count")
    outcome = calc.evaluate_definition(count, {"5": 7.0})
    # division without denominator is a config error, not a crash
    assert outcome.status == calc.STATUS_ERROR


# ── expression computation ──────────────────────────────────────────────────

def test_expression_mode_computes_with_precedence():
    defn = _expr("({5} + {5.b.1}) / {2} * 100", multiplier=1.0)
    outcome = calc.evaluate_definition(defn, {"5": 30.0, "5.b.1": 10.0, "2": 200.0})
    assert outcome.status == calc.STATUS_OK
    assert outcome.value == pytest.approx(20.0)


def test_expression_division_by_zero_status():
    defn = _expr("{5} / ({2} - {2})")
    outcome = calc.evaluate_definition(defn, {"5": 30.0, "2": 150.0})
    assert outcome.status == calc.STATUS_ZERO_DENOMINATOR
    assert outcome.value is None


def test_expression_missing_code_propagates():
    defn = _expr("{5} / {2} * 100")
    outcome = calc.evaluate_definition(defn, {"5": 30.0})
    assert outcome.status == calc.STATUS_MISSING
    assert outcome.value is None


def test_expression_with_invalid_formula_saved_somehow_is_error():
    defn = _expr("not a formula")
    outcome = calc.evaluate_definition(defn, {"5": 1.0})
    assert outcome.status == calc.STATUS_ERROR
    assert outcome.value is None


# ── expression builders ─────────────────────────────────────────────────────

def test_build_ratio_expression_is_parseable_and_roundtrips():
    expr = calc.build_ratio_expression(["5"], ["2"], "/", 100.0)
    ast = calc.parse_expression(expr)
    assert calc.ast_codes(ast) == ["5", "2"]
    value, status = calc.evaluate(ast, {"5": 30.0, "2": 150.0})
    assert status == calc.STATUS_OK
    assert value == pytest.approx(20.0)


def test_build_ratio_expression_multi_codes_and_no_denominator():
    expr = calc.build_ratio_expression(["2.a", "2.b"], [], "*", 1.0)
    ast = calc.parse_expression(expr)
    assert calc.ast_codes(ast) == ["2.a", "2.b"]
    value, status = calc.evaluate(ast, {"2.a": 5.0, "2.b": 7.0})
    assert status == calc.STATUS_OK and value == 12.0


def test_definition_codes_both_modes():
    assert calc.definition_codes(_ratio(["5"], ["2"])) == ["5", "2"]
    assert calc.definition_codes(_expr("{10.a} + {10.b}")) == ["10.a", "10.b"]


# ── DB integration (raw rows in, results out) ───────────────────────────────

def test_load_raw_values_distinguishes_missing_row_from_null(db_session):
    _seed_values(db_session, {"5": 30.0})
    raw = calc.load_raw_values(db_session, ["5", "2"], 1, "2026-03")
    assert "5" in raw and raw["5"] == 30.0
    assert "2" not in raw  # no row at all — absent key
    # no rows anywhere → empty map (no_data, not zero)
    assert calc.load_raw_values(db_session, ["5", "2"], 1, "2099-01") == {}


def test_compute_for_hospital_month_uses_correct_hospital_and_period(db_session):
    _seed_values(db_session, {"5": 30.0, "2": 150.0}, hospital_id=1, month="2026-03")
    _seed_values(db_session, {"5": 45.0, "2": 150.0}, hospital_id=2, month="2026-03")
    _seed_values(db_session, {"5": 10.0, "2": 100.0}, hospital_id=1, month="2026-04")
    defn = _ratio(["5"], ["2"], multiplier=100.0)

    h1_mar = calc.compute_for_hospital_month(db_session, defn, 1, "2026-03")
    assert h1_mar.status == calc.STATUS_OK
    assert h1_mar.value == pytest.approx(20.0)

    h2_mar = calc.compute_for_hospital_month(db_session, defn, 2, "2026-03")
    assert h2_mar.value == pytest.approx(30.0)

    h1_apr = calc.compute_for_hospital_month(db_session, defn, 1, "2026-04")
    assert h1_apr.value == pytest.approx(10.0)

    # wrong hospital+period (no rows) → no_data, never 0
    h2_apr = calc.compute_for_hospital_month(db_session, defn, 2, "2026-04")
    assert h2_apr.status == calc.STATUS_NO_DATA


def test_compute_and_store_never_writes_raw_indicator_values(db_session):
    from app.models import Indicator, IndicatorResult, IndicatorValue
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    defn = _orm_ratio(db_session, ["5"], ["2"])

    raw_before = db_session.query(IndicatorValue).count()
    calc.compute_and_store(db_session, defn, 1, "2026-03")
    db_session.commit()

    assert db_session.query(IndicatorValue).count() == raw_before
    row = db_session.query(IndicatorResult).filter_by(definition_id=defn.id).one()
    assert row.status == calc.STATUS_OK
    assert row.value == pytest.approx(20.0)
    assert row.definition_version == 1
    # raw rows for codes 5/2 untouched
    for code in ("5", "2"):
        ind = db_session.query(Indicator).filter_by(code=code).one()
        assert db_session.query(IndicatorValue).filter_by(indicator_id=ind.id).count() == 1


def test_compute_and_store_upserts_same_hospital_month(db_session):
    from app.models import IndicatorResult
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    defn = _orm_ratio(db_session, ["5"], ["2"])

    calc.compute_and_store(db_session, defn, 1, "2026-03")
    calc.compute_and_store(db_session, defn, 1, "2026-03")
    db_session.commit()
    assert db_session.query(IndicatorResult).filter_by(definition_id=defn.id).count() == 1


def test_recompute_summary_counts_statuses(db_session):
    _seed_values(db_session, {"5": 30.0, "2": 150.0}, hospital_id=1, month="2026-03")
    _seed_values(db_session, {"5": 45.0, "2": 0.0}, hospital_id=2, month="2026-03")
    _orm_ratio(db_session, ["5"], ["2"])
    db_session.commit()

    summary = calc.recompute(db_session, month="2026-03")
    assert summary["month"] == "2026-03"
    assert summary["computed"] == summary["hospitals"]  # 1 def x 3 hospitals
    assert summary["counts"][calc.STATUS_OK] >= 1            # hospital 1 computes
    assert summary["counts"][calc.STATUS_ZERO_DENOMINATOR] >= 1  # hospital 2


def test_stored_results_keep_version_and_inputs_breakdown(db_session):
    from app.models import IndicatorResult
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    defn = _orm_ratio(db_session, ["5"], ["2"])
    calc.compute_and_store(db_session, defn, 1, "2026-03")
    db_session.commit()

    # simulate an explicit formula edit (version bump) — stored row keeps
    # its original stamp so it can be detected as stale, NOT rewritten.
    defn.version = 2
    db_session.commit()
    row = db_session.query(IndicatorResult).filter_by(definition_id=defn.id).one()
    assert row.definition_version == 1
    assert row.definition_version != defn.version  # stale until recompute
    inputs = json.loads(row.inputs)
    assert inputs == {"2": 150.0, "5": 30.0}

    calc.compute_and_store(db_session, defn, 1, "2026-03")
    db_session.commit()
    row = db_session.query(IndicatorResult).filter_by(definition_id=defn.id).one()
    assert row.definition_version == 2


def test_codes_with_data_reports_period_applicability(db_session):
    _seed_values(db_session, {"5": 30.0, "2": 150.0})
    counts = calc.codes_with_data(db_session, ["5", "2"], "2026-03")
    assert counts == {"5": 1, "2": 1}
    counts = calc.codes_with_data(db_session, ["5", "2"], "2026-04")
    assert counts == {"5": 0, "2": 0}
    # scoped to one hospital
    assert calc.codes_with_data(db_session, ["5"], "2026-03", hospital_id=2)["5"] == 0
