"""Rates must come from the central indicator registry — no hardcoded math.

Audit 2026-10-21 ("for rates and clinical, also in comparison, make sure
the indicators are used — not hard-coded rates").

Contract enforced here:

* The zscore / clinical / forecast rate lists are VIEWS over the central
  registry (app.engine.rate_config) — editing a builtin spec is the only
  place a rate's numerator/denominator/multiplier lives.
* The comparative (regional) engine maps its metrics onto registry
  definitions and computes through ``indicator_rate_from_values``.
* The clinical screen (summary / risk profile / morbidity /
  recommendations) and the smart action-board C-section series FOLLOW the
  registry: patching a builtin spec changes their output — a hardcoded
  ``x / y * 100`` would not.
"""
import contextlib
import dataclasses

# Delivery / birth mix used by every behavioural case below.
_VALUES = {
    "2": 100.0, "5": 30.0, "6": 90.0, "7": 3.0, "6.f": 9.0, "6.g": 6.0,
    "10": 6.0, "11": 1.0, "17": 2.0, "2.n": 40.0, "2.c": 4.0, "2.d": 1.0,
}


@contextlib.contextmanager
def _patch_spec(site: str, rate_code: str, **overrides):
    """Temporarily replace one builtin registry spec (frozen dataclass)."""
    from app.engine import rate_config

    key = f"{site}:{rate_code}"
    original = rate_config.BUILTIN_RATE_SPECS[key]
    rate_config.BUILTIN_RATE_SPECS[key] = dataclasses.replace(original, **overrides)
    try:
        yield original
    finally:
        rate_config.BUILTIN_RATE_SPECS[key] = original


# ── registry views (no second copy of any rate list) ───────────────────────

def test_zscore_rate_definitions_are_a_registry_view():
    from app.engine.anomaly.zscore import RATE_DEFINITIONS
    from app.engine.rate_config import zscore_specs

    expected = [
        (s.rate_name, s.numerator_codes[0], s.denominator_codes[0], s.typical_pct)
        for s in zscore_specs()
    ]
    assert RATE_DEFINITIONS == expected


def test_clinical_thresholds_carry_registry_formulas():
    from app.engine.clinical.thresholds import CLINICAL_THRESHOLDS
    from app.engine.rate_config import SITE_CLINICAL, iter_site

    specs = {s.rate_code: s for s in iter_site(SITE_CLINICAL)}
    assert CLINICAL_THRESHOLDS
    for th in CLINICAL_THRESHOLDS:
        spec = specs[th.indicator_code]
        assert th.numerator_codes == list(spec.numerator_codes), th.indicator_code
        assert th.denominator_code == spec.denominator_codes[0], th.indicator_code
        assert th.multiplier == spec.rate_multiplier, th.indicator_code
        assert th.unit == spec.unit, th.indicator_code


def test_forecast_defs_and_comparative_map_use_registry():
    from app.engine.rate_config import SITE_FORECAST, iter_site
    from app.engine.smart.indicator_forecast import INDICATOR_DEFS
    from app.engine.smart.regional import _RATE_DEFINITIONS

    specs = {s.rate_code: s for s in iter_site(SITE_FORECAST)}
    assert set(INDICATOR_DEFS) == set(specs)
    for key, d in INDICATOR_DEFS.items():
        spec = specs[key]
        assert tuple(d["numerator"]) == spec.numerator_codes, key
        assert (d["denominator"] or ()) == spec.denominator_codes, key
        assert d["per"] == spec.rate_multiplier, key
    # comparative metrics all resolve to real registry definitions
    for metric, code in _RATE_DEFINITIONS.items():
        assert code in INDICATOR_DEFS, f"{metric} -> {code} missing from registry"


# ── behavioural: the screens FOLLOW the registry ───────────────────────────

def test_clinical_risk_and_morbidity_rates_follow_the_registry():
    from app.engine.clinical.morbidity import compute_morbidity_profile
    from app.engine.clinical.risk_profile import compute_risk_profile

    def risk_value(values, name):
        profile = compute_risk_profile("H", "2026-06", values)
        return next(m.value for m in profile.metrics if m.metric_name == name)

    # Baselines equal the registry formulas: 40/100×100, (4+1)/100×100, 9/90×100
    assert risk_value(dict(_VALUES), "High-Risk Delivery Rate") == 40.0
    assert risk_value(dict(_VALUES), "Adolescent Pregnancy Rate (10-19)") == 5.0
    assert risk_value(dict(_VALUES), "Preterm Birth Rate") == 10.0

    # Registry multiplier edit → the screen follows (a hardcode would not).
    with _patch_spec("clinical", "rate_high_risk", rate_multiplier=200.0):
        assert risk_value(dict(_VALUES), "High-Risk Delivery Rate") == 80.0

    # Registry numerator edit → the screen follows.
    with _patch_spec("clinical", "rate_adolescent", numerator_codes=("2.c",)):
        assert risk_value(dict(_VALUES), "Adolescent Pregnancy Rate (10-19)") == 4.0

    def smm_value(values):
        profile = compute_morbidity_profile("H", "2026-06", values)
        return next(m.value for m in profile.metrics if m.metric_name == "SMM Rate")

    assert smm_value(dict(_VALUES)) == 6.0   # 6/100×100
    with _patch_spec("clinical", "rate_smm", rate_multiplier=200.0):
        assert smm_value(dict(_VALUES)) == 12.0


def test_clinical_summary_rates_follow_the_registry():
    from app.engine.clinical.summary import generate_clinical_summary

    def overview(values):
        summary = generate_clinical_summary(
            hospital="H", month="2026-06", values=values,
            classifications=[], risk_profile=None, morbidity_profile=None,
            recommendations=[])
        return summary.overview

    assert "C-section rate was 30.0%" in overview(dict(_VALUES))
    with _patch_spec("clinical", "rate_cs", rate_multiplier=200.0):
        assert "C-section rate was 60.0%" in overview(dict(_VALUES))


def test_clinical_recommendations_follow_the_registry():
    from app.engine.clinical.recommendations import _cs_high_rate

    rec = _cs_high_rate({"values": dict(_VALUES)})
    assert rec is not None and "30.0%" in rec.title
    with _patch_spec("clinical", "rate_cs", rate_multiplier=200.0):
        patched = _cs_high_rate({"values": dict(_VALUES)})
        assert patched is not None and "60.0%" in patched.title
        assert patched.priority == "critical"   # 60% > 40% per the registry


def test_action_board_cs_series_follows_registry(db_session):
    from app.api.smart_analytics import _hospital_rate_series
    from app.engine.smart import indicator_forecast
    from app.models import Hospital, Indicator, IndicatorValue

    hosp = Hospital(name="Series Hospital", is_active=True)
    db_session.add(hosp)
    db_session.flush()
    ids = {}
    for code in ("2", "5"):
        existing = db_session.query(Indicator).filter(Indicator.code == code).first()
        if existing:
            ids[code] = existing.id
            continue
        ind = Indicator(code=code, name=f"Ind {code}")
        db_session.add(ind)
        db_session.flush()
        ids[code] = ind.id
    db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ids["2"],
                                  month="2026-05", value=100.0))
    db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ids["5"],
                                  month="2026-05", value=30.0))
    db_session.commit()

    names = {hosp.id: hosp.name}
    series = _hospital_rate_series(db_session, names)
    assert series[hosp.name][-1][1] == 30.0    # registry cs_rate = 5/2×100

    original = dict(indicator_forecast.INDICATOR_DEFS["cs_rate"])
    patched = dict(original)
    patched["per"] = 200.0
    indicator_forecast.INDICATOR_DEFS["cs_rate"] = patched
    try:
        series = _hospital_rate_series(db_session, names)
        assert series[hosp.name][-1][1] == 60.0  # follows the registry
    finally:
        indicator_forecast.INDICATOR_DEFS["cs_rate"] = original
