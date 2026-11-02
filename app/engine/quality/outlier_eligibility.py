"""Approved denominator for the layered outlier penalty.

The penalty asks *"of the indicators this hospital/month must be assessed on,
what share were flagged?"* — not *"what share of the rows that happened to be
evaluated?"*.  Rows only exist when an observation exists, so a month reporting
1 of 40 Required elements used to score 1/1 = 100% for a single finding, while
a complete month with the same finding scored 1/40 = 5%.  That is the same
missingness completeness already measures, punished a second time through an
unstable divisor.

Eligibility rules (approved indicator configuration)
----------------------------------------------------
* **Required** — ``requirement_type == "Required"`` (NULL behaves as Required),
  reported or missing.  A real reporting gap must not shrink the denominator.
* **Optional** — included only when it was actually assessed (present in the
  evaluated set).  An absent Optional element is a legitimate non-event.
* **Optional by inheritance** — a Required node whose whole source subtree is
  Optional follows the Optional rule: only counted when itself assessed.
* **Manually disabled** — excluded for this hospital/month (hospital override
  wins over the monthly default).  Rates that need a disabled input are not
  assessable and are excluded too.
* **Auto-disable-on-null** — deliberately NOT applied.  That is a completeness
  rule; applying it here would recreate the very defect this policy fixes.
* **Covered** — a required absent child already explained by its total is
  excluded, exactly as completeness excludes it: it has nothing of its own to
  analyse.
* **Synthetic labels** — never eligible.
* **Derived rates** — only when the rate itself was evaluated and all of its
  numerator/denominator inputs are eligible.

Zero is a value, not absence: a required indicator with value ``0`` stays in
the denominator (and produces a normal row).  Missing values also stay in the
denominator but have no row, so they count as *not flagged*.
"""
from typing import Iterable, Optional, Set

from sqlalchemy.orm import Session

from app.indicators import SYNTHETIC_INDICATOR_CODES


def _manual_disabled_ids(session: Session, hospital_id: int, month: str) -> Set[int]:
    """Only configuration-driven disables (hospital override > monthly default)."""
    from app.engine.pipeline import get_effective_manual_disabled_ids

    return set(get_effective_manual_disabled_ids(session, hospital_id, month))


def _optional_ids(session: Session) -> Set[int]:
    from app.engine.pipeline import get_optional_source_indicator_ids

    return set(get_optional_source_indicator_ids(session))


def _covered_codes(session: Session, hospital_id: int, month: str,
                   values: Optional[dict] = None) -> Set[str]:
    if values is None:
        from app.engine.pipeline import get_enabled_values_for_hospital_month
        values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    from app.engine.quality.rules import compute_covered_codes
    from app.models import Indicator

    disabled_ids = _manual_disabled_ids(session, hospital_id, month)
    disabled_codes = (
        {code for (code,) in session.query(Indicator.code)
         .filter(Indicator.id.in_(disabled_ids)).all()}
        if disabled_ids else set()
    )
    return compute_covered_codes(values or {}, disabled_codes, session)


def eligible_indicator_codes(
    session: Session,
    hospital_id: int,
    month: str,
    *,
    values: Optional[dict] = None,
    covered_codes: Optional[Iterable[str]] = None,
    evaluated_codes: Optional[Iterable[str]] = None,
) -> Set[str]:
    """Eligible Data Tree indicator codes for the outlier denominator."""
    from app.models import Indicator

    if values is None:
        from app.engine.pipeline import get_enabled_values_for_hospital_month
        values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    values = values or {}
    evaluated = None if evaluated_codes is None else {
        code for code in evaluated_codes if code}

    disabled_ids = _manual_disabled_ids(session, hospital_id, month)
    optional_ids = _optional_ids(session)
    covered = set(covered_codes) if covered_codes is not None else _covered_codes(
        session, hospital_id, month, values)
    rows = session.query(
        Indicator.id, Indicator.code, Indicator.requirement_type).all()

    eligible: Set[str] = set()
    for indicator_id, code, requirement in rows:
        if not code or code in SYNTHETIC_INDICATOR_CODES:
            continue
        if indicator_id in disabled_ids or code in covered:
            continue
        optional = (indicator_id in optional_ids
                    or (requirement or "Required") != "Required")
        if optional:
            # Absence is legitimate; only an actual assessment counts.
            assessed = (code in evaluated if evaluated is not None
                        else code in values)
            if not assessed:
                continue
        eligible.add(code)
    return eligible


def eligible_outlier_units(
    session: Session,
    hospital_id: int,
    month: str,
    *,
    values: Optional[dict] = None,
    covered_codes: Optional[Iterable[str]] = None,
    evaluated_codes: Optional[Iterable[str]] = None,
) -> Set[str]:
    """The approved denominator: eligible indicators + eligible rates.

    ``evaluated_codes`` is normally the analysis codes of the layered rows for
    the hospital+month.  Required elements are added even when absent; only
    Optional elements and derived rates need to appear in that set.  When it
    is omitted, reported values are treated as the assessed set.
    """
    from app.engine.anomaly.layered import build_analysis_specs

    if values is None:
        from app.engine.pipeline import get_enabled_values_for_hospital_month
        values = get_enabled_values_for_hospital_month(session, hospital_id, month)
    values = values or {}
    evaluated = None if evaluated_codes is None else {
        code for code in evaluated_codes if code}

    eligible_codes = eligible_indicator_codes(
        session, hospital_id, month, values=values,
        covered_codes=covered_codes, evaluated_codes=evaluated)
    units: Set[str] = set(eligible_codes)
    for spec in build_analysis_specs(session):
        if not spec.is_rate:
            continue
        sources = set(spec.numerator_codes) | set(spec.denominator_codes)
        if not sources or not sources <= eligible_codes:
            continue
        if evaluated is not None:
            assessed = spec.analysis_code in evaluated
        else:
            assessed = all(values.get(code) is not None for code in sources)
        if assessed:
            units.add(spec.analysis_code)
    return units


def eligible_outlier_code_list(session: Session, hospital_id: int,
                               month: str, **kwargs) -> list:
    """Sorted list form, for deterministic provenance/tests."""
    return sorted(eligible_outlier_units(session, hospital_id, month, **kwargs))


__all__ = [
    "eligible_indicator_codes",
    "eligible_outlier_code_list",
    "eligible_outlier_units",
]
