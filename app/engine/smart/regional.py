"""Regional Health Intelligence — طبقة تحليل إقليمية فوق بيانات المستشفيات.

تجمع بيانات المستشفيات على مستوى المحافظة، وتحسب مؤشرات معيارية (معدلات
الوفيات والقيصرية وغيرها) بمقامات مُتحقَّق منها، وتقارن كل محافظة بمعيار
الإقليم (متوسط/وسيط/مئوي/انحراف)، وتحلل العلاقة بين حجم الولادات والوفيات
(خام مقابل معياري)، وتحسب النسبة الملاحظة/المتوقعة (O/E) بانحدار Poisson /
Negative Binomial عند توفر البيانات، وتكشف الاتجاهات الشهرية على مستوى
المحافظة، وتُنتج درجة خطر إقليمية ببوابة جودة تُخفض الثقة عند ضعف البيانات.

المبادئ الملزمة (من مواصفة Regional Health Intelligence):
- لا تُحسب أي نسبة بدون مقام صالح (صفر/غائب => None مع تنبيه).
- لا تُفسَّر الارتباطات كسببية؛ تُعرض الصياغة «ارتباط/ارتباط إحصائي».
- البيانات ضعيفة الجودة => ثقة منخفضة وتنبيه صريح، لا استنتاج سريري قوي.
- الإحالات (referrals) غير موجودة في البيانات إطلاقاً => تُتجاهل صراحةً.
"""

import math
from typing import Any, Dict, List, Optional

import numpy as np

from app.engine.smart import _load_hospital_data

# ── أسماء المؤشرات ثنائية اللغة ──
METRIC_NAMES_AR = {
    "nmr": "معدل وفيات المواليد",
    "mmr": "نسبة الوفيات الأمومية",
    "stillbirth_rate": "معدل الولادات الميتة",
    "cs_rate": "معدل العمليات القيصارية",
    "preterm_rate": "معدل الولادات المبكرة",
    "lbw_rate": "معدل نقص وزن الولادة",
    "smm_rate": "معدل المضاعفات الخطيرة",
    "adolescent_rate": "نسبة الحوامل المراهقات",
    "high_risk_rate": "نسبة حالات الخطر العالي",
}
METRIC_NAMES_EN = {
    "nmr": "Neonatal mortality rate",
    "mmr": "Maternal mortality ratio",
    "stillbirth_rate": "Stillbirth rate",
    "cs_rate": "C-section rate",
    "preterm_rate": "Preterm birth rate",
    "lbw_rate": "Low birth weight rate",
    "smm_rate": "Severe maternal morbidity rate",
    "adolescent_rate": "Adolescent pregnancy rate",
    "high_risk_rate": "High-risk delivery rate",
}

# الأكواد المصدريّة المُجمَّعة على مستوى المحافظة (مستبعدة المعطّلة مسبقاً
# داخل _load_hospital_data) — تُجمَّع الأعداد ثم تُحسب المعدلات على المجاميع
# (لا متوسط معدلات المستشفيات) لأن المعدل المجمّع أدق إحصائياً.
_SRC = {
    "deliveries": "2",
    "cs_count": "5",
    "live_births": "6",
    "preterm": "6.f",
    "lbw": "6.g",
    "sb": "7",
    "smm": "10",
    "mat_deaths": "11",
    "nd": "17",
    "high_risk": "2.n",
    "adol_a": "2.c",
    "adol_b": "2.d",
}

# المؤشرات التي «انخفاضها أفضل» (نتائج سريرية/وفيات) — تستخدم في الاتجاهات
# والمخاطر لتمييز الاتجاه الصحيح.
_LOWER_IS_BETTER = {
    "nmr", "mmr", "stillbirth_rate", "cs_rate", "preterm_rate",
    "lbw_rate", "smm_rate", "adolescent_rate", "high_risk_rate",
}

# معدلات تُحسب لكل ألف/مئة ألف (المقامات بالأساس)
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

# عتبات خطر الوفيات (نسبة الانحراف عن معيار الإقليم)
_DEVIATION_HIGH = 50.0
_DEVIATION_MEDIUM = 20.0

# عتبات حجم العينة: أقل من ذلك يُعلَّم «عينة صغيرة — تفسير بحذر»
_SMALL_SAMPLE_BIRTHS = 100
_TINY_SAMPLE_BIRTHS = 30


def _safe_rate(num: Optional[float], den: Optional[float], scale: float) -> Optional[float]:
    """نسبة بمقام مُتحقَّق منه: غياب/صفر المقام => None (لا نسبة وهمية)."""
    if num is None or den is None or den <= 0:
        return None
    return num / den * scale


def _gov_aggregates(all_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """تجميع الأعداد الخام لكل محافظة من بيانات المستشفيات (المعطّلة مستبعدة)."""
    govs: Dict[str, Dict[str, Any]] = {}
    for name, entry in all_data.items():
        gov = entry.get("governorate") or "unknown"
        values = entry.get("values", {}) or {}
        agg = govs.setdefault(gov, {
            "hospital_count": 0, "hospital_names": [], "sums": {k: 0.0 for k in _SRC},
        })
        agg["hospital_count"] += 1
        agg["hospital_names"].append(name)
        for key, code in _SRC.items():
            v = values.get(code)
            if v is not None:
                try:
                    agg["sums"][key] += float(v)
                except (TypeError, ValueError):
                    pass
    return govs


def _gov_metrics(agg: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """المؤشرات المعيارية للمحافظة من المجاميع الخام مع بوابة المقام."""
    s = agg["sums"]
    births = s["live_births"] or None
    deliveries = s["deliveries"] or None
    adol = s["adol_a"] + s["adol_b"]

    metrics: Dict[str, Optional[float]] = {
        "births": births,
        "deliveries": deliveries,
        "cs_count": s["cs_count"] or None,
        "mat_deaths": s["mat_deaths"] or None,
        "nd": s["nd"] or None,
        "sb": s["sb"] or None,
        "smm": s["smm"] or None,
        "preterm": s["preterm"] or None,
        "lbw": s["lbw"] or None,
        "high_risk": s["high_risk"] or None,
        "adolescent": adol if (s["adol_a"] or s["adol_b"]) else None,
    }
    # ملاحظة التعريف: stillbirth_rate يستخدم المواليد الأحياء مقاماً — وهو
    # التعريف المعتمد في النظام (stillbirth_rate في xgboost_predictor).
    metrics["nmr"] = _safe_rate(metrics["nd"], births, _RATE_SCALE["nmr"])
    metrics["mmr"] = _safe_rate(metrics["mat_deaths"], births, _RATE_SCALE["mmr"])
    metrics["stillbirth_rate"] = _safe_rate(metrics["sb"], births, _RATE_SCALE["stillbirth_rate"])
    metrics["cs_rate"] = _safe_rate(metrics["cs_count"], deliveries, _RATE_SCALE["cs_rate"])
    metrics["preterm_rate"] = _safe_rate(metrics["preterm"], births, _RATE_SCALE["preterm_rate"])
    metrics["lbw_rate"] = _safe_rate(metrics["lbw"], births, _RATE_SCALE["lbw_rate"])
    metrics["smm_rate"] = _safe_rate(metrics["smm"], deliveries, _RATE_SCALE["smm_rate"])
    metrics["adolescent_rate"] = _safe_rate(metrics["adolescent"], births, _RATE_SCALE["adolescent_rate"])
    metrics["high_risk_rate"] = _safe_rate(metrics["high_risk"], births, _RATE_SCALE["high_risk_rate"])
    return metrics


def _percentile_rank(value: float, values: List[float]) -> Optional[float]:
    """المئوي النسبي لقيمة داخل توزيع (0-100). قيمة أعلى = ترتيب أعلى."""
    n = len(values)
    if n == 0 or value is None:
        return None
    if n == 1:
        return 50.0
    rank = sum(1 for v in values if v <= value)
    return round((rank - 1) / (n - 1) * 100, 1)


def _benchmarks(metrics_by_gov: Dict[str, Dict[str, Optional[float]]]) -> Dict[str, Dict[str, float]]:
    """معيار إقليمي لكل معدل: متوسط/وسيط/أدنى/أقصى/انحراف معياري."""
    benchmarks: Dict[str, Dict[str, float]] = {}
    for metric in _RATE_SCALE:
        vals = [m[metric] for m in metrics_by_gov.values() if m.get(metric) is not None]
        if len(vals) == 0:
            benchmarks[metric] = {"mean": None, "median": None, "min": None, "max": None, "std": None, "n": 0}
            continue
        arr = np.array(vals)
        benchmarks[metric] = {
            "mean": round(float(arr.mean()), 4),
            "median": round(float(np.median(arr)), 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "std": round(float(arr.std()), 4) if len(arr) > 1 else 0.0,
            "n": len(arr),
        }
    return benchmarks


def _monthly_gov_metrics(session, month: str, months_back: int = 6) -> Dict[str, Dict[str, Dict[str, Optional[float]]]]:
    """معدلات كل محافظة لكل شهر في النافذة (تغذي الاتجاهات والشذوذ التاريخي)."""
    from app.models import QualityScore

    months = [
        r[0] for r in session.query(QualityScore.month).distinct().order_by(QualityScore.month).all()
    ]
    window = [m for m in months if m <= month][-months_back:]
    per_month = {}
    for m in window:
        data = _load_hospital_data(session, m)
        if not data:
            continue
        govs = _gov_aggregates(data)
        per_month[m] = {
            gov: _gov_metrics(agg) for gov, agg in govs.items()
        }
    return per_month


def _regional_anomalies(session, month: str, metrics_by_gov, benchmarks, gov_names,
                        months_back: int = 6) -> List[Dict[str, Any]]:
    """شذوذ إقليمي: محافظة شاذة مقابل نظيراتها (عرضي) أو مقابل تاريخها (زمني).

    - cross_sectional: |z| ≥ 2 لمعدل محافظة مقابل معيار الإقليم (متوسط/انحراف).
    - historical: |z| ≥ 2 لقيمة الشهر الحالي مقابل متوسط الأشهر السابقة لنفس
      المحافظة (يلزم 3 أشهر سابقة على الأقل).
    لا يُعلَّم التقلّب العشوائي شذوذاً، والعيّنات الصغيرة تُخفِّض الشدة.
    """
    findings: List[Dict[str, Any]] = []

    # ── عرضي: محافظة مقابل نظيراتها ──
    for gov in gov_names:
        m = metrics_by_gov[gov]
        births = m.get("births") or 0
        for metric in _RATE_SCALE:
            value = m.get(metric)
            bm = benchmarks.get(metric, {})
            mean_v, std_v = bm.get("mean"), bm.get("std")
            if value is None or mean_v is None or not std_v or std_v <= 0:
                continue
            z = (value - mean_v) / std_v
            if abs(z) < 2.0:
                continue
            dev = (value - mean_v) / mean_v * 100 if mean_v else 0.0
            severity = "critical" if abs(z) >= 3.0 else "warning"
            if 0 < births < _SMALL_SAMPLE_BIRTHS and severity == "critical":
                severity = "warning"  # عينة صغيرة لا تدعم «حرج» بثقة
            higher = z > 0
            direction = "increased" if higher else "decreased"
            # ملاحظة الاتجاه الصحيح: ارتفاع معدلات النتائج السريرية خطر، انخفاضها جيد
            summary_ar = (
                f"محافظة {gov} {('أعلى' if higher else 'أدنى')} من نظيراتها في "
                f"{METRIC_NAMES_AR[metric]}: {value:.1f} مقابل متوسط الإقليم {mean_v:.1f} "
                f"(انحراف {dev:+.1f}%، z={z:.1f})"
            )
            summary_en = (
                f"{gov} is {'higher' if higher else 'lower'} than peers in "
                f"{METRIC_NAMES_EN[metric]}: {value:.1f} vs regional mean {mean_v:.1f} "
                f"(deviation {dev:+.1f}%, z={z:.1f})"
            )
            findings.append({
                "governorate": gov,
                "metric": metric,
                "metric_ar": METRIC_NAMES_AR[metric],
                "metric_en": METRIC_NAMES_EN[metric],
                "type": "cross_sectional",
                "observed": round(float(value), 3),
                "benchmark": round(float(mean_v), 3),
                "deviation_pct": round(float(dev), 1),
                "z_score": round(float(z), 2),
                "severity": severity,
                "direction": direction,
                "small_sample": 0 < births < _SMALL_SAMPLE_BIRTHS,
                "summary_ar": summary_ar,
                "summary_en": summary_en,
            })

    # ── زمني: محافظة مقابل تاريخها ──
    per_month = _monthly_gov_metrics(session, month, months_back)
    if len(per_month) >= 3:
        months_sorted = sorted(per_month)
        for gov in gov_names:
            m = metrics_by_gov[gov]
            births = m.get("births") or 0
            for metric in ("nmr", "mmr", "stillbirth_rate", "cs_rate", "preterm_rate"):
                value = m.get(metric)
                if value is None:
                    continue
                prior = []
                for mth in months_sorted:
                    if mth >= month:
                        continue
                    v = per_month[mth].get(gov, {}).get(metric)
                    if v is not None:
                        prior.append(v)
                if len(prior) < 3:
                    continue
                arr = np.array(prior, dtype=float)
                pm, ps = float(arr.mean()), float(arr.std())
                if ps <= 1e-9:
                    continue
                z = (value - pm) / ps
                if abs(z) < 2.0:
                    continue
                dev = (value - pm) / pm * 100 if pm else 0.0
                severity = "critical" if abs(z) >= 3.0 else "warning"
                if 0 < births < _SMALL_SAMPLE_BIRTHS and severity == "critical":
                    severity = "warning"
                higher = z > 0
                summary_ar = (
                    f"{METRIC_NAMES_AR[metric]} في محافظة {gov} قفز هذا الشهر: "
                    f"{value:.1f} مقابل متوسط {pm:.1f} لأشهرها السابقة (z={z:.1f})"
                    if higher else
                    f"{METRIC_NAMES_AR[metric]} في محافظة {gov} انخفض هذا الشهر: "
                    f"{value:.1f} مقابل متوسط {pm:.1f} لأشهرها السابقة (z={z:.1f})"
                )
                summary_en = (
                    f"{METRIC_NAMES_EN[metric]} in {gov} spiked this month: "
                    f"{value:.1f} vs its prior mean {pm:.1f} (z={z:.1f})"
                    if higher else
                    f"{METRIC_NAMES_EN[metric]} in {gov} dropped this month: "
                    f"{value:.1f} vs its prior mean {pm:.1f} (z={z:.1f})"
                )
                findings.append({
                    "governorate": gov,
                    "metric": metric,
                    "metric_ar": METRIC_NAMES_AR[metric],
                    "metric_en": METRIC_NAMES_EN[metric],
                    "type": "historical",
                    "observed": round(float(value), 3),
                    "benchmark": round(pm, 3),
                    "deviation_pct": round(float(dev), 1),
                    "z_score": round(float(z), 2),
                    "severity": severity,
                    "direction": "increased" if higher else "decreased",
                    "small_sample": 0 < births < _SMALL_SAMPLE_BIRTHS,
                    "summary_ar": summary_ar,
                    "summary_en": summary_en,
                })

    findings.sort(key=lambda f: (f["type"] != "cross_sectional", -abs(f["z_score"])))
    return findings[:24]


def _explain_risk(metrics_by_gov, benchmarks, risk_scores) -> List[Dict[str, Any]]:
    """تفكيك درجة الخطر لكل محافظة إلى أهم 5 عوامل (شرح SHAP-style).

    درجة الخطر مجموع خطي مُحدَّد (انحراف الوفيات + انحرافات معدلات + سريري +
    عقوبة الجودة) — فمساهمة كل عامل هي نقطته الفعلية في الدرجة، لا نموذج
    إضافي على 3-5 محافظات (سيكون غير موثوق). نُخرج مع كل عامل الانحراف %
    (بيانات العامل الفعلية) للربط ببطاقات التفاصيل.
    """
    by_gov = {r["governorate"]: r for r in risk_scores}
    out = []
    for gov, m in metrics_by_gov.items():
        rs = by_gov.get(gov)
        completeness = rs.get("completeness") if rs else None
        factors: List[Dict[str, Any]] = []

        # انحراف الوفيات (0-35 نقطة)
        bm = benchmarks.get("nmr", {})
        nmr = m.get("nmr")
        mean_v, std_v = bm.get("mean"), bm.get("std")
        if nmr is not None and mean_v and mean_v > 0:
            dev = (nmr - mean_v) / mean_v * 100
            z = (nmr - mean_v) / std_v if std_v and std_v > 0 else 0.0
            contrib = min(35.0, max(0.0, z * 7 + max(0.0, dev) / 5.0))
            factors.append({
                "feature": "nmr", "arabic_label": METRIC_NAMES_AR["nmr"],
                "contribution": round(contrib, 1),
                "deviation_pct": round(float(dev), 1),
                "observed": round(float(nmr), 3), "benchmark": round(float(mean_v), 3),
            })

        # انحراف معدلات الخطر (0-15 لكل منها)
        for metric in ("mmr", "stillbirth_rate", "cs_rate", "preterm_rate"):
            bm_m = benchmarks.get(metric, {})
            mv, bmean = m.get(metric), bm_m.get("mean")
            if mv is not None and bmean and bmean > 0:
                dev = (mv - bmean) / bmean * 100
                if dev > 0:
                    factors.append({
                        "feature": metric, "arabic_label": METRIC_NAMES_AR[metric],
                        "contribution": round(min(15.0, dev / 10.0), 1),
                        "deviation_pct": round(float(dev), 1),
                        "observed": round(float(mv), 3), "benchmark": round(float(bmean), 3),
                    })

        # مؤشرات الخطر السريرية (0-15 لكل منها)
        for metric in ("smm_rate", "high_risk_rate", "adolescent_rate"):
            bm_m = benchmarks.get(metric, {})
            mv, bmean = m.get(metric), bm_m.get("mean")
            if mv is not None and bmean and bmean > 0:
                dev = (mv - bmean) / bmean * 100
                if dev > 0:
                    factors.append({
                        "feature": metric, "arabic_label": METRIC_NAMES_AR[metric],
                        "contribution": round(min(15.0, dev / 12.0), 1),
                        "deviation_pct": round(float(dev), 1),
                        "observed": round(float(mv), 3), "benchmark": round(float(bmean), 3),
                    })

        # عقوبة نقص الاكتمال (0-15)
        if completeness is not None:
            contrib = (100.0 - completeness) / 100.0 * 15.0
            if contrib >= 0.5:
                factors.append({
                    "feature": "quality", "arabic_label": "نقص اكتمال البيانات",
                    "contribution": round(contrib, 1),
                    "deviation_pct": round(100.0 - completeness, 1),
                    "observed": round(float(completeness), 1), "benchmark": 100.0,
                })

        factors.sort(key=lambda f: f["contribution"], reverse=True)
        level = rs["level"] if rs else "low"
        out.append({
            "governorate": gov,
            "risk_score": rs["risk_score"] if rs else None,
            "level": level,
            "level_label_ar": {"high": "مرتفع", "medium": "متوسط", "low": "منخفض"}[level],
            "factors": [f for f in factors if f["contribution"] >= 0.5][:5],
            "note_ar": "تفكيك درجة الخطر إلى مساهماتها الفعلية (نقاط في الدرجة). الارتباط لا يعني سببّية.",
            "note_en": "Risk score decomposition (actual point contributions). Correlation ≠ causation.",
        })

    out.sort(key=lambda x: (x["risk_score"] or 0), reverse=True)
    return out


def _mortality_benchmark_lines(session, month: str, benchmarks, months_back: int = 6) -> Dict[str, Any]:
    """خطوط مرجعية لرسم الوفيات: المتوسط + الوسيط (هدف مرجعي) + الأساس التاريخي.

    لا يوجد هدف سريري مكوّن في النظام => الوسيط الإقليمي يُعتمد هدفاً مرجعياً
    (أقل حساسية للقيم المتطرفة من المتوسط). الأساس التاريخي = متوسط معدل
    الإقليم للأشهر السابقة (حتى 3) — الوضع قبل الشهر الحالي.
    """
    bm = benchmarks.get("nmr", {})
    lines = {
        "mean": bm.get("mean"),
        "median": bm.get("median"),
        "target": bm.get("median"),
        "target_label_ar": "الهدف المرجعي (الوسيط الإقليمي)",
        "target_label_en": "Reference target (regional median)",
    }
    per_month = _monthly_gov_metrics(session, month, months_back)
    prior = []
    for mth in sorted(per_month):
        if mth >= month:
            continue
        vals = [g.get("nmr") for g in per_month[mth].values() if g.get("nmr") is not None]
        if vals:
            prior.append(float(np.mean(vals)))
    if prior:
        lines["historical_baseline"] = round(float(np.mean(prior[-3:])), 4)
        lines["historical_baseline_label_ar"] = "الأساس التاريخي (متوسط الأشهر السابقة)"
        lines["historical_baseline_label_en"] = "Historical baseline (prior months mean)"
    else:
        lines["historical_baseline"] = None
    return lines


def _regional_trends(session, month: str, months_back: int = 6) -> List[Dict[str, Any]]:
    """اتجاهات «محافظة × شهر × مؤشر»: تدهور مستمر، تحسّن مستمر، طفرات مفاجئة.

    تُحسب المعدلات الشهرية لكل محافظة على مدى النافذة، ثم يُكشف:
    - اتجاه مستمر: انحدار خطي بـ R² ≥ 0.5 وميل يتجاوز 3% شهرياً.
    - طفرة: انحراف آخر قيمة عن متوسط ما قبلها (|z| ≥ 2).
    """
    per_month = _monthly_gov_metrics(session, month, months_back)
    window = sorted(per_month)

    findings: List[Dict[str, Any]] = []
    if len(per_month) < 3:
        return findings

    for gov in sorted({g for g in per_month.values() for g in g}):
        for metric in ("nmr", "mmr", "stillbirth_rate", "cs_rate", "preterm_rate"):
            series = []
            for m in window:
                mvals = per_month.get(m, {}).get(gov)
                v = mvals.get(metric) if mvals else None
                series.append(v)
            valid = [(m, v) for m, v in zip(window, series) if v is not None]
            if len(valid) < 3:
                continue
            months_ok = [x[0] for x in valid]
            vals = np.array([x[1] for x in valid], dtype=float)
            mean_v = float(vals.mean())
            if mean_v <= 0 or np.std(vals) < 1e-9:
                continue
            x = np.arange(len(vals), dtype=float)
            slope, intercept = np.polyfit(x, vals, 1)
            y_hat = slope * x + intercept
            ss_res = float(np.sum((vals - y_hat) ** 2))
            ss_tot = float(np.sum((vals - mean_v) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            slope_pct = slope / mean_v * 100  # % شهرياً من المتوسط

            worse = slope > 0  # كل هذه المعدلات انخفاضها أفضل

            summary_ar = summary_en = None
            if r2 >= 0.5 and abs(slope_pct) >= 3.0:
                if worse:
                    summary_ar = (
                        f"تدهور مستمر في {METRIC_NAMES_AR[metric]} بمحافظة {gov}: "
                        f"يزداد ~{abs(slope_pct):.1f}% شهرياً (R²={r2:.2f})"
                    )
                    summary_en = (
                        f"Persistent deterioration in {METRIC_NAMES_EN[metric]} in {gov}: "
                        f"~{abs(slope_pct):.1f}%/month (R²={r2:.2f})"
                    )
                else:
                    summary_ar = (
                        f"تحسّن مستمر في {METRIC_NAMES_AR[metric]} بمحافظة {gov}: "
                        f"ينخفض ~{abs(slope_pct):.1f}% شهرياً (R²={r2:.2f})"
                    )
                    summary_en = (
                        f"Persistent improvement in {METRIC_NAMES_EN[metric]} in {gov}: "
                        f"~{abs(slope_pct):.1f}%/month (R²={r2:.2f})"
                    )
                findings.append({
                    "governorate": gov,
                    "metric": metric,
                    "metric_ar": METRIC_NAMES_AR[metric],
                    "direction": "worsening" if worse else "improving",
                    "slope_pct": round(slope_pct, 2),
                    "r2": round(r2, 3),
                    "months": months_ok,
                    "values": [round(float(v), 4) for v in vals],
                    "summary_ar": summary_ar,
                    "summary_en": summary_en,
                })
            elif len(vals) >= 4:
                # طفرة مفاجئة: آخر قيمة خارج نطاق ما قبلها
                prev = vals[:-1]
                last = vals[-1]
                prev_mean = float(prev.mean())
                prev_std = float(prev.std())
                if prev_std > 1e-9:
                    z = (last - prev_mean) / prev_std
                    if abs(z) >= 2.0:
                        summary_ar = (
                            f"طفرة في {METRIC_NAMES_AR[metric]} بمحافظة {gov} آخر شهر: "
                            f"{last:.1f} مقابل متوسط {prev_mean:.1f} للأشهر السابقة (z={z:.1f})"
                        )
                        summary_en = (
                            f"Spike in {METRIC_NAMES_EN[metric]} in {gov} last month: "
                            f"{last:.1f} vs prior mean {prev_mean:.1f} (z={z:.1f})"
                        )
                        findings.append({
                            "governorate": gov,
                            "metric": metric,
                            "metric_ar": METRIC_NAMES_AR[metric],
                            "direction": "spike",
                            "spike_z": round(float(z), 2),
                            "last_value": round(float(last), 3),
                            "prior_mean": round(prev_mean, 3),
                            "months": months_ok,
                            "values": [round(float(v), 4) for v in vals],
                            "summary_ar": summary_ar,
                            "summary_en": summary_en,
                        })

    findings.sort(key=lambda f: 0 if f["direction"] == "worsening" else (1 if f["direction"] == "spike" else 2))
    return findings[:20]


def _observed_expected(metrics_by_gov: Dict[str, Dict[str, Optional[float]]], gov_names: List[str]) -> Dict[str, Any]:
    """النسبة الملاحظة/المتوقعة للوفيات (O/E) بانحدار Poisson / Negative Binomial.

    النموذج: الوفيات ~ معدلات الخطر، مع offset = log(المواليد).
    عند تشتت زائد (dispersion > 1.5) يُستبدل بـ Negative Binomial.
    البيانات غير الكافية => نموذج معياري بسيط (معدل الإقليم × مواليد).
    """
    try:
        import statsmodels.api as sm  # noqa: F401
        HAS_SM = True
    except Exception:
        HAS_SM = False

    rows = []
    for gov in gov_names:
        m = metrics_by_gov[gov]
        births = m.get("births")
        nd = m.get("nd")
        if births is None or births <= 0 or nd is None:
            continue
        rows.append({
            "gov": gov, "births": births, "nd": nd,
            "cs_rate": m.get("cs_rate"), "preterm_rate": m.get("preterm_rate"),
            "lbw_rate": m.get("lbw_rate"), "smm_rate": m.get("smm_rate"),
            "high_risk_rate": m.get("high_risk_rate"),
        })

    if not rows:
        return {"model": "none", "note_ar": "لا توجد بيانات وفيات صالحة.", "note_en": "No valid mortality data.", "results": []}

    results = []
    model_name = "simple_benchmark"
    note_ar = "بيانات غير كافية لنموذج انحداري — استُخدم معدل الإقليم كمتوقع بسيط."
    note_en = "Insufficient data for a regression model — regional rate used as simple expected."

    # معدل الإقليم كأساس
    total_births = sum(r["births"] for r in rows)
    total_nd = sum(r["nd"] for r in rows)
    regional_nmr = total_nd / total_births * 1000.0 if total_births > 0 else 0.0

    # محاولة النموذج الانحداري عند توفر بيانات كافية
    if HAS_SM and len(rows) >= 5:
        features = ["cs_rate", "preterm_rate", "lbw_rate", "smm_rate", "high_risk_rate"]
        df = [{**r, "offset": math.log(r["births"])} for r in rows]
        valid_rows = [r for r in df if all(r.get(f) is not None for f in features)]
        if len(valid_rows) >= 5:
            y = np.array([r["nd"] for r in valid_rows], dtype=float)
            X = np.array([[r[f] for f in features] for r in valid_rows], dtype=float)
            offset = np.array([r["offset"] for r in valid_rows], dtype=float)
            try:
                Xc = sm.add_constant(X)
                glm = sm.GLM(y, Xc, family=sm.families.Poisson(), offset=offset).fit()
                mu = glm.predict(Xc, offset=offset)
                disp = float(np.sum((y - mu) ** 2 / np.maximum(mu, 1e-9)) / max(1, len(y) - Xc.shape[1]))
                if disp > 1.5:
                    try:
                        glm = sm.NegativeBinomial(y, Xc, offset=offset).fit()
                        mu = glm.predict(Xc, offset=offset)
                        model_name = "negative_binomial"
                    except Exception:
                        model_name = "poisson"
                else:
                    model_name = "poisson"
                note_ar = (
                    f"نموذج انحدار {model_name.replace('_', ' ')} للوفيات ~ معدلات الخطر "
                    f"مع تعويض عدد المواليد (log offset)."
                )
                note_en = (
                    f"{model_name.replace('_', ' ')} regression of deaths ~ risk rates "
                    f"with log-birth offset."
                )
                for r, exp in zip(valid_rows, mu):
                    expected = float(exp)
                    obs = float(r["nd"])
                    oe = obs / expected if expected > 0 else None
                    results.append({
                        "governorate": r["gov"],
                        "observed": obs,
                        "expected": round(expected, 2),
                        "oe_ratio": round(oe, 2) if oe is not None else None,
                        "births": round(r["births"]),
                        "small_sample": r["births"] < _SMALL_SAMPLE_BIRTHS,
                    })
            except Exception:
                model_name = "simple_benchmark"

    if model_name == "simple_benchmark":
        for r in rows:
            expected = regional_nmr / 1000.0 * r["births"]
            oe = r["nd"] / expected if expected > 0 else None
            results.append({
                "governorate": r["gov"],
                "observed": r["nd"],
                "expected": round(expected, 2),
                "oe_ratio": round(oe, 2) if oe is not None else None,
                "births": round(r["births"]),
                "small_sample": r["births"] < _SMALL_SAMPLE_BIRTHS,
            })

    results.sort(key=lambda r: (r["oe_ratio"] if r["oe_ratio"] is not None else 0), reverse=True)
    return {
        "model": model_name,
        "regional_nmr": round(regional_nmr, 3),
        "note_ar": note_ar,
        "note_en": note_en,
        "results": results,
    }


def _births_vs_mortality(metrics_by_gov: Dict[str, Dict[str, Optional[float]]], gov_names: List[str]) -> Dict[str, Any]:
    """العلاقة بين حجم الولادات والوفيات: الخام مقابل المعياري.

    - corr_raw: ارتباط حجم الولادات بعدد الوفيات الخام (يتأثر بالحجم طبيعياً).
    - corr_rate: ارتباط حجم الولادات بمعدل الوفيات (المقارنة العادلة).
    + نقاط المبعثر وخط الانحدار للمعدل (على مستوى المحافظة).
    """
    from scipy.stats import pearsonr, spearmanr

    points = []
    for gov in gov_names:
        m = metrics_by_gov[gov]
        births = m.get("births")
        nmr = m.get("nmr")
        nd = m.get("nd")
        if births is None or births <= 0 or nmr is None or nd is None:
            continue
        points.append({"governorate": gov, "births": births, "nmr": nmr, "nd": nd})
    if len(points) < 3:
        return {"points": points, "corr_raw": None, "corr_rate": None,
                "note_ar": "بيانات غير كافية لحساب الارتباط (يلزم 3 محافظات على الأقل).",
                "note_en": "Insufficient data for correlation (need ≥3 governorates).",
                "regression": None}

    births = np.array([p["births"] for p in points], dtype=float)
    nd = np.array([p["nd"] for p in points], dtype=float)
    nmr = np.array([p["nmr"] for p in points], dtype=float)

    def _corr(x, y):
        if np.std(x) < 1e-9 or np.std(y) < 1e-9:
            return None
        r, p = pearsonr(x, y)
        rho, p_rho = spearmanr(x, y)
        return {"pearson": round(float(r), 4), "p_value": round(float(p), 4),
                "spearman": round(float(rho), 4), "spearman_p": round(float(p_rho), 4)}

    regression = None
    if np.std(births) > 1e-9 and np.std(nmr) > 1e-9:
        slope, intercept = np.polyfit(births, nmr, 1)
        regression = {"slope": round(float(slope), 6), "intercept": round(float(intercept), 4)}

    return {
        "points": points,
        "corr_raw": _corr(births, nd),
        "corr_rate": _corr(births, nmr),
        "regression": regression,
        "note_ar": (
            "ارتباط «العدد الخام» بالحجم متوقع طبيعياً (المحافظة الأكبر ولادات لديها وفيات أكثر). "
            "المقارنة العادلة هي الارتباط بـ«معدل» الوفيات. الارتباط لا يعني سببّية."
        ),
        "note_en": (
            "Raw-count correlation with volume is expected naturally (bigger governorates have "
            "more deaths). The fair comparison is the rate correlation. Correlation ≠ causation."
        ),
    }


def _risk_scores(metrics_by_gov, benchmarks, session, month, gov_names) -> List[Dict[str, Any]]:
    """درجة خطر إقليمية لكل محافظة (0-100) مع بوابة جودة تُخفض الثقة.

    المكونات: انحراف الوفيات (35) + انحراف معدلات الخطر (15) + اتجاهات (20)
    + مؤشرات الخطر السريرية (15) + عقوبة ضعف الجودة (15).
    الثقة: من اكتمال المؤشرات وصحة المقامات؛ الثقة المنخفضة تَحدّ الدرجة.
    """
    from app.models import QualityScore, ConfidenceScore, Hospital

    completeness_by_gov = {}
    confidence_by_gov = {}
    quality_by_hosp = {}
    conf_by_hosp = {}
    for q in session.query(QualityScore).filter(QualityScore.month == month).all():
        quality_by_hosp[q.hospital_id] = q
    for c in session.query(ConfidenceScore).filter(ConfidenceScore.month == month).all():
        conf_by_hosp[c.hospital_id] = c

    for h in session.query(Hospital).filter(Hospital.is_active).all():
        gov = h.governorate.name if h.governorate else "unknown"
        q = quality_by_hosp.get(h.id)
        c = conf_by_hosp.get(h.id)
        if q is not None and q.completeness is not None:
            completeness_by_gov.setdefault(gov, []).append(float(q.completeness))
        if c is not None and c.overall_confidence is not None:
            confidence_by_gov.setdefault(gov, []).append(float(c.overall_confidence))

    findings = []
    for gov in gov_names:
        m = metrics_by_gov[gov]
        comp_vals = completeness_by_gov.get(gov, [])
        completeness = round(float(np.mean(comp_vals)), 1) if comp_vals else None
        conf_vals = confidence_by_gov.get(gov, [])
        avg_confidence = round(float(np.mean(conf_vals)), 1) if conf_vals else None

        # ── مكوّن انحراف الوفيات (0-35) ──
        mortality = 0.0
        bm = benchmarks.get("nmr", {})
        nmr = m.get("nmr")
        mean_v = bm.get("mean")
        std_v = bm.get("std")
        if nmr is not None and mean_v is not None and mean_v > 0:
            dev_pct = (nmr - mean_v) / mean_v * 100
            z = (nmr - mean_v) / std_v if std_v and std_v > 0 else 0.0
            mortality = min(35.0, max(0.0, z * 7 + max(0.0, dev_pct) / 5.0))

        # ── مكوّن انحراف معدلات الخطر (0-15) ──
        rate_dev = 0.0
        worst_rate = None
        for metric in ("mmr", "stillbirth_rate", "cs_rate", "preterm_rate"):
            bm_m = benchmarks.get(metric, {})
            mv = m.get(metric)
            bmean = bm_m.get("mean")
            if mv is not None and bmean and bmean > 0:
                dev = (mv - bmean) / bmean * 100
                if dev > 0:
                    contrib = min(15.0, dev / 10.0)
                    if contrib > rate_dev:
                        rate_dev = contrib
                        worst_rate = metric

        # ── مكوّن مؤشرات الخطر السريرية (0-15) ──
        clinical = 0.0
        for metric in ("smm_rate", "high_risk_rate", "adolescent_rate"):
            bm_m = benchmarks.get(metric, {})
            mv = m.get(metric)
            bmean = bm_m.get("mean")
            if mv is not None and bmean and bmean > 0:
                dev = (mv - bmean) / bmean * 100
                if dev > 0:
                    clinical = max(clinical, min(15.0, dev / 12.0))

        # ── عقوبة ضعف الجودة (0-15): نقص الاكتمال يزيد الخطر لكنه يخفض الثقة ──
        quality_penalty = 0.0
        if completeness is not None:
            quality_penalty = (100.0 - completeness) / 100.0 * 15.0

        raw = mortality + rate_dev + clinical + quality_penalty
        score = round(min(100.0, raw), 1)

        # ── بوابة الثقة ──
        denom_ok = m.get("births") is not None and (m.get("births") or 0) > 0
        if completeness is None:
            confidence = "low"
            confidence_label_ar = "منخفضة — لا توجد درجات اكتمال"
            confidence_label_en = "Low — no completeness scores"
        elif completeness >= 70 and denom_ok:
            confidence = "high"
            confidence_label_ar = "عالية"
            confidence_label_en = "High"
        elif completeness >= 40 and denom_ok:
            confidence = "medium"
            confidence_label_ar = "متوسطة"
            confidence_label_en = "Medium"
        else:
            confidence = "low"
            confidence_label_ar = "منخفضة — بيانات غير مكتملة"
            confidence_label_en = "Low — incomplete data"

        warnings = []
        if m.get("births") is not None and 0 < m["births"] < _TINY_SAMPLE_BIRTHS:
            warnings.append("عينة صغيرة جداً — يُفسَّر بحذر شديد")
        elif m.get("births") is not None and m["births"] < _SMALL_SAMPLE_BIRTHS:
            warnings.append("حجم عينة صغير — يُفسَّر بحذر")
        if completeness is not None and completeness < 40:
            warnings.append("أقل من 40% من المؤشرات مكتملة — الاستنتاج غير موثوق")
        if not denom_ok:
            warnings.append("لا توجد بيانات مواليد صالحة كمقام")

        # الثقة المنخفضة تَحدّ الدرجة (لا خطر «مرتفع» على بيانات غير موثوقة)
        if confidence == "low":
            score = round(min(score, 60.0), 1)

        level = "high" if score >= 50 else ("medium" if score >= 25 else "low")
        level_label_ar = {"high": "مرتفع", "medium": "متوسط", "low": "منخفض"}[level]
        level_label_en = {"high": "High", "medium": "Medium", "low": "Low"}[level]

        findings.append({
            "governorate": gov,
            "risk_score": score,
            "level": level,
            "level_label_ar": level_label_ar,
            "level_label_en": level_label_en,
            "confidence": confidence,
            "confidence_label_ar": confidence_label_ar,
            "confidence_label_en": confidence_label_en,
            "completeness": completeness,
            "avg_confidence": avg_confidence,
            "components": {
                "mortality_deviation": round(mortality, 1),
                "rate_deviation": round(rate_dev, 1),
                "clinical": round(clinical, 1),
                "quality_penalty": round(quality_penalty, 1),
            },
            "worst_rate_metric": worst_rate,
            "warnings": warnings,
        })

    findings.sort(key=lambda f: f["risk_score"], reverse=True)
    return findings


def run_regional_analysis(session, month: str, months_back: int = 6) -> Dict[str, Any]:
    """التحليل الإقليمي الكامل لشهر واحد (يُخزَّن مؤقتاً لكل شهر)."""
    all_data = _load_hospital_data(session, month)
    if not all_data:
        return {
            "month": month,
            "generated_at": None,
            "governorates": [],
            "benchmarks": {},
            "mortality": [],
            "births_vs_mortality": {"points": [], "corr_raw": None, "corr_rate": None, "regression": None},
            "observed_expected": {"model": "none", "results": []},
            "trends": [],
            "risk_scores": [],
            "anomalies": [],
            "risk_explanations": [],
            "mortality_benchmarks": {},
            "referrals": {"available": False,
                          "note_ar": "لا توجد بيانات إحالات في النظام — لا يُستنتج أي تحويل بين المحافظات.",
                          "note_en": "No referral data in the system — no inter-governorate referral inference."},
        }

    govs = _gov_aggregates(all_data)
    gov_names = sorted(govs.keys())
    metrics_by_gov = {gov: _gov_metrics(govs[gov]) for gov in gov_names}
    benchmarks = _benchmarks(metrics_by_gov)

    # ── بيانات المحافظات مع الترتيب والمئوي والانحراف ──
    governorates = []
    for gov in gov_names:
        m = metrics_by_gov[gov]
        row = {
            "governorate": gov,
            "hospital_count": govs[gov]["hospital_count"],
            "hospitals": govs[gov]["hospital_names"],
            "births": m["births"],
            "deliveries": m["deliveries"],
            "cs_count": m["cs_count"],
            "mat_deaths": m["mat_deaths"],
            "nd": m["nd"],
            "sb": m["sb"],
            "rates": {},
        }
        for metric in _RATE_SCALE:
            bm = benchmarks.get(metric, {})
            vals = [metrics_by_gov[g].get(metric) for g in gov_names if metrics_by_gov[g].get(metric) is not None]
            value = m.get(metric)
            row["rates"][metric] = {
                "value": value,
                "mean": bm.get("mean"),
                "median": bm.get("median"),
                "std": bm.get("std"),
                "min": bm.get("min"),
                "max": bm.get("max"),
                "percentile": _percentile_rank(value, vals) if value is not None else None,
                "deviation_pct": (
                    round((value - bm["mean"]) / bm["mean"] * 100, 1)
                    if value is not None and bm.get("mean") else None
                ),
                "z_score": (
                    round((value - bm["mean"]) / bm["std"], 2)
                    if value is not None and bm.get("mean") is not None and bm.get("std") else None
                ),
            }
        governorates.append(row)

    # ── تحليل الوفيات الموحّد ──
    mortality = []
    for gov in gov_names:
        m = metrics_by_gov[gov]
        nmr = m.get("nmr")
        bm = benchmarks.get("nmr", {})
        mean_v = bm.get("mean")
        dev = None
        risk = "low"
        if nmr is not None and mean_v:
            dev = round((nmr - mean_v) / mean_v * 100, 1)
            risk = "high" if dev >= _DEVIATION_HIGH else ("medium" if dev >= _DEVIATION_MEDIUM else "low")
        births = m.get("births") or 0
        small_sample = 0 < births < _SMALL_SAMPLE_BIRTHS
        if small_sample and risk == "high":
            risk = "medium"  # عينة صغيرة لا تدعم «مرتفع» بثقة
        mortality.append({
            "governorate": gov,
            "observed_deaths": m.get("nd"),
            "births": m.get("births"),
            "rate": nmr,
            "benchmark": mean_v,
            "deviation_pct": dev,
            "risk": risk,
            "risk_label_ar": {"high": "مرتفع", "medium": "متوسط", "low": "منخفض"}[risk],
            "risk_label_en": {"high": "High", "medium": "Medium", "low": "Low"}[risk],
            "small_sample": small_sample,
        })
    mortality.sort(key=lambda x: (x["deviation_pct"] if x["deviation_pct"] is not None else -1e9), reverse=True)

    risk_scores = _risk_scores(metrics_by_gov, benchmarks, session, month, gov_names)

    return {
        "month": month,
        "governorates": governorates,
        "benchmarks": benchmarks,
        "mortality": mortality,
        "births_vs_mortality": _births_vs_mortality(metrics_by_gov, gov_names),
        "observed_expected": _observed_expected(metrics_by_gov, gov_names),
        "trends": _regional_trends(session, month, months_back=months_back),
        "risk_scores": risk_scores,
        "anomalies": _regional_anomalies(session, month, metrics_by_gov, benchmarks, gov_names,
                                          months_back=months_back),
        "risk_explanations": _explain_risk(metrics_by_gov, benchmarks, risk_scores),
        "mortality_benchmarks": _mortality_benchmark_lines(session, month, benchmarks,
                                                             months_back=months_back),
        "referrals": {
            "available": False,
            "note_ar": "لا توجد بيانات إحالات في النظام — لا يُستنتج أي تحويل بين المحافظات.",
            "note_en": "No referral data in the system — no inter-governorate referral inference.",
        },
    }
