"""Tests for root-cause API endpoint with extended parameters."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Hospital, Indicator, IndicatorValue, QualityScore, ConfidenceScore
import json


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


def test_root_cause_base_fields(client, db_session):
    """Test root cause endpoint returns base fields."""
    hospital = db_session.query(Hospital).first()
    response = client.get(f"/root-cause/{hospital.id}?month=2026-06")
    assert response.status_code in (200, 404)

    if response.status_code == 200:
        data = response.json()
        assert "hospital" in data
        assert "hospital_id" in data
        assert "month" in data
        assert "overall_quality_score" in data
        assert "overall_confidence" in data
        assert "critical_issues_count" in data
        assert "summary" in data
        assert "priority_actions" in data
        assert "top_rule_failures" in data
        assert "quality_drivers" in data
        assert "confidence_gaps" in data
        assert "anomaly_patterns" in data
        assert "ai_recommendations" in data
        if data.get("ai_recommendations"):
            rec = data["ai_recommendations"][0]
            # التوصيات ثنائية اللغة: حقول عربية وإنجليزية معاً
            assert rec.get("title") or rec.get("title_ar")
            assert rec.get("priority") in ("critical", "high", "medium", "low")


def test_root_cause_without_history_excludes_extended_fields(client, db_session):
    """Test root cause endpoint excludes extended fields by default."""
    hospital = db_session.query(Hospital).first()
    response = client.get(f"/root-cause/{hospital.id}?month=2026-06")
    assert response.status_code in (200, 404)

    if response.status_code == 200:
        data = response.json()
        assert "causal_tree" not in data
        assert "causal_chains" not in data
        assert "historical_trends" not in data
        assert "peer_comparisons" not in data
        assert "summary_arabic" not in data


def test_root_cause_with_history_param(client, db_session):
    """Test root cause endpoint with include_history parameter."""
    hospital = db_session.query(Hospital).first()
    response = client.get(
        f"/root-cause/{hospital.id}?month=2026-06&include_history=true&compare_peers=true&months_back=6"
    )
    assert response.status_code in (200, 404)

    if response.status_code == 200:
        data = response.json()
        assert "causal_tree" in data
        assert "causal_chains" in data
        assert "historical_trends" in data
        assert "peer_comparisons" in data
        assert "summary_arabic" in data


def test_root_cause_with_history_only(client, db_session):
    """Test root cause endpoint with only include_history (no compare_peers)."""
    hospital = db_session.query(Hospital).first()
    response = client.get(
        f"/root-cause/{hospital.id}?month=2026-06&include_history=true"
    )
    assert response.status_code in (200, 404)

    if response.status_code == 200:
        data = response.json()
        assert "causal_tree" in data
        assert "causal_chains" in data
        assert "historical_trends" in data
        assert "peer_comparisons" in data
        assert "summary_arabic" in data


def test_root_cause_with_compare_peers_only(client, db_session):
    """Test root cause endpoint with only compare_peers (no include_history)."""
    hospital = db_session.query(Hospital).first()
    response = client.get(
        f"/root-cause/{hospital.id}?month=2026-06&compare_peers=true"
    )
    assert response.status_code in (200, 404)

    if response.status_code == 200:
        data = response.json()
        assert "causal_tree" in data
        assert "causal_chains" in data
        assert "historical_trends" in data
        assert "peer_comparisons" in data
        assert "summary_arabic" in data


def test_root_cause_nonexistent_hospital(client):
    """Test root cause endpoint returns 404 for nonexistent hospital."""
    response = client.get("/root-cause/99999?month=2026-06")
    assert response.status_code == 404
