"""Tests for the read-only VERY_HIGH consistency audit.

The audit is the acceptance gate for a policy that is NOT wired into production,
so these tests protect two things at once:

* what the audit claims (identity, layer routing, unit checks, the four
  eligibility states, idempotency), and
* that reading a stored row through the audit changes nothing — the stored band
  stays on the row and the production read-time function still answers exactly
  what it answered before.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.anomaly.layered import (
    LEVEL_HIGH,
    LEVEL_MODERATE,
    LEVEL_NONE,
    LEVEL_VERY_HIGH,
    METHOD_IQR,
    METHOD_PCT_CHANGE,
    METHOD_PEER_ZSCORE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_ZSCORE,
    PEER_Z_THRESHOLD_DEFAULT,
    row_gate_threshold,
    row_layer_bands,
    row_level_assessment,
    very_high_eligibility,
)
from app.engine.canonical_identity import (
    identity_key,
    ratio_identity,
    stored_identity,
)
from app.engine.quality_alerts import alert_route, effective_severity

SCRIPT = (Path(__file__).resolve().parents[1]
          / "scripts" / "verify_very_high_consistency.py")


def _load_audit():
    """Import the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("verify_vh_consistency", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def _ctx() -> "audit.Context":
    return audit.Context(threshold=PEER_Z_THRESHOLD_DEFAULT,
                         threshold_source="test")


def _alert(*, severity=LEVEL_VERY_HIGH, perspective="history",
           method=METHOD_ROLLING_MEDIAN_MAD, history=(0.0, 1.0, 2.0, 1.0),
           current=9.0, peer_count=4, stats=None, threshold=None,
           code="10.i", formula=None, unit=None, alert_id=1):
    evidence = {
        "history": [[f"2026-0{i + 1}", value] for i, value in enumerate(history)],
        "stats": stats if stats is not None else {
            "mean": sum(history) / len(history) if history else None,
            "std": None, "median": None, "mad": None,
        },
        "peers": {},
    }
    if threshold is not None:
        evidence["z_threshold"] = threshold
    return SimpleNamespace(
        id=alert_id, hospital_id=7, month="2026-06", indicator_code=code,
        formula=formula, unit=unit, perspective=perspective, method=method,
        severity=severity, current_value=current, peer_count=peer_count,
        evidence=evidence,
    )


# A window whose own z at 9.0 is ~2.3 sigmas: the robust score saturates but
# the dispersion-aware score does not support the top band.
REFUSED_WINDOW = (0.0, 1.0, 2.0, 1.0, 8.0, 0.0)


def _row(*, stored=LEVEL_VERY_HIGH, method=METHOD_ROLLING_MEDIAN_MAD,
         history=(0.0, 1.0, 2.0, 1.0), current=9.0, rate=None,
         raw_value=None, scores=None, peers=None, peer_count=6,
         hist_std=None, zero_spread=(), thin=(), row_id=1,
         code="10.i", history_present=True, z_threshold=None):
    if raw_value is None:
        raw_value = current
    default_scores = {"raw": 1.0, "rate": None, "historical": 1.0,
                      "volume": None, "peer": None}
    default_scores.update(scores or {})
    provenance = None
    if zero_spread or thin or z_threshold is not None:
        provenance = {"zero_spread_layers": list(zero_spread),
                      "thin_peer_layers": list(thin)}
        if z_threshold is not None:
            provenance["zscore_threshold"] = z_threshold
    return SimpleNamespace(
        id=row_id, hospital_id=7, month="2026-06", analysis_code=code,
        outlier_level=stored, outlier_method=method,
        outlier_type="HISTORICAL_ANOMALY",
        raw_value=raw_value, rate=rate, peer_count=peer_count,
        peer_mean=(sum(peers) / len(peers)) if peers else None,
        raw_value_outlier_score=default_scores["raw"],
        rate_outlier_score=default_scores["rate"],
        historical_outlier_score=default_scores["historical"],
        volume_anomaly_score=default_scores["volume"],
        peer_outlier_score=default_scores["peer"],
        historical_std=hist_std,
        history_provenance=({"values": list(history)} if history_present
                            else None),
        peer_provenance=({"values": dict(enumerate(peers))} if peers else None),
        classification_provenance=provenance,
    )


# ── Identity ──────────────────────────────────────────────────────────────

def test_two_codes_with_one_formula_are_one_identity():
    """Registered-under-another-code is the same event, not two."""
    ctx = _ctx()
    left = _alert(code="sys_clinical_rate_cs", formula="{5} / {2} * 100",
                  unit="%", history=(), current=5.0)
    right = _alert(code="cs_rate", formula="{5} / {2} * 100",
                   unit="percent", history=(), current=5.0, alert_id=2)
    assert ctx.identity_for_alert(left) == ctx.identity_for_alert(right)


def test_different_perspectives_keep_one_identity():
    """A finding's perspectives are rows of ONE event, not separate events."""
    ctx = _ctx()
    history = _alert(perspective="history")
    peer = _alert(perspective="type", method=METHOD_PEER_ZSCORE, history=())
    assert ctx.identity_for_alert(history) == ctx.identity_for_alert(peer)
    # ... and the audit folds them by that identity, keeping the max band.
    views = [audit._alert_view(history, ctx), audit._alert_view(peer, ctx)]
    folded = audit._fold(views, "final_band")
    assert len(folded) == 1
    assert len(next(iter(folded.values()))) == 2


def test_a_raw_data_element_is_its_own_identity():
    ctx = _ctx()
    assert ctx.identity_for_alert(_alert(code="10.i")) == identity_key(
        stored_identity(None, None, "10.i"))


def test_a_row_without_a_current_spec_falls_back_and_says_so():
    ctx = _ctx()
    row = _row(code="deleted_code")
    key, resolved = ctx.identity_for_row(row)
    assert resolved is False
    assert key == identity_key(stored_identity(None, None, "deleted_code"))


def test_a_rate_row_identity_is_its_formula_not_its_code():
    ctx = _ctx()
    ctx.specs = {"rate_cs": SimpleNamespace(
        analysis_code="rate_cs", is_rate=True,
        numerator_codes=("5",), denominator_codes=("2",),
        rate_multiplier=100.0, unit="%")}
    key, resolved = ctx.identity_for_row(_row(code="rate_cs"))
    assert resolved is True
    assert key == identity_key(ratio_identity(("5",), ("2",), "/", 100.0,
                                              "%"))


# ── Layer routing ─────────────────────────────────────────────────────────

def test_history_layer_route_is_gated():
    ctx = _ctx()
    view = audit._layered_view(_row(current=9.0), ctx)
    assert view["route"] == audit.ROUTE_HISTORY
    assert view["decision"] in (audit.DEC_ELIGIBLE, audit.DEC_INELIGIBLE)


def test_a_peer_layer_that_holds_the_top_band_is_undecided_and_kept():
    """No equivalent peer rule exists for this gate: preserve, do not invent."""
    ctx = _ctx()
    row = _row(scores={"historical": 0.2, "raw": 0.2, "peer": 1.0},
               peers=[0.0, 1.0, 2.0, 1.0, 3.0, 4.0])
    view = audit._layered_view(row, ctx)
    assert view["route"] == audit.ROUTE_PEER
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["final_band"] == LEVEL_VERY_HIGH
    assert view["reason"] == audit.REASON_PEER_POLICY


def test_a_volume_layer_that_holds_the_top_band_is_undecided():
    """A denominator percentage change has no dispersion divisor to ask."""
    ctx = _ctx()
    row = _row(scores={"historical": 0.2, "raw": 0.2, "volume": 1.0})
    view = audit._layered_view(row, ctx)
    assert view["route"] == audit.ROUTE_VOLUME
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["final_band"] == LEVEL_VERY_HIGH


def test_a_zero_spread_peer_layer_does_not_block_the_history_gate():
    """The approved cap already refused the peer claim: it is not a holder.

    This is the defect the first audit had: it compared the peer layer's RAW
    score (1.0 from a 0/0 comparison) and declared the row ungated, so seven
    identities read HIGH on alerts and VERY_HIGH on Diagnostics.
    """
    ctx = _ctx()
    row = _row(scores={"historical": 1.0, "raw": 1.0, "peer": 1.0},
               peers=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
               history=REFUSED_WINDOW, current=9.0)
    view = audit._layered_view(row, ctx)
    assert "peer" not in view["top_layers"]
    assert view["route"] == audit.ROUTE_HISTORY
    assert view["decision"] == audit.DEC_INELIGIBLE
    assert view["final_band"] == LEVEL_HIGH


# ── Production routing and threshold resolution ──────────────────────────

@pytest.mark.parametrize("perspective,method", [
    ("history", METHOD_ZSCORE),
    ("history", METHOD_ROLLING_MEDIAN_MAD),
    ("type", METHOD_PEER_ZSCORE),
    ("ownership", METHOD_PEER_ZSCORE),
    ("all", METHOD_ZSCORE),
    (None, METHOD_PEER_ZSCORE),
    (None, METHOD_ZSCORE),
])
def test_the_audit_route_is_the_production_route(perspective, method):
    """The audit must ask production WHICH rule judges a row.

    A legacy row with no perspective is routed by its METHOD (a peer z is a
    peer comparison, anything else is the hospital's own window). Deriving the
    route from ``perspective == "history"`` reads those rows as peer claims.
    """
    ctx = _ctx()
    alert = _alert(perspective=perspective, method=method, history=())
    assert audit._alert_view(alert, ctx)["route"] == alert_route(perspective,
                                                                 method)


def test_a_legacy_row_with_no_perspective_is_still_gated():
    """The old rule left it undecided; production gates its history window."""
    ctx = _ctx()
    view = audit._alert_view(
        _alert(perspective=None, method=METHOD_ROLLING_MEDIAN_MAD), ctx)
    assert view["route"] == audit.ROUTE_HISTORY
    assert view["decision"] in (audit.DEC_ELIGIBLE, audit.DEC_INELIGIBLE)


def test_a_legacy_alert_is_judged_at_the_saved_default_not_the_live_setting():
    """Substituting today's configured value would judge a legacy row with a
    threshold the scan that wrote it never used."""
    ctx = _ctx()
    ctx.threshold = 4.0                      # what an operator set LATER
    view = audit._alert_view(_alert(perspective="history", threshold=None),
                             ctx)
    assert view["threshold"] == PEER_Z_THRESHOLD_DEFAULT


def test_a_stored_alert_threshold_wins_over_the_live_setting():
    ctx = _ctx()
    ctx.threshold = 4.0
    view = audit._alert_view(_alert(perspective="history", threshold=3.5), ctx)
    assert view["threshold"] == 3.5


def test_a_legacy_diagnostics_row_uses_the_saved_default():
    ctx = _ctx()
    ctx.threshold = 4.0
    view = audit._layered_view(_row(z_threshold=None), ctx)
    assert view["threshold"] == PEER_Z_THRESHOLD_DEFAULT


def test_a_stored_diagnostics_threshold_is_the_production_resolution():
    ctx = _ctx()
    ctx.threshold = 4.0
    row = _row(z_threshold=3.5)
    view = audit._layered_view(row, ctx)
    assert view["threshold"] == row_gate_threshold(row) == 3.5


def test_the_audit_route_constants_are_the_production_ones():
    assert audit.ROUTE_HISTORY == alert_route("history", METHOD_ZSCORE)
    assert audit.ROUTE_PEER == alert_route("type", METHOD_PEER_ZSCORE)


# ── Units ─────────────────────────────────────────────────────────────────

def test_raw_count_on_a_rate_analysis_is_a_unit_mismatch_and_undecided():
    ctx = _ctx()
    row = _row(rate=49.7, raw_value=9.0, current=49.7,
               scores={"raw": 1.0, "rate": None, "historical": 0.1})
    view = audit._layered_view(row, ctx)
    assert view["unit_compatible"] is False
    assert view["route"] == audit.ROUTE_RAW_UNIT
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["final_band"] == LEVEL_VERY_HIGH
    assert view["reason"] == audit.REASON_RAW_UNIT


def test_a_rate_window_is_judged_with_the_rate_value():
    ctx = _ctx()
    row = _row(rate=49.7, raw_value=9.0, current=49.7,
               scores={"raw": 1.0, "rate": 1.0, "historical": 1.0},
               history=(0.0, 0.0, 5.0, 6.0))
    view = audit._layered_view(row, ctx)
    assert view["unit_value"] == "rate"
    assert view["current"] == 49.7
    assert view["route"] == audit.ROUTE_HISTORY


def test_the_audit_grades_the_value_the_alert_grades():
    """The alert stores the rate for a rate indicator; the row must too."""
    rate_row = _row(rate=49.7, raw_value=9.0, current=49.7)
    alert = _alert(current=49.7, history=(0.0, 0.0, 5.0, 6.0))
    assert audit._close(alert.current_value, audit._layered_view(
        rate_row, _ctx())["current"]) is True
    wrong = _alert(current=9.0, history=(0.0, 0.0, 5.0, 6.0), alert_id=2)
    assert audit._close(wrong.current_value, audit._layered_view(
        rate_row, _ctx())["current"]) is False


# ── Missing evidence and the four states ──────────────────────────────────

def test_a_missing_current_value_is_undecided_not_ineligible():
    ctx = _ctx()
    view = audit._alert_view(_alert(history=(0.0, 1.0, 2.0, 1.0)), ctx,
                            current_override=None)
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["reason"] == audit.REASON_NO_CURRENT
    assert view["final_band"] == LEVEL_VERY_HIGH
    assert "current_value" in view["missing"]


def test_a_missing_history_window_is_undecided_not_normal():
    ctx = _ctx()
    view = audit._alert_view(_alert(history=()), ctx)
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["reason"] == audit.REASON_NO_WINDOW
    assert view["final_band"] == LEVEL_VERY_HIGH


def test_a_band_below_very_high_is_not_applicable_not_eligible():
    ctx = _ctx()
    view = audit._alert_view(_alert(severity=LEVEL_HIGH), ctx)
    assert view["decision"] == audit.DEC_NOT_APPLICABLE
    assert view["reason"] == audit.REASON_CAPPED


def test_a_legacy_peer_row_without_stored_evidence_is_not_a_pass():
    """A peer row written before the group was stored keeps its old answer.

    Nothing is inferred from today's hospital values: with no stored group the
    production reader itself answers ``undecided`` / ``PEER_POLICY``, and the
    audit reports that, not an invented verdict.
    """
    ctx = _ctx()
    view = audit._alert_view(_alert(perspective="ownership",
                                    method=METHOD_PEER_ZSCORE, history=()),
                             ctx)
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["reason"] == "PEER_POLICY"
    assert view["assessment"]["applicable"] is False
    assert view["assessment"]["eligible"] is None
    assert view["peer_values_n"] == 0
    assert "peer_values" in view["provenance_absent"]


def test_decision_mapping_keeps_null_apart():
    assert audit._decision({"applicable": False, "eligible": None}) == \
        audit.DEC_NOT_APPLICABLE
    assert audit._decision({"applicable": True, "eligible": None}) == \
        audit.DEC_UNDECIDED
    assert audit._decision({"applicable": True, "eligible": True}) == \
        audit.DEC_ELIGIBLE
    assert audit._decision({"applicable": True, "eligible": False}) == \
        audit.DEC_INELIGIBLE


# ── Idempotency and the top-band-only rule ────────────────────────────────

def test_reapplying_the_gate_changes_nothing():
    window = [0.0, 1.0, 2.0, 1.0]
    first = very_high_eligibility(LEVEL_VERY_HIGH, window, 9.0,
                                  PEER_Z_THRESHOLD_DEFAULT)["final_band"]
    second = very_high_eligibility(first, window, 9.0,
                                   PEER_Z_THRESHOLD_DEFAULT)["final_band"]
    assert first == second


def test_a_refused_top_band_falls_to_high_never_lower():
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, list(REFUSED_WINDOW),
                                    9.0, PEER_Z_THRESHOLD_DEFAULT)
    assert verdict["eligible"] is False
    assert verdict["final_band"] == LEVEL_HIGH


def test_a_band_below_the_top_is_returned_untouched():
    for band in (LEVEL_HIGH, LEVEL_MODERATE, LEVEL_NONE):
        verdict = very_high_eligibility(band, [0.0, 1.0, 2.0, 1.0], 9.0,
                                        PEER_Z_THRESHOLD_DEFAULT)
        assert verdict["applicable"] is False
        assert verdict["final_band"] == band


# ── Cross-screen agreement and production parity ──────────────────────────

def test_the_same_window_and_value_decide_the_same_on_both_sides():
    ctx = _ctx()
    window = REFUSED_WINDOW
    alert = audit._alert_view(_alert(history=window, current=9.0), ctx)
    row = audit._layered_view(_row(history=window, current=9.0), ctx)
    assert audit._same_window(alert["window"], row["window"]) is True
    assert alert["decision"] == row["decision"] == audit.DEC_INELIGIBLE


def test_the_audit_per_layer_bands_match_the_production_reader():
    """One implementation of the caps: reading the row must agree."""
    row = _row(stored=LEVEL_VERY_HIGH,
               scores={"historical": 1.0, "raw": 1.0, "peer": 1.0},
               peers=[0.0, 0.0, 0.0, 0.0, 0.0], peer_count=5)
    bands, _lowered_zero, _lowered_thin = row_layer_bands(row)
    production, _provenance = row_level_assessment(row)
    assert audit.LEVEL_RANK[production] == max(
        audit.LEVEL_RANK[b] for b in bands.values() if b is not None)


def test_reading_a_row_never_mutates_its_stored_band():
    ctx = _ctx()
    row = _row(stored=LEVEL_VERY_HIGH, current=9.0,
               scores={"historical": 1.0, "raw": 1.0})
    alert = _alert()
    before = (row.outlier_level, alert.severity, row.raw_value_outlier_score)
    audit._layered_view(row, ctx)
    audit._alert_view(alert, ctx)
    assert (row.outlier_level, alert.severity,
            row.raw_value_outlier_score) == before


def test_production_effective_severity_still_lowers_a_zero_spread_peer():
    """Regression: the stored-band cap is unchanged by this work."""
    band = effective_severity(
        LEVEL_VERY_HIGH,
        stats={"mean": 0.0, "std": 0.0},
        method=METHOD_PEER_ZSCORE, peer_count=9, series=[])
    assert band == LEVEL_HIGH


def test_production_reader_untouched_for_a_measured_history_row():
    row = _row(stored=LEVEL_VERY_HIGH, current=9.0,
               scores={"historical": 1.0, "raw": 1.0})
    assert row_level_assessment(row)[0] == LEVEL_VERY_HIGH


@pytest.mark.parametrize("method", [METHOD_ROLLING_MEDIAN_MAD, METHOD_IQR,
                                    METHOD_PCT_CHANGE])
def test_an_unmeasurable_window_never_becomes_a_refusal(method):
    """No window, or a current value alone, is 'unknown', not 'ineligible'."""
    verdict = very_high_eligibility(LEVEL_VERY_HIGH, [], 9.0,
                                    PEER_Z_THRESHOLD_DEFAULT)
    assert verdict["eligible"] is None
    assert verdict["final_band"] == LEVEL_VERY_HIGH
    assert method  # the rule is the same for every method, not just robust


# ── Peer eligibility: the audit ASKS production, it does not re-decide ────
# The peer group the scan stores is the only input these tests use; the
# expected verdicts come from the production reader, so a second copy of the
# policy inside the audit would fail here.

PEER_GROUP = {101: 10.0, 102: 12.0, 103: 14.0,
              104: 16.0, 105: 18.0, 106: 20.0}


def _peer_alert(*, values=PEER_GROUP, current=100.0, peer_count=6,
                code="10.i", perspective="ownership", formula=None):
    alert = _alert(perspective=perspective, method=METHOD_PEER_ZSCORE,
                   history=(), current=current, peer_count=peer_count,
                   code=code, formula=formula)
    if values is not None:
        alert.evidence["comparison_policy"] = {
            "peer": {"values": dict(values)}}
    return alert


def _production_peer_view(alert, ctx):
    """The production answer for the same alert and the same inputs."""
    from app.engine.quality_alerts import (
        eligibility_assessment,
        peer_gate_inputs,
        stored_threshold,
    )

    return eligibility_assessment(
        alert.severity, stats=alert.evidence.get("stats"), method=alert.method,
        peer_count=alert.peer_count, series=[], current=alert.current_value,
        perspective=alert.perspective,
        threshold=stored_threshold(alert.evidence),
        **peer_gate_inputs(alert, set(ctx.specs)))


def test_a_peer_alert_with_stored_evidence_takes_the_production_rule_b():
    ctx = _ctx()
    ctx.specs = {"10.i": object()}          # the build_analysis_specs resolver
    view = audit._alert_view(_peer_alert(), ctx)
    assert view["route"] == audit.ROUTE_PEER
    assert view["decision"] == audit.DEC_ELIGIBLE
    assert view["reason"] == "BOTH_SCALES_SUPPORT"
    # The verdict is a THIRD dimension: no band may move.
    assert view["stored_band"] == view["base_band"] == view["final_band"]
    assert view["production_band"] == LEVEL_VERY_HIGH
    assert view["peer_values_n"] == len(PEER_GROUP)
    assert view["definition_status"] == "catalog_only"
    assert view["group_comparability_status"] == "not_verified"


@pytest.mark.parametrize("values,current,decision", [
    (PEER_GROUP, 100.0, "eligible"),
    (PEER_GROUP, 15.0, "ineligible"),
    ({101: 5.0, 102: 5.0, 103: 5.0, 104: 5.0}, 100.0,
     "insufficient_robust_scale"),
    ({101: 10.0, 102: 12.0, 103: 14.0}, 100.0, "not_applicable"),
])
def test_the_audit_and_production_agree_on_the_same_peer_evidence(
        values, current, decision):
    ctx = _ctx()
    ctx.specs = {"10.i": object()}
    alert = _peer_alert(values=values, current=current,
                        peer_count=max(len(values), 4))
    view = audit._alert_view(alert, ctx)
    production = _production_peer_view(alert, ctx)
    assert view["decision"] == production["decision"] == decision
    assert view["reason"] == production["reason"]
    assert view["final_band"] == production["final_band"] == LEVEL_VERY_HIGH


def test_a_history_alert_ignores_stored_peer_evidence():
    """The peer policy must never grade a hospital's own window."""
    ctx = _ctx()
    ctx.specs = {"10.i": object()}
    alert = _alert(perspective="history", history=REFUSED_WINDOW, current=9.0)
    alert.evidence["comparison_policy"] = {"peer": {"values": dict(PEER_GROUP)}}
    view = audit._alert_view(alert, ctx)
    assert view["route"] == audit.ROUTE_HISTORY
    assert view["reason"] not in (audit.REASON_PEER_POLICY,
                                  "BOTH_SCALES_SUPPORT",
                                  "DEFINITION_NOT_ESTABLISHABLE")
    assert view["decision"] == audit.DEC_INELIGIBLE
    assert view["final_band"] == LEVEL_HIGH      # the HISTORY gate refused it


def test_a_synthetic_forecast_definition_is_not_established():
    """``build_analysis_specs`` does not analyse it, so nothing can resolve it."""
    ctx = _ctx()
    ctx.specs = {"10.i": object()}
    alert = _peer_alert(code="sys_forecast_adolescent", formula="trend")
    view = audit._alert_view(alert, ctx)
    assert view["decision"] == audit.DEC_UNDECIDED
    assert view["reason"] == "DEFINITION_NOT_ESTABLISHABLE"
    assert view["definition_status"] == "not_establishable"
    assert view["final_band"] == LEVEL_VERY_HIGH


def test_a_thin_peer_group_is_owned_by_the_approved_cap():
    """Fewer than 4 stored members: not_applicable, and never 'refused'."""
    ctx = _ctx()
    ctx.specs = {"10.i": object()}
    view = audit._alert_view(
        _peer_alert(values={101: 10.0, 102: 12.0, 103: 14.0},
                    peer_count=4), ctx)
    assert view["decision"] == audit.DEC_NOT_APPLICABLE
    assert view["reason"] == "THIN_PEER_GROUP"
    assert view["final_band"] == LEVEL_VERY_HIGH


def test_a_degenerate_peer_group_is_insufficient_robust_scale():
    """MAD = IQR = 0 is its own state, never folded into ``undecided``."""
    ctx = _ctx()
    ctx.specs = {"10.i": object()}
    view = audit._alert_view(
        _peer_alert(values={101: 5.0, 102: 5.0, 103: 5.0, 104: 5.0},
                    peer_count=4), ctx)
    assert view["decision"] == audit.DEC_INSUFFICIENT
    assert view["decision"] != audit.DEC_UNDECIDED
    assert view["reason"] == "NO_ROBUST_SCALE"
    assert view["final_band"] == LEVEL_VERY_HIGH
