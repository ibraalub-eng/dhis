import numpy as np
from scipy import stats as scipy_stats
from sqlalchemy.orm import Session

from app.engine import indicator_service
from app.engine.pipeline import get_all_hospital_data_for_month
from app.engine.rate_config import SITE_ZSCORE
from app.models import Hospital


def _provenance(resolved) -> dict:
    return {
        "indicator_id": resolved.indicator_id,
        "formula": resolved.formula,
        "formula_version": resolved.formula_version,
        "unit": resolved.unit,
    }


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

        avg = round(float(np.mean(peers)), 2)
        med = round(float(np.median(peers)), 2)
        std = float(np.std(peers, ddof=1)) if len(peers) > 1 else 0
        z = round((tval - avg) / std, 2) if std > 0 else 0
        pct_dev = round(((tval - avg) / avg) * 100, 1) if avg else 0
        below = sum(1 for p in peers if p < tval)
        equal = sum(1 for p in peers if p == tval)
        percentile = round((below + 0.5 * equal) / len(peers) * 100, 1)
        status = "critical" if abs(z) >= 3 else ("high" if abs(z) >= 2 else ("elevated" if abs(z) >= 1.5 else "normal"))
        ci = None
        if len(peers) >= 3 and std > 0:
            se = std / (len(peers) ** 0.5)
            ci_low, ci_high = scipy_stats.norm.interval(0.95, loc=avg, scale=se)
            ci = (round(float(ci_low), 2), round(float(ci_high), 2))

        comparisons[rname] = {
            "hospital_value": tval,
            "peer_average": avg,
            "peer_median": med,
            "peer_min": round(float(min(peers)), 2),
            "peer_max": round(float(max(peers)), 2),
            "peer_count": len(peers),
            "peer_std": round(std, 2),
            "z_score": z,
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
        average = float(np.mean(peer_values))
        median = float(np.median(peer_values))
        std = float(np.std(peer_values, ddof=1)) if len(peer_values) > 1 else 0.0
        z_score = (target_value - average) / std if std > 0 else 0.0
        below = sum(1 for peer in peer_values if peer < target_value)
        equal = sum(1 for peer in peer_values if peer == target_value)
        status = (
            "critical" if abs(z_score) >= 3 else
            "high" if abs(z_score) >= 2 else
            "elevated" if abs(z_score) >= 1.5 else "normal"
        )
        ci = None
        if len(peer_values) >= 3 and std > 0:
            interval = scipy_stats.norm.interval(
                0.95, loc=average, scale=std / (len(peer_values) ** 0.5))
            ci = (round(float(interval[0]), 2), round(float(interval[1]), 2))
        comparisons[resolved.name] = {
            "hospital_value": round(target_value, 2),
            "peer_average": round(average, 2),
            "peer_median": round(median, 2),
            "peer_min": round(float(min(peer_values)), 2),
            "peer_max": round(float(max(peer_values)), 2),
            "peer_count": len(peer_values),
            "peer_std": round(std, 2),
            "z_score": round(z_score, 2),
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

    return {
        "hospital": target_hospital.name,
        "month": month,
        "comparisons": comparisons,
    }
