import numpy as np
from scipy import stats as scipy_stats
from sqlalchemy.orm import Session
from app.models import Hospital
from app.engine.anomaly.zscore import RATE_DEFINITIONS
from app.engine.pipeline import get_enabled_values_for_hospital_month


def get_benchmark(db: Session, hospital_id: int, month: str) -> dict:
    hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).order_by(Hospital.name).all()
    target_hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not target_hospital:
        return {"error": "Hospital not found"}

    target_vals = get_enabled_values_for_hospital_month(db, hospital_id, month)
    if not target_vals:
        return {"error": f"No data for {target_hospital.name} / {month}"}

    all_rates = {}
    for h in hospitals:
        vals = get_enabled_values_for_hospital_month(db, h.id, month)
        if not vals:
            continue
        rates = {}
        for rate_name, num_code, den_code, _typical_pct in RATE_DEFINITIONS:
            num = sum(vals.get(c, 0) or 0 for c in num_code.split(","))
            den = vals.get(den_code, 0)
            if den:
                rates[rate_name] = round((num / den) * 100, 2)
        if rates:
            all_rates[h.name] = rates

    comparisons = {}
    target_rates = all_rates.get(target_hospital.name, {})
    for rname, tval in target_rates.items():
        peers = [v[rname] for hname, v in all_rates.items() if rname in v and hname != target_hospital.name]
        if not peers:
            continue
        avg = round(float(np.mean(peers)), 2)
        med = round(float(np.median(peers)), 2)
        std = float(np.std(peers, ddof=1)) if len(peers) > 1 else 0
        z = round((tval - avg) / std, 2) if std > 0 else 0
        pct_dev = round(((tval - avg) / avg) * 100, 1) if avg else 0
        percentile = round(sum(1 for p in peers if p <= tval) / len(peers) * 100, 0) if peers else 50
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
            "status": status,
            "confidence_interval_95": ci,
        }

    return {
        "hospital": target_hospital.name,
        "month": month,
        "comparisons": comparisons,
    }
