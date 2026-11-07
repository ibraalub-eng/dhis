"""P3.3.0 — frozen legacy Confidence parity fixture.

The fixture is generated only with ``A3_5_WRITE_CONFIDENCE_LEGACY=1``. Normal
test runs compare the current engine output with the captured pre-P3.3 data and
never rewrite it.
"""
from __future__ import annotations

import json
import os

from tests.a3_5_confidence_legacy import FIXTURE, capture, dump


def test_legacy_confidence_parity_fixture_matches(db_session):
    actual = capture(db_session)
    if os.environ.get("A3_5_WRITE_CONFIDENCE_LEGACY") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(dump(actual), encoding="utf-8")

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert actual == expected
    assert actual["fixture_version"] == "1"
    assert set(actual["results"]) == set(actual["policies"])
    assert all(
        set(results) == set(actual["scenarios"])
        for results in actual["results"].values()
    )


def test_legacy_fixture_covers_required_matrix():
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    policies = expected["policies"]
    defaults = {"rule_compliance": 0.55, "historical": 0.10,
                "cross_hospital": 0.10, "trend": 0.10, "completeness": 0.15}
    assert any(p["weights"] == defaults and not p["weights_row"]
               for p in policies.values())
    assert any(all(value == 0.2 for value in p["weights"].values())
               and p["weights_row"] for p in policies.values())
    assert any(p["cutoffs"]["confidence_high"] == 80.0
               and not p["cutoffs_row"] for p in policies.values())
    assert any(p["cutoffs"]["confidence_high"] == 95.0
               and p["cutoffs_row"] for p in policies.values())
    assert any(p["zscore_threshold"] == 2.5 and not p["zscore_row"]
               for p in policies.values())
    assert any(p["zscore_threshold"] == 99.0 and p["zscore_row"]
               for p in policies.values())
    assert set(expected["scenarios"]) == {
        "present", "missing", "multi", "rule_failure",
        "history_outlier", "cross_outlier",
    }
