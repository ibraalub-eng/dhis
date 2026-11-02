"""One canonical identity per logical rate/formula.

The Indicators Registry deliberately keeps one row per analysis site
(``sys_zscore_rate_cs``, ``sys_clinical_rate_cs``, ``sys_forecast_cs_rate``…)
and rate definitions are also mirrored under legacy codes. Those rows are the
SAME clinical number computed one way, so every engine that compares values
must identify the finding by the FORMULA, not by whichever code happened to
hold it — otherwise one deviation is reported twice.

The identity used everywhere is the one the outlier scan already relied on:

* the formula expression, exactly as ``indicator_calc`` builds it for a ratio
  (so numerator codes, denominator codes, operator and multiplier are all
  encoded), or the stored expression for expression-mode definitions, and
* the numeric display scale implied by the unit (``per 1,000`` and
  ``per 1000`` are the same scale, ``%`` and ``percent`` are the same scale).

Raw data elements have no formula and none may be invented for them, so each
one is identified by its own code and can never be merged with a rate.

This is a leaf module (``indicator_calc`` and ``rate_config`` are leaves too),
so Anomaly Diagnostics, the registry service and Quality Alerts can all import
it without a cycle.
"""
from __future__ import annotations

import zlib
from typing import Iterable, Optional, Tuple

from app.engine import indicator_calc
from app.engine.rate_config import multiplier_for_unit

IDENTITY_FORMULA = "formula"
IDENTITY_CODE = "code"


def ratio_identity(numerator_codes: Optional[Iterable[str]],
                   denominator_codes: Optional[Iterable[str]],
                   operator: Optional[str],
                   multiplier: Optional[float],
                   unit: Optional[str]) -> tuple:
    """Canonical identity of a ratio/count formula (no registry row needed)."""
    formula = indicator_calc.build_ratio_expression(
        list(numerator_codes or ()),
        list(denominator_codes or ()),
        operator or "/",
        float(multiplier or 1.0),
    )
    return (IDENTITY_FORMULA, formula, float(multiplier_for_unit(unit)))


def resolved_identity(resolved) -> tuple:
    """Canonical identity of a resolved registry definition or data element."""
    return stored_identity(getattr(resolved, "formula", None),
                           getattr(resolved, "unit", None),
                           getattr(resolved, "code", ""))


def stored_identity(formula: Optional[str], unit: Optional[str],
                    code: Optional[str]) -> tuple:
    """Identity of a STORED finding, from the formula it was computed with.

    A persisted alert keeps the formula (and unit) that produced it, so the
    formula stored on the row — not the definition's current state — decides
    which logical finding it belongs to. Editing a definition later therefore
    never re-files historical alerts under a formula they were not computed
    with; a row without a formula (raw data element) is its own identity.
    """
    if not formula:
        return (IDENTITY_CODE, str(code or ""))
    return (IDENTITY_FORMULA, str(formula), float(multiplier_for_unit(unit)))


def alert_identity(alert) -> tuple:
    """Canonical identity of a persisted QualityAlert (or similar row)."""
    return stored_identity(getattr(alert, "formula", None),
                           getattr(alert, "unit", None),
                           getattr(alert, "indicator_code", ""))


def identity_key(identity: Tuple) -> str:
    """Stable short key for a canonical identity (persisted in evidence).

    ``zlib.crc32`` rather than ``hash()``: the value is stored on alert rows,
    so it must not change from one process to the next.
    """
    payload = "|".join(str(part) for part in identity)
    return f"{zlib.crc32(payload.encode('utf-8')) & 0xFFFFFFFF:08x}"
