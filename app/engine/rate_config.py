"""Central rate-definition registry.

The three hardcoded rate sites (anomaly/zscore, clinical/thresholds,
smart/indicator_forecast) disagree today — MMR denominator 2 vs 6, stillbirth
denominator 2 vs 6, multipliers x1 / x100 / x1000. This
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
    # Multiplier follows the reported unit (same convention as the clinical and
    # forecast slices). The mortality trio used to be stored as "x100 / per
    # 100" here while clinical/forecast report per-1,000 / per-100,000 — one
    # rate key then showed TWO different formulas depending on the screen that
    # read it (Outlier Scan / Quality Alerts vs the Indicators registry).
    zs = [
        ("rate_cs", "C-section rate", "5", "2", 50.0, "%", 100.0),
        ("rate_mmr", "Maternal mortality ratio", "11", "2", 1.0, "per 100,000", 100000.0),
        ("rate_nmr", "Neonatal mortality rate", "17", "6", 30.0, "per 1,000", 1000.0),
        ("rate_preterm", "Preterm birth rate", "6.f", "6", 15.0, "%", 100.0),
        ("rate_smm", "SMM rate", "10", "2", 10.0, "%", 100.0),
        ("rate_stillbirth", "Stillbirth rate", "7", "2", 5.0, "per 1,000", 1000.0),
        ("rate_nicu", "NICU admission rate", "16", "6", 20.0, "%", 100.0),
    ]
    for code, name, num, den, pct, unit, mult in zs:
        itype = "percentage" if unit == "%" else "rate"
        specs.append(_spec(SITE_ZSCORE, name, code, name, itype,
                           (num,), (den,), mult, unit, typical_pct=pct))

    # ── clinical slice — thresholds.py CLINICAL_THRESHOLDS (lines 20-216) ──
    # The registry stores the display unit AND its numeric display scaling
    # together (same convention as the forecast slice): % = x100,
    # per-1,000 = x1,000, per-100,000 = x100,000. The earlier "x100, else x1"
    # rule lost the scaling when clinical classification moved onto
    # spec.rate_multiplier (fixed 2026-10-19: MMR/NMR/stillbirth classified
    # ~1,000x too low and test_clinical's regression matrix caught it).
    cl = [
        ("rate_cs", "C-Section Rate", ("5",), "2", "%", 100.0),
        ("rate_mmr", "Maternal Mortality Ratio", ("11",), "2", "per 100,000", 100000.0),
        ("rate_nmr", "Neonatal Mortality Rate", ("17",), "6", "per 1,000", 1000.0),
        ("rate_preterm", "Preterm Birth Rate", ("6.f",), "6", "%", 100.0),
        ("rate_smm", "Severe Maternal Morbidity Rate", ("10",), "2", "%", 100.0),
        ("rate_stillbirth", "Stillbirth Rate", ("7",), "2", "per 1,000", 1000.0),
        ("rate_nicu", "NICU Admission Rate", ("16",), "6", "%", 100.0),
        ("rate_lbw", "Low Birth Weight Rate", ("6.g",), "6", "%", 100.0),
        ("rate_bf", "Breastfeeding within 1 Hour", ("13",), "6", "%", 100.0),
        ("rate_avd", "Assisted Vaginal Delivery Rate", ("4",), "2", "%", 100.0),
        ("rate_smm_hemorrhage_proportion", "Hemorrhage Proportion of SMM", ("10.a",), "10", "%", 100.0),
        ("rate_smm_hypertensive_proportion", "Hypertensive Proportion of SMM", ("10.e",), "10", "%", 100.0),
        ("rate_adolescent", "Adolescent Pregnancy Rate (10-19)", ("2.c", "2.d"), "2", "%", 100.0),
        ("rate_high_risk", "High-Risk Delivery Rate", ("2.n",), "2", "%", 100.0),
        ("rate_hysterectomy", "Hysterectomy per 1,000 Deliveries", ("10.d",), "2", "per 1,000", 1000.0),
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
        ("smm_per_1000", "Severe maternal morbidity per 1,000 live births", "المضاعفات الخطيرة لكل 1000 مولود حي", ("10",), ("6",), 1000.0, "per 1000"),
        ("smm_per_1000_deliveries", "Severe maternal morbidity per 1,000 deliveries", "المضاعفات الخطيرة لكل 1000 ولادة", ("10",), ("2",), 1000.0, "per 1000"),
        ("mat_mortality_rate", "Maternal deaths per 100,000 live births", "الوفيات الأمومية لكل 100000 مولود حي", ("11",), ("6",), 100000.0, "per 100000"),
        ("nd_per_1000", "Neonatal deaths per 1,000 live births", "وفيات حديثي الولادة لكل 1000 مولود حي", ("17",), ("6",), 1000.0, "per 1000"),
        ("total_births", "Total live births", "إجمالي المواليد الأحياء", ("6",), (), 1.0, "count"),
        # ── عدّادات خام (طلب المستخدم): حركة المؤشر الخام بجانب معدلاته،
        # بمفاتيح مطابقة لمفاتيح FEATURE_KEYS في التحليل الذكي لتربط الشاشتان
        # نفس المؤشر — numerator مطابق لـ FEATURE_SOURCE_CODES (engine/smart) ──
        ("cs_count", "C-section deliveries (count)", "عدد العمليات القيصارية", ("5",), (), 1.0, "count"),
        ("sb", "Stillbirths (count)", "الولادات الميتة", ("7",), (), 1.0, "count"),
        ("preterm", "Preterm births (count)", "الولادات السابقة لأوانها", ("6.f",), (), 1.0, "count"),
        ("lbw", "Low birth weight newborns (count)", "نقص وزن الولادة", ("6.g",), (), 1.0, "count"),
        ("high_risk", "High-risk cases (count)", "حالات الخطر العالي", ("2.n",), (), 1.0, "count"),
        ("adolescent", "Adolescent cases (count)", "الحالات المراهقة", ("2.c", "2.d"), (), 1.0, "count"),
        ("smm_total", "Severe maternal morbidity (count)", "المضاعفات الخطيرة", ("10",), (), 1.0, "count"),
        ("mat_deaths", "Maternal deaths (count)", "الوفيات الأمومية", ("11",), (), 1.0, "count"),
        ("nd", "Neonatal deaths (count)", "الوفيات الجديدة", ("17",), (), 1.0, "count"),
    ]
    for key, en, _ar, num, den, per, unit in fc:
        itype = "count" if not den else ("percentage" if unit == "%" else "rate")
        specs.append(_spec(SITE_FORECAST, key, key, en, itype,
                           num, den, per, unit))

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
    """Return the numeric display scaling implied by a unit.

    % (or "percent") = x100, per-1,000 = x1,000, per-100,000 = x100,000,
    anything else (counts) = x1. The unit string is normalized (comma-free)
    so the clinical slice's "per 1,000"/"per 100,000" and the forecast
    slice's "per 1000"/"per 100000" resolve identically. This matches each
    spec's ``rate_multiplier`` (the registry stores the scaling right next
    to the unit), so unit-based scaling and ratio evaluation can never
    disagree — the earlier "x1 otherwise" rule classified the mortality
    trio ~1,000x too low once classification moved onto spec multipliers
    (caught by test_clinical's regression matrix, fixed 2026-10-19).
    """
    if not unit:
        return 1.0
    normalized = unit.strip().lower().replace(",", "")
    if "%" in normalized or normalized == "percent":
        return 100.0
    for scale in (1000, 100000):
        if normalized == f"per {scale}":
            return float(scale)
    return 1.0


def compute_rate(values: Dict[str, float],
                 numerator_codes: Sequence[str],
                 denominator_codes: Sequence[str],
                 rate_multiplier: float) -> Optional[float]:
    from app.engine import indicator_calc

    outcome = indicator_calc.evaluate_ratio_values(
        numerator_codes=numerator_codes,
        denominator_codes=denominator_codes,
        raw=values,
        multiplier=rate_multiplier,
    )
    return outcome.value if outcome.status == indicator_calc.STATUS_OK else None


def compute_spec_rate(spec: RateSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    return compute_rate(values, spec.numerator_codes, spec.denominator_codes,
                        spec.rate_multiplier)


def builtin_spec(site: str, rate_code: str) -> Optional[RateSpec]:
    """Builtin registry spec of a site keyed by rate_code — no DB session.

    The builtin registry is the single source of truth for every rate's
    numerator / denominator / multiplier. Screens and engine modules that
    only hold raw ``{code: value}`` dicts call this instead of re-writing
    ``x / y * 100`` inline, so a registry edit propagates everywhere.
    """
    for spec in iter_site(site):
        if spec.rate_code == rate_code:
            return spec
    return None


def builtin_rate(site: str, rate_code: str, values: Dict[str, float],
                 default: Optional[float] = 0.0) -> Optional[float]:
    """Compute a registry rate from raw values — the registry-driven
    replacement for inline ``numerator / denominator * multiplier``.

    Returns ``default`` when the registry has no such spec or the ratio
    cannot be computed (missing numerator/denominator, zero denominator —
    same statuses as :func:`compute_spec_rate`). ``default`` preserves each
    call site's legacy missing-data behaviour (0 for screens that showed a
    zero, None where missing is shown as missing).
    """
    spec = builtin_spec(site, rate_code)
    if spec is None:
        return default
    value = compute_spec_rate(spec, values)
    return default if value is None else value


# ── DB layer (design spec §4): rate_config rows merged over builtin ──────────

_RATE_SPECS_CACHE: Optional[Dict[str, RateSpec]] = None


def invalidate_rate_specs_cache() -> None:
    """Drop the DB-merged spec cache (seed_rate_config and any future
    rate_config save call this; tests reset it around every test)."""
    global _RATE_SPECS_CACHE
    _RATE_SPECS_CACHE = None


def _pick(value, fallback):
    return fallback if value is None else value


def _spec_from_rate_config_row(row, base: Optional[RateSpec]) -> RateSpec:
    """DB row over its builtin base. unit/typical_pct are not stored in the
    table (spec §3.3) — inherited from the builtin zscore-slice spec with the
    same rate_code; unknown rate_codes get empty unit."""
    numerator = tuple(row.numerator_codes or ())
    denominator = tuple(row.denominator_codes or ())
    multiplier = row.rate_multiplier if row.rate_multiplier is not None else (
        base.rate_multiplier if base else 1.0)
    return RateSpec(
        spec_key=f"db:{row.rate_code}",
        site=SITE_ZSCORE,
        rate_code=row.rate_code,
        rate_name=row.rate_name or (base.rate_name if base else row.rate_code),
        indicator_code=numerator[0] if numerator else (base.indicator_code if base else ""),
        indicator_type=row.indicator_type or (base.indicator_type if base else "rate"),
        numerator_codes=numerator,
        denominator_codes=denominator,
        rate_multiplier=float(multiplier),
        unit=base.unit if base else "",
        typical_pct=base.typical_pct if base else None,
        minimum_denominator=row.minimum_denominator,
        minimum_history_period=_pick(
            row.minimum_history_period,
            base.minimum_history_period if base else 3),
        outlier_method=row.outlier_method or (base.outlier_method if base else "auto"),
        historical_enabled=_pick(
            row.historical_enabled,
            base.historical_enabled if base else True),
        peer_comparison_enabled=_pick(
            row.peer_comparison_enabled,
            base.peer_comparison_enabled if base else True),
        is_active=_pick(row.is_active, True),
    )


def load_rate_specs(db) -> Dict[str, RateSpec]:
    """The layered engine's spec set, keyed by rate_code: DB rate_config rows
    (runtime tunables) merged over the builtin zscore-slice defaults.

    Falls back entirely to the builtin slice when the table is empty
    (pre-seed operation) or unreadable. In-process cache — call
    invalidate_rate_specs_cache() after seeding/saving rate_config rows.

    The Indicators registry is the active/inactive source of truth: a spec
    whose seed record is deactivated on the Indicators screen is filtered
    out of the CURRENT set (freshly queried on every call so a toggle takes
    effect immediately — the raw merge stays process-cached). Inactive
    indicators keep their historical results and audit records; only new
    calculation runs skip them.
    """
    global _RATE_SPECS_CACHE
    if _RATE_SPECS_CACHE is None:
        specs: Dict[str, RateSpec] = {s.rate_code: s for s in zscore_specs()}
        try:
            from app.models import RateConfig  # local: this module stays leaf-importable
            rows = db.query(RateConfig).order_by(RateConfig.rate_code).all()
        except Exception as exc:
            logger.warning("rate_config unreadable (%s); using builtin zscore slice", exc)
            rows = []
        for row in rows:
            spec = _spec_from_rate_config_row(row, specs.get(row.rate_code))
            if spec.is_active is False:
                # RateConfig explicitly switched OFF: remove the rate entirely
                # (its builtin base must not resurface as a silent default).
                specs.pop(row.rate_code, None)
                continue
            specs[row.rate_code] = spec
        _RATE_SPECS_CACHE = specs

    try:
        from app.models import IndicatorDefinition
        rows = (db.query(IndicatorDefinition.code, IndicatorDefinition.legacy_code)
                .filter(IndicatorDefinition.is_active.is_(False)).all())
    except Exception:
        rows = []
    if not rows:
        return _RATE_SPECS_CACHE
    inactive: set = set()
    for canonical, legacy in rows:
        if canonical:
            inactive.add(canonical)
        if legacy:
            inactive.add(legacy)
    if not inactive:
        return _RATE_SPECS_CACHE
    return {code: spec for code, spec in _RATE_SPECS_CACHE.items()
            if code not in inactive}


def get_spec(db, rate_code: str) -> Optional[RateSpec]:
    return load_rate_specs(db).get(rate_code)


def sync_rate_config_from_definition(db, definition) -> bool:
    """Copy an Indicators-screen rate definition onto its rate_config row.

    The zscore slice is stored twice: ``indicator_definitions`` (what the
    Indicators screen shows and edits) and ``rate_config`` (what the Outlier
    Scan / Quality Alerts engine actually calculates with). Editing the
    indicator alone left the engine on the frozen seed formula, so the same
    rate showed two different calculations — e.g. Neonatal mortality rate at
    ``{17} / {6} * 1000`` on the Indicators screen and ``{17} / {6} * 100`` in
    the Quality explanation. Every save of a zscore-scoped definition now
    writes its formula fields through to the row the engine reads.

    Returns True when a row was created or changed (the spec cache is dropped
    either way only when something changed).
    """
    if definition is None:
        return False
    if getattr(definition, "source_site", None) != SITE_ZSCORE:
        return False
    code = getattr(definition, "legacy_code", None) or getattr(definition, "code", None)
    if not code or code not in {spec.rate_code for spec in zscore_specs()}:
        return False

    from app.models import RateConfig

    row = db.query(RateConfig).filter(RateConfig.rate_code == code).first()
    created = row is None
    if created:
        row = RateConfig(rate_code=code)
        db.add(row)

    values = {
        "rate_name": definition.name,
        "indicator_type": definition.result_type,
        "rate_multiplier": definition.multiplier,
        "is_active": bool(definition.is_active),
    }
    # Formula codes only exist for ratio definitions; an expression-mode
    # definition must not blank the engine's numerator/denominator pairs.
    if (getattr(definition, "formula_type", "ratio") or "ratio") == "ratio":
        values["numerator_codes"] = list(definition.numerator_codes or [])
        values["denominator_codes"] = list(definition.denominator_codes or [])

    changed = created
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    if changed:
        db.flush()
        invalidate_rate_specs_cache()
    return changed
