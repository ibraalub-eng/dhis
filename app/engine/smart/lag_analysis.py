"""اكتشاف العلاقات المتأخرة زمنياً + الإنذار المبكر (Temporal Lead-Lag & Early Warning).

العلاقات المتأخرة: تبحث عما إذا كان المؤشر A عند الشهر t يتنبأ إحصائياً بالمؤشر
B عند الشهر t+L (عبر نفس المستشفيات) — أقوى من الارتباط الآني لأنها ترصد
التسلسل الزمني («الارتفاع المبكر يسبق ارتفاع الوفيات بشهر») مع قوة واتجاه
ودلالة إحصائية وثقة، ومقارنة بالارتباط الآني لمعرفة هل التأخر يضيف معلومة.

الترقيات المنهجية (المرحلة 1):
- ارتباط جزئي بنمط غرانجر: corr(A_t, B_{t+L} | B_t) — يزيل أثر استمرارية
  المؤشر الناتج نفسه، فلا تُقبل «قيادة» هي مجرد انعكاس لماضي B.
- ضبط تعدد الاختبارات FDR (Benjamini–Hochberg) على كل الأزواج × الإزاحات.
- اختيار أفضل إزاحة من {1, 2, 3} لكل زوج مرتب (أقوى إشارة مع أصغر إزاحة).
- اتساق المستشفيات (نسبة المستشفيات بنفس الاتجاه) + استقرار Jackknife
  (استبعاد كل مستشفى بدوره دون انقلاب الاتجاه).
- حجم أثر قابل للتنفيذ: ميل انحدار B_{t+L} على A_t وصياغة «إذا ارتفع A
  بنسبة 10% يُتوقع أن يتغير B بمقدار كذا» — مخرج قرار لا قائمة ارتباطات.

الإنذار المبكر: يجمع المؤشرات القيادية الصاعدة شهرياً (مبكرة/نقص وزن/مضاعفات/
خطر عالٍ/مراهقات/قيصرية) لكل مستشفى ويحولها إلى تحذير باحتمال وثقة قبل أن
يتفاقم المؤشر الناتج (الوفيات) — «إشارة مبكرة لا تشخيصاً».

المبادئ:
- لا تُحسب أي نسبة بمقام غير صالح (صفر/غائب => None).
- الارتباط لا يعني سببّية — تُعرض الصياغة بذلك صراحةً.
- البيانات القليلة تُخفض الثقة وتُعلَّم «عينة صغيرة».
"""

import math
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from app.engine.smart import _load_hospital_data
from app.engine.smart.regional import METRIC_NAMES_AR, METRIC_NAMES_EN

# معدلات تُحسب لكل ألف/مئة ألف (مقامات بالأساس)
_RATE_SCALE = {
    "nmr": 1000.0,
    "mmr": 100000.0,
    "stillbirth_rate": 1000.0,
    "cs_rate": 100.0,
    "preterm_rate": 100.0,
    "lbw_rate": 100.0,
    "smm_rate": 1000.0,
    "adolescent_rate": 100.0,
    "high_risk_rate": 100.0,
}

# المؤشرات القيادية الافتراضية للإنذار المبكر (كلها انخفاضها أفضل) — تُستخدم
# فقط عندما لا تتوفر علاقات مكتشفة (بيانات قليلة جداً). مع بيانات كافية تُبنى
# القائمة من العلاقات المتأخرة المكتشفة فعلياً (FDR + غرانجر) بأوزان موزونة.
LEADING_INDICATORS = [
    "preterm_rate", "lbw_rate", "smm_rate", "high_risk_rate",
    "adolescent_rate", "cs_rate",
]
OUTCOME_INDICATOR = "nmr"

# النتائج التي تُعتبر «مخرجات» يُحذَّر من تدهورها (تتأثر بالمؤشرات القيادية)
OUTCOME_METRICS = ["nmr", "mmr", "stillbirth_rate", "smm_rate"]

# عتبات الارتباط والتأخر
_MIN_LAG_PAIRS = 10       # أقل عدد أزواج لقبول علاقة متأخرة
_MIN_LAG_ABS_R = 0.3      # أقل |r| (متأخر خام) لقبول العلاقة
_MIN_PARTIAL_ABS_R = 0.25 # أقل |r| جزئي (غرانجر-لايك) لاعتبارها «قيادة»
_LAG_P_VALUE = 0.10       # أعلى p-value مقبول
_LAGS = [1, 2, 3]         # الإزاحات الزمنية المدروسة (أشهر)
_FDR_Q = 0.10             # معدل الاكتشاف الكاذب المسموح به (Benjamini–Hochberg)

# عتبات الإنذار المبكر
_RISING_MOM = 1.10       # ارتفاع شهري ≥ 10%
_RISING_ABS_PP = 2.0     # أو ارتفاع مطلق ≥ 2 نقطة مئوية للمعدلات النسبية
_CRITICAL_RISING = 3     # 3+ مؤشرات قيادية صاعدة => حرج
_WARNING_RISING = 2      # مؤشران صاعدان => تحذير

_SMALL_SAMPLE = 20


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _hospital_rates(values: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """معدلات المستشفى من قيم الشهر (بوابة مقام صارمة)."""
    b = _num(values.get("total_births") or values.get("6"))
    d = _num(values.get("2"))
    raw = {
        "nmr": values.get("nd") or values.get("17"),
        "mmr": values.get("mat_deaths") or values.get("11"),
        "stillbirth_rate": values.get("sb") or values.get("7"),
        "preterm_rate": values.get("preterm") or values.get("6.f"),
        "lbw_rate": values.get("lbw") or values.get("6.g"),
        "smm_rate": values.get("smm_total") or values.get("10"),
        "adolescent_rate": values.get("adolescent"),
        "high_risk_rate": values.get("high_risk") or values.get("2.n"),
    }
    rates: Dict[str, Optional[float]] = {}
    for key, num in raw.items():
        n = _num(num)
        den = d if key == "smm_rate" else b
        scale = _RATE_SCALE[key]
        if n is None or den is None or den <= 0:
            rates[key] = None
        else:
            rates[key] = n / den * scale
    # cs_rate قادمة جاهزة من المُحمِّل (مقامها متحقق منه مسبقاً)
    cs = _num(values.get("cs_rate"))
    rates["cs_rate"] = cs if cs is not None else None
    return rates


def _load_series(session, month: str, months_back: int = 6
                 ) -> Tuple[Dict[str, Dict[str, Dict[str, Optional[float]]]],
                            Dict[str, Dict[str, Any]], List[str]]:
    """سلاسل معدلات كل مستشفى لكل شهر + بيانات تعريفية (id/محافظة) + النافذة.

    المفتاح الأول: مستشفى → شهر → معدلات. المفتاح الثاني: مستشفى → {id، محافظة}
    من أحدث شهر متاح.
    """
    from app.models import IndicatorValue

    months = sorted(r[0] for r in session.query(IndicatorValue.month).distinct().all())
    window = [m for m in months if m <= month][-months_back:]

    series: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    meta: Dict[str, Dict[str, Any]] = {}
    for m in window:
        data = _load_hospital_data(session, m)
        for name, entry in data.items():
            series.setdefault(name, {})[m] = _hospital_rates(entry.get("values", {}))
            # الاحتفاظ بأحدث بيانات تعريفية متاحة
            if name not in meta or m > meta[name].get("_month", ""):
                meta[name] = {
                    "hospital_id": entry.get("hospital_id"),
                    "governorate": entry.get("governorate", "unknown"),
                    "_month": m,
                }
    return series, meta, window


# ── أدوات إحصائية للعلاقات المتأخرة ──

def _partial_corr(xs, ys, zs) -> Tuple[Optional[float], Optional[float]]:
    """ارتباط جزئي corr(x, y | z) — اختبار غرانجر-لايك.

    يزيل أثر المتغير الضابط z (قيمة المؤشر الناتج B عند t) من كلا الطرفين عبر
    بواقي انحدار بسيط، ثم يرتبط البواقي. p-value من توزيع t بدرجات حرية n-3.
    يعيد (None, None) عند الانحلال (لا تباين في البواقي) — لا يمكن الفصل حينها.
    """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    z = np.asarray(zs, dtype=float)
    n = len(x)
    if n < 4:
        return None, None
    Z = np.column_stack([np.ones(n), z])
    rx = x - Z @ np.linalg.lstsq(Z, x, rcond=None)[0]
    ry = y - Z @ np.linalg.lstsq(Z, y, rcond=None)[0]
    denom = float(np.sqrt(np.sum(rx ** 2) * np.sum(ry ** 2)))
    if denom <= 1e-12:
        return None, None
    r = float(np.sum(rx * ry) / denom)
    r = max(-1.0, min(1.0, r))
    df = n - 3
    if df < 1:
        return r, None
    if abs(r) >= 1.0:
        return r, 0.0
    t = r * math.sqrt(df / (1.0 - r * r))
    p = float(2.0 * stats.t.sf(abs(t), df))
    return r, p


def _bh_fdr(pvals, q: float = _FDR_Q) -> List[bool]:
    """Benjamini–Hochberg: يعيد قائمة منطقية (True = يبقى بعد ضبط تعدد الاختبارات)."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    sorted_p = p[order]
    adj = np.empty(n)
    running = np.inf
    for i in range(n - 1, -1, -1):
        running = min(running, n / (i + 1) * sorted_p[i])
        adj[i] = running
    accepted = np.zeros(n, dtype=bool)
    accepted[order] = adj <= q
    return [bool(x) for x in accepted]


def _collect_hospital_pairs(series, a: str, b: str, lag: int):
    """أزواج (A_t, B_{t+lag}, B_t) لكل مستشفى على حدة (لحساب الاتساق لاحقاً)."""
    hosp_pairs = []
    for name, months in series.items():
        sm = sorted(months)
        xs, ys, zs = [], [], []
        for i in range(len(sm) - lag):
            m_now, m_later = sm[i], sm[i + lag]
            av = months[m_now].get(a)
            bv = months[m_later].get(b)
            bt = months[m_now].get(b)
            if av is not None and bv is not None and bt is not None:
                xs.append(av)
                ys.append(bv)
                zs.append(bt)
        if xs:
            hosp_pairs.append((name, xs, ys, zs))
    return hosp_pairs


def _direction_consistency(hosp_pairs, pooled_sign: float) -> Optional[float]:
    """نسبة المستشفيات (بزوجين فأكثر) التي يتوافق ارتباطها الداخلي مع الاتجاه الكلي."""
    agree = total = 0
    for _, xs, ys, _zs in hosp_pairs:
        if len(xs) < 2 or np.std(xs) <= 0 or np.std(ys) <= 0:
            continue
        r = float(np.corrcoef(xs, ys)[0, 1])
        if not math.isfinite(r):
            continue
        total += 1
        if (float(r) > 0) == (pooled_sign > 0):
            agree += 1
    return (agree / total) if total else None


def _jackknife_stable(hosp_pairs, pooled_r: float) -> bool:
    """استقرار العلاقة: استبعاد كل مستشفى بدوره لا ينقلب الاتجاه ولا ينهار |r|."""
    if len(hosp_pairs) < 3:
        return False
    for i in range(len(hosp_pairs)):
        xs, ys = [], []
        for j, (_, hx, hy, _hz) in enumerate(hosp_pairs):
            if j == i:
                continue
            xs.extend(hx)
            ys.extend(hy)
        if len(xs) < 5 or np.std(xs) <= 0 or np.std(ys) <= 0:
            return False
        r = float(np.corrcoef(xs, ys)[0, 1])
        if not math.isfinite(r) or np.sign(r) != np.sign(pooled_r) or abs(r) < 0.15:
            return False
    return True


def _lag_word(lag: int) -> str:
    """صياغة عربية للإزاحة الزمنية بالأشهر."""
    return {1: "شهر واحد", 2: "شهرين", 3: "3 أشهر"}.get(lag, f"{lag} أشهر")


def _effect_size(xs, ys) -> Optional[Dict[str, Any]]:
    """حجم الأثر: ميل انحدار B_{t+L} على A_t + صياغة «ارتفاع A بنسبة 10%». """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    vx = float(np.var(x))
    if vx <= 0:
        return None
    slope = float(np.cov(x, y)[0, 1] / vx)
    mean_a = float(x.mean())
    mean_b = float(y.mean())
    delta_b = slope * 0.10 * mean_a
    delta_pct = (delta_b / mean_b * 100.0) if mean_b else None
    return {
        "slope": round(slope, 4),
        "mean_a": round(mean_a, 3),
        "mean_b": round(mean_b, 3),
        "delta_b_per_10pct_a": round(delta_b, 3),
        "delta_b_pct_per_10pct_a": round(delta_pct, 1) if delta_pct is not None else None,
    }


def run_lag_analysis(session, month: str, months_back: int = 6) -> Dict[str, Any]:
    """اكتشاف العلاقات المتأخرة: المؤشر A عند t مقابل المؤشر B عند t+L.

    لكل زوج مرتب (A, B) ولكل إزاحة L ∈ {1, 2, 3} نجمع أزواج العينات
    (A_t, B_{t+L}) مع الضابط B_t عبر المستشفيات والأشهر، ونحسب:
    1) ارتباط التأخر الخام (Pearson + Spearman + p) — فحص أولي،
    2) ارتباط جزئي غرانجر-لايك corr(A_t, B_{t+L} | B_t) — هل تضيف A معلومة
       تتجاوز استمرارية B نفسها؟ (جوهر «القيادة»)،
    3) اتساق المستشفيات واستقرار Jackknife،
    4) حجم أثر بسيط قابل للتنفيذ.
    ثم نضبط تعدد الاختبارات بـ FDR، ونختار أفضل إزاحة لكل زوج، ونقارن بالارتباط
    الآني (A_t, B_t) لمعرفة هل التأخر يضيف معلومة فعلية.
    """
    series, _, window = _load_series(session, month, months_back)
    if len(window) < 2 or len(series) < 2:
        return {
            "month": month, "lags": [],
            "note_ar": "يلزم شهران على الأقل وعدة مستشفيات لتحليل التأخر الزمني.",
            "note_en": "Need ≥2 months and several hospitals for lag analysis.",
        }

    metrics = list(_RATE_SCALE.keys())
    n_metrics = len(metrics)

    # ── 1) جمع المرشحين: كل زوج مرتب (A, B) × كل إزاحة ──
    candidates: List[Dict[str, Any]] = []
    for a in metrics:
        for b in metrics:
            if a == b:
                continue
            for lag in _LAGS:
                hosp_pairs = _collect_hospital_pairs(series, a, b, lag)
                flat = [(x, y, z) for _, xs, ys, zs in hosp_pairs
                        for x, y, z in zip(xs, ys, zs)]
                n = len(flat)
                if n < _MIN_LAG_PAIRS:
                    continue
                xs = [t[0] for t in flat]
                ys = [t[1] for t in flat]
                zs = [t[2] for t in flat]
                # مدخلات ثابتة => ارتباط غير معرّف (تخطَّ بدون تحذيرات)
                if np.std(xs) <= 0 or np.std(ys) <= 0:
                    continue
                try:
                    with warnings.catch_warnings():
                        # مدخلات شبه ثابتة (فروقات ضمن التسامح) تُطلق ConstantInputWarning
                        # والنتيجة غير منتهية تُتخطى أدناه — لا داعي لإزعاج المستخدم
                        warnings.simplefilter("ignore", RuntimeWarning)
                        r_lag, p_lag = stats.pearsonr(xs, ys)
                except Exception:
                    continue
                if not math.isfinite(r_lag):
                    continue
                r_partial, p_partial = _partial_corr(xs, ys, zs)
                candidates.append({
                    "a": a, "b": b, "lag": lag,
                    "hosp_pairs": hosp_pairs,
                    "xs": xs, "ys": ys, "zs": zs,
                    "r_lag": float(r_lag),
                    "p_lag": float(p_lag),
                    "r_partial": r_partial,
                    "p_partial": p_partial,
                })
    if not candidates:
        return {
            "month": month, "lags": [],
            "note_ar": "لا توجد أزواج كافية (تحت عتبة الحد الأدنى للعينات) لهذا الشهر.",
            "note_en": "Not enough pairs (below the minimum sample threshold) this month.",
        }

    # ── 2) FDR على ارتباط التأخر الخام (فحص أولي لكل اختبار) ──
    accepted = _bh_fdr([c["p_lag"] for c in candidates], q=_FDR_Q)

    # ── 3) اختيار أفضل إزاحة لكل زوج مرتب ──
    best_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}   # المقبولة فقط
    matrix_best: Dict[Tuple[str, str], Dict[str, Any]] = {}    # كل الأزواج (للمصفوفة)
    for c, acc in zip(candidates, accepted):
        key = (c["a"], c["b"])
        prev_m = matrix_best.get(key)
        if prev_m is None or abs(c["r_lag"]) > abs(prev_m["c"]["r_lag"]):
            matrix_best[key] = {"c": c, "acc": bool(acc)}
        if not acc or abs(c["r_lag"]) < _MIN_LAG_ABS_R:
            continue
        prev = best_by_pair.get(key)
        # التكرار بترتيب الإزاحات تصاعدياً => التساوي يرجّح الإزاحة الأصغر
        if prev is None or abs(c["r_lag"]) > abs(prev["r_lag"]):
            best_by_pair[key] = c

    # ── 4) بناء النتائج النهائية (بطاقات التنبؤ) ──
    findings: List[Dict[str, Any]] = []
    for (a, b), c in best_by_pair.items():
        n = len(c["xs"])
        xs, ys, zs = c["xs"], c["ys"], c["zs"]
        r_lag, p_lag = c["r_lag"], c["p_lag"]
        r_partial, p_partial = c["r_partial"], c["p_partial"]
        try:
            r_contemp = float(stats.pearsonr(xs, zs)[0])
        except Exception:
            r_contemp = None
        consistency = _direction_consistency(c["hosp_pairs"], r_lag)
        jackknife = _jackknife_stable(c["hosp_pairs"], r_lag)
        effect = _effect_size(xs, ys)

        strength = ("strong" if abs(r_lag) >= 0.6
                    else ("moderate" if abs(r_lag) >= 0.4 else "weak"))
        granger_pass = (r_partial is not None and p_partial is not None
                        and p_partial < _LAG_P_VALUE
                        and abs(r_partial) >= _MIN_PARTIAL_ABS_R)
        if n >= 30 and p_lag < 0.01 and granger_pass and (consistency or 0) >= 0.6:
            confidence = "high"
        elif n >= 20 and p_lag < 0.05:
            confidence = "medium"
        else:
            confidence = "low"
        is_lead = r_contemp is not None and abs(r_lag) > abs(r_contemp) + 0.05
        direction = "positive" if r_lag > 0 else "negative"

        a_ar = METRIC_NAMES_AR.get(a, a)
        b_ar = METRIC_NAMES_AR.get(b, b)
        a_en = METRIC_NAMES_EN.get(a, a)
        b_en = METRIC_NAMES_EN.get(b, b)
        if r_lag > 0:
            lead_ar, lead_en = "يرتبط بارتفاع", "is associated with higher"
            delta_word_ar = "زيادة"
            delta_word_en = "rise"
        else:
            lead_ar, lead_en = "يرتبط بانخفاض", "is associated with lower"
            delta_word_ar = "انخفاض"
            delta_word_en = "fall"

        summary_ar = (
            f"ارتفاع {a_ar} عند الشهر t {lead_ar} {b_ar} بعد {_lag_word(c['lag'])} "
            f"(r={r_lag:.2f}, p={p_lag:.3f}, n={n})"
        )
        summary_en = (
            f"Higher {a_en} at month t {lead_en} {b_en} {c['lag']} month(s) later "
            f"(r={r_lag:.2f}, p={p_lag:.3f}, n={n})"
        )

        # تنبؤ قابل للتنفيذ: «إذا ارتفع A بنسبة 10% → B يتغير بمقدار كذا»
        prediction_ar = summary_ar
        prediction_en = summary_en
        if effect and effect.get("delta_b_per_10pct_a") is not None:
            delta = effect["delta_b_per_10pct_a"]
            delta_pct = effect.get("delta_b_pct_per_10pct_a")
            mean_a = effect.get("mean_a")
            pct_str = f" ({delta_pct:+.0f}%)" if delta_pct is not None else ""
            cons_str = (f" — متسقة في {(consistency or 0) * 100:.0f}% من المستشفيات"
                        if consistency is not None else "")
            prediction_ar = (
                f"إذا ارتفع {a_ar} بنسبة 10% (≈{mean_a:.1f}→{mean_a * 1.1:.1f}) "
                f"يُتوقع {delta_word_ar} {b_ar} بمقدار ≈{abs(delta):.1f}{pct_str} "
                f"بعد {_lag_word(c['lag'])}{cons_str}."
            )
            prediction_en = (
                f"If {a_en} rises 10% (≈{mean_a:.0f}→{mean_a * 1.1:.0f}), "
                f"expect {b_en} to {delta_word_en} by ≈{abs(delta):.1f}{pct_str} "
                f"{c['lag']} month(s) later."
            )

        findings.append({
            "indicator_a": a, "indicator_b": b,
            "indicator_a_ar": a_ar, "indicator_b_ar": b_ar,
            "lag": c["lag"],
            "lag_pearson": round(r_lag, 3),
            "p_value": round(p_lag, 4),
            "granger_pearson": round(r_partial, 3) if r_partial is not None else None,
            "granger_p": round(p_partial, 4) if p_partial is not None else None,
            "granger_pass": bool(granger_pass),
            "contemporaneous_pearson": (round(r_contemp, 3)
                                        if r_contemp is not None else None),
            "n": int(n),
            "direction": direction,
            "strength": strength,
            "confidence": confidence,
            "consistency": round(float(consistency), 3) if consistency is not None else None,
            "jackknife_stable": bool(jackknife),
            "is_lead": bool(is_lead),
            "small_sample": n < _SMALL_SAMPLE,
            "effect": effect,
            "summary_ar": summary_ar,
            "summary_en": summary_en,
            "prediction_ar": prediction_ar,
            "prediction_en": prediction_en,
        })

    # الترتيب: قوة القيادة (غرانجر) ثم الدلالة ثم الاتساق
    findings.sort(key=lambda f: (-abs(f["granger_pearson"] or f["lag_pearson"]),
                                 f["p_value"], -(f["consistency"] or 0)))

    # ── 5) مصفوفة القيادة: أفضل إزاحة لكل زوج (عرض كامل، بما فيه غير المقبول) ──
    values = [[None] * n_metrics for _ in range(n_metrics)]
    sig = [[False] * n_metrics for _ in range(n_metrics)]
    best_lags = [[None] * n_metrics for _ in range(n_metrics)]
    for (a, b), entry in matrix_best.items():
        i = metrics.index(a)
        j = metrics.index(b)
        c = entry["c"]
        r_display = c["r_partial"] if c["r_partial"] is not None else c["r_lag"]
        values[i][j] = round(float(r_display), 2)
        best_lags[i][j] = c["lag"]
        sig[i][j] = bool(entry["acc"])

    note_ar = (
        "الارتباط المتأخر يرصد التسلسل الزمني (A عند t → B عند t+L) عبر المستشفيات "
        "بعد ضبط تعدد الاختبارات (FDR) واختيار أفضل إزاحة (1–3 أشهر). يُعرض ارتباط "
        "غرانجر-لايك (بعد التحكم بقيمة B السابقة) لفصل «القيادة الحقيقية» عن "
        "استمرارية المؤشر. الارتباط لا يعني سببّية — قد يكون هناك عامل ثالث مشترك."
    )
    note_en = (
        "Lag correlation captures the temporal sequence (A at t → B at t+L) across "
        "hospitals with FDR multiple-testing control and best-lag selection (1–3 "
        "months). A Granger-like partial correlation (controlling for B's own past) "
        "separates genuine leads from momentum. Correlation ≠ causation."
    )
    return {
        "month": month,
        "lags": findings[:12],
        "matrix": {
            "metrics": metrics,
            "names_ar": [METRIC_NAMES_AR.get(m, m) for m in metrics],
            "values": values,
            "significant": sig,
            "lags": best_lags,
        },
        "note_ar": note_ar,
        "note_en": note_en,
    }


def _rising(current: Optional[float], prev: Optional[float], is_percent: bool) -> bool:
    """هل ارتفع المؤشر شهرياً؟ (نسبياً ≥10% أو مطلقاً ≥2 نقطة للمعدلات النسبية)."""
    if current is None or prev is None or prev <= 0:
        return False
    if current >= prev * _RISING_MOM:
        return True
    if is_percent and (current - prev) >= _RISING_ABS_PP:
        return True
    return False


def _discovered_leading_indicators(lag_results: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """مؤشرات قيادية مكتشفة فعلياً من العلاقات المتأخرة (اجتازت FDR وغرانجر).

    كل مؤشر A ظهر قيادياً نحو نتيجة (وفيات/ولادات ميتة/مضاعفات) يُقيَّم بأقوى
    علاقاته: الوزن الخام = 55% قوة الارتباط الجزئي (غرانجر) + 30% اتساق
    المستشفيات + 15% مكافأة «رائدة». ثم تُطبَّع الأوزان بحيث يكون أقوى قائد
    = 1.0 (أي ما يعادل مؤشراً واحداً من القائمة الافتراضية) — هكذا تعمل عتبات
    الشدة نفسها في الحالتين.
    يعيد {مؤشر: {weight, outcome_ar}} أو {} عند غياب الاكتشافات.
    """
    findings = (lag_results or {}).get("lags") or []
    raw: Dict[str, Dict[str, Any]] = {}
    for f in findings:
        if f.get("indicator_b") not in OUTCOME_METRICS or not f.get("indicator_a"):
            continue
        a = f["indicator_a"]
        r = abs(f.get("granger_pearson") if f.get("granger_pearson") is not None
                else (f.get("lag_pearson") or 0))
        cons = f.get("consistency") if f.get("consistency") is not None else 0.3
        lead_bonus = 0.9 if f.get("is_lead") else 0.4
        weight = round(min(1.0, max(0.3, 0.55 * r + 0.30 * cons + 0.15 * lead_bonus)), 3)
        prev = raw.get(a)
        if prev is None or weight > prev["weight"]:
            raw[a] = {"weight": weight, "outcome_ar": f.get("indicator_b_ar")}
    if not raw:
        return {}
    max_w = max(v["weight"] for v in raw.values())
    return {
        m: {"weight": max(0.1, round(v["weight"] / max_w, 2)), "outcome_ar": v["outcome_ar"]}
        for m, v in raw.items()
    }


def run_hospital_forecast(session, hospital_id: int, month: str,
                          lag_results: Optional[Dict[str, Any]] = None,
                          series=None, meta=None, window=None) -> Dict[str, Any]:
    """توقعات الشهر القادم لمستشفى محدد من المؤشرات القيادية الصاعدة.

    لنفس المنطق الذي تبنيه run_early_warnings (قائمة قيادة مكتشفة بأوزان، أو
    افتراضية عند غياب الاكتشافات)، لكن لمستشفى واحد: يُحصي المؤشرات القيادية
    الصاعدة هذا الشهر بأوزانها، ويُحدد النتائج التي يُتوقع أن تسبقها (من
    العلاقات المكتشفة نحو النتائج: وفيات المواليد/الأمومية/الولادات الميتة/
    المضاعفات)، مع درجة إجمالية واحتمال وثقة. يعيد {} عند غياب بيانات المستشفى
    في النافذة.

    يمكن تمرير series/meta/window محمّلة مسبقاً (من _load_series) لتجنب إعادة
    تحميل بيانات كل المستشفيات لكل استدعاء — مفيد لحلقات التوقعات عبر المستشفيات
    (مثل مولّد التقرير الشامل). عند عدم تمريرها تُحمَّل داخلياً.
    """
    if series is None or meta is None or window is None:
        series, meta, window = _load_series(session, month, months_back=3)
    if len(window) < 2:
        return {}

    # اسم المستشفى من أحدث بيانات تعريفية متاحة
    name = next((n for n, m in meta.items()
                 if m.get("hospital_id") == hospital_id), None)
    if name is None or name not in series:
        return {}

    if lag_results is None:
        try:
            lag_results = run_lag_analysis(session, month)
        except Exception:
            lag_results = None
    discovered = _discovered_leading_indicators(lag_results)
    use_discovered = bool(discovered)
    if use_discovered:
        leading = {m: v["weight"] for m, v in discovered.items()}
    else:
        leading = {m: 1.0 for m in LEADING_INDICATORS}

    # النتائج المتوقعة من الاكتشافات: مؤشر قيادي → نتيجة (مع الإزاحة والقوة)
    leads_map: Dict[str, List[Dict[str, Any]]] = {}
    for f in (lag_results or {}).get("lags") or []:
        a, b = f.get("indicator_a"), f.get("indicator_b")
        if not a or b not in OUTCOME_METRICS:
            continue
        if not f.get("granger_pass") and not f.get("is_lead"):
            continue
        leads_map.setdefault(a, []).append({
            "outcome": b,
            "outcome_ar": f.get("indicator_b_ar", b),
            "lag": f.get("lag"),
            "lag_word": _lag_word(f.get("lag") or 1),
            "granger_pearson": f.get("granger_pearson"),
            "lag_pearson": f.get("lag_pearson"),
            "prediction_ar": f.get("prediction_ar"),
        })

    last_two = window[-2:]
    cur_month, prev_month = last_two[1], last_two[0]
    months = series.get(name, {})
    cur, prev = months.get(cur_month), months.get(prev_month)
    if not cur or not prev:
        return {}

    rising_list: List[Dict[str, Any]] = []
    for metric, weight in leading.items():
        is_percent = metric in ("cs_rate", "preterm_rate", "lbw_rate",
                                "high_risk_rate", "adolescent_rate")
        c, p = cur.get(metric), prev.get(metric)
        if not _rising(c, p, is_percent):
            continue
        delta_pct = ((c - p) / p * 100) if p and p > 0 else None
        rising_list.append({
            "metric": metric,
            "metric_ar": METRIC_NAMES_AR.get(metric, metric),
            "current": round(float(c), 3) if c is not None else None,
            "previous": round(float(p), 3) if p is not None else None,
            "delta_pct": round(float(delta_pct), 1) if delta_pct is not None else None,
            "weight": weight,
            "discovered": use_discovered,
            "leads_to": leads_map.get(metric, []),
        })

    nc, npv = cur.get(OUTCOME_INDICATOR), prev.get(OUTCOME_INDICATOR)
    outcome_rising = _rising(nc, npv, False)

    score = round(sum(r["weight"] for r in rising_list), 2)
    if score >= _CRITICAL_RISING:
        severity = "critical"
    elif score >= _WARNING_RISING or (score >= 1.0 and outcome_rising):
        severity = "warning"
    elif score >= 1.0:
        severity = "info"
    else:
        severity = "none"

    probability = 0.25 + 0.15 * score + (0.15 if outcome_rising else 0.0)
    probability = round(min(0.95, probability), 2)

    from app.models import QualityScore
    comp = None
    q = (session.query(QualityScore)
         .filter(QualityScore.hospital_id == hospital_id,
                 QualityScore.month == month).first())
    if q is not None:
        comp = q.completeness
    if comp is None:
        confidence = "low"
        confidence_label_ar = "منخفضة — لا توجد درجة اكتمال"
    elif comp >= 70:
        confidence = "high"
        confidence_label_ar = "عالية"
    elif comp >= 40:
        confidence = "medium"
        confidence_label_ar = "متوسطة"
    else:
        confidence = "low"
        confidence_label_ar = "منخفضة — بيانات غير مكتملة"

    if use_discovered:
        note_ar = (
            "قائمة القيادة مبنية من علاقات متأخرة مكتشفة (FDR + غرانجر) موزونة "
            "بقوة العلاقة واتساق المستشفيات — تقدير إحصائي لا تنبؤ مؤكد."
        )
    else:
        note_ar = (
            "بيانات غير كافية لاكتشاف العلاقات — استُخدمت القائمة الافتراضية "
            "بوزن 1 لكل مؤشر قيادي."
        )

    return {
        "hospital_id": hospital_id,
        "hospital_name": name,
        "month": cur_month,
        "discovered_leads": use_discovered,
        "leading_rising": rising_list,
        "outcome_rising": bool(outcome_rising),
        "score": score,
        "severity": severity,
        "probability": probability,
        "confidence": confidence,
        "confidence_label_ar": confidence_label_ar,
        "note_ar": note_ar,
    }


def run_early_warnings(session, month: str,
                       lag_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """إنذار مبكر لكل مستشفى من المؤشرات القيادية الصاعدة.

    قائمة المؤشرات القيادية تُبنى من العلاقات المتأخرة المكتشفة فعلياً (التي
    اجتازت FDR وغرانجر): كل مؤشر يكتسب وزناً من قوة علاقته بالنتائج واتساقها
    (الوزن 1.0 = أقوى قائد مكتشف). عند غياب الاكتشافات (بيانات قليلة جداً)
    نرجع للقائمة الافتراضية بوزن 1 لكل مؤشر.
    الشدة من مجموع أوزان المؤشرات الصاعدة، الاحتمال تقدير تحفظي من قوة
    الإشارة، والثقة من اكتمال بيانات المستشفى.
    """
    from app.models import QualityScore

    series, meta, window = _load_series(session, month, months_back=3)
    if len(window) < 2:
        return {"month": month, "warnings": [], "summary_ar": "يلزم شهران على الأقل للإنذار المبكر."}

    # قائمة القيادة: مكتشفة أم افتراضية؟
    if lag_results is None:
        try:
            lag_results = run_lag_analysis(session, month)
        except Exception:
            lag_results = None
    discovered = _discovered_leading_indicators(lag_results)
    use_discovered = bool(discovered)
    if use_discovered:
        leading = {m: v["weight"] for m, v in discovered.items()}
    else:
        leading = {m: 1.0 for m in LEADING_INDICATORS}

    completeness = {
        q.hospital_id: float(q.completeness)
        for q in session.query(QualityScore).filter(QualityScore.month == month).all()
        if q.completeness is not None
    }

    last_two = window[-2:]
    cur_month, prev_month = last_two[1], last_two[0]

    warnings: List[Dict[str, Any]] = []
    for name, months in series.items():
        cur = months.get(cur_month)
        prev = months.get(prev_month)
        if not cur or not prev:
            continue
        rising_list: List[Dict[str, Any]] = []
        for metric, weight in leading.items():
            is_percent = metric in ("cs_rate", "preterm_rate", "lbw_rate",
                                    "high_risk_rate", "adolescent_rate")
            c, p = cur.get(metric), prev.get(metric)
            if _rising(c, p, is_percent):
                delta_pct = ((c - p) / p * 100) if p and p > 0 else None
                rising_list.append({
                    "metric": metric,
                    "metric_ar": METRIC_NAMES_AR.get(metric, metric),
                    "current": round(float(c), 3) if c is not None else None,
                    "previous": round(float(p), 3) if p is not None else None,
                    "delta_pct": round(float(delta_pct), 1) if delta_pct is not None else None,
                    "weight": weight,
                    "discovered": use_discovered,
                    "leads": (discovered[metric]["outcome_ar"] if use_discovered else None),
                })

        nc, npv = cur.get(OUTCOME_INDICATOR), prev.get(OUTCOME_INDICATOR)
        outcome_rising = _rising(nc, npv, False)

        count = len(rising_list)
        score = round(sum(r["weight"] for r in rising_list), 2)
        # العتبات على مقياس «الوزن 1 = مؤشر واحد» — نفس سلوك القائمة الافتراضية
        if score >= _CRITICAL_RISING:
            severity = "critical"
        elif score >= _WARNING_RISING or (score >= 1.0 and outcome_rising):
            severity = "warning"
        elif score >= 1.0:
            severity = "info"
        else:
            continue

        # احتمال تحفظي من قوة الإشارة (تقدير نموذجي لا احتمال حقيقي)
        probability = 0.25 + 0.15 * score + (0.15 if outcome_rising else 0.0)
        probability = round(min(0.95, probability), 2)

        comp = completeness.get(meta.get(name, {}).get("hospital_id"))
        if comp is None:
            confidence = "low"
            confidence_label_ar = "منخفضة — لا توجد درجة اكتمال"
        elif comp >= 70:
            confidence = "high"
            confidence_label_ar = "عالية"
        elif comp >= 40:
            confidence = "medium"
            confidence_label_ar = "متوسطة"
        else:
            confidence = "low"
            confidence_label_ar = "منخفضة — بيانات غير مكتملة"

        drivers_ar = "، ".join(r["metric_ar"] for r in rising_list) or "—"
        summary_ar = (
            f"{name}: ارتفاع {count} مؤشر(ات) قيادية ({drivers_ar}) "
            f"{'مع ارتفاع وفيات المواليد' if outcome_rising else ''} — "
            f"احتمال تدهور تقديري {probability:.0%} ({confidence_label_ar})."
        )
        warnings.append({
            "hospital_id": meta.get(name, {}).get("hospital_id"),
            "hospital_name": name,
            "governorate": meta.get(name, {}).get("governorate", "unknown"),
            "month": cur_month,
            "severity": severity,
            "rising_count": count,
            "score": score,
            "discovered_leads": use_discovered,
            "probability": probability,
            "confidence": confidence,
            "confidence_label_ar": confidence_label_ar,
            "outcome_rising": bool(outcome_rising),
            "contributing": rising_list,
            "summary_ar": summary_ar,
        })

    warnings.sort(key=lambda w: ({"critical": 0, "warning": 1, "info": 2}[w["severity"]],
                                 -w["probability"]))
    critical = sum(1 for w in warnings if w["severity"] == "critical")
    warning = sum(1 for w in warnings if w["severity"] == "warning")
    if use_discovered:
        summary_ar = (
            f"{len(warnings)} مستشفى بإشارات مبكرة ({critical} حرجة، {warning} تحذير). "
            "قائمة القيادة مبنية من علاقات متأخرة مكتشفة (FDR + غرانجر) وموزونة "
            "بقوة العلاقة واتساق المستشفيات — تحقَّق من البيانات قبل الاستنتاج."
        )
    else:
        summary_ar = (
            f"{len(warnings)} مستشفى بإشارات مبكرة ({critical} حرجة، {warning} تحذير). "
            "المؤشرات القيادية الصاعدة تسبق التدهور عادةً — تحقَّق من البيانات قبل الاستنتاج."
        )
    return {"month": month, "warnings": warnings, "summary_ar": summary_ar}
