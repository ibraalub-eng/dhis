#!/usr/bin/env python3
"""Migrate the four indicator-value check types to the merged `value_check`.

``neg_check``, ``decimal_check``, ``missing`` and ``all_zero`` all ask a
question about indicator *values* rather than about how indicators relate, and
are now one type. The old names keep working as aliases in the engine, but a
stored rule should carry the merged type so the Rules Manager shows one shape:

    {"checks": [{"kind": "negative", "codes": ["2", "3"]}]}

Every check keeps its legacy meaning and message: a single-check rule evaluates
exactly as it did, including the intrinsic severity of ``decimal`` (LOW) and
``all_zero`` (CRITICAL). Rules whose params cannot name a code are reported and
left untouched rather than silently converted.

Usage::

    python scripts/migrate_value_check.py            # report only
    python scripts/migrate_value_check.py --apply    # write the conversion

Safe to re-run: after --apply no rule carries a legacy type, so a second run
finds nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.engine.quality.rules import (
    _LEGACY_VALUE_CHECK_TYPES,
    normalize_value_check_params,
)
from app.models import Rule

LEGACY_TYPES = tuple(_LEGACY_VALUE_CHECK_TYPES)


def migrate_rules(session, apply: bool = False) -> list:
    """Convert every legacy value-check rule.

    Returns ``[(code, old_type, new_params), …]`` for the rules that convert
    (or would convert, when ``apply`` is false). Rules without usable codes are
    printed and skipped.
    """
    converted = []
    rows = (
        session.query(Rule)
        .filter(Rule.expression_type.in_(LEGACY_TYPES))
        .order_by(Rule.code)
        .all()
    )
    for rule in rows:
        params = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
        normalized = normalize_value_check_params(rule.expression_type, params)
        if normalized is None:
            print(f"  skip {rule.code}: {rule.expression_type} names no indicator code")
            continue
        converted.append((rule.code, rule.expression_type, normalized))
        if apply:
            rule.expression_type = "value_check"
            rule.params = json.dumps(normalized, ensure_ascii=False)
    if apply and converted:
        session.commit()
    return converted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the conversion (default: report only)")
    args = parser.parse_args()

    with SessionLocal() as session:
        converted = migrate_rules(session, apply=args.apply)

    for code, old_type, _params in converted:
        print(f"  {code}: {old_type} -> value_check")
    verb = "migrated" if args.apply else "would migrate"
    print(f"{len(converted)} rule(s) {verb}.")
    if converted and not args.apply:
        print("Re-run with --apply to write the conversion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
