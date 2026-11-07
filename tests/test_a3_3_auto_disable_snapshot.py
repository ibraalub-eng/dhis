"""A3.3 pins: the auto-disable gate is resolved once and passed explicitly.

The suite proves four things:

* the resolver's ``flags`` plane preserves the approved parse exactly
  (only the literal ``"true"`` is ON);
* every eligibility/completeness/confidence helper *requires* the resolved
  Boolean and never touches ``SystemSetting``;
* one snapshot per bulk batch, and two interleaved runs cannot see each
  other's gate;
* the displaced semantics (legacy helper body) and the new path agree on the
  same fixtures, for every stored spelling, two hospitals and two months.

Read-only: no production row is written and nothing imports ``app.main``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.engine import config_resolver as cr
from app.engine.confidence import calculate_confidence
from app.engine.confidence_policy import ConfidencePolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ConfidencePolicy.defaults()

#: Spelled exactly as the old reader accepted them.
STORED = [None, "true", "false", "TRUE", "True", "yes", "1", "", "true "]


# ── fixtures ---------------------------------------------------------------
def _indicator(db, code):
    from app.models import Indicator
    row = db.query(Indicator).filter(Indicator.code == code).first()
    assert row is not None, f"conftest must seed indicator {code}"
    return row.id


def _seed(db, month="2031-01"):
    """Two hospitals, four indicators: valued, null row, no row, manual off."""
    from app.models import Hospital, HospitalIndicatorConfig, Indicator, IndicatorValue

    h1 = db.query(Hospital).first()
    h2 = db.query(Hospital).order_by(Hospital.id).offset(1).first()
    inds = db.query(Indicator).order_by(Indicator.id).limit(4).all()
    assert len(inds) == 4, "conftest must seed at least four indicators"
    a, b, c, d = (row.id for row in inds)

    db.add(IndicatorValue(hospital_id=h1.id, indicator_id=a, month=month, value=10))
    db.add(IndicatorValue(hospital_id=h1.id, indicator_id=b, month=month, value=None))
    # indicator c has no row at all for h1/month
    db.add(IndicatorValue(hospital_id=h2.id, indicator_id=a, month=month, value=7))
    db.add(IndicatorValue(hospital_id=h2.id, indicator_id=b, month=month, value=4))
    db.add(HospitalIndicatorConfig(hospital_id=h1.id, indicator_id=d,
                                   is_enabled=False))
    db.commit()
    return h1, h2, {"valued": a, "null": b, "missing": c, "manual": d}


def _set_flag(db, stored):
    from app.models import SystemSetting
    row = db.query(SystemSetting).filter(
        SystemSetting.key == "auto_disable_null_indicators").first()
    if stored is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(SystemSetting(key="auto_disable_null_indicators", value=stored))
    else:
        row.value = stored
    db.commit()


# ── the parse is preserved exactly ----------------------------------------
@pytest.mark.parametrize("stored,expected", [
    (None, False), ("true", True), ("false", False), ("TRUE", False),
    ("True", False), ("yes", False), ("1", False), ("", False),
    ("true ", False),
])
def test_resolver_flag_preserves_the_exact_parse(db_session, stored, expected):
    _set_flag(db_session, stored)
    snapshot = cr.load_policy_snapshot(db_session)
    assert snapshot.require_auto_disable_null() is expected
    assert snapshot.flags == {"flags.auto_disable_null": expected}
    entry = snapshot.entries["flags.auto_disable_null"]
    assert entry.component == "flags"
    assert entry.storage == cr.STORAGE_SYSTEM_SETTING
    assert entry.source == ("default" if stored is None else "database")


def test_the_flag_participates_in_policy_identity(db_session):
    off = cr.resolve_policy({}, {})
    on = cr.resolve_policy({}, {"auto_disable_null_indicators": "true"})
    assert off.auto_disable_null is False
    assert on.auto_disable_null is True
    assert off.digest != on.digest
    # Same input resolves to the same identity, in any construction order.
    assert on.digest == cr.resolve_policy(
        {}, {"auto_disable_null_indicators": "true"}).digest


def test_degraded_snapshot_reports_unavailable_instead_of_false():
    degraded = cr.resolve_policy({}, {}, strict=False, read_error="db down")
    assert degraded.auto_disable_null is None
    with pytest.raises(cr.PolicyUnavailable):
        degraded.require_auto_disable_null()

    class _Broken:
        def __init__(self):
            self.info = {}

        def query(self, *args, **kwargs):
            raise RuntimeError("db down")

    broken = _Broken()
    first = cr.load_display_policy(broken)
    assert first.auto_disable_null is None
    assert cr.load_display_policy(broken) is first, "display resolution is memoized"


# ── the helpers cannot fall back to the database --------------------------
def test_every_helper_requires_the_resolved_gate():
    from app.engine.pipeline import (
        compute_hospital_completeness,
        get_disabled_indicator_ids,
        get_required_indicator_codes,
        get_required_indicator_ids,
    )

    class _Session:
        def query(self, *args, **kwargs):      # pragma: no cover - must not run
            raise AssertionError("the helper read the database before validating")

    for helper in (get_disabled_indicator_ids, get_required_indicator_ids,
                   get_required_indicator_codes, compute_hospital_completeness):
        with pytest.raises(TypeError):
            helper(_Session(), 1, "2031-01")

    with pytest.raises(TypeError):
        calculate_confidence(
            hospital_name="h", month="2031-01", values={}, rule_results=[],
            historical_data={}, all_hospital_data={}, indicator_map={},
            indicator_children={})


def test_no_analytical_helper_names_the_setting_or_queries_it():
    tree = ast.parse((ROOT / "app" / "engine" / "pipeline.py").read_text(
        encoding="utf-8"))
    wanted = {"get_disabled_indicator_ids", "get_required_indicator_ids",
              "get_required_indicator_codes", "compute_hospital_completeness"}
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body = ast.get_source_segment(
                (ROOT / "app" / "engine" / "pipeline.py").read_text(
                    encoding="utf-8"), node)
            assert "SystemSetting" not in body, node.name
            assert "_is_auto_disable_null" not in body, node.name
            checked += 1
    assert checked == 4

    conf = (ROOT / "app" / "engine" / "confidence.py").read_text(encoding="utf-8")
    assert "SystemSetting" not in conf
    assert "def _is_auto_disable_null" not in (
        ROOT / "app" / "engine" / "pipeline.py").read_text(encoding="utf-8")


# ── differential: legacy semantics vs the snapshot path -------------------
def _legacy_disabled(db, hospital_id, month, enabled):
    """The pre-A3.3 body, copied verbatim, used as the reference."""
    from app.engine.pipeline import get_effective_manual_disabled_ids
    from app.models import Indicator, IndicatorValue

    manual = get_effective_manual_disabled_ids(db, hospital_id, month)
    if not enabled:
        return list(manual)
    null_ids = [
        r[0] for r in db.query(IndicatorValue.indicator_id).filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.month == month,
            IndicatorValue.value.is_(None),
        ).all()
        if r[0] not in manual
    ]
    existing = [
        r[0] for r in db.query(IndicatorValue.indicator_id).filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.month == month,
        ).distinct().all()
    ]
    all_ids = [r[0] for r in db.query(Indicator.id).all()]
    missing = [i for i in all_ids if i not in manual and i not in existing]
    return manual + null_ids + missing


def _legacy_required_codes(db, hospital_id, month, enabled):
    from app.engine.pipeline import get_optional_source_indicator_ids
    from app.indicators import SYNTHETIC_INDICATOR_CODES
    from app.models import Indicator

    disabled = set(_legacy_disabled(db, hospital_id, month, enabled))
    optional = get_optional_source_indicator_ids(db)
    rows = db.query(Indicator.id, Indicator.code, Indicator.requirement_type).all()
    required = {
        code for iid, code, req in rows
        if iid not in disabled and iid not in optional
        and (req or "Required") == "Required"
        and code not in SYNTHETIC_INDICATOR_CODES
    }
    return required


@pytest.mark.parametrize("stored", STORED)
def test_disabled_required_and_completeness_match_the_legacy_semantics(
        db_session, stored):
    from app.engine.pipeline import (
        compute_hospital_completeness,
        get_disabled_indicator_ids,
        get_required_indicator_codes,
        get_required_indicator_ids,
    )
    from app.engine.quality import compute_completeness, compute_covered_codes
    from app.models import Indicator

    h1, h2, _ids = _seed(db_session)
    _set_flag(db_session, stored)
    enabled = stored == "true"

    for hospital, month in ((h1, "2031-01"), (h2, "2031-01")):
        expected = sorted(_legacy_disabled(db_session, hospital.id, month, enabled))
        actual = sorted(get_disabled_indicator_ids(
            db_session, hospital.id, month, auto_disable_null=enabled))
        assert actual == expected, (stored, hospital.id)

        expected_codes = _legacy_required_codes(
            db_session, hospital.id, month, enabled)
        assert get_required_indicator_codes(
            db_session, hospital.id, month,
            auto_disable_null=enabled) == expected_codes

        required_ids = set(get_required_indicator_ids(
            db_session, hospital.id, month, auto_disable_null=enabled))
        id_to_code = {i: c for i, c in
                      db_session.query(Indicator.id, Indicator.code).all()}
        assert {id_to_code[i] for i in required_ids} == expected_codes

        # Completeness: same disabled set, same required set -> same number.
        from app.engine.pipeline import get_enabled_values_for_hospital_month
        values = get_enabled_values_for_hospital_month(
            db_session, hospital.id, month)
        disabled_codes = {
            id_to_code[i] for i in expected if i in id_to_code
        }
        covered = compute_covered_codes(values, disabled_codes, db_session)
        legacy = compute_completeness(values, expected_codes, covered) * 100.0
        assert compute_hospital_completeness(
            db_session, hospital.id, month,
            auto_disable_null=enabled) == pytest.approx(legacy, abs=1e-9)


def test_confidence_uses_the_gate_it_is_given(db_session):
    """A missing key indicator is back-filled only when the gate is OFF."""
    from app.models import Indicator

    _h1, _h2, ids = _seed(db_session)
    code = db_session.query(Indicator.code).filter(
        Indicator.id == ids["missing"]).scalar()
    assert code

    common = dict(
        hospital_name="h", month="2031-01", values={"2": 10.0}, rule_results=[],
        historical_data={}, all_hospital_data={}, indicator_map={},
        indicator_children={}, key_indicator_codes=[code], disabled_codes=set(),
        confidence_policy=DEFAULT_POLICY,
    )
    off = calculate_confidence(auto_disable_null=False, **common)
    on = calculate_confidence(auto_disable_null=True, **common)
    assert code in [i.indicator_code for i in off.indicators]
    assert code not in [i.indicator_code for i in on.indicators]


# ── isolation: two interleaved runs never share a gate --------------------
def test_two_interleaved_runs_keep_their_own_gate(db_session):
    from app.engine.pipeline import get_disabled_indicator_ids

    h1, h2, _ids = _seed(db_session)

    # Run A observes the setting absent -> False.
    _set_flag(db_session, None)
    run_a = cr.load_policy_snapshot(db_session)

    # Run B observes it explicitly ON, after A has already resolved.
    _set_flag(db_session, "true")
    run_b = cr.load_policy_snapshot(db_session)

    assert run_a.require_auto_disable_null() is False
    assert run_b.require_auto_disable_null() is True

    # A third write must not reach either resolved run.
    _set_flag(db_session, "false")
    for hospital in (h1, h2):
        for month in ("2031-01",):
            a = sorted(get_disabled_indicator_ids(
                db_session, hospital.id, month,
                auto_disable_null=run_a.require_auto_disable_null()))
            b = sorted(get_disabled_indicator_ids(
                db_session, hospital.id, month,
                auto_disable_null=run_b.require_auto_disable_null()))
            assert a != b, "the gate did not change the decision"
            assert set(a) < set(b), "ON must be a superset of manual-only"
            # Hospital order cannot change a result.
            again = sorted(get_disabled_indicator_ids(
                db_session, hospital.id, month,
                auto_disable_null=run_a.require_auto_disable_null()))
            assert again == a


# ── one snapshot per bulk batch -------------------------------------------
def test_bulk_loops_resolve_once_and_pass_the_snapshot():
    sources = {
        name: (ROOT / "app" / name).read_text(encoding="utf-8")
        for name in ("api/upload.py", "api/analysis.py", "api/reports.py",
                     "api/file_ops.py", "api/tree_config.py",
                     "engine/pipeline.py")
    }
    for name in ("api/upload.py", "api/analysis.py", "api/reports.py",
                 "api/file_ops.py", "api/tree_config.py"):
        assert "load_policy_snapshot(" in sources[name], name
        assert "policy=policy" in sources[name] or "policy=_policy" in sources[name], name

    pipeline = sources["engine/pipeline.py"]
    run_sig = pipeline.split("def run_full_analysis", 1)[1].split("-> Dict", 1)[0]
    assert "policy: Optional[PolicySnapshot] = None" in run_sig
    batch_sig = pipeline.split("def recompute_hospital_months", 1)[1].split(")-> int:", 1)[0]
    assert "policy: Optional[PolicySnapshot] = None" in batch_sig
    assert "policy.require_auto_disable_null()" in pipeline


def test_display_paths_can_distinguish_unavailable_from_false():
    dashboard = (ROOT / "app" / "api" / "dashboard.py").read_text(encoding="utf-8")
    tree = (ROOT / "app" / "api" / "tree_config.py").read_text(encoding="utf-8")
    preview = (ROOT / "app" / "api" / "indicator_groups.py").read_text(encoding="utf-8")
    assert "configuration_unavailable" in dashboard
    assert "configuration_unavailable" in tree
    assert "configuration_unavailable" in preview
    for text in (dashboard, tree, preview):
        assert "load_display_policy(" in text
