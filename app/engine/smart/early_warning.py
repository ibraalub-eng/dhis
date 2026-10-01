"""محرك الإنذار المبكر والتنبؤ الديناميكي (المرحلة 2).

لا يسأل فقط «ما التوقع؟» بل «ما إشارات الخطر قبل وقوعه؟ وأي مستشفى/مؤشر
يستحق التنبؤ به الآن؟»:

- **إشارات مبكرة** من مصادر موجودة: تراجع الجودة، تراجع الالتزام بالقواعد،
  ارتفاع انحراف النظراء، زخم اتجاه المؤشر، وتصعيد الأنماط المركبة — كل
  إشارة بأفق صريح («توقع تجاوز عتبة الخطر خلال 3 أشهر إن استمر الاتجاه»).
- **أهداف ديناميكية**: ترتيب المستشفيات بقوة الإشارات المجمّعة مع سقف عددي
  بدل إغراق الشاشة.
- **مزيج متعدد المصادر للمؤشر الواحد**: اتجاه تاريخي 30% + انحراف النظراء
  30% + النمط الذاتي 40% (أوزان موثّقة)، مع نطاق وثقة مرتبطة بعدد الأشهر،
  و«غير متاح» تحت 3 أشهر.
- **علاقات المؤشرات**: من نتائج lag_analysis الموجودة بصياغة ارتباطية
  صريحة («علاقة ارتباطية لا علاقة سببية»).

قواعد الصياغة: كل المخرجات تقديرات إحصائية لا تنبؤ مؤكد، والارتباط ليس
سببية، ولا يُجزم ما بعد الأفق المعلن.
"""
from typing import Dict, List, Optional

import numpy as np

# أوزان المزيج متعدد المصادر (الخطة 2.3): قابلة للتحليل وثابتة افتراضياً
DEFAULT_WEIGHTS = {"trend": 0.3, "peer": 0.3, "self": 0.4}

# الحد الأدنى لأشهر المزيج (تحت ذلك: «غير متاح بعد»)
BLEND_MIN_MONTHS = 3

# سقف الأهداف الديناميكية المعروضة
MAX_SIGNAL_TARGETS = 5

# نوافذ كشف الاتجاه: تغيّر متوسط آخر شهرين مقابل الشهرين السابقين لهما
_RECENT_WINDOW = 2

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_DISCLAIMER = "تقدير إحصائي لا تنبؤ مؤكد."

_ARABIC_KIND = {
    "quality_decline": "تراجع جودة البيانات",
    "rule_compliance_decline": "تراجع الالتزام بالقواعد",
    "peer_deviation_rise": "ارتفاع انحراف النظراء",
    "indicator_momentum": "زخم اتجاه المؤشر",
    "pattern_escalation": "تصعيد نمط مركب",
}


def _slope_pct(values: List[float]) -> float:
    """نسبة التغير بين متوسط آخر _RECENT_WINDOW وأول ما قبلهما (0 إن غير محكوم)."""
    if len(values) < _RECENT_WINDOW * 2:
        return 0.0
    recent = np.mean(values[-_RECENT_WINDOW:])
    before = np.mean(values[-_RECENT_WINDOW * 2:-_RECENT_WINDOW])
    if before <= 0:
        return 0.0
    return float((recent - before) / before * 100.0)


def _quality_signal(hospital: str, rows: List[Dict]) -> Optional[Dict]:
    quality = [float(r.get("quality") or 0.0) for r in rows]
    rule = [float(r.get("rule_compliance") or 0.0) for r in rows]
    out = []
    q_drop = _slope_pct(quality)
    r_drop = _slope_pct(rule)
    base_month = rows[-1].get("month", "") if rows else ""
    if q_drop <= -8.0:
        sev = "critical" if q_drop <= -20.0 else "warning"
        out.append({
            "hospital": hospital, "kind": "quality_decline", "severity": sev,
            "horizon_months": 3, "strength": round(min(1.0, abs(q_drop) / 25.0), 3),
            "base_month": base_month,
            "message_ar": (
                f"{hospital}: جودة البيانات تتراجع ({q_drop:.1f}% خلال الشهرين الأخيرين) — "
                f"توقع تجاوز عتبة الخطر خلال 3 أشهر إن استمر الاتجاه. {_DISCLAIMER}"
            ),
        })
    if r_drop <= -8.0:
        sev = "critical" if r_drop <= -20.0 else "warning"
        out.append({
            "hospital": hospital, "kind": "rule_compliance_decline", "severity": sev,
            "horizon_months": 3, "strength": round(min(1.0, abs(r_drop) / 25.0), 3),
            "base_month": base_month,
            "message_ar": (
                f"{hospital}: الالتزام بالقواعد يتراجع ({r_drop:.1f}%) — "
                f"توقع تصاعد مخالفات خلال 3 أشهر إن استمر الاتجاه. {_DISCLAIMER}"
            ),
        })
    return out


def _momentum_signal(hospital: str, rows: List[Dict]) -> Optional[Dict]:
    """زخم اتجاه المؤشرات الحساسة (قيصرية/وفيات ميتة) من سلسلة القيم إن توفرت."""
    for key, label in (("cs_rate", "معدل القيصارية"), ("stillbirth_rate", "معدل الولادات الميتة")):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        if len(vals) < 4:
            continue
        rise = _slope_pct(vals)
        if rise >= 15.0:
            return {
                "hospital": hospital, "kind": "indicator_momentum",
                "severity": "warning", "horizon_months": 3,
                "strength": round(min(1.0, rise / 40.0), 3),
                "base_month": rows[-1].get("month", ""),
                "message_ar": (
                    f"{hospital}: {label} يصاعد بزخم ثابت (+{rise:.1f}%) — "
                    f"توقع تجاوز النطاق المتوقع خلال 3 أشهر إن استمر. {_DISCLAIMER}"
                ),
            }
    return None


def compute_early_warning_signals(
    quality_series: Dict[str, List[Dict]],
    patterns_by_month: Dict[str, List[Dict]],
) -> List[Dict]:
    """إشارات الإنذار المبكر لكل مستشفى — كل إشارة بأفق صريح وإخلاء مسؤولية.

    quality_series: hospital -> صفوف مرتبة زمنياً (month, quality,
    rule_compliance، ومفاتيح مؤشرات اختيارية مثل cs_rate/stillbirth_rate).
    patterns_by_month: month -> أنماط مركبة (indicators, hospitals) من
    محرك الأنماط الموجود.
    """
    signals: List[Dict] = []

    for hospital, rows in (quality_series or {}).items():
        rows = sorted(rows or [], key=lambda r: r.get("month", ""))
        if len(rows) >= 4:
            signals.extend(_quality_signal(hospital, rows))
            mom = _momentum_signal(hospital, rows)
            if mom:
                signals.append(mom)

    # تصعيد الأنماط المركبة: نفس النمط (نفس المؤشرات) بشهرين متتاليين
    months = sorted(patterns_by_month or {})
    for i in range(1, len(months)):
        prev, cur = patterns_by_month[months[i - 1]], patterns_by_month[months[i]]
        for pc in cur:
            for pp in prev:
                if set(pc.get("indicators") or []) != set(pp.get("indicators") or []):
                    continue
                recurring = sorted(set(pc.get("hospitals") or []) & set(pp.get("hospitals") or []))
                for hospital in recurring:
                    signals.append({
                        "hospital": hospital, "kind": "pattern_escalation",
                        "severity": "warning", "horizon_months": 3,
                        "strength": 0.5,
                        "base_month": months[i],
                        "message_ar": (
                            f"{hospital}: النمط المركب ({' + '.join(pc.get('indicators') or [])}) "
                            f"تكرر في {months[i - 1]} و{months[i]} — "
                            f"توقع تفاقم مشترك خلال 3 أشهر إن استمر. {_DISCLAIMER}"
                        ),
                    })

    signals.sort(key=lambda s: (_SEVERITY_RANK.get(s["severity"], 3), -s["strength"]))
    return signals


def rank_forecast_targets(
    signals: List[Dict],
    max_targets: int = MAX_SIGNAL_TARGETS,
) -> List[Dict]:
    """أهداف التنبؤ الديناميكية: تجميع الإشارات لكل مستشفى وترتيبها بالقوة.

    القوة المجمّعة = مجموع قوى الإشارات مع رفع خطورة critical بمضاعف 1.5؛
    يعيد أقوى max_targets هدفاً فقط — المحرك يختار ما يستحق التنبؤ به بدل
    إغراق الشاشة.
    """
    agg: Dict[str, Dict] = {}
    for s in signals or []:
        h = s.get("hospital")
        if not h:
            continue
        weight = (1.5 if s.get("severity") == "critical" else 1.0) * float(s.get("strength") or 0.0)
        entry = agg.setdefault(h, {"hospital": h, "strength": 0.0,
                                   "signal_kinds": [], "worst_severity": "info",
                                   "horizon_months": s.get("horizon_months")})
        entry["strength"] += weight
        entry["signal_kinds"].append(s.get("kind"))
        if _SEVERITY_RANK.get(s.get("severity"), 3) < _SEVERITY_RANK.get(entry["worst_severity"], 3):
            entry["worst_severity"] = s.get("severity")
    targets = sorted(agg.values(), key=lambda t: -t["strength"])[:max(0, max_targets)]
    for t in targets:
        t["strength"] = round(t["strength"], 3)
    return targets


def blended_indicator_forecast(
    indicator: str,
    current: float,
    trend_target: float,
    peer_mean: float,
    self_mean: float,
    n_months: int,
    weights: Optional[Dict[str, float]] = DEFAULT_WEIGHTS,
) -> Dict:
    """تنبؤ مدمج متعدد المصادر لمؤشر واحد (الخطة 2.3).

    المزيج المرجّح: اتجاه المؤشر التاريخي (trend_target) 30% + متوسط النظراء
    (peer_mean) 30% + النمط الذاتي التاريخي (self_mean) 40%. الثقة ترتفع مع
    عدد الأشهر (تشبع لوجيستي بسيط)، وأقل من 3 أشهر => «غير متاح بعد».
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    if n_months < BLEND_MIN_MONTHS:
        return {
            "indicator": indicator, "available": False, "n_months": n_months,
            "note": f"تنبؤ هذا المؤشر غير متاح بعد: يلزم {BLEND_MIN_MONTHS} أشهر على الأقل (المتوفر {n_months}).",
        }
    forecast = w["trend"] * trend_target + w["peer"] * peer_mean + w["self"] * self_mean
    confidence = round(min(0.95, 0.45 + 0.08 * n_months), 3)
    spread = 0.10 * max(abs(forecast), 1.0)
    return {
        "indicator": indicator,
        "available": True,
        "current": round(float(current), 4),
        "forecast": round(float(forecast), 4),
        "lower": round(float(forecast - spread), 4),
        "upper": round(float(forecast + spread), 4),
        "confidence": confidence,
        "peer_mean": round(float(peer_mean), 4),
        "self_mean": round(float(self_mean), 4),
        "trend_target": round(float(trend_target), 4),
        "weights": dict(w),
        "n_months": n_months,
        "note": (
            f"مزيج: اتجاه المؤشر {w['trend']:.0%} + انحراف النظراء {w['peer']:.0%} + "
            f"النمط الذاتي {w['self']:.0%}. {_DISCLAIMER}"
        ),
    }


def indicator_relationships(lag_results: Optional[Dict]) -> List[Dict]:
    """علاقات المؤشرات القيادية من نتائج lag_analysis — بصياغة ارتباطية صريحة.

    «إذا ارتفع A 10% يُتوقع ارتباطه بـ B خلال L شهر — علاقة ارتباطية لا
    علاقة سببية». القيادة (is_lead/Granger) تحدد اتجاه السرد فقط.
    """
    out: List[Dict] = []
    for f in (lag_results or {}).get("lags") or []:
        a = f.get("indicator_a")
        b = f.get("indicator_b")
        if not a or not b:
            continue
        r = f.get("granger_pearson") if f.get("granger_pearson") is not None else f.get("lag_pearson")
        r = float(r) if r is not None else 0.0
        lag = int(f.get("lag") or 1)
        a_ar = f.get("indicator_a_ar") or a
        b_ar = f.get("indicator_b_ar") or b
        out.append({
            "leading": a, "leading_ar": a_ar,
            "outcome": b, "outcome_ar": b_ar,
            "lag_months": lag,
            "r": round(r, 3),
            "is_lead": bool(f.get("is_lead")),
            "message_ar": (
                f"إذا ارتفع {a_ar} 10% يُتوقع ارتباط ذلك بتغير {b_ar} خلال {lag} شهر(أشهر) "
                f"(قوة الارتباط r≈{r:.2f}) — علاقة ارتباطية لا علاقة سببية. {_DISCLAIMER}"
            ),
        })
    return out
