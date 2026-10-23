"""Phase 2: forecast action board endpoint + recommendation helper.

The action board ranks hospitals/indicators by predicted risk for a chosen
horizon, composing from the cached smart envelope (no engine run): the model
side from ``data.xgboost.predictions`` and the signal side from the cached
``data.early_warnings.warnings``.
"""
import pytest
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
        "lag_analysis": {}, "early_warnings": {"warnings": [], "summary_ar": ""},
        "healthy_hospitals": [], "xgboost": None,
    }


def _pred(hospital, hid, cur, nxt, sev, change, conf, drivers=None):
    return {
        "hospital_name": hospital, "hospital_id": hid, "current_score": cur,
        "predicted_next_score": nxt, "predicted_severity": sev,
        "risk_change": change, "confidence": conf, "top_drivers": drivers or [],
    }


# ── recommendation helper ──

def test_recommend_helper_acts_on_critical_rising():
    from app.engine.smart.early_warning import recommend_forecast_action
    out = recommend_forecast_action("increasing", "critical", "معدل القيصرية")
    assert out["recommendation_key"] == "act_on_rising_risk"
    assert "معدل القيصرية" in out["recommendation"]
    assert out["recommendation"]


def test_recommend_helper_silent_when_not_critical_or_not_rising():
    from app.engine.smart.early_warning import recommend_forecast_action
    for change, sev in [("increasing", "warning"), ("stable", "critical"),
                        ("decreasing", "critical"), ("increasing", "normal")]:
        out = recommend_forecast_action(change, sev, "x")
        assert out["recommendation"] == "", (change, sev)
        assert out["recommendation_key"] == "", (change, sev)


# ── endpoint ──

def _seed_two_hospitals():
    _seed_predictions_and_warnings(
        preds=[
            _pred("A", 1, 0.4, 0.8, "critical", "increasing", 0.9,
                  [{"feature": "cs_rate", "arabic_label": "معدل القيصرية", "shap_value": 0.2}]),
            _pred("B", 2, 0.6, 0.62, "warning", "stable", 0.5),
        ],
        warnings=[],
    )


def _seed_predictions_and_warnings(preds, warnings):
    from app.cache import cache
    skel = _data_skeleton()
    skel["xgboost"] = {
        "model_r2": 0.5, "model_mae": 0.05, "training_months": 6,
        "hospitals_trained": len(preds), "accuracy_note": "t",
        "walk_forward": [], "predictions": preds, "global_feature_importance": [],
    }
    skel["early_warnings"] = {"month": "2026-06", "warnings": warnings, "summary_ar": "s"}
    cache.set("smart_overview_2026-06_v3",
              {"month": "2026-06", "generated_at": "x", "hospitals_count": len(preds),
               "computing": False, "data": skel}, ttl=1800)


def test_action_board_shape_and_sorting(client):
    _seed_two_hospitals()
    resp = client.get("/smart/forecast-action-board/2026-06?horizon=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-06"
    assert body["horizon"] == 3
    assert isinstance(body["items"], list) and body["note"]
    items = body["items"]
    assert [i["hospital"] for i in items] == ["A", "B"]  # sorted desc by risk
    scores = [i["risk_score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    allowed_sev = {"critical", "warning", "normal", "info"}
    for it in items:
        assert 0.0 <= it["risk_score"] <= 1.0
        assert it["severity"] in allowed_sev
        assert it["direction"] in {"rising", "falling", "stable"}
        assert it["lower"] <= it["upper"]
        assert it["source"] in {"xgboost", "early_warning", "blended"}
        assert isinstance(it["recommendation"], str)
        assert it["drilldown"] == {"month": "2026-06", "hospital_id": it["hospital_id"]}
    # A is critical + rising -> actionable recommendation
    assert items[0]["recommendation"]
    assert items[0]["axis"] == "quality"
    # B is stable -> no canned recommendation
    assert items[1]["recommendation"] == ""


def test_action_board_invalid_horizon_422(client):
    _seed_two_hospitals()
    resp = client.get("/smart/forecast-action-board/2026-06?horizon=4")
    assert resp.status_code == 422


def test_action_board_empty_month_returns_items_empty(client):
    from app.cache import cache
    cache.set("smart_overview_2030-01_v3",
              {"month": "2030-01", "generated_at": "x", "hospitals_count": 0,
               "computing": False, "data": _data_skeleton()}, ttl=1800)
    resp = client.get("/smart/forecast-action-board/2030-01?horizon=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["note"]


def test_action_board_escalates_severity_when_early_warning_blended(client):
    _seed_predictions_and_warnings(
        preds=[_pred("B", 2, 0.6, 0.62, "warning", "stable", 0.5)],
        warnings=[{"hospital_id": 2, "hospital_name": "B", "severity": "critical",
                   "probability": 0.8, "score": 3.0}],
    )
    resp = client.get("/smart/forecast-action-board/2026-06?horizon=3")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["source"] == "blended"
    assert item["severity"] == "critical"


def test_action_board_requires_auth(db_session):
    from app.core.deps import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    c = TestClient(app)
    resp = c.get("/smart/forecast-action-board/2026-06?horizon=3")
    assert resp.status_code == 401
