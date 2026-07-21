import pytest
from unittest.mock import MagicMock
from app.engine.smart.schemas import SmartAnalyticsResult


def test_orchestrator_returns_result():
    from app.engine.smart import run_smart_analytics

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    result = run_smart_analytics(mock_session, "2026-06")
    assert isinstance(result, SmartAnalyticsResult)
    assert result.month == "2026-06"
