"""Optional by inheritance: a Required parent whose sources are all Optional.

Doctrine (docs/COVERAGE-DISABLE-DOCTRINE.md §1.4): a parent total is only as
required as the elements it is built from. When every child of a node is
Optional — or is itself optional by inheritance — the form never asks the
hospital to fill it, so the node's absence must not be counted in the
completeness denominator nor reported as "has no value for this month" by the
Why popup, the Audit screen or the dashboard diagnostics.

Reported case: indicator 17 (Neonatal deaths, marked Required) and 17.c
(Required, two Optional children) were listed as missing data in the outlier
score/quality popups even though every element behind them is Optional.

The rule lives in ONE place — pipeline.get_optional_source_indicator_ids —
and every surface reads it. A Required LEAF keeps its flag (14, a data
element with no sources, stays required).
"""
import pytest

from app.engine.audit.data_auditor import get_data_audit
from app.engine.audit.explain import find_data_problems
from app.engine.pipeline import (
    compute_hospital_completeness,
    get_optional_source_indicator_ids,
    get_required_indicator_codes,
    get_required_indicator_ids,
)
from app.models import Hospital, Indicator, IndicatorValue

MONTH = "2027-05"


def _ind(db_session, code, name, requirement="Required", parent=None):
    ind = Indicator(code=code, name=name, requirement_type=requirement,
                    parent=parent)
    db_session.add(ind)
    db_session.flush()
    return ind


@pytest.fixture()
def optional_tree(db_session):
    """A Required parent whose every source is Optional, next to controls.

    T_p  (Required) ── T_p.a (Optional)
        └──────────── T_p.b (Optional)
    T_mixed (Required) ── T_mixed.a (Optional), T_mixed.b (Required)
    T_leaf (Required leaf — no sources, must stay required)
    """
    parent = _ind(db_session, "T_p", "All-optional parent")
    _ind(db_session, "T_p.a", "Optional child A", "Optional", parent)
    _ind(db_session, "T_p.b", "Optional child B", "Optional", parent)

    mixed = _ind(db_session, "T_mixed", "Mixed parent")
    _ind(db_session, "T_mixed.a", "Mixed optional child", "Optional", mixed)
    _ind(db_session, "T_mixed.b", "Mixed required child", "Required", mixed)

    _ind(db_session, "T_leaf", "Required leaf")
    db_session.commit()
    return parent


def test_parent_with_all_optional_children_is_optional_by_inheritance(
        db_session, optional_tree):
    optional_ids = get_optional_source_indicator_ids(db_session)
    by_code = {i.code: i.id for i in db_session.query(Indicator).all()}

    assert by_code["T_p"] in optional_ids, (
        "every source data element of T_p is Optional — the form never asks "
        "for it, so it must not be treated as required"
    )
    assert by_code["T_mixed"] not in optional_ids, (
        "one Required child keeps the parent required"
    )
    assert by_code["T_leaf"] not in optional_ids, (
        "a Required leaf has no source elements and keeps its own flag"
    )


def test_seeded_neonatal_tree_reports_the_reported_case(db_session):
    """17 / 17.c are optional by inheritance when their subtree is Optional;
    14 (a Required leaf) stays required."""
    inds = {i.code: i for i in db_session.query(Indicator).all()}
    if not {"17", "17.c", "14"} <= set(inds):
        pytest.skip("seeded indicator tree unavailable")

    inds["17"].requirement_type = "Required"
    inds["17.c"].requirement_type = "Required"
    inds["14"].requirement_type = "Required"
    for child in db_session.query(Indicator).filter(Indicator.parent_id == inds["17"].id):
        if child.code != "17.c":
            child.requirement_type = "Optional"
    for child in db_session.query(Indicator).filter(Indicator.parent_id == inds["17.c"].id):
        child.requirement_type = "Optional"
    db_session.commit()

    optional_ids = get_optional_source_indicator_ids(db_session)
    assert inds["17.c"].id in optional_ids, "both children of 17.c are Optional"
    assert inds["17"].id in optional_ids, (
        "17's remaining Required child is itself optional by inheritance"
    )
    assert inds["14"].id not in optional_ids, "14 is a required data element"


def test_required_codes_exclude_the_inherited_optional(db_session, optional_tree):
    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    required = get_required_indicator_codes(db_session, hosp.id, MONTH)
    assert "T_p" not in required
    assert "T_mixed" in required
    assert "T_leaf" in required

    required_ids = set(get_required_indicator_ids(db_session, hosp.id, MONTH))
    assert optional_tree.id not in required_ids


def test_completeness_denominator_ignores_the_inherited_optional(
        db_session, optional_tree, monkeypatch):
    """The gate is wired into the completeness denominator: switching it off
    re-admits exactly T_p (and only T_p) to the required set."""
    import app.engine.pipeline as pipeline

    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    by_code = {i.code: i for i in db_session.query(Indicator).all()}
    db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                  indicator_id=by_code["T_p"].id, value=None))
    db_session.commit()

    codes = get_required_indicator_codes(db_session, hosp.id, MONTH)
    assert "T_p" not in codes and "T_leaf" in codes
    gated = set(get_required_indicator_ids(db_session, hosp.id, MONTH))

    monkeypatch.setattr(pipeline, "get_optional_source_indicator_ids",
                        lambda session: set())
    ungated = set(pipeline.get_required_indicator_ids(db_session, hosp.id, MONTH))

    assert ungated - gated == {optional_tree.id}, (
        "only the inherited-optional parent may re-enter the denominator"
    )
    # The score composes through the same helper, so the two cannot drift.
    assert compute_hospital_completeness(db_session, hosp.id, MONTH) >= 0.0


def test_why_popup_does_not_flag_the_inherited_optional(db_session, optional_tree):
    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    by_code = {i.code: i for i in db_session.query(Indicator).all()}
    for code in ("T_p", "T_p.a", "T_p.b", "T_leaf"):
        db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                      indicator_id=by_code[code].id, value=None))
    db_session.commit()

    from app.engine.audit.explain import _raw_values
    values = _raw_values(db_session, hosp.id, MONTH)
    flagged = {p["indicator_code"] for p in find_data_problems(values, db_session)
               if p["kind"] == "missing_value"}
    assert "T_p" not in flagged and "T_p.a" not in flagged
    assert flagged == {"T_leaf"}, "only the genuinely required leaf is a gap"


def test_audit_screen_calls_it_optional_not_missing(db_session, optional_tree):
    hosp = db_session.query(Hospital).order_by(Hospital.id).first()
    by_code = {i.code: i for i in db_session.query(Indicator).all()}
    db_session.add(IndicatorValue(hospital_id=hosp.id, month=MONTH,
                                  indicator_id=by_code["T_p"].id, value=None))
    db_session.commit()

    audit = get_data_audit(db_session, hosp.id, MONTH)
    rows = {r["indicator_code"]: r["status"]
            for r in audit["completeness"]["indicators"]}
    assert rows["T_p"] == "optional", (
        "the Audit screen must not call an inherited-optional node 'missing'"
    )
    assert rows["T_leaf"] == "missing", (
        "a genuinely required leaf with no value stays a real gap"
    )
    missing_codes = {r["indicator_code"]
                     for r in audit["completeness"]["indicators"]
                     if r["status"] == "missing"}
    assert "T_p" not in missing_codes


# ── Visibility: the Data Tree and the indicator catalog say WHY ────────────
# A node whose own flag says 'Required' while it is skipped by the
# completeness denominator used to look identical to a genuinely required
# one. Both screens now carry optional_by_inheritance and mark it distinctly.

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _walk_by_code(node, out):
    out[node.get("code")] = node
    for child in node.get("children") or []:
        _walk_by_code(child, out)


def test_tree_marks_the_inherited_optional(client, db_session, optional_tree):
    resp = client.get("/hospitals/indicator-tree/default?month=2026-01")
    assert resp.status_code == 200, resp.text

    found = {}
    for root in resp.json()["children"]:
        _walk_by_code(root, found)

    assert found["T_p"]["requirement_type"] == "Required"
    assert found["T_p"]["optional_by_inheritance"] is True, (
        "the tree must say the Required parent is not counted as required"
    )
    assert found["T_mixed"]["optional_by_inheritance"] is False, (
        "one Required child keeps the parent genuinely required"
    )
    assert found["T_leaf"]["optional_by_inheritance"] is False, (
        "a Required leaf has no sources to inherit optionality from"
    )
    assert found["T_p.a"]["optional_by_inheritance"] is False, (
        "an explicitly Optional element needs no inheritance explanation"
    )


def test_catalog_and_raw_detail_mark_the_inherited_optional(
        client, db_session, optional_tree):
    items = {i["code"]: i for i in client.get("/indicators").json()["items"]}
    assert items["T_p"]["requirement_type"] == "Required"
    assert items["T_p"]["optional_by_inheritance"] is True
    assert items["T_mixed"]["optional_by_inheritance"] is False

    detail = client.get("/indicators/raw/T_p").json()
    assert detail["requirement_type"] == "Required"
    assert detail["optional_by_inheritance"] is True
    kids = {c["code"]: c for c in detail["children"]}
    assert kids["T_p.a"]["requirement_type"] == "Optional", (
        "the drawer names the sources that make the parent optional"
    )

    mixed = client.get("/indicators/raw/T_mixed").json()
    assert mixed["optional_by_inheritance"] is False


def test_both_screens_render_the_inherited_state_distinctly():
    from pathlib import Path

    static = Path(__file__).resolve().parent.parent / "static"
    tree_js = (static / "js" / "tree.js").read_text(encoding="utf-8")
    ind_js = (static / "js" / "indicators.js").read_text(encoding="utf-8")
    i18n = (static / "js" / "i18n.js").read_text(encoding="utf-8")
    css = (static / "css" / "styles.css").read_text(encoding="utf-8")

    # Data Tree: a third chip state, not a plain "Req".
    assert "node.optional_by_inheritance" in tree_js
    assert "__('Optional (inherited)')" in tree_js
    assert "' inh'" in tree_js
    assert "_refreshInheritance" in tree_js

    # Indicators catalog + raw drawer mirror the same state.
    assert "it.optional_by_inheritance" in ind_js
    assert "d.optional_by_inheritance" in ind_js
    assert "_reqBadge" in ind_js

    assert "'Optional (inherited)':" in i18n
    assert ".tree-req-chip.inh" in css
    assert ".ind-req-chip.inh" in css
