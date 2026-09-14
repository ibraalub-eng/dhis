import numpy as np
from scipy import stats as scipy_stats
from sqlalchemy.orm import Session
from app.models import Hospital
from app.engine.anomaly.zscore import RATE_DEFINITIONS
from app.engine.pipeline import get_all_hospital_data_for_month


def get_benchmark(db: Session, hospital_id: int, month: str) -> dict:
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()
    target_hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not target_hospital:
        return {"error": "Hospital not found"}

    # Rates for every active hospital that reported data this month; a rate is
    # only computable when its denominator is nonzero.
    all_rates = {}
    for name, vals in get_all_hospital_data_for_month(db, month).items():
        rates = {}
        for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
            # Same presence rule as the anomaly engine's compute_rate: the
            # rate exists only when BOTH numerator and denominator are
            # reported. Defaulting a missing numerator to 0 fabricated rates
            # (e.g. "Stillbirth rate: 0%") for hospitals that never reported
            # that numerator, so the audit screen listed rates the anomalies
            # screen did not.
            if num_code in vals and den_code in vals and vals.get(den_code):
                num = sum(vals.get(c, 0) or 0 for c in num_code.split(","))
                rates[rate_name] = round((num / vals[den_code]) * 100, 2)
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
    for rname, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
        if rname not in target_rates:
            continue
        tval = target_rates[rname]
        # Audit-rate math uses sum-of-numerators (num_code may be a
        # comma-separated list); the anomaly engine uses single codes only.        peers = [all_rates[h][rname] for h in other_hospitals if rname in all_rates[h]]
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
            "peer_breakdown": {
                "total_active": len(hospitals),
                "excluded_target": 1,
                "no_data_month_count": len(no_data_month),
                "no_data_month_names": no_data_month,
                "no_denominator_count": len(no_denominator),
                "no_denominator_names": no_denominator,
            },
        }

    return {
        "hospital": target_hospital.name,
        "month": month,
        "comparisons": comparisons,
    }
