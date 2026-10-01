"""إغلاق الحلقة (المرحلة 3): دقة حيّة من لقطات تنبؤات شهرية.

عند تشغيل محرك XGBoost للشهر m تُحفظ لقطة تنبؤات الشهر m+1 ذرياً على
القرص تحت MODEL_DIR/forecast_snapshots — بلا أي تغيير في مخطط قاعدة
البيانات. عند توفر درجات فعلية للشهر m+1 (من سلاسل المؤشرات نفسها التي
يدرّب عليها المحرك) تُقيَّم اللقطة: خطأ حقيقي + إصابة الاتجاه (±0.05،
نفس عتبة المحرك) + إصابة درجة الخطورة، مع تجميع شهري واتجاه تحسّن/تراجع
النموذج عبر الأشهر.

التقييم يُدمج في استجابة /smart/xgboost عبر حقل forecast_tracking غير
الفتّاع (فشله لا يُسقط استجابة التنبؤات). كل القيم تقديرات إحصائية من
بيانات ماضية — لا تنبؤ مؤكد.
"""
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from app.engine.smart.xgboost_predictor import _score_to_severity, _direction_hit

logger = logging.getLogger(__name__)

_SNAP_DIR_NAME = "forecast_snapshots"
_DISCLAIMER = "تقدير إحصائي لا تنبؤ مؤكد."


def _snap_dir(snapshot_dir: Optional[str] = None) -> str:
    base = snapshot_dir or os.path.join(
        __import__("app.engine.smart.xgboost_predictor", fromlist=["MODEL_DIR"]).MODEL_DIR,
        _SNAP_DIR_NAME,
    )
    return base


def _snapshot_path(month: str, snapshot_dir: Optional[str] = None) -> str:
    return os.path.join(_snap_dir(snapshot_dir), f"snapshot_{month}.json")


def save_forecast_snapshot(
    month: str,
    predictions: List[Dict[str, Any]],
    trained_at: str = "",
    fingerprint: str = "",
    snapshot_dir: Optional[str] = None,
) -> str:
    """حفظ لقطة تنبؤات الشهر m (هدفها m+1) بكتابة ذرية عبر .tmp ثم replace.

    التنبؤات تُختزل إلى الحقول اللازمة للتقييم فقط. يُعاد المسار المحفوظ.
    """
    target = _next_months(month, 1)[0]
    slim = [
        {
            "hospital_name": p.get("hospital_name"),
            "hospital_id": p.get("hospital_id"),
            "current_score": p.get("current_score"),
            "predicted_next_score": round(float(p.get("predicted_next_score") or 0.0), 6),
            "predicted_severity": p.get("predicted_severity"),
            "risk_change": p.get("risk_change"),
        }
        for p in (predictions or [])
        if p.get("hospital_name") is not None
    ]
    snap = {
        "month": month,              # الشهر الذي بُني عليه التنبؤ
        "target_month": target,      # الشهر الفعلي الذي سيُقيَّم عنده
        "trained_at": trained_at,
        "fingerprint": fingerprint,
        "predictions": slim,
    }
    d = _snap_dir(snapshot_dir)
    os.makedirs(d, exist_ok=True)
    path = _snapshot_path(month, snapshot_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def _load_forecast_snapshot(month: str, snapshot_dir: Optional[str] = None) -> Optional[Dict]:
    path = _snapshot_path(month, snapshot_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read forecast snapshot %s: %s", path, e)
        return None


def _actual_scores(session) -> Dict[str, Dict[str, float]]:
    """درجات فعلية شهرية لكل مستشفى — بنفس صيغة المحرك (next vs cur).

    يعيد: hospital -> {month: score} حيث score = 0.5 + (cur/prev − 1)×2
    مقيّدة [0,1]، محسوبة من وسيط ميزات كل شهر (بدون أول شهر لكل مستشفى
    لأنه بلا سابق).
    """
    from app.engine.smart.xgboost_predictor import _load_multi_month_data
    from app.engine.smart.trajectory import _month_median

    months = sorted(
        r[0] for r in session.query(
            __import__("app.models", fromlist=["IndicatorValue"]).IndicatorValue.month,
        ).distinct().all()
    )
    if not months:
        return {}
    rows, _ = _load_multi_month_data(session, months)
    per: Dict[str, Dict[str, float]] = {}
    for row in rows:
        med = _month_median(row["values"])
        if med is None or med != med or med <= 0:
            continue  # NaN/صفر => شهر بلا بيانات فعلية
        per.setdefault(row["hospital_name"], {})[row["month"]] = float(med)

    out: Dict[str, Dict[str, float]] = {}
    for name, meds in per.items():
        ordered = sorted(meds)
        prev = None
        for m in ordered:
            cur = meds[m]
            if prev is not None and prev > 0:
                out.setdefault(name, {})[m] = min(max(0.5 + (cur / prev - 1.0) * 2.0, 0.0), 1.0)
            prev = cur
    return out


def evaluate_forecast_tracking(
    session=None,
    actuals_fn: Optional[Callable[[], Dict[str, Dict[str, float]]]] = None,
    snapshot_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """تقييم كل اللقطات المستحقة: شهر فعلي وصل ولقطة تنبؤ بانتظاره.

    يعيد: months (كل شهر مُقيَّم: n, mae, direction_hit_rate,
    severity_hit_rate)، overall (المجاميع + trend: improving/declining/
    stable/insufficient)، وnote بإخلاء المسؤولية.
    """
    actuals = actuals_fn() if actuals_fn else (_actual_scores(session) if session else {})

    month_dirs: List[str] = []
    d = _snap_dir(snapshot_dir)
    if os.path.isdir(d):
        month_dirs = sorted(
            f[len("snapshot_"):-len(".json")] for f in os.listdir(d)
            if f.startswith("snapshot_") and f.endswith(".json")
        )

    months_out: List[Dict[str, Any]] = []
    per_errors: List[float] = []
    dir_hits_all: List[int] = []
    sev_hits_all: List[int] = []

    for snap_month in month_dirs:
        snap = _load_forecast_snapshot(snap_month, snapshot_dir)
        if not snap:
            continue
        target = snap.get("target_month")
        rows = snap.get("predictions") or []
        errs: List[float] = []
        dir_hits: List[int] = []
        sev_hits: List[int] = []
        for p in rows:
            name = p.get("hospital_name")
            actual = actuals.get(name, {}).get(target)
            if actual is None:
                continue  # الشهر الفعلي غير متاح لهذا المستشفى بعد
            pred = float(p.get("predicted_next_score") or 0.0)
            errs.append(pred - actual)
            dir_hits.append(1 if _direction_hit(
                float(p.get("current_score") or 0.5), pred, actual) else 0)
            sev_hits.append(1 if _score_to_severity(pred) == _score_to_severity(actual) else 0)
        if not errs:
            continue  # لم يصل الفعلي لهذه اللقطة بعد — تُتخطى لا تُحذف
        n = len(errs)
        mae = sum(abs(e) for e in errs) / n
        per_errors.extend(errs)
        dir_hits_all.extend(dir_hits)
        sev_hits_all.extend(sev_hits)
        months_out.append({
            "month": target,
            "snapshot_month": snap_month,
            "n": n,
            "mae": round(mae, 4),
            "direction_hit_rate": round(sum(dir_hits) / n, 3),
            "severity_hit_rate": round(sum(sev_hits) / n, 3),
        })

    months_out.sort(key=lambda m: m["month"])
    if not months_out:
        return {
            "months": [],
            "overall": {"n_evals": 0, "mae": 0.0, "direction_hit_rate": None,
                        "severity_hit_rate": None, "trend": "insufficient"},
            "note": f"لا لقطات مُقيَّمة بعد — يحتاج التقييم وصول بيانات الشهر التالي. {_DISCLAIMER}",
        }

    n_all = len(per_errors)
    overall = {
        "n_evals": n_all,
        "mae": round(sum(abs(e) for e in per_errors) / n_all, 4),
        "direction_hit_rate": round(sum(dir_hits_all) / n_all, 3),
        "severity_hit_rate": round(sum(sev_hits_all) / n_all, 3),
        "trend": "insufficient",
    }
    if len(months_out) >= 2:
        first, last = months_out[0], months_out[-1]
        diff = last["direction_hit_rate"] - first["direction_hit_rate"]
        if diff >= 0.1:
            overall["trend"] = "improving"
        elif diff <= -0.1:
            overall["trend"] = "declining"
        else:
            overall["trend"] = "stable"
    return {
        "months": months_out,
        "overall": overall,
        "note": (
            "الدقة الحيّة: مقارنة لقطات تنبؤات محفوظة بدرجات الشهور الفعلية عند وصولها "
            f"(إصابة الاتجاه بعتبة ±0.05). {_DISCLAIMER}"
        ),
    }


def _next_months(month: str, count: int) -> List[str]:
    """الشهور القادمة بصيغة YYYY-MM (ليّنة عبر نهاية السنة)."""
    y, m = month.split("-")
    y, m = int(y), int(m)
    out = []
    for i in range(1, count + 1):
        mm = m + i
        yy = y
        while mm > 12:
            mm -= 12
            yy += 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out
