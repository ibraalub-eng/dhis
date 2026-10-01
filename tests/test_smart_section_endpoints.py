"""Tests for the new per-section smart analytics endpoints."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


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


def _data_skeleton():
    return {
        "kpi": {}, "anomalies": [], "clustering": None,
        "correlations": [], "residuals": [],
        "stratified": [], "explanations": [],
        "geo": None, "patterns": [],
        "lag_analysis": {}, "early_warnings": [],
        "healthy_hospitals": [], "xgboost": None,
    }


def _seed_empty(month):
    """Cache a finished but empty envelope (hospitals_count=0, not computing)."""
    from app.cache import cache
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 0, "computing": False, "data": _data_skeleton()},
        ttl=1800,
    )


def _seed_error(month, detail="boom"):
    """Cache a failed-computation envelope; endpoints surface it as HTTP 500."""
    from app.cache import cache
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 0, "computing": False, "error": True,
         "message": "فشل التحليل الذكي لهذا الشهر", "detail": detail,
         "data": _data_skeleton()},
        ttl=300,
    )


def test_patterns_endpoint_returns_list(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/patterns/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert isinstance(data["patterns"], list)


def test_lag_analysis_endpoint_returns_dict(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/lag-analysis/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "lag_analysis" in data


def test_lag_analysis_empty_month(client):
    _seed_empty("2030-01")
    resp = client.get("/smart/lag-analysis/2030-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("empty") is True


def test_xgboost_endpoint(client):
    _seed_empty("2026-06")
    resp = client.get("/smart/xgboost/2026-06")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-06"
    assert "xgboost" in data


# ── آفاق التنبؤ والدقة لكل مستشفى (المرحلة 1 — /smart/xgboost) ──

def _seed_xgboost_envelope(month):
    """مغلف كاش فيه تنبؤات XGBoost لمستشفيين + طيات walk-forward مصغّرة."""
    from app.cache import cache
    skel = _data_skeleton()
    skel["xgboost"] = {
        "model_r2": 0.5, "model_mae": 0.1, "training_months": 6,
        "hospitals_trained": 2, "accuracy_note": "test",
        "trained_at": "2026-01-01T00:00:00", "retrained": True,
        "data_fingerprint": "abc", "walk_forward": [],
        "feature_variant": "baseline",
        "predictions": [
            {"hospital_name": "A", "hospital_id": 1, "current_score": 0.4,
             "predicted_next_score": 0.5, "predicted_severity": "warning",
             "risk_change": "stable", "confidence": 0.9, "top_drivers": []},
            {"hospital_name": "B", "hospital_id": 2, "current_score": 0.6,
             "predicted_next_score": 0.65, "predicted_severity": "critical",
             "risk_change": "increasing", "confidence": 0.88, "top_drivers": []},
        ],
        "global_feature_importance": [],
    }
    cache.set(
        f"smart_overview_{month}_v3",
        {"month": month, "generated_at": "2026-01-01T00:00:00",
         "hospitals_count": 2, "computing": False, "data": skel},
        ttl=1800,
    )


@patch("app.api.smart_analytics.compute_forecast_accuracy")
@patch("app.api.smart_analytics.run_forecast_trajectory")
def test_xgboost_horizon_keys(mock_traj, mock_acc, client):
    """الأفق الصحيح يعيد مفاتيح forecast_accuracy وtrajectory وpeer_percentile."""
    _seed_xgboost_envelope("2026-06")
    mock_traj.return_value = {
        "base_month": "2026-06", "horizon": 3, "note": "n", "trajectories": [],
    }
    mock_acc.return_value = {
        "rows": [],
        "overall": {"n_predictions": 0, "mae": 0.0, "rmse": 0.0,
                    "direction_hit_rate": None, "model_mae": 0.1, "last_6": [],
                    "interval": {"p10": 0.0, "p90": 0.1}},
        "note": "d",
    }
    resp = client.get("/smart/xgboost/2026-06?horizon=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["horizon"] == 3
    assert data["forecast_accuracy"] is not None
    assert data["trajectory"]["horizon"] == 3
    assert "peer_percentile" in data
    assert mock_traj.call_args[0][2] == 3


def test_xgboost_invalid_horizon_422(client):
    _seed_xgboost_envelope("2026-06")
    resp = client.get("/smart/xgboost/2026-06?horizon=4")
    assert resp.status_code == 422


@patch("app.api.smart_analytics.compare_peers")
def test_xgboost_peer_percentile_merged_into_rows(mock_peers, client):
    """مئين النظير يُدمج في صفوف الدقة حسب اسم المستشفى — من الكاش بلا إعادة حساب."""
    _seed_xgboost_envelope("2026-06")
    skel = None
    # أضف شذوذ المستشفى A إلى الكاش نفسه (مصدر النظراء)
    from app.cache import cache
    env = cache.get("smart_overview_2026-06_v3")
    env["data"]["anomalies"] = [
        {"hospital_id": 1, "hospital_name": "A", "anomaly_score": 0.5,
         "governorate": "G", "hospital_type": "T", "method_scores": {},
         "severity": "warning", "is_outlier": False},
    ]
    cache.set("smart_overview_2026-06_v3", env, ttl=1800)

    peer = type("P", (), {})()
    peer.hospital_name, peer.percentile, peer.rank = "A", 90.0, 1
    peer.total_hospitals, peer.comparison_label = 2, "حرج"
    mock_peers.return_value = [peer]

    # أضف طيات للمستشفى A في مغلف الكاش ليُبنى صف دقة له
    env2 = cache.get("smart_overview_2026-06_v3")
    env2["data"]["xgboost"]["fold_predictions"] = [
        {"hospital": "A", "month": "2026-01", "y_true": 0.5, "y_pred": 0.6},
    ]
    cache.set("smart_overview_2026-06_v3", env2, ttl=1800)

    resp = client.get("/smart/xgboost/2026-06")
    assert resp.status_code == 200
    rows = resp.json()["forecast_accuracy"]["rows"]
    assert rows and rows[0]["hospital"] == "A"
    assert rows[0]["peer_percentile"] == 90.0
    assert rows[0]["peer_rank"] == 1


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_section_endpoints_error_arabic(mock_run, client):
    from app.cache import cache
    cache.invalidate("smart_overview_")
    for path, msg in [
        ("/smart/patterns/2026-06", "خطأ في تحليل الأنماط"),
        ("/smart/lag-analysis/2026-06", "خطأ في تحليل العلاقات المتأخرة"),
        ("/smart/xgboost/2026-06", "خطأ في تحليل التنبؤات"),
    ]:
        _seed_error("2026-06")
        resp = client.get(path)
        assert resp.status_code == 500, path
        assert msg in resp.json()["detail"], path


def test_slice_endpoints_empty_month(client):
    _seed_empty("2030-01")
    for path in [
        "/smart/anomalies/2030-01",
        "/smart/clusters/2030-01",
        "/smart/correlations/2030-01",
        "/smart/residuals/2030-01",
        "/smart/stratified/2030-01",
        "/smart/geo/2030-01",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        data = resp.json()
        assert data.get("empty") is True, path
        assert "No data for this month" in data.get("message", ""), path


def test_months_endpoint_returns_list(client):
    resp = client.get("/smart/months")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_hospitals_endpoint_returns_id_name_list(client):
    resp = client.get("/smart/hospitals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert set(data[0].keys()) == {"id", "name"}