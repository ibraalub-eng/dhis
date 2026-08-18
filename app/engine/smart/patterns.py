"""كشف الأنماط المركبة في المؤشرات.

يحوّل بيانات المستشفيات إلى «معاملات» (كل مستشفى = مؤشراته المرتفعة/المنخفضة)،
ثم يبحث عن التوليفات (itemsets) التي تتكرر معاً أكثر من المتوقع — مثل
«ارتفاع القيصرية + الولادات المبكرة + وفيات المولودين» في عدة مستشفيات.

المنهجية: Apriori (دعم ≥ عتبة) + Lift (تجاوز التواجد المستقل) لترتيب النتائج.
"""
from typing import Dict, List, Any, Tuple
from itertools import combinations
import numpy as np

from app.engine.smart.schemas import CompositePattern
from app.engine.smart.explainability import ARABIC_NAMES

# المؤشرات المشتركة في تحليل الشذوذ (نفس FEATURE_KEYS في anomaly.py)
PATTERN_KEYS = [
    "cs_rate", "smm_total", "mat_deaths", "nd", "sb",
    "preterm", "lbw", "high_risk", "adolescent",
]

# عتبات سريرية ثابتة للمؤشرات ذات المعنى الصحي الواضح (تُستخدم كسقف أعلى من النسبة المئوية)
_FIXED_THRESHOLDS = {
    "cs_rate": 30.0,      # WHO: >30% مرتفع بوضوح
    "smm_total": 4.0,     # ≥4 حالات مضاعفات خطيرة
    "mat_deaths": 1.0,    # أي وفاة أمومية
    "nd": 3.0,            # ≥3 وفيات مولودين
    "sb": 2.0,            # ≥2 ولادات ميتة
}

# المؤشرات التي تُعرض كنسبة مئوية
_PERCENT_KEYS = {"cs_rate"}


def _flag_indicator(value: float, key: str, pct_75: float, pct_25: float) -> str:
    """يصنّف المؤشر: elevated / lowered / none.

    القاعدة: أعلى من العتبة السريرية الثابتة أو النسبة المئوية 75 → مرتفع،
    وأقل من النسبة المئوية 25 → منخفض (للمؤشرات المستمرة فقط).
    """
    fixed = _FIXED_THRESHOLDS.get(key)
    if fixed is not None and value > fixed:
        return "elevated"
    if value > pct_75:
        return "elevated"
    if key not in _FIXED_THRESHOLDS and value < pct_25:
        return "lowered"
    return "none"


def _transactions(all_hospital_data: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """يبني معاملات المستشفيات {hospital_name: [code] } مع رفع/خفض كل مؤشر.

    رمز العلامة يحمل الحالة: 'cs_rate' = مرتفع، '_cs_rate' = منخفض.
    """
    tx = {}
    labels = {}
    # النسب المئوية تُحسب مرة واحدة لكل مؤشر على مستوى الشهر كاملاً
    series = {k: [float(e.get("values", {}).get(k)) for e in all_hospital_data.values()
                  if e.get("values", {}).get(k) is not None] for k in PATTERN_KEYS}
    percentiles = {}
    for k, vals in series.items():
        if not vals:
            continue
        percentiles[k] = (
            (float(np.percentile(vals, 75)), float(np.percentile(vals, 25)))
            if len(vals) >= 4
            else (float(np.max(vals)), float(np.min(vals)))
        )

    for name, entry in all_hospital_data.items():
        values = entry.get("values", {})
        items = []
        for key in PATTERN_KEYS:
            if key not in percentiles or values.get(key) is None:
                continue
            pct_75, pct_25 = percentiles[key]
            flag = _flag_indicator(float(values[key]), key, pct_75, pct_25)
            if flag == "elevated":
                items.append(key)
                labels[key] = "elevated"
            elif flag == "lowered":
                items.append("_" + key)
                labels["_" + key] = "lowered"
        if items:
            tx[name] = items
    return tx, labels


def _apriori_itemsets(tx: Dict[str, List[str]], min_support: float, total: int = None) -> List[Tuple[frozenset, float]]:
    """Apriori بسيط: يجد كل المجموعات المتكررة (حجم 2+) بدعم ≥ min_support.

    الدعم يُحسب على إجمالي المستشفيات (total) وليس على عدد المعاملات فقط،
    حتى لا تُبالغ النسبة عندما يكون معظم المستشفيات بلا مؤشرات مُعلَّمة.
    """
    n = total if total is not None else len(tx)
    if n == 0:
        return []

    all_items = sorted({item for items in tx.values() for item in items})

    # توليد المرشحات: أزواج ثم ثلاثيات
    frequent = []
    candidates = [frozenset(pair) for pair in combinations(all_items, 2)]
    if len(all_items) >= 3:
        candidates += [frozenset(triple) for triple in combinations(all_items, 3)]

    for cand in candidates:
        support = sum(1 for items in tx.values() if cand.issubset(items)) / n
        if support >= min_support:
            frequent.append((cand, support))

    return frequent


def _expected_support(itemset: frozenset, item_support: Dict[frozenset, float]) -> float:
    """الدعم المتوقع لو وقعت المؤشرات بشكل مستقل (حاصل ضرب دعم كل عنصر)."""
    p = 1.0
    for item in itemset:
        p *= item_support.get(frozenset([item]), 0.0)
    return p


def detect_composite_patterns(
    all_hospital_data: Dict[str, Any],
    config: Dict[str, Any],
    enabled: bool = True,
    top_n: int = 8,
) -> List[CompositePattern]:
    """يكتشف التوليفات المتكررة للمؤشرات المرتفعة/المنخفضة عبر المستشفيات."""
    if not enabled or len(all_hospital_data) < 3:
        return []

    tx, labels = _transactions(all_hospital_data)
    total_hospitals = len(all_hospital_data)  # الدعم يُحسب على كل المستشفيات لا على الحاملة فقط
    if total_hospitals < 2 or len(tx) < 2:
        return []

    configured = config.get("pattern_min_support")
    if configured is not None and str(configured).strip() != "":
        # قيمة مضبوطة صراحة من الإعدادات — تُحترم ضمن حدود معقولة
        min_support = float(configured)
    else:
        # عتبة تكيّفية حسب حجم البيانات: التوليفة تحتاج ≥ 3 مستشفيات فعلياً،
        # دون تجاوز 25% من المستشفيات ولا تقل عن 12% (يضمن أنماطاً مفيدة
        # حتى مع البيانات الصغيرة — كان السقف الثابت 25% يُخفي كل الأنماط على 17 مستشفى)
        min_support = min(0.25, max(0.12, 3.0 / total_hospitals))
    min_support = max(0.10, min(min_support, 0.45))

    itemsets = _apriori_itemsets(tx, min_support, total_hospitals)
    all_items = sorted({item for items in tx.values() for item in items})
    item_support = {
        frozenset([item]): sum(1 for items in tx.values() if item in items) / total_hospitals
        for item in all_items
    }

    patterns = []
    for itemset, support in itemsets:
        if support >= 0.95:
            continue  # نمط شبه حتمي — غير مفيد
        expected = _expected_support(itemset, item_support)
        if expected <= 0:
            continue
        lift = support / expected
        # الرفع يجب أن يكون أعلى من 1 ليبرز التوليفة كظاهرة فعلية وليس مصادفة
        if lift < 1.1:
            continue

        hospitals = [name for name, items in tx.items() if itemset.issubset(items)]
        if len(hospitals) < 2:
            continue  # نمط من مستشفى واحد ليس دليلاً على تكرار حقيقي
        names_ar = []
        statuses = []
        for item in sorted(itemset):
            key = item.lstrip("_")
            statuses.append(labels.get(item, "elevated"))
            names_ar.append(ARABIC_NAMES.get(key, key))

        parts = []
        for i, item in enumerate(sorted(itemset)):
            verb = "ارتفاع" if statuses[i] == "elevated" else "انخفاض"
            parts.append(f"{verb} {names_ar[i]}")
        summary_ar = "نمط متكرر: " + " مع ".join(parts)

        patterns.append(CompositePattern(
            indicators=sorted(itemset),
            arabic_names=names_ar,
            statuses=statuses,
            hospitals_count=len(hospitals),
            hospitals=sorted(hospitals),
            support=float(support),
            lift=float(lift),
            summary_ar=summary_ar,
        ))

    # ترتيب: قوة الرفع أولاً ثم الدعم
    patterns.sort(key=lambda p: (-p.lift, -p.support))
    return patterns[:top_n]
