"""The one disabled hospital-month eligibility rule.

A month switched off for a hospital (``month_enabled_<hid>_<YYYY-MM> = "false"``)
is outside that hospital's reporting scope. Stored rows are **not deleted**:
they stay available to the documented historical/audit views, but no active
reader may present them as current results.

Every reader must call this module instead of re-deriving the rule, so
dashboards, reports, exports, trends and drilldowns cannot drift apart again.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Set, Tuple

from sqlalchemy.orm import Session

MONTH_SETTINGS_PREFIX = "month_enabled_"
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

Pair = Tuple[int, str]


def parse_month_setting(key: str) -> Optional[Pair]:
    """``month_enabled_<hospital_id>_<YYYY-MM>`` → ``(hospital_id, month)``.

    Malformed keys (non-numeric hospital id, empty/!!invalid month, unrelated
    settings) return ``None`` and are ignored by every caller.
    """
    if not key or not key.startswith(MONTH_SETTINGS_PREFIX):
        return None
    rest = key[len(MONTH_SETTINGS_PREFIX):]
    hid_str, sep, month = rest.partition("_")
    if not sep or not hid_str.isdigit() or not _MONTH_RE.match(month):
        return None
    return int(hid_str), month


def _is_false(value) -> bool:
    """Only an explicit false disables; missing/true/anything else does not."""
    return str(value).strip().lower() == "false" if value is not None else False


def disabled_pairs(db: Session) -> Set[Pair]:
    """Every explicitly disabled ``(hospital_id, month)`` pair."""
    from app.models import SystemSetting

    rows = (
        db.query(SystemSetting.key, SystemSetting.value)
        .filter(SystemSetting.key.like(MONTH_SETTINGS_PREFIX + "%"))
        .all()
    )
    out: Set[Pair] = set()
    for key, value in rows:
        if not _is_false(value):
            continue
        pair = parse_month_setting(key)
        if pair is not None:
            out.add(pair)
    return out


def is_month_enabled(pairs: Iterable[Pair], hospital_id: int, month: str) -> bool:
    """True unless this exact pair is in the disabled set."""
    return (hospital_id, month) not in set(pairs)


def month_disabled(db: Session, hospital_id: int, month: str,
                   pairs: Optional[Iterable[Pair]] = None) -> bool:
    """Read the shared rule for one hospital+month."""
    if pairs is None:
        pairs = disabled_pairs(db)
    return (hospital_id, month) in set(pairs)


def _disabled_condition(model, pairs: Iterable[Pair], hospital_id=None):
    """SQL condition excluding disabled pairs without dropping other hospitals."""
    from sqlalchemy import and_, or_

    by_hosp: dict = {}
    for hid, month in pairs:
        if hospital_id is not None and hid != hospital_id:
            continue
        by_hosp.setdefault(hid, set()).add(month)
    if not by_hosp:
        return None
    return and_(*[
        or_(model.hospital_id != hid, ~model.month.in_(months))
        for hid, months in by_hosp.items()
    ])


def exclude_disabled(db: Session, query, model, hospital_id=None):
    """Apply the shared disabled-pair rule to a QualityScore/ConfidenceScore query.

    ``hospital_id`` narrows the rule for a single-hospital query; network-wide
    queries pass ``None`` and exclude every hospital's disabled months. A
    hospital with no disabled months passes through untouched.
    """
    pairs = disabled_pairs(db)
    if not pairs:
        return query
    if hospital_id is not None:
        months = {m for (hid, m) in pairs if hid == hospital_id}
        if not months:
            return query
        return query.filter(~model.month.in_(months))
    condition = _disabled_condition(model, pairs)
    return query.filter(condition) if condition is not None else query


def disabled_month_months(db: Session, hospital_id: int) -> Set[str]:
    """Disabled months for one hospital (badge/metadata helpers)."""
    return {month for (hid, month) in disabled_pairs(db) if hid == hospital_id}


def include_disabled_requested(value) -> bool:
    """Parse the explicit historical-view flag (``include_disabled=true``)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def disabled_quality_scores(db: Session, hospital_id: Optional[int] = None,
                            month: Optional[str] = None) -> list:
    """Stored QualityScore rows that the active rule hides.

    Read-only inventory for audit/reporting. It NEVER deletes or rewrites the
    rows: a disabled month remains historical evidence and becomes visible
    again the moment the pair is re-enabled.
    """
    from sqlalchemy import and_, or_

    from app.models import Hospital, QualityScore

    pairs = disabled_pairs(db)
    if hospital_id is not None:
        pairs = {(hid, m) for (hid, m) in pairs if hid == hospital_id}
    if month is not None:
        pairs = {(hid, m) for (hid, m) in pairs if m == month}
    if not pairs:
        return []

    by_hosp: dict = {}
    for hid, m in pairs:
        by_hosp.setdefault(hid, set()).add(m)
    condition = or_(*[
        and_(QualityScore.hospital_id == hid, QualityScore.month.in_(months))
        for hid, months in by_hosp.items()
    ])
    rows = db.query(QualityScore).filter(condition).all()
    hospitals = {
        h.id: h.name for h in db.query(Hospital).filter(Hospital.id.in_(by_hosp))
    }
    out = [
        {
            "id": r.id,
            "hospital_id": r.hospital_id,
            "hospital": hospitals.get(r.hospital_id),
            "month": r.month,
            "score": r.score,
            "scoring_fingerprint": r.scoring_fingerprint,
        }
        for r in rows
    ]
    out.sort(key=lambda r: (r["hospital_id"], r["month"], r["id"]))
    return out


__all__ = [
    "MONTH_SETTINGS_PREFIX",
    "disabled_month_months",
    "disabled_pairs",
    "disabled_quality_scores",
    "exclude_disabled",
    "include_disabled_requested",
    "is_month_enabled",
    "month_disabled",
    "parse_month_setting",
]
