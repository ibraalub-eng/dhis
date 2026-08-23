"""Tests for Smart Analytics API error handling."""
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


@pytest.mark.parametrize(
    "endpoint",
    [
        "/smart/overview/2026-06",
        "/smart/anomalies/2026-06",
        "/smart/clusters/2026-06",
        "/smart/correlations/2026-06",
        "/smart/residuals/2026-06",
        "/smart/stratified/2026-06",
        "/smart/geo/2026-06",
    ],
)
@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_endpoints_return_500_on_error(mock_run, endpoint, client):
    from app.cache import cache
    cache.invalidate("smart_overview")
    response = client.get(endpoint)
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "boom" in data["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_overview_error_message_arabic(mock_run, client):
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_anomalies_error_message_arabic(mock_run, client):
    response = client.get("/smart/anomalies/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل الشذوذ" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_clusters_error_message_arabic(mock_run, client):
    response = client.get("/smart/clusters/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل التجمعات" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_correlations_error_message_arabic(mock_run, client):
    response = client.get("/smart/correlations/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل الارتباطات" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_residuals_error_message_arabic(mock_run, client):
    response = client.get("/smart/residuals/2026-06")
    assert response.status_code == 500
    assert "خطأ في تحليل البواقي" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_stratified_error_message_arabic(mock_run, client):
    response = client.get("/smart/stratified/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل الطبقي" in response.json()["detail"]


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_geo_error_message_arabic(mock_run, client):
    response = client.get("/smart/geo/2026-06")
    assert response.status_code == 500
    assert "خطأ في التحليل الجغرافي" in response.json()["detail"]


def test_cache_returns_cached_result(client):
    """Test that cache returns cached result"""
    from app.cache import cache
    
    # Clear cache first
    cache.invalidate("smart_overview_")
    
    # Call API endpoint (this will cache the result)
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    
    # Verify result is cached
    cache_key = "smart_overview_2026-06_v3"
    cached = cache.get(cache_key)
    assert cached is not None


def test_cache_invalidates_on_upload(db_session):
    """Test that cache invalidates on upload"""
    from app.cache import cache
    
    # Run analysis first
    from app.engine.smart import run_smart_analytics
    run_smart_analytics(db_session, "2026-06")
    
    # Clear cache
    cache.invalidate("smart_overview_")
    
    # Verify cache is empty
    cache_key = "smart_overview_2026-06"
    cached = cache.get(cache_key)
    assert cached is None


def test_smart_endpoints_return_data(client):
    """Test that smart endpoints return data"""
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "kpi" in data["data"]


def test_overview_includes_healthy_hospitals_key(client):
    """نقطة نهاية overview تُرجع قائمة المستشفيات السليمة"""
    from app.cache import cache
    cache.invalidate("smart_overview_2026-06")
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "healthy_hospitals" in data
    assert isinstance(data["healthy_hospitals"], list)


def test_healthy_hospitals_ranks_and_excludes(db_session):
    """المستشفيات السليمة تُرتَّب بالدرجة المركّبة وتُستبعد الشاذة وعديمة البيانات"""
    from app.api.smart_analytics import _healthy_hospitals
    from app.models import Hospital, QualityScore, ConfidenceScore

    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(3).all()
    h1, h2, h3 = hospitals[0], hospitals[1], hospitals[2]
    month = "2027-05"

    # h1: سليم بجودة وثقة مرتفعتين
    db_session.add(QualityScore(hospital_id=h1.id, month=month, score=98.0,
                                completeness=99.0, consistency=97.0, rule_compliance=100.0))
    db_session.add(ConfidenceScore(hospital_id=h1.id, month=month, overall_confidence=91.0, level="high"))
    # h2: سليم بجودة أقل
    db_session.add(QualityScore(hospital_id=h2.id, month=month, score=75.0,
                                completeness=80.0, consistency=70.0, rule_compliance=85.0))
    db_session.add(ConfidenceScore(hospital_id=h2.id, month=month, overall_confidence=60.0, level="medium"))
    # h3: شاذ — يجب استبعاده
    db_session.add(QualityScore(hospital_id=h3.id, month=month, score=90.0,
                                completeness=95.0, consistency=90.0, rule_compliance=95.0))
    db_session.add(ConfidenceScore(hospital_id=h3.id, month=month, overall_confidence=85.0, level="high"))
    db_session.commit()

    anomalies = [
        {"hospital_id": h1.id, "hospital_name": h1.name, "governorate": "غزة",
         "hospital_type": "عام", "anomaly_score": 0.05, "severity": "normal"},
        {"hospital_id": h2.id, "hospital_name": h2.name, "governorate": "رفح",
         "hospital_type": "ميداني", "anomaly_score": 0.15, "severity": "normal"},
        {"hospital_id": h3.id, "hospital_name": h3.name, "governorate": "خان يونس",
         "hospital_type": "تخصصي", "anomaly_score": 0.72, "severity": "critical"},
    ]

    result = _healthy_hospitals(db_session, month, anomalies)
    assert len(result) == 2
    # h1 أعلى من h2 في الدرجة المركّبة
    assert result[0]["hospital_id"] == h1.id
    assert result[1]["hospital_id"] == h2.id
    assert result[0]["composite_score"] > result[1]["composite_score"]
    # الحقول المطلوبة موجودة
    for r in result:
        for key in ("hospital_id", "hospital_name", "quality_score", "completeness",
                    "consistency", "rule_compliance", "confidence", "anomaly_score",
                    "composite_score"):
            assert key in r
    # التحقق من قيمة مركّبة محددة: h1 = 0.5*98 + 0.3*91 + 0.2*(100-5) = 49 + 27.3 + 19 = 95.3
    assert abs(result[0]["composite_score"] - 95.3) < 0.1


def test_healthy_hospitals_fallback_without_scores(db_session):
    """بدون درجات جودة/ثقة تظهر المستشفيات بناءً على درجة الشذوذ فقط"""
    from app.api.smart_analytics import _healthy_hospitals
    from app.models import Hospital

    h = db_session.query(Hospital).first()
    anomalies = [
        {"hospital_id": h.id, "hospital_name": h.name, "governorate": "غزة",
         "hospital_type": "عام", "anomaly_score": 0.05, "severity": "normal"},
    ]
    result = _healthy_hospitals(db_session, "2027-09", anomalies)
    assert len(result) == 1
    assert result[0]["hospital_id"] == h.id
    assert result[0]["anomaly_score"] == 0.05


def test_healthy_hospitals_excludes_critical(db_session):
    """المستشفيات الحرجة لا تظهر في القائمة"""
    from app.api.smart_analytics import _healthy_hospitals
    from app.models import Hospital

    h = db_session.query(Hospital).first()
    anomalies = [
        {"hospital_id": h.id, "hospital_name": h.name, "governorate": "غزة",
         "hospital_type": "عام", "anomaly_score": 0.7, "severity": "critical"},
    ]
    result = _healthy_hospitals(db_session, "2027-09", anomalies)
    assert result == []


# --- Anomaly timeline (animated chart) ---

def test_anomaly_timeline_endpoint_returns_structure(client):
    """نقطة نهاية الخط الزمني تُرجع بنية الشهور والمستشفيات"""
    from app.cache import cache
    cache.invalidate("smart_timeline")
    response = client.get("/smart/anomaly-timeline")
    assert response.status_code == 200
    data = response.json()
    assert "months" in data
    assert "hospitals" in data
    assert isinstance(data["months"], list)
    assert isinstance(data["hospitals"], list)


def test_anomaly_timeline_hospital_fields(client):
    """كل مستشفى يحتوي على الاسم والدرجات حسب الشهر"""
    from app.cache import cache
    cache.invalidate("smart_timeline")
    response = client.get("/smart/anomaly-timeline")
    data = response.json()
    for h in data["hospitals"]:
        assert "hospital_id" in h
        assert "hospital_name" in h
        assert "scores" in h
        assert "severities" in h
        assert isinstance(h["scores"], dict)
        assert isinstance(h["severities"], dict)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=Exception("boom"))
def test_anomaly_timeline_error_handling(mock_run, client, db_session):
    """خطأ في التحليل يُرجع 500 برسالة عربية عندما توجد أشهر"""
    from app.cache import cache
    from app.models import QualityScore, Hospital
    cache.invalidate("smart_timeline")
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month="2026-01", score=70))
    db_session.commit()
    response = client.get("/smart/anomaly-timeline")
    assert response.status_code == 500
    assert "خطأ" in response.json()["detail"]


def test_anomaly_timeline_cache_used(client):
    """النتيجة تُخزّن مؤقتاً"""
    from app.cache import cache
    cache.invalidate("smart_timeline")
    client.get("/smart/anomaly-timeline")
    assert cache.get("smart_timeline_v3") is not None


# --- Per-month memoization (_get_smart_data) ---

def _fake_result(month):
    """A minimal SmartAnalyticsResult-shaped object for memoization tests."""
    from types import SimpleNamespace
    return SimpleNamespace(
        month=month,
        hospitals_count=1,
        kpi=SimpleNamespace(
            total_anomalies=1, critical_count=1, warning_count=0,
            affected_governorates=1, top_contributing_factor="CS",
            month_status="critical",
        ),
        anomalies=[SimpleNamespace(
            hospital_id=1, hospital_name="Test Hospital", governorate="Gaza",
            hospital_type="general", anomaly_score=0.8, severity="critical",
            is_outlier=True,
            method_scores={"isolation_forest": 0.5, "lof": 0.5, "mahalanobis": 0.5, "residual": 0.5},
        )],
        clustering=None,
        correlations=None,
        residuals=[],
        stratified=[],
        explanations=[],
        geo=None,
        patterns=[],
        xgboost_predictions=None,
    )


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_overview_memoized_single_run(mock_run, client):
    """استدعاءا overview لنفس الشهر يشغّلان الأنابيب مرة واحدة فقط."""
    from app.cache import cache
    cache.invalidate("smart_overview_2027-01")
    r1 = client.get("/smart/overview/2027-01")
    r2 = client.get("/smart/overview/2027-01")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert mock_run.call_count == 1


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_slices_share_memoized_overview(mock_run, client):
    """نقاط النهاية الشريحة تعيد استخدام نتيجة الشهر المخزّنة بدل إعادة التشغيل."""
    from app.cache import cache
    cache.invalidate("smart_overview_2027-01")
    client.get("/smart/overview/2027-01")
    client.get("/smart/anomalies/2027-01")
    client.get("/smart/clusters/2027-01")
    client.get("/smart/residuals/2027-01")
    assert mock_run.call_count == 1


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_trend_memoizes_each_month_once(mock_run, client, db_session):
    """trend يشغّل الأنابيب مرة لكل شهر مميز لا لكل تكرار في الحلقة."""
    from app.cache import cache
    from app.models import Hospital, QualityScore
    cache.invalidate()  # clear ALL cache including file cache
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=70))
    db_session.add(QualityScore(hospital_id=h.id, month="2027-02", score=75))
    db_session.commit()

    resp = client.get(f"/smart/trend/{h.id}")
    assert resp.status_code == 200
    # شهران مميزان => تشغيلان، لا تشغيل لكل استدعاء متكرر لنفس الشهر
    assert mock_run.call_count == 2

    # استدعاء لاحق لشهر مُحلَّل مسبقاً لا يعيد التشغيل
    client.get("/smart/overview/2027-01")
    assert mock_run.call_count == 2


def test_cache_keys_include_version(client):
    from app.cache import cache
    cache.invalidate("smart_overview_")
    client.get("/smart/overview/2026-06")
    assert any(k.startswith("smart_overview_") and k.endswith("_v3") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_trend_response_cached(mock_run, client, db_session):
    from app.cache import cache
    from app.models import Hospital, QualityScore
    cache.invalidate("smart_trend_")
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=70))
    db_session.commit()
    r1 = client.get(f"/smart/trend/{h.id}")
    r2 = client.get(f"/smart/trend/{h.id}")
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert any(k.startswith("smart_trend_") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_drilldown_response_cached(mock_run, client, db_session):
    from app.cache import cache
    from app.models import Hospital
    cache.invalidate("smart_drilldown_")
    h = db_session.query(Hospital).first()
    r1 = client.get(f"/smart/drilldown/{h.id}/2027-01")
    r2 = client.get(f"/smart/drilldown/{h.id}/2027-01")
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert any(k.startswith("smart_drilldown_") for k in cache._cache)


@patch("app.api.smart_analytics.run_smart_analytics", side_effect=lambda db, month: _fake_result(month))
def test_timeline_reuses_per_month_memo(mock_run, client, db_session):
    """timeline يعيد استخدام نتائج الشهور المخزّنة من استدعاءات سابقة."""
    from app.cache import cache
    from app.models import Hospital, QualityScore
    cache.invalidate("smart_overview_2027-")
    cache.invalidate("smart_timeline")
    h = db_session.query(Hospital).first()
    db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=70))
    db_session.add(QualityScore(hospital_id=h.id, month="2027-02", score=75))
    db_session.commit()

    # حُلّل شهر 2027-01 مسبقاً عبر overview => لا يُعاد تشغيله داخل timeline
    client.get("/smart/overview/2027-01")
    before = mock_run.call_count
    client.get("/smart/anomaly-timeline")
    assert mock_run.call_count == before + 1  # شهر واحد جديد فقط (2027-02)
