import numpy as np
from scipy import stats as scipy_stats
from sqlalchemy.orm import Session

from app.engine import comparison_policy, indicator_service
from app.engine.anomaly.layered import (
    effective_severity,
    peer_z_measurable,
    peer_z_provenance,
)
from app.engine.pipeline import get_all_hospital_data_for_month
from app.engine.rate_config import SITE_ZSCORE
from app.models import Hospital, LayeredOutlierResult


# ── Canonical layered evidence (Phase 6) ──────────────────────────────────
# The benchmark keeps its own audited statistics — sample standard deviation,
# z, percentile and the status ladder below — because that is its purpose. What
# it must NOT do is grade a finding the layered engine already graded. When a
# comparison is provably the SAME one (same hospital/month, same analysis unit
# and formula, same peer population, same rate), the canonical band is read
# from the stored LayeredOutlierResult; the benchmark's own status stays beside
# it, labelled independent. Nothing canonical is substituted into an
# independent calculation, and a missing row is never read as "normal".
EVIDENCE_CANONICAL = "canonical_layered"
EVIDENCE_INDEPENDENT = "independent_audit"
EVIDENCE_UNAVAILABLE = "canonical_evidence_unavailable"
STATUS_EQUIVALENT = "equivalent"
STATUS_NOT_EQUIVALENT = "not_equivalent"
STATUS_MISSING = "missing_layered_result"
STATUS_UNAVAILABLE = "canonical_evidence_unavailable"

# The benchmark's own statistical methodology, named so a reader can tell it
# apart from the canonical engine's layers.
BENCHMARK_METHODOLOGY = "benchmark_sample_stdev_ddof1_peer_zscore"


def _provenance(resolved) -> dict:
    return {
        "indicator_id": resolved.indicator_id,
        "formula": resolved.formula,
        "formula_version": resolved.formula_version,
        "unit": resolved.unit,
    }


def _canonical_context(db: Session):
    """``(specs by analysis_code, definition code -> analysis_code)``.

    The bridge is the projection the pipeline itself uses: a rate spec carried
    by ``rate_config`` under its own code is linked to the registry definition
    the benchmark resolves, by formula — never by display name.
    """
    from app.engine.anomaly.layered import build_analysis_specs
    from app.engine.anomaly.projection import projection_codes

    specs = build_analysis_specs(db)
    by_code = {spec.analysis_code: spec for spec in specs}
    bridge = {code: analysis
              for analysis, code in projection_codes(db, specs=specs).items()}
    return by_code, bridge


def _canonical_analysis_code(resolved, by_code, bridge):
    """The analysis unit a resolved benchmark indicator is stored under."""
    code = getattr(resolved, "code", None)
    if not code:
        return None
    if code in bridge:
        return bridge[code]
    if code in by_code:
        return code
    return None


def _same_formula(spec, resolved) -> bool:
    """Whether the spec computes the very expression the benchmark resolved.

    Identity, not display: the numerator/denominator codes must match, and a
    scale recorded on either side must agree. A definition without a recorded
    multiplier is not evidence of a different scale, so it is accepted.
    """
    source = (getattr(resolved, "definition", None)
              or getattr(resolved, "spec", None))
    if spec is None or source is None:
        return False
    numerator = tuple(getattr(source, "numerator_codes", None) or ())
    denominator = tuple(getattr(source, "denominator_codes", None) or ())
    if (tuple(spec.numerator_codes), tuple(spec.denominator_codes)) != \
            (numerator, denominator):
        return False
    theirs = getattr(source, "multiplier", None)
    if theirs is None:
        theirs = getattr(source, "rate_multiplier", None)
    if theirs is None:
        return True
    try:
        return round(float(theirs), 6) == round(float(spec.rate_multiplier or 1.0), 6)
    except (TypeError, ValueError):
        return False


def _stored_peer_ids(row) -> list:
    ids = []
    for key in ((getattr(row, "peer_provenance", None) or {}).get("values") or {}):
        try:
            ids.append(int(key))
        except (TypeError, ValueError):
            continue
    return sorted(ids)


def _canonical_comparison_evidence(row, spec, resolved, target_value,
                                   peer_ids, peer_group) -> dict:
    """The canonical band for ONE comparison, or the reason it is not reused.

    Equivalence needs all of: the same stored peer population (ids, not
    names), the same formula/unit, and the same rate. Anything else is an
    independent audit comparison — including a comparison that legitimately
    looks at a different population.
    """
    base = {
        "comparison_methodology": BENCHMARK_METHODOLOGY,
        "comparison_population": {
            "group": peer_group,
            "peer_ids": list(peer_ids or ()),
            "peer_count": len(peer_ids or ()),
            "target_excluded": True,
        },
        "evidence_source": EVIDENCE_INDEPENDENT,
        "evidence_status": STATUS_NOT_EQUIVALENT,
        "canonical_effective_level": None,
        "canonical_stored_level": None,
        "canonical_capped": None,
        "layered_result_id": None,
        "analysis_code": None,
        "canonical_peer_mean": None,
        "canonical_peer_count": None,
        "canonical_score": None,
    }
    if row is None:
        base.update(evidence_source=EVIDENCE_UNAVAILABLE,
                    evidence_status=STATUS_MISSING)
        return base
    if any(pid is None for pid in (peer_ids or ())):
        # A peer hospital could not be identified: equivalence unprovable.
        return base
    # The benchmark always compares the detection baseline; the STORED row must
    # say it was scored against that same baseline over the same hospitals.
    stored_group = ((getattr(row, "peer_provenance", None) or {})
                    .get("group"))
    if (stored_group != comparison_policy.DETECTION_PEER_GROUP
            or (_stored_peer_ids(row) != sorted(int(pid) for pid in peer_ids))):
        return base
    if not _same_formula(spec, resolved):
        return base
    stored_rate = getattr(row, "rate", None)
    if (stored_rate is not None and target_value is not None
            and round(float(stored_rate), 2) != round(float(target_value), 2)):
        # A different rate for the same indicator is a different measurement.
        return base
    score = getattr(row, "peer_outlier_score", None)
    if score is None or getattr(row, "peer_mean", None) is None:
        base.update(evidence_source=EVIDENCE_UNAVAILABLE,
                    evidence_status=STATUS_UNAVAILABLE)
        return base
    grade = effective_severity(row)
    base.update(
        evidence_source=EVIDENCE_CANONICAL,
        evidence_status=STATUS_EQUIVALENT,
        canonical_effective_level=grade["level"],
        canonical_stored_level=grade["stored_level"],
        canonical_capped=grade["capped"],
        layered_result_id=getattr(row, "id", None),
        analysis_code=getattr(row, "analysis_code", None),
        canonical_peer_mean=float(getattr(row, "peer_mean")),
        canonical_peer_count=getattr(row, "peer_count", None),
        canonical_score=float(score),
    )
    return base


def _canonical_rows(db: Session, hospital_id: int, month: str):
    return {row.analysis_code: row for row in
            db.query(LayeredOutlierResult).filter(
                LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month).all()}


def get_benchmark(db: Session, hospital_id: int, month: str) -> dict:
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()
    target_hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not target_hospital:
        return {"error": "Hospital not found"}

    # Rates for every active hospital that reported data this month. The
    # SHARED anomaly-engine compute_rate is the one calculation behind this
    # screen and the Outliers screen (rate_config spec multipliers) — they
    # can no longer disagree on x1 / x30 / x100 per indicator. It returns
    # None when the denominator is zero OR either side is unreported, so a
    # hospital that never reported a numerator never fabricates a 0% rate.
    all_rates = {}
    all_hospital_values = get_all_hospital_data_for_month(db, month)
    system_indicators = [
        resolved for resolved in indicator_service.resolve_active_definitions(
            db, site=SITE_ZSCORE)
        if resolved.site == SITE_ZSCORE
    ]
    for name, vals in all_hospital_values.items():
        rates = {}
        for resolved in system_indicators:
            result = indicator_service.calculate_from_values(
                resolved, vals, hospital_id=0, month=month)
            if result.status == "ok" and result.value is not None:
                rates[resolved.name] = round(result.value, 2)
        all_rates[name] = rates

    if target_hospital.name not in all_rates:
        return {"error": f"No data for {target_hospital.name} / {month}"}

    no_data_month = [h.name for h in hospitals if h.name not in all_rates]
    other_hospitals = sorted(set(all_rates) - {target_hospital.name})
    name_to_id = {h.name: h.id for h in hospitals}
    # Phase 6: canonical evidence is optional. An unreadable canonical plane
    # must be REPORTED as unavailable — never mistaken for an intentionally
    # independent comparison.
    canonical_error = False
    try:
        specs_by_code, code_bridge = _canonical_context(db)
        canonical_rows = _canonical_rows(db, target_hospital.id, month)
    except Exception:
        canonical_error = True
        specs_by_code, code_bridge, canonical_rows = {}, {}, {}

    # Rate presence must match the anomaly engine (engine.anomaly.zscore): a
    # rate exists only when the target's denominator is present AND its
    # numerator is reported. A reported denominator with a missing numerator
    # means the hospital did not report that numerator — treating it as 0
    # fabricated rates that the anomalies screen (correctly) does not list.
    target_rates = all_rates.get(target_hospital.name, {})

    comparisons = {}
    for resolved in system_indicators:
        rname = resolved.name
        if rname not in target_rates:
            continue
        tval = target_rates[rname]
        peers = [all_rates[h][rname] for h in other_hospitals if rname in all_rates[h]]
        if not peers:
            continue
        no_denominator = [h for h in other_hospitals if rname not in all_rates[h]]

        peer_count = len(peers)
        avg = round(float(np.mean(peers)), 2)
        med = round(float(np.median(peers)), 2)
        std = float(np.std(peers, ddof=1)) if len(peers) > 1 else 0
        # The z divides by the group's own spread: fewer than
        # layered.MIN_PEERS_FOR_TOP_BAND other hospitals cannot measure one
        # (layered.PEER_Z_POLICY), so this screen withholds the z AND the
        # status it grades rather than quoting |z| = 224 from a 2-peer group.
        # The values, mean/median, range and percentile are kept, so the
        # comparison is still fully readable.
        z_graded = peer_z_measurable(peer_count)
        z = round((tval - avg) / std, 2) if std > 0 else 0
        if not z_graded:
            z = None
        pct_dev = round(((tval - avg) / avg) * 100, 1) if avg else 0
        below = sum(1 for p in peers if p < tval)
        equal = sum(1 for p in peers if p == tval)
        percentile = round((below + 0.5 * equal) / len(peers) * 100, 1)
        status = None if z is None else (
            "critical" if abs(z) >= 3 else ("high" if abs(z) >= 2 else ("elevated" if abs(z) >= 1.5 else "normal")))
        ci = None
        if len(peers) >= 3 and std > 0:
            se = std / (len(peers) ** 0.5)
            ci_low, ci_high = scipy_stats.norm.interval(0.95, loc=avg, scale=se)
            ci = (round(float(ci_low), 2), round(float(ci_high), 2))

        peer_ids = [name_to_id.get(h) for h in other_hospitals
                    if rname in all_rates[h]]
        analysis_code = _canonical_analysis_code(resolved, specs_by_code,
                                                 code_bridge)
        canonical_row = canonical_rows.get(analysis_code) if analysis_code else None
        evidence = _canonical_comparison_evidence(
            canonical_row, specs_by_code.get(analysis_code), resolved, tval,
            peer_ids, comparison_policy.DETECTION_PEER_GROUP)
        if canonical_error:
            evidence.update(evidence_source=EVIDENCE_UNAVAILABLE,
                            evidence_status=STATUS_UNAVAILABLE)

        comparisons[rname] = {
            **evidence,
            "hospital_value": tval,
            "peer_average": avg,
            "peer_median": med,
            "peer_min": round(float(min(peers)), 2),
            "peer_max": round(float(max(peers)), 2),
            "peer_count": peer_count,
            "peer_std": round(std, 2),
            "z_score": z,
            # Whether a z was produced for this group, and why not — a NULL z
            # is the policy's output, not a missing measurement.
            "z_provenance": peer_z_provenance(peer_count),
            "percent_deviation": pct_dev,
            "percentile": percentile,
            "peers_below": below,
            "status": status,
            "confidence_interval_95": ci,
            # central-registry linkage (see _provenance)
            **_provenance(resolved),
            "peer_breakdown": {
                "total_active": len(hospitals),
                "excluded_target": 1,
                "no_data_month_count": len(no_data_month),
                "no_data_month_names": no_data_month,
                "no_denominator_count": len(no_denominator),
                "no_denominator_names": no_denominator,
            },
        }

    # User-managed derived definitions participate in the same peer
    # comparison; anomaly thresholds remain in the outlier module. Migrated
    # system definitions are already represented by their own site's loop
    # above — including them again here duplicated the same clinical rate
    # under a second name/unit and broke audit/outlier parity.
    for resolved in indicator_service.resolve_active_definitions(db):
        if getattr(resolved.definition, "is_system", False):
            continue
        managed_rates = {}
        for name, values in all_hospital_values.items():
            result = indicator_service.calculate_from_values(
                resolved, values, hospital_id=0, month=month)
            if result.status == "ok" and result.value is not None:
                managed_rates[name] = result.value
        if target_hospital.name not in managed_rates:
            continue
        target_value = managed_rates[target_hospital.name]
        peer_values = [
            value for name, value in managed_rates.items()
            if name != target_hospital.name
        ]
        if not peer_values:
            continue
        peer_count = len(peer_values)
        average = float(np.mean(peer_values))
        median = float(np.median(peer_values))
        std = float(np.std(peer_values, ddof=1)) if len(peer_values) > 1 else 0.0
        # Same rule as the system-rate loop above: a group too small to measure
        # a spread produces no z, so neither the z nor a z-graded status is
        # quoted for it.
        z_score = (target_value - average) / std if std > 0 else 0.0
        if not peer_z_measurable(peer_count):
            z_score = None
        below = sum(1 for peer in peer_values if peer < target_value)
        equal = sum(1 for peer in peer_values if peer == target_value)
        status = None if z_score is None else (
            "critical" if abs(z_score) >= 3 else
            "high" if abs(z_score) >= 2 else
            "elevated" if abs(z_score) >= 1.5 else "normal"
        )
        ci = None
        if len(peer_values) >= 3 and std > 0:
            interval = scipy_stats.norm.interval(
                0.95, loc=average, scale=std / (len(peer_values) ** 0.5))
            ci = (round(float(interval[0]), 2), round(float(interval[1]), 2))
        managed_peer_ids = [name_to_id.get(name) for name in managed_rates
                            if name != target_hospital.name]
        managed_analysis = _canonical_analysis_code(
            resolved, specs_by_code, code_bridge)
        managed_row = (canonical_rows.get(managed_analysis)
                       if managed_analysis else None)
        managed_evidence = _canonical_comparison_evidence(
            managed_row, specs_by_code.get(managed_analysis), resolved,
            target_value, managed_peer_ids,
            comparison_policy.DETECTION_PEER_GROUP)
        if canonical_error:
            managed_evidence.update(
                evidence_source=EVIDENCE_UNAVAILABLE,
                evidence_status=STATUS_UNAVAILABLE)
        comparisons[resolved.name] = {
            **managed_evidence,
            "hospital_value": round(target_value, 2),
            "peer_average": round(average, 2),
            "peer_median": round(median, 2),
            "peer_min": round(float(min(peer_values)), 2),
            "peer_max": round(float(max(peer_values)), 2),
            "peer_count": peer_count,
            "peer_std": round(std, 2),
            "z_score": (None if z_score is None else round(z_score, 2)),
            "z_provenance": peer_z_provenance(peer_count),
            "percent_deviation": round(
                ((target_value - average) / average) * 100, 1) if average else 0,
            "percentile": round(
                (below + 0.5 * equal) / len(peer_values) * 100, 1),
            "peers_below": below,
            "status": status,
            "confidence_interval_95": ci,
            "indicator_id": resolved.indicator_id,
            "indicator_code": resolved.code,
            "formula": resolved.formula,
            "formula_version": resolved.formula_version,
            "unit": resolved.unit,
            "peer_breakdown": {
                "total_active": len(hospitals),
                "excluded_target": 1,
                "no_data_month_count": len(no_data_month),
                "no_data_month_names": no_data_month,
                "no_denominator_count": len(other_hospitals) - len(peer_values),
                "no_denominator_names": [
                    name for name in other_hospitals if name not in managed_rates
                ],
            },
        }

    summary = {"canonical_layered": 0, "independent_audit": 0,
               "missing_layered_result": 0,
               "canonical_evidence_unavailable": 0}
    for comparison in comparisons.values():
        status = comparison.get("evidence_status")
        if comparison.get("evidence_source") == EVIDENCE_CANONICAL:
            summary["canonical_layered"] += 1
        elif status == STATUS_MISSING:
            summary["missing_layered_result"] += 1
        elif comparison.get("evidence_source") == EVIDENCE_UNAVAILABLE:
            summary["canonical_evidence_unavailable"] += 1
        else:
            summary["independent_audit"] += 1

    return {
        "hospital": target_hospital.name,
        "month": month,
        "comparisons": comparisons,
        # Phase 6: how much of this audit rests on canonical evidence.
        "evidence_summary": summary,
    }
