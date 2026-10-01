"""اختبارات إغلاق الحلقة: دقة حيّة من لقطات تنبؤات شهرية مقابل الفعلي.

المرحلة 3 من الخطة: عند حساب تنبؤات الشهر m تُحفظ لقطة ذرية على القرص
(بلا أي تغيير في مخطط DB — تحت MODEL_DIR نفسه)، وعند توفر بيانات الشهر
الفعلي m+1 تُقيَّم اللقطة: خطأ حقيقي + إصابة الاتجاه + إصابة الخطورة،
مع تجميع شهري واتجاه تحسّن النموذج عبر الأشهر.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db

from app.engine.smart import tracking
from app.engine.smart.tracking import _next_months


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestSnapshotPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        preds = [{"hospital_name": "A", "hospital_id": 1, "current_score": 0.5,
                  "predicted_next_score": 0.65, "predicted_severity": "critical",
                  "risk_change": "increasing"}]
        path = tracking.save_forecast_snapshot(
            "2026-07", predictions=preds, trained_at="t1", fingerprint="fp",
            snapshot_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        snap = tracking._load_forecast_snapshot("2026-07", snapshot_dir=str(tmp_path))
        assert snap["month"] == "2026-07"
        assert snap["target_month"] == "2026-08"
        assert snap["fingerprint"] == "fp"
        assert snap["predictions"][0]["predicted_next_score"] == 0.65

    def test_load_missing_returns_none(self, tmp_path):
        assert tracking._load_forecast_snapshot("2026-01", snapshot_dir=str(tmp_path)) is None

    def test_overwrite_same_month_atomic(self, tmp_path):
        tracking.save_forecast_snapshot("2026-07", predictions=[
            {"hospital_name": "A", "predicted_next_score": 0.5}], snapshot_dir=str(tmp_path))
        tracking.save_forecast_snapshot("2026-07", predictions=[
            {"hospital_name": "A", "predicted_next_score": 0.9}], snapshot_dir=str(tmp_path))
        snap = tracking._load_forecast_snapshot("2026-07", snapshot_dir=str(tmp_path))
        assert snap["predictions"][0]["predicted_next_score"] == 0.9
        # بلا ملفات مؤقتة متبقية (كتابة ذرية)
        assert not any(f.endswith(".tmp") for f in os.listdir(tmp_path))


def _craft_actuals():
    """فعلي محكوم: أرقام دقيقة لحساب الإحصاءات يدوياً."""
    return {
        "A": {"2026-07": 0.50, "2026-08": 0.60, "2026-09": 0.60},
        "B": {"2026-07": 0.50, "2026-08": 0.40, "2026-09": 0.55},
    }


def _craft_snapshots(tmp_path):
    tracking.save_forecast_snapshot("2026-07", predictions=[
        {"hospital_name": "A", "predicted_next_score": 0.65, "current_score": 0.50},
        {"hospital_name": "B", "predicted_next_score": 0.45, "current_score": 0.50},
    ], snapshot_dir=str(tmp_path))
    tracking.save_forecast_snapshot("2026-08", predictions=[
        {"hospital_name": "A", "predicted_next_score": 0.70, "current_score": 0.60},
        {"hospital_name": "B", "predicted_next_score": 0.55, "current_score": 0.40},
    ], snapshot_dir=str(tmp_path))


class TestEvaluationCore:
    def test_exact_aggregates_and_trend(self, tmp_path):
        _craft_snapshots(tmp_path)
        res = tracking.evaluate_forecast_tracking(
            actuals_fn=_craft_actuals, snapshot_dir=str(tmp_path),
        )
        # شهر 2026-08: خطأ A=0.05 وB=0.05؛ اتجاهان صائبان؛ خطورتان صائبتان
        m08 = next(m for m in res["months"] if m["month"] == "2026-08")
        assert m08["n"] == 2
        assert m08["mae"] == pytest.approx(0.05)
        assert m08["direction_hit_rate"] == 1.0
        assert m08["severity_hit_rate"] == 1.0
        # شهر 2026-09: A ثابت فعلياً وتنبؤه يقفز (0.7 vs 0.6) => خطأ اتجاه، خطأ 0.10
        m09 = next(m for m in res["months"] if m["month"] == "2026-09")
        assert m09["mae"] == pytest.approx(0.05)
        assert m09["direction_hit_rate"] == 0.5
        assert m09["severity_hit_rate"] == 1.0
        o = res["overall"]
        assert o["n_evals"] == 4
        assert o["mae"] == pytest.approx(0.05)
        assert o["direction_hit_rate"] == pytest.approx(0.75)
        assert o["severity_hit_rate"] == 1.0
        assert o["trend"] == "declining"  # 100% ثم 50% إصابة اتجاه
        assert "تقدير إحصائي" in res["note"]

    def test_missing_snapshot_month_skipped(self, tmp_path):
        tracking.save_forecast_snapshot("2026-07", predictions=[
            {"hospital_name": "A", "predicted_next_score": 0.55, "current_score": 0.50}],
            snapshot_dir=str(tmp_path))
        # فعلي فيه 2026-08 (لقطة 07 تُقيَّم) و2026-09 (لقطة 08 غير موجودة => تُتخطى)
        actuals = {"A": {"2026-07": 0.5, "2026-08": 0.6, "2026-09": 0.7}}
        res = tracking.evaluate_forecast_tracking(
            actuals_fn=lambda: actuals, snapshot_dir=str(tmp_path),
        )
        assert [m["month"] for m in res["months"]] == ["2026-08"]

    def test_no_snapshots_yet(self, tmp_path):
        res = tracking.evaluate_forecast_tracking(
            actuals_fn=_craft_actuals, snapshot_dir=str(tmp_path),
        )
        assert res["months"] == []
        assert res["overall"]["trend"] == "insufficient"
        assert "لا لقطات" in res["note"]

    def test_trend_improving(self, tmp_path):
        """تحسّن حقيقي بعتبة 0.1: إصابة 0% ثم 100% — بأرقام نظيفة من العوم."""
        # لقطة 07: فعلي 08 = 0.60 صاعد +0.10 عن 0.50؛ التنبؤ 0.40 هابط => خطأ.
        tracking.save_forecast_snapshot("2026-07", predictions=[
            {"hospital_name": "A", "predicted_next_score": 0.40, "current_score": 0.50}],
            snapshot_dir=str(tmp_path))
        # لقطة 08: فعلي 09 = 0.70 صاعد +0.10 عن 0.60؛ التنبؤ 0.80 صاعد => إصابة.
        tracking.save_forecast_snapshot("2026-08", predictions=[
            {"hospital_name": "A", "predicted_next_score": 0.80, "current_score": 0.60}],
            snapshot_dir=str(tmp_path))
        actuals = {"A": {"2026-07": 0.5, "2026-08": 0.6, "2026-09": 0.7}}
        res = tracking.evaluate_forecast_tracking(
            actuals_fn=lambda: actuals, snapshot_dir=str(tmp_path),
        )
        assert res["overall"]["trend"] == "improving"


class TestEngineHook:
    def test_run_xgboost_writes_snapshot(self, tmp_path, monkeypatch):
        """تشغيل المحرك يحفظ لقطة تنبؤات الشهر الحالي تلقائياً (كتابة غير فتّاعة)."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        from tests.test_smart_xgboost import _build_xgb_db

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db(months=["2026-01", "2026-02", "2026-03", "2026-04"])
        try:
            r = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            snap = tracking._load_forecast_snapshot("2026-03")
            assert snap is not None, "يجب حفظ اللقطة تحت MODEL_DIR الافتراضي"
            assert snap["month"] == "2026-03"
            assert snap["target_month"] == "2026-04"
            assert len(snap["predictions"]) == len(r.predictions)
            for row in snap["predictions"]:
                assert 0.0 <= row["predicted_next_score"] <= 1.0
        finally:
            session.close()


class TestLiveLoopIntegration:
    def test_snapshot_evaluated_when_actual_month_arrives(self, tmp_path, monkeypatch):
        """الحلقة كاملة: تنبؤ 03 → فعلي 04 وصل → تقييم حي بشهر مُقيَّم واحد."""
        from app.engine.smart.xgboost_predictor import run_xgboost_predictions
        from tests.test_smart_xgboost import _build_xgb_db

        model_dir = str(tmp_path / "models")
        monkeypatch.setattr("app.engine.smart.xgboost_predictor.MODEL_DIR", model_dir)
        session = _build_xgb_db(months=["2026-01", "2026-02", "2026-03", "2026-04"])
        try:
            run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
            res = tracking.evaluate_forecast_tracking(session)
            assert res["months"], "لقطات 03 يجب أن تُقيَّم عند وصول فعلي 04"
            m = res["months"][-1]
            assert m["month"] == "2026-04"
            assert m["n"] > 0
            assert 0.0 <= m["direction_hit_rate"] <= 1.0
            assert 0.0 <= m["severity_hit_rate"] <= 1.0
            assert m["mae"] >= 0.0
        finally:
            session.close()


class TestTrackingAPI:
    def test_xgboost_response_carries_tracking(self, client):
        from app.cache import cache
        skel = {"kpi": {}, "anomalies": [], "clustering": None, "correlations": [],
                "residuals": [], "stratified": [], "explanations": [], "geo": None,
                "patterns": [], "lag_analysis": {}, "early_warnings": [],
                "healthy_hospitals": [], "xgboost": None}
        skel["xgboost"] = {
            "model_r2": 0.5, "model_mae": 0.1, "training_months": 3,
            "hospitals_trained": 1, "accuracy_note": "t", "trained_at": "t",
            "retrained": True, "data_fingerprint": "f", "walk_forward": [],
            "fold_predictions": [], "feature_variant": "baseline",
            "predictions": [{"hospital_name": "A", "hospital_id": 1, "current_score": 0.4,
                             "predicted_next_score": 0.5, "predicted_severity": "warning",
                             "risk_change": "stable", "confidence": 0.9, "top_drivers": []}],
            "global_feature_importance": [],
        }
        cache.set("smart_overview_2026-06_v3",
                  {"month": "2026-06", "generated_at": "t", "hospitals_count": 1,
                   "computing": False, "data": skel}, ttl=600)
        resp = client.get("/smart/xgboost/2026-06")
        assert resp.status_code == 200
        data = resp.json()
        tr = data["forecast_tracking"]
        assert tr is not None
        for key in ("months", "overall", "note"):
            assert key in tr

    def test_tracking_error_is_non_fatal(self, client, monkeypatch):
        """فشل التتبع لا يُسقط استجابة التنبؤات (غير فتّاعة)."""
        from app.cache import cache
        monkeypatch.setattr(
            "app.engine.smart.tracking.evaluate_forecast_tracking",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        skel = {"kpi": {}, "anomalies": [], "clustering": None, "correlations": [],
                "residuals": [], "stratified": [], "explanations": [], "geo": None,
                "patterns": [], "lag_analysis": {}, "early_warnings": [],
                "healthy_hospitals": [], "xgboost": None}
        skel["xgboost"] = {
            "model_r2": 0.5, "model_mae": 0.1, "training_months": 3,
            "hospitals_trained": 1, "accuracy_note": "t", "trained_at": "t",
            "retrained": True, "data_fingerprint": "f", "walk_forward": [],
            "fold_predictions": [], "feature_variant": "baseline",
            "predictions": [{"hospital_name": "A", "hospital_id": 1, "current_score": 0.4,
                             "predicted_next_score": 0.5, "predicted_severity": "warning",
                             "risk_change": "stable", "confidence": 0.9, "top_drivers": []}],
            "global_feature_importance": [],
        }
        cache.set("smart_overview_2026-06_v3",
                  {"month": "2026-06", "generated_at": "t", "hospitals_count": 1,
                   "computing": False, "data": skel}, ttl=600)
        resp = client.get("/smart/xgboost/2026-06")
        assert resp.status_code == 200
        assert resp.json()["forecast_tracking"] is None
