"""A3.5 P0 — golden-master parity for the configuration-sensitive engines.

The baseline lives in ``tests/fixtures/a3_5_golden_master.json`` and is
regenerated only deliberately (``A3_5_WRITE_GOLDEN=1``). It records the
effective resolved settings for each case alongside the outputs, so a diff
shows both what changed and which configuration produced it.

P0 must pass before P1 is accepted: Rules snapshot integration must not move
any of these numbers.
"""
from __future__ import annotations

import json
import os

from tests.a3_5_golden import FIXTURE, capture_all, capture_case, dump, seed


def test_golden_master_matches(db_session):
    actual = capture_all(db_session)
    if os.environ.get("A3_5_WRITE_GOLDEN") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(dump(actual), encoding="utf-8")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert actual["default"]["settings"] != actual["stored"]["settings"]
    assert actual["partial"]["settings"]["rules.eq_tolerance"] == 10.0
    assert actual["partial"]["settings"]["rules.month_over_factor"] == 2.0
    assert actual == expected


def test_default_case_is_order_independent(db_session):
    """A stored case between two default runs must not change the second run.

    This is the pipeline-level leakage detector: process globals may hold the
    previous case's values, but every run must resolve its own settings.
    """
    hospitals = seed(db_session)
    first = capture_case(db_session, "default", hospitals)
    capture_case(db_session, "stored", hospitals)
    again = capture_case(db_session, "default", hospitals)
    assert again == first
