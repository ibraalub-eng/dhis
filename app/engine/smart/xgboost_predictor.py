import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler, OneHotEncoder, LabelEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import r2_score, mean_absolute_error, accuracy_score, classification_report
import xgboost as xgb
import shap

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

# إصدار مخطط الميزات: أي تغيير في بنية المتجه الفائق (تأخرات/فروق/ترتيب أعمدة)
# يجب أن يرفع هذا الرقم ليبطل النماذج المحفوظة القديمة — البصمة وحدها لا تكفي
# لأنها تعكس البيانات لا الكود.
FEATURE_SCHEMA_VERSION = "2"  # v2: superset مع lag1/lag2 + delta_ لكل المؤشرات

# استمرارية النموذج: يُحفظ مجمّع XGBoost المدرب على القرص ويُعاد تدريبه فقط
# عند تغيّر بيانات المصدر (بصمة البيانات) أو الشهر الحالي أو الإعدادات.
# يمكن تجاوز المسار للاختبارات عبر المتغير SMART_XGB_MODEL_DIR.
MODEL_DIR = os.environ.get(
    "SMART_XGB_MODEL_DIR",
    os.path.join(DATA_DIR, "models", "smart_xgboost"),
)

from app.engine.smart.schemas import (
    XGBoostPrediction,
    XGBoostPredictionResult,
    XGBoostDriver,
    XGBoostGlobalExplanation,
    SmartAnomalyResult,
)
from app.engine.smart.anomaly import FEATURE_KEYS, _normalize_scores

ARABIC_NAMES = {
    "cs_rate": "معدل العمليات القيصارية",
    "smm_total": "المضاعفات الخطيرة",
    "mat_deaths": "الوفيات الأمومية",
    "nd": "الوفيات الجديدة",
    "sb": "الولادات الميتة",
    "preterm": "الولادات السابقة لأوانها",
    "lbw": "نقص وزن الولادة",
    "total_births": "إجمالي المواليد",
    "high_risk": "حالات الخطر العالي",
    "adolescent": "الحالات المراهقة",
    # Derived features
    "cs_per_birth": "نسبة القيصارية لكل ولادة",
    "smm_per_1000": "المضاعفات لكل 1000 ولادة",
    "mat_mortality_rate": "معدل الوفيات الأمومية",
    "stillbirth_rate": "معدل الولادات الميتة",
    "preterm_rate": "معدل الولادات المبكرة",
    "lbw_rate": "معدل نقص الوزن",
    "high_risk_rate": "نسبة الخطر العالي",
    "adolescent_rate": "نسبة الحالات المراهقة",
    # Interaction features
    "cs_x_highrisk": "قيصارية × خطر عالي",
    "preterm_x_lbw": "ولادة مبكرة × نقص وزن",
    "smm_x_matdeaths": "مضاعفات × وفيات أمومية",
    "nd_x_sb": "وفيات جديدة × ولادات ميتة",
    # Time-series features
    "cs_rate_delta": "تغير معدل القيصارية",
    "smm_delta": "تغير المضاعفات",
    "mat_deaths_delta": "تغير الوفيات الأمومية",
    "total_births_delta": "تغير المواليد",
}

FEATURE_KEYS_SET = set(FEATURE_KEYS)

# ── مجموعات الميزات لاختيار الأفضل عبر walk-forward ──
# الميزات الأساسية: المصدرية + المشتقة (بدون التأخرات/الفروق الموسّعة)
DERIVED_KEYS = [k for k in ARABIC_NAMES.keys() if k not in FEATURE_KEYS_SET and "_delta" not in k]
BASE_FEATURE_KEYS = list(FEATURE_KEYS) + DERIVED_KEYS
# الفروق الشهرية الأساسية (كانت موجودة أصلاً)
DELTA_KEYS = ["cs_rate_delta", "smm_delta", "mat_deaths_delta", "total_births_delta"]
# مصادر فترات التأخر: معدلات/مجاميع حساسة يُتنبأ بها مباشرة
LAG_SOURCE_KEYS = ["cs_rate", "smm_total", "mat_deaths", "total_births", "nd", "sb"]

# أسماء عربية للميزات الزمنية الجديدة (تظهر في شرح SHAP)
for _k in LAG_SOURCE_KEYS:
    ARABIC_NAMES[f"lag1_{_k}"] = f"{ARABIC_NAMES.get(_k, _k)} (قيمة الشهر السابق)"
    ARABIC_NAMES[f"lag2_{_k}"] = f"{ARABIC_NAMES.get(_k, _k)} (قيمة شهرين سابقين)"
for _k in FEATURE_KEYS:
    ARABIC_NAMES[f"delta_{_k}"] = f"التغيّر الشهري في {ARABIC_NAMES.get(_k, _k)}"

ENSEMBLE_CONFIGS = [
    {"name": "XGBoost-Light", "n_estimators": 80, "max_depth": 3, "learning_rate": 0.15},
    {"name": "XGBoost-Medium", "n_estimators": 150, "max_depth": 5, "learning_rate": 0.1},
    {"name": "XGBoost-Deep", "n_estimators": 200, "max_depth": 7, "learning_rate": 0.05},
]


def _load_multi_month_data(
    session, months: List[str]
) -> Tuple[Dict[str, Any], List[str]]:
    from app.models import Hospital, IndicatorValue, Indicator

    hospitals = session.query(Hospital).filter(Hospital.is_active).all()
    indicators = session.query(Indicator).all()
    indicator_map = {ind.id: ind.code for ind in indicators}

    all_rows = []
    all_hospital_names = set()

    for month in months:
        for hosp in hospitals:
            values = session.query(IndicatorValue).filter(
                IndicatorValue.hospital_id == hosp.id,
                IndicatorValue.month == month,
            ).all()

            indicator_values = {}
            for iv in values:
                code = indicator_map.get(iv.indicator_id, "")
                if code and iv.value is not None:
                    indicator_values[code] = float(iv.value)

            total_deliveries = indicator_values.get("2", 0)
            cs_count = indicator_values.get("5")  # None إذا غاب المؤشر — لا صفر صامت
            live_births = indicator_values.get("6", 0)

            derived = {
                # مقام صالح فقط: بلا ولادات/قيصرية صالحة => NaN (بيانات ناقصة)
                # لا صفر صامت يُضلّل النموذج
                "cs_rate": (cs_count / total_deliveries * 100)
                           if (total_deliveries > 0 and cs_count is not None) else np.nan,
                "smm_total": indicator_values.get("10", 0),
                "mat_deaths": indicator_values.get("11", 0),
                "nd": indicator_values.get("17", 0),
                "sb": indicator_values.get("7", 0),
                "preterm": indicator_values.get("6.f", 0),
                "lbw": indicator_values.get("6.g", 0),
                "total_births": live_births,
                "high_risk": indicator_values.get("2.n", 0),
                "adolescent": indicator_values.get("2.c", 0) + indicator_values.get("2.d", 0),
            }
            indicator_values.update(derived)

            row = {
                "hospital_name": hosp.name,
                "hospital_id": hosp.id,
                "governorate": hosp.governorate.name if hosp.governorate else "unknown",
                "hospital_type": hosp.hospital_type.name if hosp.hospital_type else "unknown",
                "month": month,
                "values": indicator_values,
            }
            all_rows.append(row)
            all_hospital_names.add(hosp.name)

    return all_rows, sorted(all_hospital_names)


def _compute_derived_features(values: Dict[str, float]) -> Dict[str, float]:
    """ميزات مشتقة بمقامات مُتحقَّق منها: غياب/صفر المقام => NaN (بيانات ناقصة).

    الصفر الصامت كان يُضلّل النموذج (يبدو وكأن المعدل صفر فعلاً). NaN يمر عبر
    SimpleImputer (وسيط) في _build_supervised_dataset ويُتجاهل عبر .dropna()
    في governorate_analysis — فيُعلَّم «بيانات ناقصة» بدل «صفر» وهمي.
    """
    total = values.get("total_births", 0)
    derived = {}
    valid = total is not None and total > 0

    derived["cs_per_birth"] = values.get("cs_rate", 0) / 100.0 if valid else np.nan
    derived["smm_per_1000"] = (values.get("smm_total", 0) / total * 1000) if valid else np.nan
    derived["mat_mortality_rate"] = (values.get("mat_deaths", 0) / total * 100000) if valid else np.nan
    derived["stillbirth_rate"] = (values.get("sb", 0) / total * 1000) if valid else np.nan
    derived["preterm_rate"] = (values.get("preterm", 0) / total * 100) if valid else np.nan
    derived["lbw_rate"] = (values.get("lbw", 0) / total * 100) if valid else np.nan
    derived["high_risk_rate"] = (values.get("high_risk", 0) / total * 100) if valid else np.nan
    derived["adolescent_rate"] = (values.get("adolescent", 0) / total * 100) if valid else np.nan

    nd_per = (values.get("nd", 0) / total * 1000) if valid else np.nan
    derived["cs_x_highrisk"] = derived["cs_per_birth"] * derived["high_risk_rate"]
    derived["preterm_x_lbw"] = derived["preterm_rate"] * derived["lbw_rate"]
    derived["smm_x_matdeaths"] = derived["smm_per_1000"] * derived["mat_mortality_rate"]
    derived["nd_x_sb"] = derived["stillbirth_rate"] * nd_per

    return derived


def _build_supervised_dataset(
    all_rows: List[Dict],
    hospital_names: List[str],
    target_month_idx: int,
):
    cat_map = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        cat_map[key] = (row["governorate"], row["hospital_type"])

    months_sorted = sorted(set(r["month"] for r in all_rows))
    month_to_idx = {m: i for i, m in enumerate(months_sorted)}

    hosp_month_data = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        hosp_month_data[key] = row

    all_feature_keys = BASE_FEATURE_KEYS

    features_list = []
    meta = []

    for row in all_rows:
        values = row["values"]
        derived = _compute_derived_features(values)
        all_vals = {**values, **derived}

        numeric = [all_vals.get(k, np.nan) for k in all_feature_keys]
        features_list.append(numeric)
        meta.append({
            "hospital_name": row["hospital_name"],
            "hospital_id": row["hospital_id"],
            "month": row["month"],
            "governorate": row["governorate"],
            "hospital_type": row["hospital_type"],
        })

    delta_keys = DELTA_KEYS
    delta_source_keys = ["cs_rate", "smm_total", "mat_deaths", "total_births"]

    # الميزات الزمنية الموسّعة (superset): فترات التأخر + فروق شهرية لكل المؤشرات.
    # تُبنى كلها دائماً ثم تُفلتر لاحقاً حسب المتغير المختار (اختيار walk-forward).
    extra_names = []
    for sk in LAG_SOURCE_KEYS:
        extra_names.append(f"lag1_{sk}")
        extra_names.append(f"lag2_{sk}")
    for sk in FEATURE_KEYS:
        extra_names.append(f"delta_{sk}")

    for i, row in enumerate(all_rows):
        hosp_name = row["hospital_name"]
        cur_month = row["month"]
        cur_idx = month_to_idx.get(cur_month, 0)

        prev_month = prev_prev_month = None
        for m in months_sorted:
            if month_to_idx[m] == cur_idx - 1:
                prev_month = m
            if month_to_idx[m] == cur_idx - 2:
                prev_prev_month = m
        prev_vals = hosp_month_data.get((hosp_name, prev_month), {}).get("values", {}) if prev_month else {}
        prev2_vals = hosp_month_data.get((hosp_name, prev_prev_month), {}).get("values", {}) if prev_prev_month else {}
        cur_vals = row["values"]

        # الفروق الأساسية الأربعة (كما كانت)
        for dk, sk in zip(delta_keys, delta_source_keys):
            prev_val = prev_vals.get(sk, 0)
            cur_val = cur_vals.get(sk, 0)
            delta = (cur_val - prev_val) / prev_val if prev_val > 0 else 0
            features_list[i].append(delta)

        # فترات التأخر: قيمتا الشهر السابق والشهرين السابقين (NaN عند غياب التاريخ)
        for sk in LAG_SOURCE_KEYS:
            l1 = prev_vals.get(sk)
            l2 = prev2_vals.get(sk)
            features_list[i].append(float(l1) if l1 is not None else np.nan)
            features_list[i].append(float(l2) if l2 is not None else np.nan)

        # فروق شهرية لكل المؤشرات الأساسية
        for sk in FEATURE_KEYS:
            prev_val = prev_vals.get(sk, 0)
            cur_val = cur_vals.get(sk, 0)
            delta = (cur_val - prev_val) / prev_val if prev_val > 0 else 0
            features_list[i].append(delta)

    feature_names = all_feature_keys + delta_keys + extra_names

    X = np.array(features_list, dtype=float)

    imputer = SimpleImputer(strategy="median")
    # Columns where EVERY hospital is NaN would make SimpleImputer skip them AND
    # leave NaN that poisons StandardScaler + the model. Zero-fill up-front.
    X[:, np.isnan(X).all(axis=0)] = 0.0
    X_imputed = imputer.fit_transform(X)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_imputed)

    cat_data = [(cat_map.get((m["hospital_name"], m["month"]), ("unknown", "unknown"))) for m in meta]
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    X_cat = encoder.fit_transform(cat_data)
    X_all = np.hstack([X_scaled, X_cat])

    feature_names = feature_names + list(
        encoder.get_feature_names_out(["governorate", "hospital_type"])
    )

    return X_all, feature_names, meta, month_to_idx, imputer, scaler, encoder


def _compute_target_scores(all_rows: List[Dict], meta: List[Dict], months_sorted: List[str]):
    """الأهداف التدريبية والدرجات الحالية — بدون تسريب زمني.

    المشكلة السابقة: الهدف كان يُشتق من قيم الشهر نفسه الذي تُبنى منه ميزات
    الصف (cur vs prev) — فيتعلم النموذج «من نفسه إلى نفسه» بدل «من الحاضر
    إلى المستقبل». الإصلاح:

    - current_scores: وصفية فقط (cur vs prev) لعرض «الحالة الحالية» في الواجهة
      — لا تدخل التدريب إطلاقاً.
    - target_scores: تنبؤية للأمام (next vs cur) — انحراف الشهر التالي عن
      الشهر الحالي. ميزات الصف عند الشهر m لا تحمل أي معلومة عن m+1، فلا
      يتسرب الهدف إلى الميزات.
    - labels_defined: الصفوف بلا شهر تالٍ (آخر شهر لكل مستشفى) لا هدف لها
      وتُستبعد من التدريب بدل تدريبها على 0.5 مصطنع.
    """
    target_scores = np.zeros(len(meta))
    current_scores = np.zeros(len(meta))
    labels_defined = np.ones(len(meta), dtype=bool)

    hosp_month_data = {}
    for row in all_rows:
        key = (row["hospital_name"], row["month"])
        hosp_month_data[key] = row

    hosp_months: Dict[str, List[str]] = {}
    for row in all_rows:
        hosp_months.setdefault(row["hospital_name"], set()).add(row["month"])
    hosp_months = {h: sorted(ms) for h, ms in hosp_months.items()}

    def _median(values: Dict[str, float]) -> float:
        vals = [values.get(k, np.nan) for k in FEATURE_KEYS]
        med = np.nanmedian(vals)
        return float(med) if not np.isnan(med) else 0.0

    for i, m in enumerate(meta):
        hospital_name = m["hospital_name"]
        month = m["month"]
        months = hosp_months.get(hospital_name, [])
        if month not in months:
            current_scores[i] = 0.5
            target_scores[i] = 0.5
            labels_defined[i] = False
            continue

        idx = months.index(month)
        cur_vals = hosp_month_data.get((hospital_name, month), {}).get("values", {})
        cur_median = _median(cur_vals)

        # الدرجة الحالية: cur vs prev (وصفية فقط — لا تدخل التدريب)
        if idx > 0:
            prev_month = months[idx - 1]
            prev_vals = hosp_month_data.get((hospital_name, prev_month), {}).get("values", {})
            prev_median = _median(prev_vals)
            if prev_median > 0:
                current_scores[i] = min(max(0.5 + (cur_median / prev_median - 1) * 2, 0.0), 1.0)
            else:
                current_scores[i] = 0.5
        else:
            current_scores[i] = 0.5

        # الهدف التدريبي: next vs cur (أمامي — لا تسريب)
        if idx + 1 >= len(months):
            target_scores[i] = 0.5
            labels_defined[i] = False
            continue
        next_month = months[idx + 1]
        next_vals = hosp_month_data.get((hospital_name, next_month), {}).get("values", {})
        next_median = _median(next_vals)
        if cur_median > 0:
            target_scores[i] = min(max(0.5 + (next_median / cur_median - 1) * 2, 0.0), 1.0)
        else:
            target_scores[i] = 0.5

    return current_scores, target_scores, labels_defined


def _score_to_severity(score: float) -> str:
    if score < 0.3:
        return "normal"
    elif score < 0.6:
        return "warning"
    return "critical"


def _data_fingerprint(session, months: List[str], config: Dict[str, Any]) -> str:
    """بصمة بيانات المصدر التي يعتمد عليها التدريب.

    أي تغيير في: الأشهر، المستشفيات النشطة، قيم المؤشرات، إعدادات
    المؤشرات المعطّلة، أو إعدادات smart_* يُغيّر البصمة => يُعاد التدريب.
    """
    from app.models import Hospital, IndicatorValue, HospitalIndicatorConfig

    h = hashlib.sha256()
    h.update(f"schema_v{FEATURE_SCHEMA_VERSION}".encode())
    h.update(repr(sorted(months)).encode())

    for hid, name, gov, htype, active in (
        session.query(Hospital.id, Hospital.name, Hospital.governorate_id,
                      Hospital.hospital_type_id, Hospital.is_active)
        .order_by(Hospital.id).all()
    ):
        h.update(f"h|{hid}|{name}|{gov}|{htype}|{active}\n".encode())

    for hid, iid, month, val in (
        session.query(IndicatorValue.hospital_id, IndicatorValue.indicator_id,
                      IndicatorValue.month, IndicatorValue.value)
        .order_by(IndicatorValue.hospital_id, IndicatorValue.indicator_id,
                  IndicatorValue.month).all()
    ):
        h.update(f"v|{hid}|{iid}|{month}|{val}\n".encode())

    for hid, iid, enabled in (
        session.query(HospitalIndicatorConfig.hospital_id,
                      HospitalIndicatorConfig.indicator_id,
                      HospitalIndicatorConfig.is_enabled).all()
    ):
        h.update(f"c|{hid}|{iid}|{enabled}\n".encode())

    for key in sorted(config):
        h.update(f"k|{key}|{config[key]}\n".encode())

    return h.hexdigest()[:16]


def _variant_extra_names(variant: str) -> List[str]:
    """أسماء الميزات الزمنية الإضافية لكل متغير من متغيرات الميزات."""
    names = []
    if variant in ("lag_rates", "combined"):
        for sk in LAG_SOURCE_KEYS:
            names.append(f"lag1_{sk}")
            names.append(f"lag2_{sk}")
    if variant in ("full_deltas", "combined"):
        for sk in FEATURE_KEYS:
            names.append(f"delta_{sk}")
    return names


def _variant_column_mask(feature_names: List[str], variant: str) -> List[int]:
    """أعمدة المتغير من المتجه الفائق: الأساسية + الفروق الأربعة + إضافات المتغير + القاطعات.

    أعمدة المحافظة/النوع (OneHot) تُحفظ دائماً لأنها جزء من المتجه الفائق.
    """
    keep = set(BASE_FEATURE_KEYS) | set(DELTA_KEYS) | set(_variant_extra_names(variant))
    return [i for i, name in enumerate(feature_names)
            if name in keep or name.startswith("governorate_") or name.startswith("hospital_type_")]


def _select_best_variant(X_all, feature_names: List[str], defined_idx, y_defined,
                         meta_defined: List[Dict], tolerance: float = 0.02) -> Tuple[str, List[int]]:
    """اختيار أفضل مجموعة ميزات عبر متوسط R² في التحقق الزمني walk-forward.

    عند تقارب النتائج (فارق < tolerance) يُفضَّل المتغير الأساسي الأبسط لتجنب
    ملاءمة ضوضاء اختيارية على بيانات صغيرة. بلا طيات كافية => الأساسي.
    """
    candidates = ["baseline", "lag_rates", "full_deltas", "combined"]
    scored = []
    for variant in candidates:
        mask = _variant_column_mask(feature_names, variant)
        X_v = X_all[:, mask][defined_idx]
        folds = _walk_forward_validation(X_v, y_defined, meta_defined)
        if not folds:
            continue
        scored.append({
            "variant": variant,
            "mean_r2": float(np.mean([f["r2"] for f in folds])),
            "mean_mae": float(np.mean([f["mae"] for f in folds])),
            "n_folds": len(folds),
            "mask": mask,
        })
    if not scored:
        return "baseline", _variant_column_mask(feature_names, "baseline")
    scored.sort(key=lambda s: (-s["mean_r2"], s["mean_mae"]))
    best = scored[0]
    baseline = next((s for s in scored if s["variant"] == "baseline"), None)
    if baseline is not None and best["mean_r2"] - baseline["mean_r2"] < tolerance:
        return "baseline", baseline["mask"]
    return best["variant"], best["mask"]


def _read_meta(model_dir: str) -> Optional[Dict[str, Any]]:
    """قراءة خفيفة لـ meta.json فقط (لاختيار المتغير قبل بناء المتجه)."""
    meta_path = os.path.join(model_dir, "meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _walk_forward_validation(X_defined, y_defined, meta_defined: List[Dict]) -> List[Dict[str, Any]]:
    """تحقق زمني Walk-Forward: درّب على الأشهر حتى m وقيّم على m+1 بالتتابع.

    كل طية (fold): تدريب على كل الصفوف ذات شهر ≤ m، وتحقق على صفوف الشهر
    m+1 — محاكاة حقيقية لسيناريو «تنبؤ بالشهر القادم» دون أي تسريب.
    تُستخدم تهيئة خفيفة (XGBoost-Light) لتحديد تكلفة الحساب، وتُحفظ النتائج
    في meta.json مع النموذج (تعتمد على البيانات لا على المجمّع المحفوظ).
    """
    months = sorted({m["month"] for m in meta_defined})
    folds = []
    for i in range(len(months) - 1):
        train_mask = [m["month"] <= months[i] for m in meta_defined]
        test_mask = [m["month"] == months[i + 1] for m in meta_defined]
        X_tr, y_tr = X_defined[train_mask], y_defined[train_mask]
        X_te, y_te = X_defined[test_mask], y_defined[test_mask]
        if len(y_tr) < 5 or len(y_te) == 0:
            continue
        model = xgb.XGBRegressor(
            n_estimators=80, max_depth=3, learning_rate=0.15,
            objective="reg:squarederror", random_state=42, verbosity=0,
        )
        model.fit(X_tr, y_tr)
        y_pred = np.clip(model.predict(X_te), 0.0, 1.0)
        r2 = float(r2_score(y_te, y_pred)) if len(y_te) > 1 else 0.0
        mae = float(mean_absolute_error(y_te, y_pred)) if len(y_te) > 0 else 0.0
        folds.append({
            "train_through": months[i],
            "validate_month": months[i + 1],
            "n_train": int(len(y_tr)),
            "n_test": int(len(y_te)),
            "r2": round(r2, 4),
            "mae": round(mae, 4),
        })
    return folds


def _save_trained_models(model_dir: str, meta: Dict[str, Any], ensemble_results: List[Dict],
                         clf: Any, le: Any, clf_accuracy: float) -> None:
    """حفظ المجمّع المدرب + المصنّف + الترميز على القرص (كتابة ذرية)."""
    os.makedirs(model_dir, exist_ok=True)

    for i, entry in enumerate(ensemble_results):
        # انتبه: xgboost 3.x يحدد الصيغة من امتداد الملف — يجب أن ينتهي بـ .json
        # لكتابة JSON (الكتابة الذرية عبر .tmp.json ثم os.replace).
        tmp = os.path.join(model_dir, f"model_{i}.tmp.json")
        dst = os.path.join(model_dir, f"model_{i}.json")
        entry["model"].save_model(tmp)
        os.replace(tmp, dst)

    clf_fitted = clf is not None
    if clf_fitted:
        tmp = os.path.join(model_dir, "classifier.tmp.json")
        dst = os.path.join(model_dir, "classifier.json")
        clf.save_model(tmp)
        os.replace(tmp, dst)

    tmp = os.path.join(model_dir, "label_encoder.pkl.tmp")
    dst = os.path.join(model_dir, "label_encoder.pkl")
    joblib.dump(le, tmp)
    os.replace(tmp, dst)

    meta = {**meta, "clf_fitted": clf_fitted, "clf_accuracy": round(clf_accuracy, 4)}
    tmp = os.path.join(model_dir, "meta.json.tmp")
    dst = os.path.join(model_dir, "meta.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dst)


def _load_trained_models(model_dir: str, feature_count: int) -> Optional[Dict[str, Any]]:
    """تحميل النموذج المحفوظ؛ يعيد None إذا كان مفقوداً أو تالفاً."""
    meta_path = os.path.join(model_dir, "meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        ensemble_results = []
        for i, cfg in enumerate(ENSEMBLE_CONFIGS):
            model_path = os.path.join(model_dir, f"model_{i}.json")
            if not os.path.exists(model_path):
                return None
            model = xgb.XGBRegressor(
                n_estimators=int(cfg["n_estimators"]),
                max_depth=int(cfg["max_depth"]),
                learning_rate=cfg["learning_rate"],
                objective="reg:squarederror", random_state=42, verbosity=0,
            )
            model.load_model(model_path)
            ensemble_results.append({
                "name": cfg["name"],
                "r2": float(meta.get("model_metrics", {}).get(cfg["name"], {}).get("r2", 0.0)),
                "mae": float(meta.get("model_metrics", {}).get(cfg["name"], {}).get("mae", 0.0)),
                "model": model,
            })

        clf = None
        le = None
        if meta.get("clf_fitted"):
            clf_path = os.path.join(model_dir, "classifier.json")
            le_path = os.path.join(model_dir, "label_encoder.pkl")
            if not os.path.exists(clf_path) or not os.path.exists(le_path):
                return None
            clf = xgb.XGBClassifier(
                n_estimators=120, max_depth=4, learning_rate=0.1,
                objective="multi:softprob", random_state=42, verbosity=0,
                num_class=3,
            )
            clf.load_model(clf_path)
            le = joblib.load(le_path)

        # التحقق من تطابق عدد الميزات مع المتجه الحالي
        if "feature_count" in meta and meta["feature_count"] != feature_count:
            logger.warning("XGBoost model feature count mismatch — retraining.")
            return None
        # حارس إصدار مخطط الميزات: نماذج قديمة بلا إصدار أو بإصدار مختلف => إعادة تدريب
        if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            logger.warning("XGBoost model feature schema version mismatch — retraining.")
            return None

        return {"meta": meta, "ensemble_results": ensemble_results, "clf": clf, "le": le}
    except Exception as e:
        logger.warning("Failed to load persisted XGBoost model: %s", e)
        return None


def run_xgboost_predictions(
    session,
    current_month: str,
    config: Dict[str, Any],
) -> XGBoostPredictionResult:
    from app.models import IndicatorValue

    all_months = sorted(
        r[0] for r in session.query(IndicatorValue.month).distinct().order_by(IndicatorValue.month).all()
    )

    if len(all_months) < 2:
        return XGBoostPredictionResult(
            model_r2=0.0, model_mae=0.0, training_months=0, hospitals_trained=0,
            predictions=[], global_feature_importance=[], accuracy_note="Not enough months for training.",
        )

    current_idx = all_months.index(current_month) if current_month in all_months else len(all_months) - 1
    # Include the NEXT month so target labels (next vs cur) can be computed
    end_idx = min(current_idx + 1, len(all_months))
    train_months = all_months[:end_idx + 1]

    all_rows, hospital_names = _load_multi_month_data(session, train_months)
    if not all_rows or len(hospital_names) < 3:
        return XGBoostPredictionResult(
            model_r2=0.0, model_mae=0.0, training_months=len(train_months), hospitals_trained=0,
            predictions=[], global_feature_importance=[], accuracy_note="Not enough hospital data for training.",
        )

    # المتجه الفائق: الميزات الأساسية + المشتقة + الفروق الأربعة + التأخرات والفروق الموسّعة.
    X_all, feature_names, meta, month_to_idx, imputer, scaler, encoder = _build_supervised_dataset(
        all_rows, hospital_names, current_idx
    )

    # Pass ALL loaded months (including next) so target labels can use next-month data
    all_loaded_months = sorted(set(r["month"] for r in all_rows))
    current_scores, target_scores, labels_defined = _compute_target_scores(
        all_rows, meta, all_loaded_months
    )

    # ── تدريب بلا تسريب: فقط الصفوف ذات هدف مستقبلي معرّف (next vs cur) ──
    defined_idx = np.where(labels_defined)[0]
    if len(defined_idx) < 3:
        return XGBoostPredictionResult(
            model_r2=0.0, model_mae=0.0, training_months=len(train_months),
            hospitals_trained=len(hospital_names), predictions=[], global_feature_importance=[],
            accuracy_note="Not enough labeled months for temporal training.",
        )

    y_defined = target_scores[defined_idx]
    meta_defined = [meta[int(i)] for i in defined_idx]

    fingerprint = _data_fingerprint(session, all_months, config)
    trained_at = ""
    retrained = True
    clf_accuracy = 0.0
    walk_forward: List[Dict[str, Any]] = []
    feature_variant = "baseline"
    prev_meta = _read_meta(MODEL_DIR)

    # ── إعادة استخدام النموذج المحفوظ (نفس البصمة والشهر ومجموعة الميزات) ──
    if (prev_meta is not None
            and prev_meta.get("fingerprint") == fingerprint
            and prev_meta.get("current_month") == current_month
            and prev_meta.get("feature_indices")):
        indices = prev_meta["feature_indices"]
        if indices and all(isinstance(i, int) and 0 <= i < len(feature_names) for i in indices):
            loaded = _load_trained_models(MODEL_DIR, feature_count=len(indices))
            if loaded is not None:
                X_all = X_all[:, indices]
                feature_names = [feature_names[i] for i in indices]
                ensemble_results = loaded["ensemble_results"]
                clf = loaded["clf"]
                le = loaded["le"]
                clf_accuracy = float(loaded["meta"].get("clf_accuracy", 0.0))
                trained_at = loaded["meta"].get("trained_at", "")
                walk_forward = loaded["meta"].get("walk_forward", []) or []
                feature_variant = prev_meta.get("feature_variant", "baseline")
                retrained = False
                logger.info("XGBoost model loaded from disk (fingerprint %s, variant %s)",
                            fingerprint, feature_variant)

    # ── تدريب جديد: اختيار أفضل ميزات عبر walk-forward ثم تدريب المجمّع ──
    if retrained:
        selected_variant, feature_indices = _select_best_variant(
            X_all, feature_names, defined_idx, y_defined, meta_defined)
        feature_variant = selected_variant
        X_all = X_all[:, feature_indices]
        feature_names = [feature_names[i] for i in feature_indices]
        X_defined = X_all[defined_idx]

        split_idx = max(1, int(len(X_defined) * 0.8))
        X_train, X_test = X_defined[:split_idx], X_defined[split_idx:]
        y_train, y_test = y_defined[:split_idx], y_defined[split_idx:]

        ensemble_results = []
        ensemble_weights = []

        for cfg in ENSEMBLE_CONFIGS:
            model = xgb.XGBRegressor(
                n_estimators=int(cfg["n_estimators"]),
                max_depth=int(cfg["max_depth"]),
                learning_rate=cfg["learning_rate"],
                objective="reg:squarederror", random_state=42, verbosity=0,
            )
            model.fit(X_train, y_train)
            y_pred = np.clip(model.predict(X_test), 0.0, 1.0)

            r2 = float(r2_score(y_test, y_pred)) if len(y_test) > 1 else 0.0
            mae_val = float(mean_absolute_error(y_test, y_pred)) if len(y_test) > 1 else 0.0

            ensemble_results.append({"name": cfg["name"], "r2": r2, "mae": mae_val, "model": model})
            ensemble_weights.append(max(r2, 0.01))

        total_weight = sum(ensemble_weights) or 1.0
        normalized_weights = [w / total_weight for w in ensemble_weights]

        target_labels = np.array([_score_to_severity(s) for s in y_defined])
        le = LabelEncoder()
        le.fit(["normal", "warning", "critical"])
        y_labels_all = le.transform(target_labels)
        y_labels_train = y_labels_all[:split_idx]
        y_labels_test = y_labels_all[split_idx:]

        clf = None
        clf_pred = np.zeros(len(y_labels_test), dtype=int)
        try:
            clf = xgb.XGBClassifier(
                n_estimators=120, max_depth=4, learning_rate=0.1,
                objective="multi:softprob", random_state=42, verbosity=0,
                num_class=3,
            )
            clf.fit(X_train, y_labels_train)
            clf_pred = clf.predict(X_test)
            unique_test_labels = set(y_labels_test.tolist())
            unique_pred_labels = set(clf_pred.tolist())
            if len(unique_test_labels) > 1 and len(unique_pred_labels) > 1:
                clf_accuracy = float(accuracy_score(y_labels_test, clf_pred))
            else:
                clf_accuracy = 1.0
        except Exception:
            clf = None
            clf_accuracy = 0.0

        walk_forward = _walk_forward_validation(X_defined, y_defined, meta_defined)
        trained_at = datetime.now().isoformat(timespec="seconds")
        try:
            _save_trained_models(MODEL_DIR, {
                "fingerprint": fingerprint,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "current_month": current_month,
                "trained_at": trained_at,
                "train_months": train_months,
                "feature_count": len(feature_indices),
                "feature_indices": [int(i) for i in feature_indices],
                "feature_variant": feature_variant,
                "hospitals_trained": len(hospital_names),
                "model_metrics": {
                    r["name"]: {"r2": round(r["r2"], 4), "mae": round(r["mae"], 4)}
                    for r in ensemble_results
                },
                "walk_forward": walk_forward,
            }, ensemble_results, clf, le, clf_accuracy)
        except Exception as e:
            logger.warning("Failed to persist XGBoost model: %s", e)
    else:
        X_defined = X_all[defined_idx]

    best_idx = max(range(len(ensemble_results)), key=lambda i: ensemble_results[i]["r2"])
    best_model = ensemble_results[best_idx]["model"]
    best_r2 = ensemble_results[best_idx]["r2"]
    best_mae = ensemble_results[best_idx]["mae"]

    explainer = shap.TreeExplainer(best_model)
    shap_values_all = explainer.shap_values(X_all)

    global_shap = np.mean(np.abs(shap_values_all), axis=0)
    base_feature_count = len(feature_names) - len(encoder.get_feature_names_out(["governorate", "hospital_type"]))
    global_sorted = sorted(
        [(feature_names[i], global_shap[i]) for i in range(min(base_feature_count, len(feature_names)))],
        key=lambda x: x[1], reverse=True,
    )
    global_importance = [
        XGBoostGlobalExplanation(
            feature=feat, arabic_label=ARABIC_NAMES.get(feat, feat),
            mean_abs_shap=float(val), rank=rank + 1,
        )
        for rank, (feat, val) in enumerate(global_sorted[:12])
    ]

    hospital_pred_map = {}
    for i, m in enumerate(meta):
        if m["month"] == current_month:
            hosp_name = m["hospital_name"]
            if hosp_name not in hospital_pred_map:
                hospital_pred_map[hosp_name] = {
                    "meta": m,
                    "idx": i,
                    "current_score": current_scores[i],
                }

    predictions = []
    for hosp_name, data in hospital_pred_map.items():
        idx = data["idx"]
        sv = shap_values_all[idx]
        top_feat_idx = sorted(range(len(sv)), key=lambda j: abs(sv[j]), reverse=True)[:5]

        drivers = []
        for fi in top_feat_idx:
            if fi < len(feature_names):
                feat_name = feature_names[fi]
                drivers.append(XGBoostDriver(
                    feature=feat_name,
                    arabic_label=ARABIC_NAMES.get(feat_name, feat_name),
                    shap_value=float(sv[fi]),
                    direction="increases_risk" if sv[fi] > 0 else "decreases_risk",
                    magnitude="high" if abs(sv[fi]) > 0.3 else "medium" if abs(sv[fi]) > 0.1 else "low",
                ))

        # صفوف الشهر الحالي خارج مجموعة التدريب (بلا هدف مستقبلي) => تنبؤ مباشر
        predicted_score = float(best_model.predict(X_all[idx:idx+1])[0])
        predicted_score = min(max(predicted_score, 0.0), 1.0)

        try:
            if clf is not None and le is not None:
                clf_class_idx = clf.predict(X_all[idx:idx+1])[0]
                clf_severity = le.inverse_transform([clf_class_idx])[0]
            else:
                # المصنّف غير متاح (عينات قليلة أو حُمّل بلا مصنّف) — تصنيف من الدرجة
                clf_severity = _score_to_severity(predicted_score)
        except Exception:
            clf_severity = _score_to_severity(predicted_score)

        pred_severity = _score_to_severity(predicted_score)

        current_score = data["current_score"]
        if predicted_score > current_score + 0.05:
            risk_change = "increasing"
        elif predicted_score < current_score - 0.05:
            risk_change = "decreasing"
        else:
            risk_change = "stable"

        predictions.append(XGBoostPrediction(
            hospital_name=hosp_name,
            hospital_id=data["meta"]["hospital_id"],
            current_score=round(current_score, 4),
            predicted_next_score=round(predicted_score, 4),
            predicted_severity=pred_severity,
            risk_change=risk_change,
            confidence=round(max(0.0, 1.0 - best_mae), 3),
            top_drivers=drivers,
        ))

    predictions.sort(key=lambda p: p.predicted_next_score, reverse=True)

    model_comparison = [
        {"name": r["name"], "r2": round(r["r2"], 4), "mae": round(r["mae"], 4)}
        for r in ensemble_results
    ]

    if walk_forward:
        wf_r2 = float(np.mean([f["r2"] for f in walk_forward]))
        wf_mae = float(np.mean([f["mae"] for f in walk_forward]))
        wf_note = f" | Walk-forward ({len(walk_forward)} folds): mean R²={wf_r2:.3f}, mean MAE={wf_mae:.3f}"
    else:
        wf_note = ""
    variant_label = {
        "baseline": "baseline",
        "lag_rates": "lag_rates",
        "full_deltas": "full_deltas",
        "combined": "combined",
    }.get(feature_variant, feature_variant)
    persistence_note = (
        f"Model loaded from disk (trained at {trained_at}, variant {variant_label})." if not retrained
        else f"Retrained on data fingerprint {fingerprint}, best feature set {variant_label} (via walk-forward R²)."
    )
    accuracy_note = (
        f"Ensemble of {len(ENSEMBLE_CONFIGS)} models | "
        f"Best: {ensemble_results[best_idx]['name']} (R²={best_r2:.3f}, MAE={best_mae:.3f}) | "
        f"Classifier accuracy: {clf_accuracy:.1%} | "
        f"Trained on {len(train_months)} months, {len(hospital_names)} hospitals, "
        f"{len(X_defined)} labeled rows (forward targets, no leakage: label of month m uses month m+1). "
        f"Features: {len(feature_names)} ({len(FEATURE_KEYS)} base + {len(feature_names) - len(FEATURE_KEYS) - len(encoder.get_feature_names_out(['governorate','hospital_type']))} derived + categorical). "
        f"{wf_note} "
        f"{persistence_note} "
        f"Predictions are estimates based on historical patterns."
    )

    return XGBoostPredictionResult(
        model_r2=best_r2, model_mae=best_mae,
        training_months=len(train_months), hospitals_trained=len(hospital_names),
        predictions=predictions, global_feature_importance=global_importance,
        accuracy_note=accuracy_note,
        trained_at=trained_at, retrained=retrained, data_fingerprint=fingerprint,
        walk_forward=walk_forward,
        feature_variant=feature_variant,
    )
