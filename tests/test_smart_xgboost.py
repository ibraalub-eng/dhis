import pytest
import numpy as np
from app.engine.smart.xgboost_predictor import (
    run_xgboost_predictions,
    _normalize_scores,
)
from app.engine.smart.schemas import (
    XGBoostPredictionResult,
    XGBoostPrediction,
    XGBoostDriver,
    XGBoostGlobalExplanation,
)


class TestNormalizeScores:
    def test_basic_normalization(self):
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _normalize_scores(scores)
        assert result[0] == pytest.approx(0.0)
        assert result[-1] == pytest.approx(1.0)

    def test_constant_scores(self):
        scores = np.array([3.0, 3.0, 3.0])
        result = _normalize_scores(scores)
        assert all(r == pytest.approx(0.0) for r in result)

    def test_single_value(self):
        scores = np.array([5.0])
        result = _normalize_scores(scores)
        assert result[0] == pytest.approx(0.0)


class TestXGBoostSchemas:
    def test_prediction_dataclass(self):
        p = XGBoostPrediction(
            hospital_name="Test Hospital",
            hospital_id=1,
            current_score=0.4,
            predicted_next_score=0.5,
            predicted_severity="warning",
            risk_change="increasing",
            confidence=0.85,
            top_drivers=[],
        )
        assert p.hospital_name == "Test Hospital"
        assert p.predicted_severity == "warning"
        assert p.confidence == 0.85

    def test_driver_dataclass(self):
        d = XGBoostDriver(
            feature="cs_rate",
            arabic_label="معدل القيصارية",
            shap_value=0.15,
            direction="increases_risk",
            magnitude="medium",
        )
        assert d.feature == "cs_rate"
        assert d.shap_value == 0.15

    def test_global_explanation_dataclass(self):
        g = XGBoostGlobalExplanation(
            feature="cs_rate",
            arabic_label="معدل القيصارية",
            mean_abs_shap=0.234,
            rank=1,
        )
        assert g.rank == 1
        assert g.mean_abs_shap == 0.234


def _row(name, month, values):
    return {"hospital_name": name, "month": month, "governorate": "غزة",
            "hospital_type": "عام", "hospital_id": 1, "values": values}


def _flat_vals(level):
    from app.engine.smart.anomaly import FEATURE_KEYS
    return {k: float(level) for k in FEATURE_KEYS}


def _meta_for(rows):
    return [{"hospital_name": r["hospital_name"], "month": r["month"],
             "governorate": "غزة", "hospital_type": "عام", "hospital_id": 1}
            for r in rows]


class TestForwardTargetsNoLeakage:
    """الهدف التدريبي يُشتق من الشهر التالي (next vs cur) لا من الشهر نفسه.

    هذا يمنع تسريب البيانات: ميزات الصف عند الشهر m لا تحمل أي معلومة عن m+1،
    فيتعلم النموذج من الحاضر إلى المستقبل بدل «من نفسه إلى نفسه».
    """

    def test_target_uses_next_month_not_current(self):
        from app.engine.smart.xgboost_predictor import _compute_target_scores
        # m1 و m2 متطابقتان، ثم m3 تقفز للأعلى: هدف صف m2 يجب أن يعكس قفزة
        # m3 المستقبلية (بيانات لا يراها النموذج في ميزات m2).
        all_rows = [
            _row("H", "2026-01", _flat_vals(10)),
            _row("H", "2026-02", _flat_vals(10)),
            _row("H", "2026-03", _flat_vals(20)),
        ]
        meta = _meta_for(all_rows)
        current, targets, defined = _compute_target_scores(
            all_rows, meta, ["2026-01", "2026-02", "2026-03"])
        # صف m1: بلا شهر سابق => الدرجة الحالية 0.5؛ الهدف = m2/m1 = 1 => 0.5
        assert current[0] == 0.5
        assert targets[0] == 0.5
        # صف m2: الهدف = m3/m2 = 20/10 => 0.5 + 1*2 = 2.5 → مقيّد عند 1.0
        assert targets[1] == 1.0
        # الدرجة الحالية لصف m2 (m2 مقابل m1 المتطابقين) تبقى 0.5 — وصفية لا تدخل التدريب
        assert current[1] == 0.5
        # صف m3 (آخر شهر): لا هدف مستقبلي => مستبعد من التدريب
        assert defined[2] == False

    def test_target_does_not_contain_current_month_info(self):
        from app.engine.smart.xgboost_predictor import _compute_target_scores
        # قيمة m2 طبيعية تماماً لكن m3 تنهار للأدنى: الهدف يلتقط المستقبل فقط.
        all_rows = [
            _row("H", "2026-01", _flat_vals(10)),
            _row("H", "2026-02", _flat_vals(10)),
            _row("H", "2026-03", _flat_vals(2)),
        ]
        meta = _meta_for(all_rows)
        current, targets, defined = _compute_target_scores(
            all_rows, meta, ["2026-01", "2026-02", "2026-03"])
        # انهيار m3 => هدف صف m2 يصبح الأدنى (0.0) رغم أن ميزات m2 «طبيعية»
        assert targets[1] == 0.0
        # ميزات m2 نفسها لم تُغيَّر: الدرجة الحالية الوصفية 0.5
        assert current[1] == 0.5

    def test_last_month_of_each_hospital_excluded(self):
        from app.engine.smart.xgboost_predictor import _compute_target_scores
        all_rows = [
            _row("A", "2026-01", _flat_vals(5)),
            _row("A", "2026-02", _flat_vals(5)),
            _row("B", "2026-01", _flat_vals(8)),
            _row("B", "2026-02", _flat_vals(8)),
        ]
        meta = _meta_for(all_rows)
        current, targets, defined = _compute_target_scores(
            all_rows, meta, ["2026-01", "2026-02"])
        assert defined.sum() == 2  # صفّان فقط لهما هدف مستقبلي (2026-01 لكليهما)
        assert defined[0] and defined[2]
        assert not defined[1] and not defined[3]

    def test_single_month_no_labels(self):
        from app.engine.smart.xgboost_predictor import _compute_target_scores
        all_rows = [_row("A", "2026-01", _flat_vals(5))]
        meta = _meta_for(all_rows)
        current, targets, defined = _compute_target_scores(all_rows, meta, ["2026-01"])
        assert defined.sum() == 0
        assert current[0] == 0.5


def _build_xgb_db(months=None, n_hospitals=7):
    """قاعدة بيانات مؤقتة بمستشفيات وقيم مؤشرات لأشهر متعددة (لاختبار الاستمرارية)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
    import random

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add_all([Governorate(name="Gaza", id=1), HospitalType(name="general", id=1)])
    session.flush()
    for i in range(1, n_hospitals + 1):
        session.add(Hospital(id=i, name=f"Hospital {i}", governorate_id=1,
                             hospital_type_id=1, is_active=True))
    session.flush()

    for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
        session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
    session.flush()

    months = months or ["2026-01", "2026-02", "2026-03"]
    rnd = random.Random(42)
    for month in months:
        for hosp_id in range(1, n_hospitals + 1):
            for ind_id in range(1, 13):
                session.add(IndicatorValue(
                    hospital_id=hosp_id, indicator_id=ind_id, month=month,
                    value=rnd.uniform(1, 50),
                ))
    session.flush()
    return session


class TestModelPersistence:
    """استمرارية نموذج XGBoost: يُحفظ على القرص ويُعاد تدريبه فقط عند تغيّر المصدر."""

    def test_model_saved_and_reused_without_retrain(self, tmp_path, monkeypatch):
        from app.engine.smart.xgboost_predictor import (
            run_xgboost_predictions, MODEL_DIR as DEFAULT_MODEL_DIR,
        )
        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db()
        try:
            r1 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            assert r1.retrained is True
            assert r1.trained_at
            assert r1.data_fingerprint
            # الملفات محفوظة على القرص
            import os
            assert os.path.exists(os.path.join(model_dir, "meta.json"))
            assert os.path.exists(os.path.join(model_dir, "model_0.json"))

            # نفس البيانات => لا إعادة تدريب: يُحمَّل النموذج من القرص
            r2 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            assert r2.retrained is False
            assert r2.trained_at == r1.trained_at
            assert len(r2.predictions) == len(r1.predictions)
        finally:
            session.close()

    def test_retrain_when_source_data_changes(self, tmp_path, monkeypatch):
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        from app.models import IndicatorValue, Indicator
        import os

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db()
        try:
            r1 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            # تغيير قيمة مؤشر => بصمة جديدة => إعادة تدريب
            iv = session.query(IndicatorValue).first()
            iv.value = (iv.value or 0) + 999.0
            session.commit()

            r2 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            assert r2.retrained is True
            # بصمة جديدة => إعادة تدريب حقيقية (trained_at بدقة الثواني قد يتطابق
            # عند سرعة التشغيل — الفحص الجوهري هو البصمة وليس الطابع الزمني)
            assert r2.data_fingerprint != r1.data_fingerprint
            # النموذج المحفوظ يعكس البصمة الجديدة
            import json as _json
            with open(os.path.join(model_dir, "meta.json"), encoding="utf-8") as f:
                assert _json.load(f)["fingerprint"] == r2.data_fingerprint
        finally:
            session.close()

    def test_new_month_triggers_retrain(self, tmp_path, monkeypatch):
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        from app.models import IndicatorValue
        import random

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db()
        try:
            r1 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            # إضافة شهر جديد بالكامل
            rnd = random.Random(7)
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(
                        hospital_id=hosp_id, indicator_id=ind_id, month="2026-04",
                        value=rnd.uniform(1, 50),
                    ))
            session.commit()

            r2 = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 20})
            assert r2.retrained is True
            assert r2.training_months == 4
        finally:
            session.close()

    def test_walk_forward_in_result_and_persisted(self, tmp_path, monkeypatch):
        """التحقق الزمني يُحسب عند التدريب، يُحفظ، ويُعاد من القرص عند إعادة الاستخدام."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        import os, json

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db(months=["2026-01", "2026-02", "2026-03", "2026-04"])
        try:
            r1 = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 20})
            # 3 أشهر مُعلَّمة => طيتان: (م1→م2) و(م2→م3)
            assert len(r1.walk_forward) >= 1
            for fold in r1.walk_forward:
                assert "train_through" in fold and "validate_month" in fold
                assert isinstance(fold["r2"], float) and isinstance(fold["mae"], float)
                assert fold["n_train"] > 0 and fold["n_test"] > 0
            # الطيات مرتبة زمنياً والشهور متتالية
            for i in range(1, len(r1.walk_forward)):
                assert r1.walk_forward[i]["train_through"] > r1.walk_forward[i - 1]["train_through"]

            # الطيات محفوظة في meta.json وتُعاد من القرص عند إعادة الاستخدام
            with open(os.path.join(model_dir, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
            assert meta.get("walk_forward") == r1.walk_forward

            r2 = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 20})
            assert r2.retrained is False
            assert r2.walk_forward == r1.walk_forward
        finally:
            session.close()

    def test_walk_forward_empty_with_single_labeled_month(self, tmp_path, monkeypatch):
        """شهر مُعلَّم واحد فقط => لا طيات تحقق (يلزم شهران)."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db(months=["2026-01", "2026-02"])
        try:
            r = run_xgboost_predictions(session, "2026-02", {"xgb_n_estimators": 20})
            assert r.walk_forward == []
        finally:
            session.close()

    def test_schema_version_mismatch_triggers_retrain(self, tmp_path, monkeypatch):
        """نموذج محفوظ بلا إصدار مخطط الميزات (قديم) يُعاد تدريبه — حتى لو تطابقت البصمة."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        import os, json

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db()
        try:
            r1 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            assert r1.retrained is True
            # محاكاة نموذج قديم: حذف إصدار المخطط مع إبقاء البصمة مطابقة
            # (الحارس الوحيد المتبقي هو feature_schema_version في meta.json)
            meta_path = os.path.join(model_dir, "meta.json")
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            meta.pop("feature_schema_version", None)
            meta["fingerprint"] = r1.data_fingerprint
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f)

            r2 = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            assert r2.retrained is True
        finally:
            session.close()

    def test_fingerprint_changes_on_data_change(self, tmp_path, monkeypatch):
        from app.engine.smart.xgboost_predictor import _data_fingerprint
        from app.models import IndicatorValue

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db()
        try:
            months = ["2026-01", "2026-02", "2026-03"]
            fp1 = _data_fingerprint(session, months, {"xgb_n_estimators": 20.0})
            iv = session.query(IndicatorValue).first()
            iv.value = (iv.value or 0) + 5.0
            session.commit()
            fp2 = _data_fingerprint(session, months, {"xgb_n_estimators": 20.0})
            assert fp1 != fp2
            # نفس البيانات => نفس البصمة
            fp3 = _data_fingerprint(session, months, {"xgb_n_estimators": 20.0})
            assert fp2 == fp3
        finally:
            session.close()


class TestDenominatorGate:
    """المقامات الصفرية/الغائبة => NaN (بيانات ناقصة) لا صفر صامت."""

    def test_derived_rates_nan_when_no_denominator(self):
        from app.engine.smart.xgboost_predictor import _compute_derived_features
        # بلا مواليد صالحة => كل المعدلات المشتقة NaN (لا صفر وهمي)
        d = _compute_derived_features({"total_births": 0, "cs_rate": 10.0})
        assert np.isnan(d["mat_mortality_rate"])
        assert np.isnan(d["stillbirth_rate"])
        assert np.isnan(d["preterm_rate"])
        assert np.isnan(d["cs_per_birth"])
        assert np.isnan(d["nd_x_sb"])
        # بمقام صالح => قيم فعلية
        d2 = _compute_derived_features({"total_births": 100, "mat_deaths": 1, "sb": 2, "nd": 3})
        assert abs(d2["mat_mortality_rate"] - 1 / 100 * 100000) < 1e-6
        assert abs(d2["stillbirth_rate"] - 2 / 100 * 1000) < 1e-6
        assert not np.isnan(d2["nd_x_sb"])

    def test_multi_month_loader_cs_rate_nan_without_denominator(self, tmp_path, monkeypatch):
        """مستشفى بلا ولادات صالحة => cs_rate في بيانات التدريب NaN."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        from app.models import Hospital, IndicatorValue, Governorate, HospitalType, Indicator

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        import random

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            session.add_all([Governorate(name="G", id=1), HospitalType(name="t", id=1)])
            session.flush()
            for i in range(1, 5):
                session.add(Hospital(id=i, name=f"H{i}", governorate_id=1,
                                     hospital_type_id=1, is_active=True))
            session.flush()
            for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
                session.add(Indicator(id=idx, code=code, name=f"i_{code}"))
            session.flush()
            rnd = random.Random(1)
            # H1: مقام صالح؛ H2: بلا ولادات (مؤشر 2 و6 غائبان) — يجب ألا يتسرب صفر وهمي
            for month in ["2026-01", "2026-02", "2026-03"]:
                for hid in [1, 3, 4]:
                    for ind_id in range(1, 13):
                        session.add(IndicatorValue(
                            hospital_id=hid, indicator_id=ind_id, month=month,
                            value=rnd.uniform(5, 50)))
            session.flush()
            # H2 بلا ولادات صالحة => cs_rate لها في بيانات التدريب NaN لا صفر وهمي
            from app.engine.smart.xgboost_predictor import _load_multi_month_data
            rows, names = _load_multi_month_data(session, ["2026-01", "2026-02", "2026-03"])
            h2_rows = [r for r in rows if r["hospital_name"] == "H2"]
            assert h2_rows, "H2 يجب أن تظهر في بيانات التدريب"
            assert all(np.isnan(r["values"].get("cs_rate")) for r in h2_rows)
            # H1 بمقام صالح => cs_rate رقمية
            h1_rows = [r for r in rows if r["hospital_name"] == "H1"]
            assert all(not np.isnan(r["values"].get("cs_rate")) for r in h1_rows)
            # الأنابيب كاملة تعمل بلا أخطاء مع مستشفى بلا مقام
            r = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 10})
            assert r.hospitals_trained == 4
            assert len(r.predictions) >= 1
        finally:
            session.close()


class TestFeatureVariantSelection:
    """اختيار أفضل مجموعة ميزات زمنية عبر متوسط R² في التحقق الزمني walk-forward.

    المتجه الفائق يُبنى دائماً (تأخرات الشهرين السابقين + فروق شهرية لكل
    المؤشرات) ثم تُختار الأعمدة المفضلة عبر walk-forward وتُحفظ مع النموذج.
    """

    def _superset(self, n_hosp=4, months=None):
        """يبني المتجه الفائق الكامل (كل المتغيرات) ببيانات زمنية قابلة للتعلم."""
        from app.engine.smart.xgboost_predictor import _build_supervised_dataset, _compute_target_scores
        months = months or ["2026-01", "2026-02", "2026-03", "2026-04"]
        rows = []
        for h in range(n_hosp):
            base = 5.0 + h * 7.0
            for i, month in enumerate(months):
                rows.append(_row(
                    f"H{h}", month, _flat_vals(base + i * 3.0)))
        X_all, feature_names, meta, m2i, imp, scaler, enc = _build_supervised_dataset(
            rows, [f"H{h}" for h in range(n_hosp)], 0)
        cur, targets, defined = _compute_target_scores(rows, meta, months)
        defined_idx = np.where(defined)[0]
        return X_all, feature_names, meta, defined_idx, targets[defined_idx], [meta[int(i)] for i in defined_idx]

    def test_variant_masks_are_proper_subsets(self):
        from app.engine.smart.xgboost_predictor import _variant_column_mask
        X_all, feature_names, meta, _, _, _ = self._superset()
        base_mask = _variant_column_mask(feature_names, "baseline")
        comb_mask = _variant_column_mask(feature_names, "combined")
        base_names = [feature_names[i] for i in base_mask]
        comb_names = [feature_names[i] for i in comb_mask]
        # الأساسية لا تتضمن التأخرات ولا الفروق الموسّعة
        assert not any(n.startswith("lag1_") or n.startswith("lag2_") for n in base_names)
        assert not any(n.startswith("delta_") for n in base_names)
        # المجمعة تتضمن كل التأخرات والفروق لكل المؤشرات
        assert any(n.startswith("lag1_") for n in comb_names)
        assert any(n.startswith("delta_cs_rate") for n in comb_names)
        # القاطعات (المحافظة/النوع) محفوظة في كل المتغيرات
        assert any(n.startswith("governorate_") for n in base_names)
        assert len(base_mask) < len(comb_mask)

    def test_select_best_variant_returns_valid_choice(self):
        from app.engine.smart.xgboost_predictor import _select_best_variant, _variant_column_mask
        X_all, feature_names, meta, defined_idx, y_defined, meta_defined = self._superset()
        variant, mask = _select_best_variant(
            X_all, feature_names, defined_idx, y_defined, meta_defined)
        assert variant in ("baseline", "lag_rates", "full_deltas", "combined")
        assert mask == _variant_column_mask(feature_names, variant)
        # القناع يطبَّق على المتجه الفائق بنجاح (بُعد مطابق)
        assert X_all[:, mask].shape[0] == X_all.shape[0]

    def test_select_best_variant_falls_back_to_baseline_without_folds(self):
        from app.engine.smart.xgboost_predictor import _select_best_variant
        # شهر مُعلَّم واحد فقط => لا طيات walk-forward => المتغير الأساسي
        X_all, feature_names, meta, defined_idx, y_defined, meta_defined = self._superset(
            months=["2026-01", "2026-02"])
        variant, mask = _select_best_variant(
            X_all, feature_names, defined_idx, y_defined, meta_defined)
        assert variant == "baseline"

    def test_variant_choice_persisted_and_reused(self, tmp_path, monkeypatch):
        """المتغير المختار يُحفظ في meta.json مع النموذج ويُعاد استخدامه بلا إعادة تدريب."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        import os, json

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db(months=["2026-01", "2026-02", "2026-03", "2026-04"])
        try:
            r1 = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 20})
            assert r1.feature_variant in ("baseline", "lag_rates", "full_deltas", "combined")
            with open(os.path.join(model_dir, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
            assert meta.get("feature_variant") == r1.feature_variant
            assert meta.get("feature_indices"), "يجب حفظ أعمدة المتغير المختار"
            # إعادة الاستخدام: نفس البصمة => لا إعادة تدريب ونفس المتغير
            r2 = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 20})
            assert r2.retrained is False
            assert r2.feature_variant == r1.feature_variant
        finally:
            session.close()


class TestXGBoostPredictionResult:
    def test_empty_result_insufficient_data(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        result = run_xgboost_predictions(session, "2026-06", {"xgboost_enabled": True})
        assert isinstance(result, XGBoostPredictionResult)
        assert result.hospitals_trained == 0
        assert len(result.predictions) == 0
        assert "Not enough" in result.accuracy_note
        session.close()

    def test_result_with_db_has_months(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue, QualityScore
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Gaza", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            h = Hospital(id=i, name=f"Hospital {i}", governorate_id=1, hospital_type_id=1, is_active=True)
            session.add(h)
        session.flush()

        indicators = []
        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            ind = Indicator(id=idx, code=code, name=f"ind_{code}")
            indicators.append(ind)
        session.add_all(indicators)
        session.flush()

        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
        for month in months:
            for hosp_id in range(1, 8):
                for ind in indicators:
                    val = IndicatorValue(
                        hospital_id=hosp_id,
                        indicator_id=ind.id,
                        month=month,
                        value=random.uniform(1, 50),
                    )
                    session.add(val)
        session.flush()

        result = run_xgboost_predictions(session, "2026-05", {
            "xgboost_enabled": True,
            "xgb_n_estimators": 50,
            "xgb_max_depth": 3,
        })
        assert isinstance(result, XGBoostPredictionResult)
        assert result.training_months == 5
        assert result.hospitals_trained == 7
        assert len(result.predictions) == 7
        assert len(result.global_feature_importance) > 0
        for pred in result.predictions:
            assert pred.predicted_severity in ("normal", "warning", "critical")
            assert pred.risk_change in ("increasing", "decreasing", "stable")
            assert 0.0 <= pred.predicted_next_score <= 1.0
            assert 0.0 <= pred.confidence <= 1.0
        session.close()

    def test_predictions_sorted_by_score_desc(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Gaza", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            h = Hospital(id=i, name=f"Hospital {i}", governorate_id=1, hospital_type_id=1, is_active=True)
            session.add(h)
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-05", {"xgb_n_estimators": 30, "xgb_max_depth": 2})
        for i in range(len(result.predictions) - 1):
            assert result.predictions[i].predicted_next_score >= result.predictions[i + 1].predicted_next_score
        session.close()

    def test_driver_count_per_prediction(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="North Gaza", id=1)
        ht = HospitalType(name="specialist", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            session.add(Hospital(id=i, name=f"Hosp {i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
        for pred in result.predictions:
            assert len(pred.top_drivers) <= 5
            for d in pred.top_drivers:
                assert d.direction in ("increases_risk", "decreases_risk")
                assert d.magnitude in ("high", "medium", "low")
        session.close()

    def test_global_feature_importance_ranked(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Khan Younis", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            session.add(Hospital(id=i, name=f"H {i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03", "2026-04"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 25})
        assert len(result.global_feature_importance) <= 12
        ranks = [fi.rank for fi in result.global_feature_importance]
        assert ranks == sorted(ranks)
        for fi in result.global_feature_importance:
            assert fi.mean_abs_shap >= 0
        session.close()

    def test_model_metrics_are_numeric(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Rafah", id=1)
        ht = HospitalType(name="maternity", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 6):
            session.add(Hospital(id=i, name=f"H{i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"i_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02"]:
            for hosp_id in range(1, 6):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(0.1, 100)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-02", {"xgb_n_estimators": 15})
        assert isinstance(result.model_r2, float)
        assert isinstance(result.model_mae, float)
        assert result.model_mae >= 0
        session.close()
