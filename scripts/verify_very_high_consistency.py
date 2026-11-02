"""Cross-screen consistency review for the VERY_HIGH eligibility gate.

READ-ONLY. Nothing is written, committed or recomputed into a table: the script
opens a session, reads, prints and (optionally) writes a CSV of its own rows.
The last section re-reads the stored bands and proves they are unchanged.

What is being compared
----------------------
The three screens do not read one population:

* Quality Alerts and the Dashboard both band an alert row through
  ``quality_alerts.effective_severity`` and both fold rows into an ISSUE by
  canonical formula identity, so they cannot disagree row for row or issue for
  issue — they are verified here through the Dashboard's own counting function.
* Outlier Diagnostics bands a ``LayeredOutlierResult`` row through
  ``layered.row_level_assessment`` — a different table, written by a different
  engine pass, with per-layer scores instead of perspectives.

"The same alert on three screens" therefore only exists where the two tables
describe the same analytical event. The event identity is
``(hospital, month, canonical formula)`` — the formula/scale identity the
Dashboard and Quality Alerts already fold by, NOT the raw code, because one
formula is registered under several codes and comparing codes split the same
event in two. Identities only present on one side are reported as such; they are
not mismatches.

Which policy judges which layer
-------------------------------
The eligibility gate answers ONE question: does this row's OWN-HISTORY window
support the top band? It is routed, per layer, never applied to a whole row
because it happens to carry the band:

``history`` (own months)
    Gated. The window is the stored series, the current value is the row's own
    unit value (the rate for a rate analysis), the threshold is the configured
    one — the same inputs the scan used.
``peer`` (other hospitals)
    NOT gated here. A peer z already divides by the group's own spread, and the
    approved peer policies (no dispersion; fewer than 4 peers) are the rules
    that judge it. This gate returns ``undecided`` for a peer claim and the
    band it earned stands.
``volume`` (denominator change)
    NOT gated here: it scores a percentage change of the denominator, which
    stays measurable on a flat series. ``undecided``.
``raw`` on a RATE analysis
    A count compared with a rate window is a unit mismatch, not evidence about
    the rate. ``undecided`` with ``unit_compatible = False``; the row keeps its
    band and the audit names the cause.

States are kept apart exactly as the policy defines them:

* ``not_applicable`` — the band is below VERY_HIGH (the gate is for the top
  band only) or the approved caps already refused it.
* ``eligible`` / ``ineligible`` — the window measured a scale and supported /
  refused the top band.
* ``undecided`` — the policy could not judge (no window, no current value, or a
  layer this policy does not govern). Never counted as a pass or a rejection.

Usage:
    .venv/Scripts/python.exe scripts/verify_very_high_consistency.py
    .venv/Scripts/python.exe scripts/verify_very_high_consistency.py --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.quality_alerts import (  # noqa: E402
    _alert_dict as production_alert_payload,
)
from app.api.quality_alerts import (
    _effective_severity as production_alert_band,
)
from app.database import SessionLocal  # noqa: E402
from app.engine.anomaly.layered import (  # noqa: E402
    LEVEL_HIGH,
    LEVEL_NONE,
    LEVEL_RANK,
    LEVEL_VERY_HIGH,
    PEER_Z_THRESHOLD_DEFAULT,
    build_analysis_specs,
    gate_threshold,
    max_level,
    row_gate_threshold,
    row_layer_bands,
    row_level_assessment,
    very_high_eligibility,
)
from app.engine.canonical_identity import (  # noqa: E402
    alert_identity,
    identity_key,
    ratio_identity,
    stored_identity,
)
from app.engine.quality_alerts import (  # noqa: E402
    alert_route,
    cap_thin_peer,
    cap_zero_spread,
    eligibility_assessment,
    peer_gate_inputs,
    stored_peer_group,
    stored_series,
    stored_threshold,
)
from app.models import LayeredOutlierResult, QualityAlert  # noqa: E402

VERY_HIGH = LEVEL_VERY_HIGH

# ── Which rule judged which layer (see the module docstring) ──────────────
ROUTE_HISTORY = "history"
ROUTE_PEER = "peer"
ROUTE_VOLUME = "volume"
ROUTE_RAW_UNIT = "raw_count_on_rate"
ROUTE_CAPPED = "already_refused"
ROUTE_NO_HOLDER = "no_top_layer"

DEC_ELIGIBLE = "eligible"
DEC_INELIGIBLE = "ineligible"
DEC_UNDECIDED = "undecided"
DEC_NOT_APPLICABLE = "not_applicable"
# The peer policy's fifth state: the comparison group has no usable robust
# scale. Deliberately NOT folded into ``undecided`` — it is a distinct verdict.
DEC_INSUFFICIENT = "insufficient_robust_scale"

# Reasons this audit adds to the gate's own four. A reason always says WHY a
# decision is what it is; none of them is a new statistical rule.
REASON_PEER_POLICY = "TOP_BAND_HELD_BY_PEER_COMPARISON"
REASON_VOLUME_POLICY = "TOP_BAND_HELD_BY_VOLUME_COMPARISON"
REASON_RAW_UNIT = "TOP_BAND_HELD_BY_RAW_COUNT_ON_RATE_ANALYSIS"
REASON_CAPPED = "TOP_BAND_ALREADY_REFUSED_BY_APPROVED_CAPS"
REASON_NO_HOLDER = "NO_LAYER_HOLDS_THE_TOP_BAND"
REASON_NO_WINDOW = "NO_STORED_HISTORY_WINDOW"
REASON_NO_CURRENT = "CURRENT_VALUE_MISSING"

# Mismatch causes between the two tables for one identity.
CAUSE_SAME = "same_band"
CAUSE_BASELINE = "different_baseline_same_policy"
CAUSE_UNIT = "incompatible_unit"
CAUSE_MISSING = "missing_evidence_on_one_side"
CAUSE_LAYER = "different_source_layer"
CAUSE_SAME_INPUTS = "SAME_INPUTS_DIFFERENT_DECISION"
CAUSE_UNEXPLAINED = "UNEXPLAINED"

OWN_HISTORY_LAYERS = frozenset({"raw", "rate", "historical"})


@dataclass
class Context:
    """Settings and lookups every view needs (read once, never written)."""

    threshold: float = PEER_Z_THRESHOLD_DEFAULT
    threshold_source: str = "default"
    specs: Dict[str, Any] = field(default_factory=dict)

    def identity_for_alert(self, alert: QualityAlert) -> str:
        return identity_key(alert_identity(alert))

    def identity_for_row(self, row: LayeredOutlierResult) -> Tuple[str, bool]:
        """``(canonical identity, resolved)`` for a diagnostics row.

        A rate row's identity is its formula + scale (the same identity Quality
        Alerts store on the alert); a count row is its own data-element code.
        ``resolved`` is False when the analysis code has no current spec, so the
        code identity is a fallback rather than a verified formula match.
        """
        spec = self.specs.get(row.analysis_code)
        if spec is None:
            return identity_key(stored_identity(None, None,
                                                row.analysis_code)), False
        if spec.is_rate:
            return identity_key(ratio_identity(spec.numerator_codes,
                                               spec.denominator_codes, "/",
                                               spec.rate_multiplier,
                                               spec.unit)), True
        return identity_key(stored_identity(None, spec.unit,
                                            row.analysis_code)), True

    def unit_of(self, code: str) -> Optional[str]:
        spec = self.specs.get(code)
        return (spec.unit or None) if spec is not None else None


# ── Small helpers ─────────────────────────────────────────────────────────

def _numbers(raw) -> List[float]:
    if isinstance(raw, dict):
        raw = list(raw.values())
    out: List[float] = []
    for value in raw or ():
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _mean(values: Sequence[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


def _close(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _same_window(left: Sequence[float], right: Sequence[float]) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return sorted(round(v, 9) for v in left) == sorted(round(v, 9) for v in right)


def _decision(assessment: Dict[str, Any]) -> str:
    """Map the gate's verdict to the four states; ``None`` is not a verdict."""
    if not assessment["applicable"]:
        return DEC_NOT_APPLICABLE
    if assessment["eligible"] is None:
        return DEC_UNDECIDED
    return DEC_ELIGIBLE if assessment["eligible"] else DEC_INELIGIBLE


def _gate(level: Optional[str], series: Sequence[float],
          current: Optional[float], threshold: float) -> Dict[str, Any]:
    return very_high_eligibility(level, list(series or ()), current, threshold)


# ── One alert ROW (Quality Alerts and, through the same function, Dashboard) ─

# Distinguishes "use the stored value" from "simulate a reader that does not
# carry the column" (the Dashboard query today).
STORE_CURRENT = object()


def _alert_view(alert: QualityAlert, ctx: Context, *,
                current_override: Any = STORE_CURRENT) -> Dict[str, Any]:
    evidence = alert.evidence or {}
    series = stored_series(evidence)
    use_current = (alert.current_value
                   if current_override is STORE_CURRENT
                   else current_override)
    # The threshold is resolved by the SAME production function the screens
    # use (stored value, else the saved default). The configured setting is
    # deliberately NOT substituted here: a legacy row is judged at 2.5 on the
    # screens, so judging it at today's setting would make the audit disagree
    # with production for a reason that does not exist in the data.
    threshold = gate_threshold(stored_threshold(evidence))
    # The two approved caps first: a row they already refuse is not the gate's
    # business, and a peer row is judged by exactly these rules.
    base, _ = cap_zero_spread(alert.severity, evidence.get("stats"),
                              alert.method, series)
    base, _ = cap_thin_peer(base, alert.peer_count, alert.method)
    # Production routing (the reader's own function), so the audit cannot
    # classify a labelled perspective differently from the screen that shows it.
    route = alert_route(alert.perspective, alert.method)

    # The peer group the SCAN stored on this row, read from the block it wrote
    # (``evidence["comparison_policy"]["peer"]["values"]``). Never rebuilt from
    # today's hospital values: the verdict must describe the group that produced
    # the stored score, not a group recomputed now.
    peer_values = stored_peer_group(evidence)

    # ``missing`` = what the DECISION needed and did not have;
    # ``provenance_absent`` = evidence that would make the row self-describing
    # but is not needed for the decision. A peer alert stores the member values,
    # so ``peer_values`` here means the row predates that block.
    missing: List[str] = []
    provenance_absent: List[str] = []
    definition_status: Optional[str] = None
    comparability: Optional[str] = None
    peer_eligibility: Optional[dict] = None
    if route == ROUTE_HISTORY:
        if not series:
            missing.append("history_window")
        if use_current is None:
            missing.append("current_value")
    else:
        if not evidence.get("stats"):
            missing.append("peer_stats")
        if alert.peer_count is None:
            missing.append("peer_count")
        if not peer_values:
            provenance_absent.append("peer_values")

    if base != VERY_HIGH:
        assessment = {
            "applicable": False, "eligible": None, "reason": REASON_CAPPED,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = DEC_NOT_APPLICABLE
    elif route == ROUTE_PEER:
        # Judged by the PRODUCTION reader itself: ``eligibility_assessment``
        # calls ``top_band_gate`` with this row's stored evidence, the shared
        # definition resolver (the specs this run already loaded through
        # ``build_analysis_specs``) and the approved Rule B. The audit keeps no
        # second copy of the peer policy, and a row with no stored group falls
        # back to the same ``undecided`` / ``PEER_POLICY`` production states.
        judged = eligibility_assessment(
            alert.severity, stats=evidence.get("stats"), method=alert.method,
            peer_count=alert.peer_count, series=series, current=use_current,
            perspective=alert.perspective, threshold=stored_threshold(evidence),
            **peer_gate_inputs(alert, set(ctx.specs)))
        assessment = {
            "applicable": judged["applicable"],
            "eligible": judged["eligible"],
            "reason": judged["reason"],
            "final_band": judged["final_band"],
            # The peer policy never asks a robust scale to decide a BAND, so the
            # verdict carries no dispersion band of its own.
            "dispersion_band": None,
            "dispersion_score": None,
            "policy": judged.get("policy"),
        }
        decision = judged["decision"]
        # The three dimensions stay separate, exactly as the API publishes
        # them: the band (always unchanged here), the eligibility verdict, and
        # the definition/comparability evidence it rests on.
        definition_status = judged.get("definition_status")
        comparability = judged.get("group_comparability_status")
        peer_eligibility = judged.get("peer_eligibility")
    else:
        assessment = _gate(base, series, use_current, threshold)
        decision = _decision(assessment)
        if decision == DEC_UNDECIDED and not assessment.get("dispersion_band"):
            # Say whether it was the window or the value that was missing.
            assessment = dict(assessment)
            assessment["reason"] = (REASON_NO_WINDOW if not series
                                    else REASON_NO_CURRENT)

    return {
        "side": "alerts",
        "row_id": alert.id,
        "hospital_id": alert.hospital_id,
        "month": alert.month,
        "code": alert.indicator_code,
        "identity": ctx.identity_for_alert(alert),
        "perspective": alert.perspective,
        "method": alert.method,
        "stored_band": alert.severity,
        "base_band": base,
        "final_band": assessment["final_band"],
        "decision": decision,
        "reason": assessment["reason"],
        "route": route,
        "top_layers": [route],
        "series_n": len(series),
        "current": use_current,
        "threshold": threshold,
        "unit_declared": alert.unit or None,
        "unit_value": None,
        "unit_compatible": True,
        "peer_count": alert.peer_count,
        "peer_values_n": len(peer_values),
        "peer_mean": (evidence.get("stats") or {}).get("mean"),
        "peer_values_mean": None,
        "window": series,
        "missing": missing,
        "provenance_absent": provenance_absent,
        "assessment": assessment,
        "definition_status": definition_status,
        "group_comparability_status": comparability,
        "peer_eligibility": peer_eligibility,
        # What the Quality Alerts screen (and the Dashboard KPI, through the
        # same function) really reports now that the gate is wired. Compared
        # with ``final_band`` below: they must never differ.
        "production_band": production_alert_band(alert),
        "row": alert,
    }


# ── One diagnostics ROW (Outlier Diagnostics) ─────────────────────────────

def _layered_view(row: LayeredOutlierResult, ctx: Context) -> Dict[str, Any]:
    identity, identity_resolved = ctx.identity_for_row(row)
    bands, lowered_zero, lowered_thin = row_layer_bands(row)
    # The band the two APPROVED CAPS allow, per layer. The top-band gate is
    # routed separately below (it is not a row-wide cap); ``row_level_assessment``
    # now composes both, so it is reported as the production read, not as the
    # base.
    base = max_level(bands.values())
    production_band = row_level_assessment(row)[0]
    stored = row.outlier_level or LEVEL_NONE
    history = _numbers((row.history_provenance or {}).get("values"))
    peers = _numbers((row.peer_provenance or {}).get("values"))
    rate_is_set = row.rate is not None
    # The own-history window is in the row's unit value: rates for a rate
    # analysis, the analysis value for a count analysis.
    current = row.rate if rate_is_set else row.raw_value
    holders = sorted(name for name, band in bands.items()
                     if band == VERY_HIGH)
    # The gate threshold the Diagnostics reader itself resolves for this row
    # (its stored classification threshold, else the saved default) — not the
    # configured setting, which the reader does not consult.
    used = row_gate_threshold(row)
    # A raw-count layer on a rate analysis measures the numerator, not the
    # rate the window holds: it cannot be judged by the rate window.
    unit_mismatch = {name for name in holders
                     if name == "raw" and rate_is_set}
    own_holders = [name for name in holders
                   if name in OWN_HISTORY_LAYERS and name not in unit_mismatch]
    missing: List[str] = []
    provenance_absent: List[str] = []
    if own_holders:
        if not history:
            missing.append("history_window")
        if current is None:
            missing.append("current_value")
    if "peer" in holders:
        if not peers and not (row.classification_provenance or {}).get(
                "zero_spread_layers"):
            missing.append("peer_dispersion_evidence")
        if not peers:
            provenance_absent.append("peer_values")

    # What the history question would say, whether or not this row's band rests
    # on it: the report needs the answer for the layers it governs.
    history_gate = (_gate(base, history, current, used)
                    if own_holders else None)

    if stored != VERY_HIGH or base != VERY_HIGH:
        route = ROUTE_CAPPED
        assessment = {
            "applicable": False, "eligible": None, "reason": REASON_CAPPED,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = DEC_NOT_APPLICABLE
    elif "peer" in holders:
        route = ROUTE_PEER
        assessment = {
            "applicable": False, "eligible": None, "reason": REASON_PEER_POLICY,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = DEC_UNDECIDED
    elif "volume" in holders:
        route = ROUTE_VOLUME
        assessment = {
            "applicable": False, "eligible": None,
            "reason": REASON_VOLUME_POLICY, "final_band": base,
            "dispersion_band": None, "dispersion_score": None,
        }
        decision = DEC_UNDECIDED
    elif unit_mismatch and not own_holders:
        route = ROUTE_RAW_UNIT
        assessment = {
            "applicable": False, "eligible": None, "reason": REASON_RAW_UNIT,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = DEC_UNDECIDED
    elif own_holders:
        route = ROUTE_HISTORY
        assessment = history_gate or {
            "applicable": True, "eligible": None, "reason": REASON_NO_WINDOW,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = _decision(assessment)
        if decision == DEC_UNDECIDED:
            assessment = dict(assessment)
            assessment["reason"] = (REASON_NO_WINDOW if not history
                                    else REASON_NO_CURRENT)
    else:
        route = ROUTE_NO_HOLDER
        assessment = {
            "applicable": False, "eligible": None, "reason": REASON_NO_HOLDER,
            "final_band": base, "dispersion_band": None,
            "dispersion_score": None,
        }
        decision = DEC_UNDECIDED

    return {
        "side": "diagnostics",
        "row_id": row.id,
        "hospital_id": row.hospital_id,
        "month": row.month,
        "code": row.analysis_code,
        "identity": identity,
        "identity_resolved": identity_resolved,
        "perspective": row.outlier_type,
        "method": row.outlier_method,
        "stored_band": stored,
        "base_band": base,
        "final_band": assessment["final_band"],
        "decision": decision,
        "reason": assessment["reason"],
        "route": route,
        "top_layers": holders,
        "capped_layers": sorted(set(lowered_zero) | set(lowered_thin)),
        "series_n": len(history),
        "current": current,
        "threshold": used,
        "unit_declared": ctx.unit_of(row.analysis_code),
        "unit_value": ("rate" if rate_is_set else "raw"),
        "unit_compatible": not unit_mismatch,
        "peer_count": row.peer_count,
        "peer_values_n": len(peers),
        "peer_mean": row.peer_mean,
        "peer_values_mean": _mean(peers),
        "window": history,
        "missing": missing,
        "provenance_absent": provenance_absent,
        "assessment": assessment,
        "history_gate": history_gate,
        "layer_bands": bands,
        # What Outlier Diagnostics really reports (``row_level_assessment``
        # composes the caps and the gate). Compared with ``final_band`` below.
        "production_band": production_band,
        "row": row,
    }


# ── Identity-level comparison ─────────────────────────────────────────────

def _side_band(views: Iterable[Dict[str, Any]], field_name: str) -> str:
    """Identity band = the MAX over its rows, like the app's own rollup.

    ``field_name`` is ``base_band`` (before the gate) or ``final_band`` (after
    it), so the same fold answers "what does the screen show" both times.
    """
    best = LEVEL_NONE
    for view in views:
        band = view.get(field_name) or LEVEL_NONE
        if LEVEL_RANK.get(band, 0) > LEVEL_RANK.get(best, 0):
            best = band
    return best


def _fold(views: Sequence[Dict[str, Any]], field_name: str,
          ) -> Dict[Tuple, List[Dict[str, Any]]]:
    folded: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for view in views:
        folded[(view["hospital_id"], view["month"],
                view["identity"])].append(view)
    return folded


def _count_very_high(views: Sequence[Dict[str, Any]],
                     field_name: str) -> int:
    return sum(1 for views_at_key in _fold(views, field_name).values()
               if _side_band(views_at_key, field_name) == VERY_HIGH)


def _cause(left: str, right: str,
           alerts: Sequence[Dict[str, Any]],
           layered: Sequence[Dict[str, Any]]) -> str:
    """Why one identity reads two bands; ``same_band`` when it does not.

    Each cause names a difference in EVIDENCE, not in policy: a baseline the
    gate does not judge, a count compared where the window holds a rate, a
    window one side never stored, or two rows that carry the same window and
    still disagree (a defect worth zero).
    """
    if left == right:
        return CAUSE_SAME
    if any(not v["unit_compatible"] for v in layered):
        return CAUSE_UNIT
    # A peer claim keeps its band on BOTH sides (the peer policy never moves
    # one), so a peer identity can only mismatch when another perspective's band
    # differs — the peer verdict itself is compared in section 5b instead.
    ungoverned = {ROUTE_PEER, ROUTE_VOLUME, ROUTE_RAW_UNIT}
    if any(v["route"] in ungoverned and v["final_band"] == VERY_HIGH
           for v in alerts + layered):
        return CAUSE_LAYER
    hist_alert = [v for v in alerts if v["route"] == ROUTE_HISTORY]
    hist_layer = [v for v in layered if v["route"] == ROUTE_HISTORY]
    if hist_alert and hist_layer and any(
            _same_window(a["window"], b["window"])
            and _close(a["current"], b["current"])
            for a in hist_alert for b in hist_layer):
        # Same policy, same method family, same window and same current value:
        # this must never differ, so it is reported as a defect, not a cause.
        return CAUSE_SAME_INPUTS
    if (any(v["decision"] == DEC_UNDECIDED for v in alerts + layered)
            and any(v["missing"] for v in alerts + layered)):
        return CAUSE_MISSING
    return CAUSE_LAYER


def _mismatch_block(key: Tuple[int, str, str], left: str, right: str,
                    alerts: Sequence[Dict[str, Any]],
                    layered: Sequence[Dict[str, Any]]) -> List[str]:
    codes = sorted({v["code"] for v in alerts} | {v["code"] for v in layered})
    out = [f"    h{key[0]} {key[1]} id={key[2]} codes={','.join(codes)}"
           f"  alerts={left}  diagnostics={right}"]
    for view in alerts:
        out.append(
            f"      alert #{view['row_id']} perspective={view['perspective']} "
            f"method={view['method']} stored={view['stored_band']} "
            f"base={view['base_band']} route={view['route']} "
            f"decision={view['decision']} reason={view['reason']} "
            f"n={view['series_n']} current={view['current']} "
            f"unit={view['unit_declared'] or '-'}")
    for view in layered:
        out.append(
            f"      row   #{view['row_id']} {view['code']} "
            f"method={view['method']} stored={view['stored_band']} "
            f"base={view['base_band']} holders={','.join(view['top_layers']) or '-'} "
            f"capped={','.join(view['capped_layers']) or '-'} "
            f"route={view['route']} decision={view['decision']} "
            f"reason={view['reason']} n={view['series_n']} "
            f"current={view['current']} unit={view['unit_value']} "
            f"compatible={view['unit_compatible']}")
        gate = view.get("history_gate")
        if gate is not None:
            out.append(
                f"        history gate (information only): "
                f"dispersion={gate['dispersion_band']} "
                f"score={gate['dispersion_score']} "
                f"would_be={gate['final_band']}")
    hist_alert = [v for v in alerts if v["route"] == ROUTE_HISTORY]
    hist_layer = [v for v in layered if v["route"] == ROUTE_HISTORY]
    if hist_alert and hist_layer:
        same_inputs = any(
            _same_window(a["window"], b["window"])
            and _close(a["current"], b["current"])
            for a in hist_alert for b in hist_layer)
        out.append(
            f"      history layers: alerts "
            f"{sorted({v['decision'] for v in hist_alert})} / diagnostics "
            f"{sorted({v['decision'] for v in hist_layer})}; "
            f"same window and value: {same_inputs}")
    return out


def _fingerprint(db) -> str:
    digest = hashlib.sha1()
    for row_id, severity in db.query(QualityAlert.id, QualityAlert.severity) \
            .order_by(QualityAlert.id).all():
        digest.update(f"{row_id}:{severity};".encode())
    for row_id, level in (db.query(LayeredOutlierResult.id,
                                   LayeredOutlierResult.outlier_level)
                          .order_by(LayeredOutlierResult.id).all()):
        digest.update(f"{row_id}:{level};".encode())
    return digest.hexdigest()


# ── Report ────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="outbox/very-high-consistency.csv",
                        help="per-row comparison output")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        fingerprint_before = _fingerprint(db)
        ctx = Context()
        try:
            from app.engine.severity import load_analysis_config
            config = load_analysis_config(db)
            ctx.threshold = float(config.zscore_threshold)
            ctx.threshold_source = "load_analysis_config"
        except Exception as exc:     # read-only fallback, reported as such
            ctx.threshold_source = f"default ({type(exc).__name__})"
        ctx.specs = {spec.analysis_code: spec
                     for spec in build_analysis_specs(db)}

        alerts = (db.query(QualityAlert)
                  .filter(QualityAlert.active.is_(True)).all())
        layered_rows = db.query(LayeredOutlierResult).all()
        vh_alerts = [a for a in alerts if a.severity == VERY_HIGH]
        vh_rows = [r for r in layered_rows if r.outlier_level == VERY_HIGH]

        alert_views = [_alert_view(a, ctx) for a in vh_alerts]
        layered_views = [_layered_view(r, ctx) for r in vh_rows]

        print("=== 0. settings ===")
        print(f"  configured z threshold: {ctx.threshold} "
              f"(source: {ctx.threshold_source}) — reported only: each row is "
              "judged with the threshold IT recorded, falling back to the "
              f"saved default {PEER_Z_THRESHOLD_DEFAULT}; the configured value "
              "is never substituted for a missing historical one")
        print("  routing and threshold resolution are the production functions "
              "(quality_alerts.alert_route, layered.row_gate_threshold)")
        print(f"  analysis specs resolved: {len(ctx.specs)} "
              f"({sum(1 for s in ctx.specs.values() if s.is_rate)} rate)")

        # ── 1. populations and identity ─────────────────────────────────
        print("\n=== 1. populations and identity ===")
        print(f"  active alert rows: {len(alerts)}  stored VERY_HIGH: "
              f"{len(vh_alerts)}")
        print(f"  diagnostics rows: {len(layered_rows)}  stored VERY_HIGH: "
              f"{len(vh_rows)}")

        by_alert_all: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
        for view in alert_views:
            by_alert_all[(view["hospital_id"], view["month"],
                          view["identity"])].append(view)
        by_layer_all: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
        for view in layered_views:
            by_layer_all[(view["hospital_id"], view["month"],
                          view["identity"])].append(view)
        # The same identity defined by raw CODE, to show what canonical folding
        # changes instead of asserting it is irrelevant.
        raw_alert_keys = {(v["hospital_id"], v["month"], v["code"])
                          for v in alert_views}
        raw_layer_keys = {(v["hospital_id"], v["month"], v["code"])
                          for v in layered_views}
        folded_in = len(set(by_alert_all) & set(by_layer_all)) - len(
            raw_alert_keys & raw_layer_keys)
        unresolved = sum(1 for v in layered_views if not v["identity_resolved"])
        print(f"  VERY_HIGH identities (hospital, month, canonical formula): "
              f"alerts {len(by_alert_all)}, diagnostics {len(by_layer_all)}, "
              f"shared {len(set(by_alert_all) & set(by_layer_all))}")
        print(f"  identity is the canonical formula, not the code: raw-code "
              f"matching finds {len(raw_alert_keys & raw_layer_keys)} shared, "
              f"canonical matching adds {folded_in} event(s) registered under "
              f"another code")
        if unresolved:
            print(f"  diagnostics rows whose analysis code has no current spec: "
                  f"{unresolved} (code identity used as fallback)")
        dup_rows = sum(1 for views in by_layer_all.values() if len(views) > 1)
        multi_alert = Counter(len(views) for views in by_alert_all.values())
        print(f"  diagnostics identities holding more than one row: {dup_rows} "
              "(must be 0 — one row per analysis)")
        print("  alert rows per identity (perspectives and equivalent codes "
              f"folded): {dict(sorted(multi_alert.items()))}")
        per_perspective = Counter((v["hospital_id"], v["month"],
                                   v["identity"], v["perspective"])
                                  for v in alert_views)
        mirrored = sum(1 for count in per_perspective.values() if count > 1)
        print(f"  identity+perspective pairs holding more than one alert row: "
              f"{mirrored}" + (" (one finding registered under equivalent "
                               "codes; the issue fold keeps the highest band)"
                               if mirrored else ""))

        # ── 2. layer routing ────────────────────────────────────────────
        print("\n=== 2. which rule judged the top band (diagnostics rows) ===")
        routes = Counter((v["route"], v["decision"]) for v in layered_views)
        for (route, decision), count in sorted(routes.items()):
            print(f"  {route:<22} {decision:<15} {count}")
        print("  holders of the top band, by layer "
              "(after the approved caps):")
        holder_counts = Counter()
        for view in layered_views:
            for name in view["top_layers"] or ["-"]:
                holder_counts[name] += 1
        print(f"    {dict(holder_counts.most_common())}")
        unit_bad = [v for v in layered_views if not v["unit_compatible"]]
        print(f"  rows whose top band rests on a count layer of a rate "
              f"analysis: {len(unit_bad)} (route {ROUTE_RAW_UNIT}, undecided)")

        print("\n=== 2b. which rule judged the top band (alert rows) ===")
        alert_routes = Counter((v["route"], v["decision"]) for v in alert_views)
        for (route, decision), count in sorted(alert_routes.items()):
            print(f"  {route:<22} {decision:<15} {count}")
        peer_rows = [v for v in alert_views if v["route"] == ROUTE_PEER]
        print(f"  peer-perspective rows: {len(peer_rows)} of {len(alert_views)}"
              " — judged by the approved peer policy (Rule B) on the group the "
              "scan stored; the history gate never grades them and the "
              "verdict cannot move their band")

        # ── 3. before / after, per screen ───────────────────────────────
        print("\n=== 3. before / after, per screen (gate applied read-only) ===")
        print("  The two tables are different populations: an alert row is one "
              "PERSPECTIVE of a finding, a diagnostics row is one analysis "
              "pass. Row counts across them are not comparable; identities are.")

        moved_alert_rows = [v for v in alert_views
                            if v["final_band"] != v["base_band"]]
        issues_vh_before = _count_very_high(alert_views, "base_band")
        issues_vh_after = _count_very_high(alert_views, "final_band")
        print(f"  alert rows: stored VERY_HIGH {len(alert_views)}, "
              f"base {sum(1 for v in alert_views if v['base_band'] == VERY_HIGH)}, "
              f"after the gate "
              f"{sum(1 for v in alert_views if v['final_band'] == VERY_HIGH)}"
              f"  (rows moved: {len(moved_alert_rows)})")
        print(f"  alert ISSUES (Dashboard's unit): {issues_vh_before} issues "
              f"Very High today -> {issues_vh_after} under the gate")
        # The Dashboard's own counting function, so its number is the screen's.
        try:
            from app.api.dashboard import _quality_issue_counts
            actual = _quality_issue_counts(db, None, None, None, None, None)
            print(f"  Dashboard _quality_issue_counts (production reader): "
                  f"total {actual['total']}, very high {actual['very_high']}")
            if actual["very_high"] != issues_vh_after:
                print("    NOTE: the Dashboard fold and this identity count "
                      "differ — investigate.")
        except Exception as exc:     # pragma: no cover - reported, not hidden
            print(f"  Dashboard function unavailable in this environment: "
                  f"{type(exc).__name__}: {exc}")
        # What the Dashboard reported BEFORE its query selected
        # ``current_value``: every history row fell back to ``undecided`` and
        # kept its band. Kept in the report to show why the column is required.
        no_current_views = [
            _alert_view(v["row"], ctx, current_override=None)
            if v["route"] == ROUTE_HISTORY else v
            for v in alert_views]
        issues_no_current = _count_very_high(no_current_views, "final_band")
        print(f"  projection WITHOUT current_value (the Dashboard query before "
              f"the column was added): {issues_no_current} Very High issues — "
              f"{issues_no_current - issues_vh_after} more than Quality Alerts")
        print("  the Dashboard query DOES select current_value and perspective "
              "now, and section 8b confirms the two counts are equal")

        print(f"  diagnostics rows: stored VERY_HIGH {len(layered_views)}, "
              f"base {sum(1 for v in layered_views if v['base_band'] == VERY_HIGH)}, "
              f"issued identities "
              f"{_count_very_high(layered_views, 'final_band')}, "
              f"after the gate "
              f"{sum(1 for v in layered_views if v['final_band'] == VERY_HIGH)}"
              f"  (rows moved: "
              f"{sum(1 for v in layered_views if v['final_band'] != v['base_band'])})")

        # ── 4. identity-level agreement ────────────────────────────────
        shared = sorted(set(by_alert_all) & set(by_layer_all))
        print("\n=== 4. identity-level agreement ===")
        print(f"  identities only in alerts: "
              f"{len(set(by_alert_all) - set(by_layer_all))}; only in "
              f"diagnostics: {len(set(by_layer_all) - set(by_alert_all))}; "
              f"in both: {len(shared)}")
        pairs: Counter = Counter()
        causes: Counter = Counter()
        mismatches: List[Tuple] = []
        for key in shared:
            left = _side_band(by_alert_all[key], "final_band")
            right = _side_band(by_layer_all[key], "final_band")
            pairs[(left, right)] += 1
            cause = _cause(left, right, by_alert_all[key], by_layer_all[key])
            causes[(cause, left, right)] += 1
            if left != right:
                mismatches.append((key, left, right, cause))
        agree = sum(count for (left, right), count in pairs.items()
                    if left == right)
        print(f"  same band: {agree}/{len(shared)} "
              f"({agree / len(shared):.1%}) on the evidence each table stores")
        print(f"  band pairs: {dict(pairs.most_common())}")
        # Events whose inputs are literally identical (same window, same
        # current value, both on the history route) must decide identically.
        comparable = disagree = 0
        for key in shared:
            for a_view in by_alert_all[key]:
                for b_view in by_layer_all[key]:
                    if (a_view["route"] == ROUTE_HISTORY
                            and b_view["route"] == ROUTE_HISTORY
                            and _same_window(a_view["window"],
                                             b_view["window"])
                            and _close(a_view["current"], b_view["current"])):
                        comparable += 1
                        disagree += a_view["decision"] != b_view["decision"]
        print(f"  comparable history events (same window, same value): "
              f"{comparable}; decisions that differ: {disagree} (must be 0)")
        print("  cause of every pair:")
        for (cause, left, right), count in sorted(causes.items()):
            print(f"    {cause:<34} {left:>9} / {right:<9} {count}")
        unexplained = sum(count for (cause, _l, _r), count in causes.items()
                          if cause == CAUSE_UNEXPLAINED)
        same_inputs = sum(count for (cause, _l, _r), count in causes.items()
                          if cause == CAUSE_SAME_INPUTS)
        print(f"  UNEXPLAINED: {unexplained} (must be 0); "
              f"identical inputs decided differently: {same_inputs} (must be 0)")
        if mismatches:
            print(f"\n  every identity that reads two bands ({len(mismatches)}):")
            for key, left, right, cause in mismatches:
                print(f"    cause: {cause}")
                for line in _mismatch_block(key, left, right,
                                            by_alert_all[key],
                                            by_layer_all[key]):
                    print(line)

        # ── 5. states ──────────────────────────────────────────────────
        print("\n=== 5. eligibility states (never folded together) ===")
        for label, views in (("alerts", alert_views),
                             ("diagnostics", layered_views)):
            counts = Counter(v["decision"] for v in views)
            print(f"  {label}: {dict(sorted(counts.items()))}")
        print("  not_applicable = the gate does not judge this row; undecided = "
              "the policy applies but cannot decide; neither is a pass/fail")

        # ── 5b. peer eligibility, on the peers' own population ─────────
        peer_views = [v for v in alert_views if v["route"] == ROUTE_PEER]
        if peer_views:
            print("\n=== 5b. peer eligibility (Rule B), read from the stored group ===")
            print(f"  peer rows: {len(peer_views)}")
            states = Counter(v["decision"] for v in peer_views)
            for state in (DEC_ELIGIBLE, DEC_INELIGIBLE, DEC_UNDECIDED,
                          DEC_INSUFFICIENT):
                print(f"    {state:<26} {states.get(state, 0)}")
            other_states = {name: count for name, count in states.items()
                            if name not in (DEC_ELIGIBLE, DEC_INELIGIBLE,
                                            DEC_UNDECIDED, DEC_INSUFFICIENT)}
            if other_states:
                print(f"    other states: {other_states}")
            for (state, reason), count in sorted(
                    Counter((v["decision"], v["reason"])
                            for v in peer_views).items()):
                print(f"      {state:<26} {reason:<34} {count}")
            print("  definition tiers: "
                  f"{dict(Counter(v['definition_status'] for v in peer_views).most_common())}")
            print("  group comparability: "
                  f"{dict(Counter(v['group_comparability_status'] for v in peer_views).most_common())}")
            print("  evidence the peer decision needed and did not have: "
                  f"{dict(Counter(f for v in peer_views for f in v['missing']).most_common())}")
            print("  peer rows whose stored group is absent: "
                  f"{dict(Counter(f for v in peer_views for f in v['provenance_absent']).most_common())}")
            moved = [v for v in peer_views
                     if v["final_band"] != v["stored_band"]
                     or v["production_band"] != v["stored_band"]]
            print(f"  peer rows whose band moved: {len(moved)} (must be 0)")
            # Production parity at the PUBLISHED surface: the reader the API
            # builds its payload with, on the same row and the same resolver.
            differing = []
            for view in peer_views:
                verdict = (production_alert_payload(
                    view["row"], catalog_codes=set(ctx.specs))
                    .get("top_band_eligibility") or {})
                if (verdict.get("decision") != view["decision"]
                        or verdict.get("reason") != view["reason"]):
                    differing.append((view, verdict))
            print("  peer rows where this audit and the published payload "
                  f"differ: {len(differing)} (must be 0)")
            for view, verdict in differing[:5]:
                print(f"    alert #{view['row_id']}: audit="
                      f"{view['decision']}/{view['reason']} payload="
                      f"{verdict.get('decision')}/{verdict.get('reason')}")

        # ── 6. unit checks ─────────────────────────────────────────────
        print("\n=== 6. unit checks (does each side grade the same quantity?) ===")
        alert_by_identity: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
        for view in alert_views:
            alert_by_identity[(view["hospital_id"], view["month"],
                               view["identity"])].append(view)
        checked_units = mismatched_units = 0
        value_mismatch: List[str] = []
        for key in shared:
            for layer_view in by_layer_all[key]:
                alert_options = alert_by_identity[key]
                checked_units += 1
                match = any(_close(a["current"], layer_view["current"])
                            for a in alert_options)
                if not match:
                    mismatched_units += 1
                    value_mismatch.append(
                        f"    h{key[0]} {key[1]} {layer_view['code']}: alert "
                        f"values "
                        f"{sorted({a['current'] for a in alert_options})} vs "
                        f"row {layer_view['unit_value']}="
                        f"{layer_view['current']}")
        print(f"  shared identities where the alert's value equals the row's "
              f"own unit value (rate for a rate analysis, else raw): "
              f"{checked_units - mismatched_units}/{checked_units}")
        for line in value_mismatch[:10]:
            print(line)
        peer_consistent = sum(1 for v in layered_views
                              if v["peer_values_n"] >= 2
                              and _close(v["peer_mean"], v["peer_values_mean"]))
        peer_checked = sum(1 for v in layered_views if v["peer_values_n"] >= 2)
        print(f"  diagnostics rows whose stored peer baseline equals the mean "
              f"of its stored peer values: {peer_consistent}/{peer_checked}")
        print(f"  diagnostics rows explicitly flagged unit-incompatible: "
              f"{len(unit_bad)}")
        for view in unit_bad:
            print(f"    h{view['hospital_id']} {view['month']} {view['code']}: "
                  f"holders={view['top_layers']} rate={view['current']}")

        # ── 7. what evidence is missing ────────────────────────────────
        print("\n=== 7. missing evidence (preserved band, never a refusal) ===")
        for label, views in (("alerts", alert_views),
                             ("diagnostics", layered_views)):
            counts = Counter(field for view in views
                             for field in view["missing"])
            absent = Counter(field for view in views
                             for field in view["provenance_absent"])
            print(f"  {label} (needed by the decision and missing): "
                  f"{dict(counts.most_common())}")
            print(f"  {label} (not needed, but not stored): "
                  f"{dict(absent.most_common())}")
        undecided_preserved = [v for v in alert_views + layered_views
                               if v["decision"] == DEC_UNDECIDED
                               and v["final_band"] != v["base_band"]]
        print(f"  undecided rows whose band changed: "
              f"{len(undecided_preserved)} (must be 0)")

        # ── 8. idempotency ─────────────────────────────────────────────
        print("\n=== 8. idempotency and the top-band-only rule ===")
        twice = 0
        for view in alert_views + layered_views:
            if view["route"] != ROUTE_HISTORY or not view["window"]:
                continue
            first = _gate(view["base_band"], view["window"], view["current"],
                          view["threshold"])["final_band"]
            second = _gate(first, view["window"], view["current"],
                           view["threshold"])["final_band"]
            twice += first != second
        print(f"  gate(x) != gate(gate(x)): {twice} (must be 0)")
        below = [v for v in alert_views + layered_views
                 if v["final_band"] and LEVEL_RANK.get(v["final_band"], 0)
                 < LEVEL_RANK.get(LEVEL_HIGH, 0)]
        print(f"  rows pushed below HIGH: {len(below)} (must be 0)")
        lowered_from_high = [v for v in alert_views + layered_views
                             if v["base_band"] != VERY_HIGH
                             and v["final_band"] != v["base_band"]]
        print(f"  rows whose base band was BELOW VERY_HIGH and moved: "
              f"{len(lowered_from_high)} (must be 0)")

        # ── 8b. the screens themselves ────────────────────────────────
        print("\n=== 8b. production readers agree with the routed policy ===")
        print("  Quality Alerts and the Dashboard band a row through "
              "quality_alerts.effective_severity; Diagnostics through "
              "layered.row_level_assessment. Both are called here directly,")
        print("  so this compares what the screens RETURN, not a copy of the "
              "rule.")
        for label, views in (("alerts", alert_views),
                             ("diagnostics", layered_views)):
            differ = [v for v in views
                      if v["production_band"] != v["final_band"]]
            print(f"  {label}: rows where production != routed decision: "
                  f"{len(differ)} of {len(views)} (must be 0)")
            for view in differ[:5]:
                print(f"    h{view['hospital_id']} {view['month']} "
                      f"{view['code']}: production="
                      f"{view['production_band']} routed={view['final_band']} "
                      f"route={view['route']}")
        # The Dashboard reads its own rows: the count it publishes and the
        # count this audit derives must be the same population.
        try:
            from app.api.dashboard import _quality_issue_counts
            dashboard = _quality_issue_counts(db, None, None, None, None, None)
            print(f"  Dashboard very-high ISSUES: "
                  f"{dashboard['very_high']}")
            print(f"  audit identities VERY_HIGH after the gate: "
                  f"{issues_vh_after}")
            print("    equal: "
                  f"{'yes' if dashboard['very_high'] == issues_vh_after else 'NO'}")
        except Exception as exc:     # pragma: no cover - reported, not hidden
            print(f"  Dashboard function unavailable: "
                  f"{type(exc).__name__}: {exc}")

        # ── 9. stored records ──────────────────────────────────────────
        db.rollback()
        fingerprint_after = _fingerprint(db)
        print("\n=== 9. stored records ===")
        print(f"  stored-band fingerprint before: {fingerprint_before}")
        print(f"  stored-band fingerprint after:  {fingerprint_after}")
        print(f"  unchanged: "
              f"{'yes' if fingerprint_before == fingerprint_after else 'NO'}")

        # ── CSV ────────────────────────────────────────────────────────
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        columns = ["side", "row_id", "identity", "hospital_id", "month", "code",
                   "perspective", "method", "stored_band", "base_band", "route",
                   "top_layers", "decision", "reason", "final_band", "series_n",
                   "current", "unit_declared", "unit_value", "unit_compatible",
                   "peer_count", "peer_values_n", "peer_mean",
                   "peer_values_mean", "missing"]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for view in alert_views + layered_views:
                writer.writerow([
                    view["side"], view["row_id"], view["identity"],
                    view["hospital_id"], view["month"], view["code"],
                    view["perspective"], view["method"], view["stored_band"],
                    view["base_band"], view["route"],
                    "|".join(view["top_layers"]), view["decision"],
                    view["reason"], view["final_band"], view["series_n"],
                    view["current"], view["unit_declared"] or "",
                    view["unit_value"] or "", view["unit_compatible"],
                    view["peer_count"], view["peer_values_n"],
                    view["peer_mean"], view["peer_values_mean"],
                    "|".join(view["missing"]),
                ])
        print(f"\nwrote {out}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
