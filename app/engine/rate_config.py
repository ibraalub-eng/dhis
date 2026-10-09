"""Central rate-definition registry.

The four hardcoded rate sites (anomaly/zscore, clinical/thresholds,
smart/indicator_forecast, quality/rules) disagree today — MMR denominator 2
vs 6, stillbirth denominator 2 vs 6, multipliers x1 / x100 / x1000. This
registry therefore guarantees one MECHANISM and LOCATION, not one value:
every spec is stored VERBATIM under a site-scoped key so the disagreements
sit side by side and can be reconciled later without silent behavior change
(design spec 2026-10-08, section 4 amendment).

Leaf module: imports nothing from app.models or the engine (avoids cycles).
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SITE_ZSCORE = "zscore"
SITE_CLINICAL = "clinical"
SITE_FORECAST = "forecast"
SITE_RULES = "rules"


@dataclass(frozen=True)
class RateSpec:
    spec_key: str                  # "zscore:C-section rate" | "clinical:rate_cs" | ...
    site: str                      # one of the SITE_* constants above
    rate_code: str                 # synthetic analysis code
    rate_name: str                 # display name (verbatim from its source site)
    indicator_code: str            # primary (first numerator) code, "" when not applicable
    indicator_type: str            # rate | ratio | percentage | count
    numerator_codes: Tuple[str, ...]
    denominator_codes: Tuple[str, ...]   # empty tuple = count-type
    rate_multiplier: float
    unit: str                      # "%" | "per 1,000" | "per 100,000" | "count" | ""
    typical_pct: Optional[float] = None          # zscore slice only (legacy benchmark)
    minimum_denominator: Optional[float] = None  # NULL = guard dormant (spec 12)
    minimum_history_period: int = 3
    outlier_method: str = "auto"
    historical_enabled: bool = True
    peer_comparison_enabled: bool = True
    is_active: bool = True

    @property
    def is_rate(self) -> bool:
        return bool(self.denominator_codes)


def _spec(site: str, spec_id: str, rate_code: str, rate_name: str,
          indicator_type: str, num: Sequence[str], den: Sequence[str],
          multiplier: float, unit: str, indicator_code: str = "",
          typical_pct: Optional[float] = None, **overrides) -> RateSpec:
    return RateSpec(
        spec_key=f"{site}:{spec_id}",
        site=site,
        rate_code=rate_code,
        rate_name=rate_name,
        indicator_code=indicator_code or (num[0] if num else ""),
        indicator_type=indicator_type,
        numerator_codes=tuple(num),
        denominator_codes=tuple(den),
        rate_multiplier=float(multiplier),
        unit=unit,
        typical_pct=typical_pct,
        **overrides,
    )


def _build_builtin() -> Dict[str, RateSpec]:
    specs: List[RateSpec] = []

    # ── zscore slice — app/engine/anomaly/zscore.py:37 RATE_DEFINITIONS ──
    zs = [
        ("rate_cs", "C-section rate", "5", "2", 50.0, "%"),
        ("rate_mmr", "Maternal mortality ratio", "11", "2", 1.0, "per 100"),
        ("rate_nmr", "Neonatal mortality rate", "17", "6", 30.0, "per 100"),
        ("rate_preterm", "Preterm birth rate", "6.f", "6", 15.0, "%"),
        ("rate_smm", "SMM rate", "10", "2", 10.0, "%"),
        ("rate_stillbirth", "Stillbirth rate", "7", "2", 5.0, "per 100"),
        ("rate_nicu", "NICU admission rate", "16", "6", 20.0, "%"),
    ]
    for code, name, num, den, pct, unit in zs:
        itype = "percentage" if unit == "%" else "rate"
        specs.append(_spec(SITE_ZSCORE, name, code, name, itype,
                           (num,), (den,), 100.0, unit, typical_pct=pct))

    # ── clinical slice — thresholds.py CLINICAL_THRESHOLDS (lines 20-216) ──
    cl = [
        ("rate_cs", "C-Section Rate", ("5",), "2", "%", 100.0),
        ("rate_mmr", "Maternal Mortality Ratio", ("11",), "2", "per 100,000", 1.0),
        ("rate_nmr", "Neonatal Mortality Rate", ("17",), "6", "per 1,000", 1.0),
        ("rate_preterm", "Preterm Birth Rate", ("6.f",), "6", "%", 100.0),
        ("rate_smm", "Severe Maternal Morbidity Rate", ("10",), "2", "%", 100.0),
        ("rate_stillbirth", "Stillbirth Rate", ("7",), "2", "per 1,000", 1.0),
        ("rate_nicu", "NICU Admission Rate", ("16",), "6", "%", 100.0),
        ("rate_lbw", "Low Birth Weight Rate", ("6.g",), "6", "%", 100.0),
        ("rate_bf", "Breastfeeding within 1 Hour", ("13",), "6", "%", 100.0),
        ("rate_avd", "Assisted Vaginal Delivery Rate", ("4",), "2", "%", 100.0),
        ("rate_smm_hemorrhage_proportion", "Hemorrhage Proportion of SMM", ("10.a",), "10", "%", 100.0),
        ("rate_smm_hypertensive_proportion", "Hypertensive Proportion of SMM", ("10.e",), "10", "%", 100.0),
        ("rate_adolescent", "Adolescent Pregnancy Rate (10-19)", ("2.c", "2.d"), "2", "%", 100.0),
        ("rate_high_risk", "High-Risk Delivery Rate", ("2.n",), "2", "%", 100.0),
        ("rate_hysterectomy", "Hysterectomy per 1,000 Deliveries", ("10.d",), "2", "per 1,000", 1.0),
    ]
    for code, name, num, den, unit, mult in cl:
        itype = "percentage" if unit == "%" else "rate"
        specs.append(_spec(SITE_CLINICAL, code, code, name, itype,
                           num, (den,), mult, unit))

    # ── forecast slice — indicator_forecast.py INDICATOR_DEFS (lines 48-105) ──
    fc = [
        ("cs_rate", "C-section rate", "معدل العمليات القيصارية", ("5",), ("2",), 100.0, "%"),
        ("stillbirth_rate", "Stillbirth rate", "معدل الولادات الميتة", ("7",), ("6",), 1000.0, "per 1000"),
        ("preterm_rate", "Preterm birth rate", "معدل الولادات المبكرة", ("6.f",), ("6",), 100.0, "%"),
        ("lbw_rate", "Low birth weight rate", "معدل نقص وزن الولادة", ("6.g",), ("6",), 100.0, "%"),
        ("high_risk_rate", "High-risk share", "نسبة حالات الخطر العالي", ("2.n",), ("6",), 100.0, "%"),
        ("adolescent_rate", "Adolescent share", "نسبة حالات المراهقات", ("2.c", "2.d"), ("6",), 100.0, "%"),
        ("total_births", "Total live births", "إجمالي المواليد الأحياء", ("6",), (), 1.0, "count"),
    ]
    for key, en, _ar, num, den, per, unit in fc:
        itype = "count" if not den else ("percentage" if unit == "%" else "rate")
        specs.append(_spec(SITE_FORECAST, key, key, en, itype,
                           num, den, per, unit))

    # ── rules slice — quality/rules.py R043-R050 (lines 515-522) ──
    rl = [
        ("R043", "Preterm Birth Rate outlier across hospitals", "6.f", "6"),
        ("R044", "Low Birth Weight Rate outlier across hospitals", "6.g", "6"),
        ("R045", "Maternal Mortality Ratio outlier across hospitals", "11", "6"),
        ("R046", "Neonatal Mortality Rate outlier across hospitals", "17", "6"),
        ("R047", "Stillbirth Rate outlier across hospitals", "7", "2"),
        ("R048", "NICU Admission Rate outlier across hospitals", "16", "6"),
        ("R049", "SMM Rate outlier across hospitals", "10", "2"),
        ("R050", "Hemorrhage Rate outlier across hospitals", "10.a", "2"),
    ]
    for code, desc, num, den in rl:
        specs.append(_spec(SITE_RULES, code, f"rules_{code.lower()}", desc,
                           "percentage", (num,), (den,), 100.0, "%"))

    return {s.spec_key: s for s in specs}


BUILTIN_RATE_SPECS: Dict[str, RateSpec] = _build_builtin()


def iter_site(site: str) -> List[RateSpec]:
    """All specs of one site, in registry (source-file) order."""
    return [s for s in BUILTIN_RATE_SPECS.values() if s.site == site]


def zscore_specs() -> List[RateSpec]:
    return iter_site(SITE_ZSCORE)


def zscore_spec_for(numerator_code: str, denominator_code: str) -> Optional[RateSpec]:
    for s in zscore_specs():
        if s.numerator_codes == (numerator_code,) and s.denominator_codes == (denominator_code,):
            return s
    return None


def multiplier_for_unit(unit: Optional[str]) -> float:
    """100 for percent units, 1 otherwise."""
    if not unit:
        return 1.0
    for s in iter_site(SITE_CLINICAL):
        if s.unit == unit:
            return s.rate_multiplier
    return 100.0 if "%" in unit else 1.0


def compute_rate(values: Dict[str, float],
                 numerator_codes: Sequence[str],
                 denominator_codes: Sequence[str],
                 rate_multiplier: float) -> Optional[float]:
    num = 0.0
    for code in numerator_codes:
        v = values.get(code)
        if v is None:
            return None
        num += float(v)
    den = 0.0
    for code in denominator_codes:
        v = values.get(code)
        if v is None:
            return None
        den += float(v)
    if den == 0:
        return None
    return (num / den) * float(rate_multiplier)


def compute_spec_rate(spec: RateSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    return compute_rate(values, spec.numerator_codes, spec.denominator_codes,
                        spec.rate_multiplier)
