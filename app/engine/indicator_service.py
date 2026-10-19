"""Shared indicator calculation service (centralized-indicators, 2026-10-18).

The single READ path every dependent module (Audit, Outlier Analysis,
Dashboards, Reports) uses to obtain an indicator's value with full
provenance. Nothing here re-implements formula math:

* ``derived`` definitions (app.models.IndicatorDefinition) are evaluated by
  the exact same code the Indicators tab uses — ``indicator_calc``.
* ``rate_spec`` indicators (app.engine.rate_config) are re-expressed as a
  ratio definition and evaluated by ``indicator_calc.evaluate_definition``
  too, so an auditor's benchmark and the registry engine can never drift
  apart — one calculation, one set of edge-case semantics (missing vs
  reported-zero, zero denominator -> NULL value, never a silent 0).
* ``raw`` data elements just expose the stored value with the same status
  vocabulary.

Every result carries ``indicator_id``, ``formula_version``, ``hospital_id``,
``month`` and ``status`` so screens and stored findings can point back at
the exact formula that produced a number (audit-linkage requirement).
Formula versions are stable and honest about their source:

* derived  -> ``str(definition.version)`` (bumps on every content change)
* rate spec-> ``spec:<crc32 fingerprint>`` — builtin specs are code
  constants (versioned with the codebase); a fingerprint changes exactly
  when num/den/multiplier/unit/type change, so an old stored finding can
  always tell whether its formula is still current.
* raw      -> ``raw`` (elements have no formula)
"""
from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Optional

from app.engine import indicator_calc as calc
from app.engine import indicator_deps
from app.engine.rate_config import (
    SITE_CLINICAL,
    SITE_FORECAST,
    SITE_ZSCORE,
    RateSpec,
    iter_site,
    load_rate_specs,
)

logger = logging.getLogger(__name__)

SOURCE_DERIVED = "derived"
SOURCE_RATE_SPEC = "rate_spec"
SOURCE_RAW = "raw"


@dataclass
class ResolvedIndicator:
    """One indicator as the registry understands it, whatever its source."""
    source: str                      # derived | rate_spec | raw
    code: str
    name: str
    indicator_id: str                # derived:{id} | rate:{spec_key} | raw:{code}
    formula_version: str             # see module docstring
    formula: Optional[str] = None    # canonical expression / ratio string / None
    unit: Optional[str] = None
    group_name: Optional[str] = None
    indicator_type: Optional[str] = None
    is_active: bool = True
    site: Optional[str] = None       # rate_config site (rate_spec only)
    ref_codes: List[str] = field(default_factory=list)
    definition: object = None        # IndicatorDefinition (derived)
    spec: object = None              # RateSpec (rate_spec)


@dataclass
class CalculationResult:
    """Value + provenance for one indicator at one hospital+month."""
    indicator_id: str
    code: str
    name: str
    source: str
    value: Optional[float]
    status: str                      # calc.STATUS_* vocabulary
    formula: Optional[str]
    formula_version: str
    hospital_id: int
    month: Optional[str]
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    inputs: Dict[str, Optional[float]] = field(default_factory=dict)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == calc.STATUS_OK


# ── resolution ───────────────────────────────────────────────────────────────

def spec_fingerprint(spec: RateSpec) -> str:
    """Stable content fingerprint for a rate spec (zlib, not hash() —
    hash() is randomized per process and would make versions flap)."""
    payload = "|".join((
        ",".join(spec.numerator_codes or ()),
        ",".join(spec.denominator_codes or ()),
        repr(float(spec.rate_multiplier)),
        spec.unit or "",
        spec.indicator_type or "",
    ))
    return f"spec:{zlib.crc32(payload.encode('utf-8')) & 0xFFFFFFFF:08x}"


def _resolve_spec(db, code: str, site: Optional[str]) -> Optional[RateSpec]:
    """Find a rate spec for ``code``.

    site None  -> the DB-merged runtime set (load_rate_specs = builtin
                  zscore + rate_config rows) first, then the builtin
                  clinical and forecast slices.
    site given -> exactly that slice.
    """
    if site is None or site in (SITE_ZSCORE, "db"):
        try:
            spec = load_rate_specs(db).get(code)
        except Exception:  # pragma: no cover - registry is optional context
            spec = None
        if spec is not None:
            return spec
    sites = [site] if site else [SITE_CLINICAL, SITE_FORECAST]
    for s in sites:
        for spec in iter_site(s):
            if spec.rate_code == code:
                return spec
    return None


def _resolved_definition(defn) -> ResolvedIndicator:
    try:
        codes = calc.definition_codes(defn)
    except calc.FormulaError:  # pragma: no cover - stored defs are validated
        codes = []
    formula = defn.expression or None
    if getattr(defn, "formula_type", "ratio") == "ratio":
        formula = calc.build_ratio_expression(
            getattr(defn, "numerator_codes", None) or [],
            getattr(defn, "denominator_codes", None) or [],
            getattr(defn, "operator", "/") or "/",
            getattr(defn, "multiplier", 1.0) or 1.0,
        )
    return ResolvedIndicator(
        source=SOURCE_DERIVED,
        code=defn.code,
        name=defn.name,
        indicator_id=f"derived:{defn.id}",
        formula_version=str(int(getattr(defn, "version", 1) or 1)),
        formula=formula,
        unit=defn.unit,
        group_name=defn.group_name,
        indicator_type=defn.result_type,
        is_active=bool(defn.is_active),
        site=getattr(defn, "source_site", None),
        ref_codes=codes,
        definition=defn,
    )


def _resolved_spec(spec: RateSpec) -> ResolvedIndicator:
    num = list(spec.numerator_codes or ())
    den = list(spec.denominator_codes or ())
    if den:
        formula = calc.build_ratio_expression(num, den, "/", spec.rate_multiplier)
    elif num:
        formula = calc.build_ratio_expression(num, [], "*", spec.rate_multiplier)
    else:  # pragma: no cover - no builtin spec has neither part
        formula = None
    return ResolvedIndicator(
        source=SOURCE_RATE_SPEC,
        code=spec.rate_code,
        name=spec.rate_name,
        indicator_id=f"rate:{spec.spec_key}",
        formula_version=spec_fingerprint(spec),
        formula=formula,
        unit=(spec.unit or None),
        indicator_type=spec.indicator_type,
        site=spec.site,
        ref_codes=num + den,
        spec=spec,
    )


def resolve_spec(spec: RateSpec) -> ResolvedIndicator:
    """Public wrapper: turn an already-located RateSpec (e.g. from
    zscore_spec_for inside an engine) into a ResolvedIndicator without a
    registry lookup. Used by Audit/Outlier provenance attachment."""
    return _resolved_spec(spec)


def resolve(db, code: str, site: Optional[str] = None) -> Optional[ResolvedIndicator]:
    """Resolve a registry definition or raw element by stable code/alias.

    Site-scoped legacy aliases must be unambiguous unless the caller supplies
    their site. Built-in rate constants are deliberately not a runtime
    fallback: the startup migration seeds their editable registry records.
    """
    code = (code or "").strip()
    if not code:
        return None
    from app.models import Indicator, IndicatorDefinition

    query = db.query(IndicatorDefinition)
    if site:
        query = query.filter(
            ((IndicatorDefinition.source_site.is_(None))
             & (IndicatorDefinition.code == code))
            | ((IndicatorDefinition.source_site == site)
               & ((IndicatorDefinition.code == code)
                  | (IndicatorDefinition.legacy_code == code)))
        )
    else:
        query = query.filter(
            (IndicatorDefinition.code == code)
            | (IndicatorDefinition.legacy_code == code)
        )
    definitions = query.order_by(IndicatorDefinition.id).all()
    if len(definitions) == 1:
        return _resolved_definition(definitions[0])
    if len(definitions) > 1:
        logger.warning(
            "Indicator alias %r is ambiguous without a site; matching definitions: %s",
            code, [f"{d.source_site}:{d.code}" for d in definitions])
        return None

    raw_ind = db.query(Indicator).filter(Indicator.code == code).first()
    if raw_ind is not None:
        return ResolvedIndicator(
            source=SOURCE_RAW,
            code=code,
            name=raw_ind.name,
            indicator_id=f"raw:{code}",
            formula_version="raw",
            formula=(raw_ind.formula or None),
            unit=getattr(raw_ind, "unit", None),
            group_name=raw_ind.group_name,
            indicator_type=raw_ind.indicator_type or "count",
            ref_codes=[code],
        )
    return None


def resolve_active_definitions(db, site: Optional[str] = None) -> List[ResolvedIndicator]:
    """Resolve active shared definitions and the requested site's definitions."""
    from app.models import IndicatorDefinition

    query = db.query(IndicatorDefinition).filter(
        IndicatorDefinition.is_active.is_(True)
    )
    if site:
        query = query.filter(
            (IndicatorDefinition.source_site.is_(None))
            | (IndicatorDefinition.source_site == site)
        )
    definitions = query.order_by(IndicatorDefinition.code).all()
    return [_resolved_definition(definition) for definition in definitions]


# ── provenance of a STORED result ────────────────────────────────────────────

FORMULA_STATUS_CURRENT = "current"
FORMULA_STATUS_STALE = "stale"
FORMULA_STATUS_UNVERIFIED = "unverified"
FORMULA_STATUS_UNREGISTERED = "unregistered"


def resolve_ref(db, indicator_id: Optional[str]) -> Optional[ResolvedIndicator]:
    """Resolve the ``indicator_id`` stored on a result back to the registry.

    Stored ids are the ones ``_resolved_definition``/``_resolved_spec`` emit:

    * ``derived:<definition id>`` — versioned Indicators-registry row
    * ``rate:<site>:<legacy code>`` — legacy rate-spec id (``db`` = zscore)
    * ``raw:<element code>`` — raw Data-Tree element
    """
    ref = (indicator_id or "").strip()
    if not ref:
        return None
    if ref.startswith("derived:"):
        try:
            definition_id = int(ref.split(":", 1)[1])
        except (TypeError, ValueError):
            return None
        from app.models import IndicatorDefinition

        definition = (
            db.query(IndicatorDefinition)
            .filter(IndicatorDefinition.id == definition_id)
            .first()
        )
        return _resolved_definition(definition) if definition else None
    if ref.startswith("rate:"):
        payload = ref.split(":", 1)[1]
        if ":" in payload:
            site, code = payload.split(":", 1)
            site = SITE_ZSCORE if site == "db" else site
        else:
            site, code = None, payload
        resolved = resolve(db, code, site=site)
        if resolved is not None:
            return resolved
        spec = _resolve_spec(db, code, site)
        return _resolved_spec(spec) if spec else None
    if ref.startswith("raw:"):
        return resolve(db, ref.split(":", 1)[1])
    return resolve(db, ref)


def registry_provenance(
    db,
    indicator_id: Optional[str],
    formula_version: Optional[str] = None,
    formula: Optional[str] = None,
) -> Dict[str, object]:
    """Compare a stored result's formula version with the live registry.

    Returns the unit and current formula metadata plus a ``formula_status``:

    * ``current``      — the stored version matches the registry row
    * ``stale``        — the registry formula changed since the value was stored
    * ``unverified``   — the stored row predates version tracking (no version)
    * ``unregistered`` — the stored id no longer resolves to any definition
    """
    resolved = resolve_ref(db, indicator_id)
    stored = (formula_version or "").strip()
    if resolved is None:
        return {
            "indicator_id": indicator_id,
            "indicator_code": None,
            "name": None,
            "unit": None,
            "formula": formula,
            "formula_version": formula_version,
            "current_formula_version": None,
            "formula_status": FORMULA_STATUS_UNREGISTERED,
            "is_active": False,
        }
    if not stored:
        status = FORMULA_STATUS_UNVERIFIED
    elif stored == resolved.formula_version:
        status = FORMULA_STATUS_CURRENT
    else:
        status = FORMULA_STATUS_STALE
    return {
        "indicator_id": resolved.indicator_id,
        "indicator_code": resolved.code,
        "name": resolved.name,
        "unit": resolved.unit,
        "formula": formula or resolved.formula,
        "formula_version": formula_version,
        "current_formula_version": resolved.formula_version,
        "formula_status": status,
        "is_active": bool(resolved.is_active),
    }


# ── calculation ──────────────────────────────────────────────────────────────

def spec_as_definition(spec: RateSpec):
    """A rate spec in the shape ``evaluate_definition`` consumes.

    Count-type specs (no denominator) multiply; rate specs divide — the
    same formula strings the catalog displays. precision stays None: specs
    have no rounding config, consumers round for display.
    """
    return SimpleNamespace(
        formula_type="ratio",
        expression=None,
        numerator_codes=list(spec.numerator_codes or ()),
        denominator_codes=list(spec.denominator_codes or ()),
        operator=("/" if spec.denominator_codes else "*"),
        multiplier=float(spec.rate_multiplier),
        aggregation="sum",
        precision=None,
        rounding="half_up",
        result_type=spec.indicator_type,
        unit=spec.unit,
    )


def calculate_from_values(
    resolved: ResolvedIndicator,
    raw: Dict[str, Optional[float]],
    hospital_id: int,
    month: Optional[str],
) -> CalculationResult:
    """Evaluate a resolved indicator against already-loaded raw values."""
    if month is None:
        return CalculationResult(
            indicator_id=resolved.indicator_id, code=resolved.code,
            name=resolved.name, source=resolved.source, value=None,
            status=calc.STATUS_NO_DATA, formula=resolved.formula,
            formula_version=resolved.formula_version,
            hospital_id=hospital_id, month=None,
            message="No reporting month given")

    if not resolved.is_active:
        return CalculationResult(
            indicator_id=resolved.indicator_id, code=resolved.code,
            name=resolved.name, source=resolved.source, value=None,
            status="inactive", formula=resolved.formula,
            formula_version=resolved.formula_version,
            hospital_id=hospital_id, month=month,
            message="Indicator definition is inactive")

    if resolved.source == SOURCE_DERIVED:
        outcome = calc.evaluate_definition(resolved.definition, raw)
    elif resolved.source == SOURCE_RATE_SPEC:
        outcome = calc.evaluate_definition(
            spec_as_definition(resolved.spec), raw)
    else:  # raw element
        outcome = calc.ComputeOutcome(inputs=dict(raw))
        if resolved.code not in raw:
            outcome.status = calc.STATUS_NO_DATA
            outcome.message = "No data reported for this element"
        elif raw[resolved.code] is None:
            outcome.status = calc.STATUS_MISSING
            outcome.missing_codes = [resolved.code]
            outcome.message = "Reported with an empty value"
        else:
            outcome.status = calc.STATUS_OK
            outcome.value = raw[resolved.code]

    return CalculationResult(
        indicator_id=resolved.indicator_id,
        code=resolved.code,
        name=resolved.name,
        source=resolved.source,
        value=outcome.value,
        status=outcome.status,
        formula=resolved.formula,
        formula_version=resolved.formula_version,
        hospital_id=hospital_id,
        month=month,
        numerator=outcome.numerator,
        denominator=outcome.denominator,
        inputs=dict(outcome.inputs),
        message=outcome.message,
    )


def calculate(db, code: str, hospital_id: int, month: Optional[str],
              site: Optional[str] = None) -> Optional[CalculationResult]:
    """Resolve ``code`` and calculate it. None when the code is unknown."""
    resolved = resolve(db, code, site=site)
    if resolved is None:
        return None
    return calculate_resolved(db, resolved, hospital_id, month    )


def calculate_resolved(db, resolved: ResolvedIndicator, hospital_id: int,
                       month: Optional[str]) -> CalculationResult:
    """Evaluate a resolved indicator for one hospital+month (never stores)."""
    if month is None:
        return calculate_from_values(resolved, {}, hospital_id, None)
    if resolved.source == SOURCE_DERIVED:
        try:
            codes = calc.definition_codes(resolved.definition)
        except calc.FormulaError:
            codes = []
    else:
        codes = [resolved.code] if resolved.source == SOURCE_RAW else resolved.ref_codes
    raw = calc.load_raw_values(db, codes, hospital_id, month)
    return calculate_from_values(resolved, raw, hospital_id, month)


# ── dependencies ─────────────────────────────────────────────────────────────

def dependencies(resolved: ResolvedIndicator) -> List[dict]:
    """Modules depending on a resolved indicator (see indicator_deps)."""
    return indicator_deps.dependencies_for(
        resolved.source, resolved.code,
        site=resolved.site,
        ref_codes=tuple(resolved.ref_codes or ()),
    )


__all__ = [
    "SOURCE_DERIVED", "SOURCE_RATE_SPEC", "SOURCE_RAW",
    "ResolvedIndicator", "CalculationResult",
    "spec_fingerprint", "spec_as_definition",
    "resolve", "resolve_spec", "resolve_active_definitions", "resolve_ref",
    "registry_provenance",
    "FORMULA_STATUS_CURRENT", "FORMULA_STATUS_STALE",
    "FORMULA_STATUS_UNVERIFIED", "FORMULA_STATUS_UNREGISTERED",
    "calculate", "calculate_resolved",
    "calculate_from_values", "dependencies",
]
