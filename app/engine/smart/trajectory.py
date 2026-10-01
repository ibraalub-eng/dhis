"""مسار التنبؤ بدرجة المخاطرة عبر آفاق زمنية صريحة (1/3/6 أشهر).

المرحلة 1 من الخطة المعتمدة (البند 1.1):
- استقراء شهراً بشهر بنموذج بسيط مختار تلقائياً: **اتجاه خطي** إذا كانت
  السلسلة منتظمة (R² للملاءمة الخطية ≥ العتبة)، و**متوسط متحرك** إذا كانت
  متقلبة أو قصيرة — قاعدة صريحة مُختبَرة.
- المسار مثبَّت (anchored) على تنبؤ XGBoost المتحقَّق منه (walk-forward)
  للشهر m+1 حيثما توفر: الشهر الأول يأخذ قيمة التنبؤ وتستمر بقية الأشهر
  على زخم النموذج نفسه.
- نطاق عدم يقين P10–P90 مشتق من أخطاء walk-forward/backtest ويتسع خطياً
  مع الأفق (±h·σ)، وثقة تتناقص بعامل لكل أفق (m+1 كاملة، 3 أشهر ×0.85،
  6 أشهر ×0.7).
- عبور عتبات الخطورة (0.3 تحذير / 0.6 حرج — حدود _score_to_severity)
  يُدار داخل الأفق المختار فقط ولا يُجزم ما بعده.
- backtest لكل أفق: يُقيَّم الإسقاط على قيم فعلية ماضية (نافذة موسّعة
  بلا تسريب)، ويتطلب ≥ 6 أشهر وإلا يُعلَن «غير متاح بعد لهذا الأفق».

قواعد الصياغة: كل المخرجات تقديرات إحصائية لا تنبؤ مؤكد — تُرفق دائماً
بإخلاء مسؤولية ولا تُعرض كيقين، والدرجة مئين نسبي لا تشخيص مطلق.
"""
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.engine.smart.anomaly import FEATURE_KEYS
from app.engine.smart.xgboost_predictor import _score_to_severity

# عامل الثقة لكل أفق: m+1 كاملة، 3 أشهر ×0.85، 6 أشهر ×0.7 (الخطة 1.1)
HORIZON_FACTORS = {1: 1.0, 3: 0.85, 6: 0.7}

# الحد الأدنى لأشهر backtest الأفق (الخطة 1.1: «يتطلب ≥ 6 أشهر وإلا غير متاح»)
BACKTEST_MIN_MONTHS = 6

# أقل عدد نقاط لملاءمة خط (أقل من ذلك => متوسط متحرك حكماً)
MODEL_MIN_POINTS = 4

# نافذة المتوسط المتحرك
MA_WINDOW = 3

# عتبة R² التي تعتبر السلسلة «منتظمة» تستحق اتجاهاً خطياً
TREND_R2_THRESHOLD = 0.6

# حدود فئات الخطورة (من _score_to_severity: <0.3 normal، <0.6 warning، وإلا critical)
_SEVERITY_ORDER = ["normal", "warning", "critical"]
_SEVERITY_THRESHOLDS = ((0.3, "warning"), (0.6, "critical"))

_DISCLAIMER = "تقدير إحصائي لا تنبؤ مؤكد."

_MODEL_AR = {
    "linear": "اتجاه خطي",
    "moving_average": "متوسط متحرك",
    "none": "غير محدد",
}


@dataclass
class TrajectoryPoint:
    """نقطة واحدة في مسار التنبؤ: شهر مستقبلي بقيمة ونطاق."""
    month: str
    horizon_month: int          # 1 = الشهر التالي للأساس
    value: float
    lower: float                # حد النطاق الأدنى (P10 تقريبي)
    upper: float                # حد النطاق الأعلى (P90 تقريبي)


@dataclass
class ThresholdCrossing:
    """تقدير عبور عتبة خطورة داخل الأفق المختار."""
    severity: str               # warning / critical
    month: str                  # الشهر المتوقع للعبور
    months_away: int            # كم شهراً من الشهر الأساس
    from_threshold: float       # العتبة العابرة (0.3 أو 0.6)


@dataclass
class BacktestResult:
    """دقة الإسقاط لهذا الأفق على قيم فعلية ماضية."""
    available: bool
    n_evals: int
    mae: float
    note: str


@dataclass
class RiskTrajectory:
    """مسار درجة المخاطرة لمستشفى حتى أفق محدد."""
    hospital_name: str
    base_month: str
    horizon: int
    model: str
    anchor_applied: bool        # هل ثُبِّت على تنبؤ XGBoost؟
    confidence: float           # ثقة متناقصة مع الأفق
    points: List[TrajectoryPoint] = field(default_factory=list)
    threshold_crossing: Optional[ThresholdCrossing] = None
    backtest: BacktestResult = field(default_factory=lambda: BacktestResult(False, 0, 0.0, ""))
    note: str = ""


def _next_months(month: str, count: int) -> List[str]:
    """الشهور القادمة بعد month بصيغة YYYY-MM (ليّنة عبر نهاية السنة)."""
    year, mon = month.split("-")
    y, m = int(year), int(mon)
    out = []
    for i in range(1, count + 1):
        mm = m + i
        yy = y
        while mm > 12:
            mm -= 12
            yy += 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _linear_fit_r2(series: List[float]) -> Tuple[float, float, float]:
    """ملاءمة خطية بسيطة: تعيد (الميل، التقاطع، R²). سلسلة ثابتة => R²=0."""
    y = np.asarray(series, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), float(intercept), float(r2)


def _choose_model(series: List[float]) -> str:
    """اختيار النموذج بقاعدة صريحة: خطي إذا R² ≥ العتبة وإلا متوسط متحرك.

    - أقل من 4 نقاط => متوسط متحرك (لا معنى لملاءمة خط).
    - سلسلة ثابتة (تباين صفري) => متوسط متحرك لا خط وهمي.
    - القاعدة تعتمد R² للملاءمة الخطية على المستويات (وليس CV على التنبؤ)
      لأن السلسلة الصاعدة بانتظام قد «يُخطئها» تنبؤ ثابت رغم كمال اتجاهها.
    """
    if len(series) < MODEL_MIN_POINTS:
        return "moving_average"
    _, _, r2 = _linear_fit_r2(series)
    if r2 >= TREND_R2_THRESHOLD:
        return "linear"
    return "moving_average"


def _model_forecast(history: List[float], h: int) -> float:
    """قيمة استمرار النموذج عند الأفق h (شهور بعد آخر نقطة في history).

    خطي: امتداد المستقيم المُلائم. متوسط متحرك: متوسط آخر نافذة (ثابت).
    """
    model = _choose_model(history)
    n = len(history)
    if model == "linear" and n >= MODEL_MIN_POINTS:
        slope, intercept, _ = _linear_fit_r2(history)
        return slope * (n - 1 + h) + intercept
    window = history[-min(MA_WINDOW, n):]
    return float(np.mean(window))


def _band_sigma(fold_errors: Optional[List[float]]) -> float:
    """عرض النطاق الأساسي: P90−P10 للأخطاء المطلقة الموثقة (0 إن لا أخطاء)."""
    errs = sorted(abs(float(e)) for e in (fold_errors or [])
                  if e is not None and np.isfinite(e))
    if not errs:
        return 0.0
    return float(np.quantile(errs, 0.9) - np.quantile(errs, 0.1))


def _detect_threshold_crossing(
    base_last: float, points: List[TrajectoryPoint],
) -> Optional[ThresholdCrossing]:
    """أول عبور عتبة «أشد» من خطورة الأساس، داخل نقاط الأفق فقط."""
    base_sev = _score_to_severity(base_last)
    base_rank = _SEVERITY_ORDER.index(base_sev)
    for p in points:
        v = round(p.value, 6)
        for thr, sev in _SEVERITY_THRESHOLDS:
            if _SEVERITY_ORDER.index(sev) > base_rank and v >= thr:
                return ThresholdCrossing(
                    severity=sev, month=p.month,
                    months_away=p.horizon_month, from_threshold=thr,
                )
    return None


def _backtest(history: List[float], horizon: int) -> BacktestResult:
    """دقة الإسقاط لهذا الأفق: لكل شهر ماضٍ t (بتاريخ كافٍ) يُسقَط من t
    ويُقاس الخطأ عند t+h مقابل القيمة الفعلية — نافذة موسّعة بلا تسريب.
    يتطلب ≥ 6 أشهر (والأفق + حد التدريب) وإلا «غير متاح بعد»."""
    n = len(history)
    min_needed = max(BACKTEST_MIN_MONTHS, horizon + MODEL_MIN_POINTS)
    if n < min_needed:
        return BacktestResult(
            available=False, n_evals=0, mae=0.0,
            note=f"دقة هذا الأفق غير متاح بعد: يلزم {min_needed} شهراً على الأقل (المتوفر {n}).",
        )
    errs = []
    for t in range(MODEL_MIN_POINTS - 1, n - horizon):
        forecast = _model_forecast(history[:t + 1], horizon)
        errs.append(abs(history[t + horizon] - forecast))
    mae = float(np.mean(errs)) if errs else 0.0
    return BacktestResult(
        available=True, n_evals=len(errs), mae=round(mae, 4),
        note=f"backtest لهذا الأفق عبر {len(errs)} تقييماً على قيم فعلية (MAE={mae:.3f}).",
    )


def compute_risk_trajectory(
    hospital_name: str,
    history_scores: List[float],
    base_month: str,
    horizon: int,
    xgb_anchor: Optional[float] = None,
    fold_errors: Optional[List[float]] = None,
    base_confidence: float = 0.5,
) -> RiskTrajectory:
    """بناء مسار درجة المخاطرة شهراً بشهر حتى الأفق المختار.

    xgb_anchor: تنبؤ XGBoost المتحقَّق منه لدرجة الشهر m+1 — يثبِّت النقطة
    الأولى ويُرحِّل زخم النموذج على ما بعدها. fold_errors: أخطاء التحقق
    الزمني المطلقة التي يُشتق منها عرض النطاق.
    """
    if horizon not in HORIZON_FACTORS:
        raise ValueError(f"أفق غير مدعوم: {horizon} — المسموح: {sorted(HORIZON_FACTORS)}")

    months = _next_months(base_month, horizon)
    history = [float(s) for s in (history_scores or [])
               if s is not None and np.isfinite(s)]
    sigma = _band_sigma(fold_errors)
    base_conf = min(max(float(base_confidence), 0.0), 1.0)

    if not history:
        return RiskTrajectory(
            hospital_name=hospital_name, base_month=base_month, horizon=horizon,
            model="none", anchor_applied=False, confidence=0.0, points=[],
            threshold_crossing=None,
            backtest=BacktestResult(False, 0, 0.0, "لا يوجد تاريخ كافٍ لبناء مسار."),
            note=f"لا يوجد تاريخ كافٍ — {_DISCLAIMER}",
        )

    model = _choose_model(history)
    confidence = round(base_conf * HORIZON_FACTORS[horizon], 4)

    # استمرار النموذج لكل شهر في الأفق، ثم التثبيت على تنبؤ XGBoost إن وُجد:
    # النقطة الأولى تأخذ قيمة التنبؤ، وما بعدها يحمل زخم النموذج نفسه.
    cont = [_model_forecast(history, h) for h in range(1, horizon + 1)]
    if xgb_anchor is not None:
        a = min(max(float(xgb_anchor), 0.0), 1.0)
        values = [a + (c - cont[0]) for c in cont]
        anchor_applied = True
    else:
        values = cont
        anchor_applied = False

    points = []
    for h, raw in enumerate(values, 1):
        v = min(max(raw, 0.0), 1.0)
        band = sigma * h  # النطاق يتسع خطياً مع الأفق
        points.append(TrajectoryPoint(
            month=months[h - 1], horizon_month=h, value=round(v, 4),
            lower=round(min(max(v - band, 0.0), 1.0), 4),
            upper=round(min(max(v + band, 0.0), 1.0), 4),
        ))

    crossing = _detect_threshold_crossing(history[-1], points)
    backtest = _backtest(history, horizon)
    note = (
        f"مسار لأفق {horizon} شهر بنموذج {_MODEL_AR.get(model, model)}؛ "
        f"النطاق P10–P90 من أخطاء التحقق الزمني ويتسع مع الأفق. {_DISCLAIMER}"
    )

    return RiskTrajectory(
        hospital_name=hospital_name, base_month=base_month, horizon=horizon,
        model=model, anchor_applied=anchor_applied, confidence=confidence,
        points=points, threshold_crossing=crossing, backtest=backtest, note=note,
    )


def _month_median(values: Dict[str, float]) -> float:
    """وسيط مفاتيح الميزات الأساسية لشهر واحد — نفس تعريف المحرك (NaN إن نقصت)."""
    vals = [values.get(k, np.nan) for k in FEATURE_KEYS]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        med = np.nanmedian(vals)
    med = float(med)
    return med if not np.isnan(med) else float("nan")


def _score_chain(medians: List[float]) -> List[float]:
    """سلسلة درجات المخاطرة من وسطوط الأشهر — بنفس صيغة _compute_target_scores.

    الدرجة = 0.5 + (cur/prev − 1)×2 مقيّدة [0,1]؛ الشهر الأول بلا سابق
    => 0.5 اصطناعي (لا يُستخدم في المسار — نبدأ من أول درجة حقيقية).
    """
    scores = []
    prev: Optional[float] = None
    for med in medians:
        if prev is None or not (prev > 0):
            s = 0.5
        else:
            s = min(max(0.5 + (med / prev - 1.0) * 2.0, 0.0), 1.0)
        scores.append(s)
        prev = med
    return scores


def run_forecast_trajectory(
    session,
    month: str,
    horizon: int,
    xgb_predictions=None,
    fold_errors: Optional[List[float]] = None,
    base_confidence: float = 0.5,
) -> Dict[str, object]:
    """مسارات التنبؤ لكل المستشفيات النشطة ذات بيانات في الشهر الأساس.

    يعيد قاموساً: base_month (الشهر الأساس الفعلي بعد الوقوع الاحتياطي إلى
    آخر شهر متوفر)، horizon، trajectories (مرتبة تنازلياً بالقيمة المتوقعة
    الأخيرة — الأخطر أولاً)، وnote بإخلاء المسؤولية الإحصائي.
    """
    if horizon not in HORIZON_FACTORS:
        raise ValueError(f"أفق غير مدعوم: {horizon} — المسموح: {sorted(HORIZON_FACTORS)}")

    from app.models import IndicatorValue
    from app.engine.smart.xgboost_predictor import _load_multi_month_data

    all_months = sorted(
        r[0] for r in session.query(IndicatorValue.month).distinct().all()
    )
    if not all_months:
        return {"base_month": month, "horizon": horizon,
                "trajectories": [], "note": f"لا توجد بيانات — {_DISCLAIMER}"}

    base = month if month in all_months else all_months[-1]
    all_rows, _ = _load_multi_month_data(session, all_months)

    per_hosp: Dict[str, List[Tuple[str, float]]] = {}
    for row in all_rows:
        med = _month_median(row["values"])
        if med is None or not np.isfinite(med):
            continue  # بيانات الشهر ناقصة لهذا المستشفى
        if med <= 0:
            # صفوف المحرك اللائمة بلا أي قيم (المستشفى لم يُبلّغ هذا الشهر)
            # تعيد وسطاً صفرياً من _load_multi_month_data — تصنف بيانات مفقودة
            # لا شهراً حقيقياً بدرجة 0.5، وإلا انحشرت بيانات المستشفى الزمنية.
            continue
        per_hosp.setdefault(row["hospital_name"], []).append((row["month"], med))

    anchors: Dict[str, float] = {}
    if xgb_predictions is not None:
        for p in getattr(xgb_predictions, "predictions", None) or []:
            anchors[p.hospital_name] = float(p.predicted_next_score)

    trajectories: List[RiskTrajectory] = []
    for name, month_meds in per_hosp.items():
        month_meds.sort(key=lambda x: x[0])
        month_meds = [(m, v) for m, v in month_meds if m <= base]
        if not month_meds or month_meds[-1][0] != base:
            continue  # لا بيانات لهذا المستشفى في الشهر الأساس
        history = _score_chain([v for _, v in month_meds])[1:]
        trajectories.append(compute_risk_trajectory(
            name, history, base, horizon,
            xgb_anchor=anchors.get(name),
            fold_errors=fold_errors,
            base_confidence=base_confidence,
        ))

    trajectories.sort(
        key=lambda t: (t.points[-1].value if t.points else -1.0), reverse=True,
    )
    note = (
        "المسار مثبت على تنبؤ XGBoost المتحقق منه حيثما توفر؛ الدقة لكل أفق "
        f"من backtest على قيم فعلية. {_DISCLAIMER}"
    )
    return {"base_month": base, "horizon": horizon,
            "trajectories": trajectories, "note": note}
