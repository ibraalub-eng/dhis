"""Central rate registry: verbatim literals, compute_rate, per-site parity."""
from app.engine.rate_config import (
    BUILTIN_RATE_SPECS,
    compute_rate,
    compute_spec_rate,
    iter_site,
    multiplier_for_unit,
    zscore_spec_for,
    zscore_specs,
)

# Exact current values of the four hardcoded sites (copied from source before
# migration). Any drift in the registry breaks one of these assertions.
# (name, numerator, denominator, typical_pct, rate_code, unit) — zscore slice.
# unit for the mortality trio is the plan's "per 100" (the Task 6 inherited-base
# assertion pins it), NOT the clinical slice's "per 100,000"/"per 1,000": the
# zscore site has no unit field at all, so this is registry metadata, not a
# verbatim source copy.
ZSCORE_LITERALS = [
    ("C-section rate", "5", "2", 50.0, "rate_cs", "%"),
    ("Maternal mortality ratio", "11", "2", 1.0, "rate_mmr", "per 100"),
    ("Neonatal mortality rate", "17", "6", 30.0, "rate_nmr", "per 100"),
    ("Preterm birth rate", "6.f", "6", 15.0, "rate_preterm", "%"),
    ("SMM rate", "10", "2", 10.0, "rate_smm", "%"),
    ("Stillbirth rate", "7", "2", 5.0, "rate_stillbirth", "per 100"),
    ("NICU admission rate", "16", "6", 20.0, "rate_nicu", "%"),
]

# (rate_code, numerator_codes, denominator_code, multiplier, unit) — clinical
# slice values exactly as in thresholds.py CLINICAL_THRESHOLDS (line 20-216),
# multiplier derived by the current rule `100 if "%" in unit else 1`.
CLINICAL_LITERALS = [
    ("rate_cs", ("5",), "2", 100.0, "%"),
    ("rate_mmr", ("11",), "2", 1.0, "per 100,000"),
    ("rate_nmr", ("17",), "6", 1.0, "per 1,000"),
    ("rate_preterm", ("6.f",), "6", 100.0, "%"),
    ("rate_smm", ("10",), "2", 100.0, "%"),
    ("rate_stillbirth", ("7",), "2", 1.0, "per 1,000"),
    ("rate_nicu", ("16",), "6", 100.0, "%"),
    ("rate_lbw", ("6.g",), "6", 100.0, "%"),
    ("rate_bf", ("13",), "6", 100.0, "%"),
    ("rate_avd", ("4",), "2", 100.0, "%"),
    ("rate_smm_hemorrhage_proportion", ("10.a",), "10", 100.0, "%"),
    ("rate_smm_hypertensive_proportion", ("10.e",), "10", 100.0, "%"),
    ("rate_adolescent", ("2.c", "2.d"), "2", 100.0, "%"),
    ("rate_high_risk", ("2.n",), "2", 100.0, "%"),
    ("rate_hysterectomy", ("10.d",), "2", 1.0, "per 1,000"),
]

# forecast INDICATOR_DEFS: (key, numerator, denominator-or-None, per/unit)
FORECAST_LITERALS = [
    ("cs_rate", ("5",), ("2",), 100.0),
    ("stillbirth_rate", ("7",), ("6",), 1000.0),
    ("preterm_rate", ("6.f",), ("6",), 100.0),
    ("lbw_rate", ("6.g",), ("6",), 100.0),
    ("high_risk_rate", ("2.n",), ("6",), 100.0),
    ("adolescent_rate", ("2.c", "2.d"), ("6",), 100.0),
    ("total_births", ("6",), None, 1.0),
]

# rules R043-R050: (rule code, numerator, denominator) — R045 MMR uses
# denominator "6" here (disagrees with zscore/clinical "2"); that disagreement
# is the point of the per-site registry.
RULES_LITERALS = [
    ("R043", "6.f", "6"),
    ("R044", "6.g", "6"),
    ("R045", "11", "6"),
    ("R046", "17", "6"),
    ("R047", "7", "2"),
    ("R048", "16", "6"),
    ("R049", "10", "2"),
    ("R050", "10.a", "2"),
]


def test_zscore_slice_matches_rate_definitions_literals():
    specs = zscore_specs()
    assert len(specs) == 7
    for spec, (name, num, den, pct, code, unit) in zip(specs, ZSCORE_LITERALS, strict=False):
        assert spec.rate_name == name
        assert spec.numerator_codes == (num,)
        assert spec.denominator_codes == (den,)
        assert spec.typical_pct == pct
        assert spec.rate_code == code
        assert spec.unit == unit
        assert spec.rate_multiplier == 100.0  # zscore.compute_rate hardcodes x100
        assert spec.site == "zscore"


def test_clinical_slice_matches_threshold_literals():
    specs = iter_site("clinical")
    assert len(specs) == 15
    for spec, (code, num, den, mult, unit) in zip(specs, CLINICAL_LITERALS, strict=False):
        assert spec.rate_code == code
        assert spec.numerator_codes == num
        assert spec.denominator_codes == (den,)
        assert spec.rate_multiplier == mult
        assert spec.unit == unit


def test_forecast_slice_matches_indicator_defs_literals():
    specs = iter_site("forecast")
    assert len(specs) == 7
    for spec, (key, num, den, per) in zip(specs, FORECAST_LITERALS, strict=False):
        assert spec.rate_code == key
        assert spec.numerator_codes == num
        assert spec.denominator_codes == (() if den is None else den)
        assert spec.rate_multiplier == per
    assert iter_site("forecast")[-1].is_rate is False  # total_births = count


def test_rules_slice_matches_cross_hospital_rule_literals():
    specs = iter_site("rules")
    assert len(specs) == 8
    for spec, (code, num, den) in zip(specs, RULES_LITERALS, strict=False):
        assert spec.spec_key == f"rules:{code}"
        assert spec.numerator_codes == (num,)
        assert spec.denominator_codes == (den,)
        assert spec.rate_multiplier == 100.0  # rules._rate hardcodes x100
        assert spec.site == "rules"


def test_registry_keys_are_site_scoped():
    keys = list(BUILTIN_RATE_SPECS)
    assert len(keys) == len(set(keys))
    # The known disagreements must coexist under separate keys.
    assert BUILTIN_RATE_SPECS["zscore:Maternal mortality ratio"].denominator_codes == ("2",)
    assert BUILTIN_RATE_SPECS["rules:R045"].denominator_codes == ("6",)
    assert BUILTIN_RATE_SPECS["zscore:Stillbirth rate"].denominator_codes == ("2",)
    assert BUILTIN_RATE_SPECS["forecast:stillbirth_rate"].denominator_codes == ("6",)


def test_compute_rate_sums_codes_and_applies_multiplier():
    values = {"5": 80.0, "2": 300.0}
    assert compute_rate(values, ("5",), ("2",), 100.0) == 80.0 / 300.0 * 100


def test_compute_rate_multi_code_numerator():
    values = {"2.c": 40.0, "2.d": 20.0, "2": 300.0}
    assert compute_rate(values, ("2.c", "2.d"), ("2",), 100.0) == 20.0


def test_compute_rate_missing_or_zero_denominator_is_none():
    assert compute_rate({"5": 1}, ("5",), ("2",), 100.0) is None
    assert compute_rate({"5": 1, "2": 0}, ("5",), ("2",), 100.0) is None
    assert compute_rate({"2": 100}, ("5",), ("2",), 100.0) is None


def test_compute_spec_rate_uses_spec_multiplier():
    spec = BUILTIN_RATE_SPECS["zscore:C-section rate"]
    assert compute_spec_rate(spec, {"5": 30, "2": 300}) == 10.0
    spec_mmr = BUILTIN_RATE_SPECS["clinical:rate_mmr"]  # x1, per 100,000
    assert compute_spec_rate(spec_mmr, {"11": 2, "2": 300}) == 2 / 300 * 1


def test_zscore_spec_for_lookup_and_miss():
    spec = zscore_spec_for("5", "2")
    assert spec is not None and spec.rate_code == "rate_cs"
    assert zscore_spec_for("999", "2") is None


def test_multiplier_for_unit():
    assert multiplier_for_unit("%") == 100.0
    assert multiplier_for_unit("per 1,000") == 1.0
    assert multiplier_for_unit("per 100,000") == 1.0
    assert multiplier_for_unit("") == 1.0
    assert multiplier_for_unit(None) == 1.0


def test_rate_definitions_is_a_view_over_the_zscore_slice():
    from app.engine.anomaly.zscore import RATE_DEFINITIONS
    expected = [(name, num, den, pct)
                for (name, num, den, pct, _code, _unit) in ZSCORE_LITERALS]
    assert RATE_DEFINITIONS == expected


def test_zscore_compute_rate_keeps_signature_and_x100_parity():
    from app.engine.anomaly.zscore import compute_rate
    assert compute_rate({"5": 80, "2": 300}, "5", "2") == 80 / 300 * 100
    assert compute_rate({"11": 3, "2": 300}, "11", "2") == 3 / 300 * 100
    assert compute_rate({"5": 80}, "5", "2") is None
    assert compute_rate({"5": 80, "2": 0}, "5", "2") is None
    # unknown pair keeps the historical x100 default (never regresses to None)
    assert compute_rate({"99": 1, "2": 4}, "99", "2") == 25.0


def test_clinical_thresholds_built_from_registry_slice():
    from app.engine.clinical.thresholds import CLINICAL_THRESHOLDS
    assert len(CLINICAL_THRESHOLDS) == 15
    for th, (code, num, den, _mult, unit) in zip(CLINICAL_THRESHOLDS, CLINICAL_LITERALS, strict=False):
        assert th.indicator_code == code
        assert th.numerator_codes == list(num)
        assert th.denominator_code == den
        assert th.unit == unit


def test_clinical_threshold_ranges_and_guidelines_spot_check():
    from app.engine.clinical.thresholds import get_threshold
    cs = get_threshold("C-Section Rate")
    assert (cs.normal_range, cs.elevated_range, cs.high_range) == ((10, 15), (15, 25), (25, 40))
    assert cs.critical_threshold == 40
    assert cs.clinical_guideline == "WHO: 10-15% optimal C-section rate"
    assert cs.higher_is_worse is True
    bf = get_threshold("Breastfeeding within 1 Hour")
    assert bf.normal_range == (80, 100) and bf.higher_is_worse is False
    mmr = get_threshold("Maternal Mortality Ratio")
    assert mmr.clinical_guideline == "WHO/SDG 3.1: <70 per 100,000 by 2030"
    assert get_threshold("No Such Rate") is None


def test_clinical_compute_rate_multiplier_comes_from_registry():
    from app.engine.clinical.thresholds import compute_rate
    assert compute_rate(80, 300, "%") == 80 / 300 * 100
    assert compute_rate(2, 300, "per 1,000") == 2 / 300
    assert compute_rate(2, 300, "per 100,000") == 2 / 300
    assert compute_rate(5, 0, "%") is None
    assert compute_rate(5, None, "%") is None


def test_forecast_indicator_defs_built_from_registry_slice():
    from app.engine.smart.indicator_forecast import INDICATOR_DEFS
    assert list(INDICATOR_DEFS.keys()) == [
        "cs_rate", "stillbirth_rate", "preterm_rate", "lbw_rate",
        "high_risk_rate", "adolescent_rate", "total_births",
    ]
    assert INDICATOR_DEFS["cs_rate"] == {
        "label_ar": "\u0645\u0639\u062f\u0644 \u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a \u0627\u0644\u0642\u064a\u0635\u0627\u0631\u064a\u0629",
        "label_en": "C-section rate",
        "unit": "%",
        "numerator": ("5",),
        "denominator": ("2",),
        "per": 100.0,
    }
    assert INDICATOR_DEFS["stillbirth_rate"]["per"] == 1000.0
    assert INDICATOR_DEFS["stillbirth_rate"]["denominator"] == ("6",)
    assert INDICATOR_DEFS["adolescent_rate"]["numerator"] == ("2.c", "2.d")
    assert INDICATOR_DEFS["total_births"]["denominator"] is None
    assert INDICATOR_DEFS["total_births"]["per"] == 1.0


def test_forecast_rate_computation_parity():
    from app.engine.smart.indicator_forecast import available_indicators, indicator_rate_from_values
    assert [i["key"] for i in available_indicators()] == list(
        ["cs_rate", "stillbirth_rate", "preterm_rate", "lbw_rate",
         "high_risk_rate", "adolescent_rate", "total_births"])
    assert indicator_rate_from_values("cs_rate", {"5": 80, "2": 300}) == 80 / 300 * 100
    assert indicator_rate_from_values("stillbirth_rate", {"7": 6, "6": 300}) == 6 / 300 * 1000
    assert indicator_rate_from_values("total_births", {"6": 300}) == 300.0
    assert indicator_rate_from_values("adolescent_rate", {"2.c": 40, "2.d": 20, "6": 300}) == 60 / 300 * 100
    assert indicator_rate_from_values("cs_rate", {"5": 80}) is None
    assert indicator_rate_from_values("cs_rate", {"5": 80, "2": 0}) is None

