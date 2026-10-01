"""اختبارات محرك الإنذار المبكر والتنبؤ الديناميكي (المرحلة 2).

التغطية:
- الإشارات المبكرة: تراجع الجودة، تراجع الالتزام بالقواعد، ارتفاع انحراف
  النظراء، زخم اتجاه المؤشر، وتصعيد الأنماط المركبة — كل إشارة بأفق صريح.
- الأهداف الديناميكية: ترتيب المستشفيات بقوة الإشارات مع سقف عددي.
- المزيج متعدد المصادر للمؤشر الواحد: اتجاه تاريخي 30% + انحراف النظراء 30%
  + النمط الذاتي 40%، مع نطاق وثقة و«غير متاح» تحت 3 أشهر.
- علاقات المؤشرات من نتائج lag_analysis بصياغة «ارتباطية» صريحة.
- API: /smart/forecast-signals/{month}?horizon=
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db

from app.engine.smart.early_warning import (
    compute_early_warning_signals,
    rank_forecast_targets,
    blended_indicator_forecast,
    indicator_relationships,
    DEFAULT_WEIGHTS,
    MAX_SIGNAL_TARGETS,
)


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


# ── 1) الإشارات المبكرة ────────────────────────────────────────────────

class TestEarlyWarningSignals:
    def test_quality_decline_signal_with_horizon(self):
        """جودة تتراجع ثلاثة أشهر متتالية => إشارة بأفق 3 أشهر."""
        series = {"A": [
            {"month": "2026-01", "quality": 90.0, "rule_compliance": 95.0},
            {"month": "2026-02", "quality": 85.0, "rule_compliance": 94.0},
            {"month": "2026-03", "quality": 80.0, "rule_compliance": 93.0},
            {"month": "2026-04", "quality": 74.0, "rule_compliance": 92.0},
        ]}
        sigs = compute_early_warning_signals(series, {})
        q = [s for s in sigs if s["hospital"] == "A" and s["kind"] == "quality_decline"]
        assert q, "يجب اكتشاف إشارة تراجع الجودة"
        assert q[0]["severity"] in ("warning", "critical")
        assert q[0]["horizon_months"] == 3
        assert "خلال 3 أشهر" in q[0]["message_ar"]

    def test_no_signal_when_quality_stable(self):
        series = {"A": [
            {"month": "2026-0%d" % m, "quality": 90.0, "rule_compliance": 95.0}
            for m in range(1, 5)
        ]}
        sigs = compute_early_warning_signals(series, {})
        assert not [s for s in sigs if s["kind"] == "quality_decline"]

    def test_rule_compliance_decline_signal(self):
        series = {"B": [
            {"month": "2026-01", "quality": 90.0, "rule_compliance": 98.0},
            {"month": "2026-02", "quality": 90.0, "rule_compliance": 95.0},
            {"month": "2026-03", "quality": 90.0, "rule_compliance": 91.0},
            {"month": "2026-04", "quality": 90.0, "rule_compliance": 86.0},
        ]}
        sigs = compute_early_warning_signals(series, {})
        rc = [s for s in sigs if s["kind"] == "rule_compliance_decline"]
        assert rc and rc[0]["hospital"] == "B"

    def test_pattern_escalation_signal(self):
        """نمط مركب يتكرر في المستشفى بشهرين متتاليين => إشارة تصعيد."""
        patterns = {
            "2026-05": [{"indicators": ["cs_rate", "sb"], "hospitals": ["A", "B"]}],
            "2026-06": [{"indicators": ["cs_rate", "sb"], "hospitals": ["A", "C"]}],
        }
        series = {"A": [
            {"month": m, "quality": 90.0, "rule_compliance": 95.0}
            for m in ("2026-03", "2026-04", "2026-05", "2026-06")
        ]}
        sigs = compute_early_warning_signals(series, patterns)
        p = [s for s in sigs if s["kind"] == "pattern_escalation"]
        assert p and p[0]["hospital"] == "A"

    def test_signals_sorted_by_severity(self):
        series = {
            "A": [{"month": "2026-0%d" % m, "quality": 95.0 - m * 12,
                   "rule_compliance": 98.0 - m * 10} for m in range(1, 5)],
            "B": [{"month": "2026-0%d" % m, "quality": 95.0 - m,
                   "rule_compliance": 98.0 - m} for m in range(1, 5)],
        }
        sigs = compute_early_warning_signals(series, {})
        order = {"critical": 0, "warning": 1, "info": 2}
        ranks = [order[s["severity"]] for s in sigs]
        assert ranks == sorted(ranks)

    def test_statistical_disclaimer_in_all_messages(self):
        series = {"A": [
            {"month": "2026-01", "quality": 90.0, "rule_compliance": 95.0},
            {"month": "2026-02", "quality": 80.0, "rule_compliance": 90.0},
            {"month": "2026-03", "quality": 70.0, "rule_compliance": 85.0},
            {"month": "2026-04", "quality": 60.0, "rule_compliance": 80.0},
        ]}
        sigs = compute_early_warning_signals(series, {})
        assert sigs
        for s in sigs:
            assert "تقدير إحصائي" in s["message_ar"]


# ── 2) الأهداف الديناميكية ─────────────────────────────────────────────

class TestDynamicTargets:
    def test_targets_ranked_and_capped(self):
        sigs = [
            {"hospital": f"H{i}", "kind": "quality_decline", "severity": "warning",
             "horizon_months": 3, "strength": 0.1 * i, "message_ar": "x"}
            for i in range(10)
        ]
        targets = rank_forecast_targets(sigs, max_targets=MAX_SIGNAL_TARGETS)
        assert len(targets) <= MAX_SIGNAL_TARGETS
        strengths = [t["strength"] for t in targets]
        assert strengths == sorted(strengths, reverse=True)

    def test_critical_outranks_warning(self):
        sigs = [
            {"hospital": "Weak", "kind": "quality_decline", "severity": "warning",
             "horizon_months": 3, "strength": 0.9, "message_ar": "x"},
            {"hospital": "Bad", "kind": "rule_compliance_decline", "severity": "critical",
             "horizon_months": 3, "strength": 0.9, "message_ar": "x"},
        ]
        targets = rank_forecast_targets(sigs)
        assert targets[0]["hospital"] == "Bad"

    def test_empty_signals_empty_targets(self):
        assert rank_forecast_targets([]) == []


# ── 3) المزيج متعدد المصادر للمؤشر الواحد ─────────────────────────────

class TestBlendedIndicatorForecast:
    def test_weights_match_plan(self):
        assert DEFAULT_WEIGHTS == {"trend": 0.3, "peer": 0.3, "self": 0.4}

    def test_blend_weighted_average(self):
        f = blended_indicator_forecast(
            "cs_rate", current=31.0, trend_target=34.0, peer_mean=24.0,
            self_mean=28.0, n_months=8,
        )
        # 0.3*34 + 0.3*24 + 0.4*28 = 10.2 + 7.2 + 11.2 = 28.6
        assert f["forecast"] == pytest.approx(28.6, abs=0.01)
        assert f["n_months"] == 8

    def test_unavailable_under_three_months(self):
        f = blended_indicator_forecast(
            "cs_rate", current=31.0, trend_target=34.0, peer_mean=24.0,
            self_mean=28.0, n_months=2,
        )
        assert f["available"] is False
        assert "غير متاح" in f["note"]

    def test_confidence_grows_with_months(self):
        f3 = blended_indicator_forecast("cs_rate", 31.0, 34.0, 24.0, 28.0, n_months=3)
        f9 = blended_indicator_forecast("cs_rate", 31.0, 34.0, 24.0, 28.0, n_months=9)
        assert f9["confidence"] > f3["confidence"] > 0

    def test_current_included_and_peer_position(self):
        f = blended_indicator_forecast(
            "cs_rate", current=31.0, trend_target=34.0, peer_mean=24.0,
            self_mean=28.0, n_months=6,
        )
        assert f["current"] == 31.0
        assert f["peer_mean"] == 24.0
        assert f["available"] is True


# ── 4) علاقات المؤشرات (ارتباط لا سببية) ───────────────────────────────

class TestIndicatorRelationships:
    def test_relationships_from_lag_results(self):
        lag = {"lags": [{
            "indicator_a": "preterm", "indicator_a_ar": "الولادات المبكرة",
            "indicator_b": "nd", "indicator_b_ar": "الوفيات الجديدة",
            "lag": 2, "lag_pearson": 0.55, "granger_pearson": 0.48,
            "is_lead": True,
        }]}
        rels = indicator_relationships(lag)
        assert len(rels) == 1
        r = rels[0]
        assert r["leading"] == "preterm" and r["outcome"] == "nd"
        assert r["lag_months"] == 2
        assert "ارتباطية" in r["message_ar"]
        assert "لا علاقة سببية" in r["message_ar"]

    def test_empty_lags_empty_relationships(self):
        assert indicator_relationships({}) == []
        assert indicator_relationships({"lags": []}) == []


# ── 5) API ─────────────────────────────────────────────────────────────

class TestForecastSignalsAPI:
    def test_endpoint_returns_keys(self, client):
        from app.cache import cache
        cache.set(
            "smart_overview_2026-06_v3",
            {"month": "2026-06", "generated_at": "t", "hospitals_count": 0,
             "computing": False,
             "data": {"kpi": {}, "anomalies": [], "clustering": None,
                      "correlations": [], "residuals": [], "stratified": [],
                      "explanations": [], "geo": None, "patterns": [],
                      "lag_analysis": {"lags": []}, "early_warnings": [],
                      "healthy_hospitals": [], "xgboost": None}},
            ttl=600,
        )
        resp = client.get("/smart/forecast-signals/2026-06?horizon=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == "2026-06"
        assert data["horizon"] == 3
        for key in ("signals", "targets", "blended", "relationships", "note"):
            assert key in data

    def test_endpoint_invalid_horizon_422(self, client):
        resp = client.get("/smart/forecast-signals/2026-06?horizon=4")
        assert resp.status_code == 422
