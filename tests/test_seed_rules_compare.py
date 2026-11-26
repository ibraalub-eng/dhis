"""The seed catalog stores the merged `compare` type, never a retired one.

A fresh database is created from ``scripts/seed_rules.py``, not from the
migration script. Seeding a retired comparison type would bring the nine old
shapes back into every new install and require a manual
``scripts/migrate_compare.py --apply`` right after setup, so the catalog itself
must carry ``compare`` with the normalized params.
"""

import json

from app.engine.quality.rules import (
    _LEGACY_COMPARE_BLUEPRINT,
    compare_params,
    normalize_compare_params,
)
from app.models import Rule
from scripts.seed_rules import RULES

RETIRED_TYPES = set(_LEGACY_COMPARE_BLUEPRINT)


def test_seed_catalog_has_no_retired_comparison_types():
    retired = [
        (r["code"], r["expression_type"])
        for r in RULES
        if r["expression_type"] in RETIRED_TYPES
    ]
    assert retired == []


def test_seed_catalog_keeps_its_comparison_rules():
    compare = [r for r in RULES if r["expression_type"] == "compare"]
    # R001–R040, R051–R071 are comparisons; guard against a bulk deletion
    # passing this file by accident.
    assert len(compare) >= 50
    codes = {r["code"] for r in compare}
    assert {"R001", "R008", "R061", "R069", "R070", "R071"} <= codes


def test_every_seeded_compare_rule_carries_readable_params():
    for rule in RULES:
        if rule["expression_type"] != "compare":
            continue
        params = json.loads(rule["params"])
        assert params.get("left") and params.get("right"), rule["code"]
        assert params.get("op") in {"=", "!=", ">", "<", ">=", "<="}, rule["code"]
        parsed = compare_params(params)
        assert parsed is not None, rule["code"]
        assert parsed["op"] == params["op"], rule["code"]


def test_seed_compare_rules_keep_their_retired_meaning():
    by_code = {r["code"]: r for r in RULES}

    # le: child <= parent
    assert json.loads(by_code["R008"]["params"]) == {
        "left": {"codes": ["5.b.1"], "agg": "single"},
        "right": {"codes": ["5"], "agg": "single"},
        "op": "<=",
    }
    # ge_factor: parent * factor >= sum(children)
    assert json.loads(by_code["R069"]["params"]) == {
        "left": {"codes": ["2"], "agg": "single"},
        "right": {"codes": ["6"], "agg": "sum"},
        "op": ">=",
        "factor": 1.05,
    }
    # gt / lt keep their strictness
    assert json.loads(by_code["R070"]["params"])["op"] == ">"
    assert json.loads(by_code["R071"]["params"])["op"] == "<"


def test_a_freshly_seeded_database_has_no_retired_comparison_types(db_session):
    rows = db_session.query(Rule).all()
    assert rows, "the db_session fixture seeds the rule catalog"

    retired = [r.code for r in rows if r.expression_type in RETIRED_TYPES]
    assert retired == []

    compare = [r for r in rows if r.expression_type == "compare"]
    assert len(compare) >= 50
    # Params in the database parse as compare without a legacy "legacy" key.
    for rule in compare:
        params = json.loads(rule.params)
        assert params.get("left") and params.get("right"), rule.code
        assert "legacy" not in params, rule.code


def test_seed_compare_entries_still_normalize_from_a_retired_alias():
    """The alias path stays valid for imported/exported old payloads, but the
    catalog no longer depends on it."""
    legacy_params = {"parent": "2", "children": ["3", "4", "5"]}
    assert normalize_compare_params("ge", legacy_params) is not None
