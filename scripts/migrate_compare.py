#!/usr/bin/env python3
"""Migrate the nine comparison types to the merged `compare` type.

``ge``, ``gt``, ``ge_factor``, ``eq``, ``le``, ``lt``, ``le_sum``,
``parent_le`` and ``parent_lt`` are one comparison with one policy now. The old
names keep working as aliases in the engine, but a stored rule should carry the
merged type so the Rules Manager, the API and exports show one shape:

    {"left": {"codes": ["2"], "agg": "single"},
     "right": {"codes": ["3", "4", "5"], "agg": "sum"},
     "op": ">=", "factor": 1.05}

Only the roles, the operator and the optional factor change:
``normalize_compare_params`` translates each legacy rule, so tolerance, missing
data and the 0/0 exemption stay the shared comparison policy rather than
per-rule settings. Rules whose params cannot name both sides are reported and
left untouched.

Before anything is written, the script evaluates every rule against every month
it has computed results for, once with its stored legacy definition and once
with the converted ``compare`` definition, over the active hospitals, and
reports the two status tallies side by side. A status difference means the two
paths disagree, so ``--apply`` refuses to write and prints the hospitals that
changed.

Usage::

    python scripts/migrate_compare.py            # report only (default)
    python scripts/migrate_compare.py --apply    # write the conversion

Safe to re-run: after ``--apply`` no stored rule carries a legacy type, so a
second run finds nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Rule names carry symbols such as "≈"; the Windows console defaults to a
# legacy code page that cannot encode them, so never let a report crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.database import SessionLocal
from app.engine.pipeline import (
    get_all_hospital_data_for_month,
    get_disabled_indicator_ids,
    get_enabled_values_for_hospital_month,
    get_historical_months,
)
from app.engine.quality import ValidationContext, dispatch_rule
from app.engine.quality.rules import (
    _LEGACY_COMPARE_BLUEPRINT,
    compare_params,
    normalize_compare_params,
)
from app.models import Hospital, Indicator, Rule, ValidationResult

LEGACY_TYPES = tuple(_LEGACY_COMPARE_BLUEPRINT)
NO_DATA = "NO_DATA"

STATUSES = ("PASS", "FAIL", NO_DATA)


@dataclass
class Conversion:
    """One legacy rule paired with the `compare` rule it becomes."""

    rule: Rule
    old_type: str
    old_params: dict
    new_params: dict

    @property
    def code(self) -> str:
        return self.rule.code


def collect(session) -> List[Conversion]:
    """Return every legacy comparison rule that converts cleanly.

    Rules whose params cannot name both sides are printed and skipped rather
    than converted into a comparison that would pass vacuously.
    """
    rows = (
        session.query(Rule)
        .filter(Rule.expression_type.in_(LEGACY_TYPES))
        .order_by(Rule.code)
        .all()
    )
    conversions: List[Conversion] = []
    for rule in rows:
        params = rule.params
        if isinstance(params, str):
            try:
                params = json.loads(params or "{}")
            except ValueError:
                params = {}
        params = params or {}
        normalized = normalize_compare_params(rule.expression_type, params)
        if normalized is None:
            print(f"  skip {rule.code}: {rule.expression_type} params cannot name both sides")
            continue
        if compare_params(normalized) is None:
            print(f"  skip {rule.code}: {rule.expression_type} produced unreadable compare params")
            continue
        conversions.append(Conversion(rule, rule.expression_type, params, normalized))
    return conversions


def apply_conversion(session, conversions: List[Conversion]) -> None:
    """Write the merged type and params for the given conversions."""
    for item in conversions:
        item.rule.expression_type = "compare"
        item.rule.params = json.dumps(item.new_params, ensure_ascii=False)
    if conversions:
        session.commit()


def _contexts(session, months: List[str]):
    """Build one validation context per hospital/month, shared by all rules."""
    from app.engine.config_resolver import load_display_policy
    from app.engine.policy_view import rules_policy_from_snapshot

    display = load_display_policy(session)
    policy = rules_policy_from_snapshot(display)
    auto_disable_null = display.require_auto_disable_null()
    hospitals = (
        session.query(Hospital)
        .filter(Hospital.is_active.is_(True))
        .order_by(Hospital.name)
        .all()
    )
    contexts: Dict[Tuple[str, int], Optional[ValidationContext]] = {}
    for month in months:
        all_data = get_all_hospital_data_for_month(session, month) or {}
        for hospital in hospitals:
            values = get_enabled_values_for_hospital_month(session, hospital.id, month)
            if not values:
                contexts[(month, hospital.id)] = None
                continue
            historical = get_historical_months(session, hospital.id, month)
            disabled_ids = get_disabled_indicator_ids(
                session, hospital.id, month, auto_disable_null=auto_disable_null,
            )
            disabled_codes = set()
            if disabled_ids:
                disabled_codes = {
                    row.code
                    for row in session.query(Indicator).filter(Indicator.id.in_(disabled_ids)).all()
                }
            contexts[(month, hospital.id)] = ValidationContext(
                values=values,
                hospital_name=hospital.name,
                month=month,
                all_hospital_data=all_data,
                historical_data=historical or {},
                disabled_codes=disabled_codes,
                rules=policy,
            )
    return hospitals, contexts


def _status(rule: Rule, expr: str, params, ctx: Optional[ValidationContext]) -> str:
    """One rule's status for one hospital/month, as the Rules Manager sees it."""
    if ctx is None:
        return NO_DATA
    probe = SimpleNamespace(
        code=rule.code,
        name=rule.name,
        rule_type=rule.rule_type,
        severity=rule.severity,
        expression_type=expr,
        params=params if isinstance(params, str) else json.dumps(params, ensure_ascii=False),
    )
    result = dispatch_rule(probe, ctx)
    if result is None:
        return NO_DATA
    return getattr(result.status, "value", str(result.status))


@dataclass
class MonthResult:
    month: str
    before: Counter
    after: Counter
    changed: List[Tuple[str, str, str]]  # (hospital, before_status, after_status)


def _months_by_rule(session, codes: List[str]) -> Dict[str, List[str]]:
    rows = (
        session.query(ValidationResult.rule_code, ValidationResult.month)
        .filter(ValidationResult.rule_code.in_(codes))
        .distinct()
        .all()
    )
    months: Dict[str, set] = {}
    for code, month in rows:
        if month:
            months.setdefault(code, set()).add(month)
    return {code: sorted(values) for code, values in months.items()}


def report(session, conversions: List[Conversion]) -> Tuple[List[MonthResult], int, int]:
    """Evaluate every rule/month before and after conversion.

    Returns ``(results, evaluations, differences)``. The contexts are shared,
    so the cost is one context build per hospital/month plus two evaluations per
    rule/month/hospital.
    """
    months_by_rule = _months_by_rule(session, [item.code for item in conversions])
    all_months = sorted({month for values in months_by_rule.values() for month in values})
    hospitals, contexts = _contexts(session, all_months)

    results: List[MonthResult] = []
    evaluations = 0
    differences = 0
    for item in conversions:
        rule = item.rule
        months = months_by_rule.get(item.code, [])
        print(f"\n{rule.code}  {rule.name}  [{item.old_type} -> compare]")
        print(f"  params: {json.dumps(item.new_params, ensure_ascii=False)}")
        if not months:
            print("  no computed months in validation_results")
            continue
        for month in months:
            before: Counter = Counter()
            after: Counter = Counter()
            changed: List[Tuple[str, str, str]] = []
            for hospital in hospitals:
                ctx = contexts.get((month, hospital.id))
                old_status = _status(rule, item.old_type, item.old_params, ctx)
                new_status = _status(rule, "compare", item.new_params, ctx)
                evaluations += 2
                before[old_status] += 1
                after[new_status] += 1
                if old_status != new_status:
                    changed.append((hospital.name, old_status, new_status))
            differences += len(changed)
            results.append(MonthResult(month, before, after, changed))
            print(f"  {month}: " + _tally("before", before) + " | " + _tally("after", after)
                  + (" | changed: none" if not changed else f" | changed: {len(changed)}"))
            for name, old_status, new_status in changed:
                print(f"      {name}: {old_status} -> {new_status}")
    return results, evaluations, differences


def _tally(label: str, counts: Counter) -> str:
    parts = [f"{status} {counts.get(status, 0)}" for status in STATUSES]
    return f"{label} " + " ".join(parts)


def _summary(results: List[MonthResult], evaluations: int, differences: int) -> None:
    before: Counter = Counter()
    after: Counter = Counter()
    for item in results:
        before.update(item.before)
        after.update(item.after)
    print("\nSummary")
    print(f"  rule-months: {len(results)}")
    print(f"  hospital evaluations: {evaluations} ({evaluations // 2} per definition)")
    print(f"  {_tally('before', before)}")
    print(f"  {_tally('after', after)}")
    print(f"  status differences: {differences}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the conversion (default: report only)")
    args = parser.parse_args()

    with SessionLocal() as session:
        conversions = collect(session)
        print(f"{len(conversions)} legacy comparison rule(s) can convert to compare.")
        if not conversions:
            print("Nothing to migrate.")
            return 0
        for item in conversions:
            print(f"  {item.code}: {item.old_type} -> compare")
        _results, evaluations, differences = report(session, conversions)
        _summary(_results, evaluations, differences)

        if differences:
            print("\nThe legacy and compare definitions disagree on at least one hospital;"
                  " nothing was written. Inspect the hospitals listed above.")
            return 1

        if args.apply:
            apply_conversion(session, conversions)
            print(f"\nmigrated {len(conversions)} rule(s) to compare.")
        else:
            print(f"\n{len(conversions)} rule(s) would migrate. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
