# -*- coding: utf-8 -*-
"""Indicator code "0" ("Main elements complete ratio") is a SYNTHETIC
form-header label, not a data indicator: it is never reported by any hospital
file, has no IndicatorValue rows, and exists only because the SRMNH sheet
header was seeded like an indicator.

It must therefore be invisible in the Indicator Tree UI — showing it made
users think a real indicator was missing. Engine guards (rule details,
completeness counting, audit rows, upload template) already skip it via
SYNTHETIC_INDICATOR_CODES; this file locks the tree/flat-list views.
"""
import pytest
from fastapi.testclient import TestClient

from app.indicators import (
    SYNTHETIC_INDICATOR_CODES,
    build_tree_from_db,
    get_flat_list_from_db,
)


def test_synthetic_constant_unchanged():
    assert SYNTHETIC_INDICATOR_CODES == {"0"}


def test_rare_real_indicators_are_NOT_hidden():
    """The 2026-09 audit found 8 more indicators with zero value rows — but
    they are REAL rarely-occurring indicators (deaths, referrals, ICU…):
    in-tree, rule-referenced (R004/R073/R048…), some with per-hospital
    configs. They must NEVER join SYNTHETIC_INDICATOR_CODES — hiding them
    would hide real upload gaps. If you believe one is synthetic, it must
    satisfy ALL four criteria in docs/COVERAGE-DISABLE-DOCTRINE.md §8 and
    this test updated deliberately."""
    rare_real = {"2.k", "2.l", "11.a", "11.b", "12", "16", "21", "26"}
    hidden = rare_real & SYNTHETIC_INDICATOR_CODES
    assert not hidden, (
        f"rare-but-real indicators must not be hidden from the tree: {hidden}"
    )


def test_db_tree_hides_synthetic_label(db_session):
    tree = build_tree_from_db(db_session)

    def _codes(nodes):
        out = set()
        for n in nodes or []:
            out.add(str(n["id"]))
            out |= _codes(n.get("children"))
        return out

    codes = _codes(tree.get("children"))
    assert "0" not in codes, "synthetic label must not render as a tree node"
    assert "2" in codes, "real indicators must still render"


def test_flat_list_hides_synthetic_label(db_session):
    flat = get_flat_list_from_db(db_session)
    codes = {str(item["code"]) for item in flat}
    assert "0" not in codes
    assert "2" in codes


def test_tree_endpoints_hide_synthetic_label(app, db_session):
    client = TestClient(app)
    for url in (
        "/hospitals/indicator-tree/manage",
        "/hospitals/indicator-tree/default?month=__all__",
        "/hospitals/1/indicator-tree?month=__all__",
    ):
        resp = client.get(url)
        assert resp.status_code == 200, url

        def _codes(nodes):
            out = set()
            for n in nodes or []:
                out.add(str(n.get("code")))
                out |= _codes(n.get("children"))
            return out

        body = resp.json()
        codes = _codes(body.get("children"))
        assert "0" not in codes, f"code 0 leaked through {url}"
        assert "2" in codes, f"real indicators missing from {url}"
