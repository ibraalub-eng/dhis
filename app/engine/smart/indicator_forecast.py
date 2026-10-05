"""تنبؤ بسلوك مؤشر واحد عبر عدة مستشفيات يختارها المستخدم خلال أفق زمني صريح.

المرحلة 4 (طلب المستخدم): «تنبؤ بسلوك مؤشر معيّن خلال الفترة الزمنية على
المستشفيات حيث يمكنني اختيار عدة مستشفيات خلال الفترة الزمنية».

البنية:
- **تعريفات مؤشرات** (INDICATOR_DEFS): مؤشرات مشتقة بصيغ مطابقة تماماً لما
  يحسبه المحرك في xgboost_predictor (cs_rate=5/2×100، stillbirth_rate=sb/6×1000
  — المقام المواليد الأحياء هو التعريف المعتمد في النظام —، preterm/lbw/
  high_risk/adolescent من مقام المواليد الأحياء، total_births عدّاد خام).
- **سلسلة شهرية لكل مستشفى**: من قيم المؤشرات المخزنة مباشرة، والشهر الناقص
  مقامه أو بسطه يُسقط (بيانات ناقصة لا صفر صامت — نفس مبدأ _hospital_rate_series).
- **مسار لكل مستشفى**: نفس منهجية trajectory.py — اتجاه خطي إذا R²≥0.6 وإلا
  متوسط متحرك، نطاق عدم يقين يتسع خطياً مع الأفق، ثقة تتناقص بعوامل الأفق
  (1/3/6 => 1.0/0.85/0.7)، ومزيج 30/30/40 (اتجاه/نظراء/نمط ذاتي) للقيمة
  النهائية كما في blended_indicator_forecast.
- **بلا أي تغيير في مخطط DB**: كل الحساب من IndicatorValue المخزنة.

قواعد الصياغة: كل المخرجات تقديرات إحصائية لا تنبؤ مؤكد، وكل رسالة تنتهي
بإخلاء المسؤولية الإحصائي.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from app.engine.smart.trajectory import (
    HORIZON_FACTORS,
    MA_WINDOW,
    MODEL_MIN_POINTS,
    TREND_R2_THRESHOLD,
    _linear_fit_r2,
    _next_months,
)

# سقف المستشفيات المختارة في الطلب الواحد (حماية أداء: كل مستشفى = مسار كامل)
MAX_INDICATOR_FORECAST_HOSPITALS = 12

_DISCLAIMER = "تقدير إحصائي لا تنبؤ مؤكد."

# ── تعريفات المؤشرات المتاحة للتنبؤ (المفاتيح منطق المحرك، القيم صيغ SQL/ORM) ──
# numerator/denominator: رموز مؤشرات DB. join للمراهقات (2.c + 2.d).
# per-unit: 100 (نسبة) أو 1000 (لكل ألف مولود حي).
# صيغ مطابقة لـ xgboost_predictor._load_multi_month_data و_compute_derived_features.
INDICATOR_DEFS: Dict[str, Dict] = {
    "cs_rate": {
        "label_ar": "معدل العمليات القيصارية",
        "label_en": "C-section rate",
        "unit": "%",
        "numerator": ("5",),
        "denominator": ("2",),
        "per": 100.0,
    },
    "stillbirth_rate": {
        "label_ar": "معدل الولادات الميتة",
        "label_en": "Stillbirth rate",
        "unit": "per 1000",
        "numerator": ("7",),
        "denominator": ("6",),
        "per": 1000.0,
    },
    "preterm_rate": {
        "label_ar": "معدل الولادات المبكرة",
        "label_en": "Preterm birth rate",
        "unit": "%",
        "numerator": ("6.f",),
        "denominator": ("6",),
        "per": 100.0,
    },
    "lbw_rate": {
        "label_ar": "معدل نقص وزن الولادة",
        "label_en": "Low birth weight rate",
        "unit": "%",
        "numerator": ("6.g",),
        "denominator": ("6",),
        "per": 100.0,
    },
    "high_risk_rate": {
        "label_ar": "نسبة حالات الخطر العالي",
        "label_en": "High-risk share",
        "unit": "%",
        "numerator": ("2.n",),
        "denominator": ("6",),
        "per": 100.0,
    },
    "adolescent_rate": {
        "label_ar": "نسبة حالات المراهقات",
        "label_en": "Adolescent share",
        "unit": "%",
        "numerator": ("2.c", "2.d"),
        "denominator": ("6",),
        "per": 100.0,
    },
    "total_births": {
        "label_ar": "إجمالي المواليد الأحياء",
        "label_en": "Total live births",
        "unit": "count",
        "numerator": ("6",),
        "denominator": None,
        "per": 1.0,
    },
}


def available_indicators() -> List[Dict]:
    """كتالوج المؤشرات المتاحة للتنبؤ — ثابت الترتيب وبلا أي استعلام DB."""
    return [
        {"key": k, **{f: d[f] for f in ("label_ar", "label_en", "unit")}}
        for k, d in INDICATOR_DEFS.items()
    ]


def indicator_rate_from_values(indicator: str, values: Dict[str, float]) -> Optional[float]:
    """حساب قيمة مؤشر واحد من قيم رموز DB لشهر/مستشفى واحد.

    يعيد None عند نقص البسط أو المقام (أو مقام ≤ 0) — بيانات ناقصة لا صفر صامت.
    """
    d = INDICATOR_DEFS.get(indicator)
    if d is None:
        raise ValueError(f"مؤشر غير معروف: {indicator}")
    num = 0.0
    for code in d["numerator"]:
        v = values.get(code)
        if v is None:
            return None
        num += float(v)
    if d["denominator"] is None:
        return float(num) * d["per"]
    den = 0.0
    for code in d["denominator"]:
        v = values.get(code)
        if v is None:
            return None
        den += float(v)
    if den <= 0:
        return None
    return num / den * d["per"]


def load_indicator_series(session, indicator: str) -> Dict[str, List]:
    """السلسلة الشهرية للمؤشر لكل المستشفيات النشطة: {اسم المستشفى: [(month, value)]}.

    مصدر واحد IndicatorValue (بلا أي تغيير في المخطط). الشهر الناقص بسطه أو
    مقامه يُسقط من سلسلة المستشفى. مرتبة زمنياً تصاعدياً.
    """
    from app.models import Hospital, Indicator, IndicatorValue

    d = INDICATOR_DEFS.get(indicator)
    if d is None:
        raise ValueError(f"مؤشر غير معروف: {indicator}")

    ind_map = {i.id: i.code for i in session.query(Indicator).all()}
    hosp_names = {h.id: h.name for h in session.query(Hospital).filter(Hospital.is_active).all()}
    needed = set(d["numerator"]) | (set(d["denominator"]) if d["denominator"] else set())

    per: Dict[tuple, Dict[str, float]] = {}
    rows = (
        session.query(IndicatorValue.hospital_id, IndicatorValue.month,
                      IndicatorValue.indicator_id, IndicatorValue.value)
        .filter(IndicatorValue.value.isnot(None))
        .all()
    )
    for hid, m, iid, v in rows:
        code = ind_map.get(iid)
        if code not in needed or hid not in hosp_names:
            continue
        per.setdefault((hid, m), {})[code] = float(v)

    series: Dict[str, List] = {}
    for (hid, m), vals in per.items():
        rate = indicator_rate_from_values(indicator, vals)
        if rate is None:
            continue
        series.setdefault(hosp_names[hid], []).append((m, rate))
    for name in series:
        series[name].sort(key=lambda x: x[0])
    return series


# ── استيراد اختياري للمزيج متعدد المصادر (نفس أوزان early_warning) ──
try:
    from app.engine.smart.early_warning import BLEND_MIN_MONTHS, DEFAULT_WEIGHTS
except ImportError:  # pragma: no cover - early_warning موجود دائماً في هذا المستودع
    BLEND_MIN_MONTHS = 3
    DEFAULT_WEIGHTS = {"trend": 0.3, "peer": 0.3, "self": 0.4}


@dataclass
class _Point:
    month: str
    horizon_month: int
    value: float
    lower: float
    upper: float


def _model_forecast(history: List[float], h: int) -> float:
    """قيمة استمرار النموذج عند الأفق h — نفس قاعدة _choose_model في trajectory.py."""
    n = len(history)
    if n >= MODEL_MIN_POINTS:
        slope, intercept, r2 = _linear_fit_r2(history)
        if r2 >= TREND_R2_THRESHOLD:
            return float(slope * (n - 1 + h) + intercept)
    window = history[-min(MA_WINDOW, n):]
    return float(np.mean(window))


def _choose_model_name(history: List[float]) -> str:
    n = len(history)
    if n >= MODEL_MIN_POINTS:
        _, _, r2 = _linear_fit_r2(history)
        if r2 >= TREND_R2_THRESHOLD:
            return "linear"
    return "moving_average"


def _sigma(history: List[float]) -> float:
    """عرض النطاق الأساسي: IQR تقريبي لبقایا النموذج على التاريخ (0 لنموذج كامل)."""
    if len(history) < MODEL_MIN_POINTS:
        return 0.0
    fitted = [_model_forecast(history[: max(1, i)], 1) for i in range(1, len(history))]
    residuals = [abs(history[i] - fitted[i - 1]) for i in range(1, len(history))]
    residuals = [r for r in residuals if np.isfinite(r)]
    if not residuals:
        return 0.0
    q10, q90 = np.quantile(residuals, 0.1), np.quantile(residuals, 0.9)
    return float(q90 - q10)


def _direction(history: List[float]) -> str:
    """اتجاه السلسلة عبر ميل انحدار خطي — عتبة 1% من آخر قيمة لكل خطوة."""
    if len(history) < 2:
        return "stable"
    slope = float(np.polyfit(np.arange(len(history)), np.asarray(history, dtype=float), 1)[0])
    tol = max(abs(history[-1]) * 0.01, 1e-9)
    if slope > tol:
        return "rising"
    if slope < -tol:
        return "falling"
    return "stable"


def forecast_indicator_trajectory(
    history: List,
    horizon: int,
    peer_mean: Optional[float] = None,
) -> Dict:
    """مسار مؤشر واحد لمستشفى واحد (history: [(month, value)] مرتبة زمنياً).

    - النموذج: خطي إذا R² ≥ 0.6 (و≥4 نقاط) وإلا متوسط متحرك — نفس قاعدة
      trajectory.py. نطاق عدم يقين يتسع خطياً مع الأفق.
    - المزيج النهائي (30/30/40): 0.3×قيمة المسار + 0.3×متوسط النظراء +
      0.4×متوسط النمط الذاتي — غير متاح تحت BLEND_MIN_MONTHS أشهر (نفس
      blended_indicator_forecast).
    - الثقة: 0.9×معامل أفق HORIZON_FACTORS (ثقة النموذج الوصفي أعلى من ثقة
      درجة المخاطرة المجمّعة لكنها تظل تقديراً إحصائياً موثقاً بإخلاء مسؤولية).
    """
    if horizon not in HORIZON_FACTORS:
        raise ValueError(f"أفق غير مدعوم: {horizon} — المسموح: {sorted(HORIZON_FACTORS)}")

    hist = [(str(m), float(v)) for m, v in (history or []) if v is not None]
    if len(hist) < 2:
        # نقطة واحدة لا تكفي لأي استقراء شهري — «غير متاح» لا صفر صامت
        return {
            "available": False, "points": [], "model": "none",
            "confidence": 0.0, "direction": "stable",
            "current": (round(hist[-1][1], 4) if hist else None),
            "note": f"لا يوجد تاريخ كافٍ لبناء مسار (يلزم شهران على الأقل) — {_DISCLAIMER}",
        }
    base_month = hist[-1][0]
    values = [v for _, v in hist]
    model = _choose_model_name(values)
    sigma = _sigma(values)
    months_ahead = _next_months(base_month, horizon)

    cont = [_model_forecast(values, h) for h in range(1, horizon + 1)]
    points = []
    for h, raw in enumerate(cont, 1):
        band = sigma * h
        points.append({
            "month": months_ahead[h - 1], "horizon_month": h,
            "value": round(raw, 4),
            "lower": round(raw - band, 4),
            "upper": round(raw + band, 4),
        })

    # المزيج 30/30/40 للقيمة النهائية (trend=قيمة المسار، peer، self=متوسط التاريخ)
    n_months = len(values)
    self_mean = float(np.mean(values))
    if peer_mean is None or not np.isfinite(peer_mean):
        w = {"trend": 1.0, "peer": 0.0, "self": 0.0}
        if n_months >= BLEND_MIN_MONTHS:
            blend_val = cont[-1]
        else:
            blend_val = None
    else:
        w = dict(DEFAULT_WEIGHTS)
        blend_val = None
        if n_months >= BLEND_MIN_MONTHS:
            blend_val = w["trend"] * cont[-1] + w["peer"] * float(peer_mean) + w["self"] * self_mean
    if blend_val is None:
        blended = {
            "available": False, "n_months": n_months,
            "note": f"المزيج غير متاح بعد: يلزم {BLEND_MIN_MONTHS} أشهر على الأقل.",
        }
    else:
        spread = 0.10 * max(abs(blend_val), 1.0)
        blended = {
            "available": True,
            "forecast": round(float(blend_val), 4),
            "lower": round(float(blend_val - spread), 4),
            "upper": round(float(blend_val + spread), 4),
            "peer_mean": (round(float(peer_mean), 4) if peer_mean is not None else None),
            "self_mean": round(self_mean, 4),
            "weights": dict(w),
            "n_months": n_months,
        }

    note = (
        f"مسار لأفق {horizon} شهر بنموذج "
        f"{'اتجاه خطي' if model == 'linear' else 'متوسط متحرك'}؛ "
        f"النطاق يتسع مع الأفق. {_DISCLAIMER}"
    )
    return {
        "available": True,
        "model": model,
        "confidence": round(0.9 * HORIZON_FACTORS[horizon], 4),
        "direction": _direction(values),
        "current": round(values[-1], 4),
        "points": points,
        "blended": blended,
        "note": note,
    }


def run_indicator_forecast(
    session,
    month: str,
    indicator: str,
    hospital_ids: List[int],
    horizon: int,
) -> Dict:
    """تنبؤ مؤشر واحد لعدة مستشفيات يختارها المستخدم — نقطة الدخول للـ endpoint.

    - الشهر الأساس: المطلوب إن توفر، وإلا آخر شهر متوفر (وقوع احتياطي صريح
      يظهر في الاستجابة base_month + fallback_used).
    - كل مستشفى مختار يظهر إما في hospitals (مساره) أو unavailable (السبب).
    - متوسط النظراء للمزيج: متوسط آخر قيمة للمستشفيات المختارة الأخرى ذات
      التاريخ الكافي.
    """
    if indicator not in INDICATOR_DEFS:
        raise ValueError(f"مؤشر غير معروف: {indicator}")
    if horizon not in HORIZON_FACTORS:
        raise ValueError(f"أفق غير مدعوم: {horizon} — المسموح: {sorted(HORIZON_FACTORS)}")

    d = INDICATOR_DEFS[indicator]
    series = load_indicator_series(session, indicator)

    all_months = sorted({m for pts in series.values() for m, _ in pts})
    base = month if month in all_months else (all_months[-1] if all_months else month)
    fallback_used = base != month

    from app.models import Hospital
    id_to_name = {h.id: h.name for h in session.query(Hospital).filter(Hospital.is_active).all()}

    hospitals_out: List[Dict] = []
    unavailable: List[Dict] = []

    # قيم الأساس لكل مستشفى مختار (لحساب متوسط النظراء داخل الاختيار)
    base_vals: Dict[int, float] = {}
    selected = []
    for hid in hospital_ids:
        name = id_to_name.get(hid)
        if name is None:
            unavailable.append({"hospital_id": hid, "reason": "المستشفى غير موجود أو غير نشط."})
            continue
        pts = [(m, v) for m, v in (series.get(name) or []) if m <= base]
        if not pts or pts[-1][0] != base:
            unavailable.append({
                "hospital_id": hid, "hospital_name": name,
                "reason": f"لا توجد بيانات كافية لهذا المؤشر في {base}.",
            })
            continue
        selected.append((hid, name, pts))
        base_vals[hid] = pts[-1][1]

    for hid, name, pts in selected:
        others = [v for h2, v in base_vals.items() if h2 != hid]
        peer_mean = float(np.mean(others)) if others else None
        out = forecast_indicator_trajectory(pts, horizon, peer_mean=peer_mean)
        hospitals_out.append({
            "hospital_id": hid,
            "hospital_name": name,
            "series": [{"month": m, "value": round(v, 4)} for m, v in pts],
            **out,
        })

    hospitals_out.sort(key=lambda r: -(r["points"][-1]["value"] if r["points"] else -1e18))
    note = (
        f"تنبؤ {d['label_ar']} لأفق {horizon} شهر لعدة مستشفيات مختارة — "
        f"كل المسارات تقديرات إحصائية لا تنبؤ مؤكد، والنطاق يتسع مع الأفق. {_DISCLAIMER}"
    )
    return {
        "month": month,
        "base_month": base,
        "fallback_used": fallback_used,
        "horizon": horizon,
        "indicator": indicator,
        "indicator_ar": d["label_ar"],
        "indicator_en": d["label_en"],
        "unit": d["unit"],
        "hospitals": hospitals_out,
        "unavailable": unavailable,
        "note": note,
    }
