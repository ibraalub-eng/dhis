#!/usr/bin/env python3
"""Rebuild Data Groups from the clinical domains of the managed definitions.

The Data Group screen is backed by ``indicator_groups`` /
``indicator_group_members``. Those tables were introduced on 2026-09-28, so the
2026-09-22 production dump cannot restore them; after a database reset the
screen is empty and there is no backup to replay.

The indicator catalog does still know its clinical domains: every managed
``IndicatorDefinition`` carries a ``group_name`` (Delivery & Surgery, Maternal
Outcomes, Newborn Care, Newborn Outcomes, Risk Factors, System Rates) and the
raw data elements its formula depends on. This script recreates one group per
domain with those data elements as members.

Membership is exclusive by design (creating a group evicts its indicators from
any other group), so each data element is assigned to the first domain that
references it. The result is a derived reconstruction, not the user's original
selection.

Usage::

    python scripts/rebuild_indicator_groups.py
    python scripts/rebuild_indicator_groups.py --apply
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine
from app.models import Indicator, IndicatorDefinition, IndicatorGroup, IndicatorGroupMember

# Specific domains first: shared denominators (2 = deliveries, 6 = births)
# belong to the domain that reports them most directly.
DOMAIN_ORDER = [
    "Delivery & Surgery",
    "Maternal Outcomes",
    "Newborn Care",
    "Newborn Outcomes",
    "Risk Factors",
    "System Rates",
]

DOMAIN_DESCRIPTIONS = {
    "Delivery & Surgery": "Delivery volumes, caesarean section, assisted vaginal delivery and hysterectomy rates.",
    "Maternal Outcomes": "Maternal mortality and severe maternal morbidity rates and proportions.",
    "Newborn Care": "Newborn feeding and care indicators.",
    "Newborn Outcomes": "Preterm, low birth weight, stillbirth, neonatal mortality and NICU indicators.",
    "Risk Factors": "Adolescent and high-risk pregnancy indicators.",
    "System Rates": "Remaining system-level rates.",
}


def _ref_codes(definition: IndicatorDefinition) -> set[str]:
    refs: set[str] = set()
    if definition.expression:
        refs |= set(re.findall(r"\{([^}]+)\}", definition.expression))
    for attr in ("numerator_codes", "denominator_codes"):
        raw = getattr(definition, attr, None)
        if not raw:
            continue
        value = raw
        if isinstance(raw, str):
            try:
                value = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                value = [part.strip().strip("'\"") for part in raw.strip("[]").split(",")]
        if isinstance(value, (list, tuple)):
            refs |= {str(item).strip() for item in value if str(item).strip()}
    return refs


def build_assignments(session) -> "OrderedDict[str, list[int]]":
    catalog = {indicator.code: indicator.id for indicator in session.query(Indicator).all()}
    claimed: dict[int, str] = {}
    assignments: OrderedDict[str, list[int]] = OrderedDict((domain, []) for domain in DOMAIN_ORDER)

    by_domain: dict[str, list[IndicatorDefinition]] = {}
    for definition in session.query(IndicatorDefinition).order_by(IndicatorDefinition.code).all():
        by_domain.setdefault(definition.group_name or "System Rates", []).append(definition)

    # Walk the domains in priority order so a shared data element (e.g. "2"
    # deliveries) stays with the domain that reports it most directly.
    ordered = [domain for domain in DOMAIN_ORDER if domain in by_domain]
    ordered += sorted(domain for domain in by_domain if domain not in DOMAIN_ORDER)
    for domain in ordered:
        assignments.setdefault(domain, [])
        for definition in by_domain[domain]:
            for code in sorted(_ref_codes(definition)):
                indicator_id = catalog.get(code)
                if indicator_id is None or indicator_id in claimed:
                    continue
                claimed[indicator_id] = domain
                assignments[domain].append(indicator_id)

    return OrderedDict((domain, ids) for domain, ids in assignments.items() if ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Data Groups from clinical domains")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL (default is a dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        existing = session.query(IndicatorGroup).count()
        catalog = {indicator.id: indicator.code for indicator in session.query(Indicator).all()}
        assignments = build_assignments(session)

        print(f"Existing groups: {existing}")
        print(f"Groups to create: {len(assignments)}")
        for domain, ids in assignments.items():
            print(f"  {domain}: {len(ids)} members -> {', '.join(catalog[i] for i in ids)}")

        if not args.apply:
            print("\nDry run — re-run with --apply to write.")
            return 0
        if existing:
            print("Groups already exist; nothing to do (delete them first to rebuild).")
            return 0

        for domain, ids in assignments.items():
            group = IndicatorGroup(
                name=domain,
                description=DOMAIN_DESCRIPTIONS.get(domain),
                scope_type="all",
            )
            session.add(group)
            session.flush()
            for order, indicator_id in enumerate(ids):
                session.add(IndicatorGroupMember(
                    group_id=group.id,
                    indicator_id=indicator_id,
                    sort_order=order,
                ))
        session.commit()
        print(f"Created {len(assignments)} groups.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
