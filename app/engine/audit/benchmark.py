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
            num = sum(vals.get(c, 0) or 0 for c in num_code.split(","))
            den = vals.get(den_code, 0)
            if den:
                rates[rate_name] = round((num / den) * 100, 2)
        all_rates[name] = rates

    if target_hospital.name not in all_rates:
        return {"error": f"No data for {target_hospital.name} / {month}"}

    no_data_month = [h.name for h in hospitals if h.name not in all_rates]
    other_hospitals = sorted(set(all_rates) - {target_hospital.name})

    comparisons = {}
    for rname, tval in all_rates[target_hospital.name].items():
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
